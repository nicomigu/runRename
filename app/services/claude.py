import logging
from datetime import datetime

import anthropic

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You name running and walking activities. Return ONLY the title, nothing else.

Rules:
- Max 8 words
- No hashtags
- Slightly poetic or humorous
- Reflect the conditions: weather, time of day, effort level
- Lowercase unless a proper noun

Examples:
- "Humid monday shuffle, legs still waking"
- "Two hours and a sunrise"
- "Foggy morning six before coffee"
"""

STYLE_HINTS = {
    "poetic": "Lean poetic and reflective.",
    "funny": "Lean funny and self-deprecating.",
    "minimal": "Keep it very short and understated, 3-5 words max.",
}


def build_context(activity_data: dict, weather: dict | None) -> dict:
    start_date = activity_data.get("start_date", "")
    try:
        dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
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

    name = response.content[0].text.strip().strip('"').strip("'")
    logger.info("Claude generated: %r (style=%s)", name, style)
    return name


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
