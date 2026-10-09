"""
One palier rule, shown where it is set (QA F21, user 2026-10-09):
  • the ladder under « Récompenses et paliers » decides every customer's
    palier — at each scan, in « Modifier la fiche », nowhere else;
  • the hidden « 10 visits and 60 € average = VIP » is now a visible,
    editable shortcut on the same card;
  • changing the ladder reclassifies everyone at once: the ones who go up
    are told (card + push), outside the daily limits; the ones who go down
    only see their card change;
  • Règles clients' « Client VIP » is « Client très actif » now.

Run: cd api && /usr/local/bin/python3 tests/test_tiers_rule.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-tiers-rule")
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
    import features.loyalty_card as LC
    import features.wallet_passes as WP
    import features.push_subscriptions as PS
    import features.send_rules as SR
    import features.customer_rules as CR

    db = server.db

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    pushed, woken = [], []
    PS.fan_out_to_customer = lambda tid, cid, title, body, url=None: pushed.append((cid, title, body)) or {"sent": 1}
    WP.notify_customer = lambda cid, message=None, google_notify=None: woken.append((cid, google_notify)) or {}
    WP.notify_tenant = lambda tid, customer_ids=None: woken.extend((c, "quiet") for c in (customer_ids or [])) or {}

    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Le Café", "is_active": True,
                           "plan": "vip", "subscription_status": "active"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10})

    T = lambda visits, paid=0, points=0: LC.tier_of({"visits": visits, "total_amount_paid": paid, "points": points}, "t1")

    print("1. La règle par défaut, visible")
    check("9 → Bronze, 10 → Argent, 20 → Or, 40 → VIP", [T(9), T(10), T(20), T(40)] == ["bronze", "silver", "gold", "vip"])
    check("the shortcut: 11 visits at 60 € average → VIP (the QA's cards 099/100)", T(11, 660) == "vip")
    check("…but not at 55 €", T(11, 605) == "silver")
    s = http("GET", "/api/owner/card/settings", headers=H).json()
    check("the card page receives the shortcut to show it", s.get("vip_shortcut") == {"enabled": True, "min_visits": 10, "min_avg": 60.0})

    print("\n2. Le propriétaire change les seuils : tout le monde est reclassé")
    for cid, v, paid, tier in (("a", 6, 30, "bronze"), ("b", 12, 120, "silver"), ("c", 25, 250, "gold"),
                               ("d", 11, 700, "vip")):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": f"Client {cid.upper()}", "barcode_id": f"FT-{cid.upper()}",
                                 "visits": v, "total_amount_paid": paid, "tier": tier, "points": 0})
    SR.put_rules(SR.RulesIn(per_client_day=1, per_client_week=0),
                 token_data=type("O", (), {"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})())
    server.dispatch_to_customer("t1", db.customers.find_one({"id": "a"}), "Promo", "…", kind="campaign")
    pushed.clear(); woken.clear()
    r = http("PUT", "/api/owner/card/rewards", headers=H, json={
        "tiers": [{"key": "bronze", "min": 0, "reward": "Café"}, {"key": "silver", "min": 5, "reward": "Croissant"},
                  {"key": "gold", "min": 30, "reward": "Menu"}, {"key": "vip", "min": 50, "reward": "Avantages VIP"}],
        "vip_shortcut": {"enabled": False, "min_visits": 10, "min_avg": 60}})
    body = r.json()
    tiers = {c["id"]: c["tier"] for c in db.customers.find({"tenant_id": "t1"})}
    check(f"saved ({r.status_code}): A 6 visits → Argent, C 25 → Argent, D without the shortcut → Argent",
          r.status_code == 200 and tiers == {"a": "silver", "b": "silver", "c": "silver", "d": "silver"})
    check("the answer says who moved: 1 up, 2 down", body.get("moved") == {"up": 1, "down": 2, "same": 1})
    a_push = [p for p in pushed if p[0] == "a"]
    check("A (up) is told — even though A already had today's one message (not counted)",
          a_push and "Argent" in a_push[0][1] and "Croissant" in a_push[0][2])
    check("…and A's card gets a Google message", any(c == "a" and isinstance(n, dict) and n.get("kind") == "tier_up" for c, n in woken))
    check("C and D (down) get no push, only their card refreshed",
          not [p for p in pushed if p[0] in ("c", "d")] and ("c", "quiet") in woken and ("d", "quiet") in woken)
    check("the daily « Atteinte d'un palier » is not stamped (no double congratulation)",
          not db.customers.find_one({"id": "a"}).get("tier_changed_at"))
    check("the shortcut setting is kept", LC.vip_shortcut(LC._template("t1"))["enabled"] is False)
    r = http("PUT", "/api/owner/card/rewards", headers=H, json=[{"key": "bronze", "min": 0}, {"key": "silver", "min": 5},
                                                               {"key": "gold", "min": 30}, {"key": "vip", "min": 50}])
    check(f"the older list-only body still saves ({r.status_code})", r.status_code == 200)

    print("\n3. Le passage en caisse suit les seuils du propriétaire")
    db.customers.insert_one({"id": "e", "tenant_id": "t1", "name": "Eva", "barcode_id": "FT-EVA", "visits": 4,
                             "total_amount_paid": 20, "tier": "bronze", "points": 0})
    r = http("POST", "/api/owner/scan", headers=H, json={"barcode_id": "FT-EVA", "amount_paid": 5})
    check(f"5th visit: Argent at the owner's 5, not the old 10 ({r.status_code})",
          r.status_code == 200 and r.json().get("tier") == "silver" and r.json().get("tier_upgraded"))
    # QA R5 F22 (2026-10-09): stamps added by hand move the card only — the
    # palier stays the real scans' (5 visits → Argent)
    r = http("POST", "/api/owner/clients/e/ajustement", headers=H, json={"visits": 3, "reason": "Cartes papier"})
    e = db.customers.find_one({"id": "e"})
    check(f"« Ajuster » +3 stamps: the card moves, the palier stays Argent ({r.status_code})",
          r.status_code == 200 and e["tier"] == "silver" and e["visits"] == 5)

    print("\n4. Carte à points : le palier se lit en points")
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"programme": "points_euro", "reward_tiers": [],
                                                                "vip_shortcut": {"enabled": False}}})
    check("default points ladder: 99 → Bronze, 100 → Argent, 600 → VIP",
          [T(1, points=99), T(1, points=100), T(1, points=600)] == ["bronze", "silver", "vip"])

    print("\n5. Règles clients : « Client très actif »")
    names = {r["key"]: r["name"] for r in CR.defaults()}
    check("the built-in is « Client très actif »", names.get("vip") == "Client très actif")
    db.customer_status_config.insert_one({"tenant_id": "t9", "rules": [
        {"id": "vip", "key": "vip", "name": "Client VIP", "description": "Client très actif et à forte valeur.",
         "conditions": [{"type": "visits_per_month", "value": 8}], "enabled": True, "order": 0}]})
    old = CR.load("t9")[0]
    check("a saved « Client VIP » reads « Client très actif »", old["name"] == "Client très actif"
          and "palier VIP" in old["description"])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
