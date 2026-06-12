"""
Custom technical indicators beyond pandas-ta standard set.
All functions return a dict {indicator_name: pd.Series}.
"""
import numpy as np
import pandas as pd


def high_low_break(df: pd.DataFrame, lookback: int = 20) -> dict[str, pd.Series]:
    """
    Detects if the current close breaks above/below the highest high / lowest low
    of the previous `lookback` candles (not including current).
    Uses high for the upper reference and low for the lower reference,
    which captures the true intraday range the market has visited.
    Returns binary Series: 1 = break, 0 = no break.
    """
    prev_high = df["high"].shift(1).rolling(lookback).max()
    prev_low  = df["low"].shift(1).rolling(lookback).min()
    break_high = (df["close"] > prev_high).astype(int)
    break_low  = (df["close"] < prev_low).astype(int)
    return {
        f"break_high_{lookback}": break_high,
        f"break_low_{lookback}": break_low,
        f"prev_high_{lookback}": prev_high,
        f"prev_low_{lookback}": prev_low,
    }


def multi_candle_cross(
    df: pd.DataFrame, col1: str, col2: str, n: int = 2
) -> dict[str, pd.Series]:
    """
    Returns 1 when col1 has been above col2 for at least `n` consecutive candles,
    -1 when col1 has been below col2 for at least `n` consecutive candles, else 0.
    Useful for confirming crossovers require sustained price action.
    """
    if col1 not in df.columns or col2 not in df.columns:
        return {}

    above = (df[col1] > df[col2]).astype(int)
    below = (df[col1] < df[col2]).astype(int)

    # Rolling sum: if sum == n then sustained for n candles
    above_n = above.rolling(n).sum() >= n
    below_n = below.rolling(n).sum() >= n

    signal = pd.Series(0, index=df.index)
    signal[above_n] = 1
    signal[below_n] = -1

    key = f"cross_{col1}_{col2}_{n}c"
    return {key: signal}


def pullback_to_indicator(
    df: pd.DataFrame, indicator_col: str, tolerance_pct: float = 1.0, lookback: int = 5
) -> dict[str, pd.Series]:
    """
    Detects when price pulls back to touch an indicator level after having moved away.
    A "touch" = close is within `tolerance_pct`% of the indicator value.
    Signal fires only when previous candles were farther away (pullback, not just flat).
    """
    if indicator_col not in df.columns:
        return {}

    ind = df[indicator_col]
    diff_pct = ((df["close"] - ind) / ind).abs() * 100
    touching = diff_pct <= tolerance_pct

    # Confirm prior candle was farther away (actual pullback, not persistent touch)
    was_far = diff_pct.shift(1) > tolerance_pct * 2
    pullback = (touching & was_far).astype(int)

    return {f"pullback_{indicator_col}_{tolerance_pct}pct": pullback}


def trend_strength(df: pd.DataFrame, ema_col: str = "ema_50", adx_col: str = "adx") -> dict[str, pd.Series]:
    """
    Composite trend strength score (0-100):
    - 50% weight: ADX value (0-100)
    - 50% weight: EMA slope normalized (positive = uptrend)
    Returns a score and a direction (+1 up, -1 down, 0 neutral).
    """
    results = {}
    if adx_col in df.columns:
        adx = df[adx_col].clip(0, 100)
    else:
        adx = pd.Series(50, index=df.index)  # neutral if unavailable

    if ema_col in df.columns:
        ema = df[ema_col]
        slope = ema.pct_change(5) * 100  # 5-period slope in %
        slope_norm = slope.clip(-5, 5) / 5 * 100  # normalize to 0-100 range offset by 50
        slope_score = (slope_norm + 100) / 2  # center around 50
    else:
        slope_score = pd.Series(50, index=df.index)

    score = (adx * 0.5 + slope_score * 0.5).round(2)

    direction = pd.Series(0, index=df.index)
    if ema_col in df.columns:
        direction[df["close"] > df[ema_col]] = 1
        direction[df["close"] < df[ema_col]] = -1

    results["trend_strength"] = score
    results["trend_direction"] = direction
    return results


def candle_patterns(df: pd.DataFrame) -> dict[str, pd.Series]:
    """
    Basic candle pattern detection:
    - doji: body < 10% of range
    - hammer: small body at top of range with long lower wick
    - shooting_star: small body at bottom of range with long upper wick
    """
    body = (df["close"] - df["open"]).abs()
    candle_range = df["high"] - df["low"]
    candle_range = candle_range.replace(0, np.nan)

    body_pct = body / candle_range

    lower_wick = df[["open", "close"]].min(axis=1) - df["low"]
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)

    doji = (body_pct < 0.1).astype(int)
    hammer = ((body_pct < 0.3) & (lower_wick > body * 2) & (upper_wick < body)).astype(int)
    shooting_star = ((body_pct < 0.3) & (upper_wick > body * 2) & (lower_wick < body)).astype(int)

    return {
        "pattern_doji": doji,
        "pattern_hammer": hammer,
        "pattern_shooting_star": shooting_star,
    }


def swing_levels(df: pd.DataFrame, n: int = 2) -> dict[str, pd.Series]:
    """
    Detects local swing highs and lows and carries their value forward as a step line.

    A swing high at bar i: high[i] > high[i-1] AND high[i] > high[i-2] ... high[i-n]
    A swing low  at bar i: low[i]  < low[i-1]  AND low[i]  < low[i-2]  ... low[i-n]

    The resulting series holds the most recent swing high/low value at each bar,
    producing a staircase line that acts as a dynamic support/resistance level.
    """
    highs = df["high"]
    lows  = df["low"]

    # A bar is a swing high if its high is strictly greater than the n bars before it
    is_swing_high = pd.Series(True, index=df.index)
    is_swing_low  = pd.Series(True, index=df.index)
    for lag in range(1, n + 1):
        is_swing_high &= highs > highs.shift(lag)
        is_swing_low  &= lows  < lows.shift(lag)

    # Mark NaN for the first n bars (not enough history)
    is_swing_high.iloc[:n] = False
    is_swing_low.iloc[:n]  = False

    # Carry the swing value forward: NaN on non-swing bars, then ffill
    swing_high_val = highs.where(is_swing_high)
    swing_low_val  = lows.where(is_swing_low)

    prev_swing_high = swing_high_val.ffill()
    prev_swing_low  = swing_low_val.ffill()

    return {
        f"swing_high_{n}":      prev_swing_high,
        f"swing_low_{n}":       prev_swing_low,
        f"is_swing_high_{n}":   is_swing_high.astype(int),
        f"is_swing_low_{n}":    is_swing_low.astype(int),
    }


def kptos(df: pd.DataFrame, rsi_col: str = "rsi_14", swing_n: int = 2, window: int = 14) -> dict[str, pd.Series]:
    """
    KPTOS indicator: state machine with COMPRA (1), VENTA (-1), NEUTRAL (0).

    Transitions:
      NEUTRAL → COMPRA : RSI > 60 for 2+ consecutive bars AND close > recent swing high
      COMPRA  → NEUTRAL: RSI < 60 AND close < recent swing low
      NEUTRAL → VENTA  : RSI < 40 for 2+ consecutive bars AND close < recent swing low
      VENTA   → NEUTRAL: RSI > 40 AND close > recent swing high

    Uses the forward-filled swing_high/low columns (shifted 1 bar) so we compare
    against the previous local max/min, not the current bar's level.
    Only considers swing points within the last `window` bars.
    """
    if rsi_col not in df.columns:
        return {}

    sh_col    = f"swing_high_{swing_n}"
    sl_col    = f"swing_low_{swing_n}"
    is_sh_col = f"is_swing_high_{swing_n}"
    is_sl_col = f"is_swing_low_{swing_n}"

    if sh_col not in df.columns or sl_col not in df.columns:
        return {}

    rsi    = df[rsi_col]
    closes = df["close"]

    # Detect new swings from when the forward-filled level changes value.
    # This avoids dependency on is_swing_high/low columns which may be absent from DB.
    is_sh = (df[sh_col] != df[sh_col].shift(1)).astype(int)
    is_sl = (df[sl_col] != df[sl_col].shift(1)).astype(int)

    # Keep swing level only when there's a swing within the last `window` bars
    has_recent_sh = is_sh.rolling(window, min_periods=1).max()
    has_recent_sl = is_sl.rolling(window, min_periods=1).max()

    # Shift by 1: compare current close against the level established BEFORE this bar
    sh_ref = df[sh_col].where(has_recent_sh == 1).shift(1)
    sl_ref = df[sl_col].where(has_recent_sl == 1).shift(1)

    rsi_above60_2 = (rsi > 60) & (rsi.shift(1) > 60)
    rsi_below40_2 = (rsi < 40) & (rsi.shift(1) < 40)
    breaks_high   = closes > sh_ref
    breaks_low    = closes < sl_ref

    n      = len(df)
    states = np.zeros(n, dtype=float)
    state  = 0

    for i in range(2, n):
        if state == 0:
            if rsi_above60_2.iloc[i] and breaks_high.iloc[i]:
                state = 1
            elif rsi_below40_2.iloc[i] and breaks_low.iloc[i]:
                state = -1
        elif state == 1:
            if rsi.iloc[i] < 60 and breaks_low.iloc[i]:
                state = 0
        elif state == -1:
            if rsi.iloc[i] > 40 and breaks_high.iloc[i]:
                state = 0
        states[i] = state

    return {"kptos": pd.Series(states, index=df.index)}


def calc_all_custom(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Calculate all custom indicators on a OHLCV + standard indicator DataFrame."""
    if df.empty or len(df) < 30:
        return {}

    results = {}
    results.update(high_low_break(df, lookback=20))
    results.update(high_low_break(df, lookback=52))  # yearly high/low
    results.update(swing_levels(df, n=2))
    results.update(swing_levels(df, n=3))

    # Multi-candle crossovers for key pairs
    for col1, col2 in [("ema_9", "ema_20"), ("ema_20", "ema_50"), ("ema_50", "ema_200"), ("close", "sma_200")]:
        if col1 in df.columns and col2 in df.columns:
            results.update(multi_candle_cross(df, col1, col2, n=2))
            results.update(multi_candle_cross(df, col1, col2, n=3))

    # Pullbacks to key indicators
    for ind_col in ["sma_20", "sma_50", "ema_20", "ema_50", "bb_mid"]:
        if ind_col in df.columns:
            results.update(pullback_to_indicator(df, ind_col, tolerance_pct=0.5))

    results.update(trend_strength(df))
    results.update(candle_patterns(df))
    # Enrich df with swing columns so kptos can use them
    df_enriched = df.assign(**{k: v for k, v in results.items() if k.startswith("is_swing_") or k.startswith("swing_")})
    results.update(kptos(df_enriched))
    return results
