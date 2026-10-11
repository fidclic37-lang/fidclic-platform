import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft, ArrowRight, Check, Pencil, Info, CalendarDays, CalendarClock, Clock, Users, UserX, User, Star, MapPin,
  BarChart3, Lightbulb, Loader2, Settings2, MessageSquare, PieChart, Link2, Image as ImageIcon, Eye, Globe, Tag,
  Store, Filter, CheckCircle2, X, Search, Plus, ShoppingCart, Gift, UserPlus, Trophy, Footprints, Sparkles, Repeat,
  Cake, Smartphone, BookOpen, ChevronDown, ChevronUp, Euro, Target, Send,
} from 'lucide-react';
import { ownerAPI } from '../../lib/api';
import LockScreenPreview from './LockScreenPreview';
import GeoZoneMap from './GeoZoneMap';
import { EMOJIS } from '../campagnes/kinds';

/**
 * « Nouvelle automatisation » — the user's 29 mockups (2026-10-11): the
 * owner's own automation, apart from the saved scenarios. Six steps:
 * Configuration · Déclencheur (7 kinds) · Message · Ciblage · Planification
 * then Règles d'envoi (step 5, the date/récurrence being the same data as
 * step 2) · Résumé. The engine is api/features/custom_rules.py.
 */

const TITLE_MAX = 80;
const BODY_MAX = 350;
const BUTTON_MAX = 30;
const DESC_MAX = 300;
const NOTE_MAX = 500;
const HOURS = Array.from({ length: 48 }, (_, i) => `${String(Math.floor(i / 2)).padStart(2, '0')}:${i % 2 ? '30' : '00'}`);
const field = 'w-full rounded-xl border border-[#D9E2F2] bg-white px-3.5 py-2.5 !text-[15px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF] focus:ring-2 focus:ring-[#2F6BFF]/15 disabled:bg-[#F8FAFC] disabled:text-[#94A3B8]';
const LINK_RE = /^https?:\/\/[^\s/?#]+\.[^\s/?#]{2,}(?:[/?#]\S*)?$/i;
const DAYS = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];
const DAY_FULL = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche'];
const MONTHS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
const TIMEZONES = [
  ['Europe/Paris', 'Paris'], ['Europe/Brussels', 'Bruxelles'], ['Europe/Luxembourg', 'Luxembourg'], ['Europe/Zurich', 'Genève / Zurich'],
  ['Europe/Monaco', 'Monaco'], ['Europe/London', 'Londres'], ['America/Guadeloupe', 'Guadeloupe'], ['America/Martinique', 'Martinique'],
  ['America/Cayenne', 'Guyane'], ['Indian/Reunion', 'La Réunion'], ['Indian/Mayotte', 'Mayotte'], ['America/Miquelon', 'Saint-Pierre-et-Miquelon'],
  ['Pacific/Noumea', 'Nouvelle-Calédonie'], ['Pacific/Tahiti', 'Polynésie française'], ['Pacific/Wallis', 'Wallis-et-Futuna'], ['America/Montreal', 'Montréal'],
];
const STEPS = ['Configuration', 'Déclencheur', 'Message', 'Ciblage', null, 'Résumé'];

const TRIGGERS = [
  { key: 'on_date', title: 'Date spécifique', sub: 'Envoyez la notification à une date précise (ex. offre limitée, événement spécial).', icon: CalendarDays, tone: ['#FEE2E2', '#E11D48'] },
  { key: 'recurring', title: 'Récurrent', sub: 'Répétez automatiquement la notification (ex. chaque semaine, chaque mois).', icon: CalendarClock, tone: ['#DBEAFE', '#2563EB'] },
  { key: 'action', title: 'Après une action client', sub: 'Déclenchez la notification après une visite, un achat ou une autre action.', icon: Clock, tone: ['#FFEDD5', '#EA580C'] },
  { key: 'loyalty', title: 'Conditions sur la fidélité', sub: "Déclenchez la notification selon les points, le nombre de visites ou le montant d'achats.", icon: BarChart3, tone: ['#F3E8FF', '#9333EA'] },
  { key: 'behavior', title: 'Comportement client', sub: "Envoyez la notification selon l'activité ou l'inactivité du client.", icon: User, tone: ['#DCFCE7', '#16A34A'] },
  { key: 'geo', title: 'Géolocalisation', sub: 'Déclenchez la notification lorsque le client entre dans une zone définie.', icon: MapPin, tone: ['#FFE4E6', '#E11D48'] },
  { key: 'other', title: 'Autre', sub: 'Règle personnalisée selon vos besoins.', icon: Star, tone: ['#EDE9FE', '#7C3AED'] },
];
const TRIGGER = Object.fromEntries(TRIGGERS.map((t) => [t.key, t]));
const ACTIONS = [['purchase', 'Achat effectué', ShoppingCart], ['visit', 'Visite en magasin', Store],
  ['signup', 'Inscription au programme de fidélité', UserPlus], ['offer_used', "Utilisation d'une offre", Gift],
  ['tier_reached', "Atteinte d'un palier de points", Trophy]];
const ACTION_LABEL = Object.fromEntries(ACTIONS.map(([k, l]) => [k, l]));
const OTHER_EVENTS = [['visit', 'Visite'], ['purchase', 'Achat'], ['inactivity', 'Inactivité client'], ['signup', 'Inscription']];
const OTHER_RULES = {
  visits_in_days: ['visit', 'X visites en Y jours'], days_after_first_visit: ['visit', 'X jours après la 1re visite'],
  spent_in_days: ['purchase', 'X € dépensés en Y jours'], no_visit_days: ['inactivity', 'Dernière visite il y a plus de X jours'],
  signup_anniversary: ['signup', "Anniversaire d'inscription"],
};
const PICKS = [
  { key: 'all', title: 'Tous les clients', sub: 'Envoyer la notification à tous vos clients.', icon: Users, tone: ['#DBEAFE', '#2563EB'] },
  { key: 'active', title: 'Clients actifs uniquement', sub: 'Uniquement les clients ayant été actifs récemment.', icon: User, tone: ['#DCFCE7', '#16A34A'] },
  { key: 'inactive', title: 'Clients inactifs', sub: "Clients n'ayant pas visité depuis une certaine période.", icon: UserX, tone: ['#FFE4E6', '#E11D48'] },
  { key: 'points', title: 'Clients avec un nombre de points', sub: 'Clients ayant un nombre de points spécifique.', icon: Star, tone: ['#F3E8FF', '#9333EA'] },
  { key: 'segment', title: "Clients d'un segment", sub: 'Sélectionnez un ou plusieurs segments de clients.', icon: Tag, tone: ['#DBEAFE', '#2563EB'] },
  { key: 'stores', title: "Clients d'un établissement", sub: "Ciblez les clients d'un ou plusieurs établissements.", icon: Store, tone: ['#FFEDD5', '#EA580C'] },
];
const LIMITS = [['trigger', 'Pas de limite (1 par déclenchement)'], ['day', '1 fois par jour'], ['week', '1 fois par semaine'],
  ['month', '1 fois par mois'], ['ever', '1 seule fois au total']];
const GAPS = [1, 3, 7, 14, 15, 30, 60, 90];
const VARS = ['prénom', 'nom', 'points', 'récompense', 'nom_commerce', 'date', 'montant', 'nombre_visites'];
const LINKS = [['card', 'La carte du client'], ['rewards', 'Page Récompenses'], ['offer', 'Une de vos offres'], ['google_review', 'Votre fiche Google'], ['url', 'Un lien personnalisé']];

// ---- small pieces (the editor's look) ------------------------------------------------
const Toggle = ({ on, onChange, label, disabled }) => (
  <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)}
          className={`relative h-7 w-12 shrink-0 rounded-full transition disabled:opacity-50 ${on ? 'bg-[#2F6BFF]' : 'bg-[#D6DEEA]'}`}>
    <span className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition ${on ? 'left-6' : 'left-1'}`} />
  </button>
);
const Label = ({ children, req, right, hint }) => (
  <span className="mb-1.5 flex items-center justify-between gap-2 text-[13.5px] font-semibold text-[#0B1C3F]">
    <span className="flex items-center gap-1">{children}{req && <span className="text-[#E11D48]">*</span>}
      {hint && <span title={hint}><Info size={14} className="text-[#64748B]" /></span>}</span>
    {right && <span className="text-[11.5px] font-normal text-[#64748B]">{right}</span>}
  </span>
);
const Help = ({ children }) => <span className="mt-1 block text-[11.5px] text-[#64748B]">{children}</span>;
function Select({ value, onChange, options, label, disabled, icon: I }) {
  return (
    <span className="relative block">
      {I && <I size={17} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[#475569]" />}
      <select aria-label={label} value={value ?? ''} disabled={disabled} onChange={(e) => onChange(e.target.value)}
              className={`${field} appearance-none bg-[length:14px] bg-[right_12px_center] bg-no-repeat pr-9 ${I ? '!pl-10' : ''}`}
              style={{ backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%230B1C3F' stroke-width='2.5'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")" }}>
        {options.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </select>
    </span>
  );
}
function Num({ value, onChange, label, max = 100000, unit, disabled, decimal }) {
  return (
    <span className={`flex items-stretch overflow-hidden rounded-xl border border-[#D9E2F2] bg-white focus-within:border-[#2F6BFF] ${disabled ? 'opacity-60' : ''}`}>
      <input inputMode={decimal ? 'decimal' : 'numeric'} aria-label={label} disabled={disabled} value={value ?? ''}
             onChange={(e) => {
               const raw = decimal ? e.target.value.replace(',', '.').replace(/[^\d.]/g, '') : e.target.value.replace(/\D/g, '');
               onChange(raw === '' ? '' : (Number(raw) > max ? String(max) : raw));
             }}
             className="w-full min-w-0 bg-transparent px-3.5 py-2.5 text-[15px] text-[#0B1C3F] outline-none" />
      {unit && <span className="flex items-center border-l border-[#E2E8F0] bg-[#F8FAFC] px-3 text-[13px] text-[#64748B]">{unit}</span>}
    </span>
  );
}
function Panel({ title, icon: I = Info, tone = '#1463FF', children, action }) {
  return (
    <section className="rounded-2xl border border-[#E6EEFB] bg-[#F7FAFF] p-4">
      <div className="mb-2 flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-white" style={{ background: tone }}><I size={18} /></span>
        <p className="min-w-0 flex-1 pt-1.5 text-[15px] font-bold text-[#0B1C3F]">{title}</p>{action}
      </div>
      <div className="space-y-2 pl-12 text-[13px] leading-relaxed text-[#475569]">{children}</div>
    </section>
  );
}
const Ticks = ({ items }) => (
  <ul className="space-y-2">{items.map((x) => <li key={x} className="flex gap-2"><Check size={16} className="mt-0.5 shrink-0 text-[#1463FF]" /><span>{x}</span></li>)}</ul>
);
const Good = ({ title = 'Bon à savoir', icon: I = CalendarDays, children }) => (
  <div className="mt-3 flex gap-3 rounded-xl bg-[#EEF4FF] p-3 text-[12.5px] text-[#334155]"><I size={20} className="shrink-0 text-[#1463FF]" />
    <span><b className="block text-[#1463FF]">{title}</b>{children}</span></div>
);

const FilterRow = ({ on, onToggle, icon: I, title, children }) => (
  <div className="flex items-start gap-3 rounded-xl border border-[#EEF2F8] p-3">
    <Toggle label={title} on={Boolean(on)} onChange={onToggle} />
    <span className="min-w-0 flex-1">
      <span className="mb-2 flex items-center gap-2 text-[13.5px] font-semibold text-[#0B1C3F]"><I size={17} className="text-[#1463FF]" />{title}</span>
      <span className={`flex flex-wrap items-center gap-2 text-[13px] text-[#334155] ${on ? '' : 'pointer-events-none opacity-50'}`}>{children}</span>
    </span>
  </div>
);

const ResRow = ({ icon: I, tone, title, children, onEdit }) => (
  <div className="flex items-start gap-4 rounded-2xl border border-[#E6EEFB] bg-white p-3.5">
    <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl" style={{ background: tone[0], color: tone[1] }}><I size={22} /></span>
    <span className="min-w-0 flex-1"><span className="block text-[15px] font-bold text-[#0B1C3F]">{title}</span>{children}</span>
    {onEdit && <button type="button" onClick={onEdit} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[#EEF4FF] px-3 py-1.5 text-[13px] font-semibold text-[#1463FF]"><Pencil size={13} /> Modifier</button>}
  </div>
);

const Boxes = ({ items }) => (
  <span className="mt-2 grid gap-2 sm:grid-cols-3">{items.map(([l, v]) => (
    <span key={l} className="rounded-xl border border-[#E6EEFB] bg-white px-3 py-2"><span className="block text-[11px] text-[#64748B]">{l}</span><span className="block text-[13.5px] font-bold text-[#0B1C3F]">{v || '—'}</span></span>
  ))}</span>
);

const ConfigHead = ({ icon: I, tone, title, sub }) => (
  <div className="mb-4 flex items-start gap-3">
    {I && <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl" style={{ background: tone?.[0] || '#EEF4FF', color: tone?.[1] || '#1463FF' }}><I size={22} /></span>}
    <span><span className="block text-[17px] font-extrabold text-[#0B1C3F]">{title}</span>{sub && <span className="text-[13px] text-[#475569]">{sub}</span>}</span>
  </div>
);

// ---- dates ---------------------------------------------------------------------------
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const parse = (s) => { const [y, m, d] = String(s || '').slice(0, 10).split('-').map(Number); return y ? new Date(y, m - 1, d) : null; };
const frDate = (s, withDay) => {
  const d = parse(s);
  if (!d) return '—';
  const base = `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  return withDay ? `${DAY_FULL[(d.getDay() + 6) % 7]} ${base}` : base;
};
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
const tzOffset = (k) => {
  try {
    const v = new Intl.DateTimeFormat('en-US', { timeZone: k, timeZoneName: 'shortOffset' }).formatToParts(new Date()).find((p) => p.type === 'timeZoneName')?.value || 'GMT';
    const m = v.match(/GMT([+-])(\d{1,2})(?::(\d{2}))?/);
    return m ? `UTC${m[1]}${m[2].padStart(2, '0')}:${m[3] || '00'}` : 'UTC+00:00';
  } catch { return 'UTC'; }
};
const TZ_OPTIONS = TIMEZONES.map(([k, l]) => [k, `(${tzOffset(k)}) ${l}`]);
const todayIn = (tz) => {
  try { return new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()); } catch { return iso(new Date()); }
};
const lastDay = (d) => new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
const perMonthDays = (d, n) => [...new Set(Array.from({ length: n }, (_, i) => 1 + Math.floor((i * lastDay(d)) / n)))];

/** The shop-wide dates a time déclencheur sends on (as custom_rules.date_due). */
function dueOn(tr, sched, d) {
  if (tr.type === 'on_date') return tr.date === iso(d);
  if (tr.type !== 'recurring') return false;
  const anchor = parse(sched.valid_from) || parse(todayIn(sched.tz));
  if (tr.period === 'weekly') {
    const wd = (d.getDay() + 6) % 7;
    if (!(tr.weekdays || []).includes(wd)) return false;
    const mon = (x) => { const y = new Date(x); y.setDate(y.getDate() - ((y.getDay() + 6) % 7)); return y; };
    const weeks = Math.round((mon(d) - mon(anchor)) / (7 * 864e5));
    return weeks >= 0 && weeks % Math.max(1, Number(tr.every_weeks) || 1) === 0;
  }
  if (tr.period === 'monthly') return (tr.monthdays || []).some((x) => Math.min(Number(x), lastDay(d)) === d.getDate());
  if (tr.period === 'yearly') {
    if ((tr.date_kind || 'fixed') !== 'fixed' || !tr.date) return false;
    const [, mm, dd] = tr.date.split('-').map(Number);
    return d.getMonth() + 1 === mm && (d.getDate() === dd || (mm === 2 && dd === 29 && d.getDate() === 28 && lastDay(d) === 28));
  }
  if (tr.period === 'custom') {
    if (tr.workdays_only && ((d.getDay() + 6) % 7) >= 5) return false;
    if (tr.rule === 'per_month') return perMonthDays(d, Number(tr.per_month) || 1).includes(d.getDate());
    const diff = Math.round((d - anchor) / 864e5);
    return diff >= 0 && diff % Math.max(1, Number(tr.every_days) || 1) === 0;
  }
  return false;
}
function nextDates(tr, sched, n = 5) {
  const out = [];
  const start = parse(todayIn(sched.tz));
  const from = parse(sched.valid_from);
  let d = from && from > start ? new Date(from) : new Date(start);
  for (let i = 0; i < 800 && out.length < n; i += 1) {
    if (sched.valid_to && iso(d) > sched.valid_to) break;
    if (dueOn(tr, sched, d)) { out.push(iso(d)); if (tr.type === 'on_date') break; }
    d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1);
  }
  return out;
}

// ---- the automation as the editor holds it ---------------------------------------------
const EMPTY_FILTERS = { points_min: '', points_max: '', spent_min: '', spent_max: '', last_visit_op: 'more', last_visit_days: '', age_min: '', age_max: '', stores: [] };
const BUTTON = { enabled: false, label: 'En savoir plus', link_type: 'card', offer_id: '', url: '' };
const TRIGGER_DEFAULTS = {
  on_date: () => ({ type: 'on_date', date: '' }),
  recurring: () => ({ type: 'recurring', period: 'weekly', every_weeks: 1, weekdays: [0], monthdays: [1], date_kind: 'fixed', date: iso(new Date()), reminder: { enabled: false, days_before: 7 }, rule: 'every_days', every_days: '10', per_month: '2', workdays_only: false }),
  action: () => ({ type: 'action', action: 'purchase', delay_value: '1', delay_unit: 'days', repeat: 'once', every_days: '30', criteria: { enabled: false, min_amount: '', stores: [], offer_id: '' } }),
  loyalty: () => ({ type: 'loyalty', match: 'any', repeat: 'once', points: '500', visits: '5', amount: '200' }),
  behavior: () => ({ type: 'behavior', client_status: 'existing', activity: 'inactive', value: '30', unit: 'days', segment: '' }),
  geo: () => ({ type: 'geo', address: '', lat: null, lng: null, radius_m: 300, days: 'all', from: '09:00', to: '22:00', new_only: false }),
  other: () => ({ type: 'other', rule_name: '', event: 'visit', rule: 'visits_in_days', x: '3', y: '60', delay_days: '0', notes: '' }),
};
const fresh = () => ({
  name: '', description: '', status: 'active',
  trigger: TRIGGER_DEFAULTS.on_date(),
  message: { title: '', body: '', image_url: null, button: { ...BUTTON } },
  message_reminder: { title: '', body: '', image_url: null, button: { ...BUTTON } },
  targeting: { pick: 'all', inactive_days: '30', segment: '', filters: { ...EMPTY_FILTERS }, on: {} },
  schedule: { tz: 'Europe/Paris', hour: '09:00', window: true, window_from: '09:00', window_to: '20:00', send_mode: 'immediate', send_at: '',
    limit: { count: 1, per: 'trigger' }, dedupe: true, min_gap_days: 7, valid_from: '', valid_to: '', rules_note: '', expire: false, period: false },
});
/** An older « Personnalisée » (visits, after_signup, after_visit, date) shown as its new déclencheur. */
function fromLegacy(tr) {
  if (tr.type === 'visits') return { ...TRIGGER_DEFAULTS.loyalty(), points: '', amount: '', visits: String(tr.visits || 5), repeat: tr.visits_repeat === 'every' ? 'each' : 'once' };
  if (tr.type === 'after_signup') return { ...TRIGGER_DEFAULTS.action(), action: 'signup', delay_value: String(tr.delay_value ?? 0), delay_unit: tr.delay_unit || 'days' };
  if (tr.type === 'after_visit') {
    return { ...TRIGGER_DEFAULTS.action(), action: 'visit', delay_value: String(tr.delay_value ?? 0), delay_unit: tr.delay_unit || 'hours',
      repeat: Number(tr.cooldown_days) ? 'gap' : 'every', every_days: String(tr.cooldown_days || 30) };
  }
  if (tr.type === 'date') {
    const m = tr.date_mode || 'once';
    if (m === 'once') return { ...TRIGGER_DEFAULTS.on_date(), date: tr.date || '' };
    const r = TRIGGER_DEFAULTS.recurring();
    if (m === 'weekly') return { ...r, period: 'weekly', weekdays: [Number(tr.weekday) || 0] };
    if (m === 'monthly') return { ...r, period: 'monthly', monthdays: [Number(tr.monthday) || 1] };
    return { ...r, period: 'yearly', date_kind: 'fixed', date: tr.date || '' };
  }
  return null;
}
function load(row) {
  const f = fresh();
  if (!row) return f;
  const tr0 = row.trigger || {};
  const legacy = fromLegacy(tr0);
  const tr = legacy || { ...TRIGGER_DEFAULTS[tr0.type]?.(), ...tr0 };
  const str = (v) => (v === null || v === undefined ? '' : String(v));
  ['every_days', 'per_month', 'delay_value', 'value', 'x', 'y', 'delay_days', 'points', 'visits', 'amount'].forEach((k) => { if (k in tr) tr[k] = str(tr[k]); });
  if (tr.type === 'action') tr.criteria = { enabled: false, min_amount: '', stores: [], offer_id: '', ...(tr.criteria || {}), min_amount: str(tr.criteria?.min_amount) };
  if (tr.type === 'recurring') tr.reminder = { enabled: false, days_before: 7, ...(tr.reminder || {}) };
  if (tr.type === 'behavior') tr.segment = tr.segment || '';
  const s = row.schedule || {};
  const tg = row.targeting || {};
  const fl = tg.filters || {};
  const btn = (m) => ({ ...BUTTON, ...(m?.button || {}), url: m?.button?.url || '', offer_id: m?.button?.offer_id || '' });
  return {
    name: row.name || '', description: row.description || '', status: row.status === 'ended' ? 'active' : (row.status || 'active'),
    trigger: tr,
    message: { ...f.message, ...(row.message || {}), button: btn(row.message) },
    message_reminder: { ...f.message_reminder, ...(row.message_reminder || {}), button: btn(row.message_reminder) },
    targeting: {
      pick: tg.pick || (tg.mode === 'segment' ? 'segment' : 'all'), inactive_days: str(tg.inactive_days || 30), segment: tg.segment || '',
      filters: { ...EMPTY_FILTERS, ...Object.fromEntries(Object.entries(fl).filter(([k]) => k in EMPTY_FILTERS).map(([k, v]) => [k, Array.isArray(v) ? v : str(v)])),
        last_visit_op: fl.last_visit_op || 'more', stores: fl.stores || [] },
      on: { age: fl.age_min != null || fl.age_max != null, points: tg.pick !== 'points' && (fl.points_min != null || fl.points_max != null),
        last: tg.pick !== 'inactive' && fl.last_visit_days != null, spent: fl.spent_min != null || fl.spent_max != null },
    },
    schedule: { ...f.schedule, ...s, tz: s.tz || 'Europe/Paris', hour: s.hour || f.schedule.hour, send_at: s.send_at || '',
      limit: { count: 1, per: 'trigger', ...(s.limit || {}) }, dedupe: Boolean(s.dedupe), min_gap_days: s.min_gap_days || 7,
      valid_from: s.valid_from || '', valid_to: s.valid_to || '', rules_note: s.rules_note || '',
      expire: Boolean(s.valid_to), period: Boolean(s.valid_from || s.valid_to) },
  };
}

// ---- the texts the Résumé / panels read --------------------------------------------------
const timed = (tr) => ['on_date', 'recurring', 'behavior'].includes(tr.type) || (tr.type === 'other' && ['no_visit_days', 'signup_anniversary', 'days_after_first_visit'].includes(tr.rule));
const hasDate = (tr) => ['on_date', 'recurring'].includes(tr.type);
function recurrenceText(tr, sc) {
  const h = sc.hour;
  if (tr.type === 'on_date') return `Le ${frDate(tr.date, true)} à ${h}`;
  if (tr.period === 'weekly') {
    const k = Number(tr.every_weeks) || 1;
    return `${k === 1 ? 'Chaque semaine' : `Toutes les ${k} semaines`} · ${(tr.weekdays || []).map((d) => DAY_FULL[d]).join(', ') || '—'} à ${h}`;
  }
  if (tr.period === 'monthly') return `Chaque mois · ${(tr.monthdays || []).map((d) => (Number(d) === 1 ? 'le 1er' : `le ${d}`)).join(' et ')} à ${h}`;
  if (tr.period === 'yearly') {
    const k = tr.date_kind || 'fixed';
    const what = k === 'birthday' ? "à l'anniversaire du client" : k === 'signup' ? "à l'anniversaire d'inscription"
      : tr.date ? `le ${Number(tr.date.slice(8, 10))} ${MONTHS[Number(tr.date.slice(5, 7)) - 1]}` : '—';
    return `Chaque année · ${what} à ${h}${tr.reminder?.enabled ? ` · rappel ${tr.reminder.days_before} j avant` : ''}`;
  }
  const base = tr.rule === 'per_month' ? `${tr.per_month} fois par mois` : `Tous les ${tr.every_days} jours`;
  return `${base} à ${h}${tr.workdays_only ? ' · jours ouvrés' : ''}`;
}

export default function NouvelleEditor({ page, row, ai, onReload }) {
  const navigate = useNavigate();
  const editing = Boolean(row);
  const [s, setS] = useState(() => {
    const d = load(row);
    if (!row && ai?.title) {
      d.message = { ...d.message, title: ai.title.slice(0, TITLE_MAX), body: (ai.body || '').slice(0, BODY_MAX) };
      d.name = ai.title.replace(/\{[^}]*\}/g, '').replace(/\s+/g, ' ').trim().slice(0, 60);
    }
    return d;
  });
  const [step, setStep] = useState(1);
  const [sub5, setSub5] = useState('plan');           // step 5: Planification, then Règles d'envoi
  const [msgTab, setMsgTab] = useState('main');       // Message principal / Rappel (Annuelle)
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [preview, setPreview] = useState(null);
  const [listOpen, setListOpen] = useState(false);
  const [emoji, setEmoji] = useState(false);
  const [adv, setAdv] = useState(true);               // Planification › Options avancées
  const [activate, setActivate] = useState(row ? row.status !== 'paused' && row.status !== 'draft' : true);
  const [addr, setAddr] = useState({ q: row?.trigger?.address || '', results: [], open: false, busy: false });
  const titleRef = useRef(null);
  const bodyRef = useRef(null);
  const fileRef = useRef(null);
  const lastFocus = useRef('body');
  const can = Boolean(page.can_edit);
  const tr = s.trigger;
  const sc = s.schedule;
  const tg = s.targeting;
  const rem = tr.type === 'recurring' && tr.period === 'yearly' && tr.reminder?.enabled;
  const cur = msgTab === 'rem' && rem ? s.message_reminder : s.message;
  const msgKey = msgTab === 'rem' && rem ? 'message_reminder' : 'message';

  const set = (patch) => setS((o) => ({ ...o, ...patch }));
  const setT = (patch) => setS((o) => ({ ...o, trigger: { ...o.trigger, ...patch } }));
  const setSc = (patch) => setS((o) => ({ ...o, schedule: { ...o.schedule, ...patch } }));
  const setTg = (patch) => setS((o) => ({ ...o, targeting: { ...o.targeting, ...patch } }));
  const setF = (patch) => setS((o) => ({ ...o, targeting: { ...o.targeting, filters: { ...o.targeting.filters, ...patch } } }));
  const setOn = (k, v) => setS((o) => ({ ...o, targeting: { ...o.targeting, on: { ...o.targeting.on, [k]: v } } }));
  const setCur = (patch) => setS((o) => ({ ...o, [msgKey]: { ...o[msgKey], ...patch } }));
  const setBtn = (patch) => setS((o) => ({ ...o, [msgKey]: { ...o[msgKey], button: { ...o[msgKey].button, ...patch } } }));
  const pickTrigger = (k) => { if (k !== tr.type) setT({ ...TRIGGER_DEFAULTS[k]() }); };

  // the targeting the server reads (the chosen card + the filters switched on)
  const targetingOut = useMemo(() => {
    const f = tg.filters;
    const on = tg.on || {};
    const out = {};
    if (on.age || false) { out.age_min = f.age_min; out.age_max = f.age_max; }
    if (on.points || tg.pick === 'points') { out.points_min = f.points_min; out.points_max = f.points_max; }
    if (on.last) { out.last_visit_op = f.last_visit_op; out.last_visit_days = f.last_visit_days; }
    if (on.spent) { out.spent_min = f.spent_min; out.spent_max = f.spent_max; }
    if (tg.pick === 'stores') out.stores = f.stores;
    const clean = Object.fromEntries(Object.entries(out).map(([k, v]) => [k, v === '' ? null : v]));
    return { mode: tg.pick === 'segment' ? 'segment' : 'filtered', pick: tg.pick, segment: tg.pick === 'segment' ? tg.segment : null,
      inactive_days: tg.pick === 'inactive' ? Number(tg.inactive_days) || 30 : null, filters: clean };
  }, [tg]);

  // « Aperçu du ciblage », live
  const tKey = JSON.stringify(targetingOut);
  useEffect(() => {
    let alive = true;
    const t0 = setTimeout(() => {
      ownerAPI.automationPreview({ scenario: 'custom', targeting: targetingOut, full: listOpen })
        .then(({ data }) => { if (alive) setPreview(data); }).catch(() => { if (alive) setPreview(null); });
    }, 250);
    return () => { alive = false; clearTimeout(t0); };
  }, [tKey, listOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  // « Adresse ou établissement »
  useEffect(() => {
    if (!addr.open) return undefined;
    let alive = true;
    const t0 = setTimeout(() => {
      setAddr((a) => ({ ...a, busy: true }));
      ownerAPI.automationAddress(addr.q).then(({ data }) => { if (alive) setAddr((a) => ({ ...a, results: data.results || [], busy: false })); })
        .catch((e) => { if (alive) setAddr((a) => ({ ...a, results: [], busy: false, err: e?.response?.data?.detail })); });
    }, 300);
    return () => { alive = false; clearTimeout(t0); };
  }, [addr.q, addr.open]);

  const sample = preview?.sample;
  const tpl = page.near || {};
  const extra = {
    'récompense': sample?.next_reward || 'votre récompense', date: (() => { const d = new Date(); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; })(),
    montant: '86,50 €', nombre_visites: String(sample?.visits ?? 5),
    offre: tr.action === 'offer_used' ? ((page.offers || []).find((o) => o.id === tr.criteria?.offer_id)?.name || 'votre offre') : 'notre offre du moment',
    palier: 'Argent',
  };
  void tpl;

  // ---- checks (as the server) --------------------------------------------------------
  const today = todayIn(sc.tz);
  const problems = (n) => {
    const out = [];
    if (n === 1 && !s.name.trim()) out.push("Donnez un nom à l'automatisation.");
    if (n === 1 && s.description.length > DESC_MAX) out.push(`Description : ${DESC_MAX} caractères au maximum.`);
    if (n === 2) {
      if (tr.type === 'on_date' && !tr.date) out.push("Choisissez la date d'envoi.");
      if (tr.type === 'on_date' && tr.date && tr.date < today) out.push('Cette date est déjà passée.');
      if (tr.type === 'recurring' && tr.period === 'weekly' && !(tr.weekdays || []).length) out.push("Cochez au moins un jour d'envoi.");
      if (tr.type === 'recurring' && tr.period === 'yearly' && (tr.date_kind || 'fixed') === 'fixed' && !tr.date) out.push("Choisissez la date d'envoi.");
      if (tr.type === 'recurring' && tr.period === 'custom' && !(Number(tr.rule === 'per_month' ? tr.per_month : tr.every_days) > 0)) out.push('Indiquez la règle personnalisée.');
      if (tr.type === 'loyalty' && !['points', 'visits', 'amount'].some((k) => Number(tr[k]) > 0)) out.push('Indiquez au moins une condition : points, visites ou montant.');
      if (tr.type === 'geo' && tr.lat == null) out.push('Choisissez une adresse ou un établissement.');
      if (tr.type === 'geo' && tr.to <= tr.from) out.push("La fin de la plage d'activation doit être après son début.");
      if (tr.type === 'other' && !tr.rule_name.trim()) out.push('Donnez un nom à la règle.');
      if (tr.type === 'other' && (tr.notes || '').length > NOTE_MAX) out.push('Notes internes : 500 caractères au maximum.');
      if (tr.type === 'behavior' && !(Number(tr.value) > 0)) out.push('Indiquez le délai depuis la dernière visite.');
    }
    if (n === 3) {
      [['message', 'Message'], ...(rem ? [['message_reminder', 'Rappel']] : [])].forEach(([k, who]) => {
        const m = s[k];
        if (!m.title.trim() || !m.body.trim()) out.push(`${who} : le titre et le message sont obligatoires.`);
        if (m.button.enabled && !m.button.label.trim()) out.push(`${who} : écrivez le texte du bouton.`);
        if (m.button.enabled && m.button.link_type === 'url' && !LINK_RE.test(m.button.url.startsWith('http') ? m.button.url : `https://${m.button.url}`)) out.push(`${who} : le lien du bouton est invalide.`);
        if (m.button.enabled && m.button.link_type === 'offer' && !m.button.offer_id) out.push(`${who} : choisissez l'offre du bouton.`);
      });
    }
    if (n === 4) {
      if (tg.pick === 'segment' && !tg.segment) out.push('Choisissez un segment.');
      if (tg.pick === 'points' && tg.filters.points_min === '' && tg.filters.points_max === '') out.push('Indiquez le nombre de points des clients ciblés.');
      if (tg.pick === 'stores' && !tg.filters.stores.length) out.push('Choisissez au moins un établissement.');
      if (tg.pick === 'inactive' && !(Number(tg.inactive_days) > 0)) out.push('Indiquez depuis combien de jours.');
      const f = tg.filters;
      if ((tg.on.points || tg.pick === 'points') && f.points_min !== '' && f.points_max !== '' && Number(f.points_max) < Number(f.points_min)) out.push('Nombre de points : le maximum doit être au moins égal au minimum.');
      if (tg.on.spent && f.spent_min !== '' && f.spent_max !== '' && Number(f.spent_max) < Number(f.spent_min)) out.push("Montant total d'achats : le maximum doit être au moins égal au minimum.");
      if (tg.on.last && !(Number(f.last_visit_days) > 0)) out.push('Date de dernière visite : indiquez le nombre de jours.');
    }
    if (n === 5) {
      if (sc.window && sc.window_to <= sc.window_from) out.push('La fin de la plage horaire doit être après son début.');
      if (sc.window && timed(tr) && !(sc.window_from <= sc.hour && sc.hour < sc.window_to)) out.push(`L'heure d'envoi (${sc.hour}) doit être comprise dans la plage horaire (${sc.window_from} – ${sc.window_to}).`);
      if (!timed(tr) && tr.type !== 'geo' && sc.send_mode === 'at' && !sc.send_at) out.push("Choisissez la date et l'heure d'envoi.");
      const vt = sc.period || sc.expire ? sc.valid_to : '';
      if (sc.period && sc.valid_from && vt && vt < sc.valid_from) out.push('La date de fin doit être après la date de début.');
      if (tr.type === 'on_date' && vt && tr.date && vt < tr.date) out.push("La date d'expiration est avant la date d'envoi : le message ne partirait jamais.");
      if (activate && vt && vt < today) out.push('La date de fin est déjà passée.');
      if (sc.rules_note.length > NOTE_MAX) out.push('Conditions supplémentaires : 500 caractères au maximum.');
    }
    return out;
  };
  const allProblems = [1, 2, 3, 4, 5].flatMap((n) => problems(n).map((p) => [n, p]));

  const go = (n, sub) => { setError(''); setStep(n); if (n === 5) setSub5(sub || 'plan'); window.scrollTo?.({ top: 0, behavior: 'smooth' }); };
  const next = () => {
    const p = problems(step);
    if (p.length) { setError(p[0]); return; }
    if (step === 5 && sub5 === 'plan') { setSub5('rules'); setError(''); return; }
    go(Math.min(6, step + 1));
  };
  const back = () => {
    if (step === 5 && sub5 === 'rules') { setSub5('plan'); setError(''); return; }
    if (step === 1) { navigate('/dashboard/automations'); return; }
    go(step - 1, step === 6 ? 'rules' : undefined);
  };

  const bodyOut = (status) => {
    const num = (v) => (v === '' || v === null || v === undefined ? null : Number(v));
    const t = { ...tr };
    ['every_days', 'per_month', 'delay_value', 'value', 'x', 'y', 'delay_days', 'every_weeks'].forEach((k) => { if (k in t) t[k] = num(t[k]); });
    if (t.type === 'loyalty') ['points', 'visits', 'amount'].forEach((k) => { t[k] = Number(t[k]) > 0 ? Number(t[k]) : null; });
    if (t.type === 'action') t.criteria = { ...t.criteria, min_amount: num(t.criteria.min_amount) };
    const msg = (m) => ({ title: m.title, body: m.body, image_url: m.image_url || null,
      button: { ...m.button, url: m.button.link_type === 'url' && m.button.url && !/^https?:\/\//i.test(m.button.url) ? `https://${m.button.url}` : m.button.url || null,
        offer_id: m.button.offer_id || null } });
    const sch = { ...sc, valid_from: sc.period || hasDate(tr) ? sc.valid_from || null : null,
      valid_to: sc.period || sc.expire ? sc.valid_to || null : null, send_at: sc.send_mode === 'at' ? sc.send_at : null };
    delete sch.expire; delete sch.period;
    return { scenario: 'custom', name: s.name.trim(), description: s.description.trim(), status, trigger: t, message: msg(s.message),
      message_reminder: rem ? msg(s.message_reminder) : null, targeting: targetingOut, schedule: sch };
  };
  const save = async (status) => {
    if (status !== 'draft') {
      const p = allProblems[0];
      if (p) { go(p[0], p[0] === 5 ? 'rules' : undefined); setError(p[1]); return; }
    } else if (!s.name.trim()) { go(1); setError("Donnez un nom à l'automatisation."); return; }
    setBusy(status); setError('');
    try {
      if (editing) await ownerAPI.updateAutomation(row.id, bodyOut(status));
      else await ownerAPI.createAutomation(bodyOut(status));
      navigate('/dashboard/automations', { state: { flash: status === 'draft' ? 'Brouillon enregistré.' : status === 'active' ? 'Automatisation enregistrée et activée.' : 'Automatisation enregistrée (en pause).' } });
      onReload?.();
    } catch (e) {
      setError(e?.response?.data?.detail || "L'automatisation n'a pas pu être enregistrée.");
    } finally { setBusy(''); }
  };

  // ---- the message's inserts -------------------------------------------------------------
  const insert = (txt) => {
    const which = lastFocus.current === 'title' ? 'title' : 'body';
    const el = which === 'title' ? titleRef.current : bodyRef.current;
    const v = cur[which] || '';
    const max = which === 'title' ? TITLE_MAX : BODY_MAX;
    const a = el?.selectionStart ?? v.length;
    const b = el?.selectionEnd ?? v.length;
    const nv = (v.slice(0, a) + txt + v.slice(b)).slice(0, max);
    setCur({ [which]: nv });
    requestAnimationFrame(() => { el?.focus(); const p = Math.min(nv.length, a + txt.length); el?.setSelectionRange?.(p, p); });
  };
  const onImage = (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (!/^image\/(png|jpe?g|webp|gif)$/.test(file.type)) { setError('Image PNG ou JPG uniquement.'); return; }
    if (file.size > 2 * 1024 * 1024) { setError("L'image dépasse 2 Mo."); return; }
    const r = new FileReader();
    r.onload = () => setCur({ image_url: String(r.result) });
    r.readAsDataURL(file);
  };
  const varsHere = [...VARS, ...(tr.type === 'action' && tr.action === 'offer_used' ? ['offre'] : []), ...(tr.type === 'action' && tr.action === 'tier_reached' ? ['palier'] : [])];

  // ---- shared bits of steps 2 and 5 (same data) ------------------------------------------
  const HourTz = (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="block"><Label req>Heure d'envoi</Label><Select icon={Clock} label="Heure d'envoi" value={sc.hour} onChange={(v) => setSc({ hour: v })} options={HOURS.map((h) => [h, h])} /></label>
      <label className="block"><Label hint="Les notifications partent à l'heure de ce fuseau, où que soient vos clients.">Fuseau horaire</Label>
        <Select icon={Globe} label="Fuseau horaire" value={sc.tz} onChange={(v) => setSc({ tz: v })} options={TZ_OPTIONS} /></label>
    </div>
  );
  const PeriodToggle = (
    <div className="flex items-start gap-3 rounded-xl border border-[#E6EEFB] p-3">
      <Toggle label="Limiter à une période" on={sc.period} onChange={(v) => setSc({ period: v, ...(v ? {} : { valid_from: '', valid_to: '' }) })} />
      <span className="min-w-0 flex-1"><span className="block text-[13px] font-semibold text-[#0B1C3F]">Limiter à une période</span>
        <span className="text-[11.5px] text-[#64748B]">Définissez une date de début et de fin pour cette automatisation.</span>
        {sc.period && (
          <span className="mt-2 grid gap-2 sm:grid-cols-2">
            <input type="date" aria-label="Début de la période" className={field} value={sc.valid_from} min={today} onChange={(e) => setSc({ valid_from: e.target.value })} />
            <input type="date" aria-label="Fin de la période" className={field} value={sc.valid_to} min={sc.valid_from || today} onChange={(e) => setSc({ valid_to: e.target.value })} />
          </span>
        )}</span>
    </div>
  );
  const dayMonth = (val, onChange, label) => {
    const mm = val ? Number(val.slice(5, 7)) : 10;
    const dd = val ? Number(val.slice(8, 10)) : 17;
    const mk = (d, m) => `2000-${String(m).padStart(2, '0')}-${String(Math.min(d, new Date(2000, m, 0).getDate())).padStart(2, '0')}`;
    return (
      <span className="grid grid-cols-[90px_1fr] gap-2">
        <Select label={`${label} (jour)`} value={String(dd)} onChange={(v) => onChange(mk(Number(v), mm))} options={Array.from({ length: new Date(2000, mm, 0).getDate() }, (_, i) => [String(i + 1), String(i + 1)])} />
        <Select icon={CalendarDays} label={`${label} (mois)`} value={String(mm)} onChange={(v) => onChange(mk(dd, Number(v)))} options={MONTHS.map((m, i) => [String(i + 1), m])} />
      </span>
    );
  };
  const RecurrenceFields = () => (
    <div className="space-y-4">
      <div><Label req>Périodicité</Label>
        <div className="grid grid-cols-2 gap-1 sm:grid-cols-4">
          {[['weekly', 'Hebdomadaire'], ['monthly', 'Mensuelle'], ['yearly', 'Annuelle'], ['custom', 'Personnalisée']].map(([k, l]) => (
            <button key={k} type="button" aria-pressed={tr.period === k} onClick={() => setT({ period: k })}
                    className={`rounded-xl border px-3 py-2 text-[13.5px] font-semibold transition ${tr.period === k ? 'border-[#2F6BFF] bg-[#2F6BFF] text-white' : 'border-[#E2E8F0] bg-white text-[#334155] hover:border-[#BFD3FF]'}`}>{l}</button>
          ))}
        </div></div>
      {tr.period === 'weekly' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block"><Label req>Fréquence d'envoi</Label>
            <Select label="Fréquence d'envoi" value={String(tr.every_weeks || 1)} onChange={(v) => setT({ every_weeks: Number(v) })}
                    options={[['1', 'Chaque semaine'], ['2', 'Toutes les 2 semaines'], ['3', 'Toutes les 3 semaines'], ['4', 'Toutes les 4 semaines']]} /></label>
          <div><Label req>Jours d'envoi</Label>
            <div className="flex flex-wrap gap-1.5">{DAYS.map((d, i) => {
              const on = (tr.weekdays || []).includes(i);
              return <button key={d} type="button" aria-pressed={on} onClick={() => setT({ weekdays: on ? tr.weekdays.filter((x) => x !== i) : [...(tr.weekdays || []), i].sort() })}
                             className={`min-w-[48px] rounded-xl border px-2.5 py-2 text-[13px] font-semibold ${on ? 'border-[#2F6BFF] bg-[#2F6BFF] text-white' : 'border-[#E2E8F0] text-[#334155]'}`}>{d}</button>;
            })}</div></div>
        </div>
      )}
      {tr.period === 'monthly' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block"><Label req>Fréquence d'envoi</Label>
            <Select label="Fréquence d'envoi" value={String((tr.monthdays || []).length || 1)}
                    onChange={(v) => { const n = Number(v); const base = [1, 15, 8, 22]; const cur0 = [...(tr.monthdays || [])]; while (cur0.length < n) cur0.push(base.find((x) => !cur0.includes(x)) || 28); setT({ monthdays: cur0.slice(0, n).sort((a, b) => a - b) }); }}
                    options={[['1', '1 fois par mois'], ['2', '2 fois par mois'], ['3', '3 fois par mois'], ['4', '4 fois par mois']]} /></label>
          <div><Label req>Jours d'envoi</Label>
            <div className="flex flex-wrap gap-2">{(tr.monthdays || []).map((d, i) => (
              <span key={i} className="flex items-center gap-1.5 rounded-xl bg-[#2F6BFF] py-1 pl-2.5 pr-1 text-[13px] font-semibold text-white"><Check size={15} /> Le
                <select aria-label={`Jour ${i + 1}`} value={d} onChange={(e) => { const v = [...tr.monthdays]; v[i] = Number(e.target.value); setT({ monthdays: [...new Set(v)].sort((a, b) => a - b) }); }}
                        className="rounded-lg bg-white/20 px-1 py-1 text-white outline-none">
                  {Array.from({ length: 31 }, (_, j) => <option key={j} value={j + 1} className="text-[#0B1C3F]">{j === 0 ? '1er' : j + 1}</option>)}
                </select> du mois</span>
            ))}</div>
            <Help>« Le 31 » part le dernier jour des mois plus courts.</Help></div>
        </div>
      )}
      {tr.period === 'yearly' && (
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block"><Label req>Date d'envoi</Label>
              <Select label="Type de date" value={tr.date_kind || 'fixed'} onChange={(v) => setT({ date_kind: v })}
                      options={[['fixed', 'Une date fixe'], ['birthday', "L'anniversaire du client"], ['signup', "L'anniversaire d'inscription"]]} />
              {(tr.date_kind || 'fixed') === 'fixed' && <span className="mt-2 block">{dayMonth(tr.date, (v) => setT({ date: v }), "Date d'envoi")}</span>}
              {tr.date_kind === 'birthday' && <Help>Chaque client le jour de son anniversaire (date de naissance renseignée à l'inscription).</Help>}
              {tr.date_kind === 'signup' && <Help>Chaque client à la date anniversaire de son inscription (à partir d'un an).</Help>}</label>
            <label className="block"><Label req>Répétition</Label><Select label="Répétition" value="yearly" onChange={() => {}} options={[['yearly', 'Chaque année']]} /></label>
          </div>
        </div>
      )}
      {tr.period === 'custom' && (
        <div className="space-y-3">
          <div><Label req>Règle personnalisée</Label>
            <div className="grid gap-2 sm:grid-cols-2">
              {[['every_days', 'Tous les', 'every_days', 'jours', 365], ['per_month', 'ou', 'per_month', 'fois par mois', 10]].map(([k, pre, f, post, mx]) => (
                <label key={k} className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-[13px] ${tr.rule === k ? 'border-[#2F6BFF] bg-[#F5F8FF]' : 'border-[#E2E8F0]'}`}>
                  <input type="radio" name="rule" checked={tr.rule === k} onChange={() => setT({ rule: k })} className="h-4 w-4 accent-[#1463FF]" /> {pre}
                  <span className="w-20"><Num label={post} value={tr[f]} max={mx} onChange={(v) => setT({ [f]: v, rule: k })} /></span> {post}
                </label>
              ))}
            </div></div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block"><Label req>Début</Label><input type="date" aria-label="Début" className={field} value={sc.valid_from} onChange={(e) => setSc({ valid_from: e.target.value })} />
              <Help>« Tous les N jours » compte à partir de cette date.</Help></label>
            <label className="block"><Label>Fin</Label><input type="date" aria-label="Fin" className={field} value={sc.valid_to} min={sc.valid_from || today}
                                                         onChange={(e) => setSc({ valid_to: e.target.value, period: Boolean(e.target.value) || Boolean(sc.valid_from) })} /></label>
          </div>
          <div className="flex items-start gap-3 rounded-xl border border-[#E6EEFB] p-3">
            <Toggle label="Jours ouvrés uniquement" on={Boolean(tr.workdays_only)} onChange={(v) => setT({ workdays_only: v })} />
            <span><span className="block text-[13px] font-semibold text-[#0B1C3F]">Jours ouvrés uniquement</span><span className="text-[11.5px] text-[#64748B]">N'envoyer que du lundi au vendredi.</span></span>
          </div>
        </div>
      )}
      {HourTz}
      {tr.period === 'yearly' && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-[#E6EEFB] p-3">
          <Toggle label="Rappel avant la date" on={Boolean(tr.reminder?.enabled)} onChange={(v) => setT({ reminder: { ...tr.reminder, enabled: v } })} />
          <span className="min-w-0 flex-1"><span className="block text-[13px] font-semibold text-[#0B1C3F]">Rappel avant la date <span className="font-normal text-[#64748B]">(optionnel)</span></span>
            <span className="text-[11.5px] text-[#64748B]">Envoyez un rappel quelques jours avant la date d'envoi, avec son propre texte (étape Message).</span></span>
          <span className="w-44"><Select label="Jours avant" disabled={!tr.reminder?.enabled} value={String(tr.reminder?.days_before || 7)} onChange={(v) => setT({ reminder: { ...tr.reminder, days_before: Number(v) } })}
                                         options={[1, 2, 3, 5, 7, 10, 14, 30].map((n) => [String(n), `${n} jour${n > 1 ? 's' : ''} avant`])} /></span>
        </div>
      )}
      {tr.period !== 'custom' && PeriodToggle}
    </div>
  );
  const OnDateFields = (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block"><Label req>Date d'envoi</Label><input type="date" aria-label="Date d'envoi" className={field} value={tr.date || ''} min={today} onChange={(e) => setT({ date: e.target.value })} /></label>
        <label className="block"><Label req>Heure d'envoi</Label><Select icon={Clock} label="Heure d'envoi" value={sc.hour} onChange={(v) => setSc({ hour: v })} options={HOURS.map((h) => [h, h])} /></label>
        <label className="block"><Label hint="Les notifications partent à l'heure de ce fuseau.">Fuseau horaire</Label><Select icon={Globe} label="Fuseau horaire" value={sc.tz} onChange={(v) => setSc({ tz: v })} options={TZ_OPTIONS} /></label>
      </div>
    </div>
  );

  // ---- step 1 ------------------------------------------------------------------------------
  const Step1 = (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <h2 className="text-[22px] font-extrabold text-[#0B1C3F]">1. Configurer votre nouvelle automatisation</h2>
      <p className="mb-5 text-[14px] text-[#475569]">Donnez un nom et une description à votre automatisation.</p>
      <label className="block"><Label req right={`${s.name.length}/60`}>Nom de l'automatisation</Label>
        <input className={field} value={s.name} maxLength={60} onChange={(e) => set({ name: e.target.value })} placeholder="Ex. Offre spéciale week-end" /></label>
      <label className="mt-4 block"><Label>Description (optionnelle)</Label>
        <textarea className={`${field} min-h-[110px] resize-y`} value={s.description} maxLength={DESC_MAX} onChange={(e) => set({ description: e.target.value })}
                  placeholder="Expliquez l'objectif de cette automatisation…" />
        <span className="mt-1 block text-right text-[12px] text-[#64748B]">{s.description.length}/{DESC_MAX}</span></label>
      <div className="mt-4 flex gap-3 rounded-xl bg-[#F1F6FF] p-4">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#1463FF] text-white"><Info size={18} /></span>
        <span className="text-[13px] text-[#475569]"><b className="block text-[14.5px] text-[#0B1C3F]">Conseil</b>
          Vous pourrez définir quand cette automatisation sera déclenchée, personnaliser le message et cibler vos clients dans les étapes suivantes.</span>
      </div>
    </section>
  );

  // ---- step 2 ------------------------------------------------------------------------------
  const triggerCard = (t, compact) => {
    const on = tr.type === t.key;
    const I = t.icon;
    return (
      <button key={t.key} type="button" aria-pressed={on} onClick={() => pickTrigger(t.key)}
              className={`flex w-full items-center gap-4 rounded-2xl border p-3 text-left transition ${on ? 'border-[#2F6BFF] bg-[#F5F8FF] shadow-[0_0_0_1px_#2F6BFF]' : 'border-[#E6EEFB] bg-white hover:border-[#BFD3FF]'}`}>
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl" style={{ background: t.tone[0], color: t.tone[1] }}><I size={24} /></span>
        <span className="min-w-0 flex-1"><span className="block text-[15px] font-bold text-[#0B1C3F]">{t.title}</span>
          <span className={`block text-[12.5px] text-[#64748B] ${compact ? 'line-clamp-2' : ''}`}>{t.sub}</span></span>
        {on ? <CheckCircle2 size={24} className="shrink-0 fill-[#1463FF] text-white" /> : <span className="h-5 w-5 shrink-0 rounded-full border-2 border-[#CBD5E1]" />}
      </button>
    );
  };
  const stores = page.stores || [];
  const storeChips = (vals, onChange) => (
    <div className="flex flex-wrap gap-1.5">{stores.map((x) => {
      const on = vals.includes(x.id);
      return <button key={x.id} type="button" aria-pressed={on} onClick={() => onChange(on ? vals.filter((v) => v !== x.id) : [...vals, x.id])}
                     className={`rounded-xl border px-3 py-1.5 text-[12.5px] font-semibold ${on ? 'border-[#2F6BFF] bg-[#EEF4FF] text-[#1D4ED8]' : 'border-[#E2E8F0] text-[#334155]'}`}>{x.name}</button>;
    })}</div>
  );
  const ActionFields = () => (
    <div className="space-y-4">
      <div className="grid gap-3 lg:grid-cols-[1.3fr_1fr_1fr]">
        <label className="block"><Label>Type d'action client</Label>
          <Select icon={(ACTIONS.find(([k]) => k === tr.action) || [])[2]} label="Type d'action client" value={tr.action} onChange={(v) => setT({ action: v })} options={ACTIONS.map(([k, l]) => [k, l])} /></label>
        <label className="block"><Label hint="0 = immédiatement après l'action.">Délai après l'action</Label>
          <span className="grid grid-cols-[1fr_110px] gap-2"><Num label="Délai après l'action" value={tr.delay_value} max={365} onChange={(v) => setT({ delay_value: v })} />
            <Select label="Unité" value={tr.delay_unit} onChange={(v) => setT({ delay_unit: v })} options={[['minutes', 'minute'], ['hours', 'heure'], ['days', 'jour']]} /></span></label>
        <label className="block"><Label hint="Combien de fois un même client peut recevoir ce message.">Répétition</Label>
          <Select icon={Repeat} label="Répétition" value={tr.repeat} onChange={(v) => setT({ repeat: v })}
                  options={[['once', 'Une seule fois'], ['every', 'À chaque fois'], ['gap', 'Au plus une fois tous les…']]} />
          {tr.repeat === 'gap' && <span className="mt-2 block"><Num label="Tous les (jours)" value={tr.every_days} max={365} unit="jours" onChange={(v) => setT({ every_days: v })} /></span>}</label>
      </div>
      <div className="rounded-2xl border border-[#E6EEFB] bg-[#FAFCFF] p-4">
        <div className="flex flex-wrap items-center gap-3">
          <Filter size={22} className="text-[#1463FF]" />
          <span className="min-w-0 flex-1"><span className="block text-[14.5px] font-bold text-[#0B1C3F]">Critères supplémentaires <span className="font-normal text-[#64748B]">(optionnel)</span></span>
            <span className="text-[12.5px] text-[#64748B]">Affinez les conditions pour déclencher cette notification.</span></span>
          <span className="flex items-center gap-2 text-[13px] text-[#334155]"><Toggle label="Ajouter des critères" on={tr.criteria.enabled} onChange={(v) => setT({ criteria: { ...tr.criteria, enabled: v } })} /> Ajouter des critères</span>
        </div>
        {tr.criteria.enabled && (
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {['purchase', 'visit', 'tier_reached'].includes(tr.action) && (
              <label className="block"><Label>Montant minimum d'achat</Label>
                <Num decimal label="Montant minimum d'achat" value={tr.criteria.min_amount} unit="€" onChange={(v) => setT({ criteria: { ...tr.criteria, min_amount: v } })} /></label>
            )}
            {tr.action === 'offer_used' && (
              <label className="block"><Label>Offre</Label>
                <Select label="Offre" value={tr.criteria.offer_id || ''} onChange={(v) => setT({ criteria: { ...tr.criteria, offer_id: v } })}
                        options={[['', 'Toutes les offres'], ...(page.offers || []).map((o) => [o.id, o.name])]} /></label>
            )}
            {stores.length > 1 && <div className="sm:col-span-2"><Label>Établissements</Label>{storeChips(tr.criteria.stores || [], (v) => setT({ criteria: { ...tr.criteria, stores: v } }))}
              <Help>Aucun coché = tous les établissements.</Help></div>}
          </div>
        )}
      </div>
    </div>
  );
  const LoyaltyFields = () => (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block"><Label hint="« Au moins une » : la première condition atteinte suffit.">Condition d'atteinte</Label>
          <Select label="Condition d'atteinte" value={tr.match} onChange={(v) => setT({ match: v })} options={[['any', 'Au moins une des conditions est remplie'], ['all', 'Toutes les conditions sont remplies']]} /></label>
        <label className="block"><Label hint="« À chaque nouvelle atteinte » : à nouveau quand les conditions redeviennent vraies (ex. après une récompense utilisée).">Répétition</Label>
          <Select label="Répétition" value={tr.repeat} onChange={(v) => setT({ repeat: v })} options={[['once', 'Une seule fois'], ['each', 'À chaque nouvelle atteinte']]} /></label>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {[['points', 'Nombre de points', 'points', 'Déclenche lorsque le client a atteint ce nombre de points.'],
          ['visits', 'Nombre de visites', 'visites', 'Déclenche lorsque le client a atteint ce nombre de visites.'],
          ['amount', "Montant d'achats", '€', "Déclenche lorsque le client a atteint ce montant cumulé d'achats."]].map(([k, l, u, h]) => (
          <label key={k} className="block"><Label hint="Laissez vide pour ne pas l'utiliser.">{l}</Label>
            <Num decimal={k === 'amount'} label={l} value={tr[k]} unit={u} max={10000000} onChange={(v) => setT({ [k]: v })} /><Help>{h}</Help></label>
        ))}
      </div>
    </div>
  );
  const BehaviorFields = () => (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="block"><Label>Statut du client</Label>
        <Select label="Statut du client" value={tr.client_status} onChange={(v) => setT({ client_status: v })}
                options={[['existing', 'Clients existants'], ['new', 'Nouveaux clients (jamais venus)'], ['all', 'Tous les clients']]} />
        <Help>Choisissez le type de clients concernés.</Help></label>
      <label className="block"><Label>Activité du client</Label>
        <Select label="Activité du client" value={tr.activity} onChange={(v) => setT({ activity: v })} options={[['inactive', 'Inactifs'], ['active', 'Actifs']]} />
        <Help>{tr.activity === 'active' ? 'Clients venus dans la période — au plus un message par période.' : "Déclenchez la notification selon l'inactivité — une fois par absence."}</Help></label>
      <label className="block"><Label>Délai depuis la dernière visite</Label>
        <span className="grid grid-cols-[1fr_130px] gap-2"><Num label="Délai depuis la dernière visite" value={tr.value} max={365} onChange={(v) => setT({ value: v })} />
          <Select label="Unité" value={tr.unit} onChange={(v) => setT({ unit: v })} options={[['days', 'jours'], ['weeks', 'semaines'], ['months', 'mois']]} /></span>
        <Help>{tr.activity === 'active' ? 'Le client est considéré actif s’il est venu dans cette période.' : 'Le client sera considéré comme inactif après cette période.'}</Help></label>
      <label className="block"><Label>Segmentation <span className="font-normal text-[#64748B]">(optionnelle)</span></Label>
        <Select label="Segmentation" value={tr.segment} onChange={(v) => setT({ segment: v })} options={[['', 'Tous les clients'], ...(page.segments || []).map((x) => [x.key, x.label])]} />
        <Help>Affinez avec un segment spécifique.</Help></label>
    </div>
  );
  const radii = [50, 100, 300, 500, 1000];
  const GeoFields = () => (
    <div className="grid gap-4 2xl:grid-cols-[1fr_210px]">
      <div className="space-y-4">
        <div className="relative"><Label>Adresse ou établissement</Label>
          <span className="relative block"><Search size={17} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#64748B]" />
            <input className={`${field} !pl-10 !pr-9`} value={addr.q} placeholder="Rechercher une adresse ou un établissement…"
                   onFocus={() => setAddr((a) => ({ ...a, open: true }))}
                   onChange={(e) => setAddr((a) => ({ ...a, q: e.target.value, open: true }))} />
            {addr.q && <button type="button" aria-label="Effacer l'adresse" onClick={() => { setAddr({ q: '', results: [], open: true }); setT({ address: '', lat: null, lng: null }); }}
                               className="absolute right-3 top-1/2 -translate-y-1/2 text-[#64748B]"><X size={16} /></button>}</span>
          {addr.open && (
            <div className="absolute z-30 mt-1 w-full overflow-hidden rounded-xl border border-[#E2E8F0] bg-white shadow-xl">
              {addr.busy && <p className="flex items-center gap-2 px-3 py-2 text-[12.5px] text-[#64748B]"><Loader2 size={14} className="animate-spin" /> Recherche…</p>}
              {!addr.busy && !addr.results.length && <p className="px-3 py-2 text-[12.5px] text-[#64748B]">{addr.err || (addr.q.length < 3 ? 'Tapez au moins 3 caractères, ou choisissez un établissement.' : 'Aucune adresse trouvée.')}</p>}
              {addr.results.map((r, i) => (
                <button key={`${r.label}-${i}`} type="button" onClick={() => { setT({ address: r.label, lat: r.lat, lng: r.lng }); setAddr({ q: r.label, results: [], open: false }); }}
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-[#0B1C3F] hover:bg-[#F1F6FF]">
                  {r.kind === 'store' ? <Store size={15} className="shrink-0 text-[#1463FF]" /> : <MapPin size={15} className="shrink-0 text-[#E11D48]" />}{r.label}</button>
              ))}
              <button type="button" onClick={() => setAddr((a) => ({ ...a, open: false }))} className="w-full border-t border-[#F1F5F9] px-3 py-1.5 text-right text-[12px] text-[#64748B]">Fermer</button>
            </div>
          )}</div>
        <div><Label>Rayon de détection</Label>
          <p className="mb-2 text-[12px] text-[#64748B]">La notification sera envoyée lorsque le client entre dans cette zone.</p>
          <div className="flex items-center gap-3">
            <input type="range" min={50} max={1000} step={10} aria-label="Rayon de détection" value={tr.radius_m} onChange={(e) => setT({ radius_m: Number(e.target.value) })} className="w-full accent-[#2F6BFF]" />
            <span className="w-32 shrink-0"><Num label="Rayon (m)" value={String(tr.radius_m)} unit="m" max={1000} onChange={(v) => setT({ radius_m: v === '' ? 50 : Number(v) })} /></span>
          </div>
          <div className="mt-1 flex justify-between pr-36 text-[11.5px] text-[#64748B]">{radii.map((r) => <button key={r} type="button" onClick={() => setT({ radius_m: r })}>{r < 1000 ? `${r} m` : '1 km'}</button>)}</div>
        </div>
        <div><Label>Plage d'activation</Label>
          <p className="mb-2 text-[12px] text-[#64748B]">Définissez les jours et horaires d'activation.</p>
          <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
            <span className="col-span-3"><Select icon={CalendarDays} label="Jours" value={tr.days} onChange={(v) => setT({ days: v })} options={[['all', 'Tous les jours'], ['weekdays', 'Du lundi au vendredi'], ['weekend', 'Le week-end']]} /></span>
            <Select icon={Clock} label="De" value={tr.from} onChange={(v) => setT({ from: v })} options={HOURS.map((h) => [h, h])} />
            <span className="text-[13px] text-[#64748B]">à</span>
            <Select label="À" value={tr.to} onChange={(v) => setT({ to: v })} options={[...HOURS, '23:59'].map((h) => [h, h])} />
          </div></div>
      </div>
      <div className="space-y-2">
        {tr.lat != null
          ? <GeoZoneMap anchors={[{ id: 'zone', name: tr.address, lat: tr.lat, lng: tr.lng }]} radius={tr.radius_m} height={210} interactive showPeople={false} />
          : <div className="flex h-[210px] items-center justify-center rounded-2xl bg-[#F1F5F9] p-4 text-center text-[12.5px] text-[#64748B]"><MapPin size={18} className="mr-1" /> Choisissez une adresse</div>}
        <p className="flex gap-2 rounded-xl bg-[#EEF4FF] p-2 text-[11.5px] text-[#334155]"><MapPin size={15} className="shrink-0 text-[#1463FF]" />
          <span>Zone de {tr.radius_m} m autour de :<br /><b>{tr.address || '—'}</b></span></p>
      </div>
      <div className="2xl:col-span-2"><p className="text-[14px] font-bold text-[#0B1C3F]">Conditions supplémentaires <span className="font-normal text-[#64748B]">(optionnel)</span></p>
        <p className="mb-2 text-[12px] text-[#64748B]">Affinez le déclenchement avec des conditions supplémentaires.</p>
        <div className="flex items-center gap-3 rounded-xl border border-[#E6EEFB] p-3"><Users size={20} className="text-[#1463FF]" />
          <span className="min-w-0 flex-1"><span className="block text-[13px] font-semibold text-[#0B1C3F]">Uniquement pour les nouveaux clients</span>
            <span className="text-[11.5px] text-[#64748B]">Ne pas envoyer si le client est déjà venu dans votre établissement.</span></span>
          <Toggle label="Uniquement pour les nouveaux clients" on={tr.new_only} onChange={(v) => setT({ new_only: v })} /></div></div>
    </div>
  );
  const ruleChoices = Object.entries(OTHER_RULES).filter(([, [ev]]) => ev === tr.event);
  const OtherFields = () => (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block"><Label req>Nom de la règle</Label><input className={field} maxLength={60} value={tr.rule_name} onChange={(e) => setT({ rule_name: e.target.value })} placeholder="Ex. Clients inactifs 30 jours" /></label>
        <label className="block"><Label req>Événement</Label>
          <Select icon={Sparkles} label="Événement" value={tr.event} onChange={(v) => { const first = Object.entries(OTHER_RULES).find(([, [ev]]) => ev === v)?.[0]; setT({ event: v, rule: first, ...(first === 'no_visit_days' || first === 'days_after_first_visit' ? { x: '30' } : first === 'spent_in_days' ? { x: '50', y: '30' } : { x: '3', y: '60' }) }); }}
                  options={OTHER_EVENTS} /></label>
        <label className="block"><Label req>Condition personnalisée</Label>
          <Select label="Condition personnalisée" value={tr.rule} onChange={(v) => setT({ rule: v })} options={ruleChoices.map(([k, [, l]]) => [k, l])} />
          {['visits_in_days', 'spent_in_days'].includes(tr.rule) && (
            <span className="mt-2 grid grid-cols-[1fr_auto_1fr_auto] items-center gap-2 text-[13px] text-[#334155]">
              <Num decimal={tr.rule === 'spent_in_days'} label="X" value={tr.x} unit={tr.rule === 'spent_in_days' ? '€' : 'visites'} onChange={(v) => setT({ x: v })} /> en
              <Num label="Y jours" value={tr.y} max={365} onChange={(v) => setT({ y: v })} /> jours</span>
          )}
          {['no_visit_days', 'days_after_first_visit'].includes(tr.rule) && (
            <span className="mt-2 block"><Num label="X jours" value={tr.x} unit="jours" max={365} onChange={(v) => setT({ x: v })} /></span>
          )}</label>
        <label className="block"><Label hint="0 = dès que la condition est remplie.">Délai d'envoi</Label>
          <span className="grid grid-cols-[1fr_110px] gap-2"><Num label="Délai d'envoi" value={tr.delay_days} max={365} onChange={(v) => setT({ delay_days: v })} />
            <Select label="Unité" value="days" onChange={() => {}} options={[['days', 'jour(s)']]} /></span>
          <Help>{Number(tr.delay_days) ? `La notification sera envoyée ${tr.delay_days} jour(s) après que la condition est remplie.` : 'La notification sera envoyée dès que la condition est remplie.'}</Help></label>
      </div>
      <label className="block"><Label>Notes internes <span className="font-normal text-[#64748B]">(optionnel)</span></Label>
        <textarea className={`${field} min-h-[70px] resize-y`} maxLength={NOTE_MAX} value={tr.notes} onChange={(e) => setT({ notes: e.target.value })}
                  placeholder="Ex. : cibler les clients inactifs pour les réengager avec une offre spéciale." />
        <span className="mt-1 block text-right text-[11.5px] text-[#64748B]">{(tr.notes || '').length}/{NOTE_MAX}</span></label>
    </div>
  );
  const configTitle = {
    on_date: ['Configuration du déclencheur', null], recurring: ['Configuration du déclencheur récurrent', 'Définissez la fréquence et la période d\'envoi de votre notification.'],
    action: ['Configurer le déclencheur : Après une action client', "La notification sera envoyée après qu'un client ait effectué l'action sélectionnée."],
    loyalty: ['Configurer les conditions sur la fidélité', 'La notification sera envoyée lorsque le client remplit les conditions définies ci-dessous.'],
    behavior: ['Configurer le déclencheur : Comportement client', 'Définissez les critères de comportement pour déclencher la notification.'],
    geo: ['Configuration : Géolocalisation', 'Définissez la zone géographique et les conditions de déclenchement pour envoyer votre notification.'],
    other: ['Configurer votre déclencheur personnalisé', 'Créez une règle sur mesure pour déclencher cette automatisation.'],
  }[tr.type];
  const [condOn, setCondOn] = useState(false);
  const Step2 = (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <h2 className="text-[22px] font-extrabold text-[#0B1C3F]">2. Déclencheur</h2>
      <p className="mb-4 text-[14px] text-[#475569]">Choisissez quand cette automatisation doit être déclenchée.</p>
      <div className={tr.type === 'geo' ? 'grid gap-4 xl:grid-cols-[290px_minmax(0,1fr)]' : ''}>
      <div className={`grid content-start gap-2 ${tr.type === 'other' ? 'sm:grid-cols-2' : ''}`}>
        {tr.type === 'other' ? [...TRIGGERS.filter((t) => t.key !== 'other')].map((t) => triggerCard(t, true)) : TRIGGERS.map((t) => triggerCard(t, tr.type === 'geo'))}
        {tr.type === 'other' && <div className="sm:col-span-2">{triggerCard(TRIGGER.other)}</div>}
      </div>
      <div className={`${tr.type === 'geo' ? 'xl:mt-0' : ''} mt-4 rounded-2xl border border-[#E6EEFB] bg-white p-4`}>
        <ConfigHead icon={tr.type === 'on_date' ? null : TRIGGER[tr.type].icon} tone={TRIGGER[tr.type].tone} title={configTitle[0]} sub={configTitle[1]} />
        {tr.type === 'on_date' && OnDateFields}
        {tr.type === 'recurring' && RecurrenceFields()}
        {tr.type === 'action' && ActionFields()}
        {tr.type === 'loyalty' && LoyaltyFields()}
        {tr.type === 'behavior' && BehaviorFields()}
        {tr.type === 'geo' && GeoFields()}
        {tr.type === 'other' && OtherFields()}
        {tr.type === 'on_date' && (
          <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-[#F1F5F9] pt-3">
            <span className="min-w-0 flex-1"><span className="block text-[13.5px] font-bold text-[#0B1C3F]">Conditions optionnelles</span>
              <span className="text-[12px] text-[#64748B]">Ajoutez des conditions pour affiner l'envoi de cette notification.</span></span>
            <span className="flex items-center gap-2 text-[13px] text-[#334155]"><Toggle label="Ajouter des conditions" on={condOn} onChange={setCondOn} /> Ajouter des conditions</span>
            {condOn && <p className="w-full rounded-xl bg-[#F1F6FF] p-3 text-[12.5px] text-[#334155]">Les conditions sur les clients (actifs, points, âge, dernière visite, montant d'achats, établissement…) se règlent à l'étape <b>4 · Ciblage</b>.
              <button type="button" onClick={() => go(4)} className="ml-2 font-semibold text-[#1463FF]">Aller au ciblage →</button></p>}
          </div>
        )}
      </div>
      </div>
    </section>
  );

  // ---- step 3 ------------------------------------------------------------------------------
  const Step3 = (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <h2 className="text-[22px] font-extrabold text-[#0B1C3F]">3. Message</h2>
      <p className="mb-4 text-[14px] text-[#475569]">Personnalisez le contenu de la notification que vos clients recevront.</p>
      {rem && (
        <div className="mb-4 grid grid-cols-2 gap-1 rounded-xl bg-[#F4F7FC] p-1" role="tablist">
          {[['main', 'Message principal'], ['rem', `Rappel (${tr.reminder.days_before} j avant)`]].map(([k, l]) => (
            <button key={k} type="button" role="tab" aria-selected={msgTab === k} onClick={() => setMsgTab(k)}
                    className={`rounded-lg py-2 text-[13px] font-semibold ${msgTab === k ? 'bg-white text-[#1463FF] shadow-[inset_0_-2px_0_#1463FF]' : 'text-[#475569]'}`}>{l}</button>
          ))}
        </div>
      )}
      <Label req>Titre de la notification</Label>
      <input ref={titleRef} className={field} value={cur.title} maxLength={TITLE_MAX} onFocus={() => { lastFocus.current = 'title'; }}
             onChange={(e) => setCur({ title: e.target.value })} placeholder={msgTab === 'rem' ? 'Ex. Bientôt votre anniversaire, {prénom} !' : 'Ex. Joyeux anniversaire {prénom} !'} />
      <span className="mt-1 block text-right text-[12px] text-[#64748B]">{cur.title.length}/{TITLE_MAX}</span>
      <Label req>Message</Label>
      <textarea ref={bodyRef} className={`${field} min-h-[96px] resize-y`} value={cur.body} maxLength={BODY_MAX} onFocus={() => { lastFocus.current = 'body'; }}
                onChange={(e) => setCur({ body: e.target.value })} placeholder="Ex. Une offre spéciale vous attend sur votre carte de fidélité 🎁" />
      <span className="mt-1 block text-right text-[12px] text-[#64748B]">{cur.body.length}/{BODY_MAX}</span>
      <p className="text-[14px] font-bold text-[#0B1C3F]">Variables personnalisées</p>
      <p className="mb-2 text-[12px] text-[#64748B]">Cliquez pour les ajouter à votre message.</p>
      <div className="flex flex-wrap items-center gap-2">
        {varsHere.map((v) => <button key={v} type="button" onClick={() => insert(`{${v}}`)} className="rounded-full bg-[#EEF4FF] px-3 py-1.5 text-[13px] font-medium text-[#1D4ED8] hover:bg-[#E0EAFF]">{`{${v}}`}</button>)}
        <span className="relative"><button type="button" onClick={() => setEmoji((x) => !x)} className="rounded-full bg-[#EEF4FF] px-3 py-1.5 text-[13px] font-medium text-[#1D4ED8]">😊 Emoji</button>
          {emoji && <span className="absolute left-0 top-9 z-20 grid w-64 grid-cols-8 gap-1 rounded-xl border border-[#E2E8F0] bg-white p-2 shadow-xl">
            {EMOJIS.map((e) => <button key={e} type="button" className="rounded p-1 text-[16px] hover:bg-[#F1F5F9]" onClick={() => { insert(e); setEmoji(false); }}>{e}</button>)}</span>}</span>
      </div>
      <div className="mt-4 rounded-2xl bg-[#F7FAFF] p-4">
        <div className="flex items-start gap-3"><Link2 size={20} className="mt-1 shrink-0 text-[#64748B]" />
          <span className="min-w-0 flex-1"><span className="block text-[14px] font-bold text-[#0B1C3F]">Lien d'action <span className="font-normal text-[#64748B]">(optionnel)</span></span>
            <span className="text-[12px] text-[#64748B]">Redirigez vos clients vers une offre, une page ou votre fiche Google — un bouton sur leur carte.</span></span>
          <Toggle label="Lien d'action" on={cur.button.enabled} onChange={(v) => setBtn({ enabled: v })} /></div>
        {cur.button.enabled && (
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="block"><Label right={`${cur.button.label.length}/${BUTTON_MAX}`}>Texte du bouton</Label>
              <input className={field} maxLength={BUTTON_MAX} value={cur.button.label} onChange={(e) => setBtn({ label: e.target.value })} placeholder="Voir l'offre" /></label>
            <label className="block"><Label>Destination</Label><Select label="Destination" value={cur.button.link_type} onChange={(v) => setBtn({ link_type: v })} options={LINKS} /></label>
            {cur.button.link_type === 'offer' && <label className="block sm:col-span-2"><Label>Offre</Label>
              <Select label="Offre" value={cur.button.offer_id} onChange={(v) => setBtn({ offer_id: v })} options={[['', 'Sélectionner une offre'], ...(page.offers || []).map((o) => [o.id, o.name])]} /></label>}
            {cur.button.link_type === 'url' && <label className="block sm:col-span-2"><Label>Adresse du lien</Label>
              <input className={field} inputMode="url" value={cur.button.url} onChange={(e) => setBtn({ url: e.target.value })} placeholder="https://" /></label>}
          </div>
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-4 rounded-2xl bg-[#F5F3FF] p-4">
        <Toggle label="Ajouter une image" on={Boolean(cur.image_url)} onChange={(v) => (v ? fileRef.current?.click() : setCur({ image_url: null }))} />
        <span className="min-w-0 flex-1"><span className="block text-[14px] font-bold text-[#0B1C3F]">Ajouter une image <span className="font-normal text-[#64748B]">(optionnel)</span></span>
          <span className="text-[12px] text-[#64748B]">Ajoutez une image pour rendre votre notification plus attractive.</span></span>
        {cur.image_url && <img src={cur.image_url} alt="" className="h-14 w-20 rounded-lg object-cover" />}
        {cur.image_url && <button type="button" onClick={() => fileRef.current?.click()} className="inline-flex items-center gap-1.5 rounded-xl border border-[#BFD3FF] bg-white px-3 py-2 text-[13px] font-semibold text-[#1463FF]"><ImageIcon size={15} /> Modifier</button>}
        <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="hidden" onChange={onImage} />
      </div>
    </section>
  );

  // ---- step 4 ------------------------------------------------------------------------------
  const ages = Array.from({ length: 83 }, (_, i) => String(i + 16));
  const Step4 = (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <h2 className="text-[22px] font-extrabold text-[#0B1C3F]">4. Ciblage</h2>
      <p className="mb-4 text-[14px] text-[#475569]">Choisissez quels clients doivent recevoir cette notification.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {PICKS.map((p) => {
          const on = tg.pick === p.key;
          const I = p.icon;
          return (
            <button key={p.key} type="button" aria-pressed={on} onClick={() => setTg({ pick: p.key })}
                    className={`flex items-start gap-3 rounded-2xl border p-4 text-left transition ${on ? 'border-[#2F6BFF] bg-[#F5F8FF] shadow-[0_0_0_1px_#2F6BFF]' : 'border-[#E6EEFB] hover:border-[#BFD3FF]'}`}>
              <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl" style={{ background: p.tone[0], color: p.tone[1] }}><I size={24} /></span>
              <span className="min-w-0 flex-1"><span className="block text-[15px] font-bold text-[#0B1C3F]">{p.title}</span><span className="text-[12.5px] text-[#64748B]">{p.sub}</span></span>
              {on ? <CheckCircle2 size={22} className="shrink-0 fill-[#1463FF] text-white" /> : <span className="h-5 w-5 shrink-0 rounded-full border-2 border-[#CBD5E1]" />}
            </button>
          );
        })}
      </div>
      {tg.pick === 'inactive' && <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-[#FFF1F2] p-3 text-[13px] text-[#0B1C3F]">Pas de visite depuis
        <span className="w-28"><Num label="Jours d'inactivité" value={tg.inactive_days} unit="jours" max={3650} onChange={(v) => setTg({ inactive_days: v })} /></span></div>}
      {tg.pick === 'points' && <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-[#FAF5FF] p-3 text-[13px] text-[#0B1C3F]">Entre
        <span className="w-32"><Num label="Points minimum" value={tg.filters.points_min} unit="pts" max={10000000} onChange={(v) => setF({ points_min: v })} /></span> et
        <span className="w-32"><Num label="Points maximum" value={tg.filters.points_max} unit="pts" max={10000000} onChange={(v) => setF({ points_max: v })} /></span>
        <span className="text-[11.5px] text-[#64748B]">(laissez vide : sans limite)</span></div>}
      {tg.pick === 'segment' && <div className="mt-3 max-w-md"><Select label="Segment" value={tg.segment} onChange={(v) => setTg({ segment: v })} options={[['', 'Choisir un segment'], ...(page.segments || []).map((x) => [x.key, x.label])]} /></div>}
      {tg.pick === 'stores' && <div className="mt-3">{storeChips(tg.filters.stores, (v) => setF({ stores: v }))}</div>}
      <div className="mt-5 rounded-2xl border border-[#E6EEFB]">
        <div className="p-3 pb-1"><p className="text-[15px] font-bold text-[#0B1C3F]">Filtres complémentaires <span className="font-normal text-[#64748B]">(optionnel)</span></p>
          <p className="text-[12.5px] text-[#64748B]">Affinez votre ciblage avec des critères supplémentaires.</p></div>
        <div className="grid gap-2 p-3 pt-2 xl:grid-cols-2">
        <FilterRow on={tg.on.age} onToggle={(v) => setOn('age', v)} icon={Cake} title="Âge du client">
          <span className="w-28"><Select label="Âge minimum" value={tg.filters.age_min || '18'} onChange={(v) => setF({ age_min: v })} options={ages.map((a) => [a, `${a} ans`])} /></span> à
          <span className="w-28"><Select label="Âge maximum" value={tg.filters.age_max || '65'} onChange={(v) => setF({ age_max: v })} options={ages.map((a) => [a, `${a} ans`])} /></span></FilterRow>
        {tg.pick !== 'points' && <FilterRow on={tg.on.points} onToggle={(v) => setOn('points', v)} icon={Star} title="Nombre de points">
          <span className="w-28"><Num label="Points min." value={tg.filters.points_min} max={10000000} onChange={(v) => setF({ points_min: v })} /></span> à
          <span className="w-28"><Num label="Points max." value={tg.filters.points_max} max={10000000} onChange={(v) => setF({ points_max: v })} /></span></FilterRow>}
        {tg.pick !== 'inactive' && <FilterRow on={tg.on.last} onToggle={(v) => setOn('last', v)} icon={CalendarDays} title="Date de dernière visite">
          <span className="w-44"><Select label="Il y a" value={tg.filters.last_visit_op} onChange={(v) => setF({ last_visit_op: v })} options={[['more', 'Il y a plus de'], ['less', 'Il y a moins de']]} /></span>
          <span className="w-24"><Num label="Jours" value={tg.filters.last_visit_days} max={3650} onChange={(v) => setF({ last_visit_days: v })} /></span> jours</FilterRow>}
        <FilterRow on={tg.on.spent} onToggle={(v) => setOn('spent', v)} icon={Euro} title="Montant total d'achats">
          <span className="w-28"><Num label="Montant min." value={tg.filters.spent_min} unit="€" onChange={(v) => setF({ spent_min: v })} /></span> à
          <span className="w-28"><Num label="Montant max." value={tg.filters.spent_max} unit="€" onChange={(v) => setF({ spent_max: v })} /></span></FilterRow>
        </div>
      </div>
    </section>
  );

  // ---- step 5 ------------------------------------------------------------------------------
  const dates = hasDate(tr) ? nextDates(tr, { ...sc, valid_to: sc.period || sc.expire ? sc.valid_to : '' }) : [];
  const planKind = tr.type === 'on_date' ? 'once' : tr.type === 'recurring' ? { weekly: 'week', monthly: 'month', yearly: 'year', custom: 'custom' }[tr.period] : null;
  const PlanCards = () => (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
      {[['once', 'Une fois', 'Envoyer une seule fois à une date précise.', CalendarDays], ['week', 'Chaque semaine', 'Répéter chaque semaine.', CalendarDays],
        ['month', 'Chaque mois', 'Répéter chaque mois.', CalendarDays], ['year', 'Chaque année', 'Répéter chaque année.', CalendarDays],
        ['custom', 'Personnalisé', 'Définir une fréquence avancée.', Settings2]].map(([k, t, sub, I]) => {
        const on = planKind === k;
        return (
          <button key={k} type="button" aria-pressed={on}
                  onClick={() => (k === 'once' ? (tr.type !== 'on_date' && setT({ ...TRIGGER_DEFAULTS.on_date() }))
                    : setT({ ...(tr.type === 'recurring' ? tr : TRIGGER_DEFAULTS.recurring()), period: { week: 'weekly', month: 'monthly', year: 'yearly', custom: 'custom' }[k] }))}
                  className={`relative rounded-2xl border p-3 text-left ${on ? 'border-[#2F6BFF] bg-[#F5F8FF] shadow-[0_0_0_1px_#2F6BFF]' : 'border-[#E6EEFB] hover:border-[#BFD3FF]'}`}>
            {on && <CheckCircle2 size={18} className="absolute right-2 top-2 fill-[#1463FF] text-white" />}
            <span className="flex items-center gap-2 text-[14px] font-bold text-[#0B1C3F]"><I size={18} className="text-[#1463FF]" />{t}</span>
            <span className="mt-1 block text-[11.5px] text-[#64748B]">{sub}</span>
          </button>
        );
      })}
    </div>
  );
  const PlanDates = () => (
    <div className="mt-4 rounded-2xl border border-[#E6EEFB] p-4">
      <p className="mb-3 text-[15px] font-bold text-[#0B1C3F]">{tr.type === 'on_date' ? 'Date et heure' : `Configuration ${{ weekly: 'hebdomadaire', monthly: 'mensuelle', yearly: 'annuelle', custom: 'personnalisée' }[tr.period]}`}</p>
      {tr.type === 'on_date' ? OnDateFields : (
        <div className="space-y-4">
          {tr.period === 'weekly' && (
            <div className="grid gap-3 sm:grid-cols-[1fr_200px]">
              <div><Label>Jours de la semaine</Label><div className="flex flex-wrap gap-1.5">{DAYS.map((d, i) => {
                const on = (tr.weekdays || []).includes(i);
                return <button key={d} type="button" aria-pressed={on} onClick={() => setT({ weekdays: on ? tr.weekdays.filter((x) => x !== i) : [...(tr.weekdays || []), i].sort() })}
                               className={`rounded-full px-3.5 py-2 text-[13px] font-semibold ${on ? 'bg-[#2F6BFF] text-white' : 'bg-[#F1F5F9] text-[#334155]'}`}>{d}</button>;
              })}</div></div>
              <label className="block"><Label>Heure d'envoi</Label><Select icon={Clock} label="Heure d'envoi" value={sc.hour} onChange={(v) => setSc({ hour: v })} options={HOURS.map((h) => [h, h])} /></label>
            </div>
          )}
          {tr.period !== 'weekly' && RecurrenceFields()}
          {tr.period === 'weekly' && (
            <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
              <label className="block"><Label>Commencer le</Label><input type="date" aria-label="Commencer le" className={field} value={sc.valid_from} min={today} onChange={(e) => setSc({ valid_from: e.target.value, period: true })} /></label>
              <label className="block"><Label>Se terminer <span className="font-normal text-[#64748B]">(optionnel)</span></Label>
                <input type="date" aria-label="Se terminer" className={field} disabled={!sc.valid_to && !sc.period} value={sc.valid_to} min={sc.valid_from || today} onChange={(e) => setSc({ valid_to: e.target.value, period: true })} /></label>
              <span className="flex items-center gap-2 pb-2 text-[13px] text-[#334155]"><Toggle label="Pas de date de fin" on={!sc.valid_to} onChange={(v) => setSc(v ? { valid_to: '' } : { valid_to: sc.valid_from || today, period: true })} /> Pas de date de fin</span>
            </div>
          )}
          {tr.period === 'weekly' && (
            <div className="rounded-2xl border border-[#E6EEFB]">
              <button type="button" onClick={() => setAdv((x) => !x)} className="flex w-full items-center justify-between p-3 text-[14.5px] font-bold text-[#0B1C3F]">Options avancées {adv ? <ChevronUp size={18} /> : <ChevronDown size={18} />}</button>
              {adv && (
                <div className="space-y-3 px-3 pb-3">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="block"><Label>Répéter toutes les</Label>
                      <span className="flex items-center gap-2"><span className="w-28"><Select label="Répéter toutes les" value={String(tr.every_weeks || 1)} onChange={(v) => setT({ every_weeks: Number(v) })} options={['1', '2', '3', '4'].map((x) => [x, x])} /></span> semaine(s)</span></label>
                    <label className="block"><Label>Fuseau horaire</Label><Select icon={Globe} label="Fuseau horaire" value={sc.tz} onChange={(v) => setSc({ tz: v })} options={TZ_OPTIONS} /></label>
                  </div>
                  <p className="flex items-center gap-2 rounded-xl bg-[#EEF4FF] p-3 text-[12.5px] text-[#334155]"><Info size={16} className="shrink-0 text-[#1463FF]" />
                    Cette notification sera envoyée {recurrenceText(tr, sc).replace(/^Chaque semaine · /, 'chaque ').replace(/^Toutes les/, 'toutes les')}{sc.valid_from ? ` à partir du ${frDate(sc.valid_from)}` : ''}.</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
  const PlanEvent = () => (
    <div className="space-y-4">
      {timed(tr) ? (
        <div className="rounded-2xl border border-[#E6EEFB] p-4"><p className="mb-3 text-[15px] font-bold text-[#0B1C3F]">Moment d'envoi</p>
          <p className="mb-3 text-[12.5px] text-[#64748B]">La condition est vérifiée chaque jour : la notification part à cette heure.</p>{HourTz}</div>
      ) : tr.type === 'geo' ? (
        <div className="rounded-2xl border border-[#E6EEFB] p-4"><p className="mb-1 text-[15px] font-bold text-[#0B1C3F]">Moment d'envoi</p>
          <p className="text-[13px] text-[#475569]">Immédiatement, quand le client entre dans la zone pendant la plage d'activation ({tr.from} – {tr.to}).</p>
          <div className="mt-3 max-w-sm"><Label>Fuseau horaire</Label><Select icon={Globe} label="Fuseau horaire" value={sc.tz} onChange={(v) => setSc({ tz: v })} options={TZ_OPTIONS} /></div></div>
      ) : (
        <div className="rounded-2xl border border-[#E6EEFB] p-4"><p className="mb-3 text-[15px] font-bold text-[#0B1C3F]">Moment d'envoi</p>
          {[['immediate', 'Immédiatement', 'Envoyer la notification dès que la condition est remplie.'], ['at', 'À une date/heure spécifique', "Programmer l'envoi à une date et une heure précises."]].map(([k, t, h]) => (
            <label key={k} className="mb-2 flex cursor-pointer items-start gap-3">
              <input type="radio" name="send_mode" checked={sc.send_mode === k} onChange={() => setSc({ send_mode: k })} className="mt-1 h-5 w-5 accent-[#1463FF]" />
              <span><span className="block text-[14px] font-semibold text-[#0B1C3F]">{t}</span><span className="text-[12px] text-[#64748B]">{h}</span></span>
            </label>
          ))}
          {sc.send_mode === 'at' && <div className="mt-2 grid gap-3 sm:grid-cols-2">
            <input type="datetime-local" aria-label="Date et heure d'envoi" className={field} value={sc.send_at} min={`${today}T00:00`} onChange={(e) => setSc({ send_at: e.target.value })} />
            <Select icon={Globe} label="Fuseau horaire" value={sc.tz} onChange={(v) => setSc({ tz: v })} options={TZ_OPTIONS} />
            <Help>Les actions d'ici là attendent ce moment ; ensuite, l'envoi est immédiat.</Help></div>}
          {tr.type === 'action' && Number(tr.delay_value) > 0 && <p className="mt-2 text-[12px] text-[#64748B]">Le délai de l'étape 2 ({tr.delay_value} {({ minutes: 'min', hours: 'h', days: 'jour(s)' })[tr.delay_unit]}) s'applique avant.</p>}
        </div>
      )}
      <div className="rounded-2xl border border-[#E6EEFB] p-4"><p className="text-[15px] font-bold text-[#0B1C3F]">Période d'activation <span className="font-normal text-[#64748B]">(optionnel)</span></p>
        <p className="mb-3 text-[12.5px] text-[#64748B]">Définissez une période pendant laquelle cette automatisation sera active.</p>
        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <label className="block"><Label>Commencer le</Label><input type="date" aria-label="Commencer le" className={field} value={sc.valid_from} min={today} onChange={(e) => setSc({ valid_from: e.target.value, period: true })} /></label>
          <label className="block"><Label>Se terminer le</Label><input type="date" aria-label="Se terminer le" className={field} value={sc.valid_to} disabled={!sc.valid_to && !sc.period} min={sc.valid_from || today} onChange={(e) => setSc({ valid_to: e.target.value, period: true, expire: true })} /></label>
          <span className="flex items-center gap-2 pb-2 text-[13px] text-[#334155]"><Toggle label="Pas de date de fin" on={!sc.valid_to} onChange={(v) => setSc(v ? { valid_to: '', expire: false } : { valid_to: sc.valid_from || today, period: true, expire: true })} /> Pas de date de fin</span>
        </div></div>
    </div>
  );
  const recapItems = () => {
    if (tr.type === 'on_date') return [[CalendarDays, 'Une date spécifique', `Le ${frDate(tr.date, true)} à ${sc.hour}`]];
    if (tr.type === 'recurring') {
      if (tr.period === 'weekly') return [[CalendarDays, 'Fréquence', Number(tr.every_weeks) > 1 ? `Toutes les ${tr.every_weeks} semaines` : 'Chaque semaine'], [CalendarDays, "Jours d'envoi", (tr.weekdays || []).map((d) => cap(DAY_FULL[d])).join(', ')], [Clock, "Heure d'envoi", sc.hour]];
      return [[CalendarClock, 'Récurrent', recurrenceText(tr, sc).split(' à ')[0]], [Clock, "Heure d'envoi", sc.hour], [Globe, 'Fuseau', (TIMEZONES.find(([k]) => k === sc.tz) || [])[1]]];
    }
    if (tr.type === 'action') return [[Store, 'Action', ACTION_LABEL[tr.action]], [Clock, 'Délai', Number(tr.delay_value) ? `${tr.delay_value} ${({ minutes: 'min', hours: 'h', days: Number(tr.delay_value) > 1 ? 'jours' : 'jour' })[tr.delay_unit]} après` : 'Immédiat'],
      [Send, "Contexte d'envoi", sc.window ? "Selon les heures d'envoi définies ci-dessous" : 'Toute la journée']];
    if (tr.type === 'loyalty') return [[Star, 'Condition sur la fidélité', ['points', 'visits', 'amount'].filter((k) => Number(tr[k]) > 0).map((k) => `${tr[k]} ${({ points: 'points', visits: 'visites', amount: '€' })[k]}`).join(tr.match === 'all' ? ' et ' : ' ou ') + ' ou plus'],
      [Clock, 'Moment de déclenchement', sc.send_mode === 'at' ? `Le ${sc.send_at.replace('T', ' à ')}` : 'Immédiat']];
    if (tr.type === 'behavior') return [[User, 'Comportement', tr.activity === 'active' ? 'Client actif' : 'Client inactif'], [Clock, tr.activity === 'active' ? 'Actif dans les' : 'Inactivité depuis', `${tr.value} ${({ days: 'jours', weeks: 'semaines', months: 'mois' })[tr.unit]}`], [Send, 'Envoi', `Chaque jour à ${sc.hour}`]];
    if (tr.type === 'geo') return [[MapPin, 'Événement', 'Entrée dans la zone'], [Target, 'Rayon', `${tr.radius_m} mètres`], [Store, 'Emplacement', tr.address || '—']];
    return [[Settings2, 'Type de déclencheur', 'Personnalisé'], [Sparkles, 'Description', tr.rule_name || '—']];
  };
  const Recap = (
    <div className="rounded-2xl border border-[#E6EEFB] bg-white p-4">
      <div className="mb-3 flex items-start gap-3">
        <span className="min-w-0 flex-1"><span className="block text-[17px] font-extrabold text-[#0B1C3F]">Récapitulatif du déclencheur</span>
          <span className="text-[12.5px] text-[#64748B]">Le déclencheur a été configuré à l'étape 2.</span></span>
        <button type="button" onClick={() => go(2)} className="inline-flex items-center gap-1.5 rounded-xl bg-[#EEF4FF] px-3.5 py-2 text-[13px] font-semibold text-[#1463FF]"><Pencil size={14} /> Modifier</button>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        {recapItems().map(([I, l, v]) => (
          <div key={l} className="flex items-center gap-3 rounded-xl bg-[#F7FAFF] p-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><I size={20} /></span>
            <span className="min-w-0"><span className="block text-[11.5px] text-[#64748B]">{l}</span><span className="block truncate text-[14px] font-bold text-[#0B1C3F]">{v || '—'}</span></span></div>
        ))}
      </div>
    </div>
  );
  const Rules = () => (
    <div className="space-y-4">
      {Recap}
      <div className="rounded-2xl border border-[#E6EEFB] p-4">
        <p className="text-[17px] font-extrabold text-[#0B1C3F]">Règles d'envoi</p>
        <p className="mb-3 text-[12.5px] text-[#64748B]">Définissez les limites d'envoi pour éviter la sur-sollicitation de vos clients.</p>
        <div className="flex flex-wrap items-start gap-3 border-b border-[#F1F5F9] pb-3">
          <Toggle label="Envoyer uniquement pendant ces heures" on={sc.window} onChange={(v) => setSc({ window: v })} />
          <span className="min-w-0 flex-1"><span className="block text-[14px] font-semibold text-[#0B1C3F]">Envoyer uniquement pendant ces heures</span>
            <span className="text-[12px] text-[#64748B]">{tr.type === 'geo' ? "Hors de cette plage, un passant ne reçoit rien." : timed(tr) ? "L'heure d'envoi doit se situer dans cette plage horaire." : 'Hors de cette plage, le message attend son ouverture.'}</span>
            {sc.window && <span className="mt-2 grid max-w-lg grid-cols-[1fr_auto_1fr] items-center gap-2">
              <Select icon={Clock} label="Heure de début" value={sc.window_from} onChange={(v) => setSc({ window_from: v })} options={HOURS.map((h) => [h, h])} />
              <span className="text-[13px] text-[#64748B]">à</span>
              <Select icon={Clock} label="Heure de fin" value={sc.window_to} onChange={(v) => setSc({ window_to: v })} options={[...HOURS, '23:59'].map((h) => [h, h])} /></span>}</span>
        </div>
        <div className="grid gap-3 border-b border-[#F1F5F9] py-3 sm:grid-cols-2">
          <label className="block"><Label hint="Nombre de notifications maximum envoyées à un même client.">Limite par client</Label>
            <Select label="Limite par client" value={sc.limit.per} onChange={(v) => setSc({ limit: { count: 1, per: v } })} options={LIMITS} /></label>
          <div><Label hint="Évite d'envoyer plusieurs fois la même notification au même client.">Éviter les doublons</Label>
            <span className="flex items-center gap-2"><Toggle label="Éviter les doublons" on={sc.dedupe} onChange={(v) => setSc({ dedupe: v })} />
              <span className="flex-1"><Select label="Ne pas renvoyer dans les" disabled={!sc.dedupe} value={String(sc.min_gap_days)} onChange={(v) => setSc({ min_gap_days: Number(v) })}
                                               options={GAPS.map((n) => [String(n), `dans les ${n} dernier${n > 1 ? 's' : ''} jour${n > 1 ? 's' : ''}`])} /></span></span></div>
        </div>
        <div className="flex flex-wrap items-start gap-3 border-b border-[#F1F5F9] py-3">
          <Toggle label="Expiration" on={sc.expire} onChange={(v) => setSc(v ? { expire: true, valid_to: sc.valid_to || (tr.type === 'on_date' && tr.date ? tr.date : today) } : { expire: false, valid_to: sc.period ? sc.valid_to : '' })} />
          <span className="min-w-0 flex-1"><span className="block text-[14px] font-semibold text-[#0B1C3F]">Expiration <span className="font-normal text-[#64748B]">(optionnel)</span></span>
            <span className="text-[12px] text-[#64748B]">Désactivez automatiquement cette notification après une certaine date (la même que « Se terminer le »).</span>
            <span className="mt-2 block max-w-xs"><input type="date" aria-label="Date d'expiration" className={field} disabled={!sc.expire} value={sc.valid_to} min={today} onChange={(e) => setSc({ valid_to: e.target.value })} /></span></span>
        </div>
        <label className="block pt-3"><Label>Conditions supplémentaires <span className="font-normal text-[#64748B]">(optionnelles)</span></Label>
          <span className="mb-1 block text-[12px] text-[#64748B]">Une note pour vous et votre équipe — elle n'est pas appliquée automatiquement.</span>
          <textarea className={`${field} min-h-[60px] resize-y`} maxLength={NOTE_MAX} value={sc.rules_note} onChange={(e) => setSc({ rules_note: e.target.value })}
                    placeholder="Ex. : uniquement pour les clients ayant plus de 3 achats, ne pas envoyer pendant les jours fériés, etc." />
          <span className="mt-1 block text-right text-[11.5px] text-[#64748B]">{sc.rules_note.length}/{NOTE_MAX}</span></label>
      </div>
    </div>
  );
  const Step5 = (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <h2 className="text-[22px] font-extrabold text-[#0B1C3F]">5. {sub5 === 'plan' ? 'Planification' : "Règles d'envoi"}</h2>
      <p className="mb-4 text-[14px] text-[#475569]">{sub5 === 'plan' ? 'Définissez quand et à quelle fréquence envoyer cette notification.' : "Définissez les règles d'envoi pour éviter la sur-sollicitation de vos clients."}</p>
      <div className="mb-4 grid grid-cols-2 gap-1 rounded-xl bg-[#F4F7FC] p-1" role="tablist" aria-label="Étape 5">
        {[['plan', 'Planification'], ['rules', "Règles d'envoi"]].map(([k, l], i) => (
          <button key={k} type="button" role="tab" aria-selected={sub5 === k} onClick={() => { if (k === 'rules' && problems(5).length && sub5 === 'plan') { setError(problems(5)[0]); return; } setSub5(k); setError(''); }}
                  className={`rounded-lg py-2 text-[13px] font-semibold ${sub5 === k ? 'bg-white text-[#1463FF] shadow-[inset_0_-2px_0_#1463FF]' : 'text-[#475569]'}`}>{i + 1}. {l}</button>
        ))}
      </div>
      {sub5 === 'plan' ? (hasDate(tr) ? <>{PlanCards()}{PlanDates()}</> : PlanEvent()) : Rules()}
    </section>
  );

  // ---- step 6 ------------------------------------------------------------------------------
  const pickText = () => {
    const p = PICKS.find((x) => x.key === tg.pick);
    if (tg.pick === 'inactive') return [`Clients inactifs depuis ${tg.inactive_days} jours`, 'Clients éligibles selon le dernier passage'];
    if (tg.pick === 'points') return [`Clients entre ${tg.filters.points_min || 0} et ${tg.filters.points_max || '∞'} points`, 'Selon leur carte de fidélité'];
    if (tg.pick === 'segment') return [`Segment : ${(page.segments || []).find((x) => x.key === tg.segment)?.label || '—'}`, "Conditions configurées à l'étape 4"];
    if (tg.pick === 'stores') return [`Clients de : ${stores.filter((x) => tg.filters.stores.includes(x.id)).map((x) => x.name).join(', ')}`, "Selon l'établissement fréquenté"];
    const extraF = ['age', 'points', 'last', 'spent'].filter((k) => tg.on[k]).length;
    return [p?.title === 'Tous les clients' ? 'Tous les clients éligibles' : p?.title, extraF ? `${extraF} filtre(s) complémentaire(s) · ${preview?.count ?? '…'} client(s)` : `Selon les filtres définis à l'étape 4 · ${preview?.count ?? '…'} client(s)`];
  };
  const rulesBoxes = () => {
    const lim = (LIMITS.find(([k]) => k === sc.limit.per) || [])[1];
    return [["Horaires autorisés", sc.window ? `${sc.window_from} – ${sc.window_to}` : 'Toute la journée'], ['Limite par client', lim === LIMITS[0][1] ? '1 / déclenchement' : lim],
      ['Anti-doublon', sc.dedupe ? `${sc.min_gap_days} jours` : 'Désactivé']];
  };
  const Step6 = (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <h2 className="text-[22px] font-extrabold text-[#0B1C3F]">6. Résumé</h2>
      <p className="mb-4 text-[14px] text-[#475569]">Vérifiez tous les paramètres de votre automatisation avant de l'enregistrer.</p>
      <div className="space-y-2.5">
        <ResRow icon={Settings2} tone={['#EEF4FF', '#1463FF']} title="Configuration" onEdit={can ? () => go(1) : null}>
          <span className="block text-[13.5px] font-semibold text-[#0B1C3F]">{s.name || '—'}</span>
          {s.description && <span className="block text-[12.5px] text-[#64748B]">{s.description}</span>}</ResRow>
        <ResRow icon={TRIGGER[tr.type].icon} tone={TRIGGER[tr.type].tone} title={`Déclencheur · ${TRIGGER[tr.type].title}`} onEdit={can ? () => go(2) : null}>
          <Boxes items={recapItems().map(([, l, v]) => [l, v])} /></ResRow>
        <ResRow icon={MessageSquare} tone={['#EEF4FF', '#1463FF']} title="Message" onEdit={can ? () => go(3) : null}>
          <span className="mt-1 block rounded-xl border border-[#E6EEFB] p-3"><b className="block text-[13.5px] text-[#0B1C3F]">{s.message.title || '—'}</b>
            <span className="text-[12.5px] text-[#475569]">{s.message.body || '—'}</span>
            {s.message.button.enabled && <span className="mt-1 block text-[12px] text-[#1463FF]">Bouton : {s.message.button.label}</span>}</span>
          {rem && <span className="mt-1 block text-[12px] text-[#64748B]">Rappel {tr.reminder.days_before} j avant : « {s.message_reminder.title} »</span>}</ResRow>
        <ResRow icon={Users} tone={['#DCFCE7', '#16A34A']} title="Ciblage" onEdit={can ? () => go(4) : null}>
          <span className="block text-[13.5px] font-semibold text-[#0B1C3F]">{pickText()[0]}</span><span className="block text-[12.5px] text-[#64748B]">{pickText()[1]}</span></ResRow>
        <ResRow icon={PieChart} tone={['#F3E8FF', '#9333EA']} title="Règles d'envoi" onEdit={can ? () => go(5, 'rules') : null}><Boxes items={rulesBoxes()} /></ResRow>
      </div>
      {allProblems.length
        ? <div className="mt-3 rounded-xl bg-[#FFF7ED] p-3 text-[12.5px] text-[#9A3412]"><b>À corriger avant l'activation :</b>
            <ul className="mt-1 list-disc pl-5">{allProblems.map(([n, p]) => <li key={p}><button type="button" onClick={() => { go(n, n === 5 ? 'rules' : undefined); setError(p); }} className="text-left underline">{p}</button></li>)}</ul></div>
        : <p className="mt-3 flex items-center gap-2 rounded-xl bg-[#ECFDF5] p-3 text-[12.5px] text-[#047857]"><Check size={16} /> Cette automatisation est prête à être enregistrée. Vérifiez les paramètres ci-dessus.</p>}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Toggle label="Activer après l'enregistrement" on={activate} onChange={setActivate} disabled={!can} />
        <span className="flex-1 text-[14px] font-semibold text-[#0B1C3F]">Activer après l'enregistrement</span>
        <button type="button" disabled={!can || !!busy} onClick={() => save('draft')} className="text-[12.5px] text-[#64748B] underline-offset-2 hover:underline">Ou enregistrer en brouillon</button>
      </div>
    </section>
  );

  // ---- the right column ----------------------------------------------------------------------
  const Phone = (heading, chip) => (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <div className="mb-3 flex items-center justify-between"><p className="text-[15px] font-bold text-[#0B1C3F]">{heading}</p>
        <span className="inline-flex items-center gap-1.5 rounded-lg bg-[#EEF4FF] px-2.5 py-1 text-[12px] font-semibold text-[#1463FF]"><Smartphone size={14} /> {chip}</span></div>
      <LockScreenPreview bare shop={page.shop} logo={page.logo_url} title={cur.title || 'Titre de votre notification'} body={cur.body || "Le message de votre automatisation s'affichera ici."}
                         image={cur.image_url} button={cur.button.enabled ? cur.button.label : ''} sample={sample} extra={extra} />
    </section>
  );
  const about = {
    on_date: ['À propos de ce déclencheur', <p key="a">La notification sera envoyée une seule fois, à la date et à l'heure que vous avez définies. Ce déclencheur est idéal pour les événements ponctuels comme une offre spéciale, un anniversaire ou une actualité importante.</p>,
      <Good key="b">Les notifications sont envoyées dans le fuseau horaire sélectionné, même si vos clients sont dans différentes zones.</Good>],
    recurring: [{ weekly: 'À propos du déclencheur récurrent', monthly: 'À propos du déclencheur mensuel', yearly: 'À propos du déclencheur annuel', custom: 'À propos du déclencheur personnalisé' }[tr.period],
      <p key="a">{{ weekly: 'Le déclencheur récurrent vous permet d’envoyer automatiquement votre notification selon une périodicité définie (hebdomadaire, mensuelle, annuelle ou personnalisée). Par exemple, une notification chaque semaine pour rappeler une offre ou mettre en avant vos nouveautés.',
        monthly: 'Le déclencheur mensuel envoie automatiquement une notification à des dates fixes chaque mois. Idéal pour une newsletter, présenter vos nouveautés ou annoncer une offre spéciale, une ou plusieurs fois par mois.',
        yearly: 'Le déclencheur annuel envoie automatiquement une notification une fois par an, à la même date. Idéal pour souhaiter un joyeux anniversaire à vos clients, fêter l’anniversaire de leur inscription ou mettre en avant un événement annuel (fêtes, ouverture, anniversaire de votre établissement).',
        custom: 'Le déclencheur personnalisé vous offre une grande flexibilité : tous les 10 jours, 2 fois par mois… Vous pouvez aussi limiter l’envoi à une période, par exemple pendant une campagne ou une saison.' }[tr.period]}</p>,
      <Good key="b" icon={tr.period === 'yearly' ? Lightbulb : tr.period === 'custom' ? BookOpen : CalendarDays}>{{ weekly: 'Les notifications récurrentes sont idéales pour entretenir la relation avec vos clients sur le long terme.', monthly: 'Par exemple, une newsletter le 1er et le 15 du mois vous permet de rester présent dans l’esprit de vos clients.', yearly: 'Activez un rappel avant la date pour envoyer une première notification quelques jours en amont.', custom: 'Idéal pour relancer vos clients tous les 10 jours, les informer 2 fois par mois ou activer une campagne temporaire.' }[tr.period]}</Good>],
    action: ['À propos de ce déclencheur', <p key="a">Cette notification est envoyée automatiquement après qu'un client ait réalisé une action spécifique dans votre établissement.</p>,
      <div key="b"><b className="text-[#0B1C3F]">Exemples d'actions :</b><ul className="mt-1 list-disc pl-5">{ACTIONS.map(([, l]) => <li key={l}>{l}</li>)}</ul></div>,
      <Good key="c" title="Astuce" icon={Lightbulb}>Utilisez des critères supplémentaires pour cibler uniquement certains types d'achats ou de clients.</Good>],
    loyalty: ['Informations', <p key="a">Cette automatisation se déclenche lorsque le client atteint un certain nombre de points, un nombre de visites ou un montant d'achats défini.</p>,
      <p key="b">Vous pouvez choisir d'envoyer la notification une seule fois ou de la répéter à chaque nouvelle atteinte des conditions.</p>],
    behavior: ['À propos de ce déclencheur', <p key="a">Le déclencheur « Comportement client » vous permet d'envoyer une notification en fonction du dernier passage de vos clients. C'est idéal pour réactiver les clients inactifs et les faire revenir dans votre établissement.</p>,
      <div key="b"><b className="text-[#0B1C3F]">Exemples d'utilisation :</b><ul className="mt-1 list-disc pl-5"><li>Relancer les clients inactifs depuis 30 jours</li><li>Proposer une offre spéciale aux clients absents</li><li>Fidéliser les clients qui n'ont plus visité depuis un certain temps</li></ul></div>],
    geo: ['Informations', <p key="a">La notification est envoyée lorsque le client entre dans la zone géographique définie. C'est idéal pour attirer les clients à proximité de votre établissement ou d'un événement avec des offres en temps réel, des promotions ou des invitations personnalisées.</p>,
      <Good key="b" icon={Info}>La détection dépend des autorisations du client (localisation, carte Wallet) et de l'activation de la géolocalisation dans Paramètres.</Good>],
    other: ['Informations sur ce déclencheur', <p key="a">L'option « Autre » vous permet de créer une règle personnalisée selon vos besoins spécifiques.</p>,
      <p key="b">Vous pouvez définir un événement, une condition et un délai d'envoi pour déclencher la notification exactement comme vous le souhaitez.</p>],
  }[tr.type];
  const exampleVars = [['{prénom}', sample?.first_name || 'Sarah'], ['{points}', String(sample?.points ?? 250)], ['{nom_commerce}', page.shop || 'Votre commerce'], ['{récompense}', extra['récompense']]];
  const aside = () => {
    if (step === 1) return <>{Phone('Aperçu de la notification', 'Push classique')}<Panel title="Bonnes pratiques" icon={Lightbulb}><Ticks items={['Utilisez un nom clair et reconnaissable.', "Expliquez l'objectif de cette automatisation.", 'Vous pourrez personnaliser le message et cibler vos clients dans les étapes suivantes.']} /></Panel></>;
    if (step === 2) return <>{tr.type !== 'geo' && Phone('Aperçu de la notification', 'Push classique')}<Panel title={about[0]}>{about.slice(1)}</Panel></>;
    if (step === 3) {
      return (<>{Phone('Aperçu de la notification', 'Push classique')}
        <Panel title="Bonnes pratiques" icon={Lightbulb}><p>Utilisez un titre court et accrocheur (max. {TITLE_MAX} caractères).</p>
          <Ticks items={['Personnalisez votre message avec le prénom du client.', "Ajoutez une image pour augmenter l'engagement.", 'Incluez un lien vers une offre ou une page pertinente.']} /></Panel>
        <Panel title="Exemple de variables remplacées" icon={Eye}>
          <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">{exampleVars.map(([k, v]) => <React.Fragment key={k}><span>{k}</span><span className="text-[#0B1C3F]">→ {v}</span></React.Fragment>)}</div></Panel></>);
    }
    if (step === 4) {
      return (<>
        <section className="rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
          <div className="mb-3 flex items-center justify-between"><p className="text-[15px] font-bold text-[#0B1C3F]">Aperçu du ciblage</p>
            <span className="rounded-lg bg-[#EEF4FF] px-2.5 py-1 text-[12px] font-semibold text-[#1463FF]">Estimation en temps réel</span></div>
          <div className="rounded-2xl bg-[#F7FAFF] p-5 text-center"><Users size={30} className="mx-auto text-[#1463FF]" />
            <p className="mt-1 text-[40px] font-extrabold leading-none text-[#0B1C3F]">{preview ? preview.count : '…'}</p>
            <p className="mt-1 text-[16px] font-semibold text-[#0B1C3F]">client{preview?.count === 1 ? '' : 's'} seront ciblé{preview?.count === 1 ? '' : 's'}</p>
            <p className="text-[12.5px] text-[#475569]">sur un total de <b>{preview?.total ?? '…'}</b> clients</p></div>
          <div className="mt-4 flex items-center justify-between"><p className="text-[14px] font-bold text-[#0B1C3F]">Exemples de clients ciblés</p>
            <button type="button" onClick={() => setListOpen(true)} className="rounded-lg bg-[#EEF4FF] px-2.5 py-1 text-[12px] font-semibold text-[#1463FF]">Voir la liste</button></div>
          <ul className="mt-2 space-y-2">{(preview?.examples || []).map((c, i) => (
            <li key={c.id} className="flex items-center gap-3"><span className="flex h-9 w-9 items-center justify-center rounded-full text-[14px] font-bold text-white" style={{ background: ['#A855F7', '#38BDF8', '#F59E0B'][i % 3] }}>{(c.name || '?').charAt(0)}</span>
              <span className="min-w-0"><span className="block text-[13.5px] font-semibold text-[#0B1C3F]">{c.name.split(' ')[0]} {c.name.split(' ')[1]?.charAt(0) ? `${c.name.split(' ')[1].charAt(0)}.` : ''}</span>
                <span className="text-[12px] text-[#64748B]">{c.points} points · Dernière visite : {c.last_visit ? new Date(c.last_visit).toLocaleDateString('fr-FR') : '—'}</span></span></li>
          ))}{preview && !preview.examples?.length && <li className="text-[12.5px] text-[#64748B]">Aucun client ne correspond pour l'instant.</li>}</ul>
        </section>
        <Panel title="À propos du ciblage"><p>Vous pouvez affiner votre ciblage pour envoyer la bonne notification aux bons clients. Cela permet d'améliorer l'efficacité de vos campagnes.</p></Panel></>);
    }
    if (step === 5) {
      const planPanel = hasDate(tr) && (
        <section className="rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
          <div className="mb-3 flex items-center justify-between"><p className="text-[15px] font-bold text-[#0B1C3F]">Aperçu de la planification</p>
            <button type="button" onClick={() => setSub5('plan')} className="inline-flex items-center gap-1.5 rounded-lg bg-[#EEF4FF] px-2.5 py-1 text-[12.5px] font-semibold text-[#1463FF]"><Pencil size={13} /> Modifier</button></div>
          <div className="rounded-2xl bg-[#F7FAFF] p-4 text-center"><CalendarDays size={30} className="mx-auto text-[#1463FF]" />
            <p className="mt-1 text-[20px] font-extrabold text-[#0B1C3F]">{tr.type === 'on_date' ? 'Date spécifique' : { weekly: 'Chaque semaine', monthly: 'Chaque mois', yearly: 'Chaque année', custom: 'Personnalisé' }[tr.period]}</p>
            <p className="text-[14px] text-[#334155]">{recurrenceText(tr, sc).split(' · ').slice(tr.type === 'on_date' ? 0 : 1).join(' · ') || recurrenceText(tr, sc)}</p>
            {sc.valid_from && <p className="text-[13px] text-[#475569]">À partir du {frDate(sc.valid_from)}</p>}</div>
          {tr.type !== 'on_date' && (
            <><p className="mb-2 mt-4 text-[14px] font-bold text-[#0B1C3F]">Prochaines dates d'envoi</p>
              {dates.length ? <ul className="space-y-1.5">{dates.map((d) => (
                <li key={d} className="flex items-center gap-3 text-[13.5px] text-[#334155]"><CalendarDays size={16} className="text-[#1463FF]" /><span className="flex-1">{cap(frDate(d, true))}</span><span>{sc.hour}</span></li>
              ))}</ul> : <p className="text-[12.5px] text-[#64748B]">{tr.period === 'yearly' ? 'Chaque client à sa propre date.' : 'Aucune date dans la période choisie.'}</p>}</>
          )}
        </section>
      );
      if (sub5 === 'plan') return <>{planPanel || Phone('Aperçu de la notification', 'Push classique')}<Panel title="Bonnes pratiques" icon={Lightbulb}><Ticks items={['Choisissez une heure où vos clients sont les plus actifs.', "Évitez d'envoyer trop de notifications.", 'Vous pourrez modifier la planification à tout moment.']} /></Panel></>;
      return (<>{planPanel}
        <Panel title={tr.type === 'behavior' ? 'À propos de ces règles' : 'Pourquoi ces règles sont importantes ?'} icon={Lightbulb}>
          <p>Ces paramètres vous aident à offrir une expérience positive à vos clients en évitant la sur-sollicitation.</p>
          <Ticks items={['Des envois au bon moment : uniquement pendant vos heures, quand vos clients sont les plus réceptifs.', 'Une fréquence maîtrisée : vous limitez le nombre de messages et espacez les notifications similaires.', 'Une expérience client préservée : moins de messages, plus d’impact.']} />
          {hasDate(tr) && <Good icon={Info}>La date et l'heure d'envoi proviennent du déclencheur défini à l'étape 2 : cette étape gère seulement les heures autorisées et l'anti-doublon.</Good>}</Panel></>);
    }
    return (<>{Phone('Aperçu de la notification', 'Aperçu illustratif')}
      <Panel title="Récapitulatif du déclencheur"><p><b className="text-[#0B1C3F]">{TRIGGER[tr.type].title}</b> — {s.description || TRIGGER[tr.type].sub}</p>
        <Good icon={Info}>{{ on_date: "Date et heure déjà définies à l'étape 2. Aucun second réglage requis ici.", recurring: "La fréquence, les jours et l'heure proviennent de l'étape 2.",
          action: `Le délai ${Number(tr.delay_value) ? `de ${tr.delay_value} ${({ minutes: 'min', hours: 'h', days: 'jour(s)' })[tr.delay_unit]} ` : ''}a été choisi à l'étape 2 et reste inchangé.`, loyalty: 'Un même palier ne génère pas de notifications répétées.',
          behavior: `Le seuil de ${tr.value} ${({ days: 'jours', weeks: 'semaines', months: 'mois' })[tr.unit]} vient de l'étape 2, sans reconfiguration ici.`, geo: 'La détection de présence dépend des autorisations et moyens techniques disponibles.',
          other: 'La règle personnalisée correspond à un événement réellement pris en charge.' }[tr.type]}</Good></Panel></>);
  };

  const stepLabel = (i) => (i === 4 ? (step === 5 && sub5 === 'rules' ? "Règles d'envoi" : 'Planification') : STEPS[i]);
  const geoWide = step === 2 && tr.type === 'geo';
  return (
    <div className="mx-auto max-w-[1400px] space-y-4 pb-4">
      <header className="flex items-start gap-4">
        <button type="button" aria-label="Retour" onClick={() => navigate('/dashboard/automations')} className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#EEF4FF] text-[#1463FF]"><ArrowLeft size={22} /></button>
        <div><h1 className="text-[26px] font-extrabold text-[#0B1C3F]">{editing ? `Modifier l'automatisation — ${row.name}` : 'Configurer votre nouvelle automatisation'}</h1>
          <p className="text-[14.5px] text-[#475569]">Créez une notification automatique pour fidéliser vos clients.</p></div>
      </header>
      <nav aria-label="Étapes" className="flex items-center gap-2 overflow-x-auto px-1 py-2">
        {STEPS.map((_, i) => {
          const n = i + 1;
          const done = n < step;
          const on = n === step;
          return (
            <React.Fragment key={n}>
              <button type="button" onClick={() => (n < step || (n > step && !allProblems.some(([m]) => m < n)) ? go(n) : null)} className="flex shrink-0 items-center gap-2.5">
                <span className={`flex h-9 w-9 items-center justify-center rounded-full text-[15px] font-bold ${done || on ? 'bg-[#1463FF] text-white' : 'bg-[#EEF2F8] text-[#475569]'}`}>{done ? <Check size={18} /> : n}</span>
                <span className={`text-[14.5px] ${on ? 'font-semibold text-[#1463FF] underline decoration-2 underline-offset-[6px]' : 'text-[#334155]'}`}>{stepLabel(i)}</span>
              </button>
              {n < 6 && <span className="h-px min-w-[24px] flex-1 bg-[#E2E8F0]" />}
            </React.Fragment>
          );
        })}
      </nav>
      {error && <p role="alert" className="rounded-xl bg-[#FEF2F2] px-4 py-2.5 text-[13px] text-[#B91C1C]">{error}</p>}
      {!can && <p className="rounded-xl bg-[#FFF7ED] px-4 py-2.5 text-[13px] text-[#9A3412]">Lecture seule : seuls le propriétaire et les administrateurs modifient les automatisations.</p>}
      <div className={`grid gap-4 ${geoWide ? 'xl:grid-cols-[minmax(0,1fr)_300px]' : 'lg:grid-cols-[minmax(0,1fr)_400px]'}`}>
        <fieldset disabled={!can} className="min-w-0 space-y-4">{[null, Step1, Step2, Step3, Step4, Step5, Step6][step]}</fieldset>
        <aside className="space-y-4">{geoWide ? Phone('Aperçu de la notification', 'Push classique') : null}{aside()}</aside>
      </div>
      <footer className="sticky bottom-0 z-30 -mx-2 rounded-2xl border border-[#E6EEFB] bg-white/95 px-4 py-3 shadow-[0_-12px_30px_-24px_rgba(11,28,63,.4)] backdrop-blur">
        <div className="flex items-center justify-between gap-3">
          <button type="button" onClick={back} className="inline-flex items-center gap-2 rounded-xl border border-[#D9E2F2] bg-white px-5 py-2.5 text-[15px] font-semibold text-[#334155]">
            <ArrowLeft size={17} /> {step === 1 ? 'Annuler' : 'Précédent'}</button>
          {step < 6 ? (
            <button type="button" onClick={next} className="inline-flex items-center gap-2 rounded-xl bg-[#1463FF] px-7 py-2.5 text-[15px] font-semibold text-white shadow-[0_10px_22px_-12px_rgba(20,99,255,.9)]">
              Suivant <ArrowRight size={17} /></button>
          ) : (
            <span className="flex items-center gap-2">
              <button type="button" disabled={!can || !!busy} onClick={() => save('draft')} className="rounded-xl border border-[#D9E2F2] bg-white px-5 py-2.5 text-[15px] font-semibold text-[#334155] disabled:opacity-60">
                {busy === 'draft' ? <Loader2 size={17} className="animate-spin" /> : 'Enregistrer en brouillon'}</button>
              <button type="button" disabled={!can || !!busy} onClick={() => save(activate ? 'active' : 'paused')}
                      className="inline-flex items-center gap-2 rounded-xl bg-[#1463FF] px-6 py-2.5 text-[15px] font-semibold text-white disabled:opacity-60">
                {busy && busy !== 'draft' ? <Loader2 size={17} className="animate-spin" /> : <Check size={17} />}
                {activate ? 'Enregistrer et activer' : 'Enregistrer (en pause)'} <ArrowRight size={17} /></button>
            </span>
          )}
        </div>
      </footer>
      {listOpen && (
        <div role="dialog" aria-modal="true" aria-label="Clients ciblés" className="fixed inset-0 z-50 flex items-center justify-center bg-[#0B1C3F]/40 p-4" onClick={() => setListOpen(false)}>
          <div className="max-h-[80vh] w-full max-w-lg overflow-hidden rounded-2xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-[#E6EEFB] p-4"><p className="text-[16px] font-bold text-[#0B1C3F]">Clients ciblés ({preview?.count ?? '…'})</p>
              <button type="button" aria-label="Fermer" onClick={() => setListOpen(false)}><X size={20} /></button></div>
            <ul className="max-h-[60vh] divide-y divide-[#F1F5F9] overflow-y-auto">
              {!preview?.list && <li className="flex items-center gap-2 p-4 text-[13px] text-[#64748B]"><Loader2 size={15} className="animate-spin" /> Chargement…</li>}
              {(preview?.list || []).map((c) => (
                <li key={c.id} className="flex items-center justify-between px-4 py-2.5 text-[13.5px]"><span className="font-semibold text-[#0B1C3F]">{c.name}</span>
                  <span className="text-[12px] text-[#64748B]">{c.points} pts · {c.last_visit ? new Date(c.last_visit).toLocaleDateString('fr-FR') : 'jamais venu'}</span></li>
              ))}
              {preview?.list && preview.count > preview.list.length && <li className="p-3 text-center text-[12px] text-[#64748B]">… et {preview.count - preview.list.length} autres</li>}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
