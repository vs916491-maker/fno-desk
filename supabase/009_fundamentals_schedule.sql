-- F&O Desk, update 9: start the Fundamentals Desk daily collection on time.
-- GitHub's own timer skipped all of its slots on 26 Oct; these Supabase timers
-- start the job on the minute. Before running: your GitHub token must also have
-- access to the NSE-fundamentals-desk repo with Actions: Read and write.
-- Run once in Supabase -> SQL Editor -> New query -> Run.

-- same as dispatch_repo_workflow (update 8) but can pass workflow inputs
create or replace function public.dispatch_repo_workflow_inputs(repo text, wf text, inputs jsonb)
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
    body := jsonb_build_object('ref', 'main', 'inputs', inputs)
  );
end;
$$;
revoke all on function public.dispatch_repo_workflow_inputs(text, text, jsonb) from public, anon, authenticated;

do $$
declare j record;
begin
  for j in select jobname from cron.job where jobname like 'fundamentals-%' loop
    perform cron.unschedule(j.jobname);
  end loop;
end $$;
-- every day 18:50 IST with the daily email (13:20 UTC), 23:30 IST catch-up for late filers (18:00 UTC)
select cron.schedule('fundamentals-evening', '20 13 * * *',
  $$select public.dispatch_repo_workflow_inputs('NSE-fundamentals-desk', 'collect.yml', '{"args": "--email"}'::jsonb)$$);
select cron.schedule('fundamentals-late', '0 18 * * *',
  $$select public.dispatch_repo_workflow_inputs('NSE-fundamentals-desk', 'collect.yml', '{"args": ""}'::jsonb)$$);
