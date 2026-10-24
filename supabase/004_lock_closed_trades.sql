-- F&O Desk, update 4: closed trades are locked.
-- Open trades can still be edited and closed; once a trade is closed, the
-- website can no longer change it (on either site). Deleting is still allowed.
-- The evening/15-minute jobs use the service key and are not affected.
-- Run once in Supabase -> SQL Editor -> New query -> Run.

-- F&O Desk trades
drop policy if exists "owner manages trades" on public.trades;
drop policy if exists "owner reads trades" on public.trades;
drop policy if exists "owner adds trades" on public.trades;
drop policy if exists "owner edits open trades" on public.trades;
drop policy if exists "owner deletes trades" on public.trades;
create policy "owner reads trades" on public.trades for select to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');
create policy "owner adds trades" on public.trades for insert to authenticated
  with check ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');
create policy "owner edits open trades" on public.trades for update to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com' and status = 'open')
  with check ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');
create policy "owner deletes trades" on public.trades for delete to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');

-- Sector Strength "My Trades" (cash trades)
drop policy if exists "owner manages cash trades" on public.cash_trades;
drop policy if exists "owner reads cash trades" on public.cash_trades;
drop policy if exists "owner adds cash trades" on public.cash_trades;
drop policy if exists "owner edits open cash trades" on public.cash_trades;
drop policy if exists "owner deletes cash trades" on public.cash_trades;
create policy "owner reads cash trades" on public.cash_trades for select to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');
create policy "owner adds cash trades" on public.cash_trades for insert to authenticated
  with check ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');
create policy "owner edits open cash trades" on public.cash_trades for update to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com' and status = 'open')
  with check ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');
create policy "owner deletes cash trades" on public.cash_trades for delete to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');
