"""
Automatisations — redesigned from the user's mockups (2026-10-11).

Eight scenarios, no others (the user removed Offre spéciale, Événement
spécial, Relance panier, Heures creuses and Nouveaux produits, data included):

    birthday       Anniversaire               time   the day of the birthday (± X days)
    tier_up        Atteinte d'un palier       event  the scan that moves the client up
    welcome        Bienvenue                  event  the card added to Apple / Google Wallet
    near_reward    Récompense bientôt dispo.  event  the scan that leaves X points / tampons to the next reward
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
from features import store_cards as _SC  # one card per establishment (multi-store)

router = APIRouter(tags=["automations"])
_db = None

READERS = ["business_owner", "administrateur", "manager"]
EDITORS = ["business_owner", "administrateur"]
TITLE_MAX = 80                 # the palier mockups (user, 2026-10-11): 80 / 350
BODY_MAX = 350
BUTTON_MAX = 30
NAME_MAX = 100                 # the Avis Google mockups (user, 2026-10-11): name 100, description 500
DESC_MAX = 500
READY_IMAGES = ("/automations/avis-google.png",)   # the Avis Google default (public/)


def init(db):
    global _db
    _db = db
    from features import custom_rules as CR
    CR.init(db)
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


def _loc(at: datetime, sched: Optional[Dict[str, Any]]) -> datetime:
    """Wall clock in the automation's « Fuseau horaire » (Paris unless chosen)."""
    if not (sched or {}).get("tz"):
        return _paris(at)
    from features import custom_rules as CR
    return CR.local(at, sched)


def _from_loc(d: date, hh: int, mm: int, sched: Optional[Dict[str, Any]]) -> datetime:
    if not (sched or {}).get("tz"):
        return _from_paris(d, hh, mm)
    from features import custom_rules as CR
    return CR.from_local(d, hh, mm, sched)


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
        # Bienvenue (mockups 2026-10-11): sent when the card lands in Apple /
        # Google Wallet — never at the web signup (user: « sirf Wallet add pe »)
        "label": "Bienvenue", "sub": "Accueillez chaque client dès qu'il ajoute sa carte dans Wallet.",
        "icon": "hand", "tone": "blue", "kind": "event", "trigger_label": "Après l'ajout de la carte dans Wallet",
        "push_kind": "welcome", "google": "automation",
        "title": "Bienvenue chez {nom_commerce} 🎉",
        "body": "Merci {prénom} ! Votre carte de fidélité est prête : à chaque visite, vous vous rapprochez de votre récompense.",
        "button": "Voir ma carte",
    },
    "near_reward": {
        # Récompense bientôt disponible (mockups 2026-10-11): X points (or
        # tampons) before the nearest reward — the card's, or the next palier's
        "label": "Récompense bientôt disponible", "sub": "Prévenez vos clients quand leur prochaine récompense est presque atteinte.",
        "icon": "gift", "tone": "violet", "kind": "event", "trigger_label": "Seuil presque atteint",
        "push_kind": "near_reward", "google": "near_reward",
        "title": "Plus que quelques points ! 🎁",
        "body": "Plus que {points_restants} avant votre prochaine récompense, {prénom} : {récompense} !",
        "button": "Voir ma récompense",
    },
    # Parrainage (mockups 2026-10-11): ONE automation, the parrain's message
    # and the filleul's (FILLEUL_DEFAULT), sent when the points are credited
    "referral": {
        "label": "Parrainage", "sub": "Remerciez parrains et filleuls quand la récompense est gagnée.",
        "icon": "users", "tone": "green", "kind": "event", "trigger_label": "Un client parraine un ami",
        "push_kind": "parrainage", "google": "parrainage",
        "title": "Merci pour votre parrainage ! 🎁",
        "body": "Votre ami a rejoint notre établissement grâce à vous. Merci ! Profitez de votre récompense de parrainage. 🎉",
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
        "title": "Votre avis compte ! ⭐",
        "body": "Merci pour votre visite !\nSi vous avez apprécié votre expérience chez nous, laissez-nous un avis sur Google. Cela nous aide énormément ! 🙏",
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
FILLEUL_DEFAULT = {"title": "Bienvenue et merci ! 🎉",
                   "body": "Votre première visite est validée ! Vos points de parrainage ont été ajoutés à votre carte. 🎁"}
SIDES = ("parrain", "filleul")
ORDER = ["custom", "birthday", "tier_up", "welcome", "near_reward", "referral", "geo", "google_review", "inactive"]
CUSTOM_TYPES = ("visits", "after_signup", "after_visit", "date")
DATE_MODES = ("once", "weekly", "monthly", "yearly")


def is_timed(scenario: str, trigger: Optional[Dict[str, Any]] = None) -> bool:
    """Sent at an hour (daily run / tick) rather than on an event."""
    kind = SCENARIOS[scenario]["kind"]
    if scenario == "custom" and (trigger or {}).get("type") in CR_V2:
        from features import custom_rules as CR
        return CR.is_timed(trigger or {})
    return kind == "time" or (scenario in ("custom", "google_review") and (trigger or {}).get("type") == "date")


# « Nouvelle automatisation » (mockups 2026-10-11): features/custom_rules
CR_V2 = ("on_date", "recurring", "action", "loyalty", "behavior", "geo", "other")
# Removed by the user (2026-10-11) — with their data.
REMOVED_BUILTINS = {"special_offer", "cart_recovery", "off_peak", "new_products", "special_event"}

VARIABLES = {
    "common": ["prénom", "nom", "nom_commerce", "points", "visites", "prochaine_récompense", "points_manquants"],
    "birthday": ["fin_offre"], "tier_up": ["palier", "récompense"], "welcome": ["offre", "lien"], "near_reward": ["points_restants", "tampons_restants", "tampons", "récompense", "visites_restantes", "visite_s"],
    "referral": ["filleul", "parrain", "points_gagnés", "visite_ami", "récompense", "lien", "amis_parraines"], "geo": ["établissement"],
    "google_review": ["établissement", "lien_avis"], "inactive": ["jours_absence", "offre", "lien"], "custom": ["prénom", "nom", "points", "récompense", "nom_commerce", "date", "montant", "nombre_visites"],
}
VARIABLES["geo"] = ["établissement", "distance", "offre"]
LINK_TYPES = ("card", "rewards", "offer", "google_review", "url")
DAY_MODES = ("all", "specific", "weekdays")
TARGET_MODES = ("all", "segment", "wallet", "filtered")
# « Type de passants » (géolocalisation mockups, 2026-10-11): lifetime visits
PASSANTS = {"new": (0, 0), "regular": (1, 10), "old": (11, None)}
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
GR_FREQS = ("every_scan", "days", "once", "smart")
# Avis Google (updated mockups, 2026-10-11): after the visit (délai), at the
# N-th visit (« Client fidèle »), or on a date
GR_TYPES = ("after_visit", "loyal", "date")
# « Type de client » = the card's statut (user, 2026-10-11 — replaces « Fréquence de visite »)
CLIENT_TYPES = {"new": ("bronze",), "regular": ("silver",), "loyal": ("gold", "vip")}
# Client inactif (mockups, 2026-10-11): the five « Condition d'inactivité » tiles,
# and the filters of its Ciblage — usable by every automation.
INACTIVE_DAYS = (30, 60, 90, 120, 180)
# « Fréquence d'achat passée »: visits per month while the client came, [lo, hi)
PAST_FREQS = {"<1": (0, 1), "1-2": (1, 2.5), "3-4": (2.5, 4.5), ">4": (4.5, None)}
# « Programme de fidélité »: the card's statut
TIERS = ("bronze", "silver", "gold", "vip")
# « Dernière offre reçue » (an offer campaign): never / under 30 days / over 30 days
LAST_OFFER = ("none", "<30", ">30")
# « Origine du client »: services/sources keys, « none » = Non renseigné
from services.sources import SOURCES as _SOURCES, UNKNOWN as _UNKNOWN, normalize as _source_key
ORIGINS = tuple(_SOURCES) + (_UNKNOWN,)
# « Répartition de l'audience » — the channel groups of the mockup
CHANNEL_GROUPS = {"qr_store": "store", "referral": "other", "import": "other", "autre": "other", _UNKNOWN: "other"}
RECENT_CONTACT_DAYS = 30        # « Exclure les clients déjà contactés récemment »
DAILY_LIMIT_MAX = 100000
IMPACT_WINDOW_DAYS = 15         # a client « réactivé » = a visit within 15 days (fidclic_impact)
IMPACT_MIN_SENDS = 20           # the shop's own history counts from 20 measured sends
IMPACT_MIN_SHOPS = 3            # the sector's pool, anonymous, from 3 shops (campaign_learning)


# ---------------------------------------------------------------------------
# defaults and the old settings carried over
# ---------------------------------------------------------------------------
def _default_trigger(scenario: str) -> Dict[str, Any]:
    return {
        "birthday": {"offset_days": 0, "offer_days": BIRTHDAY_OFFER_DAYS},
        # Atteinte d'un palier (mockups 2026-10-11): an owner threshold on
        # points (earned since the start) / visits / € spent, or the card's
        # statut; every multiple, the first time only, or with a minimum
        # gap; or a list of paliers, each with its own message.
        "tier_up": {"condition": "points", "threshold": 200, "repeat": "each", "min_days": 7,
                    "custom_tiers": False, "tiers": []},
        "welcome": {},
        # a row with « threshold » (X points / tampons, mockups 2026-10-11) is the
        # new rule; one with only « visits_left » keeps the old one until re-saved
        "near_reward": {"visits_left": 1},
        "referral": {"sides": ["parrain", "filleul"]},
        # Géolocalisation (mockups 2026-10-11): the gap per client, the weather
        # asked (none = any), the establishments watched (none = all)
        "geo": {"cooldown_days": 7, "weather": [], "stores": []},
        "google_review": {"type": "after_visit", "frequency": "once", "every_days": 30, "stop_after_click": True,
                          "visits": 5, "date": None},
        "inactive": {"days": 30, "repeat": "once", "every_days": 30},
        "custom": {"type": "after_visit", "visits": 5, "visits_repeat": "once", "cooldown_days": 0,
                   "date_mode": "once", "date": None, "weekday": 0, "monthday": 1},
    }[scenario] | {"delay_value": 0, "delay_unit": "hours"}


def _default_schedule(scenario: str) -> Dict[str, Any]:
    timed = is_timed(scenario, _default_trigger(scenario))
    return {"days": "all", "weekdays": [0, 1, 2, 3, 4, 5, 6],
            "hour": "10:00" if timed else None, "smart": False,
            "window_from": "09:00", "window_to": "21:00", "window": not timed,
            "slots": [], "holidays": True, "valid_from": None, "valid_to": None}


def trade_meta(tenant: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """SCENARIOS with the shop's trade words for « Client inactif » and
    « Géolocalisation » (services/playbooks.py) — a copy; the others as they are."""
    from services import playbooks as PB
    texts = PB.automation_texts(PB.of(tenant or {}))
    return {k: {**v, **texts.get(k, {})} for k, v in SCENARIOS.items()}


def new_doc(tid: str, scenario: str, *, meta_of: Optional[Dict[str, Dict[str, Any]]] = None,
            **over: Any) -> Dict[str, Any]:
    meta = (meta_of or SCENARIOS)[scenario]
    now = _now()
    doc = {
        "id": str(uuid.uuid4()), "tenant_id": tid, "scenario": scenario,
        "name": meta["label"], "status": "draft",
        "trigger": _default_trigger(scenario),
        "message": {"title": meta["title"], "body": meta["body"], "image_url": None,
                    "button": {"enabled": False, "label": meta["button"], "link_type": "card",
                               "offer_id": None, "url": None}},
        "targeting": {"mode": "filtered" if scenario == "geo" else "all", "segment": None, "passants": "all",
                      "filters": {"gender": [], "age": [], "frequency": [], "spent": [], "last_visit": [],
                                  "stores": [], "radius_km": None}},
        "schedule": _default_schedule(scenario),
        "created_at": now, "updated_at": now, "last_run_at": None, "store_ids": None,
    }
    if scenario == "referral":
        doc["message_filleul"] = {"title": FILLEUL_DEFAULT["title"], "body": FILLEUL_DEFAULT["body"], "image_url": None,
                                  "button": {"enabled": False, "label": meta["button"], "link_type": "card",
                                             "offer_id": None, "url": None}}
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
    trade = trade_meta(_db.tenants.find_one({"id": tid}, {"_id": 0, "sector": 1, "activity_key": 1}))

    def made(scenario: str, **over: Any) -> Dict[str, Any]:       # in the shop's trade words
        return new_doc(tid, scenario, meta_of=trade, **over)
    old = {r.get("builtin") or r.get("id"): r for r in _db.push_scenarios.find({"tenant_id": tid}, {"_id": 0})}

    def carried(key: str, scenario: str, **over: Any) -> Dict[str, Any]:
        r = old.get(key) or {}
        msg = {}
        if r.get("title"):
            msg["title"] = _french(r["title"])[:TITLE_MAX]
        if r.get("body"):
            msg["body"] = _french(r["body"])[:BODY_MAX]
        return made(scenario, status="active" if r.get("enabled") else "paused",
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
        docs.append(made("welcome", status="active" if w.get("enabled") else "paused",
                            message={"body": body}))
    except Exception:
        docs.append(made("welcome", status="paused"))
    cfg = _db.auto_message_config.find_one({"tenant_id": tid}) or {}
    gr, nr = cfg.get("google_review") or {}, cfg.get("near_reward") or {}
    docs.append(made("near_reward", status="active" if nr.get("enabled", True) else "paused",
                        trigger={"visits_left": int(nr.get("visits_left") or 1)},
                        message={k: _french(nr[k])[:TITLE_MAX if k == "title" else BODY_MAX]
                                 for k in ("title", "body") if nr.get(k)}))
    docs.append(made("google_review", status="active" if gr.get("enabled") else "paused",
                        trigger={"frequency": gr.get("frequency") if gr.get("frequency") in GR_FREQS else "days",
                                 "every_days": int(gr.get("days") or 30),
                                 "stop_after_click": bool(gr.get("stop_after_click", True))},
                        message={**{k: _french(gr[k])[:TITLE_MAX if k == "title" else BODY_MAX]
                                    for k in ("title", "body") if gr.get(k)},
                                 "button": {"enabled": True, "label": "Laisser un avis",
                                            "link_type": "google_review", "offer_id": None, "url": None}}))
    ref_on = bool((_db.referral_config.find_one({"tenant_id": tid}) or {}).get("enabled"))
    # one automation, both messages, the mockup's words (user, 2026-10-11)
    docs.append(made("referral", name="Parrainage", status="active" if ref_on else "paused"))
    tenant = _db.tenants.find_one({"id": tid}, {"_id": 0, "geo_enabled": 1, "geo_cooldown_days": 1}) or {}
    docs.append(made("geo", status="active" if tenant.get("geo_enabled") else "paused",
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
    """The MEMBERS of these establishments (their home store): each store's
    automations write to its own clients only (multi-store PR5)."""
    if not stores:
        return None
    from features import store_scope as S
    return S.home_customer_ids(S.Scope(tenant_id=tid, ids=list(stores)))


def _open_store_ids(tid: str) -> List[str]:
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "branches": 1}) or {}
    return [b["id"] for b in t.get("branches") or [] if b.get("id") and b.get("status") != "closed"]


def split_per_store(tid: str) -> int:
    """Automatisations par établissement (user, 2026-10-12): with several
    establishments, every automation belongs to ONE. One made for the whole
    shop (or for several) becomes one per establishment — the same words, the
    same switch — so every store's clients keep receiving it; the first store
    keeps the row (and its history)."""
    stores = _open_store_ids(tid)
    if len(stores) < 2:
        return 0
    if not _db.automations.find_one({"tenant_id": tid, "$or": [{"store_ids": None}, {"store_ids": []},
                                                               {"store_ids.1": {"$exists": True}}]}, {"_id": 1}):
        return 0                                   # already one establishment each (the usual case)
    made = 0
    for row in list(_db.automations.find({"tenant_id": tid}, {"_id": 0})):
        ids = [x for x in (row.get("store_ids") or []) if x in stores]
        if row.get("store_ids") and len(ids) == 1 and len(row["store_ids"]) == 1:
            continue
        targets = ids or stores
        _db.automations.update_one({"id": row["id"]}, {"$set": {"store_ids": [targets[0]]}})
        for sid in targets[1:]:
            copy = {**row, "id": str(uuid.uuid4()), "store_ids": [sid], "split_from": row["id"],
                    "created_at": row.get("created_at") or _now(), "last_run_at": None}
            _db.automations.insert_one(copy)
            made += 1
    return made


def _menu_store(tid: str, token: TokenData, request: Any = None) -> Optional[str]:
    """The establishment chosen in the menu (several stores), else None."""
    if len(_open_store_ids(tid)) < 2:
        return None
    from features import store_scope as S
    return S.resolve(token, request).single


def _segment_ids(tid: str, key: Optional[str], at: datetime) -> Optional[set]:
    if not key:
        return None
    try:
        from features import campaigns_page as CP
        return {c["id"] for c in CP._segment_people(tid, key, at, None)}
    except Exception:
        return set()


def visits_per_month(cust: Dict[str, Any], at: Optional[datetime] = None) -> Optional[float]:
    """« Fréquence d'achat passée »: visits per month between the signup and
    the last visit (a month at least) — None for a client who never came."""
    n = int(cust.get("visits") or 0)
    if n <= 0:
        return None
    first = _aware(cust.get("created_at"))
    last = _aware(cust.get("last_visit_date")) or at or _now()
    span = (last - first).days if first and last and last > first else 0
    return n / max(1.0, span / 30.0)


def origin_of(cust: Dict[str, Any]) -> str:
    """« Origine du client »: the signup channel, as services/sources reads it."""
    return _source_key(cust.get("acquisition_source")) or _UNKNOWN


def _offer_history(tid: str) -> Tuple[Dict[str, datetime], set]:
    """Who received an offer (Campagnes › Offre / Push Wallet offers): the last
    time each client got one, and who holds one still running."""
    last: Dict[str, datetime] = {}
    live: set = set()
    try:
        from features import campaign_kinds as K
        at = _now()
        for c in _db.campaigns.find({"tenant_id": tid, "status": "sent", "kind": {"$in": list(K.OFFER_KINDS)}},
                                    {"_id": 0}):
            sent = _aware(c.get("sent_at"))
            on = K.is_live(c, at)
            for cid in c.get("recipient_ids") or []:
                if sent and (cid not in last or sent > last[cid]):
                    last[cid] = sent
                if on:
                    live.add(cid)
    except Exception:
        pass
    try:
        for m in _db.push_wallet_log.find({"tenant_id": tid}, {"_id": 0, "customer_id": 1, "sent_at": 1}):
            t = _aware(m.get("sent_at"))
            cid = m.get("customer_id")
            if cid and t and (cid not in last or t > last[cid]):
                last[cid] = t
    except Exception:
        pass
    return last, live


def _recent_ids(tid: str, at: datetime) -> set:
    """« Déjà contactés récemment »: a campaign, an offer or an automation in
    the last RECENT_CONTACT_DAYS days (features/resend_guard draws the line)."""
    try:
        from features import resend_guard as RG
        ids = [c["id"] for c in _db.customers.find({"tenant_id": tid}, {"_id": 0, "id": 1})]
        return set(RG.recently_contacted(tid, ids, at, days=RECENT_CONTACT_DAYS))
    except Exception:
        return set()


def excluded(tid: str, tg: Dict[str, Any], cust: Dict[str, Any], at: datetime, cache: Dict[str, Any]) -> bool:
    """The « Exclusions » of the Ciblage — on top of the base and the filters."""
    ex = tg.get("exclusions") or {}
    if ex.get("recent_contact"):
        if "recent" not in cache:
            cache["recent"] = _recent_ids(tid, at)
        if cust["id"] in cache["recent"]:
            return True
    if ex.get("active_offer"):
        if "offers" not in cache:
            cache["offers"] = _offer_history(tid)
        if cust["id"] in cache["offers"][1]:
            return True
    return False


def matches(tid: str, row: Dict[str, Any], cust: Dict[str, Any], at: Optional[datetime] = None,
            cache: Optional[Dict[str, Any]] = None) -> bool:
    """Does this client fall inside the automation's « Ciblage »?"""
    at = at or _now()
    cache = cache if cache is not None else {}
    tg = row.get("targeting") or {}
    if cust.get("deleted_at"):
        return False
    # paused by the business: no automation, no géolocalisation (services/client_status)
    if "paused" not in cache:
        from services import client_status as _CS
        cache["paused"] = _CS.paused_ids(_db, tid)
    if cust.get("paused_at") or cust.get("id") in cache["paused"]:
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
    # « Type de passants » (géolocalisation): never / a few times / many times
    span = PASSANTS.get(tg.get("passants") or "all")
    if span:
        n = int(cust.get("visits") or 0)
        if n < span[0] or (span[1] is not None and n > span[1]):
            return False
    if excluded(tid, tg, cust, at, cache):
        return False
    # « Tous mes clients » = everyone: no filter applies (as in Campagnes, 2026-10-10);
    # « filtered » (géolocalisation) = everyone, through the filters
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
    # « Fréquence de visite » was removed (user, 2026-10-11): an old value no longer filters
    ct = as_list(f.get("client_type"), CLIENT_TYPES)
    if ct and (cust.get("tier") or "bronze").lower() not in {t for k in ct for t in CLIENT_TYPES[k]}:
        return False
    n_visits = int(cust.get("visits") or 0)
    if f.get("visits_min") not in (None, "") and n_visits < int(f["visits_min"]):
        return False
    if f.get("visits_max") not in (None, "") and n_visits > int(f["visits_max"]):
        return False
    if f.get("age_min") not in (None, "") or f.get("age_max") not in (None, ""):
        from services import customer_fields as CF
        age = CF.age_of(cust.get("birth_date"))
        if age is None:
            return False
        if f.get("age_min") not in (None, "") and age < int(f["age_min"]):
            return False
        if f.get("age_max") not in (None, "") and age > int(f["age_max"]):
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
    # « Statut client » (Récompense bientôt disponible): the shop's Règles clients
    acts = [str(x) for x in (f.get("activity") or []) if x]
    if acts:
        if "rules" not in cache:
            from features import customer_rules as R
            cache["rules"] = R.load(tid)
        from features import clients_page as CPg
        if CPg.status_of(cust, at, cache["rules"]) not in acts:
            return False
    since = f.get("signed_since")
    if since:
        joined = _aware(cust.get("created_at"))
        try:
            if not joined or _paris(joined).date() < date.fromisoformat(str(since)[:10]):
                return False
        except ValueError:
            pass
    # Nouvelle automatisation › Ciblage (2026-10-11)
    pts = int(cust.get("points") or 0)
    if f.get("points_min") not in (None, "") and pts < int(f["points_min"]):
        return False
    if f.get("points_max") not in (None, "") and pts > int(f["points_max"]):
        return False
    paid = float(cust.get("total_amount_paid") or 0)
    if f.get("spent_min") not in (None, "") and paid < float(f["spent_min"]):
        return False
    if f.get("spent_max") not in (None, "") and paid > float(f["spent_max"]):
        return False
    if f.get("last_visit_days") not in (None, ""):
        last = _aware(cust.get("last_visit_date"))
        idle = (at - last).days if last else None
        n = int(f["last_visit_days"])
        if f.get("last_visit_op") == "less":
            if idle is None or idle > n:
                return False
        elif idle is not None and idle < n:
            return False                          # « il y a plus de N jours » (never came = counts)
    # Client inactif's filters (mockups, 2026-10-11) — every automation reads them
    pf = as_list(f.get("past_freq"), PAST_FREQS)
    if pf and not within(visits_per_month(cust, at), [PAST_FREQS[x] for x in pf], half_open=True):
        return False
    tiers = as_list(f.get("tiers"), TIERS)
    if tiers and (cust.get("tier") or "bronze").lower() not in tiers:
        return False
    orig = as_list(f.get("origin"), ORIGINS)
    if orig and origin_of(cust) not in orig:
        return False
    lo = as_list(f.get("last_offer"), LAST_OFFER)
    if lo:
        if "offers" not in cache:
            cache["offers"] = _offer_history(tid)
        got = cache["offers"][0].get(cust["id"])
        bucket = "none" if not got else ("<30" if (at - got).days < 30 else ">30")
        if bucket not in lo:
            return False
    return True


# ---------------------------------------------------------------------------
# when
# ---------------------------------------------------------------------------
def _hm(s: Optional[str], default: Tuple[int, int]) -> Tuple[int, int]:
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", (s or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else default


def _day_ok(sched: Dict[str, Any], d: date) -> bool:
    if sched.get("holidays") is False:
        from features import geo_automation as GA
        if GA.is_holiday(d):
            return False                     # « Jours fériés » switched off
    if not _valid_on(sched, d):
        return False
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


def _valid_on(sched: Dict[str, Any], d: date) -> bool:
    """« Période de validité » / « Période d'activation »: inside the dates."""
    for key, after in (("valid_from", False), ("valid_to", True)):
        raw = sched.get(key)
        if not raw:
            continue
        try:
            edge = date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
        if (d > edge) if after else (d < edge):
            return False
    return True


def slots_of(sched: Dict[str, Any]) -> List[Tuple[Tuple[int, int], Tuple[int, int]]]:
    """The hours a message may leave. No window = the whole day. A slot whose
    end is before its start runs past midnight (« Nuit 21h – 8h »)."""
    if not sched.get("window", True):
        return [((0, 0), (23, 59))]
    raw = [x for x in (sched.get("slots") or []) if isinstance(x, dict)] or \
        [{"from": sched.get("window_from"), "to": sched.get("window_to")}]
    out = []
    for x in raw:
        a, b = _hm(x.get("from"), (0, 0)), _hm(x.get("to"), (23, 59))
        if a != b:
            out.append((a, b))
    return out or [((0, 0), (23, 59))]


def next_window(sched: Dict[str, Any], at: datetime) -> datetime:
    """The first moment at or after `at` inside the days, hours, dates and
    holidays of an event scenario. A window that never opens answers far away."""
    loc = _loc(at, sched)
    best: Optional[datetime] = None
    for i in range(-1, 15):                   # yesterday: a night slot may still run
        d = (loc + timedelta(days=i)).date()
        if not _day_ok(sched, d):
            continue
        for (fh, fm), (th, tm) in slots_of(sched):
            start = _from_loc(d, fh, fm, sched)
            end = _from_loc(d, th, tm, sched) if (th, tm) > (fh, fm) else _from_loc(d + timedelta(days=1), th, tm, sched)
            if (th, tm) == (23, 59):
                end += timedelta(seconds=59)
            if end < at:
                continue
            cand = max(at, start)
            if best is None or cand < best:
                best = cand
    return best or at + timedelta(days=3650)


def in_window(sched: Dict[str, Any], at: datetime) -> bool:
    return next_window(sched, at) <= at + timedelta(seconds=30)


def ended(row: Dict[str, Any], at: Optional[datetime] = None) -> bool:
    """« Terminée »: its period's last day is behind us (Paris)."""
    raw = (row.get("schedule") or {}).get("valid_to")
    if not raw:
        return False
    try:
        return _loc(at or _now(), row.get("schedule")).date() > date.fromisoformat(str(raw)[:10])
    except ValueError:
        return False


def running(row: Dict[str, Any], at: Optional[datetime] = None) -> bool:
    """Active and inside its period (not « Terminée », already started)."""
    if row.get("status") != "active" or ended(row, at):
        return False
    return _valid_on(row.get("schedule") or {}, _loc(at or _now(), row.get("schedule")).date())


def status_of(row: Dict[str, Any], at: Optional[datetime] = None) -> str:
    return "ended" if row.get("status") == "active" and ended(row, at) else row.get("status") or "draft"


# ---------------------------------------------------------------------------
# what
# ---------------------------------------------------------------------------
def _render(text: str, cust: Dict[str, Any], tenant: Dict[str, Any], extra: Dict[str, Any]) -> str:
    # one pass with the shop-wide placeholders: a sponsor named « {points} »
    # stays text (audit P07, 2026-10-29)
    try:
        import server as core
        return core.render_template(text or "", {**cust, "tenant_id": tenant.get("id")}, tenant, extra=extra)
    except Exception:
        out = text or ""
        for k, v in (extra or {}).items():
            out = out.replace("{" + k + "}", str(v))
        return out


def _live_offer(tid: str) -> Optional[str]:
    """{offre}: the shop's latest offer still running (Campagnes)."""
    if not tid:
        return None
    from services import send_batch as _SB

    def find() -> Optional[str]:
        try:
            from features import campaign_kinds as K
            for c in _db.campaigns.find({"tenant_id": tid, "status": "sent"}, {"_id": 0}).sort("sent_at", -1).limit(20):
                if c.get("kind") in K.OFFER_KINDS and K.is_live(c, _now()):
                    return (c.get("name") or "").strip() or None
        except Exception:
            pass
        return None
    return _SB.memo(("live_offer", tid), find)       # once per send, not per message


def _extra(scenario: str, cust: Dict[str, Any], ctx: Dict[str, Any], tpl: Dict[str, Any]) -> Dict[str, Any]:
    reward = tpl.get("reward_description") or "votre récompense"
    out: Dict[str, Any] = {"prochaine_récompense": reward, "prochaine_recompense": reward}
    out["nom"] = cust.get("name") or ""
    if scenario == "birthday" and ctx.get("offer_until"):
        out["fin_offre"] = fr_day(ctx["offer_until"])
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
        # a row saved before the mockups (« X visites ») speaks the new words too:
        # its seuil is in visits, and the reward is the card's
        word = "visite" if left == 1 else "visites"
        out["points_restants"] = out["tampons_restants"] = f"{left} {word}"
        out["récompense"] = out["recompense"] = reward
        if ctx.get("remaining") is not None:
            unit = reward_unit(tpl)
            n = int(ctx["remaining"])
            word = {"points": "point" if n == 1 else "points", "tampons": "tampon" if n == 1 else "tampons"}.get(unit, unit)
            out["points_restants"] = out["tampons_restants"] = f"{n} {word}"
            out["récompense"] = out["recompense"] = ctx.get("reward") or reward
        per_stamp = max(1, int(tpl.get("visits_per_stamp") or 1))
        out["tampons"] = max(0, int(cust.get("visits") or 0) - int(cust.get("visits_at_last_redemption") or 0)) // per_stamp
    if scenario == "custom":
        out["récompense"] = out["recompense"] = reward
        today = _paris(_now()).date()
        months = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
                  "novembre", "décembre"]
        out["date"] = f"{today.day} {months[today.month - 1]}"
        out["montant"] = f"{float(cust.get('total_amount_paid') or 0):.2f} €".replace(".", ",")
        out["nombre_visites"] = int(cust.get("visits") or 0)
        if ctx.get("offre"):
            out["offre"] = ctx["offre"]
        if ctx.get("palier"):
            out["palier"] = ctx["palier"]
    if scenario == "referral":
        out.update({"visite_ami": "est revenu" if ctx.get("kind") == "next" else "est venu",
                    "filleul": ctx.get("filleul") or "votre ami", "parrain": ctx.get("parrain") or "votre parrain",
                    "points_gagnés": ctx.get("points") or 0, "points_gagnes": ctx.get("points") or 0})
        # mockup chips « Récompense », « Lien », « Nombre d'amis parrainés » (validated ones)
        # the reward in words — points, tampons or the shop's own offer (2026-10-13)
        pts = int(ctx.get("points") or 0)
        got = ctx.get("reward") or (f"{pts} point{'s' if pts > 1 else ''}" if pts else "")
        out["récompense"] = out["recompense"] = got or "votre récompense"
        try:
            from services import card_owner as CO
            out["lien"] = CO.owner_url(public_base(), cust.get("barcode_id") or "")
        except Exception:
            out["lien"] = ""
        out["amis_parraines"] = _db.referral_redemptions.count_documents(
            {"referrer_customer_id": cust.get("id"), "referrer_pending": False})
    if scenario == "geo":
        out["établissement"] = ctx.get("store") or ""
        out["etablissement"] = ctx.get("store") or ""
        # {distance}: known when the card itself asked; on the lock screen « deux pas »
        # (written « à {distance} » it reads « à 80 m » / « à deux pas »)
        d = ctx.get("distance_m")
        out["distance"] = f"{int(round(float(d) / 10.0) * 10)} m" if d is not None else "deux pas"
        out["offre"] = _live_offer(cust.get("tenant_id") or ctx.get("tenant_id") or "") or "notre offre du moment"
    if scenario == "google_review":
        b = ctx.get("branch_id")
        tid = cust.get("tenant_id") or ctx.get("tenant_id") or ""
        branch = next((x for x in _branches(tid) if x["id"] == b), None) if tid else None
        tenant_name = (_db.tenants.find_one({"id": tid}, {"_id": 0, "name": 1}) or {}).get("name") or ""
        out["établissement"] = out["etablissement"] = (branch or {}).get("name") or tenant_name
        out["lien_avis"] = f"{public_base()}/api/avis/{cust.get('barcode_id') or ''}" + (f"?b={b}" if b else "")
    if scenario == "inactive":
        last = _aware(cust.get("last_visit_date")) or _aware(cust.get("created_at"))
        out["jours_absence"] = (_now() - last).days if last else ""
    if scenario in ("inactive", "welcome"):
        # mockup chips « Offre » and « Lien »: the offer running now, the client's card
        out["offre"] = _live_offer(cust.get("tenant_id") or ctx.get("tenant_id") or "") or "notre offre du moment"
        try:
            from services import card_owner as CO
            out["lien"] = CO.owner_url(public_base(), cust.get("barcode_id") or "")
        except Exception:
            out["lien"] = ""
    return out


def _target_url(tid: str, row: Dict[str, Any], cust: Dict[str, Any],
                ctx: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Where the action button goes — any link the owner put."""
    msg = row.get("message") or {}
    if row.get("scenario") == "referral" and (ctx or {}).get("side") == "filleul" and row.get("message_filleul"):
        msg = row["message_filleul"]                  # the filleul's own button
    if row.get("scenario") == "custom" and (ctx or {}).get("reminder") and row.get("message_reminder"):
        msg = row["message_reminder"]
    btn = (msg.get("button") or {})
    if not btn.get("enabled"):
        return None
    from services import card_owner as CO
    serial = cust.get("barcode_id") or ""
    t = btn.get("link_type")
    if t == "url":
        return safe_url(btn.get("url"))
    if t == "google_review":
        b = (ctx or {}).get("branch_id")
        return f"{public_base()}/api/avis/{serial}" + (f"?b={b}" if b else "")
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


@_SC.customer_store("cust")
def _deliver(tid: str, row: Dict[str, Any], cust: Dict[str, Any], ctx: Dict[str, Any],
             at: datetime) -> Optional[Dict[str, Any]]:
    """One client, one message. Returns what was said, or None."""
    scenario = row["scenario"]
    meta = SCENARIOS[scenario]
    tenant = _db.tenants.find_one({"id": tid}) or {}
    tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0}) or {}
    until = birthday_until(row, cust, at) if scenario == "birthday" else None
    if until:
        ctx = {**ctx, "offer_until": until}
    extra = _extra(scenario, cust, ctx, tpl)
    msg = row.get("message") or {}
    if scenario == "referral" and ctx.get("side") == "filleul" and row.get("message_filleul"):
        msg = row["message_filleul"]                  # one automation, each side its own words
    if scenario == "custom" and ctx.get("reminder") and row.get("message_reminder"):
        msg = row["message_reminder"]                 # Annuelle › « Rappel avant la date »
    # a palier of its own (paliers personnalisés) speaks its own words
    raw_title = ctx.get("tier_title") or msg.get("title") or meta["title"]
    raw_body = ctx.get("tier_body") or msg.get("body") or meta["body"]
    title = _render(raw_title, cust, tenant, extra)[:160]
    body = _render(raw_body, cust, tenant, extra)[:600]
    target = _target_url(tid, row, cust, ctx)
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
    if ctx.get("year"):
        log["year"] = ctx["year"]
    if ctx.get("reminder"):
        log["reminder"] = True
    if ctx.get("level") is not None:
        log["level"] = ctx["level"]
    if until:
        log["offer_until"] = until.isoformat()
    # groupe témoin (user, 2026-10-25): a relance this client is drawn out of
    # is logged — « once per absence » and cool-downs see it handled — but
    # nothing is said, pushed or put on the card
    from features import temoin as T
    if T.holds_automation(tid, row, cust["id"], at):
        _db.automation_log.insert_one({**log, "status": "holdout", "title": None, "body": None,
                                       "target_url": None, "button_label": None})
        return None
    _db.automation_log.insert_one(dict(log))
    _db.push_notifications.insert_one({"tenant_id": tid, "customer_id": cust["id"], "type": meta["push_kind"],
                                       "title": title, "body": body, "sent_at": at, "automatic": True,
                                       "automation_id": row["id"], "log_id": log_id,
                                       # a relance a groupe témoin measures (fidclic_impact: never « attendu »)
                                       "temoin": scenario in T.AUTOMATION_SCENARIOS and T.enabled(tid)})
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
        if until:
            news["until"] = until.isoformat()
        if scenario == "referral" and (ctx or {}).get("reward_kind", "points") == "points":
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
    split_per_store(tid)
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


# Récompense bientôt disponible (mockups, 2026-10-11) -------------------------
def reward_unit(tpl: Dict[str, Any]) -> str:
    """The seuil's unit, from the card's programme: « points » (points per euro
    / per visit), « tampons » (stamps), « € » (cagnotte: paliers only)."""
    from features import loyalty_card as LC
    prog = LC._programme(tpl)
    return "tampons" if prog == "stamps" else ("€" if prog == "cashback" else "points")


@_SC.customer_store("cust")
def reward_targets(tid: str, cust: Dict[str, Any], tpl: Optional[Dict[str, Any]] = None,
                   cycle: Optional[str] = None) -> List[Dict[str, Any]]:
    """The rewards ahead of this client, in the seuil's unit (user's answer:
    « jo pehle aaye »): the card's own reward — redeemable, its cycle restarting
    at each redemption — and the next palier, when the owner wrote a reward
    for it. Each: {kind, key, remaining, reward}. Nothing already reached."""
    from features import loyalty_card as LC
    tpl = tpl if tpl is not None else (_db.card_templates.find_one({"tenant_id": tid}, {"_id": 0}) or {})
    prog = LC._programme(tpl)
    per_stamp = max(1, int(tpl.get("visits_per_stamp") or 1))
    visits = int(cust.get("visits") or 0)
    in_cycle = max(0, visits - int(cust.get("visits_at_last_redemption") or 0))
    cyc = cycle or "first"
    out: List[Dict[str, Any]] = []
    if prog in ("points_euro", "points_visit"):
        goal = int(tpl.get("reward_points") or 100)
        left = goal - int(cust.get("points") or 0)
        if left > 0:
            out.append({"kind": "card", "key": f"card:{cyc}", "remaining": left,
                        "reward": (tpl.get("reward_description") or "").strip() or "votre récompense"})
    elif prog == "stamps":
        goal = max(1, int(tpl.get("reward_threshold_stamps") or 10))
        left = goal - in_cycle // per_stamp
        if left > 0:
            out.append({"kind": "card", "key": f"card:{cyc}", "remaining": left,
                        "reward": (tpl.get("reward_description") or "").strip() or "votre récompense"})
    # the next palier — measured as tier_of measures it (points, or visits on a stamps card)
    value = visits if prog == "stamps" else int(cust.get("points") or 0)
    # the first palier above with a reward written (one without is not a reward)
    for t in LC.tiers_for(tid):
        if t["min"] > value and t.get("reward"):
            gap = t["min"] - value
            left = -(-gap // per_stamp) if prog == "stamps" else gap      # visits → tampons
            out.append({"kind": "tier", "key": f"tier:{t['key']}:{cyc}", "remaining": left,
                        "reward": t["reward"], "tier": t["key"], "tier_label": t["label"]})
            break
    out.sort(key=lambda x: (x["remaining"], 0 if x["kind"] == "card" else 1))
    return out


def nearest_reward(tid: str, cust: Dict[str, Any], tpl: Optional[Dict[str, Any]] = None,
                   cycle: Optional[str] = None) -> Optional[Dict[str, Any]]:
    got = reward_targets(tid, cust, tpl, cycle)
    return got[0] if got else None


def _eligible(tid: str, row: Dict[str, Any], cust: Dict[str, Any], ctx: Dict[str, Any], at: datetime) -> bool:
    """The scenario's own rule, on top of the targeting."""
    sc, tr = row["scenario"], row.get("trigger") or {}
    q = {"tenant_id": tid, "automation_id": row["id"], "customer_id": cust["id"]}
    if sc == "near_reward" and tr.get("threshold") is not None:
        # X points / tampons before the nearest reward, once per reward and cycle
        hit = nearest_reward(tid, cust, None, ctx.get("cycle"))
        if not hit or not (0 < hit["remaining"] <= int(tr["threshold"])):
            return False
        if _db.automation_log.find_one({**q, "cycle": hit["key"]}) or \
                _db.automation_queue.find_one({**q, "ctx.cycle": hit["key"]}):
            return False
        ctx.update({"cycle": hit["key"], "remaining": hit["remaining"], "reward": hit["reward"]})
    elif sc == "near_reward":                     # saved before the mockups: X visits
        if int(ctx.get("visits_left") or -1) != int(tr.get("visits_left") or 1):
            return False
        cyc = ctx.get("cycle")
        if _db.automation_log.find_one({**q, **({"cycle": cyc} if cyc else {})}) or \
                _db.automation_queue.find_one({**q, **({"ctx.cycle": cyc} if cyc else {})}):
            return False
    elif sc == "referral":
        sides = tr.get("sides") if isinstance(tr.get("sides"), list) else [tr.get("side") or "parrain"]
        if ctx.get("side") not in sides:
            return False                          # that side's message is switched off
    elif sc == "welcome":
        if ctx.get("event") != "wallet":
            return False                         # only the card landing in a Wallet (2026-10-11)
        if _db.automation_log.find_one(q) or _db.automation_queue.find_one(q):
            return False                         # once per client: a re-add or a 2nd phone says nothing
    elif sc == "geo":
        from features import geo_automation as GA
        want = set(tr.get("stores") or [])
        if want and ctx.get("store_id") and ctx["store_id"] not in want:
            return False                         # near an establishment this one does not watch
        if not in_window(row.get("schedule") or {}, at):
            return False                         # a passer-by does not wait for the window
        last = _db.automation_log.find_one(q, sort=[("sent_at", -1)])
        if last and at - _aware(last["sent_at"]) < timedelta(days=max(1, int(tr.get("cooldown_days") or 7))):
            return False
        spot = next((a for a in GA.zone(tid, row) if a["id"] == ctx.get("store_id")), None) or \
            (GA.zone(tid, row) or [None])[0]
        if not GA.weather_ok(tid, tr, spot, at):
            return False
    elif sc == "google_review":
        t = gr_type(tr)
        if t == "loyal" and int(cust.get("visits") or 0) != int(tr.get("visits") or 0):
            return False                         # « Client fidèle »: at the N-th visit
        if t in ("after_visit", "loyal") and ctx.get("event", "visit") != "visit":
            return False
        if t == "date" and ctx.get("event") != "date":
            return False
        # the établissement visited speaks with ITS Google link (2+ établissements)
        branch = ctx.get("branch_id") if t != "date" else None
        if not branch and t == "date":
            branch = _last_branch(tid, cust)
        if not review_link(tid, branch):
            return False
        ctx["branch_id"] = branch
        if tr.get("stop_after_click", True) and _db.google_review_clicks.find_one({"tenant_id": tid,
                                                                                  "customer_id": cust["id"]}):
            return False                         # already opened the review page: not asked again
        if _db.automation_queue.find_one(q):
            return False
        last = _db.automation_log.find_one(q, sort=[("sent_at", -1)])
        freq = gr_freq(tr)
        if freq in ("once", "smart") and last:
            return False
        every = 1 if tr.get("frequency") == "every_scan" else max(1, int(tr.get("every_days") or 30))
        if freq == "days" and last and at - _aware(last["sent_at"]) < timedelta(days=every):
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
    elif sc == "custom" and tr.get("type") in CR_V2:
        from features import custom_rules as CR
        if not CR.eligible(tid, row, cust, ctx, at) or not CR.rules_ok(row, cust, at, ctx):
            return False
        if tr.get("type") == "geo" and (row.get("schedule") or {}).get("window") and not in_window(row["schedule"], at):
            return False                         # outside the plage horaire: a passer-by does not wait
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


def gr_type(tr: Dict[str, Any]) -> str:
    return tr.get("type") if tr.get("type") in GR_TYPES else "after_visit"


def gr_freq(tr: Dict[str, Any]) -> str:
    """Une seule fois / Répétition régulière / Envoi intelligent (« after
    each visit » before the mockups = every day at most)."""
    f = tr.get("frequency")
    return "days" if f == "every_scan" else (f if f in GR_FREQS else "days")


def _branches(tid: str) -> List[Dict[str, Any]]:
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "branches": 1}) or {}
    return [b for b in t.get("branches") or [] if b.get("id") and b.get("status") != "closed"]


def review_link(tid: str, branch_id: Optional[str] = None) -> Optional[str]:
    """The Google review page a client is sent to: with 2+ établissements,
    the one they visited (each has its own, required); else the shop's link
    (Insights › Avis Google). None = not configured → nothing is sent."""
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "google_review_url": 1, "google_reviews_enabled": 1,
                                           "branches": 1}) or {}
    if not t.get("google_reviews_enabled"):
        return None
    branches = [b for b in t.get("branches") or [] if b.get("id") and b.get("status") != "closed"]
    if len(branches) > 1:
        b = next((x for x in branches if x["id"] == branch_id), None)
        return (b or {}).get("google_review_url") or None
    return t.get("google_review_url") or (branches[0].get("google_review_url") if branches else None) or None


def _last_branch(tid: str, cust: Dict[str, Any]) -> Optional[str]:
    v = _db.visits.find_one({"tenant_id": tid, "customer_id": cust["id"], "branch_id": {"$nin": [None, ""]}},
                            {"_id": 0, "branch_id": 1}, sort=[("visit_time", -1)])
    return (v or {}).get("branch_id") or cust.get("branch_id")


def usual_hour(tid: str, cust: Dict[str, Any]) -> int:
    """« Envoi intelligent »: the hour this client usually comes (their last
    visits, Paris), else the shop's busiest hour — always between 8h and 20h."""
    hours = []
    for v in _db.visits.find({"tenant_id": tid, "customer_id": cust["id"]}, {"_id": 0, "visit_time": 1}
                             ).sort("visit_time", -1).limit(20):
        t = _aware(v.get("visit_time"))
        if t:
            hours.append(_paris(t).hour)
    if len(hours) >= 3:
        h = sorted(hours)[len(hours) // 2]
    else:
        h = 10
        try:
            from features import campaigns_page as CP
            best = CP.best_slot(tid)
            if best:
                h = int(best["from"][:2])
        except Exception:
            pass
    return max(8, min(19, h))


def smart_due(tid: str, cust: Dict[str, Any], sched: Dict[str, Any], earliest: datetime) -> datetime:
    """The first day (ticked, inside the period) at the client's usual hour,
    not before `earliest`."""
    h = usual_hour(tid, cust)
    loc = _paris(earliest)
    for i in range(0, 15):
        d = (loc + timedelta(days=i)).date()
        if not _day_ok(sched, d):
            continue
        cand = _from_paris(d, h, 0)
        if cand >= earliest:
            return cand
    return next_window(sched, earliest)


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


def _sent_on(row: Dict[str, Any], day: date) -> int:
    """Messages this automation sent on that Paris day (its daily limit)."""
    a = _from_paris(day, 0, 0)
    return _db.automation_log.count_documents({"automation_id": row["id"], "status": {"$nin": ["deferred", "holdout"]},
                                               "sent_at": {"$gte": a, "$lt": a + timedelta(days=1)}})


def _over_limit(row: Dict[str, Any], due: datetime) -> Optional[datetime]:
    """« Limite d'envoi quotidienne » of an event automation: when that day is
    full (sent + already waiting for it), the first moment of the next day's
    plage — nobody is dropped (user, 2026-10-11). None = room that day."""
    sched = row.get("schedule") or {}
    limit = sched.get("daily_limit")
    if not limit:
        return None
    moved = None
    for _ in range(60):                       # the first day with room, two months at most
        day = _paris(due).date()
        a = _from_paris(day, 0, 0)
        waiting = _db.automation_queue.count_documents({"automation_id": row["id"],
                                                        "due_at": {"$gte": a, "$lt": a + timedelta(days=1)}})
        if _sent_on(row, day) + waiting < int(limit):
            return moved
        due = moved = next_window(sched, _from_paris(day + timedelta(days=1), 0, 0))
    return moved


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
            if not running(row, at):
                continue                           # « Terminée », or its period not begun
            try:
                if not matches(tid, row, cust, at, cache) or not _eligible(tid, row, cust, ctx, at):
                    continue
                due = at + _delay(row.get("trigger") or {})
                v2 = scenario == "custom" and (row.get("trigger") or {}).get("type") in CR_V2
                if v2:
                    from features import custom_rules as CR
                    due = CR.send_moment(row, due)             # « à une date / heure spécifique »
                if v2 and (row.get("trigger") or {}).get("type") == "geo":
                    pass                                     # a passer-by does not wait (checked in _eligible)
                elif scenario == "google_review" and gr_freq(row.get("trigger") or {}) == "smart":
                    due = smart_due(tid, cust, row.get("schedule") or {}, due)   # the client's own time
                elif scenario != "geo":
                    due = next_window(row.get("schedule") or {}, due)
                if scenario != "geo":
                    due = _over_limit(row, due) or due      # the day is full: the next one
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


def wallet_added(tid: str, cust: Dict[str, Any], wallet: str) -> List[Dict[str, Any]]:
    """The card just landed in a Wallet (Apple: the device registered the
    pass; Google: its « save » callback): the Bienvenue goes, once per client."""
    if not tid or not cust or not cust.get("id"):
        return []
    fresh = _db.customers.find_one({"id": cust["id"]}, {"_id": 0}) or cust
    return fire("welcome", tid, fresh, {"event": "wallet", "wallet": wallet})


# ---------------------------------------------------------------------------
# the clock
# ---------------------------------------------------------------------------
def tick_seen(at: datetime) -> bool:
    row = _db.automation_meta.find_one({"_id": "tick"}) or {}
    last = _aware(row.get("at"))
    return bool(last and at - last < timedelta(hours=2))


# Anniversaire, the same day (user, 2026-10-20): after the day's round at its
# hour, a client whose birthday is today — a card added or a birthday saved
# later — is greeted on a later 15-minute tick, until 20:00 (Paris); later
# than that, the next day's round. A card added less than an hour ago waits
# that hour, so the birthday does not land on top of « Bienvenue ». The
# offer is valid BIRTHDAY_OFFER_DAYS days from the birthday unless the owner
# says otherwise (trigger.offer_days, 1–60): that is also how late a missed
# greeting may still go.
BIRTHDAY_OFFER_DAYS = 7
BIRTHDAY_LAST = (20, 0)
BIRTHDAY_AFTER_CARD = timedelta(minutes=60)


def offer_days(row: Dict[str, Any]) -> int:
    try:
        n = int((row.get("trigger") or {}).get("offer_days") or BIRTHDAY_OFFER_DAYS)
    except (TypeError, ValueError):
        n = BIRTHDAY_OFFER_DAYS
    return max(1, min(60, n))


def birthday_until(row: Dict[str, Any], cust: Dict[str, Any], at: datetime) -> Optional[date]:
    """The last day of this client's birthday offer: their birthday this time
    round (the one this greeting is for) + the offer's days − 1."""
    off = int((row.get("trigger") or {}).get("offset_days") or 0)
    n = offer_days(row)
    key = str(cust.get("birthday") or "")[-5:]
    today = _paris(at).date()
    for back in range(0, max(1, n - off) + 31):
        bday = today - timedelta(days=back) - timedelta(days=off)
        if bday.strftime("%m-%d") == key:
            return bday + timedelta(days=n - 1)
    return None


def _birthday_due(tid: str, row: Dict[str, Any], at: datetime) -> List[Dict[str, Any]]:
    """Clients whose birthday (± offset) is today, or earlier while its offer
    is still valid, not greeted by this automation this year — a skipped day
    (« jours ouvrés »), a missed run or a card added late is caught up, never
    doubled. A card added within the hour waits (« Bienvenue » first)."""
    off = int((row.get("trigger") or {}).get("offset_days") or 0)
    today = _paris(at).date()
    keys = {}
    for back in range(0, max(1, offer_days(row) - off)):
        d = today - timedelta(days=back)
        bday = d - timedelta(days=off)            # offset −3 = three days BEFORE the birthday
        keys[bday.strftime("%m-%d")] = d
    people = list(_db.customers.find({"tenant_id": tid, "birthday": {"$in": list(keys)}}, {"_id": 0}))
    # one birthday a year: greeted by this automation in the last 300 days = done
    done = set(_db.automation_log.distinct("customer_id", {"tenant_id": tid, "automation_id": row["id"],
                                                           "sent_at": {"$gte": at - timedelta(days=300)}}))
    done |= set(_db.automation_queue.distinct("customer_id", {"automation_id": row["id"]}))
    fresh = at - BIRTHDAY_AFTER_CARD
    return [c for c in people if c["id"] not in done
            and not ((_aware(c.get("created_at")) or fresh) > fresh)]


def _inactive_due(tid: str, row: Dict[str, Any], at: datetime) -> List[Dict[str, Any]]:
    """Clients past the inactivity, not told for this absence yet (or due a
    relance), not already waiting in today's spread — the most recently
    lapsed first: they are the likeliest to come back, and a daily limit
    keeps them."""
    tr = row.get("trigger") or {}
    days = max(1, int(tr.get("days") or 30))
    cutoff = at - timedelta(days=days)
    waiting = set(_db.automation_queue.distinct("customer_id", {"automation_id": row["id"]}))
    # each client's last relance from this automation, in one read (was one per client)
    told: Dict[str, Any] = {}
    for g in _db.automation_log.find({"tenant_id": tid, "automation_id": row["id"]},
                                     {"_id": 0, "customer_id": 1, "sent_at": 1}):
        prev_at = _aware(g.get("sent_at"))
        if prev_at and (g.get("customer_id") not in told or prev_at > told[g["customer_id"]]):
            told[g["customer_id"]] = prev_at
    out = []
    for c in _db.customers.find({"tenant_id": tid}, {"_id": 0}):
        if c["id"] in waiting:
            continue
        last = _aware(c.get("last_visit_date")) or _aware(c.get("created_at"))
        if not last or last > cutoff:
            continue
        sent = told.get(c["id"])
        if sent:
            if sent >= last and tr.get("repeat") != "every":
                continue                          # once per absence: until they come back
            if tr.get("repeat") == "every" and at - sent < timedelta(days=max(1, int(tr.get("every_days") or 30))):
                continue
        out.append(c)
    out.sort(key=lambda c: _aware(c.get("last_visit_date")) or _aware(c.get("created_at")) or at, reverse=True)
    return out


def _spread(sched: Dict[str, Any], at: datetime, n: int) -> List[datetime]:
    """« Limite d'envoi par jour »: the day's sends shared out evenly from now
    to the end of the plage horaire (« lisser l'envoi sur la journée »)."""
    if n <= 1 or not sched.get("window"):
        return [at] * n
    th, tm = _hm(sched.get("window_to"), (20, 0))
    end = _from_paris(_paris(at).date(), th, tm)
    if end <= at + timedelta(minutes=15):
        return [at] * n
    step = (end - at) / n
    return [at + step * i for i in range(n)]


# a run holds its automation while it sends: longer than a function lives
# (vercel.json maxDuration 360 s), shorter than the 15-minute tick — a run
# killed mid-way is taken up by the next tick, its clients already told skipped
RUN_LEASE = timedelta(minutes=10)


def _lease_free(field: str, at: datetime) -> Dict[str, Any]:
    return {"$or": [{field: None}, {field: {"$lt": at - RUN_LEASE}}]}


def _claim(row: Dict[str, Any], at: datetime) -> bool:
    """Two runs at once (the 15-minute tick and the daily cron, a slow run):
    the first to take the lease sends, the other skips (audit 2026-10-26:
    780 of 1 560 inactive clients got the relance twice). « last_run_at »
    unchanged since read: a run that already finished today is not redone."""
    q = {"id": row["id"], "last_run_at": row.get("last_run_at"), **_lease_free("running_at", at)}
    return _db.automations.update_one(q, {"$set": {"running_at": at}}).modified_count == 1


def _release(row: Dict[str, Any], at: datetime, done: bool) -> None:
    """Done: today is marked. Failed: the next tick tries again."""
    _db.automations.update_one({"id": row["id"], "running_at": at},
                               {"$set": {"running_at": None, **({"last_run_at": at} if done else {})}})


def run_due(at: Optional[datetime] = None, source: str = "daily") -> Dict[str, Any]:
    """Release what is due. `source` « tick » (every 15 min, Vercel Pro) or
    « daily » (07:00 UTC): without a recent tick the daily run sends all of
    today's — early rather than never. One run reads each shop and card once
    (services/doc_cache, audit 2026-10-26: five times per message before)."""
    from services import doc_cache as _DC
    token = _DC.begin()
    try:
        return _run_due(at, source)
    finally:
        _DC.end(token)


def _run_due(at: Optional[datetime] = None, source: str = "daily") -> Dict[str, Any]:
    at = at or _now()
    if source == "tick":
        _db.automation_meta.update_one({"_id": "tick"}, {"$set": {"at": at}}, upsert=True)
    strict = source == "tick" or tick_seen(at)
    loc_today = _paris(at).date()
    summary = {"at": at.isoformat(), "queued_sent": 0, "time_sent": 0, "errors": 0, "strict": strict}
    # 1. the event messages that waited for their window / delay
    horizon = at if strict else _from_paris(loc_today, 23, 59)
    for q in list(_db.automation_queue.find({"due_at": {"$lte": horizon}}, {"_id": 0}).limit(5000)):
        if not _db.automation_queue.delete_one({"id": q["id"]}).deleted_count:
            continue                              # another run took this one
        row = _db.automations.find_one({"id": q["automation_id"], "status": "active"}, {"_id": 0})
        cust = _db.customers.find_one({"id": q["customer_id"]}, {"_id": 0})
        if not row or not cust or not _plan_ok(row["tenant_id"]) or not running(row, at) \
                or not matches(row["tenant_id"], row, cust, at):
            continue
        limit = (row.get("schedule") or {}).get("daily_limit")
        if limit and not is_timed(row["scenario"], row.get("trigger")) \
                and _sent_on(row, _paris(at).date()) >= int(limit):
            # today is full: the next day with room, at its plage (nobody dropped)
            nxt = next_window(row.get("schedule") or {}, _from_paris(_paris(at).date() + timedelta(days=1), 0, 0))
            _db.automation_queue.insert_one({**q, "due_at": _over_limit(row, nxt) or nxt})
            continue
        if row["scenario"] == "custom" and (row.get("trigger") or {}).get("type") in CR_V2:
            from features import custom_rules as CR
            if not CR.rules_ok(row, cust, at, q.get("ctx")):
                continue                          # the limit / anti-doublon filled up meanwhile
        if row["scenario"] == "inactive":         # came back while waiting: nothing to say
            last = _aware(cust.get("last_visit_date")) or _aware(cust.get("created_at"))
            if not last or at - last < timedelta(days=max(1, int((row.get("trigger") or {}).get("days") or 30))):
                continue
        try:
            if _deliver(row["tenant_id"], row, cust, q.get("ctx") or {}, at):
                summary["queued_sent"] += 1
        except Exception:
            summary["errors"] += 1
    # 2. the time scenarios, once a day each, at their hour
    for row in list(_db.automations.find({"status": "active",
                                          "scenario": {"$in": ["birthday", "inactive", "custom", "google_review"]}},
                                         {"_id": 0})):
        if row["scenario"] in ("custom", "google_review") and (row.get("trigger") or {}).get("type") != "date":
            continue                               # (« Nouvelle automatisation »: run_custom below)
        tid = row["tenant_id"]
        claimed = False
        try:
            sched = row.get("schedule") or {}
            if not _day_ok(sched, loc_today) or not _plan_ok(tid) or not running(row, at):
                continue
            last = _aware(row.get("last_run_at"))
            if last and _paris(last).date() == loc_today:
                if row["scenario"] == "birthday" and strict:
                    summary["time_sent"] += _birthday_catch_up(tid, row, at, loc_today)
                continue
            hh, mm = _send_hour(tid, sched)
            if strict and at < _from_paris(loc_today, hh, mm):
                continue
            if row["scenario"] in ("custom", "google_review") and not date_due(row.get("trigger") or {}, loc_today):
                continue
            if not _claim(row, at):
                continue                           # another run is sending it
            claimed = True
            if row["scenario"] in ("custom", "google_review"):
                people = list(_db.customers.find({"tenant_id": tid}, {"_id": 0}))
            else:
                people = _birthday_due(tid, row, at) if row["scenario"] == "birthday" else _inactive_due(tid, row, at)
            cache: Dict[str, Any] = {}
            chosen = []
            for c in people:
                ctx: Dict[str, Any] = {"event": "date"}
                if not matches(tid, row, c, at, cache):
                    continue
                if row["scenario"] == "google_review" and not _eligible(tid, row, c, ctx, at):
                    continue                       # its link, the click, « une seule fois »…
                chosen.append((c, ctx))
            limit = sched.get("daily_limit")
            if limit:
                chosen = chosen[:int(limit)]       # the rest are still due tomorrow
            # with a limit and the 15-minute tick, the day's sends are spread
            # over the plage horaire; without the tick they all go now
            times = _spread(sched, at, len(chosen)) if limit and strict else [at] * len(chosen)
            from services import send_batch as _SB
            with _SB.batch(_db, tid, [c["id"] for (c, _), when in zip(chosen, times)
                                      if when <= at + timedelta(seconds=30)]):
                for (c, ctx), when in zip(chosen, times):
                    if when <= at + timedelta(seconds=30):
                        if _deliver(tid, row, c, ctx, at):
                            summary["time_sent"] += 1
                    else:
                        _db.automation_queue.insert_one({"id": str(uuid.uuid4()), "tenant_id": tid,
                                                         "automation_id": row["id"], "customer_id": c["id"],
                                                         "due_at": when, "ctx": ctx, "created_at": at})
                        summary.setdefault("spread", 0)
                        summary["spread"] += 1
            _release(row, at, done=True)
        except Exception as exc:
            summary["errors"] += 1
            if claimed:
                _release(row, at, done=False)
            print(f"automations: {row.get('id')} failed ({exc})")
    run_custom(at, strict, summary)
    return summary


def _birthday_catch_up(tid: str, row: Dict[str, Any], at: datetime, today: date) -> int:
    """The day's round is done: a birthday that turned up since (card added,
    birthday saved) is greeted now, until 20:00 — never twice, within the
    daily limit."""
    if at >= _from_paris(today, *BIRTHDAY_LAST):
        return 0                                   # too late today: tomorrow's round
    limit = (row.get("schedule") or {}).get("daily_limit")
    room = (int(limit) - _sent_on(row, today)) if limit else None
    if room is not None and room <= 0:
        return 0
    # one catch-up at a time (a run that died frees it after RUN_LEASE)
    if not _db.automations.update_one({"id": row["id"], **_lease_free("catch_up_at", at)},
                                      {"$set": {"catch_up_at": at}}).modified_count:
        return 0
    sent, cache = 0, {}
    try:
        for c in _birthday_due(tid, row, at):
            if room is not None and sent >= room:
                break
            if not matches(tid, row, c, at, cache):
                continue
            if _deliver(tid, row, c, {"event": "date"}, at):
                sent += 1
    finally:
        _db.automations.update_one({"id": row["id"]}, {"$set": {"catch_up_at": None}})
    return sent


def run_custom(at: datetime, strict: bool, summary: Dict[str, Any]) -> None:
    """« Nouvelle automatisation » on a clock (date, récurrent, comportement,
    autre › inactivité / anniversaire / 1re visite): once a day each, at its
    hour in its own « Fuseau horaire »."""
    from features import custom_rules as CR
    rows = [r for r in _db.automations.find({"status": "active", "scenario": "custom",
                                             "trigger.type": {"$in": list(CR_V2)}}, {"_id": 0})
            if CR.is_timed(r.get("trigger") or {})]
    for row in rows:
        tid = row["tenant_id"]
        claimed = False
        try:
            sched = row.get("schedule") or {}
            if not _plan_ok(tid) or not running(row, at):
                continue
            today = CR.local(at, sched).date()
            last = _aware(row.get("last_run_at"))
            if last and CR.local(last, sched).date() == today:
                continue
            hh, mm = _hm(sched.get("hour"), (10, 0))
            if strict and at < CR.from_local(today, hh, mm, sched):
                continue
            if not _claim(row, at):
                continue                           # another run is sending it
            claimed = True
            cache: Dict[str, Any] = {}
            for c, ctx in CR.due_people(tid, row, at):
                if not matches(tid, row, c, at, cache) or not CR.rules_ok(row, c, at, ctx):
                    continue
                if _deliver(tid, row, c, ctx, at):
                    summary["time_sent"] += 1
            _release(row, at, done=True)
        except Exception as exc:
            summary["errors"] += 1
            if claimed:
                _release(row, at, done=False)
            print(f"automations: custom {row.get('id')} failed ({exc})")


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
    until = None
    if n.get("until"):
        try:
            until = date.fromisoformat(str(n["until"])[:10])
        except ValueError:
            until = None
        if until and _paris(at or _now()).date() > until:
            return None                            # the birthday offer is over: off the card
    return {"log_id": n.get("log_id"), "title": n.get("title"), "body": n.get("body"), "pass": n.get("pass", True),
            "button_label": n.get("label"), "button_url": n.get("url"), "image_url": n.get("image_url"),
            "sent_at": sent.isoformat(), "until": until.isoformat() if until else None,
            "until_label": f"Offre valable jusqu'au {fr_day(until)}" if until else None}


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
                                             "status": {"$nin": ["deferred", "holdout"]}},
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
    logs = list(_db.automation_log.find({"tenant_id": tid, "automation_id": r["id"], "status": {"$nin": ["deferred", "holdout"]}},
                                        {"_id": 0, "customer_id": 1, "sent_at": 1, "clicked_at": 1}))
    reach = len({x["customer_id"] for x in logs})
    opened = _opened(tid, logs) if logs else 0
    clicks = sum(1 for x in logs if x.get("clicked_at"))
    out = {k: r.get(k) for k in ("id", "scenario", "name", "description", "status", "trigger", "message", "targeting",
                                 "schedule", "store_ids", "message_filleul", "message_reminder")}
    out["status"] = status_of(r)                  # « Terminée » once its period is over
    if r["scenario"] == "geo":
        from features import geo_automation as GA
        out["results"] = GA.results(tid, r["id"])
    from features import temoin as T
    if r["scenario"] in T.AUTOMATION_SCENARIOS:
        # groupe témoin: its clients held back vs messaged, and « +X € » once measured
        out["temoin"] = T.automation_block(tid, r["id"])
        out["temoin_on"] = T.enabled(tid)
    if r["scenario"] == "custom" and (r.get("trigger") or {}).get("type") in CR_V2:
        from features import custom_rules as CR
        out["next_dates"] = CR.next_dates(r, CR.local(_now(), r.get("schedule")).date())
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


def review_text(tr: Dict[str, Any]) -> str:
    """« Après la visite · 2 heures après · une seule fois » — the list's words."""
    t, f = gr_type(tr), gr_freq(tr)
    if t == "loyal":
        n = int(tr.get("visits") or 0)
        head = f"Client fidèle · à la {n}{'re' if n == 1 else 'e'} visite"
    elif t == "date":
        try:
            on = date.fromisoformat(str(tr.get("date") or "")[:10])
            head = f"Le {on.day}{'er' if on.day == 1 else ''} {MONTHS_FR[on.month - 1]} {on.year}"
        except ValueError:
            head = "Date à choisir"
    else:
        head = "Après la visite" + (f" · {_span(tr)} après" if int(tr.get("delay_value") or 0) else "")
    n = int(tr.get("every_days") or 30)
    tail = {"once": "une seule fois", "smart": "envoi intelligent",
            "days": "au plus une fois par jour" if n == 1 else f"au plus tous les {n} jours"}[f]
    return f"{head} · {tail}"


def trigger_text(r: Dict[str, Any]) -> str:
    sc, tr = r["scenario"], r.get("trigger") or {}
    if sc == "tier_up":
        return tier_text(tr)
    if sc == "custom" and tr.get("type") in CR_V2:
        from features import custom_rules as CR
        return CR.trigger_text(tr, r.get("schedule"))
    if sc == "custom":
        return custom_text(tr)
    if sc == "birthday":
        off = int(tr.get("offset_days") or 0)
        when = "Le jour même" if off == 0 else (f"{-off} jour{'s' if off < -1 else ''} avant" if off < 0
                                                 else f"{off} jour{'s' if off > 1 else ''} après")
        n = offer_days(r)
        return f"{when} · offre valable {n} jour{'s' if n > 1 else ''}"
    if sc == "near_reward":
        if tr.get("threshold") is not None:
            n = int(tr["threshold"])
            unit = reward_unit(_db.card_templates.find_one({"tenant_id": r.get("tenant_id")}, {"_id": 0}) or {}) \
                if r.get("tenant_id") else (tr.get("unit") or "points")
            word = {"points": "point" if n == 1 else "points", "tampons": "tampon" if n == 1 else "tampons"}.get(unit, unit)
            return f"Seuil presque atteint · {n} {word} avant la récompense"
        n = int(tr.get("visits_left") or 1)
        return f"À {n} visite{'s' if n > 1 else ''} de la récompense"
    if sc == "inactive":
        n = int(tr.get("days") or 30)
        return f"Après {n} jours sans visite" + (" · puis tous les " + str(int(tr.get('every_days') or 30)) + " j"
                                                if tr.get("repeat") == "every" else "")
    if sc == "referral":
        sides = tr.get("sides") if isinstance(tr.get("sides"), list) else [tr.get("side") or "parrain"]
        who = " et ".join({"parrain": "au parrain", "filleul": "au filleul"}[x] for x in SIDES if x in sides) or "à personne"
        return f"Un client parraine un ami · points crédités · message {who}"
    if sc == "welcome":
        return "Après l'ajout de la carte dans Wallet"
    if sc == "google_review":
        return review_text(tr)
    if sc == "geo":
        n = int(tr.get("cooldown_days") or 7)
        base = "Entrée dans la zone · " + ("au plus une fois par jour" if n == 1 else f"au plus tous les {n} jours")
        w = [GEO_WEATHER[x] for x in tr.get("weather") or [] if x in GEO_WEATHER]
        return base + (f" · météo : {' ou '.join(w).lower()}" if w else "")
    return SCENARIOS[sc]["trigger_label"]


DAY_NAMES = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
GEO_WEATHER = {"sun": "Ensoleillé", "clouds": "Nuageux", "rain": "Pluie", "cold": "Froid", "hot": "Chaud"}


MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
             "octobre", "novembre", "décembre"]


def fr_day(d: date) -> str:
    """« 27 octobre »."""
    return f"{d.day} {MONTHS_FR[d.month - 1]}"


def _fr_date(raw: Any) -> str:
    try:
        return date.fromisoformat(str(raw)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return ""


def schedule_text(r: Dict[str, Any]) -> str:
    s = r.get("schedule") or {}
    if r.get("scenario") == "custom" and (r.get("trigger") or {}).get("type") in CR_V2:
        from features import custom_rules as CR
        return CR.rules_text(s)
    days = {"all": "Tous les jours", "weekdays": "Jours ouvrés"}.get(s.get("days") or "all") or \
        ", ".join(DAY_NAMES[int(d)] for d in sorted(s.get("weekdays") or []))
    period = ""
    if s.get("valid_from") or s.get("valid_to"):
        a, b = _fr_date(s.get("valid_from")), _fr_date(s.get("valid_to"))
        period = f" · du {a} au {b}" if a and b else (f" · à partir du {a}" if a else f" · jusqu'au {b}")
    if is_timed(r["scenario"], r.get("trigger")):
        out = f"{days} · {'plage intelligente' if s.get('smart') else (s.get('hour') or '10:00')}"
        if r["scenario"] == "inactive" and s.get("window"):
            out += f" · entre {s.get('window_from') or '09:00'} et {s.get('window_to') or '21:00'}"
        if s.get("daily_limit"):
            out += f" · {int(s['daily_limit'])} max/jour"
        return out + period
    if not s.get("window", True):
        return f"{days} · {'toute la journée' if r['scenario'] == 'geo' else 'immédiat'}{period}"
    hours = " / ".join(f"{a[0]:02d}h{a[1]:02d}–{b[0]:02d}h{b[1]:02d}".replace("h00", "h") for a, b in slots_of(s))
    return f"{days} · {hours}{period}"


OLD_NEAR_LABEL = "Proche de la récompense"


def merge_referrals(tid: str) -> None:
    """Parrainage is ONE automation with both messages (user, 2026-10-11).
    The older rows — one per side (« Parrainage — parrain / — filleul ») —
    become that: each side keeps its words and its on/off; the first parrain
    row and the first filleul row merge (the filleul's sends counted under
    the merged one); any further one stays, holding its own side only."""
    rows = list(_db.automations.find({"tenant_id": tid, "scenario": "referral", "trigger.side": {"$exists": True}},
                                     {"_id": 0}).sort([("order", 1), ("created_at", 1)]))
    if not rows:
        return
    parrains = [r for r in rows if (r["trigger"].get("side") or "parrain") == "parrain"]
    filleuls = [r for r in rows if r["trigger"].get("side") == "filleul"]
    for r in rows:                                 # each on its own first: one side, its words, its status
        side = r["trigger"].get("side") or "parrain"
        upd = {"trigger": {**{k: v for k, v in r["trigger"].items() if k != "side"}, "sides": [side]},
               "message_filleul": r.get("message") if side == "filleul" else
               {"title": FILLEUL_DEFAULT["title"], "body": FILLEUL_DEFAULT["body"], "image_url": None,
                "button": {"enabled": False, "label": SCENARIOS["referral"]["button"], "link_type": "card",
                           "offer_id": None, "url": None}}}
        if side == "filleul":
            upd["message"] = {**(r.get("message") or {}), "title": SCENARIOS["referral"]["title"],
                              "body": SCENARIOS["referral"]["body"]}
        _db.automations.update_one({"id": r["id"]}, {"$set": upd})
    if parrains and filleuls:
        p_row, f_row = parrains[0], filleuls[0]
        p_on, f_on = p_row.get("status") == "active", f_row.get("status") == "active"
        sides = [x for x, on in (("parrain", p_on), ("filleul", f_on)) if on]
        _db.automations.update_one({"id": p_row["id"]}, {"$set": {
            "name": "Parrainage" if p_row.get("name") in ("Parrainage — parrain", "Parrainage") else p_row.get("name"),
            "trigger": {**{k: v for k, v in p_row["trigger"].items() if k != "side"},
                        # both sides were off: the automation is paused, each message ready
                        "sides": sides or ["parrain", "filleul"]},
            "status": "active" if sides else p_row.get("status"),
            "message_filleul": f_row.get("message"), "updated_at": _now()}})
        _db.automation_log.update_many({"automation_id": f_row["id"]}, {"$set": {"automation_id": p_row["id"]}})
        _db.automation_queue.update_many({"automation_id": f_row["id"]}, {"$set": {"automation_id": p_row["id"]}})
        _db.automations.delete_one({"id": f_row["id"]})


def referral_page(tid: str) -> Dict[str, Any]:
    """The Parrainage programme's rules, for the editor's « Récompenses »."""
    cfg = _db.referral_config.find_one({"tenant_id": tid}, {"_id": 0}) or {}
    return {"enabled": bool(cfg.get("enabled")),
            "referrer_reward_points": int(cfg.get("referrer_reward_points") or 0),
            "referee_reward_points": int(cfg.get("referee_reward_points") or 0),
            "reward_mode": cfg.get("reward_mode") or "once",
            "referrer_reward_points_next": int(cfg.get("referrer_reward_points_next") or 0),
            "referee_reward_points_next": int(cfg.get("referee_reward_points_next") or 0),
            "minimum_visits_to_earn": int(cfg.get("minimum_visits_to_earn") or 1)}


def near_page(tid: str) -> Dict[str, Any]:
    """What the Récompense bientôt disponible editor needs of the card: the
    programme's unit and the card's own reward (its « exemple de scénario »)."""
    from features import loyalty_card as LC
    tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0}) or {}
    prog = LC._programme(tpl)
    goal = int(tpl.get("reward_points") or 100) if prog in ("points_euro", "points_visit") else \
        (max(1, int(tpl.get("reward_threshold_stamps") or 10)) if prog == "stamps" else None)
    return {"programme": prog, "unit": reward_unit(tpl), "card_goal": goal,
            "card_reward": (tpl.get("reward_description") or "").strip() or "votre récompense",
            "tiers": [{"key": t["key"], "label": t["label"], "min": t["min"], "reward": t.get("reward") or ""}
                      for t in LC.tiers_for(tid)]}


def _list(tid: str, token: TokenData, request: Any = None) -> Dict[str, Any]:
    migrate(tid)
    split_per_store(tid)
    at = _now()
    # the scenario's new name (user, 2026-10-11) on the rows that kept the default one
    _db.automations.update_many({"tenant_id": tid, "scenario": "near_reward", "name": OLD_NEAR_LABEL},
                                {"$set": {"name": SCENARIOS["near_reward"]["label"]}})
    merge_referrals(tid)
    split_per_store(tid)
    q: Dict[str, Any] = {"tenant_id": tid}
    menu = _menu_store(tid, token, request)
    if menu:                                       # the establishment chosen: its automations
        q["store_ids"] = [menu]
    rows = [_row_view(r, tid) for r in _db.automations.find(q, {"_id": 0}).sort([("order", 1), ("created_at", 1)])]
    active = sum(1 for r in rows if r["status"] == "active")
    counts = {"all": len(rows), "active": active, "paused": sum(1 for r in rows if r["status"] == "paused"),
              "draft": sum(1 for r in rows if r["status"] == "draft"),
              "ended": sum(1 for r in rows if r["status"] == "ended")}
    from features import campaigns_page as CP
    tenant = _db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    trade = trade_meta(tenant)
    tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "logo_url": 1, "brand_fields": 1}) or {}
    offers = []
    for c in _db.campaigns.find({"tenant_id": tid, "status": "sent"}, {"_id": 0}).sort("sent_at", -1).limit(40):
        try:
            from features import campaign_kinds as K
            if menu and c.get("store_ids") and menu not in c["store_ids"]:
                continue                           # another establishment's offer
            if K.is_live(c, at) and c.get("kind") != "defi":
                offers.append({"id": c["id"], "name": c.get("name") or "Offre", "terms": K.terms_label(c)})
        except Exception:
            pass
    from features import team_access as T
    return {
        "rows": rows, "counts": counts,
        "stats": {"active": active, "total": len(rows), **_stats(tid, at)},
        "scenarios": [{"key": k, **{f: trade[k][f] for f in ("label", "sub", "icon", "tone", "kind",
                                                              "trigger_label", "title", "body", "button")},
                       "variables": VARIABLES["common"] + VARIABLES[k]} for k in ORDER],
        "segments": CP.segment_options(tid, at, None),
        "stores": [{"id": s["id"], "name": s.get("name")} for s in T.stores(tid)],
        "offers": offers,
        "best_slot": CP.best_slot(tid),
        "has_position": CP._has_position(tid),
        "google_review_ready": bool(tenant.get("google_reviews_enabled") and any(current_links(tid).values())),
        "google": {"links": current_links(tid), "enabled": bool(tenant.get("google_reviews_enabled")),
                   "stores": [{"id": b["id"], "name": b.get("name") or "Établissement"} for b in _branches(tid)]
                   if len(_branches(tid)) > 1 else []},
        "geo_ready": bool(tenant.get("geo_enabled")),
        "geo": _geo_page(tid, tenant),
        "shop": tenant.get("campaign_sender_name") or tenant.get("name") or "",
        "logo_url": (tpl.get("brand_fields") or {}).get("logo_url") or tpl.get("logo_url") or "",
        "can_edit": token.role in EDITORS,
        "tick": tick_seen(at),
        "near": near_page(tid),
        "referral": {**referral_page(tid), "can_edit": _may(token, "referral")},
        "statuses": _statuses(tid),
    }


def _statuses(tid: str) -> List[Dict[str, str]]:
    try:
        from features import customer_rules as R
        return R.statuses(R.load(tid))
    except Exception:
        return []


def _geo_page(tid: str, tenant: Dict[str, Any]) -> Dict[str, Any]:
    """Step 2 of a géolocalisation: the establishments, the shop's radius, what
    lets it run, and the shop's busy hours (Insights) for « forte affluence »."""
    from features import geo_automation as GA
    busy = None
    try:
        from features import insights_page as IP
        hrs = IP._hours(IP.Shop(tid, _now(), None))
        if hrs:
            busy = [int(hrs["busy"][0]), int(hrs["busy"][1])]
    except Exception:
        pass
    return {"anchors": GA.anchors(tid), "radius_m": GA.radius_of(tenant), "live": GA.live(tid),
            "weather": [{"key": k, "label": v} for k, v in GA.WEATHER.items()], "busy": busy,
            "radii": list(GA.RADII_M)}


@router.get("/api/owner/automations/geo/zone")
def geo_zone(token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    """The map's live layer: clients detected near a shop (card opened, rounded,
    seven days), and the weather now — real data only."""
    from features import geo_automation as GA
    tid = token_data.tenant_id
    at = _now()
    spots = [a for a in GA.anchors(tid) if a["lat"] is not None]
    w = GA.weather_now(tid, spots[0]["lat"], spots[0]["lng"], at) if spots else None
    return {**GA.detections(tid, at),
            "weather_now": ({"tags": w["tags"], "temp": round(w["temp"]), "labels": [GA.WEATHER[t] for t in w["tags"]]}
                            if w else None)}


@router.get("/api/owner/automations")
def list_automations(request: Request = None, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    return _list(token_data.tenant_id, token_data, request)


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
    frequency: Any = []                 # removed from the page (2026-10-11): ignored
    spent: Any = []
    last_visit: Any = []
    stores: List[str] = []
    radius_km: Any = None
    client_type: Any = []               # « Type de client » = card statut
    visits_min: Any = None              # « Nombre de visites »: owner-typed
    visits_max: Any = None
    age_min: Any = None                 # « Âge »: two dropdowns, « Tous » = none
    age_max: Any = None
    past_freq: Any = []                 # Client inactif (2026-10-11): « Fréquence d'achat passée »
    tiers: Any = []                     # « Programme de fidélité » (statut)
    origin: Any = []                    # « Origine du client »
    last_offer: Any = []                # « Dernière offre reçue »
    points_min: Any = None              # Nouvelle automatisation › Ciblage (2026-10-11)
    points_max: Any = None
    spent_min: Any = None
    spent_max: Any = None
    last_visit_op: Any = None           # « Date de dernière visite » : il y a plus / moins de
    last_visit_days: Any = None
    activity: Any = []                  # « Statut client » (Règles clients keys)
    signed_since: Optional[str] = None  # « Inscription depuis » (a date)


class ExclusionsIn(BaseModel):
    recent_contact: bool = False        # a message in the last 30 days
    active_offer: bool = False          # an offer still running


class TargetingIn(BaseModel):
    mode: str = "all"
    pick: Optional[str] = None          # Nouvelle automatisation: the card chosen (all, active, inactive…)
    inactive_days: Any = None
    segment: Optional[str] = None
    passants: Optional[str] = "all"
    filters: FiltersIn = FiltersIn()
    exclusions: ExclusionsIn = ExclusionsIn()


class ScheduleIn(BaseModel):
    days: str = "all"
    weekdays: List[Any] = []
    hour: Optional[str] = None
    smart: bool = False
    window: bool = True
    window_from: Optional[str] = "09:00"
    window_to: Optional[str] = "21:00"
    slots: List[Dict[str, Any]] = []
    holidays: bool = True
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    daily_limit: Any = None             # « Limite d'envoi par jour » (optionnel)
    # Nouvelle automatisation (features/custom_rules): Planification + Règles d'envoi
    tz: Optional[str] = None
    limit: Optional[Dict[str, Any]] = None
    dedupe: bool = False
    min_gap_days: Any = None
    send_mode: Optional[str] = None
    send_at: Optional[str] = None
    rules_note: Optional[str] = None


class AutomationIn(BaseModel):
    scenario: str
    name: Optional[str] = None
    description: Optional[str] = None
    google_links: Optional[Dict[str, Any]] = None   # Avis Google: {"main": url} or {branch_id: url}
    status: str = "active"
    trigger: Dict[str, Any] = {}
    message: MessageIn
    message_reminder: Optional["MessageIn"] = None   # Annuelle › « Rappel avant la date »
    message_filleul: Optional[MessageIn] = None      # Parrainage: the filleul's own words
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


def clean_message(m: "MessageIn", sc: str, tid: str, required: bool, who: str = "") -> Dict[str, Any]:
    """One message of an automation, checked (the parrain's and the filleul's
    go through the same rules). `who` prefixes the errors (« Filleul : … »)."""
    try:
        return _clean_message(m, sc, tid, required)
    except HTTPException as exc:
        if who:
            raise HTTPException(status_code=exc.status_code, detail=f"{who} : {exc.detail}")
        raise


def _clean_message(m: "MessageIn", sc: str, tid: str, required: bool) -> Dict[str, Any]:
    title, text = re.sub(r"\s+", " ", m.title or "").strip(), re.sub(r"[ \t]+", " ", m.body or "").strip()
    if required and (not title or not text):
        raise HTTPException(status_code=400, detail="Le titre et le message sont obligatoires.")
    if len(title) > TITLE_MAX:
        raise HTTPException(status_code=400, detail=f"Titre : {TITLE_MAX} caractères au maximum.")
    if len(text) > BODY_MAX:
        raise HTTPException(status_code=400, detail=f"Message : {BODY_MAX} caractères au maximum.")
    img = (m.image_url or "").strip() or None
    # FidClic's own ready images (public/automations/…) are allowed by their path
    from services import media as _M
    if img and not (_M.is_image_value(img) or img in READY_IMAGES):
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
        if button["link_type"] == "google_review" and sc != "google_review" \
                and not any(current_links(tid).values()):
            raise HTTPException(status_code=400, detail="Ajoutez d'abord votre lien Google (Insights › Avis Google).")
    return {"title": title, "body": text, "image_url": img, "button": button}


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
        tr["offer_days"] = _int(tr_in.get("offer_days", BIRTHDAY_OFFER_DAYS), 1, 60, "Durée de validité de l'offre")
    elif sc == "near_reward":
        if tr_in.get("threshold") is not None:                # the mockups' seuil
            tr.pop("visits_left", None)
            tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0}) or {}
            unit = reward_unit(tpl)
            label = {"points": "Seuil (points)", "tampons": "Seuil (tampons)"}.get(unit, "Seuil (€)")
            tr["threshold"] = _int(tr_in["threshold"], 1, 100000, label)
            from features import loyalty_card as LC
            prog = LC._programme(tpl)
            goal = int(tpl.get("reward_points") or 100) if prog in ("points_euro", "points_visit") else \
                (max(1, int(tpl.get("reward_threshold_stamps") or 10)) if prog == "stamps" else None)
            if goal and tr["threshold"] >= goal:
                raise HTTPException(status_code=400, detail=f"Le seuil doit être inférieur à la récompense de la carte ({goal} {unit}).")
        else:
            tr["visits_left"] = _int(tr_in.get("visits_left", 1), 1, 50, "Visites avant la récompense")
    elif sc == "inactive":
        tr["days"] = _int(tr_in.get("days", 30), 7, 365, "Jours sans visite")
        tr["repeat"] = "every" if tr_in.get("repeat") == "every" else "once"
        tr["every_days"] = _int(tr_in.get("every_days", 30), 7, 365, "Répéter tous les")
    elif sc == "referral":
        raw = tr_in.get("sides")
        if raw is None and tr_in.get("side") in SIDES:          # an older client
            raw = [tr_in["side"]]
        if not isinstance(raw, list) or any(x not in SIDES for x in raw):
            raise HTTPException(status_code=400, detail="Choisissez qui reçoit le message : parrain et/ou filleul.")
        tr.pop("side", None)
        tr["sides"] = [x for x in SIDES if x in raw]
        if not tr["sides"] and not draft:
            raise HTTPException(status_code=400, detail="Envoyez au moins un message : au parrain ou au filleul.")
    elif sc == "geo":
        tr["cooldown_days"] = _int(tr_in.get("cooldown_days", 7), 1, 90, "Délai entre deux messages")
        weather = tr_in.get("weather") or []
        if not isinstance(weather, list) or any(w not in GEO_WEATHER for w in weather):
            raise HTTPException(status_code=400, detail="Météo : valeur inconnue.")
        tr["weather"] = list(dict.fromkeys(weather))
        from features import geo_automation as GA
        spots = {a["id"]: a for a in GA.anchors(tid)}
        stores = [x for x in dict.fromkeys(tr_in.get("stores") or []) if x in spots]
        if len(spots) > 1 and tr_in.get("stores") and not stores:
            raise HTTPException(status_code=400, detail="Cochez au moins un établissement.")
        tr["stores"] = [] if len(stores) == len(spots) else stores
        if not draft and not any(spots[x]["lat"] is not None for x in (tr["stores"] or list(spots))):
            raise HTTPException(status_code=400, detail="La position de votre établissement est inconnue : placez-le sur la carte dans Paramètres › Établissement.")
        if tr_in.get("radius_m") not in (None, ""):
            tr["radius_m"] = _int(tr_in.get("radius_m"), 50, 2000, "Rayon de détection (m)")
    elif sc == "google_review":
        t = tr_in.get("type", "after_visit")
        if t not in GR_TYPES:
            raise HTTPException(status_code=400, detail="Choisissez quand demander l'avis.")
        f_in = "days" if tr_in.get("frequency") == "every_scan" else tr_in.get("frequency", "once")
        if f_in not in ("once", "days", "smart"):
            raise HTTPException(status_code=400, detail="Fréquence inconnue.")
        if f_in == "smart" and t == "date":
            raise HTTPException(status_code=400, detail="L'envoi intelligent suit chaque client après sa visite : pour une date, choisissez l'heure d'envoi.")
        tr.update(type=t, frequency=f_in, stop_after_click=True)
        tr["every_days"] = 1 if tr_in.get("frequency") == "every_scan" else \
            _int(tr_in.get("every_days", 30), 1, 365, "Répéter tous les (jours)")
        if t == "after_visit" and tr_in.get("delay_unit") == "minutes":
            raise HTTPException(status_code=400, detail="Délai après la visite : en heures ou en jours.")
        if t == "loyal":
            tr["visits"] = _int(tr_in.get("visits", 5), 1, 1000, "Nombre de visites")
        if t == "date":
            try:
                on = date.fromisoformat(str(tr_in.get("date") or "")[:10])
            except ValueError:
                raise HTTPException(status_code=400, detail="Choisissez la date d'envoi.")
            if not draft and on < _paris(_now()).date():
                raise HTTPException(status_code=400, detail="Cette date est déjà passée.")
            tr["date"] = on.isoformat()
            tr["date_mode"] = "once"
            tr["delay_value"] = 0
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
    elif sc == "custom" and tr_in.get("type") in CR_V2:
        from features import custom_rules as CR
        tr = CR.clean_trigger(tid, tr_in, draft, _paris(_now()).date())
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
    sides_on = (tr.get("sides") or []) if sc == "referral" else None
    message = clean_message(body.message, sc, tid, not draft and (sc != "referral" or "parrain" in sides_on),
                            "Parrain" if sc == "referral" else "")
    message_filleul = None
    if sc == "referral":
        mf = body.message_filleul or MessageIn(title=FILLEUL_DEFAULT["title"], body=FILLEUL_DEFAULT["body"])
        message_filleul = clean_message(mf, sc, tid, not draft and "filleul" in sides_on, "Filleul")
    t = body.targeting
    if t.mode not in TARGET_MODES:
        raise HTTPException(status_code=400, detail="Ciblage inconnu.")
    passants = t.passants or "all"
    if passants != "all" and passants not in PASSANTS:
        raise HTTPException(status_code=400, detail="Type de passants inconnu.")
    if t.mode == "segment" and not t.segment:
        raise HTTPException(status_code=400, detail="Choisissez un segment.")
    f = t.filters
    picked: Dict[str, List[str]] = {}
    for key, val, allowed, label in (("gender", f.gender, GENDERS, "Genre"), ("age", f.age, AGES, "Âge"),
                                     ("spent", f.spent, SPENT, "Montant total des achats"),
                                     ("last_visit", f.last_visit, LAST_VISIT, "Dernière visite"),
                                     ("client_type", f.client_type, CLIENT_TYPES, "Type de client"),
                                     ("past_freq", f.past_freq, PAST_FREQS, "Fréquence d'achat passée"),
                                     ("tiers", f.tiers, TIERS, "Programme de fidélité"),
                                     ("origin", f.origin, ORIGINS, "Origine du client"),
                                     ("last_offer", f.last_offer, LAST_OFFER, "Dernière offre reçue")):
        raw = [] if val in (None, "", "all") else (val if isinstance(val, list) else [val])
        if any(str(x) not in allowed for x in raw):
            raise HTTPException(status_code=400, detail=f"{label} : valeur inconnue.")
        picked[key] = as_list(raw, allowed)
    v2 = sc == "custom" and tr.get("type") in CR_V2
    PICKS = ("all", "active", "inactive", "points", "segment", "stores")
    pick = (t.pick if t.pick in PICKS else None) if v2 else None
    if v2 and pick is None:
        pick = {"segment": "segment"}.get(t.mode, "all")
    for key, lo, hi, label in (("points_min", 0, 10000000, "Nombre de points (minimum)"),
                               ("points_max", 0, 10000000, "Nombre de points (maximum)"),
                               ("spent_min", 0, 10000000, "Montant total d'achats (minimum)"),
                               ("spent_max", 0, 10000000, "Montant total d'achats (maximum)"),
                               ("last_visit_days", 1, 3650, "Date de dernière visite (jours)")):
        v = getattr(f, key)
        picked[key] = None if v in (None, "") else _int(v, lo, hi, label)
    for a_, b_, label in (("points_min", "points_max", "Nombre de points"), ("spent_min", "spent_max", "Montant total d'achats")):
        if picked[a_] is not None and picked[b_] is not None and picked[b_] < picked[a_]:
            raise HTTPException(status_code=400, detail=f"{label} : le maximum doit être au moins égal au minimum.")
    picked["last_visit_op"] = (f.last_visit_op if f.last_visit_op in ("more", "less") else "more") \
        if picked["last_visit_days"] is not None else None
    if pick == "inactive":
        picked["last_visit_op"], picked["last_visit_days"] = "more", _int(t.inactive_days if t.inactive_days not in (None, "") else 30, 1, 3650, "Clients inactifs depuis (jours)")
    if pick == "points" and picked["points_min"] is None and picked["points_max"] is None:
        raise HTTPException(status_code=400, detail="Indiquez le nombre de points des clients ciblés.")
    if pick == "stores" and not [x for x in f.stores or [] if x]:
        raise HTTPException(status_code=400, detail="Choisissez au moins un établissement.")
    nums: Dict[str, Optional[int]] = {}
    for key, lo, hi, label in (("visits_min", 0, 100000, "Nombre de visites (minimum)"),
                               ("visits_max", 0, 100000, "Nombre de visites (maximum)"),
                               ("age_min", 10, 100, "Âge (à partir de)"), ("age_max", 10, 100, "Âge (jusqu'à)")):
        v = getattr(f, key)
        nums[key] = None if v in (None, "") else _int(v, lo, hi, label)
    if nums["visits_min"] is not None and nums["visits_max"] is not None and nums["visits_max"] < nums["visits_min"]:
        raise HTTPException(status_code=400, detail="Nombre de visites : le maximum doit être au moins égal au minimum.")
    if nums["age_min"] is not None and nums["age_max"] is not None and nums["age_max"] < nums["age_min"]:
        raise HTTPException(status_code=400, detail="Âge : la fin doit être après le début.")
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
    acts = [] if f.activity in (None, "", "all") else (f.activity if isinstance(f.activity, list) else [f.activity])
    if pick == "active":                          # « Clients actifs uniquement »: the shop's active statuts
        from features import customer_rules as R
        acts = [x["key"] for x in R.statuses(R.load(tid)) if ACTIVITY_GROUPS.get(x["key"]) == "active"]
    if acts:
        from features import customer_rules as R
        allowed_acts = {x["key"] for x in R.statuses(R.load(tid))}
        if any(str(x) not in allowed_acts for x in acts):
            raise HTTPException(status_code=400, detail="Statut client : valeur inconnue.")
        acts = list(dict.fromkeys(str(x) for x in acts))
    signed = None
    if f.signed_since not in (None, ""):
        try:
            signed = date.fromisoformat(str(f.signed_since)[:10]).isoformat()
        except ValueError:
            raise HTTPException(status_code=400, detail="Inscription depuis : date invalide.")
    s = body.schedule
    if s.days not in DAY_MODES:
        raise HTTPException(status_code=400, detail="Jours d'envoi inconnus.")
    weekdays = sorted({_int(d, 0, 6, "Jour") for d in (s.weekdays or [])})
    if s.days == "specific" and not weekdays:
        raise HTTPException(status_code=400, detail="Cochez au moins un jour d'envoi.")
    day_mode = "all" if s.days == "specific" and len(weekdays) == 7 else s.days   # every day ticked = « Tous les jours »
    timed = is_timed(sc, tr)
    hour = None
    if timed:
        hh = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", (s.hour or "10:00").strip())
        if not hh:
            raise HTTPException(status_code=400, detail="Heure d'envoi invalide.")
        hour = hh.group(0)
    wf, wt = (s.window_from or "09:00").strip(), (s.window_to or "21:00").strip()
    hm = r"([01]\d|2[0-3]):([0-5]\d)"
    slots: List[Dict[str, str]] = []
    # Client inactif (mockups 2026-10-11): an hour (Déclencheur) AND a plage
    # horaire (Planification) — the hour sits inside the plage, which the
    # daily limit spreads the sends over
    windowed = bool(s.window) and (not timed or sc == "inactive")
    if timed and windowed:
        for v in (wf, wt):
            if not re.fullmatch(hm, v):
                raise HTTPException(status_code=400, detail="Plage horaire invalide.")
        if wt <= wf:
            raise HTTPException(status_code=400, detail="La fin de la plage horaire doit être après son début.")
        if not s.smart and not (wf <= hour < wt):
            raise HTTPException(status_code=400, detail=f"L'heure d'envoi ({hour}) doit être comprise dans la plage horaire ({wf} – {wt}).")
    limit = None
    if s.daily_limit not in (None, "", 0, "0", False):
        limit = _int(s.daily_limit, 1, DAILY_LIMIT_MAX, "Limite d'envoi par jour")
    if not timed and s.window:
        if s.slots:
            # « Plages horaires spécifiques » (géolocalisation): several, a night one may pass midnight
            if len(s.slots) > 6:
                raise HTTPException(status_code=400, detail="6 plages horaires au maximum.")
            for x in s.slots:
                a, b = str((x or {}).get("from") or "").strip(), str((x or {}).get("to") or "").strip()
                if not re.fullmatch(hm, a) or not re.fullmatch(hm, b):
                    raise HTTPException(status_code=400, detail="Plage horaire invalide.")
                if a == b:
                    raise HTTPException(status_code=400, detail="Une plage horaire commence et finit à la même heure.")
                if b < a and sc != "geo":
                    raise HTTPException(status_code=400, detail="La fin de la plage horaire doit être après son début.")
                if {"from": a, "to": b} not in slots:
                    slots.append({"from": a, "to": b})
            slots.sort(key=lambda x: x["from"])
            wf, wt = slots[0]["from"], slots[0]["to"]
        else:
            for v in (wf, wt):
                if not re.fullmatch(hm, v):
                    raise HTTPException(status_code=400, detail="Plage horaire invalide.")
            if wt <= wf:
                raise HTTPException(status_code=400, detail="La fin de la plage horaire doit être après son début.")
    valid: Dict[str, Optional[str]] = {}
    for key, label in (("valid_from", "Date de début"), ("valid_to", "Date de fin")):
        raw = (getattr(s, key) or "").strip()
        if not raw:
            valid[key] = None
            continue
        try:
            valid[key] = date.fromisoformat(raw[:10]).isoformat()
        except ValueError:
            raise HTTPException(status_code=400, detail=f"{label} invalide.")
    if valid["valid_from"] and valid["valid_to"] and valid["valid_to"] < valid["valid_from"]:
        raise HTTPException(status_code=400, detail="La date de fin doit être après la date de début.")
    if not draft and body.status == "active" and valid["valid_to"] and valid["valid_to"] < _paris(_now()).date().isoformat():
        raise HTTPException(status_code=400, detail="La date de fin est déjà passée : choisissez une nouvelle date pour l'activer.")
    raw_name = re.sub(r"\s+", " ", body.name or "").strip()
    if len(raw_name) > NAME_MAX:
        raise HTTPException(status_code=400, detail=f"Nom de l'automatisation : {NAME_MAX} caractères au maximum.")
    name = raw_name or SCENARIOS[sc]["label"]
    desc = "" if sc == "google_review" else re.sub(r"[ \t]+", " ", body.description or "").strip()
    if len(desc) > DESC_MAX:
        raise HTTPException(status_code=400, detail=f"Description : {DESC_MAX} caractères au maximum.")
    links = _clean_links(tid, body.google_links, draft) if sc == "google_review" else None
    out = {
        "scenario": sc, "name": name, "description": desc, "status": body.status, "trigger": tr,
        "message": message,
        "targeting": {"mode": t.mode, "segment": t.segment if t.mode == "segment" else None, "passants": passants,
                      "filters": ({"gender": [], "age": [], "spent": [], "last_visit": [], "client_type": [],
                                   "stores": [], "radius_km": None, "visits_min": None, "visits_max": None,
                                   "age_min": None, "age_max": None, "past_freq": [], "tiers": [], "origin": [],
                                   "last_offer": [], "activity": [], "signed_since": None} if t.mode == "all" else
                                  {**picked, **nums, "stores": stores, "radius_km": radius,
                                   "activity": acts, "signed_since": signed}),
                      "exclusions": {"recent_contact": bool(t.exclusions.recent_contact),
                                     "active_offer": bool(t.exclusions.active_offer)}},
        "schedule": {"days": day_mode, "weekdays": weekdays if day_mode == "specific" else [0, 1, 2, 3, 4, 5, 6],
                     "hour": hour, "smart": bool(s.smart) if timed else False,
                     "window": windowed, "daily_limit": limit,
                     "window_from": wf, "window_to": wt, "slots": slots,
                     "holidays": bool(s.holidays), **valid},
    }
    if v2:
        from features import custom_rules as CR
        today = _paris(_now()).date()
        out["schedule"] = CR.clean_schedule(body.schedule, tr, draft, body.status, today)
        fl = {**picked, **nums, "stores": stores, "radius_km": radius, "activity": acts, "signed_since": signed}
        has = any(v not in (None, [], "") for k, v in fl.items() if k != "last_visit_op")
        mode = "segment" if pick == "segment" else ("filtered" if pick != "all" or has else "all")
        out["targeting"] = {**out["targeting"], "mode": mode, "pick": pick,
                            "segment": t.segment if pick == "segment" else None,
                            "inactive_days": picked["last_visit_days"] if pick == "inactive" else None,
                            "filters": fl if mode != "all" else out["targeting"]["filters"]}
        rem = (tr.get("reminder") or {}).get("enabled") and tr.get("period") == "yearly"
        if rem:
            out["message_reminder"] = clean_message(body.message_reminder or MessageIn(title="", body=""), sc, tid,
                                                    not draft, "Rappel")
        else:
            out["message_reminder"] = clean_message(body.message_reminder, sc, tid, False, "Rappel") \
                if body.message_reminder else None
    if links is not None:
        out["google_links"] = links
    if message_filleul is not None:
        out["message_filleul"] = message_filleul
    # the trade's rules on the owner's words (pentest 2026-10-28): every title,
    # body and button of every side, reminder and palier — draft included
    from services import playbooks as PB
    broken = PB.owner_text_check(_db.tenants.find_one({"id": tid}, {"_id": 0, "sector": 1, "activity_key": 1}),
                                 out.get("name"), *_words(out))
    if broken:
        raise HTTPException(status_code=422, detail=broken)
    return out


def _words(x: Any) -> List[str]:
    """Every title / body / label typed in an automation, however deep."""
    if isinstance(x, dict):
        own = [v for k, v in x.items() if k in ("title", "body", "label") and isinstance(v, str)]
        return own + [w for v in x.values() for w in _words(v)]
    if isinstance(x, list):
        return [w for v in x for w in _words(v)]
    return []


def current_links(tid: str) -> Dict[str, str]:
    """The Google review links as the page shows them: {"main": url}, or one per établissement."""
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "google_review_url": 1, "branches": 1}) or {}
    branches = _branches(tid)
    if len(branches) > 1:
        return {b["id"]: b.get("google_review_url") or "" for b in branches}
    return {"main": t.get("google_review_url") or (branches[0].get("google_review_url") if branches else "") or ""}


def _clean_links(tid: str, raw: Any, draft: bool) -> Dict[str, str]:
    """1 établissement: the shop's link (the one in Insights › Avis Google).
    2+: each établissement's own link, all required (user, 2026-10-11)."""
    raw = raw if isinstance(raw, dict) else current_links(tid)
    branches = _branches(tid)
    spots = [(b["id"], b.get("name") or "Établissement") for b in branches] if len(branches) > 1 else [("main", None)]
    out: Dict[str, str] = {}
    for key, label in spots:
        v = str(raw.get(key) or "").strip()
        u = safe_url(v) if v else None
        if v and not u:
            raise HTTPException(status_code=400, detail=(f"Lien Google de « {label} » invalide." if label else
                                                         "Lien Google invalide : collez l'adresse de votre fiche, par exemple https://g.page/r/…/review."))
        if not u and not draft:
            raise HTTPException(status_code=400, detail=(f"Ajoutez le lien Google de « {label} »." if label else
                                                         "Ajoutez le lien vers votre fiche Google Avis."))
        if u:
            out[key] = u
    return out


def _save_links(tid: str, links: Optional[Dict[str, str]]) -> None:
    """The links live on the shop (and on each établissement): Insights shows
    the same; saving them switches the Google review requests on."""
    if not links:
        return
    for key, url in links.items():
        if key == "main":
            _db.tenants.update_one({"id": tid}, {"$set": {"google_review_url": url}})
        else:
            _db.tenants.update_one({"id": tid, "branches.id": key}, {"$set": {"branches.$.google_review_url": url}})
    _db.tenants.update_one({"id": tid}, {"$set": {"google_reviews_enabled": True}})


def _own(tid: str, aid: str) -> Dict[str, Any]:
    row = _db.automations.find_one({"tenant_id": tid, "id": aid}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="Automatisation introuvable.")
    return row


def _may(token: TokenData, page: str, level: str = "edit") -> bool:
    """« Modifier » on that page (Équipe & accès) — the owner always."""
    from features import role_perms as RP
    return RP.may(token, page, level)


def _guard(token: TokenData, row: Optional[Dict[str, Any]] = None) -> None:
    if token.role not in EDITORS and not _may(token, "automations"):
        raise HTTPException(status_code=403, detail="Seuls le propriétaire et les administrateurs modifient les automatisations.")
    if row and token.role != "business_owner":
        own = _own_stores(token)                   # None: every establishment
        if own is not None and not (row.get("store_ids") and set(row["store_ids"]) <= set(own)):
            raise HTTPException(status_code=403, detail="Cette automatisation concerne d'autres établissements.")


def _geo_saved(tid: str, data: Optional[Dict[str, Any]]) -> None:
    """A géolocalisation saved: the shop's one radius follows step 2
    (Paramètres › Établissement shows the same), and the passes follow."""
    if data and data.get("scenario") == "geo":
        r = (data.get("trigger") or {}).pop("radius_m", None)
        if r:
            _db.tenants.update_one({"id": tid}, {"$set": {"geo_radius_meters": int(r)}})


def _wake_geo(tid: str) -> None:
    try:
        from features import geo_automation as GA
        GA.sync_passes(tids=[tid])
    except Exception as exc:
        print(f"automations: geo passes not refreshed ({exc})")


@router.post("/api/owner/automations")
def create_automation(body: AutomationIn, request: Request = None,
                      token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True))):
    tid = token_data.tenant_id
    _guard(token_data)
    migrate(tid)
    data = clean(body, tid)
    if data["scenario"] == "geo":
        _geo_saved(tid, data)
    _save_links(tid, data.pop("google_links", None))
    doc = new_doc(tid, data["scenario"])
    doc.update(data)
    # the establishment chosen in the menu (multi-store PR5); else, as before
    menu = _menu_store(tid, token_data, request)
    doc["store_ids"] = [menu] if menu else _own_stores(token_data)
    doc["order"] = _db.automations.count_documents({"tenant_id": tid})
    doc["created_by"] = token_data.email
    _db.automations.insert_one(dict(doc))
    if doc["scenario"] == "geo":
        _wake_geo(tid)
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
    _save_links(tid, data.pop("google_links", None))
    if data["scenario"] == "geo":
        r = (data.get("trigger") or {}).pop("radius_m", None)
        if r:
            _db.tenants.update_one({"id": tid}, {"$set": {"geo_radius_meters": int(r)}})
    data["updated_at"] = _now()
    _db.automations.update_one({"id": aid}, {"$set": data})
    if data["status"] != "active":
        _db.automation_queue.delete_many({"automation_id": aid})
    if data["scenario"] == "geo":
        _wake_geo(tid)
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
        if ended(row):
            raise HTTPException(status_code=400, detail="Sa période de validité est terminée : modifiez la date de fin pour la réactiver.")
        # a draft is checked as a whole before it may run
        clean(AutomationIn(**{**row, "status": "active", "google_links": current_links(tid)}), tid)
    _db.automations.update_one({"id": aid}, {"$set": {"status": body.status, "updated_at": _now()}})
    if body.status != "active":
        _db.automation_queue.delete_many({"automation_id": aid})
    if row["scenario"] == "geo":
        _wake_geo(tid)
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
    if row["scenario"] == "geo":
        _wake_geo(tid)
    return {"deleted": aid}


class IdeaIn(BaseModel):
    objective: str


# what the owner's words point to — the editor opens on that scenario
_HINTS = [
    ("birthday", ("anniversaire", "birthday")),
    ("google_review", ("avis", "google", "note", "review")),
    ("referral", ("parrain", "filleul", "ami", "recommand")),
    ("welcome", ("bienvenue", "inscri", "nouveau client", "nouveaux clients", "wallet", "ajout de la carte")),
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
    from services import playbooks as PB
    play = PB.of(tenant)
    user = (f"Commerce : {tenant.get('name') or 'un commerce'}. "
            f"Message automatique de fidélité. Objectif : {objective}. "
            "Tu peux utiliser {prénom} pour le prénom du client et {nom_commerce} pour le commerce. "
            f"{PB.prompt_context(play, PB.paris_month())}")
    try:                                          # « Ce que FidClic IA retient » (2026-10-30)
        from features import copilot_memory as CM
        said = CM.memory_block(token_data.tenant_id, getattr(token_data, "email", None))
        if said:
            user += "\n" + said
    except Exception as exc:
        print(f"automations: memory unavailable ({exc})")
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
    broken = PB.breaks_rules(play, f"{title} {message}")      # loi Évin, no CBD health claim
    if broken:
        raise HTTPException(status_code=503, detail=broken)
    return {"title": title[:TITLE_MAX], "body": message[:BODY_MAX], "scenario": suggest(objective),
            "scenario_label": SCENARIOS[suggest(objective)]["label"]}


class PreviewIn(BaseModel):
    scenario: str
    targeting: TargetingIn = TargetingIn()
    trigger: Dict[str, Any] = {}          # Client inactif: its « X jours »
    full: bool = False                    # Nouvelle automatisation: « Voir la liste »


AGE_BARS = (("18-25", 18, 25), ("26-35", 26, 35), ("36-50", 36, 50), ("50+", 51, 200))


def _last_seen(c: Dict[str, Any]) -> Optional[datetime]:
    return _aware(c.get("last_visit_date")) or _aware(c.get("created_at"))


def _reactivation(tid: str, at: datetime) -> Optional[Dict[str, Any]]:
    """How often a Client inactif message brought the client back within
    IMPACT_WINDOW_DAYS: this shop's own sends first (from IMPACT_MIN_SENDS),
    else its sector's, pooled and anonymous (from IMPACT_MIN_SHOPS shops) —
    else nothing: no number is made up."""
    def measure(tids: List[str]) -> Tuple[int, int, int]:
        n = came = 0
        shops = set()
        cutoff = at - timedelta(days=IMPACT_WINDOW_DAYS)
        for lg in _db.automation_log.find({"tenant_id": {"$in": tids}, "scenario": "inactive",
                                           "status": {"$nin": ["deferred", "holdout"]}, "sent_at": {"$lte": cutoff}},
                                          {"_id": 0, "tenant_id": 1, "customer_id": 1, "sent_at": 1}):
            sent = _aware(lg.get("sent_at"))
            if not sent:
                continue
            n += 1
            shops.add(lg["tenant_id"])
            if _db.visits.find_one({"tenant_id": lg["tenant_id"], "customer_id": lg["customer_id"],
                                    "visit_time": {"$gt": sent, "$lte": sent + timedelta(days=IMPACT_WINDOW_DAYS)}}):
                came += 1
        return n, came, len(shops)
    n, came, _ = measure([tid])
    if n >= IMPACT_MIN_SENDS:
        return {"rate": round(came / n, 4), "basis": "shop", "sends": n}
    sector = (_db.tenants.find_one({"id": tid}, {"_id": 0, "sector": 1}) or {}).get("sector")
    if sector:
        peers = [t["id"] for t in _db.tenants.find({"sector": sector, "id": {"$ne": tid}}, {"_id": 0, "id": 1})]
        if peers:
            n, came, shops = measure(peers)
            if shops >= IMPACT_MIN_SHOPS and n >= IMPACT_MIN_SENDS:
                return {"rate": round(came / n, 4), "basis": "sector", "sends": n}
    return None


# the 4 boxes of « Répartition estimée » over the shop's own statuses (user, 2026-10-11)
ACTIVITY_GROUPS = {"actif": "active", "regulier": "active", "fidele": "active", "vip": "active",
                   "bientot_perdu": "risk", "dormant": "inactive", "inactif": "inactive", "nouveau": "new"}


def near_insights(tid: str, row: Dict[str, Any], at: datetime) -> Dict[str, Any]:
    """Récompense bientôt disponible's right panels, real data only: the
    clients within the seuil of their nearest reward now (and a month ago,
    from the points / visits on record), and their statuts in four boxes."""
    from features import clients_page as CPg
    from features import customer_rules as R
    tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0}) or {}
    tr = row.get("trigger") or {}
    seuil = max(1, min(100000, int(tr.get("threshold") or 10)))
    own = _store_people(tid, row["store_ids"]) if row.get("store_ids") else None
    people = [c for c in _db.customers.find({"tenant_id": tid, "deleted_at": None}, {"_id": 0})
              if own is None or c["id"] in own]
    cache: Dict[str, Any] = {}

    def within(c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        hit = nearest_reward(tid, c, tpl)
        return hit if hit and 0 < hit["remaining"] <= seuil else None
    now_in = [c for c in people if within(c) and matches(tid, row, c, at, cache)]
    # a month ago: points / visits then = now minus what came since; a client
    # who redeemed since is left out of that count (their balance then is unknown)
    then = at - timedelta(days=30)
    since_pts: Dict[str, int] = {}
    since_vis: Dict[str, int] = {}
    for v in _db.visits.find({"tenant_id": tid, "visit_time": {"$gte": then}}, {"_id": 0, "customer_id": 1, "points_awarded": 1}):
        since_pts[v["customer_id"]] = since_pts.get(v["customer_id"], 0) + int(v.get("points_awarded") or 0)
        since_vis[v["customer_id"]] = since_vis.get(v["customer_id"], 0) + 1
    redeemed = set(_db.rewards_redeemed.distinct("customer_id", {"tenant_id": tid, "redeemed_at": {"$gte": then}}))
    was = 0
    for c in people:
        joined = _aware(c.get("created_at"))
        if c["id"] in redeemed or not joined or joined > then:
            continue
        past = {**c, "points": int(c.get("points") or 0) - since_pts.get(c["id"], 0),
                "visits": int(c.get("visits") or 0) - since_vis.get(c["id"], 0)}
        if within(past):
            was += 1
    rules = R.load(tid)
    boxes = {"active": 0, "risk": 0, "inactive": 0, "new": 0, "other": 0}
    for c in now_in:
        boxes[ACTIVITY_GROUPS.get(CPg.status_of(c, at, rules), "other")] += 1
    n = len(now_in)
    pct = lambda k: round(boxes[k] / n * 100) if n else 0  # noqa: E731
    return {"threshold": seuil, "unit": reward_unit(tpl), "count": n, "month_ago": was,
            "delta": (round((n - was) / was * 100) if was else None),
            "groups": [{"key": k, "n": boxes[k], "pct": pct(k)} for k in ("active", "risk", "inactive", "new", "other")]}


def inactive_insights(tid: str, row: Dict[str, Any], at: datetime) -> Dict[str, Any]:
    """The Client inactif editor's right panels, from real data only:
    « Estimation de l'audience » (now, and a month ago), the inactive clients
    the filters / exclusions leave out, « Répartition de l'audience » and
    « Estimation de l'impact »."""
    from services import customer_fields as CF
    days = max(7, min(365, int(((row.get("trigger") or {}).get("days")) or 30)))
    cache: Dict[str, Any] = {}
    own = None
    if row.get("store_ids"):
        own = _store_people(tid, row["store_ids"]) or set()
    people = [c for c in _db.customers.find({"tenant_id": tid, "deleted_at": None}, {"_id": 0})
              if own is None or c["id"] in own]
    cutoff = at - timedelta(days=days)
    lapsed = [c for c in people if (_last_seen(c) or at) <= cutoff]
    targeted = [c for c in lapsed if matches(tid, row, c, at, cache)]
    # a month ago: each client's last visit BEFORE that day, from the visits
    then = at - timedelta(days=30)
    before: Dict[str, datetime] = {}
    for v in _db.visits.find({"tenant_id": tid, "visit_time": {"$lt": then}}, {"_id": 0, "customer_id": 1, "visit_time": 1}):
        t = _aware(v.get("visit_time"))
        if t and (v["customer_id"] not in before or t > before[v["customer_id"]]):
            before[v["customer_id"]] = t
    was = 0
    for c in people:
        joined = _aware(c.get("created_at"))
        if not joined or joined > then:
            continue                               # not a client yet
        seen = before.get(c["id"]) or joined
        if seen <= then - timedelta(days=days) and matches(tid, row, c, then, {}):
            was += 1
    count = len(targeted)
    ages: Dict[str, int] = {k: 0 for k, _, _ in AGE_BARS}
    genders = {"F": 0, "M": 0}
    channels = {"store": 0, "online": 0, "other": 0}
    for c in targeted:
        a = CF.age_of(c.get("birth_date"))
        for k, lo, hi in AGE_BARS:
            if a is not None and lo <= a <= hi:
                ages[k] += 1
        if c.get("gender") in genders:
            genders[c["gender"]] += 1
        channels[CHANNEL_GROUPS.get(origin_of(c), "online")] += 1
    pct = lambda n, d: round(n / d * 100) if d else 0  # noqa: E731
    known_age, known_g = sum(ages.values()), sum(genders.values())
    rate = _reactivation(tid, at)
    paid = sum(float(c.get("total_amount_paid") or 0) for c in targeted)
    visits = sum(int(c.get("visits") or 0) for c in targeted)
    basket = (paid / visits) if visits and paid else None
    back = round(count * rate["rate"]) if rate else None
    return {
        "days": days, "count": count, "lapsed": len(lapsed), "excluded": len(lapsed) - count,
        "month_ago": was, "delta": (round((count - was) / was * 100) if was else None),
        "cutoff": cutoff.date().isoformat(),
        "breakdown": {"age": [{"key": k, "n": n, "pct": pct(n, known_age)} for k, n in ages.items()],
                      "gender": [{"key": k, "n": n, "pct": pct(n, known_g)} for k, n in genders.items()],
                      "channel": [{"key": k, "n": n, "pct": pct(n, count)} for k, n in channels.items()]},
        "impact": {"rate": rate["rate"] if rate else None, "basis": rate["basis"] if rate else None,
                   "sends": rate["sends"] if rate else 0, "reactivated": back,
                   "basket": round(basket, 2) if basket else None,
                   "revenue": round(back * basket) if back is not None and basket else None},
    }


def pick_targeting(tid: str, tg: Dict[str, Any]) -> Dict[str, Any]:
    """Nouvelle automatisation › Ciblage: the chosen card as filters (as clean() saves it)."""
    pick = tg.get("pick") or "all"
    f = dict(tg.get("filters") or {})
    if pick == "active":
        from features import customer_rules as R
        f["activity"] = [x["key"] for x in R.statuses(R.load(tid)) if ACTIVITY_GROUPS.get(x["key"]) == "active"]
    if pick == "inactive":
        f["last_visit_op"], f["last_visit_days"] = "more", int(tg.get("inactive_days") or 30)
    has = any(v not in (None, [], "") for k, v in f.items() if k != "last_visit_op")
    mode = "segment" if pick == "segment" else ("filtered" if pick != "all" or has else "all")
    return {**tg, "mode": mode, "filters": f}


@router.post("/api/owner/automations/preview")
def preview(body: PreviewIn, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    """Step 4's count, and a real client to fill the preview's variables."""
    tid = token_data.tenant_id
    if body.scenario not in SCENARIOS:
        raise HTTPException(status_code=400, detail="Scénario inconnu.")
    tg = body.targeting.model_dump()
    if body.scenario == "custom" and tg.get("pick"):
        tg = pick_targeting(tid, tg)              # Nouvelle automatisation: the card chosen → its filters
    row = {"id": "preview", "scenario": body.scenario, "store_ids": _own_stores(token_data),
           "targeting": tg, "trigger": body.trigger or {}}
    at = _now()
    cache: Dict[str, Any] = {}
    people = [c for c in _db.customers.find({"tenant_id": tid}, {"_id": 0}) if matches(tid, row, c, at, cache)]
    # « Clients joignables »: targeted AND reachable — a Wallet card (lock
    # screen) or notifications switched on (web push)
    subs = set(_db.push_subscriptions.distinct("customer_id", {"tenant_id": tid}))
    wallet = sum(1 for c in people if _has_wallet(c))
    push = sum(1 for c in people if c["id"] in subs)
    either = sum(1 for c in people if c["id"] in subs or _has_wallet(c))
    sample = None
    if people:
        c = people[0]
        tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "reward_description": 1}) or {}
        sample = {"first_name": (c.get("name") or "").split(" ")[0] or "Sarah", "name": c.get("name") or "",
                  "points": int(c.get("points") or 0),
                  "visits": int(c.get("visits") or 0), "next_reward": tpl.get("reward_description") or "votre récompense"}
    out = {"count": len(people), "sample": sample, "reachable": {"total": either, "wallet": wallet, "push": push}}
    if body.scenario == "custom":
        # « Aperçu du ciblage »: out of how many, three real clients, and the list
        out["total"] = _db.customers.count_documents({"tenant_id": tid, "deleted_at": None})
        def brief(c):
            lv = _aware(c.get("last_visit_date"))
            return {"id": c["id"], "name": c.get("name") or "", "points": int(c.get("points") or 0),
                    "last_visit": _paris(lv).date().isoformat() if lv else None}
        ordered = sorted(people, key=lambda c: _aware(c.get("last_visit_date")) or datetime.min.replace(tzinfo=timezone.utc),
                         reverse=True)
        out["examples"] = [brief(c) for c in ordered[:3]]
        if body.full:
            out["list"] = [brief(c) for c in ordered[:500]]
    if body.scenario == "inactive":
        out["inactive"] = inactive_insights(tid, row, at)
    if body.scenario == "near_reward":
        out["near"] = near_insights(tid, row, at)
    return out


# ---------------------------------------------------------------------------
# Nouvelle automatisation: the address search (Géolocalisation) and the till's
# « Offre utilisée » (Après une action client › Utilisation d'une offre)
# ---------------------------------------------------------------------------
@router.get("/api/owner/automations/address-search")
def address_search(q: str = "", token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True))):
    """« Adresse ou établissement »: the shop's own establishments first, then
    any address (Base Adresse Nationale / Photon)."""
    tid = token_data.tenant_id
    q = (q or "").strip()
    out: List[Dict[str, Any]] = []
    from features import geo_automation as GA
    fold = lambda x: re.sub(r"\s+", " ", (x or "").lower())  # noqa: E731
    for a in GA.anchors(tid):
        if a.get("lat") is None:
            continue
        label = " – ".join(x for x in (a.get("name"), a.get("address")) if x)
        if not q or fold(q) in fold(label):
            out.append({"kind": "store", "label": label, "lat": a["lat"], "lng": a["lng"], "id": a.get("id")})
    if len(q) >= 3:
        try:
            from services import addresses
            t = _db.tenants.find_one({"id": tid}, {"_id": 0, "country": 1}) or {}
            for r in addresses.search(q, t.get("country") or "FR", "address", 6):
                if r.get("lat") is not None:
                    out.append({"kind": "address", "label": r["label"], "lat": r["lat"], "lng": r["lng"]})
        except Exception as exc:              # noqa: BLE001 — a geocoder outage is a message
            if not out:
                print(f"automations: address search failed ({exc})")
                raise HTTPException(status_code=503, detail="La recherche d'adresse est momentanément indisponible. Réessayez dans un instant.")
    return {"results": out[:10]}


class OfferUseIn(BaseModel):
    customer_id: str
    branch_id: Optional[str] = None


@router.post("/api/owner/offers/{campaign_id}/use")
def use_offer(campaign_id: str, body: OfferUseIn,
              token_data: TokenData = Depends(require_role(["business_owner", "administrateur", "manager", "staff"]))):
    """The till: the client used this offer now (once per offer and client)."""
    tid = token_data.tenant_id
    cust = _db.customers.find_one({"id": body.customer_id, "tenant_id": tid, "deleted_at": None}, {"_id": 0})
    if not cust:
        raise HTTPException(status_code=404, detail="Client introuvable.")
    offer = _db.campaigns.find_one({"id": campaign_id, "tenant_id": tid}, {"_id": 0})
    if not offer:
        raise HTTPException(status_code=404, detail="Offre introuvable.")
    try:
        from features import campaign_kinds as K
        live = offer.get("status") == "sent" and offer.get("kind") in K.OFFER_KINDS and \
            cust["id"] in (offer.get("recipient_ids") or []) and K.active_now(offer, _now())
    except Exception:
        live = False
    if not live:
        raise HTTPException(status_code=400, detail="Cette offre n'est pas valable pour ce client en ce moment.")
    from features import custom_rules as CR
    return {"ok": True, "use": CR.offer_used(tid, cust, offer, getattr(token_data, "email", None), body.branch_id)}
