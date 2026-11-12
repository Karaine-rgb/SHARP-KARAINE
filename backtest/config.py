"""Every parameter of the backtest, fixed BEFORE looking at any result.

Nothing here is tuned on the test period. To change a rule, edit it here and
rerun; the report is regenerated from these values.
"""
from __future__ import annotations

# --- windows -------------------------------------------------------------
WINDOWS_MIN = (5, 15, 60)          # move-size windows (feature 4)
HOLD_HORIZONS_MIN = (10, 15)       # hold checks (feature 6)
SPAN_FACTOR = 2.0                  # a "w-minute" change must come from a snapshot at most 2w back,
                                   # and a hold snapshot must fall in [t0+h, t0+2h]; otherwise the
                                   # gap is too coarse for that window and the event is skipped

# --- typical-move calibration (feature 4) ------------------------------------
CAL_FRACTION = 0.70                # earliest 70% of matches by kickoff date calibrate; the rest test
HOURS_EDGES = (0.0, 1.0, 3.0, 6.0, 12.0, 24.0, 48.0, float("inf"))   # hours-to-kickoff buckets
MIN_CELL_N = 150                   # a (series, window, tier, hours) cell needs this many past changes,
                                   # else fall back to (series, window, hours) pooled over tiers,
                                   # then to (series, window) pooled
FLOOR_FRAC = 0.20                  # typical move floor = 20% of the pooled (series, window) std

# --- closing line ------------------------------------------------------------
USABLE_CLOSE_MAX_MIN = 30.0        # closing snapshot must be within 30 min of kickoff

# --- scoring / reporting ----------------------------------------------------------
BUCKET_EDGES = (0.0, 1.0, 2.0, 3.0, 4.0, float("inf"))   # steam-score buckets asked for
FLAG_MIN_SCORE = 1.0               # "flagged" = steam score >= 1 (lower edge of the first non-trivial bucket)
RAW_MOVE_PCTS = (2.0, 5.0)         # baseline: raw price shortened by more than X% over the 15-minute window
RAW_WINDOW_MIN = 15
MIN_EVENTS_CELL = 30               # a table cell with fewer events or matches than this is marked "too few"
MIN_MATCHES_CELL = 10
BOOT_B = 2000                      # bootstrap resamples (whole matches)
SEED = 20260101

# --- league tiers (the data has no tier column; this is a name-based grouping) --
TIER1 = {
    "England - Premier League", "Spain - La Liga", "Italy - Serie A",
    "Germany - Bundesliga", "France - Ligue 1",
}
TIER3 = {"Spain - Primera Federacion", "Spain - Segunda Division Corners", "England - EFL Cup"}
# everything else (other first divisions, second divisions of the big five) = tier 2


def tier_of(league: str) -> int:
    if league in TIER1:
        return 1
    if league in TIER3:
        return 3
    return 2
