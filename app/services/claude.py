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


def _suffer_to_effort(suffer_score: int | float) -> tuple[int, str]:
    if suffer_score <= 25:
        return 2, "chill"
    if suffer_score <= 50:
        return 3, "easy"
    if suffer_score <= 75:
        return 5, "moderate"
    if suffer_score <= 100:
        return 6, "solid"
    if suffer_score <= 150:
        return 7, "hard"
    if suffer_score <= 200:
        return 9, "brutal"
    return 10, "death"


def _calculate_gap(pace_str: str | None, weather: dict | None) -> str | None:
    if not pace_str or not weather:
        return None

    temp = weather.get("temp_c")
    if temp is None:
        return None

    parts = pace_str.split(":")
    if len(parts) != 2:
        return None
    pace_seconds = int(parts[0]) * 60 + int(parts[1])

    penalty_pct = 0.0

    if temp > 15:
        excess = temp - 15
        penalty_pct += excess * 1.5
        if temp > 25:
            penalty_pct += (temp - 25) * 0.5
    elif temp < 0:
        penalty_pct += abs(temp) * 0.5

    humidity = weather.get("humidity")
    if humidity and humidity > 60 and temp > 20:
        penalty_pct += (humidity - 60) * 0.1

    wind_speed = weather.get("wind_speed_ms")
    if wind_speed and wind_speed > 3:
        penalty_pct += (wind_speed - 3) * 0.8

    if penalty_pct < 2:
        return None

    ideal_seconds = pace_seconds / (1 + penalty_pct / 100)
    ideal_min = int(ideal_seconds // 60)
    ideal_sec = int(ideal_seconds % 60)
    return f"{ideal_min}:{ideal_sec:02d}"


def build_description_block(context: dict) -> str:
    parts = []

    weather = context.get("weather")
    if weather and isinstance(weather, dict):
        weather_bits = []
        if weather.get("temp_c") is not None:
            weather_bits.append(f"{weather['temp_c']}°C")
        if weather.get("description"):
            weather_bits.append(weather["description"])
        if weather.get("humidity") is not None:
            weather_bits.append(f"{weather['humidity']}% humidity")
        if weather_bits:
            parts.append(f"🌤️ {', '.join(weather_bits)}")

    hr = context.get("average_heartrate")
    suffer = context.get("suffer_score")
    hr_line_parts = []
    if hr:
        hr_line_parts.append(f"{int(hr)} bpm avg")
    if suffer:
        effort, label = _suffer_to_effort(suffer)
        hr_line_parts.append(f"effort {effort}/10 ({label})")
    if hr_line_parts:
        parts.append(f"❤️ {' · '.join(hr_line_parts)}")

    pace = context.get("pace_min_per_km")
    gap = _calculate_gap(pace, weather)
    if pace and gap:
        parts.append(f"⚡ {pace}/km → ~{gap}/km in ideal conditions")
    elif pace and weather and weather.get("temp_c") is not None:
        parts.append(f"⚡ {pace}/km · near ideal conditions 👌")

    return "\n".join(parts)


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
