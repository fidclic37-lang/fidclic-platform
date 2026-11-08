"""
FidClic's own pages, for FidClic IA (golden set « Comment faire », #427): the
Copilote did not know where anything lives in the app. The menu comes from
role_perms.PAGES (the same list as the sidebar's rights); this module adds
what each page is for, finds the page a « comment… ? / où… ? » question
means, and answers it plainly when no model can.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from services.ai_checks import fold

PURPOSE = {
    "dashboard": "la vue d'ensemble du jour",
    "scan": "scanner la carte d'un client, enregistrer sa visite, ajouter des tampons ou des points, donner une récompense",
    "analytics": "les statistiques détaillées : visites, chiffre d'affaires, produits, heures",
    "customers": "la liste des clients, leur fiche, l'import de clients existants",
    "campaigns": "créer et envoyer une campagne",
    "card": "le design de la carte de fidélité, ses récompenses et ses paliers",
    "automations": "les messages automatiques : anniversaire, relance des inactifs, bienvenue",
    "segmentation": "créer des groupes de clients",
    "referral": "activer et régler le parrainage",
    "geolocation": "les clients autour de la boutique et les rappels géolocalisés",
    "catalogue": "ajouter et modifier les produits et services",
    "insights": "les idées de campagnes et les recommandations de FidClic IA",
    "ai": "discuter avec FidClic IA",
    "history": "tout ce qui s'est passé dans le compte",
    "settings": "le profil du commerce, les horaires d'ouverture, la langue, les points",
    "milestones": "les objectifs et leurs récompenses",
    "team": "ajouter un employé, ses rôles et ses accès",
    "employee_links": "le lien d'inscription de chaque employé",
    "billing": "l'abonnement et les factures",
}
PARENT = {"milestones": "Paramètres", "team": "Paramètres", "employee_links": "Paramètres", "billing": "Paramètres"}
# words a merchant uses for a page that its name and purpose do not say
WORDS = {
    "scan": "donner client visite",
    "analytics": "stats detaillees",
    "card": "personnaliser couleur logo",
    "automations": "automatique automatiquement relancer",
    "segmentation": "groupe clients segment",
    "referral": "parrain filleul",
    "geolocation": "autour boutique clients plan",
    "insights": "idee campagnes fidclic ia",
    "history": "hier passe compte journal",
    "settings": "horaires ouverture",
    "team": "employe membre",
    "employee_links": "lien inscription employe",
    "billing": "abonnement facture payer offre",
}
_HOW = re.compile(r"^\s*(?:comment\b|ou\b|est-ce que je peux|puis-je|je veux|je voudrais|je cherche)|\b(?:ou (?:je|sont|est|se trouve|trouver)|comment (?:faire|on))\b")
_STOP = set("comment ou je j me mes mon ma le la les l de des du d un une a au aux dans ce ca qui s est sont vois voir change "
            "regle puis faire pour sur avec ses et en mon votre vos on se trouve trouver peux veux voudrais cherche quoi".split())


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w[-1] in "sx" else w


def _words(text: str) -> set:
    return {_stem(w) for w in re.findall(r"[a-z]+", fold(text)) if w not in _STOP}


def pages() -> List[Dict[str, Any]]:
    from features import role_perms as RP
    return [p for p in RP.PAGES if p.get("to") and p["key"] in PURPOSE]


def name(page: Dict[str, Any]) -> str:
    parent = PARENT.get(page["key"])
    return f"{parent} › {page['label']}" if parent else page["label"]


def guide_text() -> str:
    return ("Où trouver quoi dans FidClic (menu de gauche) — pour « comment faire » ou « où est », nomme la page :\n"
            + "\n".join(f"- {name(p)} : {PURPOSE[p['key']]}" for p in pages()))


def page_for(question: str, force: bool = False) -> Optional[Dict[str, Any]]:
    """The page a « comment… ? / où… ? » question means, or None."""
    q = fold(question or "")
    if not q.strip() or (not force and not _HOW.search(q)):
        return None
    asked = _words(q)
    best, score = None, 0
    for p in pages():
        s = len(asked & (_words(p["label"]) | _words(PURPOSE[p["key"]]) | _words(WORDS.get(p["key"], ""))))
        if s > score:
            best, score = p, s
    return best


def how_to(question: str, may_open: bool) -> Optional[Dict[str, Any]]:
    """{reply, action} for a how-to question, without a model."""
    p = page_for(question)
    if not p:
        return None
    reply = f"Ouvrez « {name(p)} » dans le menu : {PURPOSE[p['key']]}."
    if not may_open:
        reply += " Votre accès ne permet pas d'ouvrir cette page ; le propriétaire peut vous l'ouvrir."
    return {"reply": reply, "page": p,
            "action": {"label": f"Ouvrir « {p['label']} »", "kind": "navigate", "to": p["to"]} if may_open else None}
