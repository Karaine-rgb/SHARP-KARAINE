# Sharp Karaine — Megajackpot Sharp Money Tracker

Tracks Pinnacle's Arcadia guest API (1X2 + Asian Handicap odds and limits)
for the matches that make up a SportPesa Megajackpot round, stores every
price snapshot, and serves a live dashboard that shows how each match has
moved: which sides have had a steam move (ranked by size), the opening-line
favorite, and charts of the raw series.

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
- **The tier / score engine has been removed.** The original build scored
  each match 0-10 into tiers (Strong Sharp, Sharp, Watch, No Signal) and sent
  Telegram alerts on tier changes; backtesting showed it did not predict
  results (see `RESEARCH_FINDINGS.md`), so it, the limit-movement signal and
  the Telegram tier alerts are gone. The dashboard now lists, per match, each
  side that has had a **steam move** at any moment, ranked by the size of its
  biggest steam swing. Each swing is labelled **early** (finished more than 3 hours before
  kickoff) or **late** (within the last 3 hours; `late_steam_hours` in `CONFIG`), and each side
  shows its biggest early and late swing so the ranked number can be traced to the swing it
  came from. Steam is a shape label from `velocity_shape()`, and it
  is still unproven as a predictor - treat it as a description of what the
  market did, not a pick. The remaining thresholds live in `CONFIG` at the
  top of `app/signals.py`.
- **Signal scorecard.** Above the match table, per round (and for all rounds), the dashboard
  counts how many matches with a final score the engine's favourite, the steam signal and the
  two together got right (`app/scorecard.py`, `GET /api/matches/scorecard`). Steam counts as right
  when the side that won was any of the steaming sides (size not used), so it also shows how
  many sides it covers and what blind picks of that many sides would get. Computed on request
  from the snapshots and the scores you enter; nothing is stored.
- **No backtesting is built in**, but every raw snapshot is persisted
  (`market_snapshots` is insert-only) and the CSV export carries them with
  the final scores, so you can check anything you like against real results.
  The movement readings are computed on demand from those snapshots, so
  nothing derived is stored.

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
   redeploy). The Telegram fields are currently unused (tier alerts were
   removed).
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
4. Run `pytest` — this covers the odds math, de-vig, ingest normalization,
   and the movement readings without needing network or a database.

## Architecture

```
Pinnacle Arcadia API
        |  (poller, adaptive interval)
        v
 fetcher -> devig -> Postgres (Supabase)
        |                 |
        +-- WebSocket ----+
                          v
              FastAPI REST + static frontend
              (movement readings computed on demand)
```

See `app/signals.py` for the movement readings (steam moves, move shapes,
favorite) and
`app/ingest.py` for how raw Arcadia payloads are normalized and
version-diffed before being persisted.
