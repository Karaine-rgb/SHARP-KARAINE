from datetime import datetime, timedelta, timezone

import pytest

from app.signals import (
    CONFIG,
    ah_line_shift,
    classify_tier,
    compute_match_score,
    data_sufficiency,
    detect_contested,
    limit_drop_pct,
    x2_displacement,
)

KICKOFF = datetime(2026, 9, 6, 15, 0, tzinfo=timezone.utc)


def t(hours_before_kickoff):
    return KICKOFF - timedelta(hours=hours_before_kickoff)


def ml_point(hours_before, fh, fd, fa, limit=2500.0, status="open"):
    return {
        "captured_at": t(hours_before),
        "fair_home_prob": fh,
        "fair_draw_prob": fd,
        "fair_away_prob": fa,
        "limit_amount": limit,
        "status": status,
    }


def sp_point(hours_before, points, limit=5000.0, status="open"):
    return {
        "captured_at": t(hours_before),
        "home_points": points,
        "limit_amount": limit,
        "status": status,
    }


# ---------------------------------------------------------------------------
# ah_line_shift
# ---------------------------------------------------------------------------

def test_ah_line_shift_home_backed():
    series = [sp_point(48, -0.25), sp_point(1, -1.25)]
    result = ah_line_shift(series)
    assert result["shift"] == -1.0
    assert result["direction"] == "home"
    assert result["magnitude"] == 1.0


def test_ah_line_shift_away_backed():
    series = [sp_point(48, -0.5), sp_point(1, 0.25)]
    result = ah_line_shift(series)
    assert result["direction"] == "away"


def test_ah_line_shift_below_threshold_no_direction():
    series = [sp_point(48, -0.5), sp_point(1, -0.6)]
    result = ah_line_shift(series)
    assert result["direction"] is None


def test_ah_line_shift_insufficient_data():
    result = ah_line_shift([])
    assert result["direction"] is None
    assert result["magnitude"] == 0.0


# ---------------------------------------------------------------------------
# x2_displacement
# ---------------------------------------------------------------------------

def test_x2_displacement_home_backed():
    series = [
        ml_point(48, 0.40, 0.28, 0.32),
        ml_point(1, 0.42, 0.27, 0.31),
    ]
    result = x2_displacement(series)
    assert result["home_pp"] == pytest.approx(2.0, abs=0.05)
    assert result["direction"] == "home"


def test_x2_displacement_noise_floor():
    series = [
        ml_point(48, 0.40, 0.30, 0.30),
        ml_point(1, 0.4015, 0.2995, 0.2990),
    ]
    result = x2_displacement(series)
    assert result["direction"] is None


# ---------------------------------------------------------------------------
# limit_drop_pct
# ---------------------------------------------------------------------------

def test_limit_drop_pct_severe():
    series = [sp_point(48, -0.5, limit=5000.0), sp_point(1, -1.0, limit=2000.0)]
    assert limit_drop_pct(series) == 60.0


def test_limit_drop_pct_no_drop_floors_at_zero():
    series = [sp_point(48, -0.5, limit=2000.0), sp_point(1, -0.5, limit=5000.0)]
    assert limit_drop_pct(series) == 0.0


# ---------------------------------------------------------------------------
# contested detection
# ---------------------------------------------------------------------------

def test_detect_contested_true_on_direction_flip():
    series = [
        ml_point(60, 0.40, 0.30, 0.30),
        ml_point(50, 0.44, 0.28, 0.28),  # early: home backed
        ml_point(10, 0.44, 0.28, 0.28),
        ml_point(1, 0.38, 0.30, 0.32),  # late: away backed
    ]
    assert detect_contested(series, KICKOFF) is True


def test_detect_contested_false_when_consistent():
    series = [
        ml_point(60, 0.40, 0.30, 0.30),
        ml_point(50, 0.44, 0.28, 0.28),
        ml_point(10, 0.46, 0.27, 0.27),
        ml_point(1, 0.48, 0.26, 0.26),
    ]
    assert detect_contested(series, KICKOFF) is False


def test_detect_contested_false_without_enough_history_each_side():
    series = [ml_point(50, 0.44, 0.28, 0.28), ml_point(1, 0.38, 0.30, 0.32)]
    assert detect_contested(series, KICKOFF) is False


# ---------------------------------------------------------------------------
# tiers
# ---------------------------------------------------------------------------

def test_classify_tier_boundaries():
    assert classify_tier(0.0) == "no_signal"
    assert classify_tier(1.9) == "no_signal"
    assert classify_tier(2.0) == "watch"
    assert classify_tier(4.5) == "sharp"
    assert classify_tier(7.0) == "strong_sharp"
    assert classify_tier(999) == "strong_sharp"  # capped at 10 before classifying


# ---------------------------------------------------------------------------
# data sufficiency
# ---------------------------------------------------------------------------

def test_data_sufficiency_false_when_too_new():
    now = KICKOFF - timedelta(hours=47.5)
    series = [ml_point(48, 0.4, 0.3, 0.3), ml_point(47.6, 0.4, 0.3, 0.3)]
    assert data_sufficiency(series, [], now) is False


def test_data_sufficiency_true_with_enough_age_and_points():
    now = KICKOFF - timedelta(hours=10)
    series = [ml_point(48, 0.4, 0.3, 0.3), ml_point(10, 0.4, 0.3, 0.3)]
    assert data_sufficiency(series, [], now) is True


# ---------------------------------------------------------------------------
# end-to-end scoring scenarios
# ---------------------------------------------------------------------------

def test_compute_match_score_insufficient_data():
    result = compute_match_score([ml_point(0.1, 0.4, 0.3, 0.3)], [], KICKOFF, now=KICKOFF - timedelta(hours=71.9))
    assert result["tier"] == "insufficient_data"


def test_compute_match_score_strong_sharp_convergence():
    ml = [
        ml_point(48, 0.40, 0.30, 0.30, limit=2500.0),
        ml_point(1, 0.46, 0.28, 0.26, limit=1000.0),  # 60% limit drop, home backed
    ]
    sp = [
        sp_point(48, -0.25, limit=5000.0),
        sp_point(1, -1.5, limit=2000.0),  # syndicate-level AH shift, home backed
    ]
    result = compute_match_score(ml, sp, KICKOFF, now=KICKOFF - timedelta(hours=0.5))
    assert result["tier"] == "strong_sharp"
    assert result["sharp_side"] == "home"
    assert result["convergence_bonus"] == CONFIG["convergence_bonus"]


def test_compute_match_score_quiet_market_is_no_signal():
    ml = [ml_point(48, 0.40, 0.30, 0.30), ml_point(1, 0.401, 0.2995, 0.2995)]
    sp = [sp_point(48, -0.5), sp_point(1, -0.5)]
    result = compute_match_score(ml, sp, KICKOFF, now=KICKOFF - timedelta(hours=0.5))
    assert result["tier"] == "no_signal"
    assert result["sharp_side"] is None
