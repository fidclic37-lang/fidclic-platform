"""
Groupe témoin — what FidClic really brings in, measured (user, 2026-10-25).

« CA FidClic » counts every client back within 15 days of a message, but many
would have come anyway (a regular due back that week). So, on each group
send, 15 % of its clients — drawn at random, a new draw every send, so nobody
is left out for good — do NOT get the message. Fifteen days later both groups
are compared: what the messaged clients spent per head, minus what the
témoin spent per head, times the messaged clients, is « +X € grâce à
FidClic ». The clients who were coming anyway are in both groups alike, so
they cancel out.

    Held back    group campaigns (the composer, Autopilot, Copilote, « a
                 repéré ») and the relance automations (inactifs, géolocali-
                 sation). NEVER: anniversaire, récompense, bienvenue, a message
                 to one client (a group send never escapes by its label).
    Small sends  at least MIN_SEND_HOLD (4) held, so a small send still
                 measures, but never more than half of it and nobody under 3
                 clients (user, 2026-10-29: 3→1, 4–5→2, 6–7→3, 8–26→4,
                 27+→15 %). Splitting a big send in small ones escapes nothing.
    Owner        ON by default, switchable in Paramètres (« pas mesuré » then);
                 told in the composer, the automation editor, Paramètres and
                 Analyses. Only the counts are shown, never the témoin's
                 names, so the owner cannot message them aside and break it.
    Honest       a send counts once its 15 days are over; under MIN_HOLD
                 témoin clients the figure says « pas encore assez de données ».

Campaigns keep the témoin in `campaigns.holdout_ids` (`recipient_ids` stays
« sent to »). Automations write an `automation_log` row with status
« holdout » and no message, so « once per absence » and cool-downs treat the
client as handled, like a sent one.
"""
from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import require_role
from features.platform_access import require_admin
from models import TokenData

SHARE = 0.15                     # user, 2026-10-25: « 15 % rakho »
WINDOW_DAYS = 15                 # the CA FidClic window (fidclic_impact)
MIN_HOLD = 30                    # témoin clients before a figure is claimed
MIN_SEND_HOLD = 4                # user, 2026-10-29: « 3-4 ko nahi jaayega », not 15 % of a few
AUTOMATION_SCENARIOS = {"inactive", "geo"}          # the relance automations
SINGLE_TEMPLATES = {"client", "brain"}              # « Contacter » one client
READERS = ["business_owner", "administrateur", "manager"]

router = APIRouter(tags=["temoin"])
_db = None


def init(db):
    global _db
    _db = db


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


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Who is held back
# ---------------------------------------------------------------------------
def enabled(tid: Optional[str]) -> bool:
    if not tid:
        return False
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "temoin": 1}) or {}
    return (t.get("temoin") or {}).get("enabled", True) is not False


def hold_count(n: int) -> int:
    """How many of a send of n clients are held back: 15 %, at least 4, at
    most half — the messaged side is never the smaller one."""
    if n < 3:
        return 0
    return min(max(MIN_SEND_HOLD, int(n * SHARE)), n // 2)


def for_campaign(template: Optional[str], n: int = 2) -> bool:
    """Only a message to ONE client is free of the témoin; the « client » /
    « brain » label comes from the request body, so it frees nothing else
    (audit P25: a send to everyone labelled « client » escaped)."""
    return n != 1 or (template or "").split(":")[0] not in SINGLE_TEMPLATES


def split(tid: str, people: Sequence[Dict[str, Any]], seed: str,
          template: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(sent, held back) for a group campaign; nobody held when switched off,
    for one client, or for a send too small to spare one."""
    people = list(people)
    k = hold_count(len(people))
    if not k or not for_campaign(template, len(people)) or not enabled(tid):
        return people, []
    rng = random.Random(f"temoin:{seed}")
    held_ids = {c["id"] for c in rng.sample(sorted(people, key=lambda c: c["id"]), k)}
    return [c for c in people if c["id"] not in held_ids], [c for c in people if c["id"] in held_ids]


def holds_automation(tid: str, row: Dict[str, Any], cust_id: str, at: datetime) -> bool:
    """One relance automation message: is this client the témoin this time?
    A fresh draw per message (the moment is in the key), reproducible."""
    if row.get("scenario") not in AUTOMATION_SCENARIOS or not enabled(tid):
        return False
    h = hashlib.sha256(f"{row.get('id')}:{cust_id}:{at.isoformat()}".encode()).digest()
    return int.from_bytes(h[:4], "big") / 2 ** 32 < SHARE


# ---------------------------------------------------------------------------
# What it shows
# ---------------------------------------------------------------------------
def _rows_campaign(c: Dict[str, Any]) -> List[Tuple[str, datetime, bool]]:
    at = _aware(c.get("sent_at"))
    if not at or not c.get("holdout_ids"):
        return []
    return ([(i, at, False) for i in c.get("recipient_ids") or []]
            + [(i, at, True) for i in c.get("holdout_ids") or []])


def _automation_rows(q: Dict[str, Any]) -> Dict[str, List[Tuple[str, datetime, bool]]]:
    """Per automation, its messages and témoin since its first témoin (sends
    from before had none to compare with)."""
    logs = list(_db.automation_log.find({**q, "scenario": {"$in": list(AUTOMATION_SCENARIOS)},
                                         "status": {"$in": ["sent", "holdout"]}},
                                        {"_id": 0, "automation_id": 1, "customer_id": 1, "sent_at": 1, "status": 1,
                                         "tenant_id": 1}))
    first: Dict[str, datetime] = {}
    for g in logs:
        t = _aware(g.get("sent_at"))
        if g.get("status") == "holdout" and t and (g["automation_id"] not in first or t < first[g["automation_id"]]):
            first[g["automation_id"]] = t
    out: Dict[str, List[Tuple[str, datetime, bool]]] = defaultdict(list)
    for g in logs:
        t = _aware(g.get("sent_at"))
        start = first.get(g.get("automation_id"))
        if t and start and t >= start:
            out[g["automation_id"]].append((g["customer_id"], t, g.get("status") == "holdout"))
    return out


def measure(tid: str, rows: Iterable[Tuple[str, datetime, bool]], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Both groups' return and spend in the WINDOW_DAYS after each message —
    only messages whose window is over — and the difference it made."""
    now = now or _now()
    rows = list(rows)
    window = timedelta(days=WINDOW_DAYS)
    done = [r for r in rows if r[1] + window <= now]
    pending = len(rows) - len(done)
    g = {False: {"n": 0, "came": 0, "revenue": 0.0}, True: {"n": 0, "came": 0, "revenue": 0.0}}
    if done:
        ids = list({r[0] for r in done})
        lo = min(r[1] for r in done)
        hi = max(r[1] for r in done) + window
        visits: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)
        for v in _db.visits.find({"tenant_id": tid, "customer_id": {"$in": ids}, "visit_time": {"$gte": lo, "$lte": hi}},
                                 {"_id": 0, "customer_id": 1, "visit_time": 1, "amount_paid": 1}):
            t = _aware(v.get("visit_time"))
            if t:
                visits[v["customer_id"]].append((t, float(v.get("amount_paid") or 0)))
        for cid, at, held in done:
            mine = [a for t, a in visits.get(cid, []) if at < t <= at + window]
            s = g[held]
            s["n"] += 1
            s["came"] += bool(mine)
            s["revenue"] += sum(mine)
    return _figures(g[False], g[True], pending)


def _figures(sent: Dict[str, Any], hold: Dict[str, Any], pending: int = 0) -> Dict[str, Any]:
    def side(s):
        n = s["n"]
        return {"n": n, "came": s["came"], "rate": round(100 * s["came"] / n, 1) if n else None,
                "revenue": round(s["revenue"], 2), "per_client": round(s["revenue"] / n, 2) if n else None}
    a, b = side(sent), side(hold)
    enough = b["n"] >= MIN_HOLD and a["n"] > 0
    extra = round((a["per_client"] - b["per_client"]) * a["n"], 2) if a["n"] and b["n"] else None
    extra_visits = round((a["came"] / a["n"] - b["came"] / b["n"]) * a["n"]) if a["n"] and b["n"] else None
    return {"sent": a, "temoin": b, "pending": pending, "enough": enough, "min_hold": MIN_HOLD,
            "extra_revenue": extra, "extra_clients": extra_visits,
            "points": round(a["rate"] - b["rate"], 1) if a["rate"] is not None and b["rate"] is not None else None,
            "window_days": WINDOW_DAYS, "share": int(SHARE * 100)}


def campaign_block(tid: str, c: Dict[str, Any], now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The campaign detail's « Groupe témoin »: counts, never names."""
    if not c.get("holdout_ids"):
        return None
    out = measure(tid, _rows_campaign(c), now)
    at = _aware(c.get("sent_at"))
    out["counts"] = {"sent": len(c.get("recipient_ids") or []), "temoin": len(c["holdout_ids"])}
    out["ready_on"] = (at + timedelta(days=WINDOW_DAYS)).isoformat() if at else None
    return out


def automation_block(tid: str, automation_id: str, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    rows = _automation_rows({"tenant_id": tid, "automation_id": automation_id}).get(automation_id)
    if not rows:
        return None
    out = measure(tid, rows, now)
    out["counts"] = {"sent": sum(1 for r in rows if not r[2]), "temoin": sum(1 for r in rows if r[2])}
    return out


def period(tid: str, since: datetime, until: datetime, now: Optional[datetime] = None,
           customer_ids: Optional[set] = None) -> Dict[str, Any]:
    """Analyses › Impact FidClic: every measured send of the period, pooled,
    and split by campagnes / automatisations."""
    now = now or _now()
    rng = {"$gte": since, "$lt": until}
    keep = (lambda r: r[0] in customer_ids) if customer_ids is not None else (lambda r: True)
    camp_rows: List[Tuple[str, datetime, bool]] = []
    for c in _db.campaigns.find({"tenant_id": tid, "sent_at": rng, "holdout_ids.0": {"$exists": True}},
                                {"_id": 0, "recipient_ids": 1, "holdout_ids": 1, "sent_at": 1}):
        camp_rows += [r for r in _rows_campaign(c) if keep(r)]
    auto_rows = [r for rows in _automation_rows({"tenant_id": tid, "sent_at": rng}).values() for r in rows if keep(r)]
    out = measure(tid, camp_rows + auto_rows, now)
    out["by"] = {"campagnes": measure(tid, camp_rows, now), "automatisations": measure(tid, auto_rows, now)}
    out["enabled"] = enabled(tid)
    return out


# ---------------------------------------------------------------------------
# Paramètres › Groupe témoin
# ---------------------------------------------------------------------------
class TemoinIn(BaseModel):
    enabled: bool


@router.get("/api/owner/temoin")
def get_settings(token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    return {"enabled": enabled(token_data.tenant_id), "share": int(SHARE * 100), "window_days": WINDOW_DAYS,
            "min_hold": MIN_HOLD, "min_hold_send": MIN_SEND_HOLD, "can_edit": token_data.role == "business_owner"}


@router.put("/api/owner/temoin")
def put_settings(body: TemoinIn, token_data: TokenData = Depends(require_role(["business_owner"]))):
    _db.tenants.update_one({"id": token_data.tenant_id},
                           {"$set": {"temoin": {"enabled": bool(body.enabled), "changed_at": _now()}}})
    return {"enabled": bool(body.enabled)}


# ---------------------------------------------------------------------------
# Super admin › Précision: the uplift journal, every shop, by sector
# ---------------------------------------------------------------------------
@router.get("/api/admin/ai/uplift")
def admin_uplift(_: TokenData = Depends(require_admin("ai"))):
    now = _now()
    sectors: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"shops": set(), "sends": 0, "rows": []})
    tenants = {t["id"]: (t.get("sector") or "autre") for t in _db.tenants.find({}, {"_id": 0, "id": 1, "sector": 1})}
    for c in _db.campaigns.find({"holdout_ids.0": {"$exists": True}},
                                {"_id": 0, "tenant_id": 1, "recipient_ids": 1, "holdout_ids": 1, "sent_at": 1}):
        s = sectors[tenants.get(c["tenant_id"], "autre")]
        s["shops"].add(c["tenant_id"])
        s["sends"] += 1
        s["rows"].append((c["tenant_id"], _rows_campaign(c)))
    for aid, rows in _automation_rows({}).items():
        a = _db.automations.find_one({"id": aid}, {"_id": 0, "tenant_id": 1}) or {}
        tid = a.get("tenant_id")
        if not tid:
            continue
        s = sectors[tenants.get(tid, "autre")]
        s["shops"].add(tid)
        s["sends"] += 1
        s["rows"].append((tid, rows))
    out = []
    total = {False: {"n": 0, "came": 0, "revenue": 0.0}, True: {"n": 0, "came": 0, "revenue": 0.0}}
    for sector, s in sorted(sectors.items()):
        g = {False: {"n": 0, "came": 0, "revenue": 0.0}, True: {"n": 0, "came": 0, "revenue": 0.0}}
        pending = 0
        for tid, rows in s["rows"]:
            m = measure(tid, rows, now)
            pending += m["pending"]
            for held, key in ((False, "sent"), (True, "temoin")):
                for k in ("n", "came", "revenue"):
                    g[held][k] += m[key][k]
                    total[held][k] += m[key][k]
        f = _figures(g[False], g[True], pending)
        out.append({"sector": sector, "shops": len(s["shops"]), "sends": s["sends"], **f,
                    "per_100": round(f["extra_revenue"] / f["sent"]["n"] * 100, 2)
                    if f["extra_revenue"] is not None and f["sent"]["n"] else None})
    return {"sectors": out, "total": _figures(total[False], total[True]),
            "share": int(SHARE * 100), "window_days": WINDOW_DAYS, "min_hold": MIN_HOLD}
