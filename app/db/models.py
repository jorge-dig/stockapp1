from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    Integer, BigInteger, String, Text, Date, DateTime, Enum,
    DECIMAL, JSON, ForeignKey, UniqueConstraint, Index, SmallInteger, Float
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class Ticker(Base):
    __tablename__ = "tickers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(200))
    asset_type: Mapped[str] = mapped_column(Enum("stock", "index", "crypto", "forex"), nullable=False)
    exchange: Mapped[Optional[str]] = mapped_column(String(50))
    active: Mapped[int] = mapped_column(SmallInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    ohlcv: Mapped[list["OHLCV"]] = relationship("OHLCV", back_populates="ticker", cascade="all, delete-orphan")
    indicators: Mapped[list["Indicator"]] = relationship("Indicator", back_populates="ticker", cascade="all, delete-orphan")
    signals: Mapped[list["Signal"]] = relationship("Signal", back_populates="ticker", cascade="all, delete-orphan")
    data_events: Mapped[list["DataEvent"]] = relationship("DataEvent", back_populates="ticker", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Ticker {self.symbol} ({self.asset_type})>"


class OHLCV(Base):
    __tablename__ = "ohlcv"
    __table_args__ = (
        UniqueConstraint("ticker_id", "date", name="uq_ticker_date"),
        Index("idx_ticker_date", "ticker_id", "date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker_id: Mapped[int] = mapped_column(Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 6))
    high: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 6))
    low: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 6))
    close: Mapped[Optional[float]] = mapped_column(DECIMAL(20, 6))
    volume: Mapped[Optional[int]] = mapped_column(BigInteger)
    source: Mapped[Optional[str]] = mapped_column(String(30))

    ticker: Mapped["Ticker"] = relationship("Ticker", back_populates="ohlcv")


class Indicator(Base):
    __tablename__ = "indicators"
    __table_args__ = (
        UniqueConstraint("ticker_id", "date", "indicator_name", name="uq_ticker_date_indicator"),
        Index("idx_ticker_date_ind", "ticker_id", "date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker_id: Mapped[int] = mapped_column(Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    indicator_name: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[Optional[float]] = mapped_column(DECIMAL(30, 8))

    ticker: Mapped["Ticker"] = relationship("Ticker", back_populates="indicators")


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    rules_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    active: Mapped[int] = mapped_column(SmallInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    signals: Mapped[list["Signal"]] = relationship("Signal", back_populates="strategy", cascade="all, delete-orphan")


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        Index("idx_signals_ticker_date", "ticker_id", "date"),
        Index("idx_signals_strategy", "strategy_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker_id: Mapped[int] = mapped_column(Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False)
    strategy_id: Mapped[int] = mapped_column(Integer, ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    signal_type: Mapped[str] = mapped_column(Enum("BUY", "SELL", "ALERT"), nullable=False)
    details_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    ticker: Mapped["Ticker"] = relationship("Ticker", back_populates="signals")
    strategy: Mapped["Strategy"] = relationship("Strategy", back_populates="signals")
    alerts: Mapped[list["AlertLog"]] = relationship("AlertLog", back_populates="signal", cascade="all, delete-orphan")


class AlertLog(Base):
    __tablename__ = "alerts_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("signals.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(Enum("sent", "failed", "skipped"), default="sent")
    error_msg: Mapped[Optional[str]] = mapped_column(Text)

    signal: Mapped["Signal"] = relationship("Signal", back_populates="alerts")


class DataEvent(Base):
    """Audit log: every data load, update, refresh, or indicator-calc event per ticker."""
    __tablename__ = "data_events"
    __table_args__ = (
        Index("idx_data_events_ticker_time", "ticker_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(
        Enum("initial_load", "incremental_update", "manual_refresh", "indicator_calc"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    date_from: Mapped[Optional[date]] = mapped_column(Date)
    date_to: Mapped[Optional[date]] = mapped_column(Date)
    rows_added: Mapped[Optional[int]] = mapped_column(Integer)
    rows_updated: Mapped[Optional[int]] = mapped_column(Integer)
    total_rows_after: Mapped[Optional[int]] = mapped_column(Integer)
    source: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(
        Enum("running", "success", "failed"), default="running"
    )
    error_msg: Mapped[Optional[str]] = mapped_column(Text)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)

    ticker: Mapped["Ticker"] = relationship("Ticker", back_populates="data_events")
