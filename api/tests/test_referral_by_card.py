"""
Parrainage by card QR — the whole path, end to end.

There is no referral link and no second QR any more: an existing customer's
own loyalty card is the invitation. This boots the real server.py on
mongomock and walks the path a real pair of customers would:

    a stranger scans Marie's card
        → the QR is Marie's card URL, so the phone opens it
        → the phone carries no card, so it is sent to the signup form
        → the form asks who invited them and is told "Marie"
        → they sign up  → referral recorded, PENDING, nobody credited
        → they come in  → both credited, once, and never again

Run: /usr/local/bin/python3 api/tests/test_referral_by_card.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-for-referral-by-card")

passed = failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {label}")
    else:
        failed += 1
        print(f"  ✗ {label}")


def main():
    import server
    import features.referrals as R
    import features.wallet_passes as W

    db = server.db
    R._db = db
    W._db = db
    now = dt.datetime.now(dt.timezone.utc)

    db.tenants.insert_one({"id": "t1", "slug": "petit-cafe", "name": "Le Petit Café"})
    db.tenants.insert_one({"id": "t2", "slug": "rival", "name": "Rival"})
    db.referral_config.insert_one({
        "tenant_id": "t1", "enabled": True,
        "referrer_reward_points": 50, "referee_reward_points": 25,
        "minimum_visits_to_earn": 1})

    def customer(cid, tid, barcode, name, visits=0, points=0):
        db.customers.insert_one({"id": cid, "tenant_id": tid, "barcode_id": barcode,
                                 "name": name, "visits": visits, "points": points,
                                 "phone": f"06{cid[-1]}0000000", "created_at": now})
        return db.customers.find_one({"id": cid})

    marie = customer("c-marie", "t1", "FT-MARIE01", "Marie Dupont", visits=12, points=300)
    paul = customer("c-paul", "t1", "FT-PAUL001", "Paul Martin", visits=4, points=80)
    customer("c-rival", "t2", "FT-RIVAL01", "Chez le rival", visits=3)

    # ---- 1. one QR, and the till can still read it ------------------------------------------
    print("\n1. Un seul QR code")
    b = server.barcode_from
    check("the QR on the card is a URL, and the till finds the id in it",
          b("https://app.fidclic.com/card/FT-MARIE01") == "FT-MARIE01")
    check("query strings do not confuse it",
          b("https://app.fidclic.com/card/FT-MARIE01?notify=1") == "FT-MARIE01")
    check("an older card carrying the bare id still scans", b("FT-MARIE01") == "FT-MARIE01")
    check("a hand-typed lowercase code still scans", b("  ft-marie01 ") == "FT-MARIE01")
    check("nothing scanned is nothing matched", b("") == "" and b(None) == "")

    pass_json = W.build_pass_json(W._card_payload("FT-MARIE01"))
    check("the Apple pass carries the same URL, not the bare id",
          pass_json["barcodes"][0]["message"].endswith("/card/FT-MARIE01"))
    check("the till reads the Apple pass too",
          b(pass_json["barcodes"][0]["message"]) == "FT-MARIE01")
    check("the human-readable line under it is still the card number",
          pass_json["barcodes"][0]["altText"] == "FT-MARIE01")

    # ---- 2. what the signup form is told ----------------------------------------------------
    print("\n2. Qui invite")
    inv = R.inviter("FT-MARIE01")
    check("the form learns the inviter's first name", inv["first_name"] == "Marie")
    check("the form learns which shop to sign up for", inv["slug"] == "petit-cafe")
    check("the form learns what the filleul will get", inv["referee_points"] == 25)
    check("nothing else about the inviter leaks",
          set(inv) == {"enabled", "first_name", "slug", "business_name",
                       "referee_points", "referrer_points"})
    check("lowercase in the URL still resolves", R.inviter("ft-marie01")["first_name"] == "Marie")
    try:
        R.inviter("FT-NOBODY")
        found = True
    except Exception as exc:
        found = getattr(exc, "status_code", None) != 404
    check("an unknown card is a 404, not a blank invitation", not found)

    db.referral_config.update_one({"tenant_id": "t1"}, {"$set": {"enabled": False}})
    check("a shop with the programme off says so, and the card page stays a card page",
          R.inviter("FT-MARIE01")["enabled"] is False)
    check("and nothing is recorded while it is off",
          R.record("t1", "FT-MARIE01", {"id": "someone"}) is None)
    db.referral_config.update_one({"tenant_id": "t1"}, {"$set": {"enabled": True}})

    # ---- 3. the signup records it, and credits nobody ---------------------------------------
    print("\n3. L'inscription")
    lea = customer("c-lea", "t1", "FT-LEA0001", "Léa Bernard")
    row = R.record("t1", "FT-MARIE01", lea)
    check("the referral is recorded", row is not None)
    saved = db.referral_redemptions.find_one({"referee_customer_id": "c-lea"})
    check("it names the parrain", saved["referrer_customer_id"] == "c-marie")
    check("it is pending", saved["referrer_pending"] is True)
    check("it remembers it came from a card", saved["source"] == "qr_card")
    check("NOBODY is credited at signup",
          db.customers.find_one({"id": "c-marie"})["points"] == 300
          and db.customers.find_one({"id": "c-lea"})["points"] == 0)
    check("what each side is owed is frozen now",
          saved["referrer_points_promised"] == 50 and saved["referee_points_promised"] == 25)

    check("a card from another shop cannot parrainer here",
          R.record("t1", "FT-RIVAL01", customer("c-tom", "t1", "FT-TOM0001", "Tom")) is None)
    check("an unknown card records nothing",
          R.record("t1", "FT-NOBODY", customer("c-zoe", "t1", "FT-ZOE0001", "Zoé")) is None)
    check("nobody can be their own parrain",
          R.record("t1", "FT-MARIE01", db.customers.find_one({"id": "c-marie"})) is None)
    check("a filleul is parrainé exactly once",
          R.record("t1", "FT-PAUL001", db.customers.find_one({"id": "c-lea"})) is None)

    # ---- 4. the first visit pays both, once -------------------------------------------------
    print("\n4. La première visite")
    check("before the visit, nothing settles", R.settle("t1", "c-lea") is None)

    db.customers.update_one({"id": "c-lea"}, {"$set": {"visits": 1}})
    out = R.settle("t1", "c-lea")
    check("the first visit settles it", out is not None)
    check("the parrain is credited what they were promised",
          db.customers.find_one({"id": "c-marie"})["points"] == 350)
    check("the filleul is credited too",
          db.customers.find_one({"id": "c-lea"})["points"] == 25)
    settled = db.referral_redemptions.find_one({"referee_customer_id": "c-lea"})
    check("the row stops being pending", settled["referrer_pending"] is False)
    check("the row records what was actually paid",
          settled["referrer_points"] == 50 and settled["referee_points"] == 25)

    db.customers.update_one({"id": "c-lea"}, {"$set": {"visits": 2}})
    check("a second visit pays nothing more", R.settle("t1", "c-lea") is None)
    check("and the balances have not moved",
          db.customers.find_one({"id": "c-marie"})["points"] == 350
          and db.customers.find_one({"id": "c-lea"})["points"] == 25)

    # The merchant changing the reward must not rewrite what was promised.
    hugo = customer("c-hugo", "t1", "FT-HUGO001", "Hugo")
    R.record("t1", "FT-PAUL001", hugo)
    db.referral_config.update_one({"tenant_id": "t1"}, {"$set": {"referrer_reward_points": 5}})
    db.customers.update_one({"id": "c-hugo"}, {"$set": {"visits": 1}})
    R.settle("t1", "c-hugo")
    check("a reward changed after the fact does not rewrite history",
          db.customers.find_one({"id": "c-paul"})["points"] == 130)   # 80 + the promised 50

    # ---- 5. a shop that asks for more than one visit ----------------------------------------
    print("\n5. Quand le commerçant exige plus d'une visite")
    db.referral_config.update_one({"tenant_id": "t1"}, {"$set": {"minimum_visits_to_earn": 3}})
    nina = customer("c-nina", "t1", "FT-NINA001", "Nina")
    R.record("t1", "FT-MARIE01", nina)
    db.customers.update_one({"id": "c-nina"}, {"$set": {"visits": 2}})
    check("two visits are not enough when the shop asked for three",
          R.settle("t1", "c-nina") is None
          and db.referral_redemptions.find_one({"referee_customer_id": "c-nina"})["referrer_pending"])
    db.customers.update_one({"id": "c-nina"}, {"$set": {"visits": 3}})
    check("the third visit settles it", R.settle("t1", "c-nina") is not None)
    db.referral_config.update_one({"tenant_id": "t1"}, {"$set": {"minimum_visits_to_earn": 1}})

    # ---- 6. the retired code programme is really gone ---------------------------------------
    print("\n6. Le programme par code est retiré")
    paths = {r.path for r in server.app.routes if hasattr(r, "methods")}
    for gone in ("/api/customer/referral/code", "/api/customer/referral/redeem",
                 "/api/owner/referrals/share"):
        check(f"{gone} is gone", gone not in paths)
    check("/api/card/{barcode_id}/inviter is mounted instead",
          "/api/card/{barcode_id}/inviter" in paths)
    check("the pages that read the programme still exist",
          "/api/owner/referrals/overview" in paths and "/api/owner/referrals/export" in paths)
    src = open(os.path.join(os.path.dirname(__file__), "..", "features", "referrals.py")).read()
    check("the codes collection is no longer created", "referral_codes" not in src)
    check("the card is named as the one way in", "qr_card" in src)

    # ---- 7. the signup and the till are really wired ----------------------------------------
    print("\n7. Le câblage")
    server_src = open(os.path.join(os.path.dirname(__file__), "..", "server.py")).read()
    check("the signup accepts the card that was scanned", "parrain_barcode" in server_src)
    check("the signup records the referral", "record as _record_referral" in server_src)
    check("a scan settles what is owed", "settle as _settle_referral" in server_src)
    check("the till reads the id out of the URL", "normalized_barcode = barcode_from" in server_src)

    card_src = open(os.path.join(os.path.dirname(__file__), "..", "..",
                                 "src", "components", "PremiumLoyaltyCard.jsx")).read()
    check("the card's own QR is the card URL", "value={cardUrl(customer?.barcode_id)}" in card_src)
    join_src = open(os.path.join(os.path.dirname(__file__), "..", "..",
                                 "src", "pages", "JoinPage.jsx")).read()
    check("the signup form reads ?p= and sends it",
          "searchParams.get('p')" in join_src and "payload.parrain_barcode" in join_src)
    my_src = open(os.path.join(os.path.dirname(__file__), "..", "..",
                               "src", "pages", "MyWalletCardPage.jsx")).read()
    check("a phone with no card of its own is sent to the signup form",
          "fidelitour:last_card" in my_src and "/join/${data.slug}?p=" in my_src)
    check("ownership is read before the page claims the card for itself",
          "const [wasMine] = useState(() => {" in my_src
          and "if (wasMine === barcodeId) return;" in my_src)
    check("and it reads the snapshot index.html takes before React boots",
          "__fidclicPrevCard" in my_src)
    html = open(os.path.join(os.path.dirname(__file__), "..", "..", "index.html")).read()
    check("index.html snapshots the previous card before claiming this one",
          "window.__fidclicPrevCard = localStorage.getItem('fidelitour:last_card');" in html
          and html.index("window.__fidclicPrevCard")
              < html.index("localStorage.setItem('fidelitour:last_card', bc);"))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
