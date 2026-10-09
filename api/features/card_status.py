"""
Is the customer's card still on their phone — and getting it back
(user, 2026-10-09: « pta chalna chahiye, warna loss hai business owner ka »).

WHAT THE SHOP SEES
    Each client's card: « Active », « Supprimée » (deleted from the FidClic
    card page) or « Retirée d'Apple Wallet » (the last Apple Wallet holding
    it unregistered), with the date. Google Wallet sends no such signal, so
    a card removed there still reads « Active ».
    • Clients list: the status on the row, and a filter (card=active|deleted).
    • The bell: « Marie D. a supprimé sa carte » (last 7 days).
    • Tableau de bord: how many cards were deleted in the last 30 days.

GETTING IT BACK (decided with the user)
    A one-time link, valid 48 hours, that puts the card back on the phone
    that opens it — with its owner key (services/card_owner), so the card
    opens there and nowhere else.
    • Shown as a QR at the counter: every role, staff included (the Scan
      page finds the client by phone).
    • Sent by e-mail: owner, administrateur, manager.
    The link is never the card itself: whoever opens it must press
    « Récupérer ma carte », once; then it is spent.

Mounts at:
    GET  /api/owner/clients/{customer_id}/card          status + last links
    POST /api/owner/clients/{customer_id}/card/readd    {channel: qr|email}
    POST /api/owner/card-readd/find                     {phone} → the client (Scan page)
    GET  /api/card-readd/{token}                        the public page's preview
    POST /api/card-readd/{token}                        use it: card + owner key
"""
from __future__ import annotations

import html
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import require_role
from features import store_scope as S
from models import TokenData

router = APIRouter(tags=["clients"])
_db = None

LINK_HOURS = 48
QR_ROLES = ["business_owner", "administrateur", "manager", "staff"]
EMAIL_ROLES = ["business_owner", "administrateur", "manager"]
BELL_DAYS = 7
DASHBOARD_DAYS = 30

STATE_LABELS = {"active": "Active", "deleted": "Supprimée", "wallet_removed": "Retirée d'Apple Wallet"}


def init(db):
    global _db
    _db = db
    try:
        db.card_readd_links.create_index("token", unique=True)
        db.card_readd_links.create_index([("customer_id", 1), ("created_at", -1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# the status
# ---------------------------------------------------------------------------
FIELDS = {"card_deleted_at": 1, "wallet_removed_at": 1, "card_claimed_at": 1}


def state_of(c: Dict[str, Any]) -> Dict[str, Any]:
    """{state, label, at} — deleted from the card page wins, then Apple Wallet
    removal (unless the card was opened again with its key since)."""
    deleted = _aware(c.get("card_deleted_at"))
    if deleted:
        return {"state": "deleted", "label": STATE_LABELS["deleted"], "at": deleted.isoformat()}
    removed = _aware(c.get("wallet_removed_at"))
    claimed = _aware(c.get("card_claimed_at"))
    if removed and not (claimed and claimed > removed):
        return {"state": "wallet_removed", "label": STATE_LABELS["wallet_removed"], "at": removed.isoformat()}
    return {"state": "active", "label": STATE_LABELS["active"], "at": None}


def matches(c: Dict[str, Any], wanted: str) -> bool:
    """The Clients filter: « deleted » is either way of losing the card."""
    st = state_of(c)["state"]
    if wanted == "active":
        return st == "active"
    if wanted == "deleted":
        return st != "active"
    return True


def recent_losses(tid: str, days: int, at: Optional[datetime] = None,
                  ids: Optional[set] = None) -> List[Dict[str, Any]]:
    """Cards lost in the last `days` days, newest first."""
    at = at or _now()
    since = at - timedelta(days=days)
    q = {"tenant_id": tid, "$or": [{"card_deleted_at": {"$gte": since}}, {"wallet_removed_at": {"$gte": since}}],
         "deleted_at": {"$exists": False}}
    out = []
    for c in _db.customers.find(q, {"_id": 0, "id": 1, "name": 1, **FIELDS}):
        if ids is not None and c["id"] not in ids:
            continue
        st = state_of(c)
        when = _aware(st["at"])
        if st["state"] != "active" and when and when >= since:
            out.append({"id": c["id"], "name": c.get("name") or "Un client", "state": st["state"], "at": when})
    out.sort(key=lambda r: r["at"], reverse=True)
    return out


def _short(name: str) -> str:
    parts = (name or "").split()
    return f"{parts[0]} {parts[-1][0]}." if len(parts) > 1 else (parts[0] if parts else "Un client")


def bell_alerts(tid: str, at: Optional[datetime] = None, ids: Optional[set] = None) -> List[Dict[str, Any]]:
    """For the owner's bell (server.get_alerts_per_shop): one line per card lost
    in the last week, the five newest named, the rest counted."""
    at = at or _now()
    rows = recent_losses(tid, BELL_DAYS, at, ids)
    href = "/dashboard/customers?card=deleted"
    actions = [{"kind": "open", "label": "Voir les clients", "href": href}]
    out = []
    for r in rows[:5]:
        verb = "a supprimé sa carte" if r["state"] == "deleted" else "a retiré sa carte d'Apple Wallet"
        out.append({"id": f"card-lost:{r['id']}:{r['at']:%Y%m%d%H%M}", "severity": "warning",
                    "title": f"{_short(r['name'])} {verb}",
                    "body": "Proposez-lui de la récupérer : un QR en caisse ou un lien par e-mail (fiche client).",
                    "metric": None, "action": href, "actions": actions, "href": href,
                    "ts": r["at"].isoformat(), "branch_id": None, "branch_name": None, "scope": "shop"})
    if len(rows) > 5:
        n = len(rows) - 5
        out.append({"id": f"card-lost:more:{at:%Y%m%d}", "severity": "warning",
                    "title": f"…et {n} autre{'s' if n > 1 else ''} carte{'s' if n > 1 else ''} supprimée{'s' if n > 1 else ''} cette semaine",
                    "body": "La liste complète est dans Clients, filtre « Carte supprimée ».",
                    "metric": str(n), "action": href, "actions": actions, "href": href,
                    "ts": at.isoformat(), "branch_id": None, "branch_name": None, "scope": "shop"})
    return out


def dashboard_count(tid: str, at: Optional[datetime] = None, ids: Optional[set] = None) -> Dict[str, Any]:
    rows = recent_losses(tid, DASHBOARD_DAYS, at, ids)
    return {"count": len(rows), "days": DASHBOARD_DAYS, "href": "/dashboard/customers?card=deleted"}


# ---------------------------------------------------------------------------
# the shop's side
# ---------------------------------------------------------------------------
def _customer(token_data: TokenData, request: Optional[Request], customer_id: str) -> Dict[str, Any]:
    c = _db.customers.find_one({"id": customer_id, "tenant_id": token_data.tenant_id}, {"_id": 0})
    if not c or c.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Client introuvable.")
    mine = S.customer_ids(S.resolve(token_data, request))
    if mine is not None and customer_id not in mine:
        raise HTTPException(status_code=403, detail="Ce client n'appartient pas à vos établissements.")
    return c


def _site_url() -> str:
    return (os.getenv("PUBLIC_APP_URL") or os.getenv("PUBLIC_SITE_URL") or "https://app.fidclic.com").rstrip("/")


def _new_link(c: Dict[str, Any], channel: str, by: str) -> Dict[str, Any]:
    token = secrets.token_urlsafe(18)
    at = _now()
    row = {"id": str(uuid.uuid4()), "token": token, "tenant_id": c["tenant_id"], "customer_id": c["id"],
           "barcode_id": c["barcode_id"], "channel": channel, "created_by": by, "created_at": at,
           "expires_at": at + timedelta(hours=LINK_HOURS), "used_at": None}
    _db.card_readd_links.insert_one(dict(row))
    return {**row, "url": f"{_site_url()}/carte/recuperer/{token}"}


def _link_view(r: Dict[str, Any]) -> Dict[str, Any]:
    exp = _aware(r.get("expires_at"))
    used = _aware(r.get("used_at"))
    return {"channel": r.get("channel"), "created_at": _aware(r.get("created_at")).isoformat(),
            "created_by": r.get("created_by"), "expires_at": exp.isoformat() if exp else None,
            "used_at": used.isoformat() if used else None,
            "state": "used" if used else ("expired" if exp and exp < _now() else "open")}


@router.get("/api/owner/clients/{customer_id}/card")
def card_info(customer_id: str, request: Request = None,
              token_data: TokenData = Depends(require_role(QR_ROLES, partial_ok=True))):
    c = _customer(token_data, request, customer_id)
    links = list(_db.card_readd_links.find({"customer_id": c["id"]}, {"_id": 0}).sort("created_at", -1).limit(5))
    return {"name": c.get("name") or "", "email": c.get("email") or "", "state": state_of(c),
            "can_email": token_data.role in EMAIL_ROLES, "hours": LINK_HOURS,
            "links": [_link_view(r) for r in links]}


class ReaddIn(BaseModel):
    channel: str = "qr"           # qr | email


def _readd(c: Dict[str, Any], channel: str, token_data: TokenData) -> Dict[str, Any]:
    if channel not in ("qr", "email"):
        raise HTTPException(status_code=400, detail="Canal inconnu.")
    if channel == "email" and token_data.role not in EMAIL_ROLES:
        raise HTTPException(status_code=403, detail="L'envoi par e-mail est réservé au propriétaire, aux administrateurs et aux managers.")
    if channel == "email" and not (c.get("email") or "").strip():
        raise HTTPException(status_code=400, detail="Ce client n'a pas d'e-mail : montrez-lui le QR en caisse.")
    link = _new_link(c, channel, token_data.email)
    out = {"url": link["url"], "expires_at": link["expires_at"].isoformat(), "hours": LINK_HOURS, "channel": channel}
    if channel == "email":
        out.update(_send_email(c, link))
    try:
        import server as core
        core.log_audit("card.readd_link", actor=token_data.email, actor_type="user", tenant_id=c["tenant_id"],
                       target=c["id"], meta={"channel": channel})
    except Exception:
        pass
    return out


def _send_email(c: Dict[str, Any], link: Dict[str, Any]) -> Dict[str, Any]:
    from services import mailer
    tenant = _db.tenants.find_one({"id": c["tenant_id"]}, {"_id": 0, "name": 1, "campaign_sender_name": 1}) or {}
    shop = tenant.get("campaign_sender_name") or tenant.get("name") or "votre commerce"
    first = (c.get("name") or "").split(" ")[0]
    url = link["url"]
    subject = f"Récupérez votre carte de fidélité {shop}"
    body = (f"<p>Bonjour{(' ' + html.escape(first)) if first else ''},</p>"
            f"<p>Vous avez demandé à récupérer votre carte de fidélité <strong>{html.escape(shop)}</strong>. "
            "Vos points et vos tampons vous attendent.</p>"
            f"<p><a href=\"{url}\" style=\"display:inline-block;padding:12px 20px;border-radius:10px;"
            "background:#2F6BFF;color:#fff;text-decoration:none;font-weight:600\">Récupérer ma carte</a></p>"
            f"<p style=\"color:#64748B;font-size:13px\">Ce lien fonctionne une seule fois, pendant {LINK_HOURS} heures. "
            "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.</p>")
    text = (f"Bonjour{(' ' + first) if first else ''},\nRécupérez votre carte de fidélité {shop} : {url}\n"
            f"Ce lien fonctionne une seule fois, pendant {LINK_HOURS} heures.")
    if not mailer.ready():
        return {"sent": False, "reason": "L'envoi d'e-mails n'est pas configuré : montrez le QR ou copiez le lien."}
    r = mailer.send(c["email"], subject, body, text=text, to_name=c.get("name") or None)
    return {"sent": bool(r.get("sent")), "to": c["email"],
            **({} if r.get("sent") else {"reason": "L'e-mail n'a pas pu partir. Réessayez ou montrez le QR."})}


@router.post("/api/owner/clients/{customer_id}/card/readd")
def readd(customer_id: str, body: ReaddIn, request: Request = None,
          token_data: TokenData = Depends(require_role(QR_ROLES, partial_ok=True))):
    return _readd(_customer(token_data, request, customer_id), body.channel, token_data)


class FindIn(BaseModel):
    phone: str


@router.post("/api/owner/card-readd/find")
def find_by_phone(body: FindIn, request: Request = None,
                  token_data: TokenData = Depends(require_role(QR_ROLES, partial_ok=True))):
    """The Scan page (staff have no Clients page): the client by phone number."""
    from services import customer_fields as CF
    key = CF.phone_digits(body.phone)
    if len(key) < 6:
        raise HTTPException(status_code=400, detail="Indiquez le numéro de téléphone du client.")
    mine = S.customer_ids(S.resolve(token_data, request))
    for c in _db.customers.find({"tenant_id": token_data.tenant_id, "deleted_at": {"$exists": False}},
                                {"_id": 0, "id": 1, "name": 1, "phone": 1, **FIELDS}):
        if CF.phone_digits(c.get("phone")) == key and (mine is None or c["id"] in mine):
            return {"id": c["id"], "name": c.get("name") or "", "state": state_of(c)}
    raise HTTPException(status_code=404, detail="Aucun client avec ce numéro.")


# ---------------------------------------------------------------------------
# the customer's side — public, the token is the only key
# ---------------------------------------------------------------------------
def _open_link(token: str) -> Dict[str, Any]:
    r = _db.card_readd_links.find_one({"token": token}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Ce lien n'existe pas.")
    if r.get("used_at"):
        raise HTTPException(status_code=410, detail="Ce lien a déjà été utilisé. Demandez-en un nouveau au commerce.")
    exp = _aware(r.get("expires_at"))
    if exp and exp < _now():
        raise HTTPException(status_code=410, detail="Ce lien a expiré. Demandez-en un nouveau au commerce.")
    return r


@router.get("/api/card-readd/{token}")
def preview(token: str):
    """What the page says before the button — the shop, a first name."""
    r = _open_link(token)
    c = _db.customers.find_one({"id": r["customer_id"]}, {"_id": 0, "name": 1}) or {}
    t = _db.tenants.find_one({"id": r["tenant_id"]}, {"_id": 0, "name": 1}) or {}
    return {"business_name": t.get("name") or "", "first_name": (c.get("name") or "").split(" ")[0],
            "expires_at": _aware(r["expires_at"]).isoformat()}


@router.post("/api/card-readd/{token}")
def use(token: str):
    """Once: the card comes back on this phone, with its owner key."""
    r = _open_link(token)
    at = _now()
    done = _db.card_readd_links.update_one({"token": token, "used_at": None}, {"$set": {"used_at": at}})
    if not getattr(done, "modified_count", 1):
        raise HTTPException(status_code=410, detail="Ce lien a déjà été utilisé. Demandez-en un nouveau au commerce.")
    c = _db.customers.find_one({"id": r["customer_id"]}, {"_id": 0})
    if not c or c.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Cette carte n'existe plus.")
    _db.customers.update_one({"id": c["id"]}, {"$unset": {"card_deleted_at": ""},
                                               "$set": {"card_claimed_at": at, "pass_issued": True, "updated_at": at}})
    _db.card_prefs.update_one({"customer_id": c["id"]}, {"$set": {"deleted": False}}, upsert=False)
    from services import card_owner as CO
    return {"barcode_id": c["barcode_id"], "card_key": CO.key_for(c["barcode_id"])}
