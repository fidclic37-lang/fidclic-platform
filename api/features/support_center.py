"""
Super admin › « Centre de support » — built to the approved mockup
(2026-10-01) — and the merchant's side of the same conversations.

What the user decided (2026-10-01):
- A merchant sees the answers on the platform (« Besoin d'aide ? » ›
  « Mes demandes »: the list and the whole conversation, where they can
  reply) AND by email (every answer of the team, once BREVO_API_KEY is set).
- Once a ticket is « Résolu », the merchant is asked for a 1–5 star rating;
  « satisfaction » in the commerce panel is the average of those ratings.
- A ticket the team creates (« Nouveau ticket », e.g. after a phone call) is
  visible to the merchant, who can reply.
- Attachments: up to 10 MB a file (the user is moving to a paid Atlas plan).

The model
- support_tickets: one per conversation — commerce, subject, category,
  status, priority, tags, assignee, unread counters for each side, rating.
  Tickets written before this module (status « open », a single `message`)
  are brought to this shape the first time the module starts.
- support_messages: the thread — kind « message » (merchant or team),
  « note » (internal, never shown to the merchant) and « event » (status,
  assignment… — the history, shown to the team only).
- support_files: the attachments, in the database (like call recordings).
  Uploaded first, then attached to the message that sends them.

Statuses
    nouveau     nobody of the team has answered yet
    en_cours    the team is on it (set by hand, or the merchant wrote again)
    en_attente  the team answered — waiting for the merchant
    urgent      set by hand; stays until resolved
    resolu      done; the merchant is asked for a rating. A new message
                from either side reopens it.
"""
from __future__ import annotations

import csv
from services import safe_csv
import io
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bson.binary import Binary
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth import TokenData, get_current_user_data, require_role
from features.platform_access import require_admin, TEAM_ROLES

router = APIRouter(tags=["support"])
_db = None

STATUSES = [("nouveau", "Nouveau"), ("en_cours", "En cours"), ("en_attente", "En attente"), ("urgent", "Urgent"), ("resolu", "Résolu")]
STATUS_LABEL = dict(STATUSES)
PRIORITIES = [("basse", "Basse"), ("normale", "Normale"), ("haute", "Haute")]
PRIORITY_LABEL = dict(PRIORITIES)
CATEGORIES = [("carte", "Carte fidélité"), ("wallet", "Apple / Google Wallet"), ("facturation", "Facturation"),
              ("technique", "Technique"), ("campagnes", "Campagnes"), ("compte", "Compte & accès"), ("autre", "Autre")]
CATEGORY_LABEL = dict(CATEGORIES)
TAG_COLORS = ("rose", "blue", "green", "amber", "violet", "slate")
DEFAULT_TAGS = [{"label": "Apple Wallet", "color": "rose"}, {"label": "Google Wallet", "color": "green"},
                {"label": "Carte fidélité", "color": "blue"}, {"label": "Technique", "color": "blue"},
                {"label": "Urgent", "color": "rose"}, {"label": "Facturation", "color": "amber"}]
TAGS_KEY = "support_tags"
MERCHANT = ["business_owner", "administrateur", "manager"]
MAX_FILE = 10 * 1024 * 1024
MAX_FILES = 5
FILE_TYPES = {
    "image/png", "image/jpeg", "image/webp", "image/gif", "image/heic", "application/pdf", "text/plain", "text/csv",
    "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/zip", "video/mp4", "video/quicktime",
}
PERIOD_DAYS = 30


def init(db):
    global _db
    _db = db
    for coll, keys in (("support_tickets", [("id", 1)]), ("support_tickets", [("tenant_id", 1), ("last_message_at", -1)]),
                       ("support_tickets", [("status", 1), ("last_message_at", -1)]), ("support_messages", [("ticket_id", 1), ("created_at", 1)]),
                       ("support_files", [("id", 1)])):
        try:
            _db[coll].create_index(keys)
        except Exception:  # noqa: BLE001
            pass
    try:
        _migrate()
    except Exception as exc:  # noqa: BLE001
        print(f"[support] migration skipped: {exc}")


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


def _iso(v: Any) -> Optional[str]:
    d = _aware(v)
    return d.isoformat() if d else None


def _id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Tickets written before this module
# ---------------------------------------------------------------------------
def _migrate() -> int:
    """Old tickets (status « open », one `message`) → this shape, once."""
    n = 0
    for t in _db.support_tickets.find({"v": {"$ne": 2}}, {"_id": 0}):
        at = _aware(t.get("created_at")) or _now()
        status = {"open": "nouveau", "closed": "resolu", "resolved": "resolu"}.get(t.get("status") or "open", t.get("status"))
        if status not in STATUS_LABEL:
            status = "nouveau"
        prio = {"prioritaire": "haute"}.get(t.get("priority") or "normale", t.get("priority") or "normale")
        if prio not in PRIORITY_LABEL:
            prio = "normale"
        if t.get("message") and not _db.support_messages.find_one({"ticket_id": t["id"]}):
            _db.support_messages.insert_one({"id": _id(), "ticket_id": t["id"], "tenant_id": t.get("tenant_id"), "kind": "message",
                                             "author_type": "merchant", "author_email": t.get("from_email"),
                                             "author_name": t.get("from_name") or t.get("tenant_name") or t.get("from_email"),
                                             "body": t["message"], "attachments": [], "created_at": at})
        _db.support_tickets.update_one({"id": t["id"]}, {"$set": {
            "v": 2, "status": status, "priority": prio, "category": t.get("category") or "autre", "tags": t.get("tags") or [],
            "assigned_to": t.get("assigned_to"), "source": t.get("source") or "formulaire",
            "last_message_at": at, "last_message_preview": (t.get("message") or "")[:160], "last_from": "merchant",
            "unread_team": 1 if status == "nouveau" else 0, "unread_merchant": 0, "updated_at": at,
            "pin": _pin({"status": status, "priority": prio})}})
        n += 1
    return n


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _tenant(tid: Optional[str]) -> Dict[str, Any]:
    return (_db.tenants.find_one({"id": tid}, {"_id": 0}) if tid else None) or {}


def _owner(tid: Optional[str]) -> Dict[str, Any]:
    if not tid:
        return {}
    return _db.users.find_one({"tenant_id": tid, "role": "business_owner"}, {"_id": 0, "email": 1, "first_name": 1, "last_name": 1}) or {}


def _person(u: Dict[str, Any]) -> str:
    return " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or (u.get("email") or "").split("@")[0]


def _team() -> Dict[str, Dict[str, Any]]:
    """Members of FidClic's team who can see support (the assignee list)."""
    from features import platform_access as PA
    out = {}
    for u in _db.users.find({"role": {"$in": list(TEAM_ROLES)}, "active": {"$ne": False}}, {"_id": 0, "email": 1, "first_name": 1, "last_name": 1, "role": 1}):
        if u.get("role") != "super_admin":
            perms = PA.perms_for(u["email"]) or {}
            if not (perms.get("support") or {}).get("view"):
                continue
        out[u["email"]] = {"email": u["email"], "name": _person(u), "initials": "".join(w[0] for w in _person(u).split()[:2]).upper()}
    return out


def _logo(tid: Optional[str]) -> Optional[str]:
    if not tid:
        return None
    c = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "logo_url": 1, "brand_fields.logo_url": 1}) or {}
    return c.get("logo_url") or (c.get("brand_fields") or {}).get("logo_url")


def _commerce_brief(t: Dict[str, Any]) -> Dict[str, Any]:
    import server as core
    from features import admin_commerces as AC
    if not t:
        return {}
    key = core._canonical_plan(t.get("plan"))
    return {"id": t["id"], "name": t.get("name") or "—", "sector": AC._sector(t.get("sector")), "city": t.get("city") or "",
            "logo": _logo(t["id"]), "plan": {"key": key, "label": core.plan_label(key)}}


def _tags() -> List[Dict[str, str]]:
    doc = _db.platform_settings.find_one({"key": TAGS_KEY}, {"_id": 0, "value": 1})
    return list((doc or {}).get("value") or DEFAULT_TAGS)


def _alert(kind: str, text: str, ticket: Dict[str, Any], to: Optional[str] = None, audience: str = "team") -> None:
    try:
        _db.support_alerts.insert_one({"id": _id(), "kind": kind, "text": text, "ticket_id": ticket["id"], "tenant_id": ticket.get("tenant_id"),
                                       "to": to, "audience": audience, "at": _now(), "read_by": []})
    except Exception:  # noqa: BLE001
        pass


def _app_url() -> str:
    return (os.environ.get("PUBLIC_APP_URL") or "https://app.fidclic.com").rstrip("/")


def _merchant_email(ticket: Dict[str, Any]) -> Optional[str]:
    return ticket.get("from_email") or _owner(ticket.get("tenant_id")).get("email")


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


def _email_merchant(ticket: Dict[str, Any], title: str, body: str) -> Dict[str, Any]:
    """Every answer of the team also goes by email (user, 2026-10-01). Never
    raises: without BREVO_API_KEY it is simply not sent."""
    to = _merchant_email(ticket)
    if not to:
        return {"sent": False, "reason": "no_email"}
    from services import mailer
    link = f"{_app_url()}/dashboard/aide?ticket={ticket['id']}"
    html = (f"<div style=\"font-family:Inter,Arial,sans-serif;max-width:560px;margin:0 auto;color:#0B1C3F\">"
            f"<p style=\"font-size:12px;color:#2F6BFF;font-weight:700;letter-spacing:.06em;text-transform:uppercase\">FidClic · Support</p>"
            f"<h2 style=\"font-size:18px;margin:4px 0 14px\">{_esc(title)}</h2>"
            f"<p style=\"font-size:13px;color:#64748B;margin:0 0 6px\">Votre demande : <b>{_esc(ticket.get('subject') or '')}</b></p>"
            f"<div style=\"background:#F4F7FC;border-radius:12px;padding:14px 16px;font-size:14px;line-height:1.55\">{_esc(body)}</div>"
            f"<p style=\"margin:18px 0\"><a href=\"{link}\" style=\"background:#2F6BFF;color:#fff;padding:10px 18px;border-radius:10px;"
            f"text-decoration:none;font-weight:600;font-size:14px\">Voir et répondre</a></p>"
            f"<p style=\"font-size:12px;color:#94A3B8\">Répondez depuis votre espace FidClic › Besoin d'aide ? › Mes demandes.</p></div>")
    try:
        return mailer.send(to, f"[FidClic Support] {title}", html, text=f"{title}\n\n{body}\n\n{link}")
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "reason": str(exc)[:120]}


def _notify_inbox(ticket: Dict[str, Any], body: str) -> None:
    """A new ticket from a merchant also reaches FidClic's support mailbox,
    as the form always did (SMTP → Resend → Formsubmit, server.py). In the
    background: Formsubmit can take up to 10 s, the merchant must not wait —
    the ticket is already stored and in the team's inbox and bell."""
    import threading
    try:
        import server as core
        legacy = {**ticket, "created_at": _aware(ticket.get("created_at")) or _now(), "tenant_slug": _tenant(ticket.get("tenant_id")).get("slug")}
        subject = ("[PRIORITAIRE] " if ticket.get("priority") == "haute" else "") + (ticket.get("subject") or "")
        chain = (core._support_send_smtp, core._support_send_resend, core._support_send_formsubmit)
    except Exception:  # noqa: BLE001
        return

    def run():
        for fn in chain:
            try:
                sent, _err = fn(subject, body, legacy)
            except Exception:  # noqa: BLE001
                sent = False
            if sent:
                return
    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------------------
# Creating tickets and messages
# ---------------------------------------------------------------------------
def _take_files(ids: List[str], ticket_id: str, message_id: str, uploader: str, note: bool = False) -> List[Dict[str, Any]]:
    ids = [i for i in (ids or []) if isinstance(i, str)][:MAX_FILES]
    out = []
    for fid in ids:
        f = _db.support_files.find_one({"id": fid, "uploaded_by": uploader, "message_id": None}, {"_id": 0, "data": 0})
        if not f:
            raise HTTPException(status_code=400, detail="Une pièce jointe est introuvable — ajoutez-la à nouveau.")
        _db.support_files.update_one({"id": fid}, {"$set": {"ticket_id": ticket_id, "message_id": message_id, "team_only": note}})
        out.append({"id": fid, "name": f["name"], "size": f["size"], "type": f["content_type"]})
    return out


def new_ticket(*, tenant_id: Optional[str], subject: str, body: str, author_type: str, author_email: Optional[str],
               author_name: Optional[str], category: str = "autre", priority: Optional[str] = None, source: str = "plateforme",
               from_email: Optional[str] = None, from_name: Optional[str] = None, attachments: Optional[List[str]] = None,
               first_kind: str = "message", created_by: Optional[str] = None) -> Dict[str, Any]:
    """One place that opens a conversation — the merchant's form, the
    team's « Nouveau ticket » and the old public contact form."""
    import server as core
    subject, body = (subject or "").strip(), (body or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="L'objet est obligatoire.")
    if not body:
        raise HTTPException(status_code=400, detail="Le message est obligatoire.")
    if len(subject) > 200 or len(body) > 10000:
        raise HTTPException(status_code=400, detail="Objet (200) ou message (10 000 caractères) trop long.")
    t = _tenant(tenant_id)
    if tenant_id and not t:
        raise HTTPException(status_code=404, detail="Commerce introuvable.")
    if priority not in PRIORITY_LABEL:
        priority = "haute" if t and core.features_for(t).get("priority_support") else "normale"
    now = _now()
    team_side = author_type == "team"
    ticket = {"id": _id(), "v": 2, "tenant_id": t.get("id"), "tenant_name": t.get("name"), "subject": subject,
              "category": category if category in CATEGORY_LABEL else "autre", "status": "en_attente" if team_side and first_kind == "message" else "nouveau",
              "priority": priority, "tags": [], "assigned_to": created_by if team_side else None, "source": source,
              "from_email": (from_email or (author_email if not team_side else None) or _owner(t.get("id")).get("email") or None),
              "from_name": from_name or (author_name if not team_side else None), "created_by": created_by,
              "created_at": now, "updated_at": now, "last_message_at": now, "last_message_preview": body[:160],
              "last_from": author_type, "unread_team": 0 if team_side else 1,
              "unread_merchant": 1 if team_side and first_kind == "message" else 0, "first_response_at": now if team_side and first_kind == "message" else None,
              "resolved_at": None, "rating": None}
    if team_side and first_kind == "note":
        ticket["status"] = "en_cours"
    ticket["pin"] = _pin(ticket)
    _db.support_tickets.insert_one(dict(ticket))
    mid = _id()
    files = _take_files(attachments or [], ticket["id"], mid, author_email or "", note=first_kind == "note")
    _db.support_messages.insert_one({"id": mid, "ticket_id": ticket["id"], "tenant_id": ticket["tenant_id"], "kind": first_kind,
                                     "author_type": author_type, "author_email": author_email, "author_name": author_name,
                                     "body": body, "attachments": files, "created_at": now})
    if team_side:
        _event(ticket, author_email, "Ticket créé par l'équipe")
        if first_kind == "message":
            _email_merchant(ticket, "Nouveau message de l'équipe FidClic", body)
            _alert("reply", f"Nouveau message du support : {subject}", ticket, audience="merchant")
    else:
        _alert("new", f"Nouvelle demande — {t.get('name') or from_email or 'contact'} : {subject}", ticket)
        _notify_inbox(ticket, body)
    return ticket


def _event(ticket: Dict[str, Any], by: Optional[str], text: str, meta: Optional[Dict[str, Any]] = None) -> None:
    _db.support_messages.insert_one({"id": _id(), "ticket_id": ticket["id"], "tenant_id": ticket.get("tenant_id"), "kind": "event",
                                     "author_type": "team", "author_email": by, "author_name": (_team().get(by or "") or {}).get("name") or by,
                                     "body": text, "meta": meta or {}, "attachments": [], "created_at": _now()})


def _pin(t: Dict[str, Any]) -> int:
    """Plan Limits › « Support prioritaire »: a priority business's open
    tickets come first in the inbox — so do urgent ones."""
    return 1 if t.get("status") != "resolu" and (t.get("priority") == "haute" or t.get("status") == "urgent") else 0


def _repin(tid: str) -> None:
    t = _db.support_tickets.find_one({"id": tid}, {"_id": 0, "status": 1, "priority": 1, "pin": 1})
    if t and t.get("pin") != _pin(t):
        _db.support_tickets.update_one({"id": tid}, {"$set": {"pin": _pin(t)}})


def _ticket(tid: str) -> Dict[str, Any]:
    t = _db.support_tickets.find_one({"id": tid}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket introuvable.")
    return t


def _set_status(ticket: Dict[str, Any], status: str, by: Optional[str]) -> Dict[str, Any]:
    if status == ticket.get("status"):
        return {}
    sets: Dict[str, Any] = {"status": status, "updated_at": _now()}
    if status == "resolu":
        sets["resolved_at"] = _now()
    elif ticket.get("status") == "resolu":
        sets["resolved_at"] = None
    _event(ticket, by, f"Statut : {STATUS_LABEL.get(ticket.get('status'), '—')} → {STATUS_LABEL[status]}", {"field": "status", "from": ticket.get("status"), "to": status})
    return sets


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
def _row(t: Dict[str, Any], team: Dict[str, Dict[str, Any]], tenants: Dict[str, Dict[str, Any]], logos: Dict[str, Optional[str]]) -> Dict[str, Any]:
    import server as core
    from features import admin_commerces as AC
    ten = tenants.get(t.get("tenant_id") or "") or {}
    key = core._canonical_plan(ten.get("plan")) if ten else None
    return {"id": t["id"], "subject": t.get("subject") or "", "preview": t.get("last_message_preview") or "", "status": t.get("status"),
            "status_label": STATUS_LABEL.get(t.get("status"), "—"), "priority": t.get("priority"), "priority_label": PRIORITY_LABEL.get(t.get("priority"), "—"),
            "category": t.get("category"), "category_label": CATEGORY_LABEL.get(t.get("category"), "Autre"), "tags": t.get("tags") or [],
            "unread": int(t.get("unread_team") or 0), "last_from": t.get("last_from"), "last_message_at": _iso(t.get("last_message_at")),
            "created_at": _iso(t.get("created_at")), "assigned": team.get(t.get("assigned_to") or ""),
            "commerce": {"id": ten.get("id"), "name": ten.get("name") or t.get("tenant_name") or t.get("from_name") or t.get("from_email") or "Contact",
                         "sector": AC._sector(ten.get("sector")) if ten else "", "city": ten.get("city") or "", "logo": logos.get(ten.get("id") or ""),
                         "plan": {"key": key, "label": core.plan_label(key)} if key else None},
            "contact": t.get("from_email"), "rating": (t.get("rating") or {}).get("stars")}


def _filter_query(tab: str = "", q: str = "", status: str = "", priority: str = "", category: str = "", assigned: str = "", tag: str = "",
                  plan: str = "", unread: str = "", me: str = "") -> Dict[str, Any]:
    import server as core
    m: Dict[str, Any] = {}
    st = status or {"nouveaux": "nouveau", "en_cours": "en_cours", "en_attente": "en_attente", "urgents": "urgent", "resolus": "resolu"}.get(tab, "")
    if st in STATUS_LABEL:
        m["status"] = st
    if priority in PRIORITY_LABEL:
        m["priority"] = priority
    if category in CATEGORY_LABEL:
        m["category"] = category
    if assigned == "moi":
        m["assigned_to"] = me
    elif assigned == "aucun":
        m["assigned_to"] = None
    elif assigned:
        m["assigned_to"] = assigned
    if tag:
        m["tags"] = tag
    if unread == "1":
        m["unread_team"] = {"$gt": 0}
    if plan:
        ids = [t["id"] for t in _db.tenants.find({}, {"_id": 0, "id": 1, "plan": 1}) if core._canonical_plan(t.get("plan")) == plan]
        m["tenant_id"] = {"$in": ids}
    if q.strip():
        rx = re.compile(re.escape(q.strip()), re.I)
        by_msg = {x["ticket_id"] for x in _db.support_messages.find({"body": rx, "kind": {"$in": ["message", "note"]}}, {"_id": 0, "ticket_id": 1})}
        by_ten = [t["id"] for t in _db.tenants.find({"$or": [{"name": rx}, {"city": rx}]}, {"_id": 0, "id": 1})]
        m["$or"] = [{"subject": rx}, {"tenant_name": rx}, {"from_email": rx}, {"from_name": rx}, {"id": {"$in": list(by_msg)}},
                    {"tenant_id": {"$in": by_ten}}]
    return m


def _counts() -> Dict[str, int]:
    c = {k: 0 for k, _ in STATUSES}
    for x in _db.support_tickets.find({}, {"_id": 0, "status": 1}):
        if x.get("status") in c:
            c[x["status"]] += 1
    return c


def _kpis(now: datetime) -> List[Dict[str, Any]]:
    """Five cards: how many tickets are in each status today, and how many
    entered it over the last 30 days against the 30 days before."""
    c = _counts()
    a, b = now - timedelta(days=PERIOD_DAYS), now - timedelta(days=2 * PERIOD_DAYS)
    flow = {k: [0, 0] for k, _ in STATUSES}
    for t in _db.support_tickets.find({"created_at": {"$gte": b}}, {"_id": 0, "created_at": 1}):
        at = _aware(t.get("created_at"))
        if at:
            flow["nouveau"][0 if at >= a else 1] += 1
    for e in _db.support_messages.find({"kind": "event", "meta.field": "status", "created_at": {"$gte": b}}, {"_id": 0, "meta": 1, "created_at": 1}):
        to, at = (e.get("meta") or {}).get("to"), _aware(e.get("created_at"))
        if to in flow and at and to != "nouveau":
            flow[to][0 if at >= a else 1] += 1
    from features import admin_commerces as AC
    return [{"key": k, "label": {"nouveau": "Nouveaux", "en_cours": "En cours", "en_attente": "En attente", "urgent": "Urgents", "resolu": "Résolus"}[k],
             "value": c[k], "delta": AC._delta(flow[k][0], flow[k][1]), "period": flow[k][0]} for k in ("nouveau", "en_cours", "en_attente", "resolu", "urgent")]


def _message_view(m: Dict[str, Any], merchant_read_at: Optional[datetime], for_merchant: bool = False) -> Dict[str, Any]:
    at = _aware(m.get("created_at"))
    out = {"id": m["id"], "kind": m.get("kind"), "author_type": m.get("author_type"), "author_name": m.get("author_name") or m.get("author_email") or "",
           "body": m.get("body") or "", "attachments": m.get("attachments") or [], "created_at": _iso(at)}
    if not for_merchant:
        out["author_email"] = m.get("author_email")
        out["meta"] = m.get("meta") or {}
    if m.get("author_type") == "team" and m.get("kind") == "message":
        out["read"] = bool(merchant_read_at and at and merchant_read_at >= at)
    return out


def _panel(t: Dict[str, Any]) -> Dict[str, Any]:
    """« Informations commerce »."""
    import server as core
    from features import admin_commerces as AC
    ten = _tenant(t.get("tenant_id"))
    if not ten:
        return {"contact": {"email": t.get("from_email"), "name": t.get("from_name")}}
    now = _now()
    r = AC.rules()
    since = now - timedelta(days=int(r["window_days"]))
    cards = _db.customers.count_documents({"tenant_id": ten["id"], **AC.LIVE, "created_at": {"$gte": since}})
    scans = _db.visits.count_documents({"tenant_id": ten["id"], "visit_time": {"$gte": since}})
    st = AC.status_of(ten, cards, r, now, scans)
    standing = AC.standing_of(ten, now)
    label = {"essai": "En essai", "impaye": "Impayé", "resilie": "Résilié", "non_converti": "Essai non converti"}.get(standing) or \
        {"actif": "Client actif", "inactif": "Client inactif", "a_risque": "Client à risque", "suspendu": "Suspendu"}.get(st["key"], "Client")
    owner = _owner(ten["id"])
    rated = [x["rating"]["stars"] for x in _db.support_tickets.find({"tenant_id": ten["id"], "rating.stars": {"$gte": 1}}, {"_id": 0, "rating": 1})]
    key = core._canonical_plan(ten.get("plan"))
    return {**_commerce_brief(ten), "status": st["key"], "status_label": label,
            "phone": ten.get("phone") or "", "email": owner.get("email") or ten.get("email") or t.get("from_email") or "",
            "owner": _person(owner) if owner else "", "address": ", ".join(x for x in (ten.get("city"), "France") if x),
            "plan": {"key": key, "label": core.plan_label(key)},
            "plan_since": _iso(ten.get("subscription_started_at") or ten.get("created_at")),
            "clients": _db.customers.count_documents({"tenant_id": ten["id"], **AC.LIVE}),
            "campaigns": _db.campaigns.count_documents({"tenant_id": ten["id"]}),
            "satisfaction": round(sum(rated) / len(rated), 1) if rated else None, "ratings": len(rated),
            "tickets": _db.support_tickets.count_documents({"tenant_id": ten["id"]})}


def _options(team: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    import models
    return {"statuses": [{"key": k, "label": v} for k, v in STATUSES], "priorities": [{"key": k, "label": v} for k, v in PRIORITIES],
            "categories": [{"key": k, "label": v} for k, v in CATEGORIES], "team": list(team.values()), "tags": _tags(),
            "plans": [{"key": k, "label": v} for k, v in models.PLAN_LABELS.items()]}


# ---------------------------------------------------------------------------
# Super admin endpoints
# ---------------------------------------------------------------------------
@router.get("/api/admin/support/overview")
def overview(token_data: TokenData = Depends(require_admin("support"))):
    c = _counts()
    return {"kpis": _kpis(_now()), "counts": {**c, "tous": sum(c.values()), "ouverts": sum(v for k, v in c.items() if k != "resolu")},
            "unread": _db.support_tickets.count_documents({"unread_team": {"$gt": 0}})}


@router.get("/api/admin/support/badge")
def badge(token_data: TokenData = Depends(require_admin("support"))):
    return {"unread": _db.support_tickets.count_documents({"unread_team": {"$gt": 0}})}


@router.get("/api/admin/support/tickets")
def list_tickets(tab: str = "", q: str = "", status: str = "", priority: str = "", category: str = "", assigned: str = "", tag: str = "",
                 plan: str = "", unread: str = "", page: int = 1, per_page: int = 30,
                 token_data: TokenData = Depends(require_admin("support"))):
    m = _filter_query(tab, q, status, priority, category, assigned, tag, plan, unread, token_data.email)
    per_page = max(1, min(100, int(per_page)))
    total = _db.support_tickets.count_documents(m)
    pages = max(1, -(-total // per_page))
    page = max(1, min(int(page), pages))
    rows = list(_db.support_tickets.find(m, {"_id": 0}).sort([("pin", -1), ("last_message_at", -1)]).skip((page - 1) * per_page).limit(per_page))
    team = _team()
    tids = list({r.get("tenant_id") for r in rows if r.get("tenant_id")})
    tenants = {t["id"]: t for t in _db.tenants.find({"id": {"$in": tids}}, {"_id": 0})}
    logos = {tid: _logo(tid) for tid in tids}
    c = _counts()
    return {"rows": [_row(t, team, tenants, logos) for t in rows], "total": total, "page": page, "pages": pages, "per_page": per_page,
            "tabs": {"tous": sum(c.values()), "nouveaux": c["nouveau"], "en_cours": c["en_cours"]},
            "open": sum(v for k, v in c.items() if k != "resolu"), "options": _options(team)}


@router.get("/api/admin/support/tickets/{tid}")
def get_ticket(tid: str, token_data: TokenData = Depends(require_admin("support"))):
    t = _ticket(tid)
    if t.get("unread_team"):
        _db.support_tickets.update_one({"id": tid}, {"$set": {"unread_team": 0, "team_read_at": _now()}})
        t["unread_team"] = 0
    team = _team()
    msgs = list(_db.support_messages.find({"ticket_id": tid}, {"_id": 0}).sort("created_at", 1))
    read_at = _aware(t.get("merchant_read_at"))
    ten = _tenant(t.get("tenant_id"))
    row = _row(t, team, {ten["id"]: ten} if ten else {}, {ten["id"]: _logo(ten["id"])} if ten else {})
    return {"ticket": {**row, "from_name": t.get("from_name"), "source": t.get("source"), "resolved_at": _iso(t.get("resolved_at")),
                       "rating": t.get("rating") and {**t["rating"], "at": _iso(t["rating"].get("at"))}, "first_response_at": _iso(t.get("first_response_at"))},
            "messages": [_message_view(m, read_at) for m in msgs], "commerce": _panel(t), "options": _options(team)}


class TicketIn(BaseModel):
    tenant_id: Optional[str] = None
    contact_email: Optional[str] = None
    subject: str = Field(..., max_length=200)
    body: str = Field(..., max_length=10000)
    category: str = "autre"
    priority: str = "normale"
    kind: str = "message"                    # « message » the merchant sees, or an internal « note »
    attachments: List[str] = []
    assigned_to: Optional[str] = None


@router.post("/api/admin/support/tickets")
def create_ticket(body: TicketIn, token_data: TokenData = Depends(require_admin("support"))):
    if not body.tenant_id and not (body.contact_email or "").strip():
        raise HTTPException(status_code=400, detail="Choisissez un commerce.")
    me = _team().get(token_data.email) or {"name": token_data.email}
    t = new_ticket(tenant_id=body.tenant_id, subject=body.subject, body=body.body, author_type="team", author_email=token_data.email,
                   author_name=me["name"], category=body.category, priority=body.priority, source="equipe",
                   from_email=(body.contact_email or "").strip() or None, attachments=body.attachments,
                   first_kind="note" if body.kind == "note" else "message", created_by=token_data.email)
    if body.assigned_to and body.assigned_to != token_data.email:
        patch_ticket(t["id"], PatchIn(assigned_to=body.assigned_to), token_data)
    return {"ok": True, "id": t["id"]}


class MessageIn(BaseModel):
    body: str = Field("", max_length=10000)
    kind: str = "message"
    attachments: List[str] = []
    mentions: List[str] = []


@router.post("/api/admin/support/tickets/{tid}/messages")
def team_message(tid: str, body: MessageIn, token_data: TokenData = Depends(require_admin("support"))):
    t = _ticket(tid)
    text = (body.body or "").strip()
    if not text and not body.attachments:
        raise HTTPException(status_code=400, detail="Écrivez un message ou ajoutez une pièce jointe.")
    note = body.kind == "note"
    team = _team()
    me = team.get(token_data.email) or {"name": token_data.email}
    mid, now = _id(), _now()
    files = _take_files(body.attachments, tid, mid, token_data.email, note=note)
    _db.support_messages.insert_one({"id": mid, "ticket_id": tid, "tenant_id": t.get("tenant_id"), "kind": "note" if note else "message",
                                     "author_type": "team", "author_email": token_data.email, "author_name": me["name"], "body": text,
                                     "attachments": files, "mentions": [e for e in body.mentions if e in team], "created_at": now})
    sets: Dict[str, Any] = {"updated_at": now}
    if not note:
        sets.update({"last_message_at": now, "last_message_preview": (text or f"📎 {files[0]['name']}")[:160], "last_from": "team",
                     "unread_merchant": int(t.get("unread_merchant") or 0) + 1})
        if not t.get("first_response_at"):
            sets["first_response_at"] = now
        if t.get("status") in ("nouveau", "en_cours", "resolu"):
            sets.update(_set_status(t, "en_attente", token_data.email))
        if not t.get("assigned_to"):
            sets["assigned_to"] = token_data.email
        _db.support_tickets.update_one({"id": tid}, {"$set": sets})
        _repin(tid)
        _alert("reply", f"Nouvelle réponse du support : {t.get('subject')}", t, audience="merchant")
        _email_merchant(t, "Nouvelle réponse de l'équipe FidClic", text or "Une pièce jointe vous a été envoyée.")
    else:
        _db.support_tickets.update_one({"id": tid}, {"$set": sets})
    for e in set(body.mentions):
        if e in team and e != token_data.email:
            _alert("mention", f"{me['name']} vous a mentionné : {t.get('subject')}", t, to=e)
    return {"ok": True, "id": mid}


class PatchIn(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    assigned_to: Optional[str] = None       # "" = nobody
    tags: Optional[List[str]] = None        # the whole list
    add_tags: Optional[List[str]] = None    # or one change at a time — two quick
    remove_tags: Optional[List[str]] = None  # clicks can never undo each other


def _patch(t: Dict[str, Any], body: PatchIn, by: str) -> Dict[str, Any]:
    sets: Dict[str, Any] = {}
    team = _team()
    if body.status is not None:
        if body.status not in STATUS_LABEL:
            raise HTTPException(status_code=400, detail="Statut inconnu.")
        sets.update(_set_status(t, body.status, by))
        if body.status == "resolu" and t.get("status") != "resolu":
            _alert("resolved", f"Votre demande est résolue : {t.get('subject')} — donnez votre avis", t, audience="merchant")
            _email_merchant(t, "Votre demande est résolue", "Notre équipe a marqué votre demande comme résolue. "
                            "Si ce n'est pas le cas, répondez simplement depuis votre espace. Vous pouvez aussi nous donner votre avis (1 à 5 étoiles).")
    if body.priority is not None and body.priority != t.get("priority"):
        if body.priority not in PRIORITY_LABEL:
            raise HTTPException(status_code=400, detail="Priorité inconnue.")
        sets["priority"] = body.priority
        _event(t, by, f"Priorité : {PRIORITY_LABEL.get(t.get('priority'), '—')} → {PRIORITY_LABEL[body.priority]}", {"field": "priority", "to": body.priority})
    if body.category is not None and body.category != t.get("category"):
        if body.category not in CATEGORY_LABEL:
            raise HTTPException(status_code=400, detail="Catégorie inconnue.")
        sets["category"] = body.category
        _event(t, by, f"Catégorie : {CATEGORY_LABEL.get(t.get('category'), '—')} → {CATEGORY_LABEL[body.category]}", {"field": "category", "to": body.category})
    if body.assigned_to is not None and (body.assigned_to or None) != t.get("assigned_to"):
        who = body.assigned_to or None
        if who and who not in team:
            raise HTTPException(status_code=400, detail="Ce membre de l'équipe n'a pas accès au support.")
        sets["assigned_to"] = who
        _event(t, by, f"Assigné à {team[who]['name']}" if who else "Ticket désassigné", {"field": "assigned_to", "to": who})
        if who and who != by:
            _alert("assigned", f"Ticket assigné par {(team.get(by) or {}).get('name') or by} : {t.get('subject')}", t, to=who)
    if body.add_tags or body.remove_tags:
        fresh = (_db.support_tickets.find_one({"id": t["id"]}, {"_id": 0, "tags": 1}) or {}).get("tags") or []
        drop = {(x or "").strip() for x in (body.remove_tags or [])}
        body.tags = [x for x in fresh if x not in drop] + [x for x in (body.add_tags or []) if x not in fresh]
    if body.tags is not None:
        known = {x["label"] for x in _tags()}
        tags = []
        for x in body.tags:
            x = (x or "").strip()[:40]
            if x and x not in tags:
                tags.append(x)
        new = [x for x in tags if x not in known]
        if new:
            _db.platform_settings.update_one({"key": TAGS_KEY}, {"$set": {"key": TAGS_KEY, "value": _tags() + [{"label": x, "color": "slate"} for x in new]}}, upsert=True)
        sets["tags"] = tags[:12]
    if sets:
        sets["updated_at"] = _now()
        _db.support_tickets.update_one({"id": t["id"]}, {"$set": sets})
        _repin(t["id"])
    return sets


@router.patch("/api/admin/support/tickets/{tid}")
def patch_ticket(tid: str, body: PatchIn, token_data: TokenData = Depends(require_admin("support"))):
    _patch(_ticket(tid), body, token_data.email)
    return {"ok": True}


class BulkIn(BaseModel):
    ids: List[str]
    status: Optional[str] = None
    assigned_to: Optional[str] = None
    read: Optional[bool] = None


@router.post("/api/admin/support/tickets/bulk")
def bulk(body: BulkIn, token_data: TokenData = Depends(require_admin("support"))):
    n = 0
    for tid in body.ids[:200]:
        t = _db.support_tickets.find_one({"id": tid}, {"_id": 0})
        if not t:
            continue
        if body.status is not None or body.assigned_to is not None:
            _patch(t, PatchIn(status=body.status, assigned_to=body.assigned_to), token_data.email)
        if body.read is not None:
            _db.support_tickets.update_one({"id": tid}, {"$set": {"unread_team": 0 if body.read else max(1, int(t.get("unread_team") or 0))}})
        n += 1
    return {"ok": True, "count": n}


@router.post("/api/admin/support/tickets/{tid}/unread")
def mark_unread(tid: str, token_data: TokenData = Depends(require_admin("support"))):
    t = _ticket(tid)
    _db.support_tickets.update_one({"id": tid}, {"$set": {"unread_team": max(1, int(t.get("unread_team") or 0))}})
    return {"ok": True}


def _csv(rows: List[List[Any]], name: str) -> Response:
    buf = io.StringIO()
    w = safe_csv.writer(buf)
    for r in rows:
        w.writerow(r)
    return Response(content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}-{_now().strftime("%Y-%m-%d")}.csv"'})


def _fr(v: Any) -> str:
    d = _aware(v)
    return d.astimezone(timezone(timedelta(hours=2))).strftime("%d/%m/%Y %H:%M") if d else ""


@router.get("/api/admin/support/export")
def export(tab: str = "", q: str = "", status: str = "", priority: str = "", category: str = "", assigned: str = "", tag: str = "",
           plan: str = "", unread: str = "", ids: str = "", token_data: TokenData = Depends(require_admin("support"))):
    m = {"id": {"$in": ids.split(",")}} if ids else _filter_query(tab, q, status, priority, category, assigned, tag, plan, unread, token_data.email)
    team = _team()
    rows = [["Commerce", "Contact", "Objet", "Catégorie", "Statut", "Priorité", "Assigné à", "Tags", "Créé le", "Dernier message",
             "Première réponse", "Résolu le", "Note (1-5)", "Messages"]]
    for t in _db.support_tickets.find(m, {"_id": 0}).sort("last_message_at", -1):
        n = _db.support_messages.count_documents({"ticket_id": t["id"], "kind": "message"})
        rows.append([t.get("tenant_name") or "", t.get("from_email") or "", t.get("subject") or "", CATEGORY_LABEL.get(t.get("category"), ""),
                     STATUS_LABEL.get(t.get("status"), ""), PRIORITY_LABEL.get(t.get("priority"), ""),
                     (team.get(t.get("assigned_to") or "") or {}).get("name") or t.get("assigned_to") or "", ", ".join(t.get("tags") or []),
                     _fr(t.get("created_at")), _fr(t.get("last_message_at")), _fr(t.get("first_response_at")), _fr(t.get("resolved_at")),
                     (t.get("rating") or {}).get("stars") or "", n])
    return _csv(rows, "support-tickets")


@router.get("/api/admin/support/tickets/{tid}/export")
def export_thread(tid: str, token_data: TokenData = Depends(require_admin("support"))):
    t = _ticket(tid)
    rows = [["Date", "Type", "Auteur", "Message", "Pièces jointes"]]
    kinds = {"message": "Message", "note": "Note interne", "event": "Historique"}
    for m in _db.support_messages.find({"ticket_id": tid}, {"_id": 0}).sort("created_at", 1):
        rows.append([_fr(m.get("created_at")), kinds.get(m.get("kind"), ""), m.get("author_name") or m.get("author_email") or "",
                     m.get("body") or "", ", ".join(a["name"] for a in m.get("attachments") or [])])
    slug = re.sub(r"[^a-z0-9]+", "-", (t.get("tenant_name") or "ticket").lower()).strip("-") or "ticket"
    return _csv(rows, f"support-{slug}")


# Saved replies (« Réponse enregistrée »)
class ReplyIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)
    body: str = Field(..., min_length=1, max_length=5000)


DEFAULT_REPLIES = [
    {"title": "Accusé de réception", "body": "Bonjour {prenom},\n\nMerci pour votre message. Nous regardons cela tout de suite et revenons vers vous rapidement.\n\nL'équipe FidClic"},
    {"title": "Demande de capture d'écran", "body": "Bonjour {prenom},\n\nPouvez-vous nous envoyer une capture d'écran du message que voient vos clients ? Cela nous aidera à identifier le problème.\n\nMerci !"},
    {"title": "Problème résolu", "body": "Bonjour {prenom},\n\nLe problème est maintenant résolu de notre côté. N'hésitez pas à nous répondre si quelque chose ne fonctionne toujours pas.\n\nBonne journée,\nL'équipe FidClic"},
]


def _replies() -> List[Dict[str, Any]]:
    if not _db.support_replies.find_one({}):
        for r in DEFAULT_REPLIES:
            _db.support_replies.insert_one({"id": _id(), **r, "created_by": "fidclic", "updated_at": _now()})
    return [{**r, "updated_at": _iso(r.get("updated_at"))} for r in _db.support_replies.find({}, {"_id": 0}).sort("title", 1)]


@router.get("/api/admin/support/replies")
def list_replies(token_data: TokenData = Depends(require_admin("support"))):
    return {"rows": _replies()}


@router.post("/api/admin/support/replies")
def add_reply(body: ReplyIn, token_data: TokenData = Depends(require_admin("support"))):
    rid = _id()
    _db.support_replies.insert_one({"id": rid, "title": body.title.strip(), "body": body.body.strip(), "created_by": token_data.email, "updated_at": _now()})
    return {"ok": True, "id": rid}


@router.put("/api/admin/support/replies/{rid}")
def edit_reply(rid: str, body: ReplyIn, token_data: TokenData = Depends(require_admin("support"))):
    r = _db.support_replies.update_one({"id": rid}, {"$set": {"title": body.title.strip(), "body": body.body.strip(), "updated_at": _now()}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Réponse introuvable.")
    return {"ok": True}


@router.delete("/api/admin/support/replies/{rid}")
def delete_reply(rid: str, token_data: TokenData = Depends(require_admin("support"))):
    _db.support_replies.delete_one({"id": rid})
    return {"ok": True}


# Tags (« Gérer »)
class TagIn(BaseModel):
    label: str = Field(..., min_length=1, max_length=40)
    color: str = "slate"


class TagsIn(BaseModel):
    tags: List[TagIn]
    renamed: Dict[str, str] = {}


@router.get("/api/admin/support/tags")
def get_tags(token_data: TokenData = Depends(require_admin("support"))):
    return {"tags": _tags(), "colors": list(TAG_COLORS)}


@router.put("/api/admin/support/tags")
def save_tags(body: TagsIn, token_data: TokenData = Depends(require_admin("support"))):
    clean, seen = [], set()
    for x in body.tags:
        label = x.label.strip()
        if label and label.lower() not in seen:
            seen.add(label.lower())
            clean.append({"label": label, "color": x.color if x.color in TAG_COLORS else "slate"})
    before = {x["label"] for x in _tags()}
    _db.platform_settings.update_one({"key": TAGS_KEY}, {"$set": {"key": TAGS_KEY, "value": clean}}, upsert=True)
    for old, new in body.renamed.items():               # a renamed tag follows on its tickets
        if old in before and new.strip():
            for t in _db.support_tickets.find({"tags": old}, {"_id": 0, "id": 1, "tags": 1}):
                _db.support_tickets.update_one({"id": t["id"]}, {"$set": {"tags": [new.strip() if x == old else x for x in t["tags"]]}})
    gone = before - {x["label"] for x in clean} - set(body.renamed)
    for g in gone:                                      # a deleted tag leaves its tickets
        _db.support_tickets.update_many({"tags": g}, {"$pull": {"tags": g}})
    return {"ok": True, "tags": clean}


# The commerces a ticket can be opened for (« Nouveau ticket »)
@router.get("/api/admin/support/commerces")
def pick_commerce(q: str = "", token_data: TokenData = Depends(require_admin("support"))):
    m: Dict[str, Any] = {"is_active": {"$ne": False}}
    if q.strip():
        rx = re.compile(re.escape(q.strip()), re.I)
        m["$or"] = [{"name": rx}, {"city": rx}]
    return {"rows": [_commerce_brief(t) for t in _db.tenants.find(m, {"_id": 0}).sort("name", 1).limit(20)]}


# The bell of FidClic's team
@router.get("/api/admin/support/alerts")
def team_alerts(token_data: TokenData = Depends(require_admin("support"))):
    rows = list(_db.support_alerts.find({"audience": "team", "$or": [{"to": None}, {"to": token_data.email}],
                                         "at": {"$gte": _now() - timedelta(days=14)}}, {"_id": 0}).sort("at", -1).limit(30))
    sev = {"new": "warning", "mention": "info", "assigned": "info"}
    return {"alerts": [{"id": f"sup-{a['id']}", "severity": sev.get(a["kind"], "info"), "title": a["text"],
                        "body": {"new": "Nouvelle demande de support", "mention": "Mention dans une note interne",
                                 "assigned": "Ticket assigné"}.get(a["kind"], "Support"),
                        "created_at": _iso(a["at"]), "action": {"label": "Ouvrir le ticket", "href": f"/admin/support?ticket={a['ticket_id']}"}}
                       for a in rows]}


# ---------------------------------------------------------------------------
# Files (both sides)
# ---------------------------------------------------------------------------
async def _store(file: UploadFile, uploader: str, tenant_id: Optional[str]) -> Dict[str, Any]:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Fichier vide.")
    if len(data) > MAX_FILE:
        raise HTTPException(status_code=413, detail="Fichier trop lourd (10 Mo maximum).")
    ctype = (file.content_type or "application/octet-stream").split(";")[0].strip().lower()
    if ctype not in FILE_TYPES:
        raise HTTPException(status_code=415, detail="Format non accepté (images, PDF, Word, Excel, CSV, texte, ZIP, vidéo).")
    name = re.sub(r"[\\/\r\n\"]+", "_", (file.filename or "fichier").strip())[:120] or "fichier"
    fid = _id()
    # Files picked but never sent are cleaned after a day.
    _db.support_files.delete_many({"message_id": None, "created_at": {"$lt": _now() - timedelta(days=1)}})
    _db.support_files.insert_one({"id": fid, "name": name, "content_type": ctype, "size": len(data), "data": Binary(data),
                                  "uploaded_by": uploader, "tenant_id": tenant_id, "ticket_id": None, "message_id": None,
                                  "team_only": False, "created_at": _now()})
    return {"id": fid, "name": name, "size": len(data), "type": ctype}


@router.post("/api/admin/support/files")
async def team_upload(file: UploadFile = File(...), token_data: TokenData = Depends(require_admin("support", write=True))):
    return await _store(file, token_data.email, None)


@router.post("/api/owner/support/files")
async def merchant_upload(file: UploadFile = File(...), token_data: TokenData = Depends(require_role(MERCHANT))):
    return await _store(file, token_data.email, token_data.tenant_id)


@router.get("/api/support/files/{fid}")
def download(fid: str, inline: int = 0, token_data: TokenData = Depends(get_current_user_data)):
    f = _db.support_files.find_one({"id": fid}, {"_id": 0})
    if not f:
        raise HTTPException(status_code=404, detail="Fichier introuvable.")
    allowed = False
    if token_data.role in TEAM_ROLES:
        from features import platform_access as PA
        perms = PA.perms_for(token_data.email) or {}
        allowed = token_data.role == "super_admin" or bool((perms.get("support") or {}).get("view"))
    elif token_data.role in MERCHANT:
        mine = f.get("uploaded_by") == token_data.email and not f.get("message_id")
        t = _db.support_tickets.find_one({"id": f.get("ticket_id")}, {"_id": 0, "tenant_id": 1}) if f.get("ticket_id") else None
        allowed = mine or bool(t and t.get("tenant_id") == token_data.tenant_id and not f.get("team_only"))
    if not allowed:
        raise HTTPException(status_code=404, detail="Fichier introuvable.")
    disp = "inline" if inline and f["content_type"].startswith("image/") else "attachment"
    return Response(content=bytes(f["data"]), media_type=f["content_type"],
                    headers={"Content-Disposition": f'{disp}; filename="{f["name"]}"', "Cache-Control": "private, max-age=3600"})


# ---------------------------------------------------------------------------
# The merchant's side (« Besoin d'aide ? » › « Mes demandes »)
# ---------------------------------------------------------------------------
def _mine(tid: str, token_data: TokenData) -> Dict[str, Any]:
    t = _db.support_tickets.find_one({"id": tid, "tenant_id": token_data.tenant_id}, {"_id": 0})
    if not t or not token_data.tenant_id:
        raise HTTPException(status_code=404, detail="Demande introuvable.")
    return t


def _merchant_row(t: Dict[str, Any]) -> Dict[str, Any]:
    status = t.get("status")
    return {"id": t["id"], "subject": t.get("subject") or "", "preview": t.get("last_message_preview") or "",
            "status": "en_cours" if status == "urgent" else status,        # « urgent » is the team's own triage
            "status_label": {"nouveau": "Envoyée", "en_cours": "En cours", "urgent": "En cours", "en_attente": "Réponse reçue",
                             "resolu": "Résolue"}.get(status, "—"),
            "category_label": CATEGORY_LABEL.get(t.get("category"), "Autre"), "unread": int(t.get("unread_merchant") or 0),
            "last_message_at": _iso(t.get("last_message_at")), "created_at": _iso(t.get("created_at")),
            "rating": (t.get("rating") or {}).get("stars"), "can_rate": status == "resolu" and not t.get("rating")}


@router.get("/api/owner/support/tickets")
def my_tickets(token_data: TokenData = Depends(require_role(MERCHANT))):
    rows = list(_db.support_tickets.find({"tenant_id": token_data.tenant_id}, {"_id": 0}).sort("last_message_at", -1).limit(100)) if token_data.tenant_id else []
    return {"rows": [_merchant_row(t) for t in rows], "categories": [{"key": k, "label": v} for k, v in CATEGORIES]}


@router.get("/api/owner/support/tickets/{tid}")
def my_ticket(tid: str, token_data: TokenData = Depends(require_role(MERCHANT))):
    t = _mine(tid, token_data)
    now = _now()
    _db.support_tickets.update_one({"id": tid}, {"$set": {"unread_merchant": 0, "merchant_read_at": now}})
    _db.support_alerts.update_many({"ticket_id": tid, "audience": "merchant"}, {"$addToSet": {"read_by": token_data.email}})
    msgs = list(_db.support_messages.find({"ticket_id": tid, "kind": "message"}, {"_id": 0}).sort("created_at", 1))
    return {"ticket": {**_merchant_row({**t, "unread_merchant": 0}), "rating": t.get("rating") and {"stars": t["rating"].get("stars"), "comment": t["rating"].get("comment")}},
            "messages": [_message_view(m, None, for_merchant=True) for m in msgs]}


class MerchantTicketIn(BaseModel):
    subject: str = Field(..., max_length=200)
    body: str = Field(..., max_length=10000)
    category: str = "autre"
    attachments: List[str] = []


@router.post("/api/owner/support/tickets")
def my_new_ticket(body: MerchantTicketIn, token_data: TokenData = Depends(require_role(MERCHANT))):
    if not token_data.tenant_id:
        raise HTTPException(status_code=400, detail="Aucun commerce associé à ce compte.")
    u = _db.users.find_one({"email": token_data.email}, {"_id": 0, "first_name": 1, "last_name": 1, "email": 1}) or {"email": token_data.email}
    t = new_ticket(tenant_id=token_data.tenant_id, subject=body.subject, body=body.body, author_type="merchant", author_email=token_data.email,
                   author_name=_person(u), category=body.category, source="plateforme", from_email=token_data.email, from_name=_person(u),
                   attachments=body.attachments)
    return {"ok": True, "id": t["id"]}


class MerchantMessageIn(BaseModel):
    body: str = Field("", max_length=10000)
    attachments: List[str] = []


@router.post("/api/owner/support/tickets/{tid}/messages")
def my_message(tid: str, body: MerchantMessageIn, token_data: TokenData = Depends(require_role(MERCHANT))):
    t = _mine(tid, token_data)
    text = (body.body or "").strip()
    if not text and not body.attachments:
        raise HTTPException(status_code=400, detail="Écrivez un message ou ajoutez une pièce jointe.")
    u = _db.users.find_one({"email": token_data.email}, {"_id": 0, "first_name": 1, "last_name": 1, "email": 1}) or {"email": token_data.email}
    mid, now = _id(), _now()
    files = _take_files(body.attachments, tid, mid, token_data.email)
    _db.support_messages.insert_one({"id": mid, "ticket_id": tid, "tenant_id": t.get("tenant_id"), "kind": "message", "author_type": "merchant",
                                     "author_email": token_data.email, "author_name": _person(u), "body": text, "attachments": files, "created_at": now})
    sets: Dict[str, Any] = {"last_message_at": now, "last_message_preview": (text or f"📎 {files[0]['name']}")[:160], "last_from": "merchant",
                            "unread_team": int(t.get("unread_team") or 0) + 1, "unread_merchant": 0, "merchant_read_at": now, "updated_at": now}
    if t.get("status") in ("en_attente", "resolu"):
        sets.update(_set_status(t, "en_cours", token_data.email))
        if t.get("status") == "resolu":
            sets["rating"] = None                           # a reopened ticket is rated again once resolved
    _db.support_tickets.update_one({"id": tid}, {"$set": sets})
    _repin(tid)
    _alert("new", f"Nouveau message — {t.get('tenant_name') or token_data.email} : {t.get('subject')}", t,
           to=t.get("assigned_to"))
    return {"ok": True, "id": mid}


class RatingIn(BaseModel):
    stars: int = Field(..., ge=1, le=5)
    comment: str = Field("", max_length=1000)


@router.post("/api/owner/support/tickets/{tid}/rating")
def rate(tid: str, body: RatingIn, token_data: TokenData = Depends(require_role(MERCHANT))):
    t = _mine(tid, token_data)
    if t.get("status") != "resolu":
        raise HTTPException(status_code=400, detail="Vous pourrez noter cette demande une fois résolue.")
    _db.support_tickets.update_one({"id": tid}, {"$set": {"rating": {"stars": body.stars, "comment": body.comment.strip(), "by": token_data.email, "at": _now()}}})
    _event(t, token_data.email, f"Note du commerçant : {body.stars}/5" + (f" — « {body.comment.strip()} »" if body.comment.strip() else ""),
           {"field": "rating", "to": body.stars})
    return {"ok": True}


@router.get("/api/owner/support/alerts")
def merchant_alerts(token_data: TokenData = Depends(require_role(MERCHANT))):
    if not token_data.tenant_id:
        return {"alerts": []}
    rows = list(_db.support_alerts.find({"audience": "merchant", "tenant_id": token_data.tenant_id, "read_by": {"$ne": token_data.email},
                                         "at": {"$gte": _now() - timedelta(days=30)}}, {"_id": 0}).sort("at", -1).limit(20))
    return {"alerts": [{"id": f"sup-{a['id']}", "severity": "info", "title": a["text"], "body": "Support FidClic",
                        "created_at": _iso(a["at"]), "action": {"label": "Voir la demande", "href": f"/dashboard/aide?ticket={a['ticket_id']}"}}
                       for a in rows]}


@router.get("/api/owner/support/unread")
def merchant_unread(token_data: TokenData = Depends(require_role(MERCHANT))):
    if not token_data.tenant_id:
        return {"unread": 0}
    return {"unread": _db.support_tickets.count_documents({"tenant_id": token_data.tenant_id, "unread_merchant": {"$gt": 0}})}
