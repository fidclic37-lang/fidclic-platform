"""
« Anniversaires du mois » (user, 2026-11-04): the same clients everywhere — the
Clients chip, its list and the Segmentation row — on the shop's calendar (Paris),
whatever form an older date of birth was stored in.

Run: cd api && python3 tests/test_birthday_segment.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-birthday-segment")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {str(detail)[:300]}"))


def main():
    import server
    import auth
    import httpx
    from services import customer_fields as CF
    from features import clients_page as CP
    from features import segmentation as SG

    db = server.db
    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC)
    paris_month = now.astimezone(CF.PARIS).month
    this = f"{paris_month:02d}"
    other = f"{paris_month % 12 + 1:02d}"

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=H if headers is None else headers, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    # ---- the rule itself ---------------------------------------------------------------------
    print("\nLe mois de naissance")
    month = CF.birth_month
    check("MM-DD", month({"birthday": "03-12"}) == 3)
    check("an older 1990-03-12", month({"birthday": "1990-03-12"}) == 3)
    check("an older 12/03/1990 is the 12th of March", month({"birthday": "12/03/1990"}) == 3)
    check("an older 12/03", month({"birthday": "12/03"}) == 3)
    check("single digits 3-2", month({"birthday": "3-2"}) == 3)
    check("spaces around", month({"birthday": " 03-12 "}) == 3)
    check("29 February", month({"birthday": "02-29"}) == 2)
    check("no birthday but a full date", month({"birthday": "", "birth_date": "1990-07-04"}) == 7)
    check("the birthday wins over the full date", month({"birthday": "03-12", "birth_date": "1990-07-04"}) == 3)
    check("empty", month({"birthday": ""}) is None)
    check("missing", month({}) is None)
    check("None", month({"birthday": None}) is None)
    check("month 13", month({"birthday": "13-01"}) is None)
    check("month 00", month({"birthday": "00-10"}) is None)
    check("31 February", month({"birthday": "02-31"}) is None)
    check("text", month({"birthday": "birthdays"}) is None)
    check("a number", month({"birthday": 12}) is None)
    check("bad birthday falls back on the full date", month({"birthday": "x", "birth_date": "2001-11-30"}) == 11)

    print("\nLe mois du commerce : Paris, pas UTC")
    in_month = CF.is_birth_month
    late_oct = dt.datetime(2026, 10, 31, 23, 30, tzinfo=UTC)         # already 1 Nov 00:30 in Paris
    check("31 Oct 23:30 UTC is November in Paris", in_month({"birthday": "11-02"}, late_oct))
    check("… so October's clients are out", not in_month({"birthday": "10-02"}, late_oct))
    dst = dt.datetime(2026, 3, 31, 22, 30, tzinfo=UTC)               # summer time: 1 April 00:30
    check("after the clock change: 31 Mar 22:30 UTC is April", in_month({"birthday": "04-20"}, dst))
    before = dt.datetime(2026, 3, 31, 21, 30, tzinfo=UTC)            # 23:30 in Paris
    check("one hour before it is still March", in_month({"birthday": "03-20"}, before))
    winter = dt.datetime(2026, 12, 31, 23, 30, tzinfo=UTC)           # the year turns
    check("31 Dec 23:30 UTC is January", in_month({"birthday": "01-01"}, winter))
    check("a naive date is read as UTC", in_month({"birthday": "11-02"}, dt.datetime(2026, 10, 31, 23, 30)))
    check("no birthday is in no month", not in_month({}, late_oct))

    # ---- the shop ----------------------------------------------------------------------------
    for tid, name in (("t1", "Café"), ("t2", "Rival")):
        db.tenants.insert_one({"id": tid, "slug": tid, "name": name, "plan": "vip",
                               "subscription_status": "active", "is_active": True})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    db.users.insert_one({"email": "r@x.fr", "role": "business_owner", "tenant_id": "t2"})
    db.users.insert_one({"email": "s@x.fr", "role": "staff", "tenant_id": "t1"})
    token = lambda email, role, tid: {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": email, "role": role, "tenant_id": tid})}
    H = token("o@x.fr", "business_owner", "t1")
    RIVAL = token("r@x.fr", "business_owner", "t2")
    STAFF = token("s@x.fr", "staff", "t1")
    db.tenants.update_one({"id": "t1"}, {"$set": {"branches": [{"id": "b1", "name": "Nord", "status": "active"},
                                                              {"id": "b2", "name": "Sud", "status": "active"}]}})
    db.users.insert_one({"email": "m@x.fr", "role": "manager", "tenant_id": "t1", "branch_ids": ["b1"]})
    MANAGER = token("m@x.fr", "manager", "t1")

    def person(cid, tid="t1", **kw):
        db.customers.insert_one({"id": cid, "tenant_id": tid, "name": f"Client {cid}", "barcode_id": f"FT-{cid.upper()}",
                                 "visits": 2, "total_amount_paid": 20.0, "created_at": now - dt.timedelta(days=100),
                                 "last_visit_date": now - dt.timedelta(days=5), **kw})

    person("mm", birthday=f"{this}-10", branch_id="b1")
    person("iso", birthday=f"1990-{this}-11", branch_id="b1")
    person("full", birthday="", birth_date=f"1985-{this}-12", branch_id="b2")
    person("nope", birthday=f"{other}-10", branch_id="b1", tier="vip")
    person("none", branch_id="b1")
    person("gone", birthday=f"{this}-13", deleted_at=now, branch_id="b1")
    person("rival", tid="t2", birthday=f"{this}-14")
    expected = {"mm", "iso", "full"}

    print("\nLa page Clients : le chiffre du filtre = sa liste")
    chip = lambda headers=None: next(s for s in http("GET", "/api/owner/clients/overview", headers=headers).json()["segments"]
                                     if s["key"] == "birthday")["count"]
    listed = lambda query="segment=birthday", headers=None: http(
        "GET", f"/api/owner/clients/list?per_page=100&{query}", headers=headers).json()
    check("the chip counts the three", chip() == 3, chip())
    got = listed()
    check("the list shows the same three", {r["id"] for r in got["rows"]} == expected, got)
    check("its total is the chip's", got["total"] == chip())
    check("the export-side ids agree", set(http("GET", "/api/owner/clients/ids?segment=birthday").json()["ids"]) == expected)
    check("a deleted client is out", "gone" not in {r["id"] for r in got["rows"]})
    check("another shop's client is out", "rival" not in {r["id"] for r in got["rows"]})
    check("a search that matches nobody gives 0, never someone else",
          listed("segment=birthday&search=birthdays")["total"] == 0)
    check("a search and the filter together narrow", {r["id"] for r in listed("segment=birthday&search=Client%20iso")["rows"]} == {"iso"})
    check("several segments: any of them", "nope" in {r["id"] for r in listed("segment=birthday,vip")["rows"]})

    print("\nSegmentation : le segment par défaut")
    page = http("GET", "/api/owner/segmentation/page").json()
    row = next((s for s in page["segments"] if s["id"] == "model:anniversaires"), None)
    check("« Anniversaires du mois » is there by default", row and row["name"] == "Anniversaires du mois", [s["id"] for s in page["segments"]])
    check("built in, nothing to create", row and row["builtin"] is True)
    check("its count is the Clients chip's", row and row["count"] == chip(), row and row["count"])
    check("its share is of the whole base", row and row["share"] == round(3 / 5 * 100))
    check("the rule reads as a sentence", row and row["summary"] == [{"icon": "calendar", "text": "Anniversaire : ce mois-ci"}], row and row["summary"])
    mem = http("GET", "/api/owner/segmentation/segments/model:anniversaires/clients").json()
    check("« Voir » lists the same three", set(mem["ids"]) == expected, mem)
    check("… with their names", {c["name"] for c in mem["clients"]} == {f"Client {i}" for i in expected})
    check("the five rows of the design are still there",
          {f"model:{k}" for k in ("inactifs", "fideles", "nouveaux", "gros_paniers", "locaux")} <= {s["id"] for s in page["segments"]})
    check("the builder offers the criterion", any(f["key"] == "birthday" for f in page["fields"]))
    prev = http("POST", "/api/owner/segmentation/preview",
                json={"rules": [{"field": "birthday", "op": "eq", "value": "current"}]}).json()
    check("the builder's preview counts the same", prev["count"] == 3, prev)
    check("a value the builder does not offer is dropped",
          SG._clean_rules([{"field": "birthday", "op": "eq", "value": "13"}]) == [])
    check("nor an operator", SG._clean_rules([{"field": "birthday", "op": "gt", "value": "current"}]) == [])

    print("\nLe segment suit le calendrier, sans rien enregistrer")
    same = lambda at: {c["id"] for c in SG.evaluate("t1", SG._clean_rules([{"field": "birthday", "op": "eq", "value": "current"}]), at=at)}
    db.customers.insert_many([{"id": "oct", "tenant_id": "t1", "birthday": "10-05", "deleted_at": None},
                              {"id": "nov", "tenant_id": "t1", "birthday": "11-05", "deleted_at": None}])
    check("October names October's", "oct" in same(dt.datetime(2026, 10, 15, tzinfo=UTC)))
    check("the night the month turns, Paris decides", "nov" in same(late_oct) and "oct" not in same(late_oct))
    CP_at = lambda c, at: CP._matches_segment("birthday", c, at, 0.0, set(), None)
    check("the Clients chip turns the same night", CP_at({"birthday": "11-05"}, late_oct) and not CP_at({"birthday": "10-05"}, late_oct))
    db.customers.delete_many({"id": {"$in": ["oct", "nov"]}})

    print("\nEnregistré dans « mes segments »")
    made = http("POST", "/api/owner/segmentation/segments", json={"name": "", "model": "anniversaires"})
    check("« Enregistrer dans mes segments » works", made.status_code == 200 and made.json()["count"] == 3, made.text)
    page = http("GET", "/api/owner/segmentation/page").json()
    names = [s["name"] for s in page["segments"]]
    check("then it is listed once", names.count("Anniversaires du mois") == 1, names)
    again = http("POST", "/api/owner/segmentation/segments", json={"name": "", "model": "anniversaires"})
    check("not twice", again.status_code == 409, again.status_code)
    mine = next(s for s in page["segments"] if s["name"] == "Anniversaires du mois")
    check("the saved one counts the same", mine["count"] == 3)
    http("DELETE", f"/api/owner/segmentation/segments/{mine['id']}")
    check("deleted, the default comes back",
          any(s["id"] == "model:anniversaires" for s in http("GET", "/api/owner/segmentation/page").json()["segments"]))

    print("\nPentest : autres rôles, autres commerces, autres établissements")
    check("no token: refused", http("GET", "/api/owner/segmentation/segments/model:anniversaires/clients", headers={}).status_code == 401)
    check("staff: refused", http("GET", "/api/owner/segmentation/segments/model:anniversaires/clients", headers=STAFF).status_code == 403)
    theirs = http("GET", "/api/owner/segmentation/segments/model:anniversaires/clients", headers=RIVAL).json()
    check("another shop sees only its own client", theirs["ids"] == ["rival"], theirs)
    check("… and its chip says 1", chip(headers=RIVAL) == 1)
    nord = {**H, "X-FidClic-Store": "b1"}
    sud = {**H, "X-FidClic-Store": "b2"}
    check("store Nord: two", set(http("GET", "/api/owner/segmentation/segments/model:anniversaires/clients", headers=nord).json()["ids"]) == {"mm", "iso"})
    check("store Sud: one", set(http("GET", "/api/owner/segmentation/segments/model:anniversaires/clients", headers=sud).json()["ids"]) == {"full"})
    check("Clients chip of Nord agrees", chip(headers=nord) == 2)
    check("Clients chip of Sud agrees", chip(headers=sud) == 1)
    check("a manager of Nord sees Nord", set(http("GET", "/api/owner/segmentation/segments/model:anniversaires/clients", headers=MANAGER).json()["ids"]) == {"mm", "iso"})
    asked_sud = http("GET", "/api/owner/segmentation/segments/model:anniversaires/clients", headers={**MANAGER, "X-FidClic-Store": "b2"})
    check("asking for Sud does not show Sud's client", asked_sud.status_code == 403 or "full" not in asked_sud.json().get("ids", []), asked_sud.text)
    check("nor on his chip", chip(headers=MANAGER) == 2)
    bad = http("GET", "/api/owner/clients/list?segment=birthday&search=%7B%22%24ne%22%3Anull%7D").json()
    check("a Mongo-shaped search finds nobody", bad["total"] == 0)
    check("a regex search finds nobody", http("GET", "/api/owner/clients/list?segment=birthday&search=.*").json()["total"] == 0)
    db.customers.insert_one({"id": "xss", "tenant_id": "t1", "name": "<img src=x onerror=alert(1)>", "birthday": f"{this}-01", "deleted_at": None})
    got = http("GET", "/api/owner/segmentation/segments/model:anniversaires/clients").json()
    check("a name with HTML comes back as plain data", "<img src=x onerror=alert(1)>" in {c["name"] for c in got["clients"]})
    db.customers.delete_one({"id": "xss"})

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
