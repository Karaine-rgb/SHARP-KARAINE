"""Run the steam backtest.   python -m backtest.run --data DIR --out DIR

Reads the exported snapshot CSVs (read-only), writes
  <out>/events_test.csv     every candidate event in the TEST period with features and outcomes
  <out>/tables.md           all result tables
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import statistics as st
import sys
import time
from datetime import datetime, timezone

from . import config as C
from . import data, features, stats


def fmt(x, nd=3):
    return "-" if x is None else f"{x:.{nd}f}"


def ci(d, nd=3, scale=1.0):
    if d.get("mean") is None:
        return "-"
    return f"{d['mean']*scale:.{nd}f} [{d['lo']*scale:.{nd}f}, {d['hi']*scale:.{nd}f}]"


def enough(d) -> bool:
    return d["n"] >= C.MIN_EVENTS_CELL and d["matches"] >= C.MIN_MATCHES_CELL


def cell(d, nd=3, scale=1.0):
    if d["n"] == 0:
        return "no events"
    s = ci(d, nd, scale)
    return s if enough(d) else f"{s} (too few)"


def md_table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def data_summary(matches, info, interval_min, windows, holds, cal, test, ms_all):
    gaps_all, gaps_near = [], []
    for m in matches:
        for a, b in zip(m.snaps, m.snaps[1:]):
            g = (b.t - a.t) / 60.0
            gaps_all.append(g)
            if (m.kickoff - b.t) / 3600.0 <= 3:
                gaps_near.append(g)
    q = lambda v, p: sorted(v)[int(p * (len(v) - 1))]
    kos = [datetime.fromtimestamp(m.kickoff, timezone.utc).date() for m in matches]
    close_gap = [(m.kickoff - m.snaps[-1].t) / 60.0 for m in matches]
    usable = sum(1 for g in close_gap if g <= C.USABLE_CLOSE_MAX_MIN)
    fit_ok = [ok for ms in ms_all for ok in ms.fit_ok]
    lines = [
        f"- Files read: {info['files']} ({info['rows']:,} rows, {info['dup_rows']:,} exact duplicate snapshot rows ignored)",
        f"- Matches with a usable 1X2 + AH + total series: **{len(matches)}**; snapshots: **{sum(len(m.snaps) for m in matches):,}**",
        f"- Kickoff range: {min(kos)} to {max(kos)}",
        f"- Gap between snapshots: median {q(gaps_all,.5):.1f} min overall; within 3 h of kickoff median {q(gaps_near,.5):.1f} min, "
        f"10th percentile {q(gaps_near,.1):.1f} min, 90th percentile {q(gaps_near,.9):.1f} min",
        f"- Matches with a usable closing line (last snapshot within {C.USABLE_CLOSE_MAX_MIN:.0f} min of kickoff): **{usable} of {len(matches)}**",
        f"- Collection interval used for skipping = {interval_min:.1f} min (10th percentile near-kickoff gap)",
        f"- Move windows used: {list(windows)} min; skipped: {[w for w in C.WINDOWS_MIN if w not in windows]} (shorter than the collection interval)",
        f"- Hold horizons used: {list(holds)} min; skipped: {[h for h in C.HOLD_HORIZONS_MIN if h not in holds]} (a snapshot cannot exist inside that gap)",
        f"- Poisson fit reached both targets on {100*sum(fit_ok)/len(fit_ok):.2f}% of snapshots; largest gap between the model's AH / over probability and the fair target: {_fit_resid(ms_all):.1e}",
        f"- Calibration: earliest {len(cal)} matches ({datetime.fromtimestamp(cal[0].match.kickoff, timezone.utc).date()} to "
        f"{datetime.fromtimestamp(cal[-1].match.kickoff, timezone.utc).date()}); TEST: latest {len(test)} matches "
        f"({datetime.fromtimestamp(test[0].match.kickoff, timezone.utc).date()} to {datetime.fromtimestamp(test[-1].match.kickoff, timezone.utc).date()})",
        f"- Tiers (name-based): " + ", ".join(f"tier {t}: {sum(1 for m in matches if m.tier==t)}" for t in (1, 2, 3)),
    ]
    return "\n".join(lines)


def _fit_resid(ms_all):
    from . import poisson
    worst = 0.0
    for ms in ms_all:
        for sn, S_, T_ in zip(ms.match.snaps, ms.S, ms.T):
            lh, la = (T_ + S_) / 2, (T_ - S_) / 2
            worst = max(worst, abs(poisson.home_cover_prob(lh, la, sn.ah_line) - sn.ah_fair_home),
                        abs(poisson.over_prob(T_, sn.tot_line) - sn.tot_fair_over))
    return worst


def smoothness(ms_all):
    """Does the fitted supremacy / total stay smooth when the quoted line changes?"""
    d = {"ah_chg": [], "ah_same": [], "tot_chg": [], "tot_same": [], "line_chg": [], "line_same": []}
    for ms in ms_all:
        sn = ms.match.snaps
        for i in range(1, len(sn)):
            if ms.t[i] - ms.t[i - 1] > 3600:
                continue
            ds, dt_ = abs(ms.S[i] - ms.S[i - 1]), abs(ms.T[i] - ms.T[i - 1])
            dl = abs(sn[i].ah_line - sn[i - 1].ah_line)
            (d["ah_chg"] if dl > 0 else d["ah_same"]).append(ds)
            (d["line_chg"] if dl > 0 else d["line_same"]).append(dl)
            (d["tot_chg"] if sn[i].tot_line != sn[i - 1].tot_line else d["tot_same"]).append(dt_)
    mean = lambda v: sum(v) / len(v) if v else float("nan")
    return (f"| step | n | mean abs change in the quoted line | mean abs change in fitted supremacy |\n|---|---|---|---|\n"
            f"| AH line changed | {len(d['ah_chg'])} | {mean(d['line_chg']):.3f} goals | {mean(d['ah_chg']):.3f} goals |\n"
            f"| AH line unchanged | {len(d['ah_same'])} | 0 | {mean(d['ah_same']):.3f} goals |\n"
            f"| total line changed | {len(d['tot_chg'])} | - | {mean(d['tot_chg']):.3f} goals (expected total) |\n"
            f"| total line unchanged | {len(d['tot_same'])} | - | {mean(d['tot_same']):.3f} goals (expected total) |")


def csv_columns(events):
    cols = []
    for e in events:
        for k in e:
            if k not in cols:
                cols.append(k)
    return cols


def run(data_dir: str, out_dir: str) -> str:
    t_start = time.time()
    os.makedirs(out_dir, exist_ok=True)
    matches, info = data.load_matches(data_dir)
    ms_all = [features.build_series(m) for m in matches]
    n_cal = int(math.ceil(C.CAL_FRACTION * len(ms_all)))
    cal, test = ms_all[:n_cal], ms_all[n_cal:]

    near_gaps = [(b.t - a.t) / 60.0 for m in matches for a, b in zip(m.snaps, m.snaps[1:]) if (m.kickoff - b.t) / 3600.0 <= 3]
    interval = sorted(near_gaps)[int(0.1 * (len(near_gaps) - 1))]
    windows = tuple(w for w in C.WINDOWS_MIN if w >= interval)
    holds = tuple(h for h in C.HOLD_HORIZONS_MIN if h >= interval)

    typ = features.Typical(cal, windows)           # calibrated on the earliest 70% only
    events = []
    for ms in test:
        events.extend(features.candidate_events(ms, typ, windows, holds))
    keys = [ms.match.key for ms in test]
    boot = stats.Boot(keys, C.BOOT_B, C.SEED)

    # ----------------------------------------------------------------- csv
    for e in events:
        e["flagged"] = 1 if e["steam"] >= C.FLAG_MIN_SCORE else 0
        e["kickoff"] = datetime.fromtimestamp(e["kickoff"], timezone.utc).isoformat()
        e["t0_iso"] = datetime.fromtimestamp(e["t0"], timezone.utc).isoformat()
        e["flag_iso"] = datetime.fromtimestamp(e["flag_t"], timezone.utc).isoformat()
    events.sort(key=lambda e: (e["kickoff"], e["t0"]))
    cols = csv_columns(events)
    with open(os.path.join(out_dir, "events_test.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for e in events:
            w.writerow({k: ("" if e.get(k) is None else (round(e[k], 6) if isinstance(e[k], float) else e[k])) for k in cols})

    # ----------------------------------------------------------------- tables
    E = events
    out = []
    P = out.append
    P("## 1. Data summary\n")
    P(data_summary(matches, info, interval, windows, holds, cal, test, ms_all))
    P(f"\nCandidate events in the test period (a snapshot with a measurable move, a hold snapshot and a later close): **{len(E)}** "
      f"from **{len({e['match'] for e in E})}** of {len(test)} test matches. "
      f"Typical-move lookups: {typ.fallbacks}.\n")
    P("Smoothness of the fitted supremacy / expected total when the quoted line changes (all matches, steps up to 1 h apart):\n")
    P(smoothness(ms_all))

    OUTS = [("1X2 continuation (pp of fair home prob)", lambda e: e["cont_L_pp"], 1, 3),
            ("supremacy continuation (goals)", lambda e: e["cont_S"], 1, 4),
            ("CLV of mover side", lambda e: e["clv_mover"], 100, 2)]

    def bucket_table(title, events_, score, edges=C.BUCKET_EDGES):
        rows = []
        for b in range(len(edges) - 1):
            g = [e for e in events_ if score(e) is not None and stats.bucket_of(score(e), edges) == b]
            row = [stats.bucket_label(b, edges), len(g), len({e['match'] for e in g})]
            for _, val, sc, nd in OUTS:
                row.append(cell(boot.mean(g, val), nd, sc))
            rows.append(row)
        P(f"\n{title}\n")
        P(md_table(["score bucket", "events", "matches"] + [o[0] + (" (%)" if o[2] == 100 else "") for o in OUTS], rows))
        sl = [boot.slope(events_, score, val) for _, val, _, _ in OUTS]
        P("\nSlope of outcome per +1 score (all events), 95% match-level CI: " + "; ".join(
            f"{OUTS[i][0]}: {fmt(sl[i]['slope'], 4)} [{fmt(sl[i]['lo'], 4)}, {fmt(sl[i]['hi'], 4)}] (n={sl[i]['n']})" for i in range(len(OUTS))))

    P("\n## 2. Steam score buckets (TEST period only)")
    bucket_table("Steam = Agree x min(|z_1X2|, |z_supremacy|) x Hold", E, lambda e: e["steam"])

    # baselines
    P("\n## 3. Baselines (same flag-to-close measurement)\n")
    base_rows = []
    def base_row(name, g, val_c, val_k):
        c, k = boot.mean(g, val_c), boot.mean(g, val_k)
        return [name, c["n"], c["matches"], cell(c, 3), cell(k, 2, 100)]
    all_ev = [e for e in E]
    base_rows.append(base_row("all candidate snapshots (direction = 1X2 move)", all_ev, lambda e: e["cont_L_pp"], lambda e: e["clv_mover"]))
    for X in C.RAW_MOVE_PCTS:
        g = [e for e in E if e["raw_short_pct"] is not None and e["raw_short_pct"] > X]
        base_rows.append(base_row(f"raw price shortened > {X:g}% in {C.RAW_WINDOW_MIN} min", g, lambda e: e["raw_cont_L_pp"], lambda e: e["raw_clv"]))
    for lo, name in ((C.FLAG_MIN_SCORE, f"steam score >= {C.FLAG_MIN_SCORE:g}"), (2.0, "steam score >= 2")):
        g = [e for e in E if e["steam"] >= lo]
        base_rows.append(base_row(name, g, lambda e: e["cont_L_pp"], lambda e: e["clv_mover"]))
    P(md_table(["group", "events", "matches", "1X2 continuation (pp) [95% CI]", "CLV of mover side (%) [95% CI]"], base_rows))
    flagged = [e for e in E if e["steam"] >= C.FLAG_MIN_SCORE]
    d_c = boot.diff(flagged, all_ev, lambda e: e["cont_L_pp"])
    d_k = boot.diff(flagged, all_ev, lambda e: e["clv_mover"])
    P(f"\nFlagged (score >= {C.FLAG_MIN_SCORE:g}) minus all snapshots: continuation {fmt(d_c['diff'])} pp [{fmt(d_c['lo'])}, {fmt(d_c['hi'])}]; "
      f"CLV {fmt(None if d_k['diff'] is None else d_k['diff']*100, 2)} pp [{fmt(None if d_k['lo'] is None else d_k['lo']*100, 2)}, {fmt(None if d_k['hi'] is None else d_k['hi']*100, 2)}]")
    for X in C.RAW_MOVE_PCTS:
        g = [e for e in E if e["raw_short_pct"] is not None and e["raw_short_pct"] > X]
        dc = boot.diff(flagged, g, lambda e: e["cont_L_pp"], lambda e: e["raw_cont_L_pp"])
        dk = boot.diff(flagged, g, lambda e: e["clv_mover"], lambda e: e["raw_clv"])
        P(f"\nFlagged minus raw>{X:g}% rule: continuation {fmt(dc['diff'])} pp [{fmt(dc['lo'])}, {fmt(dc['hi'])}]; "
          f"CLV {fmt(None if dk['diff'] is None else dk['diff']*100, 2)} pp [{fmt(None if dk['lo'] is None else dk['lo']*100, 2)}, {fmt(None if dk['hi'] is None else dk['hi']*100, 2)}]")

    # ----------------------------------------------------------------- features alone and ablation
    P("\n## 4. Each feature alone, and removing one at a time\n")
    P("Groups are events at or above the score shown. Margin features use the tool's margin distribution for the 1X2 snapshot.\n")
    variants = [
        ("FULL = steam x margin-on-side gate", lambda e: e["steam_full"]),
        ("full minus margin gate = steam", lambda e: e["steam"]),
        ("full minus Agree", lambda e: None if e["margin_onside"] is None else e["steam_no_agree"] * e["margin_onside"]),
        ("full minus Hold", lambda e: None if e["margin_onside"] is None else e["agree"] * e["zmin"] * e["margin_onside"]),
        ("|z 1X2| alone", lambda e: abs(e["z_L"])),
        ("|z supremacy| alone", lambda e: abs(e["z_S"])),
        ("min(|z 1X2|, |z supremacy|) alone (no Agree, no Hold)", lambda e: e["zmin"]),
        ("steam without Agree", lambda e: e["steam_no_agree"]),
        ("steam without Hold", lambda e: e["steam_no_hold"]),
    ]
    rows = []
    for name, sc in variants:
        for thr in (1.0, 2.0):
            g = [e for e in E if sc(e) is not None and sc(e) >= thr]
            c, k = boot.mean(g, lambda e: e["cont_L_pp"]), boot.mean(g, lambda e: e["clv_mover"])
            s = boot.slope([e for e in E if sc(e) is not None], sc, lambda e: e["cont_L_pp"])
            rows.append([name, f">= {thr:g}", c["n"], c["matches"], cell(c, 3), cell(k, 2, 100),
                         f"{fmt(s['slope'],3)} [{fmt(s['lo'],3)}, {fmt(s['hi'],3)}]"])
    P(md_table(["score", "group", "events", "matches", "1X2 continuation (pp)", "CLV (%)", "slope of continuation per +1 (all events)"], rows))

    P("\n### Binary / bounded features split\n")
    def split(name, groups):
        rws = []
        for gname, g in groups:
            c, k = boot.mean(g, lambda e: e["cont_L_pp"]), boot.mean(g, lambda e: e["clv_mover"])
            rws.append([name, gname, c["n"], c["matches"], cell(c, 3), cell(k, 2, 100)])
        return rws
    rows = []
    rows += split("Agree", [("Agree = 1", [e for e in E if e["agree"] == 1]), ("Agree = 0", [e for e in E if e["agree"] == 0])])
    rows += split("Hold (steam-direction hold)", [(f"hold {lo:g}-{hi:g}", [e for e in E if lo <= e["hold"] < hi or (hi == 1.0001 and e["hold"] >= lo)]) for lo, hi in ((0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0001))])
    ml = [e for e in E if e["margin_onside"] is not None]
    rows += split("margin shifted onto mover", [("onside = 1", [e for e in ml if e["margin_onside"] == 1]), ("onside = 0", [e for e in ml if e["margin_onside"] == 0])])
    rows += split("total margin change over window", [("margin rose", [e for e in ml if e["margin_total_chg"] > 1e-9]), ("margin fell", [e for e in ml if e["margin_total_chg"] < -1e-9]), ("unchanged", [e for e in ml if abs(e["margin_total_chg"]) <= 1e-9])])
    st_ml = [e for e in ml if e["steam"] >= C.FLAG_MIN_SCORE]
    rows += split("within steam >= 1: margin on side", [("onside = 1", [e for e in st_ml if e["margin_onside"] == 1]), ("onside = 0", [e for e in st_ml if e["margin_onside"] == 0])])
    rows += split("within steam >= 1: total margin", [("margin rose", [e for e in st_ml if e["margin_total_chg"] > 1e-9]), ("margin fell", [e for e in st_ml if e["margin_total_chg"] < -1e-9])])
    P(md_table(["feature", "group", "events", "matches", "1X2 continuation (pp)", "CLV (%)"], rows))

    P("\n### Paired differences (match-level bootstrap, same resamples)\n")
    def dline(name, ga, gb):
        dc = boot.diff(ga, gb, lambda e: e["cont_L_pp"])
        dk = boot.diff(ga, gb, lambda e: e["clv_mover"])
        sc = lambda d, k, m=1: "-" if d[k] is None else f"{d[k]*m:.2f}"
        return [name, len(ga), len(gb), f"{sc(dc,'diff')} [{sc(dc,'lo')}, {sc(dc,'hi')}]", f"{sc(dk,'diff',100)} [{sc(dk,'lo',100)}, {sc(dk,'hi',100)}]"]
    zs = [e for e in E if e["zmin"] >= 1.0]
    drows = [
        dline("steam >= 1  minus  steam < 1", [e for e in E if e["steam"] >= 1], [e for e in E if e["steam"] < 1]),
        dline("steam >= 2  minus  steam < 1", [e for e in E if e["steam"] >= 2], [e for e in E if e["steam"] < 1]),
        dline("steam >= 1 & margin onside  minus  steam >= 1 & not onside", [e for e in st_ml if e["margin_onside"] == 1], [e for e in st_ml if e["margin_onside"] == 0]),
        dline("[min z >= 1] Agree = 1  minus  Agree = 0", [e for e in zs if e["agree"] == 1], [e for e in zs if e["agree"] == 0]),
        dline("[min z >= 1 & Agree] Hold >= 0.75  minus  Hold < 0.75", [e for e in zs if e["agree"] == 1 and e["hold"] >= 0.75], [e for e in zs if e["agree"] == 1 and e["hold"] < 0.75]),
    ]
    P(md_table(["comparison", "events A", "events B", "continuation diff (pp) [95% CI]", "CLV diff (pp) [95% CI]"], drows))
    P(f"\nEvents with min(|z|) >= 1 but Agree = 0: {sum(1 for e in zs if e['agree']==0)} of {len(zs)}.")

    # ----------------------------------------------------------------- hours and tier
    P("\n## 5. Breakdown by hours to kickoff (at flag time) and league tier\n")
    rows = []
    for hb in range(len(C.HOURS_EDGES) - 1):
        for gname, cond in ((f"steam < {C.FLAG_MIN_SCORE:g}", lambda e: e["steam"] < C.FLAG_MIN_SCORE), (f"steam >= {C.FLAG_MIN_SCORE:g}", lambda e: e["steam"] >= C.FLAG_MIN_SCORE)):
            g = [e for e in E if features.hours_bucket(e["hours_flag"]) == hb and cond(e)]
            if not g:
                continue
            c, k = boot.mean(g, lambda e: e["cont_L_pp"]), boot.mean(g, lambda e: e["clv_mover"])
            rows.append([features.hours_label(hb), gname, c["n"], c["matches"], cell(c, 3), cell(k, 2, 100)])
    P(md_table(["hours to kickoff", "group", "events", "matches", "1X2 continuation (pp)", "CLV (%)"], rows))
    rows = []
    for tier in (1, 2, 3):
        for gname, cond in ((f"steam < {C.FLAG_MIN_SCORE:g}", lambda e: e["steam"] < C.FLAG_MIN_SCORE), (f"steam >= {C.FLAG_MIN_SCORE:g}", lambda e: e["steam"] >= C.FLAG_MIN_SCORE)):
            g = [e for e in E if e["tier"] == tier and cond(e)]
            if not g:
                continue
            c, k = boot.mean(g, lambda e: e["cont_L_pp"]), boot.mean(g, lambda e: e["clv_mover"])
            rows.append([f"tier {tier}", gname, c["n"], c["matches"], cell(c, 3), cell(k, 2, 100)])
    P("\n" + md_table(["league tier", "group", "events", "matches", "1X2 continuation (pp)", "CLV (%)"], rows))

    # ----------------------------------------------------------------- totals
    P("\n## 6. Totals steam (expected total goals, scored on its own)\n")
    for label, sc in (("|z total|", lambda e: e["totals_score"]), ("|z total| x Hold(total)", lambda e: e["totals_score_hold"])):
        rows = []
        for b in range(len(C.BUCKET_EDGES) - 1):
            g = [e for e in E if stats.bucket_of(sc(e), C.BUCKET_EDGES) == b]
            c = boot.mean(g, lambda e: e["cont_T"])
            k = boot.mean(g, lambda e: e["clv_totals"])
            rows.append([stats.bucket_label(b, C.BUCKET_EDGES), c["n"], c["matches"], cell(c, 4), k["n"], cell(k, 2, 100)])
        P(f"\n{label}\n")
        P(md_table(["bucket", "events", "matches", "expected-total continuation (goals)", "events with same-line Over/Under CLV", "Over/Under CLV (%)"], rows))
        s = boot.slope(E, sc, lambda e: e["cont_T"])
        P(f"\nSlope of continuation per +1: {fmt(s['slope'],4)} [{fmt(s['lo'],4)}, {fmt(s['hi'],4)}] (n={s['n']})")

    P(f"\n_Run took {time.time()-t_start:.0f}s; bootstrap {C.BOOT_B} resamples of whole matches, seed {C.SEED}._")
    text = "\n".join(out)
    with open(os.path.join(out_dir, "tables.md"), "w") as fh:
        fh.write(text + "\n")
    return text


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="folder with *match_snapshots*.csv exports (read-only)")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "results"))
    a = ap.parse_args(argv)
    print(run(a.data, a.out))


if __name__ == "__main__":
    main()
