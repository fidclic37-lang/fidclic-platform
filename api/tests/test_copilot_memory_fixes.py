"""
La mémoire du Copilote — the findings of #403's pentest and load run, fixed
(user, 2026-10-30, « a to d ek ek »):

  a  the regular pass reads each account's new messages together (300
     accounts were not done after 200 passes)
  b  a super admin in « Accéder au compte » never writes the owner's memory
  c  a deleted fact leaves what the model reads: its messages and the summary
  d  more phone / e-mail forms are hidden (abroad, in words, « [at] »)

Run: cd api && /usr/local/bin/python3 tests/test_copilot_memory_fixes.py
"""
import asyncio
import contextlib
import datetime as dt
import io
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-copilot-memory-fixes")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
UTC = dt.timezone.utc


def check(label, cond, show=None):
    global passed, failed
    cond = bool(cond)
    if not cond and show is not None:
        print("    →", show)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx
    from features import copilot as K
    from features import copilot_memory as CM
    from services import llm

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    clock = {"t": dt.datetime(2026, 10, 30, 9, tzinfo=UTC)}
    lock = threading.Lock()

    def tick_clock():
        with lock:
            clock["t"] += dt.timedelta(seconds=30)
            return clock["t"]
    K._now = tick_clock
    CM.NOW = lambda: clock["t"]

    def tok(email, role, tid, **extra):
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": role, "tenant_id": tid, **extra})}

    # ------------------------------------------------------------------ a
    print("a · Le passage régulier lit chaque compte d'un coup")
    calls = []

    def model(system, user):
        with lock:
            calls.append({"system": system, "user": user})
        if CM.EXTRACT_MARK in system:
            return "[]"
        if CM.SUMMARY_MARK in system:
            return "Résumé."
        return "ok"
    llm._force_complete = model
    now = clock["t"]
    db.copilot_chats.insert_many([{"tenant_id": f"s{s}", "by": f"o@s{s}", "role": "user", "text": f"je fais {k}",
                                   "at": now - dt.timedelta(minutes=k)} for s in range(300) for k in range(20)])
    pending = lambda: db.copilot_chats.count_documents({"role": "user", "memo": {"$exists": False}})   # noqa: E731
    passes = 0
    while pending() and passes < 50:
        CM.learn_due(now)
        passes += 1
    check("300 accounts × 20 new messages: all read within 6 passes (1 h 30 at one pass / 15 min)", passes <= 6 and not pending(),
          (passes, pending()))
    reads = [c for c in calls if CM.EXTRACT_MARK in c["system"]]
    check("one model call per account (its 20 messages together), not one per message", len(reads) == 300, len(reads))
    check("…each call holds one account's 20 messages", all(c["user"].count("\n- je fais ") == 20 for c in reads))

    calls.clear()
    db.copilot_chats.insert_many([{"tenant_id": "big", "by": "o@big", "role": "user", "text": f"long {k} " + "y" * 300,
                                   "at": now - dt.timedelta(minutes=500 - k)} for k in range(200)])
    passes = 0
    while pending() and passes < 20:
        CM.learn_due(now)
        passes += 1
    reads = [c for c in calls if CM.EXTRACT_MARK in c["system"]]
    check("one account's long backlog (200 × 300 chars) is read in chunks until done",
          not pending() and len(reads) >= 5 and any("long 0 " in r["user"] for r in reads), (passes, len(reads)))

    calls.clear()
    db.copilot_chats.insert_many([{"tenant_id": f"w{s}", "by": f"o@w{s}", "role": "user", "text": "je ferme tard",
                                   "at": now} for s in range(40)])

    def slow(system, user):
        time.sleep(0.2)
        return model(system, user)
    llm._force_complete = slow
    real_budget = CM.PASS_SECONDS
    CM.PASS_SECONDS = 0.5
    t0 = time.perf_counter()
    CM.learn_due(now)
    took = time.perf_counter() - t0
    CM.PASS_SECONDS = real_budget
    left = pending()
    check("a slow model: the pass stops at its time budget", took < 3, took)
    check("…and what it did not read waits for the next pass (nothing lost)", 0 < left < 40, left)
    llm._force_complete = model
    while pending():
        CM.learn_due(now)
    check("…then everything is read", not pending())

    # ------------------------------------------------------------------ b
    print("\nb · « Accéder au compte » n'écrit pas la mémoire du commerçant")
    db.tenants.insert_one({"id": "v", "slug": "v", "name": "Shop v", "sector": "salon", "activity_key": "barbier",
                           "plan": "vip", "is_active": True, "subscription_status": "active"})
    db.users.insert_one({"email": "o@v.fr", "role": "business_owner", "tenant_id": "v", "active": True})
    OV = tok("o@v.fr", "business_owner", "v")
    AV = tok("o@v.fr", "business_owner", "v", view_by="admin@fidclic.com", act_by="admin@fidclic.com")   # as admin_commerces makes it
    seen = []

    def m2(system, user):
        seen.append(user)
        if CM.EXTRACT_MARK in system:
            return json.dumps(["Le super admin a testé ici"]) if "super admin" in user else "[]"
        return "ok"
    llm._force_complete = m2
    http("POST", "/api/owner/copilot/chat", OV, json={"message": "Question du propriétaire"})
    r = http("POST", "/api/owner/copilot/chat", AV, json={"message": "Retiens que le super admin a testé ici"})
    check("the super admin's chat still answers", r.status_code == 200, r.text)
    check("…and says nothing is kept for the shop", "rien n'est retenu" in r.json()["reply"], r.json()["reply"])
    items = http("GET", "/api/me/ai-memory", OV).json()["items"]
    check("« Retiens que… » from « Accéder au compte » is not kept in the owner's memory",
          not any("super admin" in i["text"] for i in items), items)
    row = db.copilot_chats.find_one({"tenant_id": "v", "text": "Retiens que le super admin a testé ici"})
    check("the message says who wrote it (view_by)", row and row.get("view_by") == "admin@fidclic.com", row)
    http("POST", "/api/owner/copilot/chat", OV, json={"message": "Et ensuite ?"})
    check("the owner's next question does not carry the super admin's messages", "super admin" not in seen[-1], seen[-1][-400:])
    hist = [m["text"] for m in http("GET", "/api/owner/copilot/chat", OV).json()["messages"]]
    check("the owner's history does not show them", not any("super admin" in t for t in hist), hist)
    ahist = [m["text"] for m in http("GET", "/api/owner/copilot/chat", AV).json()["messages"]]
    check("the super admin sees the owner's conversation and their own",
          "Question du propriétaire" in ahist and "Retiens que le super admin a testé ici" in ahist, ahist)
    http("POST", "/api/owner/copilot/chat", AV, json={"message": "Et pour la suite ?"})
    check("…and their follow-up carries both (to help the owner)", "Question du propriétaire" in seen[-1]
          and "Retiens que le super admin" in seen[-1])
    n = len(seen)
    db.copilot_chats.update_many({"tenant_id": "v"}, {"$unset": {"memo": ""}})   # even if marked unread
    CM.learn_due(clock["t"])
    check("the regular pass never reads the super admin's messages", not any("super admin" in u for u in seen[n:]))
    check("…so no fact comes from them", not any("super admin" in i["text"] for i in http("GET", "/api/me/ai-memory", OV).json()["items"]))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
