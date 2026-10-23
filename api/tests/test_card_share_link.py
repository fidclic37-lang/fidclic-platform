"""
« Programme de parrainage — 🎁 Partagez la carte » on the back of the card
(user, 2026-10-23: a customer could not share their own card's QR or link).
The link opens /card/<id>/partager; it never carries the owner key; Google
gets it as a link, not as text.

Run: cd api && /usr/local/bin/python3 tests/test_card_share_link.py
"""
import contextlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-card-share")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import features.wallet_passes as WP

    db = server.db
    WP._site_url = lambda: "https://app.fidclic.com"
    db.tenants.insert_one({"id": "t1", "slug": "oshop", "name": "O'SHOP", "plan": "vip",
                           "subscription_status": "active", "is_active": True})
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "name": "Léa Martin", "barcode_id": "FT-SHARE001",
                             "visits": 1, "points": 0, "deleted_at": None, "card_key": "secretkey123"})
    pay = lambda: server._serialize_card_payload(db.customers.find_one({"id": "c1"}, {"_id": 0}))  # noqa: E731

    print("1. On the back of the Apple card")
    back = WP.build_pass_json(pay())["storeCard"]["backFields"]
    f = next((x for x in back if x["key"] == "share_link"), None)
    check("a « Partager ma carte » row (no parrainage set up)", f and f["label"] == "Partager ma carte")
    check("…its link opens the share page", f and f["value"] == "https://app.fidclic.com/card/FT-SHARE001/partager"
          and '>🎁 Partagez la carte</a>' in f["attributedValue"])
    check("…never with the owner key", f and "secretkey123" not in json.dumps(f) and "k=" not in f["value"])
    keys = [x["key"] for x in back]
    check("…right after « Ma carte en ligne »", keys.index("share_link") == keys.index("card") + 1)

    db.referral_config.insert_one({"tenant_id": "t1", "enabled": True})
    back = WP.build_pass_json(pay())["storeCard"]["backFields"]
    f = next(x for x in back if x["key"] == "share_link")
    check("parrainage on: « Programme de parrainage »", f["label"] == "Programme de parrainage")

    print("\n2. On the Google card")
    obj = WP._gw_object(pay())
    uris = [u["uri"] for u in obj["linksModuleData"]["uris"]]
    check("a link to the share page", "https://app.fidclic.com/card/FT-SHARE001/partager" in uris)
    check("…not a text row", not any(m["id"] == "share_link" for m in obj["textModulesData"]))

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
