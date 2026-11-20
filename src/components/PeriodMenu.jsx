import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Loader2 } from 'lucide-react';
import {
  MAX_DAYS, MAX_MONTHS, PRESETS, periodLabel, rangeError, lastParts,
} from '../lib/period';
import {
  monthGrid, clickDay, selectionToken, selectionFromToken, tabFor, monthGroups,
  shiftMonth, canShift, startMonth, dayLabel, calendarMonths,
} from '../lib/periodCalendar';

/**
 * The period menu of the Tableau de bord and Analyses, made simpler
 * (user, 2026-11-21: « ekdm complicated feel hota hai »). Same choices as
 * before (2026-11-03), shown one group at a time behind three tabs:
 *   Rapide      the presets + « Les derniers N jours / mois »
 *   Mois        the 24 months as a grid — one click
 *   Calendrier  one month of days — one click is a day, a second click
 *               closes a du → au range — then Appliquer
 * The tokens, their labels and what the API reads live in lib/period.js;
 * the calendar's arithmetic in lib/periodCalendar.js. The previous menu is
 * kept, unimported, in PeriodMenuOld.jsx.
 */
export {
  MAX_DAYS, MAX_MONTHS, PRESETS, validPeriod, periodDays, periodLabel, periodParams, readPeriod, savePeriod,
} from '../lib/period';

const TABS = [
  { key: 'quick', label: 'Rapide' },
  { key: 'month', label: 'Mois' },
  { key: 'calendar', label: 'Calendrier' },
];
const WEEK = ['L', 'M', 'M', 'J', 'V', 'S', 'D'];
const NO_DAY = 'Choisissez un jour, ou deux pour une période.';

const go = 'rounded-lg bg-[#2F6BFF] px-3.5 py-1.5 text-[12.5px] font-semibold text-white transition hover:bg-[#2559DB] disabled:opacity-50';
const arrow = 'grid h-8 w-8 shrink-0 place-items-center rounded-lg text-[#475569] transition hover:bg-[#F1F5FB] disabled:cursor-not-allowed disabled:opacity-30';

export default function PeriodMenu({ value, onChange, busy = false, lead = false }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState(tabFor(value));
  const cur = lastParts(value);
  const [n, setN] = useState(cur && !cur.preset ? String(cur.n) : '');
  const [unit, setUnit] = useState(cur && !cur.preset ? cur.unit : 'd');
  const [err, setErr] = useState('');
  const [sel, setSel] = useState(selectionFromToken(value));
  const [view, setView] = useState(startMonth(value));
  const [calErr, setCalErr] = useState('');
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

  // every opening starts from the period on screen: its tab, its days, its month
  const toggle = () => {
    if (!open) {
      setTab(tabFor(value));
      setSel(selectionFromToken(value));
      setView(startMonth(value));
      setErr(''); setCalErr('');
    }
    setOpen((o) => !o);
  };

  const pick = (token) => { setOpen(false); setErr(''); setCalErr(''); if (token !== value) onChange(token); };

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

  const applyDays = (e) => {
    e.preventDefault();
    const token = selectionToken(sel);
    if (!token) { setCalErr(NO_DAY); return; }
    const why = rangeError(sel.from, sel.to || sel.from);
    if (why) { setCalErr(why); return; }
    pick(token);
  };

  const custom = cur && !cur.preset;
  const chosen = selectionToken(sel);
  const end = sel.to || sel.from;
  return (
    <div ref={box} className="relative">
      <button type="button" disabled={busy} onClick={toggle}
              aria-haspopup="dialog" aria-expanded={open} aria-label="Période analysée"
              className={`inline-flex items-center gap-2 rounded-xl border border-[#E6EEFB] bg-white font-medium text-[#334155] outline-none transition hover:border-[#BFD3FF] focus:border-[#2F6BFF] disabled:opacity-60 ${
                lead ? 'py-2.5 pl-3 pr-2.5 text-[13px] shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]'
                     : 'py-2 pl-3 pr-2 text-[12.5px]'}`}>
        {lead && <CalendarDays size={15} className="text-[#2F6BFF]" />}
        <span className="whitespace-nowrap">{periodLabel(value)}</span>
        {busy ? <Loader2 size={14} className="animate-spin text-[#2F6BFF]" />
              : <ChevronDown size={14} className={`text-[#94A3B8] transition ${open ? 'rotate-180' : ''}`} />}
      </button>

      {open && (
        <div role="dialog" aria-label="Choisir la période" ref={menu}
             className={`absolute ${side === 'left' ? 'left-0' : 'right-0'} z-30 mt-2 max-h-[min(80vh,600px)] w-[300px] max-w-[calc(100vw-24px)] overflow-y-auto overscroll-contain rounded-2xl border border-[#E6EEFB] bg-white p-3 text-left shadow-[0_24px_48px_-20px_rgba(11,28,63,.35)]`}>
          <div role="tablist" aria-label="Type de période" className="mb-3 grid grid-cols-3 gap-1 rounded-xl bg-[#F1F5FB] p-1">
            {TABS.map((t) => {
              const on = tab === t.key;
              return (
                <button key={t.key} type="button" role="tab" id={`period-tab-${t.key}`} aria-selected={on}
                        aria-controls={`period-panel-${t.key}`} onClick={() => setTab(t.key)}
                        className={`rounded-lg py-1.5 text-[12.5px] transition ${
                          on ? 'bg-white font-semibold text-[#0B1C3F] shadow-[0_1px_2px_rgba(11,28,63,.12)]'
                             : 'font-medium text-[#64748B] hover:text-[#0B1C3F]'}`}>
                  {t.label}
                </button>
              );
            })}
          </div>

          {tab === 'quick' && (
            <div role="tabpanel" id="period-panel-quick" aria-labelledby="period-tab-quick">
              <div className="grid grid-cols-2 gap-1.5">
                {PRESETS.map((p) => {
                  const on = value === p.key;
                  return (
                    <button key={p.key} type="button" aria-pressed={on} onClick={() => pick(p.key)}
                            className={`rounded-xl border px-2.5 py-2 text-left text-[12.5px] transition ${
                              on ? 'border-[#2F6BFF] bg-[#EAF1FF] font-semibold text-[#2F6BFF]'
                                 : 'border-[#E6EEFB] text-[#334155] hover:border-[#BFD3FF] hover:bg-[#F5F8FE]'}`}>
                      {p.label}
                    </button>
                  );
                })}
              </div>
              <form onSubmit={apply}
                    className={`mt-3 rounded-xl border p-2.5 ${custom ? 'border-[#2F6BFF] bg-[#F5F8FF]' : 'border-[#EEF3FB]'}`}>
                <p className={`mb-1.5 text-[12px] font-medium ${custom ? 'text-[#2F6BFF]' : 'text-[#64748B]'}`}>Les derniers …</p>
                <div className="flex items-center gap-1.5">
                  <input type="text" inputMode="numeric" autoComplete="off" value={n} placeholder="45"
                         aria-label="Nombre"
                         onChange={(e) => { setErr(''); setN(e.target.value.replace(/\D/g, '').replace(/^0+/, '').slice(0, 3)); }}
                         className="w-[58px] shrink-0 rounded-lg border border-[#E6EEFB] bg-white px-2 py-1.5 text-[13px] tabular-nums text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />
                  <select value={unit} onChange={(e) => { setErr(''); setUnit(e.target.value); }} aria-label="Unité"
                          className="min-w-0 flex-1 rounded-lg border border-[#E6EEFB] bg-white px-1.5 py-1.5 text-[13px] text-[#334155] outline-none focus:border-[#2F6BFF]">
                    <option value="d">jours</option>
                    <option value="m">mois</option>
                  </select>
                  <button type="submit" disabled={!n} className={`${go} shrink-0 px-2.5`}>Appliquer</button>
                </div>
                {err && <p className="mt-1.5 text-[11.5px] text-[#C0392B]">{err}</p>}
              </form>
            </div>
          )}

          {tab === 'month' && (
            <div role="tabpanel" id="period-panel-month" aria-labelledby="period-tab-month" className="space-y-3">
              {monthGroups().map((g) => (
                <div key={g.year}>
                  <p className="mb-1.5 text-[11.5px] font-semibold text-[#94A3B8]">{g.year}</p>
                  <div className="grid grid-cols-4 gap-1">
                    {g.months.map((m) => {
                      const on = value === m.key;
                      return (
                        <button key={m.key} type="button" aria-label={m.label} aria-pressed={on} disabled={m.disabled}
                                title={m.current ? `${m.label} (en cours)` : m.label} onClick={() => pick(m.key)}
                                className={`relative rounded-lg py-2 text-[12.5px] transition disabled:cursor-not-allowed disabled:text-[#CBD5E1] ${
                                  on ? 'bg-[#2F6BFF] font-semibold text-white'
                                     : 'text-[#334155] hover:bg-[#F1F5FB] disabled:hover:bg-transparent'}`}>
                          {m.short}
                          {m.current && !on && <span aria-hidden="true" className="absolute bottom-1 left-1/2 h-1 w-1 -translate-x-1/2 rounded-full bg-[#2F6BFF]" />}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === 'calendar' && (
            <form role="tabpanel" id="period-panel-calendar" aria-labelledby="period-tab-calendar" onSubmit={applyDays}>
              <div className="mb-2 flex items-center gap-1">
                <button type="button" aria-label="Mois précédent" disabled={!canShift(view, -1)}
                        onClick={() => setView(shiftMonth(view, -1))} className={arrow}><ChevronLeft size={16} /></button>
                <select aria-label="Mois affiché" value={view} onChange={(e) => setView(e.target.value)}
                        className="min-w-0 flex-1 cursor-pointer appearance-none rounded-lg bg-transparent px-1 py-1 text-center text-[13.5px] font-semibold text-[#0B1C3F] outline-none hover:bg-[#F1F5FB] focus:bg-[#F1F5FB]">
                  {calendarMonths().map((m) => <option key={m.ym} value={m.ym}>{m.label}</option>)}
                </select>
                <button type="button" aria-label="Mois suivant" disabled={!canShift(view, 1)}
                        onClick={() => setView(shiftMonth(view, 1))} className={arrow}><ChevronRight size={16} /></button>
              </div>
              <div className="grid grid-cols-7 text-center text-[11px] font-semibold text-[#94A3B8]" aria-hidden="true">
                {WEEK.map((d, i) => <span key={i} className="py-1">{d}</span>)}
              </div>
              <div className="grid grid-cols-7 gap-y-0.5">
                {monthGrid(view).flat().map((c, i) => {
                  if (!c) return <span key={`b${i}`} />;
                  const edge = c.date === sel.from || c.date === end;
                  const inside = sel.from && end && c.date > sel.from && c.date < end;
                  return (
                    <button key={c.date} type="button" aria-label={dayLabel(c.date)} aria-pressed={!!(sel.from && edge)}
                            disabled={c.disabled} onClick={() => { setCalErr(''); setSel((s) => clickDay(s, c.date)); }}
                            className={`h-9 text-[12.5px] tabular-nums transition disabled:cursor-not-allowed disabled:text-[#CBD5E1] ${
                              sel.from && edge ? 'rounded-lg bg-[#2F6BFF] font-semibold text-white'
                                : inside ? 'bg-[#EAF1FF] text-[#2F6BFF]'
                                  : `rounded-lg text-[#334155] hover:bg-[#F1F5FB] disabled:hover:bg-transparent ${c.today ? 'font-semibold ring-1 ring-inset ring-[#BFD3FF]' : ''}`}`}>
                      {c.day}
                    </button>
                  );
                })}
              </div>
              <div className="mt-3 flex items-center justify-between gap-2 border-t border-[#EEF3FB] pt-2.5">
                <p className="min-w-0 text-[12px] leading-snug text-[#64748B]" aria-live="polite">
                  {chosen ? <span className="font-semibold text-[#0B1C3F]">{periodLabel(chosen)}</span>
                          : 'Un clic : un jour. Deux clics : du … au …'}
                </p>
                <button type="submit" className={`${go} shrink-0`}>Appliquer</button>
              </div>
              {calErr && <p className="mt-1.5 text-[11.5px] text-[#C0392B]">{calErr}</p>}
            </form>
          )}
        </div>
      )}
    </div>
  );
}
