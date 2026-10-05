"""
The two e-mails of a new business (user, 2026-10-05), sent the moment it goes
live — « Commencer l'essai » on the plan step, when it appears in the super
admin (features/onboarding.start_trial):

  1. to FidClic (ADMIN_SIGNUP_EMAIL, default fidclic37@gmail.com):
     « Nouveau commerce inscrit » with everything needed to call them back;
  2. to the owner: « Bienvenue dans la famille FidClic », in French — the
     trial, the first four steps with direct links, their sign-up link, and
     how to reach us (reply to the e-mail = contact@fidclic.com).

Both go through Brevo (services/mailer). Never raises: a mail that fails is
logged, the sign-up goes on.
"""
from __future__ import annotations

import html
import os
from datetime import datetime
from typing import Any, Dict, Optional

SECTORS_FR = {"cafe": "Café / salon de thé", "restaurant": "Restaurant", "pizzeria": "Pizzeria",
              "bakery": "Boulangerie / pâtisserie", "bar": "Bar / cave à vin", "spa": "Spa / institut de beauté",
              "salon": "Salon de coiffure", "gym": "Salle de sport", "retail": "Boutique / commerce", "other": "Autre"}
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
          "octobre", "novembre", "décembre"]
BLUE, INK, MUTED = "#2F6BFF", "#0B1C3F", "#4B5C7A"


def _app() -> str:
    return (os.getenv("PUBLIC_APP_URL") or "https://app.fidclic.com").rstrip("/")


def _contact() -> str:
    return os.getenv("SUPPORT_CONTACT_EMAIL", "contact@fidclic.com")


def _admin_to() -> str:
    return os.getenv("ADMIN_SIGNUP_EMAIL", "fidclic37@gmail.com")


def _date_fr(d: Any) -> str:
    if isinstance(d, str):
        try:
            d = datetime.fromisoformat(d.replace("Z", "+00:00"))
        except ValueError:
            return d
    if not isinstance(d, datetime):
        return ""
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def _e(v: Any) -> str:
    return html.escape(str(v or ""))


def _frame(body: str) -> str:
    return f"""<div style="background:#F4F7FC;padding:28px 12px;font-family:Arial,Helvetica,sans-serif;color:{INK}">
  <div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #E6EEFB">
    <div style="padding:22px 28px;border-bottom:1px solid #EEF2F9">
      <img src="{_app()}/brand/fidclic-logo.png" alt="FidClic" height="36" style="display:block;height:36px">
    </div>
    <div style="padding:26px 28px;font-size:15px;line-height:1.6">{body}</div>
  </div>
  <p style="max-width:560px;margin:14px auto 0;font-size:11.5px;color:#94A3B8;text-align:center">
    FidClic · La fidélité en un clic · <a href="https://www.fidclic.com/cgu" style="color:#94A3B8">CGU</a> ·
    <a href="https://www.fidclic.com/confidentialite" style="color:#94A3B8">Confidentialité</a></p>
</div>"""


def _button(href: str, label: str) -> str:
    return (f'<a href="{href}" style="display:inline-block;background:{BLUE};color:#ffffff;text-decoration:none;'
            f'font-weight:bold;padding:12px 22px;border-radius:999px">{label}</a>')


def welcome_html(tenant: Dict[str, Any], user: Dict[str, Any]) -> str:
    app, contact = _app(), _contact()
    first = _e(user.get("first_name")) or "Bonjour"
    shop = _e(tenant.get("name") or "votre commerce")
    join = f"{app}/join/{tenant.get('slug')}" if tenant.get("slug") else ""
    steps = [
        ("Personnalisez votre carte de fidélité", "logo, couleurs, récompense : c'est la carte que vos clients ajouteront à Apple Wallet et Google Wallet.", f"{app}/dashboard/card"),
        ("Affichez votre QR code en caisse", "vos clients le scannent et reçoivent leur carte en quelques secondes, sans application à télécharger.", f"{app}/dashboard/parametres/lien-inscription"),
        ("Enregistrez chaque passage", "bouton « Scanner » en haut de votre espace : les tampons et points s'ajoutent tout seuls.", f"{app}/dashboard/scan"),
        ("Envoyez votre première offre", "une notification sur le téléphone de vos clients, en deux minutes.", f"{app}/dashboard/campaigns"),
    ]
    steps_html = "".join(
        f'<tr><td style="vertical-align:top;padding:0 12px 14px 0"><span style="display:inline-block;width:26px;height:26px;'
        f'border-radius:50%;background:#EEF4FF;color:{BLUE};font-weight:bold;text-align:center;line-height:26px">{i}</span></td>'
        f'<td style="padding-bottom:14px"><a href="{href}" style="color:{INK};font-weight:bold;text-decoration:none">{t}</a>'
        f'<br><span style="color:{MUTED};font-size:14px">{d}</span></td></tr>'
        for i, (t, d, href) in enumerate(steps, 1))
    trial_end = _date_fr(tenant.get("trial_ends_at"))
    body = f"""
<h1 style="font-size:22px;margin:0 0 12px">Bienvenue dans la famille FidClic, {first} !</h1>
<p style="margin:0 0 14px">Toute l'équipe est ravie de vous compter parmi nous. <b>{shop}</b> est prêt à fidéliser
ses clients : des cartes de fidélité directement dans leur téléphone, des offres qui les font revenir, et des
chiffres clairs pour piloter votre commerce.</p>
<div style="background:#E9F8EF;border-radius:12px;padding:14px 16px;margin:0 0 20px;color:#137A3E">
  <b>Votre essai gratuit est activé : 30 jours de Pro AI</b>, toutes les fonctionnalités, sans carte bancaire{f", jusqu'au <b>{trial_end}</b>" if trial_end else ""}.
  Vous choisirez ensuite la formule qui vous convient.
</div>
<p style="margin:0 0 10px;font-weight:bold">Vos premiers pas</p>
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 8px">{steps_html}</table>
<p style="margin:0 0 22px">{_button(app + "/dashboard", "Accéder à mon espace")}</p>
<p style="margin:0 0 6px;font-weight:bold">À garder sous la main</p>
<ul style="margin:0 0 20px;padding-left:18px;color:{MUTED}">
  <li>Votre espace : <a href="{app}" style="color:{BLUE}">{app.replace("https://", "")}</a> — identifiant : <b>{_e(user.get("email"))}</b></li>
  {f'<li>Le lien d’inscription de vos clients : <a href="{join}" style="color:{BLUE}">{join.replace("https://", "")}</a></li>' if join else ""}
  <li>Le centre d’aide, le chat et le suivi de vos demandes : menu <b>« Besoin d’aide ? »</b> dans votre espace</li>
</ul>
<div style="border-top:1px solid #EEF2F9;padding-top:18px">
  <p style="margin:0 0 6px;font-weight:bold">Nous sommes là pour vous</p>
  <p style="margin:0;color:{MUTED}">Une question, un doute, une idée ? Écrivez-nous à tout moment à
  <a href="mailto:{contact}" style="color:{BLUE}">{contact}</a>, ou répondez simplement à cet e-mail : un vrai
  membre de l'équipe vous répond. Nous pouvons aussi vous aider à installer votre carte et votre QR code.</p>
</div>
<p style="margin:22px 0 0">Merci de votre confiance, et à très vite,<br><b>L'équipe FidClic</b></p>"""
    return _frame(body)


def admin_html(tenant: Dict[str, Any], user: Dict[str, Any], verified: Optional[str]) -> str:
    app = _app()
    owner = " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x) or "—"
    rows = [
        ("Commerce", tenant.get("name")), ("Raison sociale", tenant.get("legal_name")),
        ("Secteur", SECTORS_FR.get(tenant.get("sector") or "", tenant.get("sector"))),
        ("Adresse", tenant.get("address")), ("Pays", tenant.get("country")),
        ("Propriétaire", owner), ("E-mail", user.get("email")), ("Téléphone", tenant.get("phone") or user.get("phone")),
        ("Vérifié par", verified or {"google": "Google", "apple": "Apple"}.get(user.get("auth_provider") or "") or "—"),
        ("Inscription", "Google" if user.get("auth_provider") == "google" else "Apple" if user.get("auth_provider") == "apple" else "E-mail + mot de passe"),
        ("Essai", f"Pro AI, jusqu'au {_date_fr(tenant.get('trial_ends_at'))}"),
    ]
    table = "".join(f'<tr><td style="padding:6px 14px 6px 0;color:{MUTED};white-space:nowrap">{k}</td>'
                    f'<td style="padding:6px 0"><b>{_e(v) or "—"}</b></td></tr>' for k, v in rows)
    body = f"""
<h1 style="font-size:20px;margin:0 0 6px">Nouveau commerce inscrit 🎉</h1>
<p style="margin:0 0 16px;color:{MUTED}">{_e(tenant.get("name"))} vient de démarrer son essai gratuit.</p>
<table role="presentation" cellpadding="0" cellspacing="0" style="font-size:14px;margin:0 0 20px">{table}</table>
<p style="margin:0">{_button(f"{app}/admin/commerces/{tenant.get('id')}", "Ouvrir la fiche commerce")}</p>"""
    return _frame(body)


def send_signup_emails(tenant: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
    from services import mailer
    out: Dict[str, Any] = {}
    verified = ("e-mail" if user.get("email_verified_at") else None) or ("SMS" if user.get("phone_verified_at") else None)
    try:
        out["admin"] = mailer.send(to=_admin_to(),
                                   subject=f"Nouveau commerce inscrit : {tenant.get('name') or '—'}",
                                   html=admin_html(tenant, user, verified))
    except Exception as exc:                       # noqa: BLE001
        out["admin"] = {"sent": False, "reason": str(exc)[:120]}
    try:
        out["welcome"] = mailer.send(
            to=user["email"],
            to_name=" ".join(x for x in [user.get("first_name"), user.get("last_name")] if x) or None,
            subject="Bienvenue dans la famille FidClic 🎉",
            html=welcome_html(tenant, user),
            reply_to=_contact())
    except Exception as exc:                       # noqa: BLE001
        out["welcome"] = {"sent": False, "reason": str(exc)[:120]}
    return out
