"""
FidClic Lab — one shop's history, anonymous, for the lab (user, 2026-10-29:
« Royal Trim Liberté ka data se seekhna — production pe nahi, read-only
export pe »; the shop agreed and a legal advisor approved; what is learned
may improve every barber's defaults).

    POST /api/admin/ai/lab/exports              {tenant_id} → {id, parts, counts}
    GET  /api/admin/ai/lab/exports/{id}/parts/{n}  one part of the file

Super Admin only. It READS the shop and writes nothing of it: only the
export's own row here (its codes key, one hour) and a line in the Journal
d'activité. The browser fetches the parts one by one (one Vercel answer is
capped at 4.5 MB) and saves them as one file; `assemble()` does the same.

WHAT LEAVES — by allow-list, field by field (never « everything but »):
    shop       activity, sector, card programme, « client actif » days,
               stores as codes
    customers  code, store code, signup date, source kind (« qr »,
               « employee »), age in years (from a full birthday only),
               genre, département (2 digits), paused / deleted / pass flags
    visits     client code, store code, time, amount, products (id, name,
               qty, price), paper / source flags
    campaigns  code, kind, template kind, status, dates, recipients and
               témoin as client codes; title and text without tags for a
               group send only (a message to one client may be about them)
    automation_log / push   client code, campaign / automation code, kind,
               status, sent / opened / clicked times, témoin flag
NEVER: names, phone, e-mail, address, city, GPS, birthday, notes, any staff
e-mail, barcode, free text written about a client.

Codes are an HMAC of the real id with a key drawn for THIS export and
deleted with it: inside one file a client is the same code everywhere; two
exports cannot be joined, and nobody can go back to the real id.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from features.platform_access import require_super
from models import TokenData

router = APIRouter(tags=["lab"])
_db = None

FORMAT = "fidclic-lab/1"
PART_ROWS = 3000                 # rows per part: ~1 MB of JSON, far under 4.5 MB
LIFETIME = timedelta(hours=1)    # the export (and its codes key) is gone after
# kind → (collection, its query on the shop, sort key)
KINDS: List[Tuple[str, str, str]] = [
    ("customers", "customers", "id"),
    ("visits", "visits", "id"),
    ("campaigns", "campaigns", "id"),
    ("automation_log", "automation_log", "id"),
    ("push", "push_notifications", "sent_at"),
]
GENDERS = {"homme", "femme", "autre", "h", "f", "m"}
_KIND_RE = re.compile(r"^[a-z_]{1,24}$")


def init(db):
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            p = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return p if p.tzinfo else p.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _iso(v: Any) -> Optional[str]:
    d = _aware(v)
    return d.isoformat() if d else None


# ---------------------------------------------------------------------------
# codes
# ---------------------------------------------------------------------------
def code(key: bytes, kind: str, real: Any) -> Optional[str]:
    """The export's code for a real id (None stays None)."""
    if real is None or real == "":
        return None
    mac = hmac.new(key, f"{kind}:{real}".encode(), hashlib.sha256).digest()
    return base64.b32encode(mac[:8]).decode().rstrip("=").lower()


def _kind(v: Any) -> Optional[str]:
    """A source / template / scenario as its kind only: « employee:Paul » → « employee »."""
    s = str(v or "").split(":")[0].strip().lower()
    return s if _KIND_RE.match(s) else None


def _text(v: Any, limit: int = 500) -> Optional[str]:
    if not isinstance(v, str):
        return None
    return re.sub(r"<[^<>]*>", "", v).replace("<", "").replace(">", "")[:limit]


def _age(c: Dict[str, Any], at: datetime) -> Optional[int]:
    """Age in years from a full birthday (YYYY-MM-DD); « 07-14 » says nothing."""
    for f in ("birth_date", "birthday"):
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(c.get(f) or ""))
        if m:
            y, mo, d = (int(x) for x in m.groups())
            try:
                return at.year - y - ((at.month, at.day) < (mo, d))
            except Exception:
                return None
    return None


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


# ---------------------------------------------------------------------------
# one row of each kind
# ---------------------------------------------------------------------------
def _customer(c: Dict[str, Any], key: bytes, at: datetime) -> Dict[str, Any]:
    postal = str(c.get("postal_code") or "")
    gender = str(c.get("gender") or "").strip().lower()
    return {
        "c": code(key, "c", c.get("id")), "store": code(key, "s", c.get("branch_id")),
        "created_at": _iso(c.get("created_at")),
        "source": _kind(c.get("acquisition_source") or c.get("source")),
        "age": _age(c, at), "gender": gender if gender in GENDERS else None,
        "postal": postal[:2] if re.match(r"^\d{5}$", postal) else None,
        "paused": bool(c.get("paused") or c.get("paused_at")), "deleted": bool(c.get("deleted_at")),
        "pass": bool(c.get("pass_issued")),
    }


def _visit(v: Dict[str, Any], key: bytes, at: datetime) -> Dict[str, Any]:
    items = []
    for it in v.get("items") or []:
        if isinstance(it, dict):
            items.append({"id": _text(str(it.get("item_id") or it.get("id") or ""), 60) or None,
                          "name": _text(it.get("name"), 80), "qty": int(_num(it.get("qty")) or 1),
                          "price": _num(it.get("price"))})
    return {"c": code(key, "c", v.get("customer_id")), "store": code(key, "s", v.get("branch_id")),
            "at": _iso(v.get("visit_time")), "amount": _num(v.get("amount_paid")), "items": items,
            "paper": bool(v.get("paper_stamps")), "source": _kind(v.get("source")),
            "programme": _kind(v.get("programme"))}


def _campaign(c: Dict[str, Any], key: bytes, at: datetime) -> Dict[str, Any]:
    return {"id": code(key, "k", c.get("id")), "kind": _kind(c.get("kind")), "template": _kind(c.get("template")),
            "status": _kind(c.get("status")), "created_at": _iso(c.get("created_at")),
            "sent_at": _iso(c.get("sent_at")), "starts_at": _iso(c.get("starts_at") or c.get("start_date")),
            "ends_at": _iso(c.get("ends_at") or c.get("end_date")),
            "recipients": [code(key, "c", x) for x in c.get("recipient_ids") or []],
            "holdout": [code(key, "c", x) for x in c.get("holdout_ids") or []],
            # the text of a group send only: a message to one client may be about them
            **({"title": _text(c.get("title") or c.get("name"), 120), "content": _text(c.get("content"))}
               if len(c.get("recipient_ids") or []) + len(c.get("holdout_ids") or []) >= 2
               else {"title": None, "content": None})}


def _log(r: Dict[str, Any], key: bytes, at: datetime) -> Dict[str, Any]:
    return {"c": code(key, "c", r.get("customer_id")), "automation": code(key, "a", r.get("automation_id")),
            "scenario": _kind(r.get("scenario")), "status": _kind(r.get("status")),
            "sent_at": _iso(r.get("sent_at")), "clicked_at": _iso(r.get("clicked_at"))}


def _push(p: Dict[str, Any], key: bytes, at: datetime) -> Dict[str, Any]:
    return {"c": code(key, "c", p.get("customer_id")), "campaign": code(key, "k", p.get("campaign_id")),
            "automation": code(key, "a", p.get("automation_id")), "kind": _kind(p.get("type")),
            "sent_at": _iso(p.get("sent_at")), "opened_at": _iso(p.get("opened_at")),
            "clicked_at": _iso(p.get("clicked_at")), "temoin": bool(p.get("temoin"))}


ROW = {"customers": _customer, "visits": _visit, "campaigns": _campaign, "automation_log": _log, "push": _push}


def _shop(tid: str, key: bytes) -> Dict[str, Any]:
    from services import activities as A
    t = _db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "programme": 1}) or {}
    try:
        from features import customer_rules as R
        rule = int(R.active_days(R.load(tid)))
    except Exception:
        rule = None
    stores = [{"id": code(key, "s", b.get("id")), "status": _kind(b.get("status"))}
              for b in t.get("branches") or [] if isinstance(b, dict) and b.get("id")]
    return {"activity": A.of(t)["key"], "sector": _kind(t.get("sector")), "programme": _kind(tpl.get("programme")),
            "rule_days": rule, "stores": stores}


# ---------------------------------------------------------------------------
# the export: a plan of parts, then each part on demand
# ---------------------------------------------------------------------------
class ExportIn(BaseModel):
    tenant_id: str


def _plan(counts: Dict[str, int]) -> List[Dict[str, Any]]:
    parts: List[Dict[str, Any]] = [{"kind": "shop", "skip": 0}]
    for kind, _coll, _sort in KINDS:
        for skip in range(0, counts[kind], PART_ROWS):
            parts.append({"kind": kind, "skip": skip})
    return parts


def _purge() -> None:
    _db.lab_exports.delete_many({"expires_at": {"$lt": _now()}})


@router.post("/api/admin/ai/lab/exports")
def start(body: ExportIn, request: Request, token_data: TokenData = Depends(require_super())):
    _purge()
    tid = body.tenant_id
    if not tid or not _db.tenants.find_one({"id": tid}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Commerce introuvable.")
    counts = {kind: _db[coll].count_documents({"tenant_id": tid}) for kind, coll, _s in KINDS}
    at = _now()
    doc = {"id": uuid.uuid4().hex, "tenant_id": tid, "by": token_data.email, "at": at,
           "expires_at": at + LIFETIME, "key": secrets.token_hex(32), "rows": PART_ROWS,
           "parts": _plan(counts), "counts": counts}
    _db.lab_exports.insert_one(doc)
    try:
        import server as core
        core.log_audit("lab.export", actor=token_data.email, actor_type="user", tenant_id=tid,
                       target=doc["id"], request=request, meta={"counts": counts})
    except Exception:
        pass
    return {"id": doc["id"], "parts": len(doc["parts"]), "counts": counts, "format": FORMAT,
            "expires_at": doc["expires_at"].isoformat()}


@router.get("/api/admin/ai/lab/exports/{eid}/parts/{n}")
def part(eid: str, n: int, token_data: TokenData = Depends(require_super())):
    _purge()
    doc = _db.lab_exports.find_one({"id": eid, "by": token_data.email}, {"_id": 0})
    if not doc or n < 0 or n >= len(doc["parts"]):
        raise HTTPException(status_code=404, detail="Export introuvable ou expiré.")
    key, tid, at = bytes.fromhex(doc["key"]), doc["tenant_id"], _aware(doc["at"])
    p = doc["parts"][n]
    out: Dict[str, Any] = {"format": FORMAT, "part": n, "of": len(doc["parts"]), "kind": p["kind"]}
    if p["kind"] == "shop":
        out.update({"shop": _shop(tid, key), "exported_at": at.isoformat(), "counts": doc["counts"]})
        return out
    coll, sort = next((c, s) for k, c, s in KINDS if k == p["kind"])
    rows = _db[coll].find({"tenant_id": tid}, {"_id": 0}).sort([(sort, 1), ("_id", 1)]).skip(p["skip"]).limit(int(doc["rows"]))
    out["rows"] = [ROW[p["kind"]](r, key, at) for r in rows]
    return out


def assemble(parts: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """The parts → one export file (the browser does the same in JS)."""
    data: Dict[str, Any] = {"format": FORMAT, "shop": None, "exported_at": None, "counts": None,
                            **{k: [] for k, _c, _s in KINDS}}
    for p in sorted(parts, key=lambda x: int(x.get("part") or 0)):
        if p.get("kind") == "shop":
            data.update({"shop": p.get("shop"), "exported_at": p.get("exported_at"), "counts": p.get("counts")})
        elif p.get("kind") in data:
            data[p["kind"]].extend(p.get("rows") or [])
    return data
