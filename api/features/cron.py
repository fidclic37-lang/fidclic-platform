"""
Cron — the agent's alarm clock (S13).

Status: 🟢 Core.
Mounts at: /api/cron/agent-daily
Trigger: Vercel Cron (vercel.json), daily 07:00 UTC = 08:00/09:00 Paris —
         early enough that relances/drafts sit in the team's queues when the
         cabinet opens, late enough to count "today" correctly.

SECURITY
    No user auth here — the caller is Vercel's scheduler. Vercel sends
    `Authorization: Bearer $CRON_SECRET` automatically when the CRON_SECRET
    env var exists on the project. We refuse anything else with 401, so a
    random visitor cannot make the agent run on demand (that would let an
    outsider control WHEN emails leave, a spam/abuse lever).

DESIGN
    One pass over every active cabinet; each cabinet is isolated in its own
    try/except so one broken cabinet cannot stop the others' relances.
    Everything the agent does inside is already audited per-cabinet with
    triggered_by="cron".
"""
from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException

router = APIRouter(tags=["cron"])
_db = None


def init(db):
    global _db
    _db = db


@router.get("/api/cron/backup-weekly")
@router.post("/api/cron/backup-weekly")
def backup_weekly(authorization: str = Header(default="")):
    """S3 finale — the parachute. Weekly JSON snapshot of every business-
    critical collection, gzipped and EMAILED to the founder.

    Why email as the destination: at this scale (KBs, not GBs) the founder's
    inbox is an off-site, access-controlled, versioned store that costs
    nothing and needs zero new infrastructure. When data outgrows an
    attachment, this function is the single place that changes (S3/GCS).
    A backup that lives only inside the same database it protects is not a
    backup — that is why there is no "backups" collection.
    """
    secret = os.getenv("CRON_SECRET")
    if not secret:
        raise HTTPException(503, "CRON_SECRET non configuré.")
    if authorization != f"Bearer {secret}":
        raise HTTPException(401, "Non autorisé.")

    import base64
    import gzip
    import json as _json
    from datetime import datetime, timezone

    COLLECTIONS = ["users", "tenants", "cabinets", "cabinet_memberships",
                   "cabinet_links", "dossier_tasks", "fact_invoices",
                   "fact_received_invoices", "fact_credit_notes",
                   "fact_ereports", "subscriptions", "doc_requests",
                   "exception_cases", "customers"]
    dump = {}
    for name in COLLECTIONS:
        try:
            rows = []
            for d in getattr(_db, name).find():
                d.pop("_id", None)
                rows.append(d)
            dump[name] = rows
        except Exception:
            dump[name] = []
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw = _json.dumps(dump, default=str).encode()
    packed = base64.b64encode(gzip.compress(raw)).decode()

    from services import mailer
    key = mailer._api_key()
    if not key:
        return {"ok": False, "reason": "mailer_disabled"}
    to = os.getenv("BACKUP_EMAIL", mailer.SENDER_EMAIL)
    res = mailer._post({
        "sender": {"email": mailer.SENDER_EMAIL, "name": "FidClic Backup"},
        "to": [{"email": to}],
        "subject": f"[FidClic] Sauvegarde hebdomadaire {stamp}",
        "htmlContent": f"<p>Sauvegarde du {stamp} — {sum(len(v) for v in dump.values())} "
                       f"documents, {len(raw) // 1024} Ko avant compression. "
                       f"Conservez cet email : c'est votre copie hors-site.</p>",
        "attachment": [{"name": f"fidclic-backup-{stamp}.json.gz",
                        "content": packed}],
    }, key)
    return {"ok": True, "documents": sum(len(v) for v in dump.values()),
            "size_kb": len(raw) // 1024, "sent_to": to,
            "message_id": res.get("messageId")}


@router.get("/api/cron/agent-daily")
@router.post("/api/cron/agent-daily")
def agent_daily(authorization: str = Header(default="")):
    secret = os.getenv("CRON_SECRET")
    if not secret:
        raise HTTPException(503, "CRON_SECRET non configuré.")
    if authorization != f"Bearer {secret}":
        raise HTTPException(401, "Non autorisé.")

    from features.agent_collect import run_collection_for_cabinet
    from features.agent_billing import run_billing_for_cabinet
    from features.agent_gardien import run_gardien_for_cabinet

    summary: Dict[str, Any] = {"cabinets": 0, "emails_sent": 0,
                               "cases_opened": 0, "invoices_drafted": 0,
                               "gardien_findings": 0, "failures": []}
    for cab in _db.cabinets.find({"status": "active"}):
        summary["cabinets"] += 1
        try:
            c = run_collection_for_cabinet(cab["id"], "cron")
            summary["emails_sent"] += c.get("emails_sent", 0)
            summary["cases_opened"] += c.get("cases_opened", 0)
        except Exception as e:                                   # noqa: BLE001
            summary["failures"].append({"cabinet": cab.get("name"),
                                        "step": "collect", "error": str(e)[:120]})
        try:
            b = run_billing_for_cabinet(cab["id"], "cron")
            summary["invoices_drafted"] += b.get("invoices_drafted", 0)
        except Exception as e:                                   # noqa: BLE001
            summary["failures"].append({"cabinet": cab.get("name"),
                                        "step": "billing", "error": str(e)[:120]})
        try:
            from features import cabinet_os as co
            g = run_gardien_for_cabinet(cab["id"], co.agent_actor(cab["id"]), "cron")
            summary["gardien_findings"] += g.get("findings_created", 0)
        except Exception as e:                                   # noqa: BLE001
            summary["failures"].append({"cabinet": cab.get("name"),
                                        "step": "gardien", "error": str(e)[:120]})
    # Loyalty-side: day-27 "choose your plan" reminder for trialing tenants.
    try:
        from features.onboarding import run_trial_reminders
        summary["trial_reminders"] = run_trial_reminders()
    except Exception as e:                                       # noqa: BLE001
        summary["failures"].append({"step": "trial_reminders", "error": str(e)[:120]})
    return summary
