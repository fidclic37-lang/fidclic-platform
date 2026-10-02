import React, { useEffect, useRef, useState } from 'react';
import { CalendarDays, Check, ChevronDown, Loader2 } from 'lucide-react';

/**
 * The period a page reads its figures over — Tableau de bord and Analyses.
 *
 * A period is a short token, so it fits in the URL and in localStorage:
 *   '1' '7' '30' '90' '365'  the offered ones (« Aujourd'hui » is '1')
 *   '45d' / '6m'             one the merchant typed, in days or in months
 * `periodDays(token)` turns it into the `days` the API reads; a month is a
 * calendar month (6 mois back from today), not 30 days.
 *
 * The API reaches back two years: 730 jours, 24 mois.
 */
export const MAX_DAYS = 730;
export const MAX_MONTHS = 24;

export const PRESETS = [
  { key: '1', label: "Aujourd'hui" },
  { key: '7', label: '7 derniers jours' },
  { key: '30', label: '30 derniers jours' },
  { key: '90', label: '90 derniers jours' },
  { key: '365', label: '12 derniers mois' },
];

const parse = (token) => {
  const m = /^(\d+)([dm]?)$/.exec(String(token ?? '').trim());
  if (!m) return null;
  const n = Number(m[1]);
  const unit = m[2] || 'd';
  if (!n || n < 1) return null;
  if (unit === 'd' && n > MAX_DAYS) return null;
  if (unit === 'm' && n > MAX_MONTHS) return null;
  return { n, unit, preset: !m[2] && PRESETS.some((p) => p.key === String(n)) };
};

export const validPeriod = (token) => parse(token) !== null;

export function periodDays(token) {
  const p = parse(token);
  if (!p) return 30;
  if (p.unit === 'd') return p.n;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const from = new Date(today);
  from.setMonth(from.getMonth() - p.n);
  return Math.min(MAX_DAYS, Math.max(1, Math.round((today - from) / 86400000)));
}

export function periodLabel(token) {
  const p = parse(token);
  if (!p) return '30 derniers jours';
  if (p.preset) return PRESETS.find((x) => x.key === String(p.n)).label;
  if (p.unit === 'm') return p.n === 1 ? 'Le dernier mois' : `${p.n} derniers mois`;
  return p.n === 1 ? "Aujourd'hui" : `${p.n} derniers jours`;
}

export default function PeriodMenu({ value, onChange, busy = false, lead = false }) {
  const [open, setOpen] = useState(false);
  const cur = parse(value);
  const [n, setN] = useState(cur && !cur.preset ? String(cur.n) : '');
  const [unit, setUnit] = useState(cur && !cur.preset ? cur.unit : 'd');
  const [err, setErr] = useState('');
  const box = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc); };
  }, [open]);

  const pick = (token) => { setOpen(false); setErr(''); if (token !== value) onChange(token); };

  const apply = (e) => {
    e?.preventDefault?.();
    const num = Number(n);
    const max = unit === 'm' ? MAX_MONTHS : MAX_DAYS;
    if (!n || !Number.isInteger(num) || num < 1) { setErr('Entrez un nombre supérieur à 0.'); return; }
    if (num > max) { setErr(unit === 'm' ? `24 mois au maximum.` : `${MAX_DAYS} jours au maximum.`); return; }
    // 7 jours typed by hand is the « 7 derniers jours » preset.
    const token = unit === 'd' && PRESETS.some((p) => p.key === String(num)) ? String(num) : `${num}${unit}`;
    pick(token);
  };

  const custom = cur && !cur.preset;
  return (
    <div ref={box} className="relative">
      <button type="button" disabled={busy} onClick={() => setOpen((o) => !o)}
              aria-haspopup="listbox" aria-expanded={open} aria-label="Période analysée"
              className={`inline-flex items-center gap-2 rounded-xl border border-[#E6EEFB] bg-white font-medium text-[#334155] outline-none transition hover:border-[#BFD3FF] focus:border-[#2F6BFF] disabled:opacity-60 ${
                lead ? 'py-2.5 pl-3 pr-2.5 text-[13px] shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]'
                     : 'py-2 pl-3 pr-2 text-[12.5px]'}`}>
        {lead && <CalendarDays size={15} className="text-[#2F6BFF]" />}
        <span className="whitespace-nowrap">{periodLabel(value)}</span>
        {busy ? <Loader2 size={14} className="animate-spin text-[#2F6BFF]" />
              : <ChevronDown size={14} className={`text-[#94A3B8] transition ${open ? 'rotate-180' : ''}`} />}
      </button>

      {open && (
        <div role="listbox"
             className="absolute right-0 z-30 mt-2 w-[248px] rounded-2xl border border-[#E6EEFB] bg-white p-1.5 text-left shadow-[0_24px_48px_-20px_rgba(11,28,63,.35)]">
          {PRESETS.map((p) => {
            const on = value === p.key;
            return (
              <button key={p.key} type="button" role="option" aria-selected={on} onClick={() => pick(p.key)}
                      className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-[13px] transition ${
                        on ? 'bg-[#EAF1FF] font-semibold text-[#2F6BFF]' : 'text-[#334155] hover:bg-[#F5F8FE]'}`}>
                {p.label} {on && <Check size={14} />}
              </button>
            );
          })}
          <form onSubmit={apply} className="mt-1.5 border-t border-[#EEF3FB] px-2 pb-1.5 pt-2.5">
            <p className={`mb-2 flex items-center justify-between text-[11.5px] font-semibold uppercase tracking-wide ${custom ? 'text-[#2F6BFF]' : 'text-[#94A3B8]'}`}>
              Personnalisé {custom && <Check size={13} />}
            </p>
            <div className="flex items-center gap-1.5">
              <span className="text-[12.5px] text-[#64748B]">Les</span>
              <input type="text" inputMode="numeric" autoComplete="off" value={n} placeholder="Ex. 45"
                     aria-label="Nombre"
                     onChange={(e) => { setErr(''); setN(e.target.value.replace(/\D/g, '').replace(/^0+/, '').slice(0, 3)); }}
                     className="w-[64px] rounded-lg border border-[#E6EEFB] px-2 py-1.5 text-[13px] tabular-nums text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />
              <select value={unit} onChange={(e) => { setErr(''); setUnit(e.target.value); }} aria-label="Unité"
                      className="rounded-lg border border-[#E6EEFB] bg-white px-2 py-1.5 text-[13px] text-[#334155] outline-none focus:border-[#2F6BFF]">
                <option value="d">derniers jours</option>
                <option value="m">derniers mois</option>
              </select>
            </div>
            {err && <p className="mt-1.5 text-[11.5px] text-[#C0392B]">{err}</p>}
            <button type="submit" disabled={!n}
                    className="mt-2 w-full rounded-lg bg-[#2F6BFF] py-1.5 text-[12.5px] font-semibold text-white transition hover:bg-[#2559DB] disabled:opacity-50">
              Appliquer
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
