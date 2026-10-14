"""
Multi-store PR5 (user, 2026-10-12: « jo store upar selected hoga, campaigns and
offers bhi usi k customers ko jaayenge »; automations per store):
  • a campaign / an offer goes to the MEMBERS of the establishment chosen in
    the menu (their home store) — never to a client who only visited it;
  • with several establishments a send must name one;
  • the Campagnes page lists that establishment's campaigns;
  • every automation belongs to one establishment, writes to its members only;
    one made for the whole shop becomes one per establishment (nothing lost);
  • a one-shop account works as before.

Run: cd api && /usr/local/bin/python3 tests/test_store_campaigns.py
"""
import asyncio
import contextlib
import io
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-store-campaigns")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx
    import features.wallet_passes as WP
    from features import automations as AU

    WP.notify_passes = lambda *a, **k: {"sent": 0}
    WP.notify_customer = lambda *a, **k: {}
    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = datetime.now(timezone.utc)
    db.tenants.insert_many([
        {"id": "t1", "slug": "royal", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active", "is_active": True,
         "branches": [{"id": "pal", "name": "PALISSY", "is_main": True}, {"id": "mon", "name": "MONSTRE"}]},
        {"id": "t2", "slug": "solo", "name": "Solo", "plan": "vip", "subscription_status": "active", "is_active": True},
    ])
    db.card_templates.insert_many([{"tenant_id": "t1", "reward_threshold_stamps": 10, "reward_description": "Coupe"},
                                   {"tenant_id": "t2", "reward_threshold_stamps": 10, "reward_description": "Café"}])
    for cid, home, tid in (("a", "pal", "t1"), ("b", "mon", "t1"), ("c", "pal", "t1"), ("s1", None, "t2")):
        db.customers.insert_one({"id": cid, "tenant_id": tid, "name": f"Client {cid}", "barcode_id": f"FT-{cid.upper()}CAMP01",
                                 **({"branch_id": home} if home else {}), "visits": 3, "points": 0,
                                 "created_at": now - timedelta(days=60), "last_visit_date": now - timedelta(days=2)})
    # b is MONSTRE's member, and came once to PALISSY
    db.visits.insert_one({"id": "v1", "tenant_id": "t1", "customer_id": "b", "branch_id": "pal", "visit_time": now})
    db.users.insert_many([
        {"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True},
        {"email": "a@x.fr", "role": "administrateur", "tenant_id": "t1", "active": True, "branch_ids": ["pal"]},
        {"email": "r@x.fr", "role": "business_owner", "tenant_id": "t2", "active": True},
    ])
    tok = lambda e, r, t="t1": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})  # noqa: E731
    OWNER, ADMIN, SOLO = tok("o@x.fr", "business_owner"), tok("a@x.fr", "administrateur"), tok("r@x.fr", "business_owner", "t2")

    def H(who, store=None):
        return {"Authorization": who, **({"X-FidClic-Store": store} if store else {})}

    def compose(store, who=OWNER, **kw):
        body = {"title": "Coupe -20 %", "message": "Venez !", "segment": "all", "push": True, "wallet": True, **kw}
        return http("POST", "/api/owner/campaigns/compose", headers=H(who, store), json=body)

    print("1. A campaign goes to the chosen establishment's members")
    r = http("POST", "/api/owner/campaigns/audience-preview", headers=H(OWNER, "pal"), json={"audience": {"mode": "all"}})
    check(f"PALISSY's audience: its 2 members, not the visitor from MONSTRE ({r.json().get('count')})", r.json().get("count") == 2)
    r = compose("pal")
    check(f"sent ({r.status_code})", r.status_code == 200)
    doc = db.campaigns.find_one({"id": r.json().get("id")})
    check(f"to a and c only ({sorted(doc['recipient_ids'])})", sorted(doc["recipient_ids"]) == ["a", "c"])
    check("…recorded as PALISSY's", doc["store_ids"] == ["pal"])
    r = compose("mon", title="Monstre day")
    check("MONSTRE's campaign reaches b only", sorted(db.campaigns.find_one({"id": r.json()["id"]})["recipient_ids"]) == ["b"])
    r = compose(None)
    check(f"no establishment chosen: refused, in French ({r.status_code})", r.status_code == 400 and "établissement" in r.json()["detail"])
    r = compose("pal", customer_ids=["b", "c"])
    check("hand-picked: MONSTRE's member is dropped from PALISSY's send",
          r.status_code == 200 and db.campaigns.find_one({"id": r.json()["id"]})["recipient_ids"] == ["c"])
    r = compose("pal", customer_ids=["b"])
    check("only another store's members: refused, nothing sent", r.status_code == 400)

    print("\n2. The Campagnes page lists the chosen establishment's")
    names = lambda store: [x["name"] for x in http("GET", "/api/owner/campaigns/page", headers=H(OWNER, store)).json().get("recent") or []]  # noqa: E731
    check(f"PALISSY: its campaigns ({names('pal')})", "Coupe -20 %" in names("pal") and "Monstre day" not in names("pal"))
    check(f"MONSTRE: its own ({names('mon')})", "Monstre day" in names("mon") and "Coupe -20 %" not in names("mon"))

    print("\n3. Contacter un groupe, the card's banner: the chosen establishment's members")
    r = http("POST", "/api/owner/campaigns/send-to-group", headers=H(OWNER, "mon"),
             json={"customer_ids": ["a", "b"], "name": "Hello", "content": "Bonjour"})
    check(f"group send from MONSTRE: b only ({r.json().get('recipient_ids')})", r.status_code == 200 and r.json()["recipient_ids"] == ["b"])
    check("…refused without an establishment", http("POST", "/api/owner/campaigns/send-to-group", headers=H(OWNER),
                                                     json={"customer_ids": ["a"], "content": "x"}).status_code == 400)
    r = http("POST", "/api/owner/card-overrides/push", headers=H(OWNER, "pal"), json={"filters": {}, "override": {"strip_title": "Promo"}, "send_push": False})
    got = {o["customer_id"] for o in db.customer_card_overrides.find({"tenant_id": "t1"})}
    check(f"the card's banner: PALISSY's members ({sorted(got)})", r.status_code == 200 and got == {"a", "c"})

    print("\n4. Automations: one establishment each")
    db.automations.insert_one({**AU.new_doc("t1", "birthday", status="active"), "store_ids": None, "name": "Anniversaire"})
    db.automation_meta.insert_one({"tenant_id": "t1", "migrated": True})
    pal = http("GET", "/api/owner/automations", headers=H(OWNER, "pal")).json()["rows"]
    mon = http("GET", "/api/owner/automations", headers=H(OWNER, "mon")).json()["rows"]
    check(f"a whole-shop automation became one per establishment ({len(pal)} + {len(mon)})",
          [r["name"] for r in pal] == ["Anniversaire"] and [r["name"] for r in mon] == ["Anniversaire"])
    rows = list(db.automations.find({"tenant_id": "t1"}))
    check("…same words and switch, each its own establishment",
          sorted(tuple(r["store_ids"]) for r in rows) == [("mon",), ("pal",)] and all(r["status"] == "active" for r in rows))
    check("…once (listing again makes no more)", len(http("GET", "/api/owner/automations", headers=H(OWNER, "pal")).json()["rows"]) == 1
          and db.automations.count_documents({"tenant_id": "t1"}) == 2)
    row_pal = next(r for r in rows if r["store_ids"] == ["pal"])
    cust = {c["id"]: c for c in db.customers.find({"tenant_id": "t1"}, {"_id": 0})}
    check("PALISSY's automation writes to its members", AU.matches("t1", row_pal, cust["a"]) and AU.matches("t1", row_pal, cust["c"]))
    check("…not to MONSTRE's member who came once", not AU.matches("t1", row_pal, cust["b"]))
    body = {**{k: v for k, v in row_pal.items() if k in ("scenario", "name", "message", "trigger", "targeting", "schedule")},
            "status": "draft", "name": "Anniversaire Monstre"}
    r = http("POST", "/api/owner/automations", headers=H(OWNER, "mon"), json=body)
    check(f"created in MONSTRE: MONSTRE's ({r.status_code})", r.status_code == 200
          and db.automations.find_one({"id": r.json().get("id")})["store_ids"] == ["mon"])
    mon_row = db.automations.find_one({"store_ids": ["mon"], "name": "Anniversaire"})
    r = http("POST", f"/api/owner/automations/{mon_row['id']}/status", headers=H(ADMIN, "pal"), json={"status": "paused"})
    check(f"PALISSY's administrateur cannot touch MONSTRE's ({r.status_code})", r.status_code == 403)
    r = http("POST", f"/api/owner/automations/{row_pal['id']}/status", headers=H(ADMIN, "pal"), json={"status": "paused"})
    check(f"…but manages PALISSY's ({r.status_code})", r.status_code == 200)
    offers = lambda store: [o["name"] for o in http("GET", "/api/owner/automations", headers=H(OWNER, store)).json().get("offers") or []]  # noqa: E731
    check(f"the offers an automation can link: the establishment's own ({offers('mon')})", "Coupe -20 %" not in offers("mon"))

    print("\n5. A one-shop account: as before")
    r = http("POST", "/api/owner/campaigns/compose", headers=H(SOLO),
             json={"title": "Solo", "message": "Hi", "segment": "all", "push": True})
    check(f"no establishment to choose: sent to everyone ({r.status_code})", r.status_code == 200
          and db.campaigns.find_one({"id": r.json()["id"]})["recipient_ids"] == ["s1"])
    db.automations.insert_one({**AU.new_doc("t2", "birthday", status="active"), "store_ids": None})
    db.automation_meta.insert_one({"tenant_id": "t2", "migrated": True})
    http("GET", "/api/owner/automations", headers=H(SOLO))
    check("its automations are not split", db.automations.count_documents({"tenant_id": "t2"}) == 1)

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
