"""
Support FidClic — the help page's assistant, and the knowledge base behind it.
Status: 🟢 Core.
Mounts at:
    GET  /api/support/kb            → the FAQ the help page renders
    POST /api/owner/support/chat    → ask a question, get an answer + sources
    GET  /api/owner/support/chat    → this merchant's recent conversation

HOW IT ANSWERS
    Retrieval first, model second. Every question is matched against the
    knowledge base below with a small lexical scorer (accent-folded, stopwords
    dropped, title and keyword hits weighted above body hits). The best
    passages are then handed to services.llm to be phrased in French.

WHY IT NEVER ERRORS
    The model is the *phrasing* layer, never the source of truth. If no API key
    is configured, if the provider is down, or if the reply comes back empty,
    the endpoint returns the best retrieved article verbatim. A merchant asking
    "comment ajouter des points" always gets the real answer — worst case
    without the conversational wrapper. The only "I don't know" is when the
    knowledge base genuinely has nothing, and then it offers the human channels.

EDITING THE KNOWLEDGE BASE
    KB below is plain data: id, title, keywords, body, and the section it
    belongs to. Add an entry and both the FAQ list and the assistant learn it.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from auth import require_role, TokenData

router = APIRouter(tags=["support"])
_db = None

SUPPORT_PHONE = "01 84 80 10 20"
SUPPORT_HOURS = "Lun. – Ven. : 9h – 18h"
SUPPORT_EMAIL_DELAY = "sous 24h"
CHAT_DELAY = "moins de 5 min."

# ---------------------------------------------------------------------------
# Knowledge base — the single source the FAQ and the assistant both read.
# ---------------------------------------------------------------------------
KB: List[Dict[str, Any]] = [
    {
        "id": "creer-carte",
        "section": "Carte de fidélité",
        "title": "Comment créer une carte de fidélité ?",
        "keywords": ["créer", "carte", "fidélité", "nouvelle", "démarrer", "configurer", "commencer"],
        "body": (
            "Votre carte est créée automatiquement à l'inscription, à l'étape « Configuration carte ». "
            "Pour la modifier ensuite, ouvrez **Carte de fidélité** dans le menu : vous y réglez le nom, "
            "les couleurs, le logo, l'image de fond et le texte d'accueil, puis vous cliquez sur "
            "« Enregistrer les modifications ». Chaque commerce dispose d'une seule carte, que vous faites "
            "évoluer quand vous voulez — les cartes déjà chez vos clients se mettent à jour toutes seules."
        ),
        "link": {"label": "Ouvrir la carte de fidélité", "to": "/dashboard/card"},
    },
    {
        "id": "ajouter-points",
        "section": "Au quotidien",
        "title": "Comment ajouter des points à un client ?",
        "keywords": ["ajouter", "points", "client", "scanner", "scan", "caisse", "visite", "tampon",
                     "créditer", "solde", "cagnotte", "qr"],
        "body": (
            "En caisse, ouvrez la page **Scanner** et scannez le QR code de la carte du client (ou saisissez "
            "son numéro de carte). Les points sont crédités selon le programme choisi : par euro dépensé, "
            "un montant fixe par visite, un tampon par passage, ou un pourcentage du ticket en cagnotte. "
            "Le solde du client et sa carte dans Wallet se mettent à jour immédiatement après le scan."
        ),
        "link": {"label": "Ouvrir le scanner", "to": "/dashboard/scan"},
    },
    {
        "id": "personnaliser-carte",
        "section": "Carte de fidélité",
        "title": "Comment personnaliser ma carte de fidélité ?",
        "keywords": ["personnaliser", "modifier", "changer", "couleur", "logo", "design", "apparence",
                     "bannière", "image", "texte", "police", "fond", "aperçu", "carte"],
        "body": (
            "Dans **Carte de fidélité**, la colonne de gauche règle l'apparence : couleur principale "
            "(le fond de la carte), couleur secondaire (les accents), logo, image de bannière et texte "
            "d'accueil. L'aperçu au centre montre immédiatement le résultat, en vue client et en vue Wallet. "
            "Le bouton « Options avancées » ouvre les réglages fins : type de code, libellés, informations "
            "au dos de la carte, rappel de proximité, date d'expiration."
        ),
        "link": {"label": "Personnaliser ma carte", "to": "/dashboard/card"},
    },
    {
        "id": "envoyer-campagne",
        "section": "Campagnes",
        "title": "Comment envoyer une campagne ?",
        "keywords": ["campagne", "envoyer", "notification", "push", "message", "offre", "promotion",
                     "promo", "cibler", "segment", "programmer", "clients"],
        "body": (
            "Ouvrez **Campagnes**, rédigez votre message, choisissez qui le reçoit (tous vos clients ou un "
            "segment : palier, fréquence, inactivité, code postal…) et envoyez — immédiatement ou à une date "
            "programmée. Le message arrive en notification sur le téléphone des clients qui l'ont acceptée. "
            "Vous pouvez aussi publier une offre directement sur les cartes : elle remplace la bannière et "
            "déclenche une notification sur l'écran verrouillé."
        ),
        "link": {"label": "Créer une campagne", "to": "/dashboard/campaigns"},
    },
    {
        "id": "consulter-stats",
        "section": "Analyses",
        "title": "Comment consulter les statistiques ?",
        "keywords": ["statistiques", "stats", "analyses", "chiffres", "performance", "rapport",
                     "visites", "suivi", "consulter", "voir", "panier", "fréquentation"],
        "body": (
            "**Analyses** réunit le suivi complet : visites, nouveaux clients contre clients fidèles, heures "
            "de pointe, panier moyen, sources d'acquisition et avis clients, sur la période de votre choix. "
            "La page **Carte de fidélité** affiche en plus les quatre chiffres propres au programme : cartes "
            "actives, scans de QR code, récompenses utilisées et clients fidèles, comparés à la période "
            "précédente."
        ),
        "link": {"label": "Voir les analyses", "to": "/dashboard/analytics"},
    },
    {
        "id": "wallet",
        "section": "Carte de fidélité",
        "title": "Comment mes clients ajoutent-ils la carte à Apple Wallet ?",
        "keywords": ["wallet", "apple", "google", "téléphone", "ajouter", "pass", "portefeuille", "iphone"],
        "body": (
            "Le client rejoint votre programme en scannant votre QR code, puis ouvre sa carte et appuie sur "
            "« Ajouter à Apple Wallet ». La carte vit alors dans son téléphone : elle se met à jour toute "
            "seule après chaque passage en caisse, et peut s'afficher sur l'écran verrouillé quand il passe "
            "près de votre établissement."
        ),
    },
    {
        "id": "recompenses",
        "section": "Programme",
        "title": "Comment fonctionnent les récompenses et les paliers ?",
        "keywords": ["récompense", "palier", "cadeau", "seuil", "fidélité", "niveau", "bronze", "argent", "or", "vip"],
        "body": (
            "Vous définissez une récompense principale (par exemple 100 points = une boisson offerte) et "
            "quatre paliers — Bronze, Argent, Or, VIP — avec le seuil de chacun, en points, en visites ou en "
            "euros cagnottés selon votre programme. Ces seuils décident du palier de chaque client, à chaque "
            "passage ; quand vous les changez, tous vos clients sont reclassés et ceux qui montent sont "
            "prévenus. Un raccourci, réglable au même endroit : VIP aussi dès un nombre de visites avec un "
            "panier moyen élevé (10 visites et 60 € par défaut). Le « Client très actif » des Règles clients "
            "est autre chose : il compte les visites par mois. Quand une carte est complète, la récompense est mise de "
            "côté et la carte repart à zéro à la visite suivante : rien n'est perdu, le client garde sa "
            "récompense à réclamer en caisse."
        ),
        "link": {"label": "Gérer les récompenses", "to": "/dashboard/card"},
    },
    {
        "id": "importer-clients",
        "section": "Clients",
        "title": "Puis-je importer mes clients existants ?",
        "keywords": ["importer", "import", "csv", "excel", "clients", "existants", "base", "fichier", "migrer"],
        "body": (
            "Oui. Depuis **Clients**, importez votre fichier (CSV ou export de votre caisse) avec le nom, le "
            "téléphone, l'email et éventuellement un solde de départ. Vos clients retrouvent leur historique "
            "dès leur première visite, sans rien ressaisir."
        ),
        "link": {"label": "Ouvrir mes clients", "to": "/dashboard/customers"},
    },
    {
        "id": "abonnement",
        "section": "Abonnement",
        "title": "Comment fonctionne mon abonnement ?",
        "keywords": ["abonnement", "plan", "formule", "facture", "facturation", "prix", "tarif", "coûte",
                     "coût", "essai", "gratuit", "paiement", "payer", "résilier", "limite", "engagement"],
        "body": (
            "Vous démarrez avec 30 jours d'essai gratuit sur Pro AI, sans carte bancaire. Ensuite, la formule se choisit "
            "selon votre nombre de clients actifs — un client actif est venu au moins une fois dans l'année ; "
            "les clients dormants restent dans votre base sans compter. Vous changez de formule à tout moment, "
            "sans engagement, depuis **Paramètres › Abonnement**."
        ),
        "link": {"label": "Voir mon abonnement", "to": "/dashboard/settings#settings-billing"},
    },
    {
        "id": "notifications",
        "section": "Campagnes",
        "title": "Pourquoi certains clients ne reçoivent pas mes notifications ?",
        "keywords": ["notification", "reçoit", "reçoivent", "pas", "problème", "push", "bloqué", "activer"],
        "body": (
            "Une notification n'arrive que si le client l'a autorisée sur son téléphone. Le tableau de bord "
            "affiche le pourcentage de clients joignables ; pour les autres, deux leviers : le QR code "
            "d'activation proposé en caisse après un scan, et la relance par SMS depuis la page Campagnes. "
            "Sur iPhone, la carte doit être ajoutée à l'écran d'accueil ou à Wallet pour recevoir les "
            "notifications."
        ),
    },
    {
        "id": "equipe",
        "section": "Paramètres",
        "title": "Comment ajouter un membre de mon équipe ?",
        "keywords": ["équipe", "employé", "collaborateur", "compte", "accès", "staff", "serveur", "ajouter"],
        "body": (
            "Dans **Paramètres › Équipe**, invitez vos collaborateurs par email. Chacun reçoit son propre "
            "accès : un compte « staff » ne voit que le scanner, ce qui permet de savoir qui a scanné quoi et "
            "de retirer un accès sans changer le mot de passe de tout le monde."
        ),
        "link": {"label": "Gérer l'équipe", "to": "/dashboard/settings#settings-team"},
    },
    {
        "id": "rgpd",
        "section": "Données",
        "title": "Mes données et celles de mes clients sont-elles protégées ?",
        "keywords": ["rgpd", "données", "confidentialité", "sécurité", "protection", "cnil", "supprimer", "export"],
        "body": (
            "Les données sont hébergées dans l'Union européenne et le consentement de chaque client est "
            "horodaté à l'inscription, conformément au RGPD. Un client peut à tout moment télécharger ses "
            "données ou demander leur suppression depuis sa carte ; vous pouvez exporter votre base quand "
            "vous le souhaitez depuis la page Clients."
        ),
    },
]

QUICK_REPLIES = [
    {"id": "carte", "label": "Ma carte de fidélité", "question": "Comment personnaliser ma carte de fidélité ?"},
    {"id": "campagnes", "label": "Mes campagnes", "question": "Comment envoyer une campagne ?"},
    {"id": "clients", "label": "Mes clients", "question": "Puis-je importer mes clients existants ?"},
    {"id": "notifications", "label": "Mes notifications", "question": "Pourquoi certains clients ne reçoivent pas mes notifications ?"},
    {"id": "abonnement", "label": "Mon abonnement", "question": "Comment fonctionne mon abonnement ?"},
    {"id": "technique", "label": "Un problème technique", "question": "J'ai un problème technique avec la plateforme."},
    {"id": "autre", "label": "Autre question", "question": ""},
]

GREETING = "Bonjour 👋 Comment pouvons-nous vous aider aujourd'hui ?"
NO_ANSWER = (
    "Je n'ai pas encore la réponse à cette question dans ma base. "
    f"Notre équipe peut vous répondre directement : par chat ({CHAT_DELAY}), "
    f"par email ({SUPPORT_EMAIL_DELAY}) ou au {SUPPORT_PHONE} ({SUPPORT_HOURS})."
)


def init(db):
    global _db
    _db = db
    try:
        _db.support_chats.create_index([("tenant_id", 1), ("created_at", -1)])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Retrieval — small, deterministic, and testable
# ---------------------------------------------------------------------------
_STOPWORDS = {
    "le", "la", "les", "un", "une", "des", "du", "de", "d", "je", "j", "mon", "ma", "mes", "me",
    "comment", "est", "ce", "que", "qui", "quoi", "pour", "a", "à", "au", "aux", "en", "dans",
    "sur", "avec", "et", "ou", "il", "elle", "on", "nous", "vous", "ils", "faire", "fait",
    "puis", "peux", "peut", "dois", "veux", "y", "l", "s", "se", "sont", "suis", "the", "how",
}


def _fold(text: str) -> str:
    """Lower-case, strip accents — so « récompense » matches « recompense »."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def _tokens(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", _fold(text)) if len(t) > 1 and t not in _STOPWORDS]


def _stem(token: str) -> str:
    """Crude French stemming — enough to tie « points » to « point » and
    « campagnes » to « campagne » without pulling in a dependency."""
    for suffix in ("ations", "ation", "ements", "ement", "aux", "ales", "als", "es", "s", "e"):
        if len(token) > 4 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _overlap(q: set, target: set) -> float:
    """How much of the query the target covers. Exact stem match counts 1;
    a prefix match counts 0.7, which is what ties « promo » to « promotion »
    and « stat » to « statistiques » without a real stemmer."""
    total = 0.0
    for token in q:
        if token in target:
            total += 1.0
        elif len(token) >= 4 and any(t.startswith(token) or token.startswith(t) for t in target if len(t) >= 4):
            total += 0.7
    return total


def _score(query_tokens: List[str], article: Dict[str, Any]) -> float:
    if not query_tokens:
        return 0.0
    q = {_stem(t) for t in query_tokens}
    title = {_stem(t) for t in _tokens(article["title"])}
    keys = {_stem(t) for t in article.get("keywords", [])}
    body = {_stem(t) for t in _tokens(article["body"])}
    section = {_stem(t) for t in _tokens(article.get("section", ""))}
    # A hit in the keywords or the title says much more than one in the prose.
    score = (3.0 * _overlap(q, keys) + 2.5 * _overlap(q, title)
             + 1.5 * _overlap(q, section) + 1.0 * _overlap(q, body))
    return score / (len(q) ** 0.5)


def search_kb(question: str, limit: int = 3) -> List[Dict[str, Any]]:
    toks = _tokens(question)
    ranked = sorted(((_score(toks, a), a) for a in KB), key=lambda p: p[0], reverse=True)
    return [a for s, a in ranked[:limit] if s > 0.8]


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------
SYSTEM = (
    "Tu es l'assistant du support FidClic, une plateforme de cartes de fidélité pour les commerces "
    "de proximité en France. Tu réponds au commerçant, en français, avec vouvoiement.\n"
    "RÈGLES ABSOLUES :\n"
    "- Réponds UNIQUEMENT à partir des extraits de documentation fournis. N'invente aucune "
    "fonctionnalité, aucun prix, aucun délai.\n"
    "- Si les extraits ne contiennent pas la réponse, dis-le et propose de contacter l'équipe.\n"
    "- 3 phrases maximum, ton direct et concret. Nomme la page à ouvrir quand c'est utile.\n"
    "- Pas de markdown, pas de listes à puces, pas d'emoji."
)


def _plain(text: str) -> str:
    """The KB is written with a little markdown for the FAQ; the chat bubble
    shows plain text."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text or "")


def answer(question: str, tenant_name: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve, then phrase. The retrieved article is the answer; the model
    only rewrites it for the question actually asked."""
    hits = search_kb(question)
    if not hits:
        return {"answer": NO_ANSWER, "sources": [], "escalate": True, "phrased_by": "none"}

    best = hits[0]
    fallback = _plain(best["body"])
    context = "\n\n".join(f"[{a['title']}]\n{_plain(a['body'])}" for a in hits)

    phrased = None
    try:
        from services import llm
        user = (f"Question du commerçant{f' ({tenant_name})' if tenant_name else ''} : {question}\n\n"
                f"Extraits de la documentation FidClic :\n{context}")
        phrased = llm.complete(SYSTEM, user, max_tokens=220, temperature=0.2)
    except Exception as exc:  # noqa: BLE001 — the model must never break support
        print(f"support_assistant: llm unavailable ({exc})")

    text = (phrased or "").strip()
    return {
        # No key, provider down, or an empty reply → the documentation itself.
        "answer": text or fallback,
        "phrased_by": "model" if text else "kb",
        "sources": [{"id": a["id"], "title": a["title"], "link": a.get("link")} for a in hits],
        "link": best.get("link"),
        "escalate": False,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/api/support/kb")
def get_kb():
    """The FAQ list and the chat's opening state — public, no secrets here."""
    return {
        "faq": [{"id": a["id"], "section": a["section"], "title": a["title"], "body": a["body"],
                 "link": a.get("link")} for a in KB],
        "quick_replies": QUICK_REPLIES,
        "greeting": GREETING,
        "channels": {
            "chat": {"delay": CHAT_DELAY, "online": True},
            "email": {"delay": SUPPORT_EMAIL_DELAY},
            "phone": {"number": SUPPORT_PHONE, "hours": SUPPORT_HOURS},
        },
    }


class ChatMessage(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)


@router.post("/api/owner/support/chat")
def chat(body: ChatMessage,
         token_data: TokenData = Depends(require_role(["business_owner", "administrateur", "manager", "staff", "super_admin"]))):
    try:
        tenant = (_db.tenants.find_one({"id": token_data.tenant_id}) or {}) if _db is not None else {}
    except Exception:
        tenant = {}     # the shop's name is a nicety; the answer is not
    result = answer(body.message, tenant.get("name"))
    now = datetime.now(timezone.utc)
    try:
        _db.support_chats.insert_one({
            "tenant_id": token_data.tenant_id, "email": token_data.email,
            "question": body.message[:1000], "answer": result["answer"],
            "sources": [s["id"] for s in result["sources"]],
            "phrased_by": result["phrased_by"], "created_at": now,
        })
    except Exception:
        pass    # a logging failure must never cost the merchant their answer
    return {**result, "at": now.isoformat()}


@router.get("/api/owner/support/chat")
def chat_history(limit: int = 20,
                 token_data: TokenData = Depends(require_role(["business_owner", "administrateur", "manager", "staff", "super_admin"]))):
    rows = list(_db.support_chats.find(
        {"tenant_id": token_data.tenant_id}, {"_id": 0, "question": 1, "answer": 1, "created_at": 1},
    ).sort("created_at", -1).limit(max(1, min(50, limit))))
    rows.reverse()
    return {"messages": [{"question": r["question"], "answer": r["answer"],
                          "at": r["created_at"].isoformat() if r.get("created_at") else None}
                         for r in rows], "greeting": GREETING, "quick_replies": QUICK_REPLIES}
