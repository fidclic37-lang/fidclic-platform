"""
La mémoire du Copilote (user, 2026-10-30): the chat remembers as much as it
can — every message is kept for good; each question carries the recent
conversation in full (a size budget, never « the last 10 »), a summary of
the older one and « Ce que FidClic IA retient », the facts the account told
it. Each account has its own memory, on every plan. The owner sees, edits
and deletes those facts. Phone numbers and e-mails never reach the model.

Run: cd api && /usr/local/bin/python3 tests/test_copilot_memory.py
"""
import asyncio
import contextlib
import datetime as dt
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-copilot-memory")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
UTC = dt.timezone.utc


def check(label, cond, show=None):
    global passed, failed
    cond = bool(cond)
    if not cond and show is not None:
        print("    →", show)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx
    from features import copilot as K
    from features import copilot_memory as CM
    from services import llm

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    clock = {"t": dt.datetime(2026, 10, 30, 9, tzinfo=UTC)}

    def tick_clock():
        clock["t"] += dt.timedelta(seconds=30)
        return clock["t"]
    K._now = tick_clock
    CM.NOW = lambda: clock["t"]

    for tid, plan in (("t1", "vip"), ("t2", "vip"), ("st", "starter")):
        db.tenants.insert_one({"id": tid, "slug": tid, "name": f"Shop {tid}", "sector": "salon", "activity_key": "barbier",
                               "plan": plan, "is_active": True, "subscription_status": "active"})
    users = (("o@t1.fr", "business_owner", "t1"), ("m@t1.fr", "manager", "t1"), ("s@t1.fr", "staff", "t1"),
             ("o@t2.fr", "business_owner", "t2"), ("o@st.fr", "business_owner", "st"))
    H = {}
    for email, role, tid in users:
        db.users.insert_one({"email": email, "role": role, "tenant_id": tid, "active": True, "name": email})
        H[email] = {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": role, "tenant_id": tid})}
    O, M, S2 = H["o@t1.fr"], H["m@t1.fr"], H["o@t2.fr"]

    seen = []

    def model(system, user):
        seen.append({"system": system, "user": user})
        if CM.EXTRACT_MARK in system:
            return json.dumps(["Le salon est fermé le dimanche"])
        if CM.SUMMARY_MARK in system:
            return "Résumé : le commerçant a parlé de ses étudiants et de ses horaires."
        return f"Réponse {len(seen)}."
    llm._force_complete = model

    def ask(msg, h=O):
        r = http("POST", "/api/owner/copilot/chat", h, json={"message": msg})
        return r

    def last_chat_prompt():
        return next(s["user"] for s in reversed(seen) if CM.EXTRACT_MARK not in s["system"] and CM.SUMMARY_MARK not in s["system"])

    print("Le calcul (pur)")
    s = CM.scrub("Appelle Karim au 06 12 34 56 78, au +33 6 12 34 56 78 ou karim.b@mail.fr")
    check("phone numbers and e-mails are hidden, the name stays", "Karim" in s and "56 78" not in s
          and "+33" not in s and "@" not in s, s)
    check("prices, dates and counts are not taken for phone numbers",
          CM.scrub("12,50 € le 30/10/2026, 150 clients, 2026") == "12,50 € le 30/10/2026, 150 clients, 2026")
    check("« Retiens que … » is a fact to keep", CM.explicit("Retiens que je suis fermé le lundi") == "je suis fermé le lundi")
    check("« Souviens-toi : … » too", CM.explicit("Souviens-toi : mes clients sont surtout des étudiants")
          == "mes clients sont surtout des étudiants")
    check("a question is not", CM.explicit("Combien de visites cette semaine ?") is None)
    check("« retiens » with nothing after is not", CM.explicit("retiens") is None)

    print("\nLa conversation")
    r1 = ask("Combien de visites cette semaine ?")
    check("the chat answers", r1.status_code == 200 and r1.json()["reply"], r1.text)
    a1 = r1.json()["reply"]
    ask("Et la semaine dernière ?")
    p = last_chat_prompt()
    check("the follow-up carries the previous question and answer", "Combien de visites cette semaine ?" in p and a1 in p, p[:600])
    check("…and not twice the question being asked", p.count("Et la semaine dernière ?") == 1)
    check("the model is told to use the conversation", "conversation" in seen[-1]["system"].lower())
    for i in range(60):
        db.copilot_chats.insert_one({"tenant_id": "t1", "by": "o@t1.fr", "role": "user" if i % 2 == 0 else "assistant",
                                     "text": f"message court {i:02d}", "at": tick_clock()})
    ask("Encore une question")
    p = last_chat_prompt()
    check("no « last 10 / 20 » limit: 60 short messages are all there", all(f"message court {i:02d}" in p for i in range(60)))

    print("\nChaque compte a sa mémoire")
    ask("Question du manager", M)
    p = last_chat_prompt()
    check("the manager's chat does not carry the owner's conversation", "Combien de visites" not in p and "message court" not in p)
    ask("Question d'un autre commerce", S2)
    check("another shop's neither", "Question du manager" not in last_chat_prompt() and "Combien de visites" not in last_chat_prompt())

    print("\nCe que FidClic IA retient")
    r = ask("Retiens que je ferme le lundi")
    items = http("GET", "/api/me/ai-memory", O).json()["items"]
    check("« Retiens que … » is kept at once", any(i["text"] == "je ferme le lundi" for i in items), items)
    ask("Quel jour faire une promo ?")
    p = last_chat_prompt()
    check("the next question carries it", "je ferme le lundi" in p and "Ce que FidClic IA retient" in p, p[:400])
    check("…not the manager's", "je ferme le lundi" not in (ask("Et moi ?", M) and last_chat_prompt()))
    ask("Retiens que je ferme le lundi")
    items = http("GET", "/api/me/ai-memory", O).json()["items"]
    check("the same fact is not kept twice", sum(i["text"] == "je ferme le lundi" for i in items) == 1)

    r = http("POST", "/api/me/ai-memory", O, json={"text": "Ma cible : les étudiants du quartier"})
    check("the owner adds a fact", r.status_code == 200 and r.json()["item"]["source"] == "vous", r.text)
    iid = r.json()["item"]["id"]
    r = http("PATCH", f"/api/me/ai-memory/{iid}", O, json={"text": "Ma cible : les étudiants et les familles"})
    check("…edits it", r.status_code == 200 and r.json()["item"]["text"] == "Ma cible : les étudiants et les familles")
    check("an empty fact is refused", http("POST", "/api/me/ai-memory", O, json={"text": "   "}).status_code == 400)
    check("a fact over 300 characters is refused", http("POST", "/api/me/ai-memory", O, json={"text": "x" * 301}).status_code == 400)
    r = http("POST", "/api/me/ai-memory", O, json={"text": "Mon portable 06 11 22 33 44, mail moi@ici.fr"})
    check("a phone or e-mail in a fact is hidden before it is kept", r.status_code == 200
          and "06 11" not in r.json()["item"]["text"] and "@" not in r.json()["item"]["text"])
    check("the manager cannot see the owner's facts", all(i["id"] != iid for i in http("GET", "/api/me/ai-memory", M).json()["items"]))
    check("…nor edit them (404)", http("PATCH", f"/api/me/ai-memory/{iid}", M, json={"text": "piraté"}).status_code == 404)
    check("…nor delete them (404)", http("DELETE", f"/api/me/ai-memory/{iid}", M).status_code == 404)
    check("another shop's owner cannot either", http("DELETE", f"/api/me/ai-memory/{iid}", S2).status_code == 404)
    check("the owner deletes it", http("DELETE", f"/api/me/ai-memory/{iid}", O).status_code == 200
          and all(i["id"] != iid for i in http("GET", "/api/me/ai-memory", O).json()["items"]))
    check("every plan keeps a memory (Starter: 200)", http("GET", "/api/me/ai-memory", H["o@st.fr"]).status_code == 200
          and http("POST", "/api/me/ai-memory", H["o@st.fr"], json={"text": "Ouvert 7j/7"}).status_code == 200)
    check("every account too (staff: 200)", http("POST", "/api/me/ai-memory", H["s@t1.fr"], json={"text": "Je fais les après-midis"}).status_code == 200)
    check("no token: 401/403", http("GET", "/api/me/ai-memory").status_code in (401, 403))

    print("\nLes téléphones et e-mails ne partent jamais au modèle")
    ask("Envoie un message à Karim, 06 98 76 54 32, karim@exemple.fr")
    p = last_chat_prompt()
    check("not in the question sent to the model", "98 76" not in p and "karim@exemple.fr" not in p and "Karim" in p, p[-300:])
    hist = http("GET", "/api/owner/copilot/chat", O).json()
    check("the owner's own history keeps what they typed", any("06 98 76 54 32" in m["text"] for m in hist["messages"]))

    print("\nL'historique complet")
    check("the history comes in pages, with « more » when older messages exist", hist.get("has_more") is True and len(hist["messages"]) == 20, hist.get("has_more"))
    older = http("GET", "/api/owner/copilot/chat", O, params={"before": hist["before"]}).json()
    check("…and the page before is older", older["messages"] and older["messages"][-1]["text"] != hist["messages"][0]["text"]
          and all(m["text"] not in {x["text"] for x in hist["messages"]} for m in older["messages"]))

    print("\nLe passage régulier (tick) : faits et résumé")
    n_before = len(seen)
    out = CM.learn_due(clock["t"])
    items = http("GET", "/api/me/ai-memory", O).json()["items"]
    check("the facts told in passing are found and kept (source « chat »)",
          any(i["text"] == "Le salon est fermé le dimanche" and i["source"] == "chat" for i in items), items)
    check("the model never sees a phone in what it reads to find facts",
          all("98 76" not in s["user"] for s in seen[n_before:]))
    n2 = len(seen)
    CM.learn_due(clock["t"])
    check("each message is read once (a second pass asks the model nothing new)",
          not any(CM.EXTRACT_MARK in s["system"] for s in seen[n2:]))
    items2 = http("GET", "/api/me/ai-memory", O).json()["items"]
    check("…and keeps no duplicate", sum(i["text"] == "Le salon est fermé le dimanche" for i in items2) == 1)

    for i in range(400):
        db.copilot_chats.insert_one({"tenant_id": "t1", "by": "o@t1.fr", "role": "user" if i % 2 == 0 else "assistant",
                                     "text": f"vieux message {i:03d} " + "x" * 200, "at": clock["t"] - dt.timedelta(days=40, minutes=-i)})
    CM.learn_due(clock["t"])
    st = db.copilot_memory_state.find_one({"tenant_id": "t1", "by": "o@t1.fr"})
    check("the older conversation is summed up", st and st.get("summary", "").startswith("Résumé"), st)
    ask("Et maintenant ?")
    p = last_chat_prompt()
    check("the next question carries the summary", "Résumé : le commerçant a parlé" in p)
    check("…and stays within its size budget", len(p) < CM.RECENT_CHARS + CM.SUMMARY_CHARS + CM.MEMO_CHARS + 20000, len(p))
    check("every message is still kept (nothing deleted)", db.copilot_chats.count_documents({"tenant_id": "t1", "by": "o@t1.fr", "text": {"$regex": "^vieux"}}) == 400)

    db.copilot_chats.insert_one({"tenant_id": "t2", "role": "user", "text": "Retiens rien, ancienne question", "at": clock["t"]})
    CM.learn_due(clock["t"])
    check("messages from before accounts were told apart become the owner's",
          db.copilot_chats.find_one({"tenant_id": "t2", "text": "Retiens rien, ancienne question"}).get("by") == "o@t2.fr")

    real_ctx = CM.context
    CM.context = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("memory broken"))
    r = ask("Question quand la mémoire est cassée")
    CM.context = real_ctx
    check("a broken memory never stops the model's answer", r.status_code == 200 and r.json()["source"] == "model", r.text)

    def down(system, user):
        raise RuntimeError("provider down")
    llm._force_complete = down
    db.copilot_chats.insert_one({"tenant_id": "t1", "by": "o@t1.fr", "role": "user", "text": "Je fais aussi des barbes", "at": tick_clock()})
    res = CM.learn_due(clock["t"])
    check("the model down: the pass does not break", isinstance(res, dict))
    check("…and the message waits for the next pass", db.copilot_chats.find_one({"text": "Je fais aussi des barbes"}).get("memo") is None)
    r = ask("Une question quand le modèle est en panne")
    check("the chat still answers from the facts", r.status_code == 200 and r.json()["source"] == "facts")
    llm._force_complete = None

    src = open(os.path.join(os.path.dirname(__file__), "..", "server.py")).read()
    check("the tick runs the memory pass", "copilot_memory" in src and "learn_due" in src)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
