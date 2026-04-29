from unittest.mock import AsyncMock, patch

import pytest

from app.services.claude import FALLBACK_NAME, build_context, generate_name, sanitize_name


def test_build_context_with_weather():
    activity = {
        "type": "Run",
        "start_date": "2026-04-29T06:30:00Z",
        "distance": 10000,
        "moving_time": 3000,
        "average_heartrate": 145,
        "suffer_score": 50,
    }
    weather = {"temp_c": 14.5, "humidity": 82, "description": "light rain"}

    ctx = build_context(activity, weather)
    assert ctx["activity_type"] == "Run"
    assert ctx["time_of_day"] == "early morning"
    assert ctx["day_of_week"] == "Wednesday"
    assert ctx["distance_km"] == 10.0
    assert ctx["duration_min"] == 50
    assert ctx["pace_min_per_km"] == "5:00"
    assert ctx["weather"]["description"] == "light rain"


def test_build_context_without_weather():
    activity = {
        "type": "Walk",
        "start_date": "2026-04-29T20:00:00Z",
        "distance": 3000,
        "moving_time": 1800,
    }
    ctx = build_context(activity, None)
    assert ctx["activity_type"] == "Walk"
    assert ctx["time_of_day"] == "evening"
    assert "weather" not in ctx


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
    assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
    assert call_kwargs["max_tokens"] == 50


@pytest.mark.parametrize("raw,expected", [
    ('"Rainy dawn miles"', "Rainy dawn miles"),
    ("'foggy morning run'", "foggy morning run"),
    ("  sunrise shuffle  ", "sunrise shuffle"),
    ("one two three four five six seven eight nine ten", "one two three four five six seven eight"),
    ("#running #morning just a run", "just a run"),
    ("#hashtag #only", FALLBACK_NAME),
    ("", FALLBACK_NAME),
    ("   ", FALLBACK_NAME),
])
def test_sanitize_name(raw: str, expected: str):
    assert sanitize_name(raw) == expected
