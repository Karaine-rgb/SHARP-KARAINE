"""REST + WebSocket API."""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app import db
from app import round_delete
from app.odds import MARGIN_COLUMNS, margin_columns
from app.pinnacle_client import ArcadiaClient, ArcadiaError
from app.poller import poller
from app.storage_guard import guard
from app.settings_store import get_all_settings_masked, get_arcadia_api_key, set_setting
from app.signals import favorite_strength
from app.ws import manager

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class SettingsUpdate(BaseModel):
    arcadia_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None


@router.get("/settings")
async def get_settings():
    return await get_all_settings_masked()


@router.post("/settings")
async def update_settings(body: SettingsUpdate):
    changed_arcadia = False
    for key, value in body.model_dump(exclude_none=True).items():
        await set_setting(key, value)
        if key == "arcadia_api_key":
            changed_arcadia = True
    if changed_arcadia:
        await poller.refresh_client()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Saved leagues (persisted so league IDs don't need to be re-found in the
# browser's network tab every time - Pinnacle's UI doesn't expose them).
# ---------------------------------------------------------------------------

class SavedLeague(BaseModel):
    league_id: int
    league_name: str


@router.get("/saved-leagues")
async def list_saved_leagues():
    rows = await db.fetch(
        "select league_id, league_name, added_at from saved_leagues order by league_name asc"
    )
    return [dict(r) for r in rows]


@router.post("/saved-leagues")
async def add_saved_league(body: SavedLeague):
    await db.execute(
        """
        insert into saved_leagues (league_id, league_name) values ($1, $2)
        on conflict (league_id) do update set league_name = excluded.league_name
        """,
        body.league_id,
        body.league_name,
    )
    return {"ok": True}


@router.delete("/saved-leagues/{league_id}")
async def delete_saved_league(league_id: int):
    await db.execute("delete from saved_leagues where league_id = $1", league_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

@router.get("/leagues/{league_id}/matchups")
async def discover_league_matchups(league_id: int):
    client = ArcadiaClient(api_key=await get_arcadia_api_key())
    try:
        matchups = await client.get_league_matchups(league_id)
    except ArcadiaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await client.aclose()
    return matchups


@router.get("/debug/markets/{matchup_id}")
async def debug_raw_markets(matchup_id: int):
    """Raw passthrough of the markets endpoint, for diagnosing schema
    mismatches against a live response - not used by the frontend.
    """
    client = ArcadiaClient(api_key=await get_arcadia_api_key())
    try:
        return await client.get_matchup_markets(matchup_id)
    except ArcadiaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await client.aclose()


class MatchToTrack(BaseModel):
    pinnacle_matchup_id: int
    home_team: str
    away_team: str
    start_time: datetime
    league_id: int
    league_name: str | None = None


class TrackMatchesRequest(BaseModel):
    matches: list[MatchToTrack]
    mjp_round_label: str | None = None


@router.post("/monitored-matches")
async def add_monitored_matches(body: TrackMatchesRequest):
    added = []
    for m in body.matches:
        row = await db.fetchrow(
            """
            insert into matchups (
                pinnacle_matchup_id, league_id, league_name, home_team, away_team,
                start_time, is_monitored, mjp_round_label
            ) values ($1,$2,$3,$4,$5,$6,true,$7)
            on conflict (pinnacle_matchup_id) do update set
                is_monitored = true,
                mjp_round_label = excluded.mjp_round_label
            returning id
            """,
            m.pinnacle_matchup_id,
            m.league_id,
            m.league_name,
            m.home_team,
            m.away_team,
            m.start_time,
            body.mjp_round_label,
        )
        added.append(row["id"])
    return {"added": added}


@router.patch("/matches/{matchup_id}")
async def update_match_monitoring(matchup_id: int, is_monitored: bool):
    await db.execute("update matchups set is_monitored = $1 where id = $2", is_monitored, matchup_id)
    return {"ok": True}


class MatchResult(BaseModel):
    home_score: int | None = None
    away_score: int | None = None


@router.patch("/matches/{matchup_id}/result")
async def update_match_result(matchup_id: int, body: MatchResult):
    """Manually entered final score, kept permanently for backtesting real
    signals against real outcomes - the dashboard has no other way to know
    who won. Both null clears a previously-entered result."""
    await db.execute(
        "update matchups set home_score = $1, away_score = $2 where id = $3",
        body.home_score,
        body.away_score,
        matchup_id,
    )
    return {"ok": True}


@router.patch("/matches/{matchup_id}/remove-from-round")
async def remove_match_from_round(matchup_id: int):
    """Takes a match out of its round without deleting it or touching
    is_monitored - it just moves to the "(unlabeled)" bucket, the same
    convention every other endpoint already uses for a null mjp_round_label.
    All its collected data (snapshots, scores, signals, result) stays put."""
    await db.execute("update matchups set mjp_round_label = null where id = $1", matchup_id)
    return {"ok": True}


class RoundRename(BaseModel):
    old_label: str
    new_label: str


@router.patch("/rounds/rename")
async def rename_round(body: RoundRename):
    """Renames a round across every match carrying that label. Takes the
    labels in the request body rather than the URL path since round labels
    are free text and can contain spaces/slashes that don't belong in a
    path segment.

    old_label == "(unlabeled)" is allowed: it renames every match that
    currently has a null mjp_round_label (a snapshot of what's unlabeled
    right now). "(unlabeled)" itself stays reserved as the sentinel for
    null - any match removed from a round afterwards (mjp_round_label set
    back to null) still lands back under "(unlabeled)" automatically,
    since /rounds groups by coalesce(mjp_round_label, '(unlabeled)')
    regardless of what a past batch of nulls got renamed to.
    """
    new_label = body.new_label.strip()
    if not new_label:
        raise HTTPException(status_code=400, detail="New round name can't be empty")
    if new_label == "(unlabeled)":
        raise HTTPException(
            status_code=400,
            detail="(unlabeled) is reserved for matches with no round - pick a different name",
        )
    if body.old_label == "(unlabeled)":
        await db.execute("update matchups set mjp_round_label = $1 where mjp_round_label is null", new_label)
    else:
        await db.execute(
            "update matchups set mjp_round_label = $1 where mjp_round_label = $2",
            new_label,
            body.old_label,
        )
    # Keep the "already downloaded" record with the round: move it to the new
    # label, or drop it if that label already has its own record (a merge).
    await db.execute(
        "update round_downloads set round_label = $1 where round_label = $2 "
        "and not exists (select 1 from round_downloads where round_label = $1)",
        new_label,
        body.old_label,
    )
    await db.execute("delete from round_downloads where round_label = $1", body.old_label)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Summary + detail
# ---------------------------------------------------------------------------

@router.get("/rounds")
async def list_rounds():
    """Every Megajackpot round ever tracked, most recent first, with
    whether it's still actively being polled (is_active) - lets the
    dashboard distinguish the live round from archived history rather
    than matches just disappearing once auto-unmonitored.
    """
    rows = await db.fetch(
        """
        select
            coalesce(mjp_round_label, '(unlabeled)') as round_label,
            count(*) as match_count,
            min(start_time) as earliest_kickoff,
            max(start_time) as latest_kickoff,
            bool_or(is_monitored) as is_active
        from matchups
        where mjp_round_label is distinct from $1
        group by coalesce(mjp_round_label, '(unlabeled)')
        order by min(start_time) desc
        """,
        round_delete.DELETING_LABEL,
    )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Storage: see what is using the database and delete old rounds to free space
# ---------------------------------------------------------------------------

_DATA_TABLES = ("market_snapshots", "signals", "match_scores", "alerts_sent")
_SIZE_QUERY = "select pg_database_size(current_database())"


@router.get("/storage")
async def storage_overview():
    """Database size, per-table size, and each round's match/snapshot counts
    with an estimated size, so old rounds can be judged before deleting.

    Per-round size is an estimate: the round's share of all snapshots times
    the combined size of the tables that hold per-match data. Table sizes
    include dead rows until space is reclaimed, so after a delete the
    reported database size only drops once reclaim has run.
    """
    db_bytes = await db.fetchval(_SIZE_QUERY)
    tables = await db.fetch(
        """
        select c.relname as name, pg_total_relation_size(c.oid) as bytes
        from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relkind = 'r'
        order by 2 desc
        """
    )
    rounds = await db.fetch(
        """
        select
            coalesce(m.mjp_round_label, '(unlabeled)') as round_label,
            count(distinct m.id) as match_count,
            count(s.id) as snapshot_count,
            coalesce(bool_or(m.is_monitored), false) as is_active,
            min(m.start_time) as earliest_kickoff,
            max(d.downloaded_at) as downloaded_at,
            max(d.snapshot_count) as downloaded_snapshots
        from matchups m
        left join market_snapshots s on s.matchup_id = m.id
        left join round_downloads d on d.round_label = coalesce(m.mjp_round_label, '(unlabeled)')
        where m.mjp_round_label is distinct from $1
        group by 1
        order by min(m.start_time) desc
        """,
        round_delete.DELETING_LABEL,
    )
    usage = await guard.usage(force=True)
    table_list = [{"name": t["name"], "bytes": int(t["bytes"])} for t in tables]
    data_bytes = sum(t["bytes"] for t in table_list if t["name"] in _DATA_TABLES)
    total_snaps = sum(int(r["snapshot_count"]) for r in rounds) or 1
    out_rounds = []
    for r in rounds:
        d = dict(r)
        d["snapshot_count"] = int(d["snapshot_count"])
        d["match_count"] = int(d["match_count"])
        d["est_bytes"] = int(data_bytes * d["snapshot_count"] / total_snaps)
        d["downloaded_snapshots"] = int(d["downloaded_snapshots"]) if d.get("downloaded_snapshots") is not None else None
        out_rounds.append(d)

    # Headroom: how many more rounds of the average size fit before the
    # pause line, and how long at the last 24 hours' collection rate.
    sized = [r["est_bytes"] for r in out_rounds if r["snapshot_count"] > 0]
    avg_round = int(sum(sized) / len(sized)) if sized else 0
    snaps_24h = int(
        await db.fetchval("select count(*) from market_snapshots where captured_at > now() - interval '24 hours'") or 0
    )
    bytes_per_snapshot = data_bytes / total_snaps if out_rounds else 0
    bytes_per_day = int(snaps_24h * bytes_per_snapshot)
    headroom = {
        "avg_round_bytes": avg_round,
        "rounds_left": int(usage["usable_bytes"] // avg_round) if avg_round else None,
        "snapshots_24h": snaps_24h,
        "bytes_per_day": bytes_per_day,
        "days_left": round(usage["usable_bytes"] / bytes_per_day, 1) if bytes_per_day else None,
    }
    return {
        "db_bytes": int(db_bytes),
        "usage": usage,
        "headroom": headroom,
        "pending_delete_matches": await round_delete.pending_count(),
        "tables": table_list,
        "rounds": out_rounds,
    }


@router.get("/storage/status")
async def storage_status():
    """Cheap database-size check for the dashboard's always-visible banner:
    used / limit / free, the warn-critical-paused level, and whether the
    poller has paused collection to stay under the free-tier limit.
    """
    return await guard.usage(force=True)


@router.delete("/rounds")
async def delete_round(round_label: str, allow_undownloaded: bool = False):
    """Delete a round. Returns at once: the matches are hidden from every
    list immediately and their data (snapshots, signals, scores, alerts) is
    purged in the background - see app/round_delete.py.

    round_label is a query parameter (labels contain slashes). Refuses while
    any match in the round is still monitored - stop tracking it first so the
    poller is not writing to rows being deleted. A round that has never been
    downloaded as CSV is refused (409, "never_downloaded") unless
    allow_undownloaded=true is sent, so deleting data that exists nowhere else
    always takes a deliberate second step.
    """
    if round_label == "(unlabeled)":
        condition, params = "mjp_round_label is null", []
    else:
        if round_label == round_delete.DELETING_LABEL:
            raise HTTPException(status_code=404, detail="no such round")
        condition, params = "mjp_round_label = $1", [round_label]
    matches = await db.fetch(f"select id, is_monitored from matchups where {condition}", *params)
    if not matches:
        raise HTTPException(status_code=404, detail="no such round")
    if any(m["is_monitored"] for m in matches):
        raise HTTPException(
            status_code=409,
            detail="this round still has monitored matches - stop tracking it before deleting",
        )
    downloaded = await db.fetchrow(
        "select downloaded_at from round_downloads where round_label = $1", round_label
    )
    if downloaded is None and not allow_undownloaded:
        raise HTTPException(
            status_code=409,
            detail="never_downloaded: this round has never been downloaded as CSV - "
            "deleting it loses the data for good; confirm explicitly to delete anyway",
        )
    ids = [m["id"] for m in matches]
    await round_delete.hide_matches(ids)
    await db.execute("delete from round_downloads where round_label = $1", round_label)
    round_delete.start_purge()
    return {"ok": True, "deleted_matches": len(ids), "purging_in_background": True}


@router.post("/storage/reclaim")
async def reclaim_space():
    """Rewrite the data tables so deleted rows' space is returned to the
    database's size accounting (VACUUM FULL). Plain deletes only mark space
    reusable; the free-tier size meter does not drop until this runs. It
    takes an exclusive lock on each table while it works.

    VACUUM FULL writes a compact copy of a table before dropping the old one,
    so it needs free space about equal to the table's live data. That would
    push a nearly full database over the limit, so each table is rewritten
    only if the copy fits under the limit with a safety margin; the smallest
    tables go first (their space frees up room for the larger ones). Tables
    that don't fit are reported, not attempted.
    """
    pending = await round_delete.pending_count()
    if pending:
        raise HTTPException(
            status_code=409,
            detail=f"{pending} deleted matches are still being removed in the background - try again in a moment",
        )
    before = int(await db.fetchval(_SIZE_QUERY))
    limit = guard.limit_bytes
    sizes = await db.fetch(
        """
        select c.relname as name,
               pg_total_relation_size(c.oid) as bytes,
               coalesce(st.n_live_tup, 0) as live,
               coalesce(st.n_dead_tup, 0) as dead
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        left join pg_stat_user_tables st on st.relid = c.oid
        where n.nspname = 'public' and c.relkind = 'r' and c.relname = any($1::text[])
        """,
        [*_DATA_TABLES, "matchups"],
    )
    rewritten, skipped = [], []
    for t in sorted(sizes, key=lambda r: r["bytes"]):
        total_rows = t["live"] + t["dead"]
        live_fraction = t["live"] / total_rows if total_rows else 1.0
        need = int(t["bytes"] * live_fraction * 1.1)
        used = int(await db.fetchval(_SIZE_QUERY))
        if used + need > limit * 0.97:
            skipped.append({"table": t["name"], "needs_bytes": need, "free_bytes": max(0, int(limit * 0.97) - used)})
            continue
        try:
            await db.execute(f"vacuum full {t['name']}")
        except Exception as exc:  # surface the database's own message to the UI
            raise HTTPException(status_code=500, detail=f"reclaim failed on {t['name']}: {exc}")
        rewritten.append(t["name"])
    after = int(await db.fetchval(_SIZE_QUERY))
    return {"ok": True, "before_bytes": before, "after_bytes": after, "rewritten": rewritten, "skipped": skipped}


async def _record_downloads(rows) -> None:
    """Remember that these rounds were exported, with how many snapshots the
    file held. Recorded when the file is served, which is the closest the
    server can get to "downloaded" - it cannot see whether the browser saved it.
    """
    counts: dict[str, int] = {}
    for r in rows:
        label = r["mjp_round_label"] or "(unlabeled)"
        counts[label] = counts.get(label, 0) + 1
    if counts:
        await db.executemany(
            """
            insert into round_downloads (round_label, downloaded_at, snapshot_count, download_count)
            values ($1, now(), $2, 1)
            on conflict (round_label) do update set
                downloaded_at = now(),
                snapshot_count = excluded.snapshot_count,
                download_count = round_downloads.download_count + 1
            """,
            list(counts.items()),
        )


@router.get("/export/match-snapshots.csv")
async def export_match_snapshots_csv(round_label: str | None = None):
    """One complete, download-ready file for backtesting: every raw market
    snapshot ever collected, joined to the match it belongs to and the real
    final score - the same data as the match_snapshots_export view, but
    served directly by the app so a phone browser just downloads it with
    one tap, no Supabase Table Editor involved (which warns against
    exporting a view directly on anything large). Queried once here, not
    through the view, so Supabase's own warning about live view-browsing
    doesn't apply - this is a single, one-shot query.

    Optional round_label splits the export into one file per round
    (match_snapshots_export already carries mjp_round_label on every row) -
    mainly so a round's worth of data stays small enough to upload
    somewhere with a strict file-size limit, instead of one ever-growing
    file covering every round ever tracked. No round_label still returns
    everything. "(unlabeled)" means matches with a null round, matching
    the same convention /matches/summary already uses.
    """
    if round_label is None:
        condition, params = "mjp_round_label is distinct from $1", [round_delete.DELETING_LABEL]
    elif round_label == "(unlabeled)":
        condition, params = "mjp_round_label is null", []
    else:
        condition, params = "mjp_round_label = $1", [round_label]

    rows = await db.fetch(f"select * from match_snapshots_export where {condition}", *params)
    buffer = io.StringIO()
    if rows:
        # Margin columns are derived per row from the stored prices and fair
        # probabilities (not stored in the DB), so the export carries them
        # without a schema change.
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()) + MARGIN_COLUMNS)
        writer.writeheader()
        for r in rows:
            d = dict(r)
            d.update(
                margin_columns(
                    d["home_price"], d["draw_price"], d["away_price"],
                    d["fair_home_prob"], d["fair_draw_prob"], d["fair_away_prob"],
                )
            )
            writer.writerow(d)

    safe_suffix = re.sub(r"[^A-Za-z0-9_-]+", "_", round_label).strip("_") if round_label else "all"
    filename = f"match_snapshots_{safe_suffix}.csv"
    await _record_downloads(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/matches/summary")
async def matches_summary(round_label: str | None = None):
    """Without round_label: the actively-monitored (live) matches, same
    as before. With round_label: every match in that round regardless of
    is_monitored, so an archived/finished round stays fully viewable
    instead of disappearing once auto-unmonitored.
    """
    if round_label is None:
        condition, params = "m.is_monitored = true", []
    elif round_label == "(unlabeled)":
        condition, params = "m.mjp_round_label is null", []
    else:
        condition, params = "m.mjp_round_label = $1", [round_label]

    rows = await db.fetch(
        f"""
        select
            m.id, m.pinnacle_matchup_id, m.home_team, m.away_team, m.league_name,
            m.start_time, m.mjp_round_label, m.is_monitored, m.home_score, m.away_score,
            s.tier, s.sharp_side, s.contested, s.total_score, s.ah_score, s.x2_score,
            s.computed_at as score_computed_at,
            ah.detail_json as ah_detail,
            x2.detail_json as x2_detail
        from matchups m
        left join lateral (
            select * from match_scores ms where ms.matchup_id = m.id
            order by computed_at desc limit 1
        ) s on true
        left join lateral (
            select detail_json from signals sg where sg.matchup_id = m.id
            and sg.signal_type = 'ah_line_shift' order by computed_at desc limit 1
        ) ah on true
        left join lateral (
            select detail_json from signals sg where sg.matchup_id = m.id
            and sg.signal_type = 'x2_displacement' order by computed_at desc limit 1
        ) x2 on true
        where {condition}
        order by m.start_time asc
        """,
        *params,
    )
    result = []
    for r in rows:
        d = dict(r)
        d["ah_detail"] = db.from_jsonb(d["ah_detail"])
        d["x2_detail"] = db.from_jsonb(d["x2_detail"])
        result.append(d)
    return result


@router.get("/matches/{matchup_id}/detail")
async def match_detail(matchup_id: int):
    matchup = await db.fetchrow("select * from matchups where id = $1", matchup_id)
    if not matchup:
        raise HTTPException(status_code=404, detail="Match not found")

    # Megajackpot rounds span Saturday and Sunday, so each match's own
    # "latest" reading is a moving target - a Sunday match simply gets more
    # time to move than a Saturday one, which makes them impossible to
    # compare for post-match review. Instead, surface what every match in
    # the round looked like 10 minutes before the actual betslip lock-in
    # moments: the round's earliest kickoff overall (always the first
    # Saturday match, hence "saturday_cutoff") and, separately, the
    # earliest kickoff among just the Sunday matches (the deadline for a
    # separate Sunday-only jackpot entry). Both are computed round-wide,
    # not per-match, so every match in the round shares the same two
    # reference points. Day-of-week is read in UTC (extract(dow from ...)),
    # same as every other timestamp this app stores - fine for the handful
    # of hours either side of midnight this could theoretically misclassify,
    # not worth a timezone-aware rewrite for.
    round_label = matchup["mjp_round_label"]
    if round_label is None:
        round_condition, round_params = "mjp_round_label is null", []
    else:
        round_condition, round_params = "mjp_round_label = $1", [round_label]
    cutoff_row = await db.fetchrow(
        f"""
        select
            min(start_time) as earliest_overall,
            min(start_time) filter (where extract(dow from start_time) = 0) as earliest_sunday
        from matchups
        where {round_condition}
        """,
        *round_params,
    )
    betslip_cutoffs = {
        "saturday": (cutoff_row["earliest_overall"] - timedelta(minutes=10)) if cutoff_row["earliest_overall"] else None,
        "sunday": (cutoff_row["earliest_sunday"] - timedelta(minutes=10)) if cutoff_row["earliest_sunday"] else None,
    }

    latest_score = await db.fetchrow(
        "select * from match_scores where matchup_id = $1 order by computed_at desc limit 1",
        matchup_id,
    )
    score_history = await db.fetch(
        "select computed_at, total_score, tier, sharp_side from match_scores "
        "where matchup_id = $1 order by computed_at asc",
        matchup_id,
    )
    latest_signals = await db.fetch(
        """
        select distinct on (signal_type) signal_type, direction, magnitude, detail_json, computed_at
        from signals where matchup_id = $1 and signal_type <> 'limit_movement'
        order by signal_type, computed_at desc
        """,
        matchup_id,
    )

    # Full history of every velocity_shape / x2_displacement check ever run
    # for this match - a fresh row is inserted every poll cycle, so "was
    # this ever steam" or "was home ever leading" is already sitting in the
    # data even after the label has since moved on to something else.
    # Compressed to only the moments the label actually changed, not every
    # single poll that repeated it.
    async def _label_transitions(signal_type: str) -> list[dict]:
        rows = await db.fetch(
            """
            select computed_at, direction as label, detail_json from signals
            where matchup_id = $1 and signal_type = $2
            order by computed_at asc
            """,
            matchup_id,
            signal_type,
        )
        transitions = []
        last_label = None
        for r in rows:
            if r["label"] != last_label:
                detail = db.from_jsonb(r["detail_json"]) or {}
                # velocity_shape's detail carries "side" and "total_change_pp";
                # x2_displacement has neither (its label already IS the side) -
                # both are safely None/absent there, the frontend only shows
                # what's present.
                transitions.append({
                    "at": r["computed_at"],
                    "label": r["label"],
                    "side": detail.get("side"),
                    "change_pp": detail.get("total_change_pp"),
                })
                last_label = r["label"]
        return transitions

    velocity_transitions = await _label_transitions("velocity_shape")
    x2_transitions = await _label_transitions("x2_displacement")

    # Full raw time-series for independent analysis, grouped by market so the
    # frontend can render one chart per series regardless of what the signal
    # engine concluded. Main lines (period 0, non-alternate) drive the
    # primary charts; everything else (alternates, first-half) is still
    # returned for the raw table since it was collected too.
    all_snapshots = await db.fetch(
        """
        select market_key, market_type, period, is_alternate, version, status, cutoff_at, captured_at,
               home_price, draw_price, away_price, home_points, limit_amount,
               fair_home_prob, fair_draw_prob, fair_away_prob
        from market_snapshots
        where matchup_id = $1
        order by captured_at asc
        """,
        matchup_id,
    )

    series: dict[str, list[dict]] = {"moneyline": [], "spread": [], "total": [], "team_total": [], "other": []}
    raw_table = []
    for r in all_snapshots:
        d = dict(r)
        raw_table.append(d)
        if not d["is_alternate"] and d["period"] == 0:
            series.get(d["market_type"], series["other"]).append(d)

    signals_by_type = {}
    for r in latest_signals:
        d = dict(r)
        d["detail_json"] = db.from_jsonb(d["detail_json"])
        signals_by_type[r["signal_type"]] = d

    # favorite_strength is a pure function of the main-line snapshots, so
    # derive it fresh here instead of trusting the stored row: matches
    # scored before the feature existed (or before a later refinement) have
    # no row or a stale-schema one, and would otherwise read as "pick'em".
    signals_by_type["favorite_strength"] = {
        "signal_type": "favorite_strength",
        "detail_json": favorite_strength(series["spread"], series["moneyline"]),
    }

    return {
        "matchup": dict(matchup),
        "latest_score": dict(latest_score) if latest_score else None,
        "score_history": [dict(r) for r in score_history],
        "latest_signals": signals_by_type,
        "velocity_transitions": velocity_transitions,
        "x2_transitions": x2_transitions,
        "betslip_cutoffs": betslip_cutoffs,
        "series": {
            "moneyline_main": series["moneyline"],
            "spread_main": series["spread"],
            "total_main": series["total"],
        },
        "raw_snapshots": raw_table,
    }


@router.post("/poll/force/{matchup_id}")
async def force_poll(matchup_id: int):
    poller.force_poll(matchup_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
