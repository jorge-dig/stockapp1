"""
Debug script: muestra precio, RSI y KPTOS calculado para un ticker.
Uso: python debug_kptos.py AAPL [dias]
"""
import sys
import pandas as pd
from app.db.session import SessionLocal
from app.db.models import Ticker, OHLCV, Indicator

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
DAYS   = int(sys.argv[2]) if len(sys.argv) > 2 else 90

session = SessionLocal()

ticker = session.query(Ticker).filter_by(symbol=SYMBOL).first()
if not ticker:
    print(f"Ticker '{SYMBOL}' no encontrado en BD")
    sys.exit(1)

print(f"\n=== {SYMBOL} — últimos {DAYS} días ===\n")

# OHLCV
from datetime import date, timedelta
since = date.today() - timedelta(days=DAYS + 30)  # margen para warmup

ohlcv_rows = (session.query(OHLCV)
    .filter(OHLCV.ticker_id == ticker.id, OHLCV.date >= since)
    .order_by(OHLCV.date).all())

df = pd.DataFrame([{
    "date": r.date, "close": float(r.close or 0),
    "high": float(r.high or 0), "low": float(r.low or 0),
} for r in ohlcv_rows])

# Indicadores desde BD
ind_rows = (session.query(Indicator)
    .filter(
        Indicator.ticker_id == ticker.id,
        Indicator.date >= since,
        Indicator.indicator_name.in_(["rsi_14", "swing_high_2", "swing_low_2",
                                       "is_swing_high_2", "is_swing_low_2", "kptos"])
    ).all())

session.close()

ind_df = pd.DataFrame([{"date": r.date, "name": r.indicator_name, "value": float(r.value)}
                        for r in ind_rows])

if ind_df.empty:
    print("No hay indicadores en BD para este ticker. Recalcula primero.")
    sys.exit(1)

pivot = ind_df.pivot_table(index="date", columns="name", values="value", aggfunc="first")
pivot.columns.name = None
pivot = pivot.reset_index()

df = df.merge(pivot, on="date", how="left")

# Recalcular KPTOS on-the-fly con el código actual
from app.indicators.custom import kptos
res = kptos(df)
if res:
    df["kptos_live"] = res["kptos"].values

# Mostrar solo los últimos DAYS días
cutoff = date.today() - timedelta(days=DAYS)
df = df[df["date"] >= cutoff].copy()

# Mapa de estado
state_map = {1.0: "COMPRA", -1.0: "VENTA", 0.0: "NEUTRAL"}
if "kptos" in df.columns:
    df["kptos_db"]   = df["kptos"].map(lambda v: state_map.get(v, "NEUTRAL") if pd.notna(v) else "—")
if "kptos_live" in df.columns:
    df["kptos_live_str"] = df["kptos_live"].map(lambda v: state_map.get(v, "NEUTRAL"))

cols = ["date", "close", "high", "low", "rsi_14",
        "swing_high_2", "swing_low_2"]
if "kptos_db"       in df.columns: cols.append("kptos_db")
if "kptos_live_str" in df.columns: cols.append("kptos_live_str")

df_show = df[cols].copy()
df_show["close"]        = df_show["close"].round(2)
df_show["rsi_14"]       = df_show["rsi_14"].round(1)
df_show["swing_high_2"] = df_show["swing_high_2"].round(2)
df_show["swing_low_2"]  = df_show["swing_low_2"].round(2)

pd.set_option("display.max_rows", 200)
pd.set_option("display.width", 160)
print(df_show.to_string(index=False))

# Resumen de transiciones
print("\n=== Cambios de estado KPTOS (live) ===")
if "kptos_live" in df.columns:
    changes = df[df["kptos_live"] != df["kptos_live"].shift(1)][["date","close","rsi_14","kptos_live_str"]]
    changes = changes.iloc[1:]  # quitar primera fila (no es cambio real)
    if changes.empty:
        print("Sin cambios de estado en el período — siempre NEUTRAL")
    else:
        print(changes.to_string(index=False))

print(f"\nDistribución: {df['kptos_live_str'].value_counts().to_dict() if 'kptos_live_str' in df.columns else 'N/A'}")
