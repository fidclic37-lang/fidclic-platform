"""
A client's phone, findable fast (#454's load lab, user 2026-11-09).

WHY
    Phones are kept as typed (« 06 12 34 56 78 », « +33 6… », « 0033… »), so
    finding one meant a pattern over every client of the shop: ~80 ms for
    20 000 clients on a real database, more as the shop grows.

WHAT
    `phone_tail` = the 9 last digits ("" when there are fewer), next to the
    phone, indexed with the shop (tenant_id, phone_tail). It is written by the
    database's own writes, whoever writes (services/doc_cache WRITE HOOKS): an
    insert, a $set / $setOnInsert / $unset of the phone, a replace, a
    bulk_write — no writer has to remember it. A pipeline update that may
    touch the phone recomputes the tail of what it matched, after the write.
    Clients written before this get theirs once at start-up
    (features/merchant_api.backfill_phone_tails).
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional


def tail(phone: Any) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    return digits[-9:] if len(digits) >= 9 else ""


def _doc(doc: Any) -> None:
    """An inserted / replacing document: its tail, from its phone."""
    if isinstance(doc, dict):
        doc["phone_tail"] = tail(doc.get("phone"))


def _update(upd: Any) -> bool:
    """Adds the tail to an update that writes the phone. False when it cannot
    be read (a pipeline): the caller recomputes after the write."""
    if isinstance(upd, list):
        return False
    if not isinstance(upd, dict):
        return True
    for op in ("$set", "$setOnInsert"):
        part = upd.get(op)
        if isinstance(part, dict) and "phone" in part:
            part["phone_tail"] = tail(part["phone"])
    unset = upd.get("$unset")
    if isinstance(unset, dict) and "phone" in unset:
        upd.setdefault("$set", {})["phone_tail"] = ""
    return True


def _recompute(coll, flt: Any) -> Callable[[], None]:
    def after() -> None:
        for d in coll.find(flt or {}, {"_id": 1, "phone": 1}).limit(500):
            coll.update_one({"_id": d["_id"]}, {"$set": {"phone_tail": tail(d.get("phone"))}})
    return after


def hear(coll, method: str, args: tuple, kwargs: Dict[str, Any]) -> Optional[Callable[[], None]]:
    """services/doc_cache write hook for `customers`."""
    a = list(args)
    if method == "insert_one":
        _doc(a[0] if a else kwargs.get("document"))
    elif method == "insert_many":
        for d in (a[0] if a else kwargs.get("documents")) or []:
            _doc(d)
    elif method in ("update_one", "update_many", "find_one_and_update"):
        upd = a[1] if len(a) > 1 else kwargs.get("update")
        if not _update(upd):
            return _recompute(coll, a[0] if a else kwargs.get("filter"))
    elif method in ("replace_one", "find_one_and_replace"):
        _doc(a[1] if len(a) > 1 else kwargs.get("replacement"))
    elif method == "bulk_write":
        later = []
        for op in (a[0] if a else kwargs.get("requests")) or []:
            kind, doc = type(op).__name__, getattr(op, "_doc", None)
            if kind in ("InsertOne", "ReplaceOne"):
                _doc(doc)
            elif kind in ("UpdateOne", "UpdateMany") and not _update(doc):
                later.append(_recompute(coll, getattr(op, "_filter", None)))
        if later:
            return lambda: [f() for f in later]
    return None
