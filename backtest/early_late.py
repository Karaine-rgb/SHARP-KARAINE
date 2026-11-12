"""Does early steam beat late steam?   python -m backtest.early_late --data DIR [--out FILE]

For every side the dashboard shows as steaming (app.signals.steam_moves, the same code and
the same 3-hour early/late rule), checks whether that side won, against what the market's own
closing fair probability for that side said it should win. A signal that "beats" the market
wins more often than the closing price implies; one that merely repeats the market does not.

All steam labels are formed from pre-kickoff snapshots only; results are only used to score them.
Intervals resample whole matches (sides of one match are not independent). Read-only on the data.
"""
from __future__ import annotations

import argparse
import csv
import glob
import math
import os
import random
from datetime import datetime, timezone

from app.signals import CONFIG, steam_moves

SIDES = ("home", "draw", "away")
B, SEED = 4000, 20260202


def load(data_dir):
    seen, matches = set(), {}
    for fn in sorted(glob.glob(os.path.join(data_dir, "*match_snapshots*.csv"))):
        with open(fn, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if r["snapshot_id"] in seen:
                    continue
                seen.add(r["snapshot_id"])
                if r["market_type"] != "moneyline" or r["period"] != "0" or r["is_alternate"] != "False" or r["status"] == "suspended":
                    continue
                ko = datetime.fromisoformat(r["kickoff"])
                t = datetime.fromisoformat(r["captured_at"])
                if t > ko or not r["fair_home_prob"]:
                    continue
                m = matches.setdefault(r["pinnacle_matchup_id"], {"kickoff": ko, "hs": int(r["home_score"]), "as": int(r["away_score"]), "round": r["mjp_round_label"], "series": []})
                m["series"].append({"captured_at": t, "status": "open", "fair_home_prob": float(r["fair_home_prob"]),
                                    "fair_draw_prob": float(r["fair_draw_prob"]), "fair_away_prob": float(r["fair_away_prob"])})
    for m in matches.values():
        m["series"].sort(key=lambda s: s["captured_at"])
    return matches


def build_rows(matches):
    rows = []
    for key, m in matches.items():
        ser = m["series"]
        if len(ser) < 3:
            continue
        res = "home" if m["hs"] > m["as"] else "away" if m["as"] > m["hs"] else "draw"
        close = ser[-1]
        for mv in steam_moves(ser, m["kickoff"]):
            sw = mv["swings"]
            rows.append({
                "match": key, "side": mv["side"], "timing": mv["timing"], "hours": mv["hours_before_kickoff"], "mag": mv["magnitude_pp"],
                "has_early": mv["early_pp"] is not None, "has_late": mv["late_pp"] is not None,
                "win": 1.0 if res == mv["side"] else 0.0, "p_close": close[f"fair_{mv['side']}_prob"], "p_open": ser[0][f"fair_{mv['side']}_prob"],
                "n_swings": len(sw), "rank": None,
            })
    by_match = {}
    for r in rows:
        by_match.setdefault(r["match"], []).append(r)
    for rs in by_match.values():
        for i, r in enumerate(sorted(rs, key=lambda x: -x["mag"])):
            r["rank"] = i + 1
    return rows


class Boot:
    def __init__(self, keys):
        self.keys = sorted(set(keys)); self.ix = {k: i for i, k in enumerate(self.keys)}
        rnd = random.Random(SEED); m = len(self.keys)
        self.draws = [[rnd.randrange(m) for _ in range(m)] for _ in range(B)]
        self.m = m

    def agg(self, rows, f):
        s, n = [0.0] * self.m, [0] * self.m
        for r in rows:
            i = self.ix[r["match"]]; s[i] += f(r); n[i] += 1
        return s, n

    def mean(self, rows, f):
        s, n = self.agg(rows, f)
        if not sum(n):
            return None
        pt = sum(s) / sum(n)
        bs = sorted(sum(s[i] for i in d) / sum(n[i] for i in d) for d in self.draws if sum(n[i] for i in d))
        return pt, bs[int(.025 * (len(bs) - 1))], bs[int(.975 * (len(bs) - 1))]

    def diff(self, a, b, f):
        sa, na = self.agg(a, f); sb, nb = self.agg(b, f)
        pt = sum(sa) / sum(na) - sum(sb) / sum(nb)
        bs = []
        for d in self.draws:
            x, y = sum(na[i] for i in d), sum(nb[i] for i in d)
            if x and y:
                bs.append(sum(sa[i] for i in d) / x - sum(sb[i] for i in d) / y)
        bs.sort()
        return pt, bs[int(.025 * (len(bs) - 1))], bs[int(.975 * (len(bs) - 1))]


def ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i]); rk = [0.0] * len(v); i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            rk[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return rk


def pearson(x, y):
    n = len(x); mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x)); sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx and sy else 0.0


def spearman_cluster(boot, rows, xf, yf):
    def corr(rs):
        return pearson(ranks([xf(r) for r in rs]), ranks([yf(r) for r in rs]))
    pt = corr(rows)
    by = {}
    for r in rows:
        by.setdefault(r["match"], []).append(r)
    keys = sorted(by); out = []
    for d in boot.draws[:2000]:
        rs = [r for i in d for r in by.get(boot.keys[i], [])]
        if len(rs) > 5:
            out.append(corr(rs))
    out.sort()
    return pt, out[int(.025 * (len(out) - 1))], out[int(.975 * (len(out) - 1))]


def fmt_group(boot, name, rows, resid=lambda r: r["win"] - r["p_close"]):
    if not rows:
        return f"| {name} | 0 | 0 | - | - | - |"
    o, e = sum(r["win"] for r in rows), sum(r["p_close"] for r in rows)
    pt, lo, hi = boot.mean(rows, resid)
    return (f"| {name} | {len(rows)} | {len({r['match'] for r in rows})} | {o/len(rows):.1%} | {e/len(rows):.1%} | "
            f"{pt*100:+.1f} [{lo*100:+.1f}, {hi*100:+.1f}] |")


HEAD = "| group | sides | matches | won | expected from closing price | edge, pp [95% CI] |\n|---|---|---|---|---|---|"


def run(data_dir):
    matches = load(data_dir)
    rows = build_rows(matches)
    boot = Boot([r["match"] for r in rows])
    out = []; P = out.append
    early = [r for r in rows if r["timing"] == "early"]; late = [r for r in rows if r["timing"] == "late"]
    resid = lambda r: r["win"] - r["p_close"]
    P(f"## Early vs late steam ({len(matches)} matches, {len(rows)} steaming sides, {len({r['match'] for r in rows})} matches with steam)\n")
    P(f"Late = the side's biggest steam swing finished within {CONFIG['late_steam_hours']:g} h of kickoff (dashboard rule). Edge = won minus the closing fair probability of that side.\n")
    P("### 1. Sides by the timing of their biggest swing (the label on the dashboard)\n"); P(HEAD)
    P(fmt_group(boot, "early", early)); P(fmt_group(boot, "late", late)); P(fmt_group(boot, "all steaming sides", rows))
    d = boot.diff(early, late, resid)
    P(f"\n**early minus late edge: {d[0]*100:+.1f} pp [{d[1]*100:+.1f}, {d[2]*100:+.1f}]**; raw win rate {sum(r['win'] for r in early)/len(early):.1%} vs {sum(r['win'] for r in late)/len(late):.1%}\n")
    P("What the two groups look like (so the comparison is read fairly):\n")
    P("| | early | late |\n|---|---|---|")
    mean = lambda rs, f: sum(f(r) for r in rs) / len(rs)
    med = lambda rs, f: sorted(f(r) for r in rs)[len(rs) // 2]
    P(f"| median biggest swing (pp) | {med(early, lambda r: r['mag']):.2f} | {med(late, lambda r: r['mag']):.2f} |")
    P(f"| mean closing prob of the side | {mean(early, lambda r: r['p_close']):.1%} | {mean(late, lambda r: r['p_close']):.1%} |")
    for sd in SIDES:
        P(f"| share that are {sd} | {sum(1 for r in early if r['side']==sd)/len(early):.0%} | {sum(1 for r in late if r['side']==sd)/len(late):.0%} |")
    P("\n### 2. Sides by which periods they had steam in\n"); P(HEAD)
    only_e = [r for r in rows if r["has_early"] and not r["has_late"]]
    only_l = [r for r in rows if r["has_late"] and not r["has_early"]]
    both = [r for r in rows if r["has_early"] and r["has_late"]]
    P(fmt_group(boot, "early steam only", only_e)); P(fmt_group(boot, "late steam only", only_l)); P(fmt_group(boot, "early AND late steam", both))
    for nm, a, b in (("early only minus late only", only_e, only_l), ("both minus late only", both, only_l), ("both minus early only", both, only_e)):
        d = boot.diff(a, b, resid); P(f"\n- {nm}: {d[0]*100:+.1f} pp [{d[1]*100:+.1f}, {d[2]*100:+.1f}]")
    P("\n### 3. Each match's top-ranked steam side, by timing\n"); P(HEAD)
    top = [r for r in rows if r["rank"] == 1]
    te = [r for r in top if r["timing"] == "early"]; tl = [r for r in top if r["timing"] == "late"]
    P(fmt_group(boot, "top side, early", te)); P(fmt_group(boot, "top side, late", tl))
    d = boot.diff(te, tl, resid); P(f"\nearly minus late (top side): {d[0]*100:+.1f} pp [{d[1]*100:+.1f}, {d[2]*100:+.1f}]")
    P("\n### 4. Bigger swings only (2 pp or more)\n"); P(HEAD)
    be = [r for r in early if r["mag"] >= 2]; bl = [r for r in late if r["mag"] >= 2]
    P(fmt_group(boot, "early >= 2pp", be)); P(fmt_group(boot, "late >= 2pp", bl))
    if be and bl:
        d = boot.diff(be, bl, resid); P(f"\nearly minus late (>= 2pp): {d[0]*100:+.1f} pp [{d[1]*100:+.1f}, {d[2]*100:+.1f}]")
    P("\n### 5. Same match, early side vs late side (paired inside matches that have both)\n"); P(HEAD)
    mk = {}
    for r in rows:
        mk.setdefault(r["match"], []).append(r)
    paired = [k for k, rs in mk.items() if any(r["timing"] == "early" for r in rs) and any(r["timing"] == "late" for r in rs)]
    pe = [r for k in paired for r in mk[k] if r["timing"] == "early"]; pl = [r for k in paired for r in mk[k] if r["timing"] == "late"]
    P(fmt_group(boot, f"early sides ({len(paired)} matches)", pe)); P(fmt_group(boot, "late sides (same matches)", pl))
    if pe and pl:
        d = boot.diff(pe, pl, resid); P(f"\nearly minus late within those matches: {d[0]*100:+.1f} pp [{d[1]*100:+.1f}, {d[2]*100:+.1f}]")
    P("\n### 6. No cutoff: hours before kickoff of the biggest swing vs the edge\n")
    c = spearman_cluster(boot, rows, lambda r: r["hours"], resid)
    P(f"Spearman correlation (more hours before kickoff = earlier) with edge: {c[0]:+.3f} [{c[1]:+.3f}, {c[2]:+.3f}] over {len(rows)} sides")
    P("\nSensitivity to where 'late' starts (not a tuned choice; the dashboard uses 3 h):\n")
    P("| late = within | early sides | late sides | early minus late edge, pp [95% CI] |\n|---|---|---|---|")
    for h in (1.0, 2.0, 3.0, 6.0, 12.0):
        e2 = [r for r in rows if r["hours"] > h]; l2 = [r for r in rows if r["hours"] <= h]
        if e2 and l2:
            d = boot.diff(e2, l2, resid)
            P(f"| {h:g} h | {len(e2)} | {len(l2)} | {d[0]*100:+.1f} [{d[1]*100:+.1f}, {d[2]*100:+.1f}] |")
    P("\n### 7. Checks on the within-match result (section 5)\n")
    rnd = random.Random(SEED + 1)
    def paired_diff(rs_by_match, shuffle):
        a = b = ea = eb = 0.0; na = nb = 0
        for k, rs in rs_by_match.items():
            labels = [r["timing"] for r in rs]
            if shuffle:
                rnd.shuffle(labels)
            for r, lab in zip(rs, labels):
                x = r["win"] - r["p_close"]
                if lab == "early":
                    a += x; na += 1
                else:
                    b += x; nb += 1
        return a / na - b / nb
    pm = {k: mk[k] for k in paired}
    obs = paired_diff(pm, False)
    perm = [paired_diff(pm, True) for _ in range(5000)]
    p_perm = (sum(1 for x in perm if abs(x) >= abs(obs)) + 1) / (len(perm) + 1)
    P(f"- Shuffling the early/late labels among the steaming sides of each of those {len(paired)} matches: observed {obs*100:+.1f} pp, permutation p = {p_perm:.3f}")
    ha = lambda rs: [r for r in rs if r["side"] != "draw"]
    de, dl = ha(pe), ha(pl)
    if de and dl:
        d = boot.diff(de, dl, resid)
        P(f"- Same comparison with draw sides removed (late steam is more often on the draw): early {len(de)} vs late {len(dl)} sides, {d[0]*100:+.1f} pp [{d[1]*100:+.1f}, {d[2]*100:+.1f}]")
    nonpaired_e = [r for r in early if r["match"] not in set(paired)]; nonpaired_l = [r for r in late if r["match"] not in set(paired)]
    if nonpaired_e and nonpaired_l:
        d = boot.diff(nonpaired_e, nonpaired_l, resid)
        P(f"- Early vs late in all OTHER matches (no early/late pair): {len(nonpaired_e)} vs {len(nonpaired_l)} sides, {d[0]*100:+.1f} pp [{d[1]*100:+.1f}, {d[2]*100:+.1f}]")
    P("- Comparisons reported above: about 20, so one or two intervals that just exclude zero are expected by chance alone.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default=None, help="optional markdown file to write")
    a = ap.parse_args(argv)
    text = run(a.data)
    print(text)
    if a.out:
        with open(a.out, "w") as fh:
            fh.write(text + "\n")


if __name__ == "__main__":
    main()
