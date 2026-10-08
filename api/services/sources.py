"""
Where a customer came from — one list for the whole platform (user,
2026-10-08: « accuracy honi chahiye »).

Every place that writes or reads `customers.acquisition_source` goes through
this module: the signup page, the join endpoint, the Clients filter, Analyses,
the Dashboard, History, the super-admin. A source has one key, one label, one
place in the order, so « Instagram » means the same customers everywhere and
nothing is silently counted as « QR code en magasin ».

HOW A SOURCE IS DECIDED
    • The owner shares one link per channel (Paramètres › Lien d'inscription):
      /join/<slug>/insta, /wa, /fb, /tiktok, /site, /google, and the shop's
      QR codes open /join/<slug>/qr. The link says the channel; the customer
      is never asked.
    • A friend's card scanned (/join/<slug>?p=FT-…) is « Parrainage », always —
      never « QR code en magasin », which is only for new customers who came
      to the shop on their own.
    • An imported file is « Import de fichier ».
    • The bare link with no channel asks the customer « Comment nous avez-vous
      connu ? »; no answer is « Non renseigné », never a guess.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# key → label, in the order the platform shows them
SOURCES: Dict[str, str] = {
    "qr_store": "QR code en magasin",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "whatsapp": "WhatsApp",
    "tiktok": "TikTok",
    "google": "Google",
    "website": "Site web",
    "email": "E-mail",
    "sms": "SMS",
    "referral": "Parrainage",
    "import": "Import de fichier",
    "autre": "Autre",
}
UNKNOWN = "none"
UNKNOWN_LABEL = "Non renseigné"

# the sources a customer can arrive by on the signup page (a channel link or
# the « Comment nous avez-vous connu ? » answer)
SIGNUP_SOURCES = ("qr_store", "instagram", "facebook", "whatsapp", "tiktok", "google", "website",
                  "email", "sms", "autre")

# the short words the owner's links use, and every spelling we accept
ALIASES: Dict[str, str] = {
    "qr": "qr_store", "qrcode": "qr_store", "qr_code": "qr_store", "qr_store": "qr_store", "store": "qr_store",
    "magasin": "qr_store", "in_store": "qr_store", "instore": "qr_store", "qr_code_in_store": "qr_store",
    "insta": "instagram", "ig": "instagram", "instagram": "instagram",
    "fb": "facebook", "facebook": "facebook", "meta": "facebook",
    "wa": "whatsapp", "whatsapp": "whatsapp", "whats_app": "whatsapp", "wapp": "whatsapp",
    "tt": "tiktok", "tiktok": "tiktok", "tik_tok": "tiktok",
    "google": "google", "gmb": "google", "maps": "google", "google_maps": "google",
    "site": "website", "web": "website", "website": "website", "site_web": "website",
    "email": "email", "mail": "email", "e_mail": "email", "newsletter": "email",
    "sms": "sms", "texto": "sms",
    "parrainage": "referral", "referral": "referral", "ami": "referral",
    "import": "import", "autre": "autre", "other": "autre",
}

# what each channel link looks like: /join/<slug>/<word>
CHANNEL_WORDS: Dict[str, str] = {
    "qr_store": "qr", "instagram": "insta", "facebook": "fb", "whatsapp": "wa",
    "tiktok": "tiktok", "google": "google", "website": "site", "email": "mail", "sms": "sms",
}


def normalize(raw: Optional[str]) -> Optional[str]:
    """Any spelling → its key, or None when it is not a source we know."""
    if not raw:
        return None
    k = re.sub(r"[^a-z_]", "", str(raw).strip().lower().replace(" ", "_").replace("-", "_"))
    return ALIASES.get(k)


def key_of(customer: Dict) -> str:
    """The customer's source key, as every page groups it: « Non renseigné »
    when nothing was recorded, « Autre » for an older free-text value."""
    raw = customer.get("acquisition_source")
    if not raw or not str(raw).strip():
        return UNKNOWN
    return normalize(raw) or "autre"


def label(key: Optional[str]) -> str:
    return SOURCES.get(key or "", UNKNOWN_LABEL)


def ordered(counts: Dict[str, int]) -> List[Dict]:
    """[{key, label, count}] in the platform's order, empty ones left out."""
    keys = list(SOURCES) + [UNKNOWN]
    return [{"key": k, "label": label(k), "count": counts[k]} for k in keys if counts.get(k)]
