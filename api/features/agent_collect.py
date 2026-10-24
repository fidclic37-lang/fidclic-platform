"""
Agent — Collecte des pièces (S12). The first AUTONOMOUS work of the agent.

Status: 🟢 Core (agent capability #1).
Mounts at: /api/cabinet/doc-requests*, /api/cabinet/agent/collect/run
Storage: doc_requests, tenant doc field doc_reliability.

THE PROBLEM (research: opportunity #2, the #1 named time-sink)
    A collaborateur loses 9-12 hours/month chasing clients for documents;
    60% of clients don't respond within 5 days. Generic mass reminders
    BACKFIRE (they flood the cabinet with unusable pieces) — the defensible
    version adapts to each client's demonstrated reliability.

HOW IT WORKS
    1. Anyone working the dossier records what is missing ("Relevé bancaire
       juillet", due 10/08, client email).
    2. The agent run (human-triggered for now, scheduled later) walks every
       pending request and decides PER CLIENT whether today is the day to
       write — based on the client's reliability score:
         reliable   (>=80): first nudge 2 days AFTER due, then every 7 days
         average (50-79):   nudge at due date, then every 4 days
         flaky      (<50):  nudge 2 days BEFORE due, then every 2 days
       One email per client per run, listing ALL their pending pieces —
       never one email per piece (that is how you train clients to ignore you).
    3. Every send is audited as the AGENT (actor = agent identity,
       triggered_by = the human who pressed run).
    4. After 3 reminders with silence → Exception Centre case
       (missing_document) on the dossier owner. Email escalates to a human;
       the agent never harasses forever.

RELIABILITY SCORE
    Per tenant: {asked, received, on_time}. score = 100*(0.6*received/asked
    + 0.4*on_time/asked), default 70 with no history. It updates itself every
    time a piece is marked received — the longer a cabinet uses FidClic, the
    smarter the cadence gets. That accumulating data is the moat.
"""
from __future__ import annotations

from datetime import datetime, timezone, date, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from auth import require_role

router = APIRouter(tags=["agent-collect"])
_db = None

MAX_REMINDERS = 3


def init(db):
    global _db
    _db = db
    try:
        _db.doc_requests.create_index([("cabinet_id", 1), ("status", 1)])
        _db.doc_requests.create_index([("tenant_id", 1), ("status", 1)])
    except Exception:
        pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> date:
    """Today in Paris — a due date is a French accounting day, not UTC's
    (from midnight to 2 a.m. they differ)."""
    from zoneinfo import ZoneInfo
    return datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Paris")).date()


def _audit(*args, **kwargs):
    try:
        from features import audit
        audit.log(*args, **kwargs)
    except Exception:
        pass


# --------------------------------------------------------------------------
# reliability
# --------------------------------------------------------------------------

def reliability(tenant: Dict[str, Any]) -> int:
    r = tenant.get("doc_reliability") or {}
    asked = r.get("asked", 0)
    if not asked:
        return 70                                   # benefit of the doubt
    received = r.get("received", 0)
    on_time = r.get("on_time", 0)
    return max(0, min(100, round(100 * (0.6 * received / asked
                                        + 0.4 * on_time / asked))))


def _cadence(score: int) -> Dict[str, int]:
    """When to write, relative to the due date, and how often after."""
    if score >= 80:
        return {"first_offset_days": +2, "repeat_days": 7}   # gentle, late
    if score >= 50:
        return {"first_offset_days": 0, "repeat_days": 4}
    return {"first_offset_days": -2, "repeat_days": 2}       # early, insistent


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------

@router.post("/api/cabinet/dossiers/{tenant_id}/doc-requests")
def create_request(tenant_id: str, body: Dict[str, Any],
                   token_data=Depends(require_role(["comptable"]))):
    """Record a missing piece. Anyone who can see the dossier can ask."""
    from features import cabinet_os as co
    m = co.current_membership(token_data.email)
    co.assert_can_see_tenant(token_data.email, tenant_id)

    label = (body.get("label") or "").strip()
    if not label:
        raise HTTPException(422, "Précisez la pièce demandée (ex. « Relevé bancaire juillet »).")
    email = (body.get("client_email") or "").strip().lower()
    if not email:
        # fall back to the dossier's known owner account, if any
        u = _db.users.find_one({"tenant_id": tenant_id, "role": "business_owner"})
        email = (u or {}).get("email") or ""
    if not email or "@" not in email:
        raise HTTPException(422, "Email du client requis (aucun compte client connu pour ce dossier).")
    due = body.get("due_date") or (_today() + timedelta(days=7)).isoformat()
    # optional WhatsApp reach — the agent will use it when the channel is live
    from services import whatsapp as wa
    phone = wa.normalize_phone(body.get("client_phone") or "")
    channel_pref = (body.get("channel") or "auto").strip().lower()
    if channel_pref not in ("auto", "email", "whatsapp"):
        channel_pref = "auto"

    doc = {
        "id": str(uuid4()), "cabinet_id": m["cabinet_id"], "tenant_id": tenant_id,
        "label": label, "due_date": due, "client_email": email,
        "client_phone": phone, "channel_pref": channel_pref,
        "status": "pending", "reminders": [],
        "created_by": token_data.email, "created_at": _now(),
    }
    _db.doc_requests.insert_one(dict(doc))
    # NOTE: the reliability score only counts COMPLETED cycles (received or
    # escalated). Counting "asked" at creation would score a brand-new client
    # 0/100 while their very first request is still pending — and the agent
    # would immediately treat them as flaky and over-remind. Found by a test.
    _audit("doc_request.created", tenant_id=tenant_id, actor=token_data,
           object_kind="doc_request", object_id=doc["id"],
           after={"label": label, "due": due})
    doc.pop("_id", None)
    return {"ok": True, "request": doc}


@router.get("/api/cabinet/dossiers/{tenant_id}/doc-requests")
def list_requests(tenant_id: str, token_data=Depends(require_role(["comptable"]))):
    from features import cabinet_os as co
    co.assert_can_see_tenant(token_data.email, tenant_id)
    t = _db.tenants.find_one({"id": tenant_id}) or {}
    docs = []
    for d in _db.doc_requests.find({"tenant_id": tenant_id}).sort("created_at", -1):
        d.pop("_id", None)
        docs.append(d)
    return {"requests": docs, "reliability": reliability(t)}


@router.post("/api/cabinet/doc-requests/{request_id}/received")
def mark_received(request_id: str, token_data=Depends(require_role(["comptable"]))):
    """The piece arrived — close the loop AND teach the reliability score."""
    from features import cabinet_os as co
    d = _db.doc_requests.find_one({"id": request_id})
    if not d:
        raise HTTPException(404, "Demande introuvable.")
    co.assert_can_see_tenant(token_data.email, d["tenant_id"])
    if d["status"] != "pending":
        raise HTTPException(409, "Cette demande n'est plus en attente.")

    on_time = _today().isoformat() <= d["due_date"]
    _db.doc_requests.update_one({"id": request_id}, {"$set": {
        "status": "received", "received_at": _now(), "on_time": on_time}})
    inc = {"doc_reliability.asked": 1, "doc_reliability.received": 1}
    if on_time:
        inc["doc_reliability.on_time"] = 1
    _db.tenants.update_one({"id": d["tenant_id"]}, {"$inc": inc})
    _audit("doc_request.received", tenant_id=d["tenant_id"], actor=token_data,
           object_kind="doc_request", object_id=request_id,
           detail={"on_time": on_time})
    return {"ok": True, "on_time": on_time}


# --------------------------------------------------------------------------
# the agent run
# --------------------------------------------------------------------------

def _due_for_reminder(req: Dict[str, Any], score: int, today: date) -> bool:
    cad = _cadence(score)
    try:
        due = date.fromisoformat(req["due_date"])
    except Exception:
        due = today
    reminders = req.get("reminders") or []
    if not reminders:
        return today >= due + timedelta(days=cad["first_offset_days"])
    last = reminders[-1].get("at", "")[:10]
    try:
        last_d = date.fromisoformat(last)
    except Exception:
        return True
    return today >= last_d + timedelta(days=cad["repeat_days"])


def _email_html(cabinet_name: str, client_name: str,
                items: List[Dict[str, Any]], nth: int) -> str:
    urgency = ("" if nth <= 1 else
               "<p><strong>Ceci est une relance"
               + (" importante" if nth >= 3 else "")
               + ".</strong> Sans ces éléments, nous ne pourrons pas tenir les échéances déclaratives.</p>")
    rows = "".join(
        f"<li><strong>{i['label']}</strong> — attendu pour le {i['due_date']}</li>"
        for i in items)
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#1C1917">
      <p>Bonjour {client_name},</p>
      <p>Pour tenir la comptabilité de votre entreprise à jour, votre cabinet
      <strong>{cabinet_name}</strong> attend les pièces suivantes :</p>
      <ul>{rows}</ul>
      {urgency}
      <p>Vous pouvez simplement répondre à cet email avec les documents en
      pièce jointe, ou les transmettre à votre cabinet comme d'habitude.</p>
      <p style="color:#57534E;font-size:13px">— L'assistant FidClic, pour le
      cabinet {cabinet_name}<br>
      <span style="font-size:11px;color:#8B8680">Message préparé automatiquement
      et tracé dans l'historique du dossier. Répondez « STOP » pour que le
      cabinet vous contacte directement.</span></p>
    </div>"""


def _relance_text(cabinet_name: str, client_name: str,
                  items: List[Dict[str, Any]], nth: int) -> str:
    """Plain-text version of the relance for WhatsApp/SMS channels."""
    lines = "\n".join(f"• {i['label']} (pour le {i['due_date']})" for i in items)
    head = (f"Bonjour {client_name}, votre cabinet {cabinet_name} attend "
            f"ces pièces :" if nth <= 1 else
            f"Rappel{' important' if nth >= 3 else ''} — {cabinet_name} attend "
            f"toujours ces pièces :")
    return (f"{head}\n{lines}\n\nVous pouvez les envoyer directement ici en "
            f"réponse.\n— Assistant FidClic, pour {cabinet_name}")


def _pick_channel(reqs: List[Dict[str, Any]]) -> str:
    """Decide email vs whatsapp for a client group.

    WhatsApp only when the channel is actually live (configured) AND we hold a
    phone AND the client didn't pin 'email'. Otherwise email — the always-on
    default. So the agent degrades gracefully until the Meta account is ready.
    """
    from services import whatsapp as wa
    phone = next((r.get("client_phone") for r in reqs if r.get("client_phone")), "")
    prefs = {r.get("channel_pref", "auto") for r in reqs}
    if "email" in prefs:
        return "email"
    wants_wa = "whatsapp" in prefs or "auto" in prefs
    if phone and wants_wa and wa.is_configured():
        return "whatsapp"
    return "email"


@router.post("/api/cabinet/agent/collect/run")
def run_collection(token_data=Depends(require_role(["comptable"]))):
    """One agent pass over every pending request of MY cabinet (human trigger)."""
    from features import cabinet_os as co
    actor_h = co.require_cabinet_role(token_data.email, co.ASSIGN_ROLES)
    return run_collection_for_cabinet(actor_h["cabinet_id"], token_data.email)


def run_collection_for_cabinet(cabinet_id: str, triggered_by: str) -> Dict[str, Any]:
    """The actual pass — shared by the human button and the daily cron.

    Identity, audit and escalation are identical for both triggers; only the
    `triggered_by` note differs ("cron" vs a person's email).
    """
    from features import cabinet_os as co
    from services import mailer
    cabinet = _db.cabinets.find_one({"id": cabinet_id}) or {}
    agent = co.ensure_agent(cabinet_id)
    agent_actor = co.agent_actor(cabinet_id)
    today = _today()

    pending = list(_db.doc_requests.find({"cabinet_id": cabinet_id,
                                          "status": "pending"}))
    # group per (tenant, client_email) — ONE email listing everything
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in pending:
        groups.setdefault((r["tenant_id"], r["client_email"]), []).append(r)

    sent, escalated, skipped = 0, 0, 0
    for (tenant_id, email), reqs in groups.items():
        t = _db.tenants.find_one({"id": tenant_id}) or {}
        score = reliability(t)

        # escalate the exhausted ones (3 reminders, still nothing)
        exhausted = [r for r in reqs if len(r.get("reminders") or []) >= MAX_REMINDERS]
        for r in exhausted:
            try:
                from features import exceptions_centre as exc
                exc.open_case(tenant_id, "missing_document",
                              detail_fr=f"« {r['label']} » demandé pour le {r['due_date']} — "
                                        f"{MAX_REMINDERS} relances de l'agent sans réponse.",
                              related_kind="doc_request", related_id=r["id"],
                              related_ref=r["label"])
                _db.doc_requests.update_one({"id": r["id"]},
                                            {"$set": {"status": "escalated",
                                                      "escalated_at": _now()}})
                # an escalated request is a completed (failed) cycle
                _db.tenants.update_one({"id": tenant_id},
                                       {"$inc": {"doc_reliability.asked": 1}})
                escalated += 1
            except Exception:
                pass

        due_items = [r for r in reqs
                     if len(r.get("reminders") or []) < MAX_REMINDERS
                     and _due_for_reminder(r, score, today)]
        if not due_items:
            skipped += len(reqs) - len(exhausted)
            continue

        nth = max(len(r.get("reminders") or []) for r in due_items) + 1
        client_name = t.get("legal_name") or t.get("name") or "Madame, Monsieur"
        cab_name = cabinet.get("name", "votre cabinet")
        items = [{"label": r["label"], "due_date": r["due_date"]} for r in due_items]

        channel = _pick_channel(due_items)
        if channel == "whatsapp":
            from services import whatsapp as wa
            phone = next((r.get("client_phone") for r in due_items
                          if r.get("client_phone")), "")
            res = wa.send_whatsapp(phone, _relance_text(cab_name, client_name, items, nth))
            dest = phone
        else:
            res = mailer.send(
                to=email, to_name=client_name,
                subject=f"Documents en attente — {cab_name}"
                        + (f" (relance {nth})" if nth > 1 else ""),
                html=_email_html(cab_name, client_name, items, nth),
            )
            dest = email

        stamp = {"at": _now(), "to": dest, "channel": channel, "nth": nth,
                 "sent": res.get("sent", False),
                 **({"error": res.get("reason") or res.get("error")}
                    if not res.get("sent") else {})}
        for r in due_items:
            _db.doc_requests.update_one({"id": r["id"]}, {"$push": {"reminders": stamp}})
        if res.get("sent"):
            sent += 1
        _audit("agent.reminder_sent", tenant_id=tenant_id, actor=agent_actor,
               object_kind="doc_request",
               object_id=",".join(r["id"] for r in due_items),
               after={"to": dest, "channel": channel,
                      "pieces": [r["label"] for r in due_items],
                      "nth": nth, "delivered": res.get("sent", False),
                      "reliability_score": score},
               detail={"triggered_by": triggered_by,
                       "agent": agent["user_email"]})

    return {"ok": True, "emails_sent": sent, "cases_opened": escalated,
            "waiting_not_due": skipped}
