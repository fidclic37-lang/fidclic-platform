"""
Bienvenue — from the user's mockups (2026-10-11): the message goes when the
card lands in Apple or Google Wallet, never at the web signup (« sirf Wallet
add pe »), once per client, at once, with the {offre} / {lien} variables.

Edge cases: a second phone, a re-add, Apple then Google, a duplicate Google
callback, a removal, a forged call, a paused automation, a deleted client,
another shop, a card added at night.

Run: cd api && /usr/local/bin/python3 tests/test_automation_welcome.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-automation-welcome")
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
    import features.google_wallet_callbacks as GWC
    from features import automations as AU

    db = server.db
    pushed = []

    def fake_dispatch(tid, cust, title, body, kind="campaign", url=None):
        pushed.append({"cid": cust.get("id"), "title": title, "body": body, "kind": kind, "url": url})
        return {"sent": True, "channel": "push"}
    server.dispatch_to_customer = fake_dispatch
    WP.notify_customer = lambda cid, message=None, google_notify=None: {}
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}
    # Google's signature is tested in test_google_wallet_callbacks: here the body is trusted
    ISSUER = "3388000000099"
    WP._gw_issuer = lambda: ISSUER
    GWC.verify_and_open = lambda token, issuer, root_keys=None: token

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else H, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC)
    db.tenants.insert_many([
        {"id": "t1", "slug": "cafe", "name": "Café Lumière", "plan": "vip", "subscription_status": "active", "is_active": True},
        {"id": "t2", "slug": "rival", "name": "Rival", "plan": "vip", "subscription_status": "active", "is_active": True},
    ])
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "r@x.fr", "role": "business_owner", "tenant_id": "t2"}])
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    H, H2 = tok("o@x.fr", "business_owner"), tok("r@x.fr", "business_owner", "t2")
    db.card_templates.insert_one({"tenant_id": "t1", "reward_threshold_stamps": 10, "reward_description": "Un café offert"})
    db.campaigns.insert_one({"id": "o1", "tenant_id": "t1", "kind": "offre", "status": "sent", "name": "Café offert",
                             "sent_at": now - dt.timedelta(days=1), "recipient_ids": []})

    def person(cid, name, tid="t1", **kw):
        doc = {"id": cid, "tenant_id": tid, "name": name, "barcode_id": f"FT-{cid.upper()}", "points": 0, "visits": 0,
               "created_at": now, **kw}
        db.customers.insert_one(doc)
        return doc

    http("GET", "/api/owner/automations")                       # the shop's automations set up
    http("GET", "/api/owner/automations", headers=H2)
    wel = next(r for r in db.automations.find({"tenant_id": "t1", "scenario": "welcome"}, {"_id": 0}))
    body = {"scenario": "welcome", "name": "Bienvenue au nouveau client", "status": "active", "trigger": {},
            "message": {"title": "Bienvenue chez {nom_commerce} 👋", "body": "Merci {prénom} ! {offre} vous attend : {lien}",
                        "button": {"enabled": True, "label": "Voir ma carte", "link_type": "card"}},
            "targeting": {"mode": "all"},
            "schedule": {"days": "all", "window": False}}
    r = http("PUT", f"/api/owner/automations/{wel['id']}", json=body)
    check("the editor's Bienvenue is saved: immediate, every day", r.status_code == 200
          and r.json()["schedule_text"] == "Tous les jours · immédiat")
    check("its trigger reads « Après l'ajout de la carte dans Wallet »",
          r.json()["trigger_text"] == "Après l'ajout de la carte dans Wallet")
    page = http("GET", "/api/owner/automations").json()
    meta = next(x for x in page["scenarios"] if x["key"] == "welcome")
    check("the scenario says Wallet, and offers {offre} and {lien}",
          "Wallet" in meta["trigger_label"] and {"offre", "lien"} <= set(meta["variables"]))

    print("\n1. L'inscription seule n'envoie rien")
    pushed.clear()
    r = http("POST", "/api/join/cafe", headers={}, json={"name": "Dina Sow", "phone": "0611111111", "postal_code": "37000",
                                                         "birthday": "02/03/1995", "consent": True})
    dina = db.customers.find_one({"barcode_id": r.json().get("barcode_id")}, {"_id": 0}) or {}
    check(f"signed up ({r.status_code}): no welcome yet", r.status_code == 200 and dina and not pushed)

    print("\n2. Apple Wallet")

    def reg(serial, dev, auth_ok=True):
        h = {"Authorization": "ApplePass " + (WP._auth_token(serial) if auth_ok else "x" * 40)}
        return http("POST", f"/api/passes/v1/devices/{dev}/registrations/pass.x/{serial}", headers=h, json={"pushToken": "t"})
    r = reg(dina["barcode_id"], "iphone", auth_ok=False)
    check("a forged registration is refused and sends nothing", r.status_code == 401 and not pushed)
    r = reg(dina["barcode_id"], "iphone")
    mine = [p for p in pushed if p["cid"] == dina["id"]]
    check(f"the card added to Apple Wallet: the welcome goes at once ({r.status_code})",
          r.status_code == 201 and len(mine) == 1 and mine[0]["title"] == "Bienvenue chez Café Lumière 👋")
    check("{prénom}, {offre} and {lien} are filled",
          mine[0]["body"].startswith("Merci Dina !") and "Café offert" in mine[0]["body"] and dina["barcode_id"] in mine[0]["body"])
    check("its tap goes through the counted link", (mine[0]["url"] or "").startswith(AU.public_base() + "/api/auto/c/"))
    log = db.automation_log.find_one({"customer_id": dina["id"], "scenario": "welcome"})
    check("it is logged as a Bienvenue", log and log["automation_id"] == wel["id"])
    check("the same phone registering again: 200, nothing more", reg(dina["barcode_id"], "iphone").status_code == 200
          and len([p for p in pushed if p["cid"] == dina["id"]]) == 1)
    reg(dina["barcode_id"], "ipad")
    check("a second phone: nothing more", len([p for p in pushed if p["cid"] == dina["id"]]) == 1)
    db.pass_registrations.delete_many({"serial": dina["barcode_id"]})
    reg(dina["barcode_id"], "iphone")
    check("removed then added again: nothing more", len([p for p in pushed if p["cid"] == dina["id"]]) == 1)

    print("\n3. Google Wallet")

    def gcb(event, serial, nonce):
        oid = f"{ISSUER}.{serial.replace('-', '_')}"
        return http("POST", "/api/passes/google/callback", headers={},
                    json={"eventType": event, "objectId": oid, "nonce": nonce, "classId": f"{ISSUER}.c"})
    eva = person("eva", "Eva Petit")
    pushed.clear()
    r = gcb("del", eva["barcode_id"], "n1")
    check("a Google removal sends nothing", r.status_code == 200 and not pushed)
    r = gcb("save", eva["barcode_id"], "n2")
    check(f"saved to Google Wallet: the welcome goes ({r.status_code})", r.status_code == 200
          and [p["cid"] for p in pushed] == ["eva"])
    gcb("save", eva["barcode_id"], "n2")
    check("Google delivering the same callback twice: once", len(pushed) == 1)
    gcb("save", eva["barcode_id"], "n3")
    check("saved again later: nothing more", len(pushed) == 1)
    reg(eva["barcode_id"], "iphone-eva")
    check("then added to Apple Wallet too: nothing more (once per client)", len(pushed) == 1)
    r = gcb("save", "FT-NOBODY", "n4")
    check("an unknown pass is ignored", r.status_code == 200 and len(pushed) == 1)

    print("\n4. Les cas qui ne doivent rien envoyer")
    pushed.clear()
    http("POST", f"/api/owner/automations/{wel['id']}/status", json={"status": "paused"})
    paul = person("paul", "Paul Martin")
    reg(paul["barcode_id"], "iphone-paul")
    check("Bienvenue paused: nothing", not pushed)
    http("POST", f"/api/owner/automations/{wel['id']}/status", json={"status": "active"})
    gone = person("gone", "Ancien Client", deleted_at=now)
    reg(gone["barcode_id"], "iphone-gone")
    check("a deleted client: nothing", not pushed)
    rival = person("riv", "Rival Client", tid="t2")
    rw = next(r for r in db.automations.find({"tenant_id": "t2", "scenario": "welcome"}, {"_id": 0}))
    db.automations.update_one({"id": rw["id"]}, {"$set": {"status": "active", "schedule.window": False,
                                                           "message.title": "Bienvenue chez Rival"}})
    reg(rival["barcode_id"], "iphone-riv")
    check("another shop's client gets THAT shop's welcome, not ours",
          [p["title"] for p in pushed] == ["Bienvenue chez Rival"])
    check("…and our automation logged nothing for them",
          not db.automation_log.find_one({"automation_id": wel["id"], "customer_id": "riv"}))
    pushed.clear()
    check("a call without the Wallet event (the old signup path) sends nothing",
          AU.fire("welcome", "t1", person("old", "Ancien Chemin")) == [] and not pushed)

    print("\n5. Envoyé à toute heure")
    pushed.clear()
    night = person("nuit", "Noé Nuit")
    late = dt.datetime(2026, 10, 14, 21, 30, tzinfo=UTC)           # 23:30 Paris
    out = AU.fire("welcome", "t1", night, {"event": "wallet", "wallet": "apple"}, at=late)
    check("a card added at 23:30 gets its welcome at once (no plage in the editor)",
          out and not out[0].get("queued") and [p["cid"] for p in pushed] == ["nuit"])
    # an older Bienvenue with a plage still waits for it (kept as it was saved)
    db.automations.update_one({"id": wel["id"]}, {"$set": {"schedule.window": True, "schedule.window_from": "09:00",
                                                            "schedule.window_to": "21:00"}})
    pushed.clear()
    out = AU.fire("welcome", "t1", person("nuit2", "Nina Nuit"), {"event": "wallet"}, at=late)
    check("…an older one with a plage horaire waits for 09:00", out and out[0].get("queued") and not pushed)

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
