"""Thin asyncpg pool wrapper.

Plain asyncpg rather than an ORM: the workload here is mostly
insert-heavy time-series writes plus a handful of hand-shaped read
queries, and JSONB columns are easier to work with via raw SQL than
through an ORM layer.
"""
import json
from typing import Any, Iterable

import asyncpg

from app.config import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        if not settings.database_url:
            raise RuntimeError(
                "DATABASE_URL is not set - point it at your Supabase Postgres "
                "connection string before starting the app."
            )
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=1,
            max_size=10,
            # Supabase's pooled connection strings already negotiate SSL;
            # if you're connecting directly to the DB host instead of the
            # pooler, add ?sslmode=require to DATABASE_URL.
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized - call init_pool() first")
    return _pool


async def fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    async with get_pool().acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args: Any) -> asyncpg.Record | None:
    async with get_pool().acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetchval(query: str, *args: Any) -> Any:
    async with get_pool().acquire() as conn:
        return await conn.fetchval(query, *args)


async def execute(query: str, *args: Any) -> str:
    async with get_pool().acquire() as conn:
        return await conn.execute(query, *args)


async def executemany(query: str, args_list: Iterable[Iterable[Any]]) -> None:
    async with get_pool().acquire() as conn:
        await conn.executemany(query, args_list)


def to_jsonb(obj: Any) -> str:
    """asyncpg needs jsonb params passed as text; Postgres casts on insert."""
    return json.dumps(obj)


def from_jsonb(value: Any) -> Any:
    """asyncpg returns jsonb columns as raw JSON text (no codec is
    registered on this pool), so anything read back that went through
    to_jsonb()/`::jsonb` needs this on the way out.
    """
    if value is None or not isinstance(value, str):
        return value
    return json.loads(value)
