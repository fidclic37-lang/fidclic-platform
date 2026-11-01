"""
A filleul whose card belongs to one establishment but who visits another
(user, 2026-11-01 — Royal Trim PL-Monstre: Apia's card is PL-Monstre's, her
visit was scanned at Liberté, so PL-Monstre's Impact FidClic read 0 € with no
word why).

A visit counts where it is scanned (multi-store rule) — unchanged. What this
adds is the explanation:
  • Analyses › Impact FidClic of a store says how much ITS filleuls spent in
    the other establishments over the period, and that it is counted there;
  • Parrainage › Derniers parrainages names the filleul's card store and the
    other stores it visited.

Run: cd api && /usr/local/bin/python3 tests/test_referral_other_store.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-referral-other-store")
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
    from features import referral_stores as RS
    db = server.db
    now = dt.datetime.now(dt.timezone.utc)
    ago = lambda d: now - dt.timedelta(days=d)

    db.tenants.insert_one({"id": "t1", "slug": "t1", "name": "ROYAL", "plan": "vip", "subscription_status": "active",
                           "branches": [{"id": "main", "name": "LIBÉRTÉ", "is_main": True},
                                        {"id": "mon", "name": "PL-MONSTRE"},
                                        {"id": "pal", "name": "PALISSY"}]})
    db.tenants.insert_one({"id": "t2", "slug": "t2", "name": "SOLO", "plan": "vip", "subscription_status": "active"})
    for email, tid in (("o@x.fr", "t1"), ("s@x.fr", "t2")):
        db.users.insert_one({"email": email, "role": "business_owner", "tenant_id": tid})
    db.users.insert_one({"email": "m@x.fr", "role": "manager", "tenant_id": "t1", "branch_ids": ["mon"]})
    tok = lambda e, role, tid: "Bearer " + auth.create_access_token({"sub": e, "role": role, "tenant_id": tid})
    OWNER, SOLO, MGR = tok("o@x.fr", "business_owner", "t1"), tok("s@x.fr", "business_owner", "t2"), tok("m@x.fr", "manager", "t1")

    def cust(cid, home, tid="t1", name=None):
        db.customers.insert_one({"id": cid, "tenant_id": tid, "name": name or cid.capitalize(), "branch_id": home,
                                 "created_at": ago(20), "deleted_at": None})

    def visit(cid, store, amount, days, tid="t1"):
        db.visits.insert_one({"id": f"v-{cid}-{store}-{days}-{amount}", "tenant_id": tid, "customer_id": cid,
                              "branch_id": store, "amount_paid": amount, "visit_time": ago(days)})

    def referral(parrain, filleul, tid="t1", pending=False):
        db.referral_redemptions.insert_one({"tenant_id": tid, "referrer_customer_id": parrain,
                                            "referee_customer_id": filleul, "created_at": ago(19),
                                            "referrer_points": 0 if pending else 50,
                                            "referrer_pending": pending, "source": "qr_card"})

    cust("amjad", "mon", name="Amjad")                 # parrain, card PL-Monstre
    cust("apia", "mon", name="Apia Konan")             # filleul, card PL-Monstre…
    visit("apia", "main", 22, 5)                       # …visit at Liberté
    visit("apia", "main", 30, 60)                      # older visit at Liberté (out of 30 days)
    cust("nino", "mon", name="Nino Mundaca")           # filleul, card PL-Monstre, 0 € at Liberté
    visit("nino", "main", 0, 3)
    cust("cara", "mon", name="Cara Home")              # filleul who visits her own store
    visit("cara", "mon", 10, 4)
    cust("dan", "main", name="Dan Libre")              # filleul of Liberté who came to PL-Monstre
    visit("dan", "mon", 15, 2)
    cust("eve", "mon", name="Eve Pending")             # pending, never came
    cust("old", None, name="Old Visit")                # filleul with no store (= main), visit with no branch
    visit("old", None, 7, 6)
    cust("xavier", "mon", name="Xavier Seul")          # NOT a filleul: never in the explanation
    visit("xavier", "main", 50, 2)
    for f in ("apia", "nino", "cara", "dan", "old"):
        referral("amjad", f)
    referral("amjad", "eve", pending=True)
    # another shop, same ids pattern: never mixed in
    cust("apia2", "mon", tid="t2")
    visit("apia2", "main", 99, 2, tid="t2")
    referral("amjad", "apia2", tid="t2")

    def get(path, who=OWNER, store=None):
        h = {"Authorization": who, **({"X-FidClic-Store": store} if store else {})}

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.get(path, headers=h)
        r = asyncio.get_event_loop().run_until_complete(run())
        return r.status_code, r.json()

    print("\nUnit — visits_by_store")
    vb = RS.visits_by_store("t1", ["apia", "old", "ghost"])
    check("Apia: 2 visits, 52 € at Liberté (all time)", vb["apia"] == {"main": {"visits": 2, "revenue": 52.0}})
    check("a visit with no store counts at the main store", vb["old"] == {"main": {"visits": 1, "revenue": 7.0}})
    check("an unknown client is simply absent", "ghost" not in vb)
    vb = RS.visits_by_store("t1", ["apia"], ago(30), now)
    check("a period keeps only its visits (22 €)", vb["apia"] == {"main": {"visits": 1, "revenue": 22.0}})
    check("no ids → nothing, no query trouble", RS.visits_by_store("t1", []) == {})
    check("another shop's visits never read", RS.visits_by_store("t1", ["apia2"]) == {})

    print("\nAnalyses › Impact FidClic — PL-Monstre")
    code, a = get("/api/owner/analyses?tab=vue&days=30", store="mon")
    imp = a["data"]["impact"]
    el = imp.get("elsewhere")
    check("200", code == 200)
    check("parrainage here unchanged: Cara 10 € + Dan 15 € (scanned here)",
          next(s for s in imp["sources"] if s["key"] == "parrainage")["revenue"] == 25)
    check("explanation present", bool(el))
    check("its filleuls spent 22 € in 2 visits elsewhere (Apia + Nino)", el and el["revenue"] == 22 and el["visits"] == 2)
    check("2 filleuls", el and el["clients"] == 2)
    check("one line: Liberté, 22 €, 2 visits",
          el and el["stores"] == [{"id": "main", "name": "LIBÉRTÉ", "revenue": 22.0, "visits": 2}])
    check("a client who is not a filleul is not in it (Xavier's 50 €)", el and el["revenue"] < 50)
    check("the note names the store and says it is counted there",
          el and "LIBÉRTÉ" in el["note"] and "22" in el["note"] and "compt" in el["note"].lower())
    code, a = get("/api/owner/analyses?tab=vue&days=90", store="mon")
    el90 = a["data"]["impact"]["elsewhere"]
    check("90 days takes the older visit too (52 €, 3 visits)", el90["revenue"] == 52 and el90["visits"] == 3)

    print("\nAnalyses › Impact FidClic — Liberté (the other way round)")
    code, a = get("/api/owner/analyses?tab=vue&days=30", store="main")
    el = a["data"]["impact"]["elsewhere"]
    check("Dan (card Liberté) spent 15 € at PL-Monstre",
          el and el["stores"] == [{"id": "mon", "name": "PL-MONSTRE", "revenue": 15.0, "visits": 1}])
    check("Old (no store = Liberté, visit with no store) is not « elsewhere »", el and el["revenue"] == 15)

    print("\nNothing to explain")
    code, a = get("/api/owner/analyses?tab=vue&days=30", store="pal")
    check("Palissy: no filleul → no box", a["data"]["impact"].get("elsewhere") is None)
    code, a = get("/api/owner/analyses?tab=vue&days=30", store="all")
    check("all establishments: everything is already counted → no box", a["data"]["impact"].get("elsewhere") is None)
    code, a = get("/api/owner/analyses?tab=vue&days=30", who=SOLO)
    check("a single-store shop: no box", code == 200 and a["data"]["impact"].get("elsewhere") is None)
    code, a = get("/api/owner/analyses?tab=vue&days=30", who=MGR)
    check("a PL-Monstre manager sees PL-Monstre's explanation", code == 200 and a["data"]["impact"]["elsewhere"]["revenue"] == 22)
    code, a = get("/api/owner/analyses?tab=vue&days=30", who=MGR, store="main")
    check("…and cannot read Liberté's by asking for it (falls back to PL-Monstre)",
          a["data"]["impact"]["elsewhere"]["stores"][0]["name"] == "LIBÉRTÉ")

    print("\nParrainage › Derniers parrainages")
    code, l = get("/api/owner/referrals/list?per_page=100&from=2020-01-01", store="mon")
    rows = {r["filleul"]["name"]: r["filleul"] for r in l["rows"]}
    apia = rows.get("Apia K.") or {}
    check("Apia: card store PL-MONSTRE", apia.get("card_store") == "PL-MONSTRE")
    check("Apia: 2 visits, 52 € at LIBÉRTÉ", apia.get("elsewhere") == [{"store": "LIBÉRTÉ", "visits": 2, "revenue": 52.0}])
    check("Nino: 1 visit, 0 € at LIBÉRTÉ", (rows.get("Nino M.") or {}).get("elsewhere") == [{"store": "LIBÉRTÉ", "visits": 1, "revenue": 0.0}])
    check("Cara (visits her own store): nothing elsewhere", (rows.get("Cara H.") or {}).get("elsewhere") == [])
    check("Eve (never came): nothing elsewhere", (rows.get("Eve P.") or {}).get("elsewhere") == [])
    code, o = get("/api/owner/referrals/overview", store="mon")
    rec = {r["filleul"]["name"]: r["filleul"] for r in o["recent"]}
    check("the first rows (overview) say it too", (rec.get("Apia K.") or {}).get("card_store") == "PL-MONSTRE"
          and rec["Apia K."]["elsewhere"][0]["store"] == "LIBÉRTÉ")
    code, l = get("/api/owner/referrals/list?per_page=100&from=2020-01-01", who=SOLO)
    check("single-store shop: no card store, no elsewhere",
          l["rows"] and l["rows"][0]["filleul"].get("card_store") is None and l["rows"][0]["filleul"].get("elsewhere") == [])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
