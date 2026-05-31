import time
import logging
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

logger = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.com/api/v3"
FRANKFURTER_BASE = "https://api.frankfurter.app"


class DataSource(ABC):
    @abstractmethod
    def fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Returns DataFrame with columns: date, open, high, low, close, volume"""


class YFinanceFetcher(DataSource):
    """Handles stocks (US), indices (SPY, QQQ), FOREX pairs (EURUSD=X), some crypto."""

    def fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(), auto_adjust=True)
            if df.empty:
                logger.warning(f"yfinance returned empty data for {symbol}")
                return pd.DataFrame()
            df = df.reset_index()
            df["Date"] = pd.to_datetime(df["Date"]).dt.date
            df = df.rename(columns={
                "Date": "date", "Open": "open", "High": "high",
                "Low": "low", "Close": "close", "Volume": "volume",
            })
            df = df[["date", "open", "high", "low", "close", "volume"]].copy()
            df["source"] = "yfinance"
            return df.dropna(subset=["close"])
        except Exception as e:
            logger.error(f"yfinance fetch error for {symbol}: {e}")
            return pd.DataFrame()


class BinanceFetcher(DataSource):
    """Fetches crypto OHLCV from Binance public API. No auth required."""

    INTERVAL = "1d"
    MAX_LIMIT = 1000

    def fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        # Binance uses USDT pairs: BTC → BTCUSDT
        pair = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
        start_ms = int(datetime.combine(start, datetime.min.time()).timestamp() * 1000)
        end_ms = int(datetime.combine(end + timedelta(days=1), datetime.min.time()).timestamp() * 1000)

        all_rows = []
        current_start = start_ms

        while current_start < end_ms:
            try:
                resp = requests.get(
                    f"{BINANCE_BASE}/klines",
                    params={
                        "symbol": pair,
                        "interval": self.INTERVAL,
                        "startTime": current_start,
                        "endTime": end_ms,
                        "limit": self.MAX_LIMIT,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                rows = resp.json()
                if not rows:
                    break
                all_rows.extend(rows)
                # advance past last returned candle
                current_start = rows[-1][0] + 86_400_000
                if len(rows) < self.MAX_LIMIT:
                    break
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"Binance fetch error for {pair}: {e}")
                break

        if not all_rows:
            return pd.DataFrame()

        df = pd.DataFrame(all_rows, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_vol", "trades", "taker_base", "taker_quote", "ignore",
        ])
        df["date"] = pd.to_datetime(df["open_time"], unit="ms").dt.date
        df = df[["date", "open", "high", "low", "close", "volume"]].copy()
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = df["volume"].astype("Int64")
        df["source"] = "binance"
        return df[(df["date"] >= start) & (df["date"] <= end)].dropna(subset=["close"])


class FrankfurterFetcher(DataSource):
    """ECB FOREX rates via frankfurter.app. Supports major pairs vs EUR. No auth needed."""

    # Maps common symbols to (base, quote) for the API
    PAIR_MAP = {
        "EURUSD": ("EUR", "USD"), "EURGBP": ("EUR", "GBP"),
        "EURJPY": ("EUR", "JPY"), "EURCHF": ("EUR", "CHF"),
        "GBPUSD": ("GBP", "USD"), "USDJPY": ("USD", "JPY"),
        "USDCHF": ("USD", "CHF"), "AUDUSD": ("AUD", "USD"),
    }

    def fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        clean = symbol.replace("=X", "").replace("/", "").upper()
        if clean not in self.PAIR_MAP:
            logger.warning(f"FrankfurterFetcher: unsupported pair {symbol}")
            return pd.DataFrame()

        base, quote = self.PAIR_MAP[clean]
        try:
            resp = requests.get(
                f"{FRANKFURTER_BASE}/{start.isoformat()}..{end.isoformat()}",
                params={"from": base, "to": quote},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            rates = data.get("rates", {})
            if not rates:
                return pd.DataFrame()

            rows = [{"date": pd.to_datetime(d).date(), "close": v[quote]} for d, v in rates.items()]
            df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
            df["open"] = df["close"]
            df["high"] = df["close"]
            df["low"] = df["close"]
            df["volume"] = None
            df["source"] = "frankfurter"
            return df[["date", "open", "high", "low", "close", "volume", "source"]]
        except Exception as e:
            logger.error(f"Frankfurter fetch error for {symbol}: {e}")
            return pd.DataFrame()


def get_fetcher(asset_type: str, symbol: str) -> DataSource:
    """Returns the best fetcher for an asset type."""
    if asset_type == "crypto":
        return BinanceFetcher()
    if asset_type == "forex":
        clean = symbol.replace("=X", "").replace("/", "").upper()
        if clean in FrankfurterFetcher.PAIR_MAP:
            return FrankfurterFetcher()
        return YFinanceFetcher()
    return YFinanceFetcher()
