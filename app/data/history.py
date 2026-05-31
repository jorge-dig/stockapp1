"""
Script de carga histórica inicial desde 2020.
Uso: python -m app.data.history [--symbol AAPL] [--all]
"""
import argparse
import logging
import time
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.db.session import SessionLocal
from app.db.models import Ticker, OHLCV, DataEvent
from app.data.fetcher import get_fetcher

logger = logging.getLogger(__name__)

HISTORY_START = date(2020, 1, 1)
BATCH_DELAY = 0.5  # seconds between tickers to respect rate limits


def upsert_ohlcv(session, ticker_id: int, df) -> int:
    """Inserts or updates OHLCV rows. Returns count of rows processed."""
    if df.empty:
        return 0
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "ticker_id": ticker_id,
            "date": row["date"],
            "open": float(row["open"]) if row["open"] is not None else None,
            "high": float(row["high"]) if row["high"] is not None else None,
            "low": float(row["low"]) if row["low"] is not None else None,
            "close": float(row["close"]) if row["close"] is not None else None,
            "volume": int(row["volume"]) if row.get("volume") is not None and str(row["volume"]) != "<NA>" else None,
            "source": row.get("source", "unknown"),
        })

    stmt = mysql_insert(OHLCV).values(rows)
    stmt = stmt.on_duplicate_key_update(
        open=stmt.inserted.open,
        high=stmt.inserted.high,
        low=stmt.inserted.low,
        close=stmt.inserted.close,
        volume=stmt.inserted.volume,
        source=stmt.inserted.source,
    )
    session.execute(stmt)
    session.commit()
    return len(rows)


def _begin_event(session, ticker_id: int, event_type: str,
                 date_from=None, date_to=None, source: str = None) -> DataEvent:
    """Create a DataEvent record in 'running' state and flush it to get an ID."""
    event = DataEvent(
        ticker_id=ticker_id,
        event_type=event_type,
        started_at=datetime.utcnow(),
        date_from=date_from,
        date_to=date_to,
        source=source,
        status="running",
    )
    session.add(event)
    session.flush()   # assigns event.id without a full commit
    return event


def _finish_event(session, event: DataEvent,
                  rows_added: int = 0, rows_updated: int = 0,
                  total_rows: int = None, error: Exception = None):
    """Stamp a DataEvent with completion info and commit."""
    now = datetime.utcnow()
    event.completed_at = now
    event.duration_seconds = (now - event.started_at).total_seconds()
    event.rows_added = rows_added
    event.rows_updated = rows_updated
    event.total_rows_after = total_rows
    if error:
        event.status = "failed"
        event.error_msg = str(error)[:1000]
    else:
        event.status = "success"
    session.commit()


def load_ticker_history(symbol: str, start: date = HISTORY_START,
                        end: date = None, event_type: str = "initial_load") -> int:
    """Download and store full history for one ticker. Returns rows inserted."""
    if end is None:
        end = date.today()

    session = SessionLocal()
    event = None
    try:
        ticker = session.query(Ticker).filter_by(symbol=symbol).first()
        if not ticker:
            logger.error(f"Ticker {symbol} not found in DB. Add it first via the dashboard.")
            return 0

        # Start audit event
        event = _begin_event(
            session, ticker.id, event_type,
            date_from=start, date_to=end,
            source=ticker.asset_type,
        )
        # flush commits the DataEvent as "running" via upsert_ohlcv's commit below;
        # a standalone commit here keeps the running record visible immediately
        session.commit()

        fetcher = get_fetcher(ticker.asset_type, symbol)
        logger.info(f"Downloading {symbol} ({ticker.asset_type}) from {start} to {end}...")
        df = fetcher.fetch(symbol, start, end)

        if df.empty:
            logger.warning(f"No data returned for {symbol}")
            total = session.query(func.count(OHLCV.id)).filter(OHLCV.ticker_id == ticker.id).scalar() or 0
            _finish_event(session, event, rows_added=0, total_rows=total)
            return 0

        count = upsert_ohlcv(session, ticker.id, df)

        total = session.query(func.count(OHLCV.id)).filter(OHLCV.ticker_id == ticker.id).scalar() or 0
        _finish_event(session, event, rows_added=count, total_rows=total)

        logger.info(f"  → {count} rows stored for {symbol} (total in DB: {total})")
        return count

    except Exception as e:
        logger.error(f"load_ticker_history error for {symbol}: {e}")
        if event is not None:
            try:
                _finish_event(session, event, error=e)
            except Exception:
                session.rollback()
        raise
    finally:
        session.close()


def get_last_date(ticker_id: int) -> date:
    """Returns the most recent date in ohlcv for a ticker, or HISTORY_START if none."""
    session = SessionLocal()
    try:
        result = session.query(func.max(OHLCV.date)).filter(OHLCV.ticker_id == ticker_id).scalar()
        return result if result else HISTORY_START
    finally:
        session.close()


def load_all_history(start: date = HISTORY_START):
    """Download history for all active tickers."""
    session = SessionLocal()
    try:
        tickers = session.query(Ticker).filter_by(active=1).all()
        total = len(tickers)
        logger.info(f"Loading history for {total} active tickers from {start}...")
        for i, t in enumerate(tickers, 1):
            logger.info(f"[{i}/{total}] {t.symbol}")
            load_ticker_history(t.symbol, start=start)
            time.sleep(BATCH_DELAY)
    finally:
        session.close()


def incremental_update():
    """Update each ticker from its last stored date to today."""
    from datetime import timedelta
    session = SessionLocal()
    try:
        tickers = session.query(Ticker).filter_by(active=1).all()
        today = date.today()
        for t in tickers:
            last = get_last_date(t.id)
            if last >= today:
                logger.info(f"{t.symbol}: already up to date")
                continue
            load_ticker_history(
                t.symbol,
                start=last + timedelta(days=1),
                end=today,
                event_type="incremental_update",
            )
            time.sleep(BATCH_DELAY)
    finally:
        session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Load historical OHLCV data")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--symbol", help="Load history for a single ticker symbol")
    group.add_argument("--all", action="store_true", help="Load history for all active tickers")
    group.add_argument("--update", action="store_true", help="Incremental update (last date → today)")
    parser.add_argument("--start", default="2020-01-01", help="Start date YYYY-MM-DD (default 2020-01-01)")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)

    if args.symbol:
        load_ticker_history(args.symbol, start=start_date)
    elif args.all:
        load_all_history(start=start_date)
    elif args.update:
        incremental_update()
