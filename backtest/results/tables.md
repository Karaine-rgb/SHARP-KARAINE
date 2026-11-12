## 1. Data summary

- Files read: 15 (338,130 rows, 129,138 exact duplicate snapshot rows ignored)
- Matches with a usable 1X2 + AH + total series: **174**; snapshots: **5,989**
- Kickoff range: 2026-09-05 to 2026-11-02
- Gap between snapshots: median 30.4 min overall; within 3 h of kickoff median 15.7 min, 10th percentile 13.7 min, 90th percentile 46.1 min
- Matches with a usable closing line (last snapshot within 30 min of kickoff): **174 of 174**
- Collection interval used for skipping = 13.7 min (10th percentile near-kickoff gap)
- Move windows used: [15, 60] min; skipped: [5] (shorter than the collection interval)
- Hold horizons used: [15] min; skipped: [10] (a snapshot cannot exist inside that gap)
- Poisson fit reached both targets on 100.00% of snapshots; largest gap between the model's AH / over probability and the fair target: 9.9e-11
- Calibration: earliest 122 matches (2026-09-05 to 2026-10-25); TEST: latest 52 matches (2026-10-25 to 2026-11-02)
- Tiers (name-based): tier 1: 71, tier 2: 82, tier 3: 21

Candidate events in the test period (a snapshot with a measurable move, a hold snapshot and a later close): **676** from **51** of 52 test matches. Typical-move lookups: {'cell': 3006, 'tier_pooled': 2706, 'window_pooled': 660}.

Smoothness of the fitted supremacy / expected total when the quoted line changes (all matches, steps up to 1 h apart):

| step | n | mean abs change in the quoted line | mean abs change in fitted supremacy |
|---|---|---|---|
| AH line changed | 157 | 0.250 goals | 0.042 goals |
| AH line unchanged | 3565 | 0 | 0.015 goals |
| total line changed | 151 | - | 0.055 goals (expected total) |
| total line unchanged | 3571 | - | 0.012 goals (expected total) |

## 2. Steam score buckets (TEST period only)

Steam = Agree x min(|z_1X2|, |z_supremacy|) x Hold

| score bucket | events | matches | 1X2 continuation (pp of fair home prob) | supremacy continuation (goals) | CLV of mover side (%) |
|---|---|---|---|---|---|
| 0-1 | 532 | 51 | 0.240 [-0.054, 0.618] | 0.0037 [-0.0091, 0.0195] | -3.60 [-4.84, -2.62] |
| 1-2 | 95 | 37 | -0.312 [-0.655, 0.046] | -0.0118 [-0.0253, 0.0030] | -4.76 [-6.22, -3.30] |
| 2-3 | 43 | 21 | -0.129 [-1.047, 0.965] | -0.0156 [-0.0692, 0.0377] | -7.10 [-14.17, -1.28] |
| 3-4 | 5 | 4 | -1.262 [-2.094, -0.462] (too few) | -0.0280 [-0.0420, -0.0188] (too few) | -15.01 [-28.46, -2.88] (too few) |
| 4+ | 1 | 1 | -0.559 [-0.559, -0.559] (too few) | -0.0007 [-0.0007, -0.0007] (too few) | -3.92 [-3.92, -3.92] (too few) |

Slope of outcome per +1 score (all events), 95% match-level CI: 1X2 continuation (pp of fair home prob): -0.2725 [-0.5752, 0.0474] (n=676); supremacy continuation (goals): -0.0093 [-0.0218, 0.0027] (n=676); CLV of mover side: -0.0158 [-0.0332, 0.0014] (n=676)

## 3. Baselines (same flag-to-close measurement)

| group | events | matches | 1X2 continuation (pp) [95% CI] | CLV of mover side (%) [95% CI] |
|---|---|---|---|---|
| all candidate snapshots (direction = 1X2 move) | 676 | 51 | 0.127 [-0.131, 0.439] | -4.07 [-5.39, -3.08] |
| raw price shortened > 2% in 15 min | 79 | 38 | -0.470 [-0.870, -0.071] | -7.80 [-11.70, -4.80] |
| raw price shortened > 5% in 15 min | 22 | 18 | -0.953 [-1.621, -0.369] (too few) | -11.14 [-17.45, -6.21] (too few) |
| steam score >= 1 | 144 | 39 | -0.292 [-0.702, 0.178] | -5.81 [-8.49, -3.38] |
| steam score >= 2 | 49 | 22 | -0.254 [-1.079, 0.738] | -7.85 [-14.55, -1.93] |

Flagged (score >= 1) minus all snapshots: continuation -0.419 pp [-0.813, -0.008]; CLV -1.74 pp [-3.68, 0.05]

Flagged minus raw>2% rule: continuation 0.178 pp [-0.187, 0.556]; CLV 1.99 pp [0.10, 4.26]

Flagged minus raw>5% rule: continuation 0.661 pp [-0.022, 1.377]; CLV 5.33 pp [1.57, 10.20]

## 4. Each feature alone, and removing one at a time

Groups are events at or above the score shown. Margin features use the tool's margin distribution for the 1X2 snapshot.

| score | group | events | matches | 1X2 continuation (pp) | CLV (%) | slope of continuation per +1 (all events) |
|---|---|---|---|---|---|---|
| FULL = steam x margin-on-side gate | >= 1 | 75 | 27 | -0.704 [-1.462, 0.066] | -7.52 [-11.69, -3.85] | -0.498 [-1.113, 0.069] |
| FULL = steam x margin-on-side gate | >= 2 | 25 | 13 | -0.818 [-2.242, 0.719] (too few) | -9.66 [-17.28, -1.61] (too few) | -0.498 [-1.113, 0.069] |
| full minus margin gate = steam | >= 1 | 144 | 39 | -0.292 [-0.702, 0.178] | -5.81 [-8.49, -3.38] | -0.273 [-0.575, 0.047] |
| full minus margin gate = steam | >= 2 | 49 | 22 | -0.254 [-1.079, 0.738] | -7.85 [-14.55, -1.93] | -0.273 [-0.575, 0.047] |
| full minus Agree | >= 1 | 75 | 27 | -0.704 [-1.462, 0.066] | -7.52 [-11.69, -3.85] | -0.513 [-1.145, 0.068] |
| full minus Agree | >= 2 | 25 | 13 | -0.818 [-2.242, 0.719] (too few) | -9.66 [-17.28, -1.61] (too few) | -0.513 [-1.145, 0.068] |
| full minus Hold | >= 1 | 99 | 32 | -0.463 [-1.171, 0.295] | -6.63 [-10.03, -3.33] | -0.444 [-0.976, 0.053] |
| full minus Hold | >= 2 | 31 | 16 | -0.921 [-2.105, 0.438] | -9.56 [-15.82, -3.01] | -0.444 [-0.976, 0.053] |
| |z 1X2| alone | >= 1 | 225 | 47 | -0.113 [-0.422, 0.276] | -4.93 [-6.82, -3.10] | -0.178 [-0.394, 0.037] |
| |z 1X2| alone | >= 2 | 74 | 28 | -0.141 [-0.894, 0.626] | -6.46 [-11.04, -2.53] | -0.178 [-0.394, 0.037] |
| |z supremacy| alone | >= 1 | 231 | 47 | -0.146 [-0.505, 0.256] | -5.27 [-7.42, -3.35] | -0.177 [-0.416, 0.077] |
| |z supremacy| alone | >= 2 | 79 | 31 | -0.245 [-0.867, 0.458] | -7.19 [-12.42, -2.87] | -0.177 [-0.416, 0.077] |
| min(|z 1X2|, |z supremacy|) alone (no Agree, no Hold) | >= 1 | 193 | 45 | -0.143 [-0.537, 0.320] | -5.26 [-7.52, -3.15] | -0.208 [-0.475, 0.068] |
| min(|z 1X2|, |z supremacy|) alone (no Agree, no Hold) | >= 2 | 61 | 26 | -0.230 [-1.024, 0.639] | -7.20 [-13.01, -2.42] | -0.208 [-0.475, 0.068] |
| steam without Agree | >= 1 | 144 | 39 | -0.292 [-0.702, 0.178] | -5.81 [-8.49, -3.38] | -0.281 [-0.586, 0.044] |
| steam without Agree | >= 2 | 49 | 22 | -0.254 [-1.079, 0.738] | -7.85 [-14.55, -1.93] | -0.281 [-0.586, 0.044] |
| steam without Hold | >= 1 | 192 | 45 | -0.151 [-0.548, 0.315] | -5.29 [-7.59, -3.15] | -0.206 [-0.468, 0.069] |
| steam without Hold | >= 2 | 61 | 26 | -0.230 [-1.024, 0.639] | -7.20 [-13.01, -2.42] | -0.206 [-0.468, 0.069] |

### Binary / bounded features split

| feature | group | events | matches | 1X2 continuation (pp) | CLV (%) |
|---|---|---|---|---|---|
| Agree | Agree = 1 | 551 | 51 | 0.113 [-0.192, 0.476] | -4.04 [-5.42, -2.91] |
| Agree | Agree = 0 | 125 | 42 | 0.190 [-0.048, 0.419] | -4.22 [-5.73, -2.78] |
| Hold (steam-direction hold) | hold 0-0.25 | 202 | 42 | 0.247 [0.033, 0.473] | -3.32 [-4.71, -2.19] |
| Hold (steam-direction hold) | hold 0.25-0.5 | 21 | 16 | 0.668 [0.013, 1.453] (too few) | -1.82 [-3.82, 0.11] (too few) |
| Hold (steam-direction hold) | hold 0.5-0.75 | 60 | 33 | 0.054 [-0.388, 0.489] | -5.37 [-7.66, -3.51] |
| Hold (steam-direction hold) | hold 0.75-1.0001 | 393 | 50 | 0.048 [-0.336, 0.463] | -4.38 [-6.12, -2.97] |
| margin shifted onto mover | onside = 1 | 329 | 49 | -0.261 [-0.572, 0.078] | -5.86 [-7.76, -4.25] |
| margin shifted onto mover | onside = 0 | 347 | 47 | 0.495 [-0.080, 1.176] | -2.38 [-4.41, -0.63] |
| total margin change over window | margin rose | 308 | 49 | 0.120 [-0.240, 0.547] | -4.71 [-7.17, -2.96] |
| total margin change over window | margin fell | 342 | 50 | 0.146 [-0.134, 0.435] | -3.36 [-4.06, -2.65] |
| total margin change over window | unchanged | 26 | 19 | -0.046 [-0.165, 0.000] (too few) | -6.00 [-11.96, -1.68] (too few) |
| within steam >= 1: margin on side | onside = 1 | 75 | 27 | -0.704 [-1.462, 0.066] | -7.52 [-11.69, -3.85] |
| within steam >= 1: margin on side | onside = 0 | 69 | 31 | 0.156 [-0.439, 0.785] | -3.95 [-7.78, -1.12] |
| within steam >= 1: total margin | margin rose | 68 | 32 | -0.292 [-0.663, 0.113] | -7.13 [-11.56, -3.32] |
| within steam >= 1: total margin | margin fell | 75 | 31 | -0.280 [-0.939, 0.473] | -4.56 [-6.90, -2.05] |

### Paired differences (match-level bootstrap, same resamples)

| comparison | events A | events B | continuation diff (pp) [95% CI] | CLV diff (pp) [95% CI] |
|---|---|---|---|---|
| steam >= 1  minus  steam < 1 | 144 | 532 | -0.53 [-1.04, -0.01] | -2.21 [-4.63, 0.07] |
| steam >= 2  minus  steam < 1 | 49 | 532 | -0.49 [-1.27, 0.44] | -4.24 [-10.27, 1.30] |
| steam >= 1 & margin onside  minus  steam >= 1 & not onside | 75 | 69 | -0.86 [-1.89, 0.15] | -3.57 [-8.68, 1.62] |
| [min z >= 1] Agree = 1  minus  Agree = 0 | 192 | 1 | -1.48 [-1.89, -1.03] | -5.70 [-8.07, -3.74] |
| [min z >= 1 & Agree] Hold >= 0.75  minus  Hold < 0.75 | 145 | 47 | -0.26 [-0.87, 0.42] | -0.56 [-3.45, 2.50] |

Events with min(|z|) >= 1 but Agree = 0: 1 of 193.

## 5. Breakdown by hours to kickoff (at flag time) and league tier

| hours to kickoff | group | events | matches | 1X2 continuation (pp) | CLV (%) |
|---|---|---|---|---|---|
| 0-1h | steam < 1 | 82 | 45 | -0.021 [-0.286, 0.243] | -3.72 [-4.92, -2.61] |
| 0-1h | steam >= 1 | 24 | 19 | -0.341 [-0.802, 0.159] (too few) | -3.81 [-5.55, -2.28] (too few) |
| 1-3h | steam < 1 | 115 | 35 | 0.335 [0.062, 0.620] | -3.04 [-4.13, -2.05] |
| 1-3h | steam >= 1 | 31 | 17 | -0.628 [-1.606, 0.393] | -5.00 [-9.19, -1.57] |
| 3-6h | steam < 1 | 135 | 42 | 0.204 [-0.369, 0.894] | -3.39 [-5.16, -1.76] |
| 3-6h | steam >= 1 | 26 | 17 | 0.113 [-0.839, 1.285] (too few) | -3.62 [-6.69, -0.80] (too few) |
| 6-12h | steam < 1 | 154 | 38 | 0.340 [-0.027, 0.755] | -3.93 [-5.30, -2.84] |
| 6-12h | steam >= 1 | 44 | 21 | -0.678 [-1.554, 0.126] | -9.33 [-15.94, -3.70] |
| 12-24h | steam < 1 | 36 | 18 | 0.224 [-0.749, 1.407] | -3.30 [-6.94, 0.33] |
| 12-24h | steam >= 1 | 14 | 6 | 1.027 [-1.005, 3.151] (too few) | -4.60 [-14.21, 5.16] (too few) |
| 24-48h | steam < 1 | 9 | 7 | 0.421 [0.000, 1.106] (too few) | -6.39 [-18.34, 0.65] (too few) |
| 24-48h | steam >= 1 | 2 | 1 | -1.358 [-1.358, -1.358] (too few) | -8.90 [-8.90, -8.90] (too few) |
| 48+h | steam < 1 | 1 | 1 | -0.756 [-0.756, -0.756] (too few) | -23.32 [-23.32, -23.32] (too few) |
| 48+h | steam >= 1 | 3 | 2 | 0.272 [0.041, 0.388] (too few) | -1.25 [-1.45, -0.85] (too few) |

| league tier | group | events | matches | 1X2 continuation (pp) | CLV (%) |
|---|---|---|---|---|---|
| tier 1 | steam < 1 | 442 | 35 | 0.295 [-0.053, 0.744] | -3.22 [-4.03, -2.43] |
| tier 1 | steam >= 1 | 117 | 29 | -0.343 [-0.844, 0.244] | -5.56 [-8.35, -3.17] |
| tier 2 | steam < 1 | 73 | 15 | 0.018 [-0.367, 0.373] | -6.02 [-12.11, -1.95] |
| tier 2 | steam >= 1 | 21 | 9 | 0.048 [-0.638, 0.942] (too few) | -8.02 [-18.33, -0.47] (too few) |
| tier 3 | steam < 1 | 17 | 1 | -0.216 [-0.216, -0.216] (too few) | -3.16 [-3.16, -3.16] (too few) |
| tier 3 | steam >= 1 | 6 | 1 | -0.490 [-0.490, -0.490] (too few) | -3.01 [-3.01, -3.01] (too few) |

## 6. Totals steam (expected total goals, scored on its own)


|z total|

| bucket | events | matches | expected-total continuation (goals) | events with same-line Over/Under CLV | Over/Under CLV (%) |
|---|---|---|---|---|---|
| 0-1 | 471 | 51 | -0.0019 [-0.0092, 0.0068] | 268 | -2.45 [-3.00, -1.84] |
| 1-2 | 123 | 32 | -0.0005 [-0.0237, 0.0244] | 107 | -2.82 [-3.98, -1.68] |
| 2-3 | 46 | 24 | 0.0054 [-0.0383, 0.0509] | 39 | -2.40 [-4.77, -0.02] |
| 3-4 | 29 | 14 | -0.0145 [-0.0519, 0.0290] (too few) | 20 | -3.49 [-4.63, -1.74] (too few) |
| 4+ | 7 | 5 | -0.0580 [-0.1105, 0.0303] (too few) | 3 | -3.68 [-5.85, -2.19] (too few) |

Slope of continuation per +1: -0.0030 [-0.0119, 0.0075] (n=676)

|z total| x Hold(total)

| bucket | events | matches | expected-total continuation (goals) | events with same-line Over/Under CLV | Over/Under CLV (%) |
|---|---|---|---|---|---|
| 0-1 | 500 | 51 | -0.0030 [-0.0110, 0.0056] | 292 | -2.49 [-3.02, -1.92] |
| 1-2 | 109 | 31 | 0.0041 [-0.0241, 0.0328] | 97 | -2.80 [-4.19, -1.48] |
| 2-3 | 38 | 21 | 0.0085 [-0.0451, 0.0571] | 29 | -2.40 [-5.42, 0.08] (too few) |
| 3-4 | 22 | 12 | -0.0184 [-0.0584, 0.0265] (too few) | 16 | -3.27 [-4.88, -1.17] (too few) |
| 4+ | 7 | 5 | -0.0580 [-0.1105, 0.0303] (too few) | 3 | -3.68 [-5.85, -2.19] (too few) |

Slope of continuation per +1: -0.0028 [-0.0127, 0.0093] (n=676)

_Run took 10s; bootstrap 2000 resamples of whole matches, seed 20260101._
