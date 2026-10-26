"""
One send, one read of what it needs.

WHY
    Audit 2026-10-26: a campaign cost ~10 database round trips per client —
    is this client paused, how many pushes this month, how many messages
    today / this week (« Limites d'envoi »), their push subscriptions, then a
    log row, a counter row, a card row. 5 000 clients ≈ 50 000 round trips,
    ~500 s on Atlas, past the function's 360 s. A relance ~12 per message.

WHAT IT DOES
    Inside `with batch(db, tid, ids):` the questions every client's send asks
    are answered from one read made at the start, then kept up to date in
    memory as the send goes (each push sent counts toward the month, each
    message toward the client's day and week, exactly as the database would
    have counted it), and the log / counter rows are written a hundred at a
    time. Outside a batch — one client, a scan, a test — nothing changes.

    The rules themselves do not move: dispatch_to_customer still asks the same
    questions in the same order; only where the answers come from changes
    (tests/test_send_batch.py compares both, client by client).

    `ENABLED = False` turns it off (the comparison in the tests).
"""
from __future__ import annotations

import contextvars
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional

ENABLED = True
CHUNK = 100                      # rows written at once; clients written to the card before their push

_B: contextvars.ContextVar[Optional["Batch"]] = contextvars.ContextVar("fidclic_send_batch", default=None)


class Batch:
    def __init__(self, db, tid: str, ids: Iterable[str]):
        self.db, self.tid = db, tid
        self.ids = {i for i in ids if i}
        self.started = datetime.now(timezone.utc)
        self._paused: Optional[set] = None
        self._quota: Optional[int] = None
        self._counts: Optional[Dict[str, Counter]] = None
        self._shop: Optional[Counter] = None
        self._subs: Optional[Dict[str, List[Dict[str, Any]]]] = None
        self._marketing: Optional[bool] = None
        self.memo: Dict[Any, Any] = {}
        self._logs: List[Dict[str, Any]] = []
        self._counters: List[Dict[str, Any]] = []

    def covers(self, tid: Optional[str], cid: Optional[str] = None) -> bool:
        return tid == self.tid and (cid is None or cid in self.ids)

    # « is this client paused » — services/client_status
    def paused(self, cid: str) -> bool:
        if self._paused is None:
            self._paused = set(self.db.customers.distinct(
                "id", {"tenant_id": self.tid, "id": {"$in": list(self.ids)}, "paused_at": {"$ne": None}}))
        return cid in self._paused

    # the month's pushes — features/plans_public.push_used_this_month
    def quota_used(self, read: Callable[[], int]) -> int:
        if self._quota is None:
            self._quota = int(read())
        return self._quota

    # « Limites d'envoi » — features/send_rules
    def _load_counts(self, day: datetime, week: datetime) -> None:
        self._counts = {"day": Counter(), "week": Counter()}
        for r in self.db.send_counter.find({"tenant_id": self.tid, "customer_id": {"$in": list(self.ids)},
                                            "at": {"$gte": min(day, week)}}, {"_id": 0, "customer_id": 1, "at": 1}):
            at = r.get("at")
            if at is not None and at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            if at is None:
                continue
            if at >= week:
                self._counts["week"][r["customer_id"]] += 1
            if at >= day:
                self._counts["day"][r["customer_id"]] += 1

    def client_count(self, cid: str, span: str, day: datetime, week: datetime) -> int:
        if self._counts is None:
            self._load_counts(day, week)
        return self._counts[span][cid]

    def shop_count(self, span: str, read: Callable[[], int]) -> int:
        if self._shop is None:
            self._shop = Counter()
        if span not in self._shop:
            self._shop[span] = int(read())
        return self._shop[span]

    def counted(self, row: Dict[str, Any]) -> None:
        """A send counted for the « Limites d'envoi »: in memory now, in the database soon."""
        self._counters.append(row)
        if self._counts is not None:
            self._counts["day"][row["customer_id"]] += 1
            self._counts["week"][row["customer_id"]] += 1
        if self._shop is not None:
            for span in list(self._shop):
                self._shop[span] += 1
        if len(self._counters) >= CHUNK:
            self.flush()

    def marketing(self, read: Callable[[], bool]) -> bool:
        if self._marketing is None:
            self._marketing = bool(read())
        return self._marketing

    # push subscriptions — features/push_subscriptions.fan_out_to_customer
    def subs(self, cid: str) -> List[Dict[str, Any]]:
        if self._subs is None:
            self._subs = defaultdict(list)
            for s in self.db.push_subscriptions.find({"tenant_id": self.tid, "customer_id": {"$in": list(self.ids)}}):
                self._subs[s.get("customer_id")].append(s)
        return list(self._subs.get(cid) or [])

    def forget_subs(self, endpoints: Iterable[str]) -> None:
        gone = set(endpoints)
        if self._subs is not None and gone:
            for cid in list(self._subs):
                self._subs[cid] = [s for s in self._subs[cid] if s.get("endpoint") not in gone]

    # delivery_log — server.dispatch_to_customer
    def logged(self, row: Dict[str, Any]) -> None:
        self._logs.append(row)
        if (self._quota is not None and row.get("channel") == "web_push"
                and int(((row.get("result") or {}).get("sent")) or 0) > 0):
            self._quota += 1
        if len(self._logs) >= CHUNK:
            self.flush()

    def flush(self) -> None:
        logs, counters = self._logs, self._counters
        self._logs, self._counters = [], []
        if logs:
            self.db.delivery_log.insert_many(logs)
        if counters:
            self.db.send_counter.insert_many(counters)


def current(tid: Optional[str] = None, cid: Optional[str] = None) -> Optional[Batch]:
    """The batch answering for this shop (and client), if any."""
    b = _B.get()
    if b is None or (tid is not None and not b.covers(tid, cid)):
        return None
    return b


@contextmanager
def batch(db, tid: str, ids: Iterable[str]) -> Iterator[Optional[Batch]]:
    if not ENABLED or _B.get() is not None:
        yield _B.get()
        return
    b = Batch(db, tid, ids)
    token = _B.set(b)
    try:
        yield b
    finally:
        try:
            b.flush()
        finally:
            _B.reset(token)


def memo(key: Any, compute: Callable[[], Any]) -> Any:
    """A value worth computing once per send (outside a batch: every time)."""
    b = _B.get()
    if b is None:
        return compute()
    if key not in b.memo:
        b.memo[key] = compute()
    return b.memo[key]


def chunks(items: List[Any], n: int = 0) -> Iterator[List[Any]]:
    n = n or CHUNK
    for i in range(0, len(items), n):
        yield items[i:i + n]
