from datetime import datetime, timedelta, timezone

import pytest

from app import api
from app.scorecard import read_match, result_side, tally

KICKOFF = datetime(2026, 9, 6, 15, 0, tzinfo=timezone.utc)


def m(result, engine, steam):
    return {"result": result, "engine": engine, "steam_sides": steam}


def test_result_side():
    assert result_side(2, 1) == "home" and result_side(0, 1) == "away" and result_side(1, 1) == "draw"
    assert result_side(None, 1) is None and result_side(1, None) is None


def test_tally_counts_each_signal_and_the_overlap():
    rows = [
        m("home", "home", ["home"]),            # engine right, steam right, converged right
        m("away", "home", ["home", "draw"]),    # engine wrong, steam wrong (away not steaming), converged wrong
        m("draw", "home", ["draw"]),            # engine wrong (draw), steam right (draw steamed), not converged
        m("away", None, ["away", "home"]),      # pick'em: no engine pick; steam right (several sides, no magnitude used)
        m("home", "home", []),                  # engine right, no steam at all
        m("home", None, []),                    # nothing from either
    ]
    t = tally(rows)
    assert t["settled"] == 6
    assert t["engine"] == {"picks": 4, "right": 2, "no_pick": 2}
    assert t["steam"]["flagged"] == 4 and t["steam"]["right"] == 3 and t["steam"]["no_steam"] == 2
    assert t["steam"]["avg_sides"] == 1.5                      # (1 + 2 + 1 + 2) / 4
    assert t["steam"]["chance_right"] == 2.0                   # 6 covered sides / 3
    assert t["converged"] == {"count": 2, "right": 1}          # rows 1 and 2 only


def test_tally_empty_round():
    t = tally([])
    assert t["settled"] == 0 and t["steam"]["avg_sides"] is None and t["converged"] == {"count": 0, "right": 0}


def test_steam_right_when_the_winning_side_steamed_even_if_not_the_biggest():
    # winning side (away) is the smaller of two steaming sides: still counts, magnitude is not used
    assert tally([m("away", None, ["home", "away"])])["steam"]["right"] == 1


def snap(mid, market_type, hours_before, fh=None, fd=None, fa=None, points=None):
    return {"matchup_id": mid, "market_type": market_type, "captured_at": KICKOFF - timedelta(hours=hours_before),
            "status": "open", "home_points": points, "fair_home_prob": fh, "fair_draw_prob": fd, "fair_away_prob": fa}


def test_read_match_uses_engine_favourite_and_steam_sides():
    ml = [snap(1, "moneyline", 48, 0.40, 0.30, 0.30), snap(1, "moneyline", 5, 0.40, 0.30, 0.30),
          snap(1, "moneyline", 2, 0.43, 0.33, 0.24), snap(1, "moneyline", 0.5, 0.46, 0.40, 0.14)]
    sp = [snap(1, "spread", 48, 0.5, None, 0.5, points=-0.5), snap(1, "spread", 1, 0.5, None, 0.5, points=-0.5)]
    r = read_match(sp, ml)
    assert r["engine"] == "home" and set(r["steam_sides"]) == {"home", "draw"}


@pytest.mark.asyncio
async def test_scorecard_endpoint_groups_by_round_and_skips_unscored(monkeypatch):
    ml = [snap(1, "moneyline", 48, 0.40, 0.30, 0.30), snap(1, "moneyline", 5, 0.40, 0.30, 0.30),
          snap(1, "moneyline", 2, 0.43, 0.33, 0.24), snap(1, "moneyline", 0.5, 0.46, 0.40, 0.14)]
    sp = [snap(1, "spread", 48, 0.5, None, 0.5, points=-0.5)]

    async def fetch(query, *params):
        if "from market_snapshots" in query:
            assert params[0] == [1]                              # only the scored match is read
            return ml + sp
        if "home_score is not null" in query:
            return [{"id": 1, "round_label": "R1", "start_time": KICKOFF, "home_score": 2, "away_score": 0}]
        return [{"round_label": "R2", "matches": 3, "earliest": KICKOFF + timedelta(days=7)},
                {"round_label": "R1", "matches": 2, "earliest": KICKOFF}]

    monkeypatch.setattr(api.db, "fetch", fetch)
    out = await api.matches_scorecard()
    r2, r1 = out["rounds"]
    assert r2["round_label"] == "R2" and r2["settled"] == 0 and r2["matches"] == 3
    assert r1["round_label"] == "R1" and r1["settled"] == 1 and r1["engine"] == {"picks": 1, "right": 1, "no_pick": 0}
    assert r1["steam"]["right"] == 1 and r1["converged"] == {"count": 1, "right": 1}
    assert out["total"]["settled"] == 1
