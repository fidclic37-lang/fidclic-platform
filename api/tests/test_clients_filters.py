"""
Clients — filtrer par dates, par âge, et lire les ventes d'un jour
(user, 2026-10-20).

The shop asked: « ek particular date ki puri sales data dekh sake … us case
mein total spent n rhe jo ki lifetime spent of a customer hai, balki us
particular date ki spending dikhe ». So when « Ventes du … au … » is set, the
table stops talking about a client's whole history and talks about those days
— and the strip above it, the file exported and the « Contacter (N) » count
must all say the same thing.

Also here: Segment and Statut taking several values at once, « de … à » on
the age beside the ready-made slices, and the exact day boundaries in France.

Run: cd api && /usr/local/bin/python3 tests/test_clients_filters.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-clients-filters")
os.environ.setdefault("DISABLE_SEED", "1")
PARIS = ZoneInfo("Europe/Paris")
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
    from features import clients_page as CP

    db = server.db
    now = datetime.now(timezone.utc)

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "shop", "name": "Le Shop", "plan": "vip",
                           "subscription_status": "active", "is_active": True})
    db.users.insert_one({"email": "o@shop.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    H = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "o@shop.fr", "role": "business_owner", "tenant_id": "t1"})}

    # Three days that matter, written in Paris time
    def paris(y, m, d, hh=12, mm=0):
        return datetime(y, m, d, hh, mm, tzinfo=PARIS).astimezone(timezone.utc)
    D1, D2 = "2026-10-19", "2026-10-20"

    def client(cid, name, birth, joined, last, visits, spent):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": name, "barcode_id": f"FT-{cid.upper()}",
                                 "email": f"{cid}@x.fr", "phone": f"06000000{cid[-2:]}", "birth_date": birth,
                                 "created_at": joined, "last_visit_date": last, "visits": visits,
                                 "total_amount_paid": spent, "deleted_at": None, "tier": "bronze"})

    def visit(cid, when, amount):
        db.visits.insert_one({"id": f"v{db.visits.count_documents({}) + 1}", "tenant_id": "t1",
                              "customer_id": cid, "amount_paid": amount, "visit_time": when})

    # Alice: 2 visits on the 20th (22 + 18), 1 on the 19th — 300 € in her life
    client("c1", "Alice Martin", "1998-03-04", paris(2026, 1, 5), paris(2026, 10, 20, 18), 12, 300.0)
    visit("c1", paris(2026, 10, 19, 11), 40.0)
    visit("c1", paris(2026, 10, 20, 10), 22.0)
    visit("c1", paris(2026, 10, 20, 18), 18.0)
    # Bob: one visit on the 20th, just after midnight in France (00:30)
    client("c2", "Bob Durand", "2006-09-30", paris(2026, 10, 18), paris(2026, 10, 20, 0, 30), 1, 29.0)
    visit("c2", paris(2026, 10, 20, 0, 30), 29.0)
    # Chloé: only the 19th — she must not appear in « le 20 »
    client("c3", "Chloé Petit", "1970-02-11", paris(2026, 9, 1), paris(2026, 10, 19, 15), 4, 120.0)
    visit("c3", paris(2026, 10, 19, 15), 55.0)
    # David: never came
    client("c4", "David Noé", None, paris(2026, 10, 17), None, 0, 0.0)

    def listed(**q):
        url = "/api/owner/clients/list?per_page=50&" + "&".join(f"{k}={v}" for k, v in q.items())
        return http("GET", url, headers=H).json()

    def names(d):
        return sorted(r["name"] for r in d["rows"])

    def by(d, name):
        return next(r for r in d["rows"] if r["name"] == name)

    # ------------------------------------------------------------------ 1
    print("\n1. Les ventes d'un jour — les colonnes parlent de CE jour")
    d = listed(sales_from=D2, sales_to=D2)
    check(f"seuls les clients venus le 20 ({names(d)})", names(d) == ["Alice Martin", "Bob Durand"])
    a = by(d, "Alice Martin")
    check(f"Alice : 40 € ce jour-là, pas ses 300 € de toujours ({a['spent']} €)", a["spent"] == 40.0)
    check(f"…et 2 visites ce jour-là, pas 12 ({a['visits']})", a["visits"] == 2)
    check("sa fiche garde quand même son total de toujours",
          a["spent_total"] == 300.0 and a["visits_total"] == 12)
    check("la page sait que les colonnes sont celles de la période", a["period_mode"] is True)
    b = by(d, "Bob Durand")
    check(f"une visite à 00h30 compte bien le 20 (heure de Paris) ({b['spent']} €)", b["spent"] == 29.0)
    check("Chloé, venue seulement le 19, n'y est pas", "Chloé Petit" not in names(d))

    print("\n2. Le bandeau au-dessus du tableau")
    p = d["period"]
    check(f"« le 20 octobre » ({p['from']} → {p['to']})", p["from"] == D2 and p["to"] == D2 and p["one_day"])
    check(f"3 visites · 2 clients · 69 € ({p['visits']} / {p['clients']} / {p['spent']})",
          p["visits"] == 3 and p["clients"] == 2 and p["spent"] == 69.0)
    check(f"panier moyen 23 € ({p['basket']})", p["basket"] == 23.0)
    check("le total du bandeau est bien la somme des lignes",
          round(sum(r["spent"] for r in d["rows"]), 2) == p["spent"])
    check("sans période, pas de bandeau", listed()["period"] is None)

    print("\n3. Deux jours, et l'ordre inversé")
    d2 = listed(sales_from=D1, sales_to=D2)
    check(f"du 19 au 20 : les trois clients ({names(d2)})",
          names(d2) == ["Alice Martin", "Bob Durand", "Chloé Petit"])
    check(f"Alice : 40 + 22 + 18 = 80 € ({by(d2, 'Alice Martin')['spent']})",
          by(d2, "Alice Martin")["spent"] == 80.0)
    check("les dates à l'envers donnent la même période",
          listed(sales_from=D2, sales_to=D1)["period"]["spent"] == d2["period"]["spent"])
    check("une seule date suffit — c'est ce jour-là",
          listed(sales_from=D2)["period"]["spent"] == 69.0
          and listed(sales_to=D2)["period"]["spent"] == 69.0)

    print("\n4. « Contacter (N) » et l'export disent la même chose")
    ids = http("GET", f"/api/owner/clients/ids?sales_from={D2}&sales_to={D2}", headers=H).json()
    check(f"autant d'ids que de lignes ({ids['total']})", ids["total"] == d["total"] == 2)
    csv = http("GET", f"/api/owner/clients/export?sales_from={D2}&sales_to={D2}", headers=H).text
    head, *body = [l for l in csv.splitlines() if l.strip()]
    check(f"l'en-tête dit le jour ({head.split(';')[7]})", "20/10/2026" in head and "Dépensé" in head)
    check("le fichier porte les montants du jour, pas ceux de toujours",
          any(line.startswith("Alice Martin;") and ";40,00;" in line for line in body))
    check("et seulement les clients venus ce jour-là", len(body) == 2)

    # ------------------------------------------------------------------ 5
    print("\n5. L'âge — de … à …, et les tranches toutes faites")
    check(f"de 18 à 25 : Bob seul ({names(listed(age_min=18, age_max=25))})",
          names(listed(age_min=18, age_max=25)) == ["Bob Durand"])
    check("à partir de 50 : Chloé", names(listed(age_min=50)) == ["Chloé Petit"])
    check("jusqu'à 30 : Bob et Alice", names(listed(age_max=30)) == ["Alice Martin", "Bob Durand"])
    check("la tranche 25-34 : Alice", names(listed(age_band="25_34")) == ["Alice Martin"])
    check("la tranche 50+ : Chloé", names(listed(age_band="50p")) == ["Chloé Petit"])
    check("une tranche et un « de … » se croisent, ils ne s'annulent pas",
          names(listed(age_band="18_24", age_min=30)) == [])
    check("sans date de naissance complète, le client n'est dans aucune tranche",
          "David Noé" not in names(listed(age_min=0)))

    print("\n6. Les dates d'inscription et de dernière visite")
    check(f"inscrits le 18 octobre ({names(listed(joined_from='2026-10-18', joined_to='2026-10-18'))})",
          names(listed(joined_from="2026-10-18", joined_to="2026-10-18")) == ["Bob Durand"])
    check("inscrits du 17 au 18 : David et Bob",
          names(listed(joined_from="2026-10-17", joined_to="2026-10-18")) == ["Bob Durand", "David Noé"])
    check("dernière visite le 19 : Chloé seule",
          names(listed(last_from=D1, last_to=D1)) == ["Chloé Petit"])
    check("dernière visite le 20 : Alice et Bob",
          names(listed(last_from=D2, last_to=D2)) == ["Alice Martin", "Bob Durand"])
    check("jamais venu → jamais dans « dernière visite »",
          "David Noé" not in names(listed(last_from="2026-01-01", last_to="2026-12-31")))

    print("\n7. Segment et Statut — plusieurs à la fois")
    rows = listed()["rows"]
    segs = {r["name"]: r["segment"] for r in rows}
    sts = {r["name"]: r["status"] for r in rows}
    one = [n for n, v in segs.items() if v == segs["David Noé"]]
    two = sorted(set(segs.values()))
    check(f"un seul segment filtre comme avant ({segs['David Noé']})",
          sorted(names(listed(segment=segs["David Noé"]))) == sorted(one))
    if len(two) > 1:
        both = listed(segment=f"{two[0]},{two[1]}")
        check(f"deux segments ensemble ({two[0]} + {two[1]} → {len(both['rows'])})",
              len(both["rows"]) == sum(1 for v in segs.values() if v in (two[0], two[1])))
    st_values = sorted(set(sts.values()))
    if len(st_values) > 1:
        both = listed(status=f"{st_values[0]},{st_values[1]}")
        check(f"deux statuts ensemble ({len(both['rows'])})",
              len(both["rows"]) == sum(1 for v in sts.values() if v in (st_values[0], st_values[1])))
    check("« all » ne filtre rien", len(listed(segment="all")["rows"]) == 4)

    print("\n8. Ce qui ne doit pas bouger")
    check("sans filtre, les quatre clients et les totaux de toujours",
          len(listed()["rows"]) == 4 and by(listed(), "Alice Martin")["spent"] == 300.0
          and by(listed(), "Alice Martin")["period_mode"] is False)
    check("une date impossible est ignorée, pas une erreur",
          len(listed(sales_from="pas-une-date")["rows"]) == 4)
    check("le client effacé reste hors de tout",
          (db.customers.update_one({"id": "c3"}, {"$set": {"deleted_at": now}}) or True)
          and "Chloé Petit" not in names(listed(sales_from=D1, sales_to=D1)))
    db.customers.update_one({"id": "c3"}, {"$set": {"deleted_at": None}})

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
