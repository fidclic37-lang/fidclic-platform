"""
The bell (user, 2026-10-03) — its clients' alerts, and where they lead.

    « N habitués décrochent »    regulars silent for over twice their rhythm
    « Votre meilleur client… »   the biggest spender, silent 30 days or more
    « N nouveaux clients… »      joined these 30 days, one visit (from 3)
    each in French, with « Voir les clients » = exactly the clients counted,
    and « Envoyer … » = the composer written for exactly them
    an alert about one establishment keeps it in both links (?store=)
    the old ones (VIP spend, repeat rate, « reactivated », birthdays) are gone
    what waits for the owner's OK keeps its own link

Run: cd api && /usr/local/bin/python3 tests/test_bell_alerts.py
"""
import asyncio
import datetime as dt
import os
import sys
from urllib.parse import urlparse, parse_qs

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    import auth
    import httpx

    db = server.db
    passed = failed = 0

    def check(label, cond, extra=""):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra and not cond else ""))

    def http(method, url, bearer, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers={"Authorization": "Bearer " + bearer, **(headers or {})}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(dt.timezone.utc)
    ago = lambda d: now - dt.timedelta(days=d)

    db.tenants.insert_one({"id": "t1", "name": "Café Lumière", "sector": "cafe", "plan": "gold",
                           "subscription_status": "active", "created_at": ago(400),
                           "branches": [{"id": "b1", "name": "Centre"}, {"id": "b2", "name": "Plumereau"}]})
    db.users.insert_one({"email": "o@c.fr", "role": "business_owner", "tenant_id": "t1"})
    OWN = auth.create_access_token({"sub": "o@c.fr", "role": "business_owner", "tenant_id": "t1"})

    def cust(cid, branch, visits, created, last, spent):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": cid.title(), "barcode_id": f"FT-{cid}",
                                 "visits": visits, "created_at": ago(created),
                                 "last_visit_date": ago(last) if last is not None else None,
                                 "total_amount_paid": spent, "branch_id": branch})
        if last is not None:
            db.visits.insert_one({"tenant_id": "t1", "customer_id": cid, "branch_id": branch,
                                  "amount_paid": 10.0, "visit_time": ago(last)})

    # Centre: two regulars slipping (10 visits in 50 days, silent 50 days),
    # one regular who is just on a monthly rhythm (not slipping), the best
    # client silent 40 days, three one-timers, a fresh regular.
    cust("alice", "b1", 10, 100, 50, 120.0)
    cust("bruno", "b1", 10, 110, 55, 90.0)
    cust("mensuel", "b1", 6, 400, 60, 80.0)      # gap 68 days: 60 silent is his rhythm
    cust("top", "b1", 30, 300, 40, 2400.0)
    cust("un1", "b1", 1, 5, 5, 8.0)
    cust("un2", "b1", 1, 12, 12, 8.0)
    cust("un3", "b1", 1, 20, 20, 8.0)
    cust("vieux1", "b1", 1, 200, 200, 8.0)        # one visit, long ago: not a « new » one-timer
    cust("regulier", "b1", 12, 90, 2, 300.0)
    # Plumereau: one slipping regular only.
    cust("zoe", "b2", 8, 90, 50, 70.0)

    print("\nThe alerts of each establishment")
    r = http("GET", "/api/owner/insights/alerts/multi-store", OWN)
    al = r.json()["alerts"]
    by = {(a["branch_id"], a["id"].split("__", 1)[1]): a for a in al if a.get("branch_id")}
    risk = by.get(("b1", "at_risk"))
    check("Centre: « 2 habitués décrochent » (the monthly regular is not one)",
          risk and risk["title"] == "2 habitués décrochent", risk and risk["title"])
    check("… said in French, with its rule", risk and "45 jours" in risk["body"] and "rythme habituel" in risk["body"])
    top = by.get(("b1", "top_silent:top"))
    check("Centre: the best client, silent 40 days", top and top["title"] == "Votre meilleur client n'est pas venu depuis 40 jours", top and top["title"])
    check("… with what they spent", top and "Top a dépensé 2" in top["body"] and "400 €" in top["body"], top and top["body"])
    once = by.get(("b1", "one_timers"))
    check("Centre: « 3 nouveaux clients ne sont venus qu'une fois » (not the old one)",
          once and once["title"] == "3 nouveaux clients ne sont venus qu'une fois", once and once["title"])
    check("Plumereau: « 1 habitué décroche », and nothing about Centre's clients",
          by.get(("b2", "at_risk"), {}).get("title") == "1 habitué décroche"
          and ("b2", "one_timers") not in by)
    gone = [a["id"] for a in al if any(k in a["id"] for k in ("vip_spend", "reactivations", "birthdays", "repeat_", "about_to_lose", "one_and_done"))]
    check("the old alerts are gone", not gone, gone)
    check("no English left", not any(w in (a["title"] + a.get("body", "")) for a in al
                                     for w in ("customers", "slipping", "spend", "birthdays")))

    print("\nWhere « Voir les clients » leads: exactly the clients counted")
    def link(a, kind):
        return next(x["href"] for x in a["actions"] if x["kind"] == kind)

    def q(href):
        u = urlparse(href)
        return u.path, {k: v[0] for k, v in parse_qs(u.query).items()}

    path, p = q(link(risk, "customers"))
    check("to the Clients page, on its segment and its establishment",
          path == "/dashboard/customers" and p == {"segment": "at_risk", "store": "b1"}, p)
    lst = http("GET", "/api/owner/clients/list", OWN, params={"segment": p["segment"], "store": p["store"]}).json()
    check("the list shows those 2, and only them", sorted(x["id"] for x in lst["rows"]) == ["alice", "bruno"], lst["total"])
    check("clicking the alert itself opens the same list", risk["href"] == link(risk, "customers"))
    path, p = q(link(once, "customers"))
    ids = http("GET", "/api/owner/clients/ids", OWN, params=p).json()["ids"]
    check("« 1 seule visite »: the 3 new one-timers", sorted(ids) == ["un1", "un2", "un3"], ids)
    path, p = q(link(top, "customers"))
    one = http("GET", "/api/owner/clients/list", OWN, params=p).json()
    check("« Voir le client »: that client alone", [x["id"] for x in one["rows"]] == ["top"], one["total"])
    path, p = q(link(by[("b2", "at_risk")], "customers"))
    check("Plumereau's list: Zoé only",
          http("GET", "/api/owner/clients/ids", OWN, params=p).json()["ids"] == ["zoe"])
    check("an explicit ?store wins over the menu's header",
          http("GET", "/api/owner/clients/ids", OWN, params=p,
               headers={"X-FidClic-Store": "all"}).json()["ids"] == ["zoe"])

    print("\nWhere « Envoyer … » leads: the composer, written for exactly them")
    path, p = q(link(risk, "campaign"))
    check("to Campagnes with its message, its establishment, « depuis une alerte »",
          path == "/dashboard/campaigns" and p == {"template": "a_risque", "store": "b1", "from": "alerte"}, p)
    t = http("GET", f"/api/owner/insights/templates/{p['template']}", OWN, params={"store": p["store"]}).json()
    check("the message is ready", t["title"] and "Cela fait un moment" in t["message"])
    check("its recipients are the same 2", sorted(t["audience"]["ids"]) == ["alice", "bruno"], t.get("audience"))
    path, p = q(link(once, "campaign"))
    t = http("GET", f"/api/owner/insights/templates/{p['template']}", OWN, params={"store": p["store"]}).json()
    check("« Envoyer l'offre 2e visite »: the 3 one-timers", p["template"] == "seconde_visite"
          and sorted(t["audience"]["ids"]) == ["un1", "un2", "un3"])
    path, p = q(link(top, "campaign"))
    t = http("GET", f"/api/owner/insights/templates/{p['template']}", OWN, params={"store": p["store"]}).json()
    check("« Lui écrire »: to that client alone", t["audience"]["ids"] == ["top"] and t["audience"]["label"] == "Top")
    check("a client of another establishment is refused",
          http("GET", "/api/owner/insights/templates/client:zoe", OWN, params={"store": "b1"}).status_code == 404)

    print("\nThe same definition everywhere")
    from features import insights_page as IP
    shop = IP.Shop("t1", now)
    check("Insights' « Clients à risque » = the bell's", sorted(c["id"] for c in IP._at_risk(shop)) == ["alice", "bruno", "zoe"])
    check("Insights' one-timers = the bell's", sorted(c["id"] for c in IP._one_timers(shop)) == ["un1", "un2", "un3"])

    print("\nWhat waits for the owner's OK keeps its own link")
    check("a bare path gets its label", server._alert_actions("/dashboard/automations?tab=pending")
          == [{"kind": "open", "label": "Valider les envois", "href": "/dashboard/automations?tab=pending"}])
    check("a {href, label} is kept", server._alert_actions({"href": "/x", "label": "Voir le rapport"})[0]["label"] == "Voir le rapport")
    db.push_wallet_pending.insert_one({"id": "lot1", "tenant_id": "t1", "status": "pending", "scenario_id": "s",
                                       "count": 4, "prepared_at": now, "store_id": None})
    al = http("GET", "/api/owner/insights/alerts/multi-store", OWN).json()["alerts"]
    pw = next((a for a in al if a["id"].startswith("pushwallet:")), None)
    # Automatisations send by themselves since the redesign (2026-10-11): an
    # old batch left in the database never raises « à valider » any more
    check("no « envois à valider » alert any more", pw is None, pw)

    print("\nEach shop its own — never mixed")
    db.push_wallet_pending.insert_one({"id": "lot2", "tenant_id": "t1", "status": "pending", "scenario_id": "s",
                                       "count": 7, "prepared_at": now, "store_id": "b2", "store_name": "Plumereau"})
    al = http("GET", "/api/owner/insights/alerts/multi-store", OWN).json()["alerts"]
    pws = [a for a in al if a["id"].startswith("pushwallet:")]
    b2 = [a for a in pws if a.get("branch_id") == "b2"]
    whole = [a for a in pws if not a.get("branch_id")]
    check("… for no establishment either", not b2 and not whole, pws)
    check("… Centre has no Plumereau alert", not any(a.get("branch_id") == "b1" and "lot2" in a["id"] for a in al))
    ids = [a["id"] for a in al if a.get("branch_id")]
    check("every shop alert has its own id (read / hidden apart)", len(ids) == len(set(ids)))
    check("… and every link of a shop alert stays in that shop",
          all(("store=" + a["branch_id"]) in x["href"] for a in al if a.get("branch_id") and not a["id"].startswith("pushwallet:")
              for x in a.get("actions") or []))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
