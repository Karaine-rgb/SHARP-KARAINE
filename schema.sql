-- Run once against the Supabase Postgres database before first startup.
-- Supabase SQL editor: paste and run. Idempotent (safe to re-run).

create table if not exists matchups (
    id                   bigserial primary key,
    pinnacle_matchup_id  bigint unique not null,
    league_id            bigint not null,
    league_name          text,
    home_team            text not null,
    away_team            text not null,
    start_time           timestamptz not null,
    is_monitored         boolean not null default false,
    mjp_round_label       text,
    added_at             timestamptz not null default now()
);

create table if not exists market_snapshots (
    id               bigserial primary key,
    matchup_id       bigint not null references matchups(id) on delete cascade,
    market_key       text not null,       -- Pinnacle's own per-line id, e.g. "s;0;s;1.25" -
                                           -- the real unique identity for a specific line;
                                           -- (market_type, period, is_alternate) alone
                                           -- collides across simultaneous alternate lines.
    market_type      text not null,       -- moneyline | spread | total | team_total
    period           int not null,        -- 0 = full match, 1 = first half
    is_alternate     boolean not null,
    version          bigint,              -- nullable: not every market carries one live
    status           text,                -- open | suspended
    cutoff_at        timestamptz,
    captured_at      timestamptz not null default now(),
    raw_json         jsonb not null,
    home_price       double precision,    -- decimal odds
    draw_price       double precision,
    away_price       double precision,
    home_points      double precision,    -- AH/total line value
    limit_amount     double precision,    -- maxRiskStake at market level
    fair_home_prob   double precision,    -- post power-devig
    fair_draw_prob   double precision,
    fair_away_prob   double precision
);

create index if not exists idx_snapshots_matchup_market
    on market_snapshots (matchup_id, market_type, period, is_alternate, captured_at);

-- Fast "last known version per market line" lookup for change detection -
-- market_key is the real per-line identity (see column comment above).
create index if not exists idx_snapshots_matchup_key_version
    on market_snapshots (matchup_id, market_key, captured_at desc);

create table if not exists signals (
    id            bigserial primary key,
    matchup_id    bigint not null references matchups(id) on delete cascade,
    computed_at   timestamptz not null default now(),
    signal_type   text not null,   -- limit_movement | ah_line_shift | x2_displacement | ah_price_move | convergence
    direction     text,            -- home | away | draw | null
    magnitude     double precision,
    detail_json   jsonb
);

create index if not exists idx_signals_matchup on signals (matchup_id, computed_at desc);

create table if not exists match_scores (
    matchup_id    bigint not null references matchups(id) on delete cascade,
    computed_at   timestamptz not null default now(),
    ah_score      double precision not null,
    x2_score      double precision not null,
    limit_bonus   double precision not null,
    convergence_bonus double precision not null default 0,
    total_score   double precision not null,
    tier          text not null,   -- strong_sharp | sharp | watch | no_signal | insufficient_data
    sharp_side    text,            -- home | away | contested | null
    contested     boolean not null default false,
    primary key (matchup_id, computed_at)
);

create table if not exists alerts_sent (
    id            bigserial primary key,
    matchup_id    bigint not null references matchups(id) on delete cascade,
    tier          text not null,
    sent_at       timestamptz not null default now(),
    telegram_message_id bigint
);

create table if not exists app_settings (
    key    text primary key,
    value  text
);

create table if not exists saved_leagues (
    league_id    bigint primary key,
    league_name  text not null,
    added_at     timestamptz not null default now()
);

-- Seed with the one league already confirmed working during development.
-- Add more via the Discovery panel's "+ Add league" form - the Pinnacle
-- league id isn't visible anywhere in the UI, only in the network tab on
-- pinnacle.com (inspect a league's odds request URL).
insert into saved_leagues (league_id, league_name) values
    (1980, 'England - Premier League')
on conflict (league_id) do nothing;
