# Odds Movement Visualizer

A small dashboard that shows how odds move over time across several
bookmakers **and betting exchanges** (Betfair, Matchbook, Smarkets) for the
matches you pick. Data comes from [The Odds API](https://the-odds-api.com) (v4).

It is built to live on the **free plan (500 credits a month)**. It runs
separately from the main Sharp Karaine app and does not need Postgres. It
stores everything in one SQLite file.

## Quick start

```bash
pip install -r requirements.txt
```

Try it with fake data first. This uses no credits:

```bash
OV_DEMO=1 uvicorn odds_visualizer.server:app --port 8010
```

Open http://localhost:8010. Then run it for real:

```bash
ODDS_API_KEY=your_key uvicorn odds_visualizer.server:app --port 8010
```

1. Pick a league and click **Load fixtures**.
2. Tick the matches you want to follow.
3. Leave it running. It polls by itself on a schedule (see below).
4. Click a tracked match to see the chart.

If no `ODDS_API_KEY` is set, it starts in demo mode on its own.

## How it saves credits

Think of the 500 credits as monthly pocket money. The tool follows these rules:

1. **One call per league, not per match.** The `/odds` call costs
   *markets x regions*, no matter how many matches it returns. So tracking 1
   EPL match or 8 EPL matches costs the same. All tracked matches in a league
   share one call.
2. **Bookmakers instead of regions.** It asks for a list of named bookmakers
   (`bookmakers=` parameter). Up to 10 bookmakers count as 1 region, so the
   default list of 10 costs **1 credit per poll** with `markets=h2h`.
   An 11th bookmaker or a second market doubles the cost.
3. **Poll often only near kickoff.** Most of the movement that matters happens late.

   | Time to kickoff | Poll every |
   |---|---|
   | more than 2 days | 24 h |
   | 1 to 2 days | 12 h |
   | 6 to 24 h | 4 h |
   | 3 to 6 h | 90 min |
   | 1 to 3 h | 45 min |
   | last hour | 20 min |
   | after kickoff | stops |

   That is about 15 to 20 credits per league per match day.
   Example: one league with all games on one day, 4 match days a month,
   is about 60 to 80 credits. So you can follow several leagues.
   A league whose games are spread over several days costs more, because
   the schedule follows the next kickoff.
4. **A daily share.** Each day may use up to 3 times the average of what is
   left for the month (`OV_DAILY_BURST`). In the last 90 minutes before a
   kickoff, polls may go over that share.
5. **A reserve.** The last 25 credits (`OV_RESERVE_CREDITS`) are never used
   by automatic polling. The **Poll now** button can use them, after asking.
6. **Real numbers, not guesses.** After every call the tool reads the API's
   `x-requests-remaining` and `x-requests-last` headers and uses those. The
   call log in the dashboard shows the real cost of each call.

The free plan has no historical odds, so the tool builds its own history:
every poll is saved in SQLite. A chart can only start from your first poll.

## Settings (env vars)

| Variable | Default | Meaning |
|---|---|---|
| `ODDS_API_KEY` | (none) | Your key. Without it, demo mode. |
| `OV_BOOKMAKERS` | pinnacle, betfair_ex_uk, betfair_ex_eu, matchbook, smarkets, williamhill, unibet_eu, onexbet, marathonbet, betsson | Keep to 10 or fewer for 1 credit per poll. |
| `OV_EXCHANGES` | betfair_ex_uk, betfair_ex_eu, betfair_ex_au, matchbook, smarkets | Drawn as dashed lines. |
| `OV_MARKETS` | h2h | Each extra market adds to the cost. |
| `OV_SPORTS` | 6 big soccer leagues | Choices in the league picker. |
| `OV_MONTHLY_CREDITS` | 500 | Used only before the first API call. |
| `OV_RESERVE_CREDITS` | 25 | Never spent by automatic polls. |
| `OV_RESET_DAY` | 1 | Day of month your quota resets. Check your account page. |
| `OV_DAILY_BURST` | 3 | How much more than the average one day may use. |
| `OV_PRIORITY_WINDOW_MIN` | 90 | Near-kickoff window that may go over the daily share. |
| `OV_DB_PATH` | odds_visualizer/odds_visualizer.db | SQLite file. |
| `OV_DEMO` | off | Force demo mode. |

The poll schedule table is `INTERVAL_TIERS` in `odds_visualizer/budget.py`.

## Not yet checked against the live API

This was built without network access to The Odds API. These points come
from third-party sources and need checking on your first real run:

- **The cost of the `/events` call** (used by Load fixtures). It is believed
  to be free. The call log shows the real cost after you click it.
- **Bookmaker keys.** The exchange keys (`betfair_ex_uk`, `matchbook`,
  `smarkets`) appear on the Odds API bookmaker page. The other keys are
  from memory. If a bookmaker never shows up in the chart, its key is wrong
  or it has no odds for that match. Check the list at
  https://the-odds-api.com/sports-odds-data/bookmaker-apis.html.
- **Exchange lay prices.** Exchanges give back prices in `h2h`. A lay market
  (`h2h_lay`) may exist, but this was not confirmed. If you add it to
  `OV_MARKETS`, the cost goes up, and it shows as its own market in the
  market picker.
- **Your reset date.** Set `OV_RESET_DAY` to match your account.

## Files

```
odds_visualizer/
  config.py     env settings + cost formula
  budget.py     poll schedule + credit rules (pure functions)
  oddsapi.py    API client + response flattening
  store.py      SQLite tables: events, snapshots, api_calls
  tracker.py    polling loop, ties it all together
  demo.py       fake data for demo mode
  server.py     FastAPI routes
  static/       dashboard (plain HTML/CSS/JS, SVG chart, no CDN)
tests/test_odds_visualizer.py
```
