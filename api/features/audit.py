"""
Audit log — append-only record of who did what, when (S2).

Status: 🟢 Core — a compliance prerequisite, not a nice-to-have.
Mounts at: /api/owner/facturation/audit  ·  /api/comptable/audit

WHY THIS EXISTS
    Three separate reasons, all real:

    1. LEGAL. Accounting data must be traceable: "who changed this VAT rate?"
       needs an answer years later. Regulators and auditors ask this.
    2. TRUST. A cabinet is handing us 45 businesses' finances. The first
       question in their security review is "can you prove what your staff and
       ours did?". Without a log the answer is no and the deal dies.
    3. PRODUCT. The cabinet dashboard's "kaun kya kar raha hai" view and the
       45-second freshness of counters are both fed by these events — the
       employee never has to "update" anything, working IS the update.

DESIGN RULES
    - APPEND-ONLY. There is no update or delete endpoint, by design.
    - NEVER blocks the business action. log() swallows its own errors: a
      logging failure must never lose an invoice.
    - No secrets in payloads. We store references (ids, field names), not
      credentials or full documents.

Safety: leaf module via features/_loader; failure here cannot take the app down.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from auth import require_role

router = APIRouter(tags=["audit"])
_db = None


def init(db):
    global _db
    _db = db
    try:
        # Fast "what happened in this dossier / this cabinet" queries.
        _db.audit_log.create_index([("tenant_id", 1), ("at", -1)])
        _db.audit_log.create_index([("actor_email", 1), ("at", -1)])
        _db.audit_log.create_index([("action", 1), ("at", -1)])
    except Exception:
        pass       # index creation is best-effort; never break boot


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ==========================================================================
# the helper every other module calls
# ==========================================================================

def log(action: str, *, tenant_id: Optional[str] = None, actor=None,
        object_kind: Optional[str] = None, object_id: Optional[str] = None,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
        detail: Optional[Dict[str, Any]] = None,
        db=None) -> None:
    """Record one event. Fire-and-forget — never raises into the caller.

    `actor` is the JWT token_data (or None for system/cron/webhook actions).
    `before`/`after` should be SMALL field-level diffs, not whole documents.
    """
    database = db or _db
    if database is None:
        return
    try:
        entry = {
            "id": str(uuid4()),
            "at": _now(),
            "action": action,
            "tenant_id": tenant_id,
            # « Accéder au compte »: the admin who really made the change,
            # on behalf of the owner whose account it is.
            "actor_email": (getattr(actor, "view_by", None) or getattr(actor, "email", None)) if actor else None,
            "actor_role": ("super_admin" if getattr(actor, "view_by", None) else getattr(actor, "role", None))
                          if actor else "system",
            **({"on_behalf_of": getattr(actor, "email", None)} if actor and getattr(actor, "view_by", None) else {}),
            "object": {"kind": object_kind, "id": object_id},
            "before": before or None,
            "after": after or None,
            "detail": detail or None,
        }
        database.audit_log.insert_one(entry)
    except Exception:
        # A failed audit write must never break the business action; the
        # alternative (raising) would mean a logging bug can stop invoicing.
        pass


def diff(before: Dict[str, Any], after: Dict[str, Any], fields: List[str]) -> Dict[str, Any]:
    """Build a compact {field: [old, new]} map for the fields that changed."""
    out: Dict[str, Any] = {}
    for f in fields:
        if (before or {}).get(f) != (after or {}).get(f):
            out[f] = [(before or {}).get(f), (after or {}).get(f)]
    return out


def _public(e: Dict[str, Any]) -> Dict[str, Any]:
    e.pop("_id", None)
    return e


# ==========================================================================
# read endpoints
# ==========================================================================

def _int(value, fallback: int) -> int:
    """Coerce a FastAPI Query default into a plain int.

    Lets these handlers be called directly from tests/scripts (where FastAPI
    isn't resolving defaults) without duplicating the endpoint logic.
    """
    return value if isinstance(value, int) else fallback


@router.get("/api/owner/facturation/audit")
def owner_audit(limit: int = Query(100, le=500),
                token_data=Depends(require_role(["business_owner", "manager"]))):
    """A business owner sees the history of their OWN company only."""
    docs = list(_db.audit_log.find({"tenant_id": token_data.tenant_id})
                .sort("at", -1).limit(_int(limit, 100)))
    return {"entries": [_public(d) for d in docs]}


@router.get("/api/comptable/audit")
def cabinet_audit(tenant_id: Optional[str] = None, limit: int = Query(150, le=500),
                  token_data=Depends(require_role(["comptable"]))):
    """Accountant view: one dossier's history, or the whole portfolio's.

    Isolation is enforced through the mandate guard — a tenant_id in the query
    string is never trusted on its own.
    """
    from features.cabinet import assert_mandate, _linked_tenant_ids  # lazy import
    if tenant_id:
        assert_mandate(token_data.email, tenant_id)
        tids = [tenant_id]
    else:
        tids = _linked_tenant_ids(token_data.email)
    if not tids:
        return {"entries": []}
    docs = list(_db.audit_log.find({"tenant_id": {"$in": tids}})
                .sort("at", -1).limit(_int(limit, 150)))
    return {"entries": [_public(d) for d in docs]}


@router.get("/api/comptable/activity-summary")
def activity_summary(days: int = Query(7, le=90),
                     token_data=Depends(require_role(["comptable"]))):
    """"Kaun kya kar raha hai" — per-actor activity over the last N days.

    This is what makes the cabinet owner's dashboard self-updating: staff never
    report their work, their actions ARE the report.
    """
    from features.cabinet import _linked_tenant_ids       # lazy import
    days = _int(days, 7)
    tids = _linked_tenant_ids(token_data.email)
    if not tids:
        return {"actors": [], "days": days}
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    docs = _db.audit_log.find({"tenant_id": {"$in": tids}, "at": {"$gte": since}})
    per: Dict[str, Dict[str, Any]] = {}
    for d in docs:
        email = d.get("actor_email") or "système"
        slot = per.setdefault(email, {"actor": email, "total": 0, "by_action": {}})
        slot["total"] += 1
        slot["by_action"][d["action"]] = slot["by_action"].get(d["action"], 0) + 1
    actors = sorted(per.values(), key=lambda a: -a["total"])
    return {"actors": actors, "days": days}
