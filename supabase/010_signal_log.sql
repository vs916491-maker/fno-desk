-- F&O Desk, update 10: signal log for the Track record tab.
-- Every stock-screener idea (and every 50 EMA signal rejected only because the
-- day's futures build-up was against it) is saved the first time a scan lists it,
-- with its score parts, signal-hour OI and warnings. Later scans fill in the
-- result: result/net_pct/r_mult use the strategy's exits (stop, 1:2 target, close
-- back across the 50 EMA, or 5 sessions); alt_* use only stop, target and 5
-- sessions (how My trades closes your trades). The jobs write with the service
-- key; the website only reads.
-- Run once in Supabase -> SQL Editor -> New query -> Run.

create table if not exists public.signal_log (
  id bigserial primary key,
  key text not null unique,                 -- symbol|side|signal candle start
  symbol text not null,
  side text not null check (side in ('Long', 'Short')),
  signal_time timestamp not null,           -- signal candle start, IST
  scan_ts timestamp,                        -- scan that first listed it, IST
  kind text not null check (kind in ('idea', 'rejected')),
  top_rank int,                             -- live Top 5 rank in that scan
  rank_v2 int,                              -- rank by the proposed score
  score numeric,
  score_v2 numeric,
  entry numeric,
  stop numeric,
  target numeric,
  info jsonb not null default '{}'::jsonb,  -- warnings, signal-hour OI, context, score parts
  result text,                              -- target | stop | ema_exit | time
  exit_price numeric,
  exit_time timestamp,
  net_pct numeric,                          -- after 0.1% costs
  r_mult numeric,
  alt_result text,
  alt_net_pct numeric,
  alt_r_mult numeric,
  mfe_r numeric,                            -- best move in R while the trade was open
  mae_r numeric,                            -- worst move in R
  done boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists signal_log_time on public.signal_log (signal_time desc);
create index if not exists signal_log_open on public.signal_log (done) where not done;

alter table public.signal_log enable row level security;
drop policy if exists "owner reads signal log" on public.signal_log;
create policy "owner reads signal log" on public.signal_log for select to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');
