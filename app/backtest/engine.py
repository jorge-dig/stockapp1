"""
Backtesting engine — multi-timeframe, 5-year window.

Flow:
  1. Load full daily OHLCV from DB
  2. Resample to target timeframe (1D / 1W / 1M)
  3. Recalculate all indicators on the resampled series
  4. Evaluate strategy rules candle-by-candle
  5. Simulate long trades and compute metrics
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

import numpy as np
import pandas as pd

from app.db.session import SessionLocal
from app.db.models import OHLCV, Ticker
from app.indicators.standard import calc_all as calc_standard
from app.indicators.custom import calc_all_custom
from app.strategies.engine import eval_strategy

logger = logging.getLogger(__name__)

YEARS = 5
Timeframe = Literal["1D", "1W", "1M"]

RESAMPLE_MAP: dict[Timeframe, str] = {
    "1D": "D",
    "1W": "W-FRI",
    "1M": "ME",      # month-end
}

TRADING_DAYS_PER_YEAR: dict[Timeframe, float] = {
    "1D": 252,
    "1W": 52,
    "1M": 12,
}


# ─────────────────────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────────────────────

def load_daily_ohlcv(ticker_id: int, years: int = YEARS) -> pd.DataFrame:
    since = date.today() - timedelta(days=years * 366)
    session = SessionLocal()
    try:
        rows = (
            session.query(OHLCV)
            .filter(OHLCV.ticker_id == ticker_id, OHLCV.date >= since)
            .order_by(OHLCV.date)
            .all()
        )
        return pd.DataFrame([{
            "date": r.date, "open": float(r.open or 0),
            "high": float(r.high or 0), "low": float(r.low or 0),
            "close": float(r.close or 0), "volume": int(r.volume or 0),
        } for r in rows])
    finally:
        session.close()


def resample_ohlcv(df: pd.DataFrame, tf: Timeframe) -> pd.DataFrame:
    """Resample a daily OHLCV DataFrame to the given timeframe."""
    if tf == "1D":
        return df.reset_index(drop=True)

    rule = RESAMPLE_MAP[tf]
    df2 = df.copy()
    df2["date"] = pd.to_datetime(df2["date"])
    df2 = df2.set_index("date")

    resampled = df2.resample(rule).agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna(subset=["close"])
    resampled = resampled[resampled["close"] > 0]
    resampled = resampled.reset_index()
    resampled["date"] = resampled["date"].dt.date
    return resampled


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all technical indicators to a resampled OHLCV DataFrame."""
    df = df.copy().reset_index(drop=True)
    std = calc_standard(df)
    for name, series in std.items():
        df[name] = series.values if hasattr(series, "values") else series

    custom = calc_all_custom(df)
    for name, series in custom.items():
        df[name] = series.values if hasattr(series, "values") else series

    return df


# ─────────────────────────────────────────────────────────────
# Signal generation
# ─────────────────────────────────────────────────────────────

def generate_signals(df: pd.DataFrame, rules: dict) -> pd.Series:
    """
    Evaluate strategy rules on every row.
    Returns a Series with values: 1 = BUY, -1 = SELL, 0 = nothing.
    """
    signals = pd.Series(0, index=df.index)
    rows_dicts = df.to_dict(orient="records")

    sig_type = rules.get("signal", "BUY")
    fire_val = 1 if sig_type in ("BUY", "ALERT") else -1

    for i in range(1, len(rows_dicts)):
        triggered = eval_strategy(rules, rows_dicts[i], rows_dicts[i - 1])
        if triggered:
            signals.iloc[i] = fire_val

    return signals


# ─────────────────────────────────────────────────────────────
# Trade simulation
# ─────────────────────────────────────────────────────────────

@dataclass
class Trade:
    entry_date: date
    entry_price: float
    exit_date: date | None = None
    exit_price: float | None = None
    pnl_pct: float = 0.0
    pnl_abs: float = 0.0

    @property
    def closed(self) -> bool:
        return self.exit_date is not None

    def close(self, exit_date: date, exit_price: float, capital: float):
        self.exit_date  = exit_date
        self.exit_price = exit_price
        self.pnl_pct    = (exit_price - self.entry_price) / self.entry_price * 100
        self.pnl_abs    = capital * (self.pnl_pct / 100)


@dataclass
class BacktestResult:
    symbol: str
    strategy_name: str
    timeframe: str
    trades: list[Trade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=pd.Series)
    df: pd.DataFrame = field(default_factory=pd.DataFrame)      # price + indicator df
    buy_signals: list[date] = field(default_factory=list)
    sell_signals: list[date] = field(default_factory=list)

    # ── Metrics ───────────────────────────────────────────────────────────────
    @property
    def closed_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.closed]

    @property
    def total_trades(self) -> int:
        return len(self.closed_trades)

    @property
    def total_return_pct(self) -> float:
        if self.equity_curve.empty:
            return 0.0
        return (self.equity_curve.iloc[-1] / self.equity_curve.iloc[0] - 1) * 100

    @property
    def buy_and_hold_pct(self) -> float:
        if self.df.empty or len(self.df) < 2:
            return 0.0
        return (self.df["close"].iloc[-1] / self.df["close"].iloc[0] - 1) * 100

    @property
    def win_rate(self) -> float:
        if not self.closed_trades:
            return 0.0
        wins = sum(1 for t in self.closed_trades if t.pnl_pct > 0)
        return wins / len(self.closed_trades) * 100

    @property
    def avg_trade_pct(self) -> float:
        if not self.closed_trades:
            return 0.0
        return np.mean([t.pnl_pct for t in self.closed_trades])

    @property
    def best_trade_pct(self) -> float:
        if not self.closed_trades:
            return 0.0
        return max(t.pnl_pct for t in self.closed_trades)

    @property
    def worst_trade_pct(self) -> float:
        if not self.closed_trades:
            return 0.0
        return min(t.pnl_pct for t in self.closed_trades)

    @property
    def max_drawdown_pct(self) -> float:
        if self.equity_curve.empty:
            return 0.0
        roll_max = self.equity_curve.cummax()
        drawdown = (self.equity_curve - roll_max) / roll_max * 100
        return float(drawdown.min())

    @property
    def sharpe_ratio(self) -> float:
        if self.equity_curve.empty or len(self.equity_curve) < 2:
            return 0.0
        returns = self.equity_curve.pct_change().dropna()
        if returns.std() == 0:
            return 0.0
        ann_factor = TRADING_DAYS_PER_YEAR.get(self.timeframe, 252) ** 0.5
        return float((returns.mean() / returns.std()) * ann_factor)

    @property
    def cagr(self) -> float:
        if self.equity_curve.empty or len(self.equity_curve) < 2:
            return 0.0
        n_years = len(self.equity_curve) / TRADING_DAYS_PER_YEAR.get(self.timeframe, 252)
        if n_years <= 0:
            return 0.0
        return ((self.equity_curve.iloc[-1] / self.equity_curve.iloc[0]) ** (1 / n_years) - 1) * 100


def run_backtest(
    ticker_id: int,
    symbol: str,
    strategy_name: str,
    rules: dict,
    tf: Timeframe,
    initial_capital: float = 10_000.0,
    years: int = YEARS,
) -> BacktestResult:
    """Run a full backtest for one ticker × strategy × timeframe."""
    result = BacktestResult(symbol=symbol, strategy_name=strategy_name, timeframe=tf)

    # 1. Load & resample data
    daily_df = load_daily_ohlcv(ticker_id, years)
    if daily_df.empty or len(daily_df) < 50:
        logger.warning(f"{symbol}: not enough data for backtest ({tf})")
        return result

    df = resample_ohlcv(daily_df, tf)
    if len(df) < 30:
        return result

    # 2. Add indicators
    df = add_indicators(df)
    result.df = df

    # 3. Generate signals
    sigs = generate_signals(df, rules)

    # 4. Simulate trades
    capital   = initial_capital
    equity    = [capital]
    dates_idx = df["date"].tolist()
    in_trade  = False
    current_trade: Trade | None = None

    for i in range(len(df)):
        sig   = sigs.iloc[i]
        close = df["close"].iloc[i]
        d     = dates_idx[i]

        if sig == 1 and not in_trade:          # BUY signal
            current_trade = Trade(entry_date=d, entry_price=close)
            in_trade = True
            result.buy_signals.append(d)

        elif sig == -1 and in_trade and current_trade:   # SELL signal
            current_trade.close(d, close, capital)
            capital += current_trade.pnl_abs
            result.trades.append(current_trade)
            result.sell_signals.append(d)
            in_trade = False
            current_trade = None

        # Mark-to-market equity while in trade
        if in_trade and current_trade:
            mtm = capital * (close / current_trade.entry_price)
            equity.append(mtm)
        else:
            equity.append(capital)

    # Close any open trade at last price
    if in_trade and current_trade:
        last_close = df["close"].iloc[-1]
        current_trade.close(dates_idx[-1], last_close, capital)
        capital += current_trade.pnl_abs
        result.trades.append(current_trade)

    result.equity_curve = pd.Series(
        equity[1:],          # drop the initial pre-loop entry
        index=pd.to_datetime(df["date"]),
    )
    return result
