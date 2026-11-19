"""
Avis Google on a shop whose first établissement is its « main » store
(user, 2026-11-19: « teen baar bbc k liye link daala, bbx k liye bhi… fir
bhi google review ka automation on nhi ho rha »).

BBC has two établissements: BBC (the account's own store, id « main ») and
BBX. The editor sends {"main": …, "<bbx id>": …}; « main » was read as the
one-shop key, so BBC's link went to the shop and never to the BBC
établissement — and every switch-on then said « Ajoutez le lien Google de
« BBC » ». The link typed for BBC must be BBC's, the switch must turn on, a
client who came to BBC must be sent to BBC's page, and the Insights link
(the shop's own) counts for the main store.

    cd api && python3 tests/test_google_review_main_store.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-gr-main")
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
    from features import automations as AU

    db = server.db
    BBC = "https://g.page/r/bbc/review"
    BBX = "https://g.page/r/bbx/review"
    SHOP = "https://search.google.com/local/writereview?placeid=ChIJshop"
    for tid, slug in (("t", "bbc"), ("u", "solo"), ("v", "ins")):
        db.tenants.insert_one({"id": tid, "slug": slug, "name": slug.upper(), "plan": "vip",
                               "subscription_status": "active", "is_active": True,
                               **({"branches": [{"id": "main", "name": "BBC"}, {"id": "x1", "name": "BBX"}]}
                                  if tid in ("t", "v") else {})})
        db.users.insert_one({"email": f"o@{tid}.fr", "role": "business_owner", "tenant_id": tid})
    tok = lambda t: {"Authorization": "Bearer " + auth.create_access_token(  # noqa: E731
        {"sub": f"o@{t}.fr", "role": "business_owner", "tenant_id": t})}

    def http(method, url, t="t", store=None, **kw):
        h = {**tok(t), **({"X-FidClic-Store": store} if store else {})}
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=h, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def avis_row(t, store=None):
        return next(r for r in http("GET", "/api/owner/automations", t=t, store=store).json()["rows"]
                    if r["scenario"] == "google_review")

    def save(t, row, links, status="paused", store=None, on=None):
        body = {k: row[k] for k in ("scenario", "name", "trigger", "message", "targeting", "schedule")}
        return http("PUT", f"/api/owner/automations/{row['id']}", t=t, store=store,
                    json={**body, "status": status, "google_links": links, **({"google_on": on} if on is not None else {})})

    def switch_on(t, row, store=None):
        return http("POST", f"/api/owner/automations/{row['id']}/status", t=t, store=store, json={"status": "active"})

    def status_of(t, store):
        return avis_row(t, store)["status"]

    print("\nBBC (« main ») + BBX: the links typed in the editor")
    page = http("GET", "/api/owner/automations").json()
    check("the editor asks one link per établissement, BBC first",
          [s["name"] for s in page["google"]["stores"]] == ["BBC", "BBX"])
    row = avis_row("t")
    r = save("t", row, {"main": BBC, "x1": BBX})
    check("saved", r.status_code == 200)
    br = {b["id"]: b.get("google_review_url") for b in db.tenants.find_one({"id": "t"})["branches"]}
    check("BBC's link is BBC's", br.get("main") == BBC)
    check("BBX's link is BBX's", br.get("x1") == BBX)
    page = http("GET", "/api/owner/automations").json()
    check("the editor shows both back", page["google"]["links"] == {"main": BBC, "x1": BBX})

    print("\nThe switch turns on")
    r = switch_on("t", row)
    check(f"switched on ({r.json().get('detail') or r.json().get('status')})",
          r.status_code == 200 and r.json().get("status") == "active")
    check("a client who came to BBC is sent to BBC's page", AU.review_link("t", "main") == BBC)
    check("one who came to BBX to BBX's", AU.review_link("t", "x1") == BBX)

    print("\nThe Insights link is the main store's")
    r = http("PUT", "/api/owner/insights/google-review", t="v", json={"url": SHOP, "enabled": True})
    check("(Insights saved)", r.status_code == 200)
    row_v = avis_row("v")
    page = http("GET", "/api/owner/automations", t="v").json()
    check("the editor shows the Insights link under BBC", page["google"]["links"].get("main") == SHOP)
    r = switch_on("v", row_v)
    check("BBC switches on with it — BBX's link is not needed for BBC",
          r.status_code == 200 and r.json().get("status") == "active")
    check("BBC's clients go to the Insights page", AU.review_link("v", "main") == SHOP)
    check("BBX's clients get nothing until BBX has its link", AU.review_link("v", "x1") is None)

    print("\nOnly the établissement open in the menu needs its link (user, 2026-11-19)")
    db.tenants.update_one({"id": "w"}, {"$set": {}}, upsert=False)
    db.tenants.insert_one({"id": "w", "slug": "trio", "name": "TRIO", "plan": "vip", "subscription_status": "active",
                           "is_active": True, "branches": [{"id": "main", "name": "BBC"}, {"id": "x1", "name": "BBX"},
                                                           {"id": "x2", "name": "BBZ"}]})
    db.users.insert_one({"email": "o@w.fr", "role": "business_owner", "tenant_id": "w"})
    page = http("GET", "/api/owner/automations", t="w", store="x1").json()
    check("the page says which établissement is open", page["google"]["open"] == "x1")
    check("and whether each one's Avis Google is on (all off)", page["google"]["on"] == {"main": False, "x1": False, "x2": False})
    rx = avis_row("w", "x1")
    check("(BBX's own row)", rx["store_ids"] == ["x1"])
    r = save("w", rx, {"x1": BBX}, status="active", store="x1")
    check("BBX open: BBX's link alone is enough, it turns on", r.status_code == 200 and r.json()["status"] == "active")
    check("…BBC and BBZ stay off", status_of("w", "main") == "paused" and status_of("w", "x2") == "paused")
    r = save("w", rx, {"x1": "", "main": BBC}, status="active", store="x1")
    check("BBX open without BBX's link: refused, named", r.status_code == 400 and "BBX" in r.json().get("detail", ""))
    r = save("w", rx, {"x1": BBX, "main": BBC}, status="active", store="x1", on={"main": False})
    check("BBC's link added but not switched on: saved", r.status_code == 200)
    tw = db.tenants.find_one({"id": "w"})
    check("…BBC has its link", AU.review_link("w", "main") == BBC)
    check("…BBC stays off: only the link waits there", status_of("w", "main") == "paused")
    page = http("GET", "/api/owner/automations", t="w", store="main").json()
    check("switching to BBC: its link is shown, ready", page["google"]["links"]["main"] == BBC and page["google"]["open"] == "main")
    r = switch_on("w", avis_row("w", "main"), store="main")
    check("…and its switch turns on without asking again", r.status_code == 200 and r.json()["status"] == "active")
    r = save("w", rx, {"x1": BBX, "x2": "https://g.page/r/bbz/review"}, status="active", store="x1", on={"x2": True})
    check("BBZ's link + « Activer » from BBX: saved", r.status_code == 200)
    check("…switching to BBZ: on", status_of("w", "x2") == "active")
    check("…BBZ's clients go to BBZ's page", AU.review_link("w", "x2") == "https://g.page/r/bbz/review")
    page = http("GET", "/api/owner/automations", t="w", store="x1").json()
    check("the page reads all three on", page["google"]["on"] == {"main": True, "x1": True, "x2": True})
    r = save("w", rx, {"x1": BBX}, status="active", store="x1", on={"x2": False})
    check("BBZ's « Activer » unticked: BBZ off, its link kept",
          r.status_code == 200 and status_of("w", "x2") == "paused" and AU.review_link("w", "x2"))
    r = save("w", rx, {"x1": BBX, "x2": ""}, status="active", store="x1", on={"x2": True})
    check("« Activer » BBZ without its link: refused, named", r.status_code == 400 and "BBZ" in r.json().get("detail", ""))
    r = save("w", rx, {"x1": BBX, "main": ""}, status="active", store="x1")
    check("emptying BBC's link while BBC's Avis Google is on: refused, named",
          r.status_code == 400 and "BBC" in r.json().get("detail", ""))
    check("…nothing changed", AU.review_link("w", "main") == BBC)
    r = save("w", rx, {"x1": BBX, "x2": "pas un lien"}, status="active", store="x1")
    check("an optional link that is not one: refused", r.status_code == 400 and "BBZ" in r.json().get("detail", ""))

    print("\nInsights › Avis Google speaks for the open établissement")
    r = http("PUT", "/api/owner/insights/google-review", t="w", store="x2",
             json={"url": "https://g.page/r/bbz2/review", "enabled": True})
    check("saved from BBZ", r.status_code == 200)
    check("…it is BBZ's link", AU.review_link("w", "x2") == "https://g.page/r/bbz2/review")
    check("…BBC's untouched", AU.review_link("w", "main") == BBC)
    ins = http("GET", "/api/owner/insights/page", t="w", store="x2").json()
    check("Insights in BBZ shows BBZ's link", (ins.get("google_review") or {}).get("url") == "https://g.page/r/bbz2/review")

    print("\nA happy rating on the card: the link of the client's own établissement")
    from features import insights_page as I
    db.customers.insert_one({"id": "c9", "tenant_id": "w", "barcode_id": "FT-C9", "name": "Zoé", "branch_id": "x1"})
    check("a BBX client is invited to BBX's page", I.google_invite_for("w", 9, "c9") == BBX)
    check("an unhappy one to none", I.google_invite_for("w", 5, "c9") is None)

    print("\nUnchanged: one shop, no établissements")
    row_u = avis_row("u")
    r = save("u", row_u, {"main": BBC}, status="active")
    check("its one link is the shop's, and it turns on", r.status_code == 200 and r.json().get("status") == "active"
          and db.tenants.find_one({"id": "u"})["google_review_url"] == BBC)
    check("its clients go there", AU.review_link("u") == BBC)

    print("\nRefusals unchanged")
    r = save("t", row, {"main": "", "x1": BBX}, status="active")
    check("BBC open, BBC's link emptied: refused, named", r.status_code == 400 and "BBC" in r.json().get("detail", ""))
    r = save("t", row, {"main": BBC, "x1": ""}, status="active")
    check("BBX's link emptied while BBX is off: fine, it waits for one", r.status_code == 200
          and AU.review_link("t", "x1") is None and AU.review_link("t", "main") == BBC)
    r = save("t", row, {"main": "pas un lien", "x1": BBX}, status="active")
    check("BBC's link not a link: refused", r.status_code == 400 and "BBC" in r.json().get("detail", ""))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


main()
