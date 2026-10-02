/**
 * Ce que veut dire chaque chiffre — l'aide « ? » de la plateforme
 * (components/InfoTip, user 2026-10-02).
 *
 * One place for every figure's explanation, so a number reads the same on the
 * Tableau de bord, in Analyses, on Clients, Campagnes, Carte de fidélité,
 * Automatisations and the monthly report. Each entry says, for the owner:
 *   what — c'est quoi
 *   how  — comment c'est calculé (exactly what the server computes)
 *   why  — à quoi ça sert, concrètement
 * Keys are « page:figure » when a name means something else on another page,
 * else the bare figure.
 */
const H = {
  // ── money ────────────────────────────────────────────────────────────────
  revenue: {
    t: "Chiffre d'affaires",
    what: "L'argent encaissé auprès de vos clients fidélité sur la période choisie.",
    how: "La somme des montants saisis à chaque scan de carte en caisse. L'évolution compare avec la période précédente de même durée.",
    why: "C'est le pouls de votre commerce : il montre si votre activité fidélité monte ou baisse. Un achat sans carte, ou un montant non saisi, n'y figure pas.",
  },
  fidclic: {
    t: 'CA FidClic',
    what: "La part de votre chiffre d'affaires que FidClic a fait revenir.",
    how: "Les visites dans les 15 jours qui suivent une campagne, une notification de géolocalisation, une offre ou une automatisation, plus toutes les visites des clients venus par parrainage. Un simple passage en caisse n'est pas compté.",
    why: "Il mesure ce que FidClic vous rapporte vraiment, au-delà des clients qui seraient venus de toute façon.",
  },
  referral: {
    t: 'CA Parrainage',
    what: "Ce que dépensent les clients arrivés grâce au parrainage.",
    how: "La somme des visites, sur la période, des clients inscrits via la carte d'un parrain — toutes leurs visites, pas seulement la première.",
    why: "Il montre ce que vous rapportent vos ambassadeurs, pour savoir si la récompense de parrainage vaut la peine.",
  },
  basket: {
    t: 'Panier moyen',
    what: "Ce qu'un client dépense en moyenne à chaque visite.",
    how: "Le chiffre d'affaires de la période divisé par le nombre de visites de la période.",
    why: "Le faire monter (menu, produit en plus) augmente le chiffre d'affaires sans avoir besoin de plus de clients.",
  },
  ltv: {
    t: 'LTV moyenne (valeur client)',
    what: "Ce qu'un client vous rapporte en moyenne depuis son inscription.",
    how: "La dépense totale de tous vos clients depuis leur inscription, divisée par le nombre de clients. Ne dépend pas de la période choisie.",
    why: "C'est ce que vaut un client : vous savez combien vous pouvez dépenser pour en gagner un nouveau, ou pour faire revenir un client inactif (un café offert coûte peu face à sa valeur).",
  },
  ltv_total: {
    t: 'LTV totale',
    what: "Ce que l'ensemble de vos clients fidélité vous a rapporté depuis leur inscription.",
    how: "La somme de la dépense de chaque client depuis son inscription. Ce chiffre ne fait que monter.",
    why: "C'est la valeur de votre base clients. Sa vitesse de progression d'un mois à l'autre mesure la croissance de votre fidélité.",
  },
  impact: {
    t: 'Impact FidClic',
    what: "Le chiffre d'affaires des clients revenus grâce à FidClic, et sa part dans votre chiffre d'affaires.",
    how: "Mêmes règles que le CA FidClic : une visite compte si elle suit, dans les 15 jours, un message de FidClic (campagne, géolocalisation, offre, automatisation), ou si le client est venu par parrainage. Chaque visite n'est attribuée qu'à une seule source : la plus récente.",
    why: "Il montre quels outils de FidClic vous rapportent le plus, pour y mettre votre énergie.",
  },
  goal: {
    t: 'Objectif du mois',
    what: "Le chiffre d'affaires que vous visez ce mois-ci, et où vous en êtes.",
    how: "Le chiffre d'affaires encaissé depuis le 1er du mois, comparé à l'objectif que vous avez fixé.",
    why: "Il vous dit tôt dans le mois s'il faut une action (campagne, offre) pour atteindre votre cible.",
  },

  // ── visits ───────────────────────────────────────────────────────────────
  visits: {
    t: 'Visites total',
    what: "Le nombre de passages en caisse avec la carte sur la période.",
    how: "Chaque scan de carte compte pour une visite. L'évolution compare avec la période précédente de même durée.",
    why: "Plus de visites, c'est des clients qui reviennent plus souvent — le cœur de la fidélité.",
  },
  campaign_visits: {
    t: 'Visites avec campagnes',
    what: "Les visites qui suivent une campagne ou une automatisation.",
    how: "Une visite compte si elle a lieu dans les 15 jours qui suivent une campagne ou une automatisation reçue par ce client.",
    why: "Il montre si vos messages font vraiment venir des clients en boutique.",
  },
  avg_visits: {
    t: 'Visites par client',
    what: "Combien de fois un client vient en moyenne.",
    how: "Le grand chiffre : toutes les visites depuis l'inscription divisées par le nombre de clients. En dessous : les visites de la période divisées par le nombre de clients.",
    why: "Il mesure l'habitude : faire passer vos clients de 2 à 3 visites vaut souvent plus que d'en trouver de nouveaux.",
  },
  life: {
    t: 'Durée moyenne',
    what: "Combien de temps un client reste actif chez vous.",
    how: "Le temps entre l'inscription et la dernière visite, en moyenne, pour les clients revenus au moins une fois après leur inscription.",
    why: "Plus elle est longue, plus vos clients vous restent fidèles. Si elle baisse, vos clients décrochent plus vite.",
  },

  // ── clients ──────────────────────────────────────────────────────────────
  clients: {
    t: 'Clients totaux',
    what: "Toutes les personnes qui ont une carte de fidélité chez vous.",
    how: "Le nombre de cartes. L'évolution compare avec le nombre de clients au début de la période.",
    why: "Il mesure la taille de votre base : ce sont les clients que vous pouvez contacter.",
  },
  loyal: {
    t: 'Clients fidélisés',
    what: "Vos clients réguliers.",
    how: "Les clients qui remplissent la règle « Client fidèle » de vos Règles clients (Paramètres). C'est le même chiffre sur le Tableau de bord, Analyses, Clients, Campagnes et la Carte de fidélité.",
    why: "Ce sont eux qui font votre chiffre d'affaires : les garder et les récompenser est votre priorité.",
  },
  inactive: {
    t: 'Clients inactifs',
    what: "Les clients qui ne viennent plus.",
    how: "Les clients pas venus depuis la durée « Client actif » de vos Règles clients (30 jours par défaut), y compris ceux jamais revenus après leur inscription.",
    why: "C'est votre réserve de chiffre d'affaires : une relance bien faite en fait revenir une partie. Moins il y en a, mieux c'est.",
  },
  new_clients: {
    t: 'Nouveaux clients',
    what: "Les clients qui ont pris une carte sur la période.",
    how: "Le nombre de cartes créées chaque jour (ou chaque heure pour « Aujourd'hui »).",
    why: "Il montre si votre programme attire : QR code en caisse, parrainage, import.",
  },
  'clients:new': {
    t: 'Nouveaux clients',
    what: "Les clients inscrits ces 30 derniers jours.",
    how: "Les cartes créées dans les 30 derniers jours — le même groupe que le segment « Nouveaux clients ». L'évolution compare avec les 30 jours d'avant.",
    why: "Un nouveau client qui revient une deuxième fois a de bonnes chances de devenir fidèle : c'est le moment de lui écrire.",
  },
  'clients:total': {
    t: 'Clients total',
    what: "Toutes les personnes qui ont une carte de fidélité chez vous.",
    how: "Le nombre de cartes. L'évolution compare avec le nombre de clients au début du mois.",
    why: "Il mesure la taille de votre base : ce sont les clients que vous pouvez contacter.",
  },
  segmentation: {
    t: 'Statut des clients',
    what: "Votre clientèle répartie en quatre groupes.",
    how: "Chaque client est dans un seul groupe, dans cet ordre : inactif, sinon fidèle, sinon nouveau (inscrit depuis moins de 30 jours), sinon occasionnel — d'après vos Règles clients. Cliquez sur un groupe pour voir ses clients.",
    why: "Il dit où agir : relancer les inactifs, récompenser les fidèles, faire revenir les nouveaux.",
  },
  basket_bands: {
    t: 'Panier moyen par client',
    what: "Combien vos clients dépensent par visite, groupés par tranche.",
    how: "Pour chaque client venu au moins une fois : sa dépense totale divisée par son nombre de visites, depuis son inscription.",
    why: "Il montre où sont vos clients : beaucoup de petits paniers = une offre « menu » ou un produit en plus peut faire monter la moyenne.",
  },

  // ── moments ──────────────────────────────────────────────────────────────
  hours: {
    t: "Heures d'affluence",
    what: "Quand vos clients viennent, par jour et par tranche de deux heures.",
    how: "Les visites de la période, à l'heure de votre commerce (Paris). La grille couvre 8 h – 20 h ; les visites en dehors sont comptées à part.",
    why: "Pour envoyer vos messages juste avant les moments forts, et remplir les heures creuses avec une offre.",
  },
  weekdays: {
    t: 'Visites par jour de la semaine',
    what: "Le nombre de visites pour chaque jour de la semaine.",
    how: "Les visites de la période, groupées par jour (heure de Paris), avec le jour et le créneau les plus chargés.",
    why: "Pour planifier votre personnel, et viser vos jours calmes avec une campagne.",
  },
  products: {
    t: 'Produits les plus populaires',
    what: "Ce que vos clients achètent le plus.",
    how: "Les articles choisis au moment du scan (catalogue produits), additionnés en quantité sur la période.",
    why: "Pour mettre en avant vos best-sellers, ou créer une offre autour d'eux.",
  },

  // ── campaigns ────────────────────────────────────────────────────────────
  campaigns_sent: {
    t: 'Campagnes envoyées',
    what: "Le nombre de campagnes parties sur la période.",
    how: "Les campagnes envoyées (pas les brouillons ni les programmées à venir).",
    why: "Il montre votre rythme de communication.",
  },
  reach: {
    t: 'Clients touchés',
    what: "Combien de clients ont reçu vos campagnes.",
    how: "La somme des destinataires de chaque campagne : un client qui en reçoit deux compte deux fois.",
    why: "Il montre la portée de vos messages.",
  },
  open_rate: {
    t: "Taux d'ouverture",
    what: "La part des clients qui ont ouvert leur carte après un message.",
    how: "Une ouverture = la carte ouverte dans les 72 h suivant l'envoi. Une notification Wallet ne renvoie pas d'accusé de lecture : c'est le seul signal fiable.",
    why: "Il dit si vos messages donnent envie d'aller voir l'offre.",
  },
  clicks: {
    t: 'Clics',
    what: "Le nombre de clics sur le lien ou l'offre de vos messages.",
    how: "Chaque clic sur le lien d'une campagne est compté.",
    why: "Il mesure l'intérêt pour votre offre, avant même la visite.",
  },
  sales: {
    t: 'Ventes attribuées',
    what: "Les clients revenus en boutique après une campagne.",
    how: "Un client compte une fois par campagne s'il est passé en caisse dans les 15 jours après l'avoir reçue.",
    why: "C'est le résultat concret de vos campagnes : des clients en boutique.",
  },
  campaign_revenue: {
    t: 'CA généré',
    what: "Ce qu'ont dépensé les clients après avoir reçu une campagne.",
    how: "La dépense des destinataires dans les 15 jours suivant l'envoi. C'est une association, pas une preuve : certains seraient venus quand même (voir « Effet »).",
    why: "Il donne l'ordre de grandeur de ce que vos campagnes accompagnent.",
  },
  effect: {
    t: 'Effet de la campagne',
    what: "Les clients venus EN PLUS grâce au message.",
    how: "Les clients revenus dans les 15 jours, moins ceux qui seraient venus de toute façon d'après leurs habitudes des 6 derniers mois. Le résultat se lit 15 jours après l'envoi.",
    why: "C'est la vraie mesure d'une campagne : un message aux habitués « marche » toujours, l'effet dit s'il a changé quelque chose.",
  },
  campaign_perf: {
    t: 'Performance des campagnes',
    what: "Ce que vos campagnes de la période ont donné.",
    how: "Campagnes envoyées ; clients touchés (la somme des destinataires) ; clics sur le lien ou l'offre ; ventes attribuées = les clients passés en caisse dans les 15 jours après avoir reçu une campagne (une fois par campagne).",
    why: "Pour voir d'un coup d'œil si vos messages font venir du monde — le détail et l'« effet » réel sont sur la page Campagnes.",
  },
  recommendations: {
    t: 'Recommandations',
    what: "Les actions que FidClic vous conseille en ce moment.",
    how: "Calculées sur vos propres chiffres : clients inactifs, campagnes, produits, objectif du mois.",
    why: "Pour savoir quoi faire aujourd'hui, sans analyser vous-même.",
  },
  report_back: {
    t: 'Clients revenus',
    what: "Les clients touchés par une campagne du mois qui sont revenus en boutique.",
    how: "Les destinataires passés en caisse dans les 15 jours après la campagne — seulement pour les campagnes dont les 15 jours sont écoulés.",
    why: "C'est le résultat brut ; « venus en plus » dit combien sont venus grâce au message.",
  },
  report_revenue: {
    t: 'CA des clients revenus',
    what: "Ce qu'ont dépensé les clients revenus après une campagne du mois.",
    how: "Leurs passages en caisse dans les 15 jours suivant la campagne.",
    why: "L'ordre de grandeur de ce que vos campagnes accompagnent ; le CA FidClic dit ce qu'elles ont fait revenir.",
  },
  learning: {
    t: 'Ce qui marche chez vous',
    what: "Ce que vos propres campagnes ont appris à FidClic.",
    how: "FidClic compare vos campagnes entre elles (offre, emoji, prénom, jour, heure, audience…). Une conclusion n'apparaît qu'avec au moins 3 campagnes de chaque côté et un écart que le hasard explique mal.",
    why: "Pour écrire vos prochains messages comme ceux qui ont le mieux marché — l'IA et l'Autopilot s'en servent aussi.",
  },

  // ── fidélisation / avis / produits / acquisition (Analyses tabs) ─────────
  'fidelisation:returning': {
    t: 'Clients revenus',
    what: "Les clients venus au moins deux fois depuis leur inscription.",
    how: "Le nombre de clients avec deux visites ou plus, depuis toujours.",
    why: "Revenir une deuxième fois est le premier pas vers la fidélité.",
  },
  'fidelisation:retention': {
    t: 'Taux de retour',
    what: "La part de vos clients qui sont revenus au moins une fois.",
    how: "Les clients venus deux fois ou plus, divisés par tous vos clients, depuis leur inscription. Ce n'est pas une cohorte mensuelle.",
    why: "Il montre si votre programme donne envie de revenir.",
  },
  'fidelisation:rewards': {
    t: 'Récompenses utilisées',
    what: "Les récompenses remises à vos clients sur la période.",
    how: "Chaque récompense validée en caisse compte une fois.",
    why: "Des récompenses utilisées, ce sont des clients qui atteignent leurs objectifs — et qui reviennent pour la suivante.",
  },
  tiers: {
    t: 'Paliers',
    what: "Combien de clients sont Bronze, Argent, Or et VIP.",
    how: "Le palier actuel de chaque client, selon les seuils de votre Carte de fidélité.",
    why: "Faire monter vos clients de palier est un objectif clair à leur proposer.",
  },
  'avis:avg': {
    t: 'Note moyenne',
    what: "La note moyenne laissée par vos clients.",
    how: "La moyenne de toutes les notes, sur 5. L'évolution compare la note des avis de la période avec celle de la période précédente.",
    why: "Une bonne note rassure les nouveaux clients ; une baisse signale un problème à corriger vite.",
  },
  'avis:count': { t: 'Avis reçus', what: "Tous les avis reçus depuis le début.", how: "Le nombre total d'avis laissés depuis la carte.", why: "Plus d'avis = une note plus fiable." },
  'avis:window': { t: 'Avis sur la période', what: "Les avis reçus sur la période choisie.", how: "Le nombre d'avis laissés pendant la période.", why: "Il montre si vos clients donnent leur avis en ce moment." },
  'produits:refs': { t: 'Références vendues', what: "Le nombre de produits différents vendus.", how: "Les articles distincts choisis au scan sur la période.", why: "Il montre la variété de ce que vos clients achètent." },
  'produits:units': { t: 'Articles vendus', what: "Le nombre total d'articles vendus.", how: "La somme des quantités choisies au scan sur la période.", why: "Il mesure le volume vendu via la carte." },
  'produits:revenue': {
    t: 'CA produits',
    what: "Le chiffre d'affaires des articles choisis au scan.",
    how: "Prix × quantité de chaque article saisi sur la période. Il peut être plus bas que le chiffre d'affaires total si les articles ne sont pas toujours saisis.",
    why: "Il montre quels produits rapportent le plus.",
  },
  'acquisition:new': { t: 'Nouveaux clients', what: "Les clients inscrits sur la période.", how: "Les cartes créées pendant la période choisie.", why: "Il mesure le recrutement de nouveaux clients." },
  'acquisition:total': { t: 'Clients au total', what: "Toutes vos cartes de fidélité.", how: "Le nombre total de clients.", why: "La taille de votre base." },
  sources: {
    t: "Sources d'acquisition",
    what: "Par où vos nouveaux clients sont arrivés.",
    how: "La source enregistrée à l'inscription (QR code en caisse, réseaux sociaux, site, parrainage, import), pour les clients inscrits sur la période.",
    why: "Pour savoir quel canal vous amène le plus de clients et y investir.",
  },
  places: {
    t: "D'où viennent vos clients",
    what: "Les villes et quartiers de vos clients.",
    how: "D'après le code postal ou la ville donnés à l'inscription.",
    why: "Pour cibler une campagne de quartier, ou savoir jusqu'où votre commerce attire.",
  },

  // ── carte de fidélité ────────────────────────────────────────────────────
  cards_active: {
    t: 'Cartes actives',
    what: "Les cartes de fidélité en circulation.",
    how: "Les cartes non supprimées. L'évolution compare les nouvelles cartes de la période avec celles de la période précédente.",
    why: "Il mesure combien de clients vous pouvez fidéliser et contacter.",
  },
  qr_scans: {
    t: 'Scans QR code',
    what: "Les passages en caisse avec la carte.",
    how: "Chaque visite enregistrée en caisse sur la période.",
    why: "Il montre si la carte est vraiment utilisée.",
  },
  rewards_used: {
    t: 'Récompenses utilisées',
    what: "Les récompenses remises sur la période.",
    how: "Chaque récompense validée en caisse compte une fois.",
    why: "Il montre si vos récompenses motivent vos clients.",
  },

  // ── automatisations ──────────────────────────────────────────────────────
  'auto:active': { t: 'Scénarios actifs', what: "Les automatisations en marche.", how: "Le nombre de scénarios activés.", why: "Chaque scénario actif travaille pour vous, sans y penser." },
  'auto:reached': { t: 'Clients touchés', what: "Les messages envoyés par vos automatisations.", how: "Le nombre de messages partis sur la période.", why: "Il montre l'activité de vos automatisations." },
  'auto:open_rate': {
    t: "Taux d'ouverture",
    what: "La part des clients qui ont ouvert leur carte après un message automatique.",
    how: "Une ouverture = la carte ouverte dans les 72 h suivant l'envoi.",
    why: "Il dit si vos messages automatiques intéressent vos clients.",
  },
  'auto:click_rate': { t: 'Taux de clic', what: "La part des messages dont le lien a été ouvert.", how: "Les clics sur le lien du message divisés par les messages envoyés.", why: "Il mesure l'intérêt pour l'offre." },
  autopilot: {
    t: 'Autopilot',
    what: "FidClic IA prépare une campagne chaque jour et une chaque semaine.",
    how: "Chaque jour : les clients dont c'est le moment (habitués en retard, leur jour habituel, nouveaux après une semaine). Chaque semaine : un grand groupe. Vos limites par client et les clients contactés ces 3 derniers jours sont respectés.",
    why: "Vos campagnes sont prêtes sans y passer de temps ; rien ne part sans votre validation.",
  },
};

export const help = (key, page) => (page && H[`${page}:${key}`]) || H[key] || null;
export default H;
