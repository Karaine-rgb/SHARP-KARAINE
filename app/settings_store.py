"""Runtime-editable settings, persisted in app_settings so the Settings
panel in the UI can update the Arcadia key / Telegram credentials without
a redeploy. Falls back to env vars (app/config.py) on first run.
"""
from __future__ import annotations

from app import db
from app.config import settings as env_settings

_SECRET_KEYS = {"arcadia_api_key", "telegram_bot_token", "telegram_chat_id"}


async def get_setting(key: str, default: str | None = None) -> str | None:
    row = await db.fetchrow("select value from app_settings where key = $1", key)
    if row is not None:
        return row["value"]
    return default


async def set_setting(key: str, value: str) -> None:
    await db.execute(
        """
        insert into app_settings (key, value) values ($1, $2)
        on conflict (key) do update set value = excluded.value
        """,
        key,
        value,
    )


async def get_arcadia_api_key() -> str:
    return await get_setting("arcadia_api_key", env_settings.arcadia_api_key)


async def get_telegram_credentials() -> tuple[str, str]:
    token = await get_setting("telegram_bot_token", env_settings.telegram_bot_token)
    chat_id = await get_setting("telegram_chat_id", env_settings.telegram_chat_id)
    return token or "", chat_id or ""


async def get_all_settings_masked() -> dict:
    """For the Settings panel GET - never return raw secret values."""
    out = {}
    for key in _SECRET_KEYS:
        val = await get_setting(key, getattr(env_settings, key, ""))
        out[key] = _mask(val)
    return out


def _mask(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return value[:3] + "*" * (len(value) - 6) + value[-3:]
