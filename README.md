# Sharp Karaine — Megajackpot Sharp Money Tracker

Tracks Pinnacle's Arcadia guest API (1X2 + Asian Handicap odds and limits)
for the matches that make up a SportPesa Megajackpot round, classifies
price/limit movement into sharp-money signals, scores each match, and
serves a live dashboard + Telegram alerts.

## Before you trust any of this

- **The discovery endpoint (`/leagues/{id}/matchups`) has now been verified
  against a live response** and fixed to match reality: it returns a flat
  list mixing real fixtures with their "special" sub-markets (Draw No Bet,
  team props, etc.), all repeating the same `parent` object for a given
  fixture. `frontend/app.js` resolves through `.parent` and dedupes by that
  id - see the comment there and in `app/pinnacle_client.py`.
- **The markets endpoint (`/matchups/{id}/markets/related/straight`,
  i.e. actual odds/limits) is still unverified live** - it follows the
  schema you supplied from a prior working build, but that could not be
  checked from the environment that built it (no network egress). Once you
  add a match to monitoring and it polls for real, report back any field
  name or shape mismatch in `app/ingest.py`'s normalization.
- **The exact scoring numbers are this build's own calibration, not
  empirical.** The *qualitative* thresholds (0.25/0.5/1.0 AH points,
  0.30/0.80/1.80pp 1X2 displacement, 30%/50% limit drop) are from your
  spec. How each threshold maps to a 0-10 score is a reasonable bridge
  this implementation invented to satisfy the tier cutoffs you gave
  (Strong Sharp 7-10, Sharp 4.5-6.9, Watch 2-4.4, No Signal 0-1.9) — it is
  not backed by real outcome data, because none exists yet. Every one of
  these numbers lives in `CONFIG` at the top of `app/signals.py` so you
  can retune them once you've watched a few rounds, without touching the
  logic. This is also why the dashboard's raw-data charts exist: don't
  take the tier badge on faith, look at the underlying series yourself.
- **No backtesting is built in.** There's no historical tick/limit data
  available anywhere to backtest against. Instead, every raw snapshot and
  every computed score is persisted permanently (`market_snapshots`,
  `match_scores`, `signals` are insert-only, nothing is pruned) so that
  after a few Megajackpot rounds you have a real dataset to check
  tier-vs-outcome accuracy and retune `CONFIG` against actual results.

## Setup

1. **Database.** Create a Supabase project, open the SQL editor, and run
   `schema.sql` once. Copy the direct Postgres connection string into
   `DATABASE_URL`.
2. **Env vars.** Copy `.env.example` to `.env` and fill in `DATABASE_URL`
   at minimum. `ARCADIA_API_KEY` has a fallback default (the guest key you
   supplied) but guest keys are known to rotate/expire — if requests start
   401ing, grab a fresh one from your browser's network tab on
   pinnacle.com and either set the env var or update it from the
   dashboard's Settings panel (which takes effect immediately, no
   redeploy). Telegram is optional; alerts are silently skipped if unset.
3. **Install.**
   ```
   pip install -r requirements.txt
   ```
4. **Run locally.**
   ```
   uvicorn main:app --reload
   ```
   Open http://localhost:8000.
5. **Deploy to Railway.** Push this repo, point a Railway service at it,
   set the same env vars there. `Procfile` starts `uvicorn` on Railway's
   `$PORT`. The poller runs in-process on startup — no separate worker
   service needed.

## Smoke test (do this before trusting it)

1. Start the app, open the dashboard, click **Discovery**, enter a known
   Pinnacle soccer league ID, and confirm real matches come back. If this
   fails or the fields look wrong, the discovery endpoint's field mapping
   in `app/pinnacle_client.py::get_league_matchups` and
   `frontend/app.js`'s discovery handler need correcting against what you
   actually get back.
2. Select one match, add it to monitoring, and confirm a row appears in
   the summary table within one poll cycle (~30s).
3. Click the row to open the drill-down and confirm the raw-data charts
   populate as snapshots accumulate — this is the one place you can
   verify the tool is reading real data correctly independent of the
   scoring logic.
4. Set a Telegram bot token + chat id in Settings and use **Force Poll**
   on a match with enough movement to hit at least "Watch" tier, or
   temporarily lower `CONFIG["tier_watch"]` in `app/signals.py` to force a
   test alert through.
5. Run `pytest` — this covers the odds math, de-vig, ingest normalization,
   and signal scoring logic without needing network or a database.

## Architecture

```
Pinnacle Arcadia API
        |  (poller, adaptive interval)
        v
 fetcher -> devig -> signal engine -> scorer -> Postgres (Supabase)
        |                                            |
        +----------------- WebSocket broadcast ------+
                                                      v
                                    FastAPI REST + static frontend
                                                      |
                                                      v
                                    Telegram alert on tier change
```

See `app/signals.py` for the signal/scoring implementation and
`app/ingest.py` for how raw Arcadia payloads are normalized and
version-diffed before being persisted.
