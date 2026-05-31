"""
First-run setup: creates DB tables and loads default tickers + strategy templates.
Run: python setup.py
"""
import sys
import logging
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    logger.info("=== StockApp Setup ===")

    # 1. Create tables
    logger.info("Creating database tables...")
    from app.db.session import engine
    from app.db import Base
    Base.metadata.create_all(bind=engine)
    logger.info("Tables created.")

    # 2. Load default tickers
    logger.info("Loading default tickers...")
    from app.db.session import SessionLocal
    from app.db.models import Ticker

    config_path = Path(__file__).parent / "config" / "tickers.yml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    TYPE_MAP = {"stocks": "stock", "indices": "index", "crypto": "crypto", "forex": "forex"}

    session = SessionLocal()
    added = 0
    try:
        for section, tickers in config.items():
            atype = TYPE_MAP.get(section, section)
            for t in tickers:
                symbol = t["symbol"]
                if not session.query(Ticker).filter_by(symbol=symbol).first():
                    session.add(Ticker(
                        symbol=symbol,
                        name=t.get("name"),
                        asset_type=atype,
                        exchange=t.get("exchange"),
                    ))
                    added += 1
        session.commit()
        logger.info(f"Added {added} tickers.")
    finally:
        session.close()

    # 3. Load strategy templates
    logger.info("Loading strategy templates...")
    from app.strategies.loader import load_templates
    load_templates()

    logger.info("=== Setup complete! ===")
    logger.info("Next steps:")
    logger.info("  1. Start MySQL: docker-compose up -d")
    logger.info("  2. Load history: python -m app.data.history --all")
    logger.info("  3. Start dashboard: streamlit run app/dashboard/app.py")
    logger.info("  4. Start scheduler: python -m app.scheduler.jobs")


if __name__ == "__main__":
    main()
