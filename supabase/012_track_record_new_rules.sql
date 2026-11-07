-- F&O Desk, update 12 (7 Nov 2026): Track record follows the current screener rules only.
-- Deletes the old 50 EMA cross rows from signal_log. New rows (Price Action "pa|...", Base 3 "pb3|...",
-- Price+OI "po|...") are kept. The job no longer writes old-rule rows, and the website
-- ignores any that are left, so this only tidies the table. It cannot be undone.
-- Run once in Supabase -> SQL Editor -> New query -> Run.

-- 1. Check first: how many rows of each kind
select coalesce(info ->> 'rules', 'old') as rules, kind, count(*) as rows
from public.signal_log
group by 1, 2
order by 1, 2;

-- 2. Delete the old-rule rows
delete from public.signal_log
where coalesce(info ->> 'rules', 'old') not in ('pa', 'po', 'pb3');

-- 3. Results of the new rules can now also be 'unclear' (stop and 1:2 target in one candle)
comment on column public.signal_log.result is 'target | stop | time | unclear (new rules); ema_exit only on deleted old rows';
