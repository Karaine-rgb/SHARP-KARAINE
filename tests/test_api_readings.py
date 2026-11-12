from datetime import datetime, timedelta, timezone

import pytest

from app import api

KICKOFF = datetime(2026, 9, 6, 15, 0, tzinfo=timezone.utc)


def snap(matchup_id, market_type, hours_before, fh=None, fd=None, fa=None, points=None):
    return {
        "matchup_id": matchup_id, "market_type": market_type, "captured_at": KICKOFF - timedelta(hours=hours_before),
        "status": "open", "home_points": points,
        "fair_home_prob": fh, "fair_draw_prob": fd, "fair_away_prob": fa,
        # extra columns the detail endpoint selects
        "market_key": "k", "period": 0, "is_alternate": False, "version": None, "cutoff_at": None,
        "home_price": None, "draw_price": None, "away_price": None, "limit_amount": None,
    }


STEAM_ML = [
    snap(1, "moneyline", 48, 0.40, 0.30, 0.30),
    snap(1, "moneyline", 5, 0.40, 0.30, 0.30),
    snap(1, "moneyline", 2, 0.43, 0.33, 0.24),
    snap(1, "moneyline", 0.5, 0.46, 0.40, 0.14),  # home +6pp, draw +10pp inside the last 3h
]
SPREAD = [snap(1, "spread", 48, 0.5, None, 0.5, points=-0.5), snap(1, "spread", 1, 0.5, None, 0.5, points=-0.75)]


def matchup_row(mid):
    return {"id": mid, "pinnacle_matchup_id": 99, "home_team": "H", "away_team": "A", "league_name": "L",
            "start_time": KICKOFF, "mjp_round_label": "R", "is_monitored": False, "home_score": None, "away_score": None}


@pytest.mark.asyncio
async def test_summary_ranks_steam_sides_and_has_no_tier_fields(monkeypatch):
    async def fetch(query, *params):
        if "from matchups m" in query:
            return [matchup_row(1), matchup_row(2)]
        assert "from market_snapshots" in query
        return STEAM_ML + SPREAD

    monkeypatch.setattr(api.db, "fetch", fetch)
    rows = await api.matches_summary(round_label="R")
    first, second = rows
    assert [m["side"] for m in first["steam_moves"]] == ["draw", "home"]
    assert first["steam_moves"][0]["magnitude_pp"] > first["steam_moves"][1]["magnitude_pp"]
    assert first["ah_detail"]["opening"] == -0.5 and first["ah_detail"]["current"] == -0.75
    assert second["steam_moves"] == []  # no snapshots yet: nothing to report, nothing breaks
    assert "tier" not in first and "sharp_side" not in first and "total_score" not in first


@pytest.mark.asyncio
async def test_summary_with_no_matches_does_not_query_snapshots_badly(monkeypatch):
    async def fetch(query, *params):
        return []

    monkeypatch.setattr(api.db, "fetch", fetch)
    assert await api.matches_summary(round_label="R") == []
