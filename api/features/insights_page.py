"""
Insights — « Faites grandir votre commerce ».

Built to the approved mockup. One request fills the page: the trend, the
month's goal, and four shelves of advice — opportunités, actions de la
semaine, idées de campagnes, conseils.

PERSONALISED, NOT PAINTED
    Every shelf is drawn from a library larger than what is shown, and each
    item earns its place on this shop's own data and sector:

      · an item a shop cannot use is never offered — a spa is not told to run
        a Happy Hour on drinks, a café is not told about "prestations";
      · an item already done drops to the back — once the birthday offer is
        running, the page stops asking the merchant to switch it on;
      · the rest is ranked by what it is worth to THIS shop, and the shelf
        keeps its mix (one "ventes", one "fidélisation", one "acquisition")
        rather than showing three variations of the same advice.

    "Voir toutes" shows the whole eligible library, done items included.

"IMPACT ESTIMÉ" — TWO KINDS, AND THE PAGE SAYS WHICH
    Computed, wherever the data allows. A segment's worth uses the same model
    the Segmentation page uses — each client's own average basket times a
    conversion probability read from their recency — but as a RANGE, with the
    merchant's own bounds:

          seen within 30 days   25 – 35 %
          30 – 60 days          15 – 20 %
          60 – 90 days          10 – 15 %
          over 90, or never      5 – 10 %

    expressed against the last 30 days of revenue. That is how "+8 à 15 %
    de CA" is reached for the inactive clients of THIS shop.

    Where nothing in the data can support a figure, a figure is shown only if
    it has a real source — the shop's playbook (services/playbooks.py) names
    it, its year and its link (« source »). Otherwise the item is advice with
    no number (« conseil »). The old « estimation courante du secteur »
    percentages are gone (user, 2026-10-26: only sourced numbers).

PER ACTIVITY
    The words (produits / prestations / séances), the offers, what fits (a
    Happy Hour only where drinks are sold, a menu du jour only where meals
    are), the trade's own advice and its key moments all come from the
    shop's playbook — one per « Activité précise ».

NOTHING HERE SENDS ANYTHING
    Buttons either navigate, pre-fill the campaign composer, or switch on an
    automation the merchant can see and switch off on its own page. The one
    exception is "Collectez plus d'avis clients", which needs the shop's Google
    review link and is therefore its own small flow.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from auth import require_role
from features import store_scope as S
from services import playbooks as PB

# Insights are read by the owner, administrateurs and managers — each on the
# establishments it may see (features/store_scope.py).
READERS = ["business_owner", "administrateur", "manager"]
from models import TokenData

router = APIRouter(tags=["insights"])
_db = None

# Conversion RANGES by recency — the merchant's own bounds. Segmentation uses
# the midpoint of each; here the page shows the range itself.
P_RANGE: List[Tuple[Optional[int], Tuple[float, float]]] = [
    (30, (0.25, 0.35)),
    (60, (0.15, 0.20)),
    (90, (0.10, 0.15)),
    (None, (0.05, 0.10)),
]

SATISFIED_AT = 8        # a review at or above this, out of ten, is a happy client
LOCAL_KM = 2.0          # "à moins de 2 km"
NEW_DAYS = 30
INACTIVE_DAYS = 30

CATEGORIES = {
    "ventes":        {"label": "Ventes",        "tone": "green"},
    "fidelisation":  {"label": "Fidélisation",  "tone": "blue"},
    "acquisition":   {"label": "Acquisition",   "tone": "violet"},
    "automne":       {"label": "Automne",       "tone": "amber"},
    "evenement":     {"label": "Événement",     "tone": "rose"},
    "hiver":         {"label": "Hiver",         "tone": "blue"},
    "printemps":     {"label": "Printemps",     "tone": "green"},
    "ete":           {"label": "Été",           "tone": "amber"},
}

def init(db):
    global _db
    _db = db
    try:
        db.google_review_clicks.create_index([("tenant_id", 1), ("at", -1)])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _money(n: float) -> float:
    return round(n + 1e-9, 2)


def _fr(n: float, digits: int = 1) -> str:
    """1.8 → "1,8" — the page is French, so is its decimal comma."""
    s = f"{n:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{round(n)}"
    return s.replace(".", ",")


def _eur_cents(n: float) -> str:
    """15,50 € — money keeps its cents (QA: « 15,5 € »); a whole amount has none."""
    n = round(float(n or 0) + 1e-9, 2)
    s = f"{n:,.0f}" if n == int(n) else f"{n:,.2f}"
    return s.replace(",", " ").replace(".", ",") + " €"


def _category(key: str) -> Dict[str, str]:
    return {"key": key, **CATEGORIES[key]}


# ---------------------------------------------------------------------------
# What a group of clients is worth — as a range
# ---------------------------------------------------------------------------
def _avg_basket(cust: Dict[str, Any]) -> Optional[float]:
    visits = int(_num(cust.get("visits")))
    return _num(cust.get("total_amount_paid")) / visits if visits > 0 else None


def _p_range(cust: Dict[str, Any], at: datetime) -> Tuple[float, float]:
    last = _aware(cust.get("last_visit_date"))
    if not last:
        return P_RANGE[-1][1]
    days = (at - last).total_seconds() / 86400.0
    for limit, rng in P_RANGE:
        if limit is None or days < limit:
            return rng
    return P_RANGE[-1][1]


def _worth(people: List[Dict[str, Any]], shop_avg: float, at: datetime) -> Tuple[float, float]:
    lo = hi = 0.0
    for c in people:
        basket = _avg_basket(c)
        if basket is None:
            basket = shop_avg
        p_lo, p_hi = _p_range(c, at)
        lo += basket * p_lo
        hi += basket * p_hi
    return lo, hi


def _eur(n: float) -> str:
    return f"{round(n):,}".replace(",", " ")


def _eur_range(lo: float, hi: float) -> str:
    a, b = round(lo), round(hi)
    return f"+{_eur(a)} € de CA" if a == b else f"+{_eur(a)} à {_eur(b)} € de CA"


def _computed(lo: float, hi: float, monthly: float, basis: str) -> Optional[Dict[str, Any]]:
    """A range, in euros — a merchant reads "+180 à 290 €" at a glance, and
    has to do arithmetic on "+7 à 11 % de CA"."""
    if hi < 0.5:
        return None
    return {"label": _eur_range(lo, hi), "basis": basis, "kind": "calcule",
            "euros": [_money(lo), _money(hi)]}


def _figure(shop: "Shop", key: str, lever: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """No computed figure: the playbook's sourced one, else advice only.

    `key` is the engine's own advice (« avis_google », « parrainage »…) or, for
    a playbook lever, the lever itself names its figure.
    """
    fact = PB.fact_of(shop.play, lever) if lever else shop.play["facts"].get(
        shop.play["generic_facts"].get(key, ""))
    if fact:
        return {"label": fact["short"], "kind": "source", "euros": None,
                "basis": f"{fact['source']} ({fact['year']})", "url": fact["url"], "text": fact["text"]}
    return {"label": "Non chiffré", "kind": "conseil", "euros": None,
            "basis": "Conseil : aucun chiffre sourcé pour votre activité"}


# ---------------------------------------------------------------------------
# What has been used — so it can make way
# ---------------------------------------------------------------------------
USED_DAYS = 14          # a recommendation used within this window steps aside

MONTHS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.",
             "nov.", "déc."]


def used_templates(tid: str, at: datetime, days: int = USED_DAYS,
                   scope: Optional["S.Scope"] = None) -> Dict[str, Dict[str, Any]]:
    """Recommendations turned into a campaign in the last `days` days.

    Every campaign created from a recommendation carries its `template` key.
    Once one is sent or scheduled, the recommendation is done for a while:
    it drops to the back of its shelf, reads "Envoyée le …", and the next one
    takes its place. After the window it may come back — if the data still
    calls for it.
    """
    out: Dict[str, Dict[str, Any]] = {}
    cut = at - timedelta(days=days)
    for c in _db.campaigns.find({"tenant_id": tid, "template": {"$ne": None},
                                 "status": {"$in": ["sent", "scheduled", "sending"]}},
                                {"_id": 0, "template": 1, "status": 1, "sent_at": 1,
                                 "scheduled_for": 1, "created_at": 1, "store_ids": 1}):
        when = _aware(c.get("sent_at")) or _aware(c.get("scheduled_for")) or _aware(c.get("created_at"))
        if not when or when < cut or not c.get("template"):
            continue
        # For an establishment's view, a campaign sent for other
        # establishments has not used this recommendation here.
        if scope is not None and not scope.is_all and c.get("store_ids") \
                and not set(c["store_ids"]) & set(scope.ids):
            continue
        prev = out.get(c["template"])
        if not prev or when > prev["at"]:
            out[c["template"]] = {"at": when, "status": c.get("status")}
    return out


def _used_label(u: Dict[str, Any]) -> str:
    d = u["at"]
    verb = "Programmée" if u["status"] in ("scheduled", "sending") else "Envoyée"
    return f"{verb} le {d.day} {MONTHS_FR[d.month - 1]}"


def _mark_used(items: List[Dict[str, Any]], used: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    for i in items:
        cta = i.get("cta") or {}
        u = used.get(cta.get("template")) if cta.get("kind") == "template" else None
        if u:
            i["done"] = True
            i["cta"] = {**cta, "done_label": _used_label(u)}
    return items


# ---------------------------------------------------------------------------
# One read of the shop
# ---------------------------------------------------------------------------
class Shop:
    """Everything the page reasons over, read once."""

    def __init__(self, tid: str, at: datetime, scope: Optional["S.Scope"] = None):
        self.tid, self.at = tid, at
        # Limited to the chosen establishments when a scope is given
        # (features/store_scope.py); the whole shop otherwise.
        self.scope = scope
        self.mine = S.customer_ids(scope) if scope else None
        self.tenant = _db.tenants.find_one({"id": tid}) or {}
        sector = str(self.tenant.get("sector") or "").lower().strip()
        self.sector = sector or None
        # The shop's playbook (services/playbooks.py): its words, what fits,
        # its own advice. « boulangerie », « café » are food shops (the old
        # FOOD_SECTORS test read them as salons).
        self.play = PB.of(self.tenant)
        self.food, self.drinks, self.meals = self.play["food"], self.play["drinks"], self.play["meals"]
        if not sector and not self.tenant.get("activity_key"):
            # No sector on file reads as the platform's core audience rather
            # than as "other": FidClic is built for cafés and restaurants first.
            self.food = self.drinks = self.meals = True
            self.play["offer"] = "1 boisson offerte"
        self.sells_products = self.play["items"][0] == "produit"
        self.people = list(_db.customers.find(S.customer_filter(scope) if scope else {"tenant_id": tid, "deleted_at": None},
                                              {"_id": 0}))
        # The periods the page reasons over, added up from the register of
        # past days — today and the cut ends live (features/visit_days): no
        # visit read whole, none judged for CA FidClic (not shown here). A
        # visit dated after `at` is in none of them.
        from features import visit_days as VD
        start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_start = (start - timedelta(days=1)).replace(day=1)
        tick = timedelta(microseconds=1)
        spans = {"d15": (at - timedelta(days=15), at), "p15": (at - timedelta(days=30), at - timedelta(days=15) - tick),
                 "d30": (at - timedelta(days=30), at), "d56": (at - timedelta(days=56), at),
                 "d90": (at - timedelta(days=90), at),
                 "month": (start, at), "prev_month": (prev_start, prev_start + (at - start))}
        self.tot = dict(zip(spans, VD.span_many(tid, scope, list(spans.values()), at, judge=False)))
        # « Panier moyen » = what was spent ÷ the visits, as on Analyses (QA
        # F15: an average of each client's average said 15,56 € where
        # Analyses said 13,30 €): the last 30 days, else the whole history.
        month = self.tot["d30"]
        if month.n:
            self.shop_avg = month.revenue / month.n
            self.shop_avg_window = 30
        else:
            n = sum(int(_num(c.get("visits"))) for c in self.people)
            self.shop_avg = (sum(_num(c.get("total_amount_paid")) for c in self.people) / n) if n else 0.0
            self.shop_avg_window = None
        self.monthly = month.revenue
        self._visits = None
        self.reviews = [r for r in _db.reviews.find({"tenant_id": tid}, {"_id": 0, "rating": 1,
                                                                          "customer_id": 1})
                        if self.mine is None or r.get("customer_id") in self.mine]
        self.signups_30 = len([c for c in self.people
                               if (d := _aware(c.get("created_at"))) and (at - d).days <= 30])
        self.used = used_templates(tid, at, scope=scope)

    # -- the visits themselves, read only when something asks -------------
    # (the page's own figures come from `tot`)
    @property
    def visits(self) -> List[Dict[str, Any]]:
        if self._visits is None:
            self._visits = list(_db.visits.find(
                {"tenant_id": self.tid, "visit_time": {"$gte": self.at - timedelta(days=152)},
                 **(S.visit_filter(self.scope) if self.scope else {})},
                {"_id": 0, "amount_paid": 1, "visit_time": 1, "items": 1, "customer_id": 1}))
        return self._visits

    def recent(self, days: int = 90) -> List[Dict[str, Any]]:
        cut = self.at - timedelta(days=days)
        return [v for v in self.visits if (t := _aware(v.get("visit_time"))) and t >= cut]


# ---------------------------------------------------------------------------
# The hero and the goal
# ---------------------------------------------------------------------------
def _hero(shop: Shop) -> Dict[str, Any]:
    """Month to date against the SAME number of days of last month.

    Comparing a 26-day September with a 31-day August would call every month
    a decline until its last day. And the headline never claims progress that
    is not there: a falling month is called a falling month.
    """
    now, was = shop.tot["month"].revenue, shop.tot["prev_month"].revenue
    if was <= 0:
        return {"direction": "start", "pct": None,
                "title": "Votre activité démarre",
                "text": "Suivez nos recommandations pour lancer la dynamique.",
                "revenue": _money(now)}
    pct = round((now - was) / was * 100)
    if pct >= 0:
        return {"direction": "up", "pct": pct,
                "title": "Votre activité est en progression !",
                "chip": f"+{pct}%", "chip_text": "de chiffre d'affaires ce mois-ci",
                "text": "Continuez sur cette lancée avec nos recommandations. 🚀",
                "revenue": _money(now)}
    return {"direction": "down", "pct": pct,
            "title": "Votre activité ralentit ce mois-ci",
            "chip": f"{pct}%", "chip_text": "de chiffre d'affaires ce mois-ci",
            "text": "Nos recommandations ci-dessous peuvent vous aider à relancer la dynamique.",
            "revenue": _money(now)}


def _goal(shop: Shop) -> Dict[str, Any]:
    """The same monthly goal the Tableau de bord and Segmentation track — the
    shop's, or the chosen establishments' own (dashboard_home.goal_target)."""
    if shop.scope is not None and not shop.scope.is_all:
        from features import dashboard_home as DH
        target = DH.goal_target(shop.tenant, shop.scope)
    else:
        target = _num(shop.tenant.get("monthly_revenue_goal"))
    made = shop.tot["month"].revenue
    return {"target": _money(target), "reached": _money(made),
            "remaining": _money(max(0.0, target - made)),
            "pct": round(min(100, made / target * 100)) if target else None,
            "is_set": target > 0}


# ---------------------------------------------------------------------------
# Groups the advice reasons over
# ---------------------------------------------------------------------------
def _inactive(shop: Shop) -> List[Dict[str, Any]]:
    # Since the last visit — or the sign-up, for a client who hasn't come yet:
    # a client who joined yesterday is not « inactif » (clients_page.last_contact).
    from features import clients_page as CP
    cut = shop.at - timedelta(days=INACTIVE_DAYS)
    return [c for c in shop.people if not (d := CP.last_contact(c)) or d < cut]


def _one_timers(shop: Shop) -> List[Dict[str, Any]]:
    # One definition with the bell and the Clients list (clients_page).
    from features import clients_page as CP
    return [c for c in shop.people if CP.is_one_timer(c, shop.at)]


def _birthdays(shop: Shop, days: int = 30) -> List[Dict[str, Any]]:
    window = {(shop.at + timedelta(days=i)).strftime("%m-%d") for i in range(days)}
    return [c for c in shop.people if str(c.get("birthday") or "")[-5:] in window]


def _at_risk(shop: Shop) -> List[Dict[str, Any]]:
    """Regulars who have stopped coming — not the long-gone, the slipping.

    A regular is someone with at least 4 visits whose own rhythm is known:
    their average gap between visits. They are "at risk" once their silence
    is both longer than 45 days and more than twice their usual gap — a
    monthly customer silent for 45 days is not the same as a weekly one.
    One definition with the bell and the Clients list (clients_page).
    """
    from features import clients_page as CP
    return [c for c in shop.people if CP.is_at_risk(c, shop.at)]


def _students(shop: Shop) -> List[Dict[str, Any]]:
    """Clients who declared themselves students at signup."""
    return [c for c in shop.people if c.get("is_student")]


def _best_weekday(shop: Shop) -> Optional[Dict[str, Any]]:
    """The strongest day of the week and by how much, over eight weeks.

    Needs at least three weeks of that day to say anything.
    """
    tot = shop.tot["d56"]
    if tot.n < 20:
        return None
    # the shop's own calendar, not UTC's (QA F19)
    per_day, seen_dates = tot.by_weekday()
    avg = {d: per_day[d] / seen_dates[d] for d in per_day if seen_dates[d] >= 3}
    if len(avg) < 3:
        return None
    best = max(avg, key=avg.get)
    others = [v for d, v in avg.items() if d != best]
    mean = sum(others) / len(others)
    if mean <= 0:
        return None
    return {"weekday": best, "lift": round((avg[best] - mean) / mean * 100)}


WEEKDAY_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _locals(shop: Shop) -> Optional[List[Dict[str, Any]]]:
    """Clients within LOCAL_KM, or None when the shop has no position — a
    missing map is not the same as nobody living nearby."""
    try:
        from features import segmentation as seg
        dist = seg._distances(shop.tid, shop.people)
    except Exception:
        dist = {}
    if not dist:
        return None
    return [c for c in shop.people if (d := dist.get(c["id"])) is not None and d <= LOCAL_KM]


def _qty(line: Dict[str, Any]) -> int:
    """How many of a product one till line holds. The Scan page writes `qty`;
    older imports wrote `quantity`. Reading only the latter counted three
    lattes as one."""
    return int(_num(line.get("qty")) or _num(line.get("quantity")) or 1)


def _items_per_visit(shop: Shop) -> Optional[float]:
    tot = shop.tot["d90"]
    if tot.iv < 5:
        return None
    return tot.iq / tot.iv


def _top_product(shop: Shop) -> Optional[str]:
    # the most sold; at equal sales the one that brought more, then by name
    top = shop.tot["d90"].top_products(1)
    return top[0]["name"] if top else None


HOURS_DAYS = 90          # the period the créneaux are read on
HOURS_MIN_VISITS = 20    # below this, no personal advice


def _paris(t: datetime) -> datetime:
    """A visit's time on the shop's clock (features/period.local)."""
    from features import period as P
    return P.local(t)


def _hours(shop: Shop) -> Optional[Dict[str, Any]]:
    """The busiest and the quietest two-hour slot, when there is enough to say.

    In Paris time (QA F19, 2026-10-09): visits stored in UTC were bucketed by
    their UTC hour, so 14:48 in the shop read as « 12h » and the advice said
    « 11h–13h » to a shop that had no visit then. A tie goes to the slot that
    starts on the busier hour, so visits all at 14h read « 14h–16h »."""
    tot = shop.tot["d90"]                 # HOURS_DAYS
    if tot.n < HOURS_MIN_VISITS:
        return None
    per = tot.by_hour()
    slots = {h: per.get(h, 0) + per.get(h + 1, 0) for h in range(7, 22)}
    busy = max(slots, key=lambda h: (slots[h], per.get(h, 0), -h))
    open_slots = {h: n for h, n in slots.items() if n > 0}
    quiet = min(open_slots, key=lambda h: (open_slots[h], h)) if len(open_slots) > 2 else None
    return {"busy": (busy, busy + 2), "quiet": (quiet, quiet + 2) if quiet is not None else None,
            "visits": tot.n, "days": HOURS_DAYS}


def _satisfied(shop: Shop) -> int:
    return len({r.get("customer_id") for r in shop.reviews
                if _num(r.get("rating")) >= SATISFIED_AT and r.get("customer_id")})


def _subscribed_pct(shop: Shop) -> Optional[int]:
    if not shop.people:
        return None
    subs = set(_db.push_subscriptions.distinct("customer_id", {"tenant_id": shop.tid}))
    return round(len(subs & {c["id"] for c in shop.people}) / len(shop.people) * 100)


# ---------------------------------------------------------------------------
# What is already done
# ---------------------------------------------------------------------------
def _birthday_on(tid: str) -> bool:
    return bool(_db.push_scenarios.find_one({"tenant_id": tid, "builtin": "birthday",
                                             "enabled": True}))


def _google_on(tenant: Dict[str, Any]) -> bool:
    return bool(tenant.get("google_reviews_enabled") and tenant.get("google_review_url"))


def _referral_on(tid: str) -> bool:
    return bool((_db.referral_config.find_one({"tenant_id": tid}) or {}).get("enabled"))


# ---------------------------------------------------------------------------
# Campaign templates — what "Utiliser ce modèle" and the campaign CTAs
# hand to the composer. Kept here so the page and the composer read one copy.
# ---------------------------------------------------------------------------
def _templates(food: bool, play: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """The composer's words. With the shop's playbook, its own offer and
    emoji; the playbook's campaigns (« pb:… ») are resolved in `template`."""
    offert = (play or {}).get("offer") or ("1 boisson offerte" if food else "une réduction offerte")
    emoji = (play or {}).get("emoji") or ("☕" if food else "✨")
    return {
        "relance_inactifs": {"title": f"{emoji} Vous nous manquez !",
                             "message": "Revenez nous voir cette semaine : une attention vous attend "
                                        "à votre prochaine visite.",
                             "segment": "inactive"},
        "offre_locale": {"title": "📍 Une offre près de chez vous",
                         "message": "Vous êtes à deux pas : profitez de -10 % cette semaine sur "
                                    "présentation de votre carte.",
                         "segment": "all", "audience": "locaux"},
        "seconde_visite": {"title": "🎁 Merci pour votre première visite !",
                           "message": "Revenez cette semaine : -10 % sur votre deuxième passage, "
                                      "sur présentation de votre carte.",
                           "segment": "all", "audience": "one_timers"},
        "menu_du_jour": {"title": "🍽️ Le menu du jour est arrivé",
                         "message": "Entrée + plat ou plat + dessert à prix doux, du lundi au "
                                    "vendredi. On vous attend !",
                         "segment": "all"},
        "offre_moment": {"title": "✨ L'offre du moment",
                         "message": "Profitez de notre offre spéciale cette semaine, sur "
                                    "présentation de votre carte.",
                         "segment": "all"},
        "rentree": {"title": "🍂 C'est la rentrée !",
                    "message": "-10 % sur une sélection de produits cette semaine. On vous attend !"
                    if food else "-10 % sur une sélection de prestations cette semaine. On vous attend !",
                    "segment": "all"},
        "happy_hour": {"title": "☕ Happy Hour : -20 % de 16h à 18h",
                       "message": "Toutes les boissons à -20 % de 16h à 18h, cette semaine seulement.",
                       "segment": "all"},
        "heures_creuses": {"title": "⏰ -15 % sur nos créneaux calmes",
                           "message": "Profitez de -15 % sur les créneaux les plus calmes de la semaine.",
                           "segment": "all"},
        "parrainage": {"title": "🎁 Parrainez un ami",
                       "message": f"1 ami parrainé = {offert}. Montrez-lui votre carte : son QR code "
                                  "suffit !",
                       "segment": "all"},
        "fetes": {"title": "🎄 Offre spéciale fêtes",
                  "message": "Des offres exclusives pour les fêtes de fin d'année. Découvrez-les "
                             "vite !",
                  "segment": "all"},
        "saint_valentin": {"title": "💝 Offre Saint-Valentin",
                           "message": "Une attention spéciale pour la Saint-Valentin : venez la "
                                      "découvrir à deux !",
                           "segment": "all"},
        "printemps": {"title": "🌸 Offre de printemps",
                      "message": "Le printemps est là ! Profitez de notre offre de saison cette "
                                 "semaine.",
                      "segment": "all"},
        "fideles_merci": {"title": "💛 Merci pour votre fidélité",
                          "message": "Pour vous remercier, une attention vous attend à votre prochaine "
                                     "visite sur présentation de votre carte.",
                          "segment": "loyal"},
        "a_risque": {"title": "💬 On pense à vous !",
                     "message": "Cela fait un moment ! Revenez cette semaine : une attention vous attend "
                                "sur présentation de votre carte.",
                     "segment": "all", "audience": "at_risk"},
        "etudiants": {"title": "🎓 Offre étudiants",
                      "message": "Sur présentation de votre carte étudiante : -15 % toute la semaine. "
                                 "On vous attend !",
                      "segment": "all", "audience": "students"},
        "anniversaires_semaine": {"title": "🎂 Joyeux anniversaire !",
                                  "message": "Pour votre anniversaire, une surprise vous attend cette "
                                             "semaine sur présentation de votre carte.",
                                  "segment": "birthday"},
        "offre_jour": {"title": "✨ Offre spéciale du jour",
                       "message": "Aujourd'hui seulement : une offre spéciale vous attend sur présentation "
                                  "de votre carte.",
                       "segment": "all"},
        "ete": {"title": "☀️ Offre d'été",
                "message": "Profitez de notre offre spéciale été, cette semaine seulement.",
                "segment": "all"},
    }


# ---------------------------------------------------------------------------
# The four shelves
# ---------------------------------------------------------------------------
def _opportunities(shop: Shop) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    m = shop.monthly

    # Ventes — panier moyen
    ipv = _items_per_visit(shop)
    one, many = shop.play["items"]
    offer_words = (f"{'menus' if shop.meals else 'formules'} ou produits" if shop.food
                   else f"formules ou {many}")
    if ipv is not None:
        body = (f"Vos clients achètent en moyenne {_fr(ipv)} produit{'s' if ipv >= 2 else ''}. "
                f"En proposant des {offer_words} complémentaires, vous pouvez augmenter votre "
                "panier moyen.") if shop.food else (
                f"Vos clients prennent en moyenne {_fr(ipv)} {many if ipv >= 2 else one}. "
                f"En proposant des {offer_words} complémentaires, vous pouvez augmenter "
                "votre panier moyen.")
    elif shop.shop_avg > 0:
        body = (f"{'Sur les 30 derniers jours, votre' if shop.shop_avg_window else 'Votre'} panier moyen est de "
                f"{_eur_cents(shop.shop_avg)}. En proposant des {offer_words} "
                "complémentaires, vous pouvez l'augmenter.")
    else:
        body = (f"En proposant des {offer_words} "
                "complémentaires, vous pouvez augmenter votre panier moyen.")
    out.append({
        "key": "panier_moyen", "category": _category("ventes"),
        "title": "Augmentez votre panier moyen", "body": body,
        "image": "panier" if shop.sells_products else "panier_services", "icon": "cart",
        "impact": _figure(shop, "panier_moyen"),
        "difficulty": {"label": "Facile", "tone": "green", "filled": 3},
        "cta": {"label": "Voir les actions", "kind": "scroll", "target": "actions"},
        "score": m * 0.085, "done": False,
    })

    # Fidélisation — inactifs
    dormant = _inactive(shop)
    if dormant:
        lo, hi = _worth(dormant, shop.shop_avg, shop.at)
        out.append({
            "key": "inactifs", "category": _category("fidelisation"),
            "title": "Réactivez vos clients inactifs",
            "body": f"{len(dormant)} client{'s' if len(dormant) > 1 else ''} n'ont pas acheté "
                    "depuis plus de 30 jours. Une campagne ciblée peut les faire revenir rapidement.",
            "image": "inactifs", "icon": "bell",
            "impact": _computed(lo, hi, m, f"calculé sur vos {len(dormant)} clients inactifs")
                      or _figure(shop, "inactifs"),
            "difficulty": {"label": "Facile", "tone": "green", "filled": 2},
            "cta": {"label": "Relancer ces clients", "kind": "template",
                    "template": "relance_inactifs"},
            "score": (lo + hi) / 2, "done": False,
        })

    # Fidélisation — seconde visite
    once = _one_timers(shop)
    if once:
        lo, hi = _worth(once, shop.shop_avg, shop.at)
        out.append({
            "key": "seconde_visite", "category": _category("fidelisation"),
            "title": "Transformez vos nouveaux clients en habitués",
            "body": f"{len(once)} client{'s' if len(once) > 1 else ''} ne "
                    f"{'sont' if len(once) > 1 else 'est'} pas revenu{'s' if len(once) > 1 else ''} après "
                    "leur 1ère visite, alors qu'ils auraient dû. Une offre pour la deuxième les fait revenir.",
            "image": "fidelite", "icon": "repeat",
            "impact": _computed(lo, hi, m, f"calculé sur vos {len(once)} nouveaux clients")
                      or _figure(shop, "seconde_visite"),
            "difficulty": {"label": "Facile", "tone": "green", "filled": 3},
            "cta": {"label": "Leur proposer une offre", "kind": "template",
                    "template": "seconde_visite"},
            "score": (lo + hi) / 2, "done": False,
        })

    # FidClic IA « a repéré » (features/brain_detectors, 2026-10-25): late
    # regulars and slowing regulars, each with the composer written for them
    from features import brain_detectors as BD
    for d in BD.detect(shop.tid, shop.people, shop.at):
        if d["key"] == "one_timers" or not d["count"]:
            continue
        who = [c for c in shop.people if c.get("id") in set(d["ids"])]
        lo, hi = _worth(who, shop.shop_avg, shop.at)
        late = d["key"] == "en_retard"
        out.append({
            "key": f"ia_{d['key']}", "category": _category("fidelisation"),
            "title": "Relancez vos habitués en retard" if late else "Rattrapez les habitués qui ralentissent",
            "body": f"{d['count']} habitué{'s' if d['count'] > 1 else ''} "
                    + ("ont dépassé leur rythme habituel. " if late else "viennent moins souvent qu'avant. ")
                    + d["why"],
            "image": "fidelite", "icon": "repeat",
            "impact": _computed(lo, hi, m, f"calculé sur ces {d['count']} habitués")
                      or _figure(shop, "inactifs"),
            "difficulty": {"label": "Facile", "tone": "green", "filled": 2},
            "cta": {"label": "Préparer le message", "kind": "template", "template": d["template"]},
            "score": (lo + hi) / 2, "done": False,
        })

    # Acquisition — proximité
    near = _locals(shop)
    if near is None:
        body = ("De nombreux clients potentiels se trouvent à moins de 2 km. Une offre "
                "géolocalisée peut augmenter votre fréquentation.")
    else:
        body = (f"{len(near)} de vos clients habitent à moins de 2 km : leurs voisins sont vos "
                "prochains clients. Une offre géolocalisée peut augmenter votre fréquentation.")
    out.append({
        "key": "proximite", "category": _category("acquisition"),
        "title": "Attirez plus de clients à proximité", "body": body,
        "image": "proximite", "icon": "pin",
        "impact": _figure(shop, "proximite"),
        "difficulty": {"label": "Moyenne", "tone": "amber", "filled": 3},
        "cta": {"label": "Créer une campagne locale", "kind": "template", "template": "offre_locale"},
        "score": m * 0.07, "done": False,
    })

    # Ventes — heures creuses
    hrs = _hours(shop)
    if hrs and hrs["quiet"]:
        a, b = hrs["quiet"]
        out.append({
            "key": "heures_creuses", "category": _category("ventes"),
            "title": "Remplissez vos heures creuses",
            "body": f"Le créneau {a}h–{b}h (heure de Paris) est le plus calme de votre journée, sur vos "
                    f"{hrs['visits']} passages des {hrs['days']} derniers jours. Une offre ciblée sur "
                    "ce créneau peut remplir vos heures creuses.",
            "image": "happyhour" if shop.drinks else "heures_creuses", "icon": "clock",
            "impact": _figure(shop, "heures_creuses"),
            "difficulty": {"label": "Moyenne", "tone": "amber", "filled": 2},
            "cta": {"label": "Créer l'offre", "kind": "template",
                    "template": "happy_hour" if shop.drinks else "heures_creuses"},
            "score": m * 0.05, "done": False,
        })

    # The trade's own advice (services/playbooks.py). Its first lever ranks
    # above everything else, so each shop sees at least one piece of advice
    # written for its activity among the three shown.
    top = max([o["score"] for o in out] + [0.0])
    for n, lv in enumerate(sector_levers(shop, "opportunite")):
        out.append({
            "key": lv["key"], "category": _category(lv["category"]), "title": lv["title"],
            "body": lv["body"], "image": lv["image"], "icon": "sparkles",
            "impact": _figure(shop, lv["key"], lv),
            "difficulty": {"label": "Facile", "tone": "green", "filled": 2},
            "cta": _lever_cta(lv), "sector": shop.play["label"],
            "score": top + 1 if n == 0 else m * 0.06, "done": False,
        })
    return out


def sector_levers(shop: "Shop", shelf: str) -> List[Dict[str, Any]]:
    """The playbook's levers for this shelf that are in season now."""
    return [lv for lv in shop.play["levers"] if lv["shelf"] == shelf and PB.in_season(lv, shop.at.month)]


def _lever_cta(lv: Dict[str, Any]) -> Dict[str, Any]:
    if lv.get("template"):
        return {"label": lv["label"], "kind": "template", "template": lv["template"]["key"]}
    return {"label": lv["label"], "kind": "navigate", "to": lv["to"]}


def _actions(shop: Shop) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    m = shop.monthly

    bdays = _birthdays(shop)
    if bdays:
        lo, hi = _worth(bdays, shop.shop_avg, shop.at)
        impact = _computed(lo, hi, m, f"calculé sur vos {len(bdays)} anniversaires du mois") \
            or _figure(shop, "anniversaire")
    else:
        impact = _figure(shop, "anniversaire")
    out.append({
        "key": "anniversaire", "title": "Lancez une offre anniversaire automatique",
        "body": "Souhaitez automatiquement un joyeux anniversaire avec une offre spéciale (ex : -20%).",
        "benefit": "Clients plus engagés", "image": "anniversaire", "icon": "cake",
        "impact": impact, "setup": "5 minutes",
        "cta": {"label": "Activer", "kind": "activate", "action": "birthday",
                "done_label": "Activée"},
        "score": (impact["euros"][1] if impact.get("euros") else m * 0.075),
        "done": _birthday_on(shop.tid),
    })

    if shop.meals:
        out.append({
            "key": "menu_du_jour", "title": "Créez un menu du jour attractif",
            "body": "Mettez en avant un menu du jour pour attirer de nouveaux clients en semaine.",
            "benefit": "Plus de fréquentation", "image": "menu", "icon": "utensils",
            "impact": _figure(shop, "menu_du_jour"), "setup": "10 minutes",
            "cta": {"label": "Créer", "kind": "template", "template": "menu_du_jour"},
            "score": m * 0.15, "done": False,
        })
    else:
        out.append({
            "key": "offre_moment", "title": "Mettez en avant une offre du moment",
            "body": "Une offre claire et limitée dans le temps donne une raison de venir cette semaine.",
            "benefit": "Plus de fréquentation", "image": "offre_moment", "icon": "sparkles",
            "impact": _figure(shop, "offre_moment"), "setup": "10 minutes",
            "cta": {"label": "Créer", "kind": "template", "template": "offre_moment"},
            "score": m * 0.10, "done": False,
        })

    out.append({
        "key": "palier", "title": "Boostez votre carte de fidélité",
        "body": f"Proposez un palier supplémentaire (ex : 1 {shop.play['items'][0]} "
                "offert) pour inciter à revenir.",
        "benefit": "Clients plus fidèles", "image": "fidelite", "icon": "card",
        "impact": _figure(shop, "palier"), "setup": "10 minutes",
        "cta": {"label": "Configurer", "kind": "navigate", "to": "/dashboard/card"},
        "score": m * 0.12, "done": False,
    })

    happy = _satisfied(shop)
    if happy:
        low = max(1, round(happy * 0.2))
        impact = {"label": f"+{low} à {happy} avis" if low < happy else f"+{happy} avis",
                  "basis": f"calculé sur vos {happy} client{'s' if happy > 1 else ''} satisfaits",
                  "kind": "calcule", "euros": None}
    else:
        impact = _figure(shop, "avis_google")
    out.append({
        "key": "avis_google", "title": "Collectez plus d'avis clients",
        "body": "Invitez automatiquement vos clients satisfaits à laisser un avis Google.",
        "benefit": "Meilleure visibilité locale", "image": "google", "icon": "star",
        "impact": impact, "setup": "5 minutes",
        "cta": {"label": "Activer", "kind": "google_review", "done_label": "Activé"},
        "score": m * 0.06 + happy, "done": _google_on(shop.tenant),
    })

    out.append({
        "key": "parrainage", "title": "Lancez votre programme de parrainage",
        "body": "Chaque client devient ambassadeur : un proche scanne sa carte et s'inscrit.",
        "benefit": "Plus de nouveaux clients", "image": "parrainage", "icon": "gift",
        "impact": _figure(shop, "parrainage"), "setup": "5 minutes",
        "cta": {"label": "Configurer", "kind": "navigate", "to": "/dashboard/referral"},
        "score": m * 0.05, "done": _referral_on(shop.tid),
    })
    return out


def _season(month: int) -> Tuple[str, str]:
    """(this season's idea, the next event worth preparing)."""
    if month in (9, 10):
        return "rentree", "fetes"
    if month in (11, 12):
        return "fetes", "saint_valentin"
    if month in (1, 2):
        return "saint_valentin", "printemps"
    if month in (3, 4, 5):
        return "printemps", "ete"
    return "ete", "rentree"


IDEAS = {
    "rentree": {"category": "automne", "title": "Offre rentrée", "image": "automne",
                "body_food": "-10% sur une sélection de produits pour attirer de nouveaux clients.",
                "body": "-10% sur une sélection de prestations pour attirer de nouveaux clients."},
    "happy_hour": {"category": "ventes", "title": "Happy Hour", "image": "happyhour",
                   "body_food": "-20% sur les boissons de 16h à 18h.", "drinks_only": True},
    "heures_creuses": {"category": "ventes", "title": "Offre heures creuses", "image": "heures_creuses",
                       "body": "-15% sur les créneaux les plus calmes de la semaine.",
                       "nodrinks_only": True},
    "parrainage": {"category": "fidelisation", "title": "Parrainage", "image": "parrainage",
                   "body": "1 ami parrainé = {offer}."},
    "fetes": {"category": "evenement", "title": "Offre spéciale fêtes", "image": "fetes",
              "body": "Des offres exclusives pour augmenter votre CA en fin d'année."},
    "saint_valentin": {"category": "evenement", "title": "Offre Saint-Valentin", "image": "saint_valentin",
                       "body": "Une attention spéciale pour venir à deux."},
    "printemps": {"category": "printemps", "title": "Offre de printemps", "image": "printemps",
                  "body": "Une offre de saison pour accueillir les beaux jours."},
    "ete": {"category": "ete", "title": "Offre d'été", "image": "ete",
            "body": "Une offre estivale, le temps d'une semaine."},
}


def _ideas(shop: Shop) -> List[Dict[str, Any]]:
    """The trade's own moments in season first (this month's, then next
    month's), then the seasonal and evergreen ideas — minus those a trade
    moment replaces (a fleuriste's Saint-Valentin, not the generic one)."""
    month = shop.at.month
    dated = sorted(sector_levers(shop, "idee"), key=lambda lv: 0 if month in lv["months"] else 1)
    replaced = {lv.get("replaces") for lv in dated}
    out = []
    for lv in dated:
        item = {"key": lv["key"], "category": _category(lv["category"]), "title": lv["title"],
                "body": lv["body"], "image": lv["image"], "sector": shop.play["label"],
                "cta": {"label": lv["label"], "kind": "template", "template": lv["template"]["key"]}}
        fact = PB.fact_of(shop.play, lv)
        if fact:
            item["fact"] = {k: fact[k] for k in ("short", "text", "source", "year", "url")}
        out.append(item)

    now_key, next_key = _season(month)
    evergreen = ["happy_hour" if shop.drinks else "heures_creuses", "parrainage"]
    order = [now_key] + evergreen + [next_key]
    rest = [k for k in IDEAS if k not in order]
    for key in order + rest:
        spec = IDEAS[key]
        if key in replaced:
            continue
        if spec.get("drinks_only") and not shop.drinks:
            continue
        if spec.get("nodrinks_only") and shop.drinks:
            continue
        body = (spec.get("body_food") if shop.food and spec.get("body_food")
                else spec.get("body") or spec.get("body_food"))
        out.append({
            "key": key, "category": _category(spec["category"]), "title": spec["title"],
            "body": body.replace("{offer}", shop.play["offer"]),
            "image": spec["image"],
            "cta": {"label": "Utiliser ce modèle", "kind": "template", "template": key},
        })
    return out


def _idea_shelf(ideas: List[Dict[str, Any]], show: int = 4) -> Dict[str, Any]:
    """Ideas keep their seasonal order; a used one gives its place to the next."""
    live = [i for i in ideas if not i.get("done")]
    done = [i for i in ideas if i.get("done")]
    return {"shown": live[:show], "all": live + done, "more": max(0, len(ideas) - min(show, len(live)))}


def _tips(shop: Shop) -> List[Dict[str, Any]]:
    out = []
    hrs = _hours(shop)
    if hrs:
        a, b = hrs["busy"]
        # what it is read on, said (QA F19): the clock, the period, the visits
        text = (f"Vos meilleurs créneaux sont entre {a}h et {b}h (heure de Paris), d'après vos "
                f"{hrs['visits']} passages des {hrs['days']} derniers jours. Renforcez votre "
                "communication sur ces horaires.")
    else:
        # not personal yet — said as general advice, never as an observation
        text = (f"Conseil général : pas encore assez de passages ({HOURS_MIN_VISITS} sur "
                f"{HOURS_DAYS} jours) pour repérer vos créneaux. Une fois atteints, vos meilleurs "
                "horaires s'afficheront ici.")
    out.append({"key": "horaires", "icon": "clock", "title": "Optimisez vos horaires", "body": text})

    top = _top_product(shop)
    if shop.sells_products:
        title = "Mettez en avant vos best-sellers"
        text = (f"« {top} » est votre produit le plus vendu. Mettez-le en avant sur votre vitrine "
                "et vos réseaux sociaux." if top else
                "Les produits les plus vendus attirent de nouveaux clients. Mettez-les en avant sur "
                "votre vitrine et vos réseaux sociaux.")
    else:
        title = f"Mettez en avant vos {shop.play['items'][1]} phares"
        text = (f"« {top} » est votre prestation la plus demandée. Mettez-la en avant sur votre "
                "vitrine et vos réseaux sociaux." if top else
                "Vos prestations les plus demandées attirent de nouveaux clients. Mettez-les en "
                "avant sur votre vitrine et vos réseaux sociaux.")
    out.append({"key": "best_sellers", "icon": "star", "title": title, "body": text})

    out.append({"key": "visibilite", "icon": "pin", "title": "Travaillez votre visibilité locale",
                "body": "Un profil Google bien optimisé peut augmenter nettement votre fréquentation."})

    ratings = [_num(r.get("rating")) for r in shop.reviews if _num(r.get("rating")) > 0]
    if ratings:
        avg = sum(ratings) / len(ratings)
        text = (f"Vos clients vous notent {_fr(avg)}/10. Un client satisfait dépense plus et "
                "recommande votre commerce.")
    else:
        text = "Un client satisfait dépense plus et recommande votre commerce."
    out.append({"key": "experience", "icon": "heart", "title": "Soignez l'expérience client",
                "body": text})

    pct = _subscribed_pct(shop)
    if pct is not None:
        out.append({"key": "notifications", "icon": "bell", "title": "Gardez le contact",
                    "body": f"{pct}% de vos clients ont activé les notifications. Rappelez-leur de "
                            "les activer pour recevoir vos offres."})
    out.append({"key": "carte_caisse", "icon": "card", "title": "Proposez la carte en caisse",
                "body": "Proposer la carte à chaque passage est le premier geste de fidélisation."})
    return out


def _shelf(items: List[Dict[str, Any]], show: int, by_category: bool = False) -> Dict[str, Any]:
    """The top of the shelf, and the whole shelf behind "Voir toutes".

    Done items go to the back. When `by_category`, the shown items keep a mix —
    the best of each category first — rather than three versions of one idea.
    """
    live = sorted([i for i in items if not i.get("done")], key=lambda i: -i.get("score", 0))
    done = [i for i in items if i.get("done")]
    if by_category:
        picked, seen = [], set()
        for i in live:
            if i["category"]["key"] not in seen:
                picked.append(i)
                seen.add(i["category"]["key"])
        for i in live:
            if len(picked) >= show:
                break
            if i not in picked:
                picked.append(i)
        shown = picked[:show]
    else:
        shown = live[:show]
    ordered = shown + [i for i in live if i not in shown] + done
    strip = lambda i: {k: v for k, v in i.items() if k != "score"}
    return {"shown": [strip(i) for i in shown], "all": [strip(i) for i in ordered],
            "more": max(0, len(ordered) - len(shown))}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
def _learned(tid: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from features import reco_ranking as RR
    return RR.rank(tid, items, lambda i, _n: i.get("score", 0))


def _payload(tid: str, at: Optional[datetime] = None, scope: Optional["S.Scope"] = None) -> Dict[str, Any]:
    shop = Shop(tid, at or _now(), scope)
    return {
        "scope": scope.describe() if scope else None,
        "sector": shop.sector, "food": shop.food,
        "activity": {"key": shop.play["key"], "label": shop.play["label"]},
        "hero": _hero(shop),
        "goal": _goal(shop),
        # the ranking that learns (2026-10-30): estimate × what was learned
        "opportunities": _shelf(_mark_used(_learned(tid, _opportunities(shop)), shop.used), 3, by_category=True),
        "actions": _shelf(_mark_used(_learned(tid, _actions(shop)), shop.used), 4),
        "ideas": _idea_shelf(_mark_used(_learned(tid, _ideas(shop)), shop.used)),
        "tips": {"shown": _tips(shop)[:4], "all": _tips(shop),
                 "more": max(0, len(_tips(shop)) - 4)},
        "google_review": {"url": shop.tenant.get("google_review_url") or "",
                          "enabled": _google_on(shop.tenant)},
        "impact_note": ("Les impacts sont en euros. Ceux « calculés sur vos clients » : le panier "
                        "moyen de chaque client multiplié par sa probabilité de retour selon sa "
                        "dernière visite (25–35 % ce mois-ci, 15–20 % entre 30 et 60 jours, 10–15 % "
                        "entre 60 et 90, 5–10 % au-delà). Les autres chiffres viennent d'une source "
                        "publiée, nommée avec son année et son lien ; sans source, la recommandation "
                        "reste un conseil, sans chiffre. Une recommandation utilisée laisse sa place "
                        "pendant 14 jours."),
    }


@router.get("/api/owner/insights/page")
def page(request: Request = None, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    scope = S.resolve(token_data, request)
    data = _payload(token_data.tenant_id, scope=scope)
    # the journal of ideas (2026-10-29): what the page shows first, and what each brought last time
    from features import reco_journal as RJ
    shelves = [data.get(k) or {} for k in ("opportunities", "actions", "ideas")]
    RJ.shown(token_data.tenant_id, "insights", [i for s in shelves for i in s.get("shown") or []], scope.key)
    RJ.attach(token_data.tenant_id, [i for s in shelves for i in (s.get("all") or []) + (s.get("shown") or [])])
    return data


def _home_note(seen: int, home: int) -> str:
    """Why the composer writes to fewer clients than the card counted."""
    if not home:
        who = "Le client repéré est inscrit" if seen == 1 else f"Les {seen} clients repérés sont inscrits"
        return f"{who} dans une autre de vos boutiques : c'est elle qui {'lui' if seen == 1 else 'leur'} envoie les messages."
    others = seen - home
    sent = "ce client" if home == 1 else f"ces {home} clients"
    rest = ("L'autre, venu ici mais inscrit dans une autre de vos boutiques, reçoit les messages de sa boutique."
            if others == 1 else
            f"Les {others} autres, venus ici mais inscrits dans une autre de vos boutiques, reçoivent les messages de leur boutique.")
    return (f"{seen} clients repérés, dont {home} inscrit{'s' if home > 1 else ''} dans cette boutique : "
            f"le message part à {sent}. {rest}")


@router.get("/api/owner/insights/templates/{key:path}")
def template(key: str, day: Optional[int] = None, request: Request = None,
             source: Optional[str] = Query(None, alias="from"),
             token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    """What a campaign CTA pre-fills the composer with.

    When the template names an audience narrower than the composer's four
    cards — clients within 2 km, one-time new clients — its members are
    resolved here, so the composer sends to exactly the people the insight
    was about.
    """
    tid = token_data.tenant_id
    scope = S.resolve(token_data, request)
    if request is not None:                 # an owner opened it (not the Autopilot): the idea was taken up
        from features import reco_journal as RJ
        RJ.event(tid, key, "opened", source if isinstance(source, str) else None, scope.key)
    shop = Shop(tid, _now(), scope)
    # Any segment — a model or one the merchant built — can be messaged: its
    # members are resolved now, by the same evaluator the Segmentation page uses.
    if key.startswith("seg:"):
        from features import segmentation as SEG
        seg = SEG.members(key[4:], token_data=token_data)
        if shop.mine is not None:
            # Never another establishment's clients, whatever the segment holds.
            seg = {**seg, "ids": [i for i in seg["ids"] if i in shop.mine]}
        return {"key": key, "title": "✨ Une attention pour vous",
                "message": "Une offre spéciale vous attend cette semaine sur présentation de votre carte.",
                "segment": "all",
                "audience": {"label": seg["name"], "hint": "Segment", "ids": seg["ids"]}}
    # One client — the bell's « meilleur client silencieux », or « Contacter »
    # on a row of Clients: the composer writes to that person only.
    if key.startswith("client:"):
        cust = next((c for c in shop.people if c.get("id") == key[7:]), None)
        if not cust:
            raise HTTPException(status_code=404, detail="Client introuvable")
        return {"key": key, "title": "💛 Une attention rien que pour vous",
                "message": "Cela fait un moment ! Une attention vous attend à votre prochaine visite, "
                           "sur présentation de votre carte.",
                "segment": "all",
                "audience": {"label": cust.get("name") or "Ce client", "hint": "Un seul client",
                             "ids": [cust["id"]]}}
    # « Offre suggérée » of the Profil client panel (FidClic IA, 2026-10-24): the
    # words the client brain picked for that one client; the owner edits, sends.
    if key.startswith("brain:"):
        from features import client_brain as CB
        cust = next((c for c in shop.people if c.get("id") == key[6:]), None)
        if not cust:
            raise HTTPException(status_code=404, detail="Client introuvable")
        b = cust.get("brain")
        if not CB.current(b):
            b = CB.refresh(tid, cust["id"]) or {}
        r = CB.rythme(b, shop.at)
        offer = CB.suggest(tid, cust, b, r, CB.profil(b, cust.get("created_at"), shop.at, r), shop.at)
        if not offer.get("message"):
            raise HTTPException(status_code=404, detail="Rien à envoyer à ce client pour l'instant.")
        return {"key": key, "title": offer["title"][:50], "message": offer["message"][:160],
                "segment": "all",
                "audience": {"label": cust.get("name") or "Ce client", "hint": "Un seul client",
                             "ids": [cust["id"]]}}
    # FidClic IA « a repéré » (features/brain_detectors): the list's clients,
    # and words that name each one's usual product ({produit_habituel}).
    if key.startswith("ia:"):
        from features import brain_detectors as BD
        spec = BD.TEMPLATES.get(key[3:])
        if not spec:
            raise HTTPException(status_code=404, detail="Modèle introuvable")
        d = next(x for x in BD.detect(tid, shop.people, shop.at) if x["key"] == key[3:])
        # The card counts who came to this store; only its own members are
        # messaged from it (multi-store PR5) — the composer says so (user,
        # 2026-10-25: « jaisa hai waisa rakho, message screen pe line daal do »).
        mine = S.home_customer_ids(scope)
        ids = d["ids"] if mine is None else [i for i in d["ids"] if i in mine]
        audience = {"label": d["label"], "hint": "FidClic IA", "ids": ids}
        if len(ids) < len(d["ids"]):
            audience["note"] = _home_note(len(d["ids"]), len(ids))
        return {"key": key, "title": spec["title"], "message": spec["message"], "segment": "all",
                "audience": audience}
    # A product to put forward (the dashboard's « Créer une offre », 2026-10-23):
    # the composer opens on step 1, the offer, for the owner to set the discount.
    if key.startswith("produit:"):
        name = re.sub(r"\s+", " ", key[8:]).strip()[:40]
        if not name:
            raise HTTPException(status_code=404, detail="Produit introuvable")
        return {"key": "produit", "kind": "offre", "start_step": 1,
                "title": f"⭐ « {name} » à l'honneur"[:50],
                "message": f"Cette semaine, une offre sur « {name} » vous attend sur présentation de votre carte."[:160],
                "segment": "all"}
    # The trade's own campaigns (services/playbooks.py) — only this shop's.
    if key.startswith("pb:"):
        lv = PB.lever_by_template(shop.play, key)
        if not lv:
            raise HTTPException(status_code=404, detail="Modèle introuvable")
        t = lv["template"]
        return {"key": key, "title": t["title"], "message": t["message"], "segment": t["segment"]}
    spec = _templates(shop.food, shop.play).get(key)
    if not spec:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
    out = {"key": key, **{k: v for k, v in spec.items() if k != "audience"}}
    who = spec.get("audience")
    if who == "locaux":
        near = _locals(shop) or []
        out["audience"] = {"label": "Clients locaux", "hint": "À moins de 2 km",
                           "ids": [c["id"] for c in near]}
    elif who == "one_timers":
        once = _one_timers(shop)
        out["audience"] = {"label": "Nouveaux clients", "hint": "Venus une seule fois",
                           "ids": [c["id"] for c in once]}
    elif who == "at_risk":
        risk = _at_risk(shop)
        out["audience"] = {"label": "Clients à risque", "hint": "Des habitués qui ne viennent plus",
                           "ids": [c["id"] for c in risk]}
    elif who == "students":
        st = _students(shop)
        out["audience"] = {"label": "Étudiants", "hint": "Déclarés à l'inscription",
                           "ids": [c["id"] for c in st]}
    # A day-specific offer names the day it was suggested for — the one asked
    # for (the Copilote's forecast peak), or else the shop's strongest day.
    if not isinstance(day, int) or not (0 <= day <= 6):
        day = None
    best = ({"weekday": day} if day is not None else _best_weekday(shop)) if key == "offre_jour" else None
    if best:
        name = WEEKDAY_FR[best["weekday"]]
        out["title"] = f"✨ Offre spéciale du {name}"[:50]
        out["message"] = (f"Ce {name} seulement : une offre spéciale vous attend sur présentation "
                          "de votre carte.")
    return out


@router.post("/api/owner/insights/actions/{action}/activate")
def activate(action: str, token_data: TokenData = Depends(require_role(["business_owner"]))):
    """Switch on what an "Activer" button names — nothing else.

    The birthday offer IS the Automatisations page's birthday scenario: this
    only turns it on, and the merchant can edit or switch it off there.
    """
    tid = token_data.tenant_id
    if action != "birthday":
        raise HTTPException(status_code=404, detail="Action inconnue")
    try:
        from features import push_wallet as pw
        pw._seed(tid)
    except Exception as exc:
        print(f"insights: push wallet seed unavailable (non-fatal): {exc}")
    res = _db.push_scenarios.update_one({"tenant_id": tid, "builtin": "birthday"},
                                        {"$set": {"enabled": True}})
    if not getattr(res, "matched_count", 0):
        raise HTTPException(status_code=409,
                            detail="Le scénario anniversaire est introuvable. Ouvrez Automatisations.")
    return {"action": "birthday", "enabled": True}


class GoogleReview(BaseModel):
    url: str
    enabled: bool = True


# A Google review link, and nothing else. The link is shown to customers, so a
# pasted arbitrary URL would turn the card into a redirect to anywhere.
_GOOGLE_HOSTS = re.compile(
    r"^https://(g\.page|maps\.app\.goo\.gl|goo\.gl/maps|search\.google\.[a-z.]+|"
    r"www\.google\.[a-z.]+|google\.[a-z.]+|maps\.google\.[a-z.]+)(/|$)", re.I)


@router.put("/api/owner/insights/google-review")
def set_google_review(body: GoogleReview,
                      token_data: TokenData = Depends(require_role(["business_owner"]))):
    url = (body.url or "").strip()
    if body.enabled and not _GOOGLE_HOSTS.match(url):
        raise HTTPException(status_code=400,
                            detail="Collez le lien d'avis de votre fiche Google "
                                   "(il commence par https://g.page/ ou https://www.google…).")
    _db.tenants.update_one({"id": token_data.tenant_id},
                           {"$set": {"google_review_url": url,
                                     "google_reviews_enabled": bool(body.enabled and url)}})
    return {"url": url, "enabled": bool(body.enabled and url)}


def google_invite_for(tenant_id: str, rating: Any) -> Optional[str]:
    """The link to hand a customer who just rated the shop — or None.

    Called by the review endpoint. Only a satisfied customer is invited:
    sending an unhappy one to a public review page is the opposite of the
    point, and the shop hears from them privately instead.
    """
    if _num(rating) < SATISFIED_AT:
        return None
    tenant = _db.tenants.find_one({"id": tenant_id}) or {}
    return tenant.get("google_review_url") if _google_on(tenant) else None


@router.post("/api/card/{barcode_id}/google-review-click")
def google_review_click(barcode_id: str):
    """A customer followed the invitation. Logged so the shop can see the
    invitation doing something — never used to identify who wrote what."""
    cust = _db.customers.find_one({"barcode_id": (barcode_id or "").strip().upper()},
                                  {"_id": 0, "id": 1, "tenant_id": 1})
    if not cust:
        raise HTTPException(status_code=404, detail="Carte inconnue")
    _db.google_review_clicks.insert_one({"tenant_id": cust["tenant_id"],
                                         "customer_id": cust["id"], "at": _now()})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
@router.get("/api/owner/insights/export.pdf")
def export_pdf(request: Request = None, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    """The page as a document the merchant can print or forward.

    Every figure keeps its basis in the PDF too — an estimate that travels
    without its caveat is how a number becomes a promise.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    tid = token_data.tenant_id
    data = _payload(tid, scope=S.resolve(token_data, request))
    tenant = _db.tenants.find_one({"id": tid}) or {}
    ink, muted, blue = colors.HexColor("#0B1C3F"), colors.HexColor("#64748B"), colors.HexColor("#2F6BFF")

    base = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=base["Title"], fontName="Helvetica-Bold", fontSize=20,
                        textColor=ink, alignment=0, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=13,
                        textColor=ink, spaceBefore=12, spaceAfter=6)
    body = ParagraphStyle("b", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5,
                          textColor=ink, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=muted, leading=11)
    esc = lambda s: (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    story = [Paragraph("Faites grandir votre commerce", h1),
             Paragraph(esc(f"{tenant.get('name') or 'Votre commerce'} — recommandations du "
                           f"{_now():%d/%m/%Y}"), small), Spacer(1, 6 * mm)]

    hero, goal = data["hero"], data["goal"]
    story.append(Paragraph(esc(hero["title"]), h2))
    story.append(Paragraph(esc(f"{hero.get('chip', '')} {hero.get('chip_text', '')} — {hero['text']}"
                               .strip(" —")), body))
    if goal["is_set"]:
        story.append(Paragraph(esc(f"Objectif du mois : {goal['target']:.0f} € — {goal['pct']} % "
                                   f"atteint, il manque {goal['remaining']:.0f} €."), body))

    def section(title, rows, cols):
        story.append(Paragraph(esc(title), h2))
        table = [[Paragraph(f"<b>{esc(c)}</b>", small) for c in cols]]
        for r in rows:
            table.append([Paragraph(esc(x), body if i == 0 else small) for i, x in enumerate(r)])
        # a table running onto the next page repeats its header (QA UX08)
        t = Table(table, colWidths=[62 * mm, 70 * mm, 45 * mm], repeatRows=1)
        t.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, blue),
            ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#E6EEFB")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)

    def impact_line(imp):
        """Each impact says what it counts (QA UX08: euros, clients and
        reviews sat under one « impact » as if all were money)."""
        lab = str(imp.get("label") or "")
        if imp.get("euros") is not None or "€" in lab:
            unit = "Chiffre d'affaires"
        elif "avis" in lab.lower():
            unit = "Avis Google"
        elif "client" in lab.lower():
            unit = "Clients"
        elif "visite" in lab.lower():
            unit = "Visites"
        else:
            unit = "Effet"
        basis = f" ({imp['basis']})" if imp.get("basis") else ""
        return f"{unit} : {lab}{basis}"

    section("Opportunités", [
        (o["title"], o["body"], impact_line(o["impact"]))
        for o in data["opportunities"]["all"]], ["Opportunité", "Pourquoi", "Impact estimé"])
    section("Actions recommandées", [
        (a["title"] + (" — déjà en place" if a.get("done") else ""), a["body"],
         f"{impact_line(a['impact'])} · {a['setup']}")
        for a in data["actions"]["all"]], ["Action", "Description", "Impact · mise en place"])
    section("Idées de campagnes", [
        (i["title"], i["body"], i["category"]["label"]) for i in data["ideas"]["all"]],
        ["Campagne", "Principe", "Catégorie"])
    section("Conseils", [(t["title"], t["body"], "") for t in data["tips"]["all"]],
            ["Conseil", "Détail", ""])

    story += [Spacer(1, 6 * mm), Paragraph(esc(data["impact_note"]), small)]

    from reportlab.pdfgen import canvas as _canvas

    class Numbered(_canvas.Canvas):
        """« Page 2 / 3 » at the foot of every page (QA UX08)."""
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for st in self._pages:
                self.__dict__.update(st)
                self.setFont("Helvetica", 8)
                self.setFillColor(muted)
                self.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {self._pageNumber} / {total}")
                self.drawString(16 * mm, 9 * mm, str(tenant.get("name") or "FidClic") + " — recommandations FidClic")
                super().showPage()
            super().save()

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                      topMargin=16 * mm, bottomMargin=18 * mm,
                      title="Recommandations FidClic").build(story, canvasmaker=Numbered)
    return Response(content=buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition":
                             f'attachment; filename="fidclic-recommandations-{_now():%Y%m%d}.pdf"'})
