"""
Produits qui font revenir — which products bring clients back, and which don't.

User, 2026-10-28: « koun se products purchase krne k baad customers sabse
zyada return karte hai, and kounse products k baad nhi ». Two corrections
shaped the method:

    · a basket of X + Y + Z: each product gets its fair share WITH the others
      counted — never "X alone" nor "with X vs without X"
    · December and the promos are not thrown away: they are counted (a tag),
      so a product sold at a bad season is not blamed for the season

THE METHOD — « la dal »
    Every purchase occasion (a client's products of one Paris day) old enough
    to have had its chance is an example: did the client come back (any
    store, a later day) within the window? A ridge logistic regression weighs
    every product at once, with the month, the promo of the day (an offer or a
    reward used), the store and — over all visits — how many times the client
    had come. The ridge pulls a product with few buyers towards the average,
    so 3 lucky buyers never make a hero. Pure Python (no numpy on Vercel):
    the rows are sparse — a few products each — so a shop of a few thousand
    occasions fits in well under a second.

    Each product is then read on its own buyers: their return rate as it is,
    and as it would be without the product (the model's other terms kept) —
    the ratio of the two, with a 90 % range from the product's standard error.

        Aimant    the whole range above 1 and the ratio ≥ 1.1
        One-shot  the whole range below 1 and the ratio ≤ 0.9
        Neutre    the rest
        everywhere  fewer than MIN_BUYERS baskets WITHOUT it: nothing to compare
        insufficient  fewer than MIN_BUYERS clients: no verdict, « 12/30 »

    Two products that sell together ≥ 90 % of the time each are one entry
    (« Gel + Cire », effet commun): no data can tell them apart. The commonest
    pairs that also sell apart get a combo term (« ensemble, ils font
    revenir plus »).

TWO VIEWS
    first   the client's first purchase — which product makes a loyal client
            (only clients who joined inside the history read, so a « first »
            is really their first)
    all     every purchase, regulars included

THE WINDOW
    The shop's rhythm (client_brain.usual_gap) × WINDOW_X_RHYTHM, between 7
    and 180 days — or the owner's own days (decision 2026-10-28).

WHERE IT LIVES
    `product_return`: one document per shop and store (« all » = the whole
    shop; one per establishment when there are several), rebuilt each week by
    the tick through features/ai_jobs, or on « Recalculer ». The page reads
    the document; it never computes. Only counts and rates are kept — never a
    client id or name.

Plans (decision 2026-10-28): Starter locked (the advanced_analytics path
rule), Pro the buckets only, Pro AI everything.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import require_role, TokenData
from features import store_scope as S

router = APIRouter(tags=["product_return"])
_db = None

PARIS = ZoneInfo("Europe/Paris")
MIN_BUYERS = 30              # clients behind a verdict
MIN_MODEL = 5                # under this, a product is not even weighed
MAX_UNITS = 120              # products weighed one by one (the commonest)
MAX_COMBOS = 5
TOGETHER = 0.9               # « toujours ensemble »: each in ≥ 90 % of the other's baskets
RIDGE = 2.0
Z90 = 1.645
AIMANT, ONE_SHOT = 1.1, 0.9
WINDOW_X_RHYTHM = 2          # « wapas aaya » = within twice the shop's rhythm
WINDOW_MIN, WINDOW_MAX = 7, 180
CA_DAYS = 90
HISTORY_DAYS = 730
COVERAGE_DAYS = 90
MONTH_MIN = 30
REBUILD_EVERY = timedelta(days=7)
DUE_PER_TICK = 20
ALL = "all"
READERS = ["business_owner", "administrateur", "manager"]
BUCKET_ORDER = {"aimant": 0, "neutre": 1, "one_shot": 2, "everywhere": 3, "insufficient": 4}
NTH = ["1", "2-4", "5+", "ancien"]


def init(db):
    global _db
    _db = db
    try:
        db.product_return.create_index([("tenant_id", 1), ("store", 1)], unique=True)
    except Exception:
        pass
    from features import ai_jobs as JOBS
    JOBS.register("product_return", _step)


# ---------------------------------------------------------------------------
# small pieces
# ---------------------------------------------------------------------------
def _aware(d: Any) -> Optional[datetime]:
    if not isinstance(d, datetime):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def paris_day(d: datetime) -> date:
    return _aware(d).astimezone(PARIS).date()


def window_for(usual_gap: float, custom: Any) -> Tuple[int, str]:
    """(days, « personnalise » | « rythme »)."""
    if custom is not None and not isinstance(custom, bool):
        try:
            v = int(custom)
        except (TypeError, ValueError):
            v = 0
        if WINDOW_MIN <= v <= WINDOW_MAX:
            return v, "personnalise"
    days = int(round(WINDOW_X_RHYTHM * float(usual_gap or 0)))
    return max(WINDOW_MIN, min(WINDOW_MAX, days)), "rythme"


def _sig(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _cholesky(a: List[List[float]]) -> List[List[float]]:
    n = len(a)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        Li = L[i]
        for j in range(i + 1):
            Lj = L[j]
            s = a[i][j] - sum(Li[k] * Lj[k] for k in range(j))
            if i == j:
                Li[i] = math.sqrt(max(s, 1e-12))
            else:
                Li[j] = s / Lj[j]
    return L


def _solve(L: List[List[float]], b: List[float]) -> List[float]:
    n = len(L)
    y = [0.0] * n
    for i in range(n):
        y[i] = (b[i] - sum(L[i][k] * y[k] for k in range(i))) / L[i][i]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (y[i] - sum(L[k][i] * x[k] for k in range(i + 1, n))) / L[i][i]
    return x


def _hessian(rows, beta, p, ridge):
    H = [[0.0] * p for _ in range(p)]
    g = [0.0] * p
    for act, y in rows:
        idx = [0] + act
        pr = _sig(sum(beta[i] for i in idx))
        w = pr * (1.0 - pr)
        r = (1.0 if y else 0.0) - pr
        for a in idx:
            g[a] += r
            Ha = H[a]
            for b in idx:
                Ha[b] += w
    H[0][0] += 1e-9
    for j in range(1, p):
        H[j][j] += ridge
        g[j] -= ridge * beta[j]
    return H, g


def fit(rows: List[Tuple[List[int], bool]], p: int, ridge: float = RIDGE,
        iters: int = 30) -> Tuple[List[float], List[float]]:
    """Ridge logistic regression on sparse 0/1 rows (index 0 = the intercept,
    never penalised; a row lists its other active indices). Returns
    (coefficients, standard errors)."""
    beta = [0.0] * p
    if not rows:
        return beta, [float("inf")] * p
    for _ in range(iters):
        H, g = _hessian(rows, beta, p, ridge)
        step = _solve(_cholesky(H), g)
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-7:
            break
    L = _cholesky(_hessian(rows, beta, p, ridge)[0])
    se = []
    for j in range(p):
        e = [0.0] * p
        e[j] = 1.0
        se.append(math.sqrt(max(_solve(L, e)[j], 0.0)))
    return beta, se


# ---------------------------------------------------------------------------
# the occasions
# ---------------------------------------------------------------------------
def _store_of(branch: Any) -> str:
    return "main" if branch in (None, "", "main") else str(branch)


class _Catalog:
    """A line → its product: by id, else by name (lines written before ids,
    products since deleted keep their name)."""

    def __init__(self, items: List[Dict[str, Any]]):
        self.names: Dict[str, str] = {}
        self.order: Dict[str, Tuple[int, str]] = {}
        self.by_name: Dict[str, str] = {}
        for n, i in enumerate(items):
            pid = str(i.get("id") or "")
            nm = str(i.get("name") or "").strip()
            if not pid or not nm:
                continue
            self.names[pid] = nm
            self.order[pid] = (n, nm.lower())
            self.by_name.setdefault(nm.lower(), pid)

    def key(self, line: Dict[str, Any]) -> Optional[str]:
        pid = str(line.get("item_id") or "")
        if pid in self.names:
            return pid
        nm = str(line.get("name") or "").strip()
        if not nm:
            return None
        hit = self.by_name.get(nm.lower())
        if hit:
            return hit
        k = "n:" + nm.lower()
        if k not in self.names:
            self.names[k] = nm
            self.order[k] = (10 ** 6, nm.lower())
        return k


def _occasions(tid: str, now: datetime, cat: _Catalog):
    """{client: [occasion]} sorted by day, the promo days, the coverage."""
    start = now - timedelta(days=HISTORY_DAYS)
    per: Dict[str, Dict[date, Dict[str, Any]]] = defaultdict(dict)
    cov: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    cov_from = now - timedelta(days=COVERAGE_DAYS)
    for v in _db.visits.find({"tenant_id": tid, "visit_time": {"$gte": start, "$lte": now}},
                             {"_id": 0, "customer_id": 1, "visit_time": 1, "amount_paid": 1,
                              "items": 1, "branch_id": 1}):
        at = _aware(v.get("visit_time"))
        cid = v.get("customer_id")
        if not at or not cid:
            continue
        store = _store_of(v.get("branch_id"))
        keys = {k for k in (cat.key(line) for line in v.get("items") or [] if isinstance(line, dict)) if k}
        if at >= cov_from:
            for s in (ALL, store):
                cov[s][0] += 1
                cov[s][1] += bool(keys)
        day = paris_day(at)
        occ = per[cid].get(day)
        if occ is None:
            per[cid][day] = {"day": day, "at": at, "store": store, "items": set(keys),
                             "amount": float(v.get("amount_paid") or 0)}
        else:
            if at < occ["at"]:
                occ["at"] = at
                if keys or not occ["items"]:
                    occ["store"] = store
            elif keys and not occ["items"]:
                occ["store"] = store
            occ["items"] |= keys
            occ["amount"] += float(v.get("amount_paid") or 0)
    promo: Set[Tuple[str, date]] = set()
    for coll, field in (("offer_uses", "used_at"), ("rewards_redeemed", "redeemed_at")):
        for r in _db[coll].find({"tenant_id": tid, field: {"$gte": start}}, {"_id": 0, "customer_id": 1, field: 1}):
            at = _aware(r.get(field))
            if at and r.get("customer_id"):
                promo.add((r["customer_id"], paris_day(at)))
    timelines = {cid: [days[d] for d in sorted(days)] for cid, days in per.items()}
    return timelines, promo, cov


def _joined(tid: str) -> Dict[str, Optional[datetime]]:
    out: Dict[str, Optional[datetime]] = {}
    for c in _db.customers.find({"tenant_id": tid}, {"_id": 0, "id": 1, "created_at": 1,
                                                     "join_date": 1, "member_since": 1}):
        at = None
        for f in ("created_at", "join_date", "member_since"):
            at = _aware(c.get(f))
            if at:
                break
        out[c.get("id")] = at
    return out


def _examples(timelines, promo, joined, now: datetime, window: int) -> Dict[str, List[Dict[str, Any]]]:
    today = paris_day(now)
    start = now - timedelta(days=HISTORY_DAYS)
    out: Dict[str, List[Dict[str, Any]]] = {"first": [], "all": []}
    for cid, occs in timelines.items():
        j = joined.get(cid)
        known_start = j is not None and j >= start if j else occs[0]["at"] >= start + timedelta(days=60)
        for i, o in enumerate(occs):
            if not o["items"] or (today - o["day"]).days < window:
                continue
            nxt = occs[i + 1] if i + 1 < len(occs) else None
            gap = (nxt["day"] - o["day"]).days if nxt else None
            ca90 = None
            if (today - o["day"]).days >= CA_DAYS:
                ca90 = sum(x["amount"] for x in occs[i + 1:] if (x["day"] - o["day"]).days <= CA_DAYS)
            nth = ("ancien" if not known_start else "1" if i == 0 else "2-4" if i < 4 else "5+")
            ex = {"cid": cid, "items": o["items"], "store": o["store"], "month": o["day"].month,
                  "promo": (cid, o["day"]) in promo, "nth": nth,
                  "y": gap is not None and gap <= window, "gap": gap, "ca90": ca90}
            out["all"].append(ex)
            if i == 0 and known_start:
                out["first"].append(ex)
    return out


# ---------------------------------------------------------------------------
# one view of one store
# ---------------------------------------------------------------------------
def _groups(exs: List[Dict[str, Any]], cat: _Catalog) -> Tuple[List[Tuple[str, ...]], Dict[str, int]]:
    """The products weighed, merged when they always sell together."""
    count: Dict[str, int] = defaultdict(int)
    pair: Dict[Tuple[str, str], int] = defaultdict(int)
    for e in exs:
        its = sorted(e["items"])
        for a in its:
            count[a] += 1
        for x in range(len(its)):
            for y in range(x + 1, len(its)):
                pair[(its[x], its[y])] += 1
    keep = sorted([k for k, n in count.items() if n >= MIN_MODEL], key=lambda k: -count[k])[:MAX_UNITS]
    kept = set(keep)
    parent = {k: k for k in keep}

    def root(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for (a, b), n in pair.items():
        if a in kept and b in kept and n >= TOGETHER * count[a] and n >= TOGETHER * count[b]:
            parent[root(a)] = root(b)
    members: Dict[str, List[str]] = defaultdict(list)
    for k in keep:
        members[root(k)].append(k)
    groups = [tuple(sorted(m, key=lambda k: cat.order.get(k, (10 ** 7, k)))) for m in members.values()]
    groups.sort(key=lambda g: cat.order.get(g[0], (10 ** 7, g[0])))
    return groups, count


def _analyse(exs: List[Dict[str, Any]], cat: _Catalog, stores: List[str], nth: bool) -> Dict[str, Any]:
    n = len(exs)
    base = sum(e["y"] for e in exs) / n if n else 0.0
    out: Dict[str, Any] = {"n": n, "base_rate": round(base, 3), "products": [], "combos": [], "months": [],
                           "controls": {"promo": sum(e["promo"] for e in exs)}}
    if not n:
        return out
    groups, count = _groups(exs, cat)
    unit_of = {k: u for u, g in enumerate(groups) for k in g}
    # combos: common pairs that also sell apart
    has: List[Set[int]] = [{unit_of[k] for k in e["items"] if k in unit_of} for e in exs]
    clients: Dict[int, Set[str]] = defaultdict(set)
    for e, us in zip(exs, has):
        for u in us:
            clients[u].add(e["cid"])
    n_unit = defaultdict(int)
    n_pair: Dict[Tuple[int, int], int] = defaultdict(int)
    for us in has:
        su = sorted(us)
        for u in su:
            n_unit[u] += 1
        for x in range(len(su)):
            for y in range(x + 1, len(su)):
                n_pair[(su[x], su[y])] += 1
    big = {u for u in range(len(groups)) if len(clients[u]) >= MIN_BUYERS and n - n_unit[u] >= MIN_BUYERS}
    combos = sorted([(c, ab) for ab, c in n_pair.items()
                     if ab[0] in big and ab[1] in big and c >= MIN_BUYERS
                     and n_unit[ab[0]] - c >= MIN_BUYERS and n_unit[ab[1]] - c >= MIN_BUYERS],
                    key=lambda x: -x[0])[:MAX_COMBOS]
    combos = [ab for _, ab in combos]
    # the columns: 0 intercept · units · combos · months · promo · stores · nth
    U, C = len(groups), len(combos)
    col_month = 1 + U + C
    col_promo = col_month + 12
    col_store = {s: col_promo + 1 + i for i, s in enumerate(stores if len(stores) > 1 else [])}
    col_nth = {b: col_promo + 1 + len(col_store) + i for i, b in enumerate(NTH if nth else [])}
    p = col_promo + 1 + len(col_store) + len(col_nth)
    rows = []
    for e, us in zip(exs, has):
        act = [1 + u for u in us]
        act += [1 + U + ci for ci, (a, b) in enumerate(combos) if a in us and b in us]
        act.append(col_month + e["month"] - 1)
        if e["promo"]:
            act.append(col_promo)
        if e["store"] in col_store:
            act.append(col_store[e["store"]])
        if e["nth"] in col_nth:
            act.append(col_nth[e["nth"]])
        rows.append((sorted(set(act)), e["y"]))
    beta, se = fit(rows, p)
    eta = [sum(beta[i] for i in [0] + act) for act, _ in rows]

    for u, g in enumerate(groups):
        name = " + ".join(cat.names.get(k, k) for k in g)
        n_cli = len(clients[u])
        entry: Dict[str, Any] = {"name": name, "clients": n_cli, "together": len(g) > 1}
        if n_cli < MIN_BUYERS:
            out["products"].append({**entry, "bucket": "insufficient", "needed": MIN_BUYERS})
            continue
        idx = [i for i, us in enumerate(has) if u in us]
        b = beta[1 + u]
        minus = [eta[i] - b for i in idx]
        without = sum(_sig(x) for x in minus) / len(idx)
        with_ = lambda bb: sum(_sig(x + bb) for x in minus) / len(idx)
        w_mid, w_lo, w_hi = with_(b), with_(b - Z90 * se[1 + u]), with_(b + Z90 * se[1 + u])
        ratio = w_mid / without if without else 1.0
        lo, hi = (w_lo / without, w_hi / without) if without else (1.0, 1.0)
        everywhere = n - n_unit[u] < MIN_BUYERS
        if everywhere:
            bucket = "everywhere"
        elif lo > 1 and ratio >= AIMANT:
            bucket = "aimant"
        elif hi < 1 and ratio <= ONE_SHOT:
            bucket = "one_shot"
        else:
            bucket = "neutre"
        width = hi - lo
        gaps = [exs[i]["gap"] for i in idx if exs[i]["y"]]
        cas = [exs[i]["ca90"] for i in idx if exs[i]["ca90"] is not None]
        entry.update({
            "bucket": bucket, "raw_rate": round(sum(exs[i]["y"] for i in idx) / len(idx), 3),
            "rate": round(w_mid, 3), "rate_without": round(without, 3),
            "ratio": round(ratio, 2), "ratio_low": round(lo, 2), "ratio_high": round(hi, 2),
            "back": round(10 * w_mid), "back_low": round(10 * w_lo), "back_high": round(10 * w_hi),
            "fiabilite": "haute" if width <= 0.35 else "moyenne" if width <= 0.7 else "faible",
            "days_back": int(median(gaps)) if gaps else None,
            "ca90": round(sum(cas) / len(cas), 2) if cas else None,
        })
        out["products"].append(entry)

    # products sold too rarely to be weighed
    weighed = {k for g in groups for k in g}
    rare_clients: Dict[str, Set[str]] = defaultdict(set)
    for e in exs:
        for k in e["items"]:
            if k not in weighed:
                rare_clients[k].add(e["cid"])
    for k, cl in rare_clients.items():
        out["products"].append({"name": cat.names.get(k, k), "clients": len(cl), "together": False,
                                "bucket": "insufficient", "needed": MIN_BUYERS})
    out["products"].sort(key=lambda x: (BUCKET_ORDER[x["bucket"]], -(x.get("ratio") or 0), -x["clients"]))

    for ci, (a, b) in enumerate(combos):
        bc, s = beta[1 + U + ci], se[1 + U + ci]
        if bc - Z90 * s > 0:
            effect = "plus"
        elif bc + Z90 * s < 0:
            effect = "moins"
        else:
            continue
        idx = [i for i, us in enumerate(has) if a in us and b in us]
        out["combos"].append({
            "a": " + ".join(cat.names.get(k, k) for k in groups[a]),
            "b": " + ".join(cat.names.get(k, k) for k in groups[b]),
            "effect": effect, "n": len(idx),
            "rate": round(sum(_sig(eta[i]) for i in idx) / len(idx), 3)})

    by_month: Dict[int, List[int]] = defaultdict(lambda: [0, 0])
    for e in exs:
        by_month[e["month"]][0] += 1
        by_month[e["month"]][1] += e["y"]
    out["months"] = [{"month": m, "n": c[0], "rate": round(c[1] / c[0], 3)}
                     for m, c in sorted(by_month.items()) if c[0] >= MONTH_MIN]
    return out


# ---------------------------------------------------------------------------
# the whole shop
# ---------------------------------------------------------------------------
def compute(tid: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Rebuild the shop's documents (one per store, « all » for the shop)."""
    from features import client_brain as CB
    now = _aware(now) or datetime.now(timezone.utc)
    tenant = _db.tenants.find_one({"id": tid}, {"_id": 0, "product_return_window_days": 1}) or {}
    gap, _src = CB.usual_gap(tid, fresh=True)
    window, source = window_for(gap, tenant.get("product_return_window_days"))
    cat_doc = _db.tenant_catalog.find_one({"tenant_id": tid}, {"_id": 0, "items": 1}) or {}
    cat = _Catalog(cat_doc.get("items") or [])
    timelines, promo, cov = _occasions(tid, now, cat)
    exs = _examples(timelines, promo, _joined(tid), now, window)
    stores = sorted({e["store"] for e in exs["all"]} | {k for k in cov if k != ALL})
    keys = [ALL] + (stores if len(stores) > 1 else [])
    for key in keys:
        views = {}
        for view in ("first", "all"):
            sub = exs[view] if key == ALL else [e for e in exs[view] if e["store"] == key]
            views[view] = _analyse(sub, cat, stores if key == ALL else [key], nth=(view == "all"))
        c = cov.get(key, [0, 0])
        doc = {"tenant_id": tid, "store": key, "built_at": now, "window_days": window,
               "window_source": source, "usual_gap": gap,
               "coverage": {"total": c[0], "with_items": c[1], "pct": round(100 * c[1] / c[0]) if c[0] else 0},
               "views": views}
        _db.product_return.replace_one({"tenant_id": tid, "store": key}, doc, upsert=True)
    return {"stores": keys, "window_days": window}


def result(tid: str, store: str = ALL) -> Optional[Dict[str, Any]]:
    doc = _db.product_return.find_one({"tenant_id": tid, "store": store}, {"_id": 0})
    if not doc and store != ALL:
        doc = _db.product_return.find_one({"tenant_id": tid, "store": ALL}, {"_id": 0})
    return doc


def _step(job: Dict[str, Any], deadline: float) -> bool:
    """features/ai_jobs « product_return »: one shop, in one go."""
    compute(job["tenant_id"], _aware(job.get("now")))
    return True


def due(now: Optional[datetime] = None) -> List[str]:
    """The tick: a shop with products sold gets its figures once a week."""
    from features import ai_jobs as JOBS
    now = _aware(now) or datetime.now(timezone.utc)
    started: List[str] = []
    for t in _db.tenants.find({}, {"_id": 0, "id": 1}):
        tid = t.get("id")
        if not tid:
            continue
        doc = _db.product_return.find_one({"tenant_id": tid, "store": ALL}, {"_id": 0, "built_at": 1})
        built = _aware((doc or {}).get("built_at"))
        if built and now - built < REBUILD_EVERY:
            continue
        if not _db.visits.find_one({"tenant_id": tid, "items.0": {"$exists": True}}, {"_id": 1}):
            continue
        job, created = JOBS.start("product_return", tid, by="tick", now=now)
        if created:
            started.append(tid)
            if len(started) >= DUE_PER_TICK:
                break
    return started


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------
BUCKET_FIELDS = ("name", "bucket", "clients", "needed", "together")


def _shape(view: Dict[str, Any], level: str) -> Dict[str, Any]:
    if level == "full":
        return view
    return {"n": view.get("n", 0),
            "products": [{k: p[k] for k in BUCKET_FIELDS if k in p} for p in view.get("products") or []]}


def _running(tid: str) -> bool:
    return bool(_db.ai_jobs.find_one({"kind": "product_return", "tenant_id": tid,
                                      "status": {"$in": ["queued", "running"]}}, {"_id": 1}))


@router.get("/api/owner/analyses/produits-retour")
def produits_retour(request: Request = None, view: str = "first",
                    token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    from features import plan_limits as PL
    from features import ai_jobs as JOBS
    tid = token_data.tenant_id
    f = PL.tenant_features(tid)
    if not PL.allows(f, "advanced_analytics"):
        raise HTTPException(status_code=403, detail=PL.locked(f, "advanced_analytics"))
    level = "full" if (f.get("ai_level") or "none") == "advanced" else "buckets"
    view = view if view in ("first", "all") else "first"
    scope = S.resolve(token_data, request)
    keys = [ALL] if scope.is_all else list(scope.ids or [])
    docs = [(k, result(tid, k)) for k in keys]
    if not any(d for _, d in docs):
        job, _ = JOBS.start("product_return", tid, by="page")
        return {"status": "pending", "level": level, "view": view}

    def one(doc):
        return {"window_days": doc["window_days"], "window_source": doc["window_source"],
                "usual_gap": doc.get("usual_gap"), "coverage": doc["coverage"],
                "built_at": _aware(doc.get("built_at")).isoformat() if doc.get("built_at") else None,
                "views": {view: _shape(doc["views"][view], level)}}

    first = next(d for _, d in docs if d)
    out = {"status": "ready", "level": level, "view": view, "refreshing": _running(tid),
           "can_edit": _may_edit(token_data, request),
           "min_buyers": MIN_BUYERS, **one(first)}
    if len(docs) > 1:
        out["stores"] = [{"store": k, "name": scope.names.get(k, k), **one(d)} for k, d in docs if d]
    return out


class WindowIn(BaseModel):
    days: Optional[int] = None


def _may_edit(token_data: TokenData, request: Request = None) -> bool:
    """« Modifier » on Analyses (Équipe & accès) — the owner always. Reading
    takes « Voir »; changing the shop's window or recomputing takes this
    (pentest of #417: a manager who only saw Analyses could do both)."""
    from features import role_perms as RP
    return RP.may(token_data, "analytics", "edit", request)


def _need_edit(token_data: TokenData, request: Request = None) -> None:
    if not _may_edit(token_data, request):
        raise HTTPException(status_code=403, detail="Accès non autorisé : il faut « Modifier » sur Analyses.")


@router.put("/api/owner/analyses/produits-retour/fenetre")
def set_window(body: WindowIn, request: Request = None,
               token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    from features import ai_jobs as JOBS
    _need_edit(token_data, request)
    if body.days is not None and not (WINDOW_MIN <= body.days <= WINDOW_MAX):
        raise HTTPException(status_code=400,
                            detail=f"Choisissez entre {WINDOW_MIN} et {WINDOW_MAX} jours.")
    if body.days is None:
        _db.tenants.update_one({"id": token_data.tenant_id}, {"$unset": {"product_return_window_days": ""}})
    else:
        _db.tenants.update_one({"id": token_data.tenant_id}, {"$set": {"product_return_window_days": int(body.days)}})
    job, _ = JOBS.start("product_return", token_data.tenant_id, by="owner")
    return {"days": body.days, "job_id": job["id"]}


@router.post("/api/owner/analyses/produits-retour/recalculer")
def recompute(request: Request = None, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    from features import ai_jobs as JOBS
    _need_edit(token_data, request)
    job, _ = JOBS.start("product_return", token_data.tenant_id, by="owner")
    return {"job_id": job["id"], "status": job["status"]}
