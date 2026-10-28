"""
A big send cut half-way: everyone gets it, nobody twice (user, 2026-10-28:
« sabko push jaaye, and kisi ko bhi 2 baar n jaaye same notification »).

Before: a hundred card rows were written, then their pushes; a send stopped
in between left the rest of those hundred without a push for ever — the tick
saw them « on their card » and skipped them. The Wallet passes were woken
only at the very end, so a cut send woke none.

Now:
    · each card row says what is left: push « pending » → « done » (saved every
      PUSH_MARK clients, and on the way out of an error), wallet the same
    · the send stops ITSELF before the function's time limit (DELIVER_BUDGET_S),
      exactly between two clients, and leaves the rest to the tick
    · the tick (resume_due) gives what is « pending », and only that
    · rows written before this change carry no mark: done

Run: cd api && python3 tests/test_cut_send.py
"""
import asyncio
import datetime as dt
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-cut-send")
os.environ.setdefault("DISABLE_SEED", "1")
UTC = dt.timezone.utc
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
    import services.web_push as WEB
    import features.wallet_passes as WP
    from features import campaigns_page as CP
    from features import temoin as T

    db = server.db
    pushed, woken = [], []

    def fake_push(sub, title, body, url=None):
        pushed.append((sub["cid"], sub["endpoint"]))
        return {"sent": True}
    WEB.send_push = fake_push
    WEB.is_configured = lambda: True

    def fake_wake(serials, **k):
        woken.extend(serials)
        return {"sent": len(serials)}
    WP.notify_passes = fake_wake
    WP.notify_customer = lambda *a, **k: {}
    T.enabled = lambda tid: False

    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=H, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    N = 250                                        # three groups of a hundred

    def shop():
        for c in ("customers", "push_subscriptions", "push_notifications", "delivery_log", "send_counter",
                  "deferred_messages", "campaigns", "tenants", "card_templates", "users"):
            db[c].delete_many({})
        pushed.clear(); woken.clear()
        db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "plan": "vip",
                               "subscription_status": "active", "is_active": True, "send_rules": {}})
        db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10})
        db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
        for i in range(N):
            cid = f"c{i:03d}"
            db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": f"Client {i}", "barcode_id": f"B{i}",
                                     "visits": 2, "created_at": dt.datetime.now(UTC) - dt.timedelta(days=100)})
            for k in range(1 + (i % 2)):             # one or two phones
                ep = f"https://push/{i}-{k}"
                db.push_subscriptions.insert_one({"tenant_id": "t1", "customer_id": cid, "endpoint": ep,
                                                  "subscription": {"endpoint": ep, "cid": cid}})

    devices = lambda: Counter(s["endpoint"] for s in db.push_subscriptions.find({}, {"_id": 0}))

    class Clock:
        """One second goes by each time the send looks at the clock."""
        def __init__(self):
            self.t = 0.0

        def __call__(self):
            self.t += 1.0
            return self.t

    real_clock = CP._clock

    def exact(label):
        per_device = Counter(ep for _, ep in pushed)
        twice = [ep for ep, n in per_device.items() if n > 1]
        missed = [ep for ep in devices() if per_device[ep] == 0]
        check(f"{label}: every phone got it ({len(missed)} missed)", not missed, missed[:5])
        check(f"{label}: no phone got it twice ({len(twice)})", not twice, twice[:5])
        w = Counter(woken)
        check(f"{label}: every Wallet pass woken exactly once",
              set(w) == {f"B{i}" for i in range(N)} and set(w.values()) == {1}, [k for k, v in w.items() if v != 1][:5])

    # ── 1. the time limit: the send stops itself between two clients ─────────
    print("La limite de temps : l'envoi s'arrête de lui-même")
    shop()
    CP._clock = Clock()
    CP.DELIVER_BUDGET_S = 120                         # ~120 clients, then it stops
    r = http("POST", "/api/owner/campaigns/compose", json={"title": "Grosse", "message": "Bonjour",
                                                           "audience": {"mode": "all"}})
    CP._clock = real_clock
    camp = db.campaigns.find_one({"name": "Grosse"})
    first = {c for c, _ in pushed}
    check(f"it answered (no crash) and stopped part-way: {len(first)} of {N} clients",
          r.status_code == 200 and 50 < len(first) < N, r.text[:200])
    check("its delivery is left « pending » for the tick", (camp.get("delivery") or {}).get("done") is False)
    rows = list(db.push_notifications.find({"campaign_id": camp["id"]}, {"_id": 0}))
    done = {x["customer_id"] for x in rows if x.get("push") == "done"}
    check("the card rows say exactly who was pushed", done == first, (len(done), len(first)))
    check("nobody was pushed twice before the stop", len(pushed) == sum(1 + (int(c[1:]) % 2) for c in first))
    started = camp["delivery"]["at"]
    started = started if started.tzinfo else started.replace(tzinfo=UTC)
    check("the tick leaves it alone at first", CP.resume_due(started + dt.timedelta(minutes=5)) == 0)
    CP.DELIVER_BUDGET_S = 300
    n = CP.resume_due(started + dt.timedelta(minutes=11))
    camp = db.campaigns.find_one({"id": camp["id"]})
    check("11 minutes later the tick finishes it", n == 1 and camp["delivery"]["done"] is True)
    exact("time limit")
    check("delivered_count adds both runs", camp["delivered_count"] == N, camp.get("delivered_count"))
    check("one card row per client", len(db.push_notifications.distinct("customer_id", {"campaign_id": camp["id"]})) == N
          and db.push_notifications.count_documents({"campaign_id": camp["id"]}) == N)

    # ── 2. a resume that itself runs out of time is resumed again ────────────
    print("Une reprise elle-même coupée")
    shop()
    CP._clock = Clock()
    CP.DELIVER_BUDGET_S = 60
    http("POST", "/api/owner/campaigns/compose", json={"title": "Deux fois", "message": "Bonjour", "audience": {"mode": "all"}})
    camp = db.campaigns.find_one({"name": "Deux fois"})
    t0 = camp["delivery"]["at"]
    t0 = t0 if t0.tzinfo else t0.replace(tzinfo=UTC)
    CP.RESUME_BUDGET_S = 60
    CP.resume_due(t0 + dt.timedelta(minutes=11))
    mid = db.campaigns.find_one({"id": camp["id"]})
    check("the first resume stops too, still « pending »", mid["delivery"]["done"] is False)
    CP._clock = real_clock
    CP.RESUME_BUDGET_S = 120
    CP.DELIVER_BUDGET_S = 300
    CP.resume_due(t0 + dt.timedelta(minutes=30))
    check("the next tick finishes it", db.campaigns.find_one({"id": camp["id"]})["delivery"]["done"] is True)
    exact("two cuts")

    # ── 3. an error half-way: what was pushed is saved on the way out ────────
    print("Une erreur en route")
    shop()

    class Killed(BaseException):
        pass

    def dying(sub, title, body, url=None):
        # between two clients: the 131st client's first phone
        if len({c for c, _ in pushed}) >= 130 and sub["cid"] not in {c for c, _ in pushed}:
            raise Killed()
        return fake_push(sub, title, body, url)
    WEB.send_push = dying
    try:
        http("POST", "/api/owner/campaigns/compose", json={"title": "Erreur", "message": "Bonjour", "audience": {"mode": "all"}})
    except BaseException:
        pass
    WEB.send_push = fake_push
    camp = db.campaigns.find_one({"name": "Erreur"})
    done = {x["customer_id"] for x in db.push_notifications.find({"campaign_id": camp["id"], "push": "done"})}
    check("the 130 clients pushed before the error are saved as done (not only the last full ten)",
          len(done) == 130, len(done))
    started = camp["delivery"]["at"]
    started = started if started.tzinfo else started.replace(tzinfo=UTC)
    CP.resume_due(started + dt.timedelta(minutes=11))
    exact("error")

    # ── 4. rows from before this change ───────────────────────────────────────
    print("Les envois d'avant")
    shop()
    at = dt.datetime.now(UTC) - dt.timedelta(hours=1)
    db.campaigns.insert_one({"id": "old", "tenant_id": "t1", "name": "Ancienne", "content": "x", "status": "sent",
                             "sent_at": at, "recipient_ids": [f"c{i:03d}" for i in range(N)],
                             "channels": {"push": True, "wallet": True}, "delivery": {"done": False, "at": at}})
    db.push_notifications.insert_many([{"customer_id": f"c{i:03d}", "tenant_id": "t1", "campaign_id": "old",
                                        "title": "Ancienne", "type": "campaign", "sent_at": at} for i in range(100)])
    CP.resume_due(dt.datetime.now(UTC))
    again = {c for c, _ in pushed} & {f"c{i:03d}" for i in range(100)}
    check("a row without a mark (written before) is never pushed again", not again, sorted(again)[:5])
    check("…and the clients without a row get it", {c for c, _ in pushed} == {f"c{i:03d}" for i in range(100, N)})

    # ── 5. the groupe témoin and the channels ─────────────────────────────────
    print("Témoin et canaux")
    shop()
    at = dt.datetime.now(UTC) - dt.timedelta(hours=1)
    db.campaigns.insert_one({"id": "tm", "tenant_id": "t1", "name": "Témoin", "content": "x", "status": "sent",
                             "sent_at": at, "recipient_ids": [f"c{i:03d}" for i in range(N)],
                             "holdout_ids": [f"c{i:03d}" for i in range(10)],
                             "channels": {"push": True, "wallet": False}, "delivery": {"done": False, "at": at}})
    CP.resume_due(dt.datetime.now(UTC))
    got = {c for c, _ in pushed}
    check("the groupe témoin never gets it on a resume", not got & {f"c{i:03d}" for i in range(10)})
    check("wallet off: no pass woken, no « wallet pending » left",
          not woken and not db.push_notifications.find_one({"campaign_id": "tm", "wallet": "pending"}))

    # ── 6. « Contacter (N) » and the scheduled sends use the same rule ───────
    print("Contacter (N) et envois programmés")
    shop()
    CP._clock = Clock()
    CP.DELIVER_BUDGET_S = 80
    http("POST", "/api/owner/campaigns/send-to-group", json={"customer_ids": [f"c{i:03d}" for i in range(N)],
                                                             "name": "Groupe", "content": "Bonjour"})
    CP._clock = real_clock
    CP.DELIVER_BUDGET_S = 300
    g = db.campaigns.find_one({"name": "Groupe"})
    check("« Contacter (N) » cut by the time limit stays « pending »", g and g["delivery"]["done"] is False)
    t0 = g["delivery"]["at"]
    t0 = t0 if t0.tzinfo else t0.replace(tzinfo=UTC)
    CP.resume_due(t0 + dt.timedelta(minutes=11))
    per_device = Counter(ep for _, ep in pushed)
    check("…and is finished by the tick, each phone once",
          set(per_device) == set(devices()) and set(per_device.values()) == {1})

    shop()
    when = dt.datetime.now(UTC) - dt.timedelta(minutes=1)
    db.campaigns.insert_one({"id": "sch", "tenant_id": "t1", "name": "Prog", "content": "x", "status": "scheduled",
                             "scheduled_for": when, "recipient_ids": [f"c{i:03d}" for i in range(N)],
                             "channels": {"push": True, "wallet": True}})
    CP._clock = Clock()
    CP.DELIVER_BUDGET_S = 100
    CP.run_due(dt.datetime.now(UTC))
    CP._clock = real_clock
    CP.DELIVER_BUDGET_S = 300
    s = db.campaigns.find_one({"id": "sch"})
    check("a scheduled send cut by the time limit stays « pending »", s["status"] == "sent" and s["delivery"]["done"] is False)
    t0 = s["delivery"]["at"]
    t0 = t0 if t0.tzinfo else t0.replace(tzinfo=UTC)
    CP.resume_due(t0 + dt.timedelta(minutes=11))
    exact("scheduled")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
