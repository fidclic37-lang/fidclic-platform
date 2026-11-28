"""Caisse (POS) plugs — one module per brand, all speaking base.py's shapes.

The common frame (connect, webhook door, dedupe, apply to the card, refunds,
nightly check, retries, status) lives in features/pos_connectors.py and is
written once. A new caisse is a new plug here: connect link, its tickets in
our shape, its signature, its nightly list, its customers.
"""
from services.pos.base import PosError  # noqa: F401


def adapters():
    """Every plug FidClic knows, by name."""
    from services.pos.square import SquareAdapter
    return {"square": SquareAdapter}


def get(name: str):
    cls = adapters().get((name or "").strip().lower())
    return cls() if cls else None
