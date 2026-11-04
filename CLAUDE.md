# F&O Desk — project notes

Owner: Vivek (GitHub `vs916491-maker`). Personal analysis only, not investment advice.
Repo: `vs916491-maker/fno-desk` (public). Site: GitHub Pages, behind email + password sign-in.

## What it is
One website combining the F&O stock screener and the index OI desk. Cloud-only: GitHub Actions collects data, Supabase stores it, GitHub Pages shows it. No laptop needed.

## Tabs
| Tab | What it shows | Updates |
|---|---|---|
| F&O stock screener (`#/stocks`) | Hourly 50 EMA cross + futures OI build-up; Top 5 (candle clarity 60% + OI change 40% + sector boost); "I took this trade"; Run scanner button | after each hourly candle (~:20 past, 10:20–15:20, and 15:35) |
| F&O index analysis (`#/index`) | Index cards, warnings (squeeze, expiry), NIFTY intraday trend scale, hourly PCR (monthly + weekly), futures OI | every 15 min, 09:15–15:30 |
| Option chain (`#/chain`) | NIFTY, SENSEX, BANKNIFTY, FINNIFTY, MIDCPNIFTY: OI, change in OI, LTP, IV, PCR, max pain, walls | every 15 min |
| Suggested index trades (`#/swing`) | Swing only (monthly chain, up to 5 sessions), 5-factor score, futures trade by OI walls / volatility; 3:15 pm signal history | every 15 min |
| Watchlist (`#/watch`) | F&O Desk's own watchlist (Supabase table `watchlist`; Sector Strength and Fundamentals Desk share a different one, `fd_watchlist`) | — |
| My Trades (`#/trades`) | Stock trades (% after costs), index trades as futures (₹ P&L); auto-close at stop, target or after 5 sessions | with each job |
| Track record (`#/record`) | Signal log (Supabase `signal_log`): every idea + signals rejected by day OI, with score parts, signal-hour OI, warnings; results by group | with each stock scan |

## Main files
- `desk/snapshot.py` – index chains (NSE v3, BSE for SENSEX), index futures, swing signals, warnings
- `desk/screener.py` – Yahoo hourly candles, 50 EMA cross, futures OI, Top 5
- `desk/signals.py` – signal-hour OI (hourly OI snapshot of all F&O stocks, doc `stock_oi_snaps`), warnings, proposed score (`score_v2`, logged only), signal log + results
- `desk/journal.py` – closes open trades; `desk/cash_journal.py` – Sector Strength cash trades
- `desk/config.py` – **all rule thresholds in one place**
- `site/` – plain HTML/CSS/JS (`app.js`, `config.js` has Supabase URL + public key)
- `supabase/*.sql` – tables and schedules (run in Supabase SQL Editor)

## Workflows
- `index-snapshot.yml` – every 15 min in market hours
- `stock-screener.yml` – hourly
- `cash-trades.yml` – 16:20 and 19:40 IST weekdays (checks Sector Strength cash trades)
- `sector-intraday.yml` – started by the "Run scan" button on Sector Strength
- `keepalive.yml` – Sundays, keeps schedules alive

## Shared setup (used by all 3 sites)
- **One Supabase project** for all three sites. Same email + password sign-in. Row-level security locks data to vs916491@gmail.com.
- Tables: `docs` (generic JSON store, keys like `ss_*`), `trades`, `trade_months`, `cash_trades`, `watchlist` (F&O Desk), `fd_watchlist` (Sector Strength + Fundamentals), `scan_requests`, `swing_history`, `swing_events`, `signal_log`, `chain_snap`, `fut_snap`, `pcr_hist`.
- **Scheduling:** GitHub's own cron runs late or skips runs. So every time-sensitive job is started by **Supabase pg_cron** calling `dispatch_workflow()` / `dispatch_repo_workflow()` / `dispatch_repo_workflow_inputs()`. GitHub cron is kept only as a backup, and each job skips if it already ran.
- GitHub token `fno-desk-supabase` stored in Supabase Vault as `github_token`. Renew yearly (steps in README). Test: `select public.dispatch_workflow('stock-screener.yml', true);` then check `net._http_response` → 204 = OK, 403 = token lacks repo access, 404 = wrong workflow name.
- Repo secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`.

## Rules / decisions to keep
- Index trades: swing only, no automatic paper trades.
- Closed trades are locked: no editing, and no Delete button on the site (open trades can still be deleted).
- Trade details kept 3 months; monthly summaries kept permanently (`trade_months`).
- My Trades totals at the top cover the current financial year only (Apr–Mar) and start fresh each 1 April; completed years show in "Year by year".
- Stock screener: day futures build-up stays the filter; signal-hour OI and the other checks (results, F&O ban, stop < 0.4% or > 2.5%, daily trend vs 20-day average, regime light, breakout volume, chop) are **warnings only**. Sector boost unchanged until the signal log has enough data. Proposed score is logged, not live.
- Stock names link to TradingView (his saved layout with 50 EMA + RSI).
- NSE/BSE endpoints are unofficial and change without notice; each run reports problems in its summary.

## How to ask for changes
Give: tab name, what's wrong or wanted, and a screenshot or symbol + date. Keep changes small; don't touch schedules without asking.
