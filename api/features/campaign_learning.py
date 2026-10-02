"""
« Ce qui marche chez vous » — FidClic learns from the campaigns the merchant
sends, and says what works (user, 2026-10-02).

Nothing is sent on its own and nothing is split for a test: FidClic only reads
the campaigns the owner already sends, measures each one, takes it apart, and
compares the parts.

1. WHAT A CAMPAIGN DID — its « effet »
    Counting who came back after a message is not enough: a message to the
    regulars always « works », because they were coming anyway. So each
    recipient's own habit is read from their visits in the HABIT_DAYS before
    the send, and turned into the chance they would have come in the next
    WINDOW_DAYS anyway (expected). The effect is what came on top:

        effet = (clients revenus − clients attendus) / clients touchés

    shown as « +9 clients pour 100 touchés ». A campaign is « mûre » once its
    WINDOW_DAYS are over; only mature campaigns teach anything.

2. WHAT A CAMPAIGN WAS — its traits
    Read from the campaign itself: the offer (cadeau / remise / points bonus /
    nouveauté / événement / aucune), urgency, emoji, the client's first name,
    length, a question, an image, a link, the day, the time of day, and the
    audience. Days and hours are on the shop's clock (Paris).

3. WHAT WORKS — the learnings
    For each trait, the campaigns with one value are compared with the others.
    A learning is only stated when it holds up: at least MIN_CAMPAIGNS
    campaigns on each side, and a difference that chance alone would rarely
    produce (a z-score over the recipients, |z| ≥ 1.64 « probable », ≥ 2.33
    « solide »). Otherwise the page says « pas encore assez de données ».

4. A NEW SHOP — what shops like it learnt
    Until a shop has its own evidence, the same comparison is made over the
    mature campaigns of other shops of its sector, when at least MIN_SHOPS of
    them took part. Only the traits and the counts are pooled — never a name,
    never a client. A shop's own learning always comes first.

Outcomes are stored once mature (`campaign_outcomes`), so a campaign is
measured once and the sector pool stays cheap to read.

Mounts at (all under the « Campagnes » plan switch — Pro and Pro AI):
    GET  /api/owner/campaigns/learning            the learnings, the best moment
    GET  /api/owner/campaigns/{id}/result         one campaign, measured and taken apart
    POST /api/owner/campaigns/learning/tips       advice on a message being written
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import require_role
from models import TokenData
from features import store_scope as S

router = APIRouter(tags=["campagnes"])
_db = None

READERS = ["business_owner", "administrateur", "manager"]
PARIS = ZoneInfo("Europe/Paris")
WINDOW_DAYS = 15          # the same attribution window as CA FidClic and the Campagnes page
HABIT_DAYS = 180          # how far back a client's habit is read
MIN_CAMPAIGNS = 3         # per side, before a comparison is stated
MIN_RECIPIENTS = 30       # per side
MIN_SHOPS = 3             # before a sector learning is used
Z_PROBABLE, Z_SOLID = 1.64, 2.33


def init(db):
    global _db
    _db = db
    try:
        db.campaign_outcomes.create_index("campaign_id", unique=True)
        db.campaign_outcomes.create_index([("sector", 1), ("tenant_id", 1)])
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


# ---------------------------------------------------------------------------
# 2. The traits of a message
# ---------------------------------------------------------------------------
def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


OFFERS = [   # first match wins, in this order (« 50 points offerts » is points, not a gift)
    ("points", re.compile(r"\b(\d+\s+points?\s+(offerts?|bonus|en plus)|points?\s+(double|doubles|x2|bonus)|double\s+points?|x2|bonus)\b")),
    ("cadeau", re.compile(r"\b(offert|offerte|offerts|offertes|gratuit|gratuite|cadeau|cadeaux|gift|free)\b")),
    ("remise", re.compile(r"(\d+\s?%|\bremise|\breduction|\bpromo|\bsolde|-\s?\d+\s?(€|eur)|\b\d+\s?(€|eur)\s+de\s+moins)")),
    ("nouveaute", re.compile(r"\b(nouveau|nouvelle|nouveaux|nouvelles|nouveaute|decouvr\w*|inedit\w*|arrivage)\b")),
    ("evenement", re.compile(r"\b(evenement|soiree|degustation|concert|atelier|masterclass|vernissage|fete)\b")),
]
URGENCY = re.compile(r"\b(aujourd'?hui|ce soir|ce midi|ce week-?end|demain|dernier|derniere|derniers|"
                     r"jusqu'?(a|au)|seulement|vite|limite|limitee|ne ratez|plus que)\b")
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐❤✨]")

TRAITS = {        # dimension → (label, values: key → label)
    "offer": ("Type d'offre", {"cadeau": "Un cadeau (« offert »)", "remise": "Une remise (% ou €)",
                               "points": "Des points bonus", "nouveaute": "Une nouveauté",
                               "evenement": "Un événement", "aucune": "Sans offre"}),
    "urgency": ("Urgence", {"oui": "Avec une date limite", "non": "Sans urgence"}),
    "emoji": ("Emoji", {"oui": "Avec emoji", "non": "Sans emoji"}),
    "prenom": ("Prénom du client", {"oui": "Avec le prénom", "non": "Sans le prénom"}),
    "length": ("Longueur", {"court": "Message court (< 80 caractères)", "long": "Message long"}),
    "question": ("Question", {"oui": "Avec une question", "non": "Sans question"}),
    "image": ("Image", {"oui": "Avec une image", "non": "Sans image"}),
    "link": ("Lien", {"oui": "Avec un lien", "non": "Sans lien"}),
    "day": ("Jour", {"lun": "Le lundi", "mar": "Le mardi", "mer": "Le mercredi", "jeu": "Le jeudi",
                     "ven": "Le vendredi", "sam": "Le samedi", "dim": "Le dimanche"}),
    "week": ("Semaine ou week-end", {"semaine": "En semaine", "weekend": "Le week-end"}),
    "slot": ("Moment de la journée", {"matin": "Le matin (avant 11 h)", "midi": "Le midi (11 h – 14 h)",
                                      "apres_midi": "L'après-midi (14 h – 17 h)", "soir": "Le soir (après 17 h)"}),
    "audience": ("Audience", {"all": "Tous les clients", "inactive": "Les clients inactifs",
                              "loyal": "Les clients fidèles", "birthday": "Les anniversaires",
                              "custom": "Une sélection de clients"}),
}
DAYS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
# Traits that describe the words — the ones advice on a draft can act on.
CONTENT = ("offer", "urgency", "emoji", "prenom", "length", "question", "image", "link")


def traits_of(title: str, message: str, *, image: bool = False, link: bool = False,
              when: Optional[datetime] = None, segment: Optional[str] = None) -> Dict[str, str]:
    raw = f"{title or ''} {message or ''}"
    text = _fold(raw)
    offer = next((k for k, rx in OFFERS if rx.search(text)), "aucune")
    out = {
        "offer": offer,
        "urgency": "oui" if URGENCY.search(text) else "non",
        "emoji": "oui" if EMOJI.search(raw) else "non",
        "prenom": "oui" if re.search(r"\{(first_name|name|prenom)\}", raw) else "non",
        "length": "court" if len((message or "").strip()) < 80 else "long",
        "question": "oui" if "?" in raw else "non",
        "image": "oui" if image else "non",
        "link": "oui" if link else "non",
    }
    if when:
        t = when.astimezone(PARIS)
        out["day"] = DAYS[t.weekday()]
        out["week"] = "weekend" if t.weekday() >= 5 else "semaine"
        out["slot"] = ("matin" if t.hour < 11 else "midi" if t.hour < 14
                       else "apres_midi" if t.hour < 17 else "soir")
    seg = segment if segment in TRAITS["audience"][1] else ("custom" if segment else None)
    if seg:
        out["audience"] = seg
    return out


def campaign_traits(c: Dict[str, Any]) -> Dict[str, str]:
    return traits_of(c.get("name") or "", c.get("content") or "", image=bool(c.get("image_url")),
                     link=bool(c.get("link_url")), when=_aware(c.get("sent_at")),
                     segment=c.get("segment") or ("custom" if c.get("recipient_ids") else None))


# ---------------------------------------------------------------------------
# 1. What a campaign did
# ---------------------------------------------------------------------------
def _habit(first: Optional[datetime], prior: int, sent_at: datetime) -> float:
    """The chance this client comes within WINDOW_DAYS anyway, from the
    visits of their last HABIT_DAYS (or since they joined, if later)."""
    known = HABIT_DAYS
    if first:
        known = max(WINDOW_DAYS, min(HABIT_DAYS, (sent_at - first).days))
    rate = prior / known
    return min(0.95, 1 - math.exp(-rate * WINDOW_DAYS))


def measure(tid: str, c: Dict[str, Any], at: Optional[datetime] = None,
            only: Optional[set] = None) -> Optional[Dict[str, Any]]:
    """{n, came, expected, revenue, effect, mature, day} for one campaign."""
    at = at or _now()
    sent_at = _aware(c.get("sent_at"))
    ids = [i for i in (c.get("recipient_ids") or []) if only is None or i in only]
    if not sent_at or not ids:
        return None
    end = sent_at + timedelta(days=WINDOW_DAYS)
    mature = at >= end
    people = {p["id"]: p for p in _db.customers.find({"tenant_id": tid, "id": {"$in": ids}},
                                                     {"_id": 0, "id": 1, "created_at": 1})}
    prior: Dict[str, int] = defaultdict(int)
    came: Dict[str, float] = {}
    for v in _db.visits.find({"tenant_id": tid, "customer_id": {"$in": ids},
                              "visit_time": {"$gte": sent_at - timedelta(days=HABIT_DAYS), "$lte": end}},
                             {"_id": 0, "customer_id": 1, "visit_time": 1, "amount_paid": 1}):
        t = _aware(v.get("visit_time"))
        cid = v.get("customer_id")
        if not t:
            continue
        if t < sent_at:
            prior[cid] += 1
        elif t <= min(end, at):
            came[cid] = came.get(cid, 0.0) + float(v.get("amount_paid") or 0)
    # An unfinished window is compared with the part of the habit it covers.
    share = 1.0 if mature else max(0.0, min(1.0, (at - sent_at).total_seconds() / (WINDOW_DAYS * 86400)))
    expected = sum(_habit(_aware((people.get(i) or {}).get("created_at")), prior[i], sent_at) for i in ids) * share
    n = len(ids)
    return {"n": n, "came": len(came), "expected": round(expected, 2), "revenue": round(sum(came.values()), 2),
            "effect": round((len(came) - expected) / n, 4), "mature": mature,
            "day": min(WINDOW_DAYS, max(0, (at - sent_at).days))}


def _sector(tid: str) -> str:
    return ((_db.tenants.find_one({"id": tid}, {"_id": 0, "sector": 1}) or {}).get("sector") or "other")


def outcome(c: Dict[str, Any], at: Optional[datetime] = None,
            stored: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """A mature campaign's measure and traits — stored the first time."""
    stored = stored or _db.campaign_outcomes.find_one({"campaign_id": c.get("id")}, {"_id": 0})
    if stored:
        return stored
    m = measure(c["tenant_id"], c, at)
    if not m or not m["mature"]:
        return None
    row = {"campaign_id": c["id"], "tenant_id": c["tenant_id"], "sector": _sector(c["tenant_id"]),
           "traits": campaign_traits(c), **{k: m[k] for k in ("n", "came", "expected", "revenue", "effect")},
           "sent_at": _aware(c.get("sent_at")), "measured_at": at or _now()}
    try:
        _db.campaign_outcomes.insert_one(dict(row))
    except Exception:
        pass                                  # measured twice at once: the first one stays
    return row


def outcomes(tid: str, at: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Every mature campaign of this shop, measured."""
    at = at or _now()
    out = []
    done = {r["campaign_id"]: r for r in _db.campaign_outcomes.find({"tenant_id": tid}, {"_id": 0})}
    for c in _db.campaigns.find({"tenant_id": tid, "status": "sent",
                                 "sent_at": {"$lte": at - timedelta(days=WINDOW_DAYS)}}, {"_id": 0}):
        if c.get("id") and c.get("recipient_ids"):
            o = outcome(c, at, done.get(c["id"]))
            if o:
                out.append(o)
    return out


# ---------------------------------------------------------------------------
# 3. What works
# ---------------------------------------------------------------------------
def _pool(rows: Iterable[Dict[str, Any]]) -> Dict[str, float]:
    rows = list(rows)
    n = sum(r["n"] for r in rows)
    came = sum(r["came"] for r in rows)
    exp = sum(r["expected"] for r in rows)
    return {"campaigns": len(rows), "n": n, "came": came, "expected": exp,
            "effect": (came - exp) / n if n else 0.0,
            "var": (came * (1 - came / n)) / (n * n) if n else 0.0,
            "shops": len({r.get("tenant_id") for r in rows}),
            "revenue_per_100": sum(r["revenue"] for r in rows) / n * 100 if n else 0.0}


def learn(rows: List[Dict[str, Any]], min_shops: int = 1) -> List[Dict[str, Any]]:
    """For every trait value with enough campaigns, its effect against the
    rest of its dimension — kept only when the difference holds up."""
    found = []
    for dim, (dim_label, values) in TRAITS.items():
        for val, val_label in values.items():
            mine = [r for r in rows if (r.get("traits") or {}).get(dim) == val]
            rest = [r for r in rows if (r.get("traits") or {}).get(dim) not in (None, val)]
            a, b = _pool(mine), _pool(rest)
            if min(a["campaigns"], b["campaigns"]) < MIN_CAMPAIGNS or min(a["n"], b["n"]) < MIN_RECIPIENTS:
                continue
            if min(a["shops"], b["shops"]) < min_shops:
                continue
            se = math.sqrt(a["var"] + b["var"]) or 1e-9
            z = (a["effect"] - b["effect"]) / se
            if abs(z) < Z_PROBABLE:
                continue
            found.append({
                "dimension": dim, "dimension_label": dim_label, "value": val, "label": val_label,
                "better": z > 0, "z": round(z, 2), "confidence": "solide" if abs(z) >= Z_SOLID else "probable",
                "per_100": round(a["effect"] * 100, 1), "others_per_100": round(b["effect"] * 100, 1),
                "campaigns": a["campaigns"], "others_campaigns": b["campaigns"],
                "revenue_per_100": round(a["revenue_per_100"], 2),
            })
    # The clearest first; one dimension can yield its best and its worst.
    found.sort(key=lambda f: -abs(f["z"]))
    return found


def _fr(x: float, signed: bool = True) -> str:
    """9.5 → « +9,5 » — French decimals."""
    s = f"{x:g}".replace(".", ",")
    return f"+{s}" if signed and x >= 0 else s


def _sentence(f: Dict[str, Any], source: str) -> str:
    sign = _fr
    who = "chez vous" if source == "vous" else "chez des commerces comme le vôtre"
    verb = "marche mieux" if f["better"] else "marche moins bien"
    return (f"{f['label']} {verb} {who} : {sign(f['per_100'])} clients de plus que prévu pour 100 touchés, "
            f"contre {sign(f['others_per_100'])} sinon ({f['campaigns']} campagnes contre {f['others_campaigns']}).")


def learnings(tid: str, at: Optional[datetime] = None) -> Dict[str, Any]:
    """The shop's own learnings, then its sector's for what it has not learnt yet."""
    at = at or _now()
    own_rows = outcomes(tid, at)
    own = learn(own_rows)
    sector = _sector(tid)
    pool = [r for r in _db.campaign_outcomes.find({"sector": sector, "tenant_id": {"$ne": tid}}, {"_id": 0})]
    theirs = learn(pool, min_shops=MIN_SHOPS) if len({r["tenant_id"] for r in pool}) >= MIN_SHOPS else []
    known = {(f["dimension"], f["value"]) for f in own}
    rows = [{**f, "source": "vous", "sentence": _sentence(f, "vous")} for f in own]
    rows += [{**f, "source": "secteur", "sentence": _sentence(f, "secteur")}
             for f in theirs if (f["dimension"], f["value"]) not in known
             and f["dimension"] not in {g["dimension"] for g in own}]
    best_time = next((f for f in rows if f["better"] and f["dimension"] in ("day", "week", "slot")), None)
    return {"learnings": rows, "campaigns_measured": len(own_rows), "sector": sector,
            "sector_shops": len({r["tenant_id"] for r in pool}), "window_days": WINDOW_DAYS,
            "needs": MIN_CAMPAIGNS, "best_time": best_time,
            "method": (f"Pour chaque campagne, les clients revenus dans les {WINDOW_DAYS} jours sont comparés "
                       "à ceux qui seraient venus de toute façon, d'après leurs habitudes des 6 derniers mois. "
                       f"Une conclusion n'est affichée qu'avec au moins {MIN_CAMPAIGNS} campagnes de chaque côté "
                       "et un écart que le hasard explique mal.")}


def prompt_hints(tid: str) -> str:
    """What the IA is told before writing for this shop."""
    rows = [f for f in learnings(tid)["learnings"] if f["dimension"] in CONTENT]
    good = [f["label"] for f in rows if f["better"]][:4]
    bad = [f["label"] for f in rows if not f["better"]][:3]
    parts = []
    if good:
        parts.append("Ce qui marche le mieux pour ce commerce : " + "; ".join(good) + ".")
    if bad:
        parts.append("À éviter pour ce commerce : " + "; ".join(bad) + ".")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/api/owner/campaigns/learning")
def get_learnings(token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    return learnings(token_data.tenant_id)


@router.get("/api/owner/campaigns/{campaign_id}/result")
def campaign_result(campaign_id: str, request: Request = None,
                    token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    tid = token_data.tenant_id
    c = _db.campaigns.find_one({"tenant_id": tid, "id": campaign_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Campagne introuvable")
    mine = S.customer_ids(S.resolve(token_data, request))
    m = measure(tid, c, only=mine)
    traits = campaign_traits(c)
    found = {(f["dimension"], f["value"]): f for f in learnings(tid)["learnings"]}
    played = []
    for dim, val in traits.items():
        f = found.get((dim, val))
        played.append({"dimension": dim, "dimension_label": TRAITS[dim][0], "value": val,
                       "label": TRAITS[dim][1].get(val, val),
                       "verdict": (None if not f else ("plus" if f["better"] else "moins")),
                       "source": f["source"] if f else None})
    return {"id": c["id"], "name": c.get("name"), "content": c.get("content"),
            "sent_at": (d.isoformat() if (d := _aware(c.get("sent_at"))) else None),
            "result": m, "traits": played, "window_days": WINDOW_DAYS}


class Draft(BaseModel):
    title: str = ""
    message: str = ""
    segment: Optional[str] = None
    image: bool = False
    link: bool = False
    schedule_at: Optional[str] = None


@router.post("/api/owner/campaigns/learning/tips")
def tips(body: Draft, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    """Advice on the message being written, from what this shop has learnt."""
    when = _aware(body.schedule_at) or _now()
    draft = traits_of(body.title, body.message, image=body.image, link=body.link,
                      when=when, segment=body.segment)
    L = learnings(token_data.tenant_id)
    out = []
    for f in L["learnings"]:
        has = draft.get(f["dimension"]) == f["value"]
        if f["better"] and has:
            out.append({"kind": "good", "text": f"{f['label']} : c'est ce qui marche le mieux "
                        f"{'chez vous' if f['source'] == 'vous' else 'chez les commerces comme le vôtre'}.", **f})
        elif f["better"] and not has and f["dimension"] in CONTENT:
            out.append({"kind": "try", "text": f"Essayez : {f['label'][0].lower() + f['label'][1:]} "
                        f"({_fr(f['per_100'])} clients pour 100 chez "
                        f"{'vous' if f['source'] == 'vous' else 'les commerces comme le vôtre'}, "
                        f"contre {_fr(f['others_per_100'])} sinon).", **f})
        elif not f["better"] and has:
            out.append({"kind": "warn", "text": f"{f['label']} marche moins bien "
                        f"{'chez vous' if f['source'] == 'vous' else 'chez les commerces comme le vôtre'}.", **f})
    if L["best_time"] and not body.schedule_at:
        bt = L["best_time"]
        out.append({"kind": "time", "text": f"Meilleur moment : {bt['label'].lower()}.", **bt})
    return {"tips": out[:6], "draft": draft, "campaigns_measured": L["campaigns_measured"],
            "needs": L["needs"], "has_learnings": bool(L["learnings"])}
