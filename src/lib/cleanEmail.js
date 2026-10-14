/*
 * An e-mail field drops what cannot be in an address the moment it arrives
 * (user, 2026-10-14: « ye email toh theek hai toh fir kyun access nhi de paa
 * rha »). A copied address often carries an invisible character — a
 * zero-width space, a non-breaking space, a soft hyphen — that the browser
 * then refuses with « A part followed by '@' should not contain the symbol
 * '' ». Nobody can see it, so nobody can remove it.
 *
 * One listener for the whole page, like keepInput.js, rather than ~20 fields:
 * in the capture phase, before React reads the field, every
 * <input type="email"> loses its invisible characters (the browser itself trims its ends). React then
 * sees the clean value as what was typed.
 */

// invisible ones: odd spaces, zero-width and joiner characters, direction marks, soft hyphen, BOM.
// A plain space stays — it is visible, and « marie dupont@… » must be refused, not glued
const INVISIBLE = /[\u00A0\u00AD\u034F\u061C\u115F\u1160\u17B4\u17B5\u180E\u2000-\u200F\u2028-\u202F\u205F-\u206F\u3000\u3164\uFEFF\uFFA0]/g;

// no trim here: a space typed between two words must stay visible until the next key
export const cleanEmail = (s) => String(s ?? '').replace(INVISIBLE, '');

const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;

function scrub(e) {
  const el = e.target;
  if (!(el instanceof HTMLInputElement) || el.type !== 'email') return;
  const clean = cleanEmail(el.value);
  if (clean === el.value) return;
  setValue.call(el, clean);              // the prototype's setter: React's tracker still holds the old value
  try { el.setSelectionRange(clean.length, clean.length); } catch (_e) { /* email inputs may refuse it */ }
}

export function installCleanEmail() {
  if (typeof document === 'undefined' || document.__cleanEmail) return;
  document.__cleanEmail = true;
  document.addEventListener('input', scrub, true);
  document.addEventListener('change', scrub, true);
}
