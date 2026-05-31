"""
Calculates all indicators for a ticker and persists them to the indicators table.
"""
import logging
from datetime import date, datetime

import pandas as pd
from sqlalchemy import func
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.db.session import SessionLocal
from app.db.models import Ticker, OHLCV, Indicator, DataEvent
from app.indicators.standard import calc_all as calc_standard
from app.indicators.custom import calc_all_custom

logger = logging.getLogger(__name__)


def load_ohlcv(session, ticker_id: int, since: date = None) -> pd.DataFrame:
    query = session.query(OHLCV).filter_by(ticker_id=ticker_id)
    if since:
        query = query.filter(OHLCV.date >= since)
    rows = query.order_by(OHLCV.date).all()
    if not rows:
        return pd.DataFrame()
    data = [{
        "date": r.date, "open": float(r.open or 0), "high": float(r.high or 0),
        "low": float(r.low or 0), "close": float(r.close or 0),
        "volume": int(r.volume) if r.volume else None,
    } for r in rows]
    return pd.DataFrame(data)


def upsert_indicators(session, ticker_id: int, date_val: date, indicators: dict):
    rows = [
        {"ticker_id": ticker_id, "date": date_val, "indicator_name": name, "value": float(val)}
        for name, val in indicators.items()
        if val is not None and str(val) not in ("nan", "inf", "-inf")
    ]
    if not rows:
        return
    stmt = mysql_insert(Indicator).values(rows)
    stmt = stmt.on_duplicate_key_update(value=stmt.inserted.value)
    session.execute(stmt)


def calc_and_store(ticker_id: int, since: date = None) -> int:
    """Calculate all indicators for ticker_id and store them. Returns rows stored."""
    session = SessionLocal()
    event = None
    started = datetime.utcnow()
    try:
        ticker = session.query(Ticker).filter_by(id=ticker_id).first()
        if not ticker:
            return 0

        # Load full OHLCV (need enough history for 200-period indicators)
        df = load_ohlcv(session, ticker_id)
        if df.empty or len(df) < 30:
            logger.warning(f"{ticker.symbol}: not enough data for indicators")
            return 0

        # Determine date range for the audit log
        date_from = df["date"].min() if since is None else since
        date_to = df["date"].max()

        # Create audit event
        event = DataEvent(
            ticker_id=ticker_id,
            event_type="indicator_calc",
            started_at=started,
            date_from=date_from,
            date_to=date_to,
            source=ticker.asset_type,
            status="running",
        )
        session.add(event)
        session.commit()

        # Calculate standard indicators on full history
        std = calc_standard(df)
        for name, series in std.items():
            df[name] = series.values

        # Then custom indicators (uses standard results via df columns)
        custom = calc_all_custom(df)
        for name, series in custom.items():
            df[name] = series.values

        all_indicator_names = list(std.keys()) + list(custom.keys())

        # Determine which dates to store (only new dates if since is set)
        if since:
            df_to_store = df[df["date"] >= since]
        else:
            df_to_store = df

        count = 0
        BATCH = 100   # commit every N dates to avoid huge transactions
        for i, (_, row) in enumerate(df_to_store.iterrows()):
            ind_values = {name: row.get(name) for name in all_indicator_names}
            upsert_indicators(session, ticker_id, row["date"], ind_values)
            count += len([v for v in ind_values.values() if v is not None])
            if (i + 1) % BATCH == 0:
                session.commit()

        session.commit()   # final remainder

        # Finish audit event
        now = datetime.utcnow()
        event.completed_at = now
        event.duration_seconds = (now - started).total_seconds()
        event.rows_added = count
        event.total_rows_after = session.query(func.count(Indicator.id)).filter(
            Indicator.ticker_id == ticker_id
        ).scalar() or 0
        event.status = "success"
        session.commit()

        logger.info(f"{ticker.symbol}: stored {count} indicator values for {len(df_to_store)} dates")
        return count
    except Exception as e:
        session.rollback()
        logger.error(f"calc_and_store error for ticker_id={ticker_id}: {e}")
        if event is not None:
            try:
                now = datetime.utcnow()
                event.completed_at = now
                event.duration_seconds = (now - started).total_seconds()
                event.status = "failed"
                event.error_msg = str(e)[:1000]
                session.commit()
            except Exception:
                session.rollback()
        return 0
    finally:
        session.close()


def calc_all_tickers(since: date = None):
    """Calculate and store indicators for all active tickers."""
    session = SessionLocal()
    try:
        tickers = session.query(Ticker).filter_by(active=1).all()
    finally:
        session.close()

    for t in tickers:
        logger.info(f"Calculating indicators for {t.symbol}...")
        calc_and_store(t.id, since=since)
