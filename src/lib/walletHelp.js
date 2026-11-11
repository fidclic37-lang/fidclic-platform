/* What the till says under a visit when the client's Wallet card can't be
   reached (`wallet_link` from the scan), and the steps worth trying for THAT
   Wallet (user, 2026-11-11, a client). Pure: unit-tested with
   node --test src/lib/walletHelp.test.js. */
export const APPLE_STEPS = [
  'Sur son iPhone : Cartes (Wallet) › sa carte › « … » › Détails de la carte › activer « Mises à jour automatiques ».',
  'Dans ces mêmes détails, tirer l’écran vers le bas pour Actualiser (Wi-Fi ou données mobiles allumés).',
  'Carte plus dans le Wallet, ou toujours rien ? Supprimer la carte du Wallet, puis la rajouter avec le QR ci-dessous (« Ajouter à Apple Wallet »).',
];
export const GOOGLE_STEPS = [
  'Ouvrir Google Wallet sur son téléphone, connecté au même compte Google que lors de l’ajout.',
  'Carte plus dans Google Wallet ? Scanner le QR ci-dessous avec son téléphone, puis « Ajouter à Google Wallet ».',
  'Internet allumé (Wi-Fi ou données mobiles) : la carte se met à jour en quelques secondes.',
];
export const WALLET_NAMES = { apple: 'Apple Wallet', google: 'Google Wallet' };
export function walletHelp(link) {
  if (!link || link.linked !== false) return null;
  if (link.reason === 'never_added') {
    return {
      tone: 'info', steps: [],
      title: 'Carte pas encore dans un Wallet.',
      note: 'La visite est enregistrée : s’il ajoute sa carte maintenant (« Ajouter à Apple Wallet / Google Wallet » sur sa page), elle aura déjà cette visite.',
      qr: 'Afficher le QR de sa carte',
    };
  }
  if (link.reason === 'removed' && link.wallet === 'google') {
    return {
      tone: 'error', steps: GOOGLE_STEPS, qr: 'Afficher le QR à scanner',
      title: 'Sa carte a été retirée de son Google Wallet : elle ne se met plus à jour.',
      note: 'La visite est bien enregistrée (sur sa page, pas dans son Wallet). À essayer, dans l’ordre :',
    };
  }
  return {
    tone: 'error', steps: APPLE_STEPS, qr: 'Afficher le QR à scanner',
    title: link.reason === 'removed'
      ? 'Son iPhone ne reçoit plus les mises à jour de sa carte (retirée du Wallet ou mises à jour coupées).'
      : 'Sa carte est sur son iPhone mais reliée à aucun téléphone : son Wallet ne se mettra pas à jour.',
    note: 'La visite est bien enregistrée (sur sa page, pas dans son Wallet). À essayer, dans l’ordre :',
  };
}
