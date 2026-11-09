"""
Super admin › Dashboard — « 3 Commerces » next to a « 10 commerces » donut
(user, 2026-11-09: « dashboard pr 3 shops and analyse mein 10 dikha rha h,
aisa mismatch kyun h »). Both were right — the tile counts the businesses in
trial or paying, the donut every registered business — but the screen did not
say so, and the donut said « Essai gratuit 100 % » for shops whose trial was
long over. The user chose 1 + 3:

  1. the tile says « N actifs sur M inscrits » (M opens all of them);
  3. the donut shows where each business stands — Essai en cours, Abonné,
     Impayé, Non converti, Résilié — summing to the same M, each slice opening
     its businesses.

Run: cd api && python3 tests/test_admin_dashboard_status.py
"""
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    from models import TokenData
    from features import admin_commerces as A
    from features import admin_dashboard as D

    db = server.db
    A.init(db)
    D.init(db)
    passed = failed = 0

    def check(label, cond, detail=None):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {detail}"))

    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    now = dt.datetime.now(dt.timezone.utc)
    old = now - dt.timedelta(days=200)

    def shop(i, **kw):
        return {"id": i, "name": f"Shop {i}", "sector": "cafe", "city": "Tours", "plan": "essai", "created_at": old, **kw}

    # Two in trial, one paying, one unpaid, three trials over, one résilié,
    # and one switched off (is_active False) that no figure may count.
    db.tenants.insert_many([
        shop("e1", subscription_status="trialing", trial_ends_at=now + dt.timedelta(days=10)),
        shop("e2", subscription_status="trialing", trial_ends_at=now + dt.timedelta(days=1)),
        shop("ab", plan="gold", subscription_status="active"),
        shop("im", plan="gold", subscription_status="active", suspended_at=now - dt.timedelta(days=3)),
        shop("n1", subscription_status="trialing", trial_ends_at=now - dt.timedelta(days=10)),   # inside the 30-day default period
        shop("n2", subscription_status="trialing", trial_ends_at=now - dt.timedelta(days=400)),   # before any period
        shop("n3", subscription_status="canceled"),                                                # never paid
        shop("re", plan="silver", resiliated_at=now - dt.timedelta(days=500)),                       # before any period
        shop("off", subscription_status="active", is_active=False),
    ])

    d = D.dashboard(date_from=None, date_to=None, token_data=ADMIN)
    K = {k["key"]: k for k in d["kpis"]}

    print("\n1. The tile: « N actifs sur M inscrits »")
    c = K["commerces"]
    check("the tile still counts trial + paying (3)", c["value"] == 3, c["value"])
    check("…and says out of how many registered (8, not the switched-off one)", c.get("registered") == 8, c.get("registered"))
    check("registered is the donut's total", c.get("registered") == d["total"], (c.get("registered"), d["total"]))

    print("\n2. The donut: where each business stands")
    rows = d.get("statuses") or []
    by = {r["key"]: r for r in rows}
    check("one slice per standing, in the order of the business's life",
          [r["key"] for r in rows] == ["essai", "abonne", "impaye", "non_converti", "resilie"], [r["key"] for r in rows])
    check("Essai en cours 2", by.get("essai", {}).get("count") == 2, by.get("essai"))
    check("Abonné 1", by.get("abonne", {}).get("count") == 1)
    check("Impayé 1 (suspended)", by.get("impaye", {}).get("count") == 1)
    check("Non converti 3 — however long ago the trial ended", by.get("non_converti", {}).get("count") == 3, by.get("non_converti"))
    check("Résilié 1 — however long ago", by.get("resilie", {}).get("count") == 1)
    check("the slices sum to the total", sum(r["count"] for r in rows) == d["total"] == 8, (sum(r["count"] for r in rows), d["total"]))
    check("percentages of the total", by["essai"]["pct"] == 25 and by["non_converti"]["pct"] == 38, by)
    check("French labels", by["essai"]["label"] == "Essai en cours" and by["non_converti"]["label"] == "Non converti"
          and by["abonne"]["label"] == "Abonné" and by["impaye"]["label"] == "Impayé" and by["resilie"]["label"] == "Résilié")
    check("the tile's 3 is the donut's Essai en cours + Abonné",
          c["value"] == by["essai"]["count"] + by["abonne"]["count"])
    check("each slice says which list it opens", all(r.get("list") for r in rows), rows)

    print("\n3. An empty standing has no slice")
    db.tenants.delete_one({"id": "re"})
    D.invalidate()
    d2 = D.dashboard(date_from=None, date_to=None, token_data=ADMIN)
    check("no Résilié slice when there is none", "resilie" not in {r["key"] for r in d2["statuses"]}, d2["statuses"])
    check("total 7 = registered 7", d2["total"] == 7 and {k["key"]: k for k in d2["kpis"]}["commerces"]["registered"] == 7)
    db.tenants.insert_one(shop("re", plan="silver", resiliated_at=now - dt.timedelta(days=500)))
    D.invalidate()

    print("\n4. Every figure opens the businesses behind it")

    def listed(key):
        r = D.dashboard_list(key, date_from=None, date_to=None, token_data=ADMIN)
        return sorted(x["id"] for x in r["rows"]), r

    ids, r = listed("inscrits")
    check("« sur 8 inscrits » opens the 8", ids == ["ab", "e1", "e2", "im", "n1", "n2", "n3", "re"], ids)
    check("…with a title", r.get("title") == "Tous les commerces inscrits", r.get("title"))
    want = {"essai": ["e1", "e2"], "abonne": ["ab"], "impaye": ["im"], "non_converti": ["n1", "n2", "n3"], "resilie": ["re"]}
    for row in D.dashboard(date_from=None, date_to=None, token_data=ADMIN)["statuses"]:
        got, _ = listed(row["list"])
        check(f"slice « {row['label']} » opens exactly its {row['count']}", got == want[row["key"]] and len(got) == row["count"], got)
    got, _ = listed("non_converti")
    check("the status card's « non converti » list keeps its period (trials ended in it)", got == ["n1"], got)

    print("\n5. Through the real endpoints — only the platform team sees it")
    import asyncio
    import auth
    import httpx

    def http(url, role, email, tenant_id=None):
        tok = auth.create_access_token({"sub": email, "role": role, "tenant_id": tenant_id})

        async def go():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.get(url, headers={"Authorization": f"Bearer {tok}"})
        return asyncio.run(go())

    db.users.insert_one({"email": "boss@fidclic.com", "role": "super_admin", "tenant_id": None})
    r = http("/api/admin/dashboard", "super_admin", "boss@fidclic.com")
    check("super admin: the dashboard carries the statuses", r.status_code == 200 and r.json().get("statuses"), r.status_code)
    r = http("/api/admin/dashboard/list/inscrits", "super_admin", "boss@fidclic.com")
    check("super admin: « inscrits » lists 8", r.status_code == 200 and len(r.json()["rows"]) == 8, r.status_code)
    for role in ("business_owner", "manager", "staff"):
        db.users.insert_one({"email": f"{role}@ab.fr", "role": role, "tenant_id": "ab"})
        for url in ("/api/admin/dashboard", "/api/admin/dashboard/list/inscrits", "/api/admin/dashboard/list/tous_non_converti"):
            r = http(url, role, f"{role}@ab.fr", "ab")
            check(f"{role} refused on {url} ({r.status_code})", r.status_code in (401, 403), r.text[:120])
    r = http("/api/admin/dashboard/list/%3Cscript%3E", "super_admin", "boss@fidclic.com")
    check("an unknown list key is a 404, not echoed", r.status_code == 404 and "<script>" not in r.text, r.text[:120])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
