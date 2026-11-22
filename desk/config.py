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

# ------------------------------------------------------------------ option ideas (14 Nov 2026, desk/ideas.py)
# Suggested index trades has a Swing / Intraday dropdown; each index gets Futures, Option buying and
# Option selling (defined-risk spreads) ideas from the chain (OI walls, IV), futures OI and India VIX.
# Intraday is display only (no logging, no My Trades), square-off by 15:15.
INTRADAY_INDICES = ["NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]   # 22 Nov 2026: all 5 (monthly chain where no weekly)
INTRADAY_MIN_SCORE = 2.0          # trend scale (+/-5): Moderate or stronger counts as a direction
INTRADAY_DAYS = 1                 # expected move over 1 session
INTRADAY_STOP_EM = 0.5            # futures / option-buy stop = 0.5 x the 1-day expected move
INTRADAY_TARGET_R = 1.5           # target = 1.5 x stop
INTRADAY_EXIT_TIME = "15:15"
VIX_LOW, VIX_HIGH = 13.0, 18.0    # India VIX: below = options cheap, above = options rich
VIX_RISE_PCT = 3.0                # VIX up this much (%) today = rising
BUY_STOP_PCT = {"swing": 30.0, "intraday": 25.0}   # option buying: stop = this % of the premium paid
BUY_DELTA = 0.5                   # ATM option moves about half the index move (used for the target premium)
SELL_WIDTH_STEPS = {"swing": 4, "intraday": 2}     # spread width in strike steps
SELL_EM_MULT = 0.8                # short strike at the OI wall or 0.8 expected move away, whichever is farther
SELL_MIN_CREDIT = 0.20            # credit at least 20% of the spread width
SELL_STOP_MULT = 2.0              # close the spread if it costs 2x the credit received to close
SELL_PROFIT_EXIT = 0.5            # take profit at 50% of the credit

# ------------------------------------------------------------------ Greeks engine (22 Nov 2026: desk/greeks.py, edge.py, strategies.py)
# Suggested index trades and the Index Track Record use these; the old 5-factor swing score is retired.
RISK_FREE = 0.065                 # India 91-day T-bill area; only discounting, small effect
GREEKS_MIN_T_MIN = 15             # time to expiry never below 15 minutes (expiry-day IV blows up)
IV_MIN, IV_MAX = 0.01, 3.0        # IV solver bounds (1% .. 300%)
IV_OUTLIER = 2.5                  # a strike's IV this far from its neighbours' median = stale LTP, dropped
FWD_MAX_GAP = 0.05                # forward more than 5% from spot = bad prices, fall back
GREEKS_HIST_DAYS = 400            # compact Greeks history (ATM IV, skew, walls, VIX) kept this long

# Direction score (-100..+100): weighted factors, each -1..+1. Price leads, positioning confirms.
EDGE_WEIGHTS = {"momentum": 25, "structure": 20, "flow": 20, "futures": 15, "skew": 10, "ivpx": 10}
EDGE_MODERATE = 30                # |score| >= 30: Moderate direction
EDGE_STRONG = 55                  # |score| >= 55: Strong
EDGE_PRICE_GATE = 0.15            # a direction needs momentum or structure at least 0.15 the same way
MOM_LOOKBACK_MIN = 30             # intraday momentum: spot move over the last 30 minutes ...
MOM_FULL_Z = 1.5                  # ... in expected-move units; 1.5 sigma = full score
FLOW_LOOKBACK_MIN = 30            # intraday writer flow: change in OI over the last 30 minutes
FUT_LOOKBACK_MIN = 60             # intraday futures build-up window
SKEW_LOOKBACK_MIN = 60            # intraday skew / IV change window
SKEW_FULL = 1.0                   # 25-delta risk reversal change of 1 vol point = full score
IV_MOVE = 0.3                     # ATM IV change (vol points) that counts as rising / falling
SESSION_MIN = 375                 # 09:15-15:30
TRADING_DAYS = 252

# Volatility regime: VIX level, ATM IV vs 10-day realised volatility, VIX rank (once 20+ sessions are stored)
RV_DAYS = 10
IVRV_CHEAP, IVRV_RICH = 0.90, 1.25
VIX_RANK_MIN_DAYS = 20
VIX_RANK_CHEAP, VIX_RANK_RICH = 25, 75
VOL_EXPAND_IV = 0.5               # ATM IV up 0.5 vol point (window above) or VIX up VIX_RISE_PCT = expanding
GAMMA_RANGE_EM = 2.5              # call and put gamma walls within 2.5 expected moves = a range

# Strategy legs (target |delta|) and exits. All P&L rules are per unit of the structure.
ST_BUY_DELTA = 0.55               # option buying: slightly in the money
ST_DEBIT_SHORT_DELTA = 0.25       # debit spread: sell this delta
ST_CREDIT_SHORT_DELTA = 0.30      # credit spread short leg
ST_CREDIT_WING_DELTA = 0.12       # credit spread hedge leg
ST_CONDOR_SHORT_DELTA = 0.20
ST_CONDOR_WING_DELTA = 0.07
ST_STRANGLE_DELTA = 0.25          # delta-hedged short strangle (with wings)
ST_STRANGLE_WING_DELTA = 0.05
ST_HEDGE_PUT_DELTA = 0.30         # futures + protective option
ST_COVER_DELTA = 0.30             # futures + covered option
ST_STOP_EM = {"swing": 0.6, "intraday": 0.5}    # futures stop = this x the expected move
ST_TARGET_R = 1.5                 # target = 1.5 x the risk to the stop
ST_BUY_STOP = {"swing": 0.30, "intraday": 0.25}  # option buying: stop at this share of the premium lost
ST_DEBIT_STOP = 0.40              # debit spread: stop at 40% of the debit lost
ST_CREDIT_TP = 0.50               # credit structures: take profit at 50% of the credit
ST_CREDIT_SL = 1.00               # ... stop when the loss equals 1 x the credit (cost to close = 2x)
ST_STRADDLE_TP, ST_STRADDLE_SL = 0.25, 0.20     # long straddle: +25% / -20% of the debit (hedge P&L included)
ST_MIN_CREDIT_WIDTH = 0.20        # credit at least 20% of the width
ST_HEDGE_COST_MAX = 0.35          # protective option costs at most 35% of the expected move
ST_SWING_MIN_DTE = 7              # swing ideas need 7+ calendar days to expiry
DH_BAND = 0.25                    # delta-hedged ideas: hedge when |net delta| > 0.25 per lot of the structure
INDEX_IDEA_SESSIONS = 5           # swing ideas: time exit after 5 sessions (or the day before expiry)

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
BB_REJ_MAX_TOP5 = 2               # at most 2 rejection + shakeout setups in each Top 5
# Shakeout in the base (6 Nov 2026, his HAVELLS example): dip below the base, close back inside
BB_SHK_DIP_ADR = 0.25             # low at least 0.25x the daily range below the base low (Short: high above)
BB_SHK_WICK_ADR = 0.4             # wick at least 0.4x the daily range
BB_SHK_CONFIRM = False            # True = wait for the next candle like rejections (entry = base breakout's, no gain)
# Base 3 (7 Nov 2026, his JSWENERGY example): the 3rd base after the EMA cross is not taken live
# (BB_MAX_BASE_NO), but it is logged for the Track record ("pb3") with the Price Action score.
# Setups that pass all conditions are logged as ideas, the others as rejected (to see if the
# conditions matter). Not shown on the screener and not in any Top 5 until the record supports it.
BB_LATE_LOG = True                # log base 3 in the Track record
BB_LATE_BASE_NO = 3               # exactly the 3rd base (4th and later stay "late", not logged)
BB_LATE_TIGHT_ADR = 0.8           # tight base: its range at most 0.8x the average daily range (live bases allow 1.5x)
BB_LATE_VOL = 1.0                 # breakout candle's volume at least the usual for that hour
BB_LATE_EMA_PCT = 5.0             # close no more than 5% away from the 50 EMA (needs the sector boost too)
