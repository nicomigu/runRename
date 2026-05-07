import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.preference import Preference
from app.models.user import User
from app.services import claude as claude_service
from app.services import strava, weather as weather_service

logger = logging.getLogger(__name__)


def parse_workout_from_laps(laps: list[dict]) -> str | None:
    if len(laps) < 3:
        return None

    middle_laps = laps[1:-1]

    if len(middle_laps) < 2:
        return None

    has_rest_periods = False
    for i in range(len(middle_laps)):
        if i % 2 == 1:
            if middle_laps[i]["distance"] < 1000:
                has_rest_periods = True
            else:
                logger.debug("Odd-index lap >= 1000m, treating as regular run")
                return None

    if not has_rest_periods:
        logger.debug("No rest periods detected, treating as regular run")
        return None

    work_intervals = [middle_laps[i] for i in range(len(middle_laps)) if i % 2 == 0]
    rest_periods = [middle_laps[i] for i in range(len(middle_laps)) if i % 2 == 1]

    if not work_intervals:
        return None

    work_times = [lap["elapsed_time"] for lap in work_intervals]
    work_distances = [lap["distance"] for lap in work_intervals]

    time_based = all(abs(t - work_times[0]) <= 5 for t in work_times)
    distance_based = all(abs(d - work_distances[0]) <= 50 for d in work_distances)

    if not time_based and not distance_based:
        logger.debug("Work intervals not consistent, treating as regular run")
        return None

    num_intervals = len(work_intervals)

    if time_based:
        interval_time_minutes = work_times[0] // 60
        interval_time_seconds = work_times[0] % 60

        if interval_time_seconds == 0:
            interval_str = f"{interval_time_minutes}min"
        else:
            interval_str = f"{interval_time_minutes}:{interval_time_seconds:02d}"

        workout_name = f"{num_intervals}x{interval_str}"

    elif distance_based:
        interval_distance = work_distances[0]

        if interval_distance >= 1000:
            if interval_distance % 1000 < 50:
                distance_str = f"{int(interval_distance / 1000)}k"
            else:
                distance_str = f"{interval_distance / 1000:.1f}k"
        else:
            distance_str = f"{int(interval_distance)}m"

        workout_name = f"{num_intervals}x{distance_str}"

    if rest_periods:
        rest_time = rest_periods[0]["elapsed_time"]
        rest_minutes = rest_time // 60
        rest_seconds = rest_time % 60

        if rest_minutes > 0 and rest_seconds == 0:
            rest_str = f"{rest_minutes} min rest"
        elif rest_minutes > 0:
            rest_str = f"{rest_minutes}:{rest_seconds:02d} rest"
        else:
            rest_str = f"{rest_seconds}s rest"

        workout_name += f" -- {rest_str}"

    return workout_name


async def rename_activity(
    activity_id: int,
    user: User,
    db: AsyncSession,
    client: httpx.AsyncClient,
    activity_row: Activity | None = None,
) -> str:
    activity_data = await strava.get_activity(activity_id, user, db, client)
    laps = activity_data.get("laps", [])
    original_name = activity_data.get("name")

    workout_name = parse_workout_from_laps(laps)

    start_latlng = activity_data.get("start_latlng")
    weather = await weather_service.get_conditions(start_latlng, client)

    pref_result = await db.execute(
        select(Preference).where(Preference.user_id == user.id)
    )
    preference = pref_result.scalar_one_or_none()
    style = preference.style if preference else "poetic"

    context = claude_service.build_context(activity_data, weather)

    if workout_name:
        new_name = await claude_service.generate_workout_tagline(workout_name, context, style)
        raw_context = {"source": "structured_workout", "laps_count": len(laps), **context}
    else:
        new_name = await claude_service.generate_name(context, style)
        raw_context = context

    desc_block = claude_service.build_description_block(context)
    logger.info("Description block for activity %s: %r", activity_id, desc_block or "(empty)")
    existing_desc = activity_data.get("description") or ""
    if desc_block:
        separator = "\n\n───\n" if existing_desc.strip() else ""
        full_description = f"{existing_desc}{separator}{desc_block}"
    else:
        full_description = None

    await strava.patch_activity(
        activity_id, user, db, client,
        name=new_name,
        description=full_description,
    )

    if activity_row:
        activity_row.original_name = original_name
        activity_row.generated_name = new_name
        activity_row.raw_context = raw_context
    else:
        db.add(Activity(
            user_id=user.id,
            strava_activity_id=activity_id,
            original_name=original_name,
            generated_name=new_name,
            raw_context=raw_context,
        ))
    await db.commit()

    logger.info("Renamed activity %s → %r for user %s", activity_id, new_name, user.strava_id)
    return new_name
