"""Environment configuration.

Everything here is a bootstrap default. Arcadia key and Telegram credentials
can be overridden at runtime via the Settings panel (see app/settings_store.py),
which persists them to the `app_settings` table so they survive redeploys
without needing to touch Railway env vars again.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


class Settings:
    # Supabase Postgres connection string, e.g.
    # postgresql://user:pass@host:5432/postgres
    database_url: str = _env("DATABASE_URL", "")

    # Guest key used by Pinnacle's own frontend. Guest tokens are known to
    # rotate/expire without notice - if requests start 401ing, grab a fresh
    # one from the network tab on pinnacle.com and set ARCADIA_API_KEY.
    arcadia_api_key: str = _env(
        "ARCADIA_API_KEY", "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"
    )
    arcadia_base_url: str = _env(
        "ARCADIA_BASE_URL", "https://guest.api.arcadia.pinnacle.com/0.1"
    )

    telegram_bot_token: str = _env("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = _env("TELEGRAM_CHAT_ID", "")

    # Polling tuning (seconds unless noted).
    poll_base_interval: float = float(_env("POLL_BASE_INTERVAL", "30"))
    poll_backoff_step: float = float(_env("POLL_BACKOFF_STEP", "15"))
    poll_max_interval: float = float(_env("POLL_MAX_INTERVAL", "120"))
    poll_jitter_min: float = float(_env("POLL_JITTER_MIN", "1.0"))
    poll_jitter_max: float = float(_env("POLL_JITTER_MAX", "3.5"))

    port: int = int(_env("PORT", "8000"))


settings = Settings()
