from unittest.mock import AsyncMock, patch

import pytest

from app.services.claude import (
    FALLBACK_NAME,
    build_context,
    generate_name,
    generate_workout_tagline,
    sanitize_name,
)
from app.services.renamer import (
    _calculate_gap,
    _conditions_difficulty,
    _weather_penalty,
    build_description_block,
)


def test_build_context_with_weather():
    activity = {
        "type": "Run",
        "start_date": "2026-04-29T06:30:00Z",
        "distance": 10000,
        "moving_time": 3000,
    }
    weather = {"temp_c": 14.5, "humidity": 82, "description": "light rain"}

    ctx = build_context(activity, weather)
    assert ctx["time_of_day"] == "early morning"
    assert ctx["day_of_week"] == "Wednesday"
    assert ctx["weather"]["description"] == "light rain"
    assert "activity_type" not in ctx
    assert "distance_km" not in ctx
    assert "pace_min_per_km" not in ctx


def test_build_context_without_weather():
    activity = {
        "type": "Walk",
        "start_date": "2026-04-29T20:00:00Z",
        "distance": 3000,
        "moving_time": 1800,
    }
    ctx = build_context(activity, None)
    assert ctx["time_of_day"] == "evening"
    assert "weather" not in ctx
    assert "activity_type" not in ctx


def test_build_context_converts_timezone():
    activity = {
        "type": "Run",
        "start_date": "2026-04-29T23:00:00Z",
        "timezone": "(GMT-05:00) America/New_York",
        "distance": 5000,
        "moving_time": 1500,
    }
    ctx = build_context(activity, None)
    assert ctx["time_of_day"] == "evening"
    assert ctx["day_of_week"] == "Wednesday"


def test_build_context_with_route_beats():
    activity = {
        "type": "Run",
        "start_date": "2026-04-29T06:30:00Z",
        "distance": 10000,
        "moving_time": 3000,
    }
    beats = [
        {"description": "a park", "position": "early"},
        {"description": "a river", "position": "mid"},
    ]
    ctx = build_context(activity, None, route_beats=beats)
    assert ctx["route_beats"] == beats
    assert len(ctx["route_beats"]) == 2


def test_build_context_without_route_beats():
    activity = {
        "type": "Run",
        "start_date": "2026-04-29T06:30:00Z",
        "distance": 10000,
        "moving_time": 3000,
    }
    ctx = build_context(activity, None)
    assert "route_beats" not in ctx

    ctx2 = build_context(activity, None, route_beats=None)
    assert "route_beats" not in ctx2


def test_build_context_no_timezone_uses_utc():
    activity = {
        "type": "Run",
        "start_date": "2026-04-29T23:00:00Z",
        "distance": 5000,
        "moving_time": 1500,
    }
    ctx = build_context(activity, None)
    assert ctx["time_of_day"] == "night"


def test_build_context_time_of_day_buckets():
    base = {"type": "Run", "distance": 5000, "moving_time": 1500}

    cases = [
        ("2026-01-01T03:00:00Z", "pre-dawn"),
        ("2026-01-01T07:00:00Z", "early morning"),
        ("2026-01-01T10:00:00Z", "morning"),
        ("2026-01-01T13:00:00Z", "midday"),
        ("2026-01-01T16:00:00Z", "afternoon"),
        ("2026-01-01T19:00:00Z", "evening"),
        ("2026-01-01T22:00:00Z", "night"),
    ]
    for start_date, expected_tod in cases:
        ctx = build_context({**base, "start_date": start_date}, None)
        assert ctx["time_of_day"] == expected_tod, f"Failed for {start_date}"


async def test_generate_name_calls_anthropic():
    mock_response = AsyncMock()
    mock_response.content = [AsyncMock(text='"Rainy dawn miles before work"')]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("app.services.claude.anthropic.AsyncAnthropic", return_value=mock_client):
        name = await generate_name(
            {"activity_type": "Run", "time_of_day": "early morning"},
            "poetic",
        )

    assert name == "Rainy dawn miles before work"
    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-4-6"
    assert call_kwargs["max_tokens"] == 50


async def test_generate_name_includes_recent_titles():
    mock_response = AsyncMock()
    mock_response.content = [AsyncMock(text="something brand new")]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    recent = ["humidity soup", "the drizzle had plans", "legs filed a complaint"]

    with patch("app.services.claude.anthropic.AsyncAnthropic", return_value=mock_client):
        await generate_name(
            {"time_of_day": "morning"},
            "poetic",
            recent_titles=recent,
        )

    call_kwargs = mock_client.messages.create.call_args.kwargs
    user_msg = call_kwargs["messages"][0]["content"]
    assert "Recent titles" in user_msg
    for title in recent:
        assert title in user_msg


async def test_generate_workout_tagline():
    mock_response = AsyncMock()
    mock_response.content = [AsyncMock(text="entering the pain cave")]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("app.services.claude.anthropic.AsyncAnthropic", return_value=mock_client):
        name = await generate_workout_tagline(
            "4x1k -- 60s rest",
            {"activity_type": "Run", "time_of_day": "morning"},
            "poetic",
        )

    assert name == "4x1k -- 60s rest. entering the pain cave"


async def test_generate_workout_tagline_fallback_on_empty():
    mock_response = AsyncMock()
    mock_response.content = []

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("app.services.claude.anthropic.AsyncAnthropic", return_value=mock_client):
        name = await generate_workout_tagline(
            "4x1k -- 60s rest",
            {"activity_type": "Run", "time_of_day": "morning"},
        )

    assert name == "4x1k -- 60s rest"


def test_weather_penalty_hot():
    penalty = _weather_penalty({"temp_c": 33, "humidity": 80, "wind_speed_ms": 1})
    assert penalty > 25

def test_weather_penalty_cool_windy():
    penalty = _weather_penalty({"temp_c": 8, "humidity": 70, "wind_speed_ms": 4.2, "description": "light rain"})
    assert penalty > 5

def test_weather_penalty_ideal():
    penalty = _weather_penalty({"temp_c": 14, "humidity": 50, "wind_speed_ms": 1})
    assert penalty < 2

def test_weather_penalty_none():
    assert _weather_penalty(None) == 0.0

def test_conditions_difficulty_none_when_ideal():
    assert _conditions_difficulty({"temp_c": 14, "humidity": 50, "wind_speed_ms": 1}, None) is None

def test_conditions_difficulty_noticeable():
    result = _conditions_difficulty({"temp_c": 8, "humidity": 70, "wind_speed_ms": 4.2, "description": "light rain"}, None)
    assert result is not None
    score, label = result
    assert score == 4
    assert label == "noticeable"

def test_conditions_difficulty_brutal():
    result = _conditions_difficulty({"temp_c": 35, "humidity": 85, "wind_speed_ms": 5}, None)
    assert result is not None
    score, label = result
    assert score == 10
    assert label == "brutal"

def test_conditions_difficulty_with_elevation():
    result = _conditions_difficulty({"temp_c": 14, "humidity": 50, "wind_speed_ms": 1}, 500)
    assert result is not None


def test_calculate_gap_hot_and_humid():
    gap = _calculate_gap("5:23", {"temp_c": 31, "humidity": 75, "wind_speed_ms": 2})
    assert gap is not None
    parts = gap.split(":")
    gap_seconds = int(parts[0]) * 60 + int(parts[1])
    assert gap_seconds < 5 * 60 + 23


def test_calculate_gap_near_ideal_returns_none():
    gap = _calculate_gap("5:00", {"temp_c": 12, "humidity": 45, "wind_speed_ms": 1})
    assert gap is None


def test_calculate_gap_no_weather():
    assert _calculate_gap("5:00", None) is None


def test_calculate_gap_no_pace():
    assert _calculate_gap(None, {"temp_c": 30}) is None


def test_build_description_block_full():
    ctx = {
        "activity_type": "Run",
        "pace_min_per_km": "5:23",
        "average_heartrate": 155,
        "weather": {"temp_c": 31, "description": "humid", "humidity": 75, "wind_speed_ms": 2},
    }
    block = build_description_block(ctx)
    assert "31°C" in block
    assert "humid" in block
    assert "conditions" in block
    assert "ideal conditions" in block


def test_build_description_block_no_weather():
    ctx = {"activity_type": "Run"}
    block = build_description_block(ctx)
    assert "🌤️" not in block
    assert "conditions" not in block


def test_build_description_block_empty():
    ctx = {"activity_type": "Walk"}
    block = build_description_block(ctx)
    assert block == ""


@pytest.mark.parametrize("raw,expected", [
    ('"Rainy dawn miles"', "Rainy dawn miles"),
    ("'foggy morning run'", "foggy morning run"),
    ("  sunrise shuffle  ", "sunrise shuffle"),
    ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen", "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen"),
    ("#running #morning just a run", "just a run"),
    ("#hashtag #only", FALLBACK_NAME),
    ("", FALLBACK_NAME),
    ("   ", FALLBACK_NAME),
])
def test_sanitize_name(raw: str, expected: str):
    assert sanitize_name(raw) == expected
