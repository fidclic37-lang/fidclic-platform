"""
Le journal d'apprentissage (user, 2026-11-02): every text FidClic IA writes,
and what the owner did with it — the examples a smaller FidClic model will
one day learn from (fine-tuning, distillation).

    surfaces   campaign_ai (« Rédiger avec l'IA »), automation_ai, autopilot,
               template (Insights / Produits / Fiche prefills), copilot,
               support
    status     proposed → accepted (sent as written) · edited (the owner's
               words kept beside the IA's) · rejected (Autopilot « Passer »)
               · abandoned (never sent in 7 days) · expired (Autopilot)
    feedback   the Copilote's 👍 / 👎, a reason, a note
    outcome    the groupe témoin's answer for the campaign it became (15 days)
    label      good / bad / None — what the export trains on

The prompt (compressed) and the system prompt (once, by hash) are kept, so
each example is a whole input → output pair. Everything is scrubbed first:
the shop's clients' names → {prénom}, the shop's and its stores' names →
{commerce}, phones, e-mails and IBANs hidden. No owner e-mail, no client id.
Rows are training-ready from day one (the user's choice, 2026-11-02).

Writing NEVER breaks a page: any failure is swallowed.
"""
from __future__ import annotations

import base64
import difflib
import hashlib
import json
import re
import time
import unicodedata
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth import TokenData, require_role
from features.platform_access import require_admin

router = APIRouter(tags=["learning-log"])
_db = None
PARIS = ZoneInfo("Europe/Paris")

SURFACES = ("campaign_ai", "automation_ai", "autopilot", "template", "copilot", "support")
REASONS = {"faux_chiffre": "Chiffre faux", "pas_utile": "Pas utile", "pas_clair": "Pas clair", "autre": "Autre"}
SAME = 0.97                    # at or above: sent as written
ABANDON_AFTER = timedelta(days=7)
OUTCOME_AFTER = timedelta(days=16)
GOAL = 10000                   # good examples before a FidClic model is trained
INPUT_MAX = 60000
NAMES_TTL_S = 600
TEMPLATE_DAY_MAX = 200         # prefill rows a shop adds a day (pentest: a script opening every client's template)
_names: Dict[str, Any] = {}


def init(db):
    global _db
    _db = db
    try:
        db.ai_examples.create_index("id", unique=True)
        db.ai_examples.create_index([("tenant_id", 1), ("created_at", -1)])
        db.ai_examples.create_index([("status", 1), ("created_at", 1)])
        db.ai_examples.create_index([("campaign_id", 1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if not isinstance(v, datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# scrub
# ---------------------------------------------------------------------------
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,3})?\b")
# pentest 2026-11-02: addresses and birth dates went through
_ADDRESS = re.compile(r"\b\d{1,4}\s*(?:bis|ter)?\s*,?\s*(?:rue|avenue|av\.|bd|boulevard|chemin|all[ée]e|place|impasse|route|quai|cours|"
                      r"square|passage|r[ée]sidence|lotissement|lieu[- ]dit)\b[^,.;\n()]{0,60}", re.IGNORECASE)
_DATE = re.compile(r"\b(?:(\d{1,2})[/.-](\d{1,2})[/.-]((?:19|20)\d{2})|((?:19|20)\d{2})-(\d{2})-(\d{2}))\b")
_WORD = re.compile(r"(?<![{_\w])[^\W\d_]{2,}(?![}_\w])")
# short or everyday words never taken for a client's name (« Anne Le Goff » must not hide « le »)
_STOP = set("""le la les de du des un une et en au aux ce se sa son ses mon ma mes ton ta tes on ne pas par pour sur dans avec est il elle ils
elles nous vous je tu me te lui leur qui que ou oui non plus moins tout tous toute bien bon bonne jour semaine mois an ans fois
lundi mardi mercredi jeudi vendredi samedi dimanche janvier fevrier mars avril mai juin juillet aout septembre octobre novembre
decembre client clients cliente commerce boutique salon cafe offre carte visite merci bonjour bonsoir chez vos votre nos notre
ici si ni car mais donc or as am pm ok via vs mr mme mlle""".split())


def _fold(w: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", (w or "").lower()) if unicodedata.category(ch) != "Mn")


def _names_of(tid: str) -> set:
    """The shop's clients' name words, folded (no accent, lower case) — a set, so a
    text is scrubbed in one pass whatever the number of clients."""
    hit = _names.get(tid)
    if hit and time.time() - hit[0] < NAMES_TTL_S:
        return hit[1]
    words: set = set()
    for c in _db.customers.find({"tenant_id": tid}, {"_id": 0, "name": 1, "first_name": 1, "last_name": 1}):
        for full in (c.get("name"), c.get("first_name"), c.get("last_name")):
            for w in re.split(r"[\s\-'’]+", str(full or "")):
                f = _fold(w)
                if len(f) >= 2 and f.isalpha() and f not in _STOP:
                    words.add(f)
    _names[tid] = (time.time(), words)
    return words


def _date(m: re.Match) -> str:
    year = int(m.group(3) or m.group(4))
    return "[date]" if year <= datetime.now(timezone.utc).year - 12 else m.group(0)   # a birth date, not « jusqu'au 15/11/2026 »


def _shop_rx(tid: str) -> Optional[re.Pattern]:
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "name": 1, "branches": 1}) or {}
    names = [t.get("name")] + [b.get("name") for b in (t.get("branches") or [])]
    names = sorted({n.strip() for n in names if n and len(n.strip()) >= 3}, key=len, reverse=True)
    return re.compile("|".join(re.escape(n) for n in names), re.IGNORECASE) if names else None


def scrub(tid: Optional[str], text: Any) -> str:
    """The text with no client name, phone, e-mail, IBAN or shop name."""
    from features import copilot_memory as CM
    t = str(text or "")
    t = _IBAN.sub("[IBAN]", t)
    t = _DATE.sub(_date, t)
    t = CM.scrub(t)
    t = _ADDRESS.sub("[adresse]", t)
    if tid and _db is not None:
        shop = _shop_rx(tid)
        if shop:
            t = shop.sub("{commerce}", t)
        names = _names_of(tid)
        if names:
            t = _WORD.sub(lambda m: "{prénom}" if _fold(m.group(0)) in names else m.group(0), t)
            t = re.sub(r"\{prénom\}(?:\s+\{prénom\})+", "{prénom}", t)
    return t


def _scrub_out(tid: Optional[str], out: Dict[str, Any]) -> Dict[str, Any]:
    return {k: scrub(tid, v) if isinstance(v, str) else v for k, v in (out or {}).items()}


def pack(text: str) -> str:
    return base64.b64encode(zlib.compress((text or "")[:INPUT_MAX].encode(), 6)).decode()


def unpack(z: Optional[str]) -> str:
    try:
        return zlib.decompress(base64.b64decode(z or "")).decode()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------
def _activity(tid: Optional[str]) -> Optional[str]:
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "activity_key": 1, "sector": 1}) or {}
    return t.get("activity_key") or t.get("sector")


def _system_ref(tid: Optional[str], system: str) -> Optional[str]:
    if not system:
        return None
    s = scrub(tid, system)
    ref = hashlib.sha1(s.encode()).hexdigest()[:16]
    _db.ai_prompts.update_one({"_id": ref}, {"$setOnInsert": {"text": s, "at": _now()}}, upsert=True)
    return ref


def capture(tid: Optional[str], surface: str, output: Dict[str, Any], *, source_key: Optional[str] = None,
            call: Optional[Dict[str, Any]] = None, dedupe_day: bool = False, ex_id: Optional[str] = None) -> Optional[str]:
    """Keep one IA text. `call` is the model call that wrote it (services.llm.last_call());
    without one (a template) the input is the template's key. Returns the example's id."""
    if _db is None or surface not in SURFACES:
        return None
    try:
        now = _now()
        if dedupe_day:
            day = now.astimezone(PARIS).strftime("%Y-%m-%d")
            hit = _db.ai_examples.find_one({"tenant_id": tid, "surface": surface, "source_key": source_key, "day": day},
                                           {"_id": 0, "id": 1})
            if hit:
                return hit["id"]
            if surface == "template" and _db.ai_examples.count_documents(
                    {"tenant_id": tid, "surface": "template", "day": day}) >= TEMPLATE_DAY_MAX:
                return None
        call = call or {}
        doc = {"id": ex_id or uuid.uuid4().hex, "tenant_id": tid, "activity": _activity(tid), "surface": surface,
               "source_key": source_key, "day": now.astimezone(PARIS).strftime("%Y-%m-%d"), "created_at": now,
               "model": call.get("model"), "provider": call.get("provider"),
               "system_ref": _system_ref(tid, call.get("system") or ""),
               "input_z": pack(scrub(tid, call.get("user") or (f"modèle : {source_key}" if source_key else ""))),
               "output": _scrub_out(tid, output), "status": "proposed", "training_ok": True, "label": None}
        _db.ai_examples.insert_one(dict(doc))
        return doc["id"]
    except Exception as exc:                 # noqa: BLE001 — never breaks the page
        print(f"learning_log: capture failed ({exc})")
        return None


def capture_last(tid: Optional[str], surface: str, output: Dict[str, Any], **kw) -> Optional[str]:
    from services import llm
    return capture(tid, surface, output, call=llm.last_call(), **kw)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def similarity(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    x = " | ".join(_norm(str(a.get(k) or "")) for k in ("title", "message", "text"))
    y = " | ".join(_norm(str(b.get(k) or "")) for k in ("title", "message", "text"))
    return round(difflib.SequenceMatcher(None, x, y).ratio(), 3)


def _label(doc: Dict[str, Any]) -> Optional[str]:
    vote = (doc.get("feedback") or {}).get("vote")
    if vote == "up":
        return "good"
    if vote == "down" or doc.get("status") == "rejected":
        return "bad"
    o = doc.get("outcome") or {}
    if doc.get("status") in ("accepted", "edited"):
        if o.get("enough") and o.get("rate") is not None and o.get("temoin_rate") is not None and o["rate"] <= o["temoin_rate"]:
            return "bad"
        return "good"
    return None


def _save(ex_id: str, upd: Dict[str, Any]) -> None:
    doc = _db.ai_examples.find_one({"id": ex_id}, {"_id": 0}) or {}
    doc.update(upd)
    upd["label"] = _label(doc)
    _db.ai_examples.update_one({"id": ex_id}, {"$set": upd})


def settle(tid: Optional[str], ex_id: Optional[str], final: Dict[str, Any], *, campaign_id: Optional[str] = None,
           automation_id: Optional[str] = None, sent: bool = True) -> None:
    """What the owner did with it: sent (as written or edited); a draft only links it."""
    if not ex_id or _db is None:
        return
    try:
        doc = _db.ai_examples.find_one({"id": str(ex_id), "tenant_id": tid}, {"_id": 0})
        if not doc:
            return
        link = {k: v for k, v in (("campaign_id", campaign_id), ("automation_id", automation_id)) if v}
        if not sent:
            _db.ai_examples.update_one({"id": doc["id"]}, {"$set": link})
            return
        fin = _scrub_out(tid, final)
        sim = similarity(doc.get("output") or {}, fin)
        _save(doc["id"], {**link, "final": fin, "similarity": sim, "status": "accepted" if sim >= SAME else "edited",
                          "decided_at": _now()})
    except Exception as exc:                 # noqa: BLE001
        print(f"learning_log: settle failed ({exc})")


def mark(tid: Optional[str], ex_id: Optional[str], status: str) -> None:
    if not ex_id or _db is None:
        return
    try:
        if _db.ai_examples.find_one({"id": str(ex_id), "tenant_id": tid}, {"_id": 1}):
            _save(str(ex_id), {"status": status, "decided_at": _now()})
    except Exception as exc:                 # noqa: BLE001
        print(f"learning_log: mark failed ({exc})")


def owned(tid: Optional[str], ex_id: Optional[str]) -> Optional[str]:
    """The id when it is this shop's example — never another shop's."""
    if not ex_id or _db is None:
        return None
    return str(ex_id) if _db.ai_examples.find_one({"id": str(ex_id), "tenant_id": tid}, {"_id": 1}) else None


# ---------------------------------------------------------------------------
# the tick: outcomes, abandons
# ---------------------------------------------------------------------------
def due(now: Optional[datetime] = None, limit: int = 300) -> Dict[str, int]:
    now = now or _now()
    out = {"abandoned": 0, "measured": 0}
    r = _db.ai_examples.update_many({"status": "proposed", "created_at": {"$lt": now - ABANDON_AFTER},
                                     "surface": {"$in": ["campaign_ai", "automation_ai", "template"]}},
                                    {"$set": {"status": "abandoned", "decided_at": now}})
    out["abandoned"] = getattr(r, "modified_count", 0)
    from features import temoin as T
    rows = list(_db.ai_examples.find({"campaign_id": {"$ne": None}, "outcome": {"$exists": False},
                                      "status": {"$in": ["accepted", "edited"]}}, {"_id": 0}).limit(limit))
    for ex in rows:
        c = _db.campaigns.find_one({"id": ex["campaign_id"], "tenant_id": ex["tenant_id"]}, {"_id": 0})
        sent = _aware((c or {}).get("sent_at"))
        if not c or not sent or now - sent < OUTCOME_AFTER:
            continue
        try:
            b = T.campaign_block(ex["tenant_id"], c, now) or {}
        except Exception:
            b = {}
        if not b.get("ready"):
            continue
        _save(ex["id"], {"outcome": {"rate": b.get("rate"), "temoin_rate": b.get("temoin_rate"), "enough": bool(b.get("enough")),
                                     "extra_revenue": b.get("extra_revenue"), "measured_at": now}})
        out["measured"] += 1
    return out


# ---------------------------------------------------------------------------
# the owner's 👍 / 👎
# ---------------------------------------------------------------------------
class FeedbackIn(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    vote: str = Field(..., pattern="^(up|down)$")
    reason: Optional[str] = Field(None, pattern="^(faux_chiffre|pas_utile|pas_clair|autre)$")
    text: Optional[str] = Field(None, max_length=500)


@router.post("/api/owner/ai/feedback")
def feedback(body: FeedbackIn, token_data: TokenData = Depends(require_role(
        ["business_owner", "administrateur", "manager", "staff"], partial_ok=True))):
    tid = token_data.tenant_id
    if not owned(tid, body.id):
        raise HTTPException(status_code=404, detail="Réponse introuvable")
    fb = {"vote": body.vote, "reason": body.reason if body.vote == "down" else None,
          "text": scrub(tid, body.text) if body.text else None, "at": _now()}
    _save(body.id, {"feedback": fb})
    _db.copilot_chats.update_one({"tenant_id": tid, "id": body.id}, {"$set": {"vote": body.vote}})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Super admin › FIDCLIC AI › Apprentissage
# ---------------------------------------------------------------------------
def _public(ex: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": ex["id"], "surface": ex.get("surface"), "activity": ex.get("activity"), "status": ex.get("status"),
            "label": ex.get("label"), "similarity": ex.get("similarity"), "output": ex.get("output"), "final": ex.get("final"),
            "feedback": {k: v for k, v in (ex.get("feedback") or {}).items() if k != "at"} or None,
            "outcome": {k: v for k, v in (ex.get("outcome") or {}).items() if k != "measured_at"} or None,
            "created_at": ex.get("created_at")}


@router.get("/api/admin/ai/learning")
def page(token_data: TokenData = Depends(require_admin("ai"))):
    surf: Dict[str, Dict[str, Any]] = {}
    up = down = good = bad = 0
    reasons: Dict[str, int] = {}
    for ex in _db.ai_examples.find({}, {"_id": 0, "surface": 1, "status": 1, "label": 1, "similarity": 1, "feedback": 1, "outcome": 1}):
        s = surf.setdefault(ex.get("surface") or "autre", {"surface": ex.get("surface") or "autre", "total": 0, "proposed": 0,
                                                           "accepted": 0, "edited": 0, "rejected": 0, "abandoned": 0,
                                                           "expired": 0, "measured": 0, "_sim": []})
        s["total"] += 1
        if ex.get("status") in s:
            s[ex["status"]] += 1
        if ex.get("similarity") is not None and ex.get("status") == "edited":
            s["_sim"].append(ex["similarity"])
        s["measured"] += bool(ex.get("outcome"))
        v = (ex.get("feedback") or {}).get("vote")
        up += v == "up"
        down += v == "down"
        r = (ex.get("feedback") or {}).get("reason")
        if v == "down" and r:
            reasons[r] = reasons.get(r, 0) + 1
        good += ex.get("label") == "good"
        bad += ex.get("label") == "bad"
    rows = []
    for s in surf.values():
        sims = s.pop("_sim")
        decided = s["accepted"] + s["edited"] + s["rejected"] + s["abandoned"]
        s["kept_pct"] = round(100 * (s["accepted"] + s["edited"]) / decided) if decided else None
        s["edit_similarity"] = round(sum(sims) / len(sims), 2) if sims else None
        rows.append(s)
    rows.sort(key=lambda s: -s["total"])
    recent = [_public(x) for x in _db.ai_examples.find({}, {"_id": 0, "input_z": 0}).sort("created_at", -1).limit(20)]
    return {"surfaces": rows, "feedback": {"up": up, "down": down, "reasons": [{"key": k, "label": REASONS.get(k, k), "n": n}
                                                                               for k, n in sorted(reasons.items(), key=lambda kv: -kv[1])]},
            "good": good, "bad": bad, "goal": GOAL, "recent": recent}


def _jsonl(label: Optional[str]):
    q: Dict[str, Any] = {"training_ok": True}
    if label:
        q["label"] = label
    prompts: Dict[str, str] = {}
    for ex in _db.ai_examples.find(q, {"_id": 0}).sort("created_at", 1):
        ref = ex.get("system_ref")
        if ref and ref not in prompts:
            prompts[ref] = ((_db.ai_prompts.find_one({"_id": ref}) or {}).get("text") or "")
        out = ex.get("final") if ex.get("status") == "edited" and ex.get("final") else ex.get("output") or {}
        answer = out.get("text") or "\n".join(x for x in (out.get("title"), out.get("message")) if x)
        msgs = ([{"role": "system", "content": prompts.get(ref, "")}] if ref else []) + [
            {"role": "user", "content": unpack(ex.get("input_z"))}, {"role": "assistant", "content": answer}]
        yield json.dumps({"messages": msgs, "surface": ex.get("surface"), "activity": ex.get("activity"),
                          "label": ex.get("label"), "status": ex.get("status"),
                          "outcome": {k: v for k, v in (ex.get("outcome") or {}).items() if k != "measured_at"} or None},
                         ensure_ascii=False) + "\n"


@router.get("/api/admin/ai/learning/export.jsonl")
def export(label: Optional[str] = "good", token_data: TokenData = Depends(require_admin("ai"))):
    if token_data.role != "super_admin":          # the whole corpus leaves the platform: the super admin only
        raise HTTPException(status_code=403, detail="Réservé au super admin.")
    lab = label if label in ("good", "bad") else None
    return StreamingResponse(_jsonl(lab), media_type="application/x-ndjson",
                             headers={"Content-Disposition": f'attachment; filename="fidclic-ia-exemples-{lab or "tous"}.jsonl"'})
