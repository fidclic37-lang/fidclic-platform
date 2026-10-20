import React from 'react';

/**
 * An hour field that always reads the French way — 13:00, 14:30 — never
 * « 1:00 PM » (user, 2026-10-20: « 13h, 14h and not 1pm, 2pm, kyunki France
 * mein aisa hi chalta hai »). The browser's own <input type="time"> follows
 * the browser's language, not the page's: an English Chrome showed « 01:53 pm ».
 *
 * Same contract as that input: value « HH:MM » (or « » when empty),
 * onChange(event-like) with event.target.value « HH:MM ».
 */
const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'));

export default function TimeInput24({
  value, onChange, className = '', step = 1, required = false, disabled = false,
  'aria-label': ariaLabel = 'Heure', allowEmpty = false, id, style,
}) {
  const [h, m] = (value || '').split(':');
  const minutes = Array.from({ length: Math.ceil(60 / step) }, (_, i) => String(i * step).padStart(2, '0'));
  // a saved minute off the step (e.g. 07 with a step of 5) stays choosable
  if (m && !minutes.includes(m)) { minutes.push(m); minutes.sort(); }
  const emit = (hh, mm) => {
    const v = hh === '' ? '' : `${hh}:${mm || '00'}`;
    onChange?.({ target: { value: v } });
  };
  const sel = 'appearance-none bg-transparent text-center outline-none tabular-nums cursor-pointer disabled:cursor-not-allowed';
  return (
    <span translate="no" role="group" aria-label={ariaLabel} style={style}
          className={`notranslate inline-flex items-center gap-0.5 ${className}`}>
      <select id={id} value={h || ''} required={required} disabled={disabled} aria-label={`${ariaLabel} — heures`}
              onChange={(e) => emit(e.target.value, m)} className={sel}>
        {(allowEmpty || !h) && <option value="">--</option>}
        {HOURS.map((x) => <option key={x} value={x}>{x}</option>)}
      </select>
      <span aria-hidden="true">:</span>
      <select value={m || (h ? '00' : '')} disabled={disabled || !h} aria-label={`${ariaLabel} — minutes`}
              onChange={(e) => emit(h || '00', e.target.value)} className={sel}>
        {!h && <option value="">--</option>}
        {minutes.map((x) => <option key={x} value={x}>{x}</option>)}
      </select>
    </span>
  );
}
