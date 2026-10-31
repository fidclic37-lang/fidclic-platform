"""
Produits qui font revenir — the actions (PR3, user 2026-10-31).

The analysis (features/product_return) says which products bring clients
back. This turns it into something to do, on Pro AI only:

    One-shot   the clients whose LAST visit had a One-shot product and who
               have been silent past the window (up to LAPSED_DAYS) get an
               offer on the Aimant product          → template « pr:os:<ref> »
    Nouveaux   the clients with one visit, still inside their window, are
               offered the Aimant for their 2nd visit → « pr:new:<ref> »
    One client the Fiche client's « À proposer »       → « prc:<client id> »

Where (decision 2026-10-31): Insights (two cards), the Copilote (a tool), the
Tableau de bord (top Aimant + top One-shot) and the Fiche client (tags +
suggestion). Nothing is sent from here: the composer opens pre-filled, the
owner sets the offer and sends — with its groupe témoin (features/temoin), and
the témoin's answer comes back on the product card: « 42 % revenus vs 18 %
témoin ».

The weekly analysis stores the counts (`product_return.actions`) — never a
client id; the clients themselves are found again when the composer opens.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from fastapi import HTTPException

_db = None

LAPSED_DAYS = 120            # silent longer than this: no longer asked back from here
NEW_JOIN_SLACK = 7           # « new » = joined within the window (+ a week)
OS_MAX = 3
OS_PREFIX, NEW_PREFIX, CLIENT_PREFIX = "pr:os:", "pr:new:", "prc:"
_KEY = re.compile(r"pr:(os|new):([0-9a-f]{10})")
ACTIVE = ("aimant", "neutre", "one_shot")
LABELS = {"aimant": "Aimant", "neutre": "Neutre", "one_shot": "One-shot"}
MONTHS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
PRO_AI = "Disponible avec Pro AI."


def init(db):
    global _db
    _db = db


def _now() -> datetime:                     # the clock (tests set it)
    return datetime.now(timezone.utc)


def ref(keys: Iterable[str]) -> str:
    """A product (or a « toujours ensemble » pair) named in a link: stable
    across the weekly rebuilds, short enough for a campaign's template."""
    return hashlib.sha1("|".join(sorted(str(k) for k in keys)).encode()).hexdigest()[:10]


def full(tid: Optional[str]) -> bool:
    """Pro AI — the actions, the ranges, the tests (decision 2026-10-28)."""
    from features import plan_limits as PL
    f = PL.tenant_features(tid)
    return PL.allows(f, "advanced_analytics") and (f.get("ai_level") or "none") == "advanced"


def store_key(scope) -> str:
    from features import product_return as PR
    if scope is None or scope.is_all or not scope.ids or len(scope.ids) != 1:
        return PR.ALL
    return list(scope.ids)[0]


def picks(views: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """The Aimant to offer (the best on a first purchase, else over all
    visits) and the One-shot products (over all visits, else the first)."""
    def of(view, bucket):
        return [p for p in ((views.get(view) or {}).get("products") or []) if p.get("bucket") == bucket and p.get("ref")]
    aim = (of("first", "aimant") or of("all", "aimant") or [None])[0]
    return aim, (of("all", "one_shot") or of("first", "one_shot"))[:OS_MAX]


def audiences(timelines: Dict[str, List[Dict[str, Any]]], today: date, window: int,
              joined: Dict[str, Optional[datetime]], now: datetime, groups: Dict[str, Set[str]],
              store: Optional[str] = None) -> Dict[str, Any]:
    """{one_shot: {ref: [client]}, new: [client]} — from each client's
    occasions (features/product_return._occasions). One establishment: the
    clients whose last visit was there."""
    out: Dict[str, Any] = {"one_shot": {r: [] for r in groups}, "new": []}
    for cid, occs in timelines.items():
        if not occs:
            continue
        last = occs[-1]
        if store is not None and last["store"] != store:
            continue
        age = (today - last["day"]).days
        if window <= age <= LAPSED_DAYS and last["items"]:
            for r, keys in groups.items():
                if last["items"] & keys:
                    out["one_shot"][r].append(cid)
        if len(occs) == 1 and age < window:
            j = joined.get(cid)
            if j is not None and (now - j).days <= window + NEW_JOIN_SLACK:
                out["new"].append(cid)
    return out


def _alive(tid: str) -> Set[str]:
    return set(_db.customers.distinct("id", {"tenant_id": tid, "deleted_at": None}))


def actions(tid: str, views: Dict[str, Any], timelines, today: date, window: int, joined, now: datetime,
            store: Optional[str] = None, alive: Optional[Set[str]] = None) -> Dict[str, Any]:
    """What the weekly analysis keeps: the Aimant, the One-shot products with
    how many of their buyers are gone, how many new clients — counts only."""
    aim, oss = picks(views)
    a = audiences(timelines, today, window, joined, now, {p["ref"]: set(p.get("keys") or []) for p in oss}, store)
    alive = _alive(tid) if alive is None else alive
    one_shot = [{"ref": p["ref"], "name": p["name"], "back": p.get("back"),
                 "lapsed": sum(1 for c in a["one_shot"][p["ref"]] if c in alive)} for p in oss]
    one_shot.sort(key=lambda x: -x["lapsed"])
    return {"aimant": {"ref": aim["ref"], "name": aim["name"], "names": aim.get("names") or [aim["name"]],
                       "back": aim.get("back")} if aim else None,
            "one_shot": one_shot, "new": sum(1 for c in a["new"] if c in alive)}


# ---------------------------------------------------------------------------
# the témoin's answer
# ---------------------------------------------------------------------------
def tests(tid: str, refs: Iterable[str], now: Optional[datetime] = None) -> Dict[str, Dict[str, Any]]:
    """{ref: the last campaign sent from it, measured against its témoin}."""
    from features import temoin as T
    now = now or _now()
    refs = [r for r in refs if r]
    if not refs:
        return {}
    keys = [p + r for r in refs for p in (OS_PREFIX, NEW_PREFIX)]
    out: Dict[str, Dict[str, Any]] = {}
    for c in _db.campaigns.find({"tenant_id": tid, "template": {"$in": keys}, "sent_at": {"$ne": None}},
                                {"_id": 0, "id": 1, "template": 1, "sent_at": 1, "recipient_ids": 1,
                                 "holdout_ids": 1}).sort("sent_at", -1):
        r = c["template"].rsplit(":", 1)[-1]
        if r in out:
            continue
        b = T.campaign_block(tid, c, now)
        if not b:
            continue
        ready = not b["pending"]
        out[r] = {"campaign": c.get("id"), "kind": "one_shot" if c["template"].startswith(OS_PREFIX) else "new",
                  "ready": ready, "ready_on": b["ready_on"], "enough": b["enough"],
                  "rate": b["sent"]["rate"] if ready else None,
                  "temoin_rate": b["temoin"]["rate"] if ready else None,
                  "extra_revenue": b["extra_revenue"] if ready and b["enough"] else None}
    return out


def pct(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return f"{int(x)}" if float(x).is_integer() else f"{x:.1f}".replace(".", ",")


def _day_fr(iso: Optional[str]) -> str:
    try:
        d = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    return f"{d.day} {MONTHS_FR[d.month - 1]}"


def test_text(t: Optional[Dict[str, Any]]) -> str:
    """« Dernier test : 50 % revenus contre 25 % pour le groupe témoin. »"""
    if not t:
        return ""
    if not t["ready"]:
        return f"Test en cours : résultat le {_day_fr(t.get('ready_on'))}."
    few = "" if t.get("enough") else " (encore peu de clients)"
    return f"Dernier test : {pct(t['rate'])} % revenus contre {pct(t['temoin_rate'])} % pour le groupe témoin{few}."


# ---------------------------------------------------------------------------
# what the pages read
# ---------------------------------------------------------------------------
def shop_actions(tid: str, scope=None, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Insights / the analysis page: the stored actions + each one's test."""
    from features import product_return as PR
    if not full(tid):
        return None
    doc = PR.result(tid, store_key(scope))
    act = (doc or {}).get("actions")
    if not act:
        return None
    refs = [o["ref"] for o in act.get("one_shot") or []] + ([act["aimant"]["ref"]] if act.get("aimant") else [])
    return {**act, "tests": tests(tid, refs, now)}


def dashboard(tid: str, scope=None) -> Optional[Dict[str, Any]]:
    """The Tableau de bord's small card: the best Aimant, the worst One-shot."""
    from features import product_return as PR
    if not full(tid):
        return None
    doc = PR.result(tid, store_key(scope))
    if not doc:
        return None
    aim, oss = picks(doc.get("views") or {})
    worst = min(oss, key=lambda p: p.get("ratio") or 0) if oss else None
    if not aim and not worst:
        return None
    side = lambda p: {"name": p["name"], "back": p.get("back")} if p else None   # noqa: E731
    return {"aimant": side(aim), "one_shot": side(worst)}


def for_client(tid: str, cid: str, items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The Fiche client: what kind each of their usual products is, and the
    Aimant to suggest when they have never taken it."""
    from features import product_return as PR
    if not full(tid):
        return None
    doc = PR.result(tid)
    if not doc:
        return None
    by_name: Dict[str, Dict[str, Any]] = {}
    for view in ("all", "first"):
        for p in ((doc.get("views") or {}).get(view) or {}).get("products") or []:
            for n in p.get("names") or []:
                by_name.setdefault(n.strip().lower(), p)
    tags, seen = [], set()
    for it in items or []:
        nm = str(it.get("name") or "").strip()
        p = by_name.get(nm.lower())
        if p and p.get("bucket") in ACTIVE and nm.lower() not in seen:
            seen.add(nm.lower())
            tags.append({"name": nm, "bucket": p["bucket"], "label": LABELS[p["bucket"]]})
    aim = (doc.get("actions") or {}).get("aimant")
    has = aim and any(n.strip().lower() in seen or n.strip().lower() in {str(i.get("name") or "").strip().lower() for i in items or []}
                      for n in aim.get("names") or [aim["name"]])
    suggest = ({"name": aim["name"], "back": aim.get("back"), "template": CLIENT_PREFIX + cid}
               if aim and not has else None)
    return {"tags": tags, "suggest": suggest}


# ---------------------------------------------------------------------------
# the composer, pre-filled (features/insights_page.template)
# ---------------------------------------------------------------------------
def _doc_or_404(tid: str, scope) -> Dict[str, Any]:
    from features import product_return as PR
    if not full(tid):
        raise HTTPException(status_code=403, detail=PRO_AI)
    doc = PR.result(tid, store_key(scope))
    aim = ((doc or {}).get("actions") or {}).get("aimant")
    if not aim:
        raise HTTPException(status_code=404, detail="Aucun produit qui fait revenir pour l'instant.")
    return doc


def _live(tid: str, doc: Dict[str, Any], scope, groups: Dict[str, Set[str]]) -> Dict[str, Any]:
    """The clients now, for the composer (the stored counts are a week old)."""
    from features import product_return as PR
    from features import store_scope as S
    now = _now()
    cat = PR._Catalog((_db.tenant_catalog.find_one({"tenant_id": tid}, {"_id": 0, "items": 1}) or {}).get("items") or [])
    timelines, _promo, _cov = PR._occasions(tid, now, cat)
    key = store_key(scope)
    a = audiences(timelines, PR.paris_day(now), int(doc.get("window_days") or 21), PR._joined(tid), now, groups,
                  None if key == PR.ALL else key)
    keep = _alive(tid)
    mine = S.home_customer_ids(scope) if scope is not None else None
    if mine is not None:
        keep &= mine
    return {"one_shot": {r: [c for c in ids if c in keep] for r, ids in a["one_shot"].items()},
            "new": [c for c in a["new"] if c in keep]}


def template(key: str, tid: str, scope) -> Dict[str, Any]:
    """« pr:os:<ref> », « pr:new:<ref> », « prc:<client> » → what the composer
    opens with: an offer to set on the Aimant product, and who gets it."""
    if key.startswith(CLIENT_PREFIX):
        from features import store_scope as S
        doc = _doc_or_404(tid, scope)
        aim = doc["actions"]["aimant"]
        q = S.customer_filter(scope) if scope is not None else {"tenant_id": tid, "deleted_at": None}
        cust = _db.customers.find_one({**q, "id": key[len(CLIENT_PREFIX):]}, {"_id": 0, "id": 1, "name": 1})
        if not cust:
            raise HTTPException(status_code=404, detail="Client introuvable")
        return {"key": key, "kind": "offre", "start_step": 1,
                "title": f"⭐ « {aim['name']} » vous attend"[:50],
                "message": f"À votre prochaine visite, une offre sur « {aim['name']} » vous attend sur présentation de votre carte."[:160],
                "segment": "all",
                "audience": {"label": cust.get("name") or "Ce client", "hint": "Un seul client", "ids": [cust["id"]]}}
    m = _KEY.fullmatch(key)
    if not m:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
    kind, r = m.groups()
    doc = _doc_or_404(tid, scope)
    aim = doc["actions"]["aimant"]
    if kind == "new":
        if aim["ref"] != r:
            raise HTTPException(status_code=404, detail="Modèle introuvable")
        ids = _live(tid, doc, scope, {})["new"]
        return {"key": key, "kind": "offre", "start_step": 1,
                "title": f"⭐ « {aim['name']} » pour votre 2e visite"[:50],
                "message": (f"Merci pour votre première visite ! Pour la deuxième, une offre sur « {aim['name']} » "
                            "vous attend sur présentation de votre carte.")[:160],
                "segment": "all",
                "audience": {"label": "Nouveaux clients", "hint": "Venus une fois, pas encore revenus", "ids": ids}}
    one = next((p for p in picks(doc.get("views") or {})[1] if p["ref"] == r), None)
    if not one:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
    ids = _live(tid, doc, scope, {r: set(one.get("keys") or [])})["one_shot"][r]
    return {"key": key, "kind": "offre", "start_step": 1,
            "title": f"⭐ Découvrez « {aim['name']} »"[:50],
            "message": f"Une offre sur « {aim['name']} » vous attend à votre prochaine visite, sur présentation de votre carte."[:160],
            "segment": "all",
            "audience": {"label": f"Ont pris « {one['name']} », pas revenus"[:60], "hint": "FidClic IA · Produits", "ids": ids}}


# ---------------------------------------------------------------------------
# the Copilote (features/copilot_tools « produits_retour »)
# ---------------------------------------------------------------------------
def tool(tid: str, scope) -> Dict[str, Any]:
    from features import plan_limits as PL
    from features import product_return as PR
    f = PL.tenant_features(tid)
    if not PL.allows(f, "advanced_analytics"):
        return {"statut": "L'analyse des produits est disponible avec Pro et Pro AI."}
    doc = PR.result(tid, store_key(scope))
    if not doc:
        return {"statut": "L'analyse des produits n'est pas encore prête : elle se prépare dans Analyses › Produits."}
    view = (doc.get("views") or {}).get("first") or {}
    prods = view.get("products") or []
    of = lambda b: [p for p in prods if p.get("bucket") == b]     # noqa: E731
    out: Dict[str, Any] = {"vue": "première visite du client", "fenetre_jours": doc.get("window_days"),
                           "pas_assez_de_donnees": [f"{p['name']} ({p['clients']}/{p.get('needed')})" for p in of("insufficient")],
                           "dans_presque_tous_les_paniers": [p["name"] for p in of("everywhere")]}
    if not full(tid):
        out.update({b: [p["name"] for p in of(k)] for b, k in (("aimants", "aimant"), ("neutres", "neutre"), ("one_shot", "one_shot"))})
        out["detail"] = "Les chiffres (sur 10 qui reviennent), les actions et les tests sont avec Pro AI."
        return out

    def row(p):
        return {"nom": p["name"], "sur_10_reviennent": p.get("back"),
                "entre": f"{p.get('back_low')} et {p.get('back_high')} sur 10", "fiabilite": p.get("fiabilite"),
                "jours_pour_revenir": p.get("days_back"), "ca_90_jours_eur": p.get("ca90")}
    out.update({"aimants": [row(p) for p in of("aimant")], "neutres": [p["name"] for p in of("neutre")],
                "one_shot": [row(p) for p in of("one_shot")]})
    act = shop_actions(tid, scope) or {}
    aim = act.get("aimant")
    out["actions"] = {"produit_a_proposer": aim["name"] if aim else None,
                      "one_shot_pas_revenus": [{"produit": o["name"], "clients": o["lapsed"]} for o in act.get("one_shot") or []],
                      "nouveaux_clients": act.get("new", 0)}
    names = {o["ref"]: o["name"] for o in act.get("one_shot") or []}
    if aim:
        names[aim["ref"]] = aim["name"]
    out["tests"] = [{"produit": names.get(r, ""), "resultat": test_text(t)} for r, t in (act.get("tests") or {}).items()]
    return out
