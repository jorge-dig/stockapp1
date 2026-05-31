"""Telegram alert sender using the Bot API (no SDK needed, just requests)."""
import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API = "https://api.telegram.org"


def send_message(text: str, parse_mode: str = "Markdown") -> bool:
    """Send a message to the configured Telegram chat. Returns True on success."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)")
        return False
    try:
        resp = requests.post(
            f"{TELEGRAM_API}/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


def format_signal(symbol: str, strategy_name: str, signal_type: str, date_val, close: float) -> str:
    emoji = {"BUY": "🟢", "SELL": "🔴", "ALERT": "🟡"}.get(signal_type, "⚪")
    return (
        f"{emoji} *{signal_type} Signal*\n"
        f"*Ticker:* {symbol}\n"
        f"*Strategy:* {strategy_name}\n"
        f"*Date:* {date_val}\n"
        f"*Close:* {close:.4f}"
    )


def send_daily_summary(total_signals: int, buy: int, sell: int, alert: int, report_date) -> bool:
    text = (
        f"📊 *Daily Summary — {report_date}*\n"
        f"Total signals: *{total_signals}*\n"
        f"🟢 BUY: {buy}  🔴 SELL: {sell}  🟡 ALERT: {alert}"
    )
    return send_message(text)
