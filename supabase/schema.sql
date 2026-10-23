-- F&O Desk: run this once in Supabase -> SQL Editor -> New query -> Run.
-- Creates the tables, locks your trades and the desk data to vs916491@gmail.com,
-- and loads your 26 earlier trades into My Trades.

-- ------------------------------------------------------------ market data (written by GitHub Actions)
create table if not exists public.docs (
  key text primary key,
  data jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists public.chain_snap (
  id bigserial primary key,
  ts timestamp not null, symbol text not null, expiry date not null, kind text, spot double precision,
  strike double precision, ce_oi double precision, ce_coi double precision, ce_ltp double precision,
  ce_iv double precision, ce_vol double precision, pe_oi double precision, pe_coi double precision,
  pe_ltp double precision, pe_iv double precision, pe_vol double precision
);
create index if not exists chain_snap_lookup on public.chain_snap (symbol, expiry, ts);
create index if not exists chain_snap_ts on public.chain_snap (ts);

create table if not exists public.fut_snap (
  id bigserial primary key,
  ts timestamp not null, symbol text not null, expiry date not null,
  ltp double precision, prev_close double precision, pchange double precision,
  oi double precision, coi double precision
);
create index if not exists fut_snap_lookup on public.fut_snap (symbol, ts);

create table if not exists public.pcr_hist (
  id bigserial primary key,
  ts timestamp not null, symbol text not null, kind text not null, expiry date,
  pcr double precision, ce_oi double precision, pe_oi double precision, spot double precision,
  combined boolean default false
);
create index if not exists pcr_hist_lookup on public.pcr_hist (symbol, kind, ts);

create table if not exists public.swing_history (
  day date not null, symbol text not null, ts timestamp, direction text, strength text,
  score double precision, spot double precision, signal jsonb,
  primary key (day, symbol)
);

-- ------------------------------------------------------------ My Trades
create table if not exists public.trades (
  id bigserial primary key,
  kind text not null default 'stock' check (kind in ('stock', 'index')),
  symbol text not null,
  side text not null check (side in ('Long', 'Short')),
  entry_time timestamp, entry double precision, stop double precision, target double precision,
  exit_time timestamp, exit double precision, exit_reason text,
  status text not null default 'open' check (status in ('open', 'closed')),
  net_pct_after_cost double precision, pnl_inr double precision,
  qty double precision, lots integer, lot_size integer, charges double precision default 0,
  instrument text, expiry date, method text, source text, notes text,
  owner text default (auth.jwt() ->> 'email'),
  created_at timestamptz not null default now()
);

-- ------------------------------------------------------------ access rules
-- Only vs916491@gmail.com (signed in on the website) can read the desk and read/write trades.
-- GitHub Actions uses the service key, which bypasses these rules.
alter table public.docs enable row level security;
alter table public.trades enable row level security;
alter table public.chain_snap enable row level security;
alter table public.fut_snap enable row level security;
alter table public.pcr_hist enable row level security;
alter table public.swing_history enable row level security;

drop policy if exists "owner reads desk" on public.docs;
create policy "owner reads desk" on public.docs for select to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');

drop policy if exists "owner reads history" on public.swing_history;
create policy "owner reads history" on public.swing_history for select to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');

drop policy if exists "owner manages trades" on public.trades;
create policy "owner manages trades" on public.trades for all to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com')
  with check ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');

-- ------------------------------------------------------------ your earlier trades (25 Sep - 21 Oct 2026)
delete from public.trades where source in ('scanner', 'manual') and entry_time < '2026-10-22' and owner = 'vs916491@gmail.com';
insert into public.trades (kind, symbol, side, entry_time, entry, stop, target, exit_time, exit, exit_reason, status, net_pct_after_cost, source, notes, owner) values
  ('stock', 'ONGC', 'Short', '2026-09-25T15:03', 235.26, 238.0, 230.0, '2026-09-28T11:36', 232.0, 'Target hit', 'closed', 1.256, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'RECLTD', 'Long', '2026-09-25T15:04', 311.2, 307.0, 330.0, '2026-09-28T09:15', 307.0, 'stop hit (auto)', 'closed', -1.48, 'scanner', '50MA Breakout + OI Builtup', 'vs916491@gmail.com'),
  ('stock', 'BHEL', 'Long', '2026-09-25T15:15', 420.0, 411.0, 445.0, '2026-09-28T09:15', 415.0, 'stop hit (auto)', 'closed', -1.32, 'scanner', 'Clean Breakout in 50 MA', 'vs916491@gmail.com'),
  ('stock', 'CANBK', 'Short', '2026-09-28T10:15', 121.98, 124.43, 117.07, '2026-09-30T11:17', 118.0, 'closed by hand', 'closed', 3.133, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'BANKBARODA', 'Short', '2026-09-28T10:15', 231.01, 234.0, 222.68, '2026-09-28T14:34', 228.0, 'closed by hand', 'closed', 1.173, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'BOSCHLTD', 'Short', '2026-09-28T10:15', 47600.0, 48048.0, 46000.0, null, 46900.0, 'closed by hand', 'closed', 1.341, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'POWERGRID', 'Short', '2026-09-28T10:31', 265.0, 270.0, 250.0, '2026-09-28T14:23', 263.0, 'closed by hand', 'closed', 0.625, 'manual', null, 'vs916491@gmail.com'),
  ('stock', 'PREMIERENE', 'Long', '2026-09-28T14:15', 908.1, 901.8, 920.71, '2026-09-29T09:15', 901.8, 'stop hit (auto)', 'closed', -0.824, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'ADANIGREEN', 'Long', '2026-09-30T10:15', 1276.3, 1251.45, 1326.01, null, 1278.0, 'closed by hand', 'closed', 0.003, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'DMART', 'Long', '2026-09-30T10:15', 3858.8, 3806.09, 3964.22, '2026-09-30T14:15', 3806.09, 'stop hit (auto)', 'closed', -1.496, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'AXISBANK', 'Long', '2026-09-30T11:15', 1220.7, 1212.79, 1236.53, '2026-09-30T13:15', 1236.53, 'target hit (auto)', 'closed', 1.167, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'PNBHOUSING', 'Long', '2026-09-30T13:15', 1121.9, 1076.0, 1191.0, null, 1110.0, 'closed by hand', 'closed', -1.191, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'PRESTIGE', 'Long', '2026-09-30T13:15', 1469.7, 1420.0, 1600.0, null, 1500.0, 'closed by hand', 'closed', 1.932, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'ENRIN', 'Long', '2026-10-01T10:15', 3302.7, 3187.81, 3532.48, '2026-10-05T09:35', 3400.0, 'closed by hand', 'closed', 2.816, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'HDFCLIFE', 'Short', '2026-10-05T10:15', 530.0, 537.09, 517.0, '2026-10-05T10:30', 525.0, 'closed by hand', 'closed', 0.813, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'CAMS', 'Long', '2026-10-06T13:15', 688.05, 675.0, 724.0, '2026-10-07T11:16', 705.0, 'closed by hand', 'closed', 2.333, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'BANKBARODA', 'Long', '2026-10-07T11:15', 234.0, 231.59, 239.72, '2026-10-08T09:57', 240.0, 'closed by hand', 'closed', 2.434, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'ADANIENSOL', 'Short', '2026-10-07T12:15', 1342.5, 1357.86, 1311.79, null, 1311.0, 'closed by hand', 'closed', 2.216, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'ITC', 'Short', '2026-10-07T13:15', 263.4, 266.37, 257.47, '2026-10-08T09:27', 258.0, 'closed by hand', 'closed', 1.92, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'ICICIPRULI', 'Short', '2026-10-07T13:15', 455.2, 458.96, 447.68, '2026-10-08T09:29', 452.0, 'closed by hand', 'closed', 0.573, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'PFC', 'Short', '2026-10-08T13:15', 325.4, 328.73, 318.74, '2026-10-09T10:13', 324.0, 'closed by hand', 'closed', 0.3, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'WAAREEENER', 'Long', '2026-10-13T10:15', 2402.0, 2327.87, 2550.26, null, 2535.0, 'closed by hand', 'closed', 5.407, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'TMPV', 'Short', '2026-10-19T12:15', 281.2, 284.83, 273.93, null, 276.0, 'closed by hand', 'closed', 1.719, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'TITAN', 'Short', '2026-10-19T12:15', 4424.5, 4477.47, 4318.55, null, 4400.0, 'closed by hand', 'closed', 0.424, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'FORCEMOT', 'Short', '2026-10-21T10:15', 17211.0, 17661.64, 16309.71, null, 16800.0, 'closed by hand', 'closed', 2.258, 'scanner', null, 'vs916491@gmail.com'),
  ('stock', 'SUZLON', 'Short', '2026-10-21T10:15', 39.52, 40.32, 37.92, null, 39.0, 'closed by hand', 'closed', 1.186, 'scanner', null, 'vs916491@gmail.com');
