## Early vs late steam (175 matches, 252 steaming sides, 155 matches with steam)

Late = the side's biggest steam swing finished within 3 h of kickoff (dashboard rule). Edge = won minus the closing fair probability of that side.

### 1. Sides by the timing of their biggest swing (the label on the dashboard)

| group | sides | matches | won | expected from closing price | edge, pp [95% CI] |
|---|---|---|---|---|---|
| early | 140 | 102 | 39.3% | 36.1% | +3.2 [-3.6, +9.8] |
| late | 112 | 88 | 31.2% | 35.6% | -4.3 [-11.5, +3.1] |
| all steaming sides | 252 | 155 | 35.7% | 35.9% | -0.1 [-4.3, +3.9] |

**early minus late edge: +7.5 pp [-3.9, +18.6]**; raw win rate 39.3% vs 31.2%

What the two groups look like (so the comparison is read fairly):

| | early | late |
|---|---|---|
| median biggest swing (pp) | 2.01 | 2.17 |
| mean closing prob of the side | 36.1% | 35.6% |
| share that are home | 40% | 29% |
| share that are draw | 20% | 33% |
| share that are away | 40% | 38% |

### 2. Sides by which periods they had steam in

| group | sides | matches | won | expected from closing price | edge, pp [95% CI] |
|---|---|---|---|---|---|
| early steam only | 124 | 92 | 36.3% | 35.6% | +0.7 [-6.7, +7.8] |
| late steam only | 87 | 70 | 34.5% | 35.1% | -0.6 [-8.8, +8.1] |
| early AND late steam | 41 | 37 | 36.6% | 38.3% | -1.8 [-14.2, +10.7] |

- early only minus late only: +1.3 pp [-11.7, +13.4]

- both minus late only: -1.2 pp [-16.9, +13.9]

- both minus early only: -2.4 pp [-17.3, +12.4]

### 3. Each match's top-ranked steam side, by timing

| group | sides | matches | won | expected from closing price | edge, pp [95% CI] |
|---|---|---|---|---|---|
| top side, early | 81 | 81 | 42.0% | 39.8% | +2.1 [-8.4, +12.0] |
| top side, late | 74 | 74 | 36.5% | 38.1% | -1.6 [-11.8, +9.0] |

early minus late (top side): +3.7 pp [-10.7, +18.0]

### 4. Bigger swings only (2 pp or more)

| group | sides | matches | won | expected from closing price | edge, pp [95% CI] |
|---|---|---|---|---|---|
| early >= 2pp | 70 | 62 | 48.6% | 40.8% | +7.8 [-3.0, +17.9] |
| late >= 2pp | 59 | 52 | 32.2% | 36.3% | -4.1 [-15.3, +7.0] |

early minus late (>= 2pp): +11.9 pp [-4.3, +27.3]

### 5. Same match, early side vs late side (paired inside matches that have both)

| group | sides | matches | won | expected from closing price | edge, pp [95% CI] |
|---|---|---|---|---|---|
| early sides (35 matches) | 42 | 35 | 47.6% | 34.3% | +13.3 [-0.4, +28.0] |
| late sides (same matches) | 40 | 35 | 22.5% | 34.6% | -12.1 [-23.4, -0.1] |

early minus late within those matches: +25.4 pp [+1.1, +49.5]

### 6. No cutoff: hours before kickoff of the biggest swing vs the edge

Spearman correlation (more hours before kickoff = earlier) with edge: +0.044 [-0.095, +0.168] over 252 sides

Sensitivity to where 'late' starts (not a tuned choice; the dashboard uses 3 h):

| late = within | early sides | late sides | early minus late edge, pp [95% CI] |
|---|---|---|---|
| 1 h | 160 | 92 | +7.2 [-4.6, +18.7] |
| 2 h | 146 | 106 | +5.1 [-6.2, +16.2] |
| 3 h | 140 | 112 | +7.5 [-3.9, +18.6] |
| 6 h | 118 | 134 | +5.6 [-5.1, +16.1] |
| 12 h | 69 | 183 | +11.1 [-2.6, +24.4] |

### 7. Checks on the within-match result (section 5)

- Shuffling the early/late labels among the steaming sides of each of those 35 matches: observed +25.4 pp, permutation p = 0.035
- Same comparison with draw sides removed (late steam is more often on the draw): early 34 vs late 21 sides, +28.3 pp [+0.1, +56.1]
- Early vs late in all OTHER matches (no early/late pair): 98 vs 72 sides, -1.1 pp [-13.0, +10.2]
- Comparisons reported above: about 20, so one or two intervals that just exclude zero are expected by chance alone.
