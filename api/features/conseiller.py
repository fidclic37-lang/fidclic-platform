"""
La Mémoire + Le Conseiller (Features Book Chapter 8, Zone 5) — agent capability #5.

Status: 🟢 Core.
Mounts at: /api/cabinet/dossiers/{tid}/memoire, /conseiller/run, /conseils
Storage: dossier_memory, conseils.

TWO HALVES, ONE IDEA
    La Mémoire — the cabinet's institutional memory of a client that today lives
    only in a collaborateur's head: "toujours en retard pour la TVA", "le gérant
    préfère WhatsApp", "clôture décalée au 30/06". When that person leaves, the
    knowledge leaves. La Mémoire persists these notes on the dossier so every
    member — and the agent — works with the same context.

    Le Conseiller — the research's #4 opportunity: cabinets leave advisory money
    on the table because nobody has time to spot the moment. The agent watches
    each dossier and, when a situation crosses a threshold, drafts a CONSEIL:
    a plain-French advisory note the human can turn into a billable conversation.
    Detection is RULE-BASED (deterministic, testable); an LLM only *phrases* the
    message, falling back to a template when no model is configured. It reads La
    Mémoire so the advice respects what the cabinet already knows.

THE GUARDRAIL
    A conseil is a DRAFT for a human, never client-facing on its own and never
    "tax advice" — the UI carries that disclaimer. The agent proposes the
    opportunity; the expert decides and bills.
"""
from __future__ import annotations

from datetime import datetime, timezone, date, timedelta
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from auth import require_role

router = APIRouter(tags=["conseiller"])
_db = None

MEMORY_KINDS = ("quirk", "preference", "deadline", "fact", "risk")


def init(db):
    global _db
    _db = db
    try:
        _db.conseils.create_index([("tenant_id", 1), ("status", 1), ("type", 1)])
        _db.dossier_memory.create_index([("tenant_id", 1)])
    except Exception:
        pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _audit(*args, **kwargs):
    try:
        from features import audit
        audit.log(*args, **kwargs)
    except Exception:
        pass


# ==========================================================================
# La Mémoire
# ==========================================================================

@router.get("/api/cabinet/dossiers/{tenant_id}/memoire")
def list_memory(tenant_id: str, token_data=Depends(require_role(["comptable"]))):
    from features import cabinet_os as co
    co.assert_can_see_tenant(token_data.email, tenant_id)
    notes = []
    for n in _db.dossier_memory.find({"tenant_id": tenant_id}).sort("created_at", -1):
        n.pop("_id", None)
        notes.append(n)
    return {"notes": notes}


@router.post("/api/cabinet/dossiers/{tenant_id}/memoire")
def add_memory(tenant_id: str, body: Dict[str, Any],
               token_data=Depends(require_role(["comptable"]))):
    from features import cabinet_os as co
    co.assert_can_see_tenant(token_data.email, tenant_id)
    m = co.current_membership(token_data.email)
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(422, "Note vide.")
    kind = (body.get("kind") or "fact").lower()
    if kind not in MEMORY_KINDS:
        kind = "fact"
    note = {"id": str(uuid4()), "tenant_id": tenant_id, "cabinet_id": m["cabinet_id"],
            "kind": kind, "text": text[:1000], "pinned": bool(body.get("pinned")),
            "created_by": token_data.email, "created_at": _now()}
    _db.dossier_memory.insert_one(dict(note))
    note.pop("_id", None)
    _audit("memoire.added", tenant_id=tenant_id, actor=token_data,
           object_kind="dossier_memory", object_id=note["id"],
           after={"kind": kind})
    return {"ok": True, "note": note}


def _memory_context(tenant_id: str) -> str:
    notes = list(_db.dossier_memory.find({"tenant_id": tenant_id}))
    if not notes:
        return ""
    return " ; ".join(f"[{n.get('kind')}] {n.get('text')}" for n in notes[:15])


# ==========================================================================
# Le Conseiller — detection
# ==========================================================================

def _sales(tenant_id: str) -> List[Dict[str, Any]]:
    from services import statuses as stt
    return [stt.ensure(i) for i in
            _db.fact_invoices.find({"tenant_id": tenant_id})]


def _ht_between(invs, start: date, end: date) -> float:
    tot = 0.0
    for i in invs:
        d = str(i.get("date") or "")[:10]
        if d and start.isoformat() <= d <= end.isoformat():
            tot += float(i.get("total_ht") or 0)
    return round(tot, 2)


def _detect(tenant_id: str) -> List[Dict[str, Any]]:
    """Rule-based signals → candidate conseils (before phrasing/dedup)."""
    invs = _sales(tenant_id)
    today = _today()
    out: List[Dict[str, Any]] = []

    # 1) cash-flow: validated, unpaid, past due
    overdue = [i for i in invs
               if i.get("review_status") == "validated"
               and i.get("payment_status") not in ("paid",)
               and str(i.get("due_date") or "")[:10]
               and str(i.get("due_date"))[:10] < today.isoformat()]
    if len(overdue) >= 2:
        amt = round(sum(float(i.get("total_ttc") or 0) for i in overdue), 2)
        out.append({
            "type": "cashflow", "severity": "warning",
            "title": "Trésorerie : impayés clients à relancer",
            "evidence": {"overdue_count": len(overdue), "overdue_ttc": amt},
            "suggested_action": "Proposer une mission de relance client / suivi de trésorerie.",
            "facts": f"{len(overdue)} factures échues impayées pour {amt} € TTC."})

    # 2) growth: last 90 days vs the 90 before
    cur = _ht_between(invs, today - timedelta(days=90), today)
    prev = _ht_between(invs, today - timedelta(days=180), today - timedelta(days=91))
    if prev > 0 and cur >= prev * 1.3:
        out.append({
            "type": "growth", "severity": "info",
            "title": "Activité en forte hausse — anticiper la fiscalité",
            "evidence": {"ht_90j": cur, "ht_90j_precedent": prev,
                         "hausse_pct": round((cur / prev - 1) * 100)},
            "suggested_action": "Proposer un point prévisionnel (TVA, IS, acomptes).",
            "facts": f"CA HT +{round((cur/prev-1)*100)} % sur 90 jours ({prev} € → {cur} €)."})

    # 3) dormant: had activity, none in the last 60 days
    if invs:
        last = max((str(i.get("date") or "")[:10] for i in invs), default="")
        if last and last < (today - timedelta(days=60)).isoformat():
            out.append({
                "type": "dormant", "severity": "info",
                "title": "Dossier silencieux depuis 2 mois",
                "evidence": {"last_invoice_date": last},
                "suggested_action": "Prendre des nouvelles du client (activité, besoins).",
                "facts": f"Aucune facture depuis le {last}."})
    return out


def _phrase(cabinet_name: str, client_name: str, cand: Dict[str, Any],
            memory: str) -> str:
    """LLM phrasing over the facts, with a deterministic template fallback."""
    from services import llm
    system = ("Tu es l'assistant d'un cabinet d'expertise comptable français. "
              "Rédige une note interne courte (2-3 phrases), en français "
              "professionnel, à destination du comptable — PAS du client. "
              "Ne donne jamais de conseil fiscal définitif ; suggère une action.")
    user = (f"Client : {client_name}. Situation détectée : {cand['facts']} "
            f"Action envisagée : {cand['suggested_action']}."
            + (f" Contexte connu du dossier : {memory}." if memory else ""))
    txt = llm.complete(system, user, max_tokens=180, feature="conseiller")
    if txt:
        return txt
    # template fallback
    return (f"{cand['facts']} {cand['suggested_action']}"
            + (f" (À garder en tête : {memory})" if memory else ""))


def run_conseiller_for(tenant_id: str, cabinet_id: str, actor,
                       triggered_by: str) -> Dict[str, Any]:
    t = _db.tenants.find_one({"id": tenant_id}) or {}
    cabinet = _db.cabinets.find_one({"id": cabinet_id}) or {}
    client_name = t.get("legal_name") or t.get("name") or "le client"
    memory = _memory_context(tenant_id)

    created = 0
    for cand in _detect(tenant_id):
        # dedupe: one open conseil per type per dossier
        if _db.conseils.find_one({"tenant_id": tenant_id, "type": cand["type"],
                                  "status": "open"}):
            continue
        msg = _phrase(cabinet.get("name", "le cabinet"), client_name, cand, memory)
        c = {"id": str(uuid4()), "tenant_id": tenant_id, "cabinet_id": cabinet_id,
             "type": cand["type"], "severity": cand["severity"],
             "title": cand["title"], "message": msg,
             "evidence": cand["evidence"], "suggested_action": cand["suggested_action"],
             "status": "open", "created_by": getattr(actor, "email", "agent"),
             "created_at": _now()}
        _db.conseils.insert_one(dict(c))
        _audit("agent.conseil_created", tenant_id=tenant_id, actor=actor,
               object_kind="conseil", object_id=c["id"],
               after={"type": c["type"], "severity": c["severity"]},
               detail={"triggered_by": triggered_by})
        created += 1
    return {"ok": True, "conseils_created": created}


@router.post("/api/cabinet/dossiers/{tenant_id}/conseiller/run")
def run_conseiller(tenant_id: str, token_data=Depends(require_role(["comptable"]))):
    from features import cabinet_os as co
    co.assert_can_see_tenant(token_data.email, tenant_id)
    m = co.current_membership(token_data.email)
    co.ensure_agent(m["cabinet_id"])
    agent_actor = co.agent_actor(m["cabinet_id"])
    return run_conseiller_for(tenant_id, m["cabinet_id"], agent_actor, token_data.email)


@router.get("/api/cabinet/dossiers/{tenant_id}/conseils")
def list_conseils(tenant_id: str, token_data=Depends(require_role(["comptable"]))):
    from features import cabinet_os as co
    co.assert_can_see_tenant(token_data.email, tenant_id)
    out = []
    for c in _db.conseils.find({"tenant_id": tenant_id}).sort("created_at", -1):
        c.pop("_id", None)
        out.append(c)
    return {"conseils": out}


@router.post("/api/cabinet/conseils/{conseil_id}/dismiss")
def dismiss_conseil(conseil_id: str, token_data=Depends(require_role(["comptable"]))):
    c = _db.conseils.find_one({"id": conseil_id})
    if not c:
        raise HTTPException(404, "Conseil introuvable.")
    from features import cabinet_os as co
    co.assert_can_see_tenant(token_data.email, c["tenant_id"])
    _db.conseils.update_one({"id": conseil_id}, {"$set": {
        "status": "dismissed", "dismissed_by": token_data.email,
        "dismissed_at": _now()}})
    _audit("conseil.dismissed", tenant_id=c["tenant_id"], actor=token_data,
           object_kind="conseil", object_id=conseil_id)
    return {"ok": True}
