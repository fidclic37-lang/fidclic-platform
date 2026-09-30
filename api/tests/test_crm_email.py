"""
CRM › Séquences & Modèles d'emails — templates, sequences, enrolment rules,
sending through (fake) Gmail, the daily limit, opens / clicks, unsubscribe,
replies read over (fake) IMAP, and the figures.

Run: cd api && /usr/local/bin/python3 tests/test_crm_email.py
"""
import datetime as dt
import os
import smtplib
import sys
from urllib.parse import parse_qs, urlparse

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"
for k in ("CRM_SMTP_USER", "CRM_SMTP_PASS", "CRM_DAILY_LIMIT"):
    os.environ.pop(k, None)

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from fastapi import HTTPException
    from models import TokenData
    from features import crm as C
    from features import crm_email as E

    db = server.db
    C.init(db)
    E.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def refused(fn, code):
        try:
            fn(); return False
        except HTTPException as e:
            return e.status_code == code

    OUTBOX = []

    class FakeSMTP:
        fail_login = False

        def send_message(self, msg):
            OUTBOX.append(msg)

        def quit(self):
            pass

    def fake_open(cfg):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        return FakeSMTP()
    E._open_smtp = fake_open

    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    SOFIA = TokenData(email="sofia@fidclic.com", role="commercial", tenant_id=None)
    now = dt.datetime.now(dt.timezone.utc)
    db.users.insert_many([{"email": "boss@fidclic.com", "role": "super_admin", "first_name": "Meriem", "last_name": "B."},
                          {"email": "sofia@fidclic.com", "role": "commercial", "first_name": "Sofia", "last_name": "R."}])
    db.platform_settings.insert_one({"key": "invoice_issuer", "value": {"legal_name": "FidClic SAS", "address": "1 rue X",
                                                                        "postal_code": "37000", "city": "Tours"}})
    mk = lambda **kw: C.create(kw, "boss@fidclic.com")        # noqa: E731
    zinc = mk(name="Le Petit Zinc", email="zinc@ex.fr", contact_name="Thomas Durand", city="Tours", sector="Restaurant")
    paul = mk(name="Boulangerie Paul", email="paul@ex.fr", city="Tours", sector="Restaurant")
    nomail = mk(name="Sans Mail", city="Tours", sector="Restaurant")
    gone = mk(name="Parti", email="parti@ex.fr", city="Tours", sector="Restaurant")
    lost = mk(name="Perdu SARL", email="perdu@ex.fr", city="Tours", sector="Restaurant")
    client = mk(name="Déjà Client", email="client@ex.fr", city="Tours", sector="Restaurant")
    other = mk(name="Ailleurs", email="ailleurs@ex.fr", city="Blois", sector="Café")
    db.crm_prospects.update_one({"id": gone["id"]}, {"$set": {"email_opt_out": True}})
    db.crm_prospects.update_one({"id": lost["id"]}, {"$set": {"stage": "perdu"}})
    db.crm_prospects.update_one({"id": client["id"]}, {"$set": {"stage": "signe"}})

    print("\nParis time")
    t = dt.datetime(2026, 7, 1, 7, 0, tzinfo=dt.timezone.utc)
    check("summer: 07:00 UTC is 09:00 in Paris", E._local(t).hour == 9 and E._utc(E._local(t)) == t)
    w = dt.datetime(2026, 12, 1, 8, 0, tzinfo=dt.timezone.utc)
    check("winter: 08:00 UTC is 09:00 in Paris", E._local(w).hour == 9 and E._at(E._local(w), "09:00") == w)

    print("\nTemplates")
    tl = E.list_templates(token_data=ADMIN)
    check("five ready-made templates", len(tl["rows"]) == 5)
    check("the case-study one is flagged « to complete »", next(r for r in tl["rows"] if r["id"] == "tpl-cas")["unfinished"])
    check("unknown variable refused", refused(lambda: E.add_template(E.TemplateIn(name="x", subject="Hi {nom_du_chien}", body="b"),
                                                                     token_data=SOFIA), 400))
    mine = E.add_template(E.TemplateIn(name="Mon modèle", category="Relance", subject="Bonjour {commerce}", body="Salut {prenom}"),
                          token_data=SOFIA)
    check("a commercial cannot edit FidClic's templates",
          refused(lambda: E.edit_template("tpl-intro", E.TemplateIn(name="x"), token_data=SOFIA), 403))
    E.edit_template(mine["id"], E.TemplateIn(subject="Bonjour {commerce} !"), token_data=SOFIA)
    check("…but can edit their own", db.crm_email_templates.find_one({"id": mine["id"]})["subject"] == "Bonjour {commerce} !")

    print("\nRendering")
    r = E.render("Pour {commerce}", "Bonjour {prenom},\n\nVoir https://fidclic.com/demo?a=1&b=2\n\n{expediteur}", C._db.crm_prospects.find_one({"id": zinc["id"]}), "Meriem B.", "sid123")
    check("variables filled", r["subject"] == "Pour Le Petit Zinc" and "Bonjour Thomas," in r["text"] and "Meriem B." in r["text"])
    r2 = E.render("x", "Bonjour {prenom},", C._db.crm_prospects.find_one({"id": paul["id"]}), "M", "s")
    check("no contact name → « Bonjour, »", r2["text"].startswith("Bonjour,"))
    href = next(a for a in r["html"].split('href="')[1:] if "/api/crm/t/c/" in a).split('"')[0].replace("&amp;", "&")
    qs = parse_qs(urlparse(href).query)
    check("links go through the click counter", qs["u"][0] == "https://fidclic.com/demo?a=1&b=2")
    check("legal name, address and unsubscribe in every mail",
          "FidClic SAS — 1 rue X, 37000 Tours" in r["html"] and "/api/crm/u/sid123" in r["html"] and "/api/crm/u/sid123" in r["text"])

    print("\nSequences")
    seq = E.add_sequence(E.SequenceIn(preset="prise-de-contact", sector="Restaurant", target="Restaurants à Tours"), token_data=ADMIN)
    check("created from a preset: 5 steps, draft", seq["steps_count"] == 5 and seq["status"] == "brouillon")
    check("activation refused while a step still has [À COMPLÉTER]",
          refused(lambda: E.sequence_status(seq["id"], E.StatusIn(status="active"), token_data=ADMIN), 400))
    steps = [E.StepIn(**{k: v for k, v in s.items() if k in ("id", "day", "time", "subject", "body", "template_id")})
             for s in seq["steps"]]
    steps[2].subject, steps[2].body = "Un exemple près de chez vous", "Bonjour {prenom},\n\nUn vrai exemple.\n\n{expediteur}"
    check("bad time refused", refused(lambda: E.edit_sequence(seq["id"], E.SequenceIn(steps=[E.StepIn(day=1, time="25:00",
                                                                                               subject="a", body="b")]), token_data=ADMIN), 400))
    E.edit_sequence(seq["id"], E.SequenceIn(steps=steps), token_data=ADMIN)
    check("a commercial cannot touch someone else's sequence",
          refused(lambda: E.sequence_status(seq["id"], E.StatusIn(status="active"), token_data=SOFIA), 403))
    E.sequence_status(seq["id"], E.StatusIn(status="active"), token_data=ADMIN)
    check("activated once complete", db.crm_sequences.find_one({"id": seq["id"]})["status"] == "active")
    seq2 = E.add_sequence(E.SequenceIn(name="Cafés", steps=[E.StepIn(day=1, subject="Bonjour", body="Hello {commerce}")]), token_data=SOFIA)
    E.sequence_status(seq2["id"], E.StatusIn(status="active"), token_data=SOFIA)
    E.enroll(seq2["id"], E.EnrollIn(prospect_ids=[other["id"]]), token_data=SOFIA)

    print("\nEnrolment")
    check("a filter or a choice is required", refused(lambda: E.enroll(seq["id"], E.EnrollIn(), token_data=ADMIN), 400))
    E.enroll(seq2["id"], E.EnrollIn(prospect_ids=[paul["id"]]), token_data=SOFIA)       # busy elsewhere
    dry = E.enroll(seq["id"], E.EnrollIn(sector="Restaurant", dry_run=True), token_data=ADMIN)
    check("dry run counts who would be added and why others are not",
          dry == {"added": 1, "no_email": 1, "opted_out": 1, "clients": 1, "lost": 1, "already": 0, "other_sequence": 1})
    check("dry run writes nothing", db.crm_enrollments.count_documents({"sequence_id": seq["id"]}) == 0)
    E.enroll(seq["id"], E.EnrollIn(sector="Restaurant"), token_data=ADMIN)
    check("enrolled", db.crm_enrollments.count_documents({"sequence_id": seq["id"]}) == 1)
    check("never twice in the same sequence", E.enroll(seq["id"], E.EnrollIn(prospect_ids=[zinc["id"]]), token_data=ADMIN)["already"] == 1)

    print("\nSending")
    check("without Gmail nothing leaves", E.run_due()["reason"] == "not_configured")
    check("status says Gmail is not connected", E.email_status(token_data=ADMIN)["configured"] is False)
    os.environ["CRM_SMTP_USER"], os.environ["CRM_SMTP_PASS"] = "contact@fidclic.com", "abcd efgh ijkl mnop"
    db.crm_enrollments.update_many({}, {"$set": {"next_at": now - dt.timedelta(minutes=1)}})
    res = E.run_due()
    check("due steps sent (both sequences)", res["sent"] == 3 and len(OUTBOX) == 3)
    m = next(x for x in OUTBOX if x["To"] == "zinc@ex.fr")
    check("from the Gmail account, in the sender's name", "Meriem B. · FidClic" in m["From"] and "contact@fidclic.com" in m["From"])
    check("one-click unsubscribe header", m["List-Unsubscribe"].startswith("<https://") and m["List-Unsubscribe-Post"])
    check("subject personalised", m["Subject"] == "Le Petit Zinc : fidélisez vos clients avec une carte 100 % digitale")
    e = db.crm_enrollments.find_one({"sequence_id": seq["id"], "prospect_id": zinc["id"]})
    nxt = E._local(C._aware(e["next_at"]))
    check("next step: day 3 at 10:00 Paris", e["step"] == 1 and nxt.strftime("%H:%M") == "10:00"
          and (nxt.date() - E._local(now).date()).days == 2)
    check("in the prospect's history", db.crm_activities.find_one({"prospect_id": zinc["id"], "type": "email"}) is not None)
    check("nothing more is due", E.run_due()["sent"] == 0)

    print("\nOpens, clicks, unsubscribe")
    send = db.crm_email_sends.find_one({"to": "zinc@ex.fr"})
    E.track_open(send["id"]); E.track_open(send["id"])
    s1 = db.crm_email_sends.find_one({"id": send["id"]})
    check("opens counted, first open dated", s1["opens"] == 2 and s1["opened_at"])
    check("a tampered link is refused", refused(lambda: E.track_click(send["id"], u="https://evil.example", s="x"), 400))
    url = "https://fidclic.com/demo"
    rr = E.track_click(send["id"], u=url, s=E._sig(send["id"], url))
    check("a good link redirects and counts", rr.status_code == 302 and db.crm_email_sends.find_one({"id": send["id"]})["clicks"] == 1)
    ps = db.crm_email_sends.find_one({"to": "ailleurs@ex.fr"})
    check("the unsubscribe page asks to confirm", b"Confirmer" in E.unsubscribe_page(ps["id"]).body)
    E.unsubscribe(ps["id"])
    check("unsubscribed: flagged and stopped", db.crm_prospects.find_one({"id": other["id"]})["email_opt_out"]
          and db.crm_enrollments.count_documents({"prospect_id": other["id"], "status": "en_cours"}) == 0
          and db.crm_activities.find_one({"prospect_id": other["id"], "type": "unsubscribe"}))
    check("never mailed again", refused(lambda: E.email_send(E.SendIn(prospect_id=other["id"], subject="a", body="b"), token_data=ADMIN), 409))

    print("\nReplies")
    check("an auto-reply is not a reply", E.match_reply({"from": "zinc@ex.fr", "subject": "Réponse automatique : absent",
                                                         "auto-submitted": "auto-replied"}) is None)
    check("matched by In-Reply-To", E.match_reply({"from": "someone@else.fr", "in-reply-to": send["message_id"]})["id"] == send["id"])
    check("matched by sender address", E.match_reply({"from": "Thomas <ZINC@ex.fr>", "subject": "Re: ok"})["id"] == send["id"])
    check("a stranger is ignored", E.match_reply({"from": "nobody@x.fr", "subject": "hello"}) is None)

    class FakeIMAP:
        def __init__(self, msgs): self.msgs = msgs
        def select(self, box, readonly=False): return ("OK", [b"1"])
        def search(self, *_): return ("OK", [b" ".join(str(i + 1).encode() for i in range(len(self.msgs)))])
        def fetch(self, ids, what): return ("OK", [(b"x", self.msgs[int(i) - 1].encode()) for i in ids.split(",")])
        def logout(self): pass
    reply = (f"From: Thomas <zinc@ex.fr>\r\nSubject: Re: Le Petit Zinc\r\nDate: Mon, 28 Sep 2026 10:00:00 +0200\r\n"
             f"Message-ID: <r1@ex.fr>\r\nIn-Reply-To: {send['message_id']}\r\n\r\n")
    E._open_imap = lambda cfg: FakeIMAP([reply, "From: pub@spam.fr\r\nSubject: Promo\r\nMessage-ID: <p@x>\r\n\r\n"])
    out = E.check_replies(force=True)
    check("one reply found", out["replies"] == 1)
    check("the sequence stops for them", db.crm_enrollments.find_one({"prospect_id": zinc["id"]})["status"] == "repondu")
    check("the prospect moves to « Contacté »", db.crm_prospects.find_one({"id": zinc["id"]})["stage"] == "contacte")
    check("a « Répondre à » task is created", db.crm_tasks.find_one({"title": "Répondre à Le Petit Zinc", "priority": "haute"}) is not None)
    check("read only once", E.check_replies(force=True)["replies"] == 0)

    print("\nLimits and stops")
    mk2 = mk(name="Nouveau Resto", email="nr@ex.fr", city="Tours", sector="Restaurant")
    mk3 = mk(name="Autre Resto", email="ar@ex.fr", city="Tours", sector="Restaurant")
    E.enroll(seq["id"], E.EnrollIn(prospect_ids=[mk2["id"], mk3["id"]]), token_data=ADMIN)
    db.crm_prospects.update_one({"id": mk3["id"]}, {"$set": {"stage": "essai"}})
    db.crm_enrollments.update_many({"status": "en_cours"}, {"$set": {"next_at": now - dt.timedelta(minutes=1)}})
    os.environ["CRM_DAILY_LIMIT"] = "5"
    res = E.run_due()
    check("a prospect who became a client is not mailed", res["sent"] == 1
          and db.crm_enrollments.find_one({"prospect_id": mk3["id"]})["stopped_reason"] == "Devenu client")
    mk4 = mk(name="Encore Un", email="eu@ex.fr", city="Tours", sector="Restaurant")
    E.enroll(seq["id"], E.EnrollIn(prospect_ids=[mk4["id"]]), token_data=ADMIN)
    db.crm_enrollments.update_many({"status": "en_cours"}, {"$set": {"next_at": now - dt.timedelta(minutes=1)}})
    os.environ["CRM_DAILY_LIMIT"] = "4"
    check("the daily limit holds the rest for tomorrow", E.run_due()["reason"] == "daily_limit")
    os.environ["CRM_DAILY_LIMIT"] = "450"
    FakeSMTP.fail_login = True
    E.run_due()
    check("a wrong App password is reported on the page", "mot de passe" in (E.email_status(token_data=ADMIN)["error"] or ""))
    FakeSMTP.fail_login = False
    check("…and cleared once mails leave again", E.run_due()["sent"] >= 1 and not E.email_status(token_data=ADMIN)["error"])

    print("\nOne-off email, figures, housekeeping")
    E.email_send(E.SendIn(prospect_id=paul["id"], subject="Suite à notre appel", body="Bonjour,\n\nComme convenu.", template_id=mine["id"]),
                 token_data=SOFIA)
    check("one-off email sent and logged", OUTBOX[-1]["To"] == "paul@ex.fr"
          and db.crm_activities.find_one({"prospect_id": paul["id"], "text": "Email envoyé : Suite à notre appel"}))
    check("[À COMPLÉTER] can never leave", refused(lambda: E.email_send(E.SendIn(prospect_id=paul["id"], subject="x",
                                                                                 body="[À COMPLÉTER : chiffre]"), token_data=ADMIN), 400))
    sm = E.sequences_summary(token_data=ADMIN)
    cards = {c["key"]: c["value"] for c in sm["cards"]}
    total = db.crm_email_sends.count_documents({"status": "sent"})
    check("cards: active sequences and e-mails sent", cards["active"] == 2 and cards["sent"] == total)
    check("rates from real opens / clicks / replies", cards["open_rate"] == round(1 / total * 100) and cards["reply_rate"] == round(1 / total * 100))
    check("by sector", {x["label"]: x["count"] for x in sm["by_sector"]}.get("Restaurant", 0) >= 3)
    check("popular templates", sm["templates"][0]["id"] == "tpl-intro" and sm["templates"][0]["uses"] >= 3)
    lst = E.list_sequences(token_data=ADMIN)
    ticks = []
    real_tick, E._tick = E._tick, lambda: ticks.append(1)
    E.list_sequences(per_page=3, quiet=True, token_data=ADMIN)
    E._tick = real_tick
    check("the overview reads the list without sending (quiet)", ticks == [])
    check("tab counts", lst["counts"]["all"] == 2 and lst["counts"]["active"] == 2)
    det = E.get_sequence(seq["id"], token_data=ADMIN)
    check("per-step figures", det["steps"][0]["sent"] >= 3 and det["steps"][0]["open_rate"] > 0)
    check("enrolled prospects with their progress", any(x["status"] == "repondu" for x in det["enrollments"]))
    check("a sequence that sent mail cannot be deleted", refused(lambda: E.delete_sequence(seq["id"], token_data=ADMIN), 409))
    dup = E.duplicate_sequence(seq["id"], token_data=SOFIA)
    check("duplicate: a draft owned by whoever copied it", db.crm_sequences.find_one({"id": dup["id"]})["status"] == "brouillon"
          and db.crm_sequences.find_one({"id": dup["id"]})["created_by"] == "sofia@fidclic.com")
    E.sequence_status(seq["id"], E.StatusIn(status="terminee"), token_data=ADMIN)
    check("ending a sequence stops everyone still in it",
          db.crm_enrollments.count_documents({"sequence_id": seq["id"], "status": "en_cours"}) == 0)
    check("an ended sequence is not restarted",
          refused(lambda: E.sequence_status(seq["id"], E.StatusIn(status="active"), token_data=ADMIN), 400))
    E.delete_sequence(dup["id"], token_data=SOFIA)
    check("a draft that never sent can be deleted", not db.crm_sequences.find_one({"id": dup["id"]}))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
