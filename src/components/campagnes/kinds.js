import { Percent, Send, Trophy, CalendarCheck2, Star, Gift, RefreshCw } from 'lucide-react';

// The campaign types of the mockup (Campagnes redesign, 2026-10-10).
export const KIND_META = {
  offre: { label: 'Offre spéciale', short: 'Offre', icon: Percent, bg: '#FFECEC', fg: '#EF4444',
    sub: 'Une promotion pour booster vos ventes.' },
  nouveaute: { label: 'Nouveauté', short: 'Nouveauté', icon: Send, bg: '#EAF1FF', fg: '#2F6BFF',
    sub: "Informez vos clients d'un nouveau produit, menu ou service." },
  defi: { label: 'Défi', short: 'Défi', icon: Trophy, bg: '#FFF4E0', fg: '#F59E0B',
    sub: 'Incitez vos clients à revenir plus souvent.' },
  evenement: { label: 'Événement', short: 'Événement', icon: CalendarCheck2, bg: '#FFECEC', fg: '#EF4444',
    sub: 'Communiquez autour d\'un événement.' },
  configurer: { label: 'Configurer une offre', short: 'Offre', icon: Star, bg: '#FFECEC', fg: '#EF4444',
    sub: 'Créez une offre ou une récompense pour votre programme de fidélité.' },
  message: { label: 'Notification', short: 'Message', icon: Send, bg: '#EAF1FF', fg: '#2F6BFF', sub: '' },
};

export const TYPE_ORDER = ['offre', 'nouveaute', 'defi', 'evenement', 'configurer'];

export const VARIABLES = [
  { key: 'prénom', label: 'Prénom du client', icon: 'user', tone: 'blue' },
  { key: 'prochaine_récompense', label: 'Prochaine récompense', icon: 'gift', tone: 'rose' },
  { key: 'nom_commerce', label: 'Nom du commerce', icon: 'store', tone: 'violet' },
  { key: 'points_manquants', label: 'Points manquants', icon: 'trophy', tone: 'amber' },
  { key: 'points', label: 'Nombre de points', icon: 'star', tone: 'green' },
  { key: 'visites', label: 'Nombre de visites', icon: 'chart', tone: 'violet' },
  // FidClic IA (2026-10-25): « votre Coupe », or « votre prochaine visite »
  { key: 'produit_habituel', label: 'Produit habituel', icon: 'gift', tone: 'green' },
];

// « Exemples de messages » — by kind, with {variables}
export function examplesFor(kind, title) {
  const t = (title || '').trim();
  const lead = {
    offre: { icon: Percent, tone: '#EF4444', bg: '#FFECEC', title: "Mettre en avant l'offre",
      text: `Bonjour {prénom} ! Profitez dès maintenant de ${t || 'notre offre'} chez {nom_commerce} !` },
    nouveaute: { icon: Send, tone: '#2F6BFF', bg: '#EAF1FF', title: 'Annoncer la nouveauté',
      text: `Bonjour {prénom} ! Découvrez ${t || 'notre nouveauté'} chez {nom_commerce}, on vous attend !` },
    evenement: { icon: CalendarCheck2, tone: '#EF4444', bg: '#FFECEC', title: "Inviter à l'événement",
      text: `{prénom}, vous êtes invité(e) : ${t || 'notre événement'} chez {nom_commerce} !` },
    defi: { icon: Trophy, tone: '#F59E0B', bg: '#FFF4E0', title: 'Lancer le défi',
      text: `Nouveau défi {prénom} : ${t || 'relevez-le'} et gagnez votre récompense chez {nom_commerce} !` },
  }[kind] || null;
  return [
    ...(lead ? [lead] : []),
    { icon: Gift, tone: '#7C3AED', bg: '#F1EAFF', title: 'Récompense disponible',
      text: 'Bonne nouvelle {prénom} 🎉 ! Votre prochaine récompense vous attend. Venez en profiter !' },
    { icon: Star, tone: '#059669', bg: '#E3F6EC', title: 'Remercier un client fidèle',
      text: 'Merci pour votre fidélité {prénom} ! Vous avez maintenant {points} points.' },
    { icon: RefreshCw, tone: '#2F6BFF', bg: '#EAF1FF', title: 'Faire revenir un client',
      text: 'Bonjour {prénom} ! Cela fait un moment que nous ne vous avons pas vu chez {nom_commerce}. On vous attend !' },
  ];
}

export const EMOJIS = ['🎉', '🔥', '⭐', '🎁', '☕', '🍰', '🍕', '🍔', '🥐', '🍹', '💇', '💅', '🛍️', '❤️',
  '😍', '😋', '👋', '👉', '⏰', '📅', '💥', '✨', '🙏', '💯'];

const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const LONG_MONTHS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
const DAYS = ['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi'];

export const dayShort = (ymd) => {
  if (!ymd) return '';
  const [y, m, d] = ymd.split('-').map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
};
export const dayLong = (date) => {
  const d = date instanceof Date ? date : new Date(date);
  const s = `${DAYS[d.getDay()]} ${d.getDate()} ${LONG_MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  return s.charAt(0).toUpperCase() + s.slice(1);
};
export const todayYmd = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};
export const addDays = (ymd, n) => {
  const [y, m, d] = ymd.split('-').map(Number);
  const x = new Date(y, m - 1, d + n);
  return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
};
export const daysBetween = (a, b) => {
  const [y1, m1, d1] = a.split('-').map(Number);
  const [y2, m2, d2] = b.split('-').map(Number);
  return Math.round((new Date(y2, m2 - 1, d2) - new Date(y1, m1 - 1, d1)) / 86400000);
};
export const hh = (t) => (t ? `${Number(t.split(':')[0])}h${t.split(':')[1] === '00' ? '' : t.split(':')[1]}` : '');
