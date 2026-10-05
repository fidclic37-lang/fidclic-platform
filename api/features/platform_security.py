"""
Super admin › Sécurité — connexions, journal d'activité, paramètres, and the
figures of the page. Only FidClic's own team is concerned (super admin,
fidclic_team, commercial); businesses have their own Sécurité page.

LOGINS (decided with the user)
    - every login of a team member is recorded in platform_logins, with the
      country and city Vercel gives (x-vercel-ip-* headers — nothing is sent
      to a third party) and the device;
    - N wrong passwords within the lock window block the account for M
      minutes (defaults 5 and 15);
    - a login from a country this person never used before is « suspecte »:
      it goes through, and the super admin gets an alert;
    - if the super admin lists allowed countries, a login from anywhere
      else is refused (« Bloquée »). When the country is unknown (no header,
      local development), nothing is blocked.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth import TokenData
from features.platform_access import TEAM_ROLES, require_admin, require_super, team_users, role_id_of, MODULES

router = APIRouter(tags=["admin"])
_db = None
SETTINGS_KEY = "platform_security"
DEFAULTS = {"max_failed": 5, "lock_minutes": 15, "alert_new_country": True, "allowed_countries": []}


def init(db):
    global _db
    _db = db
    try:
        db.platform_logins.create_index([("at", -1)])
        db.platform_logins.create_index([("email", 1), ("at", -1)])
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


def _iso(v: Any) -> Optional[str]:
    d = _aware(v)
    return d.isoformat() if d else None


def settings() -> Dict[str, Any]:
    v = (_db.platform_settings.find_one({"key": SETTINGS_KEY}, {"_id": 0}) or {}).get("value") or {}
    return {**DEFAULTS, **{k: v[k] for k in DEFAULTS if k in v}}


def _where(request: Optional[Request]) -> Dict[str, str]:
    from features.security_page import _device, _ip
    import urllib.parse
    h = request.headers if request is not None else {}
    ua = h.get("user-agent", "") if request is not None else ""
    return {"cc": (h.get("x-vercel-ip-country") or "").upper(), "city": urllib.parse.unquote(h.get("x-vercel-ip-city") or ""),
            "ip": _ip(request), "ua": ua[:300], **_device(ua)}


def _record(email: str, ok: bool, request: Optional[Request], reason: str = "", **extra) -> Dict[str, Any]:
    doc = {"id": uuid.uuid4().hex, "email": email, "at": _now(), "ok": ok, "reason": reason, **_where(request),
           "suspicious": False, "blocked": False, **extra}
    _db.platform_logins.insert_one(doc)
    return doc


def is_team(user: Optional[Dict[str, Any]]) -> bool:
    return bool(user) and user.get("role") in TEAM_ROLES


# ---------------------------------------------------------------------------
# Hooks called by server.login / server.finish_login
# ---------------------------------------------------------------------------
def before_password(user: Dict[str, Any], request: Optional[Request]) -> None:
    """Refuse at once while the account is blocked."""
    if not is_team(user):
        return
    until = _aware(user.get("locked_until"))
    if until and until > _now():
        _record(user["email"], False, request, "locked", blocked=True)
        mins = max(1, int((until - _now()).total_seconds() // 60) + 1)
        raise HTTPException(status_code=429, detail=f"Trop de tentatives : compte bloqué encore {mins} min.")


def on_bad_password(user: Dict[str, Any], request: Optional[Request]) -> None:
    if not is_team(user):
        return
    s = settings()
    _record(user["email"], False, request, "bad_password")
    since = _now() - timedelta(minutes=int(s["lock_minutes"]))
    last_ok = _db.platform_logins.find_one({"email": user["email"], "ok": True}, {"at": 1}, sort=[("at", -1)])
    if last_ok and _aware(last_ok["at"]) > since:
        since = _aware(last_ok["at"])
    fails = _db.platform_logins.count_documents({"email": user["email"], "ok": False, "reason": "bad_password", "at": {"$gt": since}})
    if fails >= int(s["max_failed"]):
        until = _now() + timedelta(minutes=int(s["lock_minutes"]))
        _db.users.update_one({"email": user["email"]}, {"$set": {"locked_until": until}})
        _alert("locked", user["email"], f"Compte bloqué {s['lock_minutes']} min après {fails} mots de passe erronés.", request)
        import server as core
        core.log_audit("security.account_locked", actor=user["email"], actor_type="user", request=request,
                       meta={"failed": fails, "minutes": s["lock_minutes"]})


def check_country(user: Dict[str, Any], request: Optional[Request]) -> None:
    """Allowed countries — before any session or 2FA code is given."""
    if not is_team(user):
        return
    s = settings()
    w = _where(request)
    if w["cc"] and s["allowed_countries"] and w["cc"] not in s["allowed_countries"]:
        import server as core
        _record(user["email"], False, request, "country", blocked=True, suspicious=True)
        _alert("blocked", user["email"], f"Connexion refusée depuis {_country(w['cc'])} (pays non autorisé).", request)
        core.log_audit("security.login_blocked", actor=user["email"], actor_type="user", request=request,
                       meta={"country": w["cc"], "city": w["city"]})
        raise HTTPException(status_code=403, detail="Connexion refusée depuis ce pays.")


def record_success(user: Dict[str, Any], request: Optional[Request], method: str = "password") -> None:
    """The login went through (after the 2FA code when there is one). A
    country this person never used before makes it « suspecte »."""
    if not is_team(user):
        return
    s = settings()
    w = _where(request)
    seen = set(_db.platform_logins.distinct("cc", {"email": user["email"], "ok": True, "cc": {"$ne": ""}}))
    new = bool(w["cc"] and seen and w["cc"] not in seen)
    _record(user["email"], True, request, method, suspicious=new)
    _db.users.update_one({"email": user["email"]}, {"$unset": {"locked_until": ""}})
    if new:
        import server as core
        if s["alert_new_country"]:
            _alert("suspicious", user["email"], f"Connexion depuis un nouveau pays : {_country(w['cc'])}{' (' + w['city'] + ')' if w['city'] else ''}.", request)
        core.log_audit("security.login_suspicious", actor=user["email"], actor_type="user", request=request,
                       meta={"country": w["cc"], "city": w["city"]})


def _alert(kind: str, email: str, text: str, request: Optional[Request]) -> None:
    _db.platform_alerts.insert_one({"id": uuid.uuid4().hex, "kind": kind, "email": email, "text": text, "at": _now(),
                                    "ip": _where(request)["ip"], "read_by": []})


COUNTRY_FR = {"FR": "France", "DZ": "Algérie", "MA": "Maroc", "TN": "Tunisie", "BE": "Belgique", "CH": "Suisse", "LU": "Luxembourg",
              "DE": "Allemagne", "ES": "Espagne", "IT": "Italie", "GB": "Royaume-Uni", "US": "États-Unis", "IN": "Inde", "TR": "Turquie",
              "PT": "Portugal", "NL": "Pays-Bas", "CA": "Canada", "SN": "Sénégal", "CI": "Côte d'Ivoire", "AE": "Émirats arabes unis",
              "SA": "Arabie saoudite", "QA": "Qatar", "EG": "Égypte", "RU": "Russie", "CN": "Chine", "BR": "Brésil", "PL": "Pologne",
              "RO": "Roumanie", "IE": "Irlande", "AT": "Autriche"}


def _country(cc: str) -> str:
    return COUNTRY_FR.get(cc, cc or "Inconnu")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class SettingsIn(BaseModel):
    max_failed: int = Field(5, ge=2, le=20)
    lock_minutes: int = Field(15, ge=1, le=1440)
    alert_new_country: bool = True
    allowed_countries: List[str] = []


@router.get("/api/admin/security/settings")
def get_settings(request: Request, token_data: TokenData = Depends(require_admin("securite"))):
    return {**settings(), "current_country": _where(request)["cc"]}


@router.put("/api/admin/security/settings")
def put_settings(body: SettingsIn, request: Request, token_data: TokenData = Depends(require_super())):
    codes = sorted({c.strip().upper() for c in body.allowed_countries if re.fullmatch(r"[A-Za-z]{2}", c.strip())})
    here = _where(request)["cc"]
    if codes and here and here not in codes:
        raise HTTPException(status_code=400, detail=f"Ajoutez votre pays actuel ({_country(here)}) : sinon vous ne pourriez plus vous connecter.")
    value = {**body.dict(), "allowed_countries": codes}
    _db.platform_settings.update_one({"key": SETTINGS_KEY}, {"$set": {"key": SETTINGS_KEY, "value": value, "updated_at": _now(),
                                                                      "updated_by": token_data.email}}, upsert=True)
    import server as core
    core.log_audit("security.settings_update", actor=token_data.email, actor_type="user", request=request, meta=value)
    return settings()


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------
def _period(date_from: Optional[str], date_to: Optional[str]):
    end = (_aware(date_to) + timedelta(days=1)) if _aware(date_to) else _now()
    start = _aware(date_from) or end - timedelta(days=30)
    return (start, end) if start < end else (end - timedelta(days=30), end)


def _delta(cur: float, prev: float) -> Optional[int]:
    return round((cur - prev) / prev * 100) if prev else None


ACTION_KIND = [  # (prefix, category, verb)
    ("admin.plan", "Plans & abonnements", "Modification"), ("admin.franchise", "Plans & abonnements", "Modification"),
    ("admin.upgrade", "Plans & abonnements", "Modification"),
    ("admin.commerce_create", "Commerces", "Création"), ("admin.commerce_suspend", "Commerces", "Modification"),
    ("admin.commerce_reactivate", "Commerces", "Modification"), ("admin.commerce", "Commerces", "Modification"),
    ("admin.act_as.write", "Commerces", "Modification"),
    ("admin.view_as", "Commerces", "Consultation"),
    ("platform.user_create", "Utilisateurs", "Création"), ("platform.user", "Utilisateurs", "Modification"),
    ("platform.role_create", "Utilisateurs", "Création"), ("platform.role_delete", "Utilisateurs", "Suppression"),
    ("platform.role", "Utilisateurs", "Modification"),
    ("security.settings", "Paramètres", "Modification"), ("security.login_suspicious", "Sécurité", "Connexion suspecte"),
    ("security.login_blocked", "Sécurité", "Connexion bloquée"), ("security.account_locked", "Sécurité", "Compte bloqué"),
    ("security", "Sécurité", "Modification"), ("platform.request", None, None),
]
LABELS = {
    "admin.plan_update": "Mise à jour des limites d'un plan", "admin.plan_change": "Changement de plan",
    "admin.franchise_terms": "Conditions Franchise fixées", "admin.commerce_create": "Ajout d'un nouveau commerce",
    "admin.commerce_edit": "Modification d'un commerce", "admin.commerce_suspend": "Suspension d'un commerce",
    "admin.commerce_reactivate": "Réactivation d'un commerce", "admin.view_as": "Accès au compte",
    "admin.act_as.write": "Modification depuis l'accès au compte",
    "platform.user_create": "Ajout d'un utilisateur", "platform.user_update": "Modification d'un utilisateur",
    "platform.user_password_reset": "Mot de passe réinitialisé", "platform.user_unlock": "Compte débloqué",
    "platform.role_create": "Création d'un rôle", "platform.role_update": "Permissions d'un rôle modifiées",
    "platform.role_delete": "Suppression d'un rôle", "security.settings_update": "Paramètres de sécurité modifiés",
    "security.login_suspicious": "Connexion depuis un nouveau pays", "security.login_blocked": "Connexion depuis un pays non autorisé",
    "security.account_locked": "Trop de mots de passe erronés",
}
METHOD_VERB = {"POST": "Création", "PUT": "Modification", "PATCH": "Modification", "DELETE": "Suppression"}
PATH_MODULE = [("/api/crm", "CRM de prospection"), ("/api/admin/commerces", "Commerces"), ("/api/admin/tenants", "Commerces"),
               ("/api/admin/plans", "Plans & abonnements"), ("/api/admin/invoicing", "Plans & abonnements"),
               ("/api/admin/broadcast", "Notifications"), ("/api/admin/card-template", "Commerces"),
               ("/api/admin/send-business-campaign", "Campagnes"), ("/api/admin/ai", "FIDCLIC AI"), ("/api/admin/security", "Sécurité")]


def _kind(a: Dict[str, Any]) -> Dict[str, str]:
    act = a.get("action") or ""
    if act == "platform.request":
        m = a.get("meta") or {}
        path = m.get("path") or ""
        cat = next((c for p, c in PATH_MODULE if path.startswith(p)), "Autres")
        return {"category": cat, "verb": METHOD_VERB.get(m.get("method"), "Modification"),
                "label": f"{METHOD_VERB.get(m.get('method'), 'Action')} — {cat}"}
    for p, cat, verb in ACTION_KIND:
        if act.startswith(p) and cat:
            return {"category": cat, "verb": verb, "label": LABELS.get(act, act)}
    return {"category": "Autres", "verb": "Action", "label": LABELS.get(act, act)}


def _status(a: Dict[str, Any]) -> str:
    act = a.get("action") or ""
    if act in ("security.login_blocked", "security.account_locked"):
        return "Bloqué"
    code = (a.get("meta") or {}).get("status")
    if isinstance(code, int) and code >= 400:
        return "Refusé"
    return "Succès"


def _details(a: Dict[str, Any], names: Dict[str, str]) -> Dict[str, str]:
    m = a.get("meta") or {}
    act = a.get("action") or ""
    tgt = a.get("target") or ""
    target = names.get(tgt, tgt)
    if act == "admin.plan_change":
        import models
        detail = f"Plan {models.PLAN_LABELS.get(m.get('from'), m.get('from'))} → {models.PLAN_LABELS.get(m.get('to'), m.get('to'))}"
    elif act == "platform.role_update" and m.get("modules"):
        detail = "Modules : " + ", ".join(dict(MODULES).get(k, k) for k in m["modules"])
    elif act in ("platform.user_create", "platform.user_update") and m.get("role"):
        detail = f"Rôle : {m['role']}"
    elif act.startswith("security.login") and m.get("country"):
        detail = f"{_country(m['country'])}{' — ' + m['city'] if m.get('city') else ''}"
    elif act == "platform.request":
        detail = f"{m.get('method')} {m.get('path')}"
        target = ""
    else:
        detail = ""
    return {"detail": detail, "target": target}


def _team_emails() -> List[str]:
    return [u["email"] for u in team_users()]


def _journal_query(emails: List[str], start: datetime, end: datetime, q: str = "", user: str = "", category: str = "",
                   status: str = "") -> List[Dict[str, Any]]:
    f: Dict[str, Any] = {"actor": {"$in": [user] if user else emails}, "ts": {"$gte": start, "$lt": end},
                         "action": {"$not": re.compile(r"^auth\.")}}
    rows = list(_db.audit_logs.find(f, {"_id": 0}).sort("ts", -1).limit(5000))
    names = {t["id"]: t.get("name") for t in _db.tenants.find({"id": {"$in": list({r.get("target") for r in rows if r.get("target")})}},
                                                             {"_id": 0, "id": 1, "name": 1})}
    people = {u["email"]: " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or u["email"] for u in team_users()}
    out = []
    for a in rows:
        k, d = _kind(a), _details(a, names)
        row = {"id": a.get("id"), "at": _iso(a.get("ts")), "email": a.get("actor"), "user": people.get(a.get("actor"), a.get("actor")),
               "category": k["category"], "verb": k["verb"], "label": k["label"], "detail": d["detail"], "target": d["target"],
               "ip": a.get("ip") or "", "status": _status(a)}
        if category and row["category"] != category:
            continue
        if status and row["status"] != status:
            continue
        if q and q.lower() not in " ".join(str(v) for v in row.values()).lower():
            continue
        out.append(row)
    return out


@router.get("/api/admin/security/overview")
def overview(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
             token_data: TokenData = Depends(require_admin("securite"))):
    if not isinstance(date_from, (str, type(None))):
        date_from = None
    if not isinstance(date_to, (str, type(None))):
        date_to = None
    start, end = _period(date_from, date_to)
    prev = start - (end - start)
    users = team_users()
    emails = [u["email"] for u in users]
    step = (end - start) / 8
    B = [(start + step * i, start + step * (i + 1)) for i in range(8)]

    def logins(a, b, **f):
        return _db.platform_logins.count_documents({"at": {"$gte": a, "$lt": b}, **f})

    def actions(a, b):
        return _db.audit_logs.count_documents({"actor": {"$in": emails}, "ts": {"$gte": a, "$lt": b}, "action": {"$not": re.compile(r"^auth\.")}})
    sus = {"$or": [{"suspicious": True}, {"blocked": True}]}
    failed = {"ok": False, "reason": {"$in": ["bad_password", "locked", "country"]}}
    created_before = lambda at: sum(1 for u in users if (_aware(u.get("created_at")) or at) < at)   # noqa: E731
    cards = [
        {"key": "users", "value": len(users), "delta": _delta(len(users), created_before(start)), "series": [created_before(b) for _, b in B]},
        {"key": "actions", "value": actions(start, end), "delta": _delta(actions(start, end), actions(prev, start)), "series": [actions(a, b) for a, b in B]},
        {"key": "logins", "value": logins(start, end, ok=True), "delta": _delta(logins(start, end, ok=True), logins(prev, start, ok=True)),
         "series": [logins(a, b, ok=True) for a, b in B]},
        {"key": "suspicious", "value": logins(start, end, **sus), "delta": _delta(logins(start, end, **sus), logins(prev, start, **sus)),
         "series": [logins(a, b, **sus) for a, b in B]},
        {"key": "failed", "value": logins(start, end, **failed), "delta": _delta(logins(start, end, **failed), logins(prev, start, **failed)),
         "series": [logins(a, b, **failed) for a, b in B]},
    ]
    j = _journal_query(emails, start, end)
    cat = defaultdict(int)
    for r in j:
        cat[r["category"]] += 1
    order = ["Plans & abonnements", "Commerces", "Utilisateurs", "Paramètres", "Sécurité", "CRM de prospection"]
    tot = sum(cat.values()) or 1
    split = [{"key": k, "label": k, "count": cat[k], "pct": round(cat[k] / tot * 100)} for k in order if cat.get(k)]
    others = sum(v for k, v in cat.items() if k not in order)
    if others:
        split.append({"key": "Autres", "label": "Autres", "count": others, "pct": round(others / tot * 100)})
    days = []
    d0 = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while d0 < end:
        d1 = d0 + timedelta(days=1)
        days.append({"day": d0.date().isoformat(), "logins": logins(d0, d1, ok=True), "suspicious": logins(d0, d1, **sus)})
        d0 = d1
    by_cc = defaultdict(int)
    for r in _db.platform_logins.find({"at": {"$gte": start, "$lt": end}, "ok": True}, {"cc": 1}):
        by_cc[r.get("cc") or "??"] += 1
    ranked = sorted(by_cc.items(), key=lambda kv: -kv[1])
    tot_cc = sum(by_cc.values()) or 1
    origins = [{"cc": cc, "label": _country(cc) if cc != "??" else "Inconnu", "count": n, "pct": round(n / tot_cc * 100)} for cc, n in ranked[:3]]
    if len(ranked) > 3:
        n = sum(v for _, v in ranked[3:])
        origins.append({"cc": "", "label": "Autres", "count": n, "pct": round(n / tot_cc * 100)})
    return {"period": {"from": start.date().isoformat(), "to": (end - timedelta(seconds=1)).date().isoformat()},
            "cards": cards, "actions_split": split, "actions_total": len(j), "logins_by_day": days[-62:], "origins": origins,
            "recent_logins": [_login_view(r) for r in _db.platform_logins.find({}, {"_id": 0}).sort("at", -1).limit(5)],
            "recent_journal": j[:5], "users": [u["email"] for u in users], "categories": order + ["Autres"]}


def _login_view(r: Dict[str, Any]) -> Dict[str, Any]:
    people = _people()
    status = "Bloquée" if r.get("blocked") else "Réussie" if r.get("ok") else "Échouée"
    return {"id": r.get("id"), "email": r.get("email"), "user": people.get(r.get("email"), r.get("email")), "at": _iso(r.get("at")),
            "status": status, "suspicious": bool(r.get("suspicious")), "reason": {"bad_password": "Mot de passe erroné",
            "locked": "Compte bloqué", "country": "Pays non autorisé"}.get(r.get("reason"), ""),
            "cc": r.get("cc") or "", "country": _country(r.get("cc") or "") if r.get("cc") else "Inconnu", "city": r.get("city") or "",
            "ip": r.get("ip") or "", "device": r.get("device") or "", "browser": r.get("browser") or "", "os": r.get("os") or ""}


_people_cache: Dict[str, Any] = {}


def _people() -> Dict[str, str]:
    return {u["email"]: " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or u["email"] for u in team_users()}


@router.get("/api/admin/security/logins")
def list_logins(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
                user: str = "", status: str = "", q: str = "", page: int = 1, per_page: int = 20,
                token_data: TokenData = Depends(require_admin("securite"))):
    if not isinstance(date_from, (str, type(None))):
        date_from = None
    if not isinstance(date_to, (str, type(None))):
        date_to = None
    start, end = _period(date_from, date_to)
    page, per_page = max(1, int(page)), max(1, min(100, int(per_page)))
    f: Dict[str, Any] = {"at": {"$gte": start, "$lt": end}}
    if user:
        f["email"] = user
    if status == "ok":
        f["ok"] = True
    elif status == "failed":
        f.update(ok=False, blocked=False)
    elif status == "blocked":
        f["blocked"] = True
    elif status == "suspicious":
        f["suspicious"] = True
    rows = [_login_view(r) for r in _db.platform_logins.find(f, {"_id": 0}).sort("at", -1).limit(5000)]
    if q:
        rows = [r for r in rows if q.lower() in f"{r['user']} {r['email']} {r['country']} {r['city']} {r['ip']}".lower()]
    total = len(rows)
    return {"rows": rows[(page - 1) * per_page: page * per_page], "total": total, "page": page, "pages": max(1, -(-total // per_page))}


@router.get("/api/admin/security/journal")
def journal(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
            user: str = "", category: str = "", status: str = "", q: str = "", page: int = 1, per_page: int = 20,
            token_data: TokenData = Depends(require_admin("securite"))):
    if not isinstance(date_from, (str, type(None))):
        date_from = None
    if not isinstance(date_to, (str, type(None))):
        date_to = None
    start, end = _period(date_from, date_to)
    page, per_page = max(1, int(page)), max(1, min(100, int(per_page)))
    rows = _journal_query(_team_emails(), start, end, q, user, category, status)
    total = len(rows)
    return {"rows": rows[(page - 1) * per_page: page * per_page], "total": total, "page": page, "pages": max(1, -(-total // per_page))}


@router.get("/api/admin/security/journal/export")
def journal_export(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
                   user: str = "", category: str = "", status: str = "", q: str = "",
                   token_data: TokenData = Depends(require_admin("securite"))):
    start, end = _period(date_from if isinstance(date_from, str) else None, date_to if isinstance(date_to, str) else None)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Date", "Utilisateur", "Email", "Action", "Détails", "Cible", "Catégorie", "Adresse IP", "Statut"])
    for r in _journal_query(_team_emails(), start, end, q, user, category, status):
        w.writerow([r["at"], r["user"], r["email"], r["label"], r["detail"], r["target"], r["category"], r["ip"], r["status"]])
    return Response(content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="journal-securite.csv"'})


@router.get("/api/admin/security/alerts")
def alerts(token_data: TokenData = Depends(require_super())):
    """For the super admin's bell: suspicious, blocked and locked logins of the
    last 30 days, in the bell's alert format."""
    rows = list(_db.platform_alerts.find({"at": {"$gte": _now() - timedelta(days=30)}}, {"_id": 0}).sort("at", -1).limit(30))
    people = _people()
    title = {"suspicious": "Connexion suspecte", "blocked": "Connexion bloquée", "locked": "Compte bloqué"}
    return {"alerts": [{"id": f"sec-{a['id']}", "severity": "critical" if a["kind"] in ("blocked", "locked") else "warning",
                        "title": f"{title.get(a['kind'], 'Sécurité')} — {people.get(a['email'], a['email'])}", "body": a["text"],
                        "created_at": _iso(a["at"]), "action": {"label": "Voir les connexions", "href": "/admin/securite/connexions"}}
                       for a in rows]}
