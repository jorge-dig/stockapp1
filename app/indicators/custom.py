"""
Custom technical indicators beyond pandas-ta standard set.
All functions return a dict {indicator_name: pd.Series}.
"""
import numpy as np
import pandas as pd


def high_low_break(df: pd.DataFrame, lookback: int = 20) -> dict[str, pd.Series]:
    """
    Detects if the current close breaks above/below the highest/lowest
    close in the previous `lookback` candles (not including current).
    Returns binary Series: 1 = break, 0 = no break.
    """
    prev_high = df["close"].shift(1).rolling(lookback).max()
    prev_low = df["close"].shift(1).rolling(lookback).min()
    break_high = (df["close"] > prev_high).astype(int)
    break_low = (df["close"] < prev_low).astype(int)
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


def pivot_high_low(df: pd.DataFrame, n: int = 2) -> dict[str, pd.Series]:
    """
    Pivot highs and lows using n-bar lookback and lookahead.
    Pivot high: daily high > high of n previous AND n subsequent bars.
    Pivot low:  daily low  < low  of n previous AND n subsequent bars.
    Returns the high/low value at confirmed pivots, NaN elsewhere.
    The last n bars are always NaN (future candles not yet available).
    """
    high = df["high"]
    low = df["low"]

    is_pivot_high = pd.Series(True, index=df.index)
    is_pivot_low = pd.Series(True, index=df.index)

    for k in range(1, n + 1):
        is_pivot_high &= (high > high.shift(k)) & (high > high.shift(-k))
        is_pivot_low &= (low < low.shift(k)) & (low < low.shift(-k))

    pivot_high = pd.Series(np.nan, index=df.index)
    pivot_low = pd.Series(np.nan, index=df.index)
    pivot_high[is_pivot_high] = high[is_pivot_high]
    pivot_low[is_pivot_low] = low[is_pivot_low]

    # Forward-fill the last confirmed pivot level — no lookahead, pure support/resistance
    last_pivot_high = pivot_high.ffill()
    last_pivot_low = pivot_low.ffill()

    return {
        f"pivot_high_{n}": pivot_high,
        f"pivot_low_{n}": pivot_low,
        f"last_pivot_high_{n}": last_pivot_high,
        f"last_pivot_low_{n}": last_pivot_low,
    }


def calc_all_custom(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Calculate all custom indicators on a OHLCV + standard indicator DataFrame."""
    if df.empty or len(df) < 30:
        return {}

    results = {}
    results.update(high_low_break(df, lookback=20))
    results.update(high_low_break(df, lookback=52))  # yearly high/low
    results.update(pivot_high_low(df, n=2))

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
    return results
