"""
Super admin › Paramètres › Services (user, 2026-11-11): every outside service
FidClic runs on — set or missing (the NAMES of what is missing, never a
value), what it powers, what stops without it — and « Tester »: a real, small
check of the service.

A test never reaches a shop or a customer: the test e-mail goes to the person
who pressed the button, Twilio's account is read (no SMS), Anthropic's model
list is read (no paid call), Stripe's balance, Vercel Blob's list. Each test
is journaled; ten a minute per person at most.

    GET  /api/admin/settings/services              (Paramètres « Voir »)
    POST /api/admin/settings/services/{key}/test   (Paramètres « Modifier »)
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request

from auth import TokenData
from features.platform_access import require_admin

router = APIRouter(tags=["admin"])
_db = None

TESTS_PER_MIN = 10
_tries: Dict[str, deque] = defaultdict(deque)

GROUPS = [
    ("socle", "Socle"), ("emails", "Emails"), ("messages", "SMS & messages"), ("paiements", "Paiements"),
    ("wallet", "Wallet & notifications"), ("stockage", "Stockage"), ("ia", "Intelligence artificielle"),
    ("connexion", "Connexion"), ("autres", "Autres"),
]


def init(db):
    global _db
    _db = db


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _missing(names: List[str]) -> List[str]:
    return [n for n in names if not _env(n)]


def _safe(fn: Callable[[], bool]) -> bool:
    try:
        return bool(fn())
    except Exception:                                    # noqa: BLE001 — a broken helper reads as « missing »
        return False


def _google_wallet() -> bool:
    from features import wallet_passes as WP
    return WP.google_configured()


def _samsung() -> bool:
    from features import samsung_wallet as SW
    return SW.configured()


def _apple_wallet() -> bool:
    from services import apns_passes as AP
    return AP.is_configured()


def _asc() -> bool:
    from services import asc_api as ASC
    return ASC.configured()


# key, group, label, env names (all needed), powers, without, required, test
# `any_of`: one of these is enough; `check`: the module's own « is it set ».
SERVICES: List[Dict[str, Any]] = [
    {"key": "mongo", "group": "socle", "label": "Base de données (MongoDB Atlas)", "envs": ["MONGODB_URI"], "required": True,
     "check": lambda: _db is not None,
     "powers": "Tout : commerces, clients, visites, cartes.", "without": "L'application ne démarre pas.", "test": True},
    {"key": "jwt", "group": "socle", "label": "Signature des connexions", "envs": ["JWT_SECRET"], "required": True,
     "powers": "Les sessions de tous les comptes.", "without": "Une clé de secours publique serait utilisée : n'importe qui pourrait se faire passer pour un compte."},
    {"key": "app_url", "group": "socle", "label": "Adresse de l'application", "envs": ["PUBLIC_APP_URL"],
     "powers": "Les liens dans les emails et les cartes.", "without": "Les liens utilisent l'adresse par défaut app.fidclic.com."},
    {"key": "cron", "group": "socle", "label": "Tâches planifiées (cron)", "envs": ["CRON_SECRET"],
     "powers": "Automatisations, anniversaires, rapports, sauvegardes de nuit.", "without": "N'importe qui pourrait déclencher les tâches planifiées."},

    {"key": "brevo", "group": "emails", "label": "Emails FidClic (Brevo)", "envs": ["BREVO_API_KEY"],
     "powers": "Emails aux commerçants : support, notifications, codes, relances CRM.", "without": "Aucun email ne part vers les commerçants.", "test": True},
    {"key": "support_smtp", "group": "emails", "label": "Boîte du support (SMTP)", "envs": ["SUPPORT_SMTP_USER", "SUPPORT_SMTP_PASS"],
     "powers": "Recevoir les nouvelles demandes de support par email.", "without": "Les demandes restent dans le Centre de support, avec Resend ou Formsubmit en secours."},
    {"key": "resend", "group": "emails", "label": "Resend (secours)", "envs": ["RESEND_API_KEY"],
     "powers": "Secours si le SMTP du support ne répond pas.", "without": "Formsubmit sert de dernier secours."},
    {"key": "crm_mail", "group": "emails", "label": "Boîte mail du CRM", "envs": ["CRM_SMTP_USER", "CRM_SMTP_PASS"],
     "powers": "Emails de prospection et lecture des réponses.", "without": "Le CRM n'envoie ni ne lit d'emails."},

    {"key": "twilio", "group": "messages", "label": "SMS (Twilio)", "envs": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"],
     "powers": "SMS des campagnes et relances.", "without": "Aucun SMS ne part.", "test": True},
    {"key": "whatsapp", "group": "messages", "label": "WhatsApp", "envs": ["WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID"],
     "powers": "Messages WhatsApp.", "without": "Aucun message WhatsApp ne part."},

    {"key": "stripe", "group": "paiements", "label": "Paiements (Stripe)", "envs": ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"], "test_envs": ["STRIPE_SECRET_KEY"],
     "powers": "Abonnements des commerces, factures, encaissements.", "without": "Aucun abonnement ne peut être payé en ligne.", "test": True},

    {"key": "vapid", "group": "wallet", "label": "Notifications web (VAPID)", "envs": ["VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT"],
     "powers": "Notifications push sur les cartes web.", "without": "Aucune notification web.", "test": True},
    {"key": "apple_wallet", "group": "wallet", "label": "Apple Wallet (certificat partagé)",
     "envs": ["APPLE_PASS_TYPE_ID", "APPLE_PASS_CERT_B64", "APPLE_PASS_KEY_B64"], "check": _apple_wallet,
     "powers": "Cartes Apple Wallet et leurs mises à jour.", "without": "Pas de carte Apple Wallet.", "test": True},
    {"key": "asc_api", "group": "wallet", "label": "App Store Connect (Pass Type ID par commerce)",
     "envs": ["ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_PRIVATE_KEY"], "check": _asc,
     "powers": "Un identifiant Apple propre à chaque commerce, créé et renouvelé tout seul.", "without": "Les cartes restent sur l'identifiant partagé."},
    {"key": "google_wallet", "group": "wallet", "label": "Google Wallet",
     "any_of": [["GOOGLE_WALLET_ISSUER_ID", "GOOGLE_WALLET_CLASS_ID"],
                ["GOOGLE_WALLET_SA_B64", "GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL + GOOGLE_WALLET_PRIVATE_KEY"]],
     "check": _google_wallet, "powers": "Cartes Google Wallet.", "without": "Pas de carte Google Wallet."},
    {"key": "samsung_wallet", "group": "wallet", "label": "Samsung Wallet",
     "envs": ["SAMSUNG_WALLET_PARTNER_ID", "SAMSUNG_WALLET_CARD_ID", "SAMSUNG_WALLET_CERT_ID"], "check": _samsung,
     "powers": "Cartes Samsung Wallet.", "without": "Pas de carte Samsung Wallet."},

    {"key": "blob", "group": "stockage", "label": "Photos (Vercel Blob)", "envs": ["BLOB_READ_WRITE_TOKEN"],
     "powers": "Logos, bannières, photos des campagnes et des cartes.", "without": "Les images sont lues depuis la base, beaucoup plus lentement.", "test": True},
    {"key": "warehouse", "group": "stockage", "label": "Entrepôt privé (Vercel Blob privé)", "envs": ["WAREHOUSE_BLOB_READ_WRITE_TOKEN"],
     "powers": "Copie de nuit de l'historique de chaque commerce, golden set sur données réelles.", "without": "Pas de copie de nuit ; les calculs relisent la base.", "test": True},

    {"key": "anthropic", "group": "ia", "label": "FidClic IA (Anthropic / Claude)", "envs": ["ANTHROPIC_API_KEY"],
     "powers": "Copilote, rédaction, autopilote, analyses IA.", "without": "L'IA passe aux fournisseurs de secours ou aux modèles de texte.", "test": True},
    {"key": "ai_backup", "group": "ia", "label": "IA de secours", "any_of": [["NVIDIA_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"]],
     "powers": "Secours si Claude ne répond pas ; lecture des menus en photo.", "without": "Sans Claude, aucune IA ne répond."},
    {"key": "golden", "group": "ia", "label": "Golden set (GitHub)", "envs": ["GOLDEN_SNAPSHOT_KEY", "GOLDEN_GITHUB_TOKEN"],
     "powers": "Le test de l'IA sur données réelles anonymisées et le bouton « Lancer ».", "without": "Le golden set ne tourne que sur les données de démo, depuis GitHub."},

    {"key": "google_signin", "group": "connexion", "label": "Connexion avec Google", "envs": ["GOOGLE_CLIENT_ID"],
     "powers": "Le bouton « Continuer avec Google ».", "without": "Le bouton est masqué."},
    {"key": "apple_signin", "group": "connexion", "label": "Connexion avec Apple", "envs": ["APPLE_CLIENT_ID", "APPLE_REDIRECT_URI"],
     "powers": "Le bouton « Continuer avec Apple ».", "without": "Le bouton est masqué."},

    {"key": "predicthq", "group": "autres", "label": "Événements locaux (PredictHQ)", "envs": ["PREDICTHQ_TOKEN"],
     "powers": "Matchs, concerts et salons près du commerce dans les prévisions.", "without": "Les prévisions ignorent les événements locaux."},
    {"key": "einvoicing", "group": "autres", "label": "Facturation électronique (B2Brouter)", "envs": ["B2BROUTER_API_KEY"],
     "powers": "Factures électroniques (module masqué pour l'instant).", "without": "Rien tant que le module est masqué."},
]
BY_KEY = {s["key"]: s for s in SERVICES}


def _state(s: Dict[str, Any]) -> Tuple[bool, List[str]]:
    if s.get("any_of"):
        miss = []
        for alts in s["any_of"]:
            if not any(all(_env(n.strip()) for n in a.split("+")) for a in alts):
                miss.append(" ou ".join(alts))
        present = _safe(s["check"]) if s.get("check") else not miss
        return present, ([] if present else miss)
    miss = _missing(s.get("envs") or [])
    present = _safe(s["check"]) if s.get("check") else not miss
    return present, ([] if present else miss)


@router.get("/api/admin/settings/services")
def services(token_data: TokenData = Depends(require_admin("parametres"))):
    groups = []
    total = ready = req_missing = 0
    for gk, gl in GROUPS:
        items = []
        for s in (x for x in SERVICES if x["group"] == gk):
            present, miss = _state(s)
            total += 1
            ready += present
            req_missing += (s.get("required", False) and not present)
            items.append({"key": s["key"], "label": s["label"], "present": present, "missing": miss,
                          "required": bool(s.get("required")), "powers": s["powers"], "without": s["without"],
                          "testable": bool(s.get("test"))})
        groups.append({"key": gk, "label": gl, "items": items})
    return {"groups": groups,
            "summary": {"total": total, "ready": ready, "missing": total - ready, "required_missing": req_missing},
            "deployment": {"env": _env("VERCEL_ENV") or "local", "region": _env("VERCEL_REGION") or None,
                           "commit": (_env("VERCEL_GIT_COMMIT_SHA") or "")[:7] or None}}


# ---------------------------------------------------------------------------
# the tests
# ---------------------------------------------------------------------------
def _http(method: str, url: str, headers: Optional[Dict[str, str]] = None, data: Optional[bytes] = None,
          timeout: int = 8) -> Tuple[int, Any]:
    """The single network seam (tests replace it). Returns (status, json-or-None)."""
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = res.read()
            status = res.status
    except urllib.error.HTTPError as e:
        body, status = e.read(), e.code
    try:
        return status, json.loads(body or b"null")
    except ValueError:
        return status, None


def _basic(user: str, pw: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()


def _t_mongo(me: str) -> Tuple[bool, str]:
    t0 = time.time()
    _db.command("ping")
    return True, f"La base répond ({round((time.time() - t0) * 1000)} ms)."


def _t_brevo(me: str) -> Tuple[bool, str]:
    from services import mailer
    when = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    r = mailer.send(me, "[FidClic] Email de test", "<p>Ceci est un email de test envoyé depuis "
                    f"Super admin › Paramètres › Services ({when}).</p><p>Si vous le lisez, les emails FidClic partent bien.</p>",
                    text=f"Email de test FidClic ({when}).")
    if r.get("sent"):
        return True, f"Email de test envoyé à {me}. Vérifiez votre boîte (et les spams)."
    return False, f"Brevo a refusé l'envoi : {str(r.get('reason') or 'raison inconnue')[:120]}"


def _t_stripe(me: str) -> Tuple[bool, str]:
    st, j = _http("GET", "https://api.stripe.com/v1/balance", {"Authorization": f"Bearer {_env('STRIPE_SECRET_KEY')}"})
    if st == 200:
        return True, "Stripe répond — mode " + ("live (paiements réels)." if (j or {}).get("livemode") else "test.")
    return False, "Stripe a refusé la clé." if st in (401, 403) else f"Stripe répond {st}."


def _t_twilio(me: str) -> Tuple[bool, str]:
    sid = _env("TWILIO_ACCOUNT_SID")
    st, j = _http("GET", f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json",
                  {"Authorization": _basic(sid, _env("TWILIO_AUTH_TOKEN"))})
    if st == 200:
        status = (j or {}).get("status") or "?"
        return status == "active", f"Compte Twilio lu (aucun SMS envoyé) — statut : {status}."
    return False, "Twilio a refusé les identifiants." if st in (401, 403) else f"Twilio répond {st}."


def _t_anthropic(me: str) -> Tuple[bool, str]:
    st, j = _http("GET", "https://api.anthropic.com/v1/models?limit=1",
                  {"x-api-key": _env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"})
    if st == 200:
        return True, "Anthropic répond (liste des modèles lue, rien de facturé)."
    return False, "Anthropic a refusé la clé." if st in (401, 403) else f"Anthropic répond {st}."


def _blob_test(env: str) -> Tuple[bool, str]:
    st, _ = _http("GET", "https://blob.vercel-storage.com?limit=1", {"Authorization": f"Bearer {_env(env)}"})
    if st == 200:
        return True, "Le stockage répond (liste lue)."
    return False, "Vercel Blob a refusé le jeton." if st in (401, 403) else f"Vercel Blob répond {st}."


def _b64url(v: str) -> bytes:
    v = v.strip()
    return base64.urlsafe_b64decode(v + "=" * (-len(v) % 4))


def _t_vapid(me: str) -> Tuple[bool, str]:
    try:
        pub, priv = _b64url(_env("VAPID_PUBLIC_KEY")), _b64url(_env("VAPID_PRIVATE_KEY"))
    except (binascii.Error, ValueError):
        return False, "Les clés VAPID ne sont pas lisibles."
    if len(pub) != 65 or pub[0] != 4:
        return False, "La clé publique VAPID n'a pas le bon format."
    if len(priv) != 32:
        return False, "La clé privée VAPID n'a pas le bon format (le format PEM n'est pas attendu ici)."
    subject = _env("VAPID_SUBJECT")
    if not subject.startswith(("mailto:", "https://")):
        return False, "VAPID_SUBJECT doit commencer par mailto: ou https://."
    return True, "Clés VAPID valides."


def _t_apple(me: str) -> Tuple[bool, str]:
    from cryptography import x509
    raw = base64.b64decode(_env("APPLE_PASS_CERT_B64"))
    try:
        cert = x509.load_pem_x509_certificate(raw)
    except ValueError:
        cert = x509.load_der_x509_certificate(raw)
    end = cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after.replace(tzinfo=timezone.utc)
    days = (end - datetime.now(timezone.utc)).days
    if days < 0:
        return False, f"Le certificat Apple a expiré le {end:%d/%m/%Y}."
    return days > 30, f"Certificat Apple valide jusqu'au {end:%d/%m/%Y} ({days} jours)." + (" À renouveler bientôt." if days <= 30 else "")


TESTS: Dict[str, Callable[[str], Tuple[bool, str]]] = {
    "mongo": _t_mongo, "brevo": _t_brevo, "stripe": _t_stripe, "twilio": _t_twilio, "anthropic": _t_anthropic,
    "blob": lambda me: _blob_test("BLOB_READ_WRITE_TOKEN"), "warehouse": lambda me: _blob_test("WAREHOUSE_BLOB_READ_WRITE_TOKEN"),
    "vapid": _t_vapid, "apple_wallet": _t_apple,
}


def _limit(who: str) -> None:
    now = time.time()
    q = _tries[who]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= TESTS_PER_MIN:
        raise HTTPException(status_code=429, detail="Trop de tests à la suite : réessayez dans une minute.")
    q.append(now)


@router.post("/api/admin/settings/services/{key}/test")
def run_test(key: str, request: Request, token_data: TokenData = Depends(require_admin("parametres"))):
    s = BY_KEY.get(key)
    if not s:
        raise HTTPException(status_code=404, detail="Service inconnu.")
    if key not in TESTS:
        raise HTTPException(status_code=400, detail="Ce service n'a pas de test.")
    _limit(token_data.email)
    present, miss = _state(s)
    if s.get("test_envs"):                  # the test needs less than the whole service (Stripe: the key, not the webhook)
        miss = _missing(s["test_envs"])
        present = not miss
    t0 = time.time()
    if not present:
        ok, msg = False, "Non configuré : " + ", ".join(miss) + "."
    else:
        try:
            ok, msg = TESTS[key](token_data.email)
        except Exception as e:                           # noqa: BLE001 — a test never turns into a 500
            ok, msg = False, f"Le service n'a pas répondu ({type(e).__name__})."
    ms = round((time.time() - t0) * 1000)
    import server as core
    core.log_audit("platform.service_test", actor=token_data.email, actor_type="user", target=key, request=request,
                   meta={"ok": ok, "ms": ms})
    return {"key": key, "ok": ok, "message": msg, "ms": ms, "at": datetime.now(timezone.utc).isoformat()}
