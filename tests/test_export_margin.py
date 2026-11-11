import csv
import io

import pytest

from app import api
from app.odds import MARGIN_COLUMNS, fair_probs_from_decimal_odds


@pytest.mark.asyncio
async def test_export_csv_includes_margin_columns(monkeypatch):
    prices = [2.63, 3.68, 2.62]
    fair = fair_probs_from_decimal_odds(prices)
    base = {
        "matchup_id": 1, "market_type": "moneyline", "home_price": prices[0], "draw_price": prices[1],
        "away_price": prices[2], "fair_home_prob": fair[0], "fair_draw_prob": fair[1], "fair_away_prob": fair[2],
    }
    two_way = {**base, "market_type": "spread", "draw_price": None, "fair_draw_prob": None,
               "home_price": 1.95, "away_price": 1.90, "fair_home_prob": 0.5, "fair_away_prob": 0.5}

    async def fake_fetch(query, *params):
        return [base, two_way]

    monkeypatch.setattr(api.db, "fetch", fake_fetch)
    resp = await api.export_match_snapshots_csv()
    rows = list(csv.DictReader(io.StringIO(resp.body.decode())))
    assert set(MARGIN_COLUMNS) <= set(rows[0].keys())
    assert float(rows[0]["margin_total_pct"]) == pytest.approx((sum(1 / p for p in prices) - 1) * 100, abs=1e-4)
    assert rows[0]["margin_draw_pp"] != ""
    assert rows[1]["margin_draw_pp"] == "" and rows[1]["margin_home_pp"] != ""
