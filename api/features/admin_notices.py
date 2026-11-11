"""
Super admin › Notifications (user, 2026-11-11): FidClic's team writes to ONE
business, several, or all of them — « all » is a choice made on purpose,
never the default. The message lands in the bell of the business's own people
(owner, administrateur, manager) and, when asked, in its owner's mailbox.

Never to a business's customers: the team reaches them from the business's
own account (view-as), with that business's name and rules. The old
« broadcast » that pushed to every shop's customers is closed (server.py).

    GET    /api/admin/notices/targets   the open businesses to pick from
    GET    /api/admin/notices           the history          (Notifications « Voir »)
    POST   /api/admin/notices           send                 (« Modifier »)
    DELETE /api/admin/notices/{id}      withdraw from bells  (« Modifier »)
    GET    /api/owner/notices           a business's bell: what FidClic sent it

Who receives is fixed when it is sent: a business that joins later never gets
an older message. Every send and withdrawal goes to the journal.
"""
from __future__ import annotations

import html as _html
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from auth import TokenData, require_role
from features.platform_access import require_admin

router = APIRouter(tags=["admin"])
_db = None

MERCHANT = ["business_owner", "administrateur", "manager"]
LEVELS = {"info": "info", "important": "warning"}         # our word → the bell's severity
BELL_DAYS = 90
BELL_MAX = 30
TITLE_MAX, BODY_MAX = 120, 2000
OPEN = {"is_active": {"$ne": False}}
# a link stays inside FidClic's app: a path of ours, never a scheme or another host
_LINK = re.compile(r"^/(?:dashboard|admin|scan|aide)(?:[/?#][^\s<>\"'\\]*)?$")


def init(db):
    global _db
    _db = db
    try:
        db.platform_notices.create_index("id", unique=True)
        db.platform_notices.create_index([("tenant_ids", 1), ("created_at", -1)])
        db.platform_notices.create_index([("created_at", -1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if not isinstance(v, datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def _iso(v: Any) -> Optional[str]:
    v = _aware(v)
    return v.isoformat() if v else None


def _owners(tids: List[str]) -> Dict[str, str]:
    """{tenant: its owner's e-mail} — one read."""
    out: Dict[str, str] = {}
    for u in _db.users.find({"tenant_id": {"$in": tids}, "role": "business_owner", "active": {"$ne": False}},
                            {"_id": 0, "tenant_id": 1, "email": 1}):
        if u.get("email") and u["tenant_id"] not in out:
            out[u["tenant_id"]] = u["email"]
    return out


class NoticeIn(BaseModel):
    title: str = Field(..., max_length=TITLE_MAX + 40)
    body: str = Field(..., max_length=BODY_MAX + 40)
    tenant_ids: Optional[List[str]] = Field(None, max_length=5000)
    all: bool = False
    level: str = "info"
    email: bool = False
    link: Optional[str] = Field(None, max_length=300)

    @field_validator("title", "body")
    @classmethod
    def _trim(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("level")
    @classmethod
    def _level(cls, v: str) -> str:
        if v not in LEVELS:
            raise ValueError("Niveau inconnu.")
        return v

    @field_validator("link")
    @classmethod
    def _link(cls, v: Optional[str]) -> Optional[str]:
        v = (v or "").strip()
        if not v:
            return None
        if not _LINK.fullmatch(v):
            raise ValueError("Le lien doit être une page de FidClic (ex. /dashboard/aide).")
        return v


# ---------------------------------------------------------------------------
# the team
# ---------------------------------------------------------------------------
@router.get("/api/admin/notices/targets")
def targets(token_data: TokenData = Depends(require_admin("notifications"))):
    from features.admin_commerces import standing_of
    rows = list(_db.tenants.find(OPEN, {"_id": 0, "id": 1, "name": 1, "plan": 1, "city": 1, "branches": 1, "resiliated_at": 1,
                                        "subscription_status": 1, "suspended_at": 1, "trial_ends_at": 1, "sector": 1}))
    owners = _owners([t["id"] for t in rows])
    now = _now()
    out = [{"id": t["id"], "name": t.get("name") or "—", "plan": t.get("plan"), "city": t.get("city"), "sector": t.get("sector"),
            "status": standing_of(t, now),
            "stores": len([b for b in (t.get("branches") or []) if (b.get("status") or "open") != "closed"]) or 1,
            "has_email": t["id"] in owners} for t in rows]
    out.sort(key=lambda r: (r["name"] or "").lower())
    return {"businesses": out}


@router.get("/api/admin/notices")
def history(token_data: TokenData = Depends(require_admin("notifications"))):
    rows = list(_db.platform_notices.find({}, {"_id": 0}).sort("created_at", -1).limit(200))
    names = {t["id"]: t.get("name") or "—" for t in _db.tenants.find(
        {"id": {"$in": sorted({tid for n in rows for tid in (n.get("tenant_ids") or [])})}}, {"_id": 0, "id": 1, "name": 1})}
    out = []
    for n in rows:
        tids = n.get("tenant_ids") or []
        out.append({"id": n["id"], "title": n.get("title"), "body": n.get("body"), "level": n.get("level") or "info",
                    "link": n.get("link"), "all": bool(n.get("all")), "businesses": len(tids),
                    "to_names": [names.get(t, "—") for t in tids[:50]], "more": max(0, len(tids) - 50),
                    "email": bool(n.get("email")), "emailed": int(n.get("emailed") or 0),
                    "by": n.get("by"), "created_at": _iso(n.get("created_at")), "withdrawn_at": _iso(n.get("withdrawn_at"))})
    return {"notices": out}


def _email_html(n: Dict[str, Any], app: str) -> str:
    esc = lambda s: _html.escape(s or "").replace("\n", "<br>")          # noqa: E731
    link = f"{app}{n['link']}" if n.get("link") else f"{app}/dashboard"
    return ("<div style=\"font-family:Inter,Arial,sans-serif;max-width:560px;margin:0 auto;color:#0B1C3F\">"
            "<p style=\"font-size:12px;color:#2F6BFF;font-weight:700;letter-spacing:.06em;text-transform:uppercase\">FidClic</p>"
            f"<h2 style=\"font-size:18px;margin:4px 0 14px\">{esc(n['title'])}</h2>"
            f"<div style=\"background:#F4F7FC;border-radius:12px;padding:14px 16px;font-size:14px;line-height:1.55\">{esc(n['body'])}</div>"
            f"<p style=\"margin:18px 0\"><a href=\"{_html.escape(link)}\" style=\"background:#2F6BFF;color:#fff;padding:10px 18px;"
            "border-radius:10px;text-decoration:none;font-weight:600;font-size:14px\">Ouvrir FidClic</a></p></div>")


@router.post("/api/admin/notices")
def send(body: NoticeIn, request: Request, token_data: TokenData = Depends(require_admin("notifications"))):
    if not body.title or not body.body:
        raise HTTPException(status_code=400, detail="Le titre et le message sont obligatoires.")
    if len(body.title) > TITLE_MAX or len(body.body) > BODY_MAX:
        raise HTTPException(status_code=400, detail=f"Titre : {TITLE_MAX} caractères maximum, message : {BODY_MAX}.")
    if body.all:
        tids = [t["id"] for t in _db.tenants.find(OPEN, {"_id": 0, "id": 1})]
    else:
        want = list(dict.fromkeys(t for t in (body.tenant_ids or []) if isinstance(t, str) and t.strip()))
        if not want:
            raise HTTPException(status_code=400, detail="Choisissez au moins un commerce (ou « Tous les commerces »).")
        found = {t["id"] for t in _db.tenants.find({"id": {"$in": want}, **OPEN}, {"_id": 0, "id": 1})}
        missing = [t for t in want if t not in found]
        if missing:
            raise HTTPException(status_code=400, detail=f"Commerce introuvable ou supprimé : {missing[0][:40]}.")
        tids = want
    if not tids:
        raise HTTPException(status_code=400, detail="Aucun commerce ouvert à qui écrire.")
    n = {"id": uuid.uuid4().hex, "title": body.title, "body": body.body, "level": body.level, "link": body.link,
         "all": bool(body.all), "tenant_ids": tids, "email": bool(body.email), "emailed": 0,
         "by": token_data.email, "created_at": _now(), "withdrawn_at": None}
    if body.email:
        from features.support_center import _app_url
        from services import mailer
        owners = _owners(tids)
        html = _email_html(n, _app_url())
        msgs = [{"to": owners[t], "subject": f"[FidClic] {body.title}", "html": html,
                 "text": f"{body.title}\n\n{body.body}"} for t in tids if t in owners]
        try:
            res = mailer.send_batch(msgs, sender_name="FidClic") if msgs else []
        except Exception:                                    # noqa: BLE001 — the bell message stands anyway
            res = []
        n["emailed"] = sum(1 for r in res if r.get("sent"))
    _db.platform_notices.insert_one(dict(n))
    import server as core
    core.log_audit("platform.notice_send", actor=token_data.email, actor_type="user", target=n["id"], request=request,
                   meta={"title": body.title[:120], "businesses": len(tids), "all": bool(body.all), "email": bool(body.email),
                         "emailed": n["emailed"]})
    return {"id": n["id"], "businesses": len(tids), "emailed": n["emailed"]}


@router.delete("/api/admin/notices/{nid}")
def withdraw(nid: str, request: Request, token_data: TokenData = Depends(require_admin("notifications"))):
    n = _db.platform_notices.find_one({"id": nid}, {"_id": 0, "id": 1, "title": 1, "withdrawn_at": 1})
    if not n:
        raise HTTPException(status_code=404, detail="Message introuvable.")
    if not n.get("withdrawn_at"):
        _db.platform_notices.update_one({"id": nid}, {"$set": {"withdrawn_at": _now(), "withdrawn_by": token_data.email}})
        import server as core
        core.log_audit("platform.notice_withdraw", actor=token_data.email, actor_type="user", target=nid, request=request,
                       meta={"title": (n.get("title") or "")[:120]})
    return {"ok": True}


# ---------------------------------------------------------------------------
# the business
# ---------------------------------------------------------------------------
@router.get("/api/owner/notices")
def bell(token_data: TokenData = Depends(require_role(MERCHANT))):
    if not token_data.tenant_id:
        return {"alerts": []}
    rows = _db.platform_notices.find({"tenant_ids": token_data.tenant_id, "withdrawn_at": None,
                                      "created_at": {"$gte": _now() - timedelta(days=BELL_DAYS)}},
                                     {"_id": 0, "id": 1, "title": 1, "body": 1, "level": 1, "link": 1, "created_at": 1}
                                     ).sort("created_at", -1).limit(BELL_MAX)
    out = []
    for n in rows:
        a = {"id": f"fidclic-{n['id']}", "kind": "fidclic", "from": "FidClic", "severity": LEVELS.get(n.get("level"), "info"),
             "title": n.get("title"), "body": n.get("body"), "created_at": _iso(n.get("created_at"))}
        if n.get("link"):
            a["action"] = {"label": "Ouvrir", "href": n["link"]}
        out.append(a)
    return {"alerts": out}
