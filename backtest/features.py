"""Features, typical-move calibration, steam score and outcomes.

Timeline for one candidate event (all times from the snapshots, no lookahead):
  t0   a snapshot: the move is measured here  (z, Agree)
  tf   flag time = the latest hold snapshot (t0 + 15 min or the first snapshot after)
       Hold is measured here, so the flag cannot be known before tf.
  c    the closing snapshot (last before kickoff)
All outcomes are measured from tf to c, using only snapshots at tf and c.
"""
from __future__ import annotations

import bisect
import math
import statistics as st
from dataclasses import dataclass

from . import config as C
from . import poisson

SERIES = ("L", "S", "T")      # L = logit(fair home), S = supremacy, T = expected total goals
SIDES = ("home", "draw", "away")


def logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def hours_bucket(h: float) -> int:
    for i in range(len(C.HOURS_EDGES) - 1):
        if C.HOURS_EDGES[i] <= h < C.HOURS_EDGES[i + 1]:
            return i
    return len(C.HOURS_EDGES) - 2


def hours_label(i: int) -> str:
    lo, hi = C.HOURS_EDGES[i], C.HOURS_EDGES[i + 1]
    return f"{lo:g}+h" if hi == float("inf") else f"{lo:g}-{hi:g}h"


@dataclass
class MatchSeries:
    match: object
    t: list            # epoch seconds
    L: list
    S: list
    T: list
    fit_ok: list
    hours: list        # hours to kickoff at each snapshot


def build_series(match) -> MatchSeries:
    t, L, S, T, ok = [], [], [], [], []
    for s in match.snaps:
        f = poisson.fit(s.ah_line, s.ah_fair_home, s.tot_line, s.tot_fair_over)
        t.append(s.t); L.append(logit(s.fair[0])); S.append(f["supremacy"]); T.append(f["total"]); ok.append(f["ok"])
    return MatchSeries(match, t, L, S, T, ok, [(match.kickoff - x) / 3600.0 for x in t])


def window_index(ms: MatchSeries, i: int, w_min: float):
    """Index j of the last snapshot at or before t_i - w, or None if it is more than 2w back."""
    target = ms.t[i] - w_min * 60.0
    j = bisect.bisect_right(ms.t, target + 1e-6) - 1
    if j < 0 or j >= i:
        return None
    if ms.t[i] - ms.t[j] > C.SPAN_FACTOR * w_min * 60.0:
        return None
    return j


def hold_index(ms: MatchSeries, i: int, h_min: float):
    """First snapshot with t >= t_i + h, only if it is within 2h."""
    k = bisect.bisect_left(ms.t, ms.t[i] + h_min * 60.0 - 1e-6)
    if k >= len(ms.t) or ms.t[k] - ms.t[i] > C.SPAN_FACTOR * h_min * 60.0:
        return None
    return k


# ---------------------------------------------------------------- calibration
class Typical:
    """Standard deviation of past changes, by series, window, league tier and hours-to-kickoff."""

    def __init__(self, cal_series: list[MatchSeries], windows: tuple):
        self.windows = windows
        cells: dict = {}
        for ms in cal_series:
            tier = ms.match.tier
            for i in range(len(ms.t)):
                hb = hours_bucket(ms.hours[i])
                for w in windows:
                    j = window_index(ms, i, w)
                    if j is None:
                        continue
                    for name in SERIES:
                        x = getattr(ms, name)
                        cells.setdefault((name, w, tier, hb), []).append(x[i] - x[j])
        self.n_changes = {k: len(v) for k, v in cells.items()}
        self.cell_sd = {k: st.pstdev(v) for k, v in cells.items() if len(v) >= 2}
        pool_h: dict = {}
        pool_w: dict = {}
        for (name, w, tier, hb), v in cells.items():
            pool_h.setdefault((name, w, hb), []).extend(v)
            pool_w.setdefault((name, w), []).extend(v)
        self.hour_sd = {k: (st.pstdev(v), len(v)) for k, v in pool_h.items() if len(v) >= 2}
        self.win_sd = {k: st.pstdev(v) for k, v in pool_w.items() if len(v) >= 2}
        self.cell_n = {k: len(v) for k, v in cells.items()}
        self.fallbacks = {"cell": 0, "tier_pooled": 0, "window_pooled": 0}

    def sd(self, name: str, w: int, tier: int, hours: float) -> float:
        hb = hours_bucket(hours)
        floor = C.FLOOR_FRAC * self.win_sd.get((name, w), 0.0)
        key = (name, w, tier, hb)
        if self.cell_n.get(key, 0) >= C.MIN_CELL_N:
            v = self.cell_sd[key]; self.fallbacks["cell"] += 1
        elif (name, w, hb) in self.hour_sd and self.hour_sd[(name, w, hb)][1] >= C.MIN_CELL_N:
            v = self.hour_sd[(name, w, hb)][0]; self.fallbacks["tier_pooled"] += 1
        else:
            v = self.win_sd.get((name, w), 0.0); self.fallbacks["window_pooled"] += 1
        return max(v, floor, 1e-9)


# ---------------------------------------------------------------- events
def _sign(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


def _clip01(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def best_window(ms: MatchSeries, typ: Typical, name: str, i: int, windows):
    """Largest |z| over the active windows -> (z, change, j, window)."""
    best = None
    x = getattr(ms, name)
    for w in windows:
        j = window_index(ms, i, w)
        if j is None:
            continue
        ch = x[i] - x[j]
        z = ch / typ.sd(name, w, ms.match.tier, ms.hours[i])
        if best is None or abs(z) > abs(best[0]):
            best = (z, ch, j, w)
    return best


def candidate_events(ms: MatchSeries, typ: Typical, windows, hold_horizons) -> list[dict]:
    """One candidate per snapshot that has a measurable move, hold and a later closing snapshot."""
    n = len(ms.t)
    c = n - 1
    close_gap_min = (ms.match.kickoff - ms.t[c]) / 60.0
    if close_gap_min > C.USABLE_CLOSE_MAX_MIN:
        return []
    snaps = ms.match.snaps
    out = []
    for i in range(n - 1):
        bw = {name: best_window(ms, typ, name, i, windows) for name in SERIES}
        if any(v is None for v in bw.values()):
            continue
        ks = [hold_index(ms, i, h) for h in hold_horizons]
        if any(k is None for k in ks):
            continue
        k = max(ks)                                  # flag time = end of the hold period
        if k >= c:                                   # nothing left after the flag
            continue
        e = {"match": ms.match.key, "kickoff": ms.match.kickoff, "league": ms.match.league, "tier": ms.match.tier,
             "t0": ms.t[i], "flag_t": ms.t[k], "hours_t0": ms.hours[i], "hours_flag": ms.hours[k],
             "min_to_close": (ms.t[c] - ms.t[k]) / 60.0}
        for name in SERIES:
            z, ch, j, w = bw[name]
            x = getattr(ms, name)
            holds = []
            for kk in ks:
                holds.append(_clip01((x[kk] - x[j]) / ch) if ch != 0 else 0.0)
            e[f"z_{name}"] = z
            e[f"chg_{name}"] = ch
            e[f"win_{name}"] = w
            e[f"dir_{name}"] = _sign(ch)
            e[f"hold_{name}"] = min(holds)
            e[f"cont_{name}"] = _sign(ch) * (x[c] - x[k])
        e["cont_L_pp"] = e["dir_L"] * (snaps[c].fair[0] - snaps[k].fair[0]) * 100.0
        # --- feature 5, 7
        e["agree"] = 1 if (e["dir_L"] != 0 and e["dir_L"] == e["dir_S"]) else 0
        e["zmin"] = min(abs(e["z_L"]), abs(e["z_S"]))
        e["hold"] = min(e["hold_L"], e["hold_S"])
        e["steam"] = e["agree"] * e["zmin"] * e["hold"]
        e["steam_no_agree"] = e["zmin"] * e["hold"]
        e["steam_no_hold"] = e["agree"] * e["zmin"]
        # --- mover side and CLV (1X2), margin features (9)
        jL = window_index(ms, i, e["win_L"])
        fair_then, fair_now = snaps[jL].fair, snaps[i].fair
        if e["dir_L"] > 0:
            mover = 0
        else:
            gains = [fair_now[s] - fair_then[s] for s in (1, 2)]
            mover = 1 + (0 if gains[0] >= gains[1] else 1)
        e["mover"] = SIDES[mover]
        e["clv_mover"] = snaps[k].ml[mover] * snaps[c].fair[mover] - 1.0
        m_then, m_now = snaps[jL].margin, snaps[i].margin
        key = f"margin_{SIDES[mover]}_share_pct"
        if m_then.get("margin_total_pct") is not None and m_now.get("margin_total_pct") is not None \
                and m_then.get(key) is not None and m_now.get(key) is not None:
            e["margin_total_chg"] = m_now["margin_total_pct"] - m_then["margin_total_pct"]
            e["margin_share_chg"] = m_now[key] - m_then[key]
            e["margin_onside"] = 1 if e["margin_share_chg"] > 0 else 0
        else:
            e["margin_total_chg"] = e["margin_share_chg"] = None
            e["margin_onside"] = None
        e["steam_full"] = e["steam"] * (e["margin_onside"] or 0) if e["margin_onside"] is not None else None
        # --- totals steam (8): own z, own hold; Over/Under CLV only if the line did not change
        e["totals_score"] = abs(e["z_T"])
        e["totals_score_hold"] = abs(e["z_T"]) * e["hold_T"]
        if snaps[k].tot_line == snaps[c].tot_line and e["dir_T"] != 0:
            if e["dir_T"] > 0:
                e["clv_totals"] = snaps[k].tot[0] * snaps[c].tot_fair_over - 1.0
            else:
                e["clv_totals"] = snaps[k].tot[1] * (1.0 - snaps[c].tot_fair_over) - 1.0
        else:
            e["clv_totals"] = None
        # --- raw-odds baseline: biggest shortening of a raw price over RAW_WINDOW_MIN
        jr = window_index(ms, i, C.RAW_WINDOW_MIN) if C.RAW_WINDOW_MIN in windows else None
        if jr is not None:
            pcts = [(snaps[i].ml[s] / snaps[jr].ml[s] - 1.0) * 100.0 for s in range(3)]
            s_best = min(range(3), key=lambda s: pcts[s])
            e["raw_short_pct"] = -pcts[s_best]
            e["raw_mover"] = SIDES[s_best]
            e["raw_dir"] = 1 if s_best == 0 else -1
            e["raw_cont_L_pp"] = e["raw_dir"] * (snaps[c].fair[0] - snaps[k].fair[0]) * 100.0
            e["raw_clv"] = snaps[k].ml[s_best] * snaps[c].fair[s_best] - 1.0
        else:
            e["raw_short_pct"] = e["raw_mover"] = e["raw_dir"] = e["raw_cont_L_pp"] = e["raw_clv"] = None
        out.append(e)
    return out
