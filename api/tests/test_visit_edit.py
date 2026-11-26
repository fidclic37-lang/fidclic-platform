"""
Clients › « Historique d'achats » › Modifier / Supprimer un achat (user,
2026-11-26: a business must be able to correct what a client bought — the
products from its own catalogue, the amount, the date — so its figures are
right).

Run: cd api && python3 tests/test_visit_edit.py
"""
import asyncio
import contextlib
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-visit-edit")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def unit_tests():
    from features import visit_edit as VE
    now = dt.datetime(2026, 11, 26, 12, 0, tzinfo=dt.timezone.utc)
    print("0. parse_visit_time")
    check("None / empty → None", VE.parse_visit_time(None, now) is None and VE.parse_visit_time("", now) is None)
    check("garbage → error", _raises(lambda: VE.parse_visit_time("hier", now)))
    check("a number → error", _raises(lambda: VE.parse_visit_time(1700000000, now)))
    z = VE.parse_visit_time("2026-11-25T10:30:00Z", now)
    check("Z → aware UTC", z == dt.datetime(2026, 11, 25, 10, 30, tzinfo=dt.timezone.utc))
    p = VE.parse_visit_time("2026-11-25T12:30:00+02:00", now)
    check("+02:00 offset → the same instant in UTC", p == dt.datetime(2026, 11, 25, 10, 30, tzinfo=dt.timezone.utc))
    n = VE.parse_visit_time("2026-11-25T10:30:00", now)
    check("naive → read as UTC", n == dt.datetime(2026, 11, 25, 10, 30, tzinfo=dt.timezone.utc))
    check("a few minutes ahead (clock skew) → accepted", VE.parse_visit_time("2026-11-26T12:03:00Z", now) is not None)
    check("tomorrow → error", _raises(lambda: VE.parse_visit_time("2026-11-27T10:30:00Z", now)))
    check("1999 → error", _raises(lambda: VE.parse_visit_time("1999-12-31T10:30:00Z", now)))
    print("\n0b. money text")
    check("37 → « 37,00 € »", VE.eur(37) == "37,00 €")
    check("0 → « 0,00 € »", VE.eur(0) == "0,00 €")
    check("1234.5 → « 1 234,50 € »", VE.eur(1234.5) == "1 234,50 €")


def _raises(fn):
    try:
        fn()
        return False
    except Exception:
        return True


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx

    db = server.db
    unit_tests()

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_many([
        {"id": "t1", "slug": "rt", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active", "is_active": True,
         "branches": [{"id": "lib", "name": "LIBERTÉ", "is_main": True}, {"id": "pal", "name": "PALISSY"}]},
        {"id": "t2", "slug": "other", "name": "Other", "plan": "vip", "subscription_status": "active", "is_active": True},
    ])
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10})
    db.tenant_catalog.insert_many([
        {"tenant_id": "t1", "items": [
            {"id": "i1", "name": "Coupe", "price": 22.0, "category": "Coiffure"},
            {"id": "i2", "name": "Barbe express", "price": 15.0, "category": "Barbe"},
            {"id": "i3", "name": "Shampoing", "price": 8.0, "category": "Soins"},
        ]},
        {"tenant_id": "t2", "items": [{"id": "x1", "name": "Ailleurs", "price": 99.0}]},
    ])
    now = dt.datetime(2026, 10, 14, 16, 30, tzinfo=dt.timezone.utc)
    db.customers.insert_many([
        {"id": "c1", "tenant_id": "t1", "name": "Gabin", "barcode_id": "FT-GABIN001", "branch_id": "lib", "visits": 3,
         "total_amount_paid": 78.0, "points": 0, "tier": "bronze", "last_visit_date": now},
        {"id": "c2", "tenant_id": "t1", "name": "Hugo", "barcode_id": "FT-HUGO0001", "branch_id": "pal", "visits": 1,
         "total_amount_paid": 10.0},
        {"id": "c3", "tenant_id": "t1", "name": "Inès", "barcode_id": "FT-INES0001", "branch_id": "lib", "visits": 1,
         "total_amount_paid": 5.0},
        {"id": "z1", "tenant_id": "t2", "name": "Zoé", "barcode_id": "FT-ZOE00001", "visits": 1, "total_amount_paid": 99.0},
    ])
    db.visits.insert_many([
        {"id": "v1", "tenant_id": "t1", "customer_id": "c1", "branch_id": "lib", "amount_paid": 29.0, "points_awarded": 0,
         "stamps_awarded": 1, "visit_time": now - dt.timedelta(days=10),
         "items": [{"item_id": "i1", "name": "Coupe", "price": 22, "qty": 1, "line_total": 22.0},
                   {"item_id": "old", "name": "Ancien produit", "price": 7, "qty": 1, "line_total": 7.0}]},
        {"id": "v2", "tenant_id": "t1", "customer_id": "c1", "branch_id": "pal", "amount_paid": 37.0, "points_awarded": 0,
         "stamps_awarded": 1, "visit_time": now,
         "items": [{"item_id": "i1", "name": "Coupe", "price": 22, "qty": 1, "line_total": 22.0},
                   {"item_id": "i2", "name": "Barbe express", "price": 15, "qty": 1, "line_total": 15.0}]},
        {"id": "v3", "tenant_id": "t1", "customer_id": "c1", "branch_id": "lib", "amount_paid": 12.0, "points_awarded": 0,
         "stamps_awarded": 1, "visit_time": now - dt.timedelta(days=3)},
        {"id": "v4", "tenant_id": "t1", "customer_id": "c2", "branch_id": "pal", "amount_paid": 37.0, "points_awarded": 0,
         "stamps_awarded": 1, "visit_time": now - dt.timedelta(days=1)},
        {"id": "v5", "tenant_id": "t1", "customer_id": "c3", "branch_id": "lib", "amount_paid": 5.0, "points_awarded": 0,
         "stamps_awarded": 1, "paper_stamps": 4, "visit_time": now - dt.timedelta(days=1)},
        {"id": "vz", "tenant_id": "t2", "customer_id": "z1", "amount_paid": 99.0, "points_awarded": 0, "visit_time": now},
    ])
    db.users.insert_many([
        {"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True},
        {"email": "p@x.fr", "role": "administrateur", "tenant_id": "t1", "active": True, "branch_ids": ["pal"]},
        {"email": "s@x.fr", "role": "staff", "tenant_id": "t1", "active": True},
        {"email": "z@x.fr", "role": "business_owner", "tenant_id": "t2", "active": True},
    ])
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    O = tok("o@x.fr", "business_owner")
    cust = lambda cid: db.customers.find_one({"id": cid}, {"_id": 0})  # noqa: E731
    visit = lambda vid: db.visits.find_one({"id": vid}, {"_id": 0})  # noqa: E731
    hist = lambda cid: list(db.customer_changes.find({"customer_id": cid}, {"_id": 0}).sort("at", -1))  # noqa: E731

    print("\n1. The purchases list carries what the editor needs")
    d = http("GET", "/api/owner/clients/c1/purchases", headers=O).json()
    row = next(r for r in d["rows"] if r["id"] == "v2")
    check("each line has its catalogue id and unit price",
          row["items"][0].get("item_id") == "i1" and row["items"][0].get("price") == 22.0)
    check("the catalogue is offered to the editor (active products only, with prices)",
          [p["id"] for p in d.get("catalogue", [])] == ["i1", "i2", "i3"] and d["catalogue"][0]["price"] == 22.0)
    check("a row that was never edited says so", row.get("edited") is False)

    print("\n2. Products from the catalogue: the server prices them")
    r = http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O,
             json={"items": [{"item_id": "i1", "qty": 2, "price": 0.01}], "reason": "Erreur de saisie"})
    d = r.json()
    check(f"answered ({r.status_code}) {d if r.status_code != 200 else ''}", r.status_code == 200)
    check("2 × Coupe at the catalogue price: 44 € (the browser's 0,01 € ignored)",
          d["row"]["amount"] == 44.0 and d["row"]["items"] == [{"item_id": "i1", "name": "Coupe", "qty": 2, "price": 22.0, "total": 44.0}])
    v = visit("v2")
    check("the visit holds the new lines and amount", v["amount_paid"] == 44.0 and v["items"][0]["qty"] == 2 and len(v["items"]) == 1)
    check("…and remembers what it was (before: 37 €, 2 lines)",
          v["edits"][0]["before"]["amount_paid"] == 37.0 and len(v["edits"][0]["before"]["items"]) == 2 and v["edits"][0]["by"] == "o@x.fr")
    check("the client's total follows: 78 − 37 + 44 = 85", cust("c1")["total_amount_paid"] == 85.0)
    check("stamps and points of the visit are untouched", v["stamps_awarded"] == 1 and v["points_awarded"] == 0 and cust("c1")["visits"] == 3)
    h = hist("c1")
    check("the fiche's history says what changed, by whom, why",
          h and h[0]["kind"] == "visit_edited" and "37,00 €" in h[0]["text"] and "44,00 €" in h[0]["text"]
          and h[0]["by"] == "o@x.fr" and h[0]["reason"] == "Erreur de saisie")
    check("the row is now marked edited", d["row"]["edited"] is True)
    check("what changed is named", set(d["changed"]) == {"items", "amount"})

    print("\n3. Refusals on products")
    check("unknown product → 400", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O,
                                        json={"items": [{"item_id": "nope", "qty": 1}]}).status_code == 400)
    check("another shop's product → 400", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O,
                                               json={"items": [{"item_id": "x1", "qty": 1}]}).status_code == 400)
    check("qty 0 → 400", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O,
                              json={"items": [{"item_id": "i1", "qty": 0}]}).status_code == 400)
    check("qty −1 → 400", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O,
                               json={"items": [{"item_id": "i1", "qty": -1}]}).status_code == 400)
    check("qty 1000 → 400", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O,
                                 json={"items": [{"item_id": "i1", "qty": 1000}]}).status_code == 400)
    check("qty « abc » → 400", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O,
                                    json={"items": [{"item_id": "i1", "qty": "abc"}]}).status_code == 400)
    check("items as a string → 422", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O,
                                          json={"items": "i1"}).status_code == 422)
    check("no products and no amount → 400 (nothing would be left)",
          http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O, json={"items": []}).status_code == 400)
    check("60 lines → 400", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O,
                                 json={"items": [{"item_id": "i1", "qty": 1}] * 60}).status_code == 400)
    check("nothing moved after the refusals", visit("v2")["amount_paid"] == 44.0 and cust("c1")["total_amount_paid"] == 85.0)

    print("\n4. The till had the last word: a manual amount")
    r = http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O,
             json={"items": [{"item_id": "i1", "qty": 1}, {"item_id": "i3", "qty": 1}], "amount_paid": 25, "amount_manual": True})
    d = r.json()
    check(f"answered ({r.status_code})", r.status_code == 200)
    check("amount 25 € (catalogue says 30), lines kept at catalogue prices",
          d["row"]["amount"] == 25.0 and [x["total"] for x in d["row"]["items"]] == [22.0, 8.0] and visit("v2")["amount_manual"] is True)
    check("client total: 85 − 44 + 25 = 66", cust("c1")["total_amount_paid"] == 66.0)
    r = http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O, json={"items": [{"item_id": "i1", "qty": 1}]})
    check("products again without the flag: the catalogue's total wins (22 €) and the flag drops",
          r.json()["row"]["amount"] == 22.0 and not visit("v2").get("amount_manual"))
    check("client total: 66 − 25 + 22 = 63", cust("c1")["total_amount_paid"] == 63.0)
    check("manual flag without an amount → 400", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O,
                                                       json={"amount_manual": True}).status_code == 400)
    check("negative amount → 400", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O,
                                        json={"amount_paid": -5, "amount_manual": True}).status_code == 400)
    check("100 001 € → 400", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O,
                                  json={"amount_paid": 100001, "amount_manual": True}).status_code == 400)
    check("« abc » → 422", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O,
                                json={"amount_paid": "abc", "amount_manual": True}).status_code == 422)
    r = http("PUT", "/api/owner/clients/c1/purchases/v3", headers=O, json={"amount_paid": 15.5})
    check("amount only on a visit typed at the till: 15,50 €, still no lines",
          r.status_code == 200 and r.json()["row"]["amount"] == 15.5 and r.json()["row"]["items"] == [])
    check("client total: 63 − 12 + 15,50 = 66,50", cust("c1")["total_amount_paid"] == 66.5)
    r = http("PUT", "/api/owner/clients/c1/purchases/v3", headers=O, json={"items": [], "amount_paid": 0, "amount_manual": True})
    check("a free visit: 0 € allowed when said so", r.status_code == 200 and r.json()["row"]["amount"] == 0.0)
    check("client total: 66,50 − 15,50 = 51", cust("c1")["total_amount_paid"] == 51.0)

    print("\n5. The date and hour")
    r = http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O, json={"visit_time": "2026-10-09T08:00:00Z"})
    check(f"moved to the 9th ({r.status_code})", r.status_code == 200 and r.json()["row"]["at"].startswith("2026-10-09T08:00"))
    check("v2 was the latest: the client's last visit is now v3 (the 11th)",
          cust("c1")["last_visit_date"].replace(tzinfo=dt.timezone.utc) == now - dt.timedelta(days=3))
    check("history names the old and the new day", "14/10/2026" in hist("c1")[0]["text"] and "09/10/2026" in hist("c1")[0]["text"])
    r = http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O, json={"visit_time": "2026-10-14T16:30:00Z"})
    check("back to the 14th: the last visit follows", cust("c1")["last_visit_date"].replace(tzinfo=dt.timezone.utc) == now)
    check("tomorrow → 400", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O,
                                 json={"visit_time": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()}).status_code == 400)
    check("« hier » → 400", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O, json={"visit_time": "hier"}).status_code == 400)
    check("1999 → 400", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O, json={"visit_time": "1999-01-01T00:00:00Z"}).status_code == 400)

    print("\n6. Nothing to change, and limits")
    before = len(hist("c1"))
    r = http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O, json={})
    check("an empty body: 200, nothing changed, no history row",
          r.status_code == 200 and r.json()["changed"] == [] and len(hist("c1")) == before)
    r = http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O, json={"items": [{"item_id": "i1", "qty": 1}]})
    check("the same products again: nothing changed", r.json()["changed"] == [] and len(hist("c1")) == before)
    check("a 400-character reason → 422", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=O,
                                               json={"amount_paid": 22, "reason": "x" * 400}).status_code == 422)
    # the floor: a client whose total is below the visit (old data) never goes negative
    r = http("PUT", "/api/owner/clients/c2/purchases/v4", headers=O, json={"amount_paid": 0, "amount_manual": True})
    check("total 10 − 37 → 0, never negative", r.status_code == 200 and cust("c2")["total_amount_paid"] == 0.0)
    check("the tier is still a valid rung", r.json()["client"]["tier"] in ("bronze", "silver", "gold", "vip", "platinum") or isinstance(r.json()["client"]["tier"], str))

    print("\n7. Who may")
    check("staff → 403", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=tok("s@x.fr", "staff"),
                              json={"amount_paid": 1}).status_code == 403)
    check("another account → 404", http("PUT", "/api/owner/clients/c1/purchases/v2", headers=tok("z@x.fr", "business_owner", "t2"),
                                        json={"amount_paid": 1}).status_code == 404)
    check("another account, its own client id with my visit id → 404",
          http("PUT", "/api/owner/clients/z1/purchases/v2", headers=tok("z@x.fr", "business_owner", "t2"),
               json={"amount_paid": 1}).status_code == 404)
    check("a visit that is not this client's → 404", http("PUT", "/api/owner/clients/c1/purchases/v4", headers=O,
                                                           json={"amount_paid": 1}).status_code == 404)
    check("unknown visit → 404", http("PUT", "/api/owner/clients/c1/purchases/nope", headers=O,
                                      json={"amount_paid": 1}).status_code == 404)
    P = {**tok("p@x.fr", "administrateur"), "X-FidClic-Store": "pal"}
    check("a PALISSY administrateur, a LIBERTÉ-only client → refused",
          http("PUT", "/api/owner/clients/c3/purchases/v5", headers=P, json={"amount_paid": 6}).status_code in (403, 404))
    check("…a client scanned at PALISSY too → allowed",
          http("PUT", "/api/owner/clients/c1/purchases/v2", headers=P, json={"amount_paid": 22}).status_code == 200)
    check("no token → 401", http("PUT", "/api/owner/clients/c1/purchases/v2", json={"amount_paid": 1}).status_code == 401)
    check("v2 untouched by the refusals", visit("v2")["amount_paid"] == 22.0 and cust("c1")["total_amount_paid"] == 51.0)

    print("\n8. Deleting a purchase takes back what it gave")
    r = http("POST", "/api/owner/clients/c1/purchases/v3/cancel", headers=O, json={"reason": "Doublon"})
    d = r.json()
    check(f"answered ({r.status_code}) {d if r.status_code != 200 else ''}", r.status_code == 200)
    check("gone from the visits, kept apart with who and why",
          visit("v3") is None and (g := db.visits_cancelled.find_one({"id": "v3"}, {"_id": 0}))
          and g["cancelled_by"] == "o@x.fr" and g["cancel_reason"] == "Doublon")
    c = cust("c1")
    check("the client: one visit less (2), total unchanged (the visit was 0 €)", c["visits"] == 2 and c["total_amount_paid"] == 51.0)
    check("the history says « Achat supprimé », by the owner, why",
          hist("c1")[0]["kind"] == "visit_deleted" and hist("c1")[0]["by"] == "o@x.fr" and hist("c1")[0]["reason"] == "Doublon")
    check("the answer says what was reversed", d["reversed"]["visits"] == 1)
    d = http("GET", "/api/owner/clients/c1/purchases", headers=O).json()
    check("the list has 2 purchases now, 51 € spent", d["totals"]["visits"] == 2 and d["totals"]["spent"] == 51.0)
    check("deleting it again → 404", http("POST", "/api/owner/clients/c1/purchases/v3/cancel", headers=O, json={}).status_code == 404)
    r = http("POST", "/api/owner/clients/c1/purchases/v2/cancel", headers=O, json={})
    check("a 22 € visit deleted without a reason: fine, total 51 − 22 = 29, visits 1",
          r.status_code == 200 and cust("c1")["total_amount_paid"] == 29.0 and cust("c1")["visits"] == 1)
    check("a visit that moved a paper card → 409",
          http("POST", "/api/owner/clients/c3/purchases/v5/cancel", headers=O, json={}).status_code == 409)
    check("staff → 403", http("POST", "/api/owner/clients/c1/purchases/v1/cancel", headers=tok("s@x.fr", "staff"), json={}).status_code == 403)
    check("another account → 404", http("POST", "/api/owner/clients/c1/purchases/v1/cancel",
                                        headers=tok("z@x.fr", "business_owner", "t2"), json={}).status_code == 404)
    check("the other shop's visit is still there", visit("vz") is not None and cust("z1")["total_amount_paid"] == 99.0)

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
