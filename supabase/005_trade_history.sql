-- F&O Desk, update 5: keep closed-trade details for 3 months, monthly summary forever.
-- Every night (02:00 IST) closed trades older than 3 months - by the date they
-- were closed - are added to a month-by-month summary and then removed. The
-- websites' "Month by month" tables and totals include the summary, so nothing
-- is lost from the statistics. Applies to the F&O Desk trades and to Sector
-- Strength's My Trades.
-- Run once in Supabase -> SQL Editor -> New query -> Run.

create table if not exists public.trade_months (
  book text not null check (book in ('fno', 'cash')),   -- fno = F&O Desk, cash = Sector Strength My Trades
  month text not null,                                   -- YYYY-MM, month the trades were closed
  kind text not null,                                    -- stock / index (F&O Desk), cash (Sector Strength)
  trades integer not null default 0,
  pct_count integer not null default 0,                  -- trades with a % result
  wins integer not null default 0,                       -- % result above 0
  sum_pct double precision not null default 0,
  gain_pct double precision not null default 0,          -- sum of winning %
  loss_pct double precision not null default 0,          -- sum of losing % (0 or below)
  inr_count integer not null default 0,                  -- trades with a rupee result
  pnl_inr double precision not null default 0,
  invested double precision not null default 0,          -- buy value (cash trades), for net %
  updated_at timestamptz not null default now(),
  primary key (book, month, kind)
);
alter table public.trade_months enable row level security;
drop policy if exists "owner reads trade months" on public.trade_months;
create policy "owner reads trade months" on public.trade_months for select to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');

create or replace function public.archive_old_trades(keep interval default interval '3 months')
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  n1 integer := 0;
  n2 integer := 0;
begin
  -- F&O Desk trades: summarise and remove in one statement, so nothing is counted twice
  with old as (
    delete from public.trades
    where status = 'closed' and coalesce(exit_time, entry_time) < (now() at time zone 'Asia/Kolkata') - keep
    returning *
  ), agg as (
    select 'fno'::text as book, to_char(coalesce(exit_time, entry_time), 'YYYY-MM') as month, kind,
           count(*)::int as trades,
           count(net_pct_after_cost)::int as pct_count,
           count(*) filter (where net_pct_after_cost > 0)::int as wins,
           coalesce(sum(net_pct_after_cost), 0) as sum_pct,
           coalesce(sum(net_pct_after_cost) filter (where net_pct_after_cost > 0), 0) as gain_pct,
           coalesce(sum(net_pct_after_cost) filter (where net_pct_after_cost <= 0), 0) as loss_pct,
           count(pnl_inr)::int as inr_count,
           coalesce(sum(pnl_inr), 0) as pnl_inr,
           0::double precision as invested
    from old group by 2, 3
  )
  insert into public.trade_months as m (book, month, kind, trades, pct_count, wins, sum_pct, gain_pct, loss_pct, inr_count, pnl_inr, invested)
  select * from agg
  on conflict (book, month, kind) do update set
    trades = m.trades + excluded.trades, pct_count = m.pct_count + excluded.pct_count,
    wins = m.wins + excluded.wins, sum_pct = m.sum_pct + excluded.sum_pct,
    gain_pct = m.gain_pct + excluded.gain_pct, loss_pct = m.loss_pct + excluded.loss_pct,
    inr_count = m.inr_count + excluded.inr_count, pnl_inr = m.pnl_inr + excluded.pnl_inr,
    invested = m.invested + excluded.invested, updated_at = now();
  get diagnostics n1 = row_count;

  -- Sector Strength My Trades (cash)
  with old as (
    delete from public.cash_trades
    where status = 'closed' and exit_date < ((now() at time zone 'Asia/Kolkata') - keep)::date
    returning *
  ), agg as (
    select 'cash'::text as book, to_char(exit_date, 'YYYY-MM') as month, 'cash'::text as kind,
           count(*)::int as trades,
           count(net_pct)::int as pct_count,
           count(*) filter (where net_pct > 0)::int as wins,
           coalesce(sum(net_pct), 0) as sum_pct,
           coalesce(sum(net_pct) filter (where net_pct > 0), 0) as gain_pct,
           coalesce(sum(net_pct) filter (where net_pct <= 0), 0) as loss_pct,
           count(pnl_inr)::int as inr_count,
           coalesce(sum(pnl_inr), 0) as pnl_inr,
           coalesce(sum(entry * qty), 0) as invested
    from old group by 2
  )
  insert into public.trade_months as m (book, month, kind, trades, pct_count, wins, sum_pct, gain_pct, loss_pct, inr_count, pnl_inr, invested)
  select * from agg
  on conflict (book, month, kind) do update set
    trades = m.trades + excluded.trades, pct_count = m.pct_count + excluded.pct_count,
    wins = m.wins + excluded.wins, sum_pct = m.sum_pct + excluded.sum_pct,
    gain_pct = m.gain_pct + excluded.gain_pct, loss_pct = m.loss_pct + excluded.loss_pct,
    inr_count = m.inr_count + excluded.inr_count, pnl_inr = m.pnl_inr + excluded.pnl_inr,
    invested = m.invested + excluded.invested, updated_at = now();
  get diagnostics n2 = row_count;
  return n1 + n2;
end;
$$;
revoke all on function public.archive_old_trades(interval) from public, anon, authenticated;

-- every night at 02:00 IST (20:30 UTC)
do $$ begin
  if exists (select 1 from cron.job where jobname = 'archive-old-trades') then
    perform cron.unschedule('archive-old-trades');
  end if;
end $$;
select cron.schedule('archive-old-trades', '30 20 * * *', $$select public.archive_old_trades()$$);
