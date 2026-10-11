"""
Récompense bientôt disponible — from the user's mockups (2026-10-11): X points
(or tampons, by the card's programme) before the nearest reward — the card's
own, or the next palier's when it has one — once per reward cycle; the
Ciblage's « Statut client » (the shop's Règles clients) and « Inscription
depuis »; a plage horaire and a daily limit whose overflow waits for the next
day (nobody dropped); the right panels from real data only.

Edge cases: jumping past the reward, a new cycle after a redemption, a palier
without a reward, a stamps card counting several visits per stamp, a cagnotte
card, a row saved before the mockups, the old default name.

Run: cd api && /usr/local/bin/python3 tests/test_automation_near_reward.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-automation-near-reward")
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
    import features.wallet_passes as WP
    import features.push_subscriptions as PS
    from features import automations as AU
    from features import clients_page as CPg
    from features import customer_rules as R

    db = server.db
    pushed = []

    def fake_dispatch(tid, cust, title, body, kind="campaign", url=None):
        pushed.append({"cid": cust.get("id"), "title": title, "body": body, "kind": kind})
        return {"sent": True, "channel": "push"}
    server.dispatch_to_customer = fake_dispatch
    WP.notify_customer = lambda cid, message=None, google_notify=None: {}
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else H, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC)
    ago = lambda d: now - dt.timedelta(days=d)  # noqa: E731
    for tid, name in (("t1", "Café Lumière"), ("t2", "Rival"), ("t3", "Tampons & Co"), ("t4", "Cagnotte")):
        db.tenants.insert_one({"id": tid, "slug": tid, "name": name, "plan": "vip", "subscription_status": "active", "is_active": True})
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "s@x.fr", "role": "staff", "tenant_id": "t1"},
                          {"email": "o3@x.fr", "role": "business_owner", "tenant_id": "t3"},
                          {"email": "r@x.fr", "role": "business_owner", "tenant_id": "t2"}])
    tok = lambda e, r, t: {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    H, STAFF, H3, H2 = tok("o@x.fr", "business_owner", "t1"), tok("s@x.fr", "staff", "t1"), \
        tok("o3@x.fr", "business_owner", "t3"), tok("r@x.fr", "business_owner", "t2")
    # t1: points per euro, the card's reward at 200 points; paliers in points, gold has no reward
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "points_euro", "reward_points": 200,
                                  "reward_description": "Un café offert",
                                  "reward_tiers": [{"key": "bronze", "min": 0, "reward": ""}, {"key": "silver", "min": 150, "reward": "Un cookie"},
                                                   {"key": "gold", "min": 400, "reward": ""}, {"key": "vip", "min": 800, "reward": "Le menu"}]})
    # t3: stamps, 10 stamps, 2 visits per stamp
    db.card_templates.insert_one({"tenant_id": "t3", "programme": "stamps", "reward_threshold_stamps": 10, "visits_per_stamp": 2,
                                  "reward_description": "Une coupe offerte",
                                  "reward_tiers": [{"key": "bronze", "min": 0, "reward": ""}, {"key": "silver", "min": 100, "reward": "x"},
                                                   {"key": "gold", "min": 200, "reward": ""}, {"key": "vip", "min": 400, "reward": ""}]})
    # t4: cagnotte — no card reward, paliers only
    db.card_templates.insert_one({"tenant_id": "t4", "programme": "cashback",
                                  "reward_tiers": [{"key": "bronze", "min": 0, "reward": ""}, {"key": "silver", "min": 50, "reward": "Un dessert"},
                                                   {"key": "gold", "min": 100, "reward": ""}, {"key": "vip", "min": 200, "reward": ""}]})

    def person(cid, tid="t1", **kw):
        doc = {"id": cid, "tenant_id": tid, "name": kw.pop("name", f"Client {cid}"), "barcode_id": f"FT-{cid.upper()}",
               "points": 0, "visits": 3, "created_at": ago(100), "last_visit_date": ago(2), **kw}
        db.customers.insert_one(doc)
        return doc

    for h in (H, H2, H3):
        http("GET", "/api/owner/automations", headers=h)       # each shop's automations set up

    print("\n1. Le nom, le seuil, les refus")
    page = http("GET", "/api/owner/automations").json()
    meta = next(x for x in page["scenarios"] if x["key"] == "near_reward")
    check("the scenario is « Récompense bientôt disponible »", meta["label"] == "Récompense bientôt disponible")
    old = next(r for r in db.automations.find({"tenant_id": "t1", "scenario": "near_reward"}, {"_id": 0}))
    db.automations.update_one({"id": old["id"]}, {"$set": {"name": "Proche de la récompense"}})
    mine = AU.new_doc("t1", "near_reward", name="Mon rappel")
    db.automations.insert_one(dict(mine))
    page = http("GET", "/api/owner/automations").json()
    names = {r["id"]: r["name"] for r in page["rows"]}
    check("a row with the old default name gets the new one", names[old["id"]] == "Récompense bientôt disponible")
    check("…an owner's own name is kept", names[mine["id"]] == "Mon rappel")
    db.automations.delete_one({"id": mine["id"]})
    check("the page knows the card: points, reward at 200", page["near"]["unit"] == "points" and page["near"]["card_goal"] == 200
          and page["near"]["card_reward"] == "Un café offert")
    check("…and the shop's own statuts for the filter", {"actif", "nouveau", "inactif"} <= {x["key"] for x in page["statuses"]})
    p3 = http("GET", "/api/owner/automations", headers=H3).json()["near"]
    check("a stamps card: tampons, 10", p3["unit"] == "tampons" and p3["card_goal"] == 10)

    base = {"scenario": "near_reward", "name": "Récompense bientôt disponible", "status": "active",
            "trigger": {"threshold": 10},
            "message": {"title": "Plus que quelques points !", "body": "Plus que {points_restants}, {prénom} : {récompense} ({points} pts)"},
            "targeting": {"mode": "filtered", "filters": {}},
            "schedule": {"days": "all", "window": False}}
    n0 = db.automations.count_documents({})

    def bad(patch, why, headers=None):
        body = {**base, **{k: ({**base[k], **v} if isinstance(v, dict) and isinstance(base.get(k), dict) else v) for k, v in patch.items()}}
        r = http("POST", "/api/owner/automations", json=body, headers=headers)
        check(f"refused: {why} ({(r.json().get('detail') or '')[:70]})", r.status_code == 400)
    bad({"trigger": {"threshold": 0}}, "a seuil of 0")
    bad({"trigger": {"threshold": -5}}, "a negative seuil")
    bad({"trigger": {"threshold": "beaucoup"}}, "a seuil that is not a number")
    bad({"trigger": {"threshold": 200}}, "a seuil equal to the card's reward")
    bad({"targeting": {"mode": "filtered", "filters": {"activity": ["champion"]}}}, "an unknown statut")
    bad({"targeting": {"mode": "filtered", "filters": {"signed_since": "hier"}}}, "a wrong inscription date")
    bad({"schedule": {"days": "all", "window": True, "window_from": "20:00", "window_to": "11:00"}}, "a plage ending before it starts")
    bad({"schedule": {"days": "all", "window": False, "daily_limit": 0.5}}, "a limit that is not whole")
    r = http("POST", "/api/owner/automations", json={**base, "trigger": {"threshold": 10}}, headers=H3)
    check("10 tampons on a 10-tampon card: refused", r.status_code == 400 and "10 tampons" in r.json()["detail"])
    check("nothing written by the refusals", db.automations.count_documents({}) == n0)
    r = http("POST", "/api/owner/automations", json=base, headers=STAFF)
    check("a staff member cannot create one", r.status_code == 403)
    r = http("POST", "/api/owner/automations", json=base)
    row = db.automations.find_one({"id": r.json()["id"]}, {"_id": 0})
    check("saved with its seuil only (no « visites » rule)", r.status_code == 200 and row["trigger"].get("threshold") == 10
          and "visits_left" not in row["trigger"])
    check("its trigger reads the seuil", r.json()["trigger_text"] == "Seuil presque atteint · 10 points avant la récompense")
    # only the new one fires in what follows
    db.automations.update_many({"tenant_id": "t1", "scenario": "near_reward", "id": {"$ne": row["id"]}}, {"$set": {"status": "paused"}})

    print("\n2. Points : la récompense de la carte, une fois par cycle")
    pushed.clear()
    alice = person("alice", name="Alice Martin", points=185)
    AU.fire("near_reward", "t1", alice, {"cycle": "first"})
    check("185 / 200: 15 to go, over the seuil — nothing", not pushed)
    db.customers.update_one({"id": "alice"}, {"$set": {"points": 190}})
    AU.fire("near_reward", "t1", db.customers.find_one({"id": "alice"}, {"_id": 0}), {"cycle": "first"})
    check("190 / 200: sent", len(pushed) == 1)
    check("the words: {points_restants}, {prénom}, {récompense}, {points}",
          pushed[0]["body"] == "Plus que 10 points, Alice : Un café offert (190 pts)")
    db.customers.update_one({"id": "alice"}, {"$set": {"points": 195}})
    AU.fire("near_reward", "t1", db.customers.find_one({"id": "alice"}, {"_id": 0}), {"cycle": "first"})
    check("195: same reward, same cycle — not again", len(pushed) == 1)
    db.customers.update_one({"id": "alice"}, {"$set": {"points": 192}})
    AU.fire("near_reward", "t1", db.customers.find_one({"id": "alice"}, {"_id": 0}), {"cycle": "2026-10-20T10:00:00"})
    check("after a redemption (a new cycle): told again", len(pushed) == 2)
    pushed.clear()
    bob = person("bob", points=185)
    db.customers.update_one({"id": "bob"}, {"$set": {"points": 205}})
    AU.fire("near_reward", "t1", db.customers.find_one({"id": "bob"}, {"_id": 0}), {"cycle": "first"})
    check("jumping past the reward in one visit: nothing (the reward itself is told)", not [p for p in pushed if p["cid"] == "bob"])
    one = person("one", points=199)
    AU.fire("near_reward", "t1", one, {"cycle": "first"})
    check("1 point to go: « 1 point » (singular)", pushed and pushed[-1]["body"].startswith("Plus que 1 point,"))

    print("\n3. Le palier, quand il est plus proche — et seulement s'il a une récompense")
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"reward_points": 1000}})
    pushed.clear()
    chloe = person("chloe", points=142)                 # silver (« Un cookie ») at 150: 8 to go; the card is 858 away
    AU.fire("near_reward", "t1", chloe, {"cycle": "first"})
    check("the next palier (8 points) comes first, with its own reward", pushed and pushed[-1]["body"].startswith("Plus que 8 points")
          and "Un cookie" in pushed[-1]["body"])
    dan = person("dan", points=395)                     # gold at 400 has NO reward written
    AU.fire("near_reward", "t1", dan, {"cycle": "first"})
    check("a palier without a reward is not « a reward »: nothing", not [p for p in pushed if p["cid"] == "dan"])
    t = AU.nearest_reward("t1", db.customers.find_one({"id": "dan"}, {"_id": 0}))
    check("…the nearest reward for him: the next palier WITH a reward, VIP's « Le menu »", t and t["reward"] == "Le menu" and t["remaining"] == 405)
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"reward_points": 200}})

    print("\n4. Tampons (2 visites par tampon) et cagnotte")
    r = http("POST", "/api/owner/automations", headers=H3,
             json={**base, "trigger": {"threshold": 2}, "message": {"title": "Presque !", "body": "Plus que {tampons_restants} : {récompense} ({tampons}/10)"}})
    check("2 tampons before a 10-tampon card: accepted", r.status_code == 200
          and r.json()["trigger_text"] == "Seuil presque atteint · 2 tampons avant la récompense")
    db.automations.update_many({"tenant_id": "t3", "scenario": "near_reward", "id": {"$ne": r.json()["id"]}}, {"$set": {"status": "paused"}})
    pushed.clear()
    eve = person("eve", tid="t3", visits=15, visits_at_last_redemption=0)        # 7 stamps: 3 to go
    AU.fire("near_reward", "t3", eve, {"cycle": "first"})
    check("15 visits = 7 tampons, 3 to go: nothing", not pushed)
    db.customers.update_one({"id": "eve"}, {"$set": {"visits": 16}})
    AU.fire("near_reward", "t3", db.customers.find_one({"id": "eve"}, {"_id": 0}), {"cycle": "first"})
    check("16 visits = 8 tampons, 2 to go: sent, in tampons", pushed and pushed[-1]["body"] == "Plus que 2 tampons : Une coupe offerte (8/10)")
    r = http("POST", "/api/owner/automations", headers=tok("o@x.fr", "business_owner", "t4"),
             json={**base, "trigger": {"threshold": 5}})
    check("a cagnotte card: no card reward to compare, the seuil is accepted", r.status_code == 200
          and r.json()["trigger_text"].endswith("5 € avant la récompense"))
    db.automations.update_many({"tenant_id": "t4", "scenario": "near_reward", "id": {"$ne": r.json()["id"]}}, {"$set": {"status": "paused"}})
    pushed.clear()
    gus = person("gus", tid="t4", points=47)
    AU.fire("near_reward", "t4", gus, {"cycle": "first"})
    check("cagnotte 47, palier at 50 (« Un dessert »): told, in €", pushed and "3 €" in pushed[-1]["body"] and "Un dessert" in pushed[-1]["body"])

    print("\n5. Ancienne automatisation (« X visites »)")
    legacy = next(r for r in db.automations.find({"tenant_id": "t1", "scenario": "near_reward", "trigger.visits_left": {"$exists": True}}, {"_id": 0}))
    db.automations.update_one({"id": legacy["id"]}, {"$set": {"status": "active", "trigger": {"visits_left": 2, "delay_value": 0, "delay_unit": "hours"},
                                                               "schedule.window": False}})
    db.automations.update_one({"id": row["id"]}, {"$set": {"status": "paused"}})
    pushed.clear()
    hugo = person("hugo", points=0)
    AU.fire("near_reward", "t1", hugo, {"visits_left": 2, "cycle": "first"})
    check("a row saved before keeps its « 2 visites » rule", len(pushed) == 1)
    AU.fire("near_reward", "t1", person("ines", points=0), {"visits_left": 3, "cycle": "first"})
    check("…and only at 2 visites", len(pushed) == 1)
    r = http("PUT", f"/api/owner/automations/{legacy['id']}", json={**base, "trigger": {"threshold": 10}})
    saved = db.automations.find_one({"id": legacy["id"]}, {"_id": 0})
    check("saved in the new editor: it switches to the seuil", r.status_code == 200 and saved["trigger"].get("threshold") == 10
          and "visits_left" not in saved["trigger"])
    db.automations.update_one({"id": legacy["id"]}, {"$set": {"status": "paused"}})
    db.automations.update_one({"id": row["id"]}, {"$set": {"status": "active"}})

    print("\n6. Le ciblage : statut client, inscription depuis")
    rules = R.load("t1")
    newbie = person("newbie", points=190, created_at=ago(3), visits=1)
    oldie = person("oldie", points=190, created_at=ago(400), visits=12, last_visit_date=ago(200))
    st_new, st_old = CPg.status_of(newbie, now, rules), CPg.status_of(oldie, now, rules)
    check(f"two different statuts to test with ({st_new} / {st_old})", st_new != st_old)

    def who(filters, mode="filtered"):
        rr = {"id": "x", "scenario": "near_reward", "targeting": {"mode": mode, "filters": filters}}
        return {c["id"] for c in db.customers.find({"tenant_id": "t1"}, {"_id": 0}) if AU.matches("t1", rr, c, now, {})}
    check("« Statut client » keeps that statut only", "newbie" in who({"activity": [st_new]}) and "oldie" not in who({"activity": [st_new]}))
    check("two statuts (OR)", {"newbie", "oldie"} <= who({"activity": [st_new, st_old]}))
    since = (now - dt.timedelta(days=10)).date().isoformat()
    check("« Inscription depuis » 10 days ago: the newcomer only", "newbie" in who({"signed_since": since}) and "oldie" not in who({"signed_since": since}))
    check("…the very day counts (signed up that day)", "newbie" in who({"signed_since": (now - dt.timedelta(days=3)).date().isoformat()}))
    check("mode all ignores the filters", "oldie" in who({"activity": [st_new]}, mode="all"))
    r = http("PUT", f"/api/owner/automations/{row['id']}", json={**base, "targeting": {"mode": "filtered", "filters": {"activity": [st_new], "signed_since": since}}})
    saved = db.automations.find_one({"id": row["id"]}, {"_id": 0})["targeting"]["filters"]
    check("saved: the statut and the date", r.status_code == 200 and saved["activity"] == [st_new] and saved["signed_since"] == since)
    pushed.clear()
    AU.fire("near_reward", "t1", db.customers.find_one({"id": "oldie"}, {"_id": 0}), {"cycle": "first"})
    AU.fire("near_reward", "t1", db.customers.find_one({"id": "newbie"}, {"_id": 0}), {"cycle": "first"})
    check("sent to the targeted one only", [p["cid"] for p in pushed] == ["newbie"])
    http("PUT", f"/api/owner/automations/{row['id']}", json=base)

    print("\n7. Plage horaire et limite quotidienne : personne n'est oublié")
    paris = AU._paris(now).date()
    # a fresh automation: today's sends of the one above do not count against this one's limit
    db.automations.update_one({"id": row["id"]}, {"$set": {"status": "paused"}})
    r = http("POST", "/api/owner/automations", json={**base, "schedule": {"days": "all", "window": True, "window_from": "11:00",
                                                                           "window_to": "20:00", "daily_limit": 1}})
    row = db.automations.find_one({"id": r.json()["id"]}, {"_id": 0})
    pushed.clear()
    noon = AU._from_paris(paris, 12, 0)
    j1, j2, j3 = person("j1", points=191), person("j2", points=192), person("j3", points=193)
    AU.fire("near_reward", "t1", j1, {"cycle": "first"}, at=noon)
    AU.fire("near_reward", "t1", j2, {"cycle": "first"}, at=noon)
    AU.fire("near_reward", "t1", j3, {"cycle": "first"}, at=noon)
    qs = sorted(db.automation_queue.find({"automation_id": row["id"]}, {"_id": 0}), key=lambda q: q["customer_id"])
    tomorrow11 = AU._from_paris(paris + dt.timedelta(days=1), 11, 0)
    after11 = AU._from_paris(paris + dt.timedelta(days=2), 11, 0)
    check("limit 1: the first at noon, the next waits", [p["cid"] for p in pushed] == ["j1"] and len(qs) == 2)
    check("…for tomorrow 11:00, and the third for the day after (each day full)",
          {q["customer_id"]: AU._aware(q["due_at"]) for q in qs} == {"j2": tomorrow11, "j3": after11})
    late = AU._from_paris(paris, 21, 30)
    pushed.clear()
    AU.fire("near_reward", "t1", person("night", points=191), {"cycle": "first"}, at=late)
    check("a scan at 21:30 (after the plage) waits too, nobody sent", not pushed and db.automation_queue.find_one({"customer_id": "night"}))
    db.automation_queue.delete_many({"customer_id": "night"})
    AU.run_due(tomorrow11, source="tick")
    check("tomorrow 11:00 the tick sends j2", [p["cid"] for p in pushed] == ["j2"])
    AU.run_due(tomorrow11 + dt.timedelta(minutes=15), source="tick")
    check("…and nothing more that day", [p["cid"] for p in pushed] == ["j2"])
    AU.run_due(after11, source="tick")
    check("the day after: j3 — nobody dropped", [p["cid"] for p in pushed] == ["j2", "j3"])
    db.automation_queue.insert_one({"id": "qx", "tenant_id": "t1", "automation_id": row["id"], "customer_id": "alice",
                                    "due_at": after11, "ctx": {"cycle": "z"}, "created_at": now})
    AU.run_due(after11 + dt.timedelta(minutes=1), source="tick")
    q = db.automation_queue.find_one({"customer_id": "alice", "automation_id": row["id"]})
    check("a waiting one released on a full day moves to the next day's plage",
          q and AU._aware(q["due_at"]) == AU._from_paris(paris + dt.timedelta(days=3), 11, 0))
    db.automation_queue.delete_many({})
    http("PUT", f"/api/owner/automations/{row['id']}", json=base)

    print("\n8. Les panneaux : de vraies données")
    db.customers.delete_many({"tenant_id": "t1"})
    pa, pb, pc = person("pa", points=190), person("pb", points=195, created_at=ago(2), visits=1), person("pc", points=100)
    db.visits.insert_many([{"tenant_id": "t1", "customer_id": "pa", "visit_time": ago(5), "points_awarded": 20},
                           {"tenant_id": "t1", "customer_id": "pc", "visit_time": ago(10), "points_awarded": 50}])
    r = http("POST", "/api/owner/automations/preview", json={"scenario": "near_reward", "targeting": {"mode": "filtered"},
                                                            "trigger": {"threshold": 10}})
    nr = r.json()["near"]
    check("audience: 2 clients within 10 points of their reward", r.status_code == 200 and nr["count"] == 2 and nr["unit"] == "points")
    check("a month ago: Alice had 170 (not within), nobody else — 0, so no %", nr["month_ago"] == 0 and nr["delta"] is None)
    groups = {g["key"]: g["n"] for g in nr["groups"]}
    check("répartition: the newcomer under « Nouveaux », the four boxes add up", groups["new"] == 1 and sum(groups.values()) == 2)
    db.rewards_redeemed.insert_one({"tenant_id": "t1", "customer_id": "pa", "redeemed_at": ago(3)})
    nr = http("POST", "/api/owner/automations/preview", json={"scenario": "near_reward", "targeting": {"mode": "filtered"},
                                                             "trigger": {"threshold": 10}}).json()["near"]
    check("a client who redeemed since is left out of « a month ago » (unknown then)", nr["month_ago"] == 0)
    r = http("POST", "/api/owner/automations/preview", json={"scenario": "near_reward", "targeting": {"mode": "filtered"}, "trigger": {"threshold": 10}},
             headers=STAFF)
    check("a staff member does not see the panels", r.status_code == 403)
    nr2 = http("POST", "/api/owner/automations/preview", json={"scenario": "near_reward", "targeting": {"mode": "filtered"}, "trigger": {"threshold": 10}},
               headers=H2).json()["near"]
    check("another shop sees its own clients only", nr2["count"] == 0)

    print("\n9. Le passage en caisse déclenche le rappel")
    pushed.clear()
    db.customers.delete_many({"tenant_id": "t1"})
    kim = person("kim", points=190)
    server._evaluate_reward_state_and_notify({"id": "kim"}, "t1")
    check("the scan's reward check sends it (no visits estimate needed)", [p["cid"] for p in pushed] == ["kim"])
    server._evaluate_reward_state_and_notify({"id": "kim"}, "t1")
    check("…once", len(pushed) == 1)

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
