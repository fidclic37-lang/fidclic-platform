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

ESTABLISHMENTS
    A scenario is the whole shop's. An administrateur may give it its own
    message, or switch it on or off, for ITS establishments: that is kept
    apart, per establishment (push_scenario_overrides), and a client hears the
    version of the establishment it last visited. The owner sees those
    versions on the page, and the owner's own change applies to every
    establishment — it replaces any version of the fields it touched. A
    manager reads the page and changes nothing. Figures follow the
    establishment menu (features/store_scope.py).

AUTOMATIC OR "À VALIDER"
    Decided with the user: the birthday goes out on its own. Every other
    scenario's daily run PREPARES a batch per establishment ("lot") and waits:
    the owner, an administrateur or a manager covering that establishment
    validates it (then it is sent) or ignores it. The next day's batch for
    the same scenario and establishment replaces one nobody acted on.
    "Envoyer maintenant" is the owner's own decision and sends at once.
    (Welcome, Google review and "récompense proche" are automatic too — they
    follow a client's own action: features/auto_messages.py.)

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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from auth import require_role, TokenData
from features import store_scope as S

router = APIRouter(tags=["push-wallet"])
_db = None

OPEN_WINDOW_H = 72          # a card opened this long after a send counts as an open
DEFAULT_COOLDOWN_DAYS = 30  # the same scenario will not reach one customer twice inside this

READERS = ["business_owner", "administrateur", "manager"]
EDITORS = ["business_owner", "administrateur"]
STORE_FIELDS = ("title", "body", "enabled")   # what an administrateur may set for its establishments
AUTOMATIC = {"birthday"}                      # sent without approval (decided with the user)
APPROVERS = ["business_owner", "administrateur", "manager"]

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
     # Off until the merchant decides on an offer: it goes to every client.
     "icon": "tag", "trigger": "date_event", "config": {"day_of_month": 1}, "enabled": False,
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
    # "Offre spéciale -20 %" used to be seeded switched on: every shop sent it
    # to all its clients on the 1st of each month without having chosen that
    # offer. Switched off once, everywhere (and any establishment's own switch
    # with it); a merchant may turn it back on — the marker keeps this from
    # running again.
    try:
        ids = [r["id"] for r in db.push_scenarios.find(
            {"builtin": "special_offer", "offer_default_off": {"$exists": False}}, {"_id": 0, "id": 1})]
        if ids:
            db.push_scenarios.update_many({"id": {"$in": ids}},
                                          {"$set": {"enabled": False, "offer_default_off": True}})
            db.push_scenario_overrides.update_many({"scenario_id": {"$in": ids}}, {"$unset": {"enabled": ""}})
    except Exception:
        pass
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
        ("push_scenario_overrides", [("tenant_id", 1), ("scenario_id", 1), ("store_id", 1)]),
        ("push_wallet_pending", [("tenant_id", 1), ("status", 1), ("prepared_at", -1)]),
    ):
        try:
            db[coll].create_index(index)
        except Exception:
            pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _paris(at: datetime) -> datetime:
    from features import period as P
    return P.local(at)


def _ran_today(row: Dict[str, Any], at: datetime) -> bool:
    """A « Plage horaire » scenario runs once a day, when its window opens —
    the 15-minute tick (server.tick_pass) would otherwise run it again and
    again inside the window."""
    last = _aware(row.get("last_run_at"))
    return bool(last and _paris(last).date() == _paris(at).date())


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
        "automatic": row.get("trigger") in AUTOMATIC,
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
# an establishment's own version
# ---------------------------------------------------------------------------
def _overrides(tid: str, scenario_id: Optional[str] = None) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """{scenario id: {store id: {title?, body?, enabled?, by, at}}}"""
    q: Dict[str, Any] = {"tenant_id": tid}
    if scenario_id:
        q["scenario_id"] = scenario_id
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for o in _db.push_scenario_overrides.find(q, {"_id": 0}):
        fields = {k: o[k] for k in STORE_FIELDS if k in o}
        if fields:
            out.setdefault(o["scenario_id"], {})[o["store_id"]] = {**fields, "by": o.get("updated_by"),
                                                                   "at": o.get("updated_at")}
    return out


def _effective(row: Dict[str, Any], version: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The scenario as one establishment runs it."""
    if not version:
        return row
    return {**row, **{k: version[k] for k in STORE_FIELDS if k in version}}


def _home_stores(tid: str, ids: List[str]) -> Dict[str, Optional[str]]:
    """Each client's establishment for a message: where it last came, or where
    it signed up."""
    out: Dict[str, Optional[str]] = {}
    for v in _db.visits.find({"tenant_id": tid, "customer_id": {"$in": ids}, "branch_id": {"$nin": [None, ""]}},
                             {"_id": 0, "customer_id": 1, "branch_id": 1, "visit_time": 1}).sort("visit_time", -1):
        out.setdefault(v["customer_id"], v["branch_id"])
    for c in _db.customers.find({"tenant_id": tid, "id": {"$in": [i for i in ids if i not in out]}},
                                {"_id": 0, "id": 1, "branch_id": 1}):
        out.setdefault(c["id"], c.get("branch_id"))
    return out


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
    # Days, weekdays and hours are the shop's — Paris — not the server's UTC
    # (2026-10-09: « 11h–13h » ran two hours late, a birthday or a date near
    # midnight landed on the wrong day).
    loc = _paris(at)

    if trigger == "birthday":
        base["birthday"] = loc.strftime("%m-%d")

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
        if int(cfg.get("day_of_month") or 0) != loc.day:
            return []

    elif trigger == "specific_date":
        if str(cfg.get("date") or "")[:10] != loc.date().isoformat():
            return []

    elif trigger == "time_slot":
        # weekdays are 0 = Monday, matching Python's weekday()
        days = cfg.get("weekdays") or []
        if days and loc.weekday() not in [int(d) for d in days]:
            return []
        start, end = int(cfg.get("from_hour") or 0), int(cfg.get("to_hour") or 24)
        if end <= start:
            # An empty window can never come round; treat it as unconfigured
            # rather than as "every hour" or as silently never.
            return []
        if not (start <= loc.hour < end):
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


def _targets(tid: str, row: Dict[str, Any], at: datetime, scheduled: bool,
             limit: int = 2000) -> List[Tuple[Dict[str, Any], Optional[str], Dict[str, Any]]]:
    """(client, its establishment, the scenario as that establishment runs it)."""
    people = _audience(tid, row, at)
    versions = _overrides(tid, row["id"]).get(row["id"], {})
    home = _home_stores(tid, [c["id"] for c in people]) if people else {}

    # An establishment may have switched the scenario on or off for itself.
    def on(c: Dict[str, Any]) -> bool:
        v = versions.get(home.get(c["id"])) or {}
        return bool(v["enabled"]) if "enabled" in v else (bool(row.get("enabled")) or not scheduled)
    return [(c, home.get(c["id"]), _effective(row, versions.get(home.get(c["id"]))))
            for c in people if on(c)][:limit]


def _deliver(tid: str, row: Dict[str, Any], items, at: datetime, result: Dict[str, Any]) -> None:
    tenant = _db.tenants.find_one({"id": tid}) or {}
    for cust, _store, mine in items:
        title = _render(mine.get("title") or "", cust, tenant)
        body = _render(mine.get("body") or "", cust, tenant)
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
                # Google Wallet notifies for a birthday (user, 2026-10-04);
                # the other scenarios update the card silently there.
                notify_customer(cust["id"], message=body,
                                google_notify=({"kind": "birthday", "header": title, "body": body}
                                               if row.get("builtin") == "birthday" else None))
            except Exception:
                pass
            # 2. and the same message down the web-push / SMS rail, so a
            #    customer with no wallet pass still hears about it.
            import server as core
            core.dispatch_to_customer(tid, cust, title, body,
                                      kind="birthday" if row.get("trigger") == "birthday" else "push_wallet")
            result["sent"] += 1
        except Exception:
            result["errors"] += 1


def run_scenario(tid: str, row: Dict[str, Any], at: Optional[datetime] = None,
                 limit: int = 2000, scheduled: bool = False) -> Dict[str, Any]:
    """Send one scenario now. Returns what it did; never raises.

    `scheduled`: the daily run, which follows each establishment's switch. Fired
    by hand ("Envoyer maintenant"), only an establishment that switched it off
    is left out."""
    at = at or _now()
    result = {"scenario_id": row["id"], "name": row.get("name"), "targeted": 0, "sent": 0, "errors": 0}
    try:
        items = _targets(tid, row, at, scheduled, limit)
        result["targeted"] = len(items)
        _deliver(tid, row, items, at, result)
        _db.push_scenarios.update_one({"id": row["id"]},
                                      {"$set": {"last_run_at": at, "updated_at": at}})
    except Exception as exc:  # noqa: BLE001 — one scenario must not stop the rest
        result["errors"] += 1
        result["error"] = str(exc)[:200]
    return result


def prepare_scenario(tid: str, row: Dict[str, Any], at: Optional[datetime] = None) -> Dict[str, Any]:
    """The daily run of a scenario that needs approval: one batch per
    establishment, waiting for an OK. Never raises."""
    at = at or _now()
    result = {"scenario_id": row["id"], "name": row.get("name"), "targeted": 0, "prepared": 0, "errors": 0}
    try:
        items = _targets(tid, row, at, scheduled=True)
        result["targeted"] = len(items)
        by_store: Dict[Optional[str], List[Tuple[Dict[str, Any], Dict[str, Any]]]] = {}
        for cust, store, mine in items:
            by_store.setdefault(store, []).append((cust, mine))
        names = {}
        try:
            from features import team_access as T
            names = {st["id"]: st["name"] for st in T.stores(tid)}
        except Exception:
            pass
        for store, group in by_store.items():
            # Yesterday's batch nobody acted on gives way to today's.
            _db.push_wallet_pending.update_many(
                {"tenant_id": tid, "scenario_id": row["id"], "store_id": store, "status": "pending"},
                {"$set": {"status": "expired", "expired_at": at}})
            sample = group[0][1]
            _db.push_wallet_pending.insert_one({
                "id": str(uuid4()), "tenant_id": tid, "scenario_id": row["id"],
                "scenario_name": row.get("name") or "Scénario", "icon": row.get("icon") or "bell",
                "store_id": store, "store_name": names.get(store) if store else None,
                "customer_ids": [c["id"] for c, _ in group], "count": len(group),
                "title": sample.get("title") or "", "body": sample.get("body") or "",
                "status": "pending", "prepared_at": at,
            })
            result["prepared"] += len(group)
        # The "since the last run" triggers (tier_up, new_product) move on.
        _db.push_scenarios.update_one({"id": row["id"]}, {"$set": {"last_run_at": at, "updated_at": at}})
    except Exception as exc:  # noqa: BLE001
        result["errors"] += 1
        result["error"] = str(exc)[:200]
    return result


TIME_TRIGGERS = {"time_slot"}       # run by the 15-minute tick, at their hour


def run_due_for_tenant(tid: str, at: Optional[datetime] = None, only: Optional[set] = None) -> Dict[str, Any]:
    """`only`: these triggers alone (the tick: « Plage horaire »)."""
    at = at or _now()
    out = {"tenant_id": tid, "ran": [], "sent": 0, "prepared": 0}
    # Switched on for the shop, or by an establishment for itself.
    on_somewhere = set(_db.push_scenario_overrides.distinct("scenario_id", {"tenant_id": tid, "enabled": True}))
    for row in _db.push_scenarios.find({"tenant_id": tid}):
        row.pop("_id", None)
        if not row.get("enabled") and row["id"] not in on_somewhere:
            continue
        if only is not None and row.get("trigger") not in only:
            continue
        if row.get("trigger") in TIME_TRIGGERS:
            if _ran_today(row, at) or not _audience_open(row, at):
                continue
        if row.get("trigger") in AUTOMATIC:
            res = run_scenario(tid, row, at, scheduled=True)
            out["sent"] += res["sent"]
        else:
            res = prepare_scenario(tid, row, at)
            out["prepared"] += res["prepared"]
        if res["targeted"]:
            out["ran"].append(res)
    return out


def _audience_open(row: Dict[str, Any], at: datetime) -> bool:
    """Is a « Plage horaire » window open now (its day, its hours, in Paris)?"""
    cfg = row.get("config") or {}
    loc = _paris(at)
    days = cfg.get("weekdays") or []
    if days and loc.weekday() not in [int(d) for d in days]:
        return False
    start, end = int(cfg.get("from_hour") or 0), int(cfg.get("to_hour") or 24)
    return end > start and start <= loc.hour < end


def run_all_due(at: Optional[datetime] = None, only: Optional[set] = None) -> Dict[str, Any]:
    """Called by the daily cron (everything) and the 15-minute tick (`only` =
    TIME_TRIGGERS). One tenant's failure never stops the others."""
    at = at or _now()
    summary = {"tenants": 0, "sent": 0, "prepared": 0, "at": at.isoformat()}
    try:
        tenants = set(_db.push_scenarios.distinct("tenant_id", {"enabled": True}))
        tenants |= set(_db.push_scenario_overrides.distinct("tenant_id", {"enabled": True}))
    except Exception:
        return summary
    from features import plan_limits
    for tid in tenants:
        if not plan_limits.allows_tenant(tid, "automations"):    # Automatisation not in the plan
            continue
        try:
            res = run_due_for_tenant(tid, at, only)
            summary["tenants"] += 1
            summary["sent"] += res["sent"]
            summary["prepared"] += res["prepared"]
        except Exception:
            continue
    return summary


# ---------------------------------------------------------------------------
# the four figures
# ---------------------------------------------------------------------------
def _counts_by_scenario(tid: str, since: Optional[datetime] = None,
                        mine: Optional[set] = None) -> Dict[str, int]:
    match: Dict[str, Any] = {"tenant_id": tid}
    if mine is not None:
        match["customer_id"] = {"$in": list(mine)}
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


def _rates(tid: str, start: datetime, end: datetime, mine: Optional[set] = None) -> Dict[str, Any]:
    """Sent, clicked, and opened — the last one measured against card opens,
    because a wallet push has no read receipt."""
    logs = list(_db.push_wallet_log.find(
        {"tenant_id": tid, "sent_at": {"$gte": start, "$lte": end},
         **({"customer_id": {"$in": list(mine)}} if mine is not None else {})},
        {"_id": 0, "customer_id": 1, "sent_at": 1, "clicked_at": 1}))
    sent = len(logs)
    clicked = sum(1 for l in logs if l.get("clicked_at"))
    opened = 0
    if logs:
        # Every card opening, not just the latest (services/card_opens): a
        # customer who opened after the push, then again days later, counts.
        from services import card_opens
        ids = list({l["customer_id"] for l in logs})
        times = card_opens.open_times(_db, tid, ids, start, end + timedelta(hours=OPEN_WINDOW_H))
        for l in logs:
            at_sent = _aware(l.get("sent_at"))
            if at_sent and (l.get("clicked_at") or any(
                    at_sent <= t <= at_sent + timedelta(hours=OPEN_WINDOW_H) for t in times.get(l["customer_id"], []))):
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
    token_data: TokenData = Depends(require_role(READERS, partial_ok=True)),
    request: Request = None,
):
    tid = token_data.tenant_id
    _seed(tid)
    scope = S.resolve(token_data, request)
    start, end = _window(date_from, date_to)
    counts = _counts_by_scenario(tid, start, S.customer_ids(scope))
    rows = list(_db.push_scenarios.find({"tenant_id": tid}).sort("order", 1))
    versions = _overrides(tid)
    shown = set(scope.ids if scope.ids is not None else scope.all_ids)

    def view(r: Dict[str, Any]) -> Dict[str, Any]:
        mine = versions.get(r["id"], {})
        # One establishment chosen: the scenario as it runs there.
        out = _public(dict(_effective(r, mine.get(scope.single)) if scope.single else r), counts)
        out["versions"] = [{"store_id": sid, "store": scope.names.get(sid, sid),
                            **{k: v[k] for k in STORE_FIELDS if k in v}, "by": v.get("by")}
                           for sid, v in mine.items() if sid in shown]
        return out

    role = getattr(token_data, "role", None)
    return {
        "scope": scope.describe(),
        "pending_count": len(pending_lots(token_data, scope)),
        "can": {"create": _shop_wide(token_data), "edit": role in EDITORS or _shop_wide(token_data),
                "message_only": not _shop_wide(token_data)},
        "scenarios": [view(r) for r in rows],
        "triggers": [{"key": k, "label": v["label"], "config": v["config"]}
                     for k, v in TRIGGERS.items()],
        "examples": EXAMPLES,
        "from": start.isoformat(), "to": end.isoformat(),
    }


@router.get("/api/owner/push-wallet/stats")
def stats(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    token_data: TokenData = Depends(require_role(READERS, partial_ok=True)),
    request: Request = None,
):
    tid = token_data.tenant_id
    _seed(tid)
    mine = S.customer_ids(S.resolve(token_data, request))
    start, end = _window(date_from, date_to)
    span = end - start
    prev_end = start - timedelta(microseconds=1)
    prev_start = prev_end - span

    now, was = _rates(tid, start, end, mine), _rates(tid, prev_start, prev_end, mine)
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
             "note": f"carte ouverte dans les {OPEN_WINDOW_H} h suivant un push, ou lien cliqué",
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
    _shop_wide_or_403(token_data)
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
                    token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True)),
                    request: Request = None):
    tid = token_data.tenant_id
    row = _db.push_scenarios.find_one({"id": scenario_id, "tenant_id": tid})
    if not row:
        raise HTTPException(status_code=404, detail="Scénario introuvable")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not _shop_wide(token_data):
        return _store_version(tid, row, patch, token_data, request)
    if "trigger" in patch and patch["trigger"] not in TRIGGERS:
        raise HTTPException(status_code=400, detail="Déclencheur inconnu")
    if "cooldown_days" in patch:
        patch["cooldown_days"] = max(0, int(patch["cooldown_days"]))
    patch["updated_at"] = _now()
    _db.push_scenarios.update_one({"id": scenario_id}, {"$set": patch})
    # The owner's change applies to every establishment: it replaces their
    # own version of the fields it touched.
    touched = [k for k in STORE_FIELDS if k in patch]
    if touched:
        _db.push_scenario_overrides.update_many({"tenant_id": tid, "scenario_id": scenario_id},
                                                {"$unset": {k: "" for k in touched}})
        _db.push_scenario_overrides.delete_many({"tenant_id": tid, "scenario_id": scenario_id,
                                                 **{k: {"$exists": False} for k in STORE_FIELDS}})
    fresh = _db.push_scenarios.find_one({"id": scenario_id})
    return _public(fresh, _counts_by_scenario(tid))


def _store_version(tid: str, row: Dict[str, Any], patch: Dict[str, Any],
                   token_data: TokenData, request: Optional[Request]) -> Dict[str, Any]:
    """An administrateur's change: the message and the switch, for its
    establishments only (the one chosen in the menu, or all of its own)."""
    if getattr(token_data, "role", None) not in EDITORS:
        raise HTTPException(status_code=403, detail="Seuls le propriétaire et les administrateurs modifient les automatisations.")
    other = [k for k in patch if k not in STORE_FIELDS]
    # The editor sends the whole form back; only a real change is refused.
    other = [k for k in other if patch[k] != row.get(k) and not (k == "config" and patch[k] == (row.get("config") or {}))]
    if other:
        raise HTTPException(status_code=403, detail="Seul le propriétaire peut changer le déclencheur, "
                                                    "le nom ou le délai d'un scénario.")
    scope = S.resolve(token_data, request)
    stores = scope.ids if scope.ids is not None else scope.allowed
    fields = {k: patch[k] for k in STORE_FIELDS if k in patch}
    for k in ("title", "body"):
        if k in fields and not str(fields[k]).strip():
            raise HTTPException(status_code=400, detail="Le titre et le message ne peuvent pas être vides.")
    if fields:
        now = _now()
        for sid in stores:
            _db.push_scenario_overrides.update_one(
                {"tenant_id": tid, "scenario_id": row["id"], "store_id": sid},
                {"$set": {**fields, "updated_by": getattr(token_data, "email", None), "updated_at": now}},
                upsert=True)
    row.pop("_id", None)
    one = stores[0] if len(stores) == 1 else None
    out = _public(dict(_effective(row, _overrides(tid, row["id"]).get(row["id"], {}).get(one)) if one else row),
                  _counts_by_scenario(tid, mine=S.customer_ids(scope)))
    out["applied_to"] = [scope.names.get(s, s) for s in stores]
    return out


@router.delete("/api/owner/push-wallet/scenarios/{scenario_id}")
def delete_scenario(scenario_id: str,
                    token_data: TokenData = Depends(require_role(["business_owner"]))):
    _shop_wide_or_403(token_data)
    res = _db.push_scenarios.delete_one({"id": scenario_id, "tenant_id": token_data.tenant_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Scénario introuvable")
    return {"deleted": True}


@router.post("/api/owner/push-wallet/scenarios/{scenario_id}/run")
def run_now(scenario_id: str,
            token_data: TokenData = Depends(require_role(["business_owner"]))):
    """Fire it now — the merchant's way of checking a scenario does what they
    think. The cooldown still applies, so this cannot be used to spam."""
    _shop_wide_or_403(token_data)
    tid = token_data.tenant_id
    row = _db.push_scenarios.find_one({"id": scenario_id, "tenant_id": tid})
    if not row:
        raise HTTPException(status_code=404, detail="Scénario introuvable")
    row.pop("_id", None)
    return run_scenario(tid, row)


@router.get("/api/owner/push-wallet/scenarios/{scenario_id}/preview")
def preview_audience(scenario_id: str,
                     token_data: TokenData = Depends(require_role(READERS, partial_ok=True)),
                     request: Request = None):
    """How many clients this would reach right now, without sending anything —
    among the chosen establishments' clients."""
    tid = token_data.tenant_id
    row = _db.push_scenarios.find_one({"id": scenario_id, "tenant_id": tid})
    if not row:
        raise HTTPException(status_code=404, detail="Scénario introuvable")
    row.pop("_id", None)
    mine = S.customer_ids(S.resolve(token_data, request))
    people = [c for c in _audience(tid, row, _now()) if mine is None or c["id"] in mine]
    return {"count": len(people),
            "sample": [{"name": c.get("name") or "Client"} for c in people[:5]]}


# ---------------------------------------------------------------------------
# À valider
# ---------------------------------------------------------------------------
def _shop_wide(token_data: TokenData) -> bool:
    """A change for the whole shop (create, delete, run, trigger/name/delay):
    the owner, or an account with « Modifier » Automatisations in EVERY
    establishment (user, 2026-10-22: « iska bhi access diya ho toh kr sake »).
    Anyone else changes its establishments' own version only."""
    from features import role_perms as RP
    return RP.may_everywhere(token_data, "automations")


def _shop_wide_or_403(token_data: TokenData) -> None:
    if not _shop_wide(token_data):
        raise HTTPException(status_code=403, detail="Accès non autorisé : il faut « Modifier » Automatisations "
                                                    "dans tous vos établissements pour changer un scénario de toute la boutique.")


def _can_act(token_data: TokenData, scope: "S.Scope", lot: Dict[str, Any]) -> bool:
    """The owner acts on every batch; an administrateur or a manager on the
    batches of the establishments it covers (a batch of clients with no
    establishment belongs to whoever covers the whole shop)."""
    if getattr(token_data, "role", None) == "business_owner":
        return True
    if getattr(token_data, "role", None) not in APPROVERS:
        return False
    store = lot.get("store_id")
    if store is None:
        return set(scope.all_ids) <= set(scope.allowed)
    return store in scope.allowed


def pending_lots(token_data: TokenData, scope: "S.Scope") -> List[Dict[str, Any]]:
    shown = set(scope.ids if scope.ids is not None else scope.all_ids)
    out = []
    for lot in _db.push_wallet_pending.find({"tenant_id": token_data.tenant_id, "status": "pending"},
                                            {"_id": 0}).sort("prepared_at", -1):
        if not _can_act(token_data, scope, lot):
            continue
        # The establishment menu narrows the list; a batch with no
        # establishment shows on the whole-shop view only.
        if lot.get("store_id") is not None and lot["store_id"] not in shown:
            continue
        if lot.get("store_id") is None and scope.ids is not None:
            continue
        out.append(lot)
    return out


def _lot_view(lot: Dict[str, Any]) -> Dict[str, Any]:
    at = _aware(lot.get("prepared_at"))
    return {"id": lot["id"], "scenario_id": lot["scenario_id"], "scenario": lot.get("scenario_name"),
            "icon": lot.get("icon") or "bell", "store": lot.get("store_name") or "Tout le commerce",
            "store_id": lot.get("store_id"), "count": int(lot.get("count") or 0),
            "title": lot.get("title") or "", "body": lot.get("body") or "",
            "prepared_at": at.isoformat() if at else None}


@router.get("/api/owner/push-wallet/pending")
def list_pending(token_data: TokenData = Depends(require_role(APPROVERS, partial_ok=True)),
                 request: Request = None):
    scope = S.resolve(token_data, request)
    return {"lots": [_lot_view(l) for l in pending_lots(token_data, scope)]}


def _lot_for(lot_id: str, token_data: TokenData, request: Optional[Request]) -> Dict[str, Any]:
    lot = _db.push_wallet_pending.find_one({"id": lot_id, "tenant_id": token_data.tenant_id}, {"_id": 0})
    if not lot:
        raise HTTPException(status_code=404, detail="Envoi introuvable")
    if not _can_act(token_data, S.resolve(token_data, request), lot):
        raise HTTPException(status_code=403, detail="Cet envoi concerne un établissement que vous ne gérez pas.")
    if lot.get("status") != "pending":
        raise HTTPException(status_code=409, detail="Cet envoi a déjà été traité.")
    return lot


@router.post("/api/owner/push-wallet/pending/{lot_id}/approve")
def approve_pending(lot_id: str, token_data: TokenData = Depends(require_role(APPROVERS, partial_ok=True)),
                    request: Request = None):
    """Validated: sent now, to the clients of the batch who still have not heard
    this scenario inside its delay."""
    tid = token_data.tenant_id
    lot = _lot_for(lot_id, token_data, request)
    row = _db.push_scenarios.find_one({"id": lot["scenario_id"], "tenant_id": tid}, {"_id": 0})
    if not row:
        _db.push_wallet_pending.update_one({"id": lot_id}, {"$set": {"status": "expired"}})
        raise HTTPException(status_code=409, detail="Ce scénario a été supprimé.")
    # Claimed first, so a double click cannot send twice.
    claimed = _db.push_wallet_pending.update_one({"id": lot_id, "status": "pending"},
                                                 {"$set": {"status": "sending"}})
    if not claimed.modified_count:
        raise HTTPException(status_code=409, detail="Cet envoi a déjà été traité.")
    at = _now()
    skip = _recently_messaged(row["id"], _cooldown_cutoff(row))
    people = [c for c in _db.customers.find({"tenant_id": tid, "id": {"$in": lot.get("customer_ids") or []}},
                                            {"_id": 0}) if c["id"] not in skip]
    versions = _overrides(tid, row["id"]).get(row["id"], {})
    items = [(c, lot.get("store_id"), _effective(row, versions.get(lot.get("store_id")))) for c in people]
    result = {"sent": 0, "errors": 0}
    _deliver(tid, row, items, at, result)
    _db.push_wallet_pending.update_one({"id": lot_id}, {"$set": {
        "status": "sent", "approved_by": getattr(token_data, "email", None), "approved_at": at,
        "sent": result["sent"]}})
    return {"status": "sent", "sent": result["sent"], "skipped": len(lot.get("customer_ids") or []) - len(people)}


@router.post("/api/owner/push-wallet/pending/{lot_id}/skip")
def skip_pending(lot_id: str, token_data: TokenData = Depends(require_role(APPROVERS, partial_ok=True)),
                 request: Request = None):
    _lot_for(lot_id, token_data, request)
    _db.push_wallet_pending.update_one({"id": lot_id}, {"$set": {
        "status": "skipped", "skipped_by": getattr(token_data, "email", None), "skipped_at": _now()}})
    return {"status": "skipped"}


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
            from services import card_owner as CO
            target = CO.owner_url("", cust["barcode_id"])     # the customer's own push: the owner's link
    return RedirectResponse(url=target, status_code=302)
