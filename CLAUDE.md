# F&O Desk — project notes

Owner: Vivek (GitHub `vs916491-maker`). Personal analysis only, not investment advice.
Repo: `vs916491-maker/fno-desk` (public). Site: GitHub Pages, behind email + password sign-in.

## What it is
One website combining the F&O stock screener and the index OI desk. Cloud-only: GitHub Actions collects data, Supabase stores it, GitHub Pages shows it. No laptop needed.

## Tabs
| Tab | What it shows | Updates |
|---|---|---|
| F&O stock screener (`#/stocks`) | Two views (6 Nov 2026): **Price Action** (default, chart only) and **Price+OI** (chart + futures OI, "Waiting for OI" list). Hourly base breakouts by 50 EMA state (`desk/setups.py`); own Top 5 per view; all ideas of the day kept by run (doc `stock_screener_day`); "I took this trade"; Run scanner button. Old 50 EMA cross rules run in the background, logged only | after each hourly candle (~:20 past, 10:20–15:20, and 15:35) |
| F&O index analysis (`#/index`) | Index cards, warnings (squeeze, expiry), NIFTY intraday trend scale, hourly PCR (monthly + weekly), futures OI | every 15 min, 09:15–15:30 |
| Option chain (`#/chain`) | NIFTY, SENSEX, BANKNIFTY, FINNIFTY, MIDCPNIFTY: OI, change in OI, LTP, IV, PCR, max pain, walls | every 15 min |
| Suggested index trades (`#/swing`) | Swing only (monthly chain, up to 5 sessions), 5-factor score, futures trade by OI walls / volatility; 3:15 pm signal history | every 15 min |
| Watchlist (`#/watch`) | F&O Desk's own watchlist (Supabase table `watchlist`; Sector Strength and Fundamentals Desk share a different one, `fd_watchlist`) | — |
| My Trades (`#/trades`) | Stock trades (% after costs), index trades as futures (₹ P&L); auto-close at stop, target or after 5 sessions | with each job |
| Readme (`#/readme`) | Current rules and scores in plain words (static text in `viewReadme` in `site/app.js`: **update it when a rule changes**) | — |
| Track record (`#/record`) | Signal log (Supabase `signal_log`): every idea + signals rejected by day OI, with score parts, signal-hour OI, warnings; results by group | with each stock scan |

## Main files
- `desk/snapshot.py` – index chains (NSE v3, BSE for SENSEX), index futures, swing signals, warnings
- `desk/screener.py` – Yahoo hourly candles, both screener views (`base_breakouts`), old 50 EMA cross rules (background), Top 5; `--dry` / `--at 2026-11-06T14:20` = read-only test (workflow `screener-test.yml`)
- `desk/setups.py` – base breakout rules: EMA state, base, stop, signal-hour OI vs usual, scores
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
- Closed trades are locked: no editing, and no Delete button on the site (open trades can still be deleted). Exception (5 Nov 2026, both sites): a trade closed by hand can be edited or reopened until the next weekday 19:40 IST (`closed_at` set by a trigger, `trade_fix_until()`, RLS in `supabase/011_fix_closed_trades.sql`); trades closed by the jobs lock at once.
- Trade details kept 3 months; monthly summaries kept permanently (`trade_months`).
- My Trades totals at the top cover the current financial year only (Apr–Mar) and start fresh each 1 April; completed years show in "Year by year".
- Stock screener rules (decided 6 Nov 2026, all numbers `BB_*` in `desk/config.py`, details at the top of `desk/setups.py`):
  - EMA state = hourly 50 EMA slope over 20 candles: rising > +0.5%, flat ±0.5%, falling < −0.5%. Base = 7–30 candles, range ≤ 1.5× average daily range (20 sessions). Breakout = solid candle closing beyond the base and the EMA. Only base 1–2 are taken.
  - Base count (his rule, 6 Nov 2026): bases must be sideways (first-to-last close ≤ 50% of the range, `BB_BASE_DRIFT`) and on the trade's side of the EMA (80% of closes); count = breakouts of such bases stepping one way since price crossed the EMA, each new base after the previous breakout; a cross resets the count (no zig-zag counting). Same for rising, flat and falling EMA.
  - Long: rising/flat EMA base 1–2 held above the EMA; falling EMA: 1st breakout ignored, must hold above the EMA 7+ candles then base. Short: falling EMA base breakdown or rejection at the EMA; flat EMA base >1% below the EMA; no shorts on a rising EMA.
  - Flattening EMA (6 Nov 2026, his ICICIBANK 23–24 Apr example): the 20-candle slope lags, so an EMA flat over the last 7 candles (within 0.15%) after a rise allows a short (after a fall, a long) when the base sits on the EMA (80% of closes within 0.3%). Gap in the trade's direction counts in the breakout candle's body. If the longest base fails, shorter bases (down to 7) are tried.
  - Rejection at the 50 EMA (6 Nov 2026, HINDALCO example), both sides: rising EMA → Long when price had been above it (80% of the last 7 closes), the low touches/pierces the EMA, close back at/above it, lower wick ≥ 50% of the candle, close in the upper half; stop below the wick. Falling EMA → Short, the mirror. `BB_REJ_*` in config.
  - Stop: breakout candle ≥ 2% of price → candle low/high, else base low/high (0.1% buffer); > 5% skipped. Target 1:2 shown only. Track record: stop, target or 5 sessions. My Trades from these tabs (source "Price Action"/"Price+OI"): auto-close at the stop only, otherwise by hand.
  - Price+OI: signal-hour OI build-up ≥ 1.5× the stock's usual hourly OI change (first hour has its own usual); rising/falling EMA also needs the day's build-up; one-candle wait (OI in the next candle → entry a candle later), else logged as rejected by OI.
  - Scores (volume removed and sector raised to 15 on 6 Nov 2026, his choice): Price Action = strength 15 + size 12 + base tight 17 + length 12 + near EMA 15 + margin 14 + sector 15. Price+OI = strength 11 + size 9 + tight 12 + length 8 + EMA 10 + margin 10 + signal-hour OI 15 + day OI 10 + sector 15. He wants chart weighted above OI (price usually moves first).
  - Warnings only: results, F&O ban, stop < 0.4%, daily trend, regime, candle size, chop (no volume warning on the new rules).
  - Signal log keys: `pa|SYM|Side|time`, `po|…` (info.rules); old rules keep the plain key. Hourly OI snapshots keep ~10 sessions (`OI_SNAP_KEEP` 75) and store yesterday's closing OI as the 3rd value.
- Signal-hour OI for a 9:15 candle is measured from yesterday's closing OI (NSE day change), never from yesterday's last snapshot (fixed 6 Nov 2026).
- Stock names link to TradingView (his saved layout with 50 EMA + RSI).
- NSE/BSE endpoints are unofficial and change without notice; each run reports problems in its summary.

## How to ask for changes
Give: tab name, what's wrong or wanted, and a screenshot or symbol + date. Keep changes small; don't touch schedules without asking.
