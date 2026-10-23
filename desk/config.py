"""F&O Desk - all tunable settings.

Index rules are ported from the OI Signal Desk, stock rules from the F&O
stock screener (hourly 50 EMA + futures OI). Change a number here; the next
scheduled run uses it.
"""

from __future__ import annotations

TZ = "Asia/Kolkata"
MARKET_OPEN = "09:15"
MARKET_CLOSE = "15:30"
REQUEST_GAP = 1.0                 # seconds between exchange requests

# ------------------------------------------------------------------ indices
# fut_key: NSE live futures feed key (SENSEX has no futures feed)
INDICES = {
    "NIFTY":      {"exchange": "NSE", "weekly": True,  "strike_step": 50,  "fut_key": "nse50_fut",
                   "quote": "NIFTY 50", "yahoo": "^NSEI"},
    "SENSEX":     {"exchange": "BSE", "weekly": True,  "strike_step": 100, "fut_key": None,
                   "quote": None, "yahoo": "^BSESN"},
    "BANKNIFTY":  {"exchange": "NSE", "weekly": False, "strike_step": 100, "fut_key": "nifty_bank_fut",
                   "quote": "NIFTY BANK", "yahoo": "^NSEBANK"},
    "FINNIFTY":   {"exchange": "NSE", "weekly": False, "strike_step": 50,  "fut_key": "finnifty_fut",
                   "quote": "NIFTY FINANCIAL SERVICES", "yahoo": None},
    "MIDCPNIFTY": {"exchange": "NSE", "weekly": False, "strike_step": 25,  "fut_key": "niftymidcap_fut",
                   "quote": "NIFTY MIDCAP SELECT", "yahoo": None},
}
# Futures lot sizes used for P&L in rupees. NSE's lot-size file overrides these
# for the NSE indices every day; SENSEX comes from here.
LOT_SIZE_FALLBACK = {"NIFTY": 65, "SENSEX": 20, "BANKNIFTY": 30, "FINNIFTY": 60, "MIDCPNIFTY": 120}

CHAIN_KEEP_STRIKES = 20           # strikes kept each side of ATM in stored snapshots
CHAIN_RETENTION_DAYS = 3          # full chain snapshots kept this long (PCR/futures history kept 60 days)
HISTORY_DAYS = 30                 # hourly PCR and futures OI charts

# ------------------------------------------------------------------ Rule 1: option chain OI shift
ATM_WINDOW = 2                    # ATM +/- 2 strikes
OI_LOOKBACK_MIN = 60              # change in OI over the last 60 minutes
OI_SHIFT_MIN_EDGE = 0.10
IMMEDIATE_LEVELS = 2

# ------------------------------------------------------------------ Rule 2: PCR
PCR_BULL = 1.20
PCR_BEAR = 0.80
PCR_NEUTRAL_LOW = 0.85
PCR_NEUTRAL_HIGH = 1.15
PCR_EXTREME_HIGH = 1.60
PCR_EXTREME_LOW = 0.50
PCR_SLOPE_PER_HOUR = 0.03
PCR_SLOPE_MIN_POINTS = 4
PCR_SLOPE_MIN_SPAN_MIN = 45

# ------------------------------------------------------------------ Rule 3: futures build-up
FUT_FLAT_PCT = 0.10

# ------------------------------------------------------------------ swing (monthly) score
MONTHLY_MIN_SCORE = 2.5           # of +/-5
STRONG_EXTRA = 1.0
MONTHLY_MIN_DTE = 7               # a 5-session swing needs 7+ calendar days to expiry
WEEKLY_MIN_DTE = 1
SIGNAL_SAVE_TIME = "15:15"        # the day's official swing signal

# Swing trade levels, two methods shown side by side
SWING_MIN_RR = 1.5                # OI walls: reward to the call/put wall >= 1.5 x risk to the other wall
SWING_DAYS = 5                    # volatility method: 5-session expected move
SWING_STOP_EM = 0.6               # stop = 0.6 x expected move
SWING_TARGET_R = 1.5              # target = 1.5 x stop
SWING_MAX_SESSIONS = 5            # journal: close index trades after 5 sessions

# ------------------------------------------------------------------ NIFTY intraday trend scale (+/-5)
TREND_ZONES = [(3.5, "Strong"), (2.0, "Moderate"), (1.0, "Mild")]

# ------------------------------------------------------------------ warnings
SQUEEZE_PCR_LOW = 0.50
SQUEEZE_PCR_HIGH = 1.80
SQUEEZE_SPOT_MOVE = 0.15          # % spot move over the last 60 min

# ------------------------------------------------------------------ stocks: hourly 50 EMA + futures OI
EF_EMA = 50
EF_BODY = 0.5                     # "solid" candle: body at least half the range ...
EF_CLOSE_ZONE = 2 / 3             # ... and a Long closes in the top third (Short: bottom third)
EF_SWING_BARS = 10                # recent swing: the 10 candles before the breakout candle
EF_STOP_BUFFER = 0.001            # stop 0.1% beyond the candle / swing extreme
EF_TARGET_R = 2.0                 # target 1:2
EF_MAX_DAYS = 5                   # close after 5 sessions (entry day = day 1)
EF_SIGNAL_BARS = 2                # show signals from the last 2 completed candles
OI_CHANGE_CAP = 15.0              # Top 5: OI change counted up to 15%

# Top 5 score (win rate removed): candle clarity 60% + OI change 40%,
# plus a boost when the stock's sector is leading in the trade's direction.
TOP5_WEIGHTS = {"clarity": 0.60, "oi_change": 0.40}
SECTOR_BOOST = 10.0
SECTOR_SITE = "https://vs916491-maker.github.io/Nifty-sector-strength/data"

COST_PCT = 0.10                   # round-trip costs for % P&L on stock trades
