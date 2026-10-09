import React, { useEffect, useRef, useState } from 'react';

/**
 * DecimalInput — an amount field that reads French and English decimals
 * alike (QA F12, 2026-10-08: in a number field, « 1,25 » became « 125 » —
 * the browser drops a comma it does not expect, and a cashier could record
 * a visit a hundred times too large).
 *
 * A text field with the decimal keypad: « 1,25 » and « 1.25 » both mean one
 * euro twenty-five. It shows a comma, keeps `decimals` digits after it at
 * most, refuses letters, and hands the parent a dot string (« 1.25 », or
 * « » when empty) that parseFloat / Number / the API all read.
 *
 * Props: value (number | string), onChange(dotString), decimals (2),
 * allowNegative (false), onInvalid(message | null); anything else goes to
 * the <input>.
 *
 * A minus sign where none is allowed (QA F20, 2026-10-09): with `onInvalid`,
 * the field keeps « -1 » on screen, hands the parent an empty value and says
 * why — so nothing can be saved by mistake. Without it, the sign is dropped
 * as before (fields that never asked to explain).
 */
export function cleanDecimal(raw, decimals = 2, allowNegative = false) {
  let s = String(raw ?? '').replace(/\s/g, '').replace(/\./g, ',');
  const negative = allowNegative && s.startsWith('-');
  s = s.replace(/[^0-9,]/g, '');
  const [whole, ...rest] = s.split(',');
  let out = whole;
  if (decimals > 0 && rest.length) out += `,${rest.join('').slice(0, decimals)}`;
  return (negative ? '-' : '') + out;
}

export const toDot = (s) => String(s ?? '').replace(',', '.');

const toDisplay = (v) => (v === null || v === undefined ? '' : String(v).replace('.', ','));

export const NEGATIVE_MESSAGE = 'Le montant ne peut pas être négatif.';

export default function DecimalInput({ value, onChange, decimals = 2, allowNegative = false, onInvalid, ...rest }) {
  const [draft, setDraft] = useState(toDisplay(value));
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setDraft(toDisplay(value));
  }, [value]);
  return (
    <input
      type="text"
      inputMode="decimal"
      autoComplete="off"
      {...rest}
      value={draft}
      onFocus={(e) => { focused.current = true; rest.onFocus && rest.onFocus(e); }}
      onBlur={(e) => { focused.current = false; rest.onBlur && rest.onBlur(e); }}
      aria-invalid={rest['aria-invalid']}
      onChange={(e) => {
        const raw = e.target.value;
        // a leading minus is a negative amount; a hyphen elsewhere is just noise
        if (onInvalid && !allowNegative && raw.trim().startsWith('-')) {
          setDraft(cleanDecimal(raw, decimals, true) || '-');
          onChange('');
          onInvalid(NEGATIVE_MESSAGE);
          return;
        }
        const d = cleanDecimal(raw, decimals, allowNegative);
        setDraft(d);
        onChange(toDot(d));
        if (onInvalid) onInvalid(null);
      }}
    />
  );
}
