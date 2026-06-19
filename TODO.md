# TODO / Tech Debt

## Harden AI rename failure handling

**Context:** A bad model ID (`claude-sonnet-4-6-20260610`) caused a 404 on every
`generate_name` / `generate_workout_tagline` call. Each failure fell into the
`except anthropic.APIError` branch and silently returned the `"morning miles"`
fallback, which is indistinguishable from a real AI-generated title. It went
unnoticed in production and shipped because the test asserted the broken ID.
Fixed in `app/services/claude.py` (commit on `feature/light-theme`).

Follow-ups to make this class of failure louder / less harmful:

- [ ] Retry once on `anthropic.APIError` in `generate_name` before falling back.
- [ ] Distinguish "AI failed" from "AI succeeded" — consider skipping the rename
      entirely on failure instead of writing a generic title to the user's Strava
      activity. The current fallback masks outages.
- [ ] Add a startup smoke-test against the Anthropic API (e.g. a tiny
      `messages.create` call on app boot) so a bad model ID / key surfaces at
      deploy time, not per-activity in prod logs.
