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
| "Steam" via the existing ratio-based classifier (`velocity_shape`, recent-vs-total change ratio) | 41.7% (n=48) - statistically indistinguishable from drift (41.2%), building (41.4%), and the 40.0% baseline | Rejected at full scale (an earlier 70-100% reading was from 2-5 decisive matches per label - noise) |
| "Steam" via rolling Z-score anomaly detection (own price vs its recent rolling mean/stdev, floored to avoid division-by-near-zero) | 34-37% accuracy across every threshold tried (1.5 to 4.0) - below the 40% baseline at every single threshold | Rejected |
| **Pinnacle's opening AH line favorite** (the very first line posted, before any money/movement) | 45.7% overall (n=70, vs 38.6% baseline) - **68.1% (n=47) once draws are set aside** - and climbs with the size of the opening handicap (50% at n=18, 80% at n=5) | **Most promising single lead so far - see section 6** |

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

## 4. Does Pinnacle move only when sharp money hits their lines?

**No - not exclusively.** This is worth separating into two different
mechanisms that get lumped together as "the market moving":

- **Lines do need real action to move, but that action isn't reliably
  "sharp."** The mechanical link is real (see the probability-pressure
  finding above, 74.8-86.5%) - something real is pushing lines, not
  randomness. But if that something were genuinely sharp (informed, right
  more often than wrong), the direction of that pressure should predict
  the match result clearly better than a coin flip. It doesn't - every
  "follow the money" signal tested landed around 50-54%. The money moving
  these lines is a mix of things - some informed, a lot of ordinary larger
  recreational bets, team news settling in, general consensus forming -
  not something that earns the label "sharp" just because it moved the
  price.
- **Limits are a different mechanism, and there's direct evidence they
  mostly aren't money-triggered at all.** Only 24.3% of limit increases
  happened alongside any real probability movement (see section 2). The
  rest look scheduled - clustered overwhelmingly close to kickoff, moving
  through the same fixed round-number tiers match after match. That's
  what a routine operational ramp-up looks like, not a sharp-money
  detector - directly contradicting the idea (proposed in the external
  research document that prompted this check) that a rising limit
  specifically signals detected sharp participation.
- **A large share of matches get no action at all.** 42 of 115 (about
  37%) never saw their line move once all week. If sharp money reliably
  sought out and corrected every mismatched line, far fewer matches
  should look like this.

**Bottom line:** Pinnacle's lines move in response to real betting
activity, but that activity isn't distinctly "sharp" by any measure
tested here, and a large share of what looks like "market movement" -
especially limit changes - is closer to scheduled housekeeping than a
reaction to informed money. The founding theory of this whole project
("sharp money moves the line, so tracking line moves tracks sharp
money") turns out to be only partly true: the moving part is real, the
sharp part isn't supported by the data.

## 5. Single-book "steam" detection - tried three ways, closed as a dead end

Without a second bookmaker to confirm cross-book contagion (the usual way
"steam" gets validated - multiple books reacting in sync), the remaining
option was to try to extract steam purely from Pinnacle's own price
velocity. Three independent mathematical approaches were tried on the
full 115-match dataset, and all three converged on the same answer:

1. **CUSUM change-detection** (tried earlier in this project) - underperformed
   baseline on real data.
2. **Ratio-based steam/drift/building classifier** - already built into
   `velocity_shape()`, never fully re-tested until now. 41.7% accuracy for
   "steam," statistically identical to every other label and to the 40%
   baseline.
3. **Rolling Z-score anomaly detection** (the PDF's proposed method) - after
   fixing a real bug in the first pass (a flat/quiet stretch could drive
   the rolling standard deviation toward zero and blow up a meaningless
   tiny move into a fake 286-sigma "anomaly"; fixed with a floor on the
   standard deviation matching the project's existing 0.30pp noise floor),
   the corrected version still scored 34-37% across every threshold tried
   - *below* the baseline every time, not just even with it.

**Conclusion: three different, independent methods for finding "steam" in
Pinnacle's own data, with no second book to confirm it, all failed the
same way.** That's a pattern, not a coincidence. Single-book steam
detection is not a productive direction with the data and tools available
right now - closing this line of investigation rather than trying further
variants of the same underlying idea.

## 6. Pinnacle's opening AH line as a standalone predictor - the most promising lead so far

Every other signal in this document is about reacting to the market -
how it moved, how fast, how confident it looked. This one is different:
it only uses Pinnacle's very *first* line on a match, before a single bet
has landed anywhere. On all 115 matches:

- **39% of matches (45/115) open with no favorite at all** - a flat
  0.00 line. That's a real fact about how tight most of these jackpot
  matches look from the very start, before any action.
- **Of the 70 matches that do open with a real favorite, that favorite
  actually won 45.7% of the time** (vs a 38.6% baseline of always
  picking home on the same matches) - a real ~7-point edge.
- **Setting the draws aside (23 of those 70, the usual unavoidable
  cost), the opening favorite was right 68.1% of the time (32/47)** -
  a genuinely strong number for the simplest possible read: nothing but
  Pinnacle's own first guess.
- **It gets stronger with a bigger opening handicap**: 45.7% at any
  nonzero line, 50.0% at ±0.5 or more (n=18), 80.0% at ±1.0 or more
  (n=5 - too few to trust that last number specifically, but the
  direction is consistent at every step).

**Why this is the most promising lead in this whole investigation:**
everything else tested here tried to extract information from how the
market *reacted*, and none of it held up - the market's reaction turned
out to be close to a coin flip against the real result (see sections 2-5).
This is the first finding that bypasses that entirely and instead checks
whether Pinnacle's own initial judgment - built from their own models and
information before the public ever gets a chance to weigh in - is any
good on its own. The honest, tested answer here is: yes, more than
anything else tried, once draws are set aside.

**Caveats, stated plainly:** draws remain exactly as unpredictable as
everywhere else in this document - this is a signal for the non-draw
cases only. The bigger-handicap buckets (n=18, n=5) are too thin yet to
pin down a specific cutoff with confidence. And this has only been
checked on 115 matches across five rounds - worth re-confirming as more
data comes in, the same discipline applied to everything else here.

## 7. The AH fair probability barely moves regardless of the line's size

Checked every match's final AH reading (one per match, n=115), grouped by
the exact line value, to see what fair probability actually shows up at
each one:

| Line | n | Probability range | Median |
|---|---|---|---|
| -1.50 (home favored by 1.5) | 1 | 48.0% | 48.0% |
| -1.00 | 4 | 47.3-51.8% | 49.3% |
| -0.50 | 9 | 46.0-53.2% | 48.2% |
| -0.25 | 36 | 44.6-53.3% | 48.6% |
| 0.00 | 38 | 45.0-53.8% | 49.0% |
| +0.25 | 19 | 46.8-54.8% | 52.2% |
| +0.50 | 6 | 50.0-54.7% | 52.9% |

**The probability barely moves from 50% no matter how big the line is.**
Even at -1.50 (a full goal and a half of head start given to the away
side), the probability of actually covering that number is still only
48%. This isn't a data quirk - it's exactly how an Asian Handicap is
supposed to work: the *point value* captures how much stronger one team
is; the line itself gets adjusted specifically to keep the probability of
covering it close to a coin flip, no matter how lopsided the real teams
are. A bigger quality gap shows up as a bigger point spread, not as a
probability far from 50%.

**One small, consistent, directional pattern:** home-favored lines
cluster a touch below 50% (47-49%), home-underdog lines cluster a touch
above it (51-53%). Best honest explanation: lines only come in
quarter-point steps, so the true fair number often sits between two
postable lines, and whichever one actually gets posted will be slightly
off from a perfect 50/50 in a consistent direction - plausible, not
proven.

**Why this matters for everything else in this document:** it explains,
structurally, why the AH fair probability was never going to measure "how
big a favorite" a team is (see section 1's correlation finding - the same
0.25pt move corresponds to anywhere from 0.47pp to 9.73pp of probability
change). The probability has almost no room to move regardless of the
line, by design - any real conviction in the market has to squeeze out
through a very narrow channel around 50%, which is part of why so many
of the probability-based signals in this document struggled to find
real separation.

## 8. Synthesis: the opening line is the signal, movement is risk management

Pulling sections 4, 6 and 7 together into one statement, since it's the
clearest conclusion this investigation has produced:

**The opening Asian Handicap line - the point value Pinnacle posts before
any money has landed - is where the real favorite/underdog signal lives.
Line movement after that is primarily about balancing the book, not about
revealing a truer favorite.**

Two independent findings support the first half:
- The opening line's favorite actually won 68.1% of non-draw matches
  (n=47), strengthening with the size of the handicap (section 6).
- The AH fair probability barely moves from 50% regardless of how big the
  line is (section 7) - confirmation that the *point value*, not the
  probability, is what encodes the quality gap between the teams.

And the second half is supported by everything in section 4: every
attempt to read the *direction* a line moved as a signal of who'd
actually win landed close to a coin flip, while real money was
confirmed to reliably drive those moves (probability pressure precedes
and matches the next line step 75-86% of the time) and most limit
increases turned out to be scheduled housekeeping rather than reactions
to specific sharp action.

**Two caveats that keep this honest, not overstated:**
- "No risk" is slightly too strong - final settlement lands close to
  balanced (46.7% / 53.3%) but not perfectly 50/50, and Pinnacle's actual
  edge is the vig either way.
- Movement isn't completely uninformative - lines nobody ever challenges
  settle noticeably less evenly than lines that do move (18 points off
  fair vs 4, section 2). Money moving the line does seem to genuinely
  improve how well-calibrated the number ends up - we just haven't found
  a way to read *which direction* it moved and turn that into a reliable
  pick for who wins.
- None of this touches draws. The opening line can tell you who the
  better side is; it says nothing about the ~27% of matches that end
  level, which remains unpredictable from every angle tried in this
  document.

## 9. Converting AH line size into a real win probability, via the 1X2 market

Section 7 showed the AH probability can't tell you how strong a favorite
is - it stays pinned near 50% regardless of line size, by design. The
1X2 market doesn't have that constraint, so pairing the two gives an
actual, usable conversion: AH line size (who, and roughly how much) to
1X2 probability (how much, as a real number), both read at the opening,
before any money has landed, across all 115 matches:

| Opening AH line | n | 1X2 favorite win-probability (median) |
|---|---|---|
| Pick'em (0.00) | 45 | 37.9% |
| 0.25pt | 52 | 42.0% |
| 0.50pt | 11 | 48.1% |
| 0.75pt | 2 | 59.9% |
| 1.00pt | 4 | 62.8% |
| 1.50pt | 1 | 71.1% |

This is a clean, sensible, monotonically increasing relationship - every
step up in the AH line corresponds to a real step up in actual win
probability. The two markets are coherent with each other: the AH line
gives the ordinal ranking (bigger number = stronger favorite), the 1X2
probability gives the cardinal number for how much stronger.

Checking the reverse direction - does a stronger 1X2 reading for the AH
favorite make that favorite's win more reliable - shows the same clean
trend, now from a second, independent angle on top of section 6's
handicap-size finding:

| 1X2 favorite probability | n | Favorite actually won |
|---|---|---|
| >=45% | 23 | 52.2% |
| >=50% | 10 | 50.0% |
| >=55% | 7 | 71.4% |
| >=60% | 5 | 80.0% |
| >=65% | 1 | 100.0% |

**Caveat, same as everywhere else in this document:** the samples thin
out fast past the >=50% row (7, 5, then just 1 match) - trust the
*direction* (stronger favorite, more reliable pick) far more than any
specific number beyond that point.

**Practical takeaway:** favorite strength can be estimated properly by
combining the two markets - use the AH opening line to identify *who* is
favored, and the opening 1X2 probability (not the AH probability) to
estimate *how much*, using the table above as a rough conversion.

## 10. A real 1X2 lead change is a sign the opening line missed something

Section 8 concluded the opening line carries the real signal and
movement is mostly risk management. This finding refines that: when the
1X2 market's own favorite actually *flips* - not just drifts, but the
underdog's probability genuinely overtakes the original favorite's by
the final reading - that reversal itself looks like a real signal, not
noise.

Across all 115 matches, 20 saw this kind of lead change (home-vs-away
only, same framing as the AH favorite/underdog work):

| | n=20 |
|---|---|
| Original favorite still won | 7 (35.0%) |
| New leader (the original underdog) won | 9 (45.0%) |
| Draw | 4 (20.0%) |
| **New leader won OR draw** | **65.0%** |

Compare that to the 95 matches where the lead never changed: the opening
favorite won 48.4% of those. So a genuine lead change drops the original
favorite's win rate from 48.4% down to 35.0% - a real gap, not a rounding
error. And it strengthens with the size of the reversal:

| Final gap size | n | Original favorite still won |
|---|---|---|
| Any flip | 20 | 35.0% |
| >=2pp | 18 | 38.9% |
| >=5pp | 9 | 22.2% (new leader or draw: 77.8%) |

**Caveat:** 20 matches total, down to 9 at the clearer >=5pp cutoff - real
enough to track, not yet large enough to build a hard rule on. But the
pattern is monotonic (gets stronger exactly where you'd expect), which is
the kind of thing that's held up elsewhere in this document.

**Refined practical takeaway:** trust the opening line's favorite by
default (section 9's conversion table), *unless* the 1X2 market later
shows a clear, sizeable reversal against it - in which case the reversal
itself is informative, and leaning toward the new leader (or expecting a
draw) looks better supported than sticking with the original favorite.

## 11. Both sides force line adjustments - each exactly when their own probability is rising

Classified every real AH line-move event (n=109, relative to each
match's opening favorite) as either **widening** (the move makes the
opening favorite even more favored) or **narrowing** (the move pulls the
line back toward the underdog):

| Move type | n | % |
|---|---|---|
| Widening - favorite backed further | 51 | 46.8% |
| Narrowing - underdog pulling it back | 58 | 53.2% |

Close to even, with narrowing slightly more common - Pinnacle corrects
back toward the underdog a bit more often than it extends the favorite's
edge, but neither direction dominates.

**The important part - whose probability was rising right before each
type of move:**

| Move type | n | Whose probability was rising beforehand |
|---|---|---|
| Widening | 38 | The favorite's own probability, 78.9% of the time |
| Narrowing | 38 | The underdog's own probability, 81.6% of the time |

**Both sides force adjustments, roughly equally often, and each time it's
exactly the side you'd expect doing the forcing.** When the favorite gets
backed further, the favorite's own probability was climbing beforehand -
more money piling onto the already-strong side. When the line pulls back
toward the underdog, the underdog's own probability was climbing
beforehand - money found value on the weaker side. This is a clean,
mechanistic confirmation of the balancing picture from sections 4 and 8,
now decomposed by which side is doing the forcing at each individual
move, not just confirmed in aggregate.

## 12. Open threads, if more data or time becomes available

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
