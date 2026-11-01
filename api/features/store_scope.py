"""
Store scope — which establishments a request is about.

The establishment dropdown under the FidClic logo sends the chosen
establishment on every call, in the X-FidClic-Store header ("all" or an
establishment id). This module turns that choice and the caller's role into
the set of establishments the data must be limited to:

    Propriétaire    any one establishment, or all of them.
    Administrateur  any one of ITS establishments, or all of its own —
                    never one it was not given.
    Manager/Employé its one establishment, whatever the header says.
An establishment the caller does not cover is never granted: the request
falls back to the caller's own establishments.

A data page asks `resolve(token, request)` once, then filters with
`visit_filter(scope)` (visits carry the branch_id of the till that scanned
them) and `customer_ids(scope)` (a client belongs to an establishment it
has visited, or where it signed up). `scope.ids is None` means "the whole
shop" — no filter at all, visits scanned without an establishment included.

Pages are brought over one by one; each one that uses this module opens to
administrateurs and to managers covering part of the shop (partial_ok on
its endpoints). See features/team_access.py for who covers what.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from fastapi import HTTPException, Request

from auth import TokenData

HEADER = "X-FidClic-Store"
ALL = "all"
_db = None


def init(db):
    global _db
    _db = db
    # « this store's clients » (customer_ids) reads the visits by store;
    # « this client's visits » (referral_stores, client pages) by client
    # (user, 2026-11-01: Analyses for one store took ~5 s)
    try:
        db.visits.create_index([("tenant_id", 1), ("branch_id", 1), ("customer_id", 1)])
        db.visits.create_index([("tenant_id", 1), ("customer_id", 1), ("visit_time", 1)])
    except Exception:
        pass


@dataclass
class Scope:
    tenant_id: str
    ids: Optional[List[str]]            # None = the whole shop
    allowed: List[str] = field(default_factory=list)
    all_ids: List[str] = field(default_factory=list)
    names: Dict[str, str] = field(default_factory=dict)
    # what this request already worked out (its clients, its home clients):
    # a Scope lives one request, so nothing outlives it
    memo: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def is_all(self) -> bool:
        return self.ids is None

    @property
    def single(self) -> Optional[str]:
        return self.ids[0] if self.ids and len(self.ids) == 1 else None

    @property
    def key(self) -> str:
        """A stable name for settings kept per establishment (e.g. the goal)."""
        return ALL if self.ids is None else ",".join(sorted(self.ids))

    def describe(self) -> Dict[str, Any]:
        return {"ids": self.ids, "all": self.is_all,
                "label": "Tous les établissements" if self.is_all
                else ", ".join(self.names.get(i, i) for i in self.ids)}


def resolve(token: TokenData, request: Optional[Request] = None, requested: Optional[str] = None) -> Scope:
    from features import team_access as T
    stores = T.stores(token.tenant_id)
    all_ids = [s["id"] for s in stores]
    names = {s["id"]: s["name"] for s in stores}
    email = getattr(token, "email", None)
    me = (_db.users.find_one({"email": email}, {"_id": 0, "role": 1, "tenant_id": 1, "branch_ids": 1}) or {}) if email else {}
    allowed = T._covered(me, all_ids) if me else []
    # The owner — and the server calling a feature on its own behalf (the
    # Copilote preparing a step: a token with no account behind it) — covers
    # every establishment.
    if getattr(token, "role", None) == "business_owner" or not email:
        allowed = list(all_ids)
    if not allowed:
        raise HTTPException(status_code=403, detail="Aucun établissement ne vous est attribué.")
    if requested is None and request is not None:
        # An explicit ?store= wins over the menu's header: a link that names
        # its establishment (an alert of the bell about Plumereau) opens that
        # establishment's clients, whatever the menu shows.
        requested = request.query_params.get("store") or request.headers.get(HEADER)
    requested = (requested or "").strip()
    if requested and requested != ALL and requested not in allowed:
        # A store since removed, or one this account does not cover (a choice
        # left in the browser by someone else): never widen — fall back to the
        # caller's own establishments.
        requested = ""
    if requested and requested != ALL:
        ids: Optional[List[str]] = [requested]
    else:
        ids = None if set(all_ids) <= set(allowed) else list(allowed)
    # A shop with a single establishment has nothing to split.
    if ids is not None and set(all_ids) <= set(ids):
        ids = None
    return Scope(tenant_id=token.tenant_id, ids=ids, allowed=allowed, all_ids=all_ids, names=names)


def _branch_values(scope: Scope) -> List[Any]:
    # "main" is the shop's own establishment: its visits from before it had
    # branches carry no branch_id, later ones carry "main" (the id it keeps
    # when its first point de vente is added — features/etablissement.py).
    vals: List[Any] = []
    for i in scope.ids or []:
        vals.extend([None, "main"] if i == "main" else [i])
    return vals


def visit_filter(scope: Scope) -> Dict[str, Any]:
    return {} if scope.is_all else {"branch_id": {"$in": _branch_values(scope)}}


def customer_ids(scope: Scope) -> Optional[Set[str]]:
    """Clients of these establishments: those who visited one, or signed up at
    one. None = everyone (the whole shop)."""
    if scope.is_all:
        return None
    if "clients" not in scope.memo:
        vals = _branch_values(scope)
        ids = set(_db.visits.distinct("customer_id", {"tenant_id": scope.tenant_id, "branch_id": {"$in": vals}}))
        ids.update(_db.customers.distinct("id", {"tenant_id": scope.tenant_id, "branch_id": {"$in": vals}}))
        ids.discard(None)
        scope.memo["clients"] = frozenset(ids)
    return set(scope.memo["clients"])          # the caller's own copy


def customer_filter(scope: Scope) -> Dict[str, Any]:
    """The clients these establishments count. A deleted client (Clients ›
    Supprimer, the inactive purge) is in no count or list (user, 2026-10-16:
    deleted, the dashboard and Analyses still counted it); its past visits
    and revenue stay — those are read from `visits`."""
    ids = customer_ids(scope)
    base: Dict[str, Any] = {"tenant_id": scope.tenant_id, "deleted_at": None}
    if ids is not None:
        base["id"] = {"$in": list(ids)}
    return base


# ---------------------------------------------------------------------------
# Sending (multi-store PR5, user 2026-10-12: « jo store upar selected hoga,
# campaigns and offers bhi usi k customers ko jaayenge »): only a client's
# HOME store (customers.branch_id, the store of its signup link) messages it —
# a client who only visited another store is not that store's to contact.
# ---------------------------------------------------------------------------
def home_customer_ids(scope: Scope) -> Optional[Set[str]]:
    """Members of these establishments (their home store). None = everyone."""
    if scope.is_all:
        return None
    if "home" in scope.memo:
        return set(scope.memo["home"])
    vals = _branch_values(scope)
    # a client never given a store belongs to the main one (as server._ensure_branch_assignments does)
    t = _db.tenants.find_one({"id": scope.tenant_id}, {"_id": 0, "branches": 1}) or {}
    open_ = [b for b in t.get("branches") or [] if b.get("id") and b.get("status") != "closed"]
    main = next((b["id"] for b in open_ if b.get("is_main") or b["id"] == "main"), open_[0]["id"] if open_ else None)
    if main in (scope.ids or []):
        vals = list(vals) + [None, ""]
    ids = set(_db.customers.distinct("id", {"tenant_id": scope.tenant_id, "branch_id": {"$in": vals}}))
    if main in (scope.ids or []):
        ids.update(_db.customers.distinct("id", {"tenant_id": scope.tenant_id, "branch_id": {"$exists": False}}))
    ids.discard(None)
    scope.memo["home"] = frozenset(ids)
    return set(ids)


def is_multi(tid: str) -> bool:
    from features import team_access as T
    return len(T.stores(tid)) > 1


def sending_scope(token: TokenData, request: Optional[Request] = None) -> Scope:
    """The establishment a send is for: the one chosen in the menu. With
    several establishments, a send for « all of them » is refused — each
    store messages its own clients."""
    from fastapi import HTTPException
    scope = resolve(token, request)
    if scope.is_all and is_multi(token.tenant_id):
        raise HTTPException(status_code=400, detail="Choisissez d'abord l'établissement dans le menu : "
                                                    "chaque établissement écrit à ses propres clients.")
    return scope

