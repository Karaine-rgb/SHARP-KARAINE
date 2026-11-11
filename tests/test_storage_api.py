import pytest
from fastapi import HTTPException

from app import api


@pytest.fixture
def fake_db(monkeypatch):
    state = {"matches": [], "deleted": [], "executed": [], "snap_count": 0, "fetch_queries": []}

    async def fetch(query, *params):
        state["fetch_queries"].append((query, params))
        if "from matchups where" in query:
            return state["matches"]
        if "pg_class" in query:
            return [{"name": "market_snapshots", "bytes": 800}, {"name": "signals", "bytes": 200}, {"name": "app_settings", "bytes": 5}]
        if "left join market_snapshots" in query:
            return [
                {"round_label": "A", "match_count": 2, "snapshot_count": 30, "is_active": False, "earliest_kickoff": None},
                {"round_label": "B", "match_count": 1, "snapshot_count": 10, "is_active": True, "earliest_kickoff": None},
            ]
        raise AssertionError(query)

    async def fetchval(query, *params):
        if "pg_database_size" in query:
            return 12345
        return state["snap_count"]

    async def execute(query, *params):
        state["executed"].append((query, params))
        return "OK"

    monkeypatch.setattr(api.db, "fetch", fetch)
    monkeypatch.setattr(api.db, "fetchval", fetchval)
    monkeypatch.setattr(api.db, "execute", execute)
    return state


@pytest.mark.asyncio
async def test_delete_requires_matching_confirm(fake_db):
    with pytest.raises(HTTPException) as e:
        await api.delete_round(round_label="A", confirm="a")
    assert e.value.status_code == 400
    assert fake_db["executed"] == []


@pytest.mark.asyncio
async def test_delete_unknown_round_404(fake_db):
    with pytest.raises(HTTPException) as e:
        await api.delete_round(round_label="A", confirm="A")
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_refuses_monitored_round(fake_db):
    fake_db["matches"] = [{"id": 1, "is_monitored": False}, {"id": 2, "is_monitored": True}]
    with pytest.raises(HTTPException) as e:
        await api.delete_round(round_label="A", confirm="A")
    assert e.value.status_code == 409
    assert fake_db["executed"] == []


@pytest.mark.asyncio
async def test_delete_removes_each_match_and_reports_counts(fake_db):
    fake_db["matches"] = [{"id": 1, "is_monitored": False}, {"id": 2, "is_monitored": False}]
    fake_db["snap_count"] = 77
    out = await api.delete_round(round_label="A/B (x)", confirm="A/B (x)")
    assert out == {"ok": True, "deleted_matches": 2, "deleted_snapshots": 77}
    assert [p for _, p in fake_db["executed"]] == [(1,), (2,)]
    assert all("delete from matchups" in q for q, _ in fake_db["executed"])


@pytest.mark.asyncio
async def test_delete_unlabeled_uses_null_condition(fake_db):
    fake_db["matches"] = [{"id": 5, "is_monitored": False}]
    await api.delete_round(round_label="(unlabeled)", confirm="(unlabeled)")
    q, params = fake_db["fetch_queries"][0]
    assert "mjp_round_label is null" in q and params == ()


@pytest.mark.asyncio
async def test_storage_overview_estimates_round_size(fake_db):
    out = await api.storage_overview()
    assert out["db_bytes"] == 12345
    a, b = out["rounds"]
    # data tables total 1000 bytes (app_settings excluded); A holds 30 of 40 snapshots
    assert a["est_bytes"] == 750 and b["est_bytes"] == 250


@pytest.mark.asyncio
async def test_reclaim_vacuums_each_data_table(fake_db):
    out = await api.reclaim_space()
    assert out["ok"] is True
    assert [q for q, _ in fake_db["executed"]] == [
        "vacuum full market_snapshots", "vacuum full signals", "vacuum full match_scores",
        "vacuum full alerts_sent", "vacuum full matchups",
    ]
