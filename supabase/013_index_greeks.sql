-- F&O Desk, update 13 (22 Nov 2026): Greeks engine, Index Track Record, My Index Trades.
--   greeks_hist   compact Greeks reading of every chain at every 15-minute snapshot
--                 (ATM IV, 25-delta skew, gamma walls, India VIX), kept 400 days
--   index_ideas   every Suggested index trades idea that passed its checks, filled at the
--                 next snapshot and closed by its own rules (Index Track Record tab)
--   index_trades  your own multi-leg index trades with futures hedges (My Index Trades tab)
-- Run once in Supabase -> SQL Editor -> New query -> Run. Safe to run again.

create table if not exists public.greeks_hist (
  id bigserial primary key,
  ts timestamp not null, symbol text not null, expiry date not null, kind text,
  spot double precision, fwd double precision, atm_iv double precision, rr25 double precision,
  call_wall double precision, put_wall double precision, pin double precision, vix double precision
);
create index if not exists greeks_hist_lookup on public.greeks_hist (symbol, expiry, ts);
create index if not exists greeks_hist_ts on public.greeks_hist (ts);

create table if not exists public.index_ideas (
  id bigserial primary key,
  key text not null unique,                 -- day|mode|symbol|strategy|bias
  day date not null,
  mode text not null check (mode in ('swing', 'intraday')),
  symbol text not null,
  strategy text not null,
  name text,
  bias text,                                -- LONG, SHORT or NEUTRAL
  score numeric,
  strength text,
  logged_ts timestamp not null,             -- snapshot that showed the idea
  entry_ts timestamp,                       -- next snapshot: filled at its prices
  status text not null default 'pending' check (status in ('pending', 'open', 'closed', 'void')),
  lot_size int,
  legs jsonb not null default '[]'::jsonb,  -- action, type, strike, expiry, ltp (when logged), entry (fill), now
  hedges jsonb not null default '[]'::jsonb,-- delta hedges: ts, qty (futures, + bought), price
  rules jsonb not null default '{}'::jsonb, -- stop_pnl, target_pnl (points per unit) or spot_stop/target, time_exit, delta_hedge
  info jsonb not null default '{}'::jsonb,  -- best idea?, fit, volatility and gamma regime, factor points
  entry_net numeric, entry_spot numeric,
  last_pnl_inr numeric, last_ts timestamp, mfe_inr numeric, mae_inr numeric,
  exit_ts timestamp, exit_reason text, exit_spot numeric,
  pnl_pts numeric, pnl_inr numeric, r_mult numeric,
  created_at timestamptz not null default now()
);
create index if not exists index_ideas_day on public.index_ideas (day desc);
create index if not exists index_ideas_status on public.index_ideas (status);

create table if not exists public.index_trades (
  id bigserial primary key,
  symbol text not null,
  mode text,                                -- swing / intraday / manual
  strategy text, name text,
  entry_time timestamp not null,
  legs jsonb not null default '[]'::jsonb,  -- action, type (CE/PE/FUT), strike, expiry, lots, entry
  hedges jsonb not null default '[]'::jsonb,-- futures hedges you added: time, action, type FUT, lots, entry, expiry
  lot_size int,
  stop_inr numeric, target_inr numeric,     -- auto-close at this loss / profit (rupees, whole position)
  time_exit timestamp,                      -- auto-close at this time
  delta_hedge boolean default false,
  status text not null default 'open' check (status in ('open', 'closed')),
  exit_time timestamp, exit_reason text,
  exit_px jsonb,                            -- exit price of each leg, then each hedge
  pnl_inr numeric, charges numeric default 0,
  source text, notes text,
  owner text default (auth.jwt() ->> 'email'),
  closed_at timestamptz,
  created_at timestamptz not null default now()
);

alter table public.greeks_hist enable row level security;
alter table public.index_ideas enable row level security;
alter table public.index_trades enable row level security;

drop policy if exists "owner reads greeks" on public.greeks_hist;
create policy "owner reads greeks" on public.greeks_hist for select to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');
drop policy if exists "owner reads index ideas" on public.index_ideas;
create policy "owner reads index ideas" on public.index_ideas for select to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');

drop policy if exists "owner reads index trades" on public.index_trades;
drop policy if exists "owner adds index trades" on public.index_trades;
drop policy if exists "owner edits open or just-closed index trades" on public.index_trades;
drop policy if exists "owner deletes open index trades" on public.index_trades;
create policy "owner reads index trades" on public.index_trades for select to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');
create policy "owner adds index trades" on public.index_trades for insert to authenticated
  with check ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');
-- same rule as My Stock Trades: a trade you close by hand can be fixed until the next weekday 19:40 IST
create policy "owner edits open or just-closed index trades" on public.index_trades for update to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com'
         and (status = 'open' or now() < public.trade_fix_until(closed_at)))
  with check ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');
create policy "owner deletes open index trades" on public.index_trades for delete to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com' and status = 'open');

drop trigger if exists index_trades_closed_at on public.index_trades;
create trigger index_trades_closed_at before insert or update on public.index_trades
  for each row execute function public.trade_set_closed_at();
