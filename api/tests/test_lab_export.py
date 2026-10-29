"""
FidClic Lab — the anonymous export (user, 2026-10-29: « Royal Trim Liberté
ka data se seekhna, production pe nahi, read-only export pe »).

Super admin › Commerce › « Export anonymisé (FidClic Lab) »: one shop's
history, read only, without who the clients are — no name, phone, e-mail,
address, birthday or free text; client / store / campaign ids replaced by
codes that change at every export. Downloaded in parts (Vercel caps one
answer at 4.5 MB) and logged. The lab then runs on a laptop.

Run: cd api && /usr/local/bin/python3 tests/test_lab_export.py
"""
import asyncio
import contextlib
import copy
import datetime as dt
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-lab-export")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
UTC = dt.timezone.utc
SECRET = "ZZSECRET"            # planted in every personal field: must never come out


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
    from features import lab_export as LX

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(UTC).replace(microsecond=0)
    db.tenants.insert_many([
        {"id": "rt", "name": f"Royal {SECRET}", "slug": "rt", "sector": "salon", "activity_key": "barbier",
         "plan": "vip", "is_active": True, "address": f"1 rue {SECRET}", "phone": f"06{SECRET}",
         "branches": [{"id": "b1", "name": f"Liberté {SECRET}", "status": "open"},
                      {"id": "b2", "name": "Nord", "status": "open"}]},
        {"id": "other", "name": "Autre", "sector": "cafe", "is_active": True}])
    db.card_templates.insert_one({"tenant_id": "rt", "programme": "stamps"})
    db.users.insert_many([{"email": "boss@fidclic.com", "role": "super_admin", "first_name": "B"},
                          {"email": "boss2@fidclic.com", "role": "super_admin", "first_name": "C"},
                          {"email": "team@fidclic.com", "role": "admin", "first_name": "T"},
                          {"email": "o@rt.fr", "role": "business_owner", "tenant_id": "rt", "active": True}])
    tok = lambda e, r, t=None: {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    BOSS, BOSS2 = tok("boss@fidclic.com", "super_admin"), tok("boss2@fidclic.com", "super_admin")
    TEAM, OWNER = tok("team@fidclic.com", "admin"), tok("o@rt.fr", "business_owner", "rt")

    for i in range(7):
        db.customers.insert_one({
            "id": f"cust-{i}", "tenant_id": "rt", "barcode_id": f"BAR{SECRET}{i}", "name": f"Jean {SECRET}",
            "first_name": SECRET, "last_name": SECRET, "phone": f"06{SECRET}", "email": f"{SECRET}@x.fr",
            "birthday": "1990-05-12" if i == 0 else ("07-14" if i == 1 else None), "postal_code": "37000",
            "address": SECRET, "city": SECRET, "notes": SECRET, "latitude": 47.39, "longitude": 0.68,
            "acquisition_source": "employee:" + SECRET if i == 2 else "qr", "gender": "homme" if i < 4 else "femme",
            "branch_id": "b1" if i < 5 else "b2", "pass_issued": True, "created_at": now - dt.timedelta(days=200),
            "deleted_at": now if i == 6 else None, "paused_at": now if i == 5 else None,
            "brain": {"note": SECRET}})
        for k in range(3):
            db.visits.insert_one({
                "id": f"v{i}{k}", "tenant_id": "rt", "customer_id": f"cust-{i}", "customer_name": SECRET,
                "amount_paid": 18.0 + k, "branch_id": "b1", "visit_time": now - dt.timedelta(days=21 * (3 - k)),
                "items": [{"item_id": "coupe", "name": "Coupe", "qty": 1, "price": 18.0, "note": SECRET}],
                "note": SECRET, "by": f"{SECRET}@x.fr", "programme": "stamps"})
    db.customers.insert_one({"id": "o1", "tenant_id": "other", "name": "Other shop client"})
    db.visits.insert_one({"id": "ov", "tenant_id": "other", "customer_id": "o1", "visit_time": now, "amount_paid": 3})
    db.campaigns.insert_one({"id": "camp1", "tenant_id": "rt", "name": "Promo d'automne", "kind": "offre",
                             "template": "ia:en_retard", "status": "sent", "sent_at": now - dt.timedelta(days=20),
                             "content": "Bonjour {prénom} <b>-20 %</b>", "recipient_ids": ["cust-0", "cust-1"],
                             "holdout_ids": ["cust-2"], "sender_name": SECRET, "created_by": f"{SECRET}@x.fr"})
    # « Contacter » one client: the owner may write about that client — its text never leaves
    db.campaigns.insert_one({"id": "camp2", "tenant_id": "rt", "name": f"Pour {SECRET}", "kind": "message",
                             "template": "client", "status": "sent", "sent_at": now - dt.timedelta(days=3),
                             "content": f"{SECRET}, votre rendez-vous", "recipient_ids": ["cust-4"]})
    db.automation_log.insert_one({"id": "l1", "tenant_id": "rt", "automation_id": "auto1", "scenario": "inactive",
                                  "customer_id": "cust-3", "sent_at": now - dt.timedelta(days=5), "status": "sent",
                                  "title": SECRET, "body": SECRET, "target_url": SECRET})
    db.push_notifications.insert_one({"tenant_id": "rt", "customer_id": "cust-0", "campaign_id": "camp1",
                                      "type": "campaign", "title": SECRET, "body": SECRET,
                                      "sent_at": now - dt.timedelta(days=20), "opened_at": now - dt.timedelta(days=19)})
    before = {c: list(db[c].find({}, {"_id": 0})) for c in ("tenants", "customers", "visits", "campaigns",
                                                            "automation_log", "push_notifications")}

    def fetch(H, tid="rt"):
        r = http("POST", "/api/admin/ai/lab/exports", headers=H, json={"tenant_id": tid})
        if r.status_code != 200:
            return r, None
        s = r.json()
        parts = [http("GET", f"/api/admin/ai/lab/exports/{s['id']}/parts/{n}", headers=H) for n in range(s["parts"])]
        return r, parts

    print("Qui peut exporter")
    check("a business owner cannot", fetch(OWNER)[0].status_code in (401, 403))
    check("a FidClic team member (not Super Admin) cannot", fetch(TEAM)[0].status_code in (401, 403))
    check("no token, no export", fetch({})[0].status_code in (401, 403))
    check("an unknown shop: 404", fetch(BOSS, "nope")[0].status_code == 404)

    print("\nL'export")
    r, parts = fetch(BOSS)
    s = r.json()
    check("the Super Admin gets an export in parts", r.status_code == 200 and s["parts"] >= 2
          and all(p.status_code == 200 for p in parts), (r.status_code, [p.status_code for p in parts or []]))
    data = LX.assemble([p.json() for p in parts])
    blob = json.dumps(data, default=str)
    check("no personal field comes out (name, phone, e-mail, address, notes, free text, staff e-mail)",
          SECRET not in blob, [blob[max(0, blob.find(SECRET) - 80):blob.find(SECRET) + 20]])
    check("no real client / campaign / store id comes out",
          not any(x in blob for x in ("cust-0", "cust-6", "camp1", "\"b1\"", "auto1", "BAR")))
    check("the other shop is not in it", "Other shop" not in blob and len(data["visits"]) == 21)
    check("counts: 7 clients, 21 visits, 2 campaigns, 1 automation message, 1 push",
          s["counts"] == {"customers": 7, "visits": 21, "campaigns": 2, "automation_log": 1, "push": 1}, s["counts"])
    cs = {c["c"]: c for c in data["customers"]}
    check("each visit points to an exported client", all(v["c"] in cs for v in data["visits"]))
    camp = next(c for c in data["campaigns"] if c["holdout"])
    one = next(c for c in data["campaigns"] if not c["holdout"])
    check("the campaign's recipients and témoin point to exported clients",
          set(camp["recipients"]) <= set(cs) and set(camp["holdout"]) <= set(cs) and len(camp["holdout"]) == 1)
    check("a push and an automation message point to exported clients",
          data["push"][0]["c"] in cs and data["automation_log"][0]["c"] in cs and data["push"][0]["campaign"] == camp["id"])
    ages = sorted(c["age"] for c in data["customers"] if c.get("age") is not None)
    check("age in years from a full birthday only (1990-05-12 → 36)", ages == [36], ages)
    check("postal code kept to its département (37)", {c.get("postal") for c in data["customers"]} == {"37"})
    check("source kept as its kind (« employee », « qr »)", {c.get("source") for c in data["customers"]} == {"employee", "qr"})
    check("genre kept", {c.get("gender") for c in data["customers"]} == {"homme", "femme"})
    check("paused / deleted clients are flagged, not dropped",
          sum(1 for c in data["customers"] if c.get("deleted")) == 1 and sum(1 for c in data["customers"] if c.get("paused")) == 1)
    check("two stores, by code", len({c["store"] for c in data["customers"]}) == 2 and len(data["shop"]["stores"]) == 2)
    v = data["visits"][0]
    check("a visit keeps its time, amount and products (no product note)",
          v["at"] and v["amount"] in (18.0, 19.0, 20.0) and v["items"][0] == {"id": "coupe", "name": "Coupe", "qty": 1, "price": 18.0})
    check("the shop: activity, sector, programme — not its name",
          data["shop"]["activity"] == "barbier" and data["shop"]["sector"] == "salon" and data["shop"]["programme"] == "stamps")
    check("a group campaign keeps its text, without tags", camp["content"] == "Bonjour {prénom} -20 %"
          and camp["title"] == "Promo d'automne", camp)
    check("a one-client message keeps no text at all", one["content"] is None and one["title"] is None, one)
    check("no GPS position", "47.39" not in blob and "0.68" not in blob)

    print("\nLecture seule, et tracé")
    after = {c: list(db[c].find({}, {"_id": 0})) for c in before}
    check("nothing of the shop changed (tenants, clients, visits, campaigns, logs, pushes)", after == before)
    log = db.audit_logs.find_one({"action": "lab.export"}) or {}
    check("the export is in the Journal d'activité (who, which shop)",
          log.get("actor") == "boss@fidclic.com" and log.get("tenant_id") == "rt", log)

    print("\nCodes et parties")
    _, parts2 = fetch(BOSS)
    data2 = LX.assemble([p.json() for p in parts2])
    check("a new export, new codes (two files cannot be joined)",
          not {c["c"] for c in data["customers"]} & {c["c"] for c in data2["customers"]})
    sid = s["id"]
    check("another Super Admin cannot read my export's parts",
          http("GET", f"/api/admin/ai/lab/exports/{sid}/parts/0", headers=BOSS2).status_code == 404)
    check("a part that does not exist: 404", http("GET", f"/api/admin/ai/lab/exports/{sid}/parts/99", headers=BOSS).status_code == 404)
    check("a negative part: 404", http("GET", f"/api/admin/ai/lab/exports/{sid}/parts/-1", headers=BOSS).status_code in (404, 422))
    db.lab_exports.update_one({"id": sid}, {"$set": {"expires_at": now - dt.timedelta(minutes=1)}})
    check("after an hour the export is gone (and its key with it)",
          http("GET", f"/api/admin/ai/lab/exports/{sid}/parts/0", headers=BOSS).status_code == 404
          and not db.lab_exports.find_one({"id": sid}))
    LX.PART_ROWS, keep = 4, LX.PART_ROWS
    r, parts3 = fetch(BOSS)
    check("big shops come in more parts, none larger than the cap",
          r.json()["parts"] >= 1 + 2 + 6 and all(len(p.json().get("rows") or []) <= 4 for p in parts3), r.json())
    check("…and they assemble to the same counts", len(LX.assemble([p.json() for p in parts3])["visits"]) == 21)
    LX.PART_ROWS = keep
    big = copy.deepcopy(data)
    check("assemble keeps the order of the parts it is given", LX.assemble([p.json() for p in parts])["shop"] == big["shop"])

    print("\nBoutique vide")
    db.tenants.insert_one({"id": "empty", "name": "Vide", "sector": "salon", "is_active": True})
    r, parts4 = fetch(BOSS, "empty")
    d4 = LX.assemble([p.json() for p in parts4])
    check("an empty shop exports an empty file, no error", r.status_code == 200 and d4["customers"] == [] and d4["visits"] == [])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
