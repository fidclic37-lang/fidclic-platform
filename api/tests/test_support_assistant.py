"""
Besoin d'aide ? — the knowledge base, the retriever and the assistant.

The point of this suite is the promise made to the merchant: the assistant
ALWAYS answers. So the LLM is exercised in all three states it can be in —
absent, broken, and working — and the answer must survive every one of them.

    cd api && python3 tests/test_support_assistant.py
"""
from __future__ import annotations

import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from features import support_assistant as SA
    import services.llm as LLM

    db = server.db
    SA.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    db.tenants.insert_one({"id": "t1", "name": "Le Petit Café", "slug": "le-petit-cafe"})

    # ---- knowledge base shape --------------------------------------------
    print("\nKnowledge base")
    check("the base is not empty", len(SA.KB) >= 10)
    check("every article has the five fields", all(
        {"id", "section", "title", "keywords", "body"} <= set(a) for a in SA.KB))
    check("ids are unique", len({a["id"] for a in SA.KB}) == len(SA.KB))
    check("every body is a real answer, not a stub", all(len(a["body"]) > 120 for a in SA.KB))
    check("the five mockup questions are all present", {
        "creer-carte", "ajouter-points", "personnaliser-carte", "envoyer-campagne", "consulter-stats",
    } <= {a["id"] for a in SA.KB})
    check("every link points inside the dashboard", all(
        a["link"]["to"].startswith("/dashboard") for a in SA.KB if a.get("link")))

    # ---- retrieval --------------------------------------------------------
    print("\nRetrieval — the right article must rank first")
    CASES = [
        ("Comment ajouter des points à un client ?", "ajouter-points"),
        ("je veux changer les couleurs de ma carte", "personnaliser-carte"),
        ("comment créer ma carte de fidélité", "creer-carte"),
        ("envoyer une promo à mes clients", "envoyer-campagne"),
        ("où voir mes statistiques", "consulter-stats"),
        ("mes chiffres de fréquentation", "consulter-stats"),
        ("apple wallet sur iphone", "wallet"),
        ("combien coûte mon abonnement", "abonnement"),
        ("importer mes clients depuis un fichier excel", "importer-clients"),
        ("ajouter un membre de mon équipe", "equipe"),
        ("mes clients ne reçoivent pas les notifications", "notifications"),
        ("rgpd et données personnelles", "rgpd"),
        ("comment marchent les paliers et récompenses", "recompenses"),
    ]
    for question, expected in CASES:
        hits = SA.search_kb(question)
        check(f"{question[:44]:46s} -> {expected}", hits and hits[0]["id"] == expected)

    check("accents are optional", SA.search_kb("recompense palier")[0]["id"] == "recompenses")
    check("an off-topic question retrieves nothing",
          SA.search_kb("quelle est la météo à Paris demain ?") == [])
    check("an empty question retrieves nothing", SA.search_kb("") == [])

    # ---- answering with NO model configured (the default deployment) ------
    print("\nAnswering with no LLM key — the documented promise")
    LLM._force_complete = lambda *a, **k: None          # provider unavailable
    a = SA.answer("Comment ajouter des points à un client ?")
    check("an answer still comes back", bool(a["answer"].strip()))
    check("it is the knowledge base verbatim", a["phrased_by"] == "kb")
    check("it is the right article", "Scanner" in a["answer"])
    check("markdown is stripped for the chat bubble", "**" not in a["answer"])
    check("the source is named", a["sources"][0]["id"] == "ajouter-points")
    check("it carries the page link", a["link"]["to"] == "/dashboard/scan")
    check("it does not escalate", a["escalate"] is False)

    # ---- answering when the model raises ---------------------------------
    print("\nAnswering when the provider blows up")
    def boom(*a, **k):
        raise RuntimeError("provider 503")
    LLM._force_complete = boom
    a = SA.answer("comment personnaliser ma carte")
    check("the exception never reaches the caller", bool(a["answer"].strip()))
    check("it falls back to the knowledge base", a["phrased_by"] == "kb")

    LLM._force_complete = lambda *a, **k: "   "         # empty/blank reply
    a = SA.answer("comment personnaliser ma carte")
    check("a blank model reply falls back too", a["phrased_by"] == "kb" and len(a["answer"]) > 80)

    # ---- answering with a working model ----------------------------------
    print("\nAnswering with a working model")
    seen = {}
    def fake(system, user, **kw):
        seen["system"], seen["user"] = system, user
        return "Ouvrez la page Scanner et scannez le QR code du client."
    LLM._force_complete = fake
    a = SA.answer("comment ajouter des points", tenant_name="Le Petit Café")
    check("the model's phrasing is used", a["phrased_by"] == "model")
    check("its text is returned", a["answer"].startswith("Ouvrez la page Scanner"))
    check("the retrieved documentation was in the prompt", "Scanner" in seen["user"])
    check("the shop name was in the prompt", "Le Petit Café" in seen["user"])
    check("the prompt forbids inventing", "N'invente" in seen["system"])

    # ---- the honest no-answer --------------------------------------------
    print("\nWhen the base genuinely has nothing")
    a = SA.answer("quelle est la météo à Paris demain ?")
    check("it says so rather than guessing", a["escalate"] is True and a["sources"] == [])
    check("it hands over the phone number", SA.SUPPORT_PHONE in a["answer"])
    check("the model was not asked to fill the gap", a["phrased_by"] == "none")

    # ---- endpoints --------------------------------------------------------
    print("\nEndpoints")
    kb = SA.get_kb()
    check("/support/kb returns every article", len(kb["faq"]) == len(SA.KB))
    check("it ships the quick replies from the mockup",
          [q["label"] for q in kb["quick_replies"]][:3] ==
          ["Ma carte de fidélité", "Mes campagnes", "Mes clients"])
    check("the last quick reply is the open one", kb["quick_replies"][-1]["id"] == "autre")
    check("the chat delay is the mockup's", kb["channels"]["chat"]["delay"] == "moins de 5 min.")
    check("the phone number is the mockup's", kb["channels"]["phone"]["number"] == "01 84 80 10 20")
    check("the opening line greets", kb["greeting"].startswith("Bonjour"))

    LLM._force_complete = lambda *a, **k: None
    r = SA.chat(SA.ChatMessage(message="comment envoyer une campagne ?"), TD())
    check("POST /owner/support/chat answers", "Campagnes" in r["answer"])
    check("it timestamps the reply", "at" in r and "T" in r["at"])
    check("the exchange is persisted", db.support_chats.count_documents({"tenant_id": "t1"}) == 1)
    row = db.support_chats.find_one({"tenant_id": "t1"})
    check("the persisted row names the merchant", row["email"] == "owner@x.fr")
    check("the persisted row keeps the sources", "envoyer-campagne" in row["sources"])

    SA.chat(SA.ChatMessage(message="comment consulter les statistiques ?"), TD())
    h = SA.chat_history(20, TD())
    check("history returns both turns", len(h["messages"]) == 2)
    check("history reads oldest first", "campagne" in h["messages"][0]["question"])
    check("history carries the quick replies too", len(h["quick_replies"]) == 7)

    class Other:
        email, role, tenant_id = "someone@else.fr", "business_owner", "t2"
    check("one merchant never sees another's thread", SA.chat_history(20, Other())["messages"] == [])

    # a write failure must never cost the merchant their answer
    class DeadDb:
        def __getattr__(self, _):
            raise RuntimeError("mongo is down")
    healthy, SA._db = SA._db, DeadDb()
    try:
        r = SA.chat(SA.ChatMessage(message="comment ajouter des points ?"), TD())
        check("a logging failure still returns the answer", "Scanner" in r["answer"])
    except Exception as exc:  # noqa: BLE001
        check(f"a logging failure still returns the answer (raised {exc})", False)
    finally:
        SA._db = healthy

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
