"""
« Impact FidClic »: the card and its detail always show the same figure
(user, 2026-11-20 — CI: card 15,43 €, detail 9,07 €).

WHY IT BROKE
    A visit is set apart as « attendu » when the client came in their usual
    window. That window leans on the shop's usual rhythm (client_brain.
    usual_gap), read from every client's brain — and every scan moves it a
    little, re-read every 10 minutes. The card sums past days from the
    register (features/visit_days), judged with the rhythm of when the day
    was summed; the detail judges every visit with the rhythm of now. A visit
    could be « FidClic » on the card and « attendu » in the detail.

WHAT THE USER CHOSE (« Aadat din mein 1 baar »)
    The shop's rhythm is fixed once per Paris day (stored, so every server
    instance reads the same one). All day long the card, the detail and the
    register judge with it; the next day it is learned again.

    · prior_for is the same all day, whatever the scans do; a new Paris day
      learns it again (midnight in Paris, not in UTC)
    · one stored row per shop and day; another shop has its own
    · the database failing never breaks a page: the live rhythm is used
    · card and detail agree after the rhythm moves mid-day (HTTP, both pages)
    · the register's brain version does not change within the day

Run: cd api && python3 tests/test_shop_rhythm_day.py
"""
import asyncio
import datetime as dt
import os
import random
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-shop-rhythm-day")
os.environ.setdefault("DISABLE_SEED", "1")
UTC, PARIS = dt.timezone.utc, ZoneInfo("Europe/Paris")
passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {str(detail)[:400]}"))


def main():
    import server
    import auth
    import httpx
    from features import client_brain as CB, visit_days as VD

    db = server.db
    rnd = random.Random(20)

    def set_rhythm(tid, gap, n=30):
        """n regulars whose brains say they come every `gap` days."""
        db.customers.update_many({"tenant_id": tid, "id": {"$in": [f"{tid}-c{i:02d}" for i in range(n)]}},
                                 {"$set": {"brain.n_gaps": 4, "brain.own_gap": float(gap)}})
        CB._usual_cache.clear()

    def shop(tid, n=40):
        db.tenants.insert_one({"id": tid, "name": f"Shop {tid}", "sector": "cafe", "plan": "vip"})
        db.customers.insert_many([{"id": f"{tid}-c{i:02d}", "tenant_id": tid, "name": f"Client {i}",
                                   "created_at": dt.datetime(2025, 1, 1, tzinfo=UTC)} for i in range(n)])

    # ── 1. one rhythm per Paris day ──────────────────────────────────────────
    print("Une aadat par jour")
    shop("s1")
    shop("s2")
    clock = [dt.datetime(2026, 11, 20, 9, 0, tzinfo=UTC)]           # 10:00 in Paris
    real_today = CB._today
    CB._today = lambda: clock[0].astimezone(PARIS).date().isoformat()
    set_rhythm("s1", 30)
    first = CB.prior_for("s1", 1)
    check(f"the shop's rhythm is its clients' ({first})", first[1] == "boutique" and first[0] > 25, first)
    set_rhythm("s1", 4)                                              # a busy morning of scans
    check(f"…and stays the same all day, whatever the scans do ({CB.prior_for('s1', 1)})",
          CB.prior_for("s1", 1) == first)
    check("both brains read the same day's rhythm", CB.prior_for("s1", 2) == first)
    check(f"the live figure did move (it is not frozen): {CB.usual_gap('s1', fresh=True)}",
          CB.usual_gap("s1", fresh=True)[0] < first[0])
    CB._day_cache.clear()                                            # another server instance
    check("another server instance reads the same stored one", CB.prior_for("s1", 1) == first)
    check("one stored row for this shop and day",
          db.brain_shop_days.count_documents({"tenant_id": "s1", "day": "2026-11-20"}) == 1)

    clock[0] = dt.datetime(2026, 11, 20, 22, 30, tzinfo=UTC)        # 23:30 in Paris: still the 20th
    check("23:30 in Paris: still the same day", CB.prior_for("s1", 1) == first)
    clock[0] = dt.datetime(2026, 11, 20, 23, 30, tzinfo=UTC)        # 00:30 in Paris: the 21st
    nxt = CB.prior_for("s1", 1)
    check(f"00:30 in Paris (23:30 UTC): a new day learns it again ({nxt})", nxt != first and nxt[0] < first[0], nxt)
    check("…stored once for the new day too",
          db.brain_shop_days.count_documents({"tenant_id": "s1", "day": "2026-11-21"}) == 1)

    set_rhythm("s2", 12)
    other = CB.prior_for("s2", 1)
    check(f"another shop has its own ({other} ≠ {nxt})", other != nxt and other[1] == "boutique", other)

    # an empty shop: where the activity starts, still one per day
    db.tenants.insert_one({"id": "s0", "name": "Vide", "sector": "cafe"})
    e = CB.prior_for("s0", 1)
    check(f"a shop with no client: the activity's start ({e})", e[1] in ("secteur", "reseau"), e)

    # the database failing: the live rhythm, never an error
    real = db.brain_shop_days
    class Broken:
        def __getattr__(self, name):
            def boom(*a, **k):
                raise RuntimeError("Atlas down")
            return boom
    CB._day_cache.clear()
    CB._db = type("DB", (), {"__getattr__": lambda s, n: Broken() if n == "brain_shop_days" else db[n],
                             "__getitem__": lambda s, n: db[n]})()
    try:
        r = CB.prior_for("s2", 1)
        check(f"stored rhythm unreachable: the live one, no error ({r})", r == CB.usual_gap("s2", fresh=True), r)
    except Exception as exc:                                         # noqa: BLE001
        check(f"stored rhythm unreachable: the live one, no error ({exc})", False)
    finally:
        CB._db = db
    assert real is db.brain_shop_days

    # ── 2. the card and its detail: the same figure ─────────────────────────
    print("\nLe card et son détail")
    CB._today = real_today                                          # the real clock from here on
    CB._day_cache.clear()
    now = dt.datetime.now(UTC)
    tid = "t1"
    shop(tid, 60)
    db.users.insert_one({"email": "o@t1.fr", "role": "business_owner", "tenant_id": tid})
    visits, notes = [], []
    for i in range(60):
        cid = f"{tid}-c{i:02d}"
        gap = rnd.choice([4, 6, 8, 11, 15, 21])
        t = now - dt.timedelta(days=200 + rnd.random() * gap)
        while t < now - dt.timedelta(hours=2):
            visits.append({"id": f"v{len(visits):05d}", "tenant_id": tid, "customer_id": cid,
                           "amount_paid": round(rnd.uniform(3, 30), 2), "visit_time": t})
            t += dt.timedelta(days=gap * rnd.uniform(.6, 1.4), hours=rnd.uniform(-6, 6))
        for _ in range(14):
            notes.append({"tenant_id": tid, "customer_id": cid, "type": rnd.choice(["campaign", "offer", "inactive"]),
                          "sent_at": now - dt.timedelta(days=rnd.uniform(0.2, 60))})
    db.visits.insert_many(visits)
    db.push_notifications.insert_many(notes)
    for i in range(60):
        CB.refresh(tid, f"{tid}-c{i:02d}")
    CB._usual_cache.clear()
    VD._bv_cache.clear()

    token = auth.create_access_token({"sub": "o@t1.fr", "role": "business_owner", "tenant_id": tid})

    def get(url):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as ac:
                return await ac.get(url, headers={"Authorization": f"Bearer {token}"})
        return asyncio.new_event_loop().run_until_complete(run())

    def money(v):
        return round(float(str(v).replace(",", ".").replace("€", "").replace(" ", "") or 0), 2)

    def pair(page="home"):
        card = get("/api/owner/home/overview?days=30" if page == "home" else "/api/owner/analyses?days=30")
        det = get(f"/api/owner/{page}/impact?days=30")
        body = card.json() if page == "home" else (card.json().get("data") or {})
        c = (body.get("impact") or {}).get("value" if page == "home" else "revenue")
        return card.status_code, det.status_code, money(c), money(det.json()["totals"]["revenue"]), det.json()["totals"]

    s1, s2, c0, d0, t0 = pair()
    check(f"to start with, the same figure ({c0} € / {d0} €)", s1 == s2 == 200 and c0 == d0 and c0 > 0, (s1, s2, c0, d0))
    check(f"…with visits set apart as « attendus » ({t0['attendus']})", t0["attendus"]["visits"] > 0, t0["attendus"])
    bv0 = VD.brain_version(tid)

    # the rhythm moves mid-day: the regulars' brains now say every 3 days
    db.customers.update_many({"tenant_id": tid}, {"$set": {"brain.own_gap": 3.0, "brain.n_gaps": 6}})
    CB._usual_cache.clear()                                         # (10 minutes later)
    VD._bv_cache.clear()
    s1, s2, c1, d1, _ = pair()
    check(f"the rhythm moved mid-day: the card and the detail still agree ({c1} € / {d1} €)",
          s1 == s2 == 200 and c1 == d1, (c1, d1))
    check("…and the register's brain version did not change within the day", VD.brain_version(tid) == bv0)
    s1, s2, c2, d2, _ = pair("analyses")
    check(f"Analyses too ({c2} € / {d2} €)", s1 == s2 == 200 and c2 == d2, (s1, s2, c2, d2))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
