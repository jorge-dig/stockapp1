"""
Daily report generator: Markdown + PDF.
Output: reports/YYYY-MM-DD/daily_report.md and daily_report.pdf
"""
import logging
from datetime import date, datetime
from pathlib import Path

from fpdf import FPDF
from sqlalchemy import func

from app.db.session import SessionLocal
from app.db.models import Ticker, OHLCV, Signal, Strategy, Indicator

logger = logging.getLogger(__name__)
REPORTS_DIR = Path(__file__).parent.parent.parent / "reports"

# Mapping of Unicode characters that are outside Latin-1 but common in financial text
_UNICODE_REPLACEMENTS = str.maketrans({
    "—": "-",   # em dash  —
    "–": "-",   # en dash  –
    "‘": "'",   # left single quotation mark
    "’": "'",   # right single quotation mark / apostrophe
    "“": '"',   # left double quotation mark
    "”": '"',   # right double quotation mark
    "…": "...", # ellipsis
    "•": "*",   # bullet
    "×": "x",   # multiplication sign
    "−": "-",   # minus sign
})


def _safe(text: str) -> str:
    """Sanitise a string so it only contains characters supported by fpdf Latin-1 fonts."""
    text = str(text).translate(_UNICODE_REPLACEMENTS)
    # Catch-all: encode to Latin-1, replacing anything still outside the range
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _get_report_data(session, report_date: date) -> dict:
    total_active = session.query(Ticker).filter_by(active=1).count()

    # Signals for the day
    signals = (
        session.query(Signal, Ticker, Strategy)
        .join(Ticker, Signal.ticker_id == Ticker.id)
        .join(Strategy, Signal.strategy_id == Strategy.id)
        .filter(Signal.date == report_date)
        .all()
    )

    buy_signals = [s for s, t, st in signals if s.signal_type == "BUY"]
    sell_signals = [s for s, t, st in signals if s.signal_type == "SELL"]
    alert_signals = [s for s, t, st in signals if s.signal_type == "ALERT"]

    # Market movers: top 5 gainers and losers for the day vs prior day
    movers = _get_movers(session, report_date, limit=5)

    return {
        "date": report_date,
        "total_active_tickers": total_active,
        "total_signals": len(signals),
        "buy_count": len(buy_signals),
        "sell_count": len(sell_signals),
        "alert_count": len(alert_signals),
        "signals": [(s, t, st) for s, t, st in signals],
        "top_gainers": movers["gainers"],
        "top_losers": movers["losers"],
    }


def _get_movers(session, report_date: date, limit: int = 5) -> dict:
    from datetime import timedelta
    prev_date = report_date - timedelta(days=1)

    today_rows = {
        r.ticker_id: r for r in session.query(OHLCV).filter_by(date=report_date).all()
    }
    prev_rows = {
        r.ticker_id: r for r in session.query(OHLCV).filter_by(date=prev_date).all()
    }

    changes = []
    for tid, today in today_rows.items():
        prev = prev_rows.get(tid)
        if prev and prev.close and today.close:
            pct = (float(today.close) - float(prev.close)) / float(prev.close) * 100
            ticker = session.query(Ticker).filter_by(id=tid).first()
            if ticker:
                changes.append({"symbol": ticker.symbol, "close": float(today.close), "change_pct": pct})

    changes.sort(key=lambda x: x["change_pct"])
    return {"losers": changes[:limit], "gainers": list(reversed(changes[-limit:]))}


def generate_markdown(data: dict) -> str:
    d = data["date"]
    lines = [
        f"# Daily Market Report — {d}",
        f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        "",
        "## Summary",
        f"- Active tickers monitored: **{data['total_active_tickers']}**",
        f"- Signals today: **{data['total_signals']}** (🟢 BUY: {data['buy_count']} | 🔴 SELL: {data['sell_count']} | 🟡 ALERT: {data['alert_count']})",
        "",
    ]

    if data["top_gainers"]:
        lines += ["## Top Gainers", "| Symbol | Close | Change % |", "|--------|-------|----------|"]
        for m in data["top_gainers"]:
            lines.append(f"| {m['symbol']} | {m['close']:.4f} | +{m['change_pct']:.2f}% |")
        lines.append("")

    if data["top_losers"]:
        lines += ["## Top Losers", "| Symbol | Close | Change % |", "|--------|-------|----------|"]
        for m in data["top_losers"]:
            lines.append(f"| {m['symbol']} | {m['close']:.4f} | {m['change_pct']:.2f}% |")
        lines.append("")

    if data["signals"]:
        lines += ["## Signals", "| Symbol | Type | Strategy | Close |", "|--------|------|----------|-------|"]
        for sig, ticker, strategy in data["signals"]:
            close = sig.details_json.get("close", "N/A") if sig.details_json else "N/A"
            lines.append(f"| {ticker.symbol} | {sig.signal_type} | {strategy.name} | {close} |")
        lines.append("")
    else:
        lines += ["## Signals", "_No signals generated today._", ""]

    return "\n".join(lines)


def generate_pdf(data: dict, output_path: Path):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _safe(f"Daily Market Report - {data['date']}"), ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _safe(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"), ln=True, align="C")
    pdf.ln(6)

    # Summary box
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Summary", ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, _safe(f"Active tickers: {data['total_active_tickers']}"), ln=True)
    pdf.cell(0, 6, _safe(
        f"Total signals: {data['total_signals']}  "
        f"(BUY: {data['buy_count']} | SELL: {data['sell_count']} | ALERT: {data['alert_count']})"
    ), ln=True)
    pdf.ln(4)

    def section_title(title):
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _safe(title), ln=True)
        pdf.set_font("Helvetica", "", 10)

    def table_row(cols, widths):
        for text, w in zip(cols, widths):
            pdf.cell(w, 6, _safe(str(text)), border=1)
        pdf.ln()

    # Movers
    if data["top_gainers"]:
        section_title("Top Gainers")
        table_row(["Symbol", "Close", "Change %"], [40, 50, 50])
        for m in data["top_gainers"]:
            table_row([m["symbol"], f"{m['close']:.4f}", f"+{m['change_pct']:.2f}%"], [40, 50, 50])
        pdf.ln(4)

    if data["top_losers"]:
        section_title("Top Losers")
        table_row(["Symbol", "Close", "Change %"], [40, 50, 50])
        for m in data["top_losers"]:
            table_row([m["symbol"], f"{m['close']:.4f}", f"{m['change_pct']:.2f}%"], [40, 50, 50])
        pdf.ln(4)

    # Signals
    section_title("Signals")
    if data["signals"]:
        table_row(["Symbol", "Type", "Strategy", "Close"], [30, 20, 80, 30])
        for sig, ticker, strategy in data["signals"]:
            close = sig.details_json.get("close", "") if sig.details_json else ""
            table_row([ticker.symbol, sig.signal_type, strategy.name[:35], str(close)[:10]], [30, 20, 80, 30])
    else:
        pdf.cell(0, 6, "No signals generated today.", ln=True)

    pdf.output(str(output_path))


def generate_daily_report(report_date: date = None) -> Path:
    if report_date is None:
        report_date = date.today()

    session = SessionLocal()
    try:
        data = _get_report_data(session, report_date)
    finally:
        session.close()

    out_dir = REPORTS_DIR / report_date.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    md_path = out_dir / "daily_report.md"
    pdf_path = out_dir / "daily_report.pdf"

    md_content = generate_markdown(data)
    md_path.write_text(md_content, encoding="utf-8")
    generate_pdf(data, pdf_path)

    logger.info(f"Report generated: {out_dir}")

    # Send summary to Telegram
    from app.alerts.telegram import send_daily_summary
    send_daily_summary(
        data["total_signals"], data["buy_count"], data["sell_count"], data["alert_count"], report_date
    )

    return out_dir
