# Steam backtest: report

All numbers are from the **test period only** (the latest 30% of matches by kickoff). Typical move sizes were
calibrated on the earliest 70%. Nothing was tuned on the test period; every rule is fixed in `config.py`.
Full tables: `results/tables.md`. Every event: `results/events_test.csv`.

## Bottom line

**On this data, the steam score does not predict where the line goes next, and flagged moves have worse closing line
value than an average snapshot.** No bucket rises with the score. The top buckets (3+) hold 6 events from 5 matches, so
nothing can be said about very large steam. I would not keep any of the nine features as a signal on this evidence.
A few measurement pieces (the fair-probability step, the Poisson fit) are worth keeping as tools, not as predictors.

## 1. Data summary

| item | value |
|---|---|
| matches with a usable 1X2 + AH + total series | 174 (5,989 snapshots; 129,138 duplicate rows across overlapping exports ignored) |
| kickoff range | 2026-09-05 to 2026-11-02 |
| gap between snapshots | median 15.7 min within 3 h of kickoff (10th percentile 13.7, 90th percentile 46.1); median 30 min overall; hours apart a day or more out |
| matches with a usable closing line (last snapshot within 30 min of kickoff) | 174 of 174 |
| calibration / test split | 122 matches (2026-09-05 to 2026-10-25) / **52 matches (2026-10-25 to 2026-11-02)** |
| candidate events in the test period | 676 from 51 matches; 144 flagged (score at least 1) from 39 matches |
| Poisson fit | reached both targets on 100% of snapshots; largest gap to the fair AH / over probabilities 1e-10 |
| recomputed fair probabilities vs the stored ones | identical (largest difference 0) |

**Skipped because the data cannot support them:**
- the **5-minute move window** (snapshots are at best about 14 minutes apart);
- the **10-minute hold** (no snapshot can exist inside that gap; carrying the old price forward would make Hold equal 1 by construction).

So z uses 15- and 60-minute windows and Hold uses 15 minutes only. The 15-minute window is effectively "the last one or two
snapshots" (15 to 30 min back). Events far from kickoff mostly drop out because snapshots there are hours apart; usable events sit within about 24 h of kickoff.

**Other things to know:**
- The league tier is my own grouping by league name (the data has no tier column): tier 1 = big-five top flights, tier 3 = Spain Primera Federacion and two oddities, tier 2 = everything else. Tier 3 has one test match with flags.
- The test period is nine days and about one round, 29 of 39 flagged matches are tier 1. Results may not carry to other periods.
- Poisson goals are independent (no Dixon-Coles correction). It is fitted to the AH and over prices only, so it makes no claim about the draw price.
- Supremacy stays smooth when the line changes: mean absolute change in fitted supremacy is 0.042 goals on a step where the AH line moved 0.25 goals, against 0.015 on steps where it did not (some line moves come with real price moves).

## 2. Steam score buckets

Steam = Agree x min(|z 1X2|, |z supremacy|) x Hold. Continuation = how far the 1X2 home fair probability kept moving in the
signal's direction from flag time to close (percentage points). CLV = Pinnacle price at flag time x fair closing probability - 1, on the side that moved. Intervals are 95%, resampling whole matches.

| steam score | events | matches | 1X2 continuation (pp) | supremacy continuation (goals) | CLV (%) |
|---|---|---|---|---|---|
| 0-1 | 532 | 51 | 0.24 [-0.05, 0.62] | 0.004 [-0.009, 0.020] | -3.6 [-4.8, -2.6] |
| 1-2 | 95 | 37 | -0.31 [-0.66, 0.05] | -0.012 [-0.025, 0.003] | -4.8 [-6.2, -3.3] |
| 2-3 | 43 | 21 | -0.13 [-1.05, 0.97] | -0.016 [-0.069, 0.038] | -7.1 [-14.2, -1.3] |
| 3-4 | 5 | 4 | too few | too few | too few |
| 4+ | 1 | 1 | too few | too few | too few |

There is no steady rise. Slope of continuation per +1 of score, all events: **-0.27 pp [-0.58, +0.05]**; CLV slope -1.6 pp per +1 [-3.3, +0.1].
CLV is about -3.6% for the quietest bucket because that is roughly Pinnacle's margin; a signal would need to sit clearly above it.

## 3. Baselines

| group | events | matches | 1X2 continuation (pp) | CLV (%) |
|---|---|---|---|---|
| all candidate snapshots | 676 | 51 | 0.13 [-0.13, 0.44] | -4.1 [-5.4, -3.1] |
| raw price shortened more than 2% in 15 min | 79 | 38 | -0.47 [-0.87, -0.07] | -7.8 [-11.7, -4.8] |
| raw price shortened more than 5% in 15 min | 22 | 18 | too few | too few |
| steam score at least 1 | 144 | 39 | -0.29 [-0.70, 0.18] | -5.8 [-8.5, -3.4] |
| steam score at least 2 | 49 | 22 | -0.25 [-1.08, 0.74] | -7.9 [-14.6, -1.9] |

- Steam (at least 1) minus all snapshots: continuation **-0.42 pp [-0.81, -0.01]**, CLV -1.7 pp [-3.7, +0.05]. Fast moves tend to settle back a little by the close, if anything.
- Steam (at least 1) minus the raw 2% rule: continuation +0.18 pp [-0.19, +0.56], CLV **+2.0 pp [+0.1, +4.3]**. Steam is a little less bad than a raw-odds rule, but both are below the all-snapshot baseline, so it is not evidence that steam works.
- With 144 flagged events from 39 matches the data can rule out a continuation edge larger than about +0.2 pp for the at-least-1 group. For at-least-2 (49 events) it cannot rule out up to +0.7 pp; for 3+ it says nothing.

## 4. Each feature alone and removing one at a time

Groups are events at or above the score shown; slope is over all events. "Full" = steam gated by whether the 1X2 margin share moved onto the side that moved.

| score | group | events | matches | continuation (pp) | CLV (%) |
|---|---|---|---|---|---|
| full | >= 1 | 75 | 27 | -0.70 [-1.46, 0.07] | -7.5 [-11.7, -3.9] |
| full minus margin gate (= steam) | >= 1 | 144 | 39 | -0.29 [-0.70, 0.18] | -5.8 [-8.5, -3.4] |
| full minus Agree | >= 1 | 75 | 27 | -0.70 [-1.46, 0.07] | -7.5 [-11.7, -3.9] |
| full minus Hold | >= 1 | 99 | 32 | -0.46 [-1.17, 0.30] | -6.6 [-10.0, -3.3] |
| \|z 1X2\| alone | >= 1 | 225 | 47 | -0.11 [-0.42, 0.28] | -4.9 [-6.8, -3.1] |
| \|z supremacy\| alone | >= 1 | 231 | 47 | -0.15 [-0.51, 0.26] | -5.3 [-7.4, -3.4] |
| min of the two z, no Agree, no Hold | >= 1 | 193 | 45 | -0.14 [-0.54, 0.32] | -5.3 [-7.5, -3.2] |

Paired differences (same match resamples):

| comparison | continuation diff (pp) | CLV diff (pp) |
|---|---|---|
| steam >= 1 minus steam < 1 | -0.53 [-1.04, -0.01] | -2.2 [-4.6, +0.1] |
| steam >= 1, margin on the mover's side, minus not | -0.86 [-1.89, +0.15] | -3.6 [-8.7, +1.6] |
| among min z >= 1: Hold >= 0.75 minus Hold < 0.75 | -0.26 [-0.87, +0.42] | -0.6 [-3.5, +2.5] |

**Agree adds nothing here.** Of 193 events with min(|z|) >= 1, only **1** has the 1X2 and supremacy moves pointing opposite ways: the AH and 1X2 lines move together at Pinnacle, so the condition is almost always true. Removing Agree does not change the counts. **Hold** only trims events (192 to 144 with it); the held group is not better than the unheld one. The **margin features** point the unwelcome way (margin moving onto the mover's side goes with worse results) but the intervals include zero.

## 5. By hours to kickoff and league tier

Flagged (>= 1) vs not, continuation in pp. No row shows flagged events doing better, and most flagged cells have too few events:

| hours to kickoff | not flagged | flagged |
|---|---|---|
| 0-1 h | -0.02 (82 events) | -0.34 (24, too few) |
| 1-3 h | 0.34 [0.06, 0.62] (115) | -0.63 [-1.61, 0.39] (31) |
| 3-6 h | 0.20 (135) | 0.11 (26, too few) |
| 6-12 h | 0.34 [-0.03, 0.76] (154) | -0.68 [-1.55, 0.13] (44) |
| 12-24 h | 0.22 (36) | 1.03 [-1.01, 3.15] (14, too few) |

Tier 1 (117 flagged events, 29 matches): -0.34 [-0.84, 0.24]. Tier 2: 21 events, too few. Tier 3: one match, nothing to conclude.

## 6. Totals steam (expected total goals, on its own)

Continuation of expected total goals by |z total| bucket: 0-1: -0.002; 1-2: -0.001; 2-3: +0.005; 3-4: -0.015 (too few); 4+: -0.058 (7 events, too few). Slope -0.003 goals per +1 [-0.012, +0.008]. Over/Under CLV (same-line cases only) is about -2.4% to -3.5% in every bucket. Adding Hold does not change this. **No sign of any effect, and the high-z buckets are too small to test.**

## 7. Verdict by feature

| # | feature | verdict | reason |
|---|---|---|---|
| 1 | Fair probabilities (tool's power de-vig) | keep (it is the base layer, not a signal) | recomputed values equal the stored ones exactly |
| 2 | 1X2 logit series | drop as a signal | \|z\| of at least 1 alone: -0.11 pp [-0.42, +0.28], CLV below baseline |
| 3 | Supremacy and expected total (Poisson) | keep as a measurement, drop as a signal | fit reaches both targets on every snapshot and is smooth across line changes; supremacy z alone shows no continuation |
| 4 | Move size z (15 and 60 min) | drop | no rise across z; slope CI includes zero and leans negative. The 5-minute window was skipped (data too coarse) |
| 5 | Agree | drop | redundant: true in 192 of 193 strong-move events |
| 6 | Hold | unclear, leaning drop | the 10-minute check was skipped; 15-minute hold gives no better outcomes (diff -0.26 pp [-0.87, +0.42]) |
| 7 | Steam score | does not work on this data | no rise across buckets; at least 1 is -0.29 pp, worse than all snapshots; buckets 3+ have 6 events: **not enough data to say anything about very large steam** |
| 8 | Totals steam | unclear (no sign of effect) | flat in every bucket; the high-z buckets have 7 events |
| 9 | Margin features | unclear | margin on the mover's side goes with worse outcomes (-0.86 pp [-1.89, +0.15]) but the interval includes zero; one of many comparisons |

## 8. Cautions

- About 60 intervals are shown. A few nominally "significant" ones (for example steam minus all snapshots at -0.42 [-0.81, -0.01]) are what chance produces at this count; do not read them as findings.
- Events in the same match overlap in time and are not independent; that is why the bootstrap resamples whole matches, and why 676 events behave like far fewer.
- One nine-day test window with 52 matches cannot settle whether steam matters in other seasons or leagues. It can say that no edge is visible here and that a big one is unlikely for scores of 1 to 3.
- If you want a better-powered answer, the data you have is the limit: collect with a shorter snapshot interval near kickoff (5-minute windows and 10-minute holds then switch on automatically), and rerun on a larger set of rounds.
