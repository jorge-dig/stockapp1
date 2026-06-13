"""
Inserta la estrategia KPTOS BUY en la BD.
Uso: python3 add_kptos_strategy.py
"""
import json
from app.db.session import SessionLocal
from app.db.models import Strategy

rules = {
    "conditions": [
        {
            "indicator": "kptos",
            "op": "cross_above",
            "value": 0.5
        }
    ],
    "logic": "AND",
    "signal": "BUY"
}

session = SessionLocal()
try:
    existing = session.query(Strategy).filter_by(name="KPTOS BUY").first()
    if existing:
        existing.rules_json = rules
        existing.description = "Compra cuando KPTOS transiciona a COMPRA (cruza por encima de 0.5)."
        existing.active = 1
        print("Estrategia KPTOS BUY actualizada.")
    else:
        s = Strategy(
            name="KPTOS BUY",
            description="Compra cuando KPTOS transiciona a COMPRA (cruza por encima de 0.5).",
            rules_json=rules,
            active=1,
        )
        session.add(s)
        print("Estrategia KPTOS BUY creada.")
    session.commit()
    s = session.query(Strategy).filter_by(name="KPTOS BUY").first()
    print(f"ID: {s.id}  |  Rules: {json.dumps(s.rules_json)}")
finally:
    session.close()
