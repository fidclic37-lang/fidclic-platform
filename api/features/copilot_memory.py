"""
La mémoire du Copilote (user, 2026-10-30: « jitna max yaad rakh sake »).

Every message of the chat is kept for good (`copilot_chats`, never deleted).
What a question carries to the model:

    Ce que FidClic IA retient   the facts this account told it (« je ferme le
                                lundi », « ma cible : les étudiants ») — the
                                owner sees, edits and deletes them
                                (Paramètres › Préférences, and the Copilote)
    a summary                   of the conversation older than the recent part
    the recent conversation     in full, up to a size budget — never « the
                                last 10 »: short messages all fit

Facts come two ways: at once when the message says so (« Retiens que… »),
and from the regular pass (the tick, every 15 min), where the model reads
the new messages once and keeps what lasts. The same pass sums up the part
of the conversation that left the recent window.

Each account has its own memory, on every plan (user: « sab plans, har
account »). Phone numbers and e-mails never reach the model: they are hidden
in everything sent to it and in every fact kept (user: names yes, phone and
e-mail never). Nothing here may break the chat or the tick.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_role
from models import TokenData

router = APIRouter(tags=["copilot-memory"])
_db = None

RECENT_CHARS = 24_000      # the recent conversation, in full (~6 000 tokens)
SUMMARY_CHARS = 6_000      # the summary of the older one
MEMO_CHARS = 8_000         # « Ce que FidClic IA retient », newest first
FACT_MAX = 300             # one fact
FACTS_MAX = 2_000          # per account — far beyond what anyone tells
EXTRACT_CHUNK = 12_000     # characters of messages read per model call
PASS_CALLS = 60            # model calls per pass at most (the tick stays short)
PASS_SECONDS = 120.0       # …and its time: what is left waits for the next pass
PASS_WORKERS = 6           # model calls at once (only the calls: the database stays in one thread)
ACCOUNT_MESSAGES = 400     # one account's new messages read in one pass
ROLES = ["business_owner", "administrateur", "manager", "staff"]

EXTRACT_MARK = "FAITS_DURABLES"
SUMMARY_MARK = "RESUME_CONVERSATION"

_EXTRACT_SYSTEM = (
    f"[{EXTRACT_MARK}] Tu lis des messages qu'un commerçant a écrits à son assistant FidClic IA. "
    "Relève UNIQUEMENT les faits durables sur son commerce ou ses préférences : horaires et fermetures, "
    "clientèle visée, offres et habitudes, ton souhaité, contraintes, objectifs, équipe. Ignore les "
    "questions, les demandes ponctuelles et les chiffres du moment. Ne recopie jamais un numéro de "
    "téléphone ni une adresse e-mail. Ne répète pas un fait déjà connu. Réponds UNIQUEMENT par un "
    "tableau JSON d'objets {\"fait\": phrase courte en français (12 mots au plus), \"message\": numéro du "
    "message d'où il vient}, ou [] s'il n'y a rien."
)
_SUMMARY_SYSTEM = (
    f"[{SUMMARY_MARK}] Tu tiens le résumé des conversations entre un commerçant et son assistant FidClic IA. "
    "On te donne le résumé précédent et la suite de la conversation : rends le nouveau résumé, en "
    "français, 250 mots au plus. Garde ses décisions, ses préférences, ses questions récurrentes, les "
    "campagnes évoquées et les chiffres cités avec leur période. Pas de numéro de téléphone ni d'e-mail."
)


def init(db):
    global _db
    _db = db
    try:
        db.copilot_memory.create_index([("tenant_id", 1), ("by", 1), ("at", -1)])
        db.copilot_memory_state.create_index([("tenant_id", 1), ("by", 1)], unique=True)
        db.copilot_chats.create_index([("tenant_id", 1), ("by", 1), ("at", -1)])
        db.copilot_chats.create_index([("role", 1), ("memo", 1), ("at", 1)])
    except Exception:
        pass


def NOW() -> datetime:                      # the clock (tests set it)
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# the pure part
# ---------------------------------------------------------------------------
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# « karim [at] mail [dot] fr », « karim (at) mail.fr », « karim arobase mail point fr », « karim at gmail dot com »
_AT = r"(?:\s*[\[(]\s*(?:at|@|arobase)\s*[\])]\s*|\s+(?:at|arobase)\s+)"
_DOT = r"(?:\s*[\[(]\s*(?:dot|point|\.)\s*[\])]\s*|\s+(?:dot|point)\s+|\.)"
_EMAIL_SPOKEN = re.compile(rf"[\w.+-]+{_AT}[\w-]+(?:{_DOT}[\w-]+)+", re.IGNORECASE)
_PHONE = re.compile(r"(?<![\w/])(?:(?:\+|00)\d{1,3}[\s.\-]?)?\(?0?\d\)?(?:[\s.\-]?\d{2}){4}(?![\w/])")
# abroad: + or 00, then 8 to 15 digits however they are grouped (+44 20 7946 0958, +1 (415) 555-2671)
_PHONE_INTL = re.compile(r"(?<![\w/])(?:\+|00)\s?\d[\d\s.\-()]{5,24}\d(?![\w/])")
# in words: six number words or more in a row (« zéro six douze trente-quatre… »)
_NUM_WORD = (r"(?:z[ée]ro|une?|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze|"
             r"seize|vingts?|trente|quarante|cinquante|soixante|cents?)")
_PHONE_WORDS = re.compile(rf"\b{_NUM_WORD}(?:[\s,\-]+(?:et[\s\-]+)?{_NUM_WORD}){{5,}}\b", re.IGNORECASE)
_EXPLICIT = re.compile(
    r"^\s*(?:retiens(?:\s+bien)?|souviens[\s-]+toi|rappelle[\s-]+toi|n['’]oublie\s+pas|note\s+bien|note(?=\s+que\b)|"
    r"garde\s+en\s+t[eê]te|m[ée]morise)\s*(?:que\s+|qu['’]|:\s*|,\s*)?(?P<fact>.+?)\s*[.!]*\s*$",
    re.IGNORECASE | re.DOTALL)


def scrub(text: str) -> str:
    """The text with every phone number and e-mail hidden."""
    t = _EMAIL.sub("[e-mail]", text or "")
    t = _EMAIL_SPOKEN.sub("[e-mail]", t)
    t = _PHONE_INTL.sub(lambda m: "[téléphone]" if 8 <= sum(c.isdigit() for c in m.group(0)) <= 15 else m.group(0), t)
    t = _PHONE.sub("[téléphone]", t)
    return _PHONE_WORDS.sub("[téléphone]", t)


def explicit(message: str) -> Optional[str]:
    """« Retiens que je ferme le lundi » → « je ferme le lundi »."""
    m = _EXPLICIT.match(message or "")
    if not m:
        return None
    fact = m.group("fact").strip()
    return fact if len(fact) >= 3 else None


def _fold(s: str) -> str:
    s = "".join(ch for ch in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _clean_fact(text: str) -> str:
    return re.sub(r"\s+", " ", scrub(text or "")).strip()


# ---------------------------------------------------------------------------
# the facts
# ---------------------------------------------------------------------------
def facts(tid: str, by: Optional[str]) -> List[Dict[str, Any]]:
    return list(_db.copilot_memory.find({"tenant_id": tid, "by": by}, {"_id": 0}).sort("at", -1).limit(FACTS_MAX))


def add(tid: str, by: Optional[str], text: str, source: str,
        src_at: Optional[List[datetime]] = None) -> Optional[Dict[str, Any]]:
    """Keep a fact, once. None when it is already known or there is no room."""
    t = _clean_fact(text)[:FACT_MAX]
    if len(t) < 3 or not by:
        return None
    key = _fold(t)
    for f in facts(tid, by):
        if _fold(f.get("text")) == key:
            return None
    if _db.copilot_memory.count_documents({"tenant_id": tid, "by": by}) >= FACTS_MAX:
        return None
    now = NOW()
    doc = {"id": uuid.uuid4().hex, "tenant_id": tid, "by": by, "text": t, "source": source, "at": now, "updated_at": now,
           "src_at": list(src_at or []),             # the messages it came from: deleting it forgets them
           "rules": rules_of(t), "rules_by": "regle"}   # firm facts at once; the model refines them next pass
    _db.copilot_memory.insert_one(dict(doc))
    return doc


def link(doc: Optional[Dict[str, Any]], at: datetime) -> None:
    """The chat's « Retiens que… »: the fact came from this message."""
    if doc:
        _db.copilot_memory.update_one({"id": doc["id"]}, {"$addToSet": {"src_at": at}})


def _has_words(text: str) -> bool:
    return len(_fold(text).split()) >= 2


def forget(f: Dict[str, Any]) -> int:
    """A fact deleted or rewritten leaves everything the model reads: the
    messages it came from (and FidClic IA's reply to each), any message of
    this account that says it word for word, and the summary — rebuilt by
    the regular pass without them. The owner's own history keeps the text,
    marked « oublié »."""
    tid, by = f["tenant_id"], f["by"]
    ats = set(a for a in (f.get("src_at") or []) if isinstance(a, datetime))
    key = _fold(f.get("text"))
    if _has_words(f.get("text") or ""):
        for m in _db.copilot_chats.find({"tenant_id": tid, "by": by, "role": "user", "forgotten": {"$ne": True}},
                                        {"_id": 0, "text": 1, "at": 1}):
            if key in _fold(m.get("text")):
                ats.add(m["at"])
    n = 0
    for at in ats:
        n += _db.copilot_chats.update_many({"tenant_id": tid, "by": by, "role": "user", "at": at},
                                           {"$set": {"forgotten": True, "memo": True}}).modified_count
        nxt = _db.copilot_chats.find_one({"tenant_id": tid, "by": by, "role": "assistant", "at": {"$gt": at}},
                                         {"_id": 0, "at": 1}, sort=[("at", 1)])
        if nxt and isinstance(nxt.get("at"), datetime) and isinstance(at, datetime) and \
                _aware(nxt["at"]) - _aware(at) <= timedelta(minutes=2):
            _db.copilot_chats.update_many({"tenant_id": tid, "by": by, "role": "assistant", "at": nxt["at"]},
                                          {"$set": {"forgotten": True}})
    _db.copilot_memory_state.update_one({"tenant_id": tid, "by": by},
                                        {"$set": {"summary": "", "upto_at": None, "rebuild": True, "at": NOW()}},
                                        upsert=True)
    return n


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _public(f: Dict[str, Any]) -> Dict[str, Any]:
    at = f.get("updated_at") or f.get("at")
    return {"id": f["id"], "text": f["text"], "source": f.get("source") or "chat",
            "at": at.isoformat() if isinstance(at, datetime) else at}


# ---------------------------------------------------------------------------
# what a question carries
# ---------------------------------------------------------------------------
def _account(tid: str, by: Optional[str], owner: bool, view_by: Optional[str] = None) -> Dict[str, Any]:
    """The account's conversation. Messages from before accounts were told
    apart belong to the owner (as in the chat's history). What a super admin
    wrote in « Accéder au compte » is never the owner's: only that super
    admin's own session reads it back."""
    own = [{"by": by}, {"by": {"$exists": False}}, {"by": None}] if owner else [{"by": by}]
    seen = [{"view_by": {"$exists": False}}] + ([{"view_by": view_by}] if view_by else [])
    return {"tenant_id": tid, "$and": [{"$or": own}, {"$or": seen}]}


def _window(q: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[datetime]]:
    """The recent conversation, newest kept first until the budget is spent;
    returned oldest first, with the date of its oldest message."""
    out: List[Dict[str, Any]] = []
    used = 0
    q = {"$and": [q, {"forgotten": {"$ne": True}}]}
    for m in _db.copilot_chats.find(q, {"_id": 0, "role": 1, "text": 1, "at": 1}).sort("at", -1):
        n = len(m.get("text") or "") + 16
        if out and used + n > RECENT_CHARS:
            break
        out.append(m)
        used += n
    out.reverse()
    return out, (out[0].get("at") if out else None)


def _state(tid: str, by: Optional[str]) -> Dict[str, Any]:
    return _db.copilot_memory_state.find_one({"tenant_id": tid, "by": by}, {"_id": 0}) or {}


def context(tid: str, by: Optional[str], owner: bool, view_by: Optional[str] = None) -> str:
    """The memory block put before the shop's figures, all scrubbed."""
    parts: List[str] = []
    kept, used = [], 0
    for f in facts(tid, by):
        line = f"- {scrub(f['text'])}"
        if used + len(line) > MEMO_CHARS:
            break
        kept.append(line)
        used += len(line) + 1
    if kept:
        parts.append("Ce que FidClic IA retient sur ce commerçant (ce qu'il t'a dit, à respecter) :\n" + "\n".join(kept))
    summary = (_state(tid, by).get("summary") or "").strip()
    if summary:
        parts.append("Résumé des conversations plus anciennes :\n" + scrub(summary)[:SUMMARY_CHARS])
    recent, _ = _window(_account(tid, by, owner, view_by))
    if recent:
        lines = [f"{'Commerçant' if m.get('role') == 'user' else 'FidClic IA'} : {scrub(m.get('text') or '')}" for m in recent]
        parts.append("Conversation récente (de la plus ancienne à la plus récente) :\n" + "\n".join(lines))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# the regular pass (the tick)
# ---------------------------------------------------------------------------
def _llm_ready() -> bool:
    try:
        from services import llm
        return bool(llm._force_complete) or llm.is_configured()
    except Exception:
        return False


def _ask(system: str, user: str, max_tokens: int) -> Optional[str]:
    from services import llm
    return llm.complete(system, user, max_tokens=max_tokens, temperature=0.2)


def _json_facts(text: str) -> List[Tuple[str, Optional[int]]]:
    """[(fact, message number or None)] — objects {fait, message}, or plain
    strings from an older or looser answer."""
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    out: List[Tuple[str, Optional[int]]] = []
    for x in data if isinstance(data, list) else []:
        if isinstance(x, dict):
            t, n = str(x.get("fait") or x.get("fact") or "").strip(), x.get("message")
            out.append((t, n if isinstance(n, int) else None)) if t else None
        elif isinstance(x, (str, int, float)) and str(x).strip():
            out.append((str(x).strip(), None))
    return out


def _owners(tids: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for u in _db.users.find({"tenant_id": {"$in": tids}, "role": "business_owner"}, {"_id": 0, "tenant_id": 1, "email": 1}):
        out.setdefault(u["tenant_id"], u.get("email"))
    return out


def _backfill_owner() -> int:
    """Messages from before accounts were told apart become the owner's."""
    q = {"$or": [{"by": {"$exists": False}}, {"by": None}]}
    tids = list({m["tenant_id"] for m in _db.copilot_chats.find(q, {"_id": 0, "tenant_id": 1}).limit(5000) if m.get("tenant_id")})
    n = 0
    for tid, email in _owners(tids).items():
        if email:
            n += _db.copilot_chats.update_many({"tenant_id": tid, **q}, {"$set": {"by": email}}).modified_count
    return n


def _chunks(msgs: List[Dict[str, Any]], size: int) -> List[List[Dict[str, Any]]]:
    out: List[List[Dict[str, Any]]] = []
    cur: List[Dict[str, Any]] = []
    used = 0
    for m in msgs:
        n = len(m.get("text") or "") + 16
        if cur and used + n > size:
            out.append(cur)
            cur, used = [], 0
        cur.append(m)
        used += n
    if cur:
        out.append(cur)
    return out


def _run(jobs: List[Tuple[str, str, int]], deadline: float) -> List[Optional[str]]:
    """The model calls of a pass, PASS_WORKERS at a time — only the calls:
    the database is read and written by the caller. A job not started
    before the deadline is skipped (None) and waits for the next pass; a
    call that fails is an exception in its slot."""
    def one(job):
        if _mono() > deadline:
            return _SKIP
        try:
            return _ask(*job)
        except Exception as exc:              # noqa: BLE001 — the slot says it failed
            return exc
    if not jobs:
        return []
    with ThreadPoolExecutor(max_workers=min(PASS_WORKERS, len(jobs))) as pool:
        return list(pool.map(one, jobs))


_SKIP = object()
_mono = time.monotonic       # the pass's clock (tests set it: a slow CI machine must not decide)


def _pending_accounts(limit: int) -> List[Tuple[str, str]]:
    """The accounts with new messages, the longest waiting first."""
    rows = _db.copilot_chats.aggregate([
        {"$match": {"role": "user", "memo": {"$exists": False}, "by": {"$nin": [None]}, "view_by": {"$exists": False}}},
        {"$group": {"_id": {"t": "$tenant_id", "b": "$by"}, "first": {"$min": "$at"}}},
        {"$sort": {"first": 1}}, {"$limit": limit}])
    return [(r["_id"]["t"], r["_id"]["b"]) for r in rows if r["_id"].get("t") and r["_id"].get("b")]


def _extract_pass(accounts: List[Tuple[str, str]], budget: List[int], deadline: float, out: Dict[str, Any]) -> None:
    """Each account's new messages read together (in chunks when long),
    every account's first chunk before anyone's second."""
    per: List[List[Tuple[str, str, List[Dict[str, Any]]]]] = []
    for tid, by in accounts:
        msgs = list(_db.copilot_chats.find({"tenant_id": tid, "by": by, "role": "user", "memo": {"$exists": False},
                                            "view_by": {"$exists": False}},
                                           {"_id": 0, "text": 1, "at": 1}).sort("at", 1).limit(ACCOUNT_MESSAGES))
        per.append([(tid, by, c) for c in _chunks(msgs, EXTRACT_CHUNK)])
    order = [job for rnd in range(max((len(x) for x in per), default=0)) for x in per if rnd < len(x) for job in [x[rnd]]]
    order = order[:max(0, budget[0])]
    prompts = []
    for tid, by, chunk in order:
        known = "\n".join(f"- {scrub(f['text'])}" for f in facts(tid, by)[:200]) or "(aucun)"
        body = "\n".join(f"{i}. {scrub(m.get('text') or '')}" for i, m in enumerate(chunk, 1))
        prompts.append((_EXTRACT_SYSTEM, f"Faits déjà connus :\n{known}\n\nNouveaux messages du commerçant :\n{body}", 300))
    replies = _run(prompts, deadline)
    for (tid, by, chunk), reply in zip(order, replies):
        if reply is _SKIP:
            continue
        budget[0] -= 1
        if reply is None or isinstance(reply, Exception):
            out["failures"] += 1                  # the messages wait for the next pass
            continue
        for f, n in _json_facts(reply)[:20]:
            src = [chunk[n - 1]["at"]] if n and 1 <= n <= len(chunk) else []
            out["facts"] += add(tid, by, f, "chat", src) is not None
        _db.copilot_chats.update_many({"tenant_id": tid, "by": by, "role": "user", "at": {"$in": [m["at"] for m in chunk]}},
                                      {"$set": {"memo": True}})


def _summary_job(tid: str, by: str) -> Optional[Tuple[List[Dict[str, Any]], Tuple[str, str, int]]]:
    """The next part of the account's conversation to sum up: what left the
    recent window since the last summary."""
    _recent, oldest = _window({"tenant_id": tid, "by": by, "view_by": {"$exists": False}})
    if oldest is None:
        return None
    st = _state(tid, by)
    q: Dict[str, Any] = {"tenant_id": tid, "by": by, "at": {"$lt": oldest}, "view_by": {"$exists": False},
                         "forgotten": {"$ne": True}}
    if st.get("upto_at"):
        q["at"]["$gt"] = st["upto_at"]
    msgs = list(_db.copilot_chats.find(q, {"_id": 0, "role": 1, "text": 1, "at": 1}).sort("at", 1).limit(400))
    chunk = _chunks(msgs, EXTRACT_CHUNK)[:1]
    if not chunk:
        return None
    body = "\n".join(f"{'Commerçant' if m.get('role') == 'user' else 'FidClic IA'} : {scrub(m.get('text') or '')}"
                     for m in chunk[0])
    prev = st.get("summary") or "(aucun)"
    return chunk[0], (_SUMMARY_SYSTEM, f"Résumé précédent :\n{prev}\n\nSuite de la conversation :\n{body}", 600)


def _summary_pass(accounts: List[Tuple[str, str]], budget: List[int], deadline: float, out: Dict[str, Any]) -> None:
    """Rounds: one part per account at a time (each part builds on the
    summary before it), until done, out of calls or out of time."""
    todo = list(accounts)
    while todo and budget[0] > 0 and _mono() < deadline:
        jobs = []
        for tid, by in todo[:budget[0]]:
            j = _summary_job(tid, by)
            if j:
                jobs.append((tid, by, j[0], j[1]))
            else:                                  # caught up: a rebuild after « oublier » is done
                _db.copilot_memory_state.update_one({"tenant_id": tid, "by": by, "rebuild": True}, {"$unset": {"rebuild": ""}})
        if not jobs:
            break
        replies = _run([j[3] for j in jobs], deadline)
        todo = []
        for (tid, by, chunk, _job), reply in zip(jobs, replies):
            if reply is _SKIP:
                continue
            budget[0] -= 1
            if reply is None or isinstance(reply, Exception) or not str(reply).strip():
                out["failures"] += 1
                continue
            _db.copilot_memory_state.update_one({"tenant_id": tid, "by": by},
                                                {"$set": {"summary": scrub(str(reply).strip())[:SUMMARY_CHARS],
                                                          "upto_at": chunk[-1]["at"], "at": NOW()}}, upsert=True)
            out["summaries"] += 1
            todo.append((tid, by))


def learn_due(now: Optional[datetime] = None) -> Dict[str, Any]:
    """The tick's call: each account's new messages read once for facts, the
    older conversation summed up. At most PASS_CALLS model calls and
    PASS_SECONDS; a model that does not answer leaves the messages for the
    next pass."""
    out: Dict[str, Any] = {"owners": 0, "facts": 0, "summaries": 0, "failures": 0}
    try:
        out["owners"] = _backfill_owner()
    except Exception:
        out["failures"] += 1
    if not _llm_ready():
        return out
    deadline = _mono() + PASS_SECONDS
    budget = [PASS_CALLS]
    accounts = _pending_accounts(PASS_CALLS)
    for st in _db.copilot_memory_state.find({"rebuild": True}, {"_id": 0, "tenant_id": 1, "by": 1}).limit(PASS_CALLS):
        if (st["tenant_id"], st["by"]) not in accounts:     # a summary to rebuild after « oublier »
            accounts.append((st["tenant_id"], st["by"]))
    try:
        _extract_pass(accounts, budget, deadline, out)
    except Exception:
        out["failures"] += 1
    try:
        _summary_pass(accounts, budget, deadline, out)
    except Exception:
        out["failures"] += 1
    try:
        _rules_pass(budget, deadline, out)
    except Exception:
        out["failures"] += 1
    out["accounts"] = len(accounts)
    return out


# ---------------------------------------------------------------------------
# « Ce que FidClic IA retient » partout (user, 2026-10-30, PR 3)
#
# The owner's facts are the shop's truth; the account's own come with them;
# automatic work (Autopilote) reads the owner's. Every AI that writes reads
# memory_block(); the pages that advise by rules read constraints() through
# features/reco_ranking: a closed day's offer is not shown, advice for the
# clients the shop aims at goes up, an offer it does not want goes down.
# ---------------------------------------------------------------------------
WEEKDAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
TARGETS = {
    "etudiants": ("etudiant",),
    "familles": ("famille", "parents", "enfant"),
    "seniors": ("senior", "retraite", "personnes agees"),
    "jeunes": ("jeune", "ado"),
    "professionnels": ("professionnel", "entreprise", "salarie", "bureau"),
    "quartier": ("quartier", "voisin", "habitant", "locaux", "moins de 2 km", "a proximite", "a cote"),
    "touristes": ("touriste", "vacancier"),
    "nouveaux": ("nouveaux clients", "nouveau client"),
    "fideles": ("fidele", "habitue", "regulier"),
}
AVOID = {
    "offres": ("promo", "remise", "reduction", "rabais", "solde", "offre", "gratuit", "cadeau"),
    "anniversaires": ("anniversaire",),
    "parrainage": ("parrainage", "parrain"),
    "avis_google": ("avis google", "avis"),
    "relances": ("relance", "relancer"),
}
_CLOSED = re.compile(r"ferm|pas ouvert|ne (?:travaill|bosse|ouvr)|n'ouvr|repos|conge|jour off|on ne bosse pas")
_AIM = re.compile(r"cibl|vise|viser|clientele|surtout|principalement|majoritairement|beaucoup d|attir|touch|public|pour les")
_NO = re.compile(r"\b(?:pas|jamais|sans|aucune?|evit\w*|refus\w*|interdit\w*|ne veu\w* pas|n'aime pas|ne fais pas|stop)\b")
RULES_MARK = "FAITS_FERMES"
_RULES_SYSTEM = (
    f"[{RULES_MARK}] Un commerçant a dit cette phrase à son assistant. Extrais les faits fermes, en JSON "
    "UNIQUEMENT : {\"jours_fermes\": [jours en minuscules parmi lundi…dimanche où le commerce est FERMÉ], "
    "\"cible\": [clientèles qu'il VISE parmi " + ", ".join(TARGETS) + "], \"eviter\": [ce qu'il NE VEUT PAS "
    "proposer parmi " + ", ".join(AVOID) + "]}. Listes vides si la phrase ne le dit pas clairement."
)


def _words(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9']+", " ", "".join(
        ch for ch in unicodedata.normalize("NFD", (text or "").lower()) if unicodedata.category(ch) != "Mn")) + " "


def rules_of(text: str) -> Dict[str, List[Any]]:
    """The firm facts a sentence says, by rules (at once; the model refines
    them in the regular pass): {jours_fermes: [0-6], cible: [...], eviter: [...]}."""
    w = _words(text)
    closed: List[int] = []
    if _CLOSED.search(w):
        closed = [i for i, d in enumerate(WEEKDAYS_FR) if re.search(rf"\b{d}s?\b", w)]
        if re.search(r"\bweek ?end", w):
            closed = sorted(set(closed) | {5, 6})
    cible = sorted(k for k, kws in TARGETS.items() if any(kw in w for kw in kws)) if _AIM.search(w) else []
    eviter = sorted(k for k, kws in AVOID.items() if any(kw in w for kw in kws)) if _NO.search(w) else []
    return {"jours_fermes": closed, "cible": cible, "eviter": eviter}


def _clean_rules(data: Any) -> Optional[Dict[str, List[Any]]]:
    if not isinstance(data, dict):
        return None
    days = [WEEKDAYS_FR.index(d) for d in (data.get("jours_fermes") or []) if isinstance(d, str) and d.lower() in WEEKDAYS_FR]
    return {"jours_fermes": sorted(set(days)),
            "cible": sorted({x for x in (data.get("cible") or []) if x in TARGETS}),
            "eviter": sorted({x for x in (data.get("eviter") or []) if x in AVOID})}


def _owner(tid: str) -> Optional[str]:
    u = _db.users.find_one({"tenant_id": tid, "role": "business_owner"}, {"_id": 0, "email": 1}, sort=[("created_at", 1)])
    return (u or {}).get("email")


def shop_facts(tid: str, by: Optional[str]) -> List[Dict[str, Any]]:
    """The owner's facts (the shop's truth), then the account's own."""
    owner = _owner(tid)
    out, seen = [], set()
    for who in [owner] + ([by] if by and by != owner else []):
        for f in facts(tid, who) if who else []:
            k = _fold(f.get("text"))
            if k not in seen:
                seen.add(k)
                out.append(f)
    return out


def memory_block(tid: str, by: Optional[str]) -> str:
    """What every AI that writes is told — scrubbed, within MEMO_CHARS."""
    lines, used = [], 0
    for f in shop_facts(tid, by):
        line = f"- {scrub(f['text'])}"
        if used + len(line) > MEMO_CHARS:
            break
        lines.append(line)
        used += len(line) + 1
    return ("Ce que le commerçant a dit à FidClic IA (à respecter) :\n" + "\n".join(lines)) if lines else ""


def constraints(tid: str, by: Optional[str] = None) -> Dict[str, Any]:
    """{closed: {0-6}, targets: {...}, avoid: {...}, said: {(kind, value): fact text}}."""
    out: Dict[str, Any] = {"closed": set(), "targets": set(), "avoid": set(), "said": {}}
    for f in shop_facts(tid, by):
        r = f.get("rules") or rules_of(f.get("text") or "")
        for kind, key, vals in (("closed", "jours_fermes", r.get("jours_fermes")), ("targets", "cible", r.get("cible")),
                                ("avoid", "eviter", r.get("eviter"))):
            for v in vals or []:
                out[kind].add(v)
                out["said"].setdefault((kind, v), f["text"])
    return out


_KEY_TARGETS = {"etudiants": {"etudiants"}, "proximite": {"quartier"}, "offre_locale": {"quartier"}, "seconde_visite": {"nouveaux"},
                "one_timers": {"nouveaux"}, "nouveaux_j7": {"nouveaux"}, "loyal": {"fideles"}, "palier_vip": {"fideles"},
                "familles": {"familles"}, "seniors": {"seniors"}}
_KEY_AVOID = {"offre_jour": {"offres"}, "anniversaires": {"anniversaires"}, "avis_google": {"avis_google"},
              "parrainage": {"parrainage"}, "relance_inactifs": {"relances"}, "a_risque": {"relances"}}


def _item_text(item: Dict[str, Any]) -> str:
    return _words(" ".join(str(item.get(k)) for k in ("title", "subtitle", "label", "description", "desc", "text")
                           if isinstance(item.get(k), str)))


def _item_days(item: Dict[str, Any], text: str) -> set:
    cta = item.get("cta") if isinstance(item.get("cta"), dict) else {}
    for v in (cta.get("day"), item.get("day"), item.get("weekday")):
        if isinstance(v, int) and 0 <= v <= 6:
            return {v}
    to = item.get("to") or cta.get("to")
    if isinstance(to, str) and (m := re.search(r"[?&]day=(\d)", to)):
        return {int(m.group(1))}
    days = {i for i, d in enumerate(WEEKDAYS_FR) if re.search(rf"\b{d}s?\b", text)}
    if re.search(r"\bweek ?end", text):
        days |= {5, 6}
    return days


def item_effect(item: Dict[str, Any], keys: Any, cons: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    """(multiplier, « Selon ce que vous avez dit : … ») — None: not shown (an
    advice for a day the shop is closed)."""
    if not (cons["closed"] or cons["targets"] or cons["avoid"]):
        return 1.0, None
    text = _item_text(item)
    days = _item_days(item, text)
    if days and days <= cons["closed"]:
        return None, None
    said = lambda kind, v: f"Selon ce que vous avez dit : « {scrub(cons['said'][(kind, v)])} »"   # noqa: E731
    keys = {k for k in ([keys] if isinstance(keys, str) or keys is None else keys) if k}   # its template and its own key
    targets = set().union(*(_KEY_TARGETS.get(k, set()) for k in keys)) | {k for k, kws in TARGETS.items() if any(kw in text for kw in kws)}
    hit = sorted(targets & cons["targets"])
    if hit:
        return 1.5, said("targets", hit[0])
    kinds = set().union(*(_KEY_AVOID.get(k, set()) for k in keys)) | {k for k, kws in AVOID.items() if any(kw in text for kw in kws)}
    hit = sorted(kinds & cons["avoid"])
    if hit:
        return 0.5, said("avoid", hit[0])
    return 1.0, None


def _rules_pass(budget: List[int], deadline: float, out: Dict[str, Any]) -> None:
    """Each fact read once by the model for its firm facts (closed days,
    clients aimed at, offers not wanted)."""
    todo = list(_db.copilot_memory.find({"rules_by": {"$ne": "ia"}}, {"_id": 0, "id": 1, "text": 1})
                .sort("updated_at", 1).limit(max(0, budget[0])))
    if not todo:
        return
    replies = _run([(_RULES_SYSTEM, f"Phrase : {scrub(f.get('text') or '')}", 120) for f in todo], deadline)
    for f, reply in zip(todo, replies):
        if reply is _SKIP:
            continue
        budget[0] -= 1
        if reply is None or isinstance(reply, Exception):
            out["failures"] += 1
            continue
        m = re.search(r"\{.*\}", str(reply), re.DOTALL)
        try:
            rules = _clean_rules(json.loads(m.group(0))) if m else None
        except Exception:
            rules = None
        if rules is None:
            out["failures"] += 1
            continue
        _db.copilot_memory.update_one({"id": f["id"], "text": f["text"]}, {"$set": {"rules": rules, "rules_by": "ia"}})
        out["rules"] = out.get("rules", 0) + 1


# ---------------------------------------------------------------------------
# « Ce que FidClic IA retient » — each account's own list
# ---------------------------------------------------------------------------
class FactIn(BaseModel):
    text: str


def _text(body: FactIn) -> str:
    t = _clean_fact(body.text)
    if not t:
        raise HTTPException(status_code=400, detail="Écrivez ce que FidClic IA doit retenir.")
    if len(t) > FACT_MAX:
        raise HTTPException(status_code=400, detail=f"{FACT_MAX} caractères au plus.")
    return t


def _writable(token_data: TokenData) -> None:
    if getattr(token_data, "view_only", False):
        raise HTTPException(status_code=403, detail="Accès en lecture seule.")


def _mine(token_data: TokenData, fid: str) -> Dict[str, Any]:
    f = _db.copilot_memory.find_one({"id": fid, "tenant_id": token_data.tenant_id, "by": token_data.email}, {"_id": 0})
    if not f:
        raise HTTPException(status_code=404, detail="Introuvable.")
    return f


@router.get("/api/me/ai-memory")
def list_memory(token_data: TokenData = Depends(require_role(ROLES, partial_ok=True))):
    items = [_public(f) for f in facts(token_data.tenant_id, token_data.email)]
    return {"items": items, "count": len(items), "max_chars": FACT_MAX}


@router.post("/api/me/ai-memory")
def add_memory(body: FactIn, token_data: TokenData = Depends(require_role(ROLES, partial_ok=True))):
    _writable(token_data)
    t = _text(body)
    doc = add(token_data.tenant_id, token_data.email, t, "vous")
    if doc is None:
        same = next((f for f in facts(token_data.tenant_id, token_data.email) if _fold(f["text"]) == _fold(t)), None)
        if same:
            return {"item": _public(same), "already": True}
        raise HTTPException(status_code=400, detail="La mémoire de ce compte est pleine : supprimez un élément.")
    return {"item": _public(doc)}


@router.patch("/api/me/ai-memory/{fid}")
def edit_memory(fid: str, body: FactIn, token_data: TokenData = Depends(require_role(ROLES, partial_ok=True))):
    _writable(token_data)
    f = _mine(token_data, fid)
    t = _text(body)
    if _fold(t) != _fold(f.get("text")):
        forget(f)                                  # the old wording leaves what the model reads
    _db.copilot_memory.update_one({"id": f["id"], "tenant_id": f["tenant_id"], "by": f["by"]},
                                  {"$set": {"text": t, "updated_at": NOW(), "src_at": [],
                                            "rules": rules_of(t), "rules_by": "regle"}})
    return {"item": _public(_mine(token_data, fid))}


@router.delete("/api/me/ai-memory/{fid}")
def delete_memory(fid: str, token_data: TokenData = Depends(require_role(ROLES, partial_ok=True))):
    _writable(token_data)
    f = _mine(token_data, fid)
    forget(f)
    _db.copilot_memory.delete_one({"id": f["id"], "tenant_id": f["tenant_id"], "by": f["by"]})
    return {"ok": True}
