-- F&O Desk, update 7: Watchlist tab.
-- Ideas from the stock screener or the suggested index trades can be moved to
-- a watchlist (Long or Short). Each entry stays for 3 market days after the
-- day it was added and is then removed automatically (every night at 02:05 IST).
-- Run once in Supabase -> SQL Editor -> New query -> Run.

create table if not exists public.watchlist (
  id bigserial primary key,
  kind text not null default 'stock' check (kind in ('stock', 'index')),
  symbol text not null,
  side text not null check (side in ('Long', 'Short')),
  added_at timestamptz not null default now(),
  expires_on date not null,                 -- last market day it is kept
  entry double precision, stop double precision, target double precision,
  lot_size integer, expiry date, method text, source text, notes text,
  signal_time text,
  owner text default (auth.jwt() ->> 'email')
);
create index if not exists watchlist_expires on public.watchlist (expires_on);

alter table public.watchlist enable row level security;
drop policy if exists "owner manages watchlist" on public.watchlist;
create policy "owner manages watchlist" on public.watchlist for all to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com')
  with check ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');

-- nightly clean-up of entries past their last day (02:05 IST = 20:35 UTC)
do $$ begin
  if exists (select 1 from cron.job where jobname = 'watchlist-cleanup') then
    perform cron.unschedule('watchlist-cleanup');
  end if;
end $$;
select cron.schedule('watchlist-cleanup', '35 20 * * *',
  $$delete from public.watchlist where expires_on < (now() at time zone 'Asia/Kolkata')::date$$);
