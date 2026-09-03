"""Telegram alerts on tier transitions only - not every poll cycle."""
from __future__ import annotations

import logging

import httpx

from app import db
from app.settings_store import get_telegram_credentials

logger = logging.getLogger("telegram")

TIER_LABELS = {
    "strong_sharp": "STRONG SHARP",
    "sharp": "SHARP",
    "watch": "WATCH",
    "contested": "CONTESTED",
    "no_signal": "No Signal",
    "insufficient_data": "Insufficient Data",
}


async def get_last_alerted_tier(matchup_id: int) -> str | None:
    row = await db.fetchrow(
        "select tier from alerts_sent where matchup_id = $1 order by sent_at desc limit 1",
        matchup_id,
    )
    return row["tier"] if row else None


async def maybe_alert_tier_change(matchup_id: int, home_team: str, away_team: str, new_tier: str, detail: str) -> None:
    """Only fires when the tier actually changed from the last alert sent
    for this match, and only for tiers worth interrupting for.
    """
    if new_tier not in ("strong_sharp", "sharp", "contested"):
        return
    last = await get_last_alerted_tier(matchup_id)
    if last == new_tier:
        return

    token, chat_id = await get_telegram_credentials()
    if not token or not chat_id:
        logger.info("Telegram not configured, skipping alert for matchup %s", matchup_id)
        return

    label = TIER_LABELS.get(new_tier, new_tier)
    text = f"[{label}] {home_team} vs {away_team}\n{detail}"

    message_id = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
            if resp.status_code == 200:
                message_id = resp.json().get("result", {}).get("message_id")
            else:
                logger.warning("Telegram send failed (%s): %s", resp.status_code, resp.text[:300])
    except httpx.TransportError as exc:
        logger.warning("Telegram send error: %s", exc)

    await db.execute(
        "insert into alerts_sent (matchup_id, tier, telegram_message_id) values ($1, $2, $3)",
        matchup_id,
        new_tier,
        message_id,
    )
