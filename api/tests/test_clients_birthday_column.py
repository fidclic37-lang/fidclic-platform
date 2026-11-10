"""
Clients › « Anniversaires du mois »: the table says WHEN (user, 2026-11-09).

The date the owner saw beside each client was « Dernière visite », read as a
birthday — so a 31 October visit looked like a wrong client in November's
birthdays. With the chip on, a column « Anniversaire » shows the day and the
list runs in birthday order (1 → 31).

    cd api && python3 tests/test_clients_birthday_column.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from features import clients_page as CP

    db = server.db
    CP.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    now = dt.datetime.now(dt.timezone.utc)
    m = now.astimezone(ZoneInfo("Europe/Paris")).month
    prev = 12 if m == 1 else m - 1
    db.tenants.insert_one({"id": "t1", "name": "Le Petit Café", "plan": "gold"})
    db.tenants.insert_one({"id": "t2", "name": "Rival", "plan": "gold"})

    def client(cid, name, joined_days, tid="t1", **extra):
        db.customers.insert_one({"id": cid, "tenant_id": tid, "name": name, "visits": 1,
                                 "total_amount_paid": 10.0, "tier": "bronze",
                                 "created_at": now - dt.timedelta(days=joined_days),
                                 "last_visit_date": now - dt.timedelta(days=joined_days), **extra})

    # joined order (newest first) is deliberately NOT birthday order
    client("c28", "Zoé Vingt-Huit", 1, birthday=f"{m:02d}-28")
    client("c15", "Bob Quinze", 2, birthday=f"{m:02d}-15")
    client("c03", "Ali Trois", 3, birth_date=f"1990-{m:02d}-03")            # full date only
    client("c07", "Eva Sept", 4, birthday=f"07/{m:02d}")                    # an old DD/MM form
    client("cprev", "Paul Dernier", 5, birthday=f"{prev:02d}-30")           # last month
    client("cnone", "Nina Sans", 6)                                          # no birthday
    client("cbad", "Max Faux", 7, birthday="pas une date")                   # unreadable
    client("xr", "Rival Client", 0, tid="t2", birthday=f"{m:02d}-01")

    print("\nThe row says the birthday")
    rows = {r["id"]: r for r in CP.list_page(per_page=50, token_data=TD())["rows"]}
    check("a MM-DD birthday is kept as MM-DD", rows["c28"]["birthday"] == f"{m:02d}-28")
    check("a client with the full date only gets its day and month", rows["c03"]["birthday"] == f"{m:02d}-03")
    check("an old DD/MM birthday is read the same way", rows["c07"]["birthday"] == f"{m:02d}-07")
    check("no birthday → None", rows["cnone"]["birthday"] is None)
    check("an unreadable birthday → None, the page does not break", rows["cbad"]["birthday"] is None)

    print("\n« Anniversaires du mois » in birthday order")
    got = CP.list_page(segment="birthday", sort="birthday", per_page=50, token_data=TD())
    check("this month only, 1 → 31", [r["id"] for r in got["rows"]] == ["c03", "c07", "c15", "c28"])
    check("last month's birthday is not in the list", "cprev" not in {r["id"] for r in got["rows"]})
    check("another shop's client never appears", "xr" not in {r["id"] for r in got["rows"]})
    p2 = CP.list_page(segment="birthday", sort="birthday", per_page=3, page=2, token_data=TD())
    check("the order holds across pages", [r["id"] for r in p2["rows"]] == ["c28"])

    print("\nThe sort is a normal choice")
    allb = [r["id"] for r in CP.list_page(sort="birthday", per_page=50, token_data=TD())["rows"]]
    check("on every client: January → December, those without a birthday last",
          allb.index("cnone") > allb.index("c28") and allb.index("cbad") > allb.index("c28")
          and set(allb[-2:]) == {"cnone", "cbad"})
    check("the other sorts are unchanged",
          CP.list_page(segment="birthday", per_page=50, token_data=TD())["rows"][0]["id"] == "c28")
    labels = {s["key"]: s["label"] for s in CP.SORT_LABELS}
    # « 1er → 31 » is not every month (30 days, février 28/29): the menu says
    # what it is (user, 2026-11-10)
    check("the sort menu names it « Anniversaires du mois »", labels.get("birthday") == "Anniversaires du mois")
    check("… and never « 1er → 31 »", not any("31" in l for l in labels.values()))

    print("\nThe screen")
    src = open(os.path.join(os.path.dirname(__file__), "..", "..",
                            "src", "pages", "ClientsPage.jsx")).read()
    check("the column « Anniversaire » appears with the chip", "showBirthday ? ['Anniversaire']" in src)
    check("the chip turns the birthday order on", "setSort('birthday')" in src)
    check("the menu offers it only with the chip", "s.key !== 'birthday' || showBirthday" in src)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
