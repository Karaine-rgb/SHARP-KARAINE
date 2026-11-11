import pytest
from fastapi import HTTPException

from app import api
from app.storage_guard import StorageGuard


@pytest.fixture
def fake_db(monkeypatch):
    state = {"matches": [], "deleted": [], "executed": [], "snap_count": 0, "fetch_queries": [],
             "downloaded": True, "many": [], "db_size": 5000, "snaps_24h": 20, "reclaim_sizes": []}

    async def fetch(query, *params):
        state["fetch_queries"].append((query, params))
        if "from matchups where" in query:
            return state["matches"]
        if "n_live_tup" in query:
            return state["reclaim_sizes"]
        if "pg_class" in query:
            return [{"name": "market_snapshots", "bytes": 800}, {"name": "signals", "bytes": 200}, {"name": "app_settings", "bytes": 5}]
        if "left join market_snapshots" in query:
            return [
                {"round_label": "A", "match_count": 2, "snapshot_count": 30, "is_active": False, "earliest_kickoff": None,
                 "downloaded_at": None, "downloaded_snapshots": None},
                {"round_label": "B", "match_count": 1, "snapshot_count": 10, "is_active": True, "earliest_kickoff": None,
                 "downloaded_at": "2026-11-01", "downloaded_snapshots": 10},
            ]
        raise AssertionError(query)

    async def fetchrow(query, *params):
        assert "round_downloads" in query
        return {"downloaded_at": "2026-11-01"} if state["downloaded"] else None

    async def executemany(query, args):
        state["many"].append((query, list(args)))

    async def fetchval(query, *params):
        if "pg_database_size" in query:
            return state["db_size"]
        if "captured_at >" in query:
            return state["snaps_24h"]
        return state["snap_count"]

    async def execute(query, *params):
        state["executed"].append((query, params))
        return "OK"

    monkeypatch.setattr(api.db, "fetch", fetch)
    monkeypatch.setattr(api.db, "fetchval", fetchval)
    monkeypatch.setattr(api.db, "fetchrow", fetchrow)
    monkeypatch.setattr(api.db, "executemany", executemany)
    monkeypatch.setattr(api.db, "execute", execute)

    async def size():
        return state["db_size"]

    monkeypatch.setattr(api, "guard", StorageGuard(10_000, 80, 90, 95, size_fn=size))
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
    deletes = [(q, p) for q, p in fake_db["executed"] if "delete from matchups" in q]
    assert [p for _, p in deletes] == [(1,), (2,)]
    assert fake_db["executed"][-1] == ("delete from round_downloads where round_label = $1", ("A/B (x)",))


@pytest.mark.asyncio
async def test_delete_unlabeled_uses_null_condition(fake_db):
    fake_db["matches"] = [{"id": 5, "is_monitored": False}]
    await api.delete_round(round_label="(unlabeled)", confirm="(unlabeled)")
    q, params = fake_db["fetch_queries"][0]
    assert "mjp_round_label is null" in q and params == ()


@pytest.mark.asyncio
async def test_storage_overview_estimates_round_size(fake_db):
    out = await api.storage_overview()
    assert out["db_bytes"] == 5000
    a, b = out["rounds"]
    # data tables total 1000 bytes (app_settings excluded); A holds 30 of 40 snapshots
    assert a["est_bytes"] == 750 and b["est_bytes"] == 250
    assert a["downloaded_at"] is None and b["downloaded_snapshots"] == 10


@pytest.mark.asyncio
async def test_reclaim_vacuums_smallest_tables_first(fake_db):
    fake_db["reclaim_sizes"] = [
        {"name": "market_snapshots", "bytes": 800, "live": 100, "dead": 0},
        {"name": "signals", "bytes": 200, "live": 10, "dead": 0},
        {"name": "matchups", "bytes": 50, "live": 5, "dead": 5},
    ]
    out = await api.reclaim_space()
    assert out["ok"] is True and out["skipped"] == []
    assert [q for q, _ in fake_db["executed"]] == [
        "vacuum full matchups", "vacuum full signals", "vacuum full market_snapshots",
    ]
    assert out["rewritten"] == ["matchups", "signals", "market_snapshots"]


@pytest.mark.asyncio
async def test_reclaim_skips_a_table_whose_copy_would_not_fit(fake_db):
    fake_db["db_size"] = 9000  # limit 10_000, 97% = 9700 -> only 700 bytes of room
    fake_db["reclaim_sizes"] = [
        {"name": "market_snapshots", "bytes": 5000, "live": 100, "dead": 0},
        {"name": "signals", "bytes": 200, "live": 10, "dead": 0},
    ]
    out = await api.reclaim_space()
    assert out["rewritten"] == ["signals"]
    assert [s["table"] for s in out["skipped"]] == ["market_snapshots"]
    assert out["skipped"][0]["needs_bytes"] > out["skipped"][0]["free_bytes"]
    assert [q for q, _ in fake_db["executed"]] == ["vacuum full signals"]


@pytest.mark.asyncio
async def test_storage_overview_reports_headroom(fake_db):
    out = await api.storage_overview()
    assert out["usage"]["used_pct"] == 50.0 and out["usage"]["level"] == "ok"
    h = out["headroom"]
    # pause line 9500, used 5000 -> 4500 usable; rounds average (750+250)/2 = 500 -> 9 more rounds
    assert h["avg_round_bytes"] == 500 and h["rounds_left"] == 9
    # 20 snapshots in 24h at 1000 data bytes / 40 snapshots = 25 bytes each -> 500/day -> 9 days
    assert h["bytes_per_day"] == 500 and h["days_left"] == 9.0


@pytest.mark.asyncio
async def test_storage_status_is_the_cheap_usage_check(fake_db):
    fake_db["db_size"] = 9600
    out = await api.storage_status()
    assert out["level"] == "paused" and out["collection_paused"] is True and out["free_bytes"] == 400


@pytest.mark.asyncio
async def test_delete_never_downloaded_round_needs_explicit_override(fake_db):
    fake_db["matches"] = [{"id": 1, "is_monitored": False}]
    fake_db["downloaded"] = False
    with pytest.raises(HTTPException) as e:
        await api.delete_round(round_label="A", confirm="A")
    assert e.value.status_code == 409 and e.value.detail.startswith("never_downloaded")
    assert fake_db["executed"] == []
    out = await api.delete_round(round_label="A", confirm="A", allow_undownloaded=True)
    assert out["deleted_matches"] == 1


@pytest.mark.asyncio
async def test_downloaded_round_deletes_without_override(fake_db):
    fake_db["matches"] = [{"id": 1, "is_monitored": False}]
    fake_db["downloaded"] = True
    out = await api.delete_round(round_label="A", confirm="A")
    assert out["ok"] is True


@pytest.mark.asyncio
async def test_export_records_each_round_downloaded(fake_db, monkeypatch):
    rows = [{"mjp_round_label": "A", "home_price": 2.0, "draw_price": None, "away_price": 1.9,
             "fair_home_prob": 0.5, "fair_draw_prob": None, "fair_away_prob": 0.5}] * 3 + [
            {"mjp_round_label": None, "home_price": 2.0, "draw_price": None, "away_price": 1.9,
             "fair_home_prob": 0.5, "fair_draw_prob": None, "fair_away_prob": 0.5}]

    async def fetch(query, *params):
        return rows

    monkeypatch.setattr(api.db, "fetch", fetch)
    await api.export_match_snapshots_csv()
    (query, args), = fake_db["many"]
    assert "round_downloads" in query
    assert dict(args) == {"A": 3, "(unlabeled)": 1}


@pytest.mark.asyncio
async def test_empty_export_records_nothing(fake_db, monkeypatch):
    async def fetch(query, *params):
        return []

    monkeypatch.setattr(api.db, "fetch", fetch)
    await api.export_match_snapshots_csv(round_label="A")
    assert fake_db["many"] == []


@pytest.mark.asyncio
async def test_rename_moves_the_download_record(fake_db):
    await api.rename_round(api.RoundRename(old_label="A", new_label="B"))
    sqls = [q for q, _ in fake_db["executed"]]
    assert any(q.startswith("update round_downloads set round_label") for q in sqls)
    assert any(q.startswith("delete from round_downloads where round_label") for q in sqls)
