"""One line in Historique when a card is lost or found again (user,
2026-10-23). It lands in `customer_changes`, like the other per-client
events, so it shows both in the shop's feed and in that client's own.

Its own module (2026-11-21): the iPhone's lane (api/wallet_lane.py) writes it
without loading server.py."""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def log(db, cust: Dict[str, Any], text: str, by: Optional[str] = None, at: Optional[datetime] = None) -> None:
    try:
        db.customer_changes.insert_one({
            "id": str(uuid.uuid4()), "tenant_id": cust.get("tenant_id"),
            "customer_id": cust.get("id"), "customer_name": cust.get("name") or "Client",
            "kind": "card_state", "at": at or datetime.now(timezone.utc),
            "text": text, "by": by,
        })
    except Exception as exc:                 # noqa: BLE001 — a log never breaks the action
        print(f"card event not logged (non-fatal): {exc}")
