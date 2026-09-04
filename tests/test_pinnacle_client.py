import pytest

from app.pinnacle_client import ArcadiaClient


@pytest.mark.asyncio
async def test_get_matchup_markets_filters_to_requested_matchup(monkeypatch):
    # Real /markets/related/straight responses include OTHER matchups'
    # markets too (some using an entirely different participantId-keyed
    # price shape) - regression test for the crash this caused when they
    # weren't filtered out before reaching ingest.
    raw = [
        {"matchupId": 111, "type": "moneyline", "key": "s;0;m", "version": 1},
        {"matchupId": 111, "type": "spread", "key": "s;0;s;0.5", "version": 1},
        {"matchupId": 999, "type": "moneyline", "key": "s;0;m", "prices": [{"participantId": 1, "price": 100}]},
    ]

    client = ArcadiaClient(api_key="test")

    async def fake_get(path, params=None, max_retries=4):
        return raw

    monkeypatch.setattr(client, "_get", fake_get)

    result = await client.get_matchup_markets(111)
    await client.aclose()

    assert len(result) == 2
    assert all(m["matchupId"] == 111 for m in result)
