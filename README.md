# StockApp — Plataforma de Análisis Bursátil

100% gratuita. Acciones USA, índices, crypto y FOREX. Datos desde 2020.

## Stack
- **Python 3.11+** + pandas-ta, yfinance, SQLAlchemy
- **MySQL 8** via Docker
- **Streamlit** dashboard (http://localhost:8501)
- **APScheduler** para updates diarios automáticos
- **Telegram** para alertas

## Inicio rápido

```bash
# 1. Clonar e instalar
pip install -r requirements.txt

# 2. Configurar entorno
cp .env.example .env
# Editar .env con tus credenciales de Telegram si lo quieres usar

# 3. Levantar MySQL + phpMyAdmin
docker-compose up -d
# phpMyAdmin disponible en http://localhost:8080

# 4. Setup inicial (tablas + tickers por defecto + estrategias)
python setup.py

# 5. Cargar histórico desde 2020 (tarda ~20-40 min para todos los tickers)
python -m app.data.history --all

# 6. Calcular indicadores
python -c "from app.indicators.calculator import calc_all_tickers; calc_all_tickers()"

# 7. Dashboard
streamlit run app/dashboard/app.py

# 8. Scheduler diario (en otra terminal o como servicio)
python -m app.scheduler.jobs
```

## Estructura

```
StockApp/
├── app/
│   ├── db/             # SQLAlchemy models + session
│   ├── data/           # Fetchers (yfinance, Binance, Frankfurter) + history loader
│   ├── indicators/     # pandas-ta standard + custom indicators
│   ├── strategies/     # Rule engine + JSON templates
│   ├── alerts/         # Telegram + JSON/CSV writer
│   ├── reports/        # Markdown + PDF generator
│   ├── scheduler/      # APScheduler daily jobs
│   └── dashboard/      # Streamlit app
├── config/
│   ├── settings.yml    # App configuration
│   └── tickers.yml     # Default ticker list
├── reports/            # Generated reports (YYYY-MM-DD/)
├── docker-compose.yml
├── requirements.txt
├── setup.py
└── .env.example
```

## APIs gratuitas usadas

| Activo | API | Notas |
|--------|-----|-------|
| Acciones USA + Índices | yfinance | Sin key |
| Crypto | Binance REST | Sin auth para datos públicos |
| FOREX | yfinance + frankfurter.app | Sin key |

## Telegram Bot

1. Habla con @BotFather en Telegram → `/newbot`
2. Copia el token a `TELEGRAM_BOT_TOKEN` en `.env`
3. Envía un mensaje a tu bot, luego ejecuta:
   ```
   curl https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
4. Copia el `chat_id` a `TELEGRAM_CHAT_ID` en `.env`

## Indicadores disponibles

**Estándar:** SMA(20,50,200), EMA(9,20,50,200), MACD, RSI(14), Stochastic, Bollinger Bands, ATR(14), OBV, VWAP, ADX

**Personalizados:**
- `break_high_20/52`: ruptura de máximo de 20/52 velas
- `cross_ema_9_ema_20_2c`: cruce confirmado en 2+ velas
- `pullback_sma_20_0.5pct`: pullback al SMA20 con tolerancia 0.5%
- `trend_strength` / `trend_direction`: fuerza y dirección de tendencia
- `pattern_doji` / `pattern_hammer` / `pattern_shooting_star`

## Operadores de estrategias

```json
{"indicator": "rsi_14", "op": ">", "value": 70}
{"indicator": "close", "op": ">", "indicator2": "ema_50"}
{"indicator": "sma_50", "op": "cross_above", "indicator2": "sma_200"}
```

Operadores: `>`, `<`, `>=`, `<=`, `==`, `!=`, `cross_above`, `cross_below`
