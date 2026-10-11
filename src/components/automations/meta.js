import { Cake, Trophy, PartyPopper, Gift, Users, MapPin, Star, RefreshCw, Sparkles } from 'lucide-react';

// The eight scenarios of the Automatisations redesign (2026-10-11) — the
// server's features/automations.py SCENARIOS, with the page's icons and colours.
export const ICONS = { sparkles: Sparkles, cake: Cake, trophy: Trophy, hand: PartyPopper, gift: Gift, users: Users, pin: MapPin, star: Star, refresh: RefreshCw };
export const TONES = {
  rose: ['#FFECEF', '#E11D48'], amber: ['#FFF4E0', '#F59E0B'], blue: ['#EAF1FF', '#2F6BFF'],
  violet: ['#F1EAFF', '#7C3AED'], green: ['#E3F6EC', '#059669'], red: ['#FFECEC', '#EF4444'],
};

export const STATUS = {
  active: ['Active', '#059669'], paused: ['En pause', '#64748B'], draft: ['Brouillon', '#B45309'],
  ended: ['Terminée', '#94A3B8'],                 // its « période de validité » is over
};

// what each {variable} reads as in the chips and in the preview
export const VAR_LABELS = {
  'prénom': 'Prénom du client', nom_commerce: 'Nom du commerce', points: 'Nombre de points', visites: 'Nombre de visites',
  'prochaine_récompense': 'Prochaine récompense', points_manquants: 'Points manquants', palier: 'Palier atteint',
  visites_restantes: 'Visites restantes', visite_s: '« visite » ou « visites »', filleul: 'Prénom du filleul', parrain: 'Prénom du parrain',
  'points_gagnés': 'Points gagnés', visite_ami: '« est venu / est revenu »', 'établissement': 'Établissement le plus proche',
  jours_absence: "Jours d'absence", nom: 'Nom complet du client', 'récompense': 'Récompense du palier',
  distance: 'Distance', offre: 'Offre en cours',
};
// the « + Prénom » chips of the message step (mockups, 2026-10-11)
export const VAR_SHORT = {
  'prénom': 'Prénom', nom: 'Nom du client', nom_commerce: 'Nom du commerce', points: 'Points', visites: 'Visites',
  'prochaine_récompense': 'Prochaine récompense', points_manquants: 'Points manquants', palier: 'Palier',
  visites_restantes: 'Visites restantes', visite_s: 'visite(s)', filleul: 'Filleul', parrain: 'Parrain',
  'points_gagnés': 'Points gagnés', visite_ami: 'Venu / revenu', 'établissement': "Nom de l'établissement",
  jours_absence: "Jours d'absence", 'récompense': 'Récompense', distance: 'Distance', offre: 'Offre',
};
// Géolocalisation (mockups 2026-10-11)
export const PASSANTS = [
  ['all', 'Tous les passants', 'Aucune restriction', ''], ['new', 'Nouveaux passants', 'Jamais venus', '0 visite'],
  ['regular', 'Passants réguliers', 'Déjà venus quelques fois', '1 à 10 visites'], ['old', 'Anciens clients', 'Déjà venus plusieurs fois', '11 visites et plus'],
];
export const RUSH = [['matin', 'Matin', '08:00', '11:00'], ['midi', 'Midi', '11:00', '14:00'], ['apm', 'Après-midi', '14:00', '17:00'],
  ['soir', 'Soir', '17:00', '21:00'], ['nuit', 'Nuit', '21:00', '08:00']];
export const hLabel = (hm) => { const [h, m] = String(hm || '').split(':'); return `${Number(h)}h${m && m !== '00' ? m : ''}`; };

export const DAY_NAMES = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];

// « Filtres avancés » (palier mockups, 2026-10-11): ticks inside a group
// widen it, groups narrow each other; nothing ticked = Tous.
export const GENDERS = [['F', 'Femme'], ['M', 'Homme'], ['X', 'Autre']];
export const AGES = [['<18', 'Moins de 18 ans'], ['18-25', '18 – 25 ans'], ['26-35', '26 – 35 ans'], ['36-50', '36 – 50 ans'], ['50+', 'Plus de 50 ans']];
export const FREQS = [['new', 'Nouveau client (1 visite)'], ['occasional', 'Occasionnel (2–3 visites)'], ['regular', 'Régulier (4–10 visites)'], ['loyal', 'Fidèle (+10 visites)']];
export const SPENT = [['<50', 'Moins de 50 €'], ['50-100', '50 € – 100 €'], ['100-200', '100 € – 200 €'], ['>200', 'Plus de 200 €']];
export const LAST_VISIT = [['<7', 'Moins de 7 jours'], ['8-30', 'Entre 8 et 30 jours'], ['1-3m', 'Entre 1 et 3 mois'], ['>3m', 'Plus de 3 mois']];
export const RADII = [1, 2, 5, 10, 20, 50];
export const EMPTY_FILTERS = { gender: [], age: [], frequency: [], spent: [], last_visit: [], stores: [], radius_km: null };
// older single values ("all", "F"…) read as lists of known ticks
export const asList = (v, allowed) => {
  const ok = new Set(allowed.map((x) => x[0]));
  if (v == null || v === '' || v === 'all') return [];
  return [...new Set((Array.isArray(v) ? v : [v]).map(String))].filter((x) => ok.has(x));
};

// Exemples de messages — ready-made words per scenario (the page's right rail
// and the « Exemples » page; the user will refine that page from mockups).
export const EXAMPLES = [
  { scenario: 'birthday', group: 'Fidélisation', title: 'Joyeux anniversaire {prénom} ! 🎉',
    body: "Toute l'équipe de {nom_commerce} vous souhaite un merveilleux anniversaire ! Une surprise vous attend.", button: 'Découvrir ma surprise' },
  { scenario: 'tier_up', group: 'Fidélisation', title: 'Bravo {prénom} ! 🏆',
    body: 'Vous avez atteint le palier {palier} chez {nom_commerce}. Découvrez vos avantages : {prochaine_récompense}.', button: 'Voir mes avantages' },
  { scenario: 'welcome', group: 'Fidélisation', title: 'Bienvenue chez {nom_commerce} 🎉',
    body: 'Merci {prénom} ! Votre carte est prête : à chaque visite, vous vous rapprochez de votre récompense.', button: 'Voir ma carte' },
  { scenario: 'near_reward', group: 'Fidélisation', title: 'Plus que {visites_restantes} visite(s), {prénom} !',
    body: 'Encore {visites_restantes} visite(s) chez {nom_commerce} et {prochaine_récompense} est à vous.', button: 'Voir ma récompense' },
  { scenario: 'referral', group: 'Fidélisation', title: 'Parrainage réussi 🎉',
    body: 'Votre ami {filleul} {visite_ami} chez {nom_commerce} : +{points_gagnés} points pour vous !', button: 'Voir mes points' },
  { scenario: 'inactive', group: 'Réactivation', title: 'On ne vous a pas vu depuis un moment',
    body: 'Bonjour {prénom}, nous serions ravis de vous retrouver chez {nom_commerce} ! Une attention vous attend.', button: 'Voir mon offre' },
  { scenario: 'google_review', group: 'Avis', title: 'Votre avis compte ⭐',
    body: 'Bonjour {prénom}, votre expérience chez {nom_commerce} nous intéresse. Laissez-nous un avis, cela nous aide beaucoup !', button: 'Laisser un avis' },
  { scenario: 'geo', group: 'Géolocalisation', title: 'Vous êtes tout près ! 👋',
    body: 'Bonjour {prénom}, profitez de votre passage près de {nom_commerce} pour découvrir notre offre du moment.', button: "Voir l'offre" },
];

// {variable} → the sample client's value, for the previews
export function fill(text, sample, shop, extra = {}) {
  const s = sample || {};
  const v = {
    'prénom': s.first_name || 'Sarah', prenom: s.first_name || 'Sarah', nom_commerce: shop || 'votre commerce',
    points: String(s.points ?? 120), visites: String(s.visits ?? 5), 'prochaine_récompense': s.next_reward || 'votre récompense',
    points_manquants: '3', palier: 'Or', visites_restantes: '2', visite_s: 'visites', filleul: 'Léa', parrain: 'Marc',
    'points_gagnés': '50', visite_ami: 'est venu', 'établissement': shop || 'votre boutique', jours_absence: '45',
    distance: '80 m', offre: 'notre offre du moment',
    first_name: s.first_name || 'Sarah', business_name: shop || 'votre commerce', ...extra,
  };
  return String(text || '').replace(/\{([^{}\s]+)\}/g, (m, k) => (k in v ? v[k] : m));
}
