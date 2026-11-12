"""Load the exported snapshot CSVs (read-only) into per-match aligned snapshots.

Only full-game (period 0), main-line (not alternate), non-suspended 1X2 / AH /
total rows captured at or before kickoff are used. Fair probabilities are
recomputed from the decimal prices with the tool's own power de-vig
(app.odds), the same way for every snapshot and every market; the stored fair
columns are only used to check the recomputation.
"""
from __future__ import annotations

import bisect
import csv
import glob
import os
from dataclasses import dataclass, field
from datetime import datetime

from app.odds import fair_probs_from_decimal_odds, margin_columns
from . import config


@dataclass
class Snap:
    t: float                    # capture time, epoch seconds
    ml: tuple                   # (home, draw, away) decimal prices
    fair: tuple                 # (home, draw, away) fair probabilities (recomputed)
    margin: dict                # tool's margin_columns for the 1X2 snapshot
    ah_line: float              # home handicap of the main AH line
    ah: tuple                   # (home, away) prices
    ah_fair_home: float
    tot_line: float
    tot: tuple                  # (over, under) prices
    tot_fair_over: float
    stored_fair_gap: float = 0.0


@dataclass
class Match:
    key: str
    kickoff: float
    league: str
    tier: int
    round_label: str
    snaps: list[Snap] = field(default_factory=list)


def _ts(s: str) -> float:
    return datetime.fromisoformat(s).timestamp()


def _f(x: str):
    return float(x) if x not in ("", None) else None


def load_matches(data_dir: str) -> tuple[list[Match], dict]:
    files = sorted(glob.glob(os.path.join(data_dir, "*match_snapshots*.csv")))
    seen: set = set()
    raw: dict[str, dict] = {}
    info = {"files": len(files), "rows": 0, "dup_rows": 0}
    for fn in files:
        with open(fn, newline="", encoding="utf-8-sig") as fh:          # read-only
            for r in csv.DictReader(fh):
                info["rows"] += 1
                sid = r["snapshot_id"]
                if sid in seen:
                    info["dup_rows"] += 1
                    continue
                seen.add(sid)
                if r["period"] != "0" or r["is_alternate"] != "False" or r["status"] == "suspended":
                    continue
                if r["market_type"] not in ("moneyline", "spread", "total"):
                    continue
                k = r["pinnacle_matchup_id"]
                m = raw.setdefault(k, {"kickoff": _ts(r["kickoff"]), "league": r["league_name"],
                                       "round": r["mjp_round_label"], "moneyline": [], "spread": [], "total": []})
                t = _ts(r["captured_at"])
                if t > m["kickoff"]:
                    continue
                h, d, a = _f(r["home_price"]), _f(r["draw_price"]), _f(r["away_price"])
                if h is None or a is None or h <= 1 or a <= 1:
                    continue
                m[r["market_type"]].append({
                    "t": t, "h": h, "d": d, "a": a, "line": _f(r["home_points"]),
                    "fair": (_f(r["fair_home_prob"]), _f(r["fair_draw_prob"]), _f(r["fair_away_prob"])),
                })
    matches: list[Match] = []
    for k, m in raw.items():
        for mk in ("moneyline", "spread", "total"):
            m[mk].sort(key=lambda e: e["t"])
        sp_t = [e["t"] for e in m["spread"]]
        to_t = [e["t"] for e in m["total"]]
        mt = Match(k, m["kickoff"], m["league"], config.tier_of(m["league"]), m["round"])
        for e in m["moneyline"]:
            if e["d"] is None or e["d"] <= 1:
                continue
            sp = _nearest(m["spread"], sp_t, e["t"])
            to = _nearest(m["total"], to_t, e["t"])
            if sp is None or to is None or sp["line"] is None or to["line"] is None:
                continue
            fair = tuple(fair_probs_from_decimal_odds([e["h"], e["d"], e["a"]]))
            ah_fair = fair_probs_from_decimal_odds([sp["h"], sp["a"]])[0]
            ov_fair = fair_probs_from_decimal_odds([to["h"], to["a"]])[0]
            gap = max(abs(a - b) for a, b in zip(fair, e["fair"]) if b is not None) if all(x is not None for x in e["fair"]) else 0.0
            mt.snaps.append(Snap(
                t=e["t"], ml=(e["h"], e["d"], e["a"]), fair=fair,
                margin=margin_columns(e["h"], e["d"], e["a"], *fair),
                ah_line=sp["line"], ah=(sp["h"], sp["a"]), ah_fair_home=ah_fair,
                tot_line=to["line"], tot=(to["h"], to["a"]), tot_fair_over=ov_fair, stored_fair_gap=gap))
        if len(mt.snaps) >= 3:
            matches.append(mt)
    matches.sort(key=lambda x: x.kickoff)
    return matches, info


def _nearest(rows: list[dict], times: list[float], t: float, tol: float = 60.0):
    i = bisect.bisect_left(times, t)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(rows) and abs(times[j] - t) <= tol and (best is None or abs(times[j] - t) < abs(best["t"] - t)):
            best = rows[j]
    return best
