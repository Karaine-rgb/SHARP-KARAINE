"""Checks on the steam backtest's maths and its no-lookahead rules (synthetic data only)."""
import copy
import random

import pytest

from backtest import config as C
from backtest import features, poisson
from backtest.data import Match, Snap


def test_poisson_fit_is_consistent_across_lines_and_pushes():
    lh, la = 1.6, 1.1
    for line in (-1.0, -0.75, -0.5, -0.25, 0.0, 0.25):
        for total in (2.25, 2.5, 2.75, 3.0):
            r = poisson.fit(line, poisson.home_cover_prob(lh, la, line), total, poisson.over_prob(lh + la, total))
            assert r["ok"]
            assert r["lh"] == pytest.approx(lh, abs=1e-6)
            assert r["la"] == pytest.approx(la, abs=1e-6)
            assert r["supremacy"] == pytest.approx(0.5, abs=1e-6) and r["total"] == pytest.approx(2.7, abs=1e-6)


def test_integer_line_probability_excludes_the_push():
    # level goals (line 0): P(win | no push) for home equals P(home win)/(P(home win)+P(away win))
    lh, la = 1.5, 1.0
    p = poisson.home_cover_prob(lh, la, 0.0)
    ph = poisson._pmf(lh, 40); pa = poisson._pmf(la, 40)
    hw = sum(ph[i] * pa[j] for i in range(41) for j in range(41) if i > j)
    aw = sum(ph[i] * pa[j] for i in range(41) for j in range(41) if i < j)
    assert p == pytest.approx(hw / (hw + aw), abs=1e-9)


def _match(seed=1, n=40, step_min=15, kickoff=10 * 3600.0, tier=1):
    rnd = random.Random(seed)
    snaps = []
    ph, pa_, po = 0.45, 0.50, 0.50
    for i in range(n):
        ph = min(max(ph + rnd.gauss(0, 0.01), 0.2), 0.7)
        pa_ = min(max(pa_ + rnd.gauss(0, 0.01), 0.3), 0.7)
        po = min(max(po + rnd.gauss(0, 0.01), 0.3), 0.7)
        t = kickoff - (n - 1 - i) * step_min * 60.0 - 60.0
        draw = 0.27
        fair = (ph, draw, 1 - ph - draw)
        ml = tuple(1.0 / (p * 0.97) for p in fair)
        margin = {"margin_total_pct": 3.0, "margin_home_share_pct": 33.0 + i % 3, "margin_draw_share_pct": 33.0, "margin_away_share_pct": 33.0}
        snaps.append(Snap(t=t, ml=ml, fair=fair, margin=margin, ah_line=-0.25, ah=(1.9, 1.9), ah_fair_home=pa_,
                          tot_line=2.5, tot=(1.9, 1.9), tot_fair_over=po))
    return Match("m%d" % seed, kickoff, "England - Premier League", tier, "r", snaps)


def _typ(matches, windows=(15, 60)):
    return features.Typical([features.build_series(m) for m in matches], windows)


def test_no_lookahead_features_do_not_change_when_later_data_is_removed():
    cal = [_match(s, kickoff=1e6 + s * 1e5) for s in range(2, 8)]
    typ = _typ(cal)
    m = _match(99)
    full = features.candidate_events(features.build_series(m), typ, (15, 60), (15,))
    assert full
    old = C.USABLE_CLOSE_MAX_MIN
    C.USABLE_CLOSE_MAX_MIN = 1e9
    try:
        for e in full[::5]:
            k = next(i for i, s in enumerate(m.snaps) if s.t == e["flag_t"])
            cut = copy.copy(m)
            cut.snaps = m.snaps[: k + 2]                      # flag snapshot plus one later "close"
            ev = features.candidate_events(features.build_series(cut), typ, (15, 60), (15,))
            same = [x for x in ev if x["t0"] == e["t0"]]
            assert same, "event disappeared when only later data was removed"
            for key in ("z_L", "z_S", "z_T", "agree", "hold", "steam", "margin_onside"):
                assert same[0][key] == pytest.approx(e[key]), key
    finally:
        C.USABLE_CLOSE_MAX_MIN = old


def test_flag_time_is_end_of_hold_period_and_outcomes_start_there():
    cal = [_match(s, kickoff=1e6 + s * 1e5) for s in range(2, 6)]
    typ = _typ(cal)
    m = _match(50)
    for e in features.candidate_events(features.build_series(m), typ, (15, 60), (15,)):
        assert e["flag_t"] >= e["t0"] + 15 * 60 - 1e-6
        assert e["flag_t"] < m.snaps[-1].t
        k = next(i for i, s in enumerate(m.snaps) if s.t == e["flag_t"])
        assert e["clv_mover"] == pytest.approx(m.snaps[k].ml[features.SIDES.index(e["mover"])] * m.snaps[-1].fair[features.SIDES.index(e["mover"])] - 1)


def test_typical_move_uses_only_the_matches_it_is_given():
    cal = [_match(s, kickoff=1e6 + s * 1e5) for s in range(2, 6)]
    t1 = _typ(cal)
    later = [_match(s, kickoff=9e6 + s * 1e5) for s in range(20, 24)]
    t2 = features.Typical([features.build_series(m) for m in cal], (15, 60))
    ms = features.build_series(later[0])
    assert t1.sd("L", 15, 1, 2.0) == t2.sd("L", 15, 1, 2.0)


def test_window_too_coarse_for_the_data_is_skipped():
    coarse = features.build_series(_match(7, step_min=45))   # snapshots 45 min apart
    assert features.window_index(coarse, 10, 15) is None     # 45 min back is more than 2 x 15 min
    assert features.hold_index(coarse, 10, 10) is None       # next snapshot is 45 min on, past 2 x 10 min
    assert features.window_index(coarse, 10, 60) is not None  # a 60-minute window is measurable (45 <= 120)
    fine = features.build_series(_match(7, step_min=15))
    assert features.window_index(fine, 10, 15) is not None
    assert features.hold_index(fine, 10, 15) is not None


def test_hold_is_clipped_between_zero_and_one():
    m = _match(3)
    # force a clean jump at snapshot 20, then a reversal beyond the start
    for i in range(20, 40):
        m.snaps[i].fair = (0.60, 0.22, 0.18)
    for i in range(0, 20):
        m.snaps[i].fair = (0.40, 0.27, 0.33)
    for i in (21, 22):
        m.snaps[i].fair = (0.30, 0.30, 0.40)                  # bounces below the start
    cal = [_match(s, kickoff=1e6 + s * 1e5) for s in range(2, 6)]
    typ = _typ(cal)
    ev = features.candidate_events(features.build_series(m), typ, (15,), (15,))
    for e in ev:
        assert 0.0 <= e["hold_L"] <= 1.0 and 0.0 <= e["hold"] <= 1.0
