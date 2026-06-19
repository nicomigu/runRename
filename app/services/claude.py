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
- Emojis welcome (1-2 max, at the end)
- Playful, energetic, like texting a friend about your run
- Think puns, inner monologue, absurd humor, or dramatic flair
- NEVER just state the day or time — "tuesday morning run" is banned
- The name should make someone smile when scrolling
- Surprise me. Two runs in the same conditions should get wildly different names

## ROUTE BEATS (optional — may be absent)

route_beats: 0-5 short plain descriptions of things passed along the route, with rough position (early/mid/late). These can be anything — terrain, buildings, water, businesses, whatever was actually there.

## RESTRAINT RULE
Beats are raw material, NOT a checklist. Use AT MOST one per title, and often zero is correct. Pick a beat only if it offers a genuinely good angle: a temptation, an irony, an image, a small human moment a runner would have actually noticed mid-run. If nothing does, title from the other material alone. A forced reference is worse than none. Do not repeat the angle or structure of recent titles.

- funny: a beat is a setup, not a punchline — find the irony or temptation in what was passed. One joke max.
- poetic: a beat is one concrete image. No abstractions.
- minimalist: at most one word of it, only if it defined the run.

Never include brand or business names. Never name streets or anything that pinpoints a location. Never invent beats not provided.

Examples of great names:
- "the drizzle had better plans 🌧️"
- "legs wrote a complaint letter today"
- "running late? more like running great 🏃‍♂️💨"
- "someone lied about the distance"
- "plot twist: the hill won"
- "a negotiation between me and gravity"
- "the sun chose violence today ☀️"
- "sweating through monday's attitude"
- "three minutes of pure ambition"

Examples of BAD names (never do this):
- "thursday morning jog" (just states time)
- "rainy afternoon walk" (just lists conditions)
- "evening 5k run" (boring, literal)
"""

STYLE_HINTS = {
    "poetic": "Lean poetic — metaphor, imagery, a runner's inner world. Still playful.",
    "funny": "Lean funny — puns, self-deprecating, absurd. Make them laugh out loud.",
    "minimal": "Keep it very short, 3-5 words max. Punchy and clever.",
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
    "Name it like a song title from a band that only runs",
    "Name it like a diary entry you'd never show anyone",
    "Name it like the run was a heist",
    "Name it like your shoes are writing a review of you",
    "Name it like a weather forecast written by someone who just ran in it",
    "Name it like a voicemail you'd leave yourself at 5am",
    "Name it like a negotiation between your brain and your body",
    "Name it like a nature documentary about suburban wildlife",
    "Name it like a recipe for the run you just had",
    "Name it like a one-star review of the route",
    "Name it like a motivational poster that's given up",
    "Name it like a haiku that broke the rules",
    "Name it from the perspective of someone watching you from a window",
    "Name it like a loading screen tip for runners",
]

FOCUS_NUDGES = [
    "Focus on the physical sensation — what did the body feel?",
    "Focus on the mood — what was the emotional arc?",
    "Ignore the weather entirely — find a different angle.",
    "Focus on the time of day — what does this hour feel like?",
    "Focus on the absurdity of choosing to do this voluntarily.",
    "Focus on what you were probably thinking about mid-run.",
    "Focus on the contrast between before and after the run.",
    "Focus on the sounds — what did the run sound like?",
    "Make it about the relationship between runner and road.",
    "Focus on what you'd tell someone who asked how it went.",
]


def _parse_timezone(tz_string: str | None) -> ZoneInfo | None:
    if not tz_string:
        return None
    try:
        iana_name = tz_string.split(") ", 1)[-1]
        return ZoneInfo(iana_name)
    except (KeyError, IndexError, ValueError):
        return None


def build_context(
    activity_data: dict,
    weather: dict | None,
    route_beats: list[dict] | None = None,
) -> dict:
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

    context = {
        "time_of_day": time_of_day,
        "day_of_week": day_of_week,
    }

    if weather:
        context["weather"] = weather

    if route_beats:
        context["route_beats"] = route_beats

    return context


WORKOUT_PROMPT = """You write a short, witty tagline about running conditions. Return ONLY the tagline, nothing else.

The tagline will be appended to a workout name, so describe the vibe or conditions, not the workout itself.

Rules:
- 2-5 words only
- No quotes, no hashtags
- Emojis welcome (1 max)
- Capture the weather, the suffering, or the mood
- Be creative, funny, or dramatic

Examples:
- "brutal heat edition 🔥"
- "the drizzle approved"
- "wind had other plans"
- "sunrise tax included"
- "sweat equity ☀️"
"""

FALLBACK_NAME = "morning miles"


def sanitize_name(raw: str, max_words: int = 15) -> str:
    raw = raw.strip().strip('"').strip("'")
    words = [w for w in raw.split() if not w.startswith("#")]
    if len(words) > max_words:
        words = words[:max_words]
    name = " ".join(words).strip()
    return name if name else FALLBACK_NAME


async def generate_name(
    context: dict,
    style: str = "poetic",
    recent_titles: list[str] | None = None,
) -> str:
    style_hint = STYLE_HINTS.get(style, STYLE_HINTS["poetic"])
    angle = random.choice(ANGLES)
    nudge = random.choice(FOCUS_NUDGES)

    user_message = (
        f"Activity context:\n{_format_context(context)}\n\n"
        f"Style: {style_hint}\n"
        f"Creative angle: {angle}\n"
        f"Focus: {nudge}"
    )

    if recent_titles:
        titles_block = "\n".join(f"  - {t}" for t in recent_titles)
        user_message += f"\n\nRecent titles (do NOT repeat these or their patterns):\n{titles_block}"

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model="claude-sonnet-4-6",
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
    logger.info("Claude generated: %r (style=%s, angle=%r)", name, style, angle)
    return name


async def generate_workout_tagline(workout_name: str, context: dict, style: str = "poetic") -> str:
    style_hint = STYLE_HINTS.get(style, STYLE_HINTS["poetic"])
    user_message = (
        f"Activity context:\n{_format_context(context)}\n\n"
        f"Style: {style_hint}"
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model="claude-sonnet-4-6",
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
            elif key == "route_beats" and isinstance(value, list):
                lines.append("route_beats:")
                for beat in value:
                    lines.append(f"  - {beat['description']} ({beat['position']})")
            else:
                lines.append(f"{key}: {value}")
    return "\n".join(lines)
