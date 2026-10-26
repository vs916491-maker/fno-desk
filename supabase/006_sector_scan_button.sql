-- F&O Desk, update 6: "Run scan" button on the Sector Strength website.
-- Lets the scan_requests table start the Sector Strength intraday scan
-- (workflow sector-intraday.yml in the fno-desk repo, which already has your
-- GitHub token and database keys). Same 3-minute throttle as the other buttons.
-- Run once in Supabase -> SQL Editor -> New query -> Run.

alter table public.scan_requests drop constraint if exists scan_requests_kind_check;
alter table public.scan_requests add constraint scan_requests_kind_check
  check (kind in ('screener', 'snapshot', 'sector'));

create or replace function public.on_scan_request()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  -- one run per kind every 3 minutes, so repeated clicks don't stack up jobs
  if exists (select 1 from public.scan_requests
             where kind = new.kind and status = 'sent' and created_at > now() - interval '3 minutes') then
    new.status := 'skipped';
  else
    perform public.dispatch_workflow(
      case new.kind when 'snapshot' then 'index-snapshot.yml'
                    when 'sector' then 'sector-intraday.yml'
                    else 'stock-screener.yml' end, true);
    new.status := 'sent';
  end if;
  return new;
end;
$$;
