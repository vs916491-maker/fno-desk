-- F&O Desk, update 8: start the Sector Strength evening update on time.
-- GitHub's own timer for that job is "best effort" and can start late or not at
-- all; these Supabase timers start it on the minute, like the F&O Desk jobs.
-- Before running: your GitHub token (stored in Vault as 'github_token') must
-- also have access to the Nifty-sector-strength repo with Actions: Read and write.
-- Run once in Supabase -> SQL Editor -> New query -> Run.

create or replace function public.dispatch_repo_workflow(repo text, wf text)
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
    url := 'https://api.github.com/repos/vs916491-maker/' || repo || '/actions/workflows/' || wf || '/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || tok,
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'fno-desk',
      'Content-Type', 'application/json'),
    body := jsonb_build_object('ref', 'main')
  );
end;
$$;
revoke all on function public.dispatch_repo_workflow(text, text) from public, anon, authenticated;

-- 19:20 and 22:20 IST, Monday to Friday (13:50 and 16:50 UTC)
do $$
declare j record;
begin
  for j in select jobname from cron.job where jobname like 'sector-eod-%' loop
    perform cron.unschedule(j.jobname);
  end loop;
end $$;
select cron.schedule('sector-eod-1', '50 13 * * 1-5',
  $$select public.dispatch_repo_workflow('Nifty-sector-strength', 'update-data.yml')$$);
select cron.schedule('sector-eod-2', '50 16 * * 1-5',
  $$select public.dispatch_repo_workflow('Nifty-sector-strength', 'update-data.yml')$$);

-- one test call now (the update finds nothing new and simply refreshes)
select public.dispatch_repo_workflow('Nifty-sector-strength', 'update-data.yml') as test_request_id;
