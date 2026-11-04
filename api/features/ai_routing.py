"""
AI routing (user, 2026-11-04): which model does which job.

One Anthropic key, one line in each request: the job's name (`feature`, the
same one the AI meter bills) picks the model. Small jobs go to Sonnet,
everything else to Opus, Haiku is in no default.

An answer that fails the checks below goes once to the next model up (Sonnet
→ Opus → Fable); if that one fails too, the caller's template answers. The
climb is paid like any other call, from the same budget, under the same limits.

Super admin › FIDCLIC AI › Routage changes a job's model at once: audited, one
click to undo, and the page asks for a Golden set run until one has tested
this exact table (« Lancer » sends it to the run).

The table only speaks for Claude: another provider in front (LLM_PROVIDER)
keeps its own model, and the page says the table is asleep.
"""
from __future__ import annotations

import contextvars
import json
import re
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import TokenData
from features.platform_access import require_admin
from services.ai_checks import _EMAIL, _EN, _FR, _PHONE, _plain, fold, money_in, unread_amounts

router = APIRouter(tags=["ai-routing"])
_db = None

HAIKU, SONNET, OPUS, FABLE = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"
LADDER = (HAIKU, SONNET, OPUS, FABLE)
LABELS = {HAIKU: "Haiku 5.5", SONNET: "Sonnet 5.5", OPUS: "Opus 5.5", FABLE: "Fable 5.1"}

DEFAULTS: Dict[str, str] = {
    "copilot": OPUS, "campaign_ai": OPUS, "automation_ai": OPUS, "autopilot": OPUS,
    "conseiller": SONNET, "support": SONNET, "campaign_recap": SONNET, "copilot_memory": SONNET,
    "admin_ai": SONNET, "invoice_ocr": SONNET, "menu_import": SONNET,
}
OTHERS = OPUS                        # a job nobody listed (« baaki kaam »), the row « autre »
JOBS = {"copilot": "Copilote", "campaign_ai": "Rédiger (campagnes)", "automation_ai": "Rédiger (automatisations)",
        "autopilot": "Autopilote", "conseiller": "Conseiller", "support": "Assistant support",
        "campaign_recap": "Bilan de campagne", "copilot_memory": "Mémoire du Copilote", "admin_ai": "FIDCLIC AI (super admin)",
        "invoice_ocr": "Lecture de factures", "menu_import": "Lecture de menus", "autre": "Autres"}

# What each job's answer is held to. Jobs that return data (a memory, a
# classification, a photo's JSON) are not read.
WRITERS = ("langue", "contact_nouveau")
CHECKS = {"copilot": ("langue", "contact", "long", "montant"),
          "campaign_ai": WRITERS, "automation_ai": WRITERS, "autopilot": WRITERS,
          "conseiller": ("langue",), "support": ("langue",)}
LONG_WORDS = 240                     # the prompt asks for far less; only a runaway answer is refused
MIN_UNREAD_EUR = 5                   # a small shop's basket can be 8 €; under 5 € it is a price, not a figure


def init(db):
    global _db
    _db = db
    try:
        db.ai_route_stats.create_index([("day", 1)])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# the table

def _saved() -> Dict[str, Any]:
    if _db is None:
        return {}
    return _db.platform_settings.find_one({"key": "ai_routing"}, {"_id": 0}) or {}


def _default(feature: str) -> str:
    return DEFAULTS.get(feature, OTHERS)


def model_for(feature: Optional[str]) -> str:
    routes = _saved().get("routes") or {}
    job = feature if feature in DEFAULTS else "autre"
    chosen = routes.get(job)
    return chosen if chosen in LADDER else _default(job)


def current() -> Dict[str, str]:
    return {job: model_for(job) for job in JOBS}


def stronger(model: Optional[str]) -> Optional[str]:
    if model not in LADDER:
        return None
    i = LADDER.index(model)
    return LADDER[i + 1] if i + 1 < len(LADDER) else None


def apply_routes(raw: Optional[str]) -> int:
    """The table a Golden set run was asked to test (its own in-memory database)."""
    try:
        data = json.loads(raw or "")
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0
    good = {job: m for job, m in data.items() if job in JOBS and m in LADDER}
    if good:
        _db.platform_settings.update_one({"key": "ai_routing"}, {"$set": {f"routes.{j}": m for j, m in good.items()}}, upsert=True)
    return len(good)


# ---------------------------------------------------------------------------
# the checks

def _foreign(text: str) -> bool:
    words = re.findall(r"[a-z']+", fold(text))
    return sum(1 for w in words if w in _EN) > sum(1 for w in words if w in _FR)


def _contacts(text: str) -> List[str]:
    return [m.group(0) for m in _PHONE.finditer(text)] + \
           [m.group(0) for m in _EMAIL.finditer(text) if not m.group(0).lower().endswith("@fidclic.com")]


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def problems(feature: Optional[str], text: Optional[str], system: str, user: str) -> List[str]:
    """What is wrong with this answer, as short codes (never its text)."""
    checks = CHECKS.get(feature or "")
    a = _plain(text or "").strip()
    if not checks or not a:
        return []
    out = []
    if "langue" in checks and _foreign(a) and not re.search(r"\banglais\b|\benglish\b", fold(user)):
        out.append("anglais")
    if "contact" in checks and _contacts(a):
        out.append("contact")
    if "contact_nouveau" in checks:
        given, given_digits = fold(user), _digits(user)
        if any((c.lower() not in given) and (_digits(c) not in given_digits or not _digits(c)) for c in _contacts(a)):
            out.append("contact")
    if "long" in checks and len(a.split()) > LONG_WORDS:
        out.append("trop_long")
    if "montant" in checks and unread_amounts(a, money_in(f"{system}\n{user}"), MIN_UNREAD_EUR):
        out.append("montant")
    return out


# Why the last answer of this request was refused for good (the Golden set's report).
_REFUSED: contextvars.ContextVar = contextvars.ContextVar("ai_refused", default=None)


def last_refusal() -> Optional[List[str]]:
    return _REFUSED.get()


def note(feature: Optional[str], kind: str, why: List[str]) -> None:
    """A climb (« escalated ») or an answer refused for good (« rejected »)."""
    _REFUSED.set(why if kind == "rejected" else None)
    if _db is None:
        return
    from features import ai_meter as AM
    job = feature if feature in DEFAULTS else "autre"
    day = AM._paris().strftime("%Y-%m-%d")
    try:
        _db.ai_route_stats.update_one({"_id": f"{day}|{job}"}, {
            "$setOnInsert": {"day": day, "feature": job},
            "$inc": {kind: 1, **({f"why.{c}": 1 for c in why} if kind == "escalated" else {})}}, upsert=True)
    except Exception as exc:                 # noqa: BLE001 — a counter never loses an answer
        print(f"ai_routing: stats failed ({exc})")


# ---------------------------------------------------------------------------
# Super admin › FIDCLIC AI › Routage

class RouteIn(BaseModel):
    model: str


def _stats() -> Dict[str, Dict[str, Any]]:
    from features import ai_meter as AM
    since = AM._now() - timedelta(days=30)
    out: Dict[str, Dict[str, Any]] = {job: {"calls": 0, "eur": 0.0, "escalated": 0, "rejected": 0, "why": {}} for job in JOBS}
    for r in _db.ai_calls.aggregate([{"$match": {"at": {"$gte": since}}},
                                     {"$group": {"_id": "$feature", "calls": {"$sum": 1}, "eur": {"$sum": "$eur"}}}]):
        row = out.get(r["_id"]) or out["autre"]
        row["calls"] += int(r["calls"])
        row["eur"] += float(r["eur"] or 0)
    for d in _db.ai_route_stats.find({"day": {"$gte": AM._paris(since).strftime("%Y-%m-%d")}}, {"_id": 0}):
        row = out.get(d.get("feature")) or out["autre"]
        row["escalated"] += int(d.get("escalated") or 0)
        row["rejected"] += int(d.get("rejected") or 0)
        for c, n in (d.get("why") or {}).items():
            row["why"][c] = row["why"].get(c, 0) + int(n)
    return out


def _golden() -> Dict[str, Any]:
    doc = next(iter(_db.golden_runs.find({}, {"report.ok": 1, "report.total": 1, "report.passed": 1, "report.routes": 1, "at": 1}).sort("at", -1).limit(1)), None)
    rep = (doc or {}).get("report") or {}
    return {"at": (doc or {}).get("at"), "ok": rep.get("ok"), "total": rep.get("total"), "passed": rep.get("passed"),
            "stale": rep.get("routes") != current()}


def _audit(action: str, token_data: TokenData, request: Request, job: str, meta: Dict[str, Any]) -> None:
    try:
        import server as core
        core.log_audit(action, actor=token_data.email, actor_type="admin", target=job, request=request, meta=meta)
    except Exception:
        pass


@router.get("/api/admin/ai/routing")
def page(token_data: TokenData = Depends(require_admin("ai"))):
    from features import ai_meter as AM
    from services import llm
    previous = _saved().get("previous") or {}
    stats = _stats()
    routes = []
    for job, label in JOBS.items():
        model = model_for(job)
        s = stats[job]
        routes.append({"feature": job, "label": label, "model": model, "default": _default(job), "changed": model != _default(job),
                       "above": stronger(model), "previous": previous.get(job) if previous.get(job) in LADDER else None,
                       **s, "eur": round(s["eur"], 4)})
    name = llm._provider_name()
    return {"provider": name, "active": name == "anthropic" and llm._has_key("anthropic"), "routes": routes,
            "models": [{"id": m, "label": LABELS[m], "in": AM._price(m)[0], "out": AM._price(m)[1]} for m in LADDER],
            "golden": _golden()}


def _set(job: str, model: str, previous: str) -> None:
    _db.platform_settings.update_one({"key": "ai_routing"}, {"$set": {f"routes.{job}": model, f"previous.{job}": previous}}, upsert=True)


@router.put("/api/admin/ai/routing/{job}")
def change(job: str, body: RouteIn, request: Request, token_data: TokenData = Depends(require_admin("ai"))):
    if job not in JOBS:
        raise HTTPException(status_code=404, detail="Travail IA introuvable")
    if body.model not in LADDER:
        raise HTTPException(status_code=400, detail="Ce modèle n'est pas dans la liste.")
    before = model_for(job)
    if before != body.model:
        _set(job, body.model, before)
        _audit("ai_routing.change", token_data, request, job, {"from": before, "to": body.model})
    return {"ok": True, "model": body.model}


@router.post("/api/admin/ai/routing/{job}/revert")
def revert(job: str, request: Request, token_data: TokenData = Depends(require_admin("ai"))):
    if job not in JOBS:
        raise HTTPException(status_code=404, detail="Travail IA introuvable")
    back = (_saved().get("previous") or {}).get(job)
    if back not in LADDER:
        raise HTTPException(status_code=409, detail="Aucun modèle précédent pour ce travail.")
    before = model_for(job)
    _set(job, back, before)
    _audit("ai_routing.revert", token_data, request, job, {"from": before, "to": back})
    return {"ok": True, "model": back}
