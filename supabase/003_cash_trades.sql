-- F&O Desk, update 3: "My Trades" journal for cash-market positional trades
-- (used by the Sector Strength website). Run once in Supabase -> SQL Editor -> New query -> Run.

create table if not exists public.cash_trades (
  id bigserial primary key,
  symbol text not null,
  entry_date date not null,
  entry double precision not null,
  qty double precision not null,
  stop double precision,
  target double precision,
  exit_rule text not null default 'system' check (exit_rule in ('system', 'stop_target', 'manual')),
  setup text, grade text, sector text, source text, notes text,
  charges double precision,
  status text not null default 'open' check (status in ('open', 'closed')),
  exit_date date, exit double precision, exit_reason text,
  pnl_inr double precision, net_pct double precision,
  last_close double precision, last_date date, sma50 double precision,
  sessions_held integer, alert text,
  owner text default (auth.jwt() ->> 'email'),
  created_at timestamptz not null default now()
);
create index if not exists cash_trades_status on public.cash_trades (status, entry_date);

alter table public.cash_trades enable row level security;
drop policy if exists "owner manages cash trades" on public.cash_trades;
create policy "owner manages cash trades" on public.cash_trades for all to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com')
  with check ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');
