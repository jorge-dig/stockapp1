"""
Writes signals to JSON and CSV files for external automation (n8n, scripts, etc.).
Output path: reports/YYYY-MM-DD/signals.json and signals.csv
"""
import csv
import json
import logging
from datetime import date
from pathlib import Path

from app.db.session import SessionLocal
from app.db.models import Signal, Ticker, Strategy, AlertLog

logger = logging.getLogger(__name__)
REPORTS_DIR = Path(__file__).parent.parent.parent / "reports"


def get_unsent_signals(session, report_date: date) -> list:
    signals = (
        session.query(Signal, Ticker, Strategy)
        .join(Ticker, Signal.ticker_id == Ticker.id)
        .join(Strategy, Signal.strategy_id == Strategy.id)
        .filter(Signal.date == report_date)
        .all()
    )
    return signals


def write_signals(report_date: date = None) -> Path:
    """Write today's signals to JSON + CSV. Returns output directory path."""
    if report_date is None:
        report_date = date.today()

    session = SessionLocal()
    try:
        rows = get_unsent_signals(session, report_date)
        out_dir = REPORTS_DIR / report_date.isoformat()
        out_dir.mkdir(parents=True, exist_ok=True)

        signals_data = []
        for sig, ticker, strategy in rows:
            record = {
                "id": sig.id,
                "date": report_date.isoformat(),
                "symbol": ticker.symbol,
                "asset_type": ticker.asset_type,
                "strategy": strategy.name,
                "signal_type": sig.signal_type,
                "close": sig.details_json.get("close") if sig.details_json else None,
                "details": sig.details_json,
            }
            signals_data.append(record)

        # Write JSON
        json_path = out_dir / "signals.json"
        json_path.write_text(json.dumps(signals_data, indent=2, default=str))

        # Write CSV
        csv_path = out_dir / "signals.csv"
        if signals_data:
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["id", "date", "symbol", "asset_type", "strategy", "signal_type", "close"])
                writer.writeheader()
                for r in signals_data:
                    writer.writerow({k: r[k] for k in ["id", "date", "symbol", "asset_type", "strategy", "signal_type", "close"]})

        logger.info(f"Wrote {len(signals_data)} signals to {out_dir}")
        return out_dir
    finally:
        session.close()


def dispatch_alerts(report_date: date = None):
    """Send unsent signals via Telegram and log them."""
    from app.alerts.telegram import send_message, format_signal

    if report_date is None:
        report_date = date.today()

    session = SessionLocal()
    try:
        rows = get_unsent_signals(session, report_date)
        sent = skipped = failed = 0

        for sig, ticker, strategy in rows:
            already_sent = session.query(AlertLog).filter_by(signal_id=sig.id, channel="telegram").first()
            if already_sent:
                skipped += 1
                continue

            close_val = sig.details_json.get("close", 0) if sig.details_json else 0
            text = format_signal(ticker.symbol, strategy.name, sig.signal_type, report_date, close_val or 0)
            ok = send_message(text)

            log = AlertLog(
                signal_id=sig.id,
                channel="telegram",
                status="sent" if ok else "failed",
            )
            session.add(log)
            if ok:
                sent += 1
            else:
                failed += 1

        session.commit()
        logger.info(f"Alerts dispatched: sent={sent}, failed={failed}, skipped={skipped}")
        return sent, failed
    finally:
        session.close()
