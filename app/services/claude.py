import logging
import random
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You name running and walking activities. Return ONLY the title, nothing else.

Rules:
- Max 15 words
- No hashtags, no quotes
- Lowercase unless a proper noun
- NEVER just state the day or time of day — "tuesday morning run" is banned
- Think storytelling, metaphor, inner monologue, or absurd humor
- The name should feel like a chapter title, not a weather report
- Surprise me. Two runs in the same conditions should get wildly different names

Examples of great names:
- "the great pursuit of the perfect lunch"
- "legs wrote a complaint letter today"
- "chasing a cloud that didn't exist"
- "someone lied about the distance"
- "victory lap, audience of pigeons"
- "the one where i forgot to stop"
- "a negotiation between me and gravity"
- "three minutes of pure ambition"
- "plot twist: the hill won"

Examples of BAD names (never do this):
- "thursday morning jog" (just states time)
- "rainy afternoon walk" (just lists conditions)
- "evening 5k run" (boring, literal)
"""

STYLE_HINTS = {
    "poetic": "Lean poetic — metaphor, imagery, a runner's inner world.",
    "funny": "Lean funny — self-deprecating, absurd, the kind of name that makes someone laugh scrolling Strava.",
    "minimal": "Keep it very short and understated, 3-5 words max. Still clever.",
}

ANGLES = [
    "Name it like a movie title",
    "Name it from the perspective of your legs",
    "Name it like a chapter in a memoir",
    "Name it like an excuse you'd give for being late",
    "Name it like a food review",
    "Name it like a nature documentary narrator",
    "Name it like a text you'd send your friend after",
    "Name it like a complaint to management",
    "Name it like the activity had its own personality",
    "Name it like a plot twist happened mid-run",
    "Name it like you're narrating your inner monologue",
    "Name it like a fortune cookie that actually ran",
]


def _parse_timezone(tz_string: str | None) -> ZoneInfo | None:
    if not tz_string:
        return None
    try:
        iana_name = tz_string.split(") ", 1)[-1]
        return ZoneInfo(iana_name)
    except (KeyError, IndexError, ValueError):
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
        "elevation_gain": activity_data.get("total_elevation_gain"),
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
    if len(words) > 15:
        words = words[:15]
    name = " ".join(words).strip()
    return name if name else FALLBACK_NAME


async def generate_name(context: dict, style: str = "poetic") -> str:
    style_hint = STYLE_HINTS.get(style, STYLE_HINTS["poetic"])
    angle = random.choice(ANGLES)

    user_message = (
        f"Activity context:\n{_format_context(context)}\n\n"
        f"Style: {style_hint}\n"
        f"Creative angle: {angle}"
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=50,
            temperature=1.0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APIError:
        logger.exception("Anthropic API error in generate_name")
        return FALLBACK_NAME

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

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=30,
            system=WORKOUT_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APIError:
        logger.exception("Anthropic API error in generate_workout_tagline")
        return workout_name

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
