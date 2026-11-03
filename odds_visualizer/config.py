"""Settings for the odds movement visualizer. All values come from env vars."""
from __future__ import annotations

import math
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _list(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
ODDS_API_BASE = os.getenv("ODDS_API_BASE", "https://api.the-odds-api.com/v4").rstrip("/")

# Up to 10 bookmakers are billed like ONE region, so keep this list at 10 or
# fewer to pay 1 credit per market per poll. Exchanges are included on purpose.
BOOKMAKERS = _list(
    "OV_BOOKMAKERS",
    "pinnacle,betfair_ex_uk,betfair_ex_eu,matchbook,smarkets,"
    "williamhill,unibet_eu,onexbet,marathonbet,betsson",
)
# Keys treated as betting exchanges (drawn dashed in charts).
EXCHANGES = set(_list("OV_EXCHANGES", "betfair_ex_uk,betfair_ex_eu,betfair_ex_au,matchbook,smarkets"))

# Each extra market multiplies the cost. "h2h" = 1X2 for soccer.
MARKETS = _list("OV_MARKETS", "h2h")

# Sports offered in the fixture picker (keys from GET /v4/sports).
SPORTS = _list(
    "OV_SPORTS",
    "soccer_epl,soccer_spain_la_liga,soccer_germany_bundesliga,"
    "soccer_italy_serie_a,soccer_france_ligue_one,soccer_uefa_champs_league",
)

MONTHLY_CREDITS = int(os.getenv("OV_MONTHLY_CREDITS", "500"))
# Credits we never touch automatically (kept for manual checks / mistakes).
RESERVE_CREDITS = int(os.getenv("OV_RESERVE_CREDITS", "25"))
# Day of month your quota resets (check your Odds API account page).
RESET_DAY = int(os.getenv("OV_RESET_DAY", "1"))
# A single day may spend up to this many times the average daily share.
DAILY_BURST = float(os.getenv("OV_DAILY_BURST", "3"))
# Inside this many minutes before kickoff, polls may go over the daily share
# (but never into the reserve).
PRIORITY_WINDOW_MIN = int(os.getenv("OV_PRIORITY_WINDOW_MIN", "90"))

DB_PATH = Path(os.getenv("OV_DB_PATH", str(Path(__file__).parent / "odds_visualizer.db")))

# Demo mode: fake fixtures + fake odds history, zero API calls.
DEMO = os.getenv("OV_DEMO", "").lower() in ("1", "true", "yes") or not ODDS_API_KEY

# How often the background loop wakes up to check if a poll is due.
LOOP_SECONDS = int(os.getenv("OV_LOOP_SECONDS", "60"))


def estimated_cost(n_markets: int | None = None, n_bookmakers: int | None = None) -> int:
    """Cost of one /odds call: markets x ceil(bookmakers / 10)."""
    m = len(MARKETS) if n_markets is None else n_markets
    b = len(BOOKMAKERS) if n_bookmakers is None else n_bookmakers
    return max(1, m) * max(1, math.ceil(b / 10))
