from app.ingest import add_fair_probs, diff_changed_markets, normalize_market, select_main_line


def moneyline_market(version=1, home=-105, draw=240, away=260, status="open"):
    return {
        "type": "moneyline",
        "period": 0,
        "isAlternate": False,
        "status": status,
        "version": version,
        "cutoffAt": "2026-09-06T15:00:00Z",
        "limits": [{"amount": 2500.0, "type": "maxRiskStake"}],
        "prices": [
            {"designation": "home", "price": home, "points": None},
            {"designation": "draw", "price": draw, "points": None},
            {"designation": "away", "price": away, "points": None},
        ],
    }


def spread_market(version=1, home_points=-0.5, home_price=-110, away_price=-110, is_alt=False):
    return {
        "type": "spread",
        "period": 0,
        "isAlternate": is_alt,
        "status": "open",
        "version": version,
        "cutoffAt": "2026-09-06T15:00:00Z",
        "limits": [{"amount": 5000.0, "type": "maxRiskStake"}],
        "prices": [
            {"designation": "home", "price": home_price, "points": home_points},
            {"designation": "away", "price": away_price, "points": -home_points},
        ],
    }


def test_normalize_moneyline_market():
    snap = normalize_market(1, moneyline_market())
    assert snap["market_type"] == "moneyline"
    assert snap["home_price"] > 1.0
    assert snap["limit_amount"] == 2500.0
    assert snap["version"] == 1


def test_normalize_spread_market_points():
    snap = normalize_market(1, spread_market(home_points=-0.75))
    assert snap["home_points"] == -0.75
    assert snap["limit_amount"] == 5000.0


def test_normalize_total_market_maps_over_under():
    market = {
        "type": "total",
        "period": 0,
        "isAlternate": False,
        "status": "open",
        "version": 1,
        "cutoffAt": None,
        "limits": [{"amount": 3000.0, "type": "maxRiskStake"}],
        "prices": [
            {"designation": "over", "price": -105, "points": 2.5},
            {"designation": "under", "price": -115, "points": 2.5},
        ],
    }
    snap = normalize_market(1, market)
    assert snap["home_points"] == 2.5
    assert snap["home_price"] > 1.0  # over
    assert snap["away_price"] > 1.0  # under


def test_add_fair_probs_moneyline_sums_to_one():
    snap = normalize_market(1, moneyline_market())
    snap = add_fair_probs(snap)
    total = snap["fair_home_prob"] + snap["fair_draw_prob"] + snap["fair_away_prob"]
    assert abs(total - 1.0) < 1e-6


def test_add_fair_probs_suspended_market_left_none():
    snap = normalize_market(1, moneyline_market(status="suspended"))
    snap = add_fair_probs(snap)
    assert snap["fair_home_prob"] is None


def test_diff_changed_markets_detects_new_and_changed():
    m1 = moneyline_market(version=1)
    m2 = spread_market(version=1)
    last_versions = {("moneyline", 0, False): 1}  # spread not seen yet
    changed = diff_changed_markets([m1, m2], last_versions)
    assert len(changed) == 1
    assert changed[0]["type"] == "spread"


def test_diff_changed_markets_no_changes():
    m1 = moneyline_market(version=1)
    last_versions = {("moneyline", 0, False): 1}
    changed = diff_changed_markets([m1], last_versions)
    assert changed == []


def test_diff_changed_markets_version_bump_is_change():
    m1 = moneyline_market(version=2)
    last_versions = {("moneyline", 0, False): 1}
    changed = diff_changed_markets([m1], last_versions)
    assert len(changed) == 1


def test_select_main_line_prefers_non_alternate_closest_to_zero():
    markets = [
        normalize_market(1, spread_market(home_points=-2.0, is_alt=True)),
        normalize_market(1, spread_market(home_points=-0.5, is_alt=False)),
    ]
    main = select_main_line(markets, "spread")
    assert main["home_points"] == -0.5
