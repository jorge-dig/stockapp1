"""Load strategy templates from JSON files into the DB."""
import json
import logging
from pathlib import Path

from app.db.session import SessionLocal
from app.db.models import Strategy

logger = logging.getLogger(__name__)
TEMPLATES_DIR = Path(__file__).parent / "templates"


def load_templates():
    """Insert predefined strategy templates if they don't already exist."""
    session = SessionLocal()
    try:
        for path in TEMPLATES_DIR.glob("*.json"):
            data = json.loads(path.read_text())
            name = data["name"]
            existing = session.query(Strategy).filter_by(name=name).first()
            if not existing:
                strategy = Strategy(
                    name=name,
                    description=data.get("description", ""),
                    rules_json=data["rules_json"],
                    active=1,
                )
                session.add(strategy)
                logger.info(f"Loaded strategy template: {name}")
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"load_templates error: {e}")
    finally:
        session.close()
