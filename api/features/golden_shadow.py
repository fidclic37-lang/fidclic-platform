"""
The Golden set's shadow replay (user, 2026-11-09, part C of « asli data … se
golden set »): the owners' own Copilote questions of the last 14 days, asked
again in production with the model being tried, and set beside the answer the
owner got. No data leaves production.

    · pick()   the questions: shops in the real-data test (Super admin › Golden
               set switch, on by default), the owner's or a team account's own
               questions — never a « Retiens que… » or a super admin's — once
               per shop and wording, shops taking turns
    · start()  a run: up to 50 questions, the routes being tried, its own €
               ceiling (3 € by default)
    · step()   a few questions at a time (the page asks for the next step; the
               15-minute tick finishes a run left open). Each one is answered
               as the account that asked it, with nothing kept (no chat, no
               learning-log row, no memory) and billed to the platform under
               « golden-shadow:<run> », never to the shop. The live checks read
               both answers: ok, regression, fixed, both bad, or the template
               answered.
    · The page shows the questions and answers scrubbed: clients' names →
      {prénom}, phones and e-mails hidden (features/learning_log.scrub).
"""
from __future__ import annotations

import re
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from features.platform_access import require_admin

router = APIRouter(tags=["golden-shadow"])
_db = None

UTC = timezone.utc
WINDOW = timedelta(days=14)
MAX_QUESTIONS = 50
DEFAULT_EUR = 3.0
STEP_BUDGET_S = 20.0
STALE = timedelta(minutes=10)            # a question a dead step left half-done is taken again
VERDICTS = ("ok", "regression", "fixed", "both_bad", "fallback")


def init(db):
    global _db
    _db = db
    try:
        db.golden_shadow_items.create_index([("run_id", 1), ("status", 1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    return None


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


# ---------------------------------------------------------------------------
# the questions
# ---------------------------------------------------------------------------
def pick(count: int, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    from features import golden_real as GR
    now = _aware(now) or _now()
    shops = {t["id"]: t for t in _db.tenants.find({}, {"_id": 0, "id": 1, "name": 1, "golden_real_off": 1, "demo": 1,
                                                       "is_active": 1}) if GR.on(t)}
    per: Dict[str, List[Dict[str, Any]]] = {}
    seen = set()
    rows = _db.copilot_chats.find({"role": "user", "tenant_id": {"$in": list(shops)}, "at": {"$gte": now - WINDOW},
                                   "memo": {"$ne": True}, "view_by": None}, {"_id": 0}).sort("at", -1)
    for m in rows:
        text = (m.get("text") or "").strip()
        key = (m["tenant_id"], _fold(text))
        if len(text) < 4 or key in seen:
            continue
        at = _aware(m.get("at"))
        old = _db.copilot_chats.find_one({"tenant_id": m["tenant_id"], "by": m.get("by"), "role": "assistant",
                                          "at": {"$gte": at, "$lte": at + timedelta(minutes=5)}}, {"_id": 0}, sort=[("at", 1)])
        if not old:
            continue
        seen.add(key)
        per.setdefault(m["tenant_id"], []).append({
            "tenant_id": m["tenant_id"], "by": m.get("by"), "question": text, "asked_at": at,
            "old": old.get("text") or "", "old_source": old.get("source"), "old_id": old.get("id")})
    out: List[Dict[str, Any]] = []
    queues = sorted(per.values(), key=lambda q: -q[0]["asked_at"].timestamp())
    while len(out) < count and any(queues):
        for q in queues:
            if q and len(out) < count:
                out.append(q.pop(0))
    return out


# ---------------------------------------------------------------------------
# a run
# ---------------------------------------------------------------------------
def _tag(rid: str) -> str:
    return f"golden-shadow:{rid}"


def start(by: str, count: int, routes: Optional[Dict[str, str]] = None, max_eur: float = DEFAULT_EUR) -> Dict[str, Any]:
    from features import ai_routing as AR
    routes = routes or {}
    bad = [j for j, m in routes.items() if j not in AR.JOBS or m not in AR.LADDER]
    if bad:
        raise HTTPException(status_code=400, detail="Modèle ou travail inconnu.")
    rid = uuid.uuid4().hex[:16]
    items = pick(count)
    tried = {**AR.current(), **routes}
    _db.golden_shadow_runs.insert_one({"id": rid, "by": by, "at": _now(), "routes": routes, "tried": tried,
                                       "max_eur": float(max_eur), "status": "running" if items else "done",
                                       "total": len(items), "why": None if items else "aucune question"})
    if items:
        _db.golden_shadow_items.insert_many([{**it, "run_id": rid, "i": i, "status": "todo"} for i, it in enumerate(items)])
    return {"id": rid, "total": len(items)}


def _spent(rid: str) -> float:
    return round(sum(float(c.get("eur") or 0) for c in _db.ai_calls.find({"user": _tag(rid)}, {"_id": 0, "eur": 1})), 4)


def _problems(text: str, prompt: Optional[str]) -> List[str]:
    """The live checks of the Copilote (features/ai_routing.problems). Without
    the prompt the answer was written from, « montant » can't be read."""
    from features import ai_routing as AR
    out = AR.problems("copilot", text, "", prompt or "")
    return [p for p in out if prompt is not None or p != "montant"]


def _old_prompt(item: Dict[str, Any]) -> Optional[str]:
    if not item.get("old_id"):
        return None
    ex = _db.ai_examples.find_one({"id": item["old_id"]}, {"_id": 0, "input_z": 1})
    if not ex:
        return None
    from features import learning_log as LL
    return LL.unpack(ex.get("input_z"))


def _account(item: Dict[str, Any]):
    """The account that asked — its own page rights and stores — or the owner."""
    from models import TokenData
    u = _db.users.find_one({"email": item.get("by"), "tenant_id": item["tenant_id"], "active": {"$ne": False}},
                           {"_id": 0, "email": 1, "role": 1})
    if not u:
        u = _db.users.find_one({"tenant_id": item["tenant_id"], "role": "business_owner"}, {"_id": 0, "email": 1, "role": 1}) or {}
    return TokenData(email=u.get("email"), role=u.get("role") or "business_owner", tenant_id=item["tenant_id"])


def _one(run: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    from features import ai_meter as AM, ai_routing as AR, copilot as K, learning_log as LL
    from services import llm
    t0 = time.monotonic()
    tok = _account(item)
    with AM.scope(tenant_id=None, user=_tag(run["id"])), AR.trying(run.get("routes")):
        AR._REFUSED.set(None)                    # a refusal is this question's, not the one before
        a = K.answer(tok, None, item["question"], record=False)
        call = llm.last_call() or {}
        refused = list(AR.last_refusal() or [])       # the live checks threw the model's answer away
    new_text = (a.get("reply") or "").strip()
    new_src = a.get("source")
    prompt = f"{call.get('system') or ''}\n{call.get('user') or ''}" if call else None
    newp = _problems(new_text, prompt) if new_src == "model" else refused
    oldp = _problems(item.get("old") or "", _old_prompt(item)) if item.get("old_source", "model") == "model" else []
    if new_src != "model" and not refused:
        verdict = "fallback"                       # no model answered (none set up, or a limit): the template did
    elif newp and not oldp:
        verdict = "regression"
    elif oldp and not newp:
        verdict = "fixed"
    elif oldp and newp:
        verdict = "both_bad"
    else:
        verdict = "ok"
    tid = item["tenant_id"]
    return {"status": "done", "verdict": verdict, "ms": int((time.monotonic() - t0) * 1000),
            "question_shown": LL.scrub(tid, item["question"]),
            "new": {"text": LL.scrub(tid, new_text), "source": new_src, "problems": newp},
            "old_shown": {"text": LL.scrub(tid, item.get("old") or ""), "problems": oldp}}


def step(rid: str, budget_s: float = STEP_BUDGET_S) -> Dict[str, Any]:
    from features import ai_meter as AM
    run = _db.golden_shadow_runs.find_one({"id": rid}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Test introuvable.")
    deadline = time.monotonic() + budget_s
    while run["status"] == "running":
        if _spent(rid) >= run["max_eur"]:
            return _stop(rid, "budget")
        if AM.state(None).get("blocked") == "global":         # the shops' own AI comes first
            return _stop(rid, "global")
        now = _now()
        item = _db.golden_shadow_items.find_one_and_update(
            {"run_id": rid, "$or": [{"status": "todo"}, {"status": "running", "claimed_at": {"$lt": now - STALE}}]},
            {"$set": {"status": "running", "claimed_at": now}}, sort=[("i", 1)])
        if not item:
            if not _db.golden_shadow_items.find_one({"run_id": rid, "status": "running"}, {"_id": 1}):
                _db.golden_shadow_runs.update_one({"id": rid, "status": "running"}, {"$set": {"status": "done", "ended_at": now}})
            break
        try:
            res = _one(run, item)
        except Exception as exc:                  # noqa: BLE001 — one question never stops the run
            res = {"status": "done", "verdict": "fallback", "error": type(exc).__name__,
                   "question_shown": "", "new": {"text": "", "source": "error", "problems": []},
                   "old_shown": {"text": "", "problems": []}}
        _db.golden_shadow_items.update_one({"run_id": rid, "i": item["i"]}, {"$set": res})
        if time.monotonic() >= deadline:
            break
        run = _db.golden_shadow_runs.find_one({"id": rid}, {"_id": 0}) or run
    return view(rid, items=False)


def _stop(rid: str, why: str) -> Dict[str, Any]:
    _db.golden_shadow_runs.update_one({"id": rid, "status": "running"}, {"$set": {"status": "stopped", "why": why,
                                                                                    "ended_at": _now()}})
    return view(rid, items=False)


def due(budget_s: float = 20.0) -> Dict[str, Any]:
    """The tick: a run left open is carried on."""
    done = []
    for r in _db.golden_shadow_runs.find({"status": "running"}, {"_id": 0, "id": 1}):
        step(r["id"], budget_s)
        done.append(r["id"])
    return {"runs": done}


def view(rid: str, items: bool = True) -> Dict[str, Any]:
    run = _db.golden_shadow_runs.find_one({"id": rid}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Test introuvable.")
    rows = list(_db.golden_shadow_items.find({"run_id": rid}, {"_id": 0}).sort("i", 1))
    finished = [r for r in rows if r.get("status") == "done"]
    names = {t["id"]: t.get("name") or t["id"] for t in _db.tenants.find({"id": {"$in": list({r["tenant_id"] for r in rows})}},
                                                                           {"_id": 0, "id": 1, "name": 1})}
    out = {"id": rid, "at": _aware(run.get("at")).isoformat() if run.get("at") else None, "by": run.get("by"),
           "routes": run.get("routes"), "tried": run.get("tried"), "status": run["status"], "why": run.get("why"),
           "total": run.get("total", 0), "done": len(finished), "cost_eur": _spent(rid), "max_eur": run.get("max_eur"),
           "summary": {v: sum(1 for r in finished if r.get("verdict") == v) for v in VERDICTS}}
    if items:
        out["items"] = [{"i": r["i"], "tenant": names.get(r["tenant_id"], ""), "question": r.get("question_shown") or "",
                         "verdict": r.get("verdict"), "old": r.get("old_shown"), "new": r.get("new"), "ms": r.get("ms")}
                        for r in finished]
    return out


# ---------------------------------------------------------------------------
# Super admin › FIDCLIC AI › Golden set
# ---------------------------------------------------------------------------
class StartIn(BaseModel):
    count: int = Field(30, ge=1, le=MAX_QUESTIONS)
    routes: Dict[str, str] = Field(default_factory=dict)
    max_eur: float = Field(DEFAULT_EUR, gt=0, le=20)


@router.get("/api/admin/ai/shadow")
def runs(token_data=Depends(require_admin("ai"))):
    rows = list(_db.golden_shadow_runs.find({}, {"_id": 0, "id": 1}).sort("at", -1).limit(10))
    return {"runs": [view(r["id"], items=False) for r in rows]}


@router.post("/api/admin/ai/shadow")
def start_run(body: StartIn, token_data=Depends(require_admin("ai"))):
    return start(token_data.email, body.count, body.routes, body.max_eur)


@router.post("/api/admin/ai/shadow/{rid}/step")
def step_run(rid: str, token_data=Depends(require_admin("ai"))):
    return step(rid)


@router.get("/api/admin/ai/shadow/{rid}")
def get_run(rid: str, token_data=Depends(require_admin("ai"))):
    return view(rid)
