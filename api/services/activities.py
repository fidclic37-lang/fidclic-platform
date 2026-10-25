"""
Activités — the precise trade under each sector, and how often its regulars
come back (user, 2026-10-25: « baaki sectors ka rhythme galat lag rha hai…
proper web research kro… fleuriste, cbd and tabac, opticien, librairie etc.
sab alag kro »).

WHAT THE FIGURE IS
    The usual number of days between two visits of a REGULAR (a loyalty-card
    client with three visit days or more) — not the population's average,
    which counts people who almost never come. It is only where brain-v2
    starts for a shop: replaced by what the network learned for the activity
    (30 regulars), then by the shop's own median (10 regulars).

WHERE EACH FIGURE COMES FROM (`basis`)
    « étude »      a published survey or study
    « pratique »   what the trade itself recommends or observes (federations,
                   professional guides, booking-software benchmarks)
    « estimation » no usable source found; reasoned from neighbouring trades
    The sources are listed in `source`, short. Research of 2026-10-25.

Chosen by the owner in Établissement › « Activité précise » (optional);
older shops whose sector already names a trade (« boulangerie », « barbier »)
are read through ALIASES.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

ACTIVITIES: List[Dict[str, Any]] = [
    # ── Boulangerie / pâtisserie
    {"key": "boulangerie", "label": "Boulangerie", "sector": "bakery", "gap": 2, "basis": "étude",
     "source": "Apaq-W 2022/2025 : 82–84 % achètent du pain chaque semaine, 27–30 % tous les jours ; fidèles 3–4 fois/semaine"},
    {"key": "patisserie", "label": "Pâtisserie", "sector": "bakery", "gap": 7, "basis": "estimation",
     "source": "achat plaisir, surtout le week-end"},
    {"key": "chocolatier", "label": "Chocolatier / confiserie", "sector": "bakery", "gap": 30, "basis": "estimation",
     "source": "achat cadeau et saisonnier (fêtes)"},
    # ── Café
    {"key": "cafe", "label": "Café / bistrot", "sector": "cafe", "gap": 3, "basis": "pratique",
     "source": "NielsenIQ OPUS 2023 : 46 % prennent un café en CHR chaque semaine ; habitués 2–3 fois/semaine"},
    {"key": "coffee_shop", "label": "Coffee shop", "sector": "cafe", "gap": 3, "basis": "pratique",
     "source": "programmes de fidélité café : 2–3 visites/semaine, jusqu'à 4–5 pour les plus fidèles"},
    {"key": "salon_the", "label": "Salon de thé", "sector": "cafe", "gap": 10, "basis": "estimation",
     "source": "sortie plus occasionnelle qu'un café"},
    {"key": "juice_bar", "label": "Bar à jus / smoothies", "sector": "cafe", "gap": 7, "basis": "estimation",
     "source": "comme un coffee shop, moins quotidien"},
    {"key": "glacier", "label": "Glacier", "sector": "cafe", "gap": 7, "basis": "estimation",
     "source": "saisonnier : hebdomadaire l'été, rare l'hiver"},
    # ── Bar
    {"key": "bar", "label": "Bar de quartier", "sector": "bar", "gap": 7, "basis": "estimation",
     "source": "habitués hebdomadaires ; NielsenIQ : visites boisson/bar mensuelles 49 %"},
    {"key": "bar_tabac", "label": "Bar-tabac / PMU", "sector": "bar", "gap": 2, "basis": "pratique",
     "source": "Confédération des buralistes : ~10 M de clients par jour"},
    {"key": "bar_vin", "label": "Bar à vin", "sector": "bar", "gap": 14, "basis": "estimation",
     "source": "sortie entre amis, tous les 15 jours"},
    {"key": "bar_cocktails", "label": "Bar à cocktails", "sector": "bar", "gap": 14, "basis": "estimation",
     "source": "sortie du week-end"},
    {"key": "pub", "label": "Pub", "sector": "bar", "gap": 7, "basis": "estimation",
     "source": "soirées matchs, habitués hebdomadaires"},
    # ── Restaurant
    {"key": "restaurant", "label": "Restaurant traditionnel", "sector": "restaurant", "gap": 21, "basis": "pratique",
     "source": "55 % fréquentent au moins 2 fois/mois les restaurants à carte de fidélité ; habitués toutes les 3 semaines"},
    {"key": "brasserie", "label": "Brasserie (déjeuner)", "sector": "restaurant", "gap": 10, "basis": "estimation",
     "source": "déjeuner de travail, habitués 1 fois/semaine ou plus"},
    {"key": "restauration_rapide", "label": "Restauration rapide / snack", "sector": "restaurant", "gap": 10,
     "basis": "étude", "source": "Simon-Kucher 2017 : fast-food 1 à 3 fois/mois pour les clients réguliers"},
    {"key": "kebab", "label": "Kebab", "sector": "restaurant", "gap": 10, "basis": "étude",
     "source": "restauration rapide : 1 à 3 fois/mois (Simon-Kucher)"},
    {"key": "burger", "label": "Burger", "sector": "restaurant", "gap": 14, "basis": "étude",
     "source": "restauration rapide : 1 à 3 fois/mois (Simon-Kucher)"},
    {"key": "sushi", "label": "Sushi / japonais", "sector": "restaurant", "gap": 14, "basis": "estimation",
     "source": "sur place ou à emporter, toutes les 2 semaines"},
    {"key": "creperie", "label": "Crêperie", "sector": "restaurant", "gap": 21, "basis": "estimation",
     "source": "comme un restaurant à table"},
    {"key": "traiteur", "label": "Traiteur", "sector": "restaurant", "gap": 14, "basis": "estimation",
     "source": "plats à emporter, toutes les 2 semaines"},
    # ── Pizzeria
    {"key": "pizzeria", "label": "Pizzeria", "sector": "pizzeria", "gap": 14, "basis": "étude",
     "source": "Simon-Kucher 2017 : chaînes de pizza 1 à 3 fois/mois ; pizzeria = 51 % des pizzas (Gira)"},
    # ── Coiffure
    {"key": "barbier", "label": "Barbier", "sector": "salon", "gap": 21, "basis": "pratique",
     "source": "barbershops : retour toutes les 2 à 4 semaines, dégradé 1 à 2 (Pall Mall Barbers, Zenoti)"},
    {"key": "coiffure_homme", "label": "Coiffure homme", "sector": "salon", "gap": 35, "basis": "étude",
     "source": "Kantar/Xerfi : hommes ~6,6 visites/an en moyenne ; habitués toutes les 4–6 semaines"},
    {"key": "coiffure_femme", "label": "Coiffure femme", "sector": "salon", "gap": 56, "basis": "étude",
     "source": "Kantar/Xerfi, UNEC : femmes ~4,4 visites/an en moyenne ; habituées toutes les 6–8 semaines"},
    {"key": "coiffure_mixte", "label": "Coiffure mixte", "sector": "salon", "gap": 42, "basis": "étude",
     "source": "entre hommes (4–6 semaines) et femmes (6–8 semaines)"},
    # ── Beauté / bien-être
    {"key": "institut", "label": "Institut de beauté / épilation", "sector": "spa", "gap": 28, "basis": "pratique",
     "source": "instituts : entretien épilation toutes les 3 à 4 semaines"},
    {"key": "onglerie", "label": "Onglerie / prothésiste ongulaire", "sector": "spa", "gap": 21, "basis": "pratique",
     "source": "remplissage gel toutes les 2 à 3 semaines ; semi-permanent 3 semaines max"},
    {"key": "spa_massage", "label": "Spa / massage", "sector": "spa", "gap": 35, "basis": "pratique",
     "source": "clients réguliers environ une fois par mois ; la moitié ne revient pas après la 1re visite"},
    # ── Sport
    {"key": "fitness", "label": "Salle de sport / fitness", "sector": "gym", "gap": 4, "basis": "étude",
     "source": "IHRSA : ~2 visites/semaine par abonné (101–104/an)"},
    {"key": "crossfit", "label": "CrossFit / cross-training", "sector": "gym", "gap": 3, "basis": "pratique",
     "source": "boxes : 2 à 4 séances/semaine"},
    {"key": "yoga", "label": "Yoga / Pilates", "sector": "gym", "gap": 5, "basis": "pratique",
     "source": "studios : 1 à 3 cours/semaine (bsport)"},
    {"key": "danse", "label": "École de danse", "sector": "gym", "gap": 7, "basis": "estimation",
     "source": "cours hebdomadaires"},
    {"key": "arts_martiaux", "label": "Arts martiaux / boxe", "sector": "gym", "gap": 5, "basis": "estimation",
     "source": "2 entraînements/semaine"},
    # ── Commerce
    {"key": "tabac_presse", "label": "Tabac / presse", "sector": "retail", "gap": 2, "basis": "étude",
     "source": "Santé publique France 2022 : 12,6 cigarettes/jour, 4 fumeurs sur 5 au buraliste → un paquet tous les 1 à 2 jours"},
    {"key": "cbd", "label": "Boutique CBD", "sector": "retail", "gap": 10, "basis": "estimation",
     "source": "budget client 50–200 €/mois, soit 2 à 4 achats par mois"},
    {"key": "fleuriste", "label": "Fleuriste", "sector": "retail", "gap": 45, "basis": "étude",
     "source": "Kantar pour VALHOR 2024 : chez le fleuriste ~5 végétaux/an par foyer acheteur ; habitués plus souvent"},
    {"key": "opticien", "label": "Opticien", "sector": "retail", "gap": 180, "basis": "étude",
     "source": "renouvellement des lunettes tous les 1 à 2 ans (remboursement tous les 2 ans) ; entre-temps ajustements, lentilles"},
    {"key": "librairie", "label": "Librairie", "sector": "retail", "gap": 30, "basis": "étude",
     "source": "CNL/Ipsos 2025 : 18 livres lus/an ; clients de librairie au moins une fois par mois"},
    {"key": "pressing", "label": "Pressing", "sector": "retail", "gap": 14, "basis": "pratique",
     "source": "client régulier 1 à 4 fois par mois"},
    {"key": "boucherie", "label": "Boucherie / charcuterie", "sector": "retail", "gap": 7, "basis": "étude",
     "source": "18 % vont chez le boucher au moins une fois par semaine (2019)"},
    {"key": "fromagerie", "label": "Fromagerie", "sector": "retail", "gap": 10, "basis": "estimation",
     "source": "commerce de bouche, un peu moins que la boucherie"},
    {"key": "primeur", "label": "Primeur (fruits et légumes)", "sector": "retail", "gap": 7, "basis": "étude",
     "source": "25 % vont chez le primeur au moins une fois par semaine (2019)"},
    {"key": "caviste", "label": "Caviste", "sector": "retail", "gap": 21, "basis": "estimation",
     "source": "achat pour un repas ou une occasion, toutes les 3 semaines"},
    {"key": "epicerie", "label": "Épicerie / épicerie fine", "sector": "retail", "gap": 7, "basis": "étude",
     "source": "CSA/CGAD 2022 : 51 % fréquentent un commerce alimentaire de proximité chaque semaine"},
    {"key": "mode", "label": "Prêt-à-porter / accessoires", "sector": "retail", "gap": 60, "basis": "estimation",
     "source": "achats saisonniers"},
    {"key": "autre_commerce", "label": "Autre commerce", "sector": "retail", "gap": 30, "basis": "estimation",
     "source": "—"},
    {"key": "autre", "label": "Autre activité", "sector": "other", "gap": 21, "basis": "estimation", "source": "—"},
]
BY_KEY: Dict[str, Dict[str, Any]] = {a["key"]: a for a in ACTIVITIES}

# A sector without a precise activity starts from its most common trade.
SECTOR_DEFAULT = {"bakery": "boulangerie", "cafe": "cafe", "bar": "bar", "restaurant": "restaurant",
                  "pizzeria": "pizzeria", "salon": "coiffure_mixte", "spa": "institut", "gym": "fitness",
                  "retail": "autre_commerce", "other": "autre"}

# Older shops (and the demo) carry the trade in the sector itself.
ALIASES: Dict[str, str] = {
    "boulangerie": "boulangerie", "boulangerie-patisserie": "boulangerie", "patisserie": "patisserie",
    "pâtisserie": "patisserie", "chocolatier": "chocolatier", "café": "cafe", "coffee": "coffee_shop",
    "coffee shop": "coffee_shop", "salon de thé": "salon_the", "tea salon": "salon_the", "juice bar": "juice_bar",
    "glacier": "glacier", "wine bar": "bar_vin", "bar à vin": "bar_vin", "pub": "pub", "bar-tabac": "bar_tabac",
    "brasserie": "brasserie", "crêperie": "creperie", "creperie": "creperie", "sushi": "sushi", "kebab": "kebab",
    "burger": "burger", "traiteur": "traiteur", "barbier": "barbier", "barber": "barbier",
    "coiffeur": "coiffure_mixte", "coiffure": "coiffure_mixte", "hair salon": "coiffure_mixte",
    "salon de coiffure": "coiffure_mixte", "institut": "institut", "institut de beauté": "institut",
    "esthétique": "institut", "onglerie": "onglerie", "massage": "spa_massage", "fitness": "fitness",
    "salle de sport": "fitness", "crossfit": "crossfit", "yoga": "yoga", "pilates": "yoga", "dance": "danse",
    "danse": "danse", "boxe": "arts_martiaux", "tabac": "tabac_presse", "presse": "tabac_presse",
    "cbd": "cbd", "fleuriste": "fleuriste", "florist": "fleuriste", "opticien": "opticien",
    "optician": "opticien", "librairie": "librairie", "book store": "librairie", "pressing": "pressing",
    "boucherie": "boucherie", "fromagerie": "fromagerie", "primeur": "primeur", "caviste": "caviste",
    "épicerie": "epicerie", "epicerie": "epicerie",
}


def of(tenant: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The shop's activity: the one it chose, else one its sector names, else
    its sector's most common trade."""
    t = tenant or {}
    key = str(t.get("activity_key") or "").strip()
    if key in BY_KEY:
        return BY_KEY[key]
    sector = str(t.get("sector") or "").strip().lower()
    if sector in ALIASES:
        return BY_KEY[ALIASES[sector]]
    from features import client_brain as CB
    return BY_KEY[SECTOR_DEFAULT.get(CB.sector_key(sector), "autre")]


def choices(sector: Optional[str]) -> List[Dict[str, str]]:
    """What Établissement offers under a sector."""
    from features import client_brain as CB
    s = CB.sector_key(sector)
    return [{"value": a["key"], "label": a["label"]} for a in ACTIVITIES if a["sector"] == s]
