import pytest

from app.odds import american_to_decimal, implied_prob, power_devig


def test_american_to_decimal_positive():
    assert american_to_decimal(150) == pytest.approx(2.5)


def test_american_to_decimal_negative():
    assert american_to_decimal(-110) == pytest.approx(1.9090909, rel=1e-4)


def test_american_to_decimal_zero_rejected():
    with pytest.raises(ValueError):
        american_to_decimal(0)


def test_power_devig_sums_to_one():
    # Typical Pinnacle-tight moneyline: -105 / +240 / +260 -> some overround
    decimals = [american_to_decimal(o) for o in (-105, 240, 260)]
    raw = [implied_prob(d) for d in decimals]
    assert sum(raw) > 1.0  # overround present

    fair = power_devig(raw)
    assert sum(fair) == pytest.approx(1.0, abs=1e-6)
    # order/relative magnitude preserved
    assert fair[0] > fair[1] > fair[2] or fair[0] > fair[2] > fair[1]


def test_power_devig_two_way_market():
    decimals = [1.91, 1.91]  # symmetric AH line, ~4.7% overround
    raw = [implied_prob(d) for d in decimals]
    fair = power_devig(raw)
    assert sum(fair) == pytest.approx(1.0, abs=1e-6)
    assert fair[0] == pytest.approx(fair[1], abs=1e-6)


def test_power_devig_noop_when_already_fair():
    fair_in = [0.5, 0.3, 0.2]
    fair_out = power_devig(fair_in)
    assert fair_out == pytest.approx(fair_in, abs=1e-6)


def test_power_devig_rejects_bad_input():
    with pytest.raises(ValueError):
        power_devig([1.2, -0.1])
