"""
Golden set on the shops' real data, anonymized (user, 2026-11-09: « asli data of
businesses ko copy krke bhi golden set mein chalao »; every shop on by default,
a super-admin switch turns one off).

  · snapshot(): names, phones, e-mails, birth dates, postal codes and every id
    leave; visits, amounts, products, stores and dates stay, so the figures are
    the shop's own.
  · build_due(): at night, one private file per shop that is on.
  · the CI reads them with its own key, loads them in memory, asks questions
    whose answers the tools compute, and reports without a figure: the repo
    is public.

Run: cd api && python3 tests/test_golden_real.py
"""
import asyncio
import datetime as dt
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-golden-real")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server
    import auth
    import httpx
    from features import golden_real as GR, golden_set as GS
    from services import blob_private as BP

    db = server.db
    UTC = dt.timezone.utc
    night = dt.datetime(2026, 11, 9, 2, 30, tzinfo=UTC)            # 03:30 in Paris

    store = {}
    BP.configured = lambda: True
    BP.put = lambda path, data, ct="": store.__setitem__(path, data) or True
    BP.get = lambda path: store.get(path)
    BP.delete = lambda paths: [store.pop(p, None) for p in paths] and True

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    # a shop like Royal Trim: three stores, real-looking clients and visits
    db.tenants.insert_one({"id": "rt", "slug": "royal", "name": "ROYAL TRIM LIBERTÉ", "sector": "salon", "activity_key": "barbier",
                           "plan": "vip", "is_active": True, "subscription_status": "active",
                           "branches": [{"id": "main", "name": "ROYAL TRIM LIBERTÉ", "is_main": True},
                                        {"id": "pal", "name": "ROYAL TRIM PALISSY"}, {"id": "pm", "name": "ROYAL TRIM PL-MONSTRE"}]})
    db.tenants.insert_one({"id": "gs", "slug": "green", "name": "GREEN SMOKE", "sector": "cbd", "plan": "gold", "is_active": True})
    db.tenants.insert_one({"id": "demo1", "slug": "demo", "name": "Demo", "demo": True, "is_active": True})
    db.card_templates.insert_one({"tenant_id": "rt", "programme": "stamps", "reward_threshold_stamps": 10, "reward_description": "Coupe offerte"})
    secrets_ = []
    for i in range(40):
        name = f"Karaboualy{i} Nathan{i}"
        phone, email = f"06{i:08d}", f"nathan{i}@gmail.com"
        secrets_ += [name, f"Karaboualy{i}", phone, email, f"c-real-{i}", "1990-05-1", "37000"]
        db.customers.insert_one({"id": f"c-real-{i}", "tenant_id": "rt", "name": name, "phone": phone, "email": email,
                                 "birth_date": f"1990-05-1{i % 10}", "birthday": f"05-1{i % 10}", "postal_code": "37000",
                                 "barcode_id": f"FT-REAL{i:04d}", "branch_id": ["main", "pal", "pm"][i % 3],
                                 "created_at": night - dt.timedelta(days=200 - i), "visits": 0, "points": 0})
    items = [("Coupe homme", 20.0), ("Barbe", 10.0), ("Coupe + barbe", 28.0)]
    for n in range(300):
        cid = f"c-real-{n % 40}"
        nm, price = items[n % 3]
        db.visits.insert_one({"id": f"v-real-{n}", "tenant_id": "rt", "customer_id": cid, "branch_id": ["main", "pal", "pm"][n % 3],
                              "amount_paid": price, "visit_time": night - dt.timedelta(hours=7 * n + 3),
                              "items": [{"name": nm, "qty": 1, "price": price, "line_total": price}], "points_awarded": 1,
                              "staff_email": "mohanedidris70@gmail.com"})
    for c in db.customers.find({"tenant_id": "rt"}):
        mine = list(db.visits.find({"customer_id": c["id"]}))
        db.customers.update_one({"id": c["id"]}, {"$set": {"visits": len(mine), "total_amount_paid": sum(v["amount_paid"] for v in mine),
                                                           "last_visit_date": max((v["visit_time"] for v in mine), default=None)}})
    secrets_ += ["mohanedidris70", "rt", "c-real-1", "v-real-1"]

    print("\n1. The snapshot keeps the figures and nothing that names a person")
    snap = GR.snapshot("rt", night)
    raw = json.dumps(snap, default=str, ensure_ascii=False)
    leaks = [s for s in set(secrets_) if s in raw and s not in ("rt",)]
    check("no name, phone, e-mail, birth date, postal code, staff e-mail or id of the shop", not leaks)
    check("not even the shop's own id", '"rt"' not in raw)
    check("every visit of the last 400 days, the same euros",
          len(snap["visits"]) == 300 and round(sum(v["amount_paid"] for v in snap["visits"]), 2)
          == round(sum(v["amount_paid"] for v in db.visits.find({"tenant_id": "rt"})), 2))
    ids = {c["id"] for c in snap["customers"]}
    check("each visit still belongs to its client", all(v["customer_id"] in ids for v in snap["visits"]))
    check("the stores keep their names, under new ids",
          sorted(b["name"] for b in snap["shop"]["branches"]) == ["ROYAL TRIM LIBERTÉ", "ROYAL TRIM PALISSY", "ROYAL TRIM PL-MONSTRE"]
          and not any(b["id"] in ("pal", "pm") for b in snap["shop"]["branches"])
          and any(b["id"] == "main" for b in snap["shop"]["branches"]))      # « main » is the account's own store: a constant
    check("the products keep their names", {i["name"] for v in snap["visits"] for i in v["items"]} == {"Coupe homme", "Barbe", "Coupe + barbe"})
    check("clients get made-up names, all different", len({c["name"] for c in snap["customers"]}) == 40)
    check("the card's rule comes along", snap["cards"][0]["reward_threshold_stamps"] == 10)
    again = GR.snapshot("rt", night)
    check("two nights: new ids every time, nothing to link", not ({c["id"] for c in again["customers"]} & ids))

    print("\n2. At night, one private file per shop that is on")
    check("daytime: nothing", GR.build_due(dt.datetime(2026, 11, 9, 12, 0, tzinfo=UTC)).get("skipped") == "daytime")
    out = GR.build_due(night)
    st = {s["tenant_id"]: s for s in db.golden_real_state.find({}, {"_id": 0})}
    check("Royal Trim and Green Smoke are built (on by default)", set(st) == {"rt", "gs"})
    check("a demo shop is not", "demo1" not in st)
    check("the file is the shop's snapshot, gzipped, under an opaque name",
          json.loads(gzip.decompress(store[st["rt"]["path"]]))["shop"]["name"] == "ROYAL TRIM LIBERTÉ" and "rt" not in st["rt"]["path"].split("/")[-1])
    n_files = len(store)
    GR.build_due(night + dt.timedelta(minutes=30))
    check("once a night", len(store) == n_files and db.golden_real_state.count_documents({}) == 2)

    print("\n3. The switch")
    os.environ["GOLDEN_SNAPSHOT_KEY"] = "k" * 40
    A = {"Authorization": "Bearer " + auth.create_access_token({"sub": "a@fidclic.fr", "role": "super_admin"})}
    db.users.insert_one({"email": "a@fidclic.fr", "role": "super_admin"})
    rows = http("GET", "/api/admin/ai/golden-real", A).json()["shops"]
    check("the super admin sees every shop, on by default", {r["id"]: r["on"] for r in rows if r["id"] in ("rt", "gs")} == {"rt": True, "gs": True})
    path_gs = st["gs"]["path"]
    r = http("PUT", "/api/admin/ai/golden-real/gs", A, json={"on": False})
    check("off: saved, and its file is gone at once", r.status_code == 200 and path_gs not in store
          and not db.golden_real_state.find_one({"tenant_id": "gs"}))
    GR.build_due(night + dt.timedelta(days=1))
    check("and it is not built again", not db.golden_real_state.find_one({"tenant_id": "gs"}))
    O = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@rt.fr", "role": "business_owner", "tenant_id": "rt"})}
    check("a shop owner can't see or flip it", http("GET", "/api/admin/ai/golden-real", O).status_code == 403
          and http("PUT", "/api/admin/ai/golden-real/rt", O, json={"on": False}).status_code == 403)

    print("\n4. What GitHub reads, with its own key")
    check("no key: refused", http("GET", "/api/golden/real").status_code == 401)
    check("a wrong key: refused", http("GET", "/api/golden/real", {"X-Golden-Key": "nope"}).status_code == 401)
    man = http("GET", "/api/golden/real", {"X-Golden-Key": "k" * 40}).json()
    check("the list: an opaque id and the trade, no name or id of a shop",
          len(man["shops"]) == 1 and "rt" not in json.dumps(man) and "ROYAL" not in json.dumps(man))
    body = http("GET", f"/api/golden/real/{man['shops'][0]['sid']}", {"X-Golden-Key": "k" * 40})
    check("the file comes down", body.status_code == 200 and json.loads(gzip.decompress(body.content))["shop"]["sector"] == "salon")
    check("an unknown file: 404", http("GET", "/api/golden/real/../../etc", {"X-Golden-Key": "k" * 40}).status_code == 404)
    check("each download is in the audit log", db.audit_logs.count_documents({"action": "golden_real.download"}) >= 1)
    os.environ.pop("GOLDEN_SNAPSHOT_KEY")
    check("no key set on the server: closed", http("GET", "/api/golden/real", {"X-Golden-Key": "k" * 40}).status_code in (401, 503))

    print("\n5. In the CI: loaded in memory, asked, graded")
    import importlib
    ci = db                       # the CI's own in-memory database: the one the tools read
    shop = GR.load(ci, snap, 1)
    bank = GR.questions(ci, shop)
    check("about thirty questions for a three-store barber", 25 <= len(bank) <= 45)
    check("ids say which real shop, never its name", all(q["id"].startswith("reel1-") for q in bank))
    old_db = GS._db
    GS.init(ci)
    try:
        GR.use(shop)
        truths = {q["id"]: GS.truth(q) for q in bank if not q.get("status")}
        check("the tools answer every question", all(t["ok"] for t in truths.values()))
        agree = [q["id"] for q in bank if not q.get("status") and GS.oracle(q) is not None
                 and [v["value"] for v in GS.oracle(q) if v["kind"] != "text"]
                 != [v["value"] for v in truths[q["id"]]["need"] if v["kind"] != "text"]]
        check("…and say what the rows say (counted apart)", not agree)
        from services import llm
        llm._force_complete = GS.fake_model          # the test model: reads with its tools, answers what it read
        db.platform_settings.update_one({"key": "ai_meter"}, {"$set": {"cap_mode": "fixed", "global_day_eur": 50, "shop_day_eur": 50,
                                                                       "user_per_min": 100000}}, upsert=True)
        rep = GR.run(http, ci, [shop])
        llm._force_complete = None
        check("the right answers pass, all, through the real endpoints", rep["ok"] and rep["passed"] == rep["total"])
        bad = GR.run(lambda *a, **k: None, ci, [shop], answer=lambda q: "J'ai envoyé la campagne, 06 12 34 56 78.")
        check("wrong ones fail", not bad["ok"])
        pub = json.dumps(GR.public(bad), ensure_ascii=False)
        check("the public report: no answer, no figure, no name of a client",
              "06 12" not in pub and not any(ch.isdigit() for f in GR.public(bad)["failures"] for w in f["why"] for ch in w)
              and not any(c["name"] in pub for c in snap["customers"]))
    finally:
        GS.init(old_db)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
