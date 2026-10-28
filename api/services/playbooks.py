"""
Playbooks — what to advise each « Activité précise » (user, 2026-10-26: a café
was getting salon advice; « jahaan jahaan possible and important ho »).

ONE PLAYBOOK PER ACTIVITY
    Every activity of services/activities.py resolves to a playbook (the one it
    chose, else the one its sector names, else its sector's most common trade —
    the same rule as the rhythms). A playbook says:

      food / drinks / meals   what the shop sells: a boulangerie is a food shop
                              without a Happy Hour; a bar sells drinks, not a
                              menu du jour; a barbier sells prestations
      items, offer, emoji     the words its messages use
      levers                  its own advice: « opportunite » on the
                              opportunities shelf, « idee » for the trade's
                              key moments (months), each with a campaign ready
                              for the composer (`template`, key « pb:… ») or a
                              page to open (`to`)
      facts                   the only figures shown: each with its source,
                              year and link. No source → no number, advice only
                              (the old « estimation courante du secteur » is gone)
      generic_facts           which of the engine's own advice a figure backs

      rules                   the trade's rules (RULES): told to FidClic IA
                              and checked on what it wrote (`breaks_rules`)
      auto                    the words « Client inactif » and
                              « Géolocalisation » open on

    Insights, the Copilote and the Tableau de bord all read `of(tenant)`;
    every IA brief carries `prompt_context` (PR2).

RULES OF THE TRADE
    Tobacco is never promoted (loi Évin): a tabac's offers are on presse,
    jeux, services. A CBD shop makes no health claim. Alcohol advice speaks of
    tastings and events, never of drinking more.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional

from services import activities as A

# ---------------------------------------------------------------------------
# The figures — each one read at its source (research of 2026-10-28)
# ---------------------------------------------------------------------------
FACTS: Dict[str, Dict[str, Any]] = {
    "avis_google": {
        "short": "83 % lisent les avis sur Google",
        "text": "83 % des consommateurs lisent les avis clients sur Google avant de choisir un commerce local.",
        "source": "BrightLocal, Local Consumer Review Survey", "year": 2025,
        "url": "https://www.brightlocal.com/research/local-consumer-review-survey-2025/"},
    "bouche_oreille": {
        "short": "89 % font confiance à leurs proches",
        "text": "89 % des consommateurs font confiance aux recommandations des personnes qu'ils connaissent.",
        "source": "Nielsen, Trust in Advertising", "year": 2021,
        "url": "https://develop.nielsen.com/wp-content/uploads/sites/2/2022/02/2021-Nielsen-Trust-In-Advertising-U.S.-sell-sheet.pdf"},
    "anniversaire": {
        "short": "≈ 5× plus d'achats qu'un envoi classique",
        "text": "Un message d'anniversaire déclenche environ 5 fois plus d'achats qu'un envoi groupé "
                "(0,49 % contre 0,10 %).",
        "source": "Experian CheetahMail, via MarketingProfs", "year": 2010,
        "url": "https://www.marketingprofs.com/charts/2010/3751/birthday-anniversary-emails-generate-more-revenue"},
    "galette": {
        "short": "≈ 10 % du CA annuel",
        "text": "La galette des rois représente environ 10 % du chiffre d'affaires annuel des artisans "
                "boulangers-pâtissiers.",
        "source": "Square France", "year": 2024,
        "url": "https://squareup.com/fr/fr/townsquare/galette-des-rois"},
    "fete_meres_fleurs": {
        "short": "jusqu'à 6 % du CA annuel",
        "text": "La Fête des mères peut représenter jusqu'à 6 % du chiffre d'affaires annuel d'un fleuriste.",
        "source": "Fédération Française des Artisans Fleuristes (FFAF)", "year": 2022,
        "url": "https://www.observatoiredelafranchise.fr/indiscretions-actualite/CARREMENT-FLEURS-carrement-fleurs-presente-les-fleurs-les-plus-plebiscitees-par-les-francais-75446.htm"},
    "paques_chocolat": {
        "short": "11 % des ventes de l'année",
        "text": "Pâques pèse 11 % des ventes annuelles de chocolat (357 M€ en 2023).",
        "source": "NielsenIQ, via LSA", "year": 2023,
        "url": "https://www.lsa-conso.fr/les-chocolats-de-paques-restent-incontournables,454684"},
    "lunettes_2_ans": {
        "short": "1 paire remboursée tous les 2 ans",
        "text": "À partir de 16 ans, l'Assurance Maladie rembourse une paire de lunettes tous les 2 ans "
                "(1 an si la vue change).",
        "source": "Assurance Maladie (forum ameli)", "year": 2024,
        "url": "https://forum-assures.ameli.fr/questions/1451370-lunettes-changement-vue-date-prescription"},
    "relance_sport": {
        "short": "45 % de résiliations en moins",
        "text": "Un membre inactif qu'on fait revenir résilie 45 % moins souvent qu'un membre qu'on laisse partir.",
        "source": "IHRSA, Member Retention Report", "year": 2016,
        "url": "https://www.attractionsmanagement.com/attractions-news/Fitness-retention-IHRSA/325741"},
}

# Every shop: the engine's own advice these figures back.
GENERIC = {"avis_google": "avis_google", "parrainage": "bouche_oreille", "anniversaire": "anniversaire"}


def _t(key: str, title: str, message: str, segment: str = "all") -> Dict[str, str]:
    return {"key": f"pb:{key}", "title": title, "message": message, "segment": segment}


def _opp(key, category, title, body, image, *, template=None, to=None, label=None, fact=None, months=None):
    lv = {"key": key, "shelf": "opportunite", "category": category, "title": title, "body": body,
          "image": image, "label": label or ("Préparer la campagne" if template else "Configurer")}
    if template:
        lv["template"] = template
    if to:
        lv["to"] = to
    if fact:
        lv["fact"] = fact
    if months:
        lv["months"] = months
    return lv


def _idea(key, months, title, body, image, template, *, fact=None, replaces=None, category="evenement"):
    lv = {"key": key, "shelf": "idee", "category": category, "title": title, "body": body, "image": image,
          "months": months, "template": template, "label": "Utiliser ce modèle"}
    if fact:
        lv["fact"] = fact
    if replaces:
        lv["replaces"] = replaces
    return lv


# ---------------------------------------------------------------------------
# Families — one per sector; an activity inherits its family's levers after its own
# ---------------------------------------------------------------------------
PRODUITS, PRESTATIONS = ("produit", "produits"), ("prestation", "prestations")

REBOOK = _opp("rdv_en_caisse", "fidelisation", "Proposez le prochain rendez-vous en caisse",
              "Au moment de payer, proposez de réserver la prochaine visite au bon rythme : c'est le "
              "geste qui fait revenir sans relance.", "fidelite", to="/dashboard/automations",
              label="Voir les automatisations")

FAMILIES: Dict[str, Dict[str, Any]] = {
    "bakery": {"food": True, "drinks": False, "meals": False, "items": PRODUITS, "emoji": "🥐",
               "offer": "1 viennoiserie offerte", "levers": [
        _opp("formule_midi", "ventes", "Proposez une formule déjeuner",
             "Sandwich, boisson et dessert à prix rond : vos habitués du matin reviennent le midi.",
             "menu", template=_t("formule_midi", "🥪 La formule déjeuner est arrivée",
                                 "Sandwich + boisson + dessert, du lundi au vendredi. On vous attend ce midi !")),
        _idea("galette", [1], "Galette des rois",
              "Le temps fort de janvier : annoncez vos galettes et prenez les commandes à l'avance.",
              "fetes", _t("galette", "👑 Nos galettes des rois sont là",
                          "Frangipane ou briochée : commandez la vôtre dès maintenant, sur présentation de votre carte."),
              fact="galette"),
        _idea("buche", [12], "Bûches de Noël",
              "Ouvrez les commandes de bûches dès fin novembre : vos fidèles réservent en premier.",
              "fetes", _t("buche", "🎄 Commandez votre bûche de Noël",
                          "Nos bûches sont en commande : réservez la vôtre en boutique avant le 20 décembre."),
              replaces="fetes"),
    ]},
    "cafe": {"food": True, "drinks": True, "meals": False, "items": PRODUITS, "emoji": "☕",
             "offer": "1 café offert", "levers": [
        _opp("petit_dej", "ventes", "Lancez une formule petit-déjeuner",
             "Café + viennoiserie à prix rond le matin : le premier passage de la journée devient une habitude.",
             "menu", template=_t("petit_dej", "☕ La formule petit-déj est servie",
                                 "Café + viennoiserie à petit prix tous les matins. À demain ?")),
        _opp("carte_a_emporter", "fidelisation", "Récompensez aussi la vente à emporter",
             "Scannez la carte pour chaque café à emporter : ce sont souvent vos clients les plus réguliers.",
             "fidelite", to="/dashboard/scan", label="Ouvrir la caisse"),
    ]},
    "bar": {"food": True, "drinks": True, "meals": False, "items": PRODUITS, "emoji": "✨", "rules": ["alcool"],
            "offer": "1 boisson offerte", "levers": [
        _opp("soirees", "acquisition", "Créez un rendez-vous chaque semaine",
             "Quiz, match, concert ou afterwork le même soir chaque semaine : vos habitués savent quand venir "
             "et amènent des amis.", "proximite",
             template=_t("soirees", "🎉 Votre rendez-vous de la semaine",
                         "Ce jeudi, on vous attend pour notre soirée de la semaine. Venez avec vos amis !")),
        _idea("fete_musique", [6], "Fête de la musique",
              "Le 21 juin, annoncez votre programme à vos clients une semaine avant.", "ete",
              _t("fete_musique", "🎶 Fête de la musique chez nous",
                 "Le 21 juin, on fête la musique ensemble : programme en boutique. On vous attend !")),
    ]},
    "restaurant": {"food": True, "drinks": True, "meals": True, "items": PRODUITS, "emoji": "🍽️",
                   "offer": "1 dessert offert", "levers": [
        _opp("reservation", "fidelisation", "Faites réserver vos habitués pour le week-end",
             "Un message le mercredi rappelle à vos habitués de réserver leur table avant que ce soit complet.",
             "fidelite", template=_t("reservation", "🍽️ Réservez votre table ce week-end",
                                     "Les tables partent vite : réservez dès maintenant pour ce week-end. À bientôt !")),
    ]},
    "pizzeria": {"food": True, "drinks": True, "meals": True, "items": PRODUITS, "emoji": "🍕",
                 "offer": "1 boisson offerte", "levers": [
        _opp("soir_calme", "ventes", "Animez votre soir le plus calme",
             "Une « pizza du jour » le soir le plus calme de la semaine donne une raison de venir ou de commander.",
             "heures_creuses", template=_t("soir_calme", "🍕 Ce soir, la pizza du jour",
                                          "Ce soir seulement : découvrez notre pizza du jour, sur place ou à emporter.")),
        _opp("emporter", "fidelisation", "Comptez aussi les commandes à emporter",
             "Scannez la carte à chaque retrait : les clients à emporter sont souvent les plus fréquents.",
             "fidelite", to="/dashboard/scan", label="Ouvrir la caisse"),
    ]},
    "salon": {"food": False, "drinks": False, "meals": False, "items": PRESTATIONS, "emoji": "✂️",
              "offer": "-10 % sur votre prochaine coupe", "levers": [
        REBOOK,
        _opp("rappel_coupe", "fidelisation", "Rappelez quand la coupe a besoin d'être refaite",
             "Un message au bon moment, quand la coupe commence à pousser, fait revenir avant que le client "
             "aille ailleurs.", "inactifs",
             template=_t("rappel_coupe", "✂️ C'est le moment de rafraîchir votre coupe",
                         "Votre coupe commence à pousser ? Réservez votre prochain passage cette semaine.",
                         "inactive")),
        _idea("fetes_coiffure", [12], "Rendez-vous des fêtes",
              "Les créneaux de fin décembre partent vite : invitez vos clients à réserver tôt.", "fetes",
              _t("fetes_coiffure", "✨ Réservez pour les fêtes",
                 "Les créneaux de fin d'année partent vite : réservez dès maintenant votre rendez-vous."),
              replaces="fetes"),
    ]},
    "spa": {"food": False, "drinks": False, "meals": False, "items": PRESTATIONS, "emoji": "💆",
            "offer": "-10 % sur votre prochain soin", "levers": [
        REBOOK,
        _opp("forfaits", "ventes", "Proposez des forfaits de soins",
             "Un forfait de plusieurs séances payé d'avance fait revenir au bon rythme et lisse votre agenda.",
             "panier_services", template=_t("forfaits", "💆 Nos forfaits soins",
                                            "Plusieurs séances à tarif doux : demandez nos forfaits lors de votre prochain passage.")),
        _idea("cartes_cadeaux_meres", [5], "Cartes cadeaux Fête des mères",
              "Un soin offert est un cadeau facile : mettez en avant vos cartes cadeaux en mai.", "printemps",
              _t("cartes_cadeaux_meres", "💐 Offrez un soin pour la Fête des mères",
                 "Nos cartes cadeaux sont disponibles en institut : le cadeau qui fait toujours plaisir.")),
        _idea("cartes_cadeaux_noel", [12], "Cartes cadeaux de Noël",
              "En décembre, vos clients cherchent des cadeaux : proposez vos cartes cadeaux.", "fetes",
              _t("cartes_cadeaux_noel", "🎁 Offrez un moment de détente",
                 "Pour Noël, offrez une carte cadeau : disponible en institut dès maintenant."),
              replaces="fetes"),
    ]},
    "gym": {"food": False, "drinks": False, "meals": False, "items": ("séance", "séances"), "emoji": "💪",
            "offer": "1 séance offerte", "generic_facts": {"inactifs": "relance_sport"}, "levers": [
        _opp("seance_ami", "acquisition", "Offrez une séance d'essai à un ami",
             "Un membre qui vient avec un ami s'entraîne plus régulièrement : proposez une séance découverte "
             "pour un proche.", "parrainage",
             template=_t("seance_ami", "💪 Venez avec un ami",
                         "Cette semaine, invitez un ami pour une séance découverte offerte. Présentez votre carte !")),
        _opp("relance_membres", "fidelisation", "Faites revenir les membres qui décrochent",
             "Un membre qui espace ses séances est celui qui résiliera : un message quand il ralentit le fait "
             "revenir.", "inactifs", fact="relance_sport",
             template=_t("relance_membres", "💪 On vous garde votre place",
                         "Ça fait un moment ! Reprenez cette semaine : on vous attend à la salle.", "inactive")),
        _idea("resolutions", [1], "Bonnes résolutions",
              "Janvier est le mois des inscriptions : relancez aussi vos anciens membres.", "printemps",
              _t("resolutions", "💪 Nouvelle année, nouvelle forme",
                 "C'est le moment de reprendre : on vous attend cette semaine à la salle !"),
              category="hiver"),
        _idea("avant_ete", [4, 5], "Objectif été",
              "Avant l'été, vos membres veulent s'y remettre : proposez un programme de quelques semaines.",
              "ete", _t("avant_ete", "☀️ Objectif été",
                        "Prêt pour l'été ? Notre programme de remise en forme commence cette semaine."),
              category="printemps"),
    ]},
    "retail": {"food": False, "drinks": False, "meals": False, "items": PRODUITS, "emoji": "✨",
               "offer": "-10 % sur votre prochain achat", "levers": []},
    "other": {"food": False, "drinks": False, "meals": False, "items": PRODUITS, "emoji": "✨",
              "offer": "une réduction offerte", "levers": []},
}

# ---------------------------------------------------------------------------
# Activities — what differs from the family (own levers come first)
# ---------------------------------------------------------------------------
NOEL_COMMANDES = lambda k, img="fetes": _idea(  # noqa: E731
    f"{k}_noel", [12], "Commandes de fêtes",
    "Ouvrez les commandes de fin d'année tôt : vos fidèles réservent en premier.", img,
    _t(f"{k}_noel", "🎄 Les commandes de fêtes sont ouvertes",
       "Réservez dès maintenant pour les fêtes, en boutique, sur présentation de votre carte."),
    replaces="fetes")

ACTIVITIES: Dict[str, Dict[str, Any]] = {
    "boulangerie": {},
    "patisserie": {"offer": "1 pâtisserie offerte", "emoji": "🍰", "levers": [
        _opp("gateaux_commande", "ventes", "Prenez les gâteaux sur commande",
             "Anniversaires, baptêmes, fêtes : rappelez que vous faites les gâteaux sur commande.", "panier",
             template=_t("gateaux_commande", "🎂 Vos gâteaux sur commande",
                         "Un anniversaire, une fête ? Commandez votre gâteau en boutique, 48 h à l'avance.")),
        _idea("patisserie_meres", [5], "Fête des mères",
              "Un entremets pour la Fête des mères : prenez les commandes la semaine d'avant.", "printemps",
              _t("patisserie_meres", "💐 Un gâteau pour la Fête des mères",
                 "Commandez votre entremets pour la Fête des mères dès maintenant, en boutique.")),
    ]},
    "chocolatier": {"offer": "1 ballotin offert", "emoji": "🍫", "own_levers": True, "levers": [
        _idea("paques", [3, 4], "Pâques",
              "Le deuxième temps fort de l'année : annoncez vos créations et prenez les commandes.", "printemps",
              _t("paques", "🐣 Les chocolats de Pâques sont arrivés",
                 "Œufs, poules, fritures : découvrez nos créations de Pâques en boutique."),
              fact="paques_chocolat", replaces="printemps"),
        _idea("choco_noel", [12], "Noël",
              "Ballotins et coffrets : vos fidèles commandent tôt pour offrir.", "fetes",
              _t("choco_noel", "🎄 Nos coffrets de Noël",
                 "Ballotins et coffrets de fêtes : réservez les vôtres dès maintenant en boutique."),
              replaces="fetes"),
        _idea("choco_valentin", [2], "Saint-Valentin",
              "Un coffret à offrir : annoncez-le une semaine avant.", "saint_valentin",
              _t("choco_valentin", "💝 Un coffret pour la Saint-Valentin",
                 "Faites-vous plaisir à deux : nos coffrets de Saint-Valentin sont en boutique."),
              replaces="saint_valentin"),
        _opp("coffrets_entreprise", "acquisition", "Proposez des coffrets aux entreprises",
             "Les cadeaux d'affaires de fin d'année se commandent dès octobre : proposez-les à vos clients pros.",
             "panier", months=[9, 10, 11],
             template=_t("coffrets_entreprise", "🎁 Coffrets pour vos équipes",
                         "Cadeaux clients ou salariés : demandez nos coffrets de fin d'année en boutique.")),
    ]},
    "cafe": {},
    "coffee_shop": {"levers": [
        _opp("boisson_saison", "ventes", "Lancez une boisson de saison",
             "Une boisson du moment, renouvelée à chaque saison, donne une raison de revenir la goûter.",
             "offre_moment", template=_t("boisson_saison", "☕ La boisson de la saison est là",
                                         "Venez goûter notre nouvelle boisson de saison cette semaine !")),
    ]},
    "salon_the": {"offer": "1 thé offert", "emoji": "🫖", "levers": [
        _opp("brunch", "ventes", "Proposez un goûter ou un brunch le week-end",
             "Une formule du week-end transforme une sortie occasionnelle en rendez-vous.", "menu",
             template=_t("brunch", "🫖 Le brunch du week-end",
                         "Ce week-end, notre formule brunch vous attend. Pensez à réserver !")),
    ]},
    "juice_bar": {"offer": "1 jus offert", "emoji": "🥤", "levers": [
        _opp("jus_saison", "ventes", "Mettez en avant le jus de la saison",
             "Des fruits de saison, une recette du moment : une nouveauté à goûter fait revenir.", "offre_moment",
             template=_t("jus_saison", "🍓 Le jus de la saison",
                         "Nouveau cette semaine : notre jus de saison, préparé avec des fruits du moment.")),
    ]},
    "glacier": {"offer": "1 boule offerte", "emoji": "🍦", "levers": [
        _idea("saison_glaces", [4, 5, 6], "Ouverture de la saison",
              "Les premiers beaux jours : prévenez vos fidèles que la saison reprend.", "ete",
              _t("saison_glaces", "🍦 La saison des glaces est ouverte",
                 "Les beaux jours sont là : venez découvrir nos parfums de la saison !"), category="printemps"),
        _opp("parfum_mois", "ventes", "Créez le parfum du mois",
             "Un parfum éphémère chaque mois donne envie de revenir le goûter avant qu'il disparaisse.",
             "offre_moment", template=_t("parfum_mois", "🍦 Le parfum du mois",
                                         "Nouveau ce mois-ci : notre parfum éphémère. Venez le goûter !")),
    ]},
    "bar": {},
    "bar_tabac": {"offer": "1 café offert", "rules": ["tabac"], "levers": [
        _opp("cafe_matin", "fidelisation", "Récompensez le café du matin",
             "Les habitués passent chaque jour : récompensez le café et la presse, jamais le tabac "
             "(publicité interdite, loi Évin).", "fidelite", to="/dashboard/card", label="Configurer la carte"),
    ]},
    "bar_vin": {"levers": [
        _opp("degustation", "acquisition", "Organisez une soirée dégustation",
             "Un vigneron invité ou une région à découvrir : un rendez-vous qui fait venir des amis de vos habitués.",
             "proximite", template=_t("degustation", "🍷 Soirée découverte",
                                      "Jeudi, un vigneron vient présenter ses vins. Réservez votre place !")),
    ]},
    "bar_cocktails": {"levers": [
        _opp("cocktail_mois", "ventes", "Créez la recette du mois",
             "Une création éphémère chaque mois donne une raison de revenir la découvrir.", "offre_moment",
             template=_t("cocktail_mois", "🍹 La création du mois",
                         "Nouveau ce mois-ci : la création de notre barman. Venez la découvrir !")),
    ]},
    "pub": {},
    "restaurant": {},
    "brasserie": {"levers": [
        _opp("plat_du_jour", "ventes", "Annoncez le plat du jour",
             "Vos habitués du midi choisissent le matin : un message avec le plat du jour les décide.", "menu",
             template=_t("plat_du_jour", "🍽️ Le plat du jour",
                         "Aujourd'hui à la carte : notre plat du jour. On vous attend ce midi !")),
    ]},
    "restauration_rapide": {"offer": "1 boisson offerte", "own_levers": True, "levers": [
        _opp("formule_etudiant", "acquisition", "Créez une formule étudiante",
             "Une formule à prix rond pour les étudiants et les jeunes actifs fait venir en semaine.", "menu",
             template=_t("formule_etudiant", "🎓 La formule étudiante",
                         "Sur présentation de votre carte étudiante : notre formule à petit prix, toute la semaine.")),
    ]},
    "kebab": {"offer": "1 boisson offerte", "own_levers": True, "levers": [
        _opp("formule_kebab", "ventes", "Mettez en avant votre formule",
             "Sandwich, frites, boisson à prix rond : la formule fait monter le panier sans effort.", "menu",
             template=_t("formule_kebab", "🥙 Notre formule du moment",
                         "Sandwich + frites + boisson à petit prix. Sur place ou à emporter !")),
    ]},
    "burger": {"offer": "1 boisson offerte", "own_levers": True, "levers": [
        _opp("burger_mois", "ventes", "Créez le burger du mois",
             "Une recette éphémère chaque mois donne envie de revenir la goûter.", "offre_moment",
             template=_t("burger_mois", "🍔 Le burger du mois",
                         "Nouveau ce mois-ci : notre burger éphémère. Venez le goûter avant qu'il disparaisse !")),
    ]},
    "sushi": {"offer": "1 boisson offerte", "levers": [
        _opp("plateaux", "ventes", "Proposez des plateaux à partager",
             "Un plateau pour 2 ou 4 le week-end transforme une commande solo en repas entre amis.", "panier",
             template=_t("plateaux", "🍣 Nos plateaux à partager",
                         "Ce week-end, commandez un plateau pour 2 ou 4 : à emporter ou sur place.")),
    ]},
    "creperie": {"offer": "1 crêpe offerte", "levers": [
        _idea("chandeleur", [2], "Chandeleur",
              "Le 2 février est votre jour : annoncez-le à vos clients la semaine d'avant.", "saint_valentin",
              _t("chandeleur", "🥞 C'est la Chandeleur !",
                 "Le 2 février, on fête les crêpes : venez en profiter, pensez à réserver."),
              category="hiver"),
    ]},
    "traiteur": {"offer": "1 dessert offert", "levers": [
        NOEL_COMMANDES("traiteur"),
        _opp("plats_semaine", "fidelisation", "Envoyez les plats de la semaine",
             "Vos clients réguliers aiment savoir ce qui les attend : le menu de la semaine, le lundi.", "menu",
             template=_t("plats_semaine", "🍲 Les plats de la semaine",
                         "Découvrez nos plats de la semaine, à emporter. Commandez en boutique !")),
    ]},
    "pizzeria": {},
    "barbier": {"offer": "1 taille de barbe offerte", "levers": [
        _idea("fete_peres", [6], "Fête des pères",
              "Une coupe ou un soin de barbe à offrir : annoncez vos cartes cadeaux en juin.", "ete",
              _t("fete_peres", "🎁 Offrez une coupe pour la Fête des pères",
                 "Nos cartes cadeaux sont disponibles au salon : coupe, barbe ou les deux.")),
    ]},
    "coiffure_homme": {"levers": [
        _idea("fete_peres_coiffure", [6], "Fête des pères",
              "Une coupe à offrir : annoncez vos cartes cadeaux en juin.", "ete",
              _t("fete_peres_coiffure", "🎁 Offrez une coupe pour la Fête des pères",
                 "Nos cartes cadeaux sont disponibles au salon. Le cadeau utile !")),
    ]},
    "coiffure_femme": {"levers": [
        _opp("soin_couleur", "ventes", "Proposez un soin avec la couleur",
             "Un soin profond le jour de la couleur fait durer le résultat et monter le panier.", "panier_services",
             template=_t("soin_couleur", "✨ Un soin pour votre couleur",
                         "Lors de votre prochaine couleur, demandez notre soin : votre couleur dure plus longtemps.")),
    ]},
    "coiffure_mixte": {},
    "institut": {"levers": [
        _idea("epilation_ete", [5, 6], "Avant l'été",
              "L'épilation reprend avant les vacances : relancez vos clientes en mai-juin.", "ete",
              _t("epilation_ete", "☀️ Prête pour l'été ?",
                 "Les vacances approchent : réservez votre rendez-vous épilation dès maintenant."),
              category="printemps"),
    ]},
    "onglerie": {"offer": "-10 % sur votre prochain remplissage", "emoji": "💅", "levers": [
        _opp("rappel_remplissage", "fidelisation", "Rappelez le remplissage au bon moment",
             "Le remplissage se fait toutes les 2 à 3 semaines : un rappel à ce moment-là évite que la "
             "cliente aille ailleurs.", "inactifs",
             template=_t("rappel_remplissage", "💅 C'est l'heure du remplissage",
                         "Vos ongles ont poussé ? Réservez votre remplissage cette semaine.", "inactive")),
    ]},
    "spa_massage": {},
    "fitness": {},
    "crossfit": {},
    "yoga": {"items": ("cours", "cours"), "offer": "1 cours offert"},
    "danse": {"items": ("cours", "cours"), "offer": "1 cours offert", "levers": [
        _idea("rentree_danse", [9], "Inscriptions de rentrée",
              "Septembre décide de l'année : relancez les élèves de l'an dernier.", "automne",
              _t("rentree_danse", "💃 Les cours reprennent",
                 "Inscriptions ouvertes pour la nouvelle saison : réservez votre place dès maintenant."),
              replaces="rentree", category="automne"),
    ]},
    "arts_martiaux": {"items": ("cours", "cours"), "offer": "1 cours offert"},
    "tabac_presse": {"offer": "1 magazine offert", "emoji": "📰", "rules": ["tabac"], "levers": [
        _opp("hors_tabac", "fidelisation", "Récompensez la presse, les jeux et les services",
             "Votre carte fidélise sur la presse, la confiserie, les recharges et les services, jamais sur le "
             "tabac (publicité interdite, loi Évin).", "fidelite", to="/dashboard/card", label="Configurer la carte"),
        _opp("services_comptoir", "ventes", "Faites connaître vos services",
             "Colis, recharges, timbres : rappelez tout ce qu'on peut faire chez vous, cela fait venir plus souvent.",
             "offre_moment", template=_t("services_comptoir", "📦 Tout ce qu'on fait pour vous",
                                         "Colis, recharges, timbres, presse : pensez à nous, on est juste à côté.")),
    ]},
    "cbd": {"offer": "-10 % sur votre prochain achat", "rules": ["cbd"], "levers": [
        _opp("nouveautes_cbd", "ventes", "Annoncez les nouveautés",
             "Une nouvelle variété ou un nouvel arôme : vos habitués aiment être prévenus les premiers. "
             "Parlez du produit, jamais d'effet sur la santé (interdit).", "offre_moment",
             template=_t("nouveautes_cbd", "🌿 Nouveautés en boutique",
                         "De nouvelles références viennent d'arriver : venez les découvrir en boutique.")),
    ]},
    "fleuriste": {"offer": "-10 % sur votre prochain bouquet", "emoji": "💐", "levers": [
        _idea("fleurs_valentin", [2], "Saint-Valentin",
              "Votre plus grand jour : prenez les commandes à l'avance pour servir tout le monde.",
              "saint_valentin", _t("fleurs_valentin", "🌹 Commandez vos roses",
                                   "Pour la Saint-Valentin, réservez votre bouquet dès maintenant en boutique."),
              replaces="saint_valentin"),
        _idea("fleurs_grands_meres", [3], "Fête des grands-mères",
              "Début mars : un rappel une semaine avant fait penser à offrir.", "printemps",
              _t("fleurs_grands_meres", "💐 Fête des grands-mères",
                 "Dimanche, c'est la fête des grands-mères : pensez à son bouquet !"), category="printemps"),
        _idea("fleurs_fete_meres", [5], "Fête des mères",
              "Fin mai : prenez les commandes à l'avance et rappelez la date à vos clients.", "printemps",
              _t("fleurs_fete_meres", "💐 Fête des mères : réservez votre bouquet",
                 "Fête des mères ce dimanche : commandez votre bouquet en boutique dès maintenant."),
              fact="fete_meres_fleurs", replaces="printemps"),
        _idea("toussaint", [10], "Toussaint",
              "Chrysanthèmes et compositions : prévenez vos clients dès mi-octobre.", "automne",
              _t("toussaint", "🍂 Toussaint",
                 "Chrysanthèmes et compositions sont arrivés : passez en boutique ou commandez."),
              replaces="rentree", category="automne"),
        _opp("bouquet_abonnement", "fidelisation", "Proposez un bouquet chaque semaine",
             "Un bouquet livré ou à retirer chaque semaine pour les particuliers et les commerces voisins.",
             "fidelite", template=_t("bouquet_abonnement", "💐 Un bouquet chaque semaine",
                                     "Envie de fleurs fraîches toutes les semaines ? Demandez notre formule en boutique.")),
    ]},
    "opticien": {"offer": "un contrôle offert", "levers": [
        _opp("renouvellement", "fidelisation", "Rappelez le renouvellement à 2 ans",
             "Deux ans après l'achat, vos clients ont droit à une nouvelle paire remboursée : prévenez-les.",
             "inactifs", fact="lunettes_2_ans",
             template=_t("renouvellement", "👓 Vos lunettes ont 2 ans ?",
                         "Vous avez peut-être droit à une nouvelle paire remboursée : passez en magasin.")),
        _opp("ajustement", "fidelisation", "Invitez à un ajustement gratuit",
             "Un nettoyage et un réglage des montures entre deux achats gardent le lien avec le client.",
             "fidelite", template=_t("ajustement", "👓 Un réglage offert",
                                     "Passez en magasin : nettoyage et réglage de vos lunettes offerts.")),
    ]},
    "librairie": {"offer": "-5 % sur votre prochain livre", "levers": [
        _idea("rentree_scolaire", [8, 9], "Rentrée",
              "Fournitures, manuels, rentrée littéraire : le moment de revoir vos clients.", "automne",
              _t("rentree_scolaire", "📚 C'est la rentrée",
                 "Rentrée littéraire et fournitures : passez découvrir nos nouveautés en librairie."),
              replaces="rentree", category="automne"),
        _opp("rencontres", "acquisition", "Organisez une rencontre ou une dédicace",
             "Un auteur, un club de lecture : un rendez-vous fait venir des lecteurs qui ne vous connaissent pas.",
             "proximite", template=_t("rencontres", "📖 Rencontre en librairie",
                                      "Rencontre avec un auteur samedi : entrée libre, venez avec vos amis !")),
    ]},
    "pressing": {"items": PRESTATIONS, "offer": "-10 % sur votre prochain dépôt", "levers": [
        _idea("couettes", [4, 5], "Couettes et rideaux de printemps",
              "Au printemps, vos clients rangent les couettes : proposez le nettoyage des grosses pièces.",
              "printemps", _t("couettes", "🧺 Le grand nettoyage de printemps",
                              "Couettes, rideaux, plaids : déposez-les cette semaine en boutique."),
              category="printemps"),
    ]},
    "boucherie": {"food": True, "offer": "-10 % sur votre prochain achat", "levers": [
        _idea("barbecue", [5, 6, 7], "Saison des barbecues",
              "Brochettes, marinades, colis : préparez vos clients aux beaux jours.", "ete",
              _t("barbecue", "🔥 La saison des barbecues",
                 "Brochettes et marinades maison : commandez pour votre prochain barbecue !"), category="ete"),
        NOEL_COMMANDES("boucherie"),
    ]},
    "fromagerie": {"food": True, "offer": "-10 % sur votre prochain achat", "levers": [
        _idea("raclette", [11, 12, 1, 2], "Raclette et fondue",
              "L'hiver est votre saison : proposez les plateaux raclette et fondue à commander.", "automne",
              _t("raclette", "🧀 Raclette et fondue",
                 "Plateaux raclette et fondue à commander en boutique : on vous prépare tout."), category="hiver"),
        NOEL_COMMANDES("fromagerie"),
    ]},
    "primeur": {"food": True, "offer": "-10 % sur votre prochain panier", "levers": [
        _opp("arrivages", "ventes", "Annoncez les arrivages de saison",
             "Les premières fraises, les premières clémentines : prévenir vos habitués les fait venir le jour même.",
             "offre_moment", template=_t("arrivages", "🍓 Nouveaux arrivages",
                                         "Les produits de saison viennent d'arriver : passez les choisir !")),
    ]},
    "caviste": {"food": True, "offer": "-10 % sur votre prochain achat", "rules": ["alcool"], "levers": [
        _opp("degustation_caviste", "acquisition", "Organisez une dégustation en boutique",
             "Un samedi avec un vigneron : vos clients découvrent et reviennent pour la bouteille qu'ils ont aimée.",
             "proximite", template=_t("degustation_caviste", "🍷 Dégustation ce samedi",
                                      "Samedi, un vigneron présente ses vins en boutique. Venez découvrir !")),
        _idea("foire_vins", [9, 10], "Foire aux vins",
              "Septembre-octobre, vos clients font leur cave : montrez votre sélection.", "automne",
              _t("foire_vins", "🍇 Notre sélection d'automne",
                 "Faites votre cave : découvrez notre sélection d'automne en boutique."),
              replaces="rentree", category="automne"),
        NOEL_COMMANDES("caviste"),
    ]},
    "epicerie": {"food": True, "offer": "-10 % sur votre prochain achat", "levers": [
        _idea("paniers_garnis", [11, 12], "Paniers garnis",
              "Pour Noël et les cadeaux d'entreprise : proposez des paniers à composer.", "fetes",
              _t("paniers_garnis", "🎁 Nos paniers garnis",
                 "Pour offrir : composez votre panier garni en boutique, on l'emballe pour vous."),
              replaces="fetes"),
    ]},
    "mode": {"offer": "-10 % sur votre prochain achat", "levers": [
        _opp("avant_premiere", "fidelisation", "Ouvrez les soldes à vos fidèles en avant-première",
             "La veille des soldes, une soirée ou un accès réservé aux porteurs de carte récompense vos fidèles.",
             "fidelite", months=[1, 6, 7],
             template=_t("avant_premiere", "🛍️ Avant-première fidèles",
                         "Avant tout le monde : venez profiter des soldes en avant-première, carte en main.")),
        _idea("nouvelle_collection", [3, 9], "Nouvelle collection",
              "Mars et septembre : présentez la collection à vos clients avant tout le monde.", "printemps",
              _t("nouvelle_collection", "✨ La nouvelle collection est arrivée",
                 "Venez découvrir notre nouvelle collection en boutique cette semaine !"), category="printemps"),
    ]},
    "autre_commerce": {},
    "autre": {},
}


# ---------------------------------------------------------------------------
# The rules of the trade — told to FidClic IA, and checked on what it wrote
# ---------------------------------------------------------------------------
RULES: Dict[str, Dict[str, Any]] = {
    "tabac": {
        "text": "Ne parle jamais de tabac, de cigarettes ni de vapotage et n'en fais aucune promotion "
                "(loi Évin) : parle de presse, jeux, confiserie, recharges et services.",
        "words": re.compile(r"tabac|cigar|cigarillo|e-cig|\bvap|\bpuff|chicha|nicotin", re.I),
        "reason": "Ce message parle de tabac : c'est interdit (loi Évin). Reformulez sur la presse, les jeux "
                  "ou les services.",
    },
    "cbd": {
        "text": "Aucune allégation de santé ni d'effet (sommeil, stress, douleur…) : c'est interdit. "
                "Parle des produits, des arômes et des nouveautés.",
        "words": re.compile(r"sommeil|dormi|stress|anxi|angoiss|douleur|apais|soulag|santé|guéri|soign|"
                            r"thérap|médic|inflamm|détend", re.I),
        "reason": "Ce message prête un effet sur la santé au CBD : c'est interdit. Reformulez sur les produits.",
    },
    "alcool": {
        "text": "Aucune incitation à boire de l'alcool (loi Évin) : pas d'offre à volonté ni de « 2 pour 1 » "
                "sur l'alcool. Parle de l'ambiance, des événements et de la découverte.",
        "words": re.compile(r"à volonté|open bar|pour le prix d'?\s?(un|une|1)\b|cul sec|\bbuvez plus|"
                            r"\bshots? (offert|gratuit)", re.I),
        "reason": "Ce message pousse à boire de l'alcool : c'est interdit (loi Évin). Reformulez sur l'ambiance "
                  "ou l'événement.",
    },
}

# ---------------------------------------------------------------------------
# The words « Client inactif » and « Géolocalisation » open on (the editor
# and a new shop's automations). {emoji} is the playbook's; {prénom} and
# {nom_commerce} are filled by the sender. No offer is promised here.
# ---------------------------------------------------------------------------
AUTO_FAMILY: Dict[str, Dict[str, Dict[str, str]]] = {
    "bakery": {
        "inactive": {"title": "Vos gourmandises vous attendent {emoji}",
                     "body": "Bonjour {prénom}, cela fait un moment ! Passez nous voir chez {nom_commerce}, "
                             "on a hâte de vous régaler."},
        "geo": {"title": "Vous êtes tout près ! {emoji}",
                "body": "Bonjour {prénom}, vous passez près de {nom_commerce} : entrez vous faire plaisir !"},
    },
    "cafe": {
        "inactive": {"title": "Votre pause vous attend {emoji}",
                     "body": "Bonjour {prénom}, cela fait un moment ! Venez faire une pause chez {nom_commerce}, "
                             "on vous attend."},
        "geo": {"title": "Une petite pause ? {emoji}",
                "body": "Bonjour {prénom}, vous passez près de {nom_commerce} : entrez faire une pause !"},
    },
    "bar": {
        "inactive": {"title": "Ça fait un moment ! {emoji}",
                     "body": "Bonjour {prénom}, toute l'équipe de {nom_commerce} serait ravie de vous revoir. "
                             "Passez nous dire bonjour !"},
        "geo": {"title": "Vous êtes dans le quartier ! {emoji}",
                "body": "Bonjour {prénom}, vous passez près de {nom_commerce} : venez dire bonjour à l'équipe !"},
    },
    "restaurant": {
        "inactive": {"title": "Votre table vous attend {emoji}",
                     "body": "Bonjour {prénom}, cela fait un moment ! Venez vous régaler chez {nom_commerce}, "
                             "on sera ravis de vous revoir."},
        "geo": {"title": "Une petite faim ? {emoji}",
                "body": "Bonjour {prénom}, vous passez près de {nom_commerce} : entrez vous régaler !"},
    },
    "salon": {
        "inactive": {"title": "Il est temps de rafraîchir votre coupe ? {emoji}",
                     "body": "Bonjour {prénom}, cela fait un moment ! Prenez votre prochain rendez-vous "
                             "chez {nom_commerce}."},
        "geo": {"title": "Vous êtes tout près ! {emoji}",
                "body": "Bonjour {prénom}, vous passez près de {nom_commerce} : profitez-en pour prendre "
                        "votre prochain rendez-vous."},
    },
    "spa": {
        "inactive": {"title": "Et si vous preniez un moment pour vous ? {emoji}",
                     "body": "Bonjour {prénom}, cela fait un moment ! Réservez votre prochain rendez-vous "
                             "chez {nom_commerce}."},
        "geo": {"title": "Vous êtes tout près ! {emoji}",
                "body": "Bonjour {prénom}, vous passez près de {nom_commerce} : passez réserver votre "
                        "prochain moment de détente."},
    },
    "gym": {
        "inactive": {"title": "Et si on reprenait ? {emoji}",
                     "body": "Bonjour {prénom}, cela fait un moment ! Toute l'équipe de {nom_commerce} vous "
                             "attend pour la reprise."},
        "geo": {"title": "Vous êtes tout près ! {emoji}",
                "body": "Bonjour {prénom}, vous passez près de {nom_commerce} : c'est peut-être le bon moment "
                        "pour revenir !"},
    },
}
AUTO_FAMILY["pizzeria"] = AUTO_FAMILY["restaurant"]
AUTO_ACTIVITY: Dict[str, Dict[str, Dict[str, str]]] = {
    "traiteur": {
        "inactive": {"title": "Vos plats préférés vous attendent {emoji}",
                     "body": "Bonjour {prénom}, cela fait un moment ! Passez chez {nom_commerce} découvrir "
                             "nos plats de la semaine."},
    },
    "fleuriste": {
        "inactive": {"title": "Un bouquet pour égayer la semaine ? {emoji}",
                     "body": "Bonjour {prénom}, cela fait un moment ! Les fleurs de saison vous attendent "
                             "chez {nom_commerce}."},
        "geo": {"title": "Vous êtes tout près ! {emoji}",
                "body": "Bonjour {prénom}, vous passez près de {nom_commerce} : entrez voir les fleurs du jour !"},
    },
    "opticien": {
        "inactive": {"title": "Vos lunettes vont bien ? 👓",
                     "body": "Bonjour {prénom}, cela fait un moment ! Passez chez {nom_commerce} : on vérifie "
                             "et on ajuste vos lunettes."},
        "geo": {"title": "Vous êtes tout près ! 👓",
                "body": "Bonjour {prénom}, vous passez près de {nom_commerce} : entrez faire ajuster vos lunettes."},
    },
    "librairie": {
        "inactive": {"title": "De nouveaux livres vous attendent 📚",
                     "body": "Bonjour {prénom}, cela fait un moment ! Venez découvrir les nouveautés "
                             "chez {nom_commerce}."},
        "geo": {"title": "Vous êtes tout près ! 📚",
                "body": "Bonjour {prénom}, vous passez près de {nom_commerce} : entrez feuilleter les nouveautés !"},
    },
    "tabac_presse": {
        "inactive": {"title": "Votre presse vous attend {emoji}",
                     "body": "Bonjour {prénom}, presse, jeux, recharges, colis : on vous attend "
                             "chez {nom_commerce} !"},
        "geo": {"title": "Vous êtes tout près ! {emoji}",
                "body": "Bonjour {prénom}, vous passez près de {nom_commerce} : pensez à votre presse et "
                        "à vos services !"},
    },
}


def _auto(key: str, sector: str, emoji: str) -> Dict[str, Dict[str, str]]:
    texts = {**(AUTO_FAMILY.get(sector) or {}), **(AUTO_ACTIVITY.get(key) or {})}
    return {sc: {f: v.replace("{emoji}", emoji) for f, v in t.items()} for sc, t in texts.items()}


def _build(key: str) -> Dict[str, Any]:
    act = A.BY_KEY[key]
    fam = FAMILIES.get(act["sector"]) or FAMILIES["other"]
    own = ACTIVITIES.get(key) or {}
    levers = list(own.get("levers") or []) + ([] if own.get("own_levers") else list(fam["levers"]))
    generic = {**GENERIC, **(fam.get("generic_facts") or {}), **(own.get("generic_facts") or {})}
    wanted = set(generic.values()) | {lv["fact"] for lv in levers if lv.get("fact")}
    return {
        "key": key, "label": act["label"], "sector": act["sector"],
        "food": bool(own.get("food", fam["food"])), "drinks": bool(own.get("drinks", fam["drinks"])),
        "meals": bool(own.get("meals", fam["meals"])),
        "items": tuple(own.get("items") or fam["items"]), "offer": own.get("offer") or fam["offer"],
        "emoji": own.get("emoji") or fam["emoji"],
        "levers": levers, "generic_facts": generic,
        "facts": {k: FACTS[k] for k in sorted(wanted)},
        "rules": sorted(set(fam.get("rules") or []) | set(own.get("rules") or [])),
        "auto": _auto(key, act["sector"], own.get("emoji") or fam["emoji"]),
    }


PLAYBOOKS: Dict[str, Dict[str, Any]] = {a["key"]: _build(a["key"]) for a in A.ACTIVITIES}


def of(tenant: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The shop's playbook — a copy, so no caller can change the catalogue."""
    return copy.deepcopy(PLAYBOOKS[A.of(tenant)["key"]])


def in_season(lever: Dict[str, Any], month: int) -> bool:
    """A dated lever shows during its months and the month before (to prepare)."""
    months = lever.get("months")
    if not months:
        return True
    return month in months or (month % 12) + 1 in months


def lever_by_template(play: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    return next((lv for lv in play["levers"] if (lv.get("template") or {}).get("key") == key), None)


def fact_of(play: Dict[str, Any], lever: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return play["facts"].get((lever or {}).get("fact") or "")


def paris_month(at: Optional[Any] = None) -> int:
    """This month in Paris — the moments of the trade follow French time."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    at = at or datetime.now(timezone.utc)
    try:
        return at.astimezone(ZoneInfo("Europe/Paris")).month
    except (ValueError, TypeError, AttributeError):
        return getattr(at, "month", 1)


def _month(month: Any) -> int:
    try:
        return (int(month) - 1) % 12 + 1
    except (TypeError, ValueError):
        return 1


def prompt_context(play: Dict[str, Any], month: Any, *, offer: bool = True) -> str:
    """What FidClic IA is told about the shop's trade: its activité, its words,
    its key moments this month and its rules. `offer=False` where the IA must
    promise nothing (Autopilot)."""
    m = _month(month)
    parts = [f"Activité du commerce : {play['label']}. Il vend des {play['items'][1]} : "
             "écris pour ce métier, jamais avec les mots d'un autre commerce."]
    if offer:
        parts.append(f"Si tu proposes une offre, qu'elle reste dans le métier (exemple : {play['offer']}).")
    moments = [lv["title"] for lv in play["levers"] if lv.get("months") and in_season(lv, m)]
    if moments:
        parts.append("Moments du métier en ce moment : " + ", ".join(dict.fromkeys(moments)) + ".")
    for r in play.get("rules") or []:
        parts.append("Règle : " + RULES[r]["text"])
    return " ".join(parts)


def breaks_rules(play: Dict[str, Any], text: Optional[str]) -> Optional[str]:
    """The reason the text breaks one of the trade's rules, else None."""
    for r in play.get("rules") or []:
        if text and RULES[r]["words"].search(text):
            return RULES[r]["reason"]
    return None


def automation_texts(play: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """{scenario: {title, body}} — the trade's words for the automations that
    have some; the others keep the generic words."""
    return copy.deepcopy(play.get("auto") or {})
