"""
CRM › Séquences d'emails and Modèles d'emails — prospecting e-mails sent from
FidClic's own Gmail / Google Workspace account (decided with the user).

SETUP (Vercel env, nothing is stored in the database)
    CRM_SMTP_USER   the Gmail address that sends (e.g. contact@fidclic.com)
    CRM_SMTP_PASS   its App password (Google account › Sécurité › Mots de
                    passe des applications — 16 letters)
    optional        CRM_SMTP_HOST (smtp.gmail.com), CRM_SMTP_PORT (587),
                    CRM_IMAP_HOST (imap.gmail.com), CRM_DAILY_LIMIT (450 —
                    Gmail allows 500 a day, Workspace 2 000), PUBLIC_APP_URL.

    crm_email_templates  reusable e-mails ({prenom}, {commerce}… variables)
    crm_sequences        a series of steps: « Jour 3 — 10:00 », subject, body
    crm_enrollments      one prospect going through one sequence
    crm_email_sends      every e-mail sent, with opens, clicks and replies

WHEN MAILS LEAVE
    Steps are due at their day and hour, Paris time. Due mails are sent by
    run_due(): every day with the platform cron, whenever someone opens the
    Séquences page, and on « Envoyer maintenant ». At most CRM_DAILY_LIMIT
    a day; the rest waits for the next day.

WHAT STOPS A PROSPECT'S SEQUENCE
    a reply (read over IMAP with the same App password — only the headers of
    mails from known prospects are read, nothing else is kept), an
    unsubscribe, becoming a FidClic client, being marked lost, or no e-mail.

THE LAW (B2B prospecting, CNIL): the sender is named in every mail, with
FidClic's legal name and address (Super admin › Facturation) and a one-click
unsubscribe link; an unsubscribed business is never mailed again.

TRACKING: an invisible image counts opens (approximate — some mail apps
block or pre-load images), links go through FidClic to count clicks.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import imaplib
import os
import re
import smtplib
import time as _time
import uuid
from datetime import datetime, time, timedelta, timezone
from email.message import EmailMessage
from email.parser import HeaderParser
from email.utils import formataddr, getaddresses, make_msgid, parsedate_to_datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from auth import require_role, TokenData, SECRET_KEY
from features.platform_access import require_admin, require_super
from features import crm as C

router = APIRouter(tags=["crm"])
_db = None

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:          # no tzdata in the image: the EU summer-time rule below
    PARIS = None

SEQ_STATUSES = [("active", "Active"), ("pause", "En pause"), ("terminee", "Terminée"), ("brouillon", "Brouillon")]
ENR_STATUSES = {"en_cours": "En cours", "termine": "Terminé", "repondu": "A répondu", "desinscrit": "Désinscrit",
                "arrete": "Arrêté", "erreur": "Erreur"}
VARIABLES = [("prenom", "Prénom du contact"), ("contact", "Nom complet du contact"), ("commerce", "Nom du commerce"),
             ("ville", "Ville"), ("secteur", "Secteur"), ("expediteur", "Votre nom")]
TO_FILL = re.compile(r"\[[^\]]*compl[ée]ter[^\]]*\]", re.I)
GIF = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")

DEFAULT_TEMPLATES = [
    {"id": "tpl-intro", "name": "Email d'introduction", "category": "Prise de contact",
     "subject": "{commerce} : fidélisez vos clients avec une carte 100 % digitale",
     "body": "Bonjour {prenom},\n\nJe suis {expediteur}, de FidClic. Nous aidons les commerces comme {commerce} à faire "
             "revenir leurs clients plus souvent, grâce à une carte de fidélité 100 % digitale.\n\nConcrètement :\n"
             "- vos clients ajoutent la carte à leur téléphone en scannant un QR code, sans application à télécharger ;\n"
             "- vous leur envoyez des offres et des rappels au bon moment ;\n- vous voyez qui revient, et quand.\n\n"
             "L'essai est gratuit pendant 30 jours, sans carte bancaire.\n\nAuriez-vous 15 minutes cette semaine pour que "
             "je vous montre ?\n\nBien cordialement,\n{expediteur}\nFidClic"},
    {"id": "tpl-valeur", "name": "Relance valeur", "category": "Relance",
     "subject": "Un outil simple pour plus de clients fidèles",
     "body": "Bonjour {prenom},\n\nJe reviens vers vous au sujet de FidClic. Un client fidèle revient plus souvent : c'est "
             "souvent le levier le plus simple pour faire grandir un commerce.\n\nAvec FidClic, la mise en place prend une "
             "dizaine de minutes : vous choisissez votre récompense, vous affichez le QR code en caisse, et c'est parti.\n\n"
             "Voulez-vous que je vous prépare une carte aux couleurs de {commerce} pour voir le rendu ?\n\n"
             "Bien cordialement,\n{expediteur}"},
    {"id": "tpl-cas", "name": "Cas client", "category": "Cas client",
     "subject": "Comment [À COMPLÉTER : nom du commerce client] fait revenir ses clients",
     "body": "Bonjour {prenom},\n\nJe voulais vous partager l'exemple de [À COMPLÉTER : nom du commerce client], un commerce "
             "proche du vôtre.\n\n[À COMPLÉTER : ce qu'il a mis en place avec FidClic et le résultat obtenu, avec ses vrais "
             "chiffres.]\n\nJe serais ravi de vous montrer comment faire la même chose chez {commerce}.\n\n"
             "Bien cordialement,\n{expediteur}"},
    {"id": "tpl-demo", "name": "Proposition de démonstration", "category": "Démonstration",
     "subject": "15 minutes pour vous montrer FidClic ?",
     "body": "Bonjour {prenom},\n\nJe vous propose une courte démonstration de FidClic, sur place chez {commerce} ou par "
             "téléphone : 15 minutes suffisent pour voir la carte, les offres et les statistiques.\n\nQuel moment vous "
             "arrange le mieux, cette semaine ou la suivante ?\n\nBien cordialement,\n{expediteur}"},
    {"id": "tpl-derniere", "name": "Dernière relance", "category": "Relance",
     "subject": "On reste en contact ?",
     "body": "Bonjour {prenom},\n\nJe ne veux pas encombrer votre boîte mail : ce sera mon dernier message à ce sujet.\n\n"
             "Si fidéliser vos clients devient une priorité pour {commerce}, il suffit de répondre à cet email et je reviens "
             "vers vous. L'essai gratuit de 30 jours reste disponible.\n\nJe vous souhaite une excellente continuation,\n"
             "{expediteur}"},
]
SEQUENCE_PRESETS = [
    {"key": "prise-de-contact", "name": "Prise de contact — 5 emails",
     "description": "Présentation, valeur, cas client, démo, dernière relance, sur 20 jours.",
     "steps": [(1, "09:00", "tpl-intro"), (3, "10:00", "tpl-valeur"), (7, "09:00", "tpl-cas"), (12, "10:00", "tpl-demo"),
               (20, "09:00", "tpl-derniere")]},
    {"key": "relance-courte", "name": "Relance courte — 3 emails",
     "description": "Présentation, proposition de démo, dernière relance, sur 10 jours.",
     "steps": [(1, "09:00", "tpl-intro"), (4, "10:00", "tpl-demo"), (10, "09:00", "tpl-derniere")]},
]


def init(db):
    global _db
    _db = db
    try:
        db.crm_sequences.create_index("id", unique=True)
        db.crm_email_templates.create_index("id", unique=True)
        db.crm_enrollments.create_index([("status", 1), ("next_at", 1)])
        db.crm_enrollments.create_index([("sequence_id", 1), ("prospect_id", 1)])
        db.crm_email_sends.create_index("id", unique=True)
        db.crm_email_sends.create_index([("sent_at", -1)])
        db.crm_email_sends.create_index("message_id")
    except Exception:
        pass
    if not db.platform_settings.find_one({"key": "crm_templates_seeded"}):
        for t in DEFAULT_TEMPLATES:
            if not db.crm_email_templates.find_one({"id": t["id"]}):
                db.crm_email_templates.insert_one({**t, "created_by": "system", "created_at": C._now(), "updated_at": C._now()})
        db.platform_settings.update_one({"key": "crm_templates_seeded"}, {"$set": {"key": "crm_templates_seeded", "at": C._now()}},
                                        upsert=True)


# ---------------------------------------------------------------------------
# Config, time, links
# ---------------------------------------------------------------------------
def _cfg() -> Optional[Dict[str, Any]]:
    user, pw = os.getenv("CRM_SMTP_USER", "").strip(), os.getenv("CRM_SMTP_PASS", "").replace(" ", "").strip()
    if not user or not pw:
        return None
    return {"user": user, "pass": pw, "host": os.getenv("CRM_SMTP_HOST", "smtp.gmail.com"),
            "port": int(os.getenv("CRM_SMTP_PORT", "587") or 587), "imap": os.getenv("CRM_IMAP_HOST", "imap.gmail.com"),
            "limit": int(os.getenv("CRM_DAILY_LIMIT", "450") or 450)}


def _base() -> str:
    return os.getenv("PUBLIC_APP_URL", "").rstrip("/") or "https://app.fidclic.com"


def _summer(d: datetime) -> bool:
    def last_sunday(month: int) -> datetime:
        x = datetime(d.year, month, 31, 1, tzinfo=timezone.utc)
        return x - timedelta(days=(x.weekday() + 1) % 7)
    return last_sunday(3) <= d < last_sunday(10)


def _local(d: datetime) -> datetime:
    """UTC → Paris wall clock (naive)."""
    d = C._aware(d)
    if PARIS:
        return d.astimezone(PARIS).replace(tzinfo=None)
    return (d + timedelta(hours=2 if _summer(d) else 1)).replace(tzinfo=None)


def _utc(naive: datetime) -> datetime:
    """Paris wall clock (naive) → UTC."""
    if PARIS:
        return naive.replace(tzinfo=PARIS).astimezone(timezone.utc)
    guess = naive.replace(tzinfo=timezone.utc) - timedelta(hours=1)
    return guess - timedelta(hours=1 if _summer(guess) else 0)


def _at(day: datetime, hhmm: str) -> datetime:
    h, m = (int(x) for x in (hhmm or "09:00").split(":")[:2])
    return _utc(datetime.combine(day.date(), time(h, m)))


def _today_start() -> datetime:
    return _utc(datetime.combine(_local(C._now()).date(), time(0, 0)))


def _sig(*parts: str) -> str:
    return hmac.new(SECRET_KEY.encode(), "|".join(parts).encode(), hashlib.sha256).hexdigest()[:20]


def _issuer_line() -> str:
    v = (_db.platform_settings.find_one({"key": "invoice_issuer"}, {"_id": 0}) or {}).get("value") or {}
    addr = ", ".join(x for x in (v.get("address"), " ".join(y for y in (v.get("postal_code"), v.get("city")) if y)) if x)
    return " — ".join(x for x in (v.get("legal_name") or "FidClic", addr) if x)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _vars(p: Dict[str, Any], sender: str) -> Dict[str, str]:
    contact = (p.get("contact_name") or "").strip()
    return {"prenom": contact.split()[0] if contact else "", "contact": contact, "commerce": p.get("name") or "",
            "ville": p.get("city") or "", "secteur": p.get("sector") or "", "expediteur": sender}


def fill(text: str, values: Dict[str, str]) -> str:
    def one(m):
        v = values.get(m.group(2).lower())
        if v is None:
            return m.group(0)
        return (m.group(1) + v) if v else ""          # an empty value takes its leading space with it
    return re.sub(r"( ?)\{(\w+)\}", one, text or "")


def _check_text(*texts: str) -> None:
    known = {k for k, _ in VARIABLES}
    for t in texts:
        for v in re.findall(r"\{(\w+)\}", t or ""):
            if v.lower() not in known:
                raise HTTPException(status_code=400, detail=f"Variable inconnue : {{{v}}}. Disponibles : "
                                    + ", ".join("{" + k + "}" for k in sorted(known)))


def _unfinished(*texts: str) -> bool:
    return any(TO_FILL.search(t or "") for t in texts)


def _track(url: str, sid: str) -> str:
    return f"{_base()}/api/crm/t/c/{sid}?u={quote(url, safe='')}&s={_sig(sid, url)}"


def render(subject: str, body: str, p: Dict[str, Any], sender: str, sid: str) -> Dict[str, str]:
    values = _vars(p, sender)
    subj, text = fill(subject, values).strip(), fill(body, values).strip()
    unsub = f"{_base()}/api/crm/u/{sid}"
    esc = html.escape(text)

    def link(m):
        raw = html.unescape(m.group(1))
        return f'<a href="{html.escape(_track(raw, sid))}" style="color:#2F6BFF">{m.group(1)}</a>'
    esc = re.sub(r"(https?://[^\s<]+)", link, esc)
    paras = "".join(f'<p style="margin:0 0 14px">{para.replace(chr(10), "<br>")}</p>' for para in re.split(r"\n\s*\n", esc))
    footer = (f'<p style="margin:24px 0 0;font-size:11px;color:#94A3B8">{html.escape(_issuer_line())}<br>'
              f'Vous recevez ce message car nous pensons que FidClic peut intéresser votre commerce. '
              f'<a href="{unsub}" style="color:#94A3B8">Ne plus recevoir nos emails</a></p>')
    pixel = f'<img src="{_base()}/api/crm/t/o/{sid}.gif" width="1" height="1" alt="" style="display:block;border:0">'
    body_html = (f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.55;color:#0B1C3F;'
                 f'max-width:620px">{paras}{footer}{pixel}</div>')
    body_text = f"{text}\n\n--\n{_issuer_line()}\nNe plus recevoir nos emails : {unsub}"
    return {"subject": subj, "html": body_html, "text": body_text, "unsubscribe": unsub}


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------
def _open_smtp(cfg: Dict[str, Any]):
    s = smtplib.SMTP(cfg["host"], cfg["port"], timeout=20)
    s.starttls()
    s.login(cfg["user"], cfg["pass"])
    return s


class _Mailer:
    def __init__(self, cfg):
        self.cfg, self.s = cfg, None

    def send(self, msg: EmailMessage) -> None:
        if self.s is None:
            self.s = _open_smtp(self.cfg)
        self.s.send_message(msg)

    def close(self) -> None:
        try:
            if self.s is not None:
                self.s.quit()
        except Exception:
            pass


def _sender_name(email: Optional[str]) -> str:
    u = C._users().get(email or "")
    return C._name(u) if u else "L'équipe FidClic"


def _sent_today() -> int:
    return _db.crm_email_sends.count_documents({"status": "sent", "sent_at": {"$gte": _today_start()}})


def _deliver(mailer: _Mailer, p: Dict[str, Any], subject: str, body: str, by: Optional[str],
             **link: Any) -> Dict[str, Any]:
    """Render, send and record one e-mail to one prospect."""
    cfg = mailer.cfg
    sid = uuid.uuid4().hex
    sender = _sender_name(by)
    r = render(subject, body, p, sender, sid)
    msg = EmailMessage()
    msg["From"] = formataddr((f"{sender} · FidClic" if by else "FidClic", cfg["user"]))
    msg["To"] = p["email"]
    msg["Subject"] = r["subject"]
    mid = make_msgid(domain=(cfg["user"].split("@")[-1] or "fidclic.com"))
    msg["Message-ID"] = mid
    msg["List-Unsubscribe"] = f"<{r['unsubscribe']}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(r["text"])
    msg.add_alternative(r["html"], subtype="html")
    rec = {"id": sid, "prospect_id": p["id"], "to": p["email"], "subject": r["subject"], "by": by, "message_id": mid,
           "opens": 0, "clicks": 0, "opened_at": None, "clicked_at": None, "replied_at": None, **link}
    try:
        mailer.send(msg)
    except Exception as exc:
        _db.crm_email_sends.insert_one({**rec, "status": "failed", "error": str(exc)[:300], "sent_at": C._now()})
        raise
    _db.crm_email_sends.insert_one({**rec, "status": "sent", "sent_at": C._now()})
    C._log(p["id"], "email", f"Email envoyé : {r['subject']}", by, send_id=sid, sequence_id=link.get("sequence_id"))
    return rec


def _lock(key: str, seconds: int) -> bool:
    now = C._now()
    _db.platform_settings.update_one({"key": key}, {"$setOnInsert": {"key": key, "until": now - timedelta(seconds=1)}}, upsert=True)
    got = _db.platform_settings.find_one_and_update({"key": key, "until": {"$lt": now}},
                                                    {"$set": {"until": now + timedelta(seconds=seconds)}})
    return got is not None


def _unlock(key: str) -> None:
    _db.platform_settings.update_one({"key": key}, {"$set": {"until": C._now() - timedelta(seconds=1)}})


def _stop(e: Dict[str, Any], status: str, why: str = "") -> None:
    _db.crm_enrollments.update_one({"id": e["id"]}, {"$set": {"status": status, "stopped_reason": why, "next_at": None,
                                                              "updated_at": C._now()}})


def _schedule_next(e: Dict[str, Any], seq: Dict[str, Any], sent_at: datetime) -> None:
    steps = seq.get("steps") or []
    nxt = e["step"] + 1
    if nxt >= len(steps):
        _db.crm_enrollments.update_one({"id": e["id"]}, {"$set": {"step": nxt, "status": "termine", "next_at": None,
                                                                  "updated_at": C._now()}})
        return
    gap = max(0, int(steps[nxt]["day"]) - int(steps[e["step"]]["day"]))
    due = _at(_local(sent_at) + timedelta(days=gap), steps[nxt]["time"])
    _db.crm_enrollments.update_one({"id": e["id"]}, {"$set": {"step": nxt, "next_at": max(due, sent_at + timedelta(hours=1)),
                                                              "updated_at": C._now()}})


def run_due(max_send: int = 40, budget_s: float = 8.0) -> Dict[str, Any]:
    """Send every step that is due, within the day's limit."""
    cfg = _cfg()
    if not cfg:
        return {"sent": 0, "reason": "not_configured"}
    if not _lock("crm_mail_lock", 120):
        return {"sent": 0, "reason": "busy"}
    started, sent, failed = _time.monotonic(), 0, 0
    mailer = _Mailer(cfg)
    try:
        left = cfg["limit"] - _sent_today()
        if left <= 0:
            return {"sent": 0, "reason": "daily_limit"}
        seqs = {s["id"]: s for s in _db.crm_sequences.find({"status": "active"}, {"_id": 0})}
        due = list(_db.crm_enrollments.find({"status": "en_cours", "next_at": {"$lte": C._now()},
                                             "sequence_id": {"$in": list(seqs)}}, {"_id": 0})
                   .sort("next_at", 1).limit(max_send))
        for e in due:
            if _time.monotonic() - started > budget_s or sent >= left:
                break
            seq = seqs[e["sequence_id"]]
            steps = seq.get("steps") or []
            p = _db.crm_prospects.find_one({"id": e["prospect_id"]}, {"_id": 0})
            if not p:
                _stop(e, "arrete", "Prospect supprimé"); continue
            if p.get("email_opt_out"):
                _stop(e, "desinscrit", "Désinscrit"); continue
            if p.get("stage") in ("essai", "signe"):
                _stop(e, "arrete", "Devenu client"); continue
            if p.get("stage") == "perdu":
                _stop(e, "arrete", "Marqué perdu"); continue
            if not p.get("email"):
                _stop(e, "arrete", "Pas d'email"); continue
            if e["step"] >= len(steps):
                _stop(e, "termine"); continue
            st = steps[e["step"]]
            if _unfinished(st.get("subject"), st.get("body")):
                continue                                   # activation refuses this; belt and braces
            try:
                _deliver(mailer, p, st["subject"], st["body"], seq.get("created_by"), sequence_id=seq["id"],
                         step_id=st["id"], enrollment_id=e["id"], template_id=st.get("template_id"))
            except smtplib.SMTPAuthenticationError as exc:
                _db.platform_settings.update_one({"key": "crm_mail_error"}, {"$set": {"key": "crm_mail_error", "at": C._now(),
                                                                                       "error": "Gmail refuse la connexion : vérifiez CRM_SMTP_USER et le mot de passe d'application."}}, upsert=True)
                failed += 1
                print(f"crm mail: auth failed ({exc})")
                break
            except Exception as exc:
                failed += 1
                tries = int(e.get("errors") or 0) + 1
                if tries >= 3:
                    _stop(e, "erreur", f"Envoi impossible : {str(exc)[:120]}")
                else:
                    _db.crm_enrollments.update_one({"id": e["id"]}, {"$set": {"errors": tries, "next_at": C._now() + timedelta(hours=1)}})
                continue
            sent += 1
            now = C._now()
            _db.crm_sequences.update_one({"id": seq["id"]}, {"$set": {"last_activity_at": now}})
            _schedule_next(e, seq, now)
        if sent:
            _db.platform_settings.delete_one({"key": "crm_mail_error"})
    finally:
        mailer.close()
        _unlock("crm_mail_lock")
    return {"sent": sent, "failed": failed}


# ---------------------------------------------------------------------------
# Replies (IMAP, headers only)
# ---------------------------------------------------------------------------
def _open_imap(cfg: Dict[str, Any]):
    m = imaplib.IMAP4_SSL(cfg["imap"], 993)
    m.login(cfg["user"], cfg["pass"])
    return m


def _on_reply(send: Dict[str, Any], subject: str, at: datetime, mid: str) -> None:
    _db.crm_email_sends.update_one({"id": send["id"]}, {"$set": {"replied_at": at, "reply_message_id": mid}})
    p = _db.crm_prospects.find_one({"id": send["prospect_id"]}, {"_id": 0}) or {}
    if send.get("enrollment_id"):
        seq = _db.crm_sequences.find_one({"id": send.get("sequence_id")}, {"_id": 0, "stop_on_reply": 1}) or {}
        if seq.get("stop_on_reply", True):
            e = _db.crm_enrollments.find_one({"id": send["enrollment_id"], "status": "en_cours"})
            if e:
                _stop(e, "repondu", "A répondu")
    if not p:
        return
    C._log(p["id"], "email_reply", f"Réponse reçue : {subject or '(sans objet)'}", None, send_id=send["id"], message_id=mid,
           at=at)
    if not p.get("tenant_id") and (p.get("stage") or "nouveau") in ("nouveau", "a_contacter"):
        _db.crm_prospects.update_one({"id": p["id"]}, {"$set": {"stage": "contacte", "updated_at": C._now()}})
        C._log(p["id"], "stage", "Étape : Contacté (a répondu à un email)", None, frm=p.get("stage"), to="contacte")
    _db.crm_tasks.insert_one({"id": uuid.uuid4().hex, "title": f"Répondre à {p.get('name')}", "type": "email",
                              "priority": "haute", "due_at": C._now() + timedelta(hours=2), "prospect_id": p["id"],
                              "assigned_to": send.get("by") or p.get("assigned_to"), "status": "a_faire",
                              "description": f"Réponse à « {send.get('subject')} » : {subject}", "duration_min": 15,
                              "confirm_status": "a_confirmer", "created_by": "system", "created_at": C._now()})


def match_reply(h: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Which of our e-mails does this incoming message answer? None for
    auto-replies, our own mail and strangers."""
    cfg = _cfg() or {}
    if (h.get("auto-submitted") or "no").lower() not in ("", "no") or h.get("x-autoreply") or h.get("x-autorespond"):
        return None
    if re.match(r"^\s*(réponse automatique|automatic reply|auto(matic)?[- ]?reply|out of office|absence)", h.get("subject") or "", re.I):
        return None
    refs = re.findall(r"<[^>]+>", (h.get("in-reply-to") or "") + " " + (h.get("references") or ""))
    for ref in refs:
        s = _db.crm_email_sends.find_one({"message_id": ref, "status": "sent"}, {"_id": 0})
        if s:
            return s
    addrs = [a.lower() for _, a in getaddresses([h.get("from") or ""]) if a]
    if not addrs or addrs[0] == (cfg.get("user") or "").lower():
        return None
    rx = {"$regex": f"^{re.escape(addrs[0])}$", "$options": "i"}
    return _db.crm_email_sends.find_one({"to": rx, "status": "sent", "sent_at": {"$gte": C._now() - timedelta(days=90)}},
                                        {"_id": 0}, sort=[("sent_at", -1)])


def check_replies(force: bool = False) -> Dict[str, Any]:
    cfg = _cfg()
    if not cfg:
        return {"replies": 0, "reason": "not_configured"}
    state = _db.platform_settings.find_one({"key": "crm_imap_state"}) or {}
    last = C._aware(state.get("checked_at"))
    if not force and last and C._now() - last < timedelta(minutes=10):
        return {"replies": 0, "reason": "recent"}
    if not _lock("crm_imap_lock", 120):
        return {"replies": 0, "reason": "busy"}
    found = 0
    try:
        since = (last or C._now() - timedelta(days=14)) - timedelta(days=1)
        m = _open_imap(cfg)
        try:
            m.select("INBOX", readonly=True)
            typ, data = m.search(None, "SINCE", since.strftime("%d-%b-%Y"))
            ids = (data[0] or b"").split()[-500:]
            for i in range(0, len(ids), 50):
                chunk = b",".join(ids[i:i + 50]).decode()
                typ, parts = m.fetch(chunk, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES "
                                            "AUTO-SUBMITTED X-AUTOREPLY X-AUTORESPOND)])")
                for part in parts or []:
                    if not isinstance(part, tuple):
                        continue
                    msg = HeaderParser().parsestr(part[1].decode("utf-8", errors="replace"))
                    h = {k.lower(): str(v) for k, v in msg.items()}
                    mid = h.get("message-id") or ""
                    if mid and _db.crm_email_sends.find_one({"reply_message_id": mid}):
                        continue
                    s = match_reply(h)
                    if not s or s.get("replied_at"):
                        continue
                    try:
                        at = C._aware(parsedate_to_datetime(h.get("date"))) or C._now()
                    except Exception:
                        at = C._now()
                    _on_reply(s, _decode(h.get("subject") or ""), at, mid)
                    found += 1
        finally:
            try:
                m.logout()
            except Exception:
                pass
        _db.platform_settings.update_one({"key": "crm_imap_state"}, {"$set": {"key": "crm_imap_state", "checked_at": C._now(),
                                                                                 "error": None}}, upsert=True)
    except Exception as exc:
        _db.platform_settings.update_one({"key": "crm_imap_state"}, {"$set": {"key": "crm_imap_state", "checked_at": C._now(),
                                                                                 "error": str(exc)[:200]}}, upsert=True)
        print(f"crm imap: {exc}")
    finally:
        _unlock("crm_imap_lock")
    return {"replies": found}


def _decode(v: str) -> str:
    from email.header import decode_header, make_header
    try:
        return str(make_header(decode_header(v)))
    except Exception:
        return v


def daily() -> Dict[str, Any]:
    """Called by the platform's daily cron."""
    return {"replies": check_replies(force=True), "sent": run_due(max_send=400, budget_s=240)}


# ---------------------------------------------------------------------------
# Public: tracking and unsubscribe (no login — reached from the e-mail)
# ---------------------------------------------------------------------------
@router.get("/api/crm/t/o/{sid}.gif")
def track_open(sid: str):
    s = _db.crm_email_sends.find_one({"id": sid}, {"_id": 0, "opened_at": 1})
    if s is not None:
        _db.crm_email_sends.update_one({"id": sid}, {"$inc": {"opens": 1},
                                                     **({"$set": {"opened_at": C._now()}} if not s.get("opened_at") else {})})
    return Response(content=GIF, media_type="image/gif", headers={"Cache-Control": "no-store, max-age=0"})


@router.get("/api/crm/t/c/{sid}")
def track_click(sid: str, u: str = "", s: str = ""):
    if not u.startswith(("http://", "https://")) or not hmac.compare_digest(s, _sig(sid, u)):
        raise HTTPException(status_code=400, detail="Lien invalide")
    rec = _db.crm_email_sends.find_one({"id": sid}, {"_id": 0, "clicked_at": 1, "opened_at": 1})
    if rec is not None:
        sets = {} if rec.get("clicked_at") else {"clicked_at": C._now()}
        if not rec.get("opened_at"):
            sets["opened_at"] = C._now()               # a click proves the open the pixel may have missed
        _db.crm_email_sends.update_one({"id": sid}, {"$inc": {"clicks": 1}, **({"$set": sets} if sets else {})})
    return RedirectResponse(u, status_code=302)


def _page(title: str, text: str, form: str = "") -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title></head><body style="margin:0;background:#F4F7FC;font-family:Arial,Helvetica,sans-serif;color:#0B1C3F">
<main style="max-width:460px;margin:12vh auto;background:#fff;border-radius:16px;padding:32px;box-shadow:0 10px 30px -18px rgba(11,28,63,.35)">
<p style="margin:0 0 6px;color:#2F6BFF;font-weight:700">FidClic</p><h1 style="font-size:22px;margin:0 0 12px">{html.escape(title)}</h1>
<p style="color:#475569;line-height:1.5">{html.escape(text)}</p>{form}</main></body></html>""")


def _opt_out(sid: str) -> bool:
    s = _db.crm_email_sends.find_one({"id": sid}, {"_id": 0})
    if not s:
        return False
    p = _db.crm_prospects.find_one({"id": s["prospect_id"]}, {"_id": 0, "id": 1, "email_opt_out": 1})
    if p and not p.get("email_opt_out"):
        _db.crm_prospects.update_one({"id": p["id"]}, {"$set": {"email_opt_out": True, "opted_out_at": C._now()}})
        C._log(p["id"], "unsubscribe", "Désinscrit des emails de prospection", None, send_id=sid)
    for e in _db.crm_enrollments.find({"prospect_id": s["prospect_id"], "status": "en_cours"}, {"_id": 0}):
        _stop(e, "desinscrit", "Désinscrit")
    return True


@router.get("/api/crm/u/{sid}")
def unsubscribe_page(sid: str):
    if not _db.crm_email_sends.find_one({"id": sid}):
        return _page("Lien expiré", "Ce lien de désinscription n'est plus valable.")
    form = (f'<form method="post" action="/api/crm/u/{html.escape(sid)}"><button type="submit" style="margin-top:12px;'
            'background:#2F6BFF;color:#fff;border:0;border-radius:10px;padding:12px 18px;font-size:15px;cursor:pointer">'
            'Confirmer la désinscription</button></form>')
    return _page("Ne plus recevoir nos emails", "Confirmez pour ne plus recevoir aucun email de prospection de FidClic.", form)


@router.post("/api/crm/u/{sid}")
def unsubscribe(sid: str):
    if not _opt_out(sid):
        return _page("Lien expiré", "Ce lien de désinscription n'est plus valable.")
    return _page("C'est fait", "Vous ne recevrez plus d'emails de prospection de FidClic. Merci et bonne continuation !")


# ---------------------------------------------------------------------------
# Status, test, one-off e-mail, preview
# ---------------------------------------------------------------------------
@router.get("/api/crm/email/status")
def email_status(token_data: TokenData = Depends(require_admin("crm"))):
    cfg = _cfg()
    err = (_db.platform_settings.find_one({"key": "crm_mail_error"}, {"_id": 0}) or {}).get("error")
    imap = _db.platform_settings.find_one({"key": "crm_imap_state"}, {"_id": 0}) or {}
    return {"configured": bool(cfg), "sender": cfg["user"] if cfg else None, "daily_limit": cfg["limit"] if cfg else None,
            "sent_today": _sent_today(), "error": err, "replies_checked_at": C._iso(imap.get("checked_at")),
            "replies_error": imap.get("error"), "issuer": _issuer_line(), "variables": [{"key": k, "label": l} for k, l in VARIABLES]}


def _need_cfg() -> Dict[str, Any]:
    cfg = _cfg()
    if not cfg:
        raise HTTPException(status_code=409, detail="Gmail n'est pas encore connecté (CRM_SMTP_USER et CRM_SMTP_PASS dans Vercel).")
    return cfg


class TestIn(BaseModel):
    to: str = Field(..., max_length=200)


@router.post("/api/crm/email/test")
def email_test(body: TestIn, token_data: TokenData = Depends(require_super())):
    cfg = _need_cfg()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = formataddr(("FidClic", cfg["user"])), body.to.strip(), "Test — CRM FidClic"
    msg.set_content("Ceci est un test : les emails de prospection partent bien de ce compte Gmail.")
    m = _Mailer(cfg)
    try:
        m.send(msg)
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=400, detail="Gmail refuse la connexion : vérifiez l'adresse et le mot de passe d'application.")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Envoi impossible : {str(exc)[:120]}")
    finally:
        m.close()
    return {"ok": True}


class PreviewIn(BaseModel):
    subject: str = ""
    body: str = ""
    prospect_id: Optional[str] = None


SAMPLE = {"id": "exemple", "name": "Café Lumière", "contact_name": "Thomas Durand", "city": "Tours", "sector": "Café"}


@router.post("/api/crm/email/preview")
def email_preview(body: PreviewIn, token_data: TokenData = Depends(require_admin("crm", write=False))):
    p = (_db.crm_prospects.find_one({"id": body.prospect_id}, {"_id": 0}) if body.prospect_id else None) or SAMPLE
    r = render(body.subject, body.body, p, _sender_name(token_data.email), "apercu")
    return {"subject": r["subject"], "html": r["html"], "prospect": p.get("name"),
            "unfinished": _unfinished(body.subject, body.body)}


class SendIn(BaseModel):
    prospect_id: str
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=20000)
    template_id: Optional[str] = None


@router.post("/api/crm/email/send")
def email_send(body: SendIn, token_data: TokenData = Depends(require_admin("crm"))):
    cfg = _need_cfg()
    _check_text(body.subject, body.body)
    if _unfinished(body.subject, body.body):
        raise HTTPException(status_code=400, detail="Complétez d'abord les passages [À COMPLÉTER].")
    p = _db.crm_prospects.find_one({"id": body.prospect_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Prospect introuvable")
    if not p.get("email"):
        raise HTTPException(status_code=400, detail="Ce commerce n'a pas d'email.")
    if p.get("email_opt_out"):
        raise HTTPException(status_code=409, detail="Ce commerce s'est désinscrit : on ne lui écrit plus.")
    if _sent_today() >= cfg["limit"]:
        raise HTTPException(status_code=429, detail="Limite d'envoi du jour atteinte. Réessayez demain.")
    m = _Mailer(cfg)
    try:
        rec = _deliver(m, p, body.subject, body.body, token_data.email, template_id=body.template_id)
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=400, detail="Gmail refuse la connexion : vérifiez le mot de passe d'application.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Envoi impossible : {str(exc)[:120]}")
    finally:
        m.close()
    return {"ok": True, "id": rec["id"]}


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def _rates(sends: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(sends)
    o = sum(1 for s in sends if s.get("opened_at"))
    c = sum(1 for s in sends if s.get("clicked_at"))
    r = sum(1 for s in sends if s.get("replied_at"))
    pct = lambda x: round(x / n * 100) if n else 0          # noqa: E731
    return {"sent": n, "opened": o, "clicked": c, "replied": r, "open_rate": pct(o), "click_rate": pct(c), "reply_rate": pct(r)}


def _sends(f: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(_db.crm_email_sends.find({**f, "status": "sent"}, {"_id": 0, "html": 0}))


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
class TemplateIn(BaseModel):
    name: Optional[str] = Field(None, max_length=120)
    category: Optional[str] = Field(None, max_length=60)
    subject: Optional[str] = Field(None, max_length=200)
    body: Optional[str] = Field(None, max_length=20000)


def _tpl_view(t: Dict[str, Any], stats: Dict[str, Any], users) -> Dict[str, Any]:
    u = users.get(t.get("created_by") or "")
    return {"id": t["id"], "name": t.get("name"), "category": t.get("category") or "", "subject": t.get("subject") or "",
            "body": t.get("body") or "", "unfinished": _unfinished(t.get("subject"), t.get("body")),
            "created_by": t.get("created_by"), "created_by_name": "FidClic" if t.get("created_by") == "system" else (C._name(u) if u else t.get("created_by")),
            "updated_at": C._iso(t.get("updated_at")), "steps": _db.crm_sequences.count_documents({"steps.template_id": t["id"]}),
            **stats}


@router.get("/api/crm/email/templates")
def list_templates(q: str = "", token_data: TokenData = Depends(require_admin("crm"))):
    f: Dict[str, Any] = {}
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        f["$or"] = [{"name": rx}, {"subject": rx}, {"category": rx}]
    rows = list(_db.crm_email_templates.find(f, {"_id": 0}).sort("name", 1))
    users = C._users()
    out = []
    for t in rows:
        st = _rates(_sends({"template_id": t["id"]}))
        out.append(_tpl_view(t, {"uses": st["sent"], "open_rate": st["open_rate"], "click_rate": st["click_rate"],
                                 "reply_rate": st["reply_rate"]}, users))
    return {"rows": out, "variables": [{"key": k, "label": l} for k, l in VARIABLES],
            "categories": sorted({t.get("category") for t in rows if t.get("category")})}


@router.post("/api/crm/email/templates")
def add_template(body: TemplateIn, token_data: TokenData = Depends(require_admin("crm"))):
    if not (body.name or "").strip() or not (body.subject or "").strip() or not (body.body or "").strip():
        raise HTTPException(status_code=400, detail="Nom, objet et texte sont obligatoires.")
    _check_text(body.subject, body.body)
    t = {"id": uuid.uuid4().hex, "name": body.name.strip(), "category": (body.category or "").strip(),
         "subject": body.subject.strip(), "body": body.body.strip(), "created_by": token_data.email,
         "created_at": C._now(), "updated_at": C._now()}
    _db.crm_email_templates.insert_one(t)
    return {"id": t["id"]}


def _own(doc: Dict[str, Any], token: TokenData) -> None:
    if token.role != "super_admin" and doc.get("created_by") != token.email:
        raise HTTPException(status_code=403, detail="Seul son auteur (ou le super admin) peut le modifier.")


@router.put("/api/crm/email/templates/{tid}")
def edit_template(tid: str, body: TemplateIn, token_data: TokenData = Depends(require_admin("crm"))):
    t = _db.crm_email_templates.find_one({"id": tid}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
    _own(t, token_data)
    d = {k: v.strip() for k, v in body.dict(exclude_unset=True).items() if isinstance(v, str)}
    if any(k in d and not d[k] for k in ("name", "subject", "body")):
        raise HTTPException(status_code=400, detail="Nom, objet et texte sont obligatoires.")
    _check_text(d.get("subject", t["subject"]), d.get("body", t["body"]))
    _db.crm_email_templates.update_one({"id": tid}, {"$set": {**d, "updated_at": C._now()}})
    return {"ok": True}


@router.delete("/api/crm/email/templates/{tid}")
def delete_template(tid: str, token_data: TokenData = Depends(require_admin("crm"))):
    t = _db.crm_email_templates.find_one({"id": tid}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
    _own(t, token_data)
    _db.crm_email_templates.delete_one({"id": tid})       # sequences keep their own copy of the text
    return {"ok": True}


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------
class StepIn(BaseModel):
    id: Optional[str] = None
    day: int = Field(1, ge=1, le=365)
    time: str = "09:00"
    subject: str = Field("", max_length=200)
    body: str = Field("", max_length=20000)
    template_id: Optional[str] = None


class SequenceIn(BaseModel):
    name: Optional[str] = Field(None, max_length=120)
    sector: Optional[str] = Field(None, max_length=80)
    target: Optional[str] = Field(None, max_length=160)
    steps: Optional[List[StepIn]] = None
    stop_on_reply: Optional[bool] = None
    preset: Optional[str] = None
    template_id: Optional[str] = None


def _clean_steps(steps: List[StepIn]) -> List[Dict[str, Any]]:
    out = []
    for s in sorted(steps, key=lambda x: x.day):
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s.time or ""):
            raise HTTPException(status_code=400, detail=f"Heure invalide : {s.time}")
        _check_text(s.subject, s.body)
        out.append({"id": s.id or uuid.uuid4().hex[:10], "day": s.day, "time": s.time, "subject": s.subject.strip(),
                    "body": s.body.strip(), "template_id": s.template_id})
    if len(out) > 12:
        raise HTTPException(status_code=400, detail="12 étapes au maximum.")
    return out


def _seq_view(s: Dict[str, Any], users, with_steps: bool = False) -> Dict[str, Any]:
    u = users.get(s.get("created_by") or "")
    st = _rates(_sends({"sequence_id": s["id"]}))
    v = {"id": s["id"], "name": s.get("name"), "sector": s.get("sector") or "", "target": s.get("target") or "",
         "status": s.get("status"), "status_label": dict(SEQ_STATUSES).get(s.get("status")), "steps_count": len(s.get("steps") or []),
         "prospects": _db.crm_enrollments.count_documents({"sequence_id": s["id"]}),
         "created_by": s.get("created_by"), "created_by_name": C._name(u) if u else s.get("created_by"),
         "created_at": C._iso(s.get("created_at")), "last_activity_at": C._iso(s.get("last_activity_at") or s.get("updated_at")),
         "stop_on_reply": s.get("stop_on_reply", True), **st}
    if with_steps:
        v["steps"] = [{**x, "unfinished": _unfinished(x.get("subject"), x.get("body")),
                       **_rates(_sends({"sequence_id": s["id"], "step_id": x["id"]}))} for x in (s.get("steps") or [])]
    return v


def _seq_filter(q: str, sector: str, status: str, created_by: str) -> Dict[str, Any]:
    f: Dict[str, Any] = {}
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        f["$or"] = [{"name": rx}, {"target": rx}, {"sector": rx}]
    if sector:
        f["sector"] = sector
    if status:
        f["status"] = status
    if created_by:
        f["created_by"] = created_by
    return f


def _tick() -> None:
    """Opening the page sends what is due (a few at most) and reads replies."""
    try:
        if _cfg():
            check_replies()
            run_due(max_send=15, budget_s=6)
    except Exception as exc:
        print(f"crm mail tick: {exc}")


@router.get("/api/crm/sequences")
def list_sequences(tab: str = "", q: str = "", sector: str = "", status: str = "", created_by: str = "", page: int = 1,
                   per_page: int = 10, quiet: bool = False, token_data: TokenData = Depends(require_admin("crm"))):
    if not quiet:          # the CRM overview only reads the list: no sending from there
        _tick()
    page, per_page = max(1, int(page)), max(1, min(100, int(per_page)))
    base = _seq_filter(q, sector, status, created_by)
    counts = {"all": _db.crm_sequences.count_documents(base),
              **{k: _db.crm_sequences.count_documents({**base, "status": k}) for k, _ in SEQ_STATUSES}}
    f = {**base, **({"status": tab} if tab in dict(SEQ_STATUSES) else {})}
    total = _db.crm_sequences.count_documents(f)
    rows = list(_db.crm_sequences.find(f, {"_id": 0}).sort([("updated_at", -1), ("id", 1)]).skip((page - 1) * per_page).limit(per_page))
    users = C._users()
    return {"rows": [_seq_view(s, users) for s in rows], "total": total, "counts": counts, "page": page,
            "pages": max(1, -(-total // per_page)), "per_page": per_page,
            "sectors": sorted({s for s in _db.crm_sequences.distinct("sector") if s})}


@router.get("/api/crm/sequences/summary")
def sequences_summary(token_data: TokenData = Depends(require_admin("crm"))):
    now = C._now()
    month, prev = now - timedelta(days=30), now - timedelta(days=60)
    allsends = _sends({"sent_at": {"$gte": prev}})

    def win(a, b):
        return [s for s in allsends if a <= C._aware(s["sent_at"]) < b]
    cur, old = _rates(win(month, now)), _rates(win(prev, month))
    series = {k: C._series(lambda a, b, k=k: _rates(win(a, b))[k], month, now)
              for k in ("sent", "open_rate", "click_rate", "reply_rate")}
    active = _db.crm_sequences.count_documents({"status": "active"})
    act_prev = _db.crm_sequences.count_documents({"status": "active", "created_at": {"$lt": month}})
    cards = [
        {"key": "active", "value": active, "delta": C._delta(active, act_prev), "series": None},
        {"key": "sent", "value": cur["sent"], "delta": C._delta(cur["sent"], old["sent"]), "series": series["sent"]},
        {"key": "open_rate", "value": cur["open_rate"], "delta": (cur["open_rate"] - old["open_rate"]) if old["sent"] else None,
         "series": series["open_rate"]},
        {"key": "click_rate", "value": cur["click_rate"], "delta": (cur["click_rate"] - old["click_rate"]) if old["sent"] else None,
         "series": series["click_rate"]},
        {"key": "reply_rate", "value": cur["reply_rate"], "delta": (cur["reply_rate"] - old["reply_rate"]) if old["sent"] else None,
         "series": series["reply_rate"]},
    ]
    today = _local(now).date()
    perf = []
    for d in range(6, -1, -1):
        day = datetime.combine(today - timedelta(days=d), time(0, 0))
        a, b = _utc(day), _utc(day + timedelta(days=1))
        r = _rates(win(a, b))
        perf.append({"day": day.date().isoformat(), "open_rate": r["open_rate"], "click_rate": r["click_rate"],
                     "reply_rate": r["reply_rate"], "sent": r["sent"]})
    month_sends = win(month, now)
    sectors = {p["id"]: p.get("sector") or "Autres" for p in _db.crm_prospects.find(
        {"id": {"$in": list({s["prospect_id"] for s in month_sends})}}, {"_id": 0, "id": 1, "sector": 1})}
    by = {}
    for s in month_sends:
        k = sectors.get(s["prospect_id"], "Autres")
        by[k] = by.get(k, 0) + 1
    ranked = sorted(by.items(), key=lambda kv: -kv[1])
    top = ranked[:7] + ([("Autres", sum(v for _, v in ranked[7:]))] if len(ranked) > 7 else [])
    tot = sum(v for _, v in top) or 1
    by_sector = [{"label": k, "count": v, "pct": round(v / tot * 100)} for k, v in top]
    tpls = []
    for t in _db.crm_email_templates.find({}, {"_id": 0}):
        r = _rates(_sends({"template_id": t["id"]}))
        tpls.append({"id": t["id"], "name": t.get("name"), "uses": r["sent"], "open_rate": r["open_rate"],
                     "unfinished": _unfinished(t.get("subject"), t.get("body"))})
    tpls.sort(key=lambda x: (-x["uses"], x["name"] or ""))
    return {"cards": cards, "performance": perf, "by_sector": by_sector, "templates": tpls[:4],
            "presets": [{"key": p["key"], "name": p["name"], "description": p["description"], "steps": len(p["steps"])}
                        for p in SEQUENCE_PRESETS],
            "overall": cur}


@router.get("/api/crm/sequences/{sid}")
def get_sequence(sid: str, token_data: TokenData = Depends(require_admin("crm"))):
    s = _db.crm_sequences.find_one({"id": sid}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Séquence introuvable")
    users = C._users()
    enr = list(_db.crm_enrollments.find({"sequence_id": sid}, {"_id": 0}).sort("enrolled_at", -1).limit(300))
    names = {p["id"]: p for p in _db.crm_prospects.find({"id": {"$in": [e["prospect_id"] for e in enr]}},
                                                        {"_id": 0, "id": 1, "name": 1, "city": 1, "email": 1})}
    sends = {}
    for x in _sends({"sequence_id": sid}):
        sends.setdefault(x["enrollment_id"], []).append(x)
    steps = s.get("steps") or []
    return {**_seq_view(s, users, with_steps=True),
            "enrollments": [{"id": e["id"], "prospect_id": e["prospect_id"], "prospect": (names.get(e["prospect_id"]) or {}).get("name"),
                             "city": (names.get(e["prospect_id"]) or {}).get("city"), "email": e.get("email"),
                             "status": e["status"], "status_label": ENR_STATUSES.get(e["status"]), "reason": e.get("stopped_reason"),
                             "step": min(e.get("step") or 0, len(steps)), "next_at": C._iso(e.get("next_at")),
                             **{k: v for k, v in _rates(sends.get(e["id"], [])).items() if k in ("sent", "opened", "clicked", "replied")}}
                            for e in enr]}


def _from_preset(key: str) -> List[Dict[str, Any]]:
    p = next((x for x in SEQUENCE_PRESETS if x["key"] == key), None)
    if not p:
        raise HTTPException(status_code=400, detail="Modèle de séquence inconnu.")
    out = []
    for day, hhmm, tid in p["steps"]:
        t = _db.crm_email_templates.find_one({"id": tid}, {"_id": 0}) or next(x for x in DEFAULT_TEMPLATES if x["id"] == tid)
        out.append({"id": uuid.uuid4().hex[:10], "day": day, "time": hhmm, "subject": t["subject"], "body": t["body"],
                    "template_id": tid})
    return out


@router.post("/api/crm/sequences")
def add_sequence(body: SequenceIn, token_data: TokenData = Depends(require_admin("crm"))):
    if body.preset:
        steps = _from_preset(body.preset)
        name = body.name or next(x["name"] for x in SEQUENCE_PRESETS if x["key"] == body.preset)
    else:
        steps = _clean_steps(body.steps or [])
        if not steps and body.template_id:
            t = _db.crm_email_templates.find_one({"id": body.template_id}, {"_id": 0})
            if t:
                steps = [{"id": uuid.uuid4().hex[:10], "day": 1, "time": "09:00", "subject": t["subject"], "body": t["body"],
                          "template_id": t["id"]}]
        name = body.name
    if not (name or "").strip():
        raise HTTPException(status_code=400, detail="Donnez un nom à la séquence.")
    s = {"id": uuid.uuid4().hex, "name": name.strip(), "sector": (body.sector or "").strip(), "target": (body.target or "").strip(),
         "steps": steps, "status": "brouillon", "stop_on_reply": True if body.stop_on_reply is None else body.stop_on_reply,
         "created_by": token_data.email, "created_at": C._now(), "updated_at": C._now()}
    _db.crm_sequences.insert_one(s)
    return _seq_view(s, C._users(), with_steps=True)


@router.put("/api/crm/sequences/{sid}")
def edit_sequence(sid: str, body: SequenceIn, token_data: TokenData = Depends(require_admin("crm"))):
    s = _db.crm_sequences.find_one({"id": sid}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Séquence introuvable")
    _own(s, token_data)
    sets: Dict[str, Any] = {"updated_at": C._now()}
    for k in ("name", "sector", "target"):
        v = getattr(body, k)
        if v is not None:
            sets[k] = v.strip()
    if "name" in sets and not sets["name"]:
        raise HTTPException(status_code=400, detail="Donnez un nom à la séquence.")
    if body.stop_on_reply is not None:
        sets["stop_on_reply"] = body.stop_on_reply
    if body.steps is not None:
        steps = _clean_steps(body.steps)
        if s.get("status") == "active":
            if not steps:
                raise HTTPException(status_code=400, detail="Une séquence active garde au moins une étape.")
            if any(_unfinished(x["subject"], x["body"]) for x in steps):
                raise HTTPException(status_code=400, detail="Complétez les passages [À COMPLÉTER] avant d'enregistrer.")
        sets["steps"] = steps
    _db.crm_sequences.update_one({"id": sid}, {"$set": sets})
    return _seq_view(_db.crm_sequences.find_one({"id": sid}, {"_id": 0}), C._users(), with_steps=True)


class StatusIn(BaseModel):
    status: str


@router.post("/api/crm/sequences/{sid}/status")
def sequence_status(sid: str, body: StatusIn, token_data: TokenData = Depends(require_admin("crm"))):
    s = _db.crm_sequences.find_one({"id": sid}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Séquence introuvable")
    _own(s, token_data)
    if body.status not in ("active", "pause", "terminee"):
        raise HTTPException(status_code=400, detail="Statut inconnu.")
    if body.status == "active":
        steps = s.get("steps") or []
        if not steps:
            raise HTTPException(status_code=400, detail="Ajoutez au moins une étape avant d'activer.")
        bad = [f"étape {i + 1}" for i, x in enumerate(steps) if not x.get("subject") or not x.get("body")]
        if bad:
            raise HTTPException(status_code=400, detail="Objet ou texte manquant : " + ", ".join(bad) + ".")
        todo = [f"étape {i + 1}" for i, x in enumerate(steps) if _unfinished(x.get("subject"), x.get("body"))]
        if todo:
            raise HTTPException(status_code=400, detail="Complétez les passages [À COMPLÉTER] : " + ", ".join(todo) + ".")
        if s.get("status") == "terminee":
            raise HTTPException(status_code=400, detail="Une séquence terminée ne se relance pas : dupliquez-la.")
    if body.status == "terminee":
        for e in _db.crm_enrollments.find({"sequence_id": sid, "status": "en_cours"}, {"_id": 0}):
            _stop(e, "arrete", "Séquence terminée")
    _db.crm_sequences.update_one({"id": sid}, {"$set": {"status": body.status, "updated_at": C._now(),
                                                        **({"activated_at": C._now()} if body.status == "active" else {})}})
    return {"status": body.status}


@router.post("/api/crm/sequences/{sid}/duplicate")
def duplicate_sequence(sid: str, token_data: TokenData = Depends(require_admin("crm"))):
    s = _db.crm_sequences.find_one({"id": sid}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Séquence introuvable")
    c = {**s, "id": uuid.uuid4().hex, "name": f"{s.get('name')} (copie)", "status": "brouillon", "created_by": token_data.email,
         "created_at": C._now(), "updated_at": C._now(), "last_activity_at": None,
         "steps": [{**x, "id": uuid.uuid4().hex[:10]} for x in s.get("steps") or []]}
    _db.crm_sequences.insert_one(c)
    return {"id": c["id"]}


@router.delete("/api/crm/sequences/{sid}")
def delete_sequence(sid: str, token_data: TokenData = Depends(require_admin("crm"))):
    s = _db.crm_sequences.find_one({"id": sid}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Séquence introuvable")
    _own(s, token_data)
    if _db.crm_email_sends.find_one({"sequence_id": sid}):
        raise HTTPException(status_code=409, detail="Des emails sont déjà partis : terminez la séquence plutôt que de la supprimer.")
    _db.crm_enrollments.delete_many({"sequence_id": sid})
    _db.crm_sequences.delete_one({"id": sid})
    return {"ok": True}


class EnrollIn(BaseModel):
    prospect_ids: Optional[List[str]] = None
    sector: str = ""
    city: str = ""
    stage: str = ""
    dry_run: bool = False


@router.post("/api/crm/sequences/{sid}/enroll")
def enroll(sid: str, body: EnrollIn, token_data: TokenData = Depends(require_admin("crm"))):
    s = _db.crm_sequences.find_one({"id": sid}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Séquence introuvable")
    if s.get("status") == "terminee":
        raise HTTPException(status_code=400, detail="Cette séquence est terminée.")
    if body.prospect_ids:
        f: Dict[str, Any] = {"id": {"$in": body.prospect_ids[:5000]}}
    elif body.sector or body.city or body.stage:
        f = C._filter("", body.sector, body.city, body.stage)
    else:
        raise HTTPException(status_code=400, detail="Choisissez des prospects ou un filtre (secteur, ville, étape).")
    here = set(_db.crm_enrollments.distinct("prospect_id", {"sequence_id": sid}))
    busy = set(_db.crm_enrollments.distinct("prospect_id", {"status": "en_cours", "sequence_id": {"$ne": sid}}))
    res = {"added": 0, "no_email": 0, "opted_out": 0, "clients": 0, "lost": 0, "already": 0, "other_sequence": 0}
    steps = s.get("steps") or []
    first = _at(_local(C._now()) + timedelta(days=(steps[0]["day"] - 1) if steps else 0), steps[0]["time"] if steps else "09:00")
    first = max(first, C._now())
    for p in _db.crm_prospects.find(f, {"_id": 0}).limit(5000):
        if p["id"] in here:
            res["already"] += 1
        elif not p.get("email") or "@" not in p["email"]:
            res["no_email"] += 1
        elif p.get("email_opt_out"):
            res["opted_out"] += 1
        elif p.get("stage") in ("essai", "signe"):
            res["clients"] += 1
        elif p.get("stage") == "perdu":
            res["lost"] += 1
        elif p["id"] in busy:
            res["other_sequence"] += 1
        else:
            res["added"] += 1
            if not body.dry_run:
                _db.crm_enrollments.insert_one({"id": uuid.uuid4().hex, "sequence_id": sid, "prospect_id": p["id"],
                                                "email": p["email"], "step": 0, "status": "en_cours", "next_at": first,
                                                "enrolled_at": C._now(), "by": token_data.email, "errors": 0})
    if res["added"] and not body.dry_run:
        _db.crm_sequences.update_one({"id": sid}, {"$set": {"updated_at": C._now()}})
    return res


@router.post("/api/crm/sequences/{sid}/enrollments/{eid}/stop")
def stop_enrollment(sid: str, eid: str, token_data: TokenData = Depends(require_admin("crm"))):
    e = _db.crm_enrollments.find_one({"id": eid, "sequence_id": sid}, {"_id": 0})
    if not e:
        raise HTTPException(status_code=404, detail="Introuvable")
    if e["status"] == "en_cours":
        _stop(e, "arrete", "Arrêté à la main")
    return {"ok": True}


@router.post("/api/crm/sequences/run")
def run_now(token_data: TokenData = Depends(require_admin("crm"))):
    _need_cfg()
    rep = check_replies(force=True)
    res = run_due(max_send=40, budget_s=20)
    return {**res, "replies": rep.get("replies", 0)}
