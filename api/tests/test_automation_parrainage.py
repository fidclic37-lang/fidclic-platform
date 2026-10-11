"""
Parrainage — from the user's mockups (2026-10-11): ONE automation with both
messages (Parrain / Filleul tabs), sent when the referral points are credited,
each side switchable, the Résumé editing the programme's rules (synced with the
Parrainage page, owner only), nothing sent while the programme is off.

Edge cases: the older two rows merged (words, on/off and sends kept), a side
switched off, both off, the « Prénom de l'ami » chip on each side, the new
chips ({récompense}, {lien}, {amis_parraines} = validated friends only), a
friend paid on every visit, a filleul message left empty while its side is
off, the errors naming the side, a manager / administrateur, another shop.

Run: cd api && /usr/local/bin/python3 tests/test_automation_parrainage.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-automation-parrainage")
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
    import features.referrals as R
    import features.wallet_passes as WP
    import features.push_subscriptions as PS
    from features import automations as AU

    db = server.db
    R._db = db
    pushed = []

    def fake_dispatch(tid, cust, title, body, kind="campaign", url=None):
        pushed.append({"cid": cust.get("id"), "title": title, "body": body, "kind": kind, "url": url})
        return {"sent": True, "channel": "push"}
    server.dispatch_to_customer = fake_dispatch
    WP.notify_customer = lambda cid, message=None, google_notify=None: {}
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    PS.fan_out_to_customer = lambda tid, cid, title, body, url=None: pushed.append(
        {"cid": cid, "title": title, "body": body, "kind": "parrainage", "url": url}) or {"sent": 1}
    import services.sms as SMS
    SMS.send_sms = lambda *a, **k: {"sent": True}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else H, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_many([
        {"id": t, "slug": s, "name": n, "plan": "vip", "subscription_status": "active", "is_active": True}
        for t, s, n in (("t1", "cafe", "Café Lumière"), ("t2", "rival", "Rival"), ("t3", "ancien", "Ancien Café"),
                        ("t4", "pause", "Café Pause"), ("t5", "seul", "Café Seul"))])
    for e, role, t in (("o@x.fr", "business_owner", "t1"), ("m@x.fr", "manager", "t1"), ("a@x.fr", "administrateur", "t1"),
                       ("r@x.fr", "business_owner", "t2"), ("o3@x.fr", "business_owner", "t3"),
                       ("o4@x.fr", "business_owner", "t4"), ("o5@x.fr", "business_owner", "t5")):
        db.users.insert_one({"email": e, "role": role, "tenant_id": t})
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    H = tok("o@x.fr", "business_owner")
    HM, HA, H2 = tok("m@x.fr", "manager"), tok("a@x.fr", "administrateur"), tok("r@x.fr", "business_owner", "t2")

    print("1. Les deux anciennes automatisations deviennent une seule")

    def legacy(tid, side, status, title, body, name):
        row = AU.new_doc(tid, "referral", name=name, status=status, trigger={"side": side},
                         message={"title": title, "body": body})
        row["trigger"] = {"side": side}
        row.pop("message_filleul", None)
        db.automations.insert_one(row)
        return row
    p3 = legacy("t3", "parrain", "active", "Bravo !", "Votre ami {filleul} est venu.", "Parrainage — parrain")
    f3 = legacy("t3", "filleul", "paused", "Bienvenue", "Merci grâce à {parrain}.", "Parrainage — filleul")
    db.automation_log.insert_one({"automation_id": f3["id"], "tenant_id": "t3", "customer_id": "x", "scenario": "referral",
                                  "sent_at": now})
    db.automation_queue.insert_one({"automation_id": f3["id"], "tenant_id": "t3", "customer_id": "y", "due_at": now})
    H3 = tok("o3@x.fr", "business_owner", "t3")
    rows = [r for r in http("GET", "/api/owner/automations", headers=H3).json()["rows"] if r["scenario"] == "referral"]
    check("one Parrainage row instead of two", len(rows) == 1 and rows[0]["id"] == p3["id"] and rows[0]["name"] == "Parrainage")
    m = rows[0]
    check("the parrain keeps its words", m["message"]["title"] == "Bravo !" and m["message"]["body"] == "Votre ami {filleul} est venu.")
    check("the filleul keeps its words", m["message_filleul"]["title"] == "Bienvenue" and "{parrain}" in m["message_filleul"]["body"])
    check("only the side that was on stays on (parrain on, filleul paused)", m["trigger"]["sides"] == ["parrain"]
          and m["status"] == "active")
    check("the filleul's sends and waiting ones now count under the merged row",
          db.automation_log.find_one({"customer_id": "x"})["automation_id"] == p3["id"]
          and db.automation_queue.find_one({"customer_id": "y"})["automation_id"] == p3["id"])
    check("the filleul row is gone", not db.automations.find_one({"id": f3["id"]}))
    again = [r for r in http("GET", "/api/owner/automations", headers=H3).json()["rows"] if r["scenario"] == "referral"]
    check("opening the page again changes nothing", again == rows)

    legacy("t4", "parrain", "paused", "P", "Parrain texte", "Parrainage — parrain")
    legacy("t4", "filleul", "paused", "F", "Filleul texte", "Parrainage — filleul")
    r4 = [r for r in http("GET", "/api/owner/automations", headers=tok("o4@x.fr", "business_owner", "t4")).json()["rows"]
          if r["scenario"] == "referral"]
    check("both were paused: one row, paused, both messages ready", len(r4) == 1 and r4[0]["status"] == "paused"
          and r4[0]["trigger"]["sides"] == ["parrain", "filleul"] and r4[0]["message_filleul"]["body"] == "Filleul texte")

    legacy("t5", "filleul", "paused", "F seul", "Le filleul seul", "Parrainage — filleul")
    r5 = [r for r in http("GET", "/api/owner/automations", headers=tok("o5@x.fr", "business_owner", "t5")).json()["rows"]
          if r["scenario"] == "referral"]
    check("a lone filleul row keeps its side (not emptied) and its words in the filleul tab",
          len(r5) == 1 and r5[0]["trigger"]["sides"] == ["filleul"] and r5[0]["message_filleul"]["body"] == "Le filleul seul")

    print("\n2. Une nouvelle boutique : une seule automatisation, les textes du mockup")
    page = http("GET", "/api/owner/automations").json()
    ref = [r for r in page["rows"] if r["scenario"] == "referral"]
    check("one row named Parrainage, both sides", len(ref) == 1 and ref[0]["name"] == "Parrainage"
          and ref[0]["trigger"]["sides"] == ["parrain", "filleul"])
    check("paused while the programme is off", ref[0]["status"] == "paused")
    check("parrain: the mockup's words", ref[0]["message"]["title"] == "Merci pour votre parrainage ! 🎁")
    check("filleul: the mockup's words", ref[0]["message_filleul"]["title"] == "Bienvenue et merci ! 🎉")
    check("the trigger reads like the mockup", "Un client parraine un ami" in ref[0]["trigger_text"])
    meta = next(x for x in page["scenarios"] if x["key"] == "referral")
    check("the chips: récompense, lien, amis parrainés and both names",
          {"récompense", "lien", "amis_parraines", "filleul", "parrain"} <= set(meta["variables"]))
    check("the editor gets the programme's rules, editable by the owner",
          page["referral"]["enabled"] is False and page["referral"]["referrer_reward_points"] == 50
          and page["referral"]["can_edit"] is True)
    check("a manager sees them read-only", http("GET", "/api/owner/automations", headers=HM).json()["referral"]["can_edit"] is False)
    aid = ref[0]["id"]

    print("\n3. Enregistrer depuis l'éditeur")

    def body(**over):
        b = {"scenario": "referral", "name": "Parrainage", "status": "active", "trigger": {"sides": ["parrain", "filleul"]},
             "message": {"title": "Merci {prénom} !", "body": "{filleul} est venu : +{récompense}. {amis_parraines} amis. {lien}"},
             "message_filleul": {"title": "Bienvenue {prénom}", "body": "Grâce à {parrain} : +{récompense} chez {nom_commerce}.",
                                 "button": {"enabled": True, "label": "Voir mes points", "link_type": "card"}},
             "targeting": {"mode": "all"}, "schedule": {"days": "all", "window": False}}
        b.update(over)
        return b
    r = http("PUT", f"/api/owner/automations/{aid}", json=body())
    check(f"both messages saved ({r.status_code})", r.status_code == 200 and r.json()["message_filleul"]["button"]["enabled"])
    r = http("PUT", f"/api/owner/automations/{aid}", json=body(message_filleul={"title": "", "body": ""}))
    check("the filleul's text is required while its side is on", r.status_code == 400 and "Filleul" in r.text)
    r = http("PUT", f"/api/owner/automations/{aid}", json=body(message={"title": "", "body": ""}))
    check("…and the parrain's, the error naming the parrain", r.status_code == 400 and "Parrain" in r.text)
    r = http("PUT", f"/api/owner/automations/{aid}", json=body(trigger={"sides": ["parrain"]}, message_filleul={"title": "", "body": ""}))
    check("a side switched off may stay empty", r.status_code == 200 and r.json()["trigger"]["sides"] == ["parrain"])
    r = http("PUT", f"/api/owner/automations/{aid}", json=body(trigger={"sides": []}))
    check("both sides off is refused (send at least one message)", r.status_code == 400)
    r = http("PUT", f"/api/owner/automations/{aid}", json=body(trigger={"sides": ["parrain", "voisin"]}))
    check("an unknown side is refused", r.status_code == 400)
    r = http("PUT", f"/api/owner/automations/{aid}", json=body(message_filleul={"title": "x" * 81, "body": "ok"}))
    check("the filleul's title limit (80) holds", r.status_code == 400 and "Filleul" in r.text)
    r = http("PUT", f"/api/owner/automations/{aid}", json=body(message_filleul={"title": "ok", "body": "ok",
                                                                                 "button": {"enabled": True, "label": "", "link_type": "card"}}))
    check("a filleul button without its text is refused", r.status_code == 400)
    r = http("PUT", f"/api/owner/automations/{aid}", json=body(), headers=HA)
    check("an administrateur may save the automation", r.status_code == 200)
    r = http("PUT", f"/api/owner/automations/{aid}", json=body(), headers=HM)
    check("a manager may not", r.status_code == 403)
    r = http("PUT", f"/api/owner/automations/{aid}", json=body(), headers=H2)
    check("another shop cannot touch it", r.status_code in (403, 404))
    http("PUT", f"/api/owner/automations/{aid}", json=body())

    print("\n4. Récompenses : les mêmes règles que la page Parrainage")
    full = http("GET", "/api/owner/referrals/config").json()
    r = http("PUT", "/api/owner/referrals/config", json={**full, "referrer_reward_points": 60, "referee_reward_points": 30})
    check("the editor's merged save keeps the other rules", r.status_code == 200 and r.json()["minimum_visits_to_earn"] == 1)
    rp = http("GET", "/api/owner/automations").json()["referral"]
    check("…and the editor reads them back", rp["referrer_reward_points"] == 60 and rp["referee_reward_points"] == 30)
    check("an administrateur cannot change the rewards", http("PUT", "/api/owner/referrals/config", headers=HA,
                                                              json={**full, "referrer_reward_points": 1}).status_code == 403)
    r = http("PUT", "/api/owner/referrals/config", json={**full, "referrer_reward_points": 60, "referee_reward_points": 30,
                                                         "reward_mode": "bizarre"})
    check("an unknown crediting mode is refused", r.status_code == 400)
    check("another shop's rules are untouched", http("GET", "/api/owner/automations", headers=H2).json()["referral"]
          ["referrer_reward_points"] == 50)

    print("\n5. Programme désactivé : rien ne part")

    def join(name, phone, parrain=None):
        b = {"name": name, "phone": phone, "email": "", "postal_code": "37000", "birthday": "1990-01-02", "consent": True}
        if parrain:
            b["parrain_barcode"] = parrain
        return http("POST", "/api/join/cafe", headers={}, json=b).json()

    def scan(bc):
        return http("POST", "/api/owner/scan", json={"barcode_id": bc, "amount_paid": 10})

    cust = lambda bc: db.customers.find_one({"barcode_id": bc}, {"_id": 0})  # noqa: E731
    lucas = join("Lucas Martin", "0611111111")["barcode_id"]
    pushed.clear()
    off = join("Zoé Off", "0699999999", parrain=lucas)
    if off.get("barcode_id"):
        scan(off["barcode_id"])
    check("programme off: no points, no message", not [p for p in pushed if p["kind"] == "parrainage"]
          and (cust(lucas)["points"] or 0) == 0)

    print("\n6. Points crédités : chacun reçoit son message")
    full = http("GET", "/api/owner/referrals/config").json()
    http("PUT", "/api/owner/referrals/config", json={**full, "enabled": True})
    pushed.clear()
    marie = join("Marie Dupont", "0622222222", parrain=lucas)["barcode_id"]
    check("signing up alone sends nothing yet", not [p for p in pushed if p["kind"] == "parrainage"])
    scan(marie)
    who = {p["cid"]: p for p in pushed if p["kind"] == "parrainage"}
    lp, mp = who.get(cust(lucas)["id"], {}), who.get(cust(marie)["id"], {})
    check("the parrain gets the parrain's message", lp.get("title") == "Merci Lucas !")
    check("{filleul} = the friend's first name, {récompense} = his points",
          lp.get("body", "").startswith("Marie est venu : +60 points."))
    check("{amis_parraines} counts the validated friends (Zoé never validated)", "1 amis." in lp.get("body", ""))
    check("{lien} is his own card link", cust(lucas)["barcode_id"] in lp.get("body", ""))
    check("the filleul gets the filleul's message, naming the parrain",
          mp.get("title") == "Bienvenue Marie" and mp.get("body") == "Grâce à Lucas : +30 points chez Café Lumière.")
    news = cust(lucas)["points_news"]
    check("on Apple Wallet it rides on the points banner", "Vous avez maintenant %@ points." in news["text"]
          and cust(lucas)["auto_news"]["pass"] is False)
    check("the filleul's button is on its card", cust(marie)["auto_news"].get("label") == "Voir mes points")
    log = list(db.automation_log.find({"automation_id": aid}))
    check("both sends are logged under the one automation", len(log) == 2)

    print("\n7. Un seul côté")
    http("PUT", f"/api/owner/automations/{aid}", json=body(trigger={"sides": ["filleul"]}))
    pushed.clear()
    sami = join("Sami Ben", "0633333333", parrain=lucas)["barcode_id"]
    scan(sami)
    who = {p["cid"] for p in pushed if p["kind"] == "parrainage"}
    check("parrain switched off: only the filleul hears", who == {cust(sami)["id"]})
    check("…yet the parrain still gets his points", cust(lucas)["points"] >= 120)
    http("PUT", f"/api/owner/automations/{aid}", json=body(trigger={"sides": ["parrain"]}))
    pushed.clear()
    lina = join("Lina Roy", "0644444444", parrain=lucas)["barcode_id"]
    scan(lina)
    lb = [p for p in pushed if p["kind"] == "parrainage"]
    check("filleul switched off: only the parrain hears, now 3 validated friends",
          [p["cid"] for p in lb] == [cust(lucas)["id"]] and "3 amis." in lb[0]["body"])
    http("POST", f"/api/owner/automations/{aid}/status", json={"status": "paused"})
    pushed.clear()
    nora = join("Nora Lee", "0655555555", parrain=lucas)["barcode_id"]
    scan(nora)
    check("automation paused: nobody hears, the points still land",
          not [p for p in pushed if p["kind"] == "parrainage"] and cust(nora)["points"] >= 30)
    http("POST", f"/api/owner/automations/{aid}/status", json={"status": "active"})

    print("\n8. Crédité à chaque visite")
    http("PUT", f"/api/owner/automations/{aid}", json=body())
    full = http("GET", "/api/owner/referrals/config").json()
    http("PUT", "/api/owner/referrals/config", json={**full, "reward_mode": "first_then", "referrer_reward_points_next": 5,
                                                     "referee_reward_points_next": 2})
    db.automations.update_one({"id": aid}, {"$set": {"message.body": "{filleul} {visite_ami} : +{récompense}"}})
    pushed.clear()
    tom = join("Tom Vidal", "0666666666", parrain=lucas)["barcode_id"]
    scan(tom)
    db.visits.update_many({}, {"$set": {"created_at": now - dt.timedelta(days=1)}})
    db.scans.update_many({}, {"$set": {"created_at": now - dt.timedelta(days=1)}}) if "scans" in db.list_collection_names() else None
    scan(tom)
    lb = [p["body"] for p in pushed if p["kind"] == "parrainage" and p["cid"] == cust(lucas)["id"]]
    check(f"first visit then each next one: the parrain hears both ({len(lb)})",
          len(lb) >= 2 and lb[0] == "Tom est venu : +60 points" and lb[-1] == "Tom est revenu : +5 points")

    print("\n9. Une autre boutique")
    rival_ref = [r for r in http("GET", "/api/owner/automations", headers=H2).json()["rows"] if r["scenario"] == "referral"]
    check("the rival has its own single row, untouched by ours", len(rival_ref) == 1 and rival_ref[0]["id"] != aid
          and rival_ref[0]["message"]["title"] == "Merci pour votre parrainage ! 🎁")
    check("our sends never land in its log", not db.automation_log.find_one({"automation_id": rival_ref[0]["id"]}))

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
