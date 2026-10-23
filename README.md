# F&O Desk

One website for the F&O stock screener and the OI Signal Desk, running in the
cloud: GitHub Actions collects the data, Supabase stores it, GitHub Pages shows
it on any device behind an email sign-in.

| Tab | What it shows | Updated |
|---|---|---|
| F&O stock screener | Hourly 50 EMA cross + futures OI build-up; Top 5 (candle clarity 60% + OI change 40% + sector boost); other trend switches; "I took this trade" | after each hourly candle (~:20 past, 10:20-15:20, and 15:35) |
| F&O index analysis | Index cards, warnings (squeeze, expiry), NIFTY intraday trend scale, hourly PCR (monthly + weekly) and futures OI with like-for-like change bars | every 15 minutes, 09:15-15:30 |
| Option chain | NIFTY, SENSEX, BANKNIFTY, FINNIFTY, MIDCPNIFTY by expiry: OI, change in OI, LTP, IV, PCR, max pain, walls | every 15 minutes |
| Suggested index trades | Swing (monthly chain, up to 5 sessions): 5-factor score, futures trade by OI walls and by volatility, "I took this trade"; 3:15 pm signal history | every 15 minutes |
| My trades | Stock trades (% after costs) and index futures trades (₹); auto-close at stop, target or after 5 sessions | with each job |

## How it runs

- `desk/snapshot.py`: index option chains (NSE v3 feed, BSE for SENSEX), index futures (NSE quote API), quotes; swing signals, trend scale, warnings, chart history. Workflow *Index snapshot (every 15 min)*.
- `desk/screener.py`: Yahoo hourly candles for all F&O stocks, 50 EMA cross, futures OI from NSE's quote API, Top 5. Workflow *Stock screener (hourly)*.
- `desk/journal.py`: closes your open trades automatically.
- `desk/config.py`: every rule threshold in one place.
- `site/`: the website (plain HTML/CSS/JS); `site/config.js` holds the Supabase URL and public anon key.
- `supabase/schema.sql`: tables, access rules (only the owner's email), and the earlier 26 trades.

GitHub's schedules can start a few minutes late. Exchange feeds are unofficial website endpoints and can change without notice; each run reports problems in its summary.

## Setup checklist

1. Supabase: run `supabase/schema.sql` in the SQL editor.
2. Supabase → Authentication → URL configuration: Site URL = this repo's Pages URL.
3. GitHub repo secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`.
4. `site/config.js`: Supabase URL and anon key.

Without step 4 the website runs in preview mode on `site/sample/`.

*For personal analysis only. Not investment advice.*

## Renewing the GitHub token (once a year)

The "Run scanner" button and the on-time schedules start GitHub jobs from
Supabase with a fine-grained token (`fno-desk-supabase`, Actions: read and
write on this repo). GitHub emails a reminder about 7 days before it expires.

1. GitHub → Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → `fno-desk-supabase` → **Regenerate token** → copy it.
2. Supabase → SQL Editor → run (with the new token inside the quotes):
   `select vault.update_secret((select id from vault.secrets where name = 'github_token'), 'NEW_TOKEN');`
3. Test: `select public.dispatch_workflow('stock-screener.yml', true);`, then
   check `select status_code from net._http_response order by created desc limit 1;` shows 204.


## Cash trades for Sector Strength's "My Trades"

`supabase/003_cash_trades.sql` creates the private `cash_trades` table used by
the Sector Strength website's My Trades tab (run it once in the SQL Editor).
The *Cash trades check* workflow (`desk/cash_journal.py`) runs at 16:20 and
19:40 IST on weekdays: it updates each open trade's last close, 50-day average
and sessions held from daily candles, and closes trades by their exit rule.
