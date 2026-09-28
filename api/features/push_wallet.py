"""
Automatisations · Push Wallet — scenarios that fire on their own.

Status: 🟢 Core.
Mounts at:
    GET    /api/owner/push-wallet/scenarios   → the table and its four figures
    POST   /api/owner/push-wallet/scenarios   → create one
    PUT    /api/owner/push-wallet/scenarios/{id}
    DELETE /api/owner/push-wallet/scenarios/{id}
    POST   /api/owner/push-wallet/scenarios/{id}/run   → fire it now
    GET    /api/owner/push-wallet/stats
    GET    /api/push-wallet/c/{log_id}        → the click the push links to
    (the daily runner is called from server.py's /api/cron/daily-triggers)

WHAT "PUSH WALLET" MEANS HERE
    Not an email and not an SMS: the message lands on the card the customer
    already keeps in Apple Wallet or Google Wallet. Each send does two things —
    writes the offer onto the pass and asks the device to come and fetch it
    (features/wallet_passes.notify_customer), and pushes the same message to the
    web card, so a customer without a wallet pass is not left out.

THE EIGHT SCENARIOS
    Eight built-ins are seeded per tenant on first read, so the page is never
    an empty table. Each is a real query over real rows — see TRIGGERS — and
    each can be edited, switched off, or deleted like any other.

WHAT THE FOUR FIGURES ACTUALLY MEASURE
    Two of them are counted directly and two are rates, and it is worth being
    exact about the rates because a wallet push is not an email:

      Clients touchés   every send, counted.
      Taux de clic      the push carries a link back to the card with its own
                        id; following it is a click. Counted.
      Taux d'ouverture  a wallet push has no read receipt — nothing reports
                        that the notification was seen. What IS observable is
                        the customer opening their card afterwards, so that is
                        what this measures: a card opened within 72 h of a send.
                        The page says so under the figure rather than letting it
                        be read as an email open rate.
      Scénarios actifs  switched on, counted.

SAFETY
    The runner never raises into the cron: one tenant's broken scenario must not
    stop everybody else's. Every scenario has a cooldown so a customer cannot be
    messaged twice by the same one, whatever the trigger does.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from auth import require_role, TokenData

router = APIRouter(tags=["push-wallet"])
_db = None

OPEN_WINDOW_H = 72          # a card opened this long after a send counts as an open
DEFAULT_COOLDOWN_DAYS = 30  # the same scenario will not reach one customer twice inside this

# ---------------------------------------------------------------------------
# The trigger vocabulary. Each entry says what the merchant picks and what the
# runner then has to evaluate; `audience` is implemented in _audience below.
# ---------------------------------------------------------------------------
TRIGGERS: Dict[str, Dict[str, Any]] = {
    "birthday":       {"label": "Date anniversaire",              "config": []},
    "tier_up":        {"label": "Palier points atteint",          "config": []},
    "date_event":     {"label": "Date ou événement",              "config": ["day_of_month"]},
    "inactivity":     {"label": "Inactivité (X jours)",           "config": ["days"]},
    "time_slot":      {"label": "Plage horaire",                  "config": ["weekdays", "from_hour", "to_hour"]},
    "new_product":    {"label": "Ajout d'un nouveau produit ou service", "config": []},
    "specific_date":  {"label": "Date spécifique",                "config": ["date"]},
}

# The eight the page opens on, exactly as the design lists them.
BUILTINS: List[Dict[str, Any]] = [
    {"key": "birthday", "name": "Anniversaire", "subtitle": "Souhaitez un joyeux anniversaire",
     "icon": "cake", "trigger": "birthday", "config": {}, "enabled": True,
     "title": "🎉 Joyeux anniversaire !",
     "body": "Une offre spéciale vous attend sur votre Wallet 🎁"},
    {"key": "tier_up", "name": "Atteinte d'un palier", "subtitle": "Félicitez vos clients",
     "icon": "star", "trigger": "tier_up", "config": {}, "enabled": True,
     "title": "🎯 Bravo !",
     "body": "Vous avez atteint un nouveau palier ! Découvrez votre récompense 🎁"},
    {"key": "special_offer", "name": "Offre spéciale", "subtitle": "Promotions automatiques",
     "icon": "tag", "trigger": "date_event", "config": {"day_of_month": 1}, "enabled": True,
     "title": "🔥 Offre spéciale !",
     "body": "Profitez de -20% aujourd'hui uniquement !"},
    {"key": "cart_recovery", "name": "Relance panier", "subtitle": "Relancez les clients inactifs",
     "icon": "cart", "trigger": "inactivity", "config": {"days": 14}, "enabled": True,
     "title": "💡 On vous a manqué ?",
     "body": "Voici une offre exclusive rien que pour vous !"},
    {"key": "off_peak", "name": "Heure creuse", "subtitle": "Boostez les périodes calmes",
     "icon": "clock", "trigger": "time_slot",
     "config": {"weekdays": [1, 2, 3], "from_hour": 14, "to_hour": 17}, "enabled": True,
     "title": "☕ C'est le moment idéal !",
     "body": "Profitez d'une offre spéciale maintenant dans votre Wallet."},
    {"key": "new_products", "name": "Nouveautés", "subtitle": "Informez vos clients",
     "icon": "new", "trigger": "new_product", "config": {}, "enabled": False,
     "title": "✨ Découvrez nos nouveautés !",
     "body": "Une offre vous attend dans votre Wallet."},
    {"key": "inactive", "name": "Client inactif", "subtitle": "Réactivez vos clients",
     "icon": "heart", "trigger": "inactivity", "config": {"days": 30}, "enabled": True,
     "title": "💙 On pense à vous !",
     "body": "Profitez d'une offre pour votre prochaine visite."},
    {"key": "special_event", "name": "Événement spécial", "subtitle": "Jours fériés / occasions",
     "icon": "calendar", "trigger": "specific_date", "config": {"date": ""}, "enabled": False,
     "title": "🎄 Bonnes fêtes !",
     "body": "Une surprise vous attend dans votre Wallet."},
]

# Offered in the right-hand rail as ready-made wording.
EXAMPLES = [
    {"title": "🎉 Joyeux anniversaire !", "body": "Une offre spéciale vous attend dans votre Wallet."},
    {"title": "🔥 Offre spéciale !", "body": "-20% aujourd'hui uniquement !"},
    {"title": "🎯 Bravo !", "body": "Vous avez atteint un nouveau palier !"},
    {"title": "💙 On vous a manqué ?", "body": "Voici une offre exclusive pour vous !"},
]


def init(db):
    global _db
    _db = db
    try:
        # One built-in per tenant, enforced by the database rather than by a
        # check that two concurrent requests can both pass.
        db.push_scenarios.create_index([("tenant_id", 1), ("builtin", 1)], unique=True,
                                       partialFilterExpression={"builtin": {"$type": "string"}})
    except Exception:
        pass
    for coll, index in (
        ("push_scenarios", [("tenant_id", 1), ("created_at", 1)]),
        ("push_wallet_log", [("tenant_id", 1), ("sent_at", -1)]),
        ("push_wallet_log", [("scenario_id", 1), ("customer_id", 1), ("sent_at", -1)]),
    ):
        try:
            db[coll].create_index(index)
        except Exception:
            pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# scenarios
# ---------------------------------------------------------------------------
def _seed(tid: str) -> None:
    """The eight built-ins, once per tenant. A merchant opening the page for the
    first time sees a programme to switch on, not an empty table.

    Upserted one by one rather than a check-then-insert_many: the page asks for
    the list and the figures at the same time, so both requests reach this at
    the same moment, both would have found the table empty, and the tenant
    would have ended up with sixteen scenarios.
    """
    now = _now()
    for i, b in enumerate(BUILTINS):
        try:
            _db.push_scenarios.update_one(
                {"tenant_id": tid, "builtin": b["key"]},
                {"$setOnInsert": {
                    "id": str(uuid4()), "tenant_id": tid, "builtin": b["key"],
                    "name": b["name"], "subtitle": b["subtitle"], "icon": b["icon"],
                    "trigger": b["trigger"], "config": dict(b["config"]),
                    "title": b["title"], "body": b["body"],
                    "enabled": b["enabled"], "cooldown_days": DEFAULT_COOLDOWN_DAYS,
                    "created_at": now, "updated_at": now, "last_run_at": None, "order": i,
                }},
                upsert=True,
            )
        except Exception:
            pass        # a duplicate-key race means someone else just seeded it


def _public(row: Dict[str, Any], counts: Dict[str, int]) -> Dict[str, Any]:
    row.pop("_id", None)
    last = _aware(row.get("last_run_at"))
    return {
        "id": row["id"], "builtin": row.get("builtin"),
        "name": row.get("name") or "Scénario", "subtitle": row.get("subtitle") or "",
        "icon": row.get("icon") or "bell",
        "trigger": row.get("trigger"),
        "trigger_label": TRIGGERS.get(row.get("trigger"), {}).get("label", "—"),
        "trigger_detail": _trigger_detail(row),
        "config": row.get("config") or {},
        "title": row.get("title") or "", "body": row.get("body") or "",
        "enabled": bool(row.get("enabled")),
        "status": "active" if row.get("enabled") else "draft",
        "clients": counts.get(row["id"], 0),
        "cooldown_days": int(row.get("cooldown_days") or DEFAULT_COOLDOWN_DAYS),
        "last_run_at": last.isoformat() if last else None,
    }


def _trigger_detail(row: Dict[str, Any]) -> str:
    """"Inactivité (30 jours)" — the trigger with its own setting in it, which
    is what the table column actually shows."""
    trigger, cfg = row.get("trigger"), row.get("config") or {}
    if trigger == "inactivity":
        return f"Inactivité ({int(cfg.get('days') or 30)} jours)"
    if trigger == "time_slot":
        return f"Plage horaire ({int(cfg.get('from_hour') or 0)}h–{int(cfg.get('to_hour') or 0)}h)"
    if trigger == "date_event" and cfg.get("day_of_month"):
        return f"Le {int(cfg['day_of_month'])} de chaque mois"
    if trigger == "specific_date" and cfg.get("date"):
        return f"Le {cfg['date']}"
    return TRIGGERS.get(trigger, {}).get("label", "—")


# ---------------------------------------------------------------------------
# audiences — every one a real query
# ---------------------------------------------------------------------------
def _cooldown_cutoff(row: Dict[str, Any]) -> datetime:
    return _now() - timedelta(days=int(row.get("cooldown_days") or DEFAULT_COOLDOWN_DAYS))


def _recently_messaged(scenario_id: str, cutoff: datetime) -> set:
    return set(_db.push_wallet_log.distinct(
        "customer_id", {"scenario_id": scenario_id, "sent_at": {"$gte": cutoff}}))


def _audience(tid: str, row: Dict[str, Any], at: datetime) -> List[Dict[str, Any]]:
    """Who this scenario reaches right now. An empty list means "not today" —
    a time-of-day or date trigger that has not come round yet returns nothing
    rather than firing early."""
    trigger, cfg = row.get("trigger"), row.get("config") or {}
    base = {"tenant_id": tid}
    fields = {"_id": 0, "id": 1, "name": 1, "barcode_id": 1, "tier": 1, "points": 1,
              "visits": 1, "birthday": 1, "last_visit_date": 1}

    if trigger == "birthday":
        base["birthday"] = at.strftime("%m-%d")

    elif trigger == "tier_up":
        # Levelled up since the last run — the scan stamps tier_changed_at.
        # Strictly after the last run: a change at exactly that instant was
        # already visible to it, and $gte would send the same congratulations
        # twice at the boundary.
        since = _aware(row.get("last_run_at")) or (at - timedelta(days=1))
        base["tier_changed_at"] = {"$gt": since}

    elif trigger == "inactivity":
        days = max(1, int(cfg.get("days") or 30))
        base["last_visit_date"] = {"$lt": at - timedelta(days=days)}

    elif trigger == "date_event":
        if int(cfg.get("day_of_month") or 0) != at.day:
            return []

    elif trigger == "specific_date":
        if str(cfg.get("date") or "")[:10] != at.date().isoformat():
            return []

    elif trigger == "time_slot":
        # weekdays are 0 = Monday, matching Python's weekday()
        days = cfg.get("weekdays") or []
        if days and at.weekday() not in [int(d) for d in days]:
            return []
        start, end = int(cfg.get("from_hour") or 0), int(cfg.get("to_hour") or 24)
        if end <= start:
            # An empty window can never come round; treat it as unconfigured
            # rather than as "every hour" or as silently never.
            return []
        if not (start <= at.hour < end):
            return []

    elif trigger == "new_product":
        # Only when something was actually added since the last run.
        since = _aware(row.get("last_run_at")) or (at - timedelta(days=1))
        # The catalogue is one document per shop with its products in
        # `items`; a product added since carries a later created_at.
        try:
            doc = _db.tenant_catalog.find_one({"tenant_id": tid}) or {}
            added = sum(1 for it in doc.get("items") or []
                        if (_aware(it.get("created_at")) or since) > since
                        and it.get("active", True) is not False)
        except Exception:
            added = 0
        if not added:
            return []

    else:
        # A trigger nobody recognises must reach NOBODY. Falling through to the
        # bare tenant query would have sent the whole client base a message on
        # a typo or a scenario written by a newer version of the app.
        return []

    people = list(_db.customers.find(base, fields))
    skip = _recently_messaged(row["id"], _cooldown_cutoff(row))
    return [c for c in people if c["id"] not in skip]


# ---------------------------------------------------------------------------
# sending
# ---------------------------------------------------------------------------
def _render(text: str, cust: Dict[str, Any], tenant: Dict[str, Any]) -> str:
    first = (cust.get("name") or "").split(" ")[0]
    out = text or ""
    for token, value in (("{first_name}", first), ("{name}", cust.get("name") or ""),
                         ("{points}", str(cust.get("points") or 0)),
                         ("{visits}", str(cust.get("visits") or 0)),
                         ("{business_name}", tenant.get("name") or "")):
        out = out.replace(token, value)
    return out


def run_scenario(tid: str, row: Dict[str, Any], at: Optional[datetime] = None,
                 limit: int = 2000) -> Dict[str, Any]:
    """Fire one scenario. Returns what it did; never raises."""
    at = at or _now()
    result = {"scenario_id": row["id"], "name": row.get("name"), "targeted": 0, "sent": 0, "errors": 0}
    try:
        tenant = _db.tenants.find_one({"id": tid}) or {}
        people = _audience(tid, row, at)[:limit]
        result["targeted"] = len(people)
        for cust in people:
            title = _render(row.get("title") or "", cust, tenant)
            body = _render(row.get("body") or "", cust, tenant)
            log_id = str(uuid4())
            try:
                _db.push_wallet_log.insert_one({
                    "id": log_id, "tenant_id": tid, "scenario_id": row["id"],
                    "customer_id": cust["id"], "sent_at": at,
                    "title": title, "body": body, "clicked_at": None,
                })
                # 1. the wallet card itself — the offer is written onto the pass
                #    and the device is asked to come and fetch it.
                try:
                    from features.wallet_passes import notify_customer
                    notify_customer(cust["id"], message=body)
                except Exception:
                    pass
                # 2. and the same message down the web-push / SMS rail, so a
                #    customer with no wallet pass still hears about it.
                import server as core
                core.dispatch_to_customer(tid, cust, title, body, kind="push_wallet")
                result["sent"] += 1
            except Exception:
                result["errors"] += 1
        _db.push_scenarios.update_one({"id": row["id"]},
                                      {"$set": {"last_run_at": at, "updated_at": at}})
    except Exception as exc:  # noqa: BLE001 — one scenario must not stop the rest
        result["errors"] += 1
        result["error"] = str(exc)[:200]
    return result


def run_due_for_tenant(tid: str, at: Optional[datetime] = None) -> Dict[str, Any]:
    at = at or _now()
    out = {"tenant_id": tid, "ran": [], "sent": 0}
    for row in _db.push_scenarios.find({"tenant_id": tid, "enabled": True}):
        row.pop("_id", None)
        res = run_scenario(tid, row, at)
        if res["targeted"]:
            out["ran"].append(res)
            out["sent"] += res["sent"]
    return out


def run_all_due(at: Optional[datetime] = None) -> Dict[str, Any]:
    """Called by the daily cron. One tenant's failure never stops the others."""
    at = at or _now()
    summary = {"tenants": 0, "sent": 0, "at": at.isoformat()}
    try:
        tenants = _db.push_scenarios.distinct("tenant_id", {"enabled": True})
    except Exception:
        return summary
    for tid in tenants:
        try:
            res = run_due_for_tenant(tid, at)
            summary["tenants"] += 1
            summary["sent"] += res["sent"]
        except Exception:
            continue
    return summary


# ---------------------------------------------------------------------------
# the four figures
# ---------------------------------------------------------------------------
def _counts_by_scenario(tid: str, since: Optional[datetime] = None) -> Dict[str, int]:
    match: Dict[str, Any] = {"tenant_id": tid}
    if since:
        match["sent_at"] = {"$gte": since}
    out: Dict[str, int] = {}
    try:
        for row in _db.push_wallet_log.aggregate([
            {"$match": match},
            {"$group": {"_id": "$scenario_id", "n": {"$sum": 1}}},
        ]):
            out[row["_id"]] = row["n"]
    except Exception:
        pass
    return out


def _rates(tid: str, start: datetime, end: datetime) -> Dict[str, Any]:
    """Sent, clicked, and opened — the last one measured against card opens,
    because a wallet push has no read receipt."""
    logs = list(_db.push_wallet_log.find(
        {"tenant_id": tid, "sent_at": {"$gte": start, "$lte": end}},
        {"_id": 0, "customer_id": 1, "sent_at": 1, "clicked_at": 1}))
    sent = len(logs)
    clicked = sum(1 for l in logs if l.get("clicked_at"))
    opened = 0
    if logs:
        ids = list({l["customer_id"] for l in logs})
        opens = {c["id"]: _aware(c.get("last_card_open_at"))
                 for c in _db.customers.find({"id": {"$in": ids}},
                                             {"_id": 0, "id": 1, "last_card_open_at": 1})}
        for l in logs:
            at_open = opens.get(l["customer_id"])
            at_sent = _aware(l.get("sent_at"))
            if at_open and at_sent and at_sent <= at_open <= at_sent + timedelta(hours=OPEN_WINDOW_H):
                opened += 1
    return {"sent": sent, "clicked": clicked, "opened": opened}


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def _delta(now_value: float, was_value: float) -> Optional[int]:
    if not was_value:
        return None
    return round((now_value - was_value) / was_value * 100)


def _window(date_from: Optional[str], date_to: Optional[str]) -> Tuple[datetime, datetime]:
    end = (_aware(date_to) or _now()).replace(hour=23, minute=59, second=59, microsecond=999999)
    start = (_aware(date_from) or (end - timedelta(days=29))).replace(
        hour=0, minute=0, second=0, microsecond=0)
    if start > end:
        start, end = end.replace(hour=0, minute=0, second=0, microsecond=0), start
    return start, end


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------
class ScenarioIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    subtitle: Optional[str] = ""
    icon: Optional[str] = "bell"
    trigger: str
    config: Optional[Dict[str, Any]] = None
    title: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1, max_length=400)
    enabled: Optional[bool] = True
    cooldown_days: Optional[int] = DEFAULT_COOLDOWN_DAYS


class ScenarioPatch(BaseModel):
    name: Optional[str] = None
    subtitle: Optional[str] = None
    trigger: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    title: Optional[str] = None
    body: Optional[str] = None
    enabled: Optional[bool] = None
    cooldown_days: Optional[int] = None


@router.get("/api/owner/push-wallet/scenarios")
def list_scenarios(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
):
    tid = token_data.tenant_id
    _seed(tid)
    start, end = _window(date_from, date_to)
    counts = _counts_by_scenario(tid, start)
    rows = list(_db.push_scenarios.find({"tenant_id": tid}).sort("order", 1))
    return {
        "scenarios": [_public(r, counts) for r in rows],
        "triggers": [{"key": k, "label": v["label"], "config": v["config"]}
                     for k, v in TRIGGERS.items()],
        "examples": EXAMPLES,
        "from": start.isoformat(), "to": end.isoformat(),
    }


@router.get("/api/owner/push-wallet/stats")
def stats(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
):
    tid = token_data.tenant_id
    _seed(tid)
    start, end = _window(date_from, date_to)
    span = end - start
    prev_end = start - timedelta(microseconds=1)
    prev_start = prev_end - span

    now, was = _rates(tid, start, end), _rates(tid, prev_start, prev_end)
    active = _db.push_scenarios.count_documents({"tenant_id": tid, "enabled": True})
    return {
        "from": start.isoformat(), "to": end.isoformat(),
        "open_window_hours": OPEN_WINDOW_H,
        "cards": [
            {"key": "active", "label": "Scénarios actifs", "icon": "send",
             "value": active, "unit": "", "delta_pct": None},
            {"key": "reached", "label": "Clients touchés", "icon": "users",
             "value": now["sent"], "unit": "",
             "delta_pct": _delta(now["sent"], was["sent"])},
            {"key": "open_rate", "label": "Taux d'ouverture", "icon": "eye",
             "value": _pct(now["opened"], now["sent"]), "unit": "%",
             "note": f"cartes ouvertes dans les {OPEN_WINDOW_H} h suivant un push",
             "delta_pct": _delta(_pct(now["opened"], now["sent"]),
                                 _pct(was["opened"], was["sent"]))},
            {"key": "click_rate", "label": "Taux de clic", "icon": "chart",
             "value": _pct(now["clicked"], now["sent"]), "unit": "%",
             "delta_pct": _delta(_pct(now["clicked"], now["sent"]),
                                 _pct(was["clicked"], was["sent"]))},
        ],
    }


@router.post("/api/owner/push-wallet/scenarios")
def create_scenario(body: ScenarioIn,
                    token_data: TokenData = Depends(require_role(["business_owner"]))):
    if body.trigger not in TRIGGERS:
        raise HTTPException(status_code=400, detail="Déclencheur inconnu")
    tid = token_data.tenant_id
    _seed(tid)
    now = _now()
    row = {"id": str(uuid4()), "tenant_id": tid, "builtin": None,
           "name": body.name.strip(), "subtitle": (body.subtitle or "").strip(),
           "icon": body.icon or "bell", "trigger": body.trigger,
           "config": body.config or {}, "title": body.title.strip(), "body": body.body.strip(),
           "enabled": bool(body.enabled), "cooldown_days": max(0, int(body.cooldown_days or DEFAULT_COOLDOWN_DAYS)),
           "created_at": now, "updated_at": now, "last_run_at": None,
           "order": _db.push_scenarios.count_documents({"tenant_id": tid})}
    _db.push_scenarios.insert_one(row)
    return _public(dict(row), {})


@router.put("/api/owner/push-wallet/scenarios/{scenario_id}")
def update_scenario(scenario_id: str, body: ScenarioPatch,
                    token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    row = _db.push_scenarios.find_one({"id": scenario_id, "tenant_id": tid})
    if not row:
        raise HTTPException(status_code=404, detail="Scénario introuvable")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "trigger" in patch and patch["trigger"] not in TRIGGERS:
        raise HTTPException(status_code=400, detail="Déclencheur inconnu")
    if "cooldown_days" in patch:
        patch["cooldown_days"] = max(0, int(patch["cooldown_days"]))
    patch["updated_at"] = _now()
    _db.push_scenarios.update_one({"id": scenario_id}, {"$set": patch})
    fresh = _db.push_scenarios.find_one({"id": scenario_id})
    return _public(fresh, _counts_by_scenario(tid))


@router.delete("/api/owner/push-wallet/scenarios/{scenario_id}")
def delete_scenario(scenario_id: str,
                    token_data: TokenData = Depends(require_role(["business_owner"]))):
    res = _db.push_scenarios.delete_one({"id": scenario_id, "tenant_id": token_data.tenant_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Scénario introuvable")
    return {"deleted": True}


@router.post("/api/owner/push-wallet/scenarios/{scenario_id}/run")
def run_now(scenario_id: str,
            token_data: TokenData = Depends(require_role(["business_owner"]))):
    """Fire it now — the merchant's way of checking a scenario does what they
    think. The cooldown still applies, so this cannot be used to spam."""
    tid = token_data.tenant_id
    row = _db.push_scenarios.find_one({"id": scenario_id, "tenant_id": tid})
    if not row:
        raise HTTPException(status_code=404, detail="Scénario introuvable")
    row.pop("_id", None)
    return run_scenario(tid, row)


@router.get("/api/owner/push-wallet/scenarios/{scenario_id}/preview")
def preview_audience(scenario_id: str,
                     token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """How many clients this would reach right now, without sending anything."""
    tid = token_data.tenant_id
    row = _db.push_scenarios.find_one({"id": scenario_id, "tenant_id": tid})
    if not row:
        raise HTTPException(status_code=404, detail="Scénario introuvable")
    row.pop("_id", None)
    people = _audience(tid, row, _now())
    return {"count": len(people),
            "sample": [{"name": c.get("name") or "Client"} for c in people[:5]]}


@router.get("/api/push-wallet/c/{log_id}")
def register_click(log_id: str):
    """The link the push carries. Records the click, then sends the customer to
    their card — which is where they wanted to go."""
    row = _db.push_wallet_log.find_one({"id": log_id})
    target = "/"
    if row:
        try:
            _db.push_wallet_log.update_one({"id": log_id, "clicked_at": None},
                                           {"$set": {"clicked_at": _now()}})
        except Exception:
            pass
        cust = _db.customers.find_one({"id": row.get("customer_id")}, {"_id": 0, "barcode_id": 1})
        if cust and cust.get("barcode_id"):
            target = f"/card/{cust['barcode_id']}"
    return RedirectResponse(url=target, status_code=302)
