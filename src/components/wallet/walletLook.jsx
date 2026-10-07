import {
  Star, BadgeCheck, CalendarDays, ShoppingBag, ShoppingCart, CreditCard, Phone, Navigation,
  BedDouble, Car, Plane, Film, AudioLines,
} from 'lucide-react';

/**
 * What Apple Wallet draws, shared by the card previews and the card editor:
 * the 14 featured action tiles (icon colour per type, after Pass Designer),
 * the pass styles and their field slots, the customer values a field can hold.
 */
export const ACTION_LOOK = {
  viewOffersRewards: { color: '#D946EF', Icon: Star, label: 'Voir les offres et récompenses' },
  membershipBenefits: { color: '#8B5CF6', Icon: BadgeCheck, label: 'Voir les avantages membres' },
  bookAppointment: { color: '#EF4444', Icon: CalendarDays, label: 'Prendre rendez-vous' },
  order: { color: '#F97316', Icon: ShoppingBag, label: 'Commander (livraison ou retrait)' },
  shop: { color: '#F97316', Icon: ShoppingCart, label: 'Boutique en ligne' },
  addToBalance: { color: '#22C55E', Icon: CreditCard, label: 'Recharger le solde' },
  call: { color: '#22C55E', Icon: Phone, label: 'Appeler', sub: 'Appeler' },
  place: { color: '#3B82F6', Icon: Navigation, label: 'Itinéraire', sub: 'Ouvrir dans Plans' },
  viewSchedule: { color: '#EF4444', Icon: CalendarDays, label: 'Voir le planning' },
  bookStay: { color: '#A855F7', Icon: BedDouble, label: 'Réserver un séjour' },
  bookCar: { color: '#3B82F6', Icon: Car, label: 'Louer une voiture' },
  bookFlight: { color: '#22C55E', Icon: Plane, label: 'Réserver un vol' },
  watchTrailer: { color: '#64748B', Icon: Film, label: 'Voir la bande-annonce' },
  listenToMusic: { color: '#EF4444', Icon: AudioLines, label: 'Écouter la musique' },
};

export function ActionTile({ type, label, s = 1 }) {
  const look = ACTION_LOOK[type] || { color: '#64748B', Icon: Star, label };
  const { Icon } = look;
  return (
    <div className="rounded-2xl text-left" style={{ padding: 10 * s, background: '#2C2C2E', color: '#F2F2F7' }}>
      <span className="mb-2 flex items-center justify-center rounded-full text-white"
            style={{ width: 24 * s, height: 24 * s, background: look.color }}>
        <Icon size={13 * s} strokeWidth={2.4} />
      </span>
      <div style={{ fontSize: 12 * s, fontWeight: 600, lineHeight: 1.25 }}>{look.label || label}</div>
      <div style={{ fontSize: 11 * s, color: '#98989D', marginTop: 4 * s }}>{look.sub || 'Ouvrir le lien'}</div>
    </div>
  );
}

// Pass styles, Pass Designer's names, and the field slots each one has
// (Apple's limits: « Defining the metadata of your Wallet Pass »).
export const STYLES = [
  { key: 'posterGeneric', label: 'Poster Generic', hint: 'Nouvelle carte iOS 27 : grande image, logo, champs en bas' },
  { key: 'generic', label: 'Generic', hint: 'Carte classique : un grand champ, une vignette, deux lignes' },
  { key: 'storeCard', label: 'Store Card', hint: 'Carte de fidélité classique avec bannière' },
  { key: 'coupon', label: 'Coupon', hint: 'Bon de réduction, bords dentelés' },
  { key: 'eventTicket', label: 'Event Ticket', hint: 'Billet d’événement' },
  { key: 'boardingPass', label: 'Boarding Pass', hint: 'Carte d’embarquement (départ → arrivée)' },
];

export const GROUPS = {
  posterGeneric: [['headerFields', 'En-tête', 1], ['primaryFields', 'Champs principaux', 4], ['footerFields', 'Pied', 2]],
  generic: [['headerFields', 'En-tête', 3], ['primaryFields', 'Champ principal', 1], ['secondaryFields', 'Champs secondaires', 4], ['auxiliaryFields', 'Champs auxiliaires', 4]],
  storeCard: [['headerFields', 'En-tête', 3], ['primaryFields', 'Champ principal (sur la bannière)', 1], ['secondaryFields', 'Champs secondaires', 4], ['auxiliaryFields', 'Champs auxiliaires', 4]],
  coupon: [['headerFields', 'En-tête', 3], ['primaryFields', 'Champ principal (sur la bannière)', 1], ['secondaryFields', 'Champs secondaires', 4], ['auxiliaryFields', 'Champs auxiliaires', 4]],
  eventTicket: [['headerFields', 'En-tête', 3], ['primaryFields', 'Champ principal', 1], ['secondaryFields', 'Champs secondaires', 4], ['auxiliaryFields', 'Champs auxiliaires', 4]],
  boardingPass: [['headerFields', 'En-tête', 3], ['primaryFields', 'Départ et arrivée', 2], ['auxiliaryFields', 'Champs auxiliaires', 5], ['secondaryFields', 'Champs secondaires', 5]],
};

// The images each style draws, Apple's sizes in points.
export const IMAGES = {
  posterGeneric: [['background', 'Image de fond', '345 × 505 pt'], ['primaryLogo', 'Logo principal (sur le poster)', '160 × 50 pt max']],
  generic: [['logo', 'Logo', '160 × 50 pt max'], ['thumbnail', 'Vignette', '90 × 90 pt']],
  storeCard: [['logo', 'Logo', '160 × 50 pt max'], ['strip', 'Bannière', '375 × 144 pt']],
  coupon: [['logo', 'Logo', '160 × 50 pt max'], ['strip', 'Bannière', '375 × 144 pt']],
  eventTicket: [['logo', 'Logo', '160 × 50 pt max'], ['background', 'Fond (flouté par Wallet)', '180 × 220 pt'], ['strip', 'Bannière', '375 × 98 pt'], ['thumbnail', 'Vignette', '90 × 90 pt']],
  boardingPass: [['logo', 'Logo', '160 × 50 pt max'], ['footer', 'Image de pied', '286 × 15 pt']],
};
export const ICON_IMAGE = ['icon', 'Icône (notifications)', '29 × 29 pt'];

// {placeholders} the server fills for each customer (features/pass_designer)
export const FIELD_VARS = [
  ['{prenom}', 'Prénom'], ['{nom}', 'Nom complet'], ['{carte}', 'N° de carte'], ['{points}', 'Points'],
  ['{tampons}', 'Tampons (3 / 10)'], ['{statut}', 'Statut'], ['{recompense}', 'Prochaine récompense'],
  ['{offre}', 'Offre du moment'], ['{visites}', 'Visites'], ['{membre_depuis}', 'Membre depuis'], ['{commerce}', 'Nom du commerce'],
];

export const TRANSIT = [
  ['PKTransitTypeGeneric', 'Générique'], ['PKTransitTypeAir', 'Avion'], ['PKTransitTypeTrain', 'Train'],
  ['PKTransitTypeBus', 'Bus'], ['PKTransitTypeBoat', 'Bateau'],
];

export const ALIGN = [
  ['', 'Automatique'], ['PKTextAlignmentLeft', 'Gauche'], ['PKTextAlignmentCenter', 'Centre'], ['PKTextAlignmentRight', 'Droite'],
];

// "rgb(r, g, b)" ↔ "#rrggbb"
export const rgbToHex = (v) => {
  const m = String(v || '').match(/(\d+)\D+(\d+)\D+(\d+)/);
  if (!m) return String(v || '').startsWith('#') ? v : '#000000';
  return `#${[m[1], m[2], m[3]].map((n) => Math.max(0, Math.min(255, Number(n))).toString(16).padStart(2, '0')).join('')}`;
};
export const hexToRgb = (h) => {
  const m = String(h || '').replace('#', '').match(/^([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
  return m ? `rgb(${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)})` : h;
};
