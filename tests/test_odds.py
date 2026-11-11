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


from app.odds import MARGIN_COLUMNS, fair_probs_from_decimal_odds, margin_columns


def test_margin_columns_three_way_sums_and_shares():
    prices = [2.63, 3.68, 2.62]
    fair = fair_probs_from_decimal_odds(prices)
    m = margin_columns(*prices, *fair)
    total = (sum(1 / p for p in prices) - 1) * 100
    assert m["margin_total_pct"] == pytest.approx(total, abs=1e-5)
    pps = [m["margin_home_pp"], m["margin_draw_pp"], m["margin_away_pp"]]
    assert sum(pps) == pytest.approx(total, abs=1e-4)
    shares = [m["margin_home_share_pct"], m["margin_draw_share_pct"], m["margin_away_share_pct"]]
    assert sum(shares) == pytest.approx(100.0, abs=1e-4)
    assert set(m) == set(MARGIN_COLUMNS)


def test_margin_columns_two_way_leaves_draw_empty():
    prices = [1.95, 1.90]
    fair = fair_probs_from_decimal_odds(prices)
    m = margin_columns(prices[0], None, prices[1], fair[0], None, fair[1])
    assert m["margin_draw_pp"] is None and m["margin_draw_share_pct"] is None
    assert m["margin_home_pp"] + m["margin_away_pp"] == pytest.approx(m["margin_total_pct"], abs=1e-4)
    assert m["margin_home_share_pct"] + m["margin_away_share_pct"] == pytest.approx(100.0, abs=1e-4)


def test_margin_columns_missing_data_gives_all_none():
    m = margin_columns(2.0, None, None, 0.5, None, None)
    assert all(v is None for v in m.values())
    m = margin_columns(None, None, None, None, None, None)
    assert all(v is None for v in m.values())
