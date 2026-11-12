"""
« Mes alertes » of FidClic's team (user, 2026-11-11): for each alert type a
member may see, « email » (the bell + an e-mail) or « bell » (the bell only).

    signup    a new business signed up             (Commerces)
    support   a new support request                (Support)
    security  a blocked account, a refused country (super admin)
    ai        FidClic IA caps and budgets          (FIDCLIC AI)
    impaye    a business's payment failed          (Abonnements)
    equipe    my team tasks (given, due, late)     (Suivi d'équipe) — mine only

Defaults keep what the platform did before: FidClic IA e-mails the super
admins, everything else stays in the bell. The FidClic inboxes (signup,
support) keep receiving as before; these e-mails go to people, on top.
Stored on the user: users.alert_prefs {kind: "email" | "bell"}.
"""
from __future__ import annotations

import html as _html
import os
from typing import Any, Dict, Iterable, List, Optional

_db = None

KINDS = [
    ("signup", "Nouveau commerce inscrit", "commerces"),
    ("support", "Nouvelle demande de support", "support"),
    ("security", "Sécurité : compte bloqué, pays refusé, nouveau pays", None),     # super admin only
    ("ai", "FidClic IA : plafonds et budgets", "ai"),
    ("impaye", "Paiement d'un commerce refusé", "abonnements"),
    ("equipe", "Mes tâches (Suivi d'équipe)", "equipe"),
    ("sante", "Santé de la plateforme : tempête Wallet, base saturée", None),       # super admin only
]
LABELS = {k: l for k, l, _ in KINDS}
MODULE = {k: m for k, _, m in KINDS}
DEFAULT_EMAIL = {"ai": {"super_admin"}, "sante": {"super_admin"}}          # kind → roles e-mailed when they never chose
TEAM = ("super_admin", "fidclic_team", "commercial")
CHANNELS = ("email", "bell")


def init(db):
    global _db
    _db = db


def may(user: Dict[str, Any], kind: str) -> bool:
    """Whether this member sees that alert type at all."""
    if kind not in LABELS or user.get("role") not in TEAM or user.get("active") is False:
        return False
    if user.get("role") == "super_admin":
        return True
    mod = MODULE[kind]
    if mod is None:
        return False
    from features import platform_access as PA
    return bool(((PA.perms_for(user["email"]) or {}).get(mod) or {}).get("view"))


def channel(user: Dict[str, Any], kind: str) -> str:
    v = (user.get("alert_prefs") or {}).get(kind)
    if v in CHANNELS:
        return v
    return "email" if user.get("role") in DEFAULT_EMAIL.get(kind, set()) else "bell"


def prefs(user: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"key": k, "label": LABELS[k], "value": channel(user, k)} for k, _, _ in KINDS if may(user, k)]


def recipients(kind: str, only: Optional[Iterable[str]] = None) -> List[str]:
    """The team members to e-mail for this alert: allowed, active, « email »."""
    if _db is None:
        return []
    q: Dict[str, Any] = {"role": {"$in": list(TEAM)}, "active": {"$ne": False}}
    if only is not None:
        q["email"] = {"$in": [e for e in only if e]}
    out = []
    for u in _db.users.find(q, {"_id": 0, "email": 1, "role": 1, "active": 1, "alert_prefs": 1}):
        if u.get("email") and may(u, kind) and channel(u, kind) == "email":
            out.append(u["email"])
    return sorted(set(out))


def _app() -> str:
    return (os.getenv("PUBLIC_APP_URL") or "https://app.fidclic.com").rstrip("/")


def notify(kind: str, title: str, text: str, href: Optional[str] = None, only: Optional[Iterable[str]] = None,
           skip: Iterable[str] = ()) -> int:
    """E-mail the members who asked for this alert type. Never raises; the
    bell rows are written by each source, as before."""
    try:
        to = [e for e in recipients(kind, only) if e not in set(skip)]
        if not to:
            return 0
        from services import mailer
        link = f"{_app()}{href}" if href else _app()
        body = (f"<div style=\"font-family:Inter,Arial,sans-serif;max-width:560px;margin:0 auto;color:#0B1C3F\">"
                f"<p style=\"font-size:12px;color:#2F6BFF;font-weight:700;letter-spacing:.06em;text-transform:uppercase\">FidClic · {_html.escape(LABELS.get(kind, ''))}</p>"
                f"<h2 style=\"font-size:18px;margin:4px 0 12px\">{_html.escape(title)}</h2>"
                f"<p style=\"font-size:14px;line-height:1.55\">{_html.escape(text)}</p>"
                f"<p style=\"margin:18px 0\"><a href=\"{_html.escape(link)}\" style=\"background:#2F6BFF;color:#fff;padding:10px 18px;"
                f"border-radius:10px;text-decoration:none;font-weight:600;font-size:14px\">Ouvrir</a></p>"
                f"<p style=\"font-size:12px;color:#94A3B8\">Vous recevez cet email car vous l'avez choisi dans Paramètres › Mes paramètres › Mes alertes.</p></div>")
        n = 0
        for e in to:
            r = mailer.send(e, f"FidClic — {title}", body, text=f"{title}\n\n{text}\n\n{link}")
            n += bool((r or {}).get("sent"))
        return n
    except Exception as exc:                                 # noqa: BLE001 — an alert never breaks its source
        print(f"team_alerts: {kind} e-mail failed ({exc})")
        return 0
