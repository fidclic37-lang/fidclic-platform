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


@dataclass
class Scope:
    tenant_id: str
    ids: Optional[List[str]]            # None = the whole shop
    allowed: List[str] = field(default_factory=list)
    all_ids: List[str] = field(default_factory=list)
    names: Dict[str, str] = field(default_factory=dict)

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
    me = _db.users.find_one({"email": token.email}, {"_id": 0, "role": 1, "tenant_id": 1, "branch_ids": 1}) or {}
    allowed = T._covered(me, all_ids) if me else []
    if token.role == "business_owner":
        allowed = list(all_ids)
    if not allowed:
        raise HTTPException(status_code=403, detail="Aucun établissement ne vous est attribué.")
    if requested is None and request is not None:
        requested = request.headers.get(HEADER) or request.query_params.get("store")
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
    # "main" is the virtual establishment of a shop without branches: its
    # visits carry no branch_id. (Only reachable when ids is not None, which
    # a single-establishment shop never is — kept for safety.)
    vals: List[Any] = []
    for i in scope.ids or []:
        vals.extend([None] if i == "main" else [i])
    return vals


def visit_filter(scope: Scope) -> Dict[str, Any]:
    return {} if scope.is_all else {"branch_id": {"$in": _branch_values(scope)}}


def customer_ids(scope: Scope) -> Optional[Set[str]]:
    """Clients of these establishments: those who visited one, or signed up at
    one. None = everyone (the whole shop)."""
    if scope.is_all:
        return None
    vals = _branch_values(scope)
    ids = set(_db.visits.distinct("customer_id", {"tenant_id": scope.tenant_id, "branch_id": {"$in": vals}}))
    ids.update(_db.customers.distinct("id", {"tenant_id": scope.tenant_id, "branch_id": {"$in": vals}}))
    ids.discard(None)
    return ids


def customer_filter(scope: Scope) -> Dict[str, Any]:
    ids = customer_ids(scope)
    base: Dict[str, Any] = {"tenant_id": scope.tenant_id}
    if ids is not None:
        base["id"] = {"$in": list(ids)}
    return base
