"""
Automatisations — redesigned from the user's mockups (2026-10-11).

Eight scenarios, no others (the user removed Offre spéciale, Événement
spécial, Relance panier, Heures creuses and Nouveaux produits, data included):

    birthday       Anniversaire               time   the day of the birthday (± X days)
    tier_up        Atteinte d'un palier       event  the scan that moves the client up
    welcome        Bienvenue                  event  the signup
    near_reward    Proche de la récompense    event  the scan that leaves X visits to go
    referral       Parrainage                 event  a parrainage reward is earned
    geo            Géolocalisation            event  the card sees the client near a shop
    google_review  Avis Google                event  after a visit
    inactive       Client inactif             time   X days without a visit

The owner may create several of each (Client inactif 30 j and 60 j…). An
« Active » automation sends by itself — no « À valider » (user's choice); the
shop's daily limits still apply (features/send_rules).

When
    A time scenario runs at its hour (or the shop's busiest hour, « plage
    intelligente »), on its days. An event one goes at once, after its
    optional delay, inside its days and hours; outside them it waits in
    `automation_queue` for the window to open. `run_due` releases what is due —
    the daily cron calls it, and the 15-minute tick when the shop has one
    (`tick_seen`): without a tick, the daily run sends all of today's.

How it reaches the client
    • Wallet: the message becomes the pass's « Dernier message » field
      (Apple raises its lock-screen banner from the field's changeMessage),
      Google Wallet gets a message; the action button is a link on the back
      of the pass. A Wallet notification cannot carry a button: the button
      lives on the card (user's choice, 2026-10-11).
    • Web push / SMS through server.dispatch_to_customer, the tap opening
      the button's link straight away (an Android web push shows the button).
    • The web card shows the latest message with its button at the top.

Every send is logged in `automation_log` (one row per client and message);
the button's link is `/api/auto/c/{log_id}`, which counts the click and goes
on to the target: any link the owner put — an offer, the card, the Google
review page, a website.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from auth import require_role, TokenData

router = APIRouter(tags=["automations"])
_db = None

READERS = ["business_owner", "administrateur", "manager"]
EDITORS = ["business_owner", "administrateur"]
TITLE_MAX = 80                 # the palier mockups (user, 2026-10-11): 80 / 350
BODY_MAX = 350
BUTTON_MAX = 30
NAME_MAX = 60


def init(db):
    global _db
    _db = db
    try:
        _db.automation_log.create_index([("tenant_id", 1), ("automation_id", 1), ("customer_id", 1)])
        _db.automation_log.create_index("id", unique=True)
        _db.automation_queue.create_index([("due_at", 1)])
        _db.automations.create_index([("tenant_id", 1), ("scenario", 1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _paris(at: datetime) -> datetime:
    from features import period as P
    return P.local(at)


def _from_paris(d: date, hh: int, mm: int) -> datetime:
    """A Paris wall-clock time as UTC."""
    from zoneinfo import ZoneInfo
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=ZoneInfo("Europe/Paris")).astimezone(timezone.utc)


def public_base() -> str:
    return (os.environ.get("PUBLIC_APP_URL") or "https://app.fidclic.com").rstrip("/")


# ---------------------------------------------------------------------------
# the eight scenarios
# ---------------------------------------------------------------------------
SCENARIOS: Dict[str, Dict[str, Any]] = {
    "birthday": {
        "label": "Anniversaire", "sub": "Souhaitez un joyeux anniversaire à vos clients.",
        "icon": "cake", "tone": "rose", "kind": "time", "trigger_label": "Date d'anniversaire",
        "push_kind": "birthday", "google": "birthday",
        "title": "Joyeux anniversaire {prénom} ! 🎉",
        "body": "Toute l'équipe de {nom_commerce} vous souhaite un merveilleux anniversaire ! Une surprise vous attend.",
        "button": "Découvrir ma surprise",
    },
    "tier_up": {
        "label": "Atteinte d'un palier", "sub": "Félicitez vos clients lorsqu'ils atteignent un nouveau palier.",
        "icon": "trophy", "tone": "amber", "kind": "event", "trigger_label": "Nouveau palier atteint",
        "push_kind": "tier_up", "google": "tier_up",
        "title": "🏆 Bravo {prénom} !",
        "body": "Vous avez atteint {palier} chez {nom_commerce} ! Découvrez votre récompense 🎁",
        "button": "Voir ma récompense",
    },
    "welcome": {
        "label": "Bienvenue", "sub": "Accueillez chaque client dès son inscription.",
        "icon": "hand", "tone": "blue", "kind": "event", "trigger_label": "Inscription du client",
        "push_kind": "welcome", "google": "automation",
        "title": "Bienvenue chez {nom_commerce} 🎉",
        "body": "Merci {prénom} ! Votre carte de fidélité est prête : à chaque visite, vous vous rapprochez de votre récompense.",
        "button": "Voir ma carte",
    },
    "near_reward": {
        "label": "Proche de la récompense", "sub": "Prévenez vos clients quand la récompense est toute proche.",
        "icon": "gift", "tone": "violet", "kind": "event", "trigger_label": "À X visites de la récompense",
        "push_kind": "near_reward", "google": "near_reward",
        "title": "Plus que {visites_restantes} {visite_s}, {prénom} !",
        "body": "Encore {visites_restantes} {visite_s} chez {nom_commerce} et {prochaine_récompense} est à vous.",
        "button": "Voir ma récompense",
    },
    "referral": {
        "label": "Parrainage", "sub": "Remerciez parrains et filleuls quand la récompense est gagnée.",
        "icon": "users", "tone": "green", "kind": "event", "trigger_label": "Récompense de parrainage gagnée",
        "push_kind": "parrainage", "google": "parrainage",
        "title": "Parrainage réussi 🎉",
        "body": "Votre ami {filleul} {visite_ami} chez {nom_commerce} : +{points_gagnés} points.",
        "button": "Voir mes points",
    },
    "geo": {
        "label": "Géolocalisation", "sub": "Attirez vos clients lorsqu'ils passent à proximité.",
        "icon": "pin", "tone": "green", "kind": "event", "trigger_label": "Entrée dans la zone",
        "push_kind": "proximity", "google": None,
        "title": "Vous êtes tout près ! 👋",
        "body": "Bonjour {prénom}, profitez de votre passage près de {nom_commerce} : une attention vous attend !",
        "button": "Voir l'offre",
    },
    "google_review": {
        "label": "Avis Google", "sub": "Demandez un avis à vos clients après leur visite.",
        "icon": "star", "tone": "violet", "kind": "event", "trigger_label": "Après une visite",
        "push_kind": "google_review", "google": "automation",
        "title": "Votre avis compte ⭐",
        "body": "Bonjour {prénom}, votre expérience chez {nom_commerce} nous intéresse. Laissez-nous un avis, cela nous aide beaucoup !",
        "button": "Laisser un avis",
    },
    "inactive": {
        "label": "Client inactif", "sub": "Réactivez vos clients après une période d'inactivité.",
        "icon": "refresh", "tone": "red", "kind": "time", "trigger_label": "Inactivité (X jours)",
        "push_kind": "push_wallet", "google": "automation",
        "title": "On ne vous a pas vu depuis un moment",
        "body": "Bonjour {prénom}, nous serions ravis de vous retrouver chez {nom_commerce} ! Une attention vous attend.",
        "button": "Voir mon offre",
    },
    # « Personnalisée » (user, 2026-10-11): the owner's own message, sent when
    # THEY decide — after X visits, X days after signup, after each visit, or
    # on a date / every week / month / year.
    "custom": {
        "label": "Personnalisée", "sub": "Votre propre message, au moment que vous choisissez.",
        "icon": "sparkles", "tone": "blue", "kind": "custom", "trigger_label": "Déclencheur personnalisé",
        "push_kind": "automation", "google": "automation",
        "title": "", "body": "", "button": "En savoir plus",
    },
}
ORDER = ["custom", "birthday", "tier_up", "welcome", "near_reward", "referral", "geo", "google_review", "inactive"]
CUSTOM_TYPES = ("visits", "after_signup", "after_visit", "date")
DATE_MODES = ("once", "weekly", "monthly", "yearly")


def is_timed(scenario: str, trigger: Optional[Dict[str, Any]] = None) -> bool:
    """Sent at an hour (daily run / tick) rather than on an event."""
    kind = SCENARIOS[scenario]["kind"]
    return kind == "time" or (kind == "custom" and (trigger or {}).get("type") == "date")
# Removed by the user (2026-10-11) — with their data.
REMOVED_BUILTINS = {"special_offer", "cart_recovery", "off_peak", "new_products", "special_event"}

VARIABLES = {
    "common": ["prénom", "nom", "nom_commerce", "points", "visites", "prochaine_récompense", "points_manquants"],
    "birthday": [], "tier_up": ["palier", "récompense"], "welcome": [], "near_reward": ["visites_restantes", "visite_s"],
    "referral": ["filleul", "parrain", "points_gagnés", "visite_ami"], "geo": ["établissement"],
    "google_review": [], "inactive": ["jours_absence"], "custom": [],
}
LINK_TYPES = ("card", "rewards", "offer", "google_review", "url")
DAY_MODES = ("all", "specific", "weekdays")
TARGET_MODES = ("all", "segment", "wallet")
# « Filtres avancés » (palier mockups, 2026-10-11 — every automation): ticks
# inside a group widen it (OR), groups narrow each other (AND); none = Tous.
GENDERS = ("F", "M", "X")
AGES = {"<18": (0, 17), "18-25": (18, 25), "26-35": (26, 35), "36-50": (36, 50), "50+": (51, 200)}
FREQS = {"new": (0, 1), "occasional": (2, 3), "regular": (4, 10), "loyal": (11, None)}   # lifetime visits
SPENT = {"<50": (0, 50), "50-100": (50, 100), "100-200": (100, 200), ">200": (200, None)}  # € spent, [lo, hi)
LAST_VISIT = {"<7": (0, 7), "8-30": (8, 30), "1-3m": (31, 90), ">3m": (91, None)}         # days since
RADII = (1, 2, 5, 10, 20, 50)


def as_list(value: Any, allowed: Iterable[str]) -> List[str]:
    """A filter as a list of known ticks — older single values ("all", "F"…) read too."""
    allowed = set(allowed)
    if value in (None, "", "all"):
        return []
    vals = value if isinstance(value, (list, tuple)) else [value]
    return [v for v in dict.fromkeys(str(x) for x in vals) if v in allowed]
GR_FREQS = ("every_scan", "days", "once")


# ---------------------------------------------------------------------------
# defaults and the old settings carried over
# ---------------------------------------------------------------------------
def _default_trigger(scenario: str) -> Dict[str, Any]:
    return {
        "birthday": {"offset_days": 0},
        # Atteinte d'un palier (mockups 2026-10-11): an owner threshold on
        # points (earned since the start) / visits / € spent, or the card's
        # statut; every multiple, the first time only, or with a minimum
        # gap; or a list of paliers, each with its own message.
        "tier_up": {"condition": "points", "threshold": 200, "repeat": "each", "min_days": 7,
                    "custom_tiers": False, "tiers": []},
        "welcome": {},
        "near_reward": {"visits_left": 1},
        "referral": {"side": "parrain"},
        "geo": {"cooldown_days": 7},
        "google_review": {"frequency": "days", "every_days": 30, "stop_after_click": True},
        "inactive": {"days": 30, "repeat": "once", "every_days": 30},
        "custom": {"type": "after_visit", "visits": 5, "visits_repeat": "once", "cooldown_days": 0,
                   "date_mode": "once", "date": None, "weekday": 0, "monthday": 1},
    }[scenario] | {"delay_value": 0, "delay_unit": "hours"}


def _default_schedule(scenario: str) -> Dict[str, Any]:
    timed = is_timed(scenario, _default_trigger(scenario))
    return {"days": "all", "weekdays": [0, 1, 2, 3, 4, 5, 6],
            "hour": "10:00" if timed else None, "smart": False,
            "window_from": "09:00", "window_to": "21:00", "window": not timed}


def new_doc(tid: str, scenario: str, **over: Any) -> Dict[str, Any]:
    meta = SCENARIOS[scenario]
    now = _now()
    doc = {
        "id": str(uuid.uuid4()), "tenant_id": tid, "scenario": scenario,
        "name": meta["label"], "status": "draft",
        "trigger": _default_trigger(scenario),
        "message": {"title": meta["title"], "body": meta["body"], "image_url": None,
                    "button": {"enabled": False, "label": meta["button"], "link_type": "card",
                               "offer_id": None, "url": None}},
        "targeting": {"mode": "all", "segment": None,
                      "filters": {"gender": [], "age": [], "frequency": [], "spent": [], "last_visit": [],
                                  "stores": [], "radius_km": None}},
        "schedule": _default_schedule(scenario),
        "created_at": now, "updated_at": now, "last_run_at": None, "store_ids": None,
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(doc.get(k), dict):
            doc[k] = {**doc[k], **v}
        else:
            doc[k] = v
    return doc


_TOKENS = (("{first_name}", "{prénom}"), ("{business_name}", "{nom_commerce}"), ("{visits}", "{visites}"),
           ("{visits_left}", "{visites_restantes}"), ("{reward}", "{prochaine_récompense}"))


def _french(text: str) -> str:
    for old, new in _TOKENS:
        text = (text or "").replace(old, new)
    return text


def migrate(tid: str) -> None:
    """Once per shop: the old automations become the new ones, keeping their
    words and their switch; the removed scenarios go, data included; nothing
    waits for an OK any more."""
    if _db.automation_meta.find_one({"tenant_id": tid, "migrated": True}):
        return
    _db.automation_meta.update_one({"tenant_id": tid}, {"$set": {"tenant_id": tid, "migrated": True,
                                                                 "migrated_at": _now()}}, upsert=True)
    if _db.automations.find_one({"tenant_id": tid}):
        return
    docs: List[Dict[str, Any]] = []
    old = {r.get("builtin") or r.get("id"): r for r in _db.push_scenarios.find({"tenant_id": tid}, {"_id": 0})}

    def carried(key: str, scenario: str, **over: Any) -> Dict[str, Any]:
        r = old.get(key) or {}
        msg = {}
        if r.get("title"):
            msg["title"] = _french(r["title"])[:TITLE_MAX]
        if r.get("body"):
            msg["body"] = _french(r["body"])[:BODY_MAX]
        return new_doc(tid, scenario, status="active" if r.get("enabled") else "paused",
                       **({"message": msg} if msg else {}), **over)

    docs.append(carried("birthday", "birthday"))
    docs.append(carried("tier_up", "tier_up", trigger={"condition": "status"}))
    inactive = old.get("inactive") or {}
    docs.append(carried("inactive", "inactive",
                        trigger={"days": int((inactive.get("config") or {}).get("days") or 30)}))
    try:
        from features.welcome_bonus import welcome_state
        w = welcome_state(tid)
        body = _french(w.get("message") or "")[:BODY_MAX] or SCENARIOS["welcome"]["body"]
        docs.append(new_doc(tid, "welcome", status="active" if w.get("enabled") else "paused",
                            message={"body": body}))
    except Exception:
        docs.append(new_doc(tid, "welcome", status="paused"))
    cfg = _db.auto_message_config.find_one({"tenant_id": tid}) or {}
    gr, nr = cfg.get("google_review") or {}, cfg.get("near_reward") or {}
    docs.append(new_doc(tid, "near_reward", status="active" if nr.get("enabled", True) else "paused",
                        trigger={"visits_left": int(nr.get("visits_left") or 1)},
                        message={k: _french(nr[k])[:TITLE_MAX if k == "title" else BODY_MAX]
                                 for k in ("title", "body") if nr.get(k)}))
    docs.append(new_doc(tid, "google_review", status="active" if gr.get("enabled") else "paused",
                        trigger={"frequency": gr.get("frequency") if gr.get("frequency") in GR_FREQS else "days",
                                 "every_days": int(gr.get("days") or 30),
                                 "stop_after_click": bool(gr.get("stop_after_click", True))},
                        message={**{k: _french(gr[k])[:TITLE_MAX if k == "title" else BODY_MAX]
                                    for k in ("title", "body") if gr.get(k)},
                                 "button": {"enabled": True, "label": "Laisser un avis",
                                            "link_type": "google_review", "offer_id": None, "url": None}}))
    ref_on = bool((_db.referral_config.find_one({"tenant_id": tid}) or {}).get("enabled"))
    docs.append(new_doc(tid, "referral", name="Parrainage — parrain", status="active" if ref_on else "paused",
                        trigger={"side": "parrain"}))
    docs.append(new_doc(tid, "referral", name="Parrainage — filleul", status="active" if ref_on else "paused",
                        trigger={"side": "filleul"},
                        message={"title": "Parrainage 🎉",
                                 "body": "Merci d'être venu grâce à {parrain} : +{points_gagnés} points de parrainage."}))
    tenant = _db.tenants.find_one({"id": tid}, {"_id": 0, "geo_enabled": 1, "geo_cooldown_days": 1}) or {}
    docs.append(new_doc(tid, "geo", status="active" if tenant.get("geo_enabled") else "paused",
                        trigger={"cooldown_days": int(tenant.get("geo_cooldown_days") or 7)}))
    for i, d in enumerate(docs):
        d["order"] = i
        # carried over: they keep sending the moment it happens, as before
        if SCENARIOS[d["scenario"]]["kind"] == "event":
            d["schedule"]["window"] = False
    _db.automations.insert_many(docs)
    # the old engine stops here: its scenarios (removed ones with their data),
    # their per-establishment versions and the lots that waited for an OK
    _db.push_wallet_log.delete_many({"tenant_id": tid, "scenario_id": {"$in": [
        r["id"] for k, r in old.items() if (r.get("builtin") in REMOVED_BUILTINS or not r.get("builtin"))]}})
    _db.push_scenarios.delete_many({"tenant_id": tid})
    _db.push_scenario_overrides.delete_many({"tenant_id": tid})
    _db.push_wallet_pending.delete_many({"tenant_id": tid})


# ---------------------------------------------------------------------------
# who
# ---------------------------------------------------------------------------
def _has_wallet(c: Dict[str, Any]) -> bool:
    from features import card_status as CS
    if CS.state_of(c)["state"] != "active":
        return False
    if c.get("wallet_added_at") or c.get("google_added_at"):
        return True
    serial = c.get("barcode_id")
    return bool(serial and (_db.pass_registrations.find_one({"serial": serial})
                            or _db.google_wallet_objects.find_one({"serial": serial})))


def _visits_30(tid: str, cid: str, at: datetime) -> int:
    return _db.visits.count_documents({"tenant_id": tid, "customer_id": cid,
                                       "visit_time": {"$gte": at - timedelta(days=30)}})


def _store_people(tid: str, stores: List[str]) -> Optional[set]:
    if not stores:
        return None
    from features import store_scope as S
    return S.customer_ids(S.Scope(tenant_id=tid, ids=list(stores)))


def _segment_ids(tid: str, key: Optional[str], at: datetime) -> Optional[set]:
    if not key:
        return None
    try:
        from features import campaigns_page as CP
        return {c["id"] for c in CP._segment_people(tid, key, at, None)}
    except Exception:
        return set()


def matches(tid: str, row: Dict[str, Any], cust: Dict[str, Any], at: Optional[datetime] = None,
            cache: Optional[Dict[str, Any]] = None) -> bool:
    """Does this client fall inside the automation's « Ciblage »?"""
    at = at or _now()
    cache = cache if cache is not None else {}
    tg = row.get("targeting") or {}
    if cust.get("deleted_at"):
        return False
    mode = tg.get("mode") or "all"
    if mode == "wallet" and not _has_wallet(cust):
        return False
    if mode == "segment":
        key = ("seg", tg.get("segment"))
        if key not in cache:
            cache[key] = _segment_ids(tid, tg.get("segment"), at) or set()
        if cust["id"] not in cache[key]:
            return False
    if row.get("store_ids"):                       # an administrateur's own establishments
        key = ("own", tuple(row["store_ids"]))
        if key not in cache:
            cache[key] = _store_people(tid, row["store_ids"]) or set()
        if cust["id"] not in cache[key]:
            return False
    # « Tous mes clients » = everyone: no filter applies (as in Campagnes, 2026-10-10)
    f = {} if mode == "all" else (tg.get("filters") or {})

    def within(value: Optional[float], ranges: List[Tuple[Any, Any]], half_open: bool = False) -> bool:
        if value is None:
            return False
        for lo, hi in ranges:
            if value >= lo and (hi is None or (value < hi if half_open else value <= hi)):
                return True
        return False
    g = as_list(f.get("gender"), GENDERS)
    if g and (cust.get("gender") or "") not in g:
        return False
    ages = as_list(f.get("age"), AGES)
    if ages:
        from services import customer_fields as CF
        if not within(CF.age_of(cust.get("birth_date")), [AGES[a] for a in ages]):
            return False
    spent = as_list(f.get("spent"), SPENT)
    if spent and not within(float(cust.get("total_amount_paid") or 0), [SPENT[x] for x in spent], half_open=True):
        return False
    lv = as_list(f.get("last_visit"), LAST_VISIT)
    if lv:
        last = _aware(cust.get("last_visit_date")) or _aware(cust.get("created_at"))
        if not within((at - last).days if last else None, [LAST_VISIT[x] for x in lv]):
            return False
    fr = as_list(f.get("frequency"), FREQS)
    if fr and not within(int(cust.get("visits") or 0), [FREQS[x] for x in fr]):
        return False
    if f.get("stores"):
        key = ("stores", tuple(sorted(f["stores"])))
        if key not in cache:
            cache[key] = _store_people(tid, f["stores"]) or set()
        if cust["id"] not in cache[key]:
            return False
    km = f.get("radius_km")
    if km:
        key = ("radius", float(km))
        if key not in cache:
            try:
                from features import campaign_kinds as K
                everyone = list(_db.customers.find({"tenant_id": tid}, {"_id": 0}))
                cache[key] = {c["id"] for c in K.zone_people(tid, everyone, float(km))[0]}
            except Exception:
                cache[key] = set()             # no shop position: nobody is « within »
        if cust["id"] not in cache[key]:
            return False
    return True


# ---------------------------------------------------------------------------
# when
# ---------------------------------------------------------------------------
def _hm(s: Optional[str], default: Tuple[int, int]) -> Tuple[int, int]:
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", (s or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else default


def _day_ok(sched: Dict[str, Any], d: date) -> bool:
    mode = sched.get("days") or "all"
    if mode == "weekdays":
        return d.weekday() < 5
    if mode == "specific":
        return d.weekday() in [int(x) for x in sched.get("weekdays") or []]
    return True


def _send_hour(tid: str, sched: Dict[str, Any]) -> Tuple[int, int]:
    """The time a time scenario leaves: its hour, or the shop's busiest hour
    (« Plage d'envoi intelligente ») when the visits say one."""
    if sched.get("smart"):
        try:
            from features import campaigns_page as CP
            best = CP.best_slot(tid)
            if best:
                return _hm(best["from"], (10, 0))
        except Exception:
            pass
    return _hm(sched.get("hour"), (10, 0))


def next_window(sched: Dict[str, Any], at: datetime) -> datetime:
    """The first moment at or after `at` inside the days and hours of an event
    scenario. A window that never opens (no day ticked) answers far away."""
    if not sched.get("window", True):
        days_only = True
    else:
        days_only = False
    fh, fm = _hm(sched.get("window_from"), (0, 0))
    th, tm = _hm(sched.get("window_to"), (23, 59))
    if days_only or (fh, fm) >= (th, tm):
        fh, fm, th, tm = 0, 0, 23, 59
    loc = _paris(at)
    for i in range(0, 8):
        d = (loc + timedelta(days=i)).date()
        if not _day_ok(sched, d):
            continue
        start, end = _from_paris(d, fh, fm), _from_paris(d, th, tm)
        if i == 0 and at > end:
            continue
        return max(at, start)
    return at + timedelta(days=3650)


# ---------------------------------------------------------------------------
# what
# ---------------------------------------------------------------------------
def _render(text: str, cust: Dict[str, Any], tenant: Dict[str, Any], extra: Dict[str, Any]) -> str:
    out = text or ""
    for k, v in (extra or {}).items():
        out = out.replace("{" + k + "}", str(v))
    try:
        import server as core
        return core.render_template(out, {**cust, "tenant_id": tenant.get("id")}, tenant)
    except Exception:
        return out


def _extra(scenario: str, cust: Dict[str, Any], ctx: Dict[str, Any], tpl: Dict[str, Any]) -> Dict[str, Any]:
    reward = tpl.get("reward_description") or "votre récompense"
    out: Dict[str, Any] = {"prochaine_récompense": reward, "prochaine_recompense": reward}
    out["nom"] = cust.get("name") or ""
    if scenario == "tier_up":
        if ctx.get("palier"):
            out["palier"] = ctx["palier"]
        else:
            try:
                from features.loyalty_card import TIER_LABELS
                out["palier"] = TIER_LABELS.get((cust.get("tier") or "").lower(), (cust.get("tier") or "").title())
            except Exception:
                out["palier"] = (cust.get("tier") or "").title()
        # {récompense}: the palier's own reward (paliers personnalisés), else the card's
        out["récompense"] = out["recompense"] = ctx.get("tier_reward") or reward
    if scenario == "near_reward":
        left = int(ctx.get("visits_left") or 1)
        out.update({"visites_restantes": left, "visite_s": "visite" if left == 1 else "visites",
                    "visits_left": left})
    if scenario == "referral":
        out.update({"visite_ami": "est revenu" if ctx.get("kind") == "next" else "est venu",
                    "filleul": ctx.get("filleul") or "votre ami", "parrain": ctx.get("parrain") or "votre parrain",
                    "points_gagnés": ctx.get("points") or 0, "points_gagnes": ctx.get("points") or 0})
    if scenario == "geo":
        out["établissement"] = ctx.get("store") or ""
        out["etablissement"] = ctx.get("store") or ""
    if scenario == "inactive":
        last = _aware(cust.get("last_visit_date")) or _aware(cust.get("created_at"))
        out["jours_absence"] = (_now() - last).days if last else ""
    return out


def _target_url(tid: str, row: Dict[str, Any], cust: Dict[str, Any]) -> Optional[str]:
    """Where the action button goes — any link the owner put."""
    btn = ((row.get("message") or {}).get("button") or {})
    if not btn.get("enabled"):
        return None
    from services import card_owner as CO
    serial = cust.get("barcode_id") or ""
    t = btn.get("link_type")
    if t == "url":
        return safe_url(btn.get("url"))
    if t == "google_review":
        return f"{public_base()}/api/avis/{serial}"
    if t == "rewards":                              # « Page Récompenses »: the card's offers and rewards
        return CO.owner_url(public_base(), serial, path="/offres")
    if t == "offer" and btn.get("offer_id"):
        return CO.owner_url(public_base(), serial, query={"offre": str(btn["offer_id"])})
    return CO.owner_url(public_base(), serial)


_URL = re.compile(r"^https?://[^\s/?#]+\.[^\s/?#]{2,}(?:[/?#]\S*)?$", re.I)


def safe_url(raw: Optional[str]) -> Optional[str]:
    s = (raw or "").strip()
    if s and not re.match(r"^[a-z][a-z0-9+.-]*:", s, re.I):
        s = "https://" + s.lstrip("/")
    return s if (s and len(s) <= 500 and _URL.match(s)) else None


def _deliver(tid: str, row: Dict[str, Any], cust: Dict[str, Any], ctx: Dict[str, Any],
             at: datetime) -> Optional[Dict[str, Any]]:
    """One client, one message. Returns what was said, or None."""
    scenario = row["scenario"]
    meta = SCENARIOS[scenario]
    tenant = _db.tenants.find_one({"id": tid}) or {}
    tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0}) or {}
    extra = _extra(scenario, cust, ctx, tpl)
    msg = row.get("message") or {}
    # a palier of its own (paliers personnalisés) speaks its own words
    raw_title = ctx.get("tier_title") or msg.get("title") or meta["title"]
    raw_body = ctx.get("tier_body") or msg.get("body") or meta["body"]
    title = _render(raw_title, cust, tenant, extra)[:160]
    body = _render(raw_body, cust, tenant, extra)[:600]
    target = _target_url(tid, row, cust)
    log_id = str(uuid.uuid4())
    click = f"{public_base()}/api/auto/c/{log_id}" if target else None
    btn = (msg.get("button") or {})
    label = (btn.get("label") or meta["button"])[:BUTTON_MAX] if target else None
    log = {"id": log_id, "tenant_id": tid, "automation_id": row["id"], "scenario": scenario,
           "customer_id": cust["id"], "sent_at": at, "title": title, "body": body,
           "button_label": label, "target_url": target, "image_url": msg.get("image_url"),
           "clicked_at": None, "status": "sent"}
    if ctx.get("cycle"):
        log["cycle"] = ctx["cycle"]
    if ctx.get("level") is not None:
        log["level"] = ctx["level"]
    _db.automation_log.insert_one(dict(log))
    _db.push_notifications.insert_one({"tenant_id": tid, "customer_id": cust["id"], "type": meta["push_kind"],
                                       "title": title, "body": body, "sent_at": at, "automatic": True,
                                       "automation_id": row["id"], "log_id": log_id})
    if scenario == "geo":                 # the card asked: it shows the message itself
        return {**log, "click_url": click}
    held = False
    try:
        import server as core
        # the button's text rides on the link (?b=): the service worker shows it
        # as the notification's own button where the phone can (Android)
        from urllib.parse import quote
        push_url = f"{click}?b={quote(label or '')}" if click else None
        res = core.dispatch_to_customer(tid, {**cust, "tenant_id": tid}, title, body,
                                        kind=meta["push_kind"], url=push_url) or {}
        held = bool(res.get("deferred")) or res.get("reason") == "marketing_off"
    except Exception as exc:
        print(f"automations: web push not sent ({exc})")
    if held:
        _db.automation_log.update_one({"id": log_id}, {"$set": {"status": "deferred"}})
    else:
        # the Wallet card: « Dernier message » + the button's link on the pass
        news = {"log_id": log_id, "title": title, "body": body, "label": label, "url": click, "at": at,
                "image_url": msg.get("image_url")}
        if scenario == "referral":
            # rides on the points field's own banner (« … Vous avez maintenant %@ points. »):
            # one notification, not two; the card page still shows it with its button
            news["pass"] = False
            total = int((_db.customers.find_one({"id": cust["id"]}, {"_id": 0, "points": 1}) or {}).get("points") or 0)
            _db.customers.update_one({"id": cust["id"]}, {"$set": {"points_news": {
                "text": f"{body.replace('%', '')} Vous avez maintenant %@ points.", "points": total, "at": at,
                "kind": "parrainage"}}})
        _db.customers.update_one({"id": cust["id"]}, {"$set": {"auto_news": news}})
        try:
            from features.wallet_passes import notify_customer
            g = meta.get("google")
            notify_customer(cust["id"], google_notify=({"kind": g, "header": title, "body": body} if g else None))
        except Exception as exc:
            print(f"automations: wallet not refreshed ({exc})")
    return {**log, "click_url": click, "deferred": held}


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------
def _active(tid: str, scenario: str) -> List[Dict[str, Any]]:
    return list(_db.automations.find({"tenant_id": tid, "scenario": scenario, "status": "active"},
                                     {"_id": 0}).sort("order", 1))


def _plan_ok(tid: str) -> bool:
    try:
        from features import plan_limits
        return plan_limits.allows_tenant(tid, "automations")
    except Exception:
        return True


TIER_CONDITIONS = ("points", "visits", "amount", "status")
TIER_REPEATS = ("each", "first", "custom")
TIER_RANK = {"bronze": 0, "silver": 1, "gold": 2, "vip": 3}


def lifetime_points(tid: str, cid: str) -> int:
    """Points earned since the start — never lowered by a reward (user,
    2026-10-11): visits, welcome bonus and parrainage points."""
    total = sum(int(v.get("points_awarded") or 0) for v in
                _db.visits.find({"tenant_id": tid, "customer_id": cid}, {"_id": 0, "points_awarded": 1}))
    total += sum(int(w.get("points") or 0) for w in
                 _db.welcome_bonus_claims.find({"tenant_id": tid, "customer_id": cid}, {"_id": 0, "points": 1}))
    for r in _db.referral_redemptions.find({"tenant_id": tid, "$or": [{"referrer_customer_id": cid},
                                                                      {"referee_customer_id": cid}]}, {"_id": 0}):
        if r.get("referrer_customer_id") == cid:
            total += int(r.get("referrer_points") or 0)
        if r.get("referee_customer_id") == cid:
            total += int(r.get("referee_points") or 0)
    return total


def palier_measure(tid: str, cust: Dict[str, Any], condition: str) -> float:
    if condition == "points":
        return lifetime_points(tid, cust["id"])
    if condition == "visits":
        return int(cust.get("visits") or 0)
    if condition == "amount":
        return float(cust.get("total_amount_paid") or 0)
    return 0


def palier_label(condition: str, value: Any) -> str:
    v = int(value)
    if condition == "points":
        return f"{v} point{'s' if v > 1 else ''}"
    if condition == "visits":
        return f"{v} visite{'s' if v > 1 else ''}"
    if condition == "amount":
        return f"{v} €"
    return str(value)


def _tier_level(tid: str, row: Dict[str, Any], cust: Dict[str, Any], ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The palier this client just reached for this automation, or None."""
    tr = row.get("trigger") or {}
    cond = tr.get("condition") or "status"          # carried-over automations: the statut
    if cond == "status":
        if ctx.get("event") != "tier":
            return None
        tier = (cust.get("tier") or "bronze").lower()
        from features.loyalty_card import TIER_LABELS
        return {"level": TIER_RANK.get(tier, 0), "label": TIER_LABELS.get(tier, tier.title()), "tier": None}
    if ctx.get("event") != "visit":
        return None
    value = palier_measure(tid, cust, cond)
    if tr.get("custom_tiers") and tr.get("tiers"):
        reached = [t for t in sorted(tr["tiers"], key=lambda t: t["value"]) if value >= t["value"]]
        if not reached:
            return None
        top = reached[-1]
        return {"level": top["value"], "label": palier_label(cond, top["value"]), "tier": top}
    step = int(tr.get("threshold") or 0)
    if step <= 0 or value < step:
        return None
    level = step if tr.get("repeat") == "first" else int(value // step) * step
    return {"level": level, "label": palier_label(cond, level), "tier": None}


def _eligible(tid: str, row: Dict[str, Any], cust: Dict[str, Any], ctx: Dict[str, Any], at: datetime) -> bool:
    """The scenario's own rule, on top of the targeting."""
    sc, tr = row["scenario"], row.get("trigger") or {}
    q = {"tenant_id": tid, "automation_id": row["id"], "customer_id": cust["id"]}
    if sc == "near_reward":
        if int(ctx.get("visits_left") or -1) != int(tr.get("visits_left") or 1):
            return False
        cyc = ctx.get("cycle")
        if _db.automation_log.find_one({**q, **({"cycle": cyc} if cyc else {})}) or \
                _db.automation_queue.find_one({**q, **({"ctx.cycle": cyc} if cyc else {})}):
            return False
    elif sc == "referral":
        if (tr.get("side") or "parrain") != ctx.get("side"):
            return False
    elif sc == "welcome":
        if _db.automation_log.find_one(q) or _db.automation_queue.find_one(q):
            return False
    elif sc == "geo":
        last = _db.automation_log.find_one(q, sort=[("sent_at", -1)])
        if last and at - _aware(last["sent_at"]) < timedelta(days=max(1, int(tr.get("cooldown_days") or 7))):
            return False
    elif sc == "google_review":
        tenant = _db.tenants.find_one({"id": tid}, {"_id": 0, "google_review_url": 1, "google_reviews_enabled": 1}) or {}
        if not (tenant.get("google_review_url") and tenant.get("google_reviews_enabled")):
            return False
        if tr.get("stop_after_click", True) and _db.google_review_clicks.find_one({"tenant_id": tid,
                                                                                  "customer_id": cust["id"]}):
            return False
        if _db.automation_queue.find_one(q):
            return False
        last = _db.automation_log.find_one(q, sort=[("sent_at", -1)])
        freq = tr.get("frequency") if tr.get("frequency") in GR_FREQS else "days"
        if freq == "once" and last:
            return False
        if freq == "days" and last and at - _aware(last["sent_at"]) < timedelta(days=max(1, int(tr.get("every_days") or 30))):
            return False
    elif sc == "tier_up":
        if _db.automation_queue.find_one(q):
            return False
        hit = _tier_level(tid, row, cust, ctx)
        if not hit:
            return False
        logs = list(_db.automation_log.find(q, {"_id": 0, "level": 1, "sent_at": 1}))
        if tr.get("repeat") == "first" and logs:
            return False                          # « uniquement la première fois »
        if logs and hit["level"] <= max(int(x.get("level") or 0) for x in logs):
            return False                          # this palier (or a higher one) was already told
        if tr.get("repeat") == "custom" and logs:
            last = max(_aware(x["sent_at"]) for x in logs)
            if at - last < timedelta(days=max(1, int(tr.get("min_days") or 1))):
                return False                      # too soon: the next visit past the gap will tell it
        ctx.update({"level": hit["level"], "palier": hit["label"],
                    **({"tier_title": hit["tier"].get("title"), "tier_body": hit["tier"].get("body"),
                        "tier_reward": hit["tier"].get("reward")} if hit.get("tier") else {})})
    elif sc == "custom":
        t = tr.get("type")
        want = {"visits": "visit", "after_visit": "visit", "after_signup": "signup"}.get(t)
        if not want or ctx.get("event") != want:
            return False
        if _db.automation_queue.find_one(q):
            return False                        # one waiting at a time per client
        if t == "visits":
            n, every = int(cust.get("visits") or 0), int(tr.get("visits") or 0)
            if tr.get("visits_repeat") == "every":     # « toutes les N visites » (as the palier's multiples)
                if every <= 0 or n <= 0 or n % every or _db.automation_log.find_one({**q, "level": n}):
                    return False
                ctx["level"] = n
            elif n != every or _db.automation_log.find_one(q):
                return False
        elif t == "after_signup":
            if _db.automation_log.find_one(q):
                return False
        elif t == "after_visit":
            cool = int(tr.get("cooldown_days") or 0)
            last = _db.automation_log.find_one(q, sort=[("sent_at", -1)])
            if cool and last and at - _aware(last["sent_at"]) < timedelta(days=cool):
                return False
    return True


def date_due(tr: Dict[str, Any], d: date) -> bool:
    """A « Personnalisée » on a date: is it today (Paris)?"""
    mode = tr.get("date_mode") or "once"
    if mode == "weekly":
        return d.weekday() == int(tr.get("weekday") or 0)
    if mode == "monthly":
        import calendar
        want = int(tr.get("monthday") or 1)
        return d.day == min(want, calendar.monthrange(d.year, d.month)[1])     # « le 31 » = last day
    try:
        on = date.fromisoformat(str(tr.get("date") or "")[:10])
    except ValueError:
        return False
    if mode == "yearly":
        if on.month == 2 and on.day == 29 and not (d.year % 4 == 0 and (d.year % 100 or d.year % 400 == 0)):
            return d.month == 2 and d.day == 28
        return (d.month, d.day) == (on.month, on.day)
    return d == on


def _delay(tr: Dict[str, Any]) -> timedelta:
    v = max(0, int(tr.get("delay_value") or 0))
    unit = tr.get("delay_unit") or "hours"
    return timedelta(minutes=v) if unit == "minutes" else timedelta(days=v) if unit == "days" else timedelta(hours=v)


def fire(scenario: str, tid: str, cust: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None,
         at: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """An event happened to a client: every active automation of that scenario
    that targets them sends now, or waits for its window. Never raises."""
    at = at or _now()
    ctx = dict(ctx or {})
    out: List[Dict[str, Any]] = []
    try:
        if not cust or not cust.get("id") or not _plan_ok(tid):
            return out
        migrate(tid)
        cache: Dict[str, Any] = {}
        base_ctx = ctx
        for row in _active(tid, scenario):
            ctx = dict(base_ctx)                   # each automation reads its own palier
            try:
                if not matches(tid, row, cust, at, cache) or not _eligible(tid, row, cust, ctx, at):
                    continue
                due = at + _delay(row.get("trigger") or {})
                if scenario != "geo":
                    due = next_window(row.get("schedule") or {}, due)
                if due <= at + timedelta(seconds=30):
                    said = _deliver(tid, row, cust, ctx, at)
                    if said:
                        out.append(said)
                else:
                    _db.automation_queue.insert_one({"id": str(uuid.uuid4()), "tenant_id": tid,
                                                     "automation_id": row["id"], "customer_id": cust["id"],
                                                     "due_at": due, "ctx": ctx, "created_at": at})
                    out.append({"queued": True, "automation_id": row["id"], "due_at": due})
            except Exception as exc:
                print(f"automations: {scenario} {row.get('id')} failed ({exc})")
    except Exception as exc:
        print(f"automations: fire {scenario} failed ({exc})")
    return out


# ---------------------------------------------------------------------------
# the clock
# ---------------------------------------------------------------------------
def tick_seen(at: datetime) -> bool:
    row = _db.automation_meta.find_one({"_id": "tick"}) or {}
    last = _aware(row.get("at"))
    return bool(last and at - last < timedelta(hours=2))


def _birthday_due(tid: str, row: Dict[str, Any], at: datetime) -> List[Dict[str, Any]]:
    """Clients whose birthday (± offset) fell in the last 7 days up to today,
    not greeted by this automation this year — a skipped day (« jours
    ouvrés ») or a missed run is caught up, never doubled."""
    off = int((row.get("trigger") or {}).get("offset_days") or 0)
    today = _paris(at).date()
    keys = {}
    for back in range(0, 7):
        d = today - timedelta(days=back)
        bday = d - timedelta(days=off)            # offset −3 = three days BEFORE the birthday
        keys[bday.strftime("%m-%d")] = d
    people = list(_db.customers.find({"tenant_id": tid, "birthday": {"$in": list(keys)}}, {"_id": 0}))
    # one birthday a year: greeted by this automation in the last 300 days = done
    done = set(_db.automation_log.distinct("customer_id", {"tenant_id": tid, "automation_id": row["id"],
                                                           "sent_at": {"$gte": at - timedelta(days=300)}}))
    done |= set(_db.automation_queue.distinct("customer_id", {"automation_id": row["id"]}))
    return [c for c in people if c["id"] not in done]


def _inactive_due(tid: str, row: Dict[str, Any], at: datetime) -> List[Dict[str, Any]]:
    tr = row.get("trigger") or {}
    days = max(1, int(tr.get("days") or 30))
    cutoff = at - timedelta(days=days)
    out = []
    for c in _db.customers.find({"tenant_id": tid}, {"_id": 0}):
        last = _aware(c.get("last_visit_date")) or _aware(c.get("created_at"))
        if not last or last > cutoff:
            continue
        prev = _db.automation_log.find_one({"tenant_id": tid, "automation_id": row["id"], "customer_id": c["id"]},
                                           sort=[("sent_at", -1)])
        if prev:
            sent = _aware(prev["sent_at"])
            if sent >= last and tr.get("repeat") != "every":
                continue                          # once per absence: until they come back
            if tr.get("repeat") == "every" and at - sent < timedelta(days=max(1, int(tr.get("every_days") or 30))):
                continue
        out.append(c)
    return out


def run_due(at: Optional[datetime] = None, source: str = "daily") -> Dict[str, Any]:
    """Release what is due. `source` « tick » (every 15 min, Vercel Pro) or
    « daily » (07:00 UTC): without a recent tick the daily run sends all of
    today's — early rather than never."""
    at = at or _now()
    if source == "tick":
        _db.automation_meta.update_one({"_id": "tick"}, {"$set": {"at": at}}, upsert=True)
    strict = source == "tick" or tick_seen(at)
    loc_today = _paris(at).date()
    summary = {"at": at.isoformat(), "queued_sent": 0, "time_sent": 0, "errors": 0, "strict": strict}
    # 1. the event messages that waited for their window / delay
    horizon = at if strict else _from_paris(loc_today, 23, 59)
    for q in list(_db.automation_queue.find({"due_at": {"$lte": horizon}}, {"_id": 0}).limit(5000)):
        _db.automation_queue.delete_one({"id": q["id"]})
        row = _db.automations.find_one({"id": q["automation_id"], "status": "active"}, {"_id": 0})
        cust = _db.customers.find_one({"id": q["customer_id"]}, {"_id": 0})
        if not row or not cust or not _plan_ok(row["tenant_id"]) or not matches(row["tenant_id"], row, cust, at):
            continue
        try:
            if _deliver(row["tenant_id"], row, cust, q.get("ctx") or {}, at):
                summary["queued_sent"] += 1
        except Exception:
            summary["errors"] += 1
    # 2. the time scenarios, once a day each, at their hour
    for row in list(_db.automations.find({"status": "active", "scenario": {"$in": ["birthday", "inactive", "custom"]}},
                                         {"_id": 0})):
        if row["scenario"] == "custom" and (row.get("trigger") or {}).get("type") != "date":
            continue
        tid = row["tenant_id"]
        try:
            sched = row.get("schedule") or {}
            if not _day_ok(sched, loc_today) or not _plan_ok(tid):
                continue
            last = _aware(row.get("last_run_at"))
            if last and _paris(last).date() == loc_today:
                continue
            hh, mm = _send_hour(tid, sched)
            if strict and at < _from_paris(loc_today, hh, mm):
                continue
            if row["scenario"] == "custom":
                if not date_due(row.get("trigger") or {}, loc_today):
                    continue
                people = list(_db.customers.find({"tenant_id": tid}, {"_id": 0}))
            else:
                people = _birthday_due(tid, row, at) if row["scenario"] == "birthday" else _inactive_due(tid, row, at)
            cache: Dict[str, Any] = {}
            for c in people:
                if matches(tid, row, c, at, cache) and _deliver(tid, row, c, {}, at):
                    summary["time_sent"] += 1
            _db.automations.update_one({"id": row["id"]}, {"$set": {"last_run_at": at}})
        except Exception as exc:
            summary["errors"] += 1
            print(f"automations: {row.get('id')} failed ({exc})")
    return summary


# ---------------------------------------------------------------------------
# the card and the pass read the latest message
# ---------------------------------------------------------------------------
NEWS_DAYS = 14


def latest_for(cust: Dict[str, Any], at: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    n = cust.get("auto_news") if isinstance(cust.get("auto_news"), dict) else None
    if not n:
        return None
    sent = _aware(n.get("at"))
    if not sent or (at or _now()) - sent > timedelta(days=NEWS_DAYS):
        return None
    return {"log_id": n.get("log_id"), "title": n.get("title"), "body": n.get("body"), "pass": n.get("pass", True),
            "button_label": n.get("label"), "button_url": n.get("url"), "image_url": n.get("image_url"),
            "sent_at": sent.isoformat()}


@router.get("/api/auto/c/{log_id}")
def click(log_id: str):
    """The action button: counted, then on to wherever the owner pointed it."""
    row = _db.automation_log.find_one({"id": log_id}, {"_id": 0})
    if not row or not row.get("target_url"):
        raise HTTPException(status_code=404, detail="Lien introuvable")
    if not row.get("clicked_at"):
        _db.automation_log.update_one({"id": log_id}, {"$set": {"clicked_at": _now()}})
    return RedirectResponse(url=row["target_url"], status_code=302)


# ---------------------------------------------------------------------------
# the owner's page
# ---------------------------------------------------------------------------
def _me(token: TokenData) -> Dict[str, Any]:
    return _db.users.find_one({"email": token.email}, {"_id": 0}) or {}


def _own_stores(token: TokenData) -> Optional[List[str]]:
    """An administrateur's automations reach its establishments only."""
    if token.role == "business_owner":
        return None
    me = _me(token)
    from features import team_access as T
    all_ids = [s["id"] for s in T.stores(token.tenant_id)]
    mine = T._covered(me, all_ids) if me else []
    return None if set(all_ids) <= set(mine) else list(mine)


def _opened(tid: str, rows: List[Dict[str, Any]]) -> int:
    """Opens of logged messages: the card opened within 72 h, or the button."""
    from services import card_opens
    n = 0
    by_time: Dict[Any, List[Dict[str, Any]]] = {}
    for r in rows:
        if r.get("clicked_at"):
            n += 1
            continue
        by_time.setdefault((r["sent_at"].date() if isinstance(r["sent_at"], datetime) else None), []).append(r)
    for _, group in by_time.items():
        sent = min(_aware(g["sent_at"]) for g in group)
        ids = [g["customer_id"] for g in group]
        try:
            n += len(card_opens.opened_ids(_db, tid, ids, sent, None, 72))
        except Exception:
            pass
    return n


def _stats(tid: str, at: datetime) -> Dict[str, Any]:
    def window(a: datetime, b: datetime) -> List[Dict[str, Any]]:
        return list(_db.automation_log.find({"tenant_id": tid, "sent_at": {"$gte": a, "$lt": b},
                                             "status": {"$ne": "deferred"}},
                                            {"_id": 0, "customer_id": 1, "sent_at": 1, "clicked_at": 1}))
    now_rows, was_rows = window(at - timedelta(days=30), at), window(at - timedelta(days=60), at - timedelta(days=30))
    reach_now, reach_was = len({r["customer_id"] for r in now_rows}), len({r["customer_id"] for r in was_rows})
    open_now = round(_opened(tid, now_rows) / len(now_rows) * 100, 1) if now_rows else 0.0
    open_was = round(_opened(tid, was_rows) / len(was_rows) * 100, 1) if was_rows else 0.0

    def delta(a: float, b: float) -> Optional[float]:
        return None if not b else round((a - b) / b * 100)
    return {"reach": reach_now, "reach_delta": delta(reach_now, reach_was),
            "open_rate": open_now, "open_delta": (round(open_now - open_was, 1) if was_rows else None)}


def _row_view(r: Dict[str, Any], tid: str) -> Dict[str, Any]:
    meta = SCENARIOS[r["scenario"]]
    logs = list(_db.automation_log.find({"tenant_id": tid, "automation_id": r["id"], "status": {"$ne": "deferred"}},
                                        {"_id": 0, "customer_id": 1, "sent_at": 1, "clicked_at": 1}))
    reach = len({x["customer_id"] for x in logs})
    opened = _opened(tid, logs) if logs else 0
    clicks = sum(1 for x in logs if x.get("clicked_at"))
    out = {k: r.get(k) for k in ("id", "scenario", "name", "status", "trigger", "message", "targeting", "schedule",
                                 "store_ids")}
    out.update({"label": meta["label"], "sub": meta["sub"], "icon": meta["icon"], "tone": meta["tone"],
                "kind": "time" if is_timed(r["scenario"], r.get("trigger")) else "event",
                "trigger_text": trigger_text(r), "schedule_text": schedule_text(r),
                "reach": reach, "sent": len(logs), "open_rate": round(opened / len(logs) * 100) if logs else None,
                "clicks": clicks,
                "updated_at": (_aware(r.get("updated_at")) or _now()).isoformat(),
                "last_run_at": (d.isoformat() if (d := _aware(r.get("last_run_at"))) else None)})
    return out


UNITS = {"minutes": ("minute", "minutes"), "hours": ("heure", "heures"), "days": ("jour", "jours")}
MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
             "novembre", "décembre"]
WEEKDAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _span(tr: Dict[str, Any]) -> str:
    v = int(tr.get("delay_value") or 0)
    one, many = UNITS.get(tr.get("delay_unit") or "hours", UNITS["hours"])
    return f"{v} {one if v == 1 else many}"


def custom_text(tr: Dict[str, Any]) -> str:
    t = tr.get("type")
    if t == "visits":
        n = int(tr.get("visits") or 0)
        if tr.get("visits_repeat") == "every":
            return "À chaque visite" if n == 1 else f"Toutes les {n} visites"
        return f"À la {n}{'re' if n == 1 else 'e'} visite"
    if t == "after_signup":
        return "Dès l'inscription" if not int(tr.get("delay_value") or 0) else f"{_span(tr)} après l'inscription"
    if t == "after_visit":
        base = "Après chaque visite" if not int(tr.get("delay_value") or 0) else f"{_span(tr)} après chaque visite"
        cool = int(tr.get("cooldown_days") or 0)
        return base + (f" · au plus tous les {cool} j" if cool else "")
    if t == "date":
        mode = tr.get("date_mode") or "once"
        if mode == "weekly":
            return f"Chaque {WEEKDAYS_FR[int(tr.get('weekday') or 0)]}"
        if mode == "monthly":
            n = int(tr.get("monthday") or 1)
            return f"Le {n}{'er' if n == 1 else ''} de chaque mois"
        try:
            on = date.fromisoformat(str(tr.get("date") or "")[:10])
        except ValueError:
            return "Date à choisir"
        day = f"{on.day}{'er' if on.day == 1 else ''} {MONTHS_FR[on.month - 1]}"
        return f"Chaque année le {day}" if mode == "yearly" else f"Le {day} {on.year}"
    return "Déclencheur personnalisé"


def tier_text(tr: Dict[str, Any]) -> str:
    cond = tr.get("condition") or "status"
    rep_ = tr.get("repeat") or "each"
    gap = f" · au moins {int(tr.get('min_days') or 1)} j entre deux" if rep_ == "custom" else ""
    first = " (première fois)" if rep_ == "first" else ""
    if cond == "status":
        return ("Nouveau statut (Bronze → Argent → Or → VIP)" if rep_ != "first" else "Premier changement de statut") + gap
    if tr.get("custom_tiers") and tr.get("tiers"):
        vals = ", ".join(str(t["value"]) for t in tr["tiers"])
        unit = {"points": "points", "visits": "visites", "amount": "€"}[cond]
        return f"Paliers : {vals} {unit}{first}{gap}"
    label = palier_label(cond, tr.get("threshold") or 0)
    return (f"À {label}" if rep_ == "first" else f"Tous les {label}") + gap


def trigger_text(r: Dict[str, Any]) -> str:
    sc, tr = r["scenario"], r.get("trigger") or {}
    if sc == "tier_up":
        return tier_text(tr)
    if sc == "custom":
        return custom_text(tr)
    if sc == "birthday":
        off = int(tr.get("offset_days") or 0)
        return "Le jour même" if off == 0 else (f"{-off} jour{'s' if off < -1 else ''} avant" if off < 0
                                                 else f"{off} jour{'s' if off > 1 else ''} après")
    if sc == "near_reward":
        n = int(tr.get("visits_left") or 1)
        return f"À {n} visite{'s' if n > 1 else ''} de la récompense"
    if sc == "inactive":
        n = int(tr.get("days") or 30)
        return f"Après {n} jours sans visite" + (" · puis tous les " + str(int(tr.get('every_days') or 30)) + " j"
                                                if tr.get("repeat") == "every" else "")
    if sc == "referral":
        return "Au parrain" if (tr.get("side") or "parrain") == "parrain" else "Au filleul"
    if sc == "google_review":
        f = tr.get("frequency")
        n = int(tr.get("every_days") or 30)
        return ("Après chaque visite" if f == "every_scan" else "Une seule fois" if f == "once"
                else "Au plus une fois par jour" if n == 1 else f"Au plus tous les {n} jours")
    if sc == "geo":
        n = int(tr.get("cooldown_days") or 7)
        return "Au plus une fois par jour" if n == 1 else f"Au plus tous les {n} jours"
    return SCENARIOS[sc]["trigger_label"]


DAY_NAMES = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def schedule_text(r: Dict[str, Any]) -> str:
    s = r.get("schedule") or {}
    days = {"all": "Tous les jours", "weekdays": "Jours ouvrés"}.get(s.get("days") or "all") or \
        ", ".join(DAY_NAMES[int(d)] for d in sorted(s.get("weekdays") or []))
    if is_timed(r["scenario"], r.get("trigger")):
        return f"{days} · {'plage intelligente' if s.get('smart') else (s.get('hour') or '10:00')}"
    if not s.get("window", True):
        return f"{days} · immédiat"
    return f"{days} · {s.get('window_from') or '09:00'}–{s.get('window_to') or '21:00'}"


def _list(tid: str, token: TokenData) -> Dict[str, Any]:
    migrate(tid)
    at = _now()
    q: Dict[str, Any] = {"tenant_id": tid}
    rows = [_row_view(r, tid) for r in _db.automations.find(q, {"_id": 0}).sort([("order", 1), ("created_at", 1)])]
    active = sum(1 for r in rows if r["status"] == "active")
    counts = {"all": len(rows), "active": active, "paused": sum(1 for r in rows if r["status"] == "paused"),
              "draft": sum(1 for r in rows if r["status"] == "draft")}
    from features import campaigns_page as CP
    tenant = _db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "logo_url": 1, "brand_fields": 1}) or {}
    offers = []
    for c in _db.campaigns.find({"tenant_id": tid, "status": "sent"}, {"_id": 0}).sort("sent_at", -1).limit(40):
        try:
            from features import campaign_kinds as K
            if K.is_live(c, at) and c.get("kind") != "defi":
                offers.append({"id": c["id"], "name": c.get("name") or "Offre", "terms": K.terms_label(c)})
        except Exception:
            pass
    from features import team_access as T
    return {
        "rows": rows, "counts": counts,
        "stats": {"active": active, "total": len(rows), **_stats(tid, at)},
        "scenarios": [{"key": k, **{f: SCENARIOS[k][f] for f in ("label", "sub", "icon", "tone", "kind",
                                                                  "trigger_label", "title", "body", "button")},
                       "variables": VARIABLES["common"] + VARIABLES[k]} for k in ORDER],
        "segments": CP.segment_options(tid, at, None),
        "stores": [{"id": s["id"], "name": s.get("name")} for s in T.stores(tid)],
        "offers": offers,
        "best_slot": CP.best_slot(tid),
        "has_position": CP._has_position(tid),
        "google_review_ready": bool(tenant.get("google_review_url") and tenant.get("google_reviews_enabled")),
        "geo_ready": bool(tenant.get("geo_enabled")),
        "shop": tenant.get("campaign_sender_name") or tenant.get("name") or "",
        "logo_url": (tpl.get("brand_fields") or {}).get("logo_url") or tpl.get("logo_url") or "",
        "can_edit": token.role in EDITORS,
        "tick": tick_seen(at),
    }


@router.get("/api/owner/automations")
def list_automations(token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    return _list(token_data.tenant_id, token_data)


class ButtonIn(BaseModel):
    enabled: bool = False
    label: Optional[str] = None
    link_type: Optional[str] = "card"
    offer_id: Optional[str] = None
    url: Optional[str] = None


class MessageIn(BaseModel):
    title: str = ""
    body: str = ""
    image_url: Optional[str] = None
    button: ButtonIn = ButtonIn()


class FiltersIn(BaseModel):
    gender: Any = []
    age: Any = []
    frequency: Any = []
    spent: Any = []
    last_visit: Any = []
    stores: List[str] = []
    radius_km: Any = None


class TargetingIn(BaseModel):
    mode: str = "all"
    segment: Optional[str] = None
    filters: FiltersIn = FiltersIn()


class ScheduleIn(BaseModel):
    days: str = "all"
    weekdays: List[Any] = []
    hour: Optional[str] = None
    smart: bool = False
    window: bool = True
    window_from: Optional[str] = "09:00"
    window_to: Optional[str] = "21:00"


class AutomationIn(BaseModel):
    scenario: str
    name: Optional[str] = None
    status: str = "active"
    trigger: Dict[str, Any] = {}
    message: MessageIn
    targeting: TargetingIn = TargetingIn()
    schedule: ScheduleIn = ScheduleIn()


def _int(v: Any, lo: int, hi: int, label: str) -> int:
    if isinstance(v, bool):
        raise HTTPException(status_code=400, detail=f"{label} : un nombre est attendu.")
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{label} : un nombre est attendu.")
    if not (lo <= n <= hi):
        raise HTTPException(status_code=400, detail=f"{label} : entre {lo} et {hi}.")
    return n


def clean(body: AutomationIn, tid: str) -> Dict[str, Any]:
    """Everything the wizard sends, checked again. French errors."""
    sc = body.scenario
    if sc not in SCENARIOS:
        raise HTTPException(status_code=400, detail="Scénario inconnu.")
    if body.status not in ("active", "paused", "draft"):
        raise HTTPException(status_code=400, detail="Statut inconnu.")
    draft = body.status == "draft"
    tr_in = body.trigger or {}
    tr = _default_trigger(sc)
    if "delay_value" in tr_in:
        tr["delay_value"] = _int(tr_in["delay_value"], 0, 365, "Délai d'envoi")
    if tr_in.get("delay_unit") in ("minutes", "hours", "days"):
        tr["delay_unit"] = tr_in["delay_unit"]
    if sc == "birthday":
        tr["offset_days"] = _int(tr_in.get("offset_days", 0), -30, 30, "Jours avant / après")
    elif sc == "near_reward":
        tr["visits_left"] = _int(tr_in.get("visits_left", 1), 1, 50, "Visites avant la récompense")
    elif sc == "inactive":
        tr["days"] = _int(tr_in.get("days", 30), 7, 365, "Jours sans visite")
        tr["repeat"] = "every" if tr_in.get("repeat") == "every" else "once"
        tr["every_days"] = _int(tr_in.get("every_days", 30), 7, 365, "Répéter tous les")
    elif sc == "referral":
        if tr_in.get("side") not in ("parrain", "filleul"):
            raise HTTPException(status_code=400, detail="Choisissez qui reçoit le message : parrain ou filleul.")
        tr["side"] = tr_in["side"]
    elif sc == "geo":
        tr["cooldown_days"] = _int(tr_in.get("cooldown_days", 7), 1, 90, "Délai entre deux messages")
    elif sc == "google_review":
        if tr_in.get("frequency", "days") not in GR_FREQS:
            raise HTTPException(status_code=400, detail="Fréquence inconnue.")
        tr["frequency"] = tr_in.get("frequency", "days")
        tr["every_days"] = _int(tr_in.get("every_days", 30), 1, 365, "Fréquence (jours)")
        tr["stop_after_click"] = bool(tr_in.get("stop_after_click", True))
    elif sc == "tier_up":
        cond = tr_in.get("condition", "points")
        if cond not in TIER_CONDITIONS:
            raise HTTPException(status_code=400, detail="Choisissez la condition d'envoi.")
        rep_ = tr_in.get("repeat", "each")
        if rep_ not in TIER_REPEATS:
            raise HTTPException(status_code=400, detail="Répétition inconnue.")
        tr.update(condition=cond, repeat=rep_, custom_tiers=False, tiers=[])
        unit = {"points": "Nombre de points", "visits": "Nombre de visites", "amount": "Montant d'achats (€)"}
        if rep_ == "custom":
            tr["min_days"] = _int(tr_in.get("min_days", 7), 1, 365, "Délai minimum entre deux envois (jours)")
        if cond != "status":
            tr["threshold"] = _int(tr_in.get("threshold", 200), 1, 1_000_000, unit[cond])
            if tr_in.get("custom_tiers"):
                raw = tr_in.get("tiers") or []
                if not isinstance(raw, list) or not raw:
                    raise HTTPException(status_code=400, detail="Ajoutez au moins un palier.")
                if len(raw) > 10:
                    raise HTTPException(status_code=400, detail="10 paliers au maximum.")
                tiers, seen = [], set()
                for i, t_in in enumerate(raw, 1):
                    t_in = t_in if isinstance(t_in, dict) else {}
                    v = _int(t_in.get("value"), 1, 1_000_000, f"Palier {i}")
                    if v in seen:
                        raise HTTPException(status_code=400, detail=f"Deux paliers ont la même valeur ({v}).")
                    seen.add(v)
                    tt = re.sub(r"\s+", " ", str(t_in.get("title") or "")).strip()
                    tb = re.sub(r"[ \t]+", " ", str(t_in.get("body") or "")).strip()
                    rw = re.sub(r"\s+", " ", str(t_in.get("reward") or "")).strip()
                    if not draft and (not tt or not tb):
                        raise HTTPException(status_code=400, detail=f"Palier {palier_label(cond, v)} : écrivez son titre et son message.")
                    if len(tt) > TITLE_MAX or len(tb) > BODY_MAX:
                        raise HTTPException(status_code=400, detail=f"Palier {palier_label(cond, v)} : titre {TITLE_MAX} / message {BODY_MAX} caractères au maximum.")
                    if len(rw) > 80:
                        raise HTTPException(status_code=400, detail=f"Palier {palier_label(cond, v)} : récompense de 80 caractères au maximum.")
                    tiers.append({"value": v, "title": tt, "body": tb, "reward": rw})
                tr.update(custom_tiers=True, tiers=sorted(tiers, key=lambda t: t["value"]))
    elif sc == "custom":
        t = tr_in.get("type")
        if t not in CUSTOM_TYPES:
            raise HTTPException(status_code=400, detail="Choisissez quand envoyer ce message.")
        tr["type"] = t
        if t == "visits":
            tr["visits"] = _int(tr_in.get("visits", 5), 1, 1000, "Nombre de visites")
            tr["visits_repeat"] = "every" if tr_in.get("visits_repeat") == "every" else "once"
        if t == "after_visit":
            tr["cooldown_days"] = _int(tr_in.get("cooldown_days", 0), 0, 365, "Au plus une fois tous les")
        if t == "date":
            mode = tr_in.get("date_mode", "once")
            if mode not in DATE_MODES:
                raise HTTPException(status_code=400, detail="Récurrence inconnue.")
            tr["date_mode"] = mode
            if mode in ("once", "yearly"):
                try:
                    on = date.fromisoformat(str(tr_in.get("date") or "")[:10])
                except ValueError:
                    raise HTTPException(status_code=400, detail="Choisissez la date d'envoi.")
                if mode == "once" and not draft and on < _paris(_now()).date():
                    raise HTTPException(status_code=400, detail="Cette date est déjà passée.")
                tr["date"] = on.isoformat()
            if mode == "weekly":
                tr["weekday"] = _int(tr_in.get("weekday", 0), 0, 6, "Jour de la semaine")
            if mode == "monthly":
                tr["monthday"] = _int(tr_in.get("monthday", 1), 1, 31, "Jour du mois")
    m = body.message
    title, text = re.sub(r"\s+", " ", m.title or "").strip(), re.sub(r"[ \t]+", " ", m.body or "").strip()
    if not draft and (not title or not text):
        raise HTTPException(status_code=400, detail="Le titre et le message sont obligatoires.")
    if len(title) > TITLE_MAX:
        raise HTTPException(status_code=400, detail=f"Titre : {TITLE_MAX} caractères au maximum.")
    if len(text) > BODY_MAX:
        raise HTTPException(status_code=400, detail=f"Message : {BODY_MAX} caractères au maximum.")
    img = (m.image_url or "").strip() or None
    if img and not (img.startswith("data:image/") or img.startswith("https://")):
        raise HTTPException(status_code=400, detail="Image invalide.")
    if img and len(img) > 2_800_000:
        raise HTTPException(status_code=400, detail="L'image dépasse 2 Mo.")
    b = m.button
    button = {"enabled": bool(b.enabled), "label": (b.label or "").strip()[:BUTTON_MAX] or SCENARIOS[sc]["button"],
              "link_type": b.link_type if b.link_type in LINK_TYPES else "card", "offer_id": None, "url": None}
    if b.enabled:
        if not (b.label or "").strip():
            raise HTTPException(status_code=400, detail="Indiquez le texte du bouton.")
        if len((b.label or "").strip()) > BUTTON_MAX:
            raise HTTPException(status_code=400, detail=f"Texte du bouton : {BUTTON_MAX} caractères au maximum.")
        if button["link_type"] == "url":
            u = safe_url(b.url)
            if not u:
                raise HTTPException(status_code=400, detail="Lien invalide : saisissez une adresse web, par exemple https://monsite.fr.")
            button["url"] = u
        if button["link_type"] == "offer":
            if not b.offer_id or not _db.campaigns.find_one({"tenant_id": tid, "id": b.offer_id}):
                raise HTTPException(status_code=400, detail="Choisissez une offre.")
            button["offer_id"] = b.offer_id
        if button["link_type"] == "google_review":
            t = _db.tenants.find_one({"id": tid}, {"_id": 0, "google_review_url": 1}) or {}
            if not t.get("google_review_url"):
                raise HTTPException(status_code=400, detail="Ajoutez d'abord votre lien Google (Insights › Avis Google).")
    t = body.targeting
    if t.mode not in TARGET_MODES:
        raise HTTPException(status_code=400, detail="Ciblage inconnu.")
    if t.mode == "segment" and not t.segment:
        raise HTTPException(status_code=400, detail="Choisissez un segment.")
    f = t.filters
    picked: Dict[str, List[str]] = {}
    for key, val, allowed, label in (("gender", f.gender, GENDERS, "Genre"), ("age", f.age, AGES, "Âge"),
                                     ("frequency", f.frequency, FREQS, "Fréquence de visite"),
                                     ("spent", f.spent, SPENT, "Montant total des achats"),
                                     ("last_visit", f.last_visit, LAST_VISIT, "Dernière visite")):
        raw = [] if val in (None, "", "all") else (val if isinstance(val, list) else [val])
        if any(str(x) not in allowed for x in raw):
            raise HTTPException(status_code=400, detail=f"{label} : valeur inconnue.")
        picked[key] = as_list(raw, allowed)
    radius = None
    if f.radius_km not in (None, "", 0, "0"):
        radius = _int(f.radius_km, 1, 50, "Rayon (km)")
        if radius not in RADII:
            raise HTTPException(status_code=400, detail="Rayon (km) : 1, 2, 5, 10, 20 ou 50 km.")
        if t.mode != "all":
            from features import campaigns_page as CPG
            if not CPG._has_position(tid):
                raise HTTPException(status_code=400, detail="La position de votre établissement est inconnue : placez-la dans Paramètres › Établissement pour filtrer par distance.")
    from features import team_access as T
    known = {s["id"] for s in T.stores(tid)}
    stores = [s for s in dict.fromkeys(f.stores or []) if s in known]
    s = body.schedule
    if s.days not in DAY_MODES:
        raise HTTPException(status_code=400, detail="Jours d'envoi inconnus.")
    weekdays = sorted({_int(d, 0, 6, "Jour") for d in (s.weekdays or [])})
    if s.days == "specific" and not weekdays:
        raise HTTPException(status_code=400, detail="Cochez au moins un jour d'envoi.")
    timed = is_timed(sc, tr)
    hour = None
    if timed:
        hh = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", (s.hour or "10:00").strip())
        if not hh:
            raise HTTPException(status_code=400, detail="Heure d'envoi invalide.")
        hour = hh.group(0)
    wf, wt = (s.window_from or "09:00").strip(), (s.window_to or "21:00").strip()
    if not timed and s.window:
        for v in (wf, wt):
            if not re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", v):
                raise HTTPException(status_code=400, detail="Plage horaire invalide.")
        if wt <= wf:
            raise HTTPException(status_code=400, detail="La fin de la plage horaire doit être après son début.")
    name = re.sub(r"\s+", " ", body.name or "").strip()[:NAME_MAX] or SCENARIOS[sc]["label"]
    return {
        "scenario": sc, "name": name, "status": body.status, "trigger": tr,
        "message": {"title": title, "body": text, "image_url": img, "button": button},
        "targeting": {"mode": t.mode, "segment": t.segment if t.mode == "segment" else None,
                      "filters": ({"gender": [], "age": [], "frequency": [], "spent": [], "last_visit": [],
                                   "stores": [], "radius_km": None} if t.mode == "all" else
                                  {**picked, "stores": stores, "radius_km": radius})},
        "schedule": {"days": s.days, "weekdays": weekdays if s.days == "specific" else [0, 1, 2, 3, 4, 5, 6],
                     "hour": hour, "smart": bool(s.smart) if timed else False,
                     "window": bool(s.window) if not timed else False,
                     "window_from": wf, "window_to": wt},
    }


def _own(tid: str, aid: str) -> Dict[str, Any]:
    row = _db.automations.find_one({"tenant_id": tid, "id": aid}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="Automatisation introuvable.")
    return row


def _guard(token: TokenData, row: Optional[Dict[str, Any]] = None) -> None:
    if token.role not in EDITORS:
        raise HTTPException(status_code=403, detail="Seuls le propriétaire et les administrateurs modifient les automatisations.")
    if row and token.role != "business_owner" and row.get("store_ids") != _own_stores(token):
        raise HTTPException(status_code=403, detail="Cette automatisation concerne d'autres établissements.")


@router.post("/api/owner/automations")
def create_automation(body: AutomationIn, token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True))):
    tid = token_data.tenant_id
    _guard(token_data)
    migrate(tid)
    data = clean(body, tid)
    doc = new_doc(tid, data["scenario"])
    doc.update(data)
    doc["store_ids"] = _own_stores(token_data)
    doc["order"] = _db.automations.count_documents({"tenant_id": tid})
    doc["created_by"] = token_data.email
    _db.automations.insert_one(dict(doc))
    return _row_view(doc, tid)


@router.put("/api/owner/automations/{aid}")
def update_automation(aid: str, body: AutomationIn,
                      token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True))):
    tid = token_data.tenant_id
    row = _own(tid, aid)
    _guard(token_data, row)
    if body.scenario != row["scenario"]:
        raise HTTPException(status_code=400, detail="Le scénario d'une automatisation ne change pas : créez-en une nouvelle.")
    data = clean(body, tid)
    data["updated_at"] = _now()
    _db.automations.update_one({"id": aid}, {"$set": data})
    if data["status"] != "active":
        _db.automation_queue.delete_many({"automation_id": aid})
    return _row_view(_own(tid, aid), tid)


class StatusIn(BaseModel):
    status: str


@router.post("/api/owner/automations/{aid}/status")
def set_status(aid: str, body: StatusIn, token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True))):
    tid = token_data.tenant_id
    row = _own(tid, aid)
    _guard(token_data, row)
    if body.status not in ("active", "paused"):
        raise HTTPException(status_code=400, detail="Statut inconnu.")
    if body.status == "active":
        # a draft is checked as a whole before it may run
        clean(AutomationIn(**{**row, "status": "active"}), tid)
    _db.automations.update_one({"id": aid}, {"$set": {"status": body.status, "updated_at": _now()}})
    if body.status != "active":
        _db.automation_queue.delete_many({"automation_id": aid})
    return _row_view(_own(tid, aid), tid)


@router.post("/api/owner/automations/{aid}/duplicate")
def duplicate(aid: str, token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True))):
    tid = token_data.tenant_id
    row = _own(tid, aid)
    _guard(token_data, row)
    copy = {**row, "id": str(uuid.uuid4()), "name": (f"{row.get('name')} (copie)")[:NAME_MAX], "status": "draft",
            "created_at": _now(), "updated_at": _now(), "last_run_at": None, "created_by": token_data.email,
            "order": _db.automations.count_documents({"tenant_id": tid})}
    _db.automations.insert_one(dict(copy))
    return _row_view(copy, tid)


@router.delete("/api/owner/automations/{aid}")
def delete_automation(aid: str, token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True))):
    tid = token_data.tenant_id
    row = _own(tid, aid)
    _guard(token_data, row)
    _db.automations.delete_one({"id": aid})
    _db.automation_queue.delete_many({"automation_id": aid})
    return {"deleted": aid}


class IdeaIn(BaseModel):
    objective: str


# what the owner's words point to — the editor opens on that scenario
_HINTS = [
    ("birthday", ("anniversaire", "birthday")),
    ("google_review", ("avis", "google", "note", "review")),
    ("referral", ("parrain", "filleul", "ami", "recommand")),
    ("welcome", ("bienvenue", "inscri", "nouveau client", "nouveaux clients")),
    ("tier_up", ("palier", "niveau", "vip", "statut")),
    ("near_reward", ("récompense", "recompense", "tampon", "presque")),
    ("geo", ("proximité", "proximite", "passe", "à côté", "autour", "quartier")),
    ("inactive", ("inactif", "revenir", "revien", "absent", "plus vu", "relanc", "perdu")),
]


def suggest(objective: str) -> str:
    low = (objective or "").lower()
    for key, words in _HINTS:
        if any(w in low for w in words):
            return key
    return "custom"


@router.post("/api/owner/automations/ai-draft")
def ai_draft(body: IdeaIn, token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True))):
    """« Besoin d'inspiration ? » — the owner says what they want, FidClic IA
    writes the title and the message, and the editor opens on the scenario
    those words point to (« Personnalisée » when none). Nothing is saved or
    sent here; an unavailable assistant says so plainly."""
    from features import campaigns_page as CP
    objective = CP._clean(body.objective, 200)
    if not objective:
        raise HTTPException(status_code=400, detail="Décrivez ce que vous voulez en une phrase.")
    tenant = _db.tenants.find_one({"id": token_data.tenant_id}) or {}
    user = (f"Commerce : {tenant.get('name') or 'un commerce'} ({tenant.get('sector') or 'commerce'}). "
            f"Message automatique de fidélité. Objectif : {objective}. "
            "Tu peux utiliser {prénom} pour le prénom du client et {nom_commerce} pour le commerce.")
    try:
        from services import llm
        if llm._force_complete is None and not llm.is_configured():
            raise HTTPException(status_code=503, detail="FidClic IA n'est pas configurée sur cette installation.")
        raw = llm.complete(CP._SYSTEM, user, max_tokens=180, temperature=0.7)
    except HTTPException:
        raise
    except Exception as exc:
        print(f"automations: ai-draft failed ({exc})")
        raise HTTPException(status_code=503, detail="FidClic IA ne répond pas pour le moment. Réessayez dans un instant.")
    title, message = CP._parse(raw)
    if not title or not message:
        raise HTTPException(status_code=502, detail="FidClic IA n'a pas trouvé de message. Reformulez votre objectif.")
    return {"title": title[:TITLE_MAX], "body": message[:BODY_MAX], "scenario": suggest(objective),
            "scenario_label": SCENARIOS[suggest(objective)]["label"]}


class PreviewIn(BaseModel):
    scenario: str
    targeting: TargetingIn = TargetingIn()


@router.post("/api/owner/automations/preview")
def preview(body: PreviewIn, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    """Step 4's count, and a real client to fill the preview's variables."""
    tid = token_data.tenant_id
    if body.scenario not in SCENARIOS:
        raise HTTPException(status_code=400, detail="Scénario inconnu.")
    row = {"id": "preview", "scenario": body.scenario, "store_ids": _own_stores(token_data),
           "targeting": body.targeting.model_dump()}
    at = _now()
    cache: Dict[str, Any] = {}
    people = [c for c in _db.customers.find({"tenant_id": tid}, {"_id": 0}) if matches(tid, row, c, at, cache)]
    sample = None
    if people:
        c = people[0]
        tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "reward_description": 1}) or {}
        sample = {"first_name": (c.get("name") or "").split(" ")[0] or "Sarah", "points": int(c.get("points") or 0),
                  "visits": int(c.get("visits") or 0), "next_reward": tpl.get("reward_description") or "votre récompense"}
    return {"count": len(people), "sample": sample}
