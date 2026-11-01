"""
Filleuls who visit another establishment than the one of their card.

A visit counts where it is scanned (multi-store rule): a PL-Monstre filleul
who comes to Liberté is in Liberté's CA FidClic, not PL-Monstre's. Right, but
unexplained it read as a bug (user, 2026-11-01: Apia's card is PL-Monstre's,
her 22 € were scanned at Liberté, PL-Monstre's Impact FidClic said 0 €).
Nothing here moves a figure — it says where the money went:
  • elsewhere(): Analyses › Impact FidClic of one establishment — what ITS
    filleuls spent in the others over the period;
  • stamp(): Parrainage › Derniers parrainages — the filleul's card store and
    the other stores it visited.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

_db = None
MAIN = "main"
FEW_IDS = 300          # up to this many clients: asked by client, through the index


def init(db):
    global _db
    _db = db


def _stores(tid: str) -> Dict[str, Any]:
    """{"names": {id: name}, "main": id} — open stores only; {} for a one-store shop."""
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "branches": 1}) or {}
    open_ = [b for b in t.get("branches") or [] if b.get("id") and b.get("status") != "closed"]
    if len(open_) < 2:
        return {}
    main = next((b["id"] for b in open_ if b.get("is_main") or b["id"] == MAIN), open_[0]["id"])
    return {"names": {b["id"]: b.get("name") or "Établissement" for b in open_}, "main": main}


def _store_of(value: Any, main: str) -> str:
    # a visit or a client with no store belongs to the main one (store_scope)
    return value or main


def visits_by_store(tid: str, ids: Iterable[str], start: Optional[datetime] = None,
                    end: Optional[datetime] = None, main: str = MAIN,
                    skip: Optional[List[Any]] = None) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """{customer_id: {store_id: {"visits", "revenue"}}} — one query. A few
    clients are read by client (the tenant + customer_id + visit_time index,
    store_scope.init); many over a period, by period (tenant + visit_time),
    kept here by client — never a query carrying thousands of ids.
    `skip` leaves out the visits of those store values."""
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}
    q: Dict[str, Any] = {"tenant_id": tid}
    if start or end:
        q["visit_time"] = {**({"$gte": start} if start else {}), **({"$lte": end} if end else {})}
    if len(ids) <= FEW_IDS or "visit_time" not in q:
        q["customer_id"] = {"$in": ids}
    if skip:
        q["branch_id"] = {"$nin": list(skip)}
    wanted = set(ids)
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for v in _db.visits.find(q, {"_id": 0, "customer_id": 1, "branch_id": 1, "amount_paid": 1}):
        if v.get("customer_id") not in wanted:
            continue
        cell = out.setdefault(v["customer_id"], {}).setdefault(_store_of(v.get("branch_id"), main),
                                                                {"visits": 0, "revenue": 0.0})
        cell["visits"] += 1
        cell["revenue"] = round(cell["revenue"] + float(v.get("amount_paid") or 0), 2)
    return out


def _eur(n: float) -> str:
    whole = round(float(n or 0))
    return f"{whole:,}".replace(",", " ") + " €"


def elsewhere(scope, start: datetime, end: datetime) -> Optional[Dict[str, Any]]:
    """What this establishment's filleuls spent in the others over the period.
    None when there is nothing to say: all establishments chosen (everything
    is already counted), a one-store shop, or no such visit."""
    if scope is None or scope.is_all:
        return None
    st = _stores(scope.tenant_id)
    if not st:
        return None
    from features import store_scope as S, fidclic_impact as FI
    home = S.home_customer_ids(scope) or set()
    referees = FI._referees(scope.tenant_id, home)
    here = set(scope.ids or [])
    per: Dict[str, Dict[str, Any]] = {}
    who = set()
    if not referees:
        return None
    for cid, stores in visits_by_store(scope.tenant_id, referees, start, end, st["main"],
                                       skip=S._branch_values(scope)).items():
        for sid, cell in stores.items():
            if sid in here or sid not in st["names"]:
                continue
            row = per.setdefault(sid, {"id": sid, "name": st["names"][sid], "revenue": 0.0, "visits": 0})
            row["revenue"] = round(row["revenue"] + cell["revenue"], 2)
            row["visits"] += cell["visits"]
            who.add(cid)
    if not per:
        return None
    rows = sorted(per.values(), key=lambda r: (-r["revenue"], -r["visits"], r["name"]))
    visits = sum(r["visits"] for r in rows)
    # An account limited to some establishments sees the link — where its
    # filleuls went, how often — not the € of a store it does not cover
    # (user, 2026-11-01).
    covered = set(scope.allowed or [])
    hidden = False
    for r in rows:
        if r["id"] not in covered:
            r["revenue"], hidden = None, True
    revenue = None if hidden else round(sum(r["revenue"] for r in rows), 2)
    where = ", ".join(r["name"] for r in rows)
    n = len(who)
    amount = "" if hidden else f"{_eur(revenue)}, "
    note = (f"{n} filleul{'s' if n > 1 else ''} dont la carte est de cet établissement "
            f"{'sont passés' if n > 1 else 'est passé'} dans un autre : {visits} visite{'s' if visits > 1 else ''}, "
            f"{amount}à {where}. Une visite est comptée dans l'établissement où elle passe en caisse : "
            f"{'elle est' if visits == 1 else 'elles sont'} dans le CA FidClic de {where}, pas ici.")
    return {"revenue": revenue, "visits": visits, "clients": n, "stores": rows, "note": note}


def stamp(tid: str, rows: List[Dict[str, Any]], people: Dict[str, Dict[str, Any]],
          referee_of: Dict[str, str], covered: Optional[Iterable[str]] = None) -> None:
    """Adds to each table row's filleul its card store and the other stores it
    visited ({"store", "visits", "revenue"}, all time). `referee_of` maps a
    row id to its filleul's customer id. A one-store shop gets None / [].
    `covered`: the stores the account covers — the € of any other is None."""
    st = _stores(tid)
    for r in rows:
        r["filleul"]["card_store"] = None
        r["filleul"]["elsewhere"] = []
    if not st:
        return
    ids = [referee_of.get(r["id"]) for r in rows]
    seen = visits_by_store(tid, [i for i in ids if i], main=st["main"])
    covered = None if covered is None else set(covered)
    for r, cid in zip(rows, ids):
        person = people.get(cid or "") or {}
        if not person:
            continue
        card = _store_of(person.get("branch_id"), st["main"])
        r["filleul"]["card_store"] = st["names"].get(card)
        r["filleul"]["elsewhere"] = [
            {"store": st["names"][sid], "visits": c["visits"],
             "revenue": c["revenue"] if covered is None or sid in covered else None}
            for sid, c in sorted((seen.get(cid) or {}).items(), key=lambda kv: -kv[1]["revenue"])
            if sid != card and sid in st["names"]]
