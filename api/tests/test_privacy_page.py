"""
Données & confidentialité — every switch does something real: marketing off
stops sends, geo off stops proximity reminders, the consent sentence reaches
the join page, export, erasure, and the retention durations.

Run: cd api && /usr/local/bin/python3 tests/test_privacy_page.py
"""
import datetime as dt
import io
import json
import os
import sys
import zipfile

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from fastapi import HTTPException
    from features import privacy_page as P
    from features import send_rules as SR

    db = server.db
    for m in (P, SR):
        m.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class OWNER:
        email, role, tenant_id = "o@corner.fr", "business_owner", "t1"

    out = []
    import features.push_subscriptions as PS
    PS.fan_out_to_customer = lambda tid, cid, title, body, url=None: (out.append((cid, title)) or {"sent": 1})
    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "slug": "corner", "name": "Le Corner Café", "plan": "gold", "geo_enabled": True})
    db.customers.insert_many([
        {"id": "c1", "tenant_id": "t1", "name": "Marie Dupont", "phone": "+33 6 12 34 56 78", "email": "marie@x.fr",
         "barcode_id": "FT-C1", "visits": 4, "points": 40, "consent": {"accepted": True, "ts": now, "policy_version": "2026-07-21"},
         "created_at": now - dt.timedelta(days=100), "last_visit_date": now - dt.timedelta(days=2)},
        {"id": "c2", "tenant_id": "t1", "name": "Paul Old", "barcode_id": "FT-C2", "visits": 1,
         "created_at": now - dt.timedelta(days=1500), "last_visit_date": now - dt.timedelta(days=1400)},
    ])
    db.visits.insert_many([
        {"id": "v1", "tenant_id": "t1", "customer_id": "c1", "amount_paid": 9.5, "visit_time": now - dt.timedelta(days=2),
         "items": [{"name": "Latte", "qty": 2}]},
        {"id": "v2", "tenant_id": "t1", "customer_id": "c1", "amount_paid": 4.0, "visit_time": now - dt.timedelta(days=2300)},
    ])

    print("\nThe page")
    v = P.get_privacy(token_data=OWNER())
    check("consent collection is always on", v["consent"]["collect"] is True)
    check("not fully compliant until the durations are saved", v["compliance"]["ok"] is False)
    check("five kinds of data listed, location optional", len(v["collected"]) == 5 and v["collected"][-1]["status"] == "optional")

    print("\nCommunications marketing")
    P.put_privacy(P.PrivacyIn(consent=P.ConsentIn(marketing=False)), token_data=OWNER())
    c1 = db.customers.find_one({"id": "c1"})
    r = server.dispatch_to_customer("t1", c1, "Promo", "…", kind="campaign")
    check("off: a campaign does not leave", r.get("reason") == "marketing_off" and not out)
    server.dispatch_to_customer("t1", c1, "Récompense", "…", kind="reward_unlocked")
    check("… what follows the client's own action still does", out == [("c1", "Récompense")])
    P.put_privacy(P.PrivacyIn(consent=P.ConsentIn(marketing=True)), token_data=OWNER())

    print("\nGéolocalisation")
    P.put_privacy(P.PrivacyIn(consent=P.ConsentIn(geo=False)), token_data=OWNER())
    check("off: the business says so", P.geo_allowed("t1") is False)
    P.put_privacy(P.PrivacyIn(consent=P.ConsentIn(geo=True)), token_data=OWNER())

    print("\nThe consent sentence and the policy, on the join page")
    txt = "J'accepte que {business_name} conserve mes visites pour ma carte et m'envoie ses offres. Je peux tout supprimer."
    P.put_privacy(P.PrivacyIn(consent=P.ConsentIn(text=txt), policy=P.PolicyIn(url="https://lecornercafe.fr/confidentialite"),
                              cookie_notice=True), token_data=OWNER())
    j = server.get_join_info("corner")["privacy_public"]
    check("the shop's own sentence, with its name", j["consent_text"].startswith("J'accepte que Le Corner Café conserve"))
    check("its policy link and cookie notice", j["policy_url"].endswith("/confidentialite") and j["cookie_notice"] is True)
    try:
        P.put_privacy(P.PrivacyIn(consent=P.ConsentIn(text="ok")), token_data=OWNER()); short = True
    except HTTPException:
        short = False
    check("a sentence that explains nothing is refused", short is False)
    try:
        P.put_privacy(P.PrivacyIn(policy=P.PolicyIn(url="http://x")), token_data=OWNER()); plain = True
    except HTTPException:
        plain = False
    check("a policy link must be https", plain is False)

    print("\nExport")
    r = P.export(P.ExportIn(format="csv", sections=["identity", "loyalty", "consents"]), token_data=OWNER())
    body = r.body.decode("utf-8")
    check("CSV for Excel: BOM, « ; », the client's data", body.startswith("﻿") and ";" in body and "Marie Dupont" in body)
    check("… with the consent proof", "2026-07-21" in body)
    r = P.export(P.ExportIn(format="csv", sections=["identity", "purchases"]), token_data=OWNER())
    z = zipfile.ZipFile(io.BytesIO(r.body))
    check("with purchases: a zip, clients.csv + visites.csv, products listed",
          set(z.namelist()) == {"clients.csv", "visites.csv"} and "2 × Latte" in z.read("visites.csv").decode("utf-8"))
    r = P.export(P.ExportIn(format="json", sections=["identity"]), token_data=OWNER())
    check("JSON too", json.loads(r.body)["clients"][0]["nom"] in ("Marie Dupont", "Paul Old"))

    print("\nErasing one client")
    check("found by name, phone or e-mail",
          [x["id"] for x in P.search(q="marie", token_data=OWNER())["results"]] == ["c1"]
          and [x["id"] for x in P.search(q="06 12 34 56 78", token_data=OWNER())["results"]] == ["c1"])
    try:
        P.erase_customer("c1", confirm=False, token_data=OWNER()); unconfirmed = True
    except HTTPException:
        unconfirmed = False
    check("never without confirmation", unconfirmed is False)
    P.erase_customer("c1", confirm=True, token_data=OWNER())
    c1 = db.customers.find_one({"id": "c1"})
    check("anonymised like a client's own request", c1["name"] == "Client supprimé" and not c1["phone"] and c1.get("gdpr_erased_at"))

    print("\nConservation")
    check("nothing is removed before the owner saves the durations", P.apply_retention()["tenants"] == 0)
    P.put_privacy(P.PrivacyIn(retention=P.RetentionIn(inactive_years=3, transactions_years=5)), token_data=OWNER())
    res = P.apply_retention()
    check("a client silent for 3+ years is anonymised", db.customers.find_one({"id": "c2"}).get("gdpr_erased_at") and res["clients_erased"] == 1)
    check("a visit older than 5 years loses its client — the amount stays",
          db.visits.find_one({"id": "v2"})["customer_id"] is None and db.visits.find_one({"id": "v2"})["amount_paid"] == 4.0
          and db.visits.find_one({"id": "v1"})["customer_id"] == "c1")
    check("now compliant", P.get_privacy(token_data=OWNER())["compliance"]["ok"] is True)
    try:
        P.put_privacy(P.PrivacyIn(retention=P.RetentionIn(inactive_years=7)), token_data=OWNER()); odd = True
    except HTTPException:
        odd = False
    check("only the offered durations", odd is False)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
