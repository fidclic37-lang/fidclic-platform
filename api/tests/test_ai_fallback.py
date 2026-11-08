"""
Refusal fallback (queue item after routing, 2026-11-04): when a Claude model
declines on safety grounds, Anthropic re-runs the same request on another
model inside the same call (`fallbacks: "default"`, beta header
server-side-fallback-2026-07-01). Sent on every call to a model that has it,
through the one gate (features/ai_meter.call). It could not be tried against
the real API (no key), so an API that refuses the field must cost nothing:
the call is sent again without it, and the field rests for an hour.

Run: cd api && /usr/local/bin/python3 tests/test_ai_fallback.py
"""
import contextlib
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-ai-fallback")
os.environ.setdefault("DISABLE_SEED", "1")
os.environ["ANTHROPIC_API_KEY"] = "test-key"
for _k in ("LLM_PROVIDER", "LLM_MODEL", "GROQ_API_KEY", "NVIDIA_API_KEY"):
    os.environ.pop(_k, None)
passed = failed = 0
UTC = dt.timezone.utc
BETA = "server-side-fallback-2026-07-01"
FR = "Bonjour, voici votre réponse pour la semaine."


def check(label, cond, show=None):
    global passed, failed
    cond = bool(cond)
    if not cond and show is not None:
        print("    →", str(show)[:400])
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    from features import ai_meter as AM
    from services import llm

    db = server.db
    clock = [dt.datetime(2026, 11, 10, 9, 0, tzinfo=UTC)]
    AM._now = lambda: clock[0]
    sent = []
    reply = {}

    def fake_send(url, headers, body, timeout):
        sent.append((dict(headers), dict(body)))
        r = reply.get("next")
        if callable(r):
            return r(headers, body)
        return 200, {"model": body.get("model"), "content": [{"type": "text", "text": FR}], "stop_reason": "end_turn",
                     "usage": {"input_tokens": 100, "output_tokens": 50}}
    AM._send = fake_send

    def reset():
        for c in ("ai_calls", "ai_spend", "ai_cache", "ai_blocks", "ai_rate"):
            db[c].delete_many({})
        db.platform_settings.delete_many({"key": {"$in": ["ai_meter", "ai_routing"]}})
        AM._NO_FALLBACK.clear()
        sent.clear()
        reply.clear()

    def ask(feature="copilot"):
        with AM.scope(tenant_id=None, feature=feature):
            return llm.complete("s", "u", feature=feature)

    def route(**r):
        db.platform_settings.update_one({"key": "ai_routing"}, {"$set": {"routes": r}}, upsert=True)

    print("Envoyé là où le modèle l'a")
    for model, has in (("claude-opus-5-5", True), ("claude-sonnet-5-5", True), ("claude-fable-5-1", True),
                       ("claude-haiku-5-5", False)):
        reset()
        route(copilot=model)
        ask()
        h, b = sent[0]
        check(f"{model}: {'with' if has else 'without'} the fallback", (b.get("fallbacks") == "default" and BETA in h.get("anthropic-beta", "")) == has
              and (("fallbacks" in b) == has), (h, b))
    reset()
    check("never to Groq or NVIDIA", "fallbacks" not in AM.with_fallback("groq", "llama-3.3-70b-versatile", {"model": "x"}, {})[1])
    check("never to an older Claude", "fallbacks" not in AM.with_fallback("anthropic", "claude-sonnet-4-6", {"model": "x"}, {})[1])
    h, b = AM.with_fallback("anthropic", "claude-opus-5-5", {"anthropic-beta": "other-2026-01-01"}, {"model": "claude-opus-5-5"})
    check("another beta header is kept", h["anthropic-beta"] == f"other-2026-01-01,{BETA}", h)
    h0, b0 = {"x": "1"}, {"model": "claude-opus-5-5"}
    AM.with_fallback("anthropic", "claude-opus-5-5", h0, b0)
    check("the caller's headers and body are not changed in place", h0 == {"x": "1"} and b0 == {"model": "claude-opus-5-5"})

    print("La photo du menu et les factures aussi")
    reset()
    server._call_vision_anthropic("iVBORw0KGgo=", "image/png", "Lis ce menu")
    check("the menu photo carries it (Sonnet 5.5)", sent and sent[0][1].get("fallbacks") == "default", sent[:1])

    print("Le refus de sécurité")
    reset()

    def refused(h, b):
        return 200, {"model": b["model"], "content": [], "stop_reason": "refusal", "stop_details": {"type": "refusal", "category": "cyber"},
                     "usage": {"input_tokens": 100, "output_tokens": 0}}
    reply["next"] = refused
    check("the whole chain refused: no text → the caller's template", ask() is None)
    row = db.ai_calls.find_one({}, {"_id": 0})
    check("written down as refused, with its category", row["status"] == "refused" and row["reason"] == "cyber", row)
    check("…and paid like any call", float(db.ai_spend.find_one({"_id": AM.key_day(None)})["eur"]) > 0)
    sent.clear()
    with AM.scope(tenant_id=None, feature="support"):
        llm.complete("s", "u", feature="support", temperature=0.2)
        llm.complete("s", "u", feature="support", temperature=0.2)
    check("a refusal is never replayed from the cache", len(sent) == 2, len(sent))
    reset()

    def rescued(h, b):
        return 200, {"model": "claude-opus-4-8", "content": [{"type": "fallback", "from": {"model": b["model"]}, "to": {"model": "claude-opus-4-8"}},
                                                          {"type": "text", "text": FR}],
                     "stop_reason": "end_turn", "usage": {"input_tokens": 100, "output_tokens": 50,
                                                         "iterations": [{"type": "message"}, {"type": "fallback_message"}]}}
    reply["next"] = rescued
    check("another model answered: its text is used", ask() == FR)
    row = db.ai_calls.find_one({}, {"_id": 0})
    check("the row says who answered", row["status"] == "ok" and row.get("served_by") == "claude-opus-4-8", row)

    print("Une API qui refuse le champ ne coûte rien")
    reset()
    calls = []

    def no_field(h, b):
        calls.append(1)
        if "fallbacks" in b:
            return 400, {"type": "error", "error": {"type": "invalid_request_error", "message": "fallbacks: Extra inputs are not permitted"}}
        return 200, {"model": b["model"], "content": [{"type": "text", "text": FR}], "usage": {"input_tokens": 100, "output_tokens": 50}}
    reply["next"] = no_field
    check("sent again without it, and answers", ask() == FR and len(sent) == 2 and "fallbacks" not in sent[1][1]
          and BETA not in sent[1][0].get("anthropic-beta", ""), [s[1].keys() for s in sent])
    check("one call billed, no error row", db.ai_calls.count_documents({"status": "ok"}) == 1 and db.ai_calls.count_documents({"status": "error"}) == 0,
          list(db.ai_calls.find({}, {"_id": 0, "status": 1, "reason": 1})))
    sent.clear()
    ask()
    check("for the next hour it is not sent", len(sent) == 1 and "fallbacks" not in sent[0][1])
    clock[0] += dt.timedelta(minutes=61)
    sent.clear()
    reply.clear()
    ask()
    check("after an hour it is tried again", sent[0][1].get("fallbacks") == "default")
    clock[0] = dt.datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    reset()
    reply["next"] = lambda h, b: (400, {"type": "error", "error": {"type": "invalid_request_error", "message": "max_tokens: too large"}})
    check("another 400 is not sent twice", ask() is None and len([s for s in sent if s[1].get("model") == "claude-opus-5-5"]) == 1, len(sent))
    check("…and the field stays on", not AM._NO_FALLBACK)
    reset()
    reply["next"] = lambda h, b: (529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
    ask()
    check("an overloaded API is not mistaken for a refused field", not AM._NO_FALLBACK)

    print("Le faux modèle des tests")
    reset()
    llm._force_complete = lambda s, u: FR
    check("forced replies are untouched", ask() == FR and not sent)
    llm._force_complete = None

    print()
    print(f"{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
