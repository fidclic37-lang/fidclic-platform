"""
Liens d'inscription par employé — « qui a amené ce client ? »
(user, 2026-10-16).

The owner writes an employee down in Paramètres › Lien d'inscription (a name,
optionally an e-mail and a phone). FidClic gives that employee a link and a QR
of their own, and every client who signs up through them is theirs — in the
Clients list, in Analyses, in the « Classement » on that page.

    /inscription/<compte>[/<établissement>]/e-marie

WHAT MAKES IT RELIABLE (the user's first worry: « ek employee k qr se signup
kiya and woh dusre employee k hisse mein dikha, ya dikha hi nhi »)
  • One field decides, everywhere: customers.acquisition_source = « agent:<id> ».
    There is no second copy to drift from it, and no name is stored on the
    client — rename the employee and every page says the new name at once.
  • The word in the link (« e-marie ») is unique in the account and is never a
    channel word (insta, wa…) nor an establishment's word, so a link can never
    be read as something else. Two employees called Marie get e-marie and
    e-marie-2.
  • An employee is never deleted, only archived: the link stops working, the
    clients they brought keep their name.
  • The establishment is the employee's own, from the record — not from the
    address. A client signed up through Marie of Palissy is a Palissy client
    even if the link was pasted without the store's word.

Mounts at /api/owner/signup-agents (permission « employee_links »: `view` sees
their own link and the whole leaderboard, `edit` writes the records and sends
the e-mails).
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import TokenData, require_role

router = APIRouter(tags=["signup-agents"])
_db = None

WORD_PREFIX = "e-"
NAME_MAX = 60
WORD_MAX = 48
ROLES = ["business_owner", "administrateur", "manager", "staff"]


def init(db) -> None:
    global _db
    _db = db
    try:
        from services import sources as SRC
        SRC.set_agent_names(name_of)
    except Exception as exc:                 # noqa: BLE001 — a label is not worth a crash
        print(f"signup_agents: sources not wired ({exc})")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except Exception:
            return None
    if not isinstance(v, datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# the word in the link
# ---------------------------------------------------------------------------
def slugify(raw: str) -> str:
    s = unicodedata.normalize("NFKD", raw or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return re.sub(r"-{2,}", "-", s)[:WORD_MAX - len(WORD_PREFIX)].strip("-")


def _taken(tid: str) -> set:
    """Everything a word may not be: a channel, an establishment, the words the
    signup page keeps for itself, and the employees already written down."""
    from services import sources as SRC
    out = set(SRC.CHANNEL_WORDS.values()) | set(SRC.CHANNEL_WORDS) | set(SRC.ALIASES)
    out |= {"preview", "inscription", "join", "p", "principal", "e"}
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "branches": 1}) or {}
    for b in t.get("branches") or []:
        if b.get("slug"):
            out.add(str(b["slug"]).lower())
    for a in _db.signup_agents.find({"tenant_id": tid}, {"_id": 0, "word": 1}):
        if a.get("word"):
            out.add(str(a["word"]).lower())
    return out


def word_for(tid: str, name: str) -> str:
    """« Marie Dupont » → « e-marie-dupont », « e-marie-dupont-2 » if taken.
    Archived employees keep their word, so a printed QR never changes hands."""
    base = slugify(name) or "employe"
    taken = _taken(tid)
    word = f"{WORD_PREFIX}{base}"
    n = 1
    while word in taken:
        n += 1
        word = f"{WORD_PREFIX}{base}-{n}"
    return word


def resolve_word(tid: str, word: Optional[str]) -> Optional[Dict[str, Any]]:
    """The employee a link's word belongs to — active ones only: an archived
    employee's link signs the client up with no employee at all, never someone
    else's."""
    if not word or not str(word).lower().startswith(WORD_PREFIX):
        return None
    return _db.signup_agents.find_one(
        {"tenant_id": tid, "word": str(word).strip().lower(), "archived_at": None}, {"_id": 0})


def source_key(agent: Dict[str, Any]) -> str:
    from services import sources as SRC
    return SRC.AGENT_PREFIX + str(agent["id"])


def name_of(agent_id: str) -> Optional[str]:
    """What services.sources calls to write « Marie Dupont » wherever the
    source is shown — archived employees included, so history stays readable."""
    if _db is None or not agent_id:
        return None
    a = _db.signup_agents.find_one({"id": str(agent_id)}, {"_id": 0, "name": 1})
    return (a or {}).get("name") or None


def agent_by_id(tid: str, aid: str) -> Optional[Dict[str, Any]]:
    return _db.signup_agents.find_one({"tenant_id": tid, "id": str(aid)}, {"_id": 0})


def brought_by(customer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """For the Clients list: who brought this client, and when."""
    from services import sources as SRC
    aid = SRC.agent_id(SRC.key_of(customer))
    if not aid:
        return None
    a = _db.signup_agents.find_one({"id": aid}, {"_id": 0, "id": 1, "name": 1, "archived_at": 1}) if _db else None
    if not a:
        return None
    at = _aware(customer.get("created_at"))
    return {"id": a["id"], "name": a.get("name") or SRC.AGENT_FALLBACK,
            "archived": bool(a.get("archived_at")), "at": at.isoformat() if at else None}


# ---------------------------------------------------------------------------
# the link
# ---------------------------------------------------------------------------
def link_of(tenant: Dict[str, Any], agent: Dict[str, Any], origin: str = "") -> str:
    """/inscription/<compte>[/<établissement>]/<mot> — the establishment's word
    only when the account has several open ones, as everywhere else."""
    base = (origin or "https://app.fidclic.com").rstrip("/")
    slug = tenant.get("slug") or ""
    open_stores = [b for b in (tenant.get("branches") or []) if b.get("id") and b.get("status") != "closed"]
    store_word = ""
    if len(open_stores) > 1:
        mine = next((b for b in open_stores if b.get("id") == agent.get("store_id")), None)
        store_word = f"/{mine['slug']}" if mine and mine.get("slug") else ""
    return f"{base}/inscription/{slug}{store_word}/{agent['word']}"


# ---------------------------------------------------------------------------
# the leaderboard
# ---------------------------------------------------------------------------
def _month_start(at: datetime) -> datetime:
    from zoneinfo import ZoneInfo
    paris = ZoneInfo("Europe/Paris")
    local = at.astimezone(paris)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def leaderboard(tid: str, at: Optional[datetime] = None, store: Optional[str] = None) -> List[Dict[str, Any]]:
    """One row per employee: the clients they brought this calendar month, in
    all, and what those clients have spent. Erased clients do not count.
    `store`: that establishment's employees only (multi-store)."""
    from services import sources as SRC
    at = at or _now()
    start = _month_start(at)
    rows: Dict[str, Dict[str, Any]] = {}
    for a in _db.signup_agents.find({"tenant_id": tid}, {"_id": 0}):
        if not _in_store(tid, a, store):
            continue
        rows[a["id"]] = {"agent_id": a["id"], "name": a.get("name") or SRC.AGENT_FALLBACK,
                         "word": a.get("word"), "store_id": a.get("store_id"),
                         "archived": bool(a.get("archived_at")), "month": 0, "total": 0, "revenue": 0.0}
    if not rows:
        return []
    for c in _db.customers.find({"tenant_id": tid, "deleted_at": None},
                                {"_id": 0, "acquisition_source": 1, "created_at": 1, "total_amount_paid": 1}):
        aid = SRC.agent_id(SRC.key_of(c))
        row = rows.get(aid or "")
        if not row:
            continue
        row["total"] += 1
        row["revenue"] += float(c.get("total_amount_paid") or 0)
        d = _aware(c.get("created_at"))
        if d and d >= start:
            row["month"] += 1
    out = sorted(rows.values(), key=lambda r: (-r["month"], -r["total"], -r["revenue"], r["name"].lower()))
    for i, r in enumerate(out):
        r["rank"] = i + 1
        r["revenue"] = round(r["revenue"], 2)
    return out


# ---------------------------------------------------------------------------
# who is asking
# ---------------------------------------------------------------------------
def _can_edit(token: TokenData) -> bool:
    if token.role == "business_owner":
        return True
    try:
        from features import role_perms as RP
        user = _db.users.find_one({"email": token.email}, {"_id": 0}) or {}
        per = RP.effective(user)
        if per is None:
            return True
        return any(v.get("employee_links") == "edit" for v in per.values())
    except Exception:
        return False


def _store_of(token: TokenData, request: Optional[Request]) -> Optional[str]:
    try:
        from features import store_scope as S
        sc = S.resolve(token, request)
        return sc.ids[0] if sc.ids and len(sc.ids) == 1 else None
    except Exception:
        return None


def _main_store(tid: str) -> Optional[str]:
    """The account's main establishment — None when it has only one (or none),
    where a link needs no establishment word at all."""
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "branches": 1}) or {}
    open_stores = [b for b in (t.get("branches") or []) if b.get("id") and b.get("status") != "closed"]
    if len(open_stores) < 2:
        return None
    main = next((b for b in open_stores if b.get("is_main")), open_stores[0])
    return main.get("id")


def _here(tid: str, token: TokenData, request: Optional[Request]) -> Optional[str]:
    """The establishment chosen in the menu — its employees only (user,
    2026-10-17: added in Liberté, they showed in Palissy and PL-Monstre too).
    None for a one-shop account: everyone."""
    return _store_of(token, request) or _main_store(tid)


def _in_store(tid: str, agent: Dict[str, Any], store: Optional[str]) -> bool:
    if not store:
        return True
    return (agent.get("store_id") or _main_store(tid)) == store


def _store_name(tid: str, store: Optional[str]) -> Optional[str]:
    if not store:
        return None
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "branches": 1}) or {}
    return next((b.get("name") for b in t.get("branches") or [] if b.get("id") == store), None)


def _agent_here(tid: str, token: TokenData, request: Optional[Request], aid: str) -> Optional[Dict[str, Any]]:
    """An employee of the establishment in the menu — another store's is not
    this page's to change."""
    a = agent_by_id(tid, aid)
    return a if a and _in_store(tid, a, _here(tid, token, request)) else None


def _mine(tid: str, email: str) -> Optional[str]:
    """The employee record of the account asking, matched on its e-mail — so a
    staff member with the permission sees their own link and no one else's."""
    if not email:
        return None
    a = _db.signup_agents.find_one({"tenant_id": tid, "email": str(email).strip().lower(),
                                    "archived_at": None}, {"_id": 0, "id": 1})
    return (a or {}).get("id")


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------
class AgentIn(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    store_id: Optional[str] = None


class AgentPatch(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    archived: Optional[bool] = None


class SendIn(BaseModel):
    agent_ids: List[str] = []


def _clean_name(raw: Optional[str]) -> str:
    name = re.sub(r"\s+", " ", str(raw or "")).strip()[:NAME_MAX]
    if not name:
        raise HTTPException(status_code=400, detail="Le nom de l'employé est obligatoire.")
    return name


def _clean_email(raw: Optional[str]) -> Optional[str]:
    e = str(raw or "").strip().lower()
    if not e:
        return None
    if not re.match(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", e):
        raise HTTPException(status_code=400, detail="Cette adresse e-mail n'est pas valide.")
    return e


def _origin(request: Optional[Request]) -> str:
    import os
    env = (os.getenv("PUBLIC_APP_URL") or "").strip().rstrip("/")
    if env:
        return env
    if request is not None:
        ref = request.headers.get("origin") or ""
        if ref.startswith("http"):
            return ref.rstrip("/")
    return "https://app.fidclic.com"


def _payload(tid: str, token: TokenData, request: Optional[Request]) -> Dict[str, Any]:
    t = _db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    origin = _origin(request)
    here = _here(tid, token, request)
    board = leaderboard(tid, store=here)
    agents = []
    for a in _db.signup_agents.find({"tenant_id": tid}, {"_id": 0}).sort("created_at", 1):
        if not _in_store(tid, a, here):
            continue
        agents.append({"id": a["id"], "name": a.get("name"), "email": a.get("email"), "phone": a.get("phone"),
                       "word": a.get("word"), "store_id": a.get("store_id"),
                       "archived": bool(a.get("archived_at")),
                       "link": link_of(t, a, origin),
                       "sent_at": (_aware(a.get("sent_at")) or "") and _aware(a.get("sent_at")).isoformat()})
    return {"agents": agents, "leaderboard": board, "can_edit": _can_edit(token),
            "mine": _mine(tid, token.email), "mail_ready": _mail_ready(),
            "shop": {"name": t.get("name") or "", "slug": t.get("slug") or ""},
            # where an employee added here works, its link and its clients' cards
            "store": {"id": here, "name": _store_name(tid, here)} if here else None}


def _mail_ready() -> bool:
    try:
        from services import mailer
        return bool(mailer.ready())
    except Exception:
        return False


@router.get("/api/owner/signup-agents")
def list_agents(request: Request = None, token_data: TokenData = Depends(require_role(ROLES))):
    return _payload(token_data.tenant_id, token_data, request)


@router.post("/api/owner/signup-agents")
def create_agent(body: AgentIn, request: Request = None, token_data: TokenData = Depends(require_role(ROLES))):
    if not _can_edit(token_data):
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas créer de lien employé.")
    tid = token_data.tenant_id
    name = _clean_name(body.name)
    email = _clean_email(body.email)
    if email and _db.signup_agents.find_one({"tenant_id": tid, "email": email, "archived_at": None}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="Un employé avec cette adresse e-mail existe déjà.")
    # An employee always belongs to an establishment when the account has
    # several: their link carries its word, and the signup files the client
    # there. Without one, the link would land on « Choisissez votre
    # établissement » — a dead end for a QR shown at the till.
    # the establishment chosen in the menu (the page sends no other); an
    # explicit store_id from the API wins
    store = body.store_id or _here(tid, token_data, request)
    doc = {"id": uuid.uuid4().hex[:12], "tenant_id": tid, "store_id": store, "name": name,
           "email": email, "phone": (str(body.phone or "").strip() or None),
           "word": word_for(tid, name), "archived_at": None, "sent_at": None,
           "created_at": _now(), "created_by": token_data.email}
    _db.signup_agents.insert_one(dict(doc))
    _log(tid, token_data.email, "signup_agent.created", doc["id"], {"name": name, "word": doc["word"]})
    return _payload(tid, token_data, request)


@router.put("/api/owner/signup-agents/{agent_id}")
def edit_agent(agent_id: str, body: AgentPatch, request: Request = None,
               token_data: TokenData = Depends(require_role(ROLES))):
    if not _can_edit(token_data):
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas modifier de lien employé.")
    tid = token_data.tenant_id
    a = _agent_here(tid, token_data, request, agent_id)
    if not a:
        raise HTTPException(status_code=404, detail="Employé introuvable.")
    sets: Dict[str, Any] = {}
    if body.name is not None:
        # the word never follows the name: a QR already printed must keep working
        sets["name"] = _clean_name(body.name)
    if body.email is not None:
        email = _clean_email(body.email)
        if email and _db.signup_agents.find_one({"tenant_id": tid, "email": email, "archived_at": None,
                                                 "id": {"$ne": a["id"]}}, {"_id": 1}):
            raise HTTPException(status_code=409, detail="Un employé avec cette adresse e-mail existe déjà.")
        sets["email"] = email
    if body.phone is not None:
        sets["phone"] = str(body.phone).strip() or None
    if body.archived is not None:
        sets["archived_at"] = _now() if body.archived else None
    if sets:
        _db.signup_agents.update_one({"id": a["id"]}, {"$set": sets})
        _log(tid, token_data.email, "signup_agent.edited", a["id"], {k: str(v)[:60] for k, v in sets.items()})
    return _payload(tid, token_data, request)


@router.delete("/api/owner/signup-agents/{agent_id}")
def archive_agent(agent_id: str, request: Request = None,
                  token_data: TokenData = Depends(require_role(ROLES))):
    """Archived, never erased: the link stops working and the clients this
    employee brought keep their name in the Clients list and in Analyses."""
    if not _can_edit(token_data):
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas supprimer de lien employé.")
    tid = token_data.tenant_id
    a = _agent_here(tid, token_data, request, agent_id)
    if not a:
        raise HTTPException(status_code=404, detail="Employé introuvable.")
    _db.signup_agents.update_one({"id": a["id"]}, {"$set": {"archived_at": _now()}})
    _log(tid, token_data.email, "signup_agent.archived", a["id"], {"name": a.get("name")})
    return _payload(tid, token_data, request)


@router.post("/api/owner/signup-agents/send")
def send_links(body: SendIn, request: Request = None, token_data: TokenData = Depends(require_role(ROLES))):
    """E-mail the chosen employees their own link and QR, with a line saying
    what it is for (user, 2026-10-16)."""
    if not _can_edit(token_data):
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas envoyer les liens employés.")
    tid = token_data.tenant_id
    t = _db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    origin = _origin(request)
    out = {"sent": 0, "no_email": [], "failed": []}
    wanted = [str(x) for x in (body.agent_ids or [])]
    if not wanted:
        raise HTTPException(status_code=400, detail="Choisissez au moins un employé.")
    for aid in wanted:
        a = _agent_here(tid, token_data, request, aid)
        if not a or a.get("archived_at"):
            out["failed"].append({"id": aid, "error": "Employé introuvable."})
            continue
        if not a.get("email"):
            out["no_email"].append({"id": aid, "name": a.get("name")})
            continue
        try:
            from services import mailer
            link = link_of(t, a, origin)
            mailer.send(to=a["email"], to_name=a.get("name"),
                        subject=f"Votre lien d'inscription — {t.get('name') or 'FidClic'}",
                        html=_email_html(t.get("name") or "", a.get("name") or "", link))
            _db.signup_agents.update_one({"id": a["id"]}, {"$set": {"sent_at": _now()}})
            out["sent"] += 1
        except Exception as exc:                 # noqa: BLE001 — one bad address never stops the rest
            out["failed"].append({"id": aid, "error": str(exc)[:120]})
    _log(tid, token_data.email, "signup_agent.sent", None, {"sent": out["sent"], "asked": len(wanted)})
    return {**out, **_payload(tid, token_data, request)}


def _email_html(shop: str, name: str, link: str) -> str:
    """What the employee receives: their link, their QR, and why it exists."""
    import urllib.parse
    qr = "https://api.qrserver.com/v1/create-qr-code/?size=320x320&data=" + urllib.parse.quote(link, safe="")
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    return f"""<div style="font-family:Inter,Arial,sans-serif;color:#0B1C3F;max-width:560px">
  <p>Bonjour {esc(name)},</p>
  <p><strong>{esc(shop)}</strong> vous a créé votre propre lien d'inscription au programme de fidélité.</p>
  <p>Chaque client qui s'inscrit avec <em>votre</em> lien ou <em>votre</em> QR code est compté comme
     amené par vous — vous apparaissez dans le classement de l'équipe. Montrez le QR code au client,
     ou envoyez-lui le lien.</p>
  <p style="margin:22px 0"><a href="{esc(link)}"
     style="background:#2F6BFF;color:#fff;padding:12px 20px;border-radius:10px;text-decoration:none;font-weight:600">
     Mon lien d'inscription</a></p>
  <p style="font-size:13px;color:#475569;word-break:break-all">{esc(link)}</p>
  <p><img src="{esc(qr)}" alt="QR code" width="200" height="200" style="border:8px solid #fff;border-radius:12px"></p>
  <p style="font-size:12.5px;color:#64748B">Ce lien est le vôtre : ne le partagez pas avec un autre employé,
     sinon ses inscriptions seront comptées pour vous.</p>
</div>"""


def _log(tid: str, actor: str, action: str, target: Optional[str], meta: Dict[str, Any]) -> None:
    try:
        import server as core
        core.log_audit(action, actor=actor, actor_type="user", tenant_id=tid, target=target, meta=meta)
    except Exception:
        pass
