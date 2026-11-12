# Steam backtest

Tests whether a "steam" signal (a fast move confirmed in more than one market that does not bounce back)
predicts where the line goes next. Separate from the tool: it reads the exported snapshot CSVs
(read-only), imports only `app.odds` (the tool's own de-vig and margin maths), and changes nothing in `app/`.

```
python -m backtest.run --data /path/to/folder/with/csv/exports --out backtest/results
python -m pytest tests/test_backtest.py
```

Standard library only. Outputs: `results/events_test.csv` (every candidate event in the test period, with
features and outcomes) and `results/tables.md` (all tables). The written verdicts are in `REPORT.md`.

| file | what it does |
|---|---|
| `config.py` | every rule and threshold, fixed before looking at results |
| `data.py` | loads and aligns 1X2 / AH / total snapshots; recomputes fair probabilities with `app.odds` |
| `poisson.py` | fits home/away goal rates to the fair AH and over probabilities (quarter lines, pushes) |
| `features.py` | typical-move calibration, z, Agree, Hold, steam score, margin features, outcomes |
| `stats.py` | bootstrap that resamples whole matches |
| `run.py` | split, tables, CSV |

To rerun with more data: drop new exports in the data folder and run again. The split is recomputed (earliest 70% of
matches by kickoff calibrate, latest 30% are reported). Windows and hold horizons shorter than the data's
collection interval are skipped automatically; with finer-grained snapshots the 5-minute window and 10-minute
hold switch on by themselves.

Rules that matter (see `config.py`):
- The flag time is the end of the hold period (first snapshot 15-30 min after the move). All outcomes start there.
- Typical move sizes come only from the calibration matches (by league tier, window, hours to kickoff; pooled when a cell has fewer than 150 changes; floor 20% of the pooled std).
- Hold = the smaller of the 1X2 and supremacy shares still standing at the hold snapshot, each clipped to 0-1.
- "Full" score = steam x (1 if the 1X2 margin share moved onto the side that moved, else 0).
- A table cell with fewer than 30 events or 10 matches is marked "too few".
