"""
Streamlit dashboard for the Stock Analysis Platform.
Run: streamlit run app/dashboard/app.py
"""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots
from sqlalchemy import func, text

from app.db.session import SessionLocal, engine
from app.db.models import Ticker, OHLCV, Indicator, Strategy, Signal, AlertLog, DataEvent
from app.db import Base

st.set_page_config(
    page_title="StockApp Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- DB init ---
@st.cache_resource
def init_db():
    Base.metadata.create_all(bind=engine)

init_db()


# --- Helpers ---
from contextlib import contextmanager

@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@st.cache_data(ttl=300)
def get_tickers_df():
    with get_session() as session:
        rows = session.query(Ticker).order_by(Ticker.symbol).all()
        return pd.DataFrame([{
            "id": t.id, "symbol": t.symbol, "name": t.name or "",
            "asset_type": t.asset_type, "exchange": t.exchange or "",
            "active": bool(t.active),
        } for t in rows])


@st.cache_data(ttl=60)
def get_ohlcv(ticker_id: int, days: int = 365, _today: date = None) -> pd.DataFrame:
    if _today is None:
        _today = date.today()
    since = _today - timedelta(days=days)
    with get_session() as session:
        rows = (
            session.query(OHLCV)
            .filter(OHLCV.ticker_id == ticker_id, OHLCV.date >= since)
            .order_by(OHLCV.date)
            .all()
        )
        return pd.DataFrame([{
            "date": r.date, "open": float(r.open or 0), "high": float(r.high or 0),
            "low": float(r.low or 0), "close": float(r.close or 0),
            "volume": int(r.volume) if r.volume else 0,
        } for r in rows])


@st.cache_data(ttl=60)
def get_indicators_pivot(ticker_id: int, days: int = 365, _today: date = None) -> pd.DataFrame:
    if _today is None:
        _today = date.today()
    since = _today - timedelta(days=days)
    with get_session() as session:
        rows = (
            session.query(Indicator)
            .filter(Indicator.ticker_id == ticker_id, Indicator.date >= since)
            .order_by(Indicator.date)
            .all()
        )
        if not rows:
            return pd.DataFrame()
        data = [{"date": r.date, "indicator_name": r.indicator_name, "value": float(r.value) if r.value is not None else None}
                for r in rows]

    df = pd.DataFrame(data)
    pivot = df.pivot_table(index="date", columns="indicator_name", values="value", aggfunc="first")
    pivot.columns.name = None          # remove the "indicator_name" axis label
    pivot = pivot.reset_index()
    return pivot


# Indicator categories for chart display
PRICE_OVERLAYS = {"sma_20", "sma_50", "sma_200", "ema_9", "ema_20", "ema_50", "ema_200",
                  "bb_upper", "bb_mid", "bb_lower", "vwap",
                  "prev_high_20", "prev_low_20", "prev_high_52", "prev_low_52",
                  "swing_high_2", "swing_low_2", "swing_high_3", "swing_low_3"}
OSCILLATORS    = {"rsi_14", "stoch_k", "stoch_d", "adx", "adx_dmp", "adx_dmn",
                  "bb_percent", "trend_strength", "trend_direction"}
VOLUME_PANEL   = {"obv"}
# ATR, bb_bandwidth, macd_* get their own panel (already handled)
EXCLUDE_OVERLAY = {"atr_14", "bb_bandwidth", "obv", "volume",
                   "macd_line", "macd_signal", "macd_histogram", "kptos"} | OSCILLATORS


@st.cache_data(ttl=60)
def get_signals_df(days: int = 30) -> pd.DataFrame:
    since = date.today() - timedelta(days=days)
    with get_session() as session:
        rows = (
            session.query(Signal, Ticker, Strategy)
            .join(Ticker, Signal.ticker_id == Ticker.id)
            .join(Strategy, Signal.strategy_id == Strategy.id)
            .filter(Signal.date >= since)
            .order_by(Signal.date.desc())
            .all()
        )
        return pd.DataFrame([{
            "date": s.date, "symbol": t.symbol, "asset_type": t.asset_type,
            "signal": s.signal_type, "strategy": st.name,
            "close": s.details_json.get("close") if s.details_json else None,
        } for s, t, st in rows])


# --- Navigation ---
PAGES = ["🏠 Home", "📋 Tickers", "📊 Charts", "🔬 Backtest", "⚙️ Strategies", "🔔 Signals", "📄 Reports", "📜 Audit Log"]
page = st.sidebar.radio("Navigation", PAGES)

# ================================================================
# PAGE: HOME
# ================================================================
if page == "🏠 Home":
    st.title("📈 StockApp Dashboard")
    st.caption(f"Today: {date.today()}")

    col1, col2, col3, col4 = st.columns(4)

    with get_session() as s:
        active_tickers = s.query(Ticker).filter_by(active=1).count()
        total_ohlcv = s.query(func.count(OHLCV.id)).scalar() or 0
        today_signals = s.query(Signal).filter(Signal.date == date.today()).count()
        total_strategies = s.query(Strategy).filter_by(active=1).count()

    col1.metric("Active Tickers", active_tickers)
    col2.metric("OHLCV Rows", f"{total_ohlcv:,}")
    col3.metric("Signals Today", today_signals)
    col4.metric("Active Strategies", total_strategies)

    st.divider()
    st.subheader("Latest Signals (last 7 days)")
    signals_df = get_signals_df(days=7)
    if signals_df.empty:
        st.info("No signals in the last 7 days.")
    else:
        def color_signal(val):
            colors = {"BUY": "background-color: #d4edda", "SELL": "background-color: #f8d7da", "ALERT": "background-color: #fff3cd"}
            return colors.get(val, "")
        st.dataframe(
            signals_df.style.map(color_signal, subset=["signal"]),
            use_container_width=True, hide_index=True
        )

    st.divider()
    st.subheader("Quick Actions")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("▶ Run Full Pipeline Now", use_container_width=True):
            with st.spinner("Running pipeline..."):
                from app.scheduler.jobs import run_daily_pipeline
                run_daily_pipeline()
            st.success("Pipeline complete!")
            st.cache_data.clear()

    with col_b:
        if st.button("🔄 Update Data Only", use_container_width=True):
            with st.spinner("Updating data..."):
                from app.data.history import incremental_update
                incremental_update()
            st.success("Data updated!")
            st.cache_data.clear()

    with col_c:
        if st.button("📊 Recalculate Indicators", use_container_width=True):
            with st.spinner("Calculating..."):
                from app.indicators.calculator import calc_all_tickers
                calc_all_tickers(since=date.today() - timedelta(days=5))
            st.success("Indicators updated!")
            st.cache_data.clear()

# ================================================================
# PAGE: TICKERS
# ================================================================
elif page == "📋 Tickers":
    st.title("📋 Ticker Management")

    tickers_df = get_tickers_df()

    tab_list, tab_bulk, tab_add = st.tabs(["📋 Ticker List", "⚡ Bulk Actions", "➕ Add / Import"])

    # ── Tab 1: per-ticker table ──────────────────────────────────────────────
    with tab_list:
        if tickers_df.empty:
            st.info("No tickers yet. Add some in the 'Add / Import' tab.")
        else:
            h1, h2, h3, h4, h5, h6, h7 = st.columns([2, 3, 2, 2, 2, 2, 2])
            for col, label in zip([h1,h2,h3,h4,h5,h6,h7],
                                   ["Symbol","Name","Type","Status","","",""]):
                col.markdown(f"**{label}**")
            st.divider()

            for _, row in tickers_df.iterrows():
                c1, c2, c3, c4, c5, c6, c7 = st.columns([2, 3, 2, 2, 2, 2, 2])
                c1.write(f"**{row['symbol']}**")
                c2.write(row['name'])
                c3.write(row['asset_type'])
                c4.write("✅ Active" if row['active'] else "⏸ Inactive")

                with c5:
                    if row['active']:
                        if st.button("Deactivate", key=f"deact_{row['id']}", use_container_width=True):
                            with get_session() as session:
                                t = session.query(Ticker).filter_by(id=row['id']).first()
                                t.active = 0
                                session.commit()
                            st.cache_data.clear(); st.rerun()
                    else:
                        if st.button("Activate", key=f"act_{row['id']}", use_container_width=True):
                            with get_session() as session:
                                t = session.query(Ticker).filter_by(id=row['id']).first()
                                t.active = 1
                                session.commit()
                            st.cache_data.clear(); st.rerun()

                with c6:
                    if st.button("🔄 Data", key=f"upd_{row['id']}", use_container_width=True,
                                 help="Download latest price data for this ticker"):
                        with st.spinner(f"Updating {row['symbol']}…"):
                            from app.data.history import load_ticker_history
                            load_ticker_history(row['symbol'], event_type="manual_refresh")
                        st.toast(f"{row['symbol']} data updated!", icon="✅")
                        st.cache_data.clear(); st.rerun()

                with c7:
                    if st.button("📊 Indicators", key=f"ind_{row['id']}", use_container_width=True,
                                 help="Recalculate all indicators (full history)"):
                        with st.spinner(f"Calculating indicators for {row['symbol']}…"):
                            from app.indicators.calculator import calc_and_store
                            n = calc_and_store(int(row['id']))
                        st.toast(f"{row['symbol']}: {n:,} values stored", icon="📊")
                        st.cache_data.clear(); st.rerun()

    # ── Tab 2: bulk actions ──────────────────────────────────────────────────
    with tab_bulk:
        if tickers_df.empty:
            st.info("No tickers yet. Add some in the 'Add / Import' tab.")
        else:
            st.markdown("Select tickers and run data updates or indicator calculations on all of them at once.")

            # ── Filters ─────────────────────────────────────────────────────
            f_col, sa_col = st.columns([3, 1])
            type_filter = f_col.selectbox(
                "Filter by asset type",
                ["All", "stock", "index", "crypto", "forex"],
                key="bulk_type_filter",
            )

            filtered_df = (
                tickers_df if type_filter == "All"
                else tickers_df[tickers_df["asset_type"] == type_filter]
            )
            filtered_symbols = sorted(filtered_df["symbol"].tolist())

            # ── Select All toggle ────────────────────────────────────────────
            select_all_bulk = sa_col.checkbox(
                "Select all",
                key="bulk_select_all",
                help=f"Select all {len(filtered_symbols)} visible tickers",
            )

            if select_all_bulk:
                selected_symbols = filtered_symbols
                st.info(f"**{len(selected_symbols)}** tickers selected (all {type_filter}).")
            else:
                selected_symbols = st.multiselect(
                    f"Choose tickers ({len(filtered_symbols)} available)",
                    options=filtered_symbols,
                    key="bulk_multiselect",
                    placeholder="Click to pick tickers…",
                )

            if not selected_symbols:
                st.warning("Select at least one ticker to enable bulk actions.")
            else:
                st.markdown(f"**{len(selected_symbols)} ticker(s) selected:** {', '.join(selected_symbols)}")
                st.divider()

                # Build lookup: symbol → (id, asset_type)
                sym_to_row = {
                    r["symbol"]: r
                    for _, r in tickers_df.iterrows()
                }

                btn_col1, btn_col2 = st.columns(2)

                # ── Bulk: Update Data ────────────────────────────────────────
                with btn_col1:
                    st.markdown("#### 🔄 Update Price Data")
                    st.caption("Downloads the latest OHLCV data for each selected ticker.")
                    if st.button(
                        f"🔄 Update data for {len(selected_symbols)} ticker(s)",
                        key="bulk_upd_btn",
                        use_container_width=True,
                        type="primary",
                    ):
                        from app.data.history import load_ticker_history
                        progress = st.progress(0, text="Starting…")
                        results_upd = []
                        for i, sym in enumerate(selected_symbols):
                            progress.progress(
                                (i) / len(selected_symbols),
                                text=f"Updating {sym} ({i+1}/{len(selected_symbols)})…",
                            )
                            try:
                                n = load_ticker_history(sym, event_type="manual_refresh")
                                results_upd.append(f"✅ **{sym}**: {n:,} rows")
                            except Exception as e:
                                results_upd.append(f"❌ **{sym}**: {e}")
                        progress.progress(1.0, text="Done!")
                        st.cache_data.clear()
                        with st.expander("Results", expanded=True):
                            for line in results_upd:
                                st.markdown(line)

                # ── Bulk: Recalculate Indicators ─────────────────────────────
                with btn_col2:
                    st.markdown("#### 📊 Recalculate Indicators")
                    st.caption("Recomputes all technical indicators (full history) for each selected ticker.")
                    if st.button(
                        f"📊 Recalculate indicators for {len(selected_symbols)} ticker(s)",
                        key="bulk_ind_btn",
                        use_container_width=True,
                        type="primary",
                    ):
                        from app.indicators.calculator import calc_and_store
                        progress2 = st.progress(0, text="Starting…")
                        results_ind = []
                        for i, sym in enumerate(selected_symbols):
                            progress2.progress(
                                (i) / len(selected_symbols),
                                text=f"Calculating {sym} ({i+1}/{len(selected_symbols)})…",
                            )
                            try:
                                ticker_id = int(sym_to_row[sym]["id"])
                                n = calc_and_store(ticker_id)
                                results_ind.append(f"✅ **{sym}**: {n:,} indicator values")
                            except Exception as e:
                                results_ind.append(f"❌ **{sym}**: {e}")
                        progress2.progress(1.0, text="Done!")
                        st.cache_data.clear()
                        with st.expander("Results", expanded=True):
                            for line in results_ind:
                                st.markdown(line)

    # ── Tab 3: add / import ──────────────────────────────────────────────────
    with tab_add:
        st.subheader("Add Single Ticker")
        with st.form("add_ticker"):
            c1, c2, c3, c4 = st.columns(4)
            symbol = c1.text_input("Symbol", placeholder="AAPL").upper().strip()
            name = c2.text_input("Name", placeholder="Apple Inc.")
            asset_type = c3.selectbox("Asset Type", ["stock", "index", "crypto", "forex"])
            exchange = c4.text_input("Exchange", placeholder="NASDAQ")
            submitted = st.form_submit_button("Add Ticker", use_container_width=True)

            if submitted and symbol:
                with get_session() as session:
                    existing = session.query(Ticker).filter_by(symbol=symbol).first()
                    if existing:
                        st.warning(f"{symbol} already exists.")
                    else:
                        session.add(Ticker(symbol=symbol, name=name, asset_type=asset_type, exchange=exchange))
                        session.commit()
                        st.success(f"Added {symbol}!")
                        st.cache_data.clear()
                        st.rerun()

        st.divider()
        st.subheader("Bulk Import")
        bulk_text = st.text_area(
            "Paste symbols (one per line, format: SYMBOL,type)",
            height=150, placeholder="AAPL,stock\nSPY,index\nBTC,crypto\nEURUSD=X,forex"
        )
        if st.button("Import"):
            added = 0
            with get_session() as session:
                for line in bulk_text.splitlines():
                    parts = line.strip().split(",")
                    if len(parts) >= 2:
                        sym, atype = parts[0].strip().upper(), parts[1].strip().lower()
                        if not session.query(Ticker).filter_by(symbol=sym).first():
                            session.add(Ticker(symbol=sym, asset_type=atype))
                            added += 1
                session.commit()
            st.success(f"Imported {added} tickers.")
            st.cache_data.clear()
            st.rerun()

# ================================================================
# PAGE: CHARTS
# ================================================================
elif page == "📊 Charts":
    st.title("📊 Price Charts")

    tickers_df = get_tickers_df()
    if tickers_df.empty:
        st.warning("No tickers configured.")
        st.stop()

    col1, col2, col3 = st.columns([3, 2, 2])
    symbol     = col1.selectbox("Ticker", tickers_df["symbol"].tolist())
    days       = col2.selectbox("Period", [90, 180, 365, 730, 1825], index=2,
                                format_func=lambda x: {90:"3M",180:"6M",365:"1Y",730:"2Y",1825:"5Y"}.get(x,f"{x}d"))
    chart_type = col3.selectbox("Chart", ["Candlestick", "Line"])

    ticker_row = tickers_df[tickers_df["symbol"] == symbol].iloc[0]
    ticker_id  = int(ticker_row["id"])

    # ── Data / indicator actions ──────────────────────────────────────────────
    with st.expander("⚙️ Data & Indicator Actions"):
        ac1, ac2, ac3 = st.columns(3)

        if ac1.button("🔄 Update price data", key="upd_data", use_container_width=True):
            with st.spinner(f"Downloading latest data for {symbol}…"):
                from app.data.history import load_ticker_history
                load_ticker_history(symbol, event_type="manual_refresh")
            st.success("Price data updated!")
            st.cache_data.clear()
            st.rerun()

        calc_mode = ac2.selectbox(
            "Recalc mode",
            ["Full history (2020→)", "Last 30 days", "Last 90 days"],
            key="calc_mode",
            label_visibility="collapsed",
        )
        if ac3.button("📊 Recalculate Indicators", key="recalc_ind", use_container_width=True):
            from app.indicators.calculator import calc_and_store
            from datetime import timedelta
            since_map = {
                "Full history (2020→)": None,
                "Last 30 days": date.today() - timedelta(days=30),
                "Last 90 days": date.today() - timedelta(days=90),
            }
            since = since_map[calc_mode]
            label = calc_mode
            with st.spinner(f"Calculating indicators for {symbol} ({label})…"):
                n = calc_and_store(ticker_id, since=since)
            st.success(f"Done — {n:,} indicator values stored for {symbol}.")
            st.cache_data.clear()
            st.rerun()

    # ── Load data ─────────────────────────────────────────────────────────────
    df     = get_ohlcv(ticker_id, days, _today=date.today())
    # Load indicators with extra warmup days so SMA200/EMA200 are populated
    # across the full visible range (200-day indicators need 200 days to warm up)
    IND_WARMUP = 250
    ind_df = get_indicators_pivot(ticker_id, days + IND_WARMUP, _today=date.today())

    if df.empty:
        st.warning(f"No OHLCV data for {symbol}. Use 'Update price data' above.")
        st.stop()

    # Info strip
    with get_session() as session:
        ind_dates = session.query(Indicator).filter_by(ticker_id=ticker_id).count()

    if ind_dates == 0:
        st.info("ℹ️ No indicators calculated yet. Use **📊 Recalculate Indicators** above.")

    # Merge indicators (left join on date — keeps all OHLCV rows)
    if not ind_df.empty:
        df = df.merge(ind_df, on="date", how="left")

    # Compute KPTOS on-the-fly if not already in df (e.g. before next scheduler run)
    if "kptos" not in df.columns and "rsi_14" in df.columns:
        from app.indicators.custom import kptos as _kptos
        _res = _kptos(df)
        if _res:
            df["kptos"] = _res["kptos"].values

    dates = pd.to_datetime(df["date"])

    # ── Indicator controls (only show what's actually in df) ──────────────────
    avail = set(df.columns) - {"date","open","high","low","close","volume"}

    price_overlay_opts = sorted(avail & PRICE_OVERLAYS)
    osc_opts           = sorted(avail & OSCILLATORS)
    show_bb = "bb_upper" in avail and "bb_lower" in avail

    with st.expander("Indicator settings", expanded=True):
        c1, c2 = st.columns(2)
        selected_overlays = c1.multiselect(
            "Price overlays (same scale as price)",
            price_overlay_opts,
            default=[x for x in ["ema_20","ema_50"] if x in price_overlay_opts],
        )
        selected_osc = c2.multiselect(
            "Oscillator panel",
            osc_opts,
            default=[x for x in ["rsi_14"] if x in osc_opts],
        )
        col_a, col_b, col_c, col_d = st.columns(4)
        show_bb     = col_a.checkbox("Bollinger Bands", value=show_bb)
        show_volume = col_b.checkbox("Volume", value=True)
        show_macd   = col_c.checkbox("MACD", value="macd_line" in avail)
        show_atr    = col_d.checkbox("ATR", value=False)

    # ── Build subplot layout ──────────────────────────────────────────────────
    subplot_specs = []
    subplot_specs.append(0.55)          # price
    if show_volume:  subplot_specs.append(0.12)
    if selected_osc: subplot_specs.append(0.15)
    if show_macd:    subplot_specs.append(0.12)
    if show_atr:     subplot_specs.append(0.10)

    n_rows = len(subplot_specs)
    fig = make_subplots(rows=n_rows, cols=1, shared_xaxes=True,
                        row_heights=subplot_specs, vertical_spacing=0.02)

    # ── Row 1: Price ──────────────────────────────────────────────────────────
    if chart_type == "Candlestick":
        fig.add_trace(go.Candlestick(
            x=dates, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
            name=symbol, increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
            increasing_fillcolor="#26a69a", decreasing_fillcolor="#ef5350",
        ), row=1, col=1)
    else:
        fig.add_trace(go.Scatter(
            x=dates, y=df["close"], name=symbol,
            line=dict(color="#1976D2", width=1.5)
        ), row=1, col=1)

    # Price overlays (SMA, EMA, VWAP — same price scale)
    overlay_colors = ["#FF6B35","#7C4DFF","#00BCD4","#FF4081","#8BC34A","#FFC107","#E91E63","#00E5FF"]
    for i, ind in enumerate(selected_overlays):
        if ind in df.columns:
            fig.add_trace(go.Scatter(
                x=dates, y=df[ind], name=ind,
                line=dict(color=overlay_colors[i % len(overlay_colors)], width=1.2),
                opacity=0.9, connectgaps=False,
            ), row=1, col=1)

    # Bollinger Bands (price overlay with fill)
    if show_bb and "bb_upper" in df.columns and "bb_lower" in df.columns:
        fig.add_trace(go.Scatter(
            x=dates, y=df["bb_upper"], name="BB Upper",
            line=dict(color="rgba(150,150,150,0.6)", width=0.8, dash="dot"),
            showlegend=True, connectgaps=False,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=dates, y=df["bb_lower"], name="BB Lower",
            line=dict(color="rgba(150,150,150,0.6)", width=0.8, dash="dot"),
            fill="tonexty", fillcolor="rgba(150,150,150,0.08)",
            showlegend=False, connectgaps=False,
        ), row=1, col=1)
        if "bb_mid" in df.columns:
            fig.add_trace(go.Scatter(
                x=dates, y=df["bb_mid"], name="BB Mid",
                line=dict(color="rgba(150,150,150,0.4)", width=0.6, dash="dot"),
                showlegend=False, connectgaps=False,
            ), row=1, col=1)

    fig.update_yaxes(title_text="Price", row=1, col=1)

    # ── Remaining rows ────────────────────────────────────────────────────────
    current_row = 2

    if show_volume:
        vol_colors = ["#26a69a" if c >= o else "#ef5350"
                      for c, o in zip(df["close"], df["open"])]
        fig.add_trace(go.Bar(
            x=dates, y=df["volume"], name="Volume",
            marker_color=vol_colors, showlegend=False,
        ), row=current_row, col=1)
        fig.update_yaxes(title_text="Vol", row=current_row, col=1, tickformat=".2s")
        current_row += 1

    if selected_osc:
        osc_colors = {"rsi_14":"#9C27B0","stoch_k":"#2196F3","stoch_d":"#FF5722",
                      "adx":"#FF9800","adx_dmp":"#4CAF50","adx_dmn":"#f44336",
                      "bb_percent":"#00BCD4","trend_strength":"#E91E63","trend_direction":"#8BC34A"}
        for ind in selected_osc:
            if ind in df.columns:
                fig.add_trace(go.Scatter(
                    x=dates, y=df[ind], name=ind,
                    line=dict(color=osc_colors.get(ind,"#aaa"), width=1.2),
                    connectgaps=False,
                ), row=current_row, col=1)
        # Reference lines
        if "rsi_14" in selected_osc:
            fig.add_hline(y=70, line_dash="dot", line_color="rgba(255,80,80,0.5)", row=current_row, col=1)
            fig.add_hline(y=30, line_dash="dot", line_color="rgba(80,200,80,0.5)",  row=current_row, col=1)
            fig.add_hline(y=50, line_dash="dot", line_color="rgba(200,200,200,0.2)", row=current_row, col=1)
        if any(x in selected_osc for x in ["stoch_k","stoch_d"]):
            fig.add_hline(y=80, line_dash="dot", line_color="rgba(255,80,80,0.5)", row=current_row, col=1)
            fig.add_hline(y=20, line_dash="dot", line_color="rgba(80,200,80,0.5)",  row=current_row, col=1)
        fig.update_yaxes(title_text=" / ".join(selected_osc[:2]), row=current_row, col=1)
        current_row += 1

    if show_macd and "macd_line" in df.columns:
        fig.add_trace(go.Scatter(
            x=dates, y=df["macd_line"], name="MACD",
            line=dict(color="#2196F3", width=1.2), connectgaps=False,
        ), row=current_row, col=1)
        if "macd_signal" in df.columns:
            fig.add_trace(go.Scatter(
                x=dates, y=df["macd_signal"], name="Signal",
                line=dict(color="#FF5722", width=1.2), connectgaps=False,
            ), row=current_row, col=1)
        if "macd_histogram" in df.columns:
            hist = df["macd_histogram"].fillna(0)
            hist_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in hist]
            fig.add_trace(go.Bar(
                x=dates, y=hist, name="MACD Hist",
                marker_color=hist_colors, showlegend=False,
            ), row=current_row, col=1)
        fig.add_hline(y=0, line_dash="dot", line_color="rgba(200,200,200,0.3)", row=current_row, col=1)
        fig.update_yaxes(title_text="MACD", row=current_row, col=1)
        current_row += 1

    if show_atr and "atr_14" in df.columns:
        fig.add_trace(go.Scatter(
            x=dates, y=df["atr_14"], name="ATR(14)",
            line=dict(color="#FF9800", width=1), fill="tozeroy",
            fillcolor="rgba(255,152,0,0.1)", connectgaps=False,
        ), row=current_row, col=1)
        fig.update_yaxes(title_text="ATR", row=current_row, col=1)

    # ── Layout ────────────────────────────────────────────────────────────────
    fig.update_layout(
        title=dict(text=f"<b>{symbol}</b>", font=dict(size=16)),
        xaxis_rangeslider_visible=False,
        height=max(600, 200 * n_rows),
        template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1, font=dict(size=11)),
        margin=dict(l=50, r=20, t=50, b=20),
        hovermode="x unified",
    )
    # Remove date gaps (weekends/holidays)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat","mon"])])

    st.plotly_chart(fig, use_container_width=True)

    # ── Stats bar ─────────────────────────────────────────────────────────────
    with st.expander("Price Statistics"):
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last
        chg  = (last["close"] - prev["close"]) / prev["close"] * 100 if prev["close"] else 0
        c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
        c1.metric("Last Close",   f"{last['close']:.2f}",  f"{chg:+.2f}%")
        c2.metric("Period High",  f"{df['high'].max():.2f}")
        c3.metric("Period Low",   f"{df['low'].min():.2f}")
        c4.metric("Avg Volume",   f"{df['volume'].mean():,.0f}")
        if "rsi_14" in df.columns and df["rsi_14"].notna().any():
            rsi_val = df["rsi_14"].dropna().iloc[-1]
            rsi_tag = "⬆ Overbought" if rsi_val > 70 else ("⬇ Oversold" if rsi_val < 30 else "Neutral")
            c5.metric("RSI(14)", f"{rsi_val:.1f}", rsi_tag)
        if "adx" in df.columns and df["adx"].notna().any():
            adx_val = df["adx"].dropna().iloc[-1]
            c6.metric("ADX", f"{adx_val:.1f}", "Strong" if adx_val > 25 else "Weak")
        if "kptos" in df.columns and df["kptos"].notna().any():
            kptos_val = df["kptos"].dropna().iloc[-1]
            kptos_map = {1.0: ("COMPRA", "🟢"), -1.0: ("VENTA", "🔴"), 0.0: ("NEUTRAL", "⚪")}
            kptos_label, kptos_icon = kptos_map.get(kptos_val, ("NEUTRAL", "⚪"))
            c7.metric("KPTOS", f"{kptos_icon} {kptos_label}")

# ================================================================
# PAGE: BACKTEST
# ================================================================
elif page == "🔬 Backtest":
    st.title("🔬 Strategy Backtest")
    st.caption("5-year window · multiple timeframes · long-only simulation")

    from app.backtest.engine import run_backtest, YEARS

    tickers_df  = get_tickers_df()
    from app.db.models import Strategy as StrategyModel
    with get_session() as session:
        strategies_db = session.query(StrategyModel).filter_by(active=1).order_by(StrategyModel.name).all()
        strat_options  = {s.name: s for s in strategies_db}

    if tickers_df.empty:
        st.warning("No tickers configured."); st.stop()
    if not strat_options:
        st.warning("No active strategies. Go to ⚙️ Strategies to add some."); st.stop()

    # ── Controls ─────────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns([2, 2, 2])
    sel_symbol   = col1.selectbox("Ticker",   tickers_df["symbol"].tolist())
    sel_strategy = col2.selectbox("Strategy", list(strat_options.keys()))
    sel_tfs      = col3.multiselect(
        "Timeframes",
        ["1D", "1W", "1M"],
        default=["1D", "1W"],
        help="1D = daily · 1W = weekly · 1M = monthly",
    )

    c_cap, c_years, c_sl, c_tp, c_days = st.columns([2, 1, 2, 2, 2])
    initial_capital = c_cap.number_input("Initial capital ($)", value=10_000, min_value=100, step=1000)
    years_back      = c_years.number_input("Years back", value=5, min_value=1, max_value=10)
    stop_loss_pct   = c_sl.number_input("Stop-loss %", value=8.0, min_value=0.0, max_value=50.0, step=0.5,
                                         help="0 = desactivado. Sale si el precio cae X% desde la entrada.")
    take_profit_pct = c_tp.number_input("Take-profit %", value=0.0, min_value=0.0, max_value=200.0, step=1.0,
                                         help="0 = desactivado. Sale si el precio sube X% desde la entrada.")
    exit_after_days = c_days.number_input("Salir tras N días", value=0, min_value=0, max_value=500, step=5,
                                           help="0 = desactivado. Cierra la posición automáticamente tras N días.")

    sl_val  = float(stop_loss_pct)   if stop_loss_pct   > 0 else None
    tp_val  = float(take_profit_pct) if take_profit_pct > 0 else None
    days_val = int(exit_after_days)  if exit_after_days > 0 else None

    c_pstype, c_psval = st.columns([2, 2])
    pos_size_type = c_pstype.selectbox(
        "Tamaño de posición",
        options=["pct", "fixed"],
        format_func=lambda x: "% del capital" if x == "pct" else "$ fijo por operación",
        help="'% del capital': invierte un porcentaje del capital disponible. '$ fijo': invierte una cantidad fija de dólares.",
    )
    if pos_size_type == "pct":
        pos_size_value = c_psval.number_input(
            "% a invertir", value=100.0, min_value=1.0, max_value=100.0, step=5.0,
            help="100% = todo el capital en cada operación. Valores menores dejan parte en cash.",
        )
    else:
        pos_size_value = c_psval.number_input(
            "$ por operación", value=float(initial_capital), min_value=1.0, max_value=float(initial_capital) * 100,
            step=500.0, help="Cantidad fija en dólares invertida en cada operación.",
        )

    run_btn = st.button("▶ Run Backtest", type="primary", use_container_width=False)
    if not run_btn:
        st.info("Select a ticker, strategy and timeframes, then press **▶ Run Backtest**.")
        st.stop()

    # ── Run ──────────────────────────────────────────────────────────────────
    if not sel_tfs:
        st.error("Select at least one timeframe."); st.stop()

    ticker_row = tickers_df[tickers_df["symbol"] == sel_symbol].iloc[0]
    ticker_id  = int(ticker_row["id"])
    strategy   = strat_options[sel_strategy]
    rules      = strategy.rules_json
    if isinstance(rules, str):
        import json as _json
        rules = _json.loads(rules)

    results: dict = {}
    with st.spinner(f"Running backtest for {sel_symbol} / {sel_strategy}…"):
        for tf in sel_tfs:
            try:
                results[tf] = run_backtest(
                    ticker_id=ticker_id,
                    symbol=sel_symbol,
                    strategy_name=sel_strategy,
                    rules=rules,
                    tf=tf,
                    initial_capital=float(initial_capital),
                    years=int(years_back),
                    stop_loss_pct=sl_val,
                    take_profit_pct=tp_val,
                    exit_after_days=days_val,
                    position_size_type=pos_size_type,
                    position_size_value=float(pos_size_value),
                )
            except Exception as _bt_err:
                st.error(f"Backtest error ({tf}): {_bt_err}")
                import traceback as _tb
                st.code(_tb.format_exc())
                st.stop()

    # ── Summary metrics table ─────────────────────────────────────────────────
    st.subheader("Performance Summary")
    summary_rows = []
    for tf, res in results.items():
        summary_rows.append({
            "Timeframe":      tf,
            "Trades":         res.total_trades,
            "Win Rate %":     f"{res.win_rate:.1f}",
            "Total Return %": f"{res.total_return_pct:.2f}",
            "Buy&Hold %":     f"{res.buy_and_hold_pct:.2f}",
            "CAGR %":         f"{res.cagr:.2f}",
            "Sharpe":         f"{res.sharpe_ratio:.2f}",
            "Max DD %":       f"{res.max_drawdown_pct:.2f}",
            "Avg Trade %":    f"{res.avg_trade_pct:.2f}",
            "Best Trade %":   f"{res.best_trade_pct:.2f}",
            "Worst Trade %":  f"{res.worst_trade_pct:.2f}",
        })
    st.dataframe(pd.DataFrame(summary_rows).set_index("Timeframe"), use_container_width=True)

    # ── Per-timeframe charts ──────────────────────────────────────────────────
    for tf, res in results.items():
        st.divider()
        st.subheader(f"Timeframe: {tf}")

        if res.df.empty:
            st.warning(f"Not enough data for {tf} backtest."); continue

        tab_chart, tab_equity, tab_trades = st.tabs(["Price + Signals", "Equity Curve", "Trade Log"])

        with tab_chart:
            from plotly.subplots import make_subplots
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                row_heights=[0.7, 0.3], vertical_spacing=0.04)

            dates_plot = pd.to_datetime(res.df["date"])

            # Candlestick
            fig.add_trace(go.Candlestick(
                x=dates_plot,
                open=res.df["open"], high=res.df["high"],
                low=res.df["low"],   close=res.df["close"],
                name=sel_symbol,
                increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
                showlegend=False,
            ), row=1, col=1)

            # Key MAs (if available)
            for ma, color in [("ema_20","#FF6B35"),("ema_50","#7C4DFF"),("sma_200","#FFC107")]:
                if ma in res.df.columns and res.df[ma].notna().any():
                    fig.add_trace(go.Scatter(
                        x=dates_plot, y=res.df[ma], name=ma,
                        line=dict(color=color, width=1), connectgaps=False,
                    ), row=1, col=1)

            # BUY markers — green upward triangle with white border, label above marker
            if res.buy_signals:
                buy_dates  = pd.to_datetime(res.buy_signals)
                buy_df     = res.df[pd.to_datetime(res.df["date"]).isin(buy_dates)]
                fig.add_trace(go.Scatter(
                    x=pd.to_datetime(buy_df["date"]),
                    y=buy_df["low"] * 0.97,
                    mode="markers+text",
                    marker=dict(
                        symbol="triangle-up",
                        size=16,
                        color="#00e676",
                        line=dict(color="white", width=1.5),
                    ),
                    text=["B"] * len(buy_df),
                    textposition="bottom center",
                    textfont=dict(color="#00e676", size=9),
                    name="BUY",
                ), row=1, col=1)

            # SELL markers — red downward triangle with white border, label below marker
            if res.sell_signals:
                sell_dates = pd.to_datetime(res.sell_signals)
                sell_df    = res.df[pd.to_datetime(res.df["date"]).isin(sell_dates)]
                fig.add_trace(go.Scatter(
                    x=pd.to_datetime(sell_df["date"]),
                    y=sell_df["high"] * 1.03,
                    mode="markers+text",
                    marker=dict(
                        symbol="triangle-down",
                        size=16,
                        color="#ff1744",
                        line=dict(color="white", width=1.5),
                    ),
                    text=["S"] * len(sell_df),
                    textposition="top center",
                    textfont=dict(color="#ff1744", size=9),
                    name="SELL",
                ), row=1, col=1)

            # Volume
            vol_colors = ["#26a69a" if c >= o else "#ef5350"
                          for c, o in zip(res.df["close"], res.df["open"])]
            fig.add_trace(go.Bar(
                x=dates_plot, y=res.df["volume"],
                marker_color=vol_colors, showlegend=False,
            ), row=2, col=1)

            fig.update_layout(
                height=550, template="plotly_dark",
                xaxis_rangeslider_visible=False,
                margin=dict(l=50, r=10, t=30, b=20),
                hovermode="x unified",
                legend=dict(orientation="h", y=1.02, x=1, xanchor="right"),
            )
            if tf == "1D":
                fig.update_xaxes(rangebreaks=[dict(bounds=["sat","mon"])])
            st.plotly_chart(fig, use_container_width=True)

        with tab_equity:
            if not res.equity_curve.empty:
                # Equity curve vs buy-and-hold
                bh_series = (res.df["close"] / res.df["close"].iloc[0] * initial_capital)
                bh_series.index = pd.to_datetime(res.df["date"])

                fig_eq = go.Figure()
                fig_eq.add_trace(go.Scatter(
                    x=res.equity_curve.index, y=res.equity_curve,
                    name="Strategy", line=dict(color="#26a69a", width=2), fill="tozeroy",
                    fillcolor="rgba(38,166,154,0.08)",
                ))
                fig_eq.add_trace(go.Scatter(
                    x=bh_series.index, y=bh_series,
                    name="Buy & Hold", line=dict(color="#FFC107", width=1.5, dash="dash"),
                ))
                fig_eq.add_hline(y=initial_capital, line_dash="dot",
                                 line_color="rgba(255,255,255,0.2)")
                fig_eq.update_layout(
                    height=380, template="plotly_dark",
                    yaxis_title="Portfolio value ($)",
                    margin=dict(l=50, r=10, t=30, b=20),
                    hovermode="x unified",
                    legend=dict(orientation="h", y=1.02, x=1, xanchor="right"),
                )
                st.plotly_chart(fig_eq, use_container_width=True)

                # Drawdown chart
                roll_max  = res.equity_curve.cummax()
                drawdown  = (res.equity_curve - roll_max) / roll_max * 100
                fig_dd = go.Figure(go.Scatter(
                    x=drawdown.index, y=drawdown,
                    fill="tozeroy", fillcolor="rgba(239,83,80,0.2)",
                    line=dict(color="#ef5350", width=1),
                    name="Drawdown %",
                ))
                fig_dd.update_layout(
                    height=200, template="plotly_dark",
                    yaxis_title="Drawdown %",
                    margin=dict(l=50, r=10, t=10, b=20),
                )
                st.plotly_chart(fig_dd, use_container_width=True)
            else:
                st.info("No equity data — no trades were generated.")

        with tab_trades:
            if res.closed_trades:
                trade_rows = [{
                    "Entry Date":   t.entry_date,
                    "Exit Date":    t.exit_date,
                    "Entry Price":  f"{t.entry_price:.4f}",
                    "Exit Price":   f"{t.exit_price:.4f}",
                    "P&L %":        round(t.pnl_pct, 2),
                    "P&L $":        round(t.pnl_abs, 2),
                } for t in res.closed_trades]
                trade_df = pd.DataFrame(trade_rows)

                def color_pnl(val):
                    if isinstance(val, (int, float)):
                        return "color: #26a69a" if val > 0 else "color: #ef5350"
                    return ""

                st.dataframe(
                    trade_df.style.map(color_pnl, subset=["P&L %", "P&L $"]),
                    use_container_width=True, hide_index=True,
                )

                # Distribution of trade returns
                pnls = [t.pnl_pct for t in res.closed_trades]
                fig_hist = go.Figure(go.Histogram(
                    x=pnls, nbinsx=20,
                    marker_color=["#26a69a" if p >= 0 else "#ef5350" for p in pnls],
                    name="Trade P&L %",
                ))
                fig_hist.add_vline(x=0, line_dash="dot", line_color="white")
                fig_hist.update_layout(
                    height=250, template="plotly_dark",
                    xaxis_title="Trade P&L %", yaxis_title="Count",
                    margin=dict(l=40, r=10, t=20, b=40),
                )
                st.plotly_chart(fig_hist, use_container_width=True)
            else:
                st.info("No completed trades for this timeframe.")

# ================================================================
# PAGE: STRATEGIES
# ================================================================
elif page == "⚙️ Strategies":
    st.title("⚙️ Strategy Manager")

    with get_session() as session:
        strategies = session.query(Strategy).order_by(Strategy.name).all()
        strat_list = [{"id": s.id, "name": s.name, "description": s.description or "", "rules": s.rules_json, "active": bool(s.active)} for s in strategies]

    tab1, tab2 = st.tabs(["Existing Strategies", "Create New"])

    with tab1:
        if not strat_list:
            if st.button("Load Default Templates"):
                from app.strategies.loader import load_templates
                load_templates()
                st.rerun()
        for strat in strat_list:
            with st.expander(f"{'✅' if strat['active'] else '⏸'} {strat['name']}"):
                st.caption(strat["description"])
                st.json(strat["rules"])
                c1, c2, c3 = st.columns(3)
                with c1:
                    if strat["active"]:
                        if st.button("Deactivate", key=f"ds_{strat['id']}"):
                            with get_session() as session:
                                s = session.query(Strategy).filter_by(id=strat["id"]).first()
                                s.active = 0
                                session.commit()
                            st.rerun()
                    else:
                        if st.button("Activate", key=f"as_{strat['id']}"):
                            with get_session() as session:
                                s = session.query(Strategy).filter_by(id=strat["id"]).first()
                                s.active = 1
                                session.commit()
                            st.rerun()
                with c2:
                    if st.button("Delete", key=f"del_{strat['id']}"):
                        with get_session() as session:
                            s = session.query(Strategy).filter_by(id=strat["id"]).first()
                            session.delete(s)
                            session.commit()
                        st.rerun()

    with tab2:
        st.subheader("Create Custom Strategy")
        with st.form("new_strategy"):
            name = st.text_input("Strategy Name")
            description = st.text_area("Description", height=80)
            signal_type = st.selectbox("Signal Type", ["BUY", "SELL", "ALERT"])
            logic = st.selectbox("Condition Logic", ["AND", "OR"])

            st.markdown("**Conditions** (JSON array):")
            example = json.dumps([
                {"indicator": "rsi_14", "op": "<", "value": 30},
                {"indicator": "close", "op": ">", "indicator2": "ema_50"}
            ], indent=2)
            conditions_raw = st.text_area("Conditions JSON", value=example, height=200)

            submitted = st.form_submit_button("Create Strategy")
            if submitted and name:
                try:
                    conditions = json.loads(conditions_raw)
                    rules = {"conditions": conditions, "logic": logic, "signal": signal_type}
                    with get_session() as session:
                        session.add(Strategy(name=name, description=description, rules_json=rules))
                        session.commit()
                    st.success(f"Strategy '{name}' created!")
                    st.rerun()
                except json.JSONDecodeError as e:
                    st.error(f"Invalid JSON: {e}")

        st.divider()
        st.subheader("Available Indicators")
        st.markdown("""
**Standard:** `sma_20`, `sma_50`, `sma_200`, `ema_9`, `ema_20`, `ema_50`, `ema_200`,
`macd_line`, `macd_signal`, `macd_histogram`, `rsi_14`, `stoch_k`, `stoch_d`,
`bb_upper`, `bb_mid`, `bb_lower`, `bb_bandwidth`, `bb_percent`, `atr_14`, `obv`, `vwap`, `adx`

**Custom:** `break_high_20`, `break_low_20`, `break_high_52`, `break_low_52`,
`cross_ema_9_ema_20_2c`, `cross_ema_20_ema_50_2c`, `cross_ema_50_ema_200_2c`,
`pullback_sma_20_0.5pct`, `pullback_ema_50_0.5pct`,
`trend_strength`, `trend_direction`, `pattern_doji`, `pattern_hammer`

**OHLCV:** `open`, `high`, `low`, `close`, `volume`

**Operators:** `>`, `<`, `>=`, `<=`, `==`, `!=`, `cross_above`, `cross_below`
        """)

# ================================================================
# PAGE: SIGNALS
# ================================================================
elif page == "🔔 Signals":
    st.title("🔔 Signals")

    col1, col2, col3 = st.columns(3)
    days_back = col1.slider("Days back", 1, 90, 30)
    sig_filter = col2.multiselect("Signal type", ["BUY", "SELL", "ALERT"], default=["BUY", "SELL", "ALERT"])
    asset_filter = col3.multiselect("Asset type", ["stock", "index", "crypto", "forex"])

    df = get_signals_df(days=days_back)
    if not df.empty:
        if sig_filter:
            df = df[df["signal"].isin(sig_filter)]
        if asset_filter:
            df = df[df["asset_type"].isin(asset_filter)]

    if df.empty:
        st.info("No signals match the current filters.")
    else:
        # Summary counts
        c1, c2, c3 = st.columns(3)
        c1.metric("BUY signals", len(df[df["signal"] == "BUY"]))
        c2.metric("SELL signals", len(df[df["signal"] == "SELL"]))
        c3.metric("ALERT signals", len(df[df["signal"] == "ALERT"]))

        def highlight(row):
            color = {"BUY": "#d4edda", "SELL": "#f8d7da", "ALERT": "#fff3cd"}.get(row["signal"], "")
            return [f"background-color: {color}"] * len(row)

        st.dataframe(df.style.apply(highlight, axis=1), use_container_width=True, hide_index=True)

        # Signal frequency chart
        st.subheader("Signal frequency by day")
        freq = df.groupby(["date", "signal"]).size().reset_index(name="count")
        fig = go.Figure()
        for sig_type, color in [("BUY", "#26a69a"), ("SELL", "#ef5350"), ("ALERT", "#FFC107")]:
            sub = freq[freq["signal"] == sig_type]
            if not sub.empty:
                fig.add_trace(go.Bar(x=sub["date"], y=sub["count"], name=sig_type, marker_color=color))
        fig.update_layout(barmode="stack", template="plotly_dark", height=300, margin=dict(t=30, b=0))
        st.plotly_chart(fig, use_container_width=True)

# ================================================================
# PAGE: REPORTS
# ================================================================
elif page == "📄 Reports":
    st.title("📄 Reports")

    REPORTS_DIR = Path(__file__).parent.parent.parent / "reports"

    col1, col2 = st.columns([2, 1])
    report_date = col1.date_input("Report date", value=date.today())

    with col2:
        st.write("")
        st.write("")
        if st.button("Generate Report", use_container_width=True):
            with st.spinner("Generating..."):
                from app.reports.generator import generate_daily_report
                out = generate_daily_report(report_date)
            st.success(f"Report saved to {out}")

    # List existing reports
    report_dirs = sorted(REPORTS_DIR.glob("????-??-??"), reverse=True)
    if not report_dirs:
        st.info("No reports generated yet.")
    else:
        selected_dir = st.selectbox("Browse reports", [d.name for d in report_dirs])
        out_dir = REPORTS_DIR / selected_dir

        md_file = out_dir / "daily_report.md"
        pdf_file = out_dir / "daily_report.pdf"
        signals_file = out_dir / "signals.json"

        if md_file.exists():
            with st.expander("Markdown Report", expanded=True):
                st.markdown(md_file.read_text(encoding="utf-8"))

        col_a, col_b, col_c = st.columns(3)
        if pdf_file.exists():
            with open(pdf_file, "rb") as f:
                col_a.download_button("Download PDF", f, file_name=f"report_{selected_dir}.pdf", mime="application/pdf")
        if md_file.exists():
            col_b.download_button("Download Markdown", md_file.read_text(), file_name=f"report_{selected_dir}.md", mime="text/markdown")
        if signals_file.exists():
            col_c.download_button("Download Signals JSON", signals_file.read_text(), file_name=f"signals_{selected_dir}.json", mime="application/json")

# ================================================================
# PAGE: AUDIT LOG
# ================================================================
elif page == "📜 Audit Log":
    st.title("📜 Audit Log")
    st.caption("Every data load, update, refresh, and indicator calculation event per ticker.")

    # ── Ticker selector ─────────────────────────────────────────────────────
    with get_session() as _s:
        all_tickers = _s.query(Ticker).order_by(Ticker.symbol).all()
        ticker_opts = {t.symbol: t.id for t in all_tickers}

    if not ticker_opts:
        st.info("No tickers in the database yet.")
        st.stop()

    col_sel, col_type, col_lim = st.columns([2, 2, 1])
    selected_sym = col_sel.selectbox("Ticker", ["— All —"] + list(ticker_opts.keys()))
    event_type_filter = col_type.selectbox(
        "Event type",
        ["All", "initial_load", "incremental_update", "manual_refresh", "indicator_calc"],
    )
    row_limit = col_lim.number_input("Max rows", min_value=10, max_value=1000, value=200, step=50)

    # ── Query ───────────────────────────────────────────────────────────────
    with get_session() as _s:
        q = _s.query(DataEvent, Ticker.symbol).join(Ticker, DataEvent.ticker_id == Ticker.id)
        if selected_sym != "— All —":
            q = q.filter(DataEvent.ticker_id == ticker_opts[selected_sym])
        if event_type_filter != "All":
            q = q.filter(DataEvent.event_type == event_type_filter)
        q = q.order_by(DataEvent.started_at.desc()).limit(int(row_limit))
        rows = q.all()

    if not rows:
        st.info("No audit events recorded yet. Run a data load or indicator calculation to see entries here.")
        st.stop()

    # ── Build display DataFrame ─────────────────────────────────────────────
    records = []
    for ev, sym in rows:
        dur = f"{ev.duration_seconds:.1f}s" if ev.duration_seconds is not None else "—"
        date_range = "—"
        if ev.date_from and ev.date_to:
            date_range = f"{ev.date_from} → {ev.date_to}"
        elif ev.date_from:
            date_range = str(ev.date_from)
        records.append({
            "Ticker": sym,
            "Event": ev.event_type,
            "Status": ev.status,
            "Started": ev.started_at.strftime("%Y-%m-%d %H:%M:%S") if ev.started_at else "—",
            "Duration": dur,
            "Date Range": date_range,
            "Rows Added": ev.rows_added if ev.rows_added is not None else "—",
            "Total After": ev.total_rows_after if ev.total_rows_after is not None else "—",
            "Source": ev.source or "—",
            "Error": ev.error_msg[:80] if ev.error_msg else "",
        })

    df_log = pd.DataFrame(records)

    # ── Summary stats ───────────────────────────────────────────────────────
    total_events = len(df_log)
    success_count = (df_log["Status"] == "success").sum()
    failed_count = (df_log["Status"] == "failed").sum()
    running_count = (df_log["Status"] == "running").sum()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Events", total_events)
    m2.metric("✅ Success", success_count)
    m3.metric("❌ Failed", failed_count)
    m4.metric("⏳ Running", running_count)

    st.divider()

    # ── Colour-code Status ───────────────────────────────────────────────────
    STATUS_COLORS = {
        "success": "background-color: #d4edda; color: #155724",
        "failed":  "background-color: #f8d7da; color: #721c24",
        "running": "background-color: #fff3cd; color: #856404",
    }

    def _style_status(val):
        return STATUS_COLORS.get(val, "")

    EVENT_ICONS = {
        "initial_load":        "📥 initial_load",
        "incremental_update":  "🔄 incremental_update",
        "manual_refresh":      "🔁 manual_refresh",
        "indicator_calc":      "📊 indicator_calc",
    }
    df_log["Event"] = df_log["Event"].map(lambda x: EVENT_ICONS.get(x, x))

    styled = df_log.style.map(_style_status, subset=["Status"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # ── Per-ticker timeline (if one ticker selected) ─────────────────────────
    if selected_sym != "— All —" and len(df_log) > 1:
        st.divider()
        st.subheader(f"📈 Event timeline — {selected_sym}")

        import plotly.express as px

        df_time = df_log.copy()
        df_time["started_dt"] = pd.to_datetime(df_time["Started"])
        df_time["rows_n"] = pd.to_numeric(df_time["Rows Added"], errors="coerce").fillna(0)

        fig_tl = px.bar(
            df_time.sort_values("started_dt"),
            x="started_dt", y="rows_n",
            color="Status",
            color_discrete_map={"success": "#28a745", "failed": "#dc3545", "running": "#ffc107"},
            hover_data=["Event", "Duration", "Date Range", "Total After"],
            labels={"started_dt": "Event Date/Time", "rows_n": "Rows Added"},
            title=f"Rows added per event — {selected_sym}",
        )
        fig_tl.update_layout(height=320, showlegend=True)
        st.plotly_chart(fig_tl, use_container_width=True)

    # ── Download ─────────────────────────────────────────────────────────────
    st.download_button(
        "⬇️ Export as CSV",
        data=df_log.to_csv(index=False),
        file_name=f"audit_log_{selected_sym.replace('— All —','all')}_{date.today()}.csv",
        mime="text/csv",
    )
