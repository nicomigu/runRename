# LogLine

AI-powered Strava activity renamer. "The story of your run." Multi-user SaaS that generates creative
activity titles using weather, time of day, and effort data.

## Stack

- Python + FastAPI
- PostgreSQL (Railway)
- Deployed on Railway
- Payments via Lemon Squeezy
- Claude Haiku for AI renaming
- OpenWeatherMap for weather context

## Project Structure

- /app/main.py - FastAPI entry point, middleware, lifespan
- /app/routes/ - auth.py, webhook.py, dashboard.py, payment.py, admin.py
- /app/services/ - strava.py, claude.py, weather.py, renamer.py
- /app/models/ - user.py, activity.py, preference.py
- /app/schemas/ - Pydantic request/response schemas
- /app/db.py - Async DB connection and session management
- /app/config.py - Settings via pydantic-settings
- CLAUDE.md - This file

## Engineering Rules

- Follow REST best practices
- Use async/await throughout (httpx, asyncpg)
- Validate all inputs with Pydantic models
- Never hardcode secrets — use environment variables
- All external API calls go in /app/services/
- Routes stay thin — logic lives in services
- Use dependency injection for DB sessions
- Handle Strava token refresh transparently in StravaService
- Meaningful error handling — no bare except clauses
- Type hints everywhere
- Keep functions small and single-purpose
- Use pydantic-settings for config, not os.environ directly
- Use httpx.AsyncClient, never the requests library

## Access Control

- beta_user = True → free forever, full access, never hits paywall
- subscribed = True → paid user, full access
- neither → can connect Strava and see dashboard, toggle is locked
- Gate check: if user.beta_user or user.subscribed → allow

## Renaming Logic (ported from existing Lambda)

- Structured workout detected via parse_workout_from_laps → keep structured name
  e.g. "4x1k", "6x3min"
- Easy / recovery / long run (no structured laps) → AI-generated creative name
- Walk, hike, other → AI-generated name

## parse_workout_from_laps — DO NOT REWRITE

This function exists in the Lambda and works correctly. Port it directly
into /app/services/renamer.py with type hints and async-compatible structure.
Only refactor for cleanliness, never change the core logic.

## AI Naming Style

- Max 8 words
- No hashtags
- Slightly poetic or humorous
- Reflects conditions (weather, time of day, effort level)
- Examples:
  - "Humid monday shuffle, legs still waking"
  - "Two hours and a sunrise"
  - "Foggy morning six before coffee"

## Database Tables

- users: strava_id, access_token, refresh_token, expires_at,
  name, profile_pic, subscribed, beta_user, created_at
- activities: id, user_id, strava_activity_id, generated_name,
  raw_context, created_at
- preferences: user_id, style (poetic / funny / minimal)

## Environment Variables

STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET,
ANTHROPIC_API_KEY, OPENWEATHERMAP_KEY,
LEMON_SQUEEZY_KEY, LEMON_SQUEEZY_WEBHOOK_SECRET, LEMON_SQUEEZY_STORE_ID, LEMON_SQUEEZY_VARIANT_ID,
DATABASE_URL, ADMIN_SECRET
