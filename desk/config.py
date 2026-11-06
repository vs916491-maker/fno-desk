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

# ------------------------------------------------------------------ signal log + track record (desk/signals.py)
# Every idea (and every signal rejected only because the day's futures build-up was
# against it) is logged with its score parts and warnings; later scans mark the result
# with the strategy's own exit rules (stop, 1:2 target, close back across the 50 EMA,
# or 5 sessions). The Track record tab compares groups from this log.
OI_SNAP_KEEP = 75                 # hourly futures OI snapshots kept (about ten sessions: "usual" hourly OI)
OI_SNAP_GAP = 0.5                 # seconds between per-stock futures quotes for the snapshot
OI_SNAP_MAX_SEC = 360             # stop the snapshot after this long (the rest waits for the next scan)
OI_SNAP_MIN_AGE_MIN = 20          # a Run-scanner press soon after a scan does not take another snapshot
HOUR_FLAT_PCT = 0.10              # signal-hour OI change smaller than this (%) counts as flat

# Warnings (shown on the idea, never block it)
WARN_RESULTS_SESSIONS = 5         # quarterly results within this many sessions
WARN_RISK_MIN = 0.4               # stop closer than this % from entry: noise can hit it
WARN_RISK_MAX = 2.5               # stop further than this %: large risk for a 5-session trade
DAILY_SMA = 20                    # daily trend: price vs its 20-day average
VOL_SESSIONS = 10                 # breakout volume vs the same hourly candle over the last 10 sessions
WARN_VOL_RATIO = 1.0              # below the usual volume for that hour
WARN_SMALL_CANDLE = 0.6           # signal candle's range below 0.6x the usual for that hour: small candle
WARN_BIG_CANDLE = 2.5             # above 2.5x: very big candle (entry far from the 50 EMA, wide stop)
CHOP_BARS = 21                    # about 3 sessions of hourly candles before the signal
WARN_CHOP_CROSSES = 3             # this many 50 EMA crosses before the signal: choppy

# Proposed score (logged only; the live Top 5 still uses TOP5_WEIGHTS + SECTOR_BOOST).
# Signal-hour OI 35, day OI 25, candle 40 (shape 25 + size 15), plus the
# same sector boost. Volume is not scored (Yahoo hourly volume is patchy and overlaps with
# OI); it stays a warning and a Track record group. The Track record tab shows how this
# score's Top 5 would have done.
V2_WEIGHTS = {"hour_oi": 35.0, "day_oi": 25.0, "shape": 25.0, "size": 15.0}
V2_SHAPE_FULL = 85.0              # candle shape: 0 at the weakest solid candle (58), full from clarity 85
V2_SIZE_MIN, V2_SIZE_FULL = 0.5, 1.5   # candle size vs the usual range for that hour: 0 at 0.5x, full from 1.5x
V2_HOUR_OI_CAP = 5.0              # signal-hour OI change counted up to 5%

# ------------------------------------------------------------------ stocks: base breakout rules (6 Nov 2026)
# Two screener tabs: Price Action (chart only) and Price+OI (chart + futures OI). The old
# 50 EMA cross rules still run in the background and are logged for the Track record.
# Rules and scores live in desk/setups.py; every number is here.
BB_SIGNAL_BARS = 2                # setups from the last 2 completed hourly candles
BB_SLOPE_BARS = 20                # 50 EMA slope over the 20 candles before the signal (~3 sessions)
BB_FLAT_PCT = 0.5                 # slope within +-0.5%: flat; above: rising; below: falling
BB_BASE_MIN, BB_BASE_MAX = 7, 30  # base: 7 to 30 hourly candles before the breakout
BB_ADR_DAYS = 20                  # average daily range (high-low % of close) over 20 sessions
BB_BASE_ADR = 1.5                 # base range at most 1.5x the average daily range
BB_BASE_HELD = 0.8                # 80% of the base's closes on the trade's side of the 50 EMA
BB_FLAT_SHORT_GAP = 1.0           # flat-EMA short: base closes more than 1% below the EMA
BB_MAX_BASE_NO = 2                # only the 1st and 2nd base after the EMA cross count
BB_HOLD_BARS = 7                  # falling EMA (Long) / rising EMA (Short): hold 7+ candles past the EMA first
BB_TOUCH_PCT = 0.2                # rejection short: high within 0.2% of the falling EMA
BB_BIG_CANDLE_PCT = 2.0           # breakout candle range >= 2% of price: stop at the candle's low/high
BB_STOP_BUFFER = 0.001            # stop 0.1% beyond the candle / base extreme
BB_MAX_RISK = 5.0                 # stop more than 5% from entry: skipped
BB_TARGET_R = 2.0                 # target 1:2 (shown; your trades close only at the stop or by hand)
BB_MAX_DAYS = 5                   # Track record: stop, target or 5 sessions
# Price+OI: futures OI must lead (or follow within one candle)
BB_OI_SURGE = 1.5                 # signal-hour OI build-up >= 1.5x the stock's usual hourly OI change
BB_OI_FULL = 4.0                  # full OI points at 4x usual
BB_FIRST_HOUR_FACTOR = 1.65       # first hour's usual OI change vs a normal hour, until 3+ days of history
BB_DAY_OI_FULL = 8.0              # day OI: full points at +8%
# Scores (0-100). Price Action has no OI parts; its chart parts are scaled up.
BB_W_PA = {"strength": 14, "size": 11, "volume": 10, "tight": 16, "length": 11, "ema": 14, "margin": 14,
           "hour_oi": 0, "day_oi": 0, "sector": 10}
BB_W_PO = {"strength": 10, "size": 8, "volume": 7, "tight": 12, "length": 8, "ema": 10, "margin": 10,
           "hour_oi": 15, "day_oi": 10, "sector": 10}
BB_OI_MIN_POINTS = 1 / 3          # an OI surge of exactly 1.5x earns a third of the OI points
# Flattening EMA (6 Nov 2026, ICICIBANK 23-24 Apr example): the 20-candle slope lags, so a
# 50 EMA that has gone flat over the last 7 candles also counts, with the base on the EMA.
BB_ROLL_BARS = 7                  # EMA change over the last 7 candles ...
BB_ROLL_FLAT_PCT = 0.15           # ... within +-0.15%: flattening
BB_ROLL_NEAR_PCT = 0.3            # base closes no more than 0.3% on the wrong side of the EMA
# Base count (6 Nov 2026, his rule): only sideways bases on the trade's side of the 50 EMA
# count, stepping in one direction since price crossed the EMA; a cross resets the count.
BB_BASE_DRIFT = 0.5               # sideways: first-to-last close move at most 50% of the base's range
BB_COUNT_LOOKBACK = 150           # count bases over at most the last 150 candles
# Rejection at the 50 EMA (both sides, 6 Nov 2026): Long on a rising EMA, Short on a falling one.
BB_REJ_PRIOR_BARS = 7             # 80% of the 7 candles before were on the trade's side of the EMA
BB_REJ_WICK = 0.5                 # wick toward the EMA at least half the candle
BB_REJ_CLOSE_PCT = 0.1            # close back at/above the EMA (Short: at/below), 0.1% tolerance
BB_REJ_TOUCH_BARS = 21            # rejection score: earlier EMA touches counted over ~3 sessions
# Rejection checks (6 Nov 2026, his HINDALCO example; all must pass, else logged as failed):
BB_REJ_SIZE = 1.5                 # A. candle range at least 1.5x the stock's usual candle for that hour
BB_REJ_WICK_ADR = 0.5             # B. wick at least 0.5x the average daily range
BB_REJ_DEPTH_ADR = 0.25           # C. low pierces the EMA by at least 0.25x the daily range (Short: high)
                                  # D. next candle closes beyond the rejection candle's close; entry a candle later
BB_REJ_MAX_TOP5 = 2               # at most 2 rejection setups in each Top 5
