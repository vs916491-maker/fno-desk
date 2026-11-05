-- F&O Desk, update 11: a trade closed by mistake can be fixed until the 7:40 pm check.
-- Replaces the full lock from update 4 with a short window:
--   * A trade you close by hand on either website can be edited or re-opened until
--     19:40 IST on the next weekday check (closed at 12:30 Thu -> until 19:40 Thu;
--     closed at 21:00 Fri -> until 19:40 Mon). After that it is locked as before.
--   * Trades closed by the jobs (stop, target, 5 sessions) are locked at once.
--   * Editing a closed trade never extends its window.
-- Applies to both books: F&O Desk "trades" and Sector Strength "cash_trades".
-- Run once in Supabase -> SQL Editor -> New query -> Run.

-- 1. When each trade was closed by hand (null = closed by a job, or before this update)
alter table public.trades add column if not exists closed_at timestamptz;
alter table public.cash_trades add column if not exists closed_at timestamptz;

-- Sector Strength trades sold today (before this update existed) get today's window too
update public.cash_trades set closed_at = now()
where status = 'closed' and closed_at is null
  and exit_date = (now() at time zone 'Asia/Kolkata')::date;

-- 2. The deadline: the first weekday 19:40 IST after the trade was closed
create or replace function public.trade_fix_until(closed timestamptz)
returns timestamptz
language sql
stable
set search_path = public
as $$
  with c as (select (closed at time zone 'Asia/Kolkata') as ist)
  select min((d::date + time '19:40') at time zone 'Asia/Kolkata')
  from c, generate_series(c.ist::date::timestamp, (c.ist::date + 4)::timestamp, interval '1 day') as d
  where c.ist is not null
    and extract(isodow from d) < 6
    and (d::date + time '19:40') > c.ist;
$$;

-- 3. Set closed_at automatically (the websites never send it)
create or replace function public.trade_set_closed_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if new.status = 'closed' then
    if tg_op = 'UPDATE' and old.status = 'closed' then
      new.closed_at := old.closed_at;                       -- an edit keeps the original window
    elsif coalesce(auth.role(), '') = 'authenticated' then
      new.closed_at := now();                               -- closed by hand on a website
    else
      new.closed_at := null;                                -- closed by a job: locked at once
    end if;
  else
    new.closed_at := null;                                  -- open (or re-opened)
  end if;
  return new;
end;
$$;

drop trigger if exists trades_closed_at on public.trades;
create trigger trades_closed_at before insert or update on public.trades
  for each row execute function public.trade_set_closed_at();
drop trigger if exists cash_trades_closed_at on public.cash_trades;
create trigger cash_trades_closed_at before insert or update on public.cash_trades
  for each row execute function public.trade_set_closed_at();

-- 4. The websites may update open trades, and closed ones only inside the window
drop policy if exists "owner edits open trades" on public.trades;
drop policy if exists "owner edits open or just-closed trades" on public.trades;
create policy "owner edits open or just-closed trades" on public.trades for update to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com'
         and (status = 'open' or now() < public.trade_fix_until(closed_at)))
  with check ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');

drop policy if exists "owner edits open cash trades" on public.cash_trades;
drop policy if exists "owner edits open or just-closed cash trades" on public.cash_trades;
create policy "owner edits open or just-closed cash trades" on public.cash_trades for update to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com'
         and (status = 'open' or now() < public.trade_fix_until(closed_at)))
  with check ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');

-- Check: closed trades you can still fix right now
-- select id, symbol, exit_date, closed_at, public.trade_fix_until(closed_at) as fix_until
-- from public.cash_trades where now() < public.trade_fix_until(closed_at);
