"""
Standard technical indicators via the `ta` library (Python 3.11+ / pandas 2.x compatible).
All functions receive an OHLCV DataFrame and return a dict {indicator_name: Series}.
"""
import logging
import pandas as pd
import ta

logger = logging.getLogger(__name__)


def _safe(name: str, func, *args, **kwargs) -> dict:
    try:
        result = func(*args, **kwargs)
        if result is None:
            return {}
        if isinstance(result, pd.Series):
            return {name: result.reset_index(drop=True)}
        return {}
    except Exception as e:
        logger.warning(f"Indicator {name} failed: {e}")
        return {}


def calc_sma(df: pd.DataFrame, periods: list = [20, 50, 200]) -> dict:
    results = {}
    for p in periods:
        results.update(_safe(f"sma_{p}", ta.trend.sma_indicator, df["close"], window=p))
    return results


def calc_ema(df: pd.DataFrame, periods: list = [9, 20, 50, 200]) -> dict:
    results = {}
    for p in periods:
        results.update(_safe(f"ema_{p}", ta.trend.ema_indicator, df["close"], window=p))
    return results


def calc_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    try:
        macd = ta.trend.MACD(df["close"], window_slow=slow, window_fast=fast, window_sign=signal)
        return {
            "macd_line":      macd.macd().reset_index(drop=True),
            "macd_signal":    macd.macd_signal().reset_index(drop=True),
            "macd_histogram": macd.macd_diff().reset_index(drop=True),
        }
    except Exception as e:
        logger.warning(f"MACD failed: {e}")
        return {}


def calc_rsi(df: pd.DataFrame, periods: list = [14]) -> dict:
    results = {}
    for p in periods:
        results.update(_safe(f"rsi_{p}", ta.momentum.rsi, df["close"], window=p))
    return results


def calc_stochastic(df: pd.DataFrame, k: int = 14, d: int = 3, smooth_k: int = 3) -> dict:
    try:
        stoch = ta.momentum.StochasticOscillator(df["high"], df["low"], df["close"], window=k, smooth_window=d)
        return {
            "stoch_k": stoch.stoch().reset_index(drop=True),
            "stoch_d": stoch.stoch_signal().reset_index(drop=True),
        }
    except Exception as e:
        logger.warning(f"Stochastic failed: {e}")
        return {}


def calc_bollinger(df: pd.DataFrame, length: int = 20, std: float = 2.0) -> dict:
    try:
        bb = ta.volatility.BollingerBands(df["close"], window=length, window_dev=std)
        return {
            "bb_upper":     bb.bollinger_hband().reset_index(drop=True),
            "bb_mid":       bb.bollinger_mavg().reset_index(drop=True),
            "bb_lower":     bb.bollinger_lband().reset_index(drop=True),
            "bb_bandwidth": bb.bollinger_wband().reset_index(drop=True),
            "bb_percent":   bb.bollinger_pband().reset_index(drop=True),
        }
    except Exception as e:
        logger.warning(f"Bollinger failed: {e}")
        return {}


def calc_atr(df: pd.DataFrame, length: int = 14) -> dict:
    return _safe(
        f"atr_{length}",
        ta.volatility.average_true_range,
        df["high"], df["low"], df["close"], window=length
    )


def calc_obv(df: pd.DataFrame) -> dict:
    return _safe("obv", ta.volume.on_balance_volume, df["close"], df["volume"])


def calc_vwap(df: pd.DataFrame) -> dict:
    if "volume" not in df.columns or df["volume"].isna().all():
        return {}
    try:
        vwap = ta.volume.VolumeWeightedAveragePrice(
            df["high"], df["low"], df["close"], df["volume"]
        )
        return {"vwap": vwap.volume_weighted_average_price().reset_index(drop=True)}
    except Exception as e:
        logger.warning(f"VWAP failed: {e}")
        return {}


def calc_adx(df: pd.DataFrame, length: int = 14) -> dict:
    try:
        adx = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=length)
        return {
            "adx":     adx.adx().reset_index(drop=True),
            "adx_dmp": adx.adx_pos().reset_index(drop=True),
            "adx_dmn": adx.adx_neg().reset_index(drop=True),
        }
    except Exception as e:
        logger.warning(f"ADX failed: {e}")
        return {}


def calc_all(df: pd.DataFrame) -> dict:
    """Calculate all standard indicators on an OHLCV DataFrame."""
    if df.empty or len(df) < 30:
        return {}

    df = df.copy().reset_index(drop=True)
    df.columns = [c.lower() for c in df.columns]

    results = {}
    results.update(calc_sma(df))
    results.update(calc_ema(df))
    results.update(calc_macd(df))
    results.update(calc_rsi(df))
    results.update(calc_stochastic(df))
    results.update(calc_bollinger(df))
    results.update(calc_atr(df))
    results.update(calc_obv(df))
    results.update(calc_vwap(df))
    results.update(calc_adx(df))
    return results
