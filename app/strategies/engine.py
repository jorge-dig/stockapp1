"""
Strategy engine: evaluates JSON-defined rule sets against indicator values
and generates signals in the DB.

Rule JSON format:
{
  "conditions": [
    {"indicator": "rsi_14", "op": ">", "value": 70},
    {"indicator": "close", "op": ">", "indicator2": "ema_50"},
    {"indicator": "macd_line", "op": "cross_above", "indicator2": "macd_signal"}
  ],
  "logic": "AND",           # AND | OR
  "signal": "SELL",         # BUY | SELL | ALERT
  "lookback": 1             # candles to look back for cross detection (optional)
}
"""
import logging
import operator
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.db.session import SessionLocal
from app.db.models import Ticker, OHLCV, Indicator, Strategy, Signal
from app.indicators.calculator import load_ohlcv

logger = logging.getLogger(__name__)

OPS = {
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


def _get_value(row: dict, key: str) -> float | None:
    val = row.get(key)
    if val is None or (isinstance(val, float) and (pd.isna(val) or not np.isfinite(val))):
        return None
    return float(val)


def eval_condition(condition: dict, row: dict, prev_row: dict | None = None) -> bool | None:
    """
    Evaluates a single condition against a row dict of {indicator: value}.
    Returns True/False, or None if data is missing (treated as False).
    """
    ind = condition["indicator"]
    op = condition["op"]
    val1 = _get_value(row, ind)
    if val1 is None:
        return None

    if op in OPS:
        if "indicator2" in condition:
            val2 = _get_value(row, condition["indicator2"])
            if val2 is None:
                return None
            return OPS[op](val1, val2)
        elif "value" in condition:
            return OPS[op](val1, float(condition["value"]))
        return None

    # Crossover operators require previous row
    if op in ("cross_above", "cross_below") and prev_row is not None:
        val1_prev = _get_value(prev_row, ind)
        if val1_prev is None:
            return None
        ind2 = condition.get("indicator2")
        if ind2:
            val2_curr = _get_value(row, ind2)
            val2_prev = _get_value(prev_row, ind2)
            if val2_curr is None or val2_prev is None:
                return None
        elif "value" in condition:
            val2_curr = float(condition["value"])
            val2_prev = val2_curr
        else:
            return None
        if op == "cross_above":
            return val1_prev <= val2_prev and val1 > val2_curr
        else:
            return val1_prev >= val2_prev and val1 < val2_curr

    return None


def eval_strategy(rules: dict, row: dict, prev_row: dict | None = None) -> bool:
    """Evaluates all conditions with AND/OR logic."""
    conditions = rules.get("conditions", [])
    # Tolerate a single condition dict instead of a list
    if isinstance(conditions, dict):
        conditions = [conditions]
    logic = rules.get("logic", "AND").upper()
    if not conditions:
        return False

    results = [eval_condition(c, row, prev_row) for c in conditions]
    # Treat None (missing data) as False
    results = [r if r is not None else False for r in results]

    if logic == "OR":
        return any(results)
    return all(results)


def build_row_dict(date_val: date, ohlcv_row: dict, indicator_rows: list[dict]) -> dict:
    """Merges OHLCV and indicator values into a flat dict for condition evaluation."""
    row = {k: v for k, v in ohlcv_row.items()}
    for ind in indicator_rows:
        row[ind["indicator_name"]] = ind["value"]
    return row


def run_strategy(strategy: Strategy, ticker: Ticker, session, since: date = None) -> list[Signal]:
    """Runs one strategy on dates >= since for one ticker. Returns new Signal objects."""
    from datetime import timedelta
    rules = strategy.rules_json
    signal_type = rules.get("signal", "ALERT")

    # Need enough lookback for cross detection even when `since` is recent.
    # Load full OHLCV but only emit signals for dates >= since.
    df = load_ohlcv(session, ticker.id)
    if df.empty:
        return []

    # Load all indicators into a pivot dict: {date: {indicator: value}}
    ind_query = session.query(Indicator).filter_by(ticker_id=ticker.id)
    ind_rows = ind_query.all()
    ind_by_date: dict[date, dict] = {}
    for r in ind_rows:
        if r.date not in ind_by_date:
            ind_by_date[r.date] = {}
        ind_by_date[r.date][r.indicator_name] = float(r.value) if r.value is not None else None

    # Check existing signals to avoid duplicates
    existing = {
        (s.date, s.strategy_id)
        for s in session.query(Signal).filter_by(ticker_id=ticker.id, strategy_id=strategy.id).all()
    }

    signals = []
    dates = sorted(df["date"].tolist())
    for i, d in enumerate(dates):
        # Skip dates before `since` — but still use them as prev_row for crossover logic
        if since and d < since:
            continue
        ohlcv_row = df[df["date"] == d].iloc[0].to_dict()
        ind_row = ind_by_date.get(d, {})
        row = {**ohlcv_row, **ind_row}

        prev_row = None
        if i > 0:
            prev_d = dates[i - 1]
            prev_ohlcv = df[df["date"] == prev_d].iloc[0].to_dict()
            prev_ind = ind_by_date.get(prev_d, {})
            prev_row = {**prev_ohlcv, **prev_ind}

        if (d, strategy.id) in existing:
            continue

        if eval_strategy(rules, row, prev_row):
            sig = Signal(
                ticker_id=ticker.id,
                strategy_id=strategy.id,
                date=d,
                signal_type=signal_type,
                details_json={
                    "close": ohlcv_row.get("close"),
                    "triggered_conditions": [str(c) for c in rules.get("conditions", [])],
                },
            )
            signals.append(sig)

    return signals


def run_all_strategies(since: date = None):
    """Evaluates all active strategies on all active tickers since a given date."""
    from datetime import timedelta
    if since is None:
        since = date.today() - timedelta(days=3)

    session = SessionLocal()
    try:
        strategies = session.query(Strategy).filter_by(active=1).all()
        tickers = session.query(Ticker).filter_by(active=1).all()
        total_signals = 0

        for strategy in strategies:
            for ticker in tickers:
                new_signals = run_strategy(strategy, ticker, session, since=since)
                if new_signals:
                    session.add_all(new_signals)
                    session.commit()
                    total_signals += len(new_signals)
                    logger.info(f"  {ticker.symbol} / {strategy.name}: {len(new_signals)} signals")

        logger.info(f"Strategy run complete. Total new signals: {total_signals}")
        return total_signals
    except Exception as e:
        session.rollback()
        logger.error(f"run_all_strategies error: {e}")
        return 0
    finally:
        session.close()
