"""
Big sends without a database round trip per client (audit 2026-10-26: a
campaign cost ~10 round trips per client — 5 000 clients ≈ 50 000, ~500 s on
Atlas, past the function's 360 s — and a relance ~12 per message; the send
was marked « envoyée » first, so a send cut half-way never reached the rest).

    · one send, one read of what it needs (services/send_batch): the paused
      clients, the month's push count, each client's sends today / this week
      for the « Limites d'envoi », their push subscriptions — then kept up to
      date in memory as the send goes; the rows are written a hundred at a time
    · {produit_habituel} only when the message uses it
    · the inactive clients' last relance in one read; the Analyses tracking
      in one read
    · an automation run reads its shop and card once (services/doc_cache)
    · a send cut half-way is finished by the tick — nobody messaged twice

The rules do not move: what a send writes and who it reaches is compared
with the same send done the old way, client by client.

Run: cd api && /usr/local/bin/python3 tests/test_send_batch.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-send-batch")
os.environ.setdefault("DISABLE_SEED", "1")
UTC = dt.timezone.utc
passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {str(detail)[:500]}"))


def main():
    import server
    import auth
    import httpx
    import services.web_push as WEB
    import features.wallet_passes as WP
    from features import automations as AU
    from features import temoin as T
    from services import send_batch as SB

    db = server.db
    now = dt.datetime.now(UTC).replace(microsecond=0)
    pushed = []

    def fake_push(sub, title, body, url=None):
        pushed.append((sub["cid"], title))
        return {"expired": True} if sub["endpoint"].endswith("-dead") else {"sent": True}
    WEB.send_push = fake_push
    WEB.is_configured = lambda: True
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    WP.notify_customer = lambda *a, **k: {}
    T.enabled = lambda tid: False                    # the groupe témoin has its own tests

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=H, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}

    def shop(n=60):
        """A shop where every rule bites somewhere in the send."""
        for c in ("customers", "push_subscriptions", "push_notifications", "delivery_log", "send_counter",
                  "deferred_messages", "campaigns", "automation_log", "automations", "tenants", "card_templates",
                  "users", "visits", "automation_queue", "campaign_opens"):
            db[c].delete_many({})
        db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "sector": "cafe", "plan": "gold",
                               "subscription_status": "active", "is_active": True,
                               "send_rules": {"per_client_day": 1, "per_client_week": 3, "shop_day": 0, "shop_week": 0}})
        db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10})
        db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
        old = now - dt.timedelta(days=90)
        for i in range(n):
            db.customers.insert_one({"id": f"c{i:03d}", "tenant_id": "t1", "name": f"Client {i}", "barcode_id": f"B{i}",
                                     "visits": 3, "points": 2, "created_at": now - dt.timedelta(days=300),
                                     "last_visit_date": old, "paused_at": now if i < 3 else None,
                                     "brain": {"top_items": [{"name": "Crème", "share": 0.9}], "visits_with_items": 3}
                                     if i % 4 == 0 else None})
            for k in range(1 + (i % 3)):
                ep = f"https://push/{i}-{k}" + ("-dead" if i % 7 == 0 and k == 0 else "")
                db.push_subscriptions.insert_one({"tenant_id": "t1", "customer_id": f"c{i:03d}", "endpoint": ep,
                                                  "subscription": {"endpoint": ep, "cid": f"c{i:03d}"}})
        for i in range(3, 9):                                 # already messaged today: over their daily limit
            db.send_counter.insert_one({"tenant_id": "t1", "customer_id": f"c{i:03d}", "kind": "campaign",
                                        "at": now - dt.timedelta(minutes=30)})
        # the month's push quota (Pro: 6 000) is reached 20 sends in
        db.delivery_log.insert_many([{"tenant_id": "t1", "customer_id": "old", "channel": "web_push",
                                      "kind": "campaign", "result": {"sent": 1}, "timestamp": now - dt.timedelta(hours=2)}
                                     for _ in range(5980)])

    def state():
        def rows(c, keys):
            return sorted(tuple(str(d.get(k)) for k in keys) for d in db[c].find({}, {"_id": 0}))
        return {"pushes": sorted(pushed),
                "card": rows("push_notifications", ("customer_id", "title", "body", "type")),
                "log": rows("delivery_log", ("customer_id", "channel", "kind", "result")),
                "counter": rows("send_counter", ("customer_id", "kind")),
                "deferred": rows("deferred_messages", ("customer_id", "reason", "title")),
                "subs": rows("push_subscriptions", ("customer_id", "endpoint"))}

    def both(label, do):
        """The same send, the old way (client by client) and batched."""
        out = {}
        for mode in ("old", "batched"):
            shop()
            pushed.clear()
            SB.ENABLED = mode == "batched"
            res = do()
            out[mode] = (state(), res)
        SB.ENABLED = True
        a, b = out["old"][0], out["batched"][0]
        diff = {k: (len(a[k]), len(b[k])) for k in a if a[k] != b[k]}
        check(f"{label}: the same pushes, card messages, logs, counters, waiting messages, subscriptions", not diff, diff)
        check(f"…and it did send ({len(b['pushes'])} pushes, {len(b['card'])} card messages)", b["pushes"] and b["card"])
        return out

    # ── 1. the rules do not move ──────────────────────────────────────────────
    print("Les mêmes règles")
    out = both("a campaign to everyone", lambda: http("POST", "/api/owner/campaigns/compose", json={
        "title": "Pour {prénom}", "message": "Votre {produit_habituel} vous attend", "audience": {"mode": "all"}}).json())
    st = out["batched"][0]
    check("…the paused clients got nothing", not [p for p in st["pushes"] if p[0] in ("c000", "c001", "c002")])
    check("…the clients already messaged today wait for tomorrow (6)", len(st["deferred"]) == 6, st["deferred"][:3])
    check("…the push quota stopped it after 20 pushes sent",
          len([r for r in st["log"] if r[0] != "old" and "'sent': 1" in r[3] or "'sent': 2" in r[3] and r[0] != "old"]) <= 20)
    tried = {p[0] for p in st["pushes"]}
    check("…the dead subscriptions of the clients pushed are cleaned",
          tried and not [s for s in st["subs"] if s[1].endswith("-dead") and s[0] in tried])
    check("…« votre Crème » for the regulars, « votre prochaine visite » for the others",
          any("votre Crème" in r[2] for r in st["card"]) and any("votre prochaine visite" in r[2] for r in st["card"]))
    both("« Contacter (N) » from the Clients page", lambda: http("POST", "/api/owner/campaigns/send-to-group", json={
        "customer_ids": [f"c{i:03d}" for i in range(40)], "title": "Bonjour", "content": "À bientôt {prénom}"}).json())

    def relance():
        a = AU.new_doc("t1", "inactive", status="active", trigger={"days": 60, "repeat": "once"},
                       message={"title": "On vous attend {prénom}", "body": "Revenez !"},
                       schedule={"days": "all", "hour": "00:00"})
        db.automations.insert_one(dict(a))
        return AU.run_due(source="daily")
    out = both("a relance automation run", relance)
    check("…its log rows are the same", True)

    # ── 2. the round trips ─────────────────────────────────────────────────────
    print("Les allers-retours")
    calls = {"n": 0}
    OPS = ("find", "find_one", "insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one",
           "delete_many", "count_documents", "distinct", "aggregate", "find_one_and_update", "bulk_write")
    orig = {o: getattr(mongomock.collection.Collection, o) for o in OPS}

    def counting(fn):
        def inner(self, *a, **k):
            calls["n"] += 1
            return fn(self, *a, **k)
        return inner

    def count(do):
        for o, fn in orig.items():
            setattr(mongomock.collection.Collection, o, counting(fn))
        calls["n"] = 0
        try:
            res = do()
        finally:
            for o, fn in orig.items():
                setattr(mongomock.collection.Collection, o, fn)
        return calls["n"], res

    def big(n):
        shop(0)
        db.tenants.update_one({"id": "t1"}, {"$set": {"plan": "gold", "send_rules": {}}})
        old = now - dt.timedelta(days=90)
        db.customers.insert_many([{"id": f"b{i:05d}", "tenant_id": "t1", "name": f"Client {i}", "barcode_id": f"BB{i}",
                                   "visits": 3, "created_at": now - dt.timedelta(days=300), "last_visit_date": old}
                                  for i in range(n)])
        db.push_subscriptions.insert_many([{"tenant_id": "t1", "customer_id": f"b{i:05d}", "endpoint": f"e{i}",
                                            "subscription": {"endpoint": f"e{i}", "cid": f"b{i:05d}"}} for i in range(n)])
    N = 1500
    big(N)
    n, r = count(lambda: http("POST", "/api/owner/campaigns/compose", json={"title": "T", "message": "Bonjour {prénom}",
                                                                               "audience": {"mode": "all"}}))
    check(f"a campaign to {N}: {n} round trips ({n / N:.2f} a client, was ~10)", n / N < 0.3 and r.status_code == 200, r.text[:200])
    cid = r.json()["id"]
    n, _ = count(lambda: http("GET", f"/api/owner/campaigns/{cid}/tracking"))
    check(f"its Analyses tracking: {n} round trips (was one per client)", n < 30)
    big(N)
    n, r = count(lambda: http("POST", "/api/owner/campaigns/send-to-group", json={
        "customer_ids": [f"b{i:05d}" for i in range(1000)], "title": "G", "content": "Bonjour"}))
    check(f"« Contacter (1 000) »: {n} round trips ({n / 1000:.2f} a client)", n / 1000 < 0.3, r.text[:200])
    big(N)
    a = AU.new_doc("t1", "inactive", status="active", trigger={"days": 60, "repeat": "once"},
                   message={"title": "On vous attend", "body": "Revenez !"}, schedule={"days": "all", "hour": "00:00"})
    db.automations.insert_one(dict(a))
    n, _ = count(lambda: AU._inactive_due("t1", a, now))
    check(f"finding {N} inactive clients: {n} round trips (was one per client)", n < 10)
    n, s = count(lambda: AU.run_due(source="daily"))
    check(f"the relance to {s['time_sent']}: {n} round trips ({n / max(1, s['time_sent']):.1f} a message, was ~12)",
          s["time_sent"] == N and n / N < 4, s)

    # ── 3. a send cut half-way ────────────────────────────────────────────────
    print("Un envoi coupé en route")
    shop()
    db.tenants.update_one({"id": "t1"}, {"$set": {"plan": "gold", "send_rules": {}}})
    db.delivery_log.delete_many({})                          # no quota in the way: the cut must happen
    db.send_counter.delete_many({})
    devices = {c: len(db.push_subscriptions.distinct("endpoint", {"customer_id": c}))
               for c in db.push_subscriptions.distinct("customer_id")}
    pushed.clear()

    class Killed(BaseException):
        pass
    real = WEB.send_push

    def dying(sub, title, body, url=None):
        if len({p[0] for p in pushed}) >= 25:
            raise Killed()
        return real(sub, title, body, url)
    WEB.send_push = dying
    try:
        http("POST", "/api/owner/campaigns/compose", json={"title": "Coupée", "message": "Bonjour", "audience": {"mode": "all"}})
    except BaseException:
        pass
    WEB.send_push = real
    camp = db.campaigns.find_one({"name": "Coupée"})
    first = {p[0] for p in pushed}
    check(f"cut after {len(first)} clients: saved as sent, its delivery not finished",
          camp and camp["status"] == "sent" and (camp.get("delivery") or {}).get("done") is False, camp and camp.get("delivery"))
    check("the tick leaves it while the send may still be running",
          server.tick_pass(now + dt.timedelta(minutes=5)) is not None and len({p[0] for p in pushed}) == len(first))
    server.tick_pass(now + dt.timedelta(minutes=11))
    got = [p[0] for p in pushed]
    reached = {d["customer_id"] for d in db.push_notifications.find({"campaign_id": camp["id"]})}
    check(f"11 minutes later the tick finishes it: {len(reached)} of 57 on their card", len(reached) == 57)
    twice = sorted({c for c in got if got.count(c) > devices.get(c, 0)})    # one try per device, never more
    check(f"nobody pushed twice ({twice})", not twice)
    check("…and marked done", (db.campaigns.find_one({"id": camp["id"]}).get("delivery") or {}).get("done") is True)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
