import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You name running and walking activities. Return ONLY the title, nothing else.

Rules:
- Max 8 words
- No hashtags
- Lowercase unless a proper noun
- Be creative, witty, and human — like a runner naming their own run
- Blend conditions (weather, time, effort) into a vibe, don't just list them
- Short activities or walks deserve fun names too — don't be boring about it

Examples:
- "humid monday shuffle, legs still waking"
- "two hours and a sunrise"
- "foggy morning six before coffee"
- "just stepped outside honestly"
- "a walk that wanted to be a nap"
- "three minutes of pure ambition"
- "sunset legs, no plan"
"""

STYLE_HINTS = {
    "poetic": "Lean poetic and reflective.",
    "funny": "Lean funny and self-deprecating.",
    "minimal": "Keep it very short and understated, 3-5 words max.",
}


def _parse_timezone(tz_string: str | None) -> ZoneInfo | None:
    if not tz_string:
        return None
    try:
        iana_name = tz_string.split(") ", 1)[-1]
        return ZoneInfo(iana_name)
    except (KeyError, IndexError):
        return None


def build_context(activity_data: dict, weather: dict | None) -> dict:
    start_date = activity_data.get("start_date", "")
    tz = _parse_timezone(activity_data.get("timezone"))
    try:
        dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        if tz:
            dt = dt.astimezone(tz)
        hour = dt.hour
        day_of_week = dt.strftime("%A")
    except (ValueError, AttributeError):
        hour = 12
        day_of_week = "Unknown"

    if hour < 6:
        time_of_day = "pre-dawn"
    elif hour < 9:
        time_of_day = "early morning"
    elif hour < 12:
        time_of_day = "morning"
    elif hour < 15:
        time_of_day = "midday"
    elif hour < 18:
        time_of_day = "afternoon"
    elif hour < 21:
        time_of_day = "evening"
    else:
        time_of_day = "night"

    distance_km = round(activity_data.get("distance", 0) / 1000, 1)
    duration_min = round(activity_data.get("moving_time", 0) / 60)

    pace_min_per_km = None
    if distance_km > 0 and activity_data.get("moving_time"):
        total_pace_sec = activity_data["moving_time"] / distance_km
        pace_min_per_km = f"{int(total_pace_sec // 60)}:{int(total_pace_sec % 60):02d}"

    context = {
        "activity_type": activity_data.get("type", "Run"),
        "time_of_day": time_of_day,
        "day_of_week": day_of_week,
        "distance_km": distance_km,
        "duration_min": duration_min,
        "pace_min_per_km": pace_min_per_km,
        "average_heartrate": activity_data.get("average_heartrate"),
        "suffer_score": activity_data.get("suffer_score"),
    }

    if weather:
        context["weather"] = weather

    return context


WORKOUT_PROMPT = """You add a short, witty tagline to a structured running workout title. You receive a workout name like "4x1k -- 60s rest" and some context. Return ONLY a short tagline (2-5 words), no quotes.

The final title will be: "{workout_name}. {your tagline}"

Rules:
- 2-5 words only
- Capture the vibe or suffering of the workout
- Be creative, funny, or dramatic
- No hashtags

Examples:
- "entering the pain cave"
- "legs had opinions today"
- "speed has a price"
- "tuesday torture session"
- "coach said easy"
"""

FALLBACK_NAME = "morning miles"


def sanitize_name(raw: str) -> str:
    raw = raw.strip().strip('"').strip("'")
    words = [w for w in raw.split() if not w.startswith("#")]
    if len(words) > 8:
        words = words[:8]
    name = " ".join(words).strip()
    return name if name else FALLBACK_NAME


async def generate_name(context: dict, style: str = "poetic") -> str:
    style_hint = STYLE_HINTS.get(style, STYLE_HINTS["poetic"])

    user_message = f"Activity context:\n{_format_context(context)}\n\nStyle: {style_hint}"

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=50,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    if not response.content or not hasattr(response.content[0], "text"):
        logger.warning("Empty response from Claude, using fallback")
        return FALLBACK_NAME

    name = sanitize_name(response.content[0].text)
    logger.info("Claude generated: %r (style=%s)", name, style)
    return name


async def generate_workout_tagline(workout_name: str, context: dict, style: str = "poetic") -> str:
    style_hint = STYLE_HINTS.get(style, STYLE_HINTS["poetic"])
    user_message = (
        f"Workout: {workout_name}\n"
        f"Activity context:\n{_format_context(context)}\n\n"
        f"Style: {style_hint}"
    )

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=30,
        system=WORKOUT_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    if not response.content or not hasattr(response.content[0], "text"):
        return workout_name

    tagline = sanitize_name(response.content[0].text)
    if tagline == FALLBACK_NAME:
        return workout_name

    logger.info("Workout tagline: %r for %s (style=%s)", tagline, workout_name, style)
    return f"{workout_name}. {tagline}"


def _format_context(context: dict) -> str:
    lines = []
    for key, value in context.items():
        if value is not None:
            if key == "weather" and isinstance(value, dict):
                for wk, wv in value.items():
                    if wv is not None:
                        lines.append(f"  {wk}: {wv}")
            else:
                lines.append(f"{key}: {value}")
    return "\n".join(lines)
