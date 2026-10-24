"""
Client brain — what the shop knows about each client, learned from their visits.

The first piece of FidClic IA's « Comprendre » (user, 2026-10-24): for every
client, from their own visits — no LLM, plain arithmetic that is printed:

    · what they usually take (« Coupe + Barbe, 8 fois sur 10 »)
    · when they come (the weekday and the two-hour slot, Paris time)
    · how much (the usual basket and its range)
    · how often (their rhythm) and whether that rhythm is slowing down
    · when they should be back (a window of dates, with a confidence)
    · where they are now: À l'heure / En retard / Décroche / Trop tôt pour savoir
    · a profile (Habitué régulier, Occasionnel, …) and the offer that fits

WHERE IT LIVES
    customers.brain — written after every scan (refresh), filled for older
    clients by the 15-minute tick (ensure) and on demand before a page that
    needs it. Only what the visits say is stored; anything that moves with the
    clock (late or not, days until the next visit) is computed when read, so a
    client who stays away slips from « À l'heure » to « En retard » without a
    write.

THE RHYTHM — SMALL DATA, SAID HONESTLY
    A shop sees a client a handful of times. Two quick visits do not make a
    weekly client, so the client's own gap is pulled towards the shop's usual
    gap, less and less as their visits pile up (a new batsman's first century
    is read against the league average):

        rhythm = (n × own_gap + K × usual_gap) / (n + K)        K = 2

    own_gap is the median of their last gaps (one odd month does not move
    it); n is how many gaps they have. usual_gap is the shop's own median
    rhythm once SHOP_MIN_REGULARS clients have one, the sector's starting
    figure before that. Two visits on one day count as one day here — a
    second scan is a visit, not a rhythm of zero days.

    The next visit is a window, never a date: rhythm ± spread, the spread
    being how much their gaps usually vary. The confidence grows with the
    number of gaps and shrinks with how irregular they are; under
    RHYTHM_MIN_VISITS visits the page says « Trop tôt pour savoir ».

« CLIENTS QUI DÉCROCHENT » — ONE DEFINITION
    Décroche = silent for more than twice their rhythm (and past its window)
    AND for more than clients_page.AT_RISK_SILENT_DAYS, with at least
    AT_RISK_MIN_VISITS visits. clients_page.is_at_risk asks here, so the
    Clients alert, Insights, the Dashboard and Segmentation count the same
    people (user, 2026-10-24: « brain = décrochent »).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request

from auth import require_role
from models import TokenData

VERSION = 1
PARIS = ZoneInfo("Europe/Paris")

K_PRIOR = 2                  # how many gaps the usual rhythm is worth
RHYTHM_MIN_VISITS = 3        # under this, « Trop tôt pour savoir »
SHOP_MIN_REGULARS = 10       # clients with a rhythm before the shop's own figure replaces the sector's
RECENT_GAPS = 10             # the rhythm reads the last gaps only — people change
TREND_MIN_GAPS = 6
TREND_SLOWER = 1.5           # recent gaps 50 % longer than before → « vient moins souvent »
TREND_FASTER = 1 / 1.5
TOP_ITEMS = 5
HABIT_SHARE = 0.4            # an item in 40 % of visits or more is « d'habitude »
SLOT_SHARE = 0.5             # a weekday / slot in half the visits or more is theirs
BIG_BASKET = 1.5             # « Gros panier »: 1.5 × the shop's usual basket

# Where a shop starts before its own clients have a rhythm: how often a client
# of the sector usually comes back, in days. A starting point only — replaced
# by the shop's own median as soon as SHOP_MIN_REGULARS clients have one.
SECTOR_GAP: Dict[str, float] = {
    "bakery": 4, "gym": 4, "cafe": 7, "bar": 10, "pizzeria": 14,
    "restaurant": 21, "retail": 30, "salon": 35, "spa": 42, "other": 21,
}
DEFAULT_GAP = 21.0
# The sector names shops really carry (the demo and older shops use French or
# finer words — « boulangerie », « barbier », « opticien ») read as the keys
# above. brain-v2 only: v1 is kept exactly as it shipped, so the journal
# compares like with like.
SECTOR_ALIASES: Dict[str, str] = {
    "boulangerie": "bakery", "patisserie": "bakery", "pâtisserie": "bakery", "boulangerie-patisserie": "bakery",
    "café": "cafe", "coffee": "cafe", "coffee shop": "cafe", "salon de thé": "cafe", "tea salon": "cafe",
    "juice bar": "cafe", "glacier": "cafe",
    "brasserie": "restaurant", "crêperie": "restaurant", "creperie": "restaurant", "sushi": "restaurant",
    "kebab": "restaurant", "burger": "restaurant", "traiteur": "restaurant",
    "wine bar": "bar", "pub": "bar", "bar à vin": "bar",
    "coiffeur": "salon", "coiffure": "salon", "barbier": "salon", "barber": "salon", "hair salon": "salon",
    "salon de coiffure": "salon",
    "institut": "spa", "institut de beauté": "spa", "esthétique": "spa", "beauté": "spa", "massage": "spa",
    "onglerie": "spa",
    "salle de sport": "gym", "fitness": "gym", "yoga": "gym", "dance": "gym", "danse": "gym", "crossfit": "gym",
    "fleuriste": "retail", "florist": "retail", "opticien": "retail", "optician": "retail", "librairie": "retail",
    "book store": "retail", "chocolatier": "retail", "cbd": "retail", "tabac": "retail", "épicerie": "retail",
    "boutique": "retail", "commerce": "retail",
}

WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
SLOTS = [  # key, label, first hour, last hour (exclusive)
    ("matin", "le matin (avant 12:00)", 0, 12),
    ("midi", "le midi (12:00–14:00)", 12, 14),
    ("apres_midi", "l'après-midi (14:00–18:00)", 14, 18),
    ("soir", "le soir (après 18:00)", 18, 24),
]
RYTHMES = {
    "a_l_heure": "À l'heure",
    "en_retard": "En retard",
    "decroche": "Décroche",
    "trop_tot": "Trop tôt pour savoir",
}
PROFILS = {
    "regulier": "Habitué régulier",
    "occasionnel": "Client occasionnel",
    "decroche": "En train de décrocher",
    "nouveau": "Nouveau client",
    "une_fois": "Venu une seule fois",
    "jamais": "Inscrit, jamais venu",
}
TENDANCES = {"baisse": "Vient moins souvent qu'avant", "hausse": "Vient plus souvent qu'avant",
             "stable": "Rythme stable"}

router = APIRouter(tags=["client-brain"])
# who opens the « Profil client » panel: those who read the Clients page
EDITORS = ["business_owner", "administrateur", "manager"]

_db = None


def init(db):
    global _db
    _db = db


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _aware(d: Any) -> Optional[datetime]:
    if isinstance(d, str):
        try:
            d = datetime.fromisoformat(d.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(d, datetime):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _days(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 86400.0


def _mad(values: List[float], mid: float) -> float:
    """Median absolute deviation, scaled to read like a standard deviation."""
    return 1.4826 * median(abs(v - mid) for v in values) if values else 0.0


def _quartiles(values: List[float]) -> Tuple[float, float]:
    s = sorted(values)
    if len(s) < 4:
        return s[0], s[-1]
    q = lambda p: s[min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))]
    return q(0.25), q(0.75)


def _round5(x: float) -> int:
    return int(5 * round(x / 5.0))


def _when(days: float) -> str:
    """« tous les 21 jours » / « toutes les 3 semaines » / « tous les 2 mois »."""
    d = max(1, int(round(days)))
    if d >= 56 and d % 30 in (0, 1, 2, 28, 29):
        return f"tous les {round(d / 30)} mois"
    if d >= 14 and d % 7 in (0, 1, 6):
        return f"toutes les {round(d / 7)} semaines"
    if d == 7:
        return "toutes les semaines"
    if d == 1:
        return "tous les jours"
    return f"tous les {d} jours"


def _eur(n: float) -> str:
    return f"{int(round(n))} €" if n >= 10 else f"{n:.2f} €".replace(".", ",")


# ---------------------------------------------------------------------------
# the shop's usual rhythm
# ---------------------------------------------------------------------------
def sector_gap(sector: Optional[str]) -> float:
    return float(SECTOR_GAP.get(str(sector or "").strip().lower(), DEFAULT_GAP))


def sector_key(sector: Optional[str]) -> str:
    """The sector as one of SECTOR_GAP's keys (« boulangerie » → bakery)."""
    s = str(sector or "").strip().lower()
    return s if s in SECTOR_GAP else SECTOR_ALIASES.get(s, "other")


# ---------------------------------------------------------------------------
# which brain is in service (user, 2026-10-25: v2 in shadow until the super
# admin switches, on Précision, once it beats v1 and the plain mean)
# ---------------------------------------------------------------------------
_champion_cache: List[Any] = [0.0, 1]
CHAMPION_TTL_S = 60


def champion(fresh: bool = False) -> int:
    now = datetime.now(timezone.utc).timestamp()
    if not fresh and now - _champion_cache[0] < CHAMPION_TTL_S:
        return _champion_cache[1]
    try:
        doc = _db.platform_settings.find_one({"key": "brain_champion"}, {"_id": 0, "value": 1}) or {}
        model = 2 if int(doc.get("value") or 1) == 2 else 1
    except Exception:
        model = 1
    _champion_cache[:] = [now, model]
    return model


def current(b: Optional[Dict[str, Any]]) -> bool:
    """A stored brain of this version, made by the brain in service."""
    return bool(b) and b.get("v") == VERSION and int(b.get("model") or 1) == champion()


def prior_for(tid: str, model: int) -> Tuple[float, str]:
    """The usual rhythm a client is pulled to: the shop's own once it has
    enough regulars; before that v1 the sector's fixed figure, v2 what the
    whole network learned for that sector (features/brain_v2)."""
    if model == 2:
        own = usual_gap(tid)
        if own[1] == "boutique":
            return own
        from features import brain_v2 as V2
        tenant = _db.tenants.find_one({"id": tid}, {"_id": 0, "sector": 1}) or {}
        return V2.sector_prior(tenant.get("sector"))
    return usual_gap(tid)


_usual_cache: Dict[str, Tuple[float, Tuple[float, str]]] = {}
USUAL_TTL_S = 600            # a scan does not re-read every client's rhythm


def usual_gap(tid: str, fresh: bool = False) -> Tuple[float, str]:
    """The shop's median rhythm once enough clients have one, else its
    sector's starting figure. Returns (days, « boutique » | « secteur »)."""
    now = datetime.now(timezone.utc).timestamp()
    hit = _usual_cache.get(tid)
    if hit and not fresh and now - hit[0] < USUAL_TTL_S:
        return hit[1]
    own: List[float] = []
    for c in _db.customers.find({"tenant_id": tid, "deleted_at": None,
                                 "brain.n_gaps": {"$gte": RHYTHM_MIN_VISITS - 1}},
                                {"_id": 0, "brain.own_gap": 1}).limit(5000):
        g = (c.get("brain") or {}).get("own_gap")
        if g:
            own.append(float(g))
    if len(own) >= SHOP_MIN_REGULARS:
        out = (round(median(own), 1), "boutique")
    else:
        tenant = _db.tenants.find_one({"id": tid}, {"_id": 0, "sector": 1}) or {}
        out = (sector_gap(tenant.get("sector")), "secteur")
    _usual_cache[tid] = (now, out)
    return out


# ---------------------------------------------------------------------------
# the brain of one client, from their visits
# ---------------------------------------------------------------------------
def build(visits: Iterable[Dict[str, Any]], prior_gap: float, prior_source: str = "secteur",
          at: Optional[datetime] = None, model: int = 1,
          calib: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Everything the visits say about one client. Pure: no database.

    model 2 (brain-v2) adds the window learned from the journal: `calib` is
    brain_v2's table of how far real returns fall from the rhythm, for
    clients like this one; the window then holds 7 returns in 10."""
    at = at or datetime.now(timezone.utc)
    rows = sorted((v for v in visits if _aware(v.get("visit_time"))), key=lambda v: _aware(v["visit_time"]))
    out: Dict[str, Any] = {"v": VERSION, "model": model, "at": at, "visits_n": len(rows),
                           "prior_gap": float(prior_gap), "prior_source": prior_source}
    if not rows:
        return out
    times = [_aware(v["visit_time"]) for v in rows]
    local = [t.astimezone(PARIS) for t in times]
    out["first"], out["last"] = times[0], times[-1]

    # rhythm — on distinct Paris days
    days: List[datetime] = []
    for t, l in zip(times, local):
        if not days or l.date() != days[-1].astimezone(PARIS).date():
            days.append(t)
    gaps = [_days(days[i - 1], days[i]) for i in range(1, len(days))]
    recent = gaps[-RECENT_GAPS:]
    n = len(recent)
    out["n_gaps"] = n
    if n:
        own = median(recent)
        out["own_gap"] = round(own, 1)
        rhythm = (n * own + K_PRIOR * prior_gap) / (n + K_PRIOR)
        spread = _mad(recent, own) if n >= 4 else 0.25 * rhythm
        cv = (spread / own) if own > 0 else 1.0
        out["gap_days"] = round(rhythm, 1)
        out["spread_days"] = round(min(max(spread, 1.0), rhythm), 1)
        out["cv"] = round(cv, 2)
        # 0–95 %: more gaps → surer; more irregular → less sure
        conf = (1 - 0.6 * min(cv, 1.0)) * (1 - math.exp(-n / 3.0))
        out["confidence"] = max(5, min(95, _round5(100 * conf)))
        if model == 2 and calib:
            from features import brain_v2 as V2
            w = V2.window_for(calib, n, out["cv"])
            if w:
                out["win"] = {"lo": w["lo"], "mid": w["mid"], "hi": w["hi"], "bucket": w["bucket"]}
                if w.get("coverage") is not None:
                    out["confidence"] = int(w["coverage"])      # measured on shops it never saw
                out["conf_rows"] = w.get("rows")
    if len(gaps) >= TREND_MIN_GAPS:
        late, early = median(gaps[-3:]), median(gaps[:-3])
        out["recent_gap"], out["earlier_gap"] = round(late, 1), round(early, 1)
        ratio = late / early if early > 0 else 1.0
        out["trend"] = "baisse" if ratio >= TREND_SLOWER else ("hausse" if ratio <= TREND_FASTER else "stable")
    span = max(_days(times[0], at), 1.0)
    out["per_month"] = round(len(rows) * 30.0 / max(span, 30.0), 2)

    # what they take
    counts: Counter = Counter()
    with_items = 0
    for v in rows:
        names = {str(it.get("name") or "").strip() for it in (v.get("items") or []) if it.get("name")}
        names.discard("")
        if names:
            with_items += 1
            counts.update(names)
    out["visits_with_items"] = with_items
    if with_items:
        out["top_items"] = [{"name": k, "visits": c, "share": round(c / with_items, 2)}
                            # ties read alphabetically, so the order never depends on a set's
                            for k, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:TOP_ITEMS]]
        out["top_item"] = out["top_items"][0]["name"]
        out["items_all"] = sorted(counts)[:60]

    # how much
    paid = [float(v.get("amount_paid") or 0) for v in rows if float(v.get("amount_paid") or 0) > 0]
    out["paid_visits"] = len(paid)
    if paid:
        lo, hi = _quartiles(paid)
        out["basket"] = round(median(paid), 2)
        out["basket_low"], out["basket_high"] = round(lo, 2), round(hi, 2)
        out["spent"] = round(sum(paid), 2)

    # when
    wd = Counter(l.weekday() for l in local)
    day_key, day_n = wd.most_common(1)[0]
    out["weekday"] = {"key": day_key, "label": WEEKDAYS[day_key], "share": round(day_n / len(local), 2)}
    sl = Counter(next(k for k, _, a, b in SLOTS if a <= l.hour < b) for l in local)
    slot_key, slot_n = sl.most_common(1)[0]
    out["slot"] = {"key": slot_key, "share": round(slot_n / len(local), 2)}
    # the two-hour window that holds most of their visits (« 17:00–19:00 »)
    hours = Counter(l.hour for l in local)
    h0 = max(range(24), key=lambda h: (hours[h] + hours[(h + 1) % 24], hours[h], -h))
    out["hours"] = {"from": h0, "to": (h0 + 2) % 24,
                    "share": round((hours[h0] + hours[(h0 + 1) % 24]) / len(local), 2)}

    # where (multi-store: a visit counts where it was scanned)
    stores = Counter(v.get("branch_id") or "main" for v in rows)
    store, store_n = stores.most_common(1)[0]
    out["store"] = {"id": store, "share": round(store_n / len(rows), 2)}
    return out


# ---------------------------------------------------------------------------
# what moves with the clock
# ---------------------------------------------------------------------------
def known(brain: Optional[Dict[str, Any]]) -> bool:
    """Enough to speak of a habit: RHYTHM_MIN_VISITS visits on as many
    different days (three scans on one afternoon are not a rhythm)."""
    b = brain or {}
    return (int(b.get("visits_n") or 0) >= RHYTHM_MIN_VISITS
            and int(b.get("n_gaps") or 0) >= RHYTHM_MIN_VISITS - 1)


def rythme(brain: Optional[Dict[str, Any]], at: Optional[datetime] = None) -> Dict[str, Any]:
    """À l'heure / En retard / Décroche / Trop tôt pour savoir, and the window
    of the next visit — read now, from what the visits said."""
    at = at or datetime.now(timezone.utc)
    b = brain or {}
    n_visits = int(b.get("visits_n") or 0)
    last = _aware(b.get("last"))
    gap = float(b.get("gap_days") or 0)
    if not known(b) or not last or gap <= 0:
        return {"key": "trop_tot", "label": RYTHMES["trop_tot"]}
    spread = float(b.get("spread_days") or 1)
    silent = _days(last, at)
    win = b.get("win")
    if win:
        # brain-v2: the window the journal taught — 7 real returns in 10 fall inside
        centre = gap * float(win["mid"])
        # no « at least a day » floor here: a bakery's regulars are often back
        # the next morning, less than 24 h later — the floor cut them out
        lo = last + timedelta(days=gap * float(win["lo"]))
        hi = last + timedelta(days=max(gap * float(win["hi"]), 0.5))
        spread = max(_days(last, hi) - centre, 1.0)
    else:
        centre = gap
        lo = last + timedelta(days=max(1.0, gap - spread))
        hi = last + timedelta(days=gap + spread)
    out = {"silent_days": int(silent), "next_from": lo, "next_to": hi,
           "next_in_days": int(math.floor(_days(at, last + timedelta(days=centre))))}
    from features import clients_page as CP
    if (silent > max(2 * gap, gap + spread) and silent > CP.AT_RISK_SILENT_DAYS
            and n_visits >= CP.AT_RISK_MIN_VISITS):
        return {**out, "key": "decroche", "label": RYTHMES["decroche"], "late_days": int(silent - gap)}
    if at <= hi:
        return {**out, "key": "a_l_heure", "label": RYTHMES["a_l_heure"]}
    return {**out, "key": "en_retard", "label": RYTHMES["en_retard"], "late_days": int(silent - gap)}


def profil(brain: Optional[Dict[str, Any]], created_at: Any = None,
           at: Optional[datetime] = None, r: Optional[Dict[str, Any]] = None) -> str:
    """One word for who this client is, from the brain and the clock."""
    at = at or datetime.now(timezone.utc)
    b = brain or {}
    n = int(b.get("visits_n") or 0)
    if n == 0:
        return "jamais"
    start = _aware(created_at) or _aware(b.get("first"))
    if n == 1:
        return "nouveau" if start and _days(start, at) <= 30 else "une_fois"
    if not known(b):
        # several visits but not yet three days of them: too soon for a habit
        return "nouveau" if start and _days(start, at) <= 30 else "occasionnel"
    r = r or rythme(b, at)
    if r["key"] == "decroche":
        return "decroche"
    cv = b.get("cv")
    if n >= 4 and cv is not None and float(cv) <= 0.6 and float(b.get("gap_days") or 999) <= 60:
        return "regulier"
    return "occasionnel"


def is_decroche(cust: Dict[str, Any], at: datetime) -> Optional[bool]:
    """None when the client has no current brain (the caller keeps its old
    rule for them until the tick has filled it)."""
    b = cust.get("brain")
    if not b or b.get("v") != VERSION:
        return None
    return rythme(b, at)["key"] == "decroche"


def caisse_line(brain: Optional[Dict[str, Any]]) -> Optional[str]:
    """One line for the till: « D'habitude : Coupe + Barbe · ~25 € · toutes les 3 semaines »."""
    b = brain or {}
    parts: List[str] = []
    habits = [i["name"] for i in (b.get("top_items") or []) if i.get("share", 0) >= HABIT_SHARE][:2]
    if habits and int(b.get("visits_with_items") or 0) >= 2:
        parts.append(" + ".join(habits))
    if int(b.get("paid_visits") or 0) >= 2 and b.get("basket"):
        parts.append(f"~{_eur(float(b['basket']))}")
    if known(b) and b.get("gap_days"):
        parts.append(_when(float(b["gap_days"])))
    return ("D'habitude : " + " · ".join(parts)) if parts else None


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------
_VISIT_FIELDS = {"_id": 0, "customer_id": 1, "visit_time": 1, "amount_paid": 1, "items": 1, "branch_id": 1}


def _stale() -> List[Dict[str, Any]]:
    """No brain, an older version, or made by the brain no longer in service
    (a switch v1 ↔ v2 re-learns every client, a few thousand per tick)."""
    out: List[Dict[str, Any]] = [{"brain": {"$exists": False}}, {"brain.v": {"$ne": VERSION}}]
    if champion() == 2:
        out.append({"brain.model": {"$ne": 2}})
    else:
        out.append({"brain.model": 2})
    return out


def model_args(tid: str, model: int) -> Dict[str, Any]:
    """What build() needs for this model: its prior, and v2's learned window."""
    prior = prior_for(tid, model)
    out: Dict[str, Any] = {"prior_gap": prior[0], "prior_source": prior[1], "model": model}
    if model == 2:
        from features import brain_v2 as V2
        out["calib"] = V2.calibration()
    return out


def refresh(tid: str, cid: str, prior: Optional[Tuple[float, str]] = None) -> Optional[Dict[str, Any]]:
    """Re-learn one client from all their visits (after a scan), with the
    brain in service. Never raises."""
    try:
        args = model_args(tid, champion())
        if prior:
            args.update(prior_gap=prior[0], prior_source=prior[1])
        visits = list(_db.visits.find({"tenant_id": tid, "customer_id": cid}, _VISIT_FIELDS))
        brain = build(visits, **args)
        _db.customers.update_one({"tenant_id": tid, "id": cid}, {"$set": {"brain": brain}})
        return brain
    except Exception as exc:
        print(f"client_brain.refresh failed (non-fatal): {exc}")
        return None


def ensure(tid: str, ids: Optional[List[str]] = None, limit: int = 2000) -> int:
    """Fill the brain of clients who have none (or an older version), in one
    pass over their visits. Returns how many were written."""
    q: Dict[str, Any] = {"tenant_id": tid, "deleted_at": None, "$or": _stale()}
    if ids is not None:
        q["id"] = {"$in": list(ids)}
    todo = [c["id"] for c in _db.customers.find(q, {"_id": 0, "id": 1}).limit(limit)]
    if not todo:
        return 0
    args = model_args(tid, champion())
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for v in _db.visits.find({"tenant_id": tid, "customer_id": {"$in": todo}}, _VISIT_FIELDS):
        by[v["customer_id"]].append(v)
    at = datetime.now(timezone.utc)
    for cid in todo:
        _db.customers.update_one({"tenant_id": tid, "id": cid},
                                 {"$set": {"brain": build(by.get(cid, []), at=at, **args)}})
    return len(todo)


def ensure_all(budget: int = 3000) -> Dict[str, int]:
    """The tick: older clients get their brain a few thousand at a time."""
    done: Dict[str, int] = {}
    left = budget
    tids = _db.customers.distinct("tenant_id", {"deleted_at": None, "$or": _stale()})
    for tid in tids:
        if left <= 0:
            break
        n = ensure(tid, limit=left)
        if n:
            done[tid] = n
            left -= n
    return done


# ---------------------------------------------------------------------------
# what to offer — never sent from here: the owner opens the composer
# ---------------------------------------------------------------------------
DISCOVER_MIN_CLIENTS = 3     # an item « others also take » needs this many clients behind it
DISCOVER_MIN_SHARE = 0.2
_discover_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _together(tid: str) -> Dict[str, Any]:
    """Who takes what, over the last year: {client: set(items)} — cached."""
    now = datetime.now(timezone.utc)
    hit = _discover_cache.get(tid)
    if hit and now.timestamp() - hit[0] < USUAL_TTL_S:
        return hit[1]
    sets: Dict[str, set] = defaultdict(set)
    for v in _db.visits.find({"tenant_id": tid, "visit_time": {"$gte": now - timedelta(days=365)},
                              "items.0": {"$exists": True}},
                             {"_id": 0, "customer_id": 1, "items.name": 1}).limit(30000):
        cid = v.get("customer_id")
        if cid:
            sets[cid].update(str(i.get("name") or "").strip() for i in v.get("items") or [] if i.get("name"))
    out = {"sets": sets}
    _discover_cache[tid] = (now.timestamp(), out)
    return out


def discover(tid: str, cid: str, brain: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What clients who take this client's usual item also take — and this
    client never has. The hidden pattern behind « Faire découvrir »."""
    top = brain.get("top_item")
    if not top:
        return None
    mine = set(brain.get("items_all") or [])
    sets = _together(tid)["sets"]
    peers = [s for c, s in sets.items() if c != cid and top in s]
    if len(peers) < DISCOVER_MIN_CLIENTS:
        return None
    counts = Counter(i for s in peers for i in s if i and i not in mine and i != top)
    if not counts:
        return None
    name, n = counts.most_common(1)[0]
    share = n / len(peers)
    if n < DISCOVER_MIN_CLIENTS or share < DISCOVER_MIN_SHARE:
        return None
    return {"name": name, "share": round(share, 2), "peers": len(peers), "with": top}


def _date(d: Optional[datetime]) -> str:
    if not d:
        return ""
    l = d.astimezone(PARIS)
    months = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
    return f"{l.day} {months[l.month - 1]}"


def suggest(tid: str, cust: Dict[str, Any], brain: Dict[str, Any], r: Dict[str, Any], prof: str,
            at: Optional[datetime] = None) -> Dict[str, Any]:
    """The one thing worth doing for this client now, why, and the words the
    client would read (the composer pre-fills them; the owner edits and sends).
    `message` and `title` are the client's; the rest is for the owner."""
    at = at or datetime.now(timezone.utc)
    b = brain or {}
    top = b.get("top_item")
    gap = float(b.get("gap_days") or 0)
    prior = float(b.get("prior_gap") or DEFAULT_GAP)
    where = {"boutique": "vos clients", "reseau": "les clients des commerces de votre secteur"}.get(
        b.get("prior_source") or "", "les clients de votre secteur")

    if prof == "jamais":
        d = int(_days(_aware(cust.get("created_at")) or at, at))
        return {"kind": "premiere", "label": "Offre de première visite", "when": "Maintenant",
                "why": f"Inscrit depuis {d} jour{'s' if d > 1 else ''}, jamais venu en boutique.",
                "title": "🎁 Votre première visite",
                "message": "Bienvenue ! Une attention vous attend lors de votre première visite, "
                           "sur présentation de votre carte."}
    if prof in ("nouveau", "une_fois") and int(b.get("visits_n") or 0) == 1:
        first = _aware(b.get("first")) or at
        due = first + timedelta(days=prior)
        send = max(at, due - timedelta(days=2))
        return {"kind": "deuxieme", "label": "Offre de deuxième visite",
                "when": "Maintenant" if send <= at else f"Vers le {_date(send)}",
                "send_on": send,
                "why": (f"Venu une seule fois, le {_date(first)} ; d'habitude, {where} reviennent "
                        f"{_when(prior)}. La deuxième visite est la plus difficile à obtenir."),
                "title": "💛 On vous attend !",
                "message": "Merci pour votre première visite ! Une attention vous attend à la prochaine, "
                           "sur présentation de votre carte."}
    if r.get("key") in ("en_retard", "decroche"):
        why = (f"Vient d'habitude {_when(gap)} ; pas venu depuis {r.get('silent_days')} jours "
               f"({r.get('late_days')} jours de retard).")
        if b.get("trend") == "baisse":
            why += " Il venait déjà moins souvent ces derniers temps."
        extra = f" sur « {top} »" if top else ""
        return {"kind": "relance", "label": f"Relance avec un petit plus{extra}", "when": "Maintenant",
                "why": why,
                "title": "💛 Vous nous manquez",
                "message": (f"Cela fait un moment ! Un petit plus vous attend{extra} à votre prochaine "
                            f"visite, sur présentation de votre carte.")[:160]}
    if r.get("key") == "a_l_heure":
        window = f"entre le {_date(r.get('next_from'))} et le {_date(r.get('next_to'))}"
        found = discover(tid, cust.get("id"), b)
        if found:
            send = max(at, r["next_from"] - timedelta(days=2))
            return {"kind": "decouverte", "label": f"Faire découvrir « {found['name']} »",
                    "when": "Maintenant" if send <= at else f"Le {_date(send)}, 2 jours avant sa visite",
                    "send_on": send,
                    "why": (f"Il revient d'habitude {_when(gap)}, prochaine visite attendue {window}. "
                            f"{int(round(found['share'] * 100))} % des clients qui prennent « {found['with']} » "
                            f"prennent aussi « {found['name']} » ; lui, jamais. Pas besoin de remise : "
                            f"il vient de toute façon."),
                    "title": "✨ À découvrir",
                    "message": (f"Et si vous essayiez « {found['name']} » lors de votre prochaine visite ? "
                                f"Demandez-le en caisse.")[:160]}
        return {"kind": "rien", "label": "Rien à envoyer pour l'instant", "when": None,
                "why": (f"Il devrait revenir de lui-même {window}. Une remise maintenant coûterait "
                        f"sans rien rapporter.")}
    days = int(b.get("n_gaps") or 0) + 1
    left = max(1, RHYTHM_MIN_VISITS - days)
    return {"kind": "rien", "label": "Rien à envoyer pour l'instant", "when": None,
            "why": (f"Venu {days} jour{'s' if days > 1 else ''} différent{'s' if days > 1 else ''} : encore "
                    f"{left} jour{'s' if left > 1 else ''} de visite et FidClic connaîtra son rythme.")}


# ---------------------------------------------------------------------------
# the « Profil client » panel
# ---------------------------------------------------------------------------


def _shop_basket(tid: str) -> Optional[float]:
    vals = [float((c.get("brain") or {}).get("basket") or 0) for c in _db.customers.find(
        {"tenant_id": tid, "deleted_at": None, "brain.basket": {"$gt": 0}}, {"_id": 0, "brain.basket": 1}).limit(5000)]
    vals = [v for v in vals if v > 0]
    return median(vals) if len(vals) >= 5 else None


def tags(brain: Dict[str, Any], shop_basket: Optional[float]) -> List[str]:
    b = brain or {}
    out: List[str] = []
    if b.get("trend") in ("baisse", "hausse"):
        out.append(TENDANCES[b["trend"]])
    if shop_basket and float(b.get("basket") or 0) >= BIG_BASKET * shop_basket and int(b.get("paid_visits") or 0) >= 2:
        out.append("Gros panier")
    wd = b.get("weekday") or {}
    if known(b) and float(wd.get("share") or 0) >= SLOT_SHARE:
        out.append(f"Fidèle du {wd['label']}")
    return out


def payload(tid: str, cust: Dict[str, Any], brain: Dict[str, Any],
            at: Optional[datetime] = None) -> Dict[str, Any]:
    at = at or datetime.now(timezone.utc)
    b = brain or {}
    n = int(b.get("visits_n") or 0)
    r = rythme(b, at)
    prof = profil(b, cust.get("created_at"), at, r)
    enough = known(b)
    wd, slot, hours = b.get("weekday") or {}, b.get("slot") or {}, b.get("hours") or {}
    slot_label = next((lab for k, lab, _, _ in SLOTS if k == slot.get("key")), None)
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "branches": 1}) or {}
    stores = {x.get("id"): x.get("name") for x in t.get("branches") or [] if x.get("id")}
    store = (b.get("store") or {}).get("id")
    iso = lambda d: _aware(d).isoformat() if _aware(d) else None  # noqa: E731
    offer = suggest(tid, cust, b, r, prof, at)
    if offer.get("send_on"):
        offer["send_on"] = iso(offer["send_on"])
    return {
        "client": {"id": cust.get("id"), "name": cust.get("name") or ""},
        "visits": n,
        "days": (int(b.get("n_gaps") or 0) + 1) if n else 0,
        "enough": enough,
        "habits": {
            "items": b.get("top_items") or [],
            "visits_with_items": int(b.get("visits_with_items") or 0),
        },
        "when": {
            "weekday": wd.get("label") if enough and float(wd.get("share") or 0) >= SLOT_SHARE else None,
            "weekday_share": wd.get("share"),
            "slot": slot_label if enough and float(slot.get("share") or 0) >= SLOT_SHARE else None,
            "hours": (f"{hours['from']:02d}:00–{hours['to']:02d}:00"
                      if enough and float(hours.get("share") or 0) >= SLOT_SHARE else None),
            "hours_share": hours.get("share"),
        },
        "basket": ({"usual": b.get("basket"), "low": b.get("basket_low"), "high": b.get("basket_high"),
                    "paid_visits": b.get("paid_visits"), "spent": b.get("spent")} if b.get("basket") else None),
        "rhythm": ({"days": b.get("gap_days"), "text": _when(float(b["gap_days"])),
                    "own_days": b.get("own_gap"), "gaps": b.get("n_gaps"),
                    "usual_days": b.get("prior_gap"), "usual_source": b.get("prior_source"),
                    "confidence": b.get("confidence"), "per_month": b.get("per_month"),
                    "trend": b.get("trend"), "trend_label": TENDANCES.get(b.get("trend") or ""),
                    "recent_days": b.get("recent_gap"), "earlier_days": b.get("earlier_gap")}
                   if enough and b.get("gap_days") else None),
        "next": ({"from": iso(r.get("next_from")), "to": iso(r.get("next_to")),
                  "in_days": r.get("next_in_days"), "confidence": b.get("confidence")}
                 if r.get("next_from") else None),
        "status": {"key": r["key"], "label": r["label"], "late_days": r.get("late_days"),
                   "silent_days": r.get("silent_days")},
        "profile": {"key": prof, "label": PROFILS[prof]},
        "tags": tags(b, _shop_basket(tid)),
        "store": stores.get(store) if len(stores) > 1 and store else None,
        "offer": {**offer, "template": f"brain:{cust.get('id')}" if offer.get("message") else None},
        "caisse": caisse_line(b),
        "how": how(b),
        "updated_at": iso(b.get("at")),
    }


_USUAL_FROM = {"boutique": "de vos clients", "reseau": "des commerces de votre secteur sur FidClic",
               "secteur": "de votre secteur"}


def how(b: Dict[str, Any]) -> str:
    """« Comment c'est calculé ? » — said for the brain that made this profile."""
    usual = _USUAL_FROM.get(b.get("prior_source") or "secteur", "de votre secteur")
    text = ("Calculé à partir de ses passages en caisse, sans IA générative. Son rythme est le rythme "
            f"médian de ses derniers passages, rapproché du rythme habituel {usual} "
            f"({_when(float(b.get('prior_gap') or DEFAULT_GAP))}) tant qu'il a peu de visites. ")
    if b.get("win"):
        return text + ("La fourchette est apprise sur les vrais retours des clients qui lui ressemblent : "
                       "7 sur 10 reviennent dedans. La confiance est mesurée sur des commerces que le modèle "
                       "n'a pas vus en apprenant.")
    return text + ("La prochaine visite est une fourchette ; la confiance monte avec le nombre de visites "
                   "et baisse si ses passages sont irréguliers.")


@router.get("/api/owner/clients/{customer_id}/profil")
def get_profil(customer_id: str, request: Request = None,
               token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True))):
    from features import customer_edit as CE
    cust = CE._customer(token_data, request, customer_id)
    b = cust.get("brain")
    if not current(b):
        b = refresh(token_data.tenant_id, customer_id) or {}
    return payload(token_data.tenant_id, cust, b)
