import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { CalendarDays, Check, ChevronDown, Loader2 } from 'lucide-react';
import {
  MAX_DAYS, MAX_MONTHS, PRESETS, periodLabel, months, rangeError, today, oldest, lastParts,
} from '../lib/period';

/**
 * The period menu of the Tableau de bord and Analyses: the presets, « Ce
 * mois-ci », a whole month, one date, a from–to range, and the last N days or
 * months typed by hand (user, 2026-11-03). The tokens, their labels and what
 * the API reads live in lib/period.js.
 */
export {
  MAX_DAYS, MAX_MONTHS, PRESETS, validPeriod, periodDays, periodLabel, periodParams, readPeriod, savePeriod,
} from '../lib/period';

const section = (on) => `mb-2 flex items-center justify-between text-[11.5px] font-semibold uppercase tracking-wide ${on ? 'text-[#2F6BFF]' : 'text-[#94A3B8]'}`;
const field = 'min-w-0 rounded-lg border border-[#E6EEFB] bg-white px-2 py-1.5 text-[13px] text-[#334155] outline-none focus:border-[#2F6BFF]';
const go = 'mt-2 w-full rounded-lg bg-[#2F6BFF] py-1.5 text-[12.5px] font-semibold text-white transition hover:bg-[#2559DB] disabled:opacity-50';

export default function PeriodMenu({ value, onChange, busy = false, lead = false }) {
  const [open, setOpen] = useState(false);
  const cur = lastParts(value);
  const [n, setN] = useState(cur && !cur.preset ? String(cur.n) : '');
  const [unit, setUnit] = useState(cur && !cur.preset ? cur.unit : 'd');
  const [err, setErr] = useState('');
  const kind = /^[mdr]\d/.test(value || '') ? value[0] : '';
  const [day, setDay] = useState(kind === 'd' ? value.slice(1) : '');
  const [from, setFrom] = useState(kind === 'r' ? value.slice(1, 11) : '');
  const [to, setTo] = useState(kind === 'r' ? value.slice(12) : '');
  const [rangeErr, setRangeErr] = useState('');
  const [dayErr, setDayErr] = useState('');
  const box = useRef(null);
  const menu = useRef(null);
  // which edge of the button the menu hangs from: the right one by default,
  // the left one when that would run past the left of the screen (a phone,
  // the button on the left — user, 2026-10-28). Measured before it paints.
  const [side, setSide] = useState('right');
  useLayoutEffect(() => {
    if (!open) { setSide('right'); return; }
    if (side !== 'right' || !menu.current) return;
    if (menu.current.getBoundingClientRect().left < document.body.getBoundingClientRect().left + 8) setSide('left');
  }, [open, side]);

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

  const showDay = (e) => {
    e.preventDefault();
    const why = rangeError(day, day);
    if (why) { setDayErr(why === 'Choisissez une date de début et une date de fin.' ? 'Choisissez une date.' : why); return; }
    pick(`d${day}`);
  };
  const showRange = (e) => {
    e.preventDefault();
    const why = rangeError(from, to);
    if (why) { setRangeErr(why); return; }
    pick(from === to ? `d${from}` : `r${from}_${to}`);
  };
  const custom = cur && !cur.preset;
  const max = today();
  const min = oldest();
  const monthList = months();
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
        <div role="listbox" ref={menu}
             className={`absolute ${side === 'left' ? 'left-0' : 'right-0'} z-30 mt-2 max-h-[min(78vh,640px)] w-[264px] max-w-[calc(100vw-24px)] overflow-y-auto overscroll-contain rounded-2xl border border-[#E6EEFB] bg-white p-1.5 text-left shadow-[0_24px_48px_-20px_rgba(11,28,63,.35)]`}>
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
          <div className="mt-1.5 border-t border-[#EEF3FB] px-2 pb-1.5 pt-2.5">
            <label htmlFor="period-month" className={section(kind === 'm')}>Un mois {kind === 'm' && <Check size={13} />}</label>
            <select id="period-month" aria-label="Un mois" value={kind === 'm' ? value : ''}
                    onChange={(e) => e.target.value && pick(e.target.value)} className={`${field} w-full`}>
              <option value="">Choisir un mois…</option>
              {monthList.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
            </select>
          </div>
          <form onSubmit={showDay} className="border-t border-[#EEF3FB] px-2 pb-1.5 pt-2.5">
            <label htmlFor="period-day" className={section(kind === 'd')}>Une date {kind === 'd' && <Check size={13} />}</label>
            <input id="period-day" type="date" lang="fr" aria-label="Une date" value={day} min={min} max={max}
                   onChange={(e) => { setDayErr(''); setDay(e.target.value); }} className={`${field} w-full`} />
            {dayErr && <p className="mt-1.5 text-[11.5px] text-[#C0392B]">{dayErr}</p>}
            <button type="submit" disabled={!day} className={go}>Voir ce jour</button>
          </form>
          <form onSubmit={showRange} className="border-t border-[#EEF3FB] px-2 pb-1.5 pt-2.5">
            <p className={section(kind === 'r')}>Du … au … {kind === 'r' && <Check size={13} />}</p>
            <div className="grid grid-cols-[auto_1fr] items-center gap-x-1.5 gap-y-1.5">
              <span className="text-[12.5px] text-[#64748B]">Du</span>
              <input type="date" lang="fr" aria-label="Du" value={from} min={min} max={max}
                     onChange={(e) => { setRangeErr(''); setFrom(e.target.value); }} className={field} />
              <span className="text-[12.5px] text-[#64748B]">Au</span>
              <input type="date" lang="fr" aria-label="Au" value={to} min={min} max={max}
                     onChange={(e) => { setRangeErr(''); setTo(e.target.value); }} className={field} />
            </div>
            {rangeErr && <p className="mt-1.5 text-[11.5px] text-[#C0392B]">{rangeErr}</p>}
            <button type="submit" disabled={!from || !to} className={go}>Voir la période</button>
          </form>
          <form onSubmit={apply} className="border-t border-[#EEF3FB] px-2 pb-1.5 pt-2.5">
            <p className={section(custom)}>
              Personnalisé {custom && <Check size={13} />}
            </p>
            <div className="flex items-center gap-1.5">
              <span className="shrink-0 text-[12.5px] text-[#64748B]">Les</span>
              <input type="text" inputMode="numeric" autoComplete="off" value={n} placeholder="Ex. 45"
                     aria-label="Nombre"
                     onChange={(e) => { setErr(''); setN(e.target.value.replace(/\D/g, '').replace(/^0+/, '').slice(0, 3)); }}
                     className="w-[62px] shrink-0 rounded-lg border border-[#E6EEFB] px-2 py-1.5 text-[13px] tabular-nums text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />
              <select value={unit} onChange={(e) => { setErr(''); setUnit(e.target.value); }} aria-label="Unité"
                      className="min-w-0 flex-1 rounded-lg border border-[#E6EEFB] bg-white px-2 py-1.5 text-[13px] text-[#334155] outline-none focus:border-[#2F6BFF]">
                <option value="d">derniers jours</option>
                <option value="m">derniers mois</option>
              </select>
            </div>
            {err && <p className="mt-1.5 text-[11.5px] text-[#C0392B]">{err}</p>}
            <button type="submit" disabled={!n} className={go}>
              Appliquer
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
