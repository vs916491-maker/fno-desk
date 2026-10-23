-- F&O Desk, update 2: "Run scanner" button, on-time schedules, swing setup log.
-- Run once in Supabase -> SQL Editor -> New query -> Run,
-- AFTER storing your GitHub token (see the separate one-line step).

create extension if not exists pg_net;
create extension if not exists pg_cron;

-- ------------------------------------------------------------ start a GitHub job
-- Calls GitHub's API to start a workflow in the fno-desk repo, using the token
-- you stored in Supabase Vault under the name 'github_token'.
create or replace function public.dispatch_workflow(wf text, force boolean default false)
returns bigint
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  tok text;
begin
  select decrypted_secret into tok from vault.decrypted_secrets where name = 'github_token' limit 1;
  if tok is null then
    raise warning 'github_token is not stored in Vault';
    return null;
  end if;
  return net.http_post(
    url := 'https://api.github.com/repos/vs916491-maker/fno-desk/actions/workflows/' || wf || '/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || tok,
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'fno-desk',
      'Content-Type', 'application/json'),
    body := jsonb_build_object('ref', 'main', 'inputs', jsonb_build_object('force', case when force then 'true' else 'false' end))
  );
end;
$$;
revoke all on function public.dispatch_workflow(text, boolean) from public, anon, authenticated;

-- ------------------------------------------------------------ "Run scanner" requests from the website
create table if not exists public.scan_requests (
  id bigserial primary key,
  kind text not null default 'screener' check (kind in ('screener', 'snapshot')),
  status text,
  created_at timestamptz not null default now(),
  owner text default (auth.jwt() ->> 'email')
);
alter table public.scan_requests enable row level security;
drop policy if exists "owner requests scans" on public.scan_requests;
create policy "owner requests scans" on public.scan_requests for all to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com')
  with check ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');

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
      case new.kind when 'snapshot' then 'index-snapshot.yml' else 'stock-screener.yml' end, true);
    new.status := 'sent';
  end if;
  return new;
end;
$$;
drop trigger if exists scan_request_dispatch on public.scan_requests;
create trigger scan_request_dispatch before insert on public.scan_requests
  for each row execute function public.on_scan_request();

-- ------------------------------------------------------------ on-time schedules (times in UTC = IST - 5:30)
-- GitHub's own schedules can start 10-30 minutes late; these start the jobs on the minute.
do $$
declare j record;
begin
  for j in select jobname from cron.job where jobname like 'fno-%' loop
    perform cron.unschedule(j.jobname);
  end loop;
end $$;
-- index snapshot every 15 minutes, 09:15-15:30 IST, Monday-Friday
select cron.schedule('fno-snapshot-open',  '45 3 * * 1-5',     $$select public.dispatch_workflow('index-snapshot.yml', false)$$);
select cron.schedule('fno-snapshot-day',   '*/15 4-9 * * 1-5', $$select public.dispatch_workflow('index-snapshot.yml', false)$$);
select cron.schedule('fno-snapshot-close', '0 10 * * 1-5',     $$select public.dispatch_workflow('index-snapshot.yml', false)$$);
-- stock scan 4 minutes after each hourly candle closes: 10:19 ... 15:19 and 15:34 IST
select cron.schedule('fno-screener-hourly', '49 4-9 * * 1-5',  $$select public.dispatch_workflow('stock-screener.yml', false)$$);
select cron.schedule('fno-screener-close',  '4 10 * * 1-5',    $$select public.dispatch_workflow('stock-screener.yml', false)$$);

-- ------------------------------------------------------------ swing setups as they form during the day
create table if not exists public.swing_events (
  id bigserial primary key,
  ts timestamp not null,
  day date not null,
  symbol text not null,
  direction text not null,          -- LONG, SHORT, or ENDED (setup dropped back to no trade)
  strength text,
  score double precision,
  spot double precision,
  signal jsonb
);
create index if not exists swing_events_day on public.swing_events (day, symbol, ts);
alter table public.swing_events enable row level security;
drop policy if exists "owner reads setups" on public.swing_events;
create policy "owner reads setups" on public.swing_events for select to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');
