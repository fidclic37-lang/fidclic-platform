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
};

// what each {variable} reads as in the chips and in the preview
export const VAR_LABELS = {
  'prénom': 'Prénom du client', nom_commerce: 'Nom du commerce', points: 'Nombre de points', visites: 'Nombre de visites',
  'prochaine_récompense': 'Prochaine récompense', points_manquants: 'Points manquants', palier: 'Palier atteint',
  visites_restantes: 'Visites restantes', visite_s: '« visite » ou « visites »', filleul: 'Prénom du filleul', parrain: 'Prénom du parrain',
  'points_gagnés': 'Points gagnés', visite_ami: '« est venu / est revenu »', 'établissement': 'Établissement le plus proche',
  jours_absence: "Jours d'absence",
};

export const DAY_NAMES = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];

export const GENDERS = [['all', 'Tous'], ['F', 'Femmes'], ['M', 'Hommes'], ['X', 'Autre']];
export const AGES = [['all', 'Tous'], ['18-24', '18 – 24 ans'], ['25-34', '25 – 34 ans'], ['35-49', '35 – 49 ans'], ['50+', '50 ans et +']];
export const FREQS = [['all', 'Tous'], ['weekly', 'Chaque semaine (4+ / mois)'], ['monthly', '1 à 3 fois par mois'], ['rare', "Moins d'une fois par mois"]];
export const SPENT = [['all', 'Tous'], ['<50', 'Moins de 50 €'], ['50-200', '50 € – 200 €'], ['200-500', '200 € – 500 €'], ['>500', 'Plus de 500 €']];
export const LAST_VISIT = [['all', 'Toutes les périodes'], ['7', 'Moins de 7 jours'], ['30', 'Moins de 30 jours'], ['90', 'Moins de 90 jours'],
  ['>30', 'Plus de 30 jours'], ['>90', 'Plus de 90 jours']];

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
    first_name: s.first_name || 'Sarah', business_name: shop || 'votre commerce', ...extra,
  };
  return String(text || '').replace(/\{([^{}\s]+)\}/g, (m, k) => (k in v ? v[k] : m));
}
