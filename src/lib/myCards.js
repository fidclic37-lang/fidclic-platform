/**
 * The cards this phone holds — { "FT-…": ownerKey } in localStorage.
 *
 * A card's QR opens /card/FT-…, so the link alone never proves the phone is
 * the card's: a friend can scan it. A card counts as this phone's only after
 * it was opened with its owner key (?k=, on the links that reach the owner:
 * Wallet, signup, SMS…) — see api/services/card_owner.py. The card page sends
 * this list to /card/{id}/whose, which answers: the card, this phone's own
 * card for that shop, or the signup form.
 *
 * `fidelitour:last_card` (the home-screen app's failsafe in main.jsx) is only
 * ever written for a card of this phone.
 */
const KEY = 'fidclic:my_cards';
const LAST = 'fidelitour:last_card';

export function readMine() {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || '{}');
    return v && typeof v === 'object' && !Array.isArray(v) ? v : {};
  } catch (_e) {
    return {};
  }
}

const write = (v) => { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch (_e) { /* private mode */ } };

export function addMine(barcodeId, key) {
  const bc = String(barcodeId || '').toUpperCase();
  if (!bc || !key) return;
  write({ ...readMine(), [bc]: key });
  try { localStorage.setItem(LAST, bc); } catch (_e) { /* private mode */ }
}

export function forgetMine(barcodeIds) {
  if (!barcodeIds?.length) return;
  const v = readMine();
  barcodeIds.forEach((b) => { delete v[String(b).toUpperCase()]; });
  write(v);
  try {
    const last = localStorage.getItem(LAST);
    if (last && barcodeIds.map((b) => String(b).toUpperCase()).includes(last.toUpperCase())) localStorage.removeItem(LAST);
  } catch (_e) { /* private mode */ }
}

export const keyOf = (barcodeId) => readMine()[String(barcodeId || '').toUpperCase()] || null;

/** /card/FT-…?k=… — the owner's link, for a card this phone holds. */
export function ownerLink(barcodeId, key, extra = '') {
  const bc = String(barcodeId || '').toUpperCase();
  const k = key || keyOf(bc);
  const q = [extra, k ? `k=${encodeURIComponent(k)}` : ''].filter(Boolean).join('&');
  return `/card/${bc}${q ? `?${q}` : ''}`;
}
