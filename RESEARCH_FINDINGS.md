# Research Findings: How Pinnacle's Market Actually Behaves

This document consolidates everything learned from backtesting real Sharp
Karaine data (98-115 real Megajackpot matches across five tracked rounds)
against the question: **can pre-match Pinnacle odds data predict who wins?**

The honest answer, after dozens of tests: **not reliably, on this data, at
this scale.** But the same testing built a solid, repeatable picture of
*how the market itself behaves*, which is documented below because it's
real and useful even though it isn't a prediction engine.

Every number below came from backtesting against real collected data and
real match results - none of it is theoretical. Sample sizes are stated
throughout; treat anything on fewer than ~30 matches as suggestive, not
proven.

## 1. Signals tested for predicting match outcomes - results

| Idea | Result | Verdict |
|---|---|---|
| AH line-shift direction (line moved >=0.25pt) | ~50-53% on careful re-test (an earlier claim of 64.5% could not be reproduced and should be treated as unconfirmed) | Not validated |
| AH flat-line probability drift (line never moved) | ~54.5% (n=44), modest edge over baseline | Weak, real but small |
| CUSUM change-detection | Underperformed baseline on real data | Rejected |
| Horizon reads (48h/72h "who's ahead") | Looked promising, shown to be an opening-favorite artifact | Rejected |
| "Whichever probability is gaining" as a universal signal | 31.6% overall - worse than baseline; actively backwards on moved lines (27.5%) because it compares probability of covering two *different* lines | Rejected |
| Raw match-by-match "hit side" read (no thresholds) | 40.8% - noise-dominated | Rejected |
| First line move's direction | 46.6% - tied exactly with "always pick home" | Rejected |
| Closing Line Value (does the market keep agreeing with the pick) | No relationship to actual correctness (avg CLV nearly identical for right vs wrong picks) | Rejected |
| Draw prediction via 1X2 draw probability | No separation between draws and non-draws (28.2% vs 28.9% avg) | Rejected |
| Draw prediction via AH handicap size | No clean separation, direction inconsistent | Rejected |
| Draw prediction via total-goals line | No clean separation | Rejected |
| Draw prediction via 1X2 home/away gap | No clean separation | Rejected |
| "Banker" rule (strong 1X2 favorite + low draw risk) | 83.3% but only n=6 matches | Promising, unproven - too small to trust |
| Deployed tool's own confidence score (`total_score`) | Wrong picks averaged a *higher* score (8.0) than right picks (7.35) | Miscalibrated |
| Betslip generator (primary pick + draw-cover) | Barely beat "just cover every match with the draw" (68.4% vs 69.4%) | Not worth the complexity as built |

## 2. What we know for certain about the market's mechanics

These held up on real data and are worth trusting more than anything in
the table above:

- **About 54% of matches end up "contested"** (the tool's own early-vs-late
  direction disagreement flag) - confirmed independently on two separate
  data batches (98 matches, then 115). The market changes its mind on
  roughly half of all matches.
- **Final Asian Handicap settlement is close to a fair coin flip**: across
  75 decisive matches, favorites covered 46.7% of the time, underdogs
  53.3% - close to 50/50, consistent with Pinnacle successfully balancing
  its book by kickoff.
- **Lines that never move settle less evenly than lines that do.**
  Moved lines: 54.0% favorite-cover rate (4.0pp from fair). Never-moved
  lines: 32.0% favorite-cover rate (18.0pp from fair), n=25. This supports
  the theory that a line only gets corrected once real action challenges
  it - an uncontested opening guess can sit there mis-calibrated.
  (Caveat: picking the *underdog* on these specific matches to win the
  real match outright did NOT work - 23.1% vs 34.6% for the favorite - so
  this is a fact about handicap settlement, not a usable win-picking rule.)
- **Probability pressure reliably precedes and matches the direction of
  the next line move.** Across 135 real line-change events: 74.8% of the
  time the probability trend right before a move matches the direction
  the line then steps - rising to 86.5% when the move was 2+ percentage
  points. This confirms the basic mechanism (money moves probability,
  probability pressure forces a line redraw) is real and coherent.
- **The first time a line moves is not specially informative.** Its
  direction never reverses net direction by the end of the week (in the
  43 matches with a clear final line, first-move direction and final
  direction always agreed) - but picking winners off it scored exactly
  the same as blindly picking home every time (46.6%).
- **Draws cannot be predicted in advance from any pre-match signal tried**
  (four independent attempts, all negative). Pre-match pricing of draws
  sits in a narrow band regardless of how the rest of the match looks.
- **Pinnacle's market limits behave mostly on a schedule, not as a sharp-
  money detector.** Across 115 matches: limits grew ~8.7x on average from
  opening to final; they move through a small set of fixed, round-number
  tiers (e.g. $300/$500/$900/$1,200/$2,000/$3,000/.../$20,000) rather
  than continuously; only 24.3% of limit increases (571 events checked)
  coincided with a meaningful probability move at that same moment; and
  limit jumps cluster heavily near kickoff (32% in the final 2 hours,
  over 75% within 24 hours). Temporary mid-week limit *drops* do happen
  (8 found) but always get overridden by later rises - no match ever
  ended the week with a lower limit than it opened with.
- **Thin/niche leagues are quieter, not noisier**, than bigger leagues -
  the opposite of the naive assumption that a small market would show
  more erratic relative movement.

## 3. The central honest conclusion

Pinnacle's final prices, by the time we read them, are close to efficient.
Every angle we tried to find leverage against that price - the direction
money moved, how early it moved, how the market's own confidence score
behaved, whether the price kept agreeing with a pick after the fact -
came back close to a coin flip. That's not a failure of testing; it's a
real, repeatedly-confirmed answer about this specific market at this
scale of data (currently ~115 real matches across 5 rounds).

## 4. Open threads, if more data or time becomes available

- Re-test the "never-moved lines draw more" observation (currently
  33.3% vs 23.3%, a real-looking gap that doesn't yet clear the usual
  statistical significance bar) as more rounds come in.
- Re-test the "banker" rule (strong favorite + low draw risk) once there
  are enough matches in that bucket to trust a specific cutoff.
- A genuinely different data source (team-level historical results, for
  a Dixon-Coles-style model) would be a real new direction, but requires
  building a new data collection pipeline, not just re-analyzing what's
  already collected.
- A "flag murky matches for manual review" tool (using the reliable ~54%
  contested rate and the never-moved-line pattern) is a realistic, honest
  product to build from what we actually know - a risk-management aid
  rather than a win-picker.

*Last updated from a backtesting session covering 115 real Megajackpot
matches across September and October 2026 rounds.*
