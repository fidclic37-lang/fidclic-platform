"""
Cabinet multi-dossier — the accountant (expert-comptable) control tower.

Status: 🟡 New (Step 7 of the Facturation build).
Mounts at: /api/owner/facturation/cabinet/*  (owner links their accountant)
           /api/comptable/*                   (accountant sees all their clients)

Why this exists:
  A French accountant with clients spread across many PAs must log into each PA
  separately (see the "Madame Rousseau" problem). Only ~10 of ~150 PAs offer a
  real cabinet view. FidClic offers one: an accountant logs in ONCE and sees the
  compliance health (Bouclier Fiscal) of ALL their linked clients, red-first,
  with per-client drill-down and a single export. This turns the accountant into
  a distribution channel — they bring their whole client book onto FidClic.

Model:
  - New role: "comptable".
  - Collection `cabinet_links`: {comptable_email, tenant_id, status} — the owner
    (client) grants their accountant access by email (the "mandat" in practice).
  - The accountant's endpoints aggregate over the tenants linked to their email.

Safety: leaf module via features/_loader; a load failure can't take the app down.
Legal: the Bouclier is an informational indicator, not tax advice / not an ECF.
"""
from __future__ import annotations

import io
import csv
from services import safe_csv
import secrets
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from auth import require_role, hash_password

router = APIRouter(tags=["cabinet"])
_db = None


def init(db):
    global _db
    _db = db
    try:
        _db.cabinet_links.create_index([("comptable_email", 1), ("status", 1)])
        _db.cabinet_links.create_index([("tenant_id", 1), ("status", 1)])
    except Exception:
        pass       # best-effort; never break boot


def _audit(*args, **kwargs):
    """Thin wrapper — an audit failure must never break a cabinet action."""
    try:
        from features import audit
        audit.log(*args, **kwargs)
    except Exception:
        pass


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc).isoformat()


def _norm(email: str) -> str:
    return (email or "").strip().lower()


def _tenant(tid):
    return _db.tenants.find_one({"id": tid})


def _linked_tenant_ids(comptable_email: str) -> List[str]:
    """Which dossiers this accountant may see.

    Two eras coexist on purpose:
      - NEW: the person has a cabinet membership (S5). Scope then comes from
        the team model — an admin sees the whole portfolio, everyone else only
        their assigned dossiers.
      - LEGACY: accounts created before the team model, linked directly by
        email. They keep working exactly as before.

    Doing it in this order means the migration needs no data rewrite and no
    downtime: the moment a membership exists, the richer rules take over.
    """
    try:
        from features.cabinet_os import visible_tenant_ids
        return visible_tenant_ids(_norm(comptable_email))
    except Exception:
        pass       # no membership (legacy account, or module unavailable)
    links = _db.cabinet_links.find({"comptable_email": _norm(comptable_email), "status": "active"})
    return [l["tenant_id"] for l in links]


def _client_summary(tenant: Dict[str, Any]) -> Dict[str, Any]:
    """Per-client compliance snapshot — reuses the owner-side Bouclier scoring
    so the cabinet view and the client's own view always agree (single source
    of truth: features.facturation.compute_bouclier)."""
    from features.facturation import compute_bouclier  # lazy: avoid load-order coupling
    tid = tenant["id"]
    b = compute_bouclier(tenant)
    c = b["counts"]
    return {
        "tenant_id": tid,
        "name": tenant.get("legal_name") or tenant.get("name"),
        "siren": tenant.get("siren"),
        "band": b["band"], "score": b["score"],
        "issued": c["issued"], "received": c["received"],
        "einvoicing": c["einvoicing"], "ereporting": c["ereporting"],
        "credit_notes": c["credit_notes"], "refused_open": c["refused_open"],
        # S1: pending-work counters so the cabinet sees workload, not just health
        "unreviewed": c.get("unreviewed", 0),
        "pending_validation": c.get("pending_validation", 0),
        "ready_to_export": c.get("ready_to_export", 0),
        "dgfip_activated": bool(tenant.get("dgfip_activated")),
        "alerts": b["alerts"], "breakdown": b["breakdown"],
    }


# ==========================================================================
# OWNER side — link / unlink my accountant
# ==========================================================================

@router.post("/api/owner/facturation/cabinet/invite")
def invite_accountant(body: Dict[str, Any],
                      token_data=Depends(require_role(["business_owner"]))):
    """Grant my accountant access to my facturation (the 'mandat').
    Creates a comptable login if the email is new (returns a temp password once)."""
    email = _norm(body.get("email"))
    if not email or "@" not in email:
        raise HTTPException(422, "Email invalide.")
    t = _tenant(token_data.tenant_id)
    if not t or not t.get("facturation_enabled"):
        raise HTTPException(403, "Module Facturation non activé.")

    temp_password = None
    existing = _db.users.find_one({"email": email})
    if not existing:
        # Policy-compliant by construction (S3) — an accountant account reaches
        # every linked client's financial data, so it never gets a weak default.
        from services import password_policy
        temp_password = password_policy.generate()
        _db.users.insert_one({
            "email": email, "role": "comptable", "tenant_id": None,
            "hashed_password": hash_password(temp_password),
            "created_at": _now(),
        })
    elif existing.get("role") not in ("comptable",):
        raise HTTPException(409, "Cet email est déjà utilisé par un autre type de compte.")

    if not _db.cabinet_links.find_one({"comptable_email": email, "tenant_id": t["id"]}):
        # Attach the mandate to the accountant's CABINET when they have one, so
        # the whole firm can be scoped/assigned — not just the individual who
        # happened to be invited. Falls back to the email-only link otherwise.
        cabinet_id = None
        assignee = None
        mem = _db.cabinet_memberships.find_one({"user_email": email, "status": "active"})
        if mem:
            cabinet_id = mem.get("cabinet_id")
            from features.cabinet_os import PORTFOLIO_WIDE_ROLES
            assignee = mem["id"] if mem.get("role") not in PORTFOLIO_WIDE_ROLES else None
        _db.cabinet_links.insert_one({
            "id": str(uuid4()), "comptable_email": email,
            "cabinet_id": cabinet_id, "assignee_membership_id": assignee,
            "tenant_id": t["id"], "status": "active", "created_at": _now(),
        })
    _audit("mandate.granted", tenant_id=t["id"], actor=token_data,
           object_kind="mandate", object_id=email,
           after={"comptable_email": email, "status": "active"},
           detail={"account_created": bool(temp_password)})
    return {"ok": True, "email": email, "temp_password": temp_password}


@router.get("/api/owner/facturation/cabinet/links")
def list_my_accountants(token_data=Depends(require_role(["business_owner"]))):
    links = list(_db.cabinet_links.find({"tenant_id": token_data.tenant_id, "status": "active"}))
    return {"accountants": [{"email": l["comptable_email"], "since": l.get("created_at")} for l in links]}


@router.delete("/api/owner/facturation/cabinet/links")
def revoke_accountant(body: Dict[str, Any],
                      token_data=Depends(require_role(["business_owner"]))):
    email = _norm(body.get("email"))
    _db.cabinet_links.update_many(
        {"tenant_id": token_data.tenant_id, "comptable_email": email},
        {"$set": {"status": "revoked", "revoked_at": _now()}})
    _audit("mandate.revoked", tenant_id=token_data.tenant_id, actor=token_data,
           object_kind="mandate", object_id=email,
           before={"status": "active"}, after={"status": "revoked"})
    return {"ok": True}


# ==========================================================================
# COMPTABLE side — the control tower
# ==========================================================================

@router.get("/api/comptable/clients")
def cabinet_clients(token_data=Depends(require_role(["comptable"]))):
    """All clients linked to this accountant, with a red-first compliance summary."""
    tids = _linked_tenant_ids(token_data.email)
    summaries = []
    for tid in tids:
        t = _tenant(tid)
        if t:
            summaries.append(_client_summary(t))
    order = {"red": 0, "amber": 1, "green": 2}
    summaries.sort(key=lambda s: (order.get(s["band"], 3), -len(s["alerts"])))
    reds = sum(1 for s in summaries if s["band"] == "red")
    ambers = sum(1 for s in summaries if s["band"] == "amber")
    return {"clients": summaries,
            "totals": {"count": len(summaries), "red": reds, "amber": ambers,
                       "green": len(summaries) - reds - ambers}}


def assert_mandate(email: str, tenant_id: str) -> Dict[str, Any]:
    """THE tenant-isolation guard for every comptable-side data access.

    Single source of truth (S2): any endpoint that touches a client's data on
    behalf of an accountant must call this. It never trusts a caller-supplied
    tenant_id — it proves an ACTIVE mandate exists for (this accountant, this
    client) and raises 403 otherwise.

    Returns the mandate document so callers can read scope/assignee from it.
    """
    # Team-model scope first (role + assignment aware), legacy email link second.
    try:
        from features.cabinet_os import assert_can_see_tenant, current_membership
        current_membership(_norm(email))          # raises if no membership
        return assert_can_see_tenant(_norm(email), tenant_id)
    except HTTPException:
        raise                                     # a real 403 must not fall through
    except Exception:
        pass                                      # legacy account: use the old path

    link = _db.cabinet_links.find_one({
        "comptable_email": _norm(email),
        "tenant_id": tenant_id,
        "status": "active",
    })
    if not link:
        raise HTTPException(403, "Vous n'avez pas accès à ce dossier.")
    return link


def _require_link(email: str, tenant_id: str):
    """Backwards-compatible alias — kept so existing call-sites keep working."""
    return assert_mandate(email, tenant_id)


@router.get("/api/comptable/clients/{tenant_id}")
def cabinet_client_detail(tenant_id: str, token_data=Depends(require_role(["comptable"]))):
    """Drill into one client (read-only): invoices + compliance snapshot."""
    _require_link(token_data.email, tenant_id)
    t = _tenant(tenant_id)
    if not t:
        raise HTTPException(404, "Dossier introuvable.")
    from services import statuses as st       # lazy: keeps leaf-module independent
    invoices = list(_db.fact_invoices.find({"tenant_id": tenant_id}).sort("created_at", -1).limit(200))
    for i in invoices:
        i.pop("_id", None)
        st.ensure(i)        # legacy rows get their 4 status families filled in
    credit_notes = list(_db.fact_credit_notes.find({"tenant_id": tenant_id}).sort("created_at", -1).limit(200))
    for c in credit_notes:
        c.pop("_id", None)
    received = list(_db.fact_received_invoices.find({"tenant_id": tenant_id}).sort("received_at", -1).limit(200))
    for r in received:
        r.pop("_id", None)
    return {"summary": _client_summary(t), "invoices": invoices,
            "credit_notes": credit_notes, "received": received}


def _is_agent(email):
    try:
        from features.cabinet_os import is_agent_email
        return is_agent_email(email)
    except Exception:
        return False


@router.get("/api/comptable/review-queue")
def review_queue(token_data=Depends(require_role(["comptable"]))):
    """S10 — "what is waiting for MY eyes" (the lab tray, not the archive).

    Every invoice across my visible dossiers whose review is not finished,
    OLDEST FIRST — the order a reviewer should actually work in. Each row says
    who prepared it, and whether validating it would need four eyes for ME
    (so the UI can grey out the button instead of letting a click bounce)."""
    tids = _linked_tenant_ids(token_data.email)
    me = _norm(token_data.email)

    seuil = 1000.0
    try:
        from features.cabinet_os import current_membership
        mem = current_membership(me)
        cab = _db.cabinets.find_one({"id": mem["cabinet_id"]}) or {}
        seuil = float((cab.get("settings") or {}).get("review_threshold_eur", 1000))
    except Exception:
        pass

    tenants = {t["id"]: t for t in _db.tenants.find({"id": {"$in": tids}})}
    rows = []
    for inv in _db.fact_invoices.find({
            "tenant_id": {"$in": tids},
            "review_status": {"$in": [None, "unreviewed", "pending_validation",
                                      "correction_required"]}}):
        from services import statuses as st
        inv = st.ensure(inv)
        if inv["review_status"] == "validated":
            continue
        t = tenants.get(inv["tenant_id"]) or {}
        ttc = float(inv.get("total_ttc") or 0)
        rows.append({
            "id": inv["id"], "number": inv.get("number"),
            "tenant_id": inv["tenant_id"],
            "client_name": t.get("legal_name") or t.get("name"),
            "total_ttc": ttc, "date": inv.get("date"),
            "review_status": inv["review_status"], "pa_status": inv.get("pa_status"),
            "created_by": inv.get("created_by"),
            "created_by_label": ("Agent FidClic"
                                 if _is_agent(inv.get("created_by"))
                                 else inv.get("created_by")),
            "created_at": inv.get("created_at"),
            # four-eyes preview FOR THE CALLER: prepared by me AND >= seuil
            "four_eyes_blocked_for_me": bool(
                inv.get("created_by") and _norm(inv.get("created_by")) == me and ttc >= seuil),
        })
    rows.sort(key=lambda r: r.get("created_at") or "")
    return {"queue": rows, "count": len(rows), "seuil": seuil}


@router.get("/api/comptable/alerts")
def cabinet_alerts(token_data=Depends(require_role(["comptable"]))):
    """One combined feed of everything that needs attention across the portfolio."""
    feed = []
    for tid in _linked_tenant_ids(token_data.email):
        t = _tenant(tid)
        if not t:
            continue
        s = _client_summary(t)
        for a in s["alerts"]:
            feed.append({"client": s["name"], "tenant_id": tid, **a})
    order = {"red": 0, "amber": 1}
    feed.sort(key=lambda a: order.get(a["level"], 2))
    return {"alerts": feed}


@router.get("/api/comptable/export")
def cabinet_export(token_data=Depends(require_role(["comptable"]))):
    """One CSV of every client's issued invoices — no per-PA logins, no re-keying."""
    buf = io.StringIO()
    w = safe_csv.writer(buf, delimiter=",")
    w.writerow(["client", "siren", "type", "channel", "number", "counterparty",
                "total_ht", "total_vat", "total_ttc", "state", "date"])
    for tid in _linked_tenant_ids(token_data.email):
        t = _tenant(tid)
        if not t:
            continue
        cname = t.get("legal_name") or t.get("name")
        siren = t.get("siren", "")
        for inv in _db.fact_invoices.find({"tenant_id": tid}):
            w.writerow([cname, siren, "facture", inv.get("channel", ""), inv.get("number", ""),
                        (inv.get("buyer") or {}).get("name", ""),
                        inv.get("total_ht", 0), inv.get("total_vat", 0),
                        inv.get("total_ttc", 0), inv.get("state", ""), inv.get("date", "")])
        for cn in _db.fact_credit_notes.find({"tenant_id": tid}):
            w.writerow([cname, siren, "avoir", "", cn.get("number", ""),
                        "corrige " + str(cn.get("original_number", "")),
                        -abs(cn.get("amount_ht", 0)), -abs(cn.get("amount_vat", 0)),
                        -abs(cn.get("amount_ttc", 0)), cn.get("state", ""), ""])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=export_cabinet.csv"})
