"""Fast round deletion.

Deleting a few hundred thousand snapshot rows (and their indexes and TOASTed
JSON) takes a while on a free-tier database, so the request does the instant
part only: matches are relabelled to a hidden marker, which removes the round
from every list at once. The rows are then purged in the background with
set-based deletes, a few matches at a time and a few chunks in parallel. A
purge that is interrupted (e.g. a redeploy) is resumed on the next startup,
because the hidden marker is still on the rows.
"""
from __future__ import annotations

import asyncio
import logging

from app import db

logger = logging.getLogger("round_delete")

DELETING_LABEL = "__deleting__"
CHUNK_MATCHES = 3
PARALLEL_CHUNKS = 3

_lock: asyncio.Lock | None = None
_tasks: set[asyncio.Task] = set()


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def hide_matches(ids: list[int]) -> None:
    """Instant step: pull the matches out of every round listing."""
    await db.execute(
        "update matchups set mjp_round_label = $1 where id = any($2::bigint[]) and is_monitored = false",
        DELETING_LABEL,
        ids,
    )


async def pending_count() -> int:
    return int(await db.fetchval("select count(*) from matchups where mjp_round_label = $1", DELETING_LABEL) or 0)


async def _purge_chunk(ids: list[int]) -> None:
    # Children first, then the matches; the same rows the FK cascade would
    # remove, but as one set-based statement per table.
    for table in ("market_snapshots", "signals", "match_scores", "alerts_sent"):
        await db.execute(f"delete from {table} where matchup_id = any($1::bigint[])", ids)
    await db.execute("delete from matchups where id = any($1::bigint[])", ids)


async def purge_pending() -> int:
    """Delete every hidden match. Returns how many were removed."""
    removed = 0
    async with _get_lock():
        while True:
            rows = await db.fetch("select id from matchups where mjp_round_label = $1", DELETING_LABEL)
            ids = [r["id"] for r in rows]
            if not ids:
                return removed
            chunks = [ids[i : i + CHUNK_MATCHES] for i in range(0, len(ids), CHUNK_MATCHES)]
            sem = asyncio.Semaphore(PARALLEL_CHUNKS)

            async def run(chunk: list[int]) -> None:
                async with sem:
                    await _purge_chunk(chunk)

            await asyncio.gather(*(run(c) for c in chunks))
            removed += len(ids)


async def _purge_safely() -> None:
    try:
        n = await purge_pending()
        if n:
            logger.info("Purged %d deleted matches", n)
    except Exception:
        logger.exception("Background round purge failed; it will resume on the next delete or restart")


def start_purge() -> asyncio.Task:
    """Run the purge in the background; keep a reference so it is not collected."""
    task = asyncio.get_running_loop().create_task(_purge_safely())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task
