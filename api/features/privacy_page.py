"""
Paramètres › Données & confidentialité — the business's GDPR controls.

Built to the approved mockup. Each switch does something real:

    Collecte du consentement   always on: nobody gets a card without
                               ticking it (the join page refuses) — shown
                               locked, because the law requires it.
    Communications marketing   off → no campaign, automation or IA message
                               leaves (features/send_rules.gate); what
                               follows a client's own action still does.
    Géolocalisation            off → no proximity reminder is sent.
    Texte de consentement      the sentence on the join page, the shop's own.
    Export                     CSV (Excel, « ; » and UTF-8) or JSON, by
                               section; visits and purchases as their own file.
    Conservation               clients with no activity for N years are
                               anonymised (the same erasure as a client's own
                               « supprimer mes données »); visits older than
                               N years lose their link to the client (the
                               amounts stay for the accounts). Runs daily, only
                               once the owner has saved these durations.
    Suppression d'un client    search, then erase — irreversible.
    Cookies                    the card and the join page use essential
                               storage only; the owner may show a short notice.
    Politique                  the shop's own policy (link or text), shown
                               next to the consent on the join page.

Mounts at /api/owner/privacy/* (owner; managers and administrateurs read).
"""
from __future__ import annotations

import csv
from services import safe_csv
import io
import json
import re
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth import require_role, TokenData
from features import settings_versions as SV   # « Réinitialiser » (Paramètres)

router = APIRouter(tags=["privacy"])
_db = None

READERS = ["business_owner", "administrateur", "manager"]
INACTIVE_YEARS = (1, 2, 3, 5)
TRANSACTION_YEARS = (5, 6, 10)
# Both names (user, 2026-10-09: « data ka maalik dono hai »); the join page
# adds « Je peux retirer mon consentement à tout moment. » under it.
DEFAULT_CONSENT = ("J'accepte que {business_name} et FidClic utilisent mes données personnelles pour gérer ma "
                   "carte de fidélité, mon compte et m'envoyer des offres personnalisées, y compris des offres "
                   "pertinentes à proximité si j'autorise ma position.")
SECTIONS = ("identity", "loyalty", "purchases", "consents", "visits")


def init(db):
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def settings(tid: str) -> Dict[str, Any]:
    p = (_db.tenants.find_one({"id": tid}, {"_id": 0, "privacy": 1}) or {}).get("privacy") or {}
    return {
        "consent": {"collect": True, "marketing": p.get("consent", {}).get("marketing", True) is not False,
                    "geo": p.get("consent", {}).get("geo", True) is not False,
                    "text": p.get("consent", {}).get("text") or ""},
        "retention": {"inactive_years": int(p.get("retention", {}).get("inactive_years") or 3),
                      "transactions_years": int(p.get("retention", {}).get("transactions_years") or 5),
                      "active": bool(p.get("retention", {}).get("saved_at"))},
        "cookies": {"notice": bool(p.get("cookies", {}).get("notice"))},
        "policy": {"url": p.get("policy", {}).get("url") or "", "text": p.get("policy", {}).get("text") or ""},
    }


def marketing_allowed(tid: str) -> bool:
    return settings(tid)["consent"]["marketing"]


def geo_allowed(tid: str) -> bool:
    return settings(tid)["consent"]["geo"]


def public_view(tenant: Dict[str, Any]) -> Dict[str, Any]:
    """What the join page shows: the consent sentence and the policy."""
    s = settings(tenant["id"])
    text = (s["consent"]["text"] or DEFAULT_CONSENT).replace("{business_name}", tenant.get("name") or "")
    return {"consent_text": text, "policy_url": s["policy"]["url"], "policy_text": s["policy"]["text"],
            "cookie_notice": s["cookies"]["notice"]}


@router.get("/api/owner/privacy")
def get_privacy(token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    tid = token_data.tenant_id
    s = settings(tid)
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "name": 1}) or {}
    total = _db.customers.count_documents({"tenant_id": tid, "deleted_at": {"$exists": False}})
    with_consent = _db.customers.count_documents({"tenant_id": tid, "consent.accepted": True,
                                                  "deleted_at": {"$exists": False}})
    geo = _db.customers.count_documents({"tenant_id": tid, "latitude": {"$exists": True}, "deleted_at": {"$exists": False}})
    checks = {"consent": True, "policy": True, "retention": s["retention"]["active"], "erasure": True}
    return {
        **s,
        "default_consent_text": DEFAULT_CONSENT.replace("{business_name}", t.get("name") or "votre commerce"),
        "compliance": {"ok": all(checks.values()), "checks": checks},
        "collected": [
            {"key": "identity", "label": "Informations d'identité", "sub": "Nom, prénom, email, téléphone", "status": "collected",
             "fields": ["Nom et prénom", "Téléphone", "Email (facultatif)", "Code postal", "Date d'anniversaire (facultative)"]},
            {"key": "loyalty", "label": "Données de fidélité", "sub": "Points, historique d'achats", "status": "collected",
             "fields": ["Points et tampons", "Palier", "Récompenses obtenues", "Montants dépensés"]},
            {"key": "visits", "label": "Données de visite", "sub": "Fréquence, date des visites", "status": "collected",
             "fields": ["Date et heure de chaque visite", "Établissement", "Produits achetés (si saisis en caisse)"]},
            {"key": "preferences", "label": "Données de préférence", "sub": "Centres d'intérêt, produits préférés", "status": "collected",
             "fields": ["Produits préférés (déduits des achats)", "Statut étudiant (déclaré)", "Préférences de notification"]},
            {"key": "location", "label": "Données de localisation", "sub": "Position (avec consentement)",
             "status": "optional" if s["consent"]["geo"] else "off",
             "fields": ["Position approximative, seulement si le client l'autorise sur sa carte"], "count": geo},
        ],
        "counts": {"total": total, "with_consent": with_consent},
        "choices": {"inactive_years": list(INACTIVE_YEARS), "transactions_years": list(TRANSACTION_YEARS)},
        "can_edit": getattr(token_data, "role", None) == "business_owner",
    }


class ConsentIn(BaseModel):
    marketing: Optional[bool] = None
    geo: Optional[bool] = None
    text: Optional[str] = Field(None, max_length=600)


class RetentionIn(BaseModel):
    inactive_years: Optional[int] = None
    transactions_years: Optional[int] = None


class PolicyIn(BaseModel):
    url: Optional[str] = Field(None, max_length=300)
    text: Optional[str] = Field(None, max_length=20000)


class PrivacyIn(BaseModel):
    consent: Optional[ConsentIn] = None
    retention: Optional[RetentionIn] = None
    cookie_notice: Optional[bool] = None
    policy: Optional[PolicyIn] = None


@router.put("/api/owner/privacy")
@SV.records("donnees")
def put_privacy(body: PrivacyIn, token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    sets: Dict[str, Any] = {}
    if body.consent:
        for k in ("marketing", "geo"):
            v = getattr(body.consent, k)
            if v is not None:
                sets[f"privacy.consent.{k}"] = bool(v)
        if body.consent.text is not None:
            txt = body.consent.text.strip()
            if txt and len(txt) < 40:
                raise HTTPException(status_code=400, detail="Le texte de consentement doit expliquer l'usage des données (40 caractères minimum).")
            sets["privacy.consent.text"] = txt
    if body.retention:
        r = body.retention
        if r.inactive_years is not None:
            if r.inactive_years not in INACTIVE_YEARS:
                raise HTTPException(status_code=400, detail="Durée de conservation inconnue.")
            sets["privacy.retention.inactive_years"] = r.inactive_years
        if r.transactions_years is not None:
            if r.transactions_years not in TRANSACTION_YEARS:
                raise HTTPException(status_code=400, detail="Durée de conservation inconnue.")
            sets["privacy.retention.transactions_years"] = r.transactions_years
        sets["privacy.retention.saved_at"] = _now()
    if body.cookie_notice is not None:
        sets["privacy.cookies.notice"] = bool(body.cookie_notice)
    if body.policy:
        if body.policy.url is not None:
            url = body.policy.url.strip()
            if url and not re.match(r"^https://", url):
                raise HTTPException(status_code=400, detail="Le lien doit commencer par https://")
            sets["privacy.policy.url"] = url
        if body.policy.text is not None:
            sets["privacy.policy.text"] = body.policy.text.strip()
    if sets:
        _db.tenants.update_one({"id": tid}, {"$set": sets})
        try:
            from server import log_audit
            log_audit("privacy.settings_updated", actor=getattr(token_data, "email", None), actor_type="user",
                      tenant_id=tid, target=tid, meta={"fields": sorted(sets)})
        except Exception:
            pass
    return get_privacy(token_data=token_data)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def _iso(v: Any) -> str:
    return v.isoformat() if isinstance(v, datetime) else (v or "")


def _rows(tid: str, sections: List[str]):
    people, visits = [], []
    customers = list(_db.customers.find({"tenant_id": tid, "deleted_at": {"$exists": False}}, {"_id": 0}))
    for c in customers:
        row: Dict[str, Any] = {"id_client": c.get("id"), "carte": c.get("barcode_id")}
        if "identity" in sections:
            row.update({"nom": c.get("name") or "", "telephone": c.get("phone") or "", "email": c.get("email") or "",
                        "code_postal": c.get("postal_code") or "", "anniversaire": c.get("birthday") or "",
                        "inscrit_le": _iso(c.get("created_at"))})
        if "loyalty" in sections:
            row.update({"palier": c.get("tier") or "", "points": c.get("points") or 0, "visites": c.get("visits") or 0,
                        "total_depense_eur": round(float(c.get("total_amount_paid") or 0), 2),
                        "derniere_visite": _iso(c.get("last_visit_date"))})
        if "consents" in sections:
            cons = c.get("consent") or {}
            prefs = _db.card_prefs.find_one({"customer_id": c.get("id")}) or {}
            row.update({"consentement": "oui" if cons.get("accepted") else "non",
                        "consentement_le": _iso(cons.get("ts")), "version_politique": cons.get("policy_version") or "",
                        "notifications_actives": "non" if prefs.get("push_enabled") is False else "oui"})
        people.append(row)
    if "visits" in sections or "purchases" in sections:
        for v in _db.visits.find({"tenant_id": tid, "customer_id": {"$ne": None}}, {"_id": 0}).sort("visit_time", 1):
            r = {"id_client": v.get("customer_id"), "date": _iso(v.get("visit_time")), "etablissement": v.get("branch_id") or ""}
            if "purchases" in sections:
                r.update({"montant_eur": round(float(v.get("amount_paid") or 0), 2),
                          "produits": ", ".join(f"{i.get('qty') or i.get('quantity') or 1} × {i.get('name')}"
                                                for i in v.get("items") or [] if i.get("name"))})
            visits.append(r)
    return people, visits


def _csv(rows: List[Dict[str, Any]]) -> bytes:
    if not rows:
        return "﻿".encode("utf-8")
    buf = io.StringIO()
    keys = list({k: None for r in rows for k in r})
    w = safe_csv.dict_writer(buf, keys)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return ("﻿" + buf.getvalue()).encode("utf-8")        # Excel reads the BOM as UTF-8


class ExportIn(BaseModel):
    format: str = "csv"
    sections: List[str] = Field(default_factory=lambda: ["identity", "loyalty", "purchases", "consents"])


@router.post("/api/owner/privacy/export")
def export(body: ExportIn, token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    sections = [s for s in body.sections if s in SECTIONS]
    if not sections:
        raise HTTPException(status_code=400, detail="Choisissez au moins une catégorie de données.")
    people, visits = _rows(tid, sections)
    stamp = _now().strftime("%Y-%m-%d")
    try:
        from server import log_audit
        log_audit("privacy.export", actor=getattr(token_data, "email", None), actor_type="user", tenant_id=tid,
                  target=tid, meta={"format": body.format, "sections": sections, "clients": len(people)})
    except Exception:
        pass
    if body.format == "json":
        data = json.dumps({"exporte_le": _now().isoformat(), "clients": people,
                           **({"visites": visits} if visits else {})}, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(content=data, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="clients-{stamp}.json"'})
    if visits:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("clients.csv", _csv(people))
            z.writestr("visites.csv", _csv(visits))
        return Response(content=buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="clients-{stamp}.zip"'})
    return Response(content=_csv(people), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="clients-{stamp}.csv"'})


# ---------------------------------------------------------------------------
# Erasing one client
# ---------------------------------------------------------------------------
@router.get("/api/owner/privacy/search")
def search(q: str = Query("", max_length=80), token_data: TokenData = Depends(require_role(["business_owner"]))):
    q = q.strip()
    if len(q) < 2:
        return {"results": []}
    rx = {"$regex": re.escape(q), "$options": "i"}
    digits = re.sub(r"\D", "", q)
    ors: List[Dict[str, Any]] = [{"name": rx}, {"email": rx}, {"barcode_id": rx}]
    if len(digits) >= 4:
        ors.append({"phone": {"$regex": ".*".join(digits[-9:])}})
    rows = _db.customers.find({"tenant_id": token_data.tenant_id, "deleted_at": {"$exists": False}, "$or": ors},
                              {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "barcode_id": 1, "visits": 1}).limit(10)
    return {"results": list(rows)}


def erase(tid: str, cid: str, actor: str, reason: str) -> bool:
    import server as core
    cust = _db.customers.find_one({"id": cid, "tenant_id": tid})
    if not cust or cust.get("gdpr_erased_at"):
        return False
    core.forget_me(cust["barcode_id"], core.ForgetMeRequest(confirm=True))
    _db.customers.update_one({"id": cid}, {"$set": {"erased_by": actor, "erase_reason": reason}})
    try:
        core.log_audit("gdpr.erased_by_business", actor=actor, actor_type="user" if reason == "owner" else "system",
                       tenant_id=tid, target=cid, meta={"reason": reason})
    except Exception:
        pass
    return True


@router.delete("/api/owner/privacy/customers/{cid}")
def erase_customer(cid: str, confirm: bool = Query(False),
                   token_data: TokenData = Depends(require_role(["business_owner"]))):
    if not confirm:
        raise HTTPException(status_code=422, detail="Confirmation requise.")
    if not erase(token_data.tenant_id, cid, getattr(token_data, "email", None) or "owner", "owner"):
        raise HTTPException(status_code=404, detail="Client introuvable")
    return {"erased": True}


# ---------------------------------------------------------------------------
# Retention — daily
# ---------------------------------------------------------------------------
def apply_retention(at: Optional[datetime] = None) -> Dict[str, int]:
    at = at or _now()
    out = {"tenants": 0, "clients_erased": 0, "visits_unlinked": 0}
    for t in _db.tenants.find({"privacy.retention.saved_at": {"$exists": True}}, {"_id": 0, "id": 1}):
        tid = t["id"]
        s = settings(tid)["retention"]
        cut = at - timedelta(days=365 * s["inactive_years"])
        stale = _db.customers.find({"tenant_id": tid, "gdpr_erased_at": {"$exists": False}, "$or": [
            {"last_visit_date": {"$lt": cut}},
            {"last_visit_date": None, "created_at": {"$lt": cut}},
            {"last_visit_date": {"$exists": False}, "created_at": {"$lt": cut}}]}, {"_id": 0, "id": 1})
        for c in stale:
            if erase(tid, c["id"], "retention", "retention"):
                out["clients_erased"] += 1
        vcut = at - timedelta(days=365 * s["transactions_years"])
        res = _db.visits.update_many({"tenant_id": tid, "visit_time": {"$lt": vcut}, "customer_id": {"$ne": None}},
                                     {"$set": {"customer_id": None, "anonymised_at": at}})
        out["visits_unlinked"] += res.modified_count
        out["tenants"] += 1
    return out
