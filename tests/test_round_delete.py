import pytest

from app import round_delete


class FakeDB:
    def __init__(self, hidden_batches):
        self.batches = list(hidden_batches)  # what "select id ... hidden" returns on each call
        self.executed = []

    async def fetch(self, query, *args):
        assert args == ("__deleting__",)
        return [{"id": i} for i in (self.batches.pop(0) if self.batches else [])]

    async def execute(self, query, *args):
        self.executed.append((query, args))


@pytest.mark.asyncio
async def test_purge_deletes_children_before_matches_in_chunks(monkeypatch):
    db = FakeDB([[1, 2, 3, 4, 5], []])
    monkeypatch.setattr(round_delete, "db", db)
    removed = await round_delete.purge_pending()
    assert removed == 5
    by_chunk = {}
    for q, (ids,) in db.executed:
        by_chunk.setdefault(tuple(ids), []).append(q.split()[2] if q.startswith("delete from") else q)
    assert set(by_chunk) == {(1, 2, 3), (4, 5)}  # 3 matches per chunk
    for qs in by_chunk.values():
        assert qs == ["market_snapshots", "signals", "match_scores", "alerts_sent", "matchups"]


@pytest.mark.asyncio
async def test_purge_loops_until_nothing_is_hidden(monkeypatch):
    db = FakeDB([[1], [2], []])  # a second round hidden while the first purge ran
    monkeypatch.setattr(round_delete, "db", db)
    assert await round_delete.purge_pending() == 2


@pytest.mark.asyncio
async def test_purge_with_nothing_pending_does_nothing(monkeypatch):
    db = FakeDB([[]])
    monkeypatch.setattr(round_delete, "db", db)
    assert await round_delete.purge_pending() == 0
    assert db.executed == []


@pytest.mark.asyncio
async def test_a_failed_purge_is_logged_not_raised(monkeypatch):
    class Boom(FakeDB):
        async def execute(self, query, *args):
            raise RuntimeError("db hiccup")

    monkeypatch.setattr(round_delete, "db", Boom([[1], []]))
    await round_delete._purge_safely()  # must not raise


@pytest.mark.asyncio
async def test_hide_matches_relabels_only_unmonitored_rows(monkeypatch):
    db = FakeDB([])
    monkeypatch.setattr(round_delete, "db", db)
    await round_delete.hide_matches([7, 8])
    (q, args), = db.executed
    assert "is_monitored = false" in q and args == ("__deleting__", [7, 8])
