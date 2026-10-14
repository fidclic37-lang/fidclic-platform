import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft, ArrowRight, Check, Pencil, Info, CalendarDays, Clock, Users, Tags, Wallet, User, Smile, Image as ImageIcon, Hash, UserPlus,
  X, Loader2, Sparkles, Lightbulb, Power, MessageSquare, RefreshCw, MousePointerClick, MapPin, Euro, Repeat,
  Trophy, Plus, Trash2, Settings2, Briefcase, Link2, BarChart3, Globe, RotateCcw, ChevronDown, PlusCircle, Award,
  Footprints, CloudSun, Flag, Store, Star, Navigation, CheckCircle2, AlertTriangle, Eye, Bell,
  MoreHorizontal, Pause, Play, Copy, Filter, Hourglass, Smartphone, UserX, ArrowUp, Ban, Target, TrendingUp, Zap, List as ListIcon,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import LockScreenPreview from '../components/automations/LockScreenPreview';
import GeoZoneMap from '../components/automations/GeoZoneMap';
import NouvelleEditor from '../components/automations/NouvelleEditor';
import {
  ICONS, TONES, VAR_LABELS, VAR_SHORT, DAY_NAMES, GENDERS, AGES, SPENT, LAST_VISIT, RADII, EMPTY_FILTERS, asList, EXAMPLES,
  CLIENT_TYPES, AGE_STEPS,
  PASSANTS, RUSH, hLabel,
  EMPTY_EXCLUSIONS, INACTIVE_DAYS, PAST_FREQS, TIERS, LAST_OFFER, ORIGINS, VISITS_MIN, AGE_BARS, CHANNELS, STATUS,
} from '../components/automations/meta';
import { EMOJIS } from '../components/campagnes/kinds';

/**
 * « Créer / Modifier une automatisation » — the six steps of the user's
 * mockups (2026-10-11): Scénario, Déclencheur, Message, Ciblage,
 * Planification, Résumé. The preview and the summary stay on the right.
 * The server checks everything again (features/automations.clean).
 */
const STEPS = [['Scénario', ''], ['Déclencheur', "Quand l'envoyer ?"], ['Message', 'Personnalisez'], ['Ciblage', 'À qui ?'],
  ['Planification', 'Programmez'], ['Résumé', 'Vérifiez']];
const TITLE_MAX = 80;                // the palier mockups (user, 2026-10-11)
const BODY_MAX = 350;
const BUTTON_MAX = 30;
const HOURS = Array.from({ length: 48 }, (_, i) => `${String(Math.floor(i / 2)).padStart(2, '0')}:${i % 2 ? '30' : '00'}`);
const field = 'w-full rounded-xl border border-[#D9E2F2] bg-white px-3.5 py-2.5 !text-[15px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF] focus:ring-2 focus:ring-[#2F6BFF]/15 disabled:bg-[#F8FAFC]';
const LINK_RE = /^https?:\/\/[^\s/?#]+\.[^\s/?#]{2,}(?:[/?#]\S*)?$/i;
const fullLink = (raw) => {
  const s = String(raw || '').trim();
  if (!s) return '';
  return /^[a-z][a-z0-9+.-]*:/i.test(s) ? s : `https://${s.replace(/^\/+/, '')}`;
};

const TRIGGERS = {
  birthday: { offset_days: 0 },
  tier_up: { condition: 'points', threshold: 200, repeat: 'each', min_days: 7, custom_tiers: false, tiers: [] },
  welcome: {}, near_reward: { visits_left: 1 }, referral: { sides: ['parrain', 'filleul'] },
  geo: { cooldown_days: 7, weather: [], stores: [] },
  google_review: { type: 'after_visit', delay_value: 2, delay_unit: 'hours', frequency: 'once', every_days: 30, visits: 5, date: '', stop_after_click: true },
  inactive: { days: 30, repeat: 'once', every_days: 30 },
  custom: { type: 'after_visit', visits: 5, visits_repeat: 'once', cooldown_days: 0, date_mode: 'once', date: '', weekday: 0, monthday: 1 },
};
const WEEKDAYS_FR = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche'];
const MONTHS_FR = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
const UNIT = { minutes: ['minute', 'minutes'], hours: ['heure', 'heures'], days: ['jour', 'jours'] };
const span = (tr) => { const v = Number(tr.delay_value || 0); const [one, many] = UNIT[tr.delay_unit] || UNIT.hours; return `${v} ${v === 1 ? one : many}`; };
// the server's custom_text (features/automations.py), word for word
export const customText = (tr) => {
  if (tr.type === 'visits') {
    const n = Number(tr.visits || 0);
    if (tr.visits_repeat === 'every') return n === 1 ? 'À chaque visite' : `Toutes les ${n} visites`;
    return `À la ${n}${n === 1 ? 're' : 'e'} visite`;
  }
  if (tr.type === 'after_signup') return Number(tr.delay_value) ? `${span(tr)} après l'inscription` : "Dès l'inscription";
  if (tr.type === 'after_visit') {
    const base = Number(tr.delay_value) ? `${span(tr)} après chaque visite` : 'Après chaque visite';
    return base + (Number(tr.cooldown_days) ? ` · au plus tous les ${tr.cooldown_days} j` : '');
  }
  if (tr.type === 'date') {
    if (tr.date_mode === 'weekly') return `Chaque ${WEEKDAYS_FR[Number(tr.weekday || 0)]}`;
    if (tr.date_mode === 'monthly') { const n = Number(tr.monthday || 1); return `Le ${n}${n === 1 ? 'er' : ''} de chaque mois`; }
    if (!tr.date) return 'Date à choisir';
    const [y, mo, d] = tr.date.split('-').map(Number);
    const day = `${d}${d === 1 ? 'er' : ''} ${MONTHS_FR[mo - 1]}`;
    return tr.date_mode === 'yearly' ? `Chaque année le ${day}` : `Le ${day} ${y}`;
  }
  return 'Déclencheur personnalisé';
};
// the server's tier_text / palier_label (features/automations.py)
const UNIT_OF = { points: 'points', visits: 'visites', amount: '€' };
export const palierLabel = (cond, v) => {
  const n = Number(v) || 0;
  if (cond === 'points') return `${n} point${n > 1 ? 's' : ''}`;
  if (cond === 'visits') return `${n} visite${n > 1 ? 's' : ''}`;
  if (cond === 'amount') return `${n} €`;
  return String(v);
};
export const tierText = (tr) => {
  const cond = tr.condition || 'status';
  const rep = tr.repeat || 'each';
  const gap = rep === 'custom' ? ` · au moins ${Number(tr.min_days) || 1} j entre deux` : '';
  const first = rep === 'first' ? ' (première fois)' : '';
  if (cond === 'status') return (rep !== 'first' ? 'Nouveau statut (Bronze → Argent → Or → VIP)' : 'Premier changement de statut') + gap;
  if (tr.custom_tiers && tr.tiers?.length) {
    return `Paliers : ${[...tr.tiers].sort((a, b) => Number(a.value) - Number(b.value)).map((t) => t.value).join(', ')} ${UNIT_OF[cond]}${first}${gap}`;
  }
  const label = palierLabel(cond, tr.threshold);
  return (rep === 'first' ? `À ${label}` : `Tous les ${label}`) + gap;
};
// « Europe/Paris (GMT+2) » in summer, GMT+1 in winter
const parisOffset = () => {
  try {
    const t = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Paris', timeZoneName: 'shortOffset' }).formatToParts(new Date());
    return (t.find((x) => x.type === 'timeZoneName') || {}).value || 'GMT+1';
  } catch { return 'GMT+1'; }
};
const AVIS_IMAGE = '/automations/avis-google.png';
// Client inactif (mockups 2026-10-11): its chips, in the mockup's words
const INACTIVE_VARS = ['prénom', 'nom_commerce', 'offre', 'jours_absence', 'lien'];
const INACTIVE_VAR_LABELS = { 'prénom': 'Prénom', nom_commerce: 'Nom établissement', offre: 'Offre', jours_absence: "Jours d'inactivité", lien: 'Lien' };
// Bienvenue (mockups 2026-10-11): three steps, sent when the card lands in Wallet
const W_STEPS = [['Déclencheur', ''], ['Message', ''], ['Résumé', '']];
const WELCOME_VARS = ['prénom', 'nom_commerce', 'offre', 'lien'];
// Parrainage (mockups 2026-10-11): one automation, the parrain's and the filleul's messages
const R_STEPS = [['Déclencheur', ''], ['Message', ''], ['Résumé', '']];
const REF_VARS = ['prénom', 'nom_commerce', 'récompense', 'lien', 'amis_parraines'];
const REF_LABELS = { 'prénom': 'Prénom', nom_commerce: "Nom de l'établissement", 'récompense': 'Récompense', lien: 'Lien',
  amis_parraines: "Nombre d'amis parrainés", filleul: "Prénom de l'ami", parrain: "Prénom de l'ami" };
const FILLEUL_MSG = { title: 'Bienvenue et merci ! 🎉', body: 'Votre première visite est validée ! Vos points de parrainage ont été ajoutés à votre carte. 🎁' };
const REWARD_MODES = [['once', 'Une fois, à la visite qui valide'], ['every', 'À cette visite, puis à chaque visite'], ['first_then', 'Un bonus, puis un autre montant à chaque visite']];
// Récompense bientôt disponible (mockups 2026-10-11): its chips, per the card's programme
const nrVars = (unit) => (unit === 'tampons' ? ['prénom', 'nom_commerce', 'tampons', 'tampons_restants', 'récompense'] : ['prénom', 'nom_commerce', 'points', 'points_restants', 'récompense']);
const NR_VAR_LABELS = { 'prénom': 'Prénom', nom_commerce: 'Nom établissement', points: 'Nombre de points actuels', tampons: 'Tampons actuels',
  points_restants: 'Points restants', tampons_restants: 'Tampons restants', 'récompense': 'Récompense' };
const WELCOME_VAR_LABELS = { 'prénom': 'Prénom', nom_commerce: "Nom de l'établissement", offre: 'Offre', lien: 'Lien' };
const defaults = (sc, meta) => ({
  ...(sc === 'referral' ? { message_filleul: { title: FILLEUL_MSG.title, body: FILLEUL_MSG.body, image_url: null,
    button: { enabled: false, label: meta?.button || 'Voir mes points', link_type: 'card', offer_id: null, url: '' } } } : {}),
  scenario: sc, name: sc === 'google_review' ? "Demande d'avis Google" : sc === 'welcome' ? 'Bienvenue au nouveau client' : meta?.label || '', description: '', status: 'active',
  trigger: { delay_value: 0, delay_unit: 'hours', ...(TRIGGERS[sc] || {}) },
  // Avis Google (mockups 2026-10-11): the ready image and the « Laisser un avis » button
  message: { title: meta?.title || '', body: meta?.body || '', image_url: sc === 'google_review' ? AVIS_IMAGE : null,
    button: { enabled: sc === 'google_review', label: meta?.button || '', link_type: sc === 'tier_up' ? 'rewards' : sc === 'google_review' ? 'google_review' : 'card', offer_id: null, url: '' } },
  // a géolocalisation targets passers-by through its filters (« filtered »);
  // Client inactif's « Tous mes clients » keeps its filters (mockups 2026-10-11)
  targeting: { mode: ['geo', 'inactive', 'near_reward'].includes(sc) ? 'filtered' : 'all', segment: null, passants: 'all',
    filters: { ...EMPTY_FILTERS }, exclusions: { ...EMPTY_EXCLUSIONS } },
  schedule: sc === 'near_reward'
    ? { days: 'specific', weekdays: [0, 1, 2, 3, 4], hour: null, smart: false, window: true, window_from: '11:00', window_to: '20:00',
      slots: [], holidays: true, valid_from: '', valid_to: '', daily_limit: null }
    : sc === 'inactive'
    // the mockup's defaults: Lun – Ven, 11:00 – 20:00, at 14:00 from today, 200 per day at most
    ? { days: 'specific', weekdays: [0, 1, 2, 3, 4], hour: '14:00', smart: false, window: true, window_from: '11:00', window_to: '20:00',
      slots: [], holidays: true, valid_from: new Date().toISOString().slice(0, 10), valid_to: '', daily_limit: 200 }
    : sc === 'google_review'
    ? { days: 'specific', weekdays: [0, 1, 2, 3, 4], hour: '10:00', smart: false, window: true, window_from: '08:00', window_to: '20:00',
      slots: [], holidays: true, valid_from: new Date().toISOString().slice(0, 10), valid_to: '', daily_limit: null }
    : { days: 'all', weekdays: [0, 1, 2, 3, 4, 5, 6], hour: '10:00', smart: false,
      window: meta?.kind !== 'time' && sc !== 'geo', window_from: '09:00', window_to: '21:00',
      slots: [], holidays: true, valid_from: '', valid_to: '', daily_limit: null },
});
const DAY_FULL = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche'];
const frDate = (iso) => (iso ? iso.split('-').reverse().join('/') : '');
const overlaps = (slot, busy) => {
  if (!busy) return false;
  const h = (x) => Number(String(x).split(':')[0]);
  const a = h(slot[2]); let b = h(slot[3]); if (b <= a) b += 24;
  return a < busy[1] && busy[0] < b;
};
const hasSlot = (sc, from, to) => sc.window && (sc.slots || []).some((x) => x.from === from && x.to === to);

// a filter of step 4, as the Avis Google mockup draws it: icon, label, one dropdown
function FilterTile({ icon: I, label, children, wide }) {
  return (
    <div className={`flex items-start gap-2.5 rounded-2xl border border-[#E6EEFB] bg-[#FAFCFF] p-3 sm:col-span-1 ${wide ? 'xl:col-span-3' : 'xl:col-span-2'}`}>
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><I size={18} /></span>
      <span className="min-w-0 flex-1"><span className="mb-1 block text-[12.5px] font-semibold text-[#0B1C3F]">{label}</span>{children}</span>
    </div>
  );
}
// one dropdown value for a list filter; an older multi-tick value still shows
const one = (vals) => (vals.length === 1 ? vals[0] : vals.length > 1 ? '__multi' : '');
const withMulti = (vals, opts) => (vals.length > 1 ? [...opts, ['__multi', `${vals.length} choix`]] : opts);

// « Tous les âges » / « 18 – 25 ans, 26 – 35 ans » — a dropdown of ticks (step 2 conditions)
function MultiPick({ label, icon: I, options, values, onChange, allLabel }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);
  const text = values.length ? options.filter(([k]) => values.includes(k)).map(([, l]) => l).join(', ') : allLabel;
  return (
    <div ref={ref} className="relative rounded-2xl border border-[#E6EEFB] p-3">
      <p className="mb-1.5 flex items-center gap-2 text-[12.5px] font-semibold text-[#0B1C3F]">{I && <I size={15} className="text-[#1463FF]" />}{label}</p>
      <button type="button" aria-haspopup="listbox" aria-expanded={open} aria-label={label} onClick={() => setOpen((v) => !v)}
              className={`${field} flex items-center justify-between gap-2 !py-2 text-left`}>
        <span className="min-w-0 truncate !text-[13px]">{text}</span><ChevronDown size={15} className="shrink-0 text-[#475569]" />
      </button>
      {open && (
        <div role="listbox" aria-multiselectable="true" className="absolute left-3 right-3 top-full z-30 mt-1 rounded-xl border border-[#E2E8F0] bg-white p-1.5 shadow-xl">
          <label className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-[12.5px] hover:bg-[#F8FAFC]">
            <input type="checkbox" className="h-4 w-4 accent-[#1463FF]" checked={!values.length} onChange={() => onChange([])} /> {allLabel}</label>
          {options.map(([k, l]) => (
            <label key={k} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-[12.5px] hover:bg-[#F8FAFC]">
              <input type="checkbox" className="h-4 w-4 accent-[#1463FF]" checked={values.includes(k)}
                     onChange={() => onChange(values.includes(k) ? values.filter((x) => x !== k) : [...values, k])} /> {l}</label>
          ))}
        </div>
      )}
    </div>
  );
}

// a row of ticks with « Tous » first (step 4 of a géolocalisation)
function ChipRow({ title, sub, options, values, onChange, allLabel = 'Tous' }) {
  const chip = (on) => `flex items-center gap-2 rounded-xl border px-3 py-2 text-[12.5px] font-medium ${on ? 'border-[#2F6BFF] bg-[#F5F8FF] text-[#0B1C3F]' : 'border-[#E2E8F0] bg-white text-[#334155] hover:border-[#BFD3FF]'}`;
  return (
    <div className="mt-4">
      <p className="text-[13.5px] font-bold text-[#0B1C3F]">{title}</p>
      {sub && <p className="mb-2 text-[12px] text-[#64748B]">{sub}</p>}
      <div className="flex flex-wrap gap-2" role="group" aria-label={title}>
        <label className={chip(!values.length)}><input type="checkbox" className="h-4 w-4 accent-[#1463FF]" checked={!values.length} onChange={() => onChange([])} /> {allLabel}</label>
        {options.map(([k, l]) => (
          <label key={k} className={chip(values.includes(k))}>
            <input type="checkbox" className="h-4 w-4 accent-[#1463FF]" checked={values.includes(k)}
                   onChange={() => onChange(values.includes(k) ? values.filter((x) => x !== k) : [...values, k])} /> {l}</label>
        ))}
      </div>
    </div>
  );
}

const Toggle = ({ on, onChange, label, disabled }) => (
  <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)}
          className={`relative h-7 w-12 shrink-0 rounded-full transition disabled:opacity-50 ${on ? 'bg-[#2F6BFF]' : 'bg-[#D6DEEA]'}`}>
    <span className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition ${on ? 'left-6' : 'left-1'}`} />
  </button>
);
const Radio = ({ on }) => (
  <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 ${on ? 'border-[#1463FF]' : 'border-[#CBD5E1]'}`}>
    {on && <span className="h-2.5 w-2.5 rounded-full bg-[#1463FF]" />}
  </span>
);
const Label = ({ children, right }) => (
  <span className="mb-1.5 flex items-center justify-between text-[13px] font-semibold text-[#0B1C3F]">
    <span>{children}</span>{right && <span className="text-[11.5px] font-normal text-[#64748B]">{right}</span>}
  </span>
);
function Card({ n, title, sub, children }) {
  return (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <header className="mb-4 flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#1463FF] text-[16px] font-bold text-white">{n}</span>
        <div><h2 className="text-[18px] font-extrabold text-[#0B1C3F]">{title}</h2>
          {sub && <p className="text-[13px] text-[#475569]">{sub}</p>}</div>
      </header>
      {children}
    </section>
  );
}
function Option({ on, onClick, icon: I, title, sub, children, disabled }) {
  return (
    <div className={`rounded-2xl border p-4 transition ${on ? 'border-[#2F6BFF] bg-[#F5F8FF]' : 'border-[#E2E8F0] bg-white hover:border-[#BFD3FF]'}`}>
      <button type="button" disabled={disabled} onClick={onClick} className="flex w-full items-start gap-3 text-left">
        {I && <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><I size={18} /></span>}
        <span className="min-w-0 flex-1"><span className="block text-[13.5px] font-bold text-[#0B1C3F]">{title}</span>
          {sub && <span className="block text-[12px] text-[#64748B]">{sub}</span>}</span>
        <Radio on={on} />
      </button>
      {on && children && <div className="mt-3">{children}</div>}
    </div>
  );
}
function Select({ value, onChange, options, label, disabled, tight }) {
  return (
    <select aria-label={label} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}
            className={`${field} appearance-none bg-[length:14px] bg-no-repeat ${tight ? '!pl-2.5 !pr-7 bg-[right_8px_center]' : 'bg-[right_12px_center] pr-9'}`}
            style={{ backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%230B1C3F' stroke-width='2.5'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")" }}>
      {options.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
    </select>
  );
}
function Num({ value, onChange, min, max, label, disabled, digits = 3 }) {
  return (
    <input inputMode="numeric" aria-label={label} disabled={disabled} value={value ?? ''}
           onChange={(e) => onChange(e.target.value.replace(/\D/g, '').slice(0, digits))}
           onBlur={() => { const n = Number(value); if (value !== '' && Number.isFinite(n)) onChange(String(Math.min(max, Math.max(min, n)))); }}
           className={`${field} ${digits > 3 ? '!w-28' : '!w-20'} shrink-0 text-center`} />
  );
}

export default function AutomationEditorPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const editing = Boolean(id);
  const [page, setPage] = useState(null);
  const [s, setS] = useState(null);
  const [step, setStep] = useState(1);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [preview, setPreview] = useState(null);
  const [emoji, setEmoji] = useState('');
  const [tierTab, setTierTab] = useState(0);          // the palier whose words are being written (step 3)
  const [varMenu, setVarMenu] = useState('');         // « Insérer une variable »: 'title' | 'body' | ''
  const [row, setRow] = useState(null);               // the saved automation (its results)
  const [zone, setZone] = useState(null);             // géolocalisation: detections + weather now
  const [links, setLinks] = useState({});             // Avis Google: the shop's (or each établissement's) link
  const [menuOpen, setMenuOpen] = useState(false);    // the header's « ••• » (Client inactif mockups)
  const [pvTab, setPvTab] = useState('mobile');       // Bienvenue: « Aperçu sur mobile » / « Aperçu Wallet »
  const [refSide, setRefSide] = useState('parrain');  // Parrainage: the message being written
  const [refCfg, setRefCfg] = useState(null);         // Parrainage: the programme's rules (« Récompenses »)
  const [refEdit, setRefEdit] = useState(false);
  const [refDirty, setRefDirty] = useState(false);
  const titleRef = useRef(null);
  const bodyRef = useRef(null);
  const fileRef = useRef(null);
  const lastFocus = useRef('body');

  // the shop's one radius, and the establishments as an explicit list of ticks (none saved = all)
  const geoInit = (trig, data) => {
    const ids = (data.geo?.anchors || []).map((a) => a.id);
    trig.radius_m = data.geo?.radius_m || 200;
    trig.weather = trig.weather || [];
    trig.stores = (trig.stores || []).filter((x) => ids.includes(x));
    if (!trig.stores.length) trig.stores = ids;
  };
  useEffect(() => {
    ownerAPI.automations().then(({ data }) => {
      setPage(data);
      setLinks(data.google?.links || {});
      if (data.referral) setRefCfg({ ...data.referral });
      const meta = Object.fromEntries(data.scenarios.map((x) => [x.key, x]));
      if (editing) {
        const row = data.rows.find((r) => r.id === id);
        if (!row) { setError('Automatisation introuvable.'); return; }
        const d = defaults(row.scenario, meta[row.scenario]);
        const rf = row.targeting?.filters || {};
        const trig = { ...d.trigger, ...row.trigger };
        // a palier carried over from before the redesign has no condition: it is the statut
        if (row.scenario === 'tier_up' && !row.trigger?.condition) trig.condition = 'status';
        if (row.scenario === 'tier_up') trig.tiers = (trig.tiers || []).map((t) => ({ ...t, value: String(t.value), reward: t.reward || '' }));
        if (row.scenario === 'geo') geoInit(trig, data);
        if (row.scenario === 'referral' && !Array.isArray(trig.sides)) trig.sides = [trig.side || 'parrain'];
        if (row.scenario === 'near_reward' && (trig.threshold === undefined || trig.threshold === null)) {
          // saved before the mockups (« X visites »): the seuil is proposed, saving switches to it
          trig.legacy_visits = trig.visits_left || 1;
          trig.threshold = data.near?.unit === 'tampons' ? String(trig.visits_left || 1) : '10';
        }
        if (row.scenario === 'google_review') {                     // before the mockups: « après chaque visite »
          trig.type = trig.type || 'after_visit';
          if (trig.frequency === 'every_scan') { trig.frequency = 'days'; trig.every_days = 1; }
        }
        setS({ ...d, name: row.name, description: row.description || '', status: row.status === 'ended' ? 'active' : row.status, trigger: trig,
          message: { ...d.message, ...row.message, button: { ...d.message.button, ...(row.message?.button || {}), url: row.message?.button?.url || '' } },
          ...(row.scenario === 'referral' ? { message_filleul: { ...d.message_filleul, ...(row.message_filleul || {}),
            button: { ...d.message_filleul.button, ...(row.message_filleul?.button || {}), url: row.message_filleul?.button?.url || '' } } } : {}),
          targeting: { ...d.targeting, ...row.targeting, filters: {
            gender: asList(rf.gender, GENDERS), age: asList(rf.age, AGES), client_type: asList(rf.client_type, CLIENT_TYPES),
            visits_min: rf.visits_min ?? '', visits_max: rf.visits_max ?? '', age_min: rf.age_min ?? '', age_max: rf.age_max ?? '',
            spent: asList(rf.spent, SPENT), last_visit: asList(rf.last_visit, LAST_VISIT), stores: rf.stores || [],
            radius_km: rf.radius_km || null, past_freq: asList(rf.past_freq, PAST_FREQS), tiers: asList(rf.tiers, TIERS),
            origin: asList(rf.origin, ORIGINS), last_offer: asList(rf.last_offer, LAST_OFFER),
            activity: rf.activity || [], signed_since: rf.signed_since || '' },
            exclusions: { ...EMPTY_EXCLUSIONS, ...(row.targeting?.exclusions || {}) },
            // a Client inactif / Récompense bientôt disponible saved as « Tous mes clients » reads its filters now
            ...(['inactive', 'near_reward'].includes(row.scenario) && (row.targeting?.mode || 'all') === 'all' ? { mode: 'filtered' } : {}) },
          schedule: { ...d.schedule, ...row.schedule, hour: row.schedule?.hour || '10:00', slots: row.schedule?.slots || [],
            valid_from: row.schedule?.valid_from || '', valid_to: row.schedule?.valid_to || '',
            holidays: row.schedule?.holidays !== false, daily_limit: row.schedule?.daily_limit ?? null,
            // Client inactif before its mockups: no plage — the whole day around its hour
            // an event automation sent at once before: the whole day, so nothing changes
            ...(row.scenario === 'near_reward' && !row.schedule?.window ? { window: true, window_from: '00:00', window_to: '23:59' } : {}),
            ...(row.scenario === 'inactive' && !row.schedule?.window ? (() => {
              const h = row.schedule?.hour || '10:00';
              return { window: true, window_from: h < '08:00' ? h : '08:00', window_to: h >= '21:00' ? '23:59' : '21:00' };
            })() : {}) } });
        setRow(row);
        const q = new URLSearchParams(location.search);
        if (q.get('step')) setStep(Math.min(6, Math.max(1, Number(q.get('step')) || 1)));
      } else {
        const q = new URLSearchParams(location.search);
        const sc = meta[q.get('scenario')] ? q.get('scenario') : 'custom';
        const d = defaults(sc, meta[sc]);
        const ai = location.state?.ai;
        if (ai?.title) d.message = { ...d.message, title: ai.title.slice(0, TITLE_MAX), body: (ai.body || '').slice(0, BODY_MAX) };
        if (ai?.title && sc === 'custom') d.name = ai.title.replace(/\{[^}]*\}/g, '').replace(/\s+/g, ' ').trim().slice(0, 60) || d.name;
        if (sc === 'geo') geoInit(d.trigger, data);
        if (sc === 'near_reward') {
          d.trigger = { ...d.trigger, threshold: data.near?.unit === 'tampons' ? '1' : '10' };
          // a stamps card speaks of tampons
          if (data.near?.unit === 'tampons') d.message = { ...d.message, title: d.message.title.replace('points', 'tampons'), body: d.message.body.replace('{points_restants}', '{tampons_restants}') };
        }
        const ex = EXAMPLES[Number(q.get('ex'))];
        if (ex && ex.scenario === sc) d.message = { ...d.message, title: ex.title, body: ex.body, button: { ...d.message.button, label: ex.button } };
        setS(d);
        if (q.get('step')) setStep(Math.min(6, Math.max(1, Number(q.get('step')) || 1)));
      }
    }).catch((e) => setError(e?.response?.data?.detail || 'Impossible de charger les automatisations.'));
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const meta = useMemo(() => Object.fromEntries((page?.scenarios || []).map((x) => [x.key, x])), [page]);
  const m = s ? meta[s.scenario] : null;
  const can = Boolean(page?.can_edit);
  const timed = m?.kind === 'time' || (['custom', 'google_review'].includes(s?.scenario) && s?.trigger?.type === 'date');
  const set = (patch) => setS((o) => ({ ...o, ...patch }));
  const setIn = (key, patch) => setS((o) => ({ ...o, [key]: { ...o[key], ...patch } }));
  const setMsg = (patch) => setS((o) => ({ ...o, message: { ...o.message, ...patch } }));
  const setBtn = (patch) => setS((o) => ({ ...o, message: { ...o.message, button: { ...o.message.button, ...patch } } }));
  const setF = (patch) => setS((o) => ({ ...o, targeting: { ...o.targeting, filters: { ...o.targeting.filters, ...patch } } }));
  const pick = (key) => (v) => { if (v !== '__multi') setF({ [key]: v ? [v] : [] }); };

  // ---- the live count (step 4) ---------------------------------------------------
  const tKey = s ? JSON.stringify([s.scenario, s.targeting, s.scenario === 'inactive' ? s.trigger.days : s.scenario === 'near_reward' ? s.trigger.threshold : 0]) : '';
  useEffect(() => {
    if (!s) return undefined;
    let alive = true;
    const t0 = setTimeout(() => {
      if (s.targeting.mode === 'segment' && !s.targeting.segment) { setPreview({ count: 0, sample: preview?.sample }); return; }
      ownerAPI.automationPreview({ scenario: s.scenario, targeting: s.targeting,
        ...(s.scenario === 'inactive' ? { trigger: { days: Number(s.trigger.days) || 30 } }
          : s.scenario === 'near_reward' ? { trigger: { threshold: Number(s.trigger.threshold) || 10 } } : {}) })
        .then(({ data }) => { if (alive) setPreview(data); }).catch(() => { if (alive) setPreview(null); });
    }, 250);
    return () => { alive = false; clearTimeout(t0); };
  }, [tKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // géolocalisation: the clients detected near the shops (7 days) and the weather now
  const geoOn = s?.scenario === 'geo';
  useEffect(() => {
    if (!geoOn) return;
    ownerAPI.automationGeoZone().then(({ data }) => setZone(data)).catch(() => setZone({ points: [], clients_week: 0, clients_today: 0 }));
  }, [geoOn]);

  if (error && !s) return <p role="alert" className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13px] text-[#B91C1C]">{error}</p>;
  if (!s || !page || !m) {
    return <div className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</div>;
  }
  // « Nouvelle automatisation » (29 mockups, 2026-10-11): the owner's own automation, its own editor
  if (s.scenario === 'custom' && (!editing || row)) {
    return <NouvelleEditor key={row?.id || 'new'} page={page} row={editing ? row : null} ai={location.state?.ai} />;
  }

  const tr = s.trigger;
  const welcomeOn = s.scenario === 'welcome';
  const nrOn = s.scenario === 'near_reward';
  const refOn = s.scenario === 'referral';
  const near = page.near || { unit: 'points', card_goal: null, card_reward: 'votre récompense', tiers: [] };
  const lastStep = welcomeOn || s.scenario === 'referral' ? 3 : 6;
  const googleStores = page.google?.stores || [];
  const googleKeys = googleStores.length > 1 ? googleStores.map((b) => b.id) : ['main'];
  const msg = s.message;
  const btn = msg.button;
  const tg = s.targeting;
  const f = tg.filters;
  const sc = s.schedule;
  const variables = m.variables || [];
  // paliers personnalisés: each palier writes its own title and message
  const tiered = s.scenario === 'tier_up' && tr.condition !== 'status' && tr.custom_tiers;
  const tabIx = tiered ? Math.min(tierTab, Math.max(0, tr.tiers.length - 1)) : 0;
  const refFil = refOn && refSide === 'filleul';
  const cur = tiered ? (tr.tiers[tabIx] || { title: '', body: '' }) : refFil ? (s.message_filleul || { title: '', body: '' }) : msg;
  const setCur = (patch) => (tiered
    ? setS((o) => ({ ...o, trigger: { ...o.trigger, tiers: o.trigger.tiers.map((t, i) => (i === tabIx ? { ...t, ...patch } : t)) } }))
    : refFil ? setS((o) => ({ ...o, message_filleul: { ...o.message_filleul, ...patch } }))
      : setMsg(patch));

  // ---- the summary lines -----------------------------------------------------------
  const triggerText = () => {
    if (s.scenario === 'birthday') {
      const o = Number(tr.offset_days || 0);
      return o === 0 ? "Date d'anniversaire (le jour même)" : o < 0 ? `${-o} jour${o < -1 ? 's' : ''} avant l'anniversaire` : `${o} jour${o > 1 ? 's' : ''} après l'anniversaire`;
    }
    if (s.scenario === 'near_reward') return `À ${tr.visits_left || 1} visite${Number(tr.visits_left) > 1 ? 's' : ''} de la récompense`;
    if (s.scenario === 'inactive') return `Après ${tr.days || 30} jours sans visite${tr.repeat === 'every' ? `, puis tous les ${tr.every_days || 30} j` : ''}`;
    if (s.scenario === 'referral') return `Récompense de parrainage gagnée · ${tr.side === 'filleul' ? 'au filleul' : 'au parrain'}`;
    if (s.scenario === 'google_review') {
      const u = tr.delay_unit === 'days' ? (Number(tr.delay_value) === 1 ? 'jour' : 'jours') : (Number(tr.delay_value) === 1 ? 'heure' : 'heures');
      const after = Number(tr.delay_value) > 0 ? `${tr.delay_value} ${u} après` : 'juste après';
      if (tr.type === 'loyal') return `Client fidèle · ${after} la ${tr.visits || '?'}${Number(tr.visits) === 1 ? 're' : 'e'} visite`;
      if (tr.type === 'date') return tr.date ? `Le ${frDate(tr.date)} à ${sc.hour}` : 'Date à choisir';
      return `Après la visite · ${after} la dernière visite`;
    }
    if (s.scenario === 'geo') return `Entrée dans la zone · ${tr.radius_m || 200} m (au plus tous les ${tr.cooldown_days || 7} j)`;
    if (s.scenario === 'custom') return customText(tr);
    if (s.scenario === 'tier_up') return tierText(tr);
    return m.trigger_label;
  };
  const delayText = () => (!timed && !['geo', 'custom', 'google_review'].includes(s.scenario) && Number(tr.delay_value) > 0
    ? ` · ${tr.delay_value} ${{ minutes: 'min', hours: 'h', days: 'j' }[tr.delay_unit] || 'h'} après` : '');
  const filterChips = () => {
    const nm = (vals, opts) => vals.map((v) => (opts.find((x) => x[0] === v) || [])[1]).filter(Boolean);
    return [...nm(f.gender, GENDERS), ...nm(f.age, AGES), ...nm(f.client_type || [], CLIENT_TYPES), ...nm(f.spent, SPENT),
      ...nm(f.last_visit, LAST_VISIT).map((x) => `Dernière visite : ${x.toLowerCase()}`),
      ...(f.age_min !== '' || f.age_max !== '' ? [`Âge : ${f.age_min || 'tous'} – ${f.age_max || '65+'}`] : []),
      ...(f.visits_min !== '' || f.visits_max !== '' ? [`${f.visits_min || 0}${f.visits_max !== '' ? ` à ${f.visits_max}` : ' et plus'} visites`] : []),
      ...(f.radius_km ? [`À moins de ${f.radius_km} km`] : []),
      ...page.stores.filter((x) => f.stores.includes(x.id)).map((x) => x.name)];
  };
  const targetText = () => {
    const base = tg.mode === 'wallet' ? 'Clients avec carte Wallet'
      : tg.mode === 'segment' ? `Segment : ${(page.segments.find((x) => x.key === tg.segment) || {}).label || '—'}` : 'Tous mes clients';
    const names = (vals, opts) => vals.map((v) => (opts.find((x) => x[0] === v) || [])[1]).filter(Boolean).join(' ou ');
    const extra = [f.gender.length && names(f.gender, GENDERS), f.age.length && names(f.age, AGES),
      f.client_type?.length && names(f.client_type, CLIENT_TYPES), f.spent.length && names(f.spent, SPENT),
      (f.visits_min !== '' || f.visits_max !== '') && `${f.visits_min !== '' ? `${f.visits_min}` : '0'}${f.visits_max !== '' ? ` à ${f.visits_max}` : ' et plus'} visites`,
      (f.age_min !== '' || f.age_max !== '') && `${f.age_min || 'Tous'} – ${f.age_max ? `${f.age_max} ans` : '65 ans et +'}`,
      f.last_visit.length && `Dernière visite : ${names(f.last_visit, LAST_VISIT)}`,
      f.radius_km && `À moins de ${f.radius_km} km`,
      f.stores?.length && page.stores.filter((x) => f.stores.includes(x.id)).map((x) => x.name).join(', ')].filter(Boolean);
    if (tg.mode === 'filtered') {
      const p = (PASSANTS.find((x) => x[0] === (tg.passants || 'all')) || PASSANTS[0])[1];
      return [p, ...extra].join(' · ');
    }
    return tg.mode === 'all' ? base : [base, ...extra].join(' · ');
  };
  const daysText = () => (sc.days === 'all' ? 'Tous les jours' : sc.days === 'weekdays' ? 'Jours ouvrés'
    : sc.weekdays.map((d) => DAY_NAMES[d]).join(', ') || '—');
  const validText = () => (sc.valid_from || sc.valid_to
    ? ` · ${sc.valid_from && sc.valid_to ? `du ${sc.valid_from.split('-').reverse().join('/')} au ${sc.valid_to.split('-').reverse().join('/')}`
      : sc.valid_from ? `à partir du ${sc.valid_from.split('-').reverse().join('/')}` : `jusqu'au ${sc.valid_to.split('-').reverse().join('/')}`}` : '');
  const freqText = () => ({ once: 'Une seule fois', smart: 'Envoi intelligent (une fois, au meilleur moment du client)',
    days: `Au plus une fois tous les ${tr.every_days || 30} jours` }[tr.frequency === 'every_scan' ? 'days' : tr.frequency || 'once']);
  const planText = () => (s.scenario === 'google_review'
    ? `${sc.days === 'all' ? 'Tous les jours' : sc.weekdays.map((d) => DAY_NAMES[d]).join(', ')}${tr.type === 'date' ? ` · ${sc.hour} (${parisOffset()} Paris)` : ''}${sc.window ? ' · entre 8h et 20h' : ''} · ${freqText()}${validText()}`
    : s.scenario === 'geo'
    ? `${sc.days === 'all' ? 'Tous les jours' : sc.weekdays.map((d) => DAY_NAMES[d]).join(', ')} · ${sc.window ? (sc.slots || []).map((x) => `${x.from}–${x.to}`).join(' / ') : 'toute la journée'}${validText()}`
    : (timed
      ? `${daysText()} à ${sc.smart && page.best_slot ? `${page.best_slot.from} (plage intelligente)` : sc.hour}`
      : `${daysText()} · ${sc.window ? `entre ${sc.window_from} et ${sc.window_to}` : 'immédiat'}`) + validText());

  // ---- the checks (the server repeats them) --------------------------------------
  const problem = (n) => {
    if (n === 1 && !s.scenario) return 'Choisissez un scénario.';
    if (n === 1 && s.scenario === 'google_review') {
      if (!s.name.trim()) return "Donnez un nom à l'automatisation.";
      const miss = googleKeys.find((k) => !String(links[k] || '').trim());
      if (miss) return miss === 'main' ? 'Ajoutez le lien vers votre fiche Google Avis.' : `Ajoutez le lien Google de « ${(googleStores.find((b) => b.id === miss) || {}).name} ».`;
      const bad = googleKeys.find((k) => !LINK_RE.test(fullLink(links[k])));
      if (bad) return 'Lien Google invalide : collez l\'adresse de votre fiche, par exemple https://g.page/r/…/review.';
    }
    if (n === 2) {
      const num = (v, lo, hi, l) => (!Number.isInteger(Number(v)) || Number(v) < lo || Number(v) > hi ? `${l} : entre ${lo} et ${hi}.` : '');
      if (s.scenario === 'birthday') return num(Math.abs(Number(tr.offset_days || 0)), 0, 30, 'Jours');
      if (s.scenario === 'near_reward') {
        const lbl = near.unit === 'tampons' ? 'Seuil (tampons)' : near.unit === '€' ? 'Seuil (€)' : 'Seuil (points)';
        const bad = num(tr.threshold, 1, 100000, lbl);
        if (bad) return bad;
        if (near.card_goal && Number(tr.threshold) >= near.card_goal) return `Le seuil doit être inférieur à la récompense de la carte (${near.card_goal} ${near.unit}).`;
        return '';
      }
      if (s.scenario === 'inactive') return num(tr.days, 7, 365, 'Jours sans visite') || (tr.repeat === 'every' ? num(tr.every_days, 7, 365, 'Répéter tous les') : '');
      if (s.scenario === 'geo') {
        if (!(tr.stores || []).length) return 'Cochez au moins un établissement.';
        if (!zoneSpots.length) return "La position de votre établissement est inconnue : placez-le sur la carte dans Paramètres › Établissement.";
        return '';
      }
      if (s.scenario === 'google_review') {
        if (tr.type === 'loyal') return num(tr.visits, 1, 1000, 'Nombre de visites');
        if (tr.type === 'date') {
          if (!tr.date) return "Choisissez la date d'envoi.";
          if (tr.date < new Date().toISOString().slice(0, 10)) return 'Cette date est déjà passée.';
          return '';
        }
        return num(tr.delay_value ?? 0, 0, 365, 'Délai après la visite');
      }
      if (s.scenario === 'tier_up') {
        if (tr.repeat === 'custom' && num(tr.min_days, 1, 365, 'Délai minimum entre deux envois (jours)')) return num(tr.min_days, 1, 365, 'Délai minimum entre deux envois (jours)');
        if (tr.condition === 'status') return '';
        if (!tr.custom_tiers) return num(tr.threshold, 1, 1000000, { points: 'Nombre de points', visits: 'Nombre de visites', amount: "Montant d'achats" }[tr.condition]);
        if (!tr.tiers.length) return 'Ajoutez au moins un palier.';
        const vals = tr.tiers.map((t) => Number(t.value));
        if (vals.some((v) => !Number.isInteger(v) || v < 1)) return 'Chaque palier a une valeur (1 ou plus).';
        if (new Set(vals).size !== vals.length) return 'Deux paliers ont la même valeur.';
        return '';
      }
      if (s.scenario === 'custom') {
        if (!tr.type) return 'Choisissez quand envoyer ce message.';
        if (tr.type === 'visits') return num(tr.visits, 1, 1000, 'Nombre de visites');
        if (tr.type === 'after_signup') return num(tr.delay_value || 0, 0, 365, 'Délai');
        if (tr.type === 'after_visit') return num(tr.delay_value || 0, 0, 365, 'Délai') || num(tr.cooldown_days || 0, 0, 365, 'Au plus une fois tous les');
        if (tr.type === 'date') {
          if (['once', 'yearly'].includes(tr.date_mode) && !tr.date) return "Choisissez la date d'envoi.";
          if (tr.date_mode === 'once' && tr.date < new Date().toISOString().slice(0, 10)) return 'Cette date est déjà passée.';
          if (tr.date_mode === 'monthly') return num(tr.monthday, 1, 31, 'Jour du mois');
        }
        return '';
      }
      if (!timed && s.scenario !== 'geo') return num(tr.delay_value || 0, 0, 365, "Délai d'envoi");
    }
    if (n === 3) {
      if (tiered) {
        const bad = tr.tiers.findIndex((t) => !String(t.title || '').trim() || !String(t.body || '').trim());
        if (bad >= 0) { setTierTab(bad); return `Palier ${palierLabel(tr.condition, tr.tiers[bad].value)} : écrivez son titre et son message.`; }
      } else {
        if (!msg.title.trim()) return 'Écrivez le titre de la notification.';
        if (!msg.body.trim()) return 'Écrivez le message.';
      }
      if (msg.title.length > TITLE_MAX) return `Titre : ${TITLE_MAX} caractères au maximum.`;
      if (msg.body.length > BODY_MAX) return `Message : ${BODY_MAX} caractères au maximum.`;
      if (btn.enabled) {
        if (!btn.label.trim()) return 'Indiquez le texte du bouton.';
        if (btn.link_type === 'url' && !LINK_RE.test(fullLink(btn.url))) return 'Lien invalide : saisissez une adresse web, par exemple https://monsite.fr.';
        if (btn.link_type === 'offer' && !btn.offer_id) return 'Choisissez une offre.';
        if (btn.link_type === 'google_review' && s.scenario !== 'google_review' && !page.google_review_ready) return "Ajoutez d'abord votre lien Google (Insights › Avis Google).";
      }
    }
    if (n === 4) {
      if (tg.mode === 'segment' && !tg.segment) return 'Choisissez un segment.';
    }
    if (n === 5) {
      if (sc.days === 'specific' && !sc.weekdays.length) return "Cochez au moins un jour d'envoi.";
      if (s.scenario === 'geo') {
        if (sc.window && !(sc.slots || []).length) return 'Ajoutez au moins une plage horaire, ou choisissez « Toute la journée ».';
        if (sc.window && sc.slots.some((x) => x.from === x.to)) return 'Une plage horaire commence et finit à la même heure.';
        const c = Number(tr.cooldown_days);
        if (!Number.isInteger(c) || c < 1 || c > 90) return 'Fréquence par client : entre 1 et 90 jours.';
      } else if (s.scenario === 'inactive') {
        if (sc.window && sc.window_to <= sc.window_from) return 'La fin de la plage horaire doit être après son début.';
        if (sc.window && !sc.smart && !(sc.window_from <= sc.hour && sc.hour < sc.window_to)) return `L'heure d'envoi (${sc.hour}, étape Déclencheur) doit être comprise dans la plage horaire (${sc.window_from} – ${sc.window_to}).`;
        if (sc.daily_limit !== null && sc.daily_limit !== undefined) {
          const n = Number(sc.daily_limit);
          if (!Number.isInteger(n) || n < 1 || n > 100000) return "Limite d'envoi par jour : entre 1 et 100 000.";
        }
      } else if (!timed && sc.window && sc.window_to <= sc.window_from) return 'La fin de la plage horaire doit être après son début.';
      if (s.scenario === 'near_reward' && sc.daily_limit !== null && sc.daily_limit !== undefined) {
        const n = Number(sc.daily_limit);
        if (!Number.isInteger(n) || n < 1 || n > 100000) return "Limite d'envoi quotidienne : entre 1 et 100 000.";
      }
      if (sc.valid_from && sc.valid_to && sc.valid_to < sc.valid_from) return 'La date de fin doit être après la date de début.';
      if (sc.valid_to && sc.valid_to < new Date().toISOString().slice(0, 10) && s.status !== 'paused') return 'La date de fin est déjà passée : choisissez une nouvelle date.';
    }
    return '';
  };
  const go = (n) => { setError(''); setStep(n); window.scrollTo({ top: 0, behavior: 'smooth' }); };
  const sideMsg = (side) => (side === 'filleul' ? (s.message_filleul || {}) : msg);
  const refProblem = () => {
    const sides = tr.sides || [];
    if (!sides.length) return 'Envoyez au moins un message : au parrain ou au filleul.';
    for (const side of sides) {
      const mm = sideMsg(side);
      const who = side === 'filleul' ? 'Filleul' : 'Parrain';
      const b = mm.button || {};
      if (!String(mm.title || '').trim()) return `${who} : écrivez le titre de la notification.`;
      if (!String(mm.body || '').trim()) return `${who} : écrivez le texte de la notification.`;
      if (mm.title.length > TITLE_MAX) return `${who} : titre de ${TITLE_MAX} caractères au maximum.`;
      if (mm.body.length > BODY_MAX) return `${who} : texte de ${BODY_MAX} caractères au maximum.`;
      if (b.enabled && !String(b.label || '').trim()) return `${who} : indiquez le texte du bouton.`;
      if (b.enabled && b.link_type === 'url' && !LINK_RE.test(fullLink(b.url))) return `${who} : lien du bouton invalide.`;
      if (b.enabled && b.link_type === 'offer' && !b.offer_id) return `${who} : choisissez une offre.`;
    }
    if (refCfg && refDirty) {
      for (const k of ['referrer_reward_points', 'referee_reward_points', 'referrer_reward_points_next', 'referee_reward_points_next']) {
        const v = Number(refCfg[k]);
        if (!Number.isInteger(v) || v < 0 || v > 10000) return 'Récompenses : des points entre 0 et 10 000.';
      }
      const mv = Number(refCfg.minimum_visits_to_earn);
      if (!Number.isInteger(mv) || mv < 1 || mv > 20) return 'Récompenses : visites du filleul avant validation entre 1 et 20.';
    }
    return '';
  };
  const next = () => {
    if (refOn) { const p = step === 2 ? refProblem() : ''; if (p) { setError(p); return; } go(step + 1); return; }
    const pn = welcomeOn ? (step === 2 ? 3 : 0) : step;
    const p = pn ? problem(pn) : '';
    if (p) { setError(p); return; }
    go(step + 1);
  };

  const body = (status) => (refOn ? {
    scenario: 'referral', name: s.name, status, description: s.description || '', trigger: { sides: tr.sides || [] },
    message: { ...msg, title: msg.title.trim(), body: msg.body.trim(),
      button: { ...btn, url: btn.link_type === 'url' ? fullLink(btn.url) : null, offer_id: btn.link_type === 'offer' ? btn.offer_id : null } },
    message_filleul: (() => { const mf = s.message_filleul || {}; const bf = mf.button || {};
      return { ...mf, title: String(mf.title || '').trim(), body: String(mf.body || '').trim(),
        button: { ...bf, url: bf.link_type === 'url' ? fullLink(bf.url) : null, offer_id: bf.link_type === 'offer' ? bf.offer_id : null } }; })(),
    targeting: { mode: 'all', segment: null, passants: 'all', filters: { ...EMPTY_FILTERS }, exclusions: { ...EMPTY_EXCLUSIONS } },
    // when the points are credited: at once
    schedule: { ...sc, days: 'all', weekdays: [0, 1, 2, 3, 4, 5, 6], window: false, slots: [], hour: null, smart: false,
      valid_from: sc.valid_from || null, valid_to: sc.valid_to || null, daily_limit: null },
  } : welcomeOn ? {
    scenario: 'welcome', name: s.name, status, description: s.description || '', trigger: {},
    message: { ...msg, title: msg.title.trim(), body: msg.body.trim(),
      button: { ...btn, url: btn.link_type === 'url' ? fullLink(btn.url) : null, offer_id: btn.link_type === 'offer' ? btn.offer_id : null } },
    targeting: { mode: 'all', segment: null, passants: 'all', filters: { ...EMPTY_FILTERS }, exclusions: { ...EMPTY_EXCLUSIONS } },
    // « dès qu'un client ajoute sa carte »: at once, any day, any hour
    schedule: { ...sc, days: 'all', weekdays: [0, 1, 2, 3, 4, 5, 6], window: false, slots: [], hour: null, smart: false,
      valid_from: sc.valid_from || null, valid_to: sc.valid_to || null, daily_limit: null },
  } : {
    scenario: s.scenario, name: s.name, status, description: s.scenario === 'google_review' ? '' : (s.description || ''),
    ...(s.scenario === 'google_review' ? { google_links: Object.fromEntries(Object.entries(links).map(([k, v]) => [k, fullLink(v)])) } : {}),
    trigger: s.scenario === 'near_reward' ? { threshold: Number(tr.threshold) } : { ...tr, offset_days: Number(tr.offset_days || 0),
      ...(s.scenario === 'tier_up' ? { threshold: Number(tr.threshold) || 0, min_days: Number(tr.min_days) || 7,
        custom_tiers: tiered, tiers: tiered ? tr.tiers.map((t) => ({ value: Number(t.value), title: String(t.title || '').trim(),
          body: String(t.body || '').trim(), reward: String(t.reward || '').trim() })) : [] } : {}) },
    message: { ...msg,
      // with paliers personnalisés the list shows the first palier's words
      title: (tiered ? String(tr.tiers[0]?.title || '') : msg.title).trim(),
      body: (tiered ? String(tr.tiers[0]?.body || '') : msg.body).trim(),
      button: { ...btn, url: btn.link_type === 'url' ? fullLink(btn.url) : null, offer_id: btn.link_type === 'offer' ? btn.offer_id : null } },
    ...(s.scenario === 'geo' ? { trigger: { cooldown_days: Number(tr.cooldown_days) || 7, weather: tr.weather || [], radius_m: Number(tr.radius_m) || 200,
      // every establishment ticked = all of them (the ones opened later too)
      stores: (tr.stores || []).length === geo.anchors.length ? [] : tr.stores } } : {}),
    targeting: tg.mode === 'all' ? { mode: 'all', segment: null, passants: 'all', filters: { ...EMPTY_FILTERS }, exclusions: tg.exclusions || { ...EMPTY_EXCLUSIONS } } : tg,
    schedule: { ...sc, hour: timed ? sc.hour : null, slots: s.scenario === 'geo' && sc.window ? sc.slots : [],
      valid_from: sc.valid_from || null, valid_to: sc.valid_to || null,
      daily_limit: sc.daily_limit === null || sc.daily_limit === undefined || sc.daily_limit === '' ? null : Number(sc.daily_limit) },
  });
  const save = async (status) => {
    if (refOn && status !== 'draft') { const p = refProblem(); if (p) { setError(p); setStep(p.startsWith('Récompenses') ? 3 : 2); return; } }
    if (status !== 'draft' && !refOn) {
      for (let n = 1; n <= 5; n += 1) { const p = problem(n); if (p) { setError(p); setStep(welcomeOn ? (n === 3 ? 2 : 1) : n); return; } }
    }
    setBusy(status); setError('');
    try {
      if (refOn && refDirty && page.referral?.can_edit) {
        // « Récompenses » edited here = the Parrainage page's rules (one document, sent whole)
        const { data: full } = await ownerAPI.referralConfig();
        await ownerAPI.saveReferralConfig({ ...full, ...Object.fromEntries(Object.entries(refCfg).filter(([k]) => k !== 'can_edit')) });
      }
      if (editing) await ownerAPI.updateAutomation(id, body(status));
      else await ownerAPI.createAutomation(body(status));
      navigate('/dashboard/automations', { state: { flash: status === 'draft' ? 'Brouillon enregistré.'
        : status === 'active' ? 'Automatisation enregistrée et activée.' : 'Automatisation enregistrée (en pause).' } });
    } catch (e) {
      setError(e?.response?.data?.detail || "L'enregistrement n'a pas abouti.");
    } finally { setBusy(''); }
  };

  // ---- inserting a variable / an emoji where the cursor is -------------------
  const insert = (text) => {
    const which = lastFocus.current === 'title' ? 'title' : 'body';
    const el = which === 'title' ? titleRef.current : bodyRef.current;
    const now = cur[which] || '';
    const max = which === 'title' ? TITLE_MAX : BODY_MAX;
    const a = el?.selectionStart ?? now.length;
    const b = el?.selectionEnd ?? now.length;
    const nextVal = (now.slice(0, a) + text + now.slice(b)).slice(0, max);
    setCur({ [which]: nextVal });
    setTimeout(() => { if (el) { el.focus(); const p = Math.min(a + text.length, nextVal.length); el.setSelectionRange(p, p); } }, 0);
  };
  const pickImage = (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (!/^image\/(png|jpe?g|webp|gif)$/.test(file.type)) { setError('Image PNG ou JPG uniquement.'); return; }
    if (file.size > 2 * 1024 * 1024) { setError("L'image dépasse 2 Mo."); return; }
    const r = new FileReader();
    r.onload = () => setMsg({ image_url: String(r.result) });
    r.readAsDataURL(file);
  };

  const ScIcon = ICONS[m.icon] || MessageSquare;
  const tone = TONES[m.tone] || TONES.blue;

  // ---- the six steps --------------------------------------------------------------
  const Step1 = (
    <Card n={1} title="Choisir un scénario" sub="Sélectionnez le type d'automatisation que vous souhaitez utiliser.">
      {editing && <p className="mb-3 flex items-center gap-2 rounded-xl bg-[#F1F6FF] px-3 py-2 text-[12px] text-[#334155]"><Info size={15} className="text-[#1463FF]" /> Le scénario d'une automatisation existante ne change pas : dupliquez-la ou créez-en une nouvelle.</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        {page.scenarios.map((x) => {
          const I = ICONS[x.icon] || MessageSquare;
          const [bg, fg] = TONES[x.tone] || TONES.blue;
          const on = s.scenario === x.key;
          return (
            <button key={x.key} type="button" disabled={editing && !on}
                    onClick={() => {
                      if (editing || on) return;
                      // words the owner (or FidClic IA) already wrote are kept
                      const own = s.message.title.trim() && s.message.title !== m.title;
                      const d = defaults(x.key, x);
                      setS({ ...d, name: d.name || x.label, ...(own ? { message: { ...d.message, title: s.message.title, body: s.message.body } } : {}) });
                    }}
                    className={`flex items-start gap-3 rounded-2xl border p-4 text-left transition disabled:opacity-50 ${on ? 'border-[#2F6BFF] bg-[#F5F8FF] shadow-[0_0_0_1px_#2F6BFF]' : 'border-[#E2E8F0] bg-white hover:border-[#BFD3FF]'}`}>
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl" style={{ background: bg, color: fg }}><I size={20} /></span>
              <span className="min-w-0 flex-1"><span className="block text-[14px] font-bold text-[#0B1C3F]">{x.label}</span>
                <span className="block text-[12px] leading-snug text-[#64748B]">{x.sub}</span></span>
              <Radio on={on} />
            </button>
          );
        })}
      </div>
      <label className="mt-4 block"><Label right={`${s.name.length}/100`}>Nom de l'automatisation{s.scenario === 'google_review' ? ' *' : ''}</Label>
        <input className={field} value={s.name} maxLength={100} onChange={(e) => set({ name: e.target.value })} placeholder={m.label} /></label>
      {s.scenario !== 'google_review' && (
        <label className="mt-3 block"><Label right={`${(s.description || '').length}/500`}>Description <span className="font-normal text-[#64748B]">(optionnelle)</span></Label>
          <textarea className={`${field} min-h-[72px] resize-y`} maxLength={500} value={s.description || ''} onChange={(e) => set({ description: e.target.value })}
                    placeholder="À quoi sert cette automatisation ? Elle s'affiche sous son nom dans la liste." /></label>
      )}
      {s.scenario === 'google_review' && (
        <div className="mt-3">
          {googleStores.length > 1 ? (
            <>
              <Label>Liens vers les fiches Google Avis *</Label>
              <div className="space-y-2">
                {googleStores.map((b) => (
                  <label key={b.id} className="block"><span className="mb-1 block text-[12px] font-semibold text-[#475569]">{b.name}</span>
                    <span className={`${field} flex items-center gap-2 !py-0`}><Link2 size={16} className="shrink-0 text-[#64748B]" />
                      <input className="min-w-0 flex-1 !border-0 bg-transparent py-2.5 !text-[14px] !shadow-none !outline-none !ring-0" inputMode="url"
                             aria-label={`Lien Google Avis de ${b.name}`} placeholder="https://g.page/votre-entreprise/review"
                             value={links[b.id] || ''} onChange={(e) => setLinks({ ...links, [b.id]: e.target.value })} /></span></label>
                ))}
              </div>
            </>
          ) : (
            <label className="block"><Label>Lien vers la fiche Google Avis *</Label>
              <span className={`${field} flex items-center gap-2 !py-0`}><Link2 size={16} className="shrink-0 text-[#64748B]" />
                <input className="min-w-0 flex-1 !border-0 bg-transparent py-2.5 !text-[14px] !shadow-none !outline-none !ring-0" inputMode="url"
                       aria-label="Lien vers la fiche Google Avis" placeholder="https://g.page/votre-entreprise/review"
                       value={links.main || ''} onChange={(e) => setLinks({ ...links, main: e.target.value })} /></span></label>
          )}
          <p className="mt-2 flex items-start gap-2 rounded-xl bg-[#F1F6FF] px-3 py-2.5 text-[12px] leading-snug text-[#334155]"><Info size={16} className="mt-0.5 shrink-0 text-[#1463FF]" />
            <span><b className="block text-[#0B1C3F]">Où trouver ce lien ?</b>Rendez-vous sur votre fiche Google Business, cliquez sur « Obtenir plus d'avis » puis sur « Copier le lien ». Collez ce lien ici pour que vos clients puissent laisser un avis directement.
              {googleStores.length > 1 ? " Chaque établissement a sa fiche : le client reçoit le lien de l'établissement où il est venu." : ' Le même lien est utilisé dans Insights › Avis Google.'}</span></p>
        </div>
      )}
    </Card>
  );

  const delayBlock = !timed && !['geo', 'custom'].includes(s.scenario) && (
    <div className="mt-3 flex flex-wrap items-center gap-3 rounded-2xl border border-[#E2E8F0] p-4">
      <span className="flex items-center gap-2 text-[13px] font-semibold text-[#0B1C3F]">Délai d'envoi <span className="font-normal text-[#64748B]">(optionnel)</span>
        <span title="Attendre un peu après l'événement avant d'envoyer (ex. 2 h après la visite pour un avis Google)."><Info size={14} className="text-[#64748B]" /></span></span>
      <span className="flex flex-1 items-center justify-end gap-2">
        <Num value={tr.delay_value ?? 0} min={0} max={365} label="Délai d'envoi" onChange={(v) => setIn('trigger', { delay_value: v })} />
        <span className="w-36"><Select label="Unité du délai" value={tr.delay_unit || 'hours'} onChange={(v) => setIn('trigger', { delay_unit: v })}
                options={[['minutes', 'minute(s)'], ['hours', 'heure(s)'], ['days', 'jour(s)']]} /></span>
        <span className="text-[12px] text-[#64748B]">{Number(tr.delay_value) > 0 ? 'après' : 'Immédiat'}</span>
      </span>
    </div>
  );
  const Step2 = (
    <Card n={2} title="Déclencheur" sub="Définissez quand cette notification doit être envoyée.">
      <div className="mb-3 flex items-start gap-3 rounded-2xl border border-[#2F6BFF] bg-[#F5F8FF] p-4">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white text-[#1463FF]"><ScIcon size={18} /></span>
        <span><span className="block text-[14px] font-bold text-[#0B1C3F]">{m.trigger_label}</span>
          <span className="text-[12.5px] text-[#475569]">{{
            birthday: "Le message part automatiquement autour de la date d'anniversaire du client.",
            tier_up: 'Choisissez le palier qui déclenche le message : des points, des visites, un montant d\'achats, ou un nouveau statut.',
            welcome: "Envoyé à chaque nouveau client, juste après son inscription.",
            near_reward: 'Envoyé après la visite qui laisse exactement X visites avant la récompense — une fois par carte.',
            referral: 'Envoyé quand des points de parrainage sont gagnés (visite du filleul).',
            geo: "Envoyé quand la carte du client voit qu'il passe près de l'un de vos établissements.",
            google_review: 'Envoyé après une visite, pour demander un avis sur votre page Google.',
            inactive: "Envoyé aux clients qui ne sont pas venus depuis X jours.",
            custom: 'Choisissez vous-même le moment : un nombre de visites, après l\'inscription, après chaque visite, ou une date.',
          }[s.scenario]}</span></span>
      </div>
      {s.scenario === 'birthday' && (
        <div className="space-y-3">
          <Option on={Number(tr.offset_days) === 0} onClick={() => setIn('trigger', { offset_days: 0 })} icon={CalendarDays} title="Le jour même" sub="Le jour de l'anniversaire du client.">
            <p className="flex items-center gap-2 rounded-xl bg-[#EEF4FF] px-3 py-2 text-[12px] text-[#1E3A8A]"><Repeat size={14} /> Répétition annuelle : envoyée automatiquement tous les ans à la même date.</p>
          </Option>
          <Option on={Number(tr.offset_days) < 0} onClick={() => setIn('trigger', { offset_days: -3 })} icon={Clock} title="X jours avant l'anniversaire" sub="Envoyez le message quelques jours avant la date d'anniversaire.">
            <span className="flex items-center gap-2 text-[13px]"><Num value={String(Math.abs(Number(tr.offset_days)))} min={1} max={30} label="Jours avant" onChange={(v) => setIn('trigger', { offset_days: -Math.max(1, Number(v) || 1) })} /> jour(s) avant</span>
          </Option>
          <Option on={Number(tr.offset_days) > 0} onClick={() => setIn('trigger', { offset_days: 3 })} icon={CalendarDays} title="X jours après l'anniversaire" sub="Envoyez le message quelques jours après la date d'anniversaire.">
            <span className="flex items-center gap-2 text-[13px]"><Num value={String(Math.abs(Number(tr.offset_days)))} min={1} max={30} label="Jours après" onChange={(v) => setIn('trigger', { offset_days: Math.max(1, Number(v) || 1) })} /> jour(s) après</span>
          </Option>
        </div>
      )}
      {s.scenario === 'near_reward' && (
        <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-[#E2E8F0] p-4 text-[13px]">
          <span className="font-semibold text-[#0B1C3F]">Envoyer quand il reste</span>
          <Num value={tr.visits_left} min={1} max={50} label="Visites restantes" onChange={(v) => setIn('trigger', { visits_left: v })} />
          <span>visite(s) avant la récompense</span>
        </div>
      )}
      {s.scenario === 'inactive' && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-[#E2E8F0] p-4 text-[13px]">
            <span className="font-semibold text-[#0B1C3F]">Aucune visite depuis</span>
            <Num value={tr.days} min={7} max={365} label="Jours sans visite" onChange={(v) => setIn('trigger', { days: v })} /> <span>jours</span>
          </div>
          <Option on={tr.repeat !== 'every'} onClick={() => setIn('trigger', { repeat: 'once' })} icon={RefreshCw} title="Une seule fois par absence" sub="Un message, puis plus rien tant que le client ne revient pas." />
          <Option on={tr.repeat === 'every'} onClick={() => setIn('trigger', { repeat: 'every' })} icon={Repeat} title="Relancer régulièrement" sub="Tant que le client ne revient pas.">
            <span className="flex items-center gap-2 text-[13px]">Tous les <Num value={tr.every_days} min={7} max={365} label="Répéter tous les" onChange={(v) => setIn('trigger', { every_days: v })} /> jours</span>
          </Option>
        </div>
      )}
      {s.scenario === 'referral' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Option on={tr.side !== 'filleul'} onClick={() => setIn('trigger', { side: 'parrain' })} icon={Users} title="Au parrain" sub="Celui qui a invité : son ami est venu, il gagne ses points." />
          <Option on={tr.side === 'filleul'} onClick={() => setIn('trigger', { side: 'filleul' })} icon={User} title="Au filleul" sub="L'ami invité : il gagne ses points grâce à son parrain." />
        </div>
      )}
      {s.scenario === 'google_review' && (
        <div className="space-y-3">
          {!page.google_review_ready && <p className="rounded-xl bg-[#FFF7ED] px-3 py-2 text-[12px] text-[#9A3412]">Votre lien Google n'est pas encore activé (Insights › Avis Google) : aucune demande ne part sans lui.</p>}
          <Option on={tr.frequency === 'every_scan'} onClick={() => setIn('trigger', { frequency: 'every_scan' })} title="Après chaque visite" />
          <Option on={tr.frequency === 'days'} onClick={() => setIn('trigger', { frequency: 'days' })} title="Au plus une fois tous les X jours">
            <span className="flex items-center gap-2 text-[13px]">Tous les <Num value={tr.every_days} min={1} max={365} label="Tous les X jours" onChange={(v) => setIn('trigger', { every_days: v })} /> jours</span>
          </Option>
          <Option on={tr.frequency === 'once'} onClick={() => setIn('trigger', { frequency: 'once' })} title="Une seule fois par client" />
          <div className="flex items-center justify-between rounded-2xl border border-[#E2E8F0] p-4">
            <span><span className="block text-[13px] font-semibold text-[#0B1C3F]">Arrêter après un clic</span>
              <span className="text-[12px] text-[#64748B]">Ne plus demander à un client qui a déjà ouvert votre page d'avis.</span></span>
            <Toggle label="Arrêter après un clic" on={tr.stop_after_click !== false} onChange={(v) => setIn('trigger', { stop_after_click: v })} />
          </div>
        </div>
      )}
      {s.scenario === 'tier_up' && (
        <div className="space-y-3">
          <div className="rounded-2xl border border-[#E6EEFB] p-4">
            <p className="mb-3 flex items-start gap-3"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#FFF4E0] text-[#F59E0B]"><Trophy size={18} /></span>
              <span><span className="block text-[13.5px] font-bold text-[#0B1C3F]">Condition d'envoi</span>
                <span className="text-[12px] text-[#64748B]">Choisissez le palier qui déclenche l'envoi de la notification.</span></span></p>
            {[['points', 'Lorsque le client atteint un nombre de points', 'points', 'Points gagnés depuis le début : une récompense ne les fait pas baisser.'],
              ['visits', 'Lorsque le client atteint un nombre de visites', 'visites'],
              ['amount', "Lorsque le client atteint un montant d'achats", '€']].map(([k, l, unit, hint]) => (
              <div key={k} className="flex flex-wrap items-center gap-3 border-t border-[#F1F5F9] py-2.5 first:border-t-0">
                <button type="button" onClick={() => setIn('trigger', { condition: k })} className="flex min-w-0 flex-1 items-center gap-3 text-left text-[13px] text-[#0B1C3F]">
                  <Radio on={tr.condition === k} /><span>{l}{hint && tr.condition === k && <span className="block text-[11.5px] text-[#64748B]">{hint}</span>}</span></button>
                {!tr.custom_tiers && (
                  <span className="flex items-center gap-2 text-[12.5px] text-[#475569]">
                    <Num value={tr.condition === k ? tr.threshold : ({ points: 200, visits: 10, amount: 100 }[k])} digits={7} min={1} max={1000000}
                         label={l} disabled={tr.condition !== k} onChange={(v) => setIn('trigger', { threshold: v })} /> {unit}</span>
                )}
              </div>
            ))}
            <div className="flex items-center gap-3 border-t border-[#F1F5F9] py-2.5">
              <button type="button" onClick={() => setIn('trigger', { condition: 'status', custom_tiers: false })} className="flex min-w-0 flex-1 items-center gap-3 text-left text-[13px] text-[#0B1C3F]">
                <Radio on={tr.condition === 'status'} /><span>Lorsque le client change de statut <span className="text-[#64748B]">(Bronze → Argent → Or → VIP)</span></span></button>
            </div>
          </div>
          <div className="rounded-2xl border border-[#E6EEFB] p-4">
            <p className="mb-3 flex items-start gap-3"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><RefreshCw size={18} /></span>
              <span><span className="block text-[13.5px] font-bold text-[#0B1C3F]">Répétition</span>
                <span className="text-[12px] text-[#64748B]">Choisissez si cette automatisation peut se déclencher plusieurs fois pour un même client.</span></span></p>
            {[['each', 'Envoyer à chaque palier atteint', ' (recommandé)', tr.condition === 'status' ? 'Le client reçoit une notification à chaque nouveau statut.'
                : tiered ? 'Le client reçoit une notification à chaque palier de votre liste.' : `Le client reçoit une notification à chaque palier : ${[1, 2, 3].map((k) => palierLabel(tr.condition, (Number(tr.threshold) || 0) * k)).join(', ')}…`],
              ['first', 'Envoyer uniquement la première fois', '', 'Le client recevra une seule notification lors de son premier palier.'],
              ['custom', 'Fréquence personnalisée', '', 'À chaque palier, mais avec un délai minimum entre deux envois.']].map(([k, l, rec, h]) => (
              <div key={k} className="border-t border-[#F1F5F9] py-2.5 first:border-t-0">
                <button type="button" onClick={() => setIn('trigger', { repeat: k })} className="flex w-full items-start gap-3 text-left">
                  <Radio on={(tr.repeat || 'each') === k} />
                  <span><span className="block text-[13px] text-[#0B1C3F]">{l}<span className="text-[#64748B]">{rec}</span></span><span className="text-[12px] text-[#64748B]">{h}</span></span>
                </button>
                {k === 'custom' && tr.repeat === 'custom' && (
                  <span className="ml-8 mt-2 flex items-center gap-2 text-[12.5px] text-[#475569]">Au moins <Num value={tr.min_days} min={1} max={365} label="Délai minimum entre deux envois" onChange={(v) => setIn('trigger', { min_days: v })} /> jours entre deux envois</span>
                )}
              </div>
            ))}
          </div>
          {tr.condition !== 'status' && (
            <div className="rounded-2xl border border-[#E6EEFB] p-4">
              <div className="flex items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#F1EAFF] text-[#7C3AED]"><Settings2 size={18} /></span>
                <span className="min-w-0 flex-1"><span className="block text-[13.5px] font-bold text-[#0B1C3F]">Paliers personnalisés <span className="font-normal text-[#64748B]">(optionnel)</span></span>
                  <span className="text-[12px] text-[#64748B]">Définissez plusieurs paliers pour envoyer des notifications différentes.</span></span>
                <Toggle label="Paliers personnalisés" on={Boolean(tr.custom_tiers)} onChange={(v) => {
                  const base = Number(tr.threshold) || ({ points: 200, visits: 10, amount: 100 }[tr.condition]);
                  setIn('trigger', { custom_tiers: v, tiers: v && !tr.tiers.length
                    ? [1, 2].map((k) => ({ value: String(base * k), title: msg.title, body: msg.body, reward: '' })) : tr.tiers });
                  setTierTab(0);
                }} />
              </div>
              {tr.custom_tiers && (
                <div className="mt-3 space-y-2">
                  {tr.tiers.map((t, i) => (
                    <div key={i} className="flex flex-wrap items-center gap-2 rounded-xl bg-[#F8FAFC] p-2.5">
                      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#FFF4E0] text-[12px] font-bold text-[#B45309]">{i + 1}</span>
                      <Num value={t.value} digits={7} min={1} max={1000000} label={`Valeur du palier ${i + 1}`}
                           onChange={(v) => setIn('trigger', { tiers: tr.tiers.map((x, j) => (j === i ? { ...x, value: v } : x)) })} />
                      <span className="text-[12.5px] text-[#475569]">{UNIT_OF[tr.condition]}</span>
                      <input className={`${field} min-w-[140px] flex-1`} maxLength={80} value={t.reward || ''} placeholder="Récompense (optionnelle), ex. un dessert offert"
                             aria-label={`Récompense du palier ${i + 1}`} onChange={(e) => setIn('trigger', { tiers: tr.tiers.map((x, j) => (j === i ? { ...x, reward: e.target.value } : x)) })} />
                      <button type="button" aria-label={`Retirer le palier ${i + 1}`} disabled={tr.tiers.length <= 1}
                              onClick={() => { setIn('trigger', { tiers: tr.tiers.filter((_, j) => j !== i) }); setTierTab(0); }}
                              className="rounded-lg p-2 text-[#DC2626] hover:bg-[#FEF2F2] disabled:opacity-30"><Trash2 size={15} /></button>
                    </div>
                  ))}
                  {tr.tiers.length < 10 && (
                    <button type="button" onClick={() => {
                      const last = Math.max(0, ...tr.tiers.map((x) => Number(x.value) || 0));
                      setIn('trigger', { tiers: [...tr.tiers, { value: String(last + (Number(tr.threshold) || 100)), title: msg.title, body: msg.body, reward: '' }] });
                    }} className="inline-flex items-center gap-1.5 rounded-xl border border-dashed border-[#BFD3FF] px-3 py-2 text-[12.5px] font-semibold text-[#1463FF]">
                      <Plus size={14} /> Ajouter un palier</button>
                  )}
                  <p className="text-[11.5px] text-[#64748B]">Chaque palier a son propre message (étape Message). Sa récompense s'affiche avec la variable {'{récompense}'}.</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {s.scenario === 'custom' && (
        <div className="space-y-3">
          <Option on={tr.type === 'visits'} onClick={() => setIn('trigger', { type: 'visits' })} icon={Hash} title="Après X visites" sub="Quand le client atteint un nombre de visites — une fois, ou toutes les X visites.">
            <span className="flex flex-wrap items-center gap-2 text-[12px]">{tr.visits_repeat === 'every' ? 'Toutes les' : 'À la'} <Num value={tr.visits} digits={4} min={1} max={1000} label="Nombre de visites" onChange={(v) => setIn('trigger', { visits: v })} /> {tr.visits_repeat === 'every' ? 'visites' : 'e visite'}</span>
            <span className="mt-2 flex flex-wrap gap-4 text-[12.5px] text-[#0B1C3F]">
              <button type="button" onClick={() => setIn('trigger', { visits_repeat: 'once' })} className="flex items-center gap-2"><Radio on={tr.visits_repeat !== 'every'} /> Une seule fois</button>
              <button type="button" onClick={() => setIn('trigger', { visits_repeat: 'every' })} className="flex items-center gap-2"><Radio on={tr.visits_repeat === 'every'} /> Répéter (comme les paliers : 5, 10, 15…)</button>
            </span>
          </Option>
          <Option on={tr.type === 'after_signup'} onClick={() => setIn('trigger', { type: 'after_signup', delay_value: Number(tr.delay_value) || 7, delay_unit: tr.delay_unit === 'minutes' ? 'days' : (tr.delay_unit || 'days') })}
                  icon={UserPlus} title="Après l'inscription" sub="Un temps après l'inscription du client (une seule fois).">
            <span className="flex flex-wrap items-center gap-2 text-[12px]"><Num value={tr.delay_value ?? 0} min={0} max={365} label="Délai après l'inscription" onChange={(v) => setIn('trigger', { delay_value: v })} />
              <span className="w-32"><Select label="Unité" value={tr.delay_unit || 'days'} onChange={(v) => setIn('trigger', { delay_unit: v })} options={[['minutes', 'minute(s)'], ['hours', 'heure(s)'], ['days', 'jour(s)']]} /></span> après l'inscription
              <span className="w-full text-[11.5px] text-[#64748B]">0 = dès l'inscription.</span></span>
          </Option>
          <Option on={tr.type === 'after_visit'} onClick={() => setIn('trigger', { type: 'after_visit' })} icon={RefreshCw} title="Après chaque visite" sub="Un temps après chaque visite (ex. remercier, demander un retour).">
            <span className="flex flex-wrap items-center gap-2 text-[12px]"><Num value={tr.delay_value ?? 0} min={0} max={365} label="Délai après la visite" onChange={(v) => setIn('trigger', { delay_value: v })} />
              <span className="w-32"><Select label="Unité" value={tr.delay_unit || 'hours'} onChange={(v) => setIn('trigger', { delay_unit: v })} options={[['minutes', 'minute(s)'], ['hours', 'heure(s)'], ['days', 'jour(s)']]} /></span> après la visite</span>
            <span className="mt-2 flex flex-wrap items-center gap-2 text-[12px]">Au plus une fois tous les <Num value={tr.cooldown_days ?? 0} min={0} max={365} label="Au plus une fois tous les" onChange={(v) => setIn('trigger', { cooldown_days: v })} /> jours
              <span className="w-full text-[11.5px] text-[#64748B]">0 = à chaque visite.</span></span>
          </Option>
          <Option on={tr.type === 'date'} onClick={() => setIn('trigger', { type: 'date' })} icon={CalendarDays} title="À une date ou régulièrement" sub="Une date précise, ou chaque semaine, chaque mois, chaque année.">
            <div className="grid gap-2 sm:grid-cols-2">
              <Select label="Récurrence" value={tr.date_mode || 'once'} onChange={(v) => setIn('trigger', { date_mode: v })}
                      options={[['once', 'Une seule fois'], ['weekly', 'Chaque semaine'], ['monthly', 'Chaque mois'], ['yearly', 'Chaque année']]} />
              {['once', 'yearly'].includes(tr.date_mode || 'once') && (
                <input type="date" aria-label="Date d'envoi" className={field} value={tr.date || ''} min={tr.date_mode === 'once' ? new Date().toISOString().slice(0, 10) : undefined}
                       onChange={(e) => setIn('trigger', { date: e.target.value })} />
              )}
              {tr.date_mode === 'weekly' && (
                <Select label="Jour de la semaine" value={String(tr.weekday ?? 0)} onChange={(v) => setIn('trigger', { weekday: Number(v) })}
                        options={WEEKDAYS_FR.map((d, i) => [String(i), d.charAt(0).toUpperCase() + d.slice(1)])} />
              )}
              {tr.date_mode === 'monthly' && (
                <span className="flex items-center gap-2 text-[12px]">Le <Num value={tr.monthday} min={1} max={31} label="Jour du mois" onChange={(v) => setIn('trigger', { monthday: v })} /> du mois</span>
              )}
            </div>
            <p className="mt-2 text-[11.5px] text-[#64748B]">L'heure d'envoi se choisit à l'étape Planification. « Le 31 » part le dernier jour des mois plus courts.</p>
          </Option>
        </div>
      )}
      {delayBlock}
    </Card>
  );

  // ---- Géolocalisation (mockups 2026-10-11) -------------------------------------
  const geo = page.geo || { anchors: [], radius_m: 200, live: {}, weather: [], busy: null, radii: [50, 100, 200, 500] };
  const zoneSpots = geo.anchors.filter((a) => (tr.stores || []).includes(a.id));
  const allDay = !sc.window && sc.days === 'all';
  const slotsText = () => (sc.window ? (sc.slots || []).map((x) => `${hLabel(x.from)} – ${hLabel(x.to)}`).join(' / ') || '—' : 'Toute la journée');
  const geoDays = () => (sc.days === 'all' ? 'Tous les jours' : sc.days === 'weekdays' ? 'Du lundi au vendredi' : sc.weekdays.map((d) => DAY_NAMES[d]).join(', ') || '—');
  const periodText = () => (sc.valid_from || sc.valid_to
    ? (sc.valid_from && sc.valid_to ? `Du ${frDate(sc.valid_from)} au ${frDate(sc.valid_to)}` : sc.valid_from ? `À partir du ${frDate(sc.valid_from)}` : `Jusqu'au ${frDate(sc.valid_to)}`)
    : 'En continu');
  const rushOn = RUSH.filter(([, , a, b]) => hasSlot(sc, a, b));
  const weatherNames = (tr.weather || []).map((k) => (geo.weather.find((w) => w.key === k) || {}).label).filter(Boolean);
  const setSlots = (slots) => setIn('schedule', { slots, window: slots.length > 0, ...(slots[0] ? { window_from: slots[0].from, window_to: slots[0].to } : {}) });
  const setDays = (weekdays) => setIn('schedule', { weekdays, days: weekdays.length === 7 ? 'all' : 'specific' });
  const geoProblems = [!geo.live?.enabled && ['Le rappel de proximité est désactivé', 'Activez-le dans Paramètres › Établissement pour que ce message parte.'],
    geo.live?.plan === false && ['Géolocalisation hors de votre offre', 'Passez à une offre qui inclut la géolocalisation.'],
    geo.live?.privacy === false && ['Géolocalisation coupée', 'Réactivez-la dans Données & confidentialité.'],
    geo.live?.marketing === false && ['Communications marketing coupées', 'Réactivez-les dans Données & confidentialité.']].filter(Boolean);

  const Step2Geo = (
    <Card n={2} title="Zone de détection" sub="Définissez la zone autour de votre établissement où les passants recevront la notification.">
      {geoProblems.map(([t, h]) => (
        <p key={t} className="mb-3 flex items-start gap-2 rounded-xl bg-[#FFF7ED] px-3 py-2 text-[12px] text-[#9A3412]"><AlertTriangle size={15} className="mt-0.5 shrink-0" /><span><b>{t}.</b> {h}</span></p>
      ))}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="min-w-0 space-y-4">
          <div>
            <Label>{geo.anchors.length > 1 ? 'Vos établissements' : 'Votre établissement'}</Label>
            <div className="space-y-2">
              {geo.anchors.map((a) => {
                const on = (tr.stores || []).includes(a.id);
                return (
                  <div key={a.id} className={`flex items-center gap-3 rounded-xl border px-3 py-2.5 ${on ? 'border-[#BFD3FF] bg-[#F5F8FF]' : 'border-[#E2E8F0]'}`}>
                    {geo.anchors.length > 1 ? (
                      <input type="checkbox" aria-label={a.name} className="h-4 w-4 accent-[#1463FF]" checked={on}
                             onChange={() => setIn('trigger', { stores: on ? tr.stores.filter((x) => x !== a.id) : [...tr.stores, a.id] })} />
                    ) : <MapPin size={17} className="shrink-0 text-[#1463FF]" />}
                    <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-semibold text-[#0B1C3F]">{geo.anchors.length > 1 ? a.name : (a.address || a.name)}</span>
                      {geo.anchors.length > 1 && <span className="block truncate text-[11.5px] text-[#64748B]">{a.address || '—'}</span>}
                      {a.lat == null && <span className="block text-[11.5px] text-[#B45309]">Position inconnue</span>}</span>
                    <a href="/dashboard/parametres/etablissement" aria-label={`Modifier l'adresse de ${a.name}`} className="rounded-lg p-1.5 text-[#1463FF] hover:bg-white"><Pencil size={15} /></a>
                  </div>
                );
              })}
            </div>
          </div>
          <div>
            <Label>Rayon de détection</Label>
            <div className="grid grid-cols-4 gap-2" role="radiogroup" aria-label="Rayon de détection">
              {[...new Set([...geo.radii, Number(tr.radius_m) || 200])].sort((x, y) => x - y).map((r) => (
                <button key={r} type="button" role="radio" aria-checked={Number(tr.radius_m) === r} onClick={() => setIn('trigger', { radius_m: r })}
                        className={`rounded-xl border py-2.5 text-[13px] font-semibold ${Number(tr.radius_m) === r ? 'border-[#1463FF] bg-[#1463FF] text-white' : 'border-[#E2E8F0] bg-white text-[#334155] hover:border-[#BFD3FF]'}`}>{r} m</button>
              ))}
            </div>
            <p className="mt-2 flex items-start gap-2 rounded-xl bg-[#F1F6FF] px-3 py-2.5 text-[12px] leading-snug text-[#334155]"><Info size={15} className="mt-0.5 shrink-0 text-[#1463FF]" />
              <span>Les clients qui passent dans ce rayon voient votre carte et ce message sur leur écran verrouillé (Apple et Google Wallet), sans rien ouvrir. Le téléphone décide lui-même de la distance exacte (environ 100 m). Ce rayon est celui de votre établissement : il vaut pour toutes vos automatisations géolocalisées.</span></p>
          </div>
        </div>
        <GeoZoneMap anchors={zoneSpots} radius={Number(tr.radius_m) || 200} points={zone?.points || []} height={300} />
      </div>

      <div className="mt-5">
        <p className="flex items-center gap-2 text-[13.5px] font-bold text-[#0B1C3F]"><Clock size={17} className="text-[#1463FF]" /> Plage d'activation <span className="font-normal text-[#64748B]">(optionnel)</span></p>
        <p className="mb-2 text-[12px] text-[#64748B]">Choisissez quand la zone de détection est active.</p>
        <div className="grid gap-2 sm:grid-cols-3">
          {[['all', 'Toute la journée', '24h/24, 7j/7', allDay, () => setIn('schedule', { window: false, days: 'all', weekdays: [0, 1, 2, 3, 4, 5, 6] })],
            ['slots', 'Plages horaires', sc.window ? slotsText() : 'Ex : 11h – 14h / 17h – 21h', sc.window,
              () => (sc.window ? setIn('schedule', { window: false }) : setSlots(sc.slots?.length ? sc.slots : [{ from: '11:00', to: '14:00' }, { from: '17:00', to: '21:00' }]))],
            ['days', 'Jours spécifiques', sc.days !== 'all' ? geoDays() : 'Ex : du lundi au vendredi', sc.days !== 'all',
              () => (sc.days !== 'all' ? setIn('schedule', { days: 'all', weekdays: [0, 1, 2, 3, 4, 5, 6] }) : setDays([0, 1, 2, 3, 4]))]].map(([k, l, h, on, click]) => (
            <button key={k} type="button" onClick={click} aria-pressed={on}
                    className={`flex items-start gap-2.5 rounded-xl border p-3 text-left ${on ? 'border-[#2F6BFF] bg-[#F5F8FF]' : 'border-[#E2E8F0] hover:border-[#BFD3FF]'}`}>
              {on ? <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-[#1463FF]" /> : <span className="mt-0.5 h-[18px] w-[18px] shrink-0 rounded-full border-2 border-[#CBD5E1]" />}
              <span className="min-w-0"><span className="block text-[13px] font-semibold text-[#0B1C3F]">{l}</span><span className="block truncate text-[11.5px] text-[#64748B]">{h}</span></span>
            </button>
          ))}
        </div>
        <button type="button" onClick={() => go(5)} className="mt-1.5 text-[12px] font-semibold text-[#1463FF]">Régler les jours et les horaires en détail (Planification) →</button>
      </div>

      <div className="mt-4">
        <p className="mb-2 flex items-center gap-2 text-[13.5px] font-bold text-[#0B1C3F]"><Settings2 size={17} className="text-[#1463FF]" /> Conditions supplémentaires <span className="font-normal text-[#64748B]">(optionnel)</span></p>
        <div className="grid gap-2 sm:grid-cols-3">
          <MultiPick label="Tranche d'âge" icon={Users} options={AGES} values={f.age} allLabel="Tous les âges" onChange={(v) => setF({ age: v })} />
          <MultiPick label="Genre" icon={User} options={GENDERS} values={f.gender} allLabel="Tous" onChange={(v) => setF({ gender: v })} />
          <MultiPick label="Météo" icon={CloudSun} options={geo.weather.map((w) => [w.key, w.label])} values={tr.weather || []} allLabel="Toutes les conditions"
                     onChange={(v) => setIn('trigger', { weather: v })} />
        </div>
        <p className="mt-1.5 text-[11.5px] text-[#64748B]">
          {zone?.weather_now ? `Météo actuelle près de votre établissement : ${zone.weather_now.labels.join(', ').toLowerCase()}, ${zone.weather_now.temp} °C. ` : ''}
          L'âge et le genre sont les mêmes qu'à l'étape Ciblage. La météo se vérifie en direct (Froid : moins de 10 °C · Chaud : 25 °C et plus).</p>
      </div>
    </Card>
  );

  const Step4Geo = (
    <Card n={4} title="Ciblage" sub="Affinez qui reçoit la notification selon vos critères.">
      <p className="text-[13.5px] font-bold text-[#0B1C3F]">Type de passants</p>
      <p className="mb-2 text-[12px] text-[#64748B]">Choisissez les profils de personnes à cibler.</p>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4" role="radiogroup" aria-label="Type de passants">
        {PASSANTS.map(([k, l, h, v], i) => {
          const on = (tg.passants || 'all') === k;
          const I = [Users, UserPlus, RefreshCw, Star][i];
          return (
            <button key={k} type="button" role="radio" aria-checked={on} onClick={() => setIn('targeting', { passants: k })}
                    className={`relative rounded-xl border p-3 text-left ${on ? 'border-[#2F6BFF] bg-[#F5F8FF]' : 'border-[#E2E8F0] hover:border-[#BFD3FF]'}`}>
              <I size={20} className="mb-1.5 text-[#1463FF]" />
              <span className="block pr-5 text-[13px] font-bold leading-tight text-[#0B1C3F]">{l}</span>
              <span className="block text-[11.5px] leading-snug text-[#64748B]">{h}</span>
              {v && <span className="block text-[11px] text-[#94A3B8]">{v}</span>}
              {on && <CheckCircle2 size={17} className="absolute right-2 top-2 text-[#1463FF]" />}
            </button>
          );
        })}
      </div>
      <ChipRow title="Tranche d'âge" sub="Sélectionnez la tranche d'âge de votre audience." options={AGES} values={f.age} allLabel="Tous les âges" onChange={(v) => setF({ age: v })} />
      <ChipRow title="Genre (optionnel)" options={GENDERS} values={f.gender} onChange={(v) => setF({ gender: v })} />
      <ChipRow title="Type de client" sub="Selon le statut de la carte du client." options={CLIENT_TYPES} values={f.client_type || []} onChange={(v) => setF({ client_type: v })} />
      <ChipRow title="Dernière visite" sub="Ciblez selon la dernière visite (si déjà clients)." options={LAST_VISIT} values={f.last_visit} onChange={(v) => setF({ last_visit: v })} />
      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        <div className="flex items-center gap-3 rounded-2xl bg-[#F1F6FF] p-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#1463FF] text-white"><Users size={17} /></span>
          <span className="flex-1 text-[12.5px] font-semibold text-[#0B1C3F]">Clients ciblés</span>
          <span className="text-[18px] font-extrabold tabular-nums text-[#1463FF]">{preview ? preview.count.toLocaleString('fr-FR') : '…'}</span>
        </div>
        <div className="flex items-center gap-3 rounded-2xl bg-[#F0FDF4] p-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#059669] text-white"><Wallet size={17} /></span>
          <span className="flex-1 text-[12.5px] font-semibold text-[#0B1C3F]">Clients joignables<span className="block text-[11px] font-normal text-[#475569]">carte Wallet ou notifications activées</span></span>
          <span className="text-[18px] font-extrabold tabular-nums text-[#059669]">{preview?.reachable ? preview.reachable.total.toLocaleString('fr-FR') : '…'}</span>
        </div>
      </div>
    </Card>
  );

  const slotOpts = [...HOURS, '23:59'].map((h) => [h, h.replace(':00', 'h').replace(':30', 'h30')]);
  const Step5Geo = (
    <Card n={5} title="Planification" sub="Définissez quand votre automatisation est active.">
      <p className="text-[13.5px] font-bold text-[#0B1C3F]">Période d'activation</p>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <Option on={!sc.valid_from && !sc.valid_to} onClick={() => setIn('schedule', { valid_from: '', valid_to: '' })} icon={CalendarDays}
                title="En continu" sub="L'automatisation reste active sans date de fin." />
        <Option on={Boolean(sc.valid_from || sc.valid_to)} icon={CalendarDays} title="Période définie" sub="Choisissez une date de début et une date de fin."
                onClick={() => { if (!sc.valid_from && !sc.valid_to) setIn('schedule', { valid_from: new Date().toISOString().slice(0, 10), valid_to: '' }); }} />
      </div>
      {(sc.valid_from || sc.valid_to) && (
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <label className="block"><Label>Date de début</Label><input type="date" aria-label="Date de début" className={field} value={sc.valid_from || ''} onChange={(e) => setIn('schedule', { valid_from: e.target.value })} /></label>
          <label className="block"><Label>Date de fin</Label><input type="date" aria-label="Date de fin" className={field} value={sc.valid_to || ''} min={sc.valid_from || undefined} onChange={(e) => setIn('schedule', { valid_to: e.target.value })} /></label>
        </div>
      )}

      <p className="mt-4 text-[13.5px] font-bold text-[#0B1C3F]">Jours de diffusion</p>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7" role="group" aria-label="Jours de diffusion">
        {DAY_FULL.map((d, i) => {
          const on = sc.days === 'all' || (sc.days === 'weekdays' ? i < 5 : sc.weekdays.includes(i));
          const cur = sc.days === 'all' ? [0, 1, 2, 3, 4, 5, 6] : sc.days === 'weekdays' ? [0, 1, 2, 3, 4] : sc.weekdays;
          return (
            <label key={d} className={`flex cursor-pointer items-center gap-2 rounded-xl border px-2.5 py-2 text-[12.5px] font-medium ${on ? 'border-[#2F6BFF] bg-[#F5F8FF]' : 'border-[#E2E8F0]'}`}>
              <input type="checkbox" className="h-4 w-4 accent-[#1463FF]" checked={on} onChange={() => setDays(on ? cur.filter((x) => x !== i) : [...cur, i].sort())} /> {d}</label>
          );
        })}
      </div>

      <p className="mt-4 text-[13.5px] font-bold text-[#0B1C3F]">Horaires de diffusion</p>
      <p className="mb-2 text-[12px] text-[#64748B]">Choisissez les plages horaires pendant lesquelles l'automatisation est active.</p>
      <div className="grid gap-2 sm:grid-cols-2">
        <Option on={!sc.window} onClick={() => setIn('schedule', { window: false })} icon={Clock} title="Toute la journée" sub="24h/24" />
        <Option on={sc.window} onClick={() => { if (!sc.window) setSlots(sc.slots?.length ? sc.slots : [{ from: '11:00', to: '14:00' }, { from: '17:00', to: '21:00' }]); }}
                icon={Clock} title="Plages horaires spécifiques" sub="Ex : 11h – 14h / 17h – 21h" />
      </div>
      {sc.window && (
        <div className="mt-2 space-y-2">
          {(sc.slots || []).map((x, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2 rounded-xl bg-[#F8FAFC] p-2">
              <span className="text-[12.5px] text-[#475569]">De</span>
              <span className="w-28"><Select label={`Début de la plage ${i + 1}`} value={x.from} options={slotOpts} onChange={(v) => setSlots(sc.slots.map((y, j) => (j === i ? { ...y, from: v } : y)))} /></span>
              <span className="text-[12.5px] text-[#475569]">à</span>
              <span className="w-28"><Select label={`Fin de la plage ${i + 1}`} value={x.to} options={slotOpts} onChange={(v) => setSlots(sc.slots.map((y, j) => (j === i ? { ...y, to: v } : y)))} /></span>
              {x.to < x.from && <span className="text-[11.5px] text-[#64748B]">(jusqu'au lendemain)</span>}
              <button type="button" aria-label={`Retirer la plage ${i + 1}`} onClick={() => setSlots(sc.slots.filter((_, j) => j !== i))}
                      className="ml-auto rounded-lg p-1.5 text-[#DC2626] hover:bg-[#FEF2F2]"><Trash2 size={15} /></button>
            </div>
          ))}
          {(sc.slots || []).length < 6 && (
            <button type="button" onClick={() => setSlots([...(sc.slots || []), { from: '09:00', to: '12:00' }])}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-dashed border-[#BFD3FF] px-3 py-2 text-[12.5px] font-semibold text-[#1463FF]"><Plus size={14} /> Ajouter une plage</button>
          )}
        </div>
      )}

      <p className="mt-4 flex items-center gap-2 text-[13.5px] font-bold text-[#0B1C3F]">Heures de forte affluence <span className="font-normal text-[#64748B]">(optionnel)</span></p>
      <p className="mb-2 text-[12px] text-[#64748B]">{geo.busy ? `D'après les visites de vos clients, votre heure de pointe est ${geo.busy[0]}h – ${geo.busy[1]}h.` : "Pas encore assez de visites pour connaître vos heures de pointe : choisissez vos créneaux."}</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {RUSH.map((r) => {
          const [k, l, a, b] = r;
          const on = hasSlot(sc, a, b);
          return (
            <label key={k} className={`relative flex cursor-pointer items-start gap-2 rounded-xl border p-2.5 ${on ? 'border-[#2F6BFF] bg-[#F5F8FF]' : 'border-[#E2E8F0]'}`}>
              <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[#1463FF]" checked={on}
                     onChange={() => setSlots(on ? sc.slots.filter((x) => !(x.from === a && x.to === b)) : [...(sc.window ? sc.slots || [] : []), { from: a, to: b }])} />
              <span><span className="block text-[12.5px] font-semibold text-[#0B1C3F]">{l}</span><span className="text-[11.5px] text-[#64748B]">{hLabel(a)} – {hLabel(b)}</span>
                {overlaps(r, geo.busy) && <span className="mt-1 block w-fit rounded-full bg-[#DCFCE7] px-1.5 text-[10.5px] font-semibold text-[#047857]">Recommandé</span>}</span>
            </label>
          );
        })}
      </div>

      <div className="mt-4 flex items-center gap-3 rounded-2xl border border-[#E6EEFB] p-3">
        <Flag size={18} className="shrink-0 text-[#1463FF]" />
        <span className="min-w-0 flex-1"><span className="block text-[13px] font-semibold text-[#0B1C3F]">Jours fériés <span className="font-normal text-[#64748B]">(optionnel)</span></span>
          <span className="text-[12px] text-[#64748B]">Diffuser l'automatisation pendant les jours fériés.</span></span>
        <Toggle label="Diffuser pendant les jours fériés" on={sc.holidays !== false} onChange={(v) => setIn('schedule', { holidays: v })} />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 rounded-2xl border border-[#E6EEFB] p-3 text-[13px]">
        <RefreshCw size={18} className="shrink-0 text-[#1463FF]" />
        <span className="font-semibold text-[#0B1C3F]">Fréquence par client :</span> au plus une fois tous les
        <Num value={tr.cooldown_days} min={1} max={90} label="Délai entre deux messages" onChange={(v) => setIn('trigger', { cooldown_days: v })} /> jours
      </div>
      <p className="mt-3 flex items-start gap-2 text-[11.5px] text-[#64748B]"><Info size={13} className="mt-0.5 shrink-0" />
        {page.tick ? 'Les cartes Wallet suivent ces jours, horaires et la météo, mises à jour toutes les 15 minutes.'
          : "Quand la carte est ouverte, tout s'applique à la minute. Sur l'écran verrouillé, les cartes Wallet sont mises à jour une fois par jour ; à la minute près dès l'envoi programmé toutes les 15 minutes."}</p>
    </Card>
  );

  // ---- Avis Google (updated mockups 2026-10-11) -----------------------------------
  const AVIS_TRIGGERS = [['after_visit', CalendarDays, 'Après la visite', "Envoyer la demande d'avis un certain temps après la dernière visite du client.", '#EAF1FF', '#2F6BFF'],
    ['loyal', Star, 'Client fidèle', "Envoyer la demande d'avis après un certain nombre de visites.", '#FFF4E0', '#F59E0B'],
    ['date', CalendarDays, 'Date spécifique', "Envoyer la demande d'avis à une date précise (ex : après un événement).", '#EAF1FF', '#2F6BFF']];
  const Step2Avis = (
    <Card n={2} title="Déclencheur" sub="Choisissez quand envoyer automatiquement la demande d'avis.">
      {!page.google_review_ready && googleKeys.every((k) => !links[k]) && (
        <p className="mb-3 rounded-xl bg-[#FFF7ED] px-3 py-2 text-[12px] text-[#9A3412]">Ajoutez votre lien Google à l'étape Scénario : aucune demande ne part sans lui.</p>
      )}
      <div className="grid gap-3 sm:grid-cols-3" role="radiogroup" aria-label="Déclencheur">
        {AVIS_TRIGGERS.map(([k, I, l, h, bg, fg]) => {
          const on = (tr.type || 'after_visit') === k;
          return (
            <button key={k} type="button" role="radio" aria-checked={on}
                    onClick={() => setIn('trigger', { type: k, ...(k === 'date' && tr.frequency === 'smart' ? { frequency: 'once' } : {}) })}
                    className={`relative rounded-2xl border p-4 text-left transition ${on ? 'border-[#2F6BFF] bg-[#F5F8FF]' : 'border-[#E2E8F0] hover:border-[#BFD3FF]'}`}>
              <span className="mb-2 flex h-10 w-10 items-center justify-center rounded-xl" style={{ background: bg, color: fg }}><I size={20} /></span>
              <span className="block pr-5 text-[14px] font-bold text-[#0B1C3F]">{l}</span>
              <span className="mt-0.5 block text-[12px] leading-snug text-[#64748B]">{h}</span>
              {on && <CheckCircle2 size={18} className="absolute right-3 top-3 text-[#1463FF]" />}
            </button>
          );
        })}
      </div>
      <p className="mb-2 mt-5 text-[15px] font-bold text-[#0B1C3F]">Configurer le déclencheur</p>
      <div className="rounded-2xl bg-[#F5F8FF] p-4">
        {(tr.type || 'after_visit') === 'after_visit' && (
          <>
            <p className="mb-2 flex items-center gap-2 text-[13px] font-semibold text-[#475569]">Délai après la visite
              <span title="Le temps qui sépare la visite (le scan de la carte) de la demande d'avis."><Info size={14} /></span></p>
            <span className="flex flex-wrap items-center gap-2 text-[13px] text-[#475569]">
              <Num value={tr.delay_value ?? 0} min={0} max={365} label="Délai après la visite" onChange={(v) => setIn('trigger', { delay_value: v })} />
              <span className="w-36"><Select label="Unité du délai" value={tr.delay_unit === 'days' ? 'days' : 'hours'} onChange={(v) => setIn('trigger', { delay_unit: v })}
                                             options={[['hours', 'heures'], ['days', 'jours']]} /></span>
              après la dernière visite du client.</span>
          </>
        )}
        {tr.type === 'loyal' && (
          <span className="flex flex-wrap items-center gap-2 text-[13px] text-[#475569]">Envoyer à la
            <Num value={tr.visits} digits={4} min={1} max={1000} label="Nombre de visites" onChange={(v) => setIn('trigger', { visits: v })} />
            <span>{Number(tr.visits) === 1 ? 're' : 'e'} visite du client, </span>
            <Num value={tr.delay_value ?? 0} min={0} max={365} label="Délai après cette visite" onChange={(v) => setIn('trigger', { delay_value: v })} />
            <span className="w-32"><Select label="Unité" value={tr.delay_unit === 'days' ? 'days' : 'hours'} onChange={(v) => setIn('trigger', { delay_unit: v })} options={[['hours', 'heures'], ['days', 'jours']]} /></span>
            après.</span>
        )}
        {tr.type === 'date' && (
          <span className="flex flex-wrap items-center gap-2 text-[13px] text-[#475569]">Envoyer le
            <input type="date" aria-label="Date d'envoi" className={`${field} !w-48`} value={tr.date || ''} min={new Date().toISOString().slice(0, 10)}
                   onChange={(e) => setIn('trigger', { date: e.target.value })} />
            <span>à l'heure choisie à l'étape Planification.</span></span>
        )}
        <div className="mt-3 flex items-start gap-2 rounded-xl bg-white/70 px-3 py-2.5 text-[12.5px] text-[#334155]"><Info size={16} className="mt-0.5 shrink-0 text-[#1463FF]" />
          <span><b className="block text-[#1463FF]">Recommandation</b>Envoyez la demande d'avis entre 1 et 4 heures après la visite, lorsque l'expérience est encore fraîche dans l'esprit du client.</span></div>
      </div>
    </Card>
  );

  const FREQ_CARDS = [['once', Navigation, 'Une seule fois', 'Envoyer la demande une seule fois selon le déclencheur.'],
    ['days', RefreshCw, 'Répétition régulière', 'Envoyer plusieurs fois selon une fréquence définie.'],
    ['smart', Sparkles, 'Envoi intelligent', 'FidClic AI choisit le meilleur moment pour chaque client (selon son comportement).']];
  const Step5Avis = (
    <Card n={5} title="Planification" sub="Définissez quand et à quelle fréquence envoyer la demande d'avis.">
      <p className="flex items-center gap-2 text-[13.5px] font-bold text-[#0B1C3F]">Jours d'envoi</p>
      <div className="mt-2 grid grid-cols-4 gap-2 sm:grid-cols-7" role="group" aria-label="Jours d'envoi">
        {DAY_NAMES.map((d, i) => {
          const on = sc.days === 'all' || (sc.days === 'weekdays' ? i < 5 : sc.weekdays.includes(i));
          const cur = sc.days === 'all' ? [0, 1, 2, 3, 4, 5, 6] : sc.days === 'weekdays' ? [0, 1, 2, 3, 4] : sc.weekdays;
          return (
            <label key={d} className={`flex cursor-pointer items-center gap-2 rounded-xl border px-2.5 py-2 text-[12.5px] font-medium ${on ? 'border-[#2F6BFF] bg-[#F5F8FF]' : 'border-[#E2E8F0]'}`}>
              <input type="checkbox" className="h-4 w-4 accent-[#1463FF]" checked={on}
                     onChange={() => { const w = on ? cur.filter((x) => x !== i) : [...cur, i].sort(); setIn('schedule', { weekdays: w, days: w.length === 7 ? 'all' : 'specific' }); }} /> {d}</label>
          );
        })}
      </div>
      {tr.type === 'date' && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="block"><Label>Heure d'envoi</Label>
            <Select label="Heure d'envoi" value={sc.hour} onChange={(v) => setIn('schedule', { hour: v })} options={HOURS.map((h) => [h, h])} /></label>
          <label className="block"><Label>Fuseau horaire</Label>
            <span className={`${field} flex items-center gap-2 bg-[#F8FAFC]`}><Globe size={15} className="text-[#64748B]" /> ({parisOffset().replace('GMT', 'GMT')}) Paris</span></label>
        </div>
      )}
      <p className="mt-4 text-[13.5px] font-bold text-[#0B1C3F]">Fréquence d'envoi</p>
      <div className="mt-2 grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Fréquence d'envoi">
        {FREQ_CARDS.map(([k, I, l, h]) => {
          const on = (tr.frequency || 'once') === k;
          const off = k === 'smart' && tr.type === 'date';
          return (
            <button key={k} type="button" role="radio" aria-checked={on} disabled={off} onClick={() => setIn('trigger', { frequency: k })}
                    title={off ? "Pour une date précise, l'heure d'envoi s'applique." : undefined}
                    className={`relative rounded-xl border p-3 text-left disabled:opacity-50 ${on ? 'border-[#2F6BFF] bg-[#F5F8FF]' : 'border-[#E2E8F0] hover:border-[#BFD3FF]'}`}>
              <span className="flex items-center gap-2"><I size={19} className={k === 'smart' ? 'text-[#7C3AED]' : 'text-[#1463FF]'} />
                {k === 'smart' && <span className="inline-flex items-center gap-1 rounded-full bg-[#DCFCE7] px-1.5 text-[10.5px] font-semibold text-[#047857]"><CheckCircle2 size={11} /> Recommandé</span>}</span>
              <span className="mt-1.5 block pr-5 text-[13.5px] font-bold text-[#0B1C3F]">{l}</span>
              <span className="text-[11.5px] leading-snug text-[#64748B]">{h}</span>
              {on ? <CheckCircle2 size={18} className="absolute right-2.5 top-2.5 text-[#1463FF]" /> : <span className="absolute right-2.5 top-2.5 h-[18px] w-[18px] rounded-full border-2 border-[#CBD5E1]" />}
            </button>
          );
        })}
      </div>
      {tr.frequency === 'days' && (
        <span className="mt-2 flex items-center gap-2 text-[12.5px] text-[#475569]">Au plus une fois tous les
          <Num value={tr.every_days} min={1} max={365} label="Répéter tous les (jours)" onChange={(v) => setIn('trigger', { every_days: v })} /> jours par client</span>
      )}
      <div className="mt-3 flex items-center gap-3 rounded-2xl bg-[#FAF7FF] p-3">
        <Toggle label="Plage d'envoi intelligente" on={sc.window} onChange={(v) => setIn('schedule', { window: v, window_from: '08:00', window_to: '20:00', slots: [] })} />
        <Sparkles size={20} className="shrink-0 text-[#7C3AED]" />
        <span className="min-w-0"><span className="block text-[13px] font-bold text-[#0B1C3F]">Plage d'envoi intelligente (FidClic AI)</span>
          <span className="text-[12px] text-[#64748B]">Envoie automatiquement la demande au moment où le client est le plus susceptible de répondre (entre 8h et 20h).</span></span>
      </div>
      <p className="mt-4 flex items-center gap-2 text-[13.5px] font-bold text-[#0B1C3F]">Période de validité de l'automatisation</p>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <label className="block"><span className="mb-1 block text-[12px] text-[#475569]">Date de début</span>
          <input type="date" aria-label="Date de début" className={field} value={sc.valid_from || ''} onChange={(e) => setIn('schedule', { valid_from: e.target.value })} /></label>
        <label className="block"><span className="mb-1 block text-[12px] text-[#475569]">Date de fin (optionnel)</span>
          <input type="date" aria-label="Date de fin" className={field} value={sc.valid_to || ''} min={sc.valid_from || undefined} onChange={(e) => setIn('schedule', { valid_to: e.target.value })} /></label>
      </div>
      <p className="mt-3 flex items-start gap-2 text-[11.5px] text-[#64748B]"><Info size={13} className="mt-0.5 shrink-0" />
        Un client qui a déjà ouvert votre page d'avis ne reçoit plus de demande.{!page.tick ? " L'envoi à la minute près arrive avec l'envoi programmé toutes les 15 minutes ; en attendant, les messages en attente partent avec l'envoi du matin." : ''}</p>
    </Card>
  );

  const VarMenu = ({ which }) => (
    <span className="relative shrink-0">
      <button type="button" onClick={() => { lastFocus.current = which; setVarMenu(varMenu === which ? '' : which); }}
              className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg px-2 py-2 text-[12.5px] font-medium text-[#1463FF] hover:bg-[#F1F6FF]">
        <PlusCircle size={15} /> Insérer une variable <ChevronDown size={13} /></button>
      {varMenu === which && (
        <span className="absolute right-0 top-10 z-30 w-60 rounded-xl border border-[#E2E8F0] bg-white p-1.5 shadow-xl">
          {variables.map((v) => (
            <button key={v} type="button" onClick={() => { lastFocus.current = which; insert(`{${v}}`); setVarMenu(''); }}
                    className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] hover:bg-[#F8FAFC]">
              <span className="text-[#0B1C3F]">{VAR_LABELS[v] || v}</span><span className="font-mono text-[11px] text-[#1D4ED8]">{`{${v}}`}</span></button>
          ))}
        </span>
      )}
    </span>
  );
  const LINK_HELP = {
    card: 'Le client sera redirigé vers sa carte de fidélité.',
    rewards: 'Le client sera redirigé vers la page des offres et récompenses.',
    offer: "Le client sera redirigé directement vers l'offre choisie.",
    google_review: "Le client sera redirigé vers votre page d'avis Google.",
    url: 'Le client sera redirigé vers le lien de votre choix.',
  };
  // Avis Google step 3 (mockup): the image tiles beside the button and its link
  const singleGoogle = googleStores.length <= 1;
  const AvisMedia = (
    <div className="mt-4 grid gap-4 sm:grid-cols-2">
      <div>
        <Label>Image <span className="font-normal text-[#64748B]">(optionnelle)</span></Label>
        <div className="grid grid-cols-2 gap-2">
          {msg.image_url ? (
            <span className="relative block overflow-hidden rounded-xl border border-[#E6EEFB] bg-[#F5F8FF]">
              <img src={msg.image_url} alt="Image de la notification" className="aspect-[1200/628] w-full object-cover" />
              <button type="button" onClick={() => setMsg({ image_url: null })} aria-label="Supprimer l'image"
                      className="absolute right-1.5 top-1.5 rounded-lg bg-white/90 p-1 text-[#1463FF] shadow hover:text-[#DC2626]"><Trash2 size={14} /></button>
            </span>
          ) : (
            <button type="button" onClick={() => setMsg({ image_url: AVIS_IMAGE })}
                    className="rounded-xl border border-dashed border-[#BFD3FF] p-2 text-center text-[11.5px] text-[#1463FF]">Remettre l'image Google</button>
          )}
          <button type="button" onClick={() => fileRef.current?.click()}
                  className="flex flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-[#9DB9FF] bg-white p-2 text-center">
            <ImageIcon size={20} className="text-[#1463FF]" />
            <span className="text-[12.5px] font-semibold text-[#1463FF]">Changer l'image</span>
            <span className="text-[10.5px] text-[#64748B]">JPG, PNG · Max 2 Mo<br />Recommandé : 1200 × 628 px</span>
          </button>
        </div>
      </div>
      <div>
        <Label>Bouton d'action</Label>
        <label className="block"><span className="mb-1 flex justify-between text-[12px] text-[#475569]"><span>Texte du bouton</span><span>{btn.label.length}/{BUTTON_MAX}</span></span>
          <input className={field} value={btn.label} maxLength={BUTTON_MAX} onChange={(e) => setBtn({ label: e.target.value, enabled: true })} placeholder="Laisser un avis" /></label>
        <label className="mt-2 block"><span className="mb-1 block text-[12px] text-[#475569]">Lien</span>
          <span className={`${field} flex items-center gap-2 !py-0`}><Link2 size={16} className="shrink-0 text-[#64748B]" />
            <input className="min-w-0 flex-1 !border-0 bg-transparent py-2.5 !text-[14px] !shadow-none !outline-none !ring-0" inputMode="url" aria-label="Lien du bouton"
                   value={btn.link_type === 'url' ? btn.url : singleGoogle ? (links.main || '') : "Lien Google de l'établissement visité"}
                   readOnly={btn.link_type !== 'url' && !singleGoogle}
                   onChange={(e) => {
                     const v = e.target.value;
                     // the Google link stays « google_review » (clicks counted, asked once); anything else is a custom link
                     if (singleGoogle && fullLink(v) === fullLink(links.main)) setBtn({ link_type: 'google_review', url: '', enabled: true });
                     else setBtn({ link_type: 'url', url: v, enabled: true });
                   }} /></span>
          <span className="mt-1 block text-[11px] text-[#64748B]">{btn.link_type === 'url'
            ? <>Un lien personnalisé. <button type="button" className="font-semibold text-[#1463FF]" onClick={() => setBtn({ link_type: 'google_review', url: '' })}>Revenir au lien Google</button></>
            : 'Le lien de votre fiche Google (étape Scénario) : le client qui l\'ouvre ne reçoit plus de demande.'}</span></label>
      </div>
    </div>
  );

  const Step3 = (
    <Card n={welcomeOn ? 2 : 3} title="Message" sub={welcomeOn ? 'Personnalisez le message qui sera envoyé à vos clients.' : 'Personnalisez le contenu de votre notification.'}>
      {!['google_review', 'welcome'].includes(s.scenario) && <p className="mb-3 inline-flex rounded-xl border border-[#2F6BFF] bg-[#F5F8FF] px-4 py-2 text-[13px] font-semibold text-[#1463FF]">Notification Wallet</p>}
      {tiered && (
        <div className="mb-3">
          <p className="mb-1.5 text-[12px] text-[#64748B]">Un message par palier — choisissez le palier à rédiger :</p>
          <div className="flex flex-wrap gap-1.5">
            {tr.tiers.map((t, i) => {
              const done = String(t.title || '').trim() && String(t.body || '').trim();
              return (
                <button key={i} type="button" onClick={() => setTierTab(i)}
                        className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-[12.5px] font-semibold ${i === tabIx ? 'border-[#2F6BFF] bg-[#1463FF] text-white' : 'border-[#E2E8F0] bg-white text-[#334155]'}`}>
                  <Award size={13} /> {palierLabel(tr.condition, t.value)} {!done && <span className={`h-1.5 w-1.5 rounded-full ${i === tabIx ? 'bg-white' : 'bg-[#F59E0B]'}`} />}
                </button>
              );
            })}
          </div>
        </div>
      )}
      <Label right={`${(cur.title || '').length}/${TITLE_MAX}`}>{['inactive', 'welcome', 'near_reward'].includes(s.scenario) ? 'Titre de la notification' : 'Titre'}{tiered ? ` — palier ${palierLabel(tr.condition, cur.value)}` : ''}</Label>
      <div className="flex items-center gap-2">
        <input ref={titleRef} className={field} value={cur.title || ''} maxLength={TITLE_MAX} onFocus={() => { lastFocus.current = 'title'; }}
               onChange={(e) => setCur({ title: e.target.value })} placeholder={m.title || 'Le titre de votre notification'} />
        <VarMenu which="title" />
      </div>
      {['inactive', 'near_reward'].includes(s.scenario) && (
        <div className="mt-2 flex flex-wrap gap-2">{(s.scenario === 'near_reward' ? nrVars(near.unit) : INACTIVE_VARS.filter((v) => v !== 'lien')).map((v) => (
          <button key={v} type="button" onMouseDown={() => { lastFocus.current = 'title'; }} onClick={() => { lastFocus.current = 'title'; insert(`{${v}}`); }}
                  className="inline-flex items-center gap-1 rounded-lg border border-[#DCE5F3] px-2.5 py-1 text-[12px] font-semibold text-[#1D4ED8] hover:bg-[#F5F8FF]"><Plus size={12} /> {(s.scenario === 'near_reward' ? NR_VAR_LABELS : INACTIVE_VAR_LABELS)[v]}</button>
        ))}</div>
      )}
      <div className="mt-3"><Label right={`${(cur.body || '').length}/${BODY_MAX}`}>{['inactive', 'welcome', 'near_reward'].includes(s.scenario) ? 'Texte de la notification' : 'Message'}</Label></div>
      <div className="flex items-start gap-2">
        <textarea ref={bodyRef} className={`${field} min-h-[96px] resize-y`} value={cur.body || ''} maxLength={BODY_MAX}
                  onFocus={() => { lastFocus.current = 'body'; }} onChange={(e) => setCur({ body: e.target.value })}
                  placeholder={m.body || 'Votre message, par exemple : Bonjour {prénom}, merci pour votre fidélité !'} />
        <VarMenu which="body" />
      </div>
      {s.scenario === 'welcome' && <p className="mt-3 text-[13.5px] font-bold text-[#0B1C3F]">Variables disponibles</p>}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {(s.scenario === 'geo' ? ['prénom', 'établissement', 'offre', 'distance', ...variables.filter((v) => !['prénom', 'établissement', 'offre', 'distance'].includes(v))]
          : s.scenario === 'google_review' ? ['nom', 'prénom', 'établissement', 'lien_avis']
          : s.scenario === 'inactive' ? INACTIVE_VARS : s.scenario === 'welcome' ? WELCOME_VARS : s.scenario === 'near_reward' ? nrVars(near.unit) : variables).map((v) => (
          <button key={v} type="button" title={`${VAR_LABELS[v] || v} — {${v}}`} onMouseDown={() => { if (s.scenario === 'inactive') lastFocus.current = 'body'; }}
                  onClick={() => { if (s.scenario === 'inactive') lastFocus.current = 'body'; insert(`{${v}}`); }}
                  className="inline-flex items-center gap-1 rounded-lg bg-[#EEF4FF] px-2.5 py-1 text-[12px] font-semibold text-[#1D4ED8] hover:bg-[#E0EAFF]"><Plus size={12} /> {(s.scenario === 'inactive' && INACTIVE_VAR_LABELS[v]) || (s.scenario === 'welcome' && WELCOME_VAR_LABELS[v]) || (s.scenario === 'near_reward' && NR_VAR_LABELS[v]) || VAR_SHORT[v] || v}</button>
        ))}
        <span className="relative">
          <button type="button" onClick={() => setEmoji((x) => (x ? '' : 'open'))} aria-label="Ajouter un emoji"
                  className="rounded-lg border border-[#E2E8F0] p-1.5 text-[#475569] hover:bg-[#F8FAFC]"><Smile size={16} /></button>
          {emoji && (
            <span className="absolute left-0 top-9 z-20 grid w-64 grid-cols-8 gap-1 rounded-xl border border-[#E2E8F0] bg-white p-2 shadow-xl">
              {EMOJIS.map((e) => <button key={e} type="button" className="rounded p-1 text-[16px] hover:bg-[#F1F5F9]" onClick={() => { insert(e); setEmoji(''); }}>{e}</button>)}
            </span>
          )}
        </span>
      </div>
      {tiered && <p className="mt-2 text-[11.5px] text-[#64748B]">L'image et le bouton ci-dessous sont communs à tous les paliers.</p>}
      {s.scenario === 'near_reward' && (
        <div className="mt-3 flex items-start gap-3 rounded-xl bg-[#F1F6FF] px-3 py-2.5 text-[12.5px] text-[#334155]"><Info size={17} className="mt-0.5 shrink-0 text-[#1463FF]" />
          <span><b className="block text-[#0B1C3F]">Exemple de variables :</b>
            <span className="block">{'{prénom}'} → le prénom du client</span>
            <span className="block">{near.unit === 'tampons' ? '{tampons} → le nombre de tampons sur la carte' : '{points} → le nombre de points actuels'}</span>
            <span className="block">{near.unit === 'tampons' ? '{tampons_restants} → les tampons restants avant la récompense (ex. « 1 tampon »)' : '{points_restants} → les points restants avant la récompense (ex. « 10 points »)'}</span>
            <span className="block">{'{récompense}'} → le nom de la récompense (celle de la carte, ou du prochain palier)</span></span>
        </div>
      )}
      {s.scenario === 'geo' && (
        <p className="mt-3 flex items-start gap-2 rounded-xl bg-[#F1F6FF] px-3 py-2.5 text-[12px] text-[#334155]"><Info size={15} className="mt-0.5 shrink-0 text-[#1463FF]" />
          <span>Sur l'écran verrouillé, l'iPhone affiche ce message près de votre établissement ; Google Wallet y écrit son propre texte. Un appui ouvre la carte, où votre message et son bouton s'affichent. {'{distance}'} n'est connue que si la carte est ouverte : écrivez « à {'{distance}'} », cela donne « à 80 m », ou « à deux pas » sur l'écran verrouillé.</span></p>
      )}
      <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={pickImage} />
      {s.scenario === 'google_review' ? AvisMedia : (<>
      <div className="mt-4 flex flex-wrap items-center gap-3 rounded-2xl border border-[#E6EEFB] p-4">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#F1EAFF] text-[#7C3AED]"><ImageIcon size={18} /></span>
        <span className="min-w-0 flex-1"><span className="block text-[13.5px] font-bold text-[#0B1C3F]">Ajouter une image <span className="font-normal text-[#64748B]">(optionnel)</span></span>
          <span className="text-[12px] text-[#64748B]">Une image rend votre notification plus attractive. PNG ou JPG, 2 Mo max.</span></span>
        {msg.image_url ? (
          <span className="flex items-center gap-2">
            <img src={msg.image_url} alt="" className="h-14 w-14 rounded-xl object-cover" />
            <button type="button" onClick={() => fileRef.current?.click()} className="rounded-lg border border-[#BFD3FF] px-3 py-1.5 text-[12.5px] font-semibold text-[#1463FF]">Changer l'image</button>
            <button type="button" onClick={() => setMsg({ image_url: null })} aria-label="Supprimer l'image" className="rounded-lg p-2 text-[#DC2626] hover:bg-[#FEF2F2]"><Trash2 size={15} /></button>
          </span>
        ) : (
          <button type="button" onClick={() => fileRef.current?.click()} className="rounded-lg border border-[#BFD3FF] px-3 py-1.5 text-[12.5px] font-semibold text-[#1463FF]">Ajouter une image</button>
        )}
      </div>
      <div className="mt-3 rounded-2xl border border-[#E6EEFB] p-4">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><Link2 size={18} /></span>
          <span className="min-w-0 flex-1"><span className="block text-[13.5px] font-bold text-[#0B1C3F]">Bouton d'action <span className="font-normal text-[#64748B]">(optionnel)</span></span>
            <span className="text-[12px] text-[#64748B]">Ajoutez un bouton pour rediriger vers une offre, une récompense, votre site…</span></span>
          <Toggle label="Bouton d'action" on={btn.enabled} onChange={(v) => setBtn({ enabled: v })} />
        </div>
        {btn.enabled && (
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="block"><Label right={`${btn.label.length}/${BUTTON_MAX}`}>Texte du bouton</Label>
              <input className={field} value={btn.label} maxLength={BUTTON_MAX} onChange={(e) => setBtn({ label: e.target.value })} placeholder="Voir ma récompense" /></label>
            <label className="block"><Label>Lien d'action</Label>
              <Select label="Lien du bouton" value={btn.link_type} onChange={(v) => setBtn({ link_type: v })}
                      options={[['rewards', 'Page Récompenses'], ['card', 'La carte du client'], ['offer', 'Une de vos offres'], ['google_review', "Votre page d'avis Google"], ['url', 'Un lien personnalisé']]} />
              <span className="mt-1 block text-[11.5px] text-[#64748B]">{LINK_HELP[btn.link_type]}</span></label>
            {btn.link_type === 'offer' && (
              <label className="block sm:col-span-2"><Label>Offre</Label>
                {page.offers.length ? (
                  <Select label="Offre" value={btn.offer_id || ''} onChange={(v) => setBtn({ offer_id: v || null })}
                          options={[['', 'Sélectionner une offre'], ...page.offers.map((o) => [o.id, o.terms ? `${o.name} — ${o.terms}` : o.name])]} />
                ) : <p className="rounded-xl bg-[#FFF7ED] px-3 py-2 text-[12px] text-[#9A3412]">Aucune offre en cours : créez-en une dans Campagnes, ou choisissez un autre lien.</p>}
              </label>
            )}
            {btn.link_type === 'url' && (
              <label className="block sm:col-span-2"><Label>Adresse du lien</Label>
                <input className={field} value={btn.url || ''} onChange={(e) => setBtn({ url: e.target.value })} placeholder="monsite.fr/reservation" inputMode="url" /></label>
            )}
            {btn.link_type === 'google_review' && !page.google_review_ready && (
              <p className="rounded-xl bg-[#FFF7ED] px-3 py-2 text-[12px] text-[#9A3412] sm:col-span-2">Ajoutez d'abord votre lien Google dans Insights › Avis Google.</p>
            )}
          </div>
        )}
      </div>
      </>)}
    </Card>
  );

  const MODES = [['all', 'Tous mes clients', 'Envoyer à toute ma base clients.', Users], ['segment', 'Segment de clients', 'Envoyer à un segment spécifique.', Tags],
    ['wallet', 'Clients avec carte Wallet', 'Uniquement les clients ayant ajouté leur carte.', Wallet]];
  const Step4 = (
    <Card n={4} title="Ciblage" sub="À quels clients envoyer cette notification ?">
      <div className="grid gap-3 sm:grid-cols-3">
        {MODES.map(([k, l, h, I]) => (
          <button key={k} type="button" onClick={() => setIn('targeting', { mode: k })}
                  className={`flex items-start gap-3 rounded-2xl border p-4 text-left transition ${tg.mode === k ? 'border-[#2F6BFF] bg-[#F5F8FF]' : 'border-[#E2E8F0] hover:border-[#BFD3FF]'}`}>
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><I size={20} /></span>
            <span className="min-w-0 flex-1"><span className="block text-[13px] font-bold text-[#0B1C3F]">{l}</span><span className="text-[12px] text-[#64748B]">{h}</span></span>
            <Radio on={tg.mode === k} />
          </button>
        ))}
      </div>
      {tg.mode === 'segment' && (
        <div className="mt-3 max-h-[220px] space-y-1.5 overflow-y-auto">
          {page.segments.map((x) => (
            <label key={x.key} className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 ${tg.segment === x.key ? 'border-[#2F6BFF] bg-[#F1F6FF]' : 'border-[#E2E8F0]'}`}>
              <input type="radio" name="au-seg" checked={tg.segment === x.key} onChange={() => setIn('targeting', { segment: x.key })} className="accent-[#1463FF]" />
              <span className="flex-1"><span className="block text-[13px] font-semibold text-[#0B1C3F]">{x.label}</span><span className="text-[11.5px] text-[#64748B]">{x.hint}</span></span>
              <span className="text-[12px] font-semibold tabular-nums text-[#475569]">{(x.count ?? 0).toLocaleString('fr-FR')}</span>
            </label>
          ))}
        </div>
      )}
      <div className="mt-4 flex items-center gap-3 rounded-2xl bg-[#F1F6FF] p-4">
        <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#1463FF] text-white"><Users size={18} /></span>
        <span className="flex-1 text-[13px] font-semibold text-[#0B1C3F]">Clients ciblés aujourd'hui</span>
        <span className="text-[20px] font-extrabold tabular-nums text-[#1463FF]">{preview ? preview.count.toLocaleString('fr-FR') : '…'}</span>
      </div>
      {tg.mode !== 'all' && (
        <div className="mt-4">
          <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
            <span><span className="block text-[14px] font-bold text-[#0B1C3F]">Filtres avancés <span className="font-normal text-[#64748B]">(optionnel)</span></span>
              <span className="text-[12px] text-[#64748B]">Affinez votre ciblage en ajoutant des critères supplémentaires.</span></span>
            <button type="button" onClick={() => setIn('targeting', { filters: { ...EMPTY_FILTERS } })}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-[#BFD3FF] px-3 py-1.5 text-[12.5px] font-semibold text-[#1463FF]"><RotateCcw size={14} /> Réinitialiser les filtres</button>
          </div>
          <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-6">
            <FilterTile icon={User} label="Genre">
              <Select label="Genre" value={one(f.gender)} onChange={pick('gender')}
                      options={withMulti(f.gender, [['', 'Tous'], ...GENDERS])} />
            </FilterTile>
            <FilterTile icon={CalendarDays} label="Âge">
              <span className="flex items-center gap-1.5">
                <Select tight label="Âge à partir de" value={String(f.age_min ?? '')} onChange={(v) => setF({ age_min: v, age: [] })}
                        options={[['', 'Tous'], ...AGE_STEPS.map((x) => [String(x), String(x)])]} />
                <span className="text-[#64748B]">–</span>
                <Select tight label="Âge jusqu'à" value={String(f.age_max ?? '')} onChange={(v) => setF({ age_max: v, age: [] })}
                        options={[['', '65+'], ...AGE_STEPS.filter((x) => x < 65).map((x) => [String(x), String(x)])]} />
              </span>
            </FilterTile>
            <FilterTile icon={Euro} label="Montant des achats">
              <Select label="Montant des achats" value={one(f.spent)} onChange={pick('spent')}
                      options={withMulti(f.spent, [['', 'Tous'], ...SPENT])} />
            </FilterTile>
            <FilterTile icon={CalendarDays} label="Dernière visite" wide>
              <Select label="Dernière visite" value={one(f.last_visit)} onChange={pick('last_visit')}
                      options={withMulti(f.last_visit, [['', 'Tous'], ...LAST_VISIT])} />
            </FilterTile>
            <FilterTile icon={RotateCcw} label="Nombre de visites" wide>
              <span className="flex items-center gap-1.5 text-[12.5px] text-[#475569]">
                <input inputMode="numeric" aria-label="Nombre de visites minimum" placeholder="min" value={f.visits_min ?? ''}
                       onChange={(e) => setF({ visits_min: e.target.value.replace(/\D/g, '').slice(0, 5) })} className={`${field} !py-2 text-center`} />
                à
                <input inputMode="numeric" aria-label="Nombre de visites maximum" placeholder="max" value={f.visits_max ?? ''}
                       onChange={(e) => setF({ visits_max: e.target.value.replace(/\D/g, '').slice(0, 5) })} className={`${field} !py-2 text-center`} />
              </span>
              <span className="mt-1 block text-[11px] text-[#94A3B8]">{f.visits_min === '' && f.visits_max === '' ? 'Vide = tous' : 'Visites depuis l\'inscription'}</span>
            </FilterTile>
            <FilterTile icon={MapPin} label="Localisation" wide>
              <Select label="Localisation" value={f.radius_km ? `r:${f.radius_km}` : f.stores.length === 1 ? `s:${f.stores[0]}` : f.stores.length ? 'multi' : ''}
                      onChange={(v) => v !== 'multi' && setF(v.startsWith('r:') ? { radius_km: Number(v.slice(2)), stores: [] } : v.startsWith('s:') ? { stores: [v.slice(2)], radius_km: null } : { stores: [], radius_km: null })}
                      options={[['', 'Toutes les zones'], ...(f.stores.length > 1 ? [['multi', `${f.stores.length} établissements`]] : []),
                        ...(page.has_position ? RADII.map((k) => [`r:${k}`, `À moins de ${k} km de mon établissement`]) : []),
                        ...(page.stores.length > 1 ? page.stores.map((x) => [`s:${x.id}`, `Clients de : ${x.name}`]) : [])]} />
            </FilterTile>
            <FilterTile icon={Award} label="Type de client" wide>
              <Select label="Type de client" value={one(f.client_type || [])} onChange={pick('client_type')}
                      options={withMulti(f.client_type || [], [['', 'Tous (Nouveaux, Réguliers, Fidèles)'], ...CLIENT_TYPES])} />
            </FilterTile>
          </div>
          {s.scenario === 'google_review' && (
            <p className="mt-3 flex items-start gap-2 rounded-xl bg-[#F1F6FF] px-3 py-2.5 text-[12.5px] text-[#334155]"><Info size={16} className="mt-0.5 shrink-0 text-[#1463FF]" />
              <span><b className="text-[#1463FF]">Conseil :</b> pour un meilleur taux de réponse, ciblez les clients venus il y a moins de 7 jours et ayant effectué au moins un achat.</span></p>
          )}
        </div>
      )}
    </Card>
  );

  const Step5 = (
    <Card n={5} title="Planification" sub="Définissez quand et comment envoyer cette automatisation.">
      <div className="rounded-2xl border border-[#E6EEFB] p-4">
        <p className="flex items-center gap-3 text-[13.5px] font-bold text-[#0B1C3F]"><span className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><CalendarDays size={20} /></span>
          <span>Période d'envoi<span className="block text-[12px] font-normal text-[#64748B]">Choisissez les jours{timed ? " et l'heure" : ' et les horaires'} d'envoi.</span></span></p>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          {[['all', 'Tous les jours', 'La notification peut être envoyée tous les jours.', CalendarDays],
            ['specific', 'Jours spécifiques', 'Choisissez les jours de la semaine.', CalendarDays],
            ['weekdays', 'Jours ouvrés', 'Du lundi au vendredi uniquement.', Briefcase]].map(([k, l, h, I]) => (
            <button key={k} type="button" onClick={() => setIn('schedule', { days: k })}
                    className={`flex items-start gap-2.5 rounded-xl border p-3 text-left ${sc.days === k ? 'border-[#2F6BFF] bg-[#F5F8FF]' : 'border-[#E2E8F0] hover:border-[#BFD3FF]'}`}>
              <I size={18} className="mt-0.5 shrink-0 text-[#1463FF]" />
              <span className="min-w-0 flex-1"><span className="block text-[13px] font-semibold text-[#0B1C3F]">{l}</span><span className="text-[11.5px] text-[#64748B]">{h}</span></span>
              <Radio on={sc.days === k} />
            </button>
          ))}
        </div>
        {sc.days === 'specific' && (
          <div className="mt-3 flex flex-wrap gap-2">
            {DAY_NAMES.map((d, i) => {
              const on = sc.weekdays.includes(i);
              return (
                <button key={d} type="button" onClick={() => setIn('schedule', { weekdays: on ? sc.weekdays.filter((x) => x !== i) : [...sc.weekdays, i].sort() })}
                        className={`rounded-xl border px-3.5 py-2 text-[12.5px] font-semibold ${on ? 'border-[#2F6BFF] bg-[#1463FF] text-white' : 'border-[#E2E8F0] text-[#334155]'}`}>{d}</button>
              );
            })}
          </div>
        )}
        {timed ? (
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="block"><Label>Heure d'envoi</Label>
              <Select label="Heure d'envoi" value={sc.hour} disabled={sc.smart && Boolean(page.best_slot)} onChange={(v) => setIn('schedule', { hour: v })} options={HOURS.map((h) => [h, h])} /></label>
            <label className="block"><Label>Fuseau horaire</Label>
              <span className={`${field} flex items-center gap-2 bg-[#F8FAFC]`}><Globe size={15} className="text-[#64748B]" /> Europe/Paris ({parisOffset()})</span></label>
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            <div className="flex items-center justify-between gap-3 rounded-xl border border-[#E2E8F0] p-3">
              <span><span className="block text-[13px] font-semibold text-[#0B1C3F]">Envoi immédiat, dans une plage horaire</span>
                <span className="text-[12px] text-[#64748B]">Un événement en dehors de la plage (la nuit…) attend son ouverture.</span></span>
              <Toggle label="Limiter à une plage horaire" on={sc.window} onChange={(v) => setIn('schedule', { window: v })} />
            </div>
            {sc.window && (
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block"><Label>De</Label><Select label="Début de la plage" value={sc.window_from} onChange={(v) => setIn('schedule', { window_from: v })} options={HOURS.map((h) => [h, h])} /></label>
                <label className="block"><Label>À</Label><Select label="Fin de la plage" value={sc.window_to} onChange={(v) => setIn('schedule', { window_to: v })} options={[...HOURS, '23:59'].map((h) => [h, h])} /></label>
              </div>
            )}
          </div>
        )}
      </div>
      {s.scenario === 'tier_up' ? (
        <div className="mt-3 rounded-2xl border border-[#E6EEFB] p-4">
          <p className="flex items-center gap-3 text-[13.5px] font-bold text-[#0B1C3F]"><span className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><RefreshCw size={18} /></span>
            <span>Fréquence<span className="block text-[12px] font-normal text-[#64748B]">Choisissez la fréquence d'envoi de cette notification (la même que la Répétition du déclencheur).</span></span></p>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            {[['each', 'À chaque palier atteint', 'Recommandé pour féliciter vos clients.'], ['first', 'Uniquement la première fois', 'Une seule notification par client.'],
              ['custom', 'Fréquence personnalisée', 'Définissez des délais entre chaque envoi.']].map(([k, l, h]) => (
              <button key={k} type="button" onClick={() => setIn('trigger', { repeat: k })}
                      className={`flex items-start gap-2.5 rounded-xl border p-3 text-left ${(tr.repeat || 'each') === k ? 'border-[#2F6BFF] bg-[#F5F8FF]' : 'border-[#E2E8F0] hover:border-[#BFD3FF]'}`}>
                <span className="min-w-0 flex-1"><span className="block text-[13px] font-semibold text-[#0B1C3F]">{l}</span><span className="text-[11.5px] text-[#64748B]">{h}</span></span>
                <Radio on={(tr.repeat || 'each') === k} />
              </button>
            ))}
          </div>
          {tr.repeat === 'custom' && (
            <span className="mt-3 flex items-center gap-2 text-[12.5px] text-[#475569]">Au moins <Num value={tr.min_days} min={1} max={365} label="Délai minimum entre deux envois (Planification)" onChange={(v) => setIn('trigger', { min_days: v })} /> jours entre deux envois</span>
          )}
        </div>
      ) : (
      <div className="mt-3 rounded-2xl border border-[#E6EEFB] p-4">
        <p className="flex items-center gap-3 text-[13.5px] font-bold text-[#0B1C3F]"><span className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><RefreshCw size={20} /></span>
          <span>Fréquence<span className="block text-[12px] font-normal text-[#64748B]">{{
            birthday: 'Une fois par an, pour chaque client (répétition annuelle).',
            tier_up: 'À chaque nouveau palier atteint.',
            welcome: 'Une seule fois par client, à son inscription.',
            near_reward: 'Une fois par carte de fidélité.',
            referral: 'À chaque récompense de parrainage gagnée.',
            geo: `Au plus une fois tous les ${tr.cooldown_days || 7} jours par client.`,
            google_review: tr.frequency === 'every_scan' ? 'Après chaque visite.' : tr.frequency === 'once' ? 'Une seule fois par client.' : `Au plus une fois tous les ${tr.every_days || 30} jours.`,
            inactive: tr.repeat === 'every' ? `Tous les ${tr.every_days || 30} jours tant que le client ne revient pas.` : 'Une fois par absence.',
            custom: { visits: tr.visits_repeat === 'every' ? `Toutes les ${tr.visits || 1} visites.` : 'Une seule fois par client, à cette visite.', after_signup: 'Une seule fois par client.',
              after_visit: Number(tr.cooldown_days) ? `Au plus une fois tous les ${tr.cooldown_days} jours par client.` : 'À chaque visite.',
              date: { once: 'Une seule fois, à cette date.', weekly: 'Chaque semaine.', monthly: 'Chaque mois.', yearly: 'Chaque année.' }[tr.date_mode || 'once'] }[tr.type] || '',
          }[s.scenario]}</span></span></p>
      </div>
      )}
      {timed && (
        <div className="mt-3 rounded-2xl border border-[#E6EEFB] p-4">
          <div className="flex items-start gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-[#F1EAFF] text-[#7C3AED]"><Sparkles size={20} /></span>
            <span className="min-w-0 flex-1"><span className="block text-[13.5px] font-bold text-[#0B1C3F]">Plage d'envoi intelligente <span className="font-normal text-[#64748B]">(recommandé)</span></span>
              <span className="text-[12px] text-[#64748B]">FidClic envoie le message au moment de la journée où vos clients viennent le plus.</span></span>
            <Toggle label="Plage d'envoi intelligente" disabled={!page.best_slot} on={sc.smart && Boolean(page.best_slot)} onChange={(v) => setIn('schedule', { smart: v })} />
          </div>
          <p className="mt-3 flex items-start gap-2 rounded-xl bg-[#F1F6FF] px-3 py-2 text-[12px] text-[#334155]"><BarChart3 size={15} className="mt-0.5 shrink-0 text-[#1463FF]" />
            {page.best_slot ? <span><b className="text-[#1463FF]">Meilleur moment estimé :</b> entre {page.best_slot.from.replace(':00', 'h')} et {page.best_slot.to.replace(':00', 'h')}<span className="block text-[11.5px] text-[#64748B]">Basé sur les heures de visite de vos clients.</span></span>
              : "Pas encore assez de visites pour trouver votre meilleur créneau : l'heure choisie s'applique."}</p>
        </div>
      )}
      <div className="mt-3 rounded-2xl border border-[#E6EEFB] p-4">
        <p className="flex items-center gap-3 text-[13.5px] font-bold text-[#0B1C3F]"><span className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><CalendarDays size={18} /></span>
          <span>Période de validité <span className="font-normal text-[#64748B]">(optionnel)</span><span className="block text-[12px] font-normal text-[#64748B]">L'automatisation part entre ces dates ; après la date de fin, elle passe « Terminée ».</span></span></p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <label className="block"><Label>Date de début</Label><input type="date" aria-label="Date de début" className={field} value={sc.valid_from || ''} onChange={(e) => setIn('schedule', { valid_from: e.target.value })} /></label>
          <label className="block"><Label>Date de fin (optionnel)</Label><input type="date" aria-label="Date de fin" className={field} value={sc.valid_to || ''} min={sc.valid_from || undefined} onChange={(e) => setIn('schedule', { valid_to: e.target.value })} /></label>
        </div>
      </div>
      {!page.tick && (
        <p className="mt-3 flex items-start gap-2 text-[11.5px] text-[#94A3B8]"><Info size={13} className="mt-0.5 shrink-0" />
          L'envoi à l'heure exacte arrive avec l'envoi programmé toutes les 15 minutes ; en attendant, les messages du jour partent avec l'envoi quotidien du matin.</p>
      )}
    </Card>
  );

  const Row = ({ icon: I, title, sub, children, n }) => (
    <div className="flex flex-wrap items-start gap-3 rounded-2xl border border-[#E6EEFB] p-4 sm:flex-nowrap">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><I size={18} /></span>
      <span className="min-w-0 flex-1 sm:w-40 sm:flex-none"><span className="block text-[13.5px] font-bold text-[#0B1C3F]">{title}</span><span className="text-[12px] text-[#64748B]">{sub}</span></span>
      <span className="order-last w-full min-w-0 break-words text-[12.5px] text-[#334155] sm:order-none sm:w-auto sm:flex-1">{children}</span>
      {can && <button type="button" onClick={() => go(n)} aria-label={`Modifier : ${title}`} className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-[#BFD3FF] px-3 py-2 text-[12.5px] font-semibold text-[#1463FF]"><Pencil size={14} /> <span className="hidden sm:inline">Modifier</span></button>}
    </div>
  );
  const Step6 = (
    <Card n={6} title="Résumé" sub="Vérifiez les paramètres de votre automatisation avant de l'enregistrer.">
      <div className="space-y-3">
        <Row n={1} icon={ScIcon} title="Scénario" sub={m.label}><b className="text-[#0B1C3F]">{s.name || m.label}</b>
          <span className="block text-[#64748B]">{s.scenario !== 'google_review' && s.description ? s.description : m.sub}</span>
          {s.scenario === 'google_review' && <span className="block break-all text-[#64748B]">{googleKeys.map((k) => links[k]).filter(Boolean).join(' · ')}</span>}</Row>
        {s.scenario === 'geo' ? (
          <Row n={2} icon={Navigation} title="Zone de détection" sub={`Rayon : ${tr.radius_m || 200} m`}>
            <span className="flex flex-wrap items-start gap-3">
              <span className="w-full max-w-[200px] shrink-0"><GeoZoneMap anchors={zoneSpots} radius={Number(tr.radius_m) || 200} height={110} interactive={false} showPeople={false} /></span>
              <span className="min-w-0 flex-1"><b>Rayon de détection :</b> {tr.radius_m || 200} m
                <span className="block"><b>{zoneSpots.length > 1 ? 'Établissements' : 'Adresse'} :</b> {zoneSpots.map((a) => (zoneSpots.length > 1 ? a.name : a.address || a.name)).join(' · ') || '—'}</span>
                <span className="block"><b>Zone active :</b> {allDay ? 'Toute la journée (24h/24, 7j/7)' : `${geoDays()} · ${slotsText()}`}</span>
                {weatherNames.length > 0 && <span className="block"><b>Météo :</b> {weatherNames.join(' ou ')}</span>}</span>
            </span>
          </Row>
        ) : <Row n={2} icon={CalendarDays} title="Déclencheur" sub={s.scenario === 'google_review' ? ({ after_visit: 'Après la visite', loyal: 'Client fidèle', date: 'Date spécifique' }[tr.type || 'after_visit']) : m.trigger_label}>{triggerText()}{delayText()}</Row>}
        <Row n={3} icon={MessageSquare} title="Message" sub="Notification Wallet">
          <span className="flex items-start gap-3"><span className="min-w-0 flex-1">
            {tiered ? tr.tiers.map((t, i) => (
              <span key={i} className="mb-1 block"><b>{palierLabel(tr.condition, t.value)} :</b> {t.title} — {t.body}{t.reward ? ` (récompense : ${t.reward})` : ''}</span>
            )) : <><b>Titre :</b> {msg.title}<span className="block"><b>Message :</b> {msg.body}</span></>}
            {btn.enabled && <span className="block"><b>Bouton :</b> {btn.label}</span>}</span>
            {msg.image_url && <img src={msg.image_url} alt="" className="h-14 w-14 shrink-0 rounded-xl object-cover" />}</span></Row>
        <Row n={4} icon={Users} title="Ciblage" sub={tg.mode === 'all' ? 'Tous mes clients' : tg.mode === 'wallet' ? 'Carte Wallet' : tg.mode === 'filtered' ? 'Passants' : 'Segment'}>
          {s.scenario === 'google_review' ? (
            <>
              <b className="text-[#0B1C3F]">{tg.mode === 'wallet' ? 'Clients avec une carte Wallet' : tg.mode === 'segment' ? `Segment : ${(page.segments.find((x) => x.key === tg.segment) || {}).label || '—'}` : 'Tous mes clients'}</b>
              <span className="block text-[#64748B]">Envoyer la demande aux clients correspondant au déclencheur{preview ? ` · ${preview.count.toLocaleString('fr-FR')} aujourd'hui` : ''}.</span>
              <span className="mt-1 block font-semibold text-[#0B1C3F]">Filtres appliqués :</span>
              <span className="mt-1 flex flex-wrap gap-1.5">{(filterChips().length ? filterChips() : ['Aucun filtre']).map((c) => (
                <span key={c} className="rounded-lg bg-[#F1F5F9] px-2 py-0.5 text-[11.5px] text-[#334155]">{c}</span>))}</span>
            </>
          ) : <>{targetText()}<span className="block text-[#64748B]">{preview ? `${preview.count.toLocaleString('fr-FR')} client(s) ciblé(s) aujourd'hui${s.scenario === 'geo' && preview.reachable ? ` · ${preview.reachable.total.toLocaleString('fr-FR')} joignable(s)` : ''}` : ''}</span></>}</Row>
        {s.scenario === 'geo' ? (
          <Row n={5} icon={Clock} title="Planification" sub={periodText()}>
            <span className="block"><b>Période :</b> {periodText()}</span>
            <span className="block"><b>Jours :</b> {geoDays()}</span>
            <span className="block"><b>Horaires :</b> {slotsText()}</span>
            {rushOn.length > 0 && <span className="block"><b>Heures de forte affluence :</b> {rushOn.map((r) => `${hLabel(r[2])} – ${hLabel(r[3])}`).join(' / ')}</span>}
            <span className="block"><b>Jours fériés :</b> {sc.holidays !== false ? 'Activé' : 'Désactivé'}</span>
            <span className="block"><b>Fréquence :</b> au plus une fois tous les {tr.cooldown_days || 7} jours par client</span>
          </Row>
        ) : s.scenario === 'google_review' ? (
          <Row n={5} icon={Clock} title="Planification" sub={freqText()}>
            <span className="block"><b>Jours d'envoi :</b> {sc.days === 'all' ? 'Tous les jours' : sc.weekdays.map((d) => DAY_FULL[d]).join(', ')}</span>
            {tr.type === 'date' && <span className="block"><b>Heure d'envoi :</b> {sc.hour} ({parisOffset()} Paris)</span>}
            <span className="block"><b>Fréquence :</b> {freqText()}</span>
            <span className="block"><b>Plage d'envoi :</b> {sc.window ? 'entre 8h et 20h (FidClic AI)' : 'à toute heure'}</span>
            <span className="block"><b>Période :</b> {sc.valid_from || sc.valid_to ? validText().replace(' · ', '').replace(/^./, (c) => c.toUpperCase()) : 'Sans limite'}</span>
          </Row>
        ) : <Row n={5} icon={Clock} title="Planification" sub={timed ? 'À heure fixe' : 'Dès l\'événement'}>{planText()}</Row>}
        <div className="flex items-center gap-3 rounded-2xl bg-[#F1FBF5] p-4">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#DCFCE7] text-[#059669]"><Power size={18} /></span>
          <span className="flex-1"><span className="block text-[13.5px] font-bold text-[#0B1C3F]">Activer l'automatisation</span>
            <span className="text-[12px] text-[#475569]">Les notifications seront envoyées automatiquement selon les paramètres définis.</span></span>
          <Toggle label="Activer l'automatisation" on={s.status !== 'paused'} onChange={(v) => set({ status: v ? 'active' : 'paused' })} disabled={!can} />
        </div>
      </div>
    </Card>
  );

  const words = tiered ? tr.tiers.map((t) => `${t.title} ${t.body}`).join(' ') : `${msg.title} ${msg.body}`;
  const tips = [
    [/\{pr[ée]nom\}/.test(words), /\{pr[ée]nom\}/.test(words) ? 'Le message est clair et personnalisé' : 'Ajoutez {prénom} : un message personnalisé est plus ouvert'],
    [timed ? Boolean(sc.smart && page.best_slot) || Boolean(sc.hour) : true, timed && sc.smart && page.best_slot ? 'Le meilleur moment d\'envoi est sélectionné' : 'Le moment d\'envoi est défini'],
    [Boolean(preview?.count), preview?.count ? 'Le ciblage est adapté' : "Aucun client ne correspond au ciblage aujourd'hui"],
    [btn.enabled, btn.enabled ? 'Le bouton d\'action invite à agir' : 'Vous pouvez ajouter un bouton (offre, carte…) pour booster l\'impact'],
  ];

  const Recap = (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <p className="mb-2 text-[14.5px] font-bold text-[#0B1C3F]">Récapitulatif de l'automatisation</p>
      {[[ScIcon, 'Scénario', s.name || m.label, tone[1]], [CalendarDays, 'Déclencheur', triggerText() + delayText()], [Users, 'Ciblage', targetText()],
        [MessageSquare, 'Message', cur.title || '—'], [Clock, step >= 5 ? 'Planification' : 'Envoi', step >= 5 ? planText() : (timed ? `À ${sc.hour}` : 'Immédiat')]].map(([I, l, v, c]) => (
        <div key={l} className="flex items-start gap-3 border-t border-[#EEF2F7] py-2.5 first:border-t-0">
          <I size={18} className="mt-0.5 shrink-0" style={{ color: c || '#475569' }} />
          <span className="w-28 shrink-0 text-[12.5px] text-[#475569]">{l}</span>
          <span className="min-w-0 flex-1 break-words text-[12.5px] font-medium text-[#0B1C3F]">{v}</span>
        </div>
      ))}
    </section>
  );

  // ---- « Conseil FidClic AI »: tips from the settings and the shop's real data,
  // « Optimisé » only when every tip of the step holds (user, 2026-10-11) ----------
  const tipsFor = (n) => {
    const named = [s.name.trim() && s.name.trim() !== m.label, s.name.trim() && s.name.trim() !== m.label
      ? 'Un nom clair : vous retrouverez facilement cette automatisation.' : 'Donnez-lui un nom clair et précis pour la retrouver facilement.'];
    if (s.scenario === 'google_review') {
      const out = [];
      const hrs = tr.delay_unit === 'days' ? Number(tr.delay_value) * 24 : Number(tr.delay_value);
      if ([1, 6].includes(n)) {
        out.push(named);
        out.push(googleKeys.every((k) => String(links[k] || '').trim()) ? [true, 'Votre lien Google est prêt : le client arrive directement sur votre fiche.']
          : [false, 'Ajoutez le lien de votre fiche Google : sans lui, aucune demande ne part.']);
      }
      if ([2, 6].includes(n)) {
        if ((tr.type || 'after_visit') === 'after_visit') {
          out.push(hrs >= 1 && hrs <= 4 ? [true, `Demande envoyée ${tr.delay_value} h après la visite : l'expérience est encore fraîche.`]
            : [false, "Les demandes d'avis répondent le mieux entre 1 et 4 heures après la visite."]);
        } else if (tr.type === 'loyal') out.push([true, 'Vos clients fidèles sont les plus enclins à laisser un avis positif.']);
        else out.push([true, 'Une date après un événement : vos clients en gardent un souvenir frais.']);
      }
      if ([3, 6].includes(n)) {
        out.push(/\{pr[ée]nom\}|\{nom\}/.test(words) ? [true, 'Message personnalisé avec le nom du client.'] : [false, 'Personnalisez votre message avec le prénom du client.']);
        out.push(btn.enabled && btn.label.trim() ? [true, 'Un bouton clair (« Laisser un avis ») augmente le taux d\'avis.'] : [false, 'Ajoutez un bouton « Laisser un avis ».']);
      }
      if ([4, 6].includes(n)) out.push(tips[2]);
      if ([5, 6].includes(n)) {
        out.push(sc.window || tr.frequency === 'smart' ? [true, 'Vos demandes partent en journée (8h – 20h), quand les clients répondent le plus.']
          : [false, "Activez la plage d'envoi intelligente : en journée (8h – 20h), les clients répondent davantage."]);
        out.push(tr.frequency !== 'days' || Number(tr.every_days) >= 30 ? [true, 'Vos clients ne sont pas sollicités trop souvent.']
          : [false, 'Ne redemandez pas un avis trop souvent : 30 jours ou plus entre deux demandes.']);
      }
      return out;
    }
    if (s.scenario === 'near_reward') {
      const sv = Number(tr.threshold) || 0;
      const [lo, hi] = near.unit === 'tampons' ? [1, 2] : near.unit === '€' ? [5, 20] : [5, 15];
      const u = near.unit === 'tampons' ? 'tampons' : near.unit === '€' ? '€' : 'points';
      const out = [];
      if ([2, 6].includes(n)) {
        out.push(sv >= lo && sv <= hi ? [true, `Un seuil de ${lo} à ${hi} ${u} fonctionne très bien pour inciter les clients à revenir.`]
          : [false, `Un seuil de ${lo} à ${hi} ${u} fonctionne le mieux : assez proche pour motiver, sans prévenir trop tôt.`]);
        out.push([true, 'Utilisez un message court et motivant.']);
        out.push([Boolean(msg.image_url || /\{récompense\}|offert|cadeau|🎁/.test(words)), msg.image_url || /\{récompense\}|offert|cadeau|🎁/.test(words)
          ? 'La récompense est mise en avant : de quoi donner envie de revenir.' : 'Ajoutez une offre ou un visuel attractif pour augmenter le taux de retour.']);
      }
      if ([3, 6].includes(n)) {
        out.push(/\{pr[ée]nom\}/.test(words) ? [true, 'Message personnalisé avec le prénom du client.'] : [false, 'Ajoutez {prénom} : un message personnalisé est plus ouvert.']);
        out.push(/\{(points|tampons)_restants\}|\{récompense\}/.test(words) ? [true, 'Le client voit ce qu\'il lui manque et ce qu\'il va gagner.']
          : [false, `Indiquez ce qui reste ({${near.unit === 'tampons' ? 'tampons' : 'points'}_restants}) et la récompense ({récompense}).`]);
      }
      if ([4, 6].includes(n)) {
        out.push(preview?.near ? (preview.near.count ? [true, 'Cette notification fonctionne particulièrement bien pour les clients actifs qui viennent régulièrement.']
          : [false, "Aucun client n'est dans le seuil aujourd'hui : il se remplira au fil des passages."]) : tips[2]);
        out.push(Number(f.visits_min) >= 2 ? [true, `Filtre « au moins ${f.visits_min} visites » : vous ciblez les clients les plus engagés.`]
          : [false, 'Vous pouvez ajouter un filtre sur le nombre de visites (ex : au moins 2 visites) pour cibler les clients les plus engagés.']);
      }
      if ([5, 6].includes(n)) {
        const best = page.best_slot;
        out.push(!best || (sc.window_from <= best.from && best.from < sc.window_to) ? [true, `Le créneau ${sc.window_from} - ${sc.window_to} est idéal pour ce type de notification${best ? ` : vos clients viennent surtout vers ${best.from}` : ''}.`]
          : [false, `Vos clients viennent surtout vers ${best.from} (d'après vos visites) : incluez ce moment dans la plage horaire.`]);
        out.push([true, 'Vous pouvez tester différents créneaux horaires pour identifier ceux qui génèrent le plus d\'engagement.']);
      }
      return out;
    }
    if (s.scenario === 'welcome') {
      if (n !== 3) return [];
      return [
        /\{pr[ée]nom\}/.test(words) || (msg.title + msg.body).length <= 160 ? [true, 'Ce message de bienvenue est clair et engageant.'] : [false, 'Faites court et chaleureux : un titre et une phrase suffisent.'],
        [true, "Il est envoyé immédiatement après l'ajout de la carte, ce qui augmente l'activation et la première visite."],
        ...(/\{pr[ée]nom\}/.test(words) ? [] : [[false, 'Ajoutez {prénom} : un accueil personnalisé est plus chaleureux.']]),
      ];
    }
    if (s.scenario === 'inactive') {
      const d = Number(tr.days) || 30;
      const out = [];
      if ([1, 6].includes(n)) out.push(named);
      if ([2, 6].includes(n)) {
        out.push(d >= 60 && d <= 90 ? [true, `Le délai de ${d} jours est idéal pour relancer des clients inactifs.${d === 90 ? ' Vous pouvez également tester 60 jours pour toucher plus de clients.' : ''}`]
          : d < 60 ? [false, `À ${d} jours, beaucoup de clients ne sont pas encore partis : 60 à 90 jours touche les vrais inactifs.`]
            : [false, `Au-delà de 90 jours, les clients reviennent moins souvent : testez 60 ou 90 jours.`]);
      }
      if ([3, 6].includes(n)) {
        out.push(tips[0]);
        out.push(/\{offre\}|%|offert|gratuit|réduction|remise|cadeau/i.test(words) ? [true, 'Un avantage clair donne envie de revenir.']
          : [false, 'Ajoutez un avantage (une remise, un produit offert, {offre}) : les clients inactifs reviennent pour une raison.']);
      }
      if ([4, 6].includes(n)) {
        out.push(preview?.inactive ? (preview.inactive.count ? [true, `${preview.inactive.count.toLocaleString('fr-FR')} client${preview.inactive.count > 1 ? 's' : ''} inactif${preview.inactive.count > 1 ? 's' : ''} correspondent aujourd'hui.`]
          : [false, "Aucun client inactif ne correspond aujourd'hui : élargissez les filtres ou le délai."]) : tips[2]);
        out.push(Number(f.visits_min) >= 2 ? [true, `Cibler des clients inactifs depuis plus de ${d} jours ayant au moins ${f.visits_min} visites passées : ils connaissent déjà votre établissement.`]
          : [false, "Ciblez les clients ayant au moins 2 visites passées : ce sont eux qui reviennent le plus après une relance."]);
      }
      if ([5, 6].includes(n)) {
        const best = page.best_slot;
        out.push(!best || (sc.window_from <= best.from && best.from < sc.window_to) ? [true, best ? `Vos clients viennent surtout vers ${best.from} : la plage horaire couvre ce moment.` : 'La plage horaire est définie.']
          : [false, `Vos clients viennent surtout vers ${best.from} (d'après vos visites) : incluez ce moment dans la plage horaire.`]);
        out.push(sc.daily_limit !== null && sc.daily_limit !== undefined && sc.daily_limit !== '' ? [true, "Le nombre d'envois par jour est limité : vos clients ne sont pas saturés."]
          : [false, "Limitez le nombre d'envois par jour pour lisser les envois et éviter la saturation."]);
      }
      return out;
    }
    if (s.scenario !== 'geo') return ({ 1: [named], 3: [tips[0], tips[3]], 4: [tips[2]], 5: [tips[1]], 6: tips })[n] || [];
    const out = [];
    const busyTxt = geo.busy ? `${geo.busy[0]}h – ${geo.busy[1]}h` : '';
    const covers = !sc.window || (sc.slots || []).some((x) => overlaps(['', '', x.from, x.to], geo.busy));
    if ([2, 6].includes(n)) {
      out.push(Number(tr.radius_m) <= 200 ? [true, `Un rayon de ${tr.radius_m} m touche les passants sans être intrusif.`]
        : [false, "Sur l'écran verrouillé, le téléphone n'affiche la carte qu'à une centaine de mètres : un grand rayon sert surtout quand la carte est ouverte."]);
    }
    if ([2, 5, 6].includes(n) && geo.busy) {
      out.push(covers ? [true, `Vos heures de pointe (${busyTxt}, d'après vos visites) sont couvertes.`]
        : [false, `Activez la zone pendant vos heures de pointe : ${busyTxt}, d'après vos visites.`]);
    }
    if ([3, 6].includes(n)) {
      const short = (msg.title || '').length <= 40 && (msg.body || '').length <= 120;
      out.push(short ? [true, 'Message court et percutant : idéal pour un passant.']
        : [false, 'Faites court : un passant lit en deux secondes (titre de 40 caractères, message de 120 au plus).']);
      out.push(/\{offre\}|%|offert|gratuit|réduction|remise/i.test(words) ? [true, "Un avantage clair donne une raison d'entrer."]
        : [false, 'Mettez en avant un avantage immédiat : une remise, un produit offert, {offre}.']);
    }
    if ([4, 6].includes(n)) {
      out.push(preview?.reachable?.total ? [true, `${preview.reachable.total.toLocaleString('fr-FR')} client${preview.reachable.total > 1 ? 's peuvent' : ' peut'} recevoir ce message.`]
        : [false, 'Aucun client joignable avec ce ciblage : élargissez-le, ou invitez vos clients à ajouter leur carte Wallet.']);
    }
    if ([5, 6].includes(n)) {
      out.push(Number(tr.cooldown_days) >= 3 ? [true, `Au plus un message tous les ${tr.cooldown_days} jours : vos clients ne se sentent pas harcelés.`]
        : [false, 'Espacez les messages (3 jours ou plus) pour ne pas lasser vos clients.']);
    }
    return out;
  };
  const stepTips = tipsFor(step);
  const Conseil = stepTips.length > 0 && (
    <section className="rounded-2xl border border-[#E9DDFE] bg-[#FAF7FF] p-4">
      <p className="mb-2 flex items-center gap-2 text-[14px] font-bold text-[#0B1C3F]"><Sparkles size={17} className="text-[#7C3AED]" /> Conseil FidClic AI
        {stepTips.every(([ok]) => ok) && <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-[#DCFCE7] px-2 py-0.5 text-[11px] font-semibold text-[#047857]"><CheckCircle2 size={12} /> Optimisé</span>}</p>
      {stepTips.map(([ok, t]) => (
        <p key={t} className={`flex items-start gap-2 py-1 text-[12.5px] ${ok ? 'text-[#14532D]' : 'text-[#7C2D12]'}`}>
          {ok ? <Check size={15} className="mt-0.5 shrink-0 text-[#16A34A]" /> : <Lightbulb size={15} className="mt-0.5 shrink-0 text-[#D97706]" />} {t}</p>
      ))}
    </section>
  );
  const Panel = ({ icon: I, title, lines, children }) => (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <p className="mb-1 flex items-center gap-2 text-[14px] font-bold text-[#0B1C3F]"><I size={17} className="text-[#1463FF]" /> {title}</p>
      {lines?.map(([l, v]) => (
        <div key={l} className="flex items-start gap-3 border-t border-[#EEF2F7] py-2 first:border-t-0">
          <span className="w-36 shrink-0 text-[12.5px] text-[#475569]">{l}</span>
          <span className="min-w-0 flex-1 break-words text-[12.5px] font-medium text-[#0B1C3F]">{v}</span>
        </div>
      ))}
      {children}
    </section>
  );
  const names = (vals, opts, all) => (vals.length ? vals.map((v) => (opts.find((x) => x[0] === v) || [])[1]).filter(Boolean).join(', ') : all);
  const Stat = ({ icon: I, label, value, hint }) => (
    <div className="flex items-center gap-3 border-t border-[#EEF2F7] py-2.5 first:border-t-0">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><I size={17} /></span>
      <span className="min-w-0 flex-1 text-[12.5px] text-[#475569]">{label}{hint && <span className="block text-[11px] text-[#94A3B8]">{hint}</span>}</span>
      <span className="text-[18px] font-extrabold tabular-nums text-[#0B1C3F]">{value}</span>
    </div>
  );
  // ---- Client inactif (mockups 2026-10-11): its own steps 2, 4, 5 and 6 ----------------
  const inactiveOn = s.scenario === 'inactive';
  const ins = preview?.inactive;
  const nf = (n) => (n === null || n === undefined ? '—' : Number(n).toLocaleString('fr-FR'));
  const inDays = Number(tr.days) || 30;
  const cutoffDate = (() => { const d = new Date(); d.setDate(d.getDate() - inDays); return d.toLocaleDateString('fr-FR'); })();
  const limitOn = sc.daily_limit !== null && sc.daily_limit !== undefined && sc.daily_limit !== '';
  const sendHour = sc.smart && page.best_slot ? page.best_slot.from : sc.hour;
  const dayList = sc.days === 'all' ? [0, 1, 2, 3, 4, 5, 6] : sc.days === 'weekdays' ? [0, 1, 2, 3, 4] : [...(sc.weekdays || [])].sort();
  const inDaysText = (() => {
    if (dayList.length === 7) return 'Tous les jours';
    if (!dayList.length) return '—';
    const run = dayList.every((d, i) => i === 0 || d === dayList[i - 1] + 1);
    return run && dayList.length > 2 ? `Du ${DAY_FULL[dayList[0]].toLowerCase()} au ${DAY_FULL[dayList[dayList.length - 1]].toLowerCase()}` : dayList.map((d) => DAY_FULL[d]).join(', ');
  })();
  // « Prochain envoi estimé »: the first allowed day from the start date, at the hour
  const nextSend = (() => {
    const now = new Date();
    const today = now.toISOString().slice(0, 10);
    const start = sc.valid_from && sc.valid_from > today ? sc.valid_from : today;
    const [hh, mm] = String(sendHour || '10:00').split(':').map(Number);
    for (let i = 0; i < 21; i += 1) {
      const d = new Date(`${start}T12:00:00`);
      d.setDate(d.getDate() + i);
      const iso = d.toISOString().slice(0, 10);
      if (sc.valid_to && iso > sc.valid_to) return null;
      if (!dayList.includes((d.getDay() + 6) % 7)) continue;
      if (iso === today && (now.getHours() > hh || (now.getHours() === hh && now.getMinutes() >= mm))) continue;
      const txt = d.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
      return `${txt.charAt(0).toUpperCase()}${txt.slice(1)} à ${sendHour}`;
    }
    return null;
  })();
  const setInDays = (weekdays) => setIn('schedule', { weekdays: [...weekdays].sort(), days: weekdays.length === 7 ? 'all' : 'specific' });
  const Sec = ({ title, sub, right, children, className = '' }) => (
    <div className={`mt-5 first:mt-0 ${className}`}>
      <div className="mb-2.5 flex flex-wrap items-end justify-between gap-2">
        <span><span className="block text-[14px] font-bold text-[#0B1C3F]">{title}</span>{sub && <span className="text-[12.5px] text-[#475569]">{sub}</span>}</span>{right}
      </div>
      {children}
    </div>
  );
  const Ticked = ({ on }) => (on ? <CheckCircle2 size={19} className="shrink-0 fill-[#1463FF] text-white" /> : <span className="inline-block h-[18px] w-[18px] shrink-0 rounded-full border-2 border-[#CBD5E1] bg-white" />);
  const hourOptions = [...(page.best_slot ? [['__smart', `Automatique — ${page.best_slot.from} (meilleur moment)`]] : []), ...HOURS.map((h) => [h, h])];

  const Step2Inactive = (
    <Card n={2} title="Déclencheur" sub="Définissez quand l'automatisation se déclenche.">
      <div className="rounded-2xl border border-[#E6EEFB] p-4">
        <p className="mb-3 flex items-start gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><UserX size={20} /></span>
          <span><span className="block text-[14px] font-bold text-[#0B1C3F]">Condition d'inactivité</span>
            <span className="text-[12.5px] text-[#475569]">Un client est considéré comme inactif s'il n'a pas visité votre établissement depuis :</span></span></p>
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-5" role="radiogroup" aria-label="Condition d'inactivité">
          {INACTIVE_DAYS.map((d) => {
            const on = inDays === d;
            return (
              <button key={d} type="button" role="radio" aria-checked={on} onClick={() => setIn('trigger', { days: d })}
                      className={`relative flex items-center gap-2.5 rounded-2xl border px-3.5 py-4 text-left transition ${on ? 'border-[#2F6BFF] bg-[#EEF4FF] shadow-[0_0_0_1px_#2F6BFF]' : 'border-[#E2E8F0] bg-white hover:border-[#BFD3FF]'}`}>
                <CalendarDays size={22} className={on ? 'text-[#1463FF]' : 'text-[#64748B]'} />
                <span className="text-[14px] font-semibold text-[#0B1C3F]">{d} jours</span>
                <span className="absolute right-2 top-2"><Ticked on={on} /></span>
              </button>
            );
          })}
        </div>
        <p className="mt-3 flex flex-wrap items-center gap-2 text-[12.5px] text-[#475569]">
          {INACTIVE_DAYS.includes(inDays) ? 'Autre durée :' : <b className="text-[#1463FF]">Durée personnalisée :</b>}
          <Num value={tr.days} min={7} max={365} label="Jours sans visite" onChange={(v) => setIn('trigger', { days: v })} /> jours <span className="text-[#94A3B8]">(7 à 365)</span>
        </p>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="block"><Label>Date d'envoi</Label>
          <span className={`${field} flex items-center gap-2.5 !py-0`}><CalendarDays size={18} className="shrink-0 text-[#64748B]" />
            <input type="date" aria-label="Date d'envoi" className="min-w-0 flex-1 bg-transparent py-2.5 !text-[15px] outline-none" value={sc.valid_from || ''}
                   onChange={(e) => setIn('schedule', { valid_from: e.target.value })} /></span></label>
        <label className="block"><Label>Heure d'envoi</Label>
          <span className="flex items-center gap-2.5"><Clock size={18} className="shrink-0 text-[#64748B]" />
            <Select label="Heure d'envoi" value={sc.smart && page.best_slot ? '__smart' : sc.hour}
                    onChange={(v) => setIn('schedule', v === '__smart' ? { smart: true } : { smart: false, hour: v })} options={hourOptions} /></span></label>
      </div>
      <p className="mt-2 flex items-start gap-2 rounded-xl bg-[#F1F6FF] px-3 py-2.5 text-[12px] text-[#334155]"><Info size={15} className="mt-0.5 shrink-0 text-[#1463FF]" />
        <span>À partir du {sc.valid_from ? frDate(sc.valid_from) : "jour de l'activation"}, chaque jour d'envoi à {sendHour}, les clients qui remplissent la condition d'inactivité reçoivent la notification, dans les jours et horaires de la Planification.</span></p>
      <div className="mt-3 rounded-2xl border border-[#E6EEFB] p-4">
        <p className="mb-2 flex items-center gap-2 text-[13.5px] font-bold text-[#0B1C3F]"><Repeat size={16} className="text-[#1463FF]" /> Relance <span className="font-normal text-[#64748B]">— si le client ne revient pas</span></p>
        <div className="flex flex-wrap gap-x-6 gap-y-2 text-[13px] text-[#0B1C3F]">
          <button type="button" onClick={() => setIn('trigger', { repeat: 'once' })} className="flex items-center gap-2"><Radio on={tr.repeat !== 'every'} /> Une seule fois par absence</button>
          <span className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => setIn('trigger', { repeat: 'every' })} className="flex items-center gap-2"><Radio on={tr.repeat === 'every'} /> Relancer tous les</button>
            <Num value={tr.every_days} min={7} max={365} label="Relancer tous les" disabled={tr.repeat !== 'every'} onChange={(v) => setIn('trigger', { every_days: v })} /> jours
          </span>
        </div>
      </div>
    </Card>
  );

  const resetExtra = () => setF({ gender: [], age: [], age_min: '', age_max: '', past_freq: [], spent: [], origin: [], tiers: [], last_offer: [],
    stores: [], radius_km: null, client_type: [], last_visit: [], visits_max: '' });
  const ex = tg.exclusions || EMPTY_EXCLUSIONS;
  const setEx = (patch) => setIn('targeting', { exclusions: { ...ex, ...patch } });
  const daysOpts = [...(INACTIVE_DAYS.includes(inDays) ? [] : [[String(inDays), `Plus de ${inDays} jours`]]), ...INACTIVE_DAYS.map((d) => [String(d), `Plus de ${d} jours`])];
  const visitsOpts = VISITS_MIN.some(([k]) => k === String(f.visits_min ?? '')) ? VISITS_MIN : [...VISITS_MIN, [String(f.visits_min), `Au moins ${f.visits_min} visites`]];
  const XSelect = ({ label, keyName, options, all }) => (
    <label className="block min-w-0"><span className="mb-1 block text-[12.5px] font-semibold text-[#0B1C3F]">{label}</span>
      <Select label={label} value={one(f[keyName] || [])} onChange={pick(keyName)} options={withMulti(f[keyName] || [], [['', all], ...options])} /></label>
  );
  const Step4Inactive = (
    <Card n={4} title="Ciblage" sub="Affinez les critères des clients qui recevront cette notification.">
      <Sec title="1. Base de clients" sub="Choisissez sur quelle base de clients appliquer la segmentation.">
        <div className={`grid gap-3 ${tg.mode === 'wallet' ? 'sm:grid-cols-3' : 'sm:grid-cols-2'}`}>
          {[['filtered', 'Tous mes clients', "Appliquer les filtres sur l'ensemble de la base", Users], ['segment', 'Segment spécifique', 'Appliquer les filtres sur un segment existant', Filter],
            ...(tg.mode === 'wallet' ? [['wallet', 'Clients avec carte Wallet', 'Uniquement les clients ayant ajouté leur carte', Wallet]] : [])].map(([k, l, h, I]) => (
            <button key={k} type="button" onClick={() => setIn('targeting', { mode: k })}
                    className={`flex items-start gap-3 rounded-2xl border p-4 text-left transition ${tg.mode === k ? 'border-[#2F6BFF] bg-[#F5F8FF] shadow-[0_0_0_1px_#2F6BFF]' : 'border-[#E2E8F0] hover:border-[#BFD3FF]'}`}>
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><I size={20} /></span>
              <span className="min-w-0 flex-1"><span className="block text-[13.5px] font-bold text-[#0B1C3F]">{l}</span><span className="text-[12px] text-[#64748B]">{h}</span></span>
              <Ticked on={tg.mode === k} />
            </button>
          ))}
        </div>
        {tg.mode === 'segment' && (
          <div className="mt-3 max-h-[220px] space-y-1.5 overflow-y-auto">
            {page.segments.map((x) => (
              <label key={x.key} className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 ${tg.segment === x.key ? 'border-[#2F6BFF] bg-[#F1F6FF]' : 'border-[#E2E8F0]'}`}>
                <input type="radio" name="au-seg-inactive" checked={tg.segment === x.key} onChange={() => setIn('targeting', { segment: x.key })} className="accent-[#1463FF]" />
                <span className="flex-1"><span className="block text-[13px] font-semibold text-[#0B1C3F]">{x.label}</span><span className="text-[11.5px] text-[#64748B]">{x.hint}</span></span>
                <span className="text-[12px] font-semibold tabular-nums text-[#475569]">{(x.count ?? 0).toLocaleString('fr-FR')}</span>
              </label>
            ))}
          </div>
        )}
      </Sec>
      <Sec title="2. Filtres des clients inactifs" sub="Affinez les critères pour cibler uniquement les clients concernés.">
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block"><span className="mb-1 block text-[12.5px] font-semibold text-[#0B1C3F]">Inactivité depuis</span>
            <Select label="Inactivité depuis" value={String(inDays)} onChange={(v) => setIn('trigger', { days: Number(v) })} options={daysOpts} /></label>
          <label className="block"><span className="mb-1 block text-[12.5px] font-semibold text-[#0B1C3F]">Nombre de visites précédentes</span>
            <Select label="Nombre de visites précédentes" value={String(f.visits_min ?? '')} onChange={(v) => setF({ visits_min: v })} options={visitsOpts} /></label>
          <label className="block"><span className="mb-1 block text-[12.5px] font-semibold text-[#0B1C3F]">Dernière visite avant le</span>
            <span className={`${field} flex items-center gap-2 bg-[#F8FAFC]`} title="Calculée depuis « Inactivité depuis »"><Clock size={16} className="text-[#64748B]" /> <span className="flex-1">{cutoffDate}</span><CalendarDays size={16} className="text-[#64748B]" /></span></label>
        </div>
      </Sec>
      <Sec title="3. Filtres supplémentaires (optionnels)" sub="Ajoutez d'autres critères pour affiner votre audience."
           right={<button type="button" onClick={resetExtra} className="inline-flex items-center gap-1.5 rounded-xl border border-[#BFD3FF] px-3 py-1.5 text-[12px] font-semibold text-[#1463FF]"><RotateCcw size={13} /> Réinitialiser</button>}>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <XSelect label="Genre" keyName="gender" options={GENDERS} all="Tous" />
          <XSelect label="Tranche d'âge" keyName="age" options={AGES} all="Tous" />
          <XSelect label="Fréquence d'achat passée" keyName="past_freq" options={PAST_FREQS} all="Tous" />
          <XSelect label="Montant dépensé total" keyName="spent" options={SPENT} all="Tous" />
          <XSelect label="Origine du client" keyName="origin" options={ORIGINS} all="Tous les canaux" />
          <XSelect label="Programme de fidélité" keyName="tiers" options={TIERS} all="Tous les statuts" />
          <XSelect label="Dernière offre reçue" keyName="last_offer" options={LAST_OFFER} all="Toutes" />
          <label className="block min-w-0"><span className="mb-1 block text-[12.5px] font-semibold text-[#0B1C3F]">Localisation</span>
            <Select label="Localisation" value={f.radius_km ? `r:${f.radius_km}` : f.stores.length === 1 ? `s:${f.stores[0]}` : f.stores.length ? 'multi' : ''}
                    onChange={(v) => v !== 'multi' && setF(v.startsWith('r:') ? { radius_km: Number(v.slice(2)), stores: [] } : v.startsWith('s:') ? { stores: [v.slice(2)], radius_km: null } : { stores: [], radius_km: null })}
                    options={[['', 'Tous'], ...(f.stores.length > 1 ? [['multi', `${f.stores.length} établissements`]] : []),
                      ...(page.has_position ? RADII.map((k) => [`r:${k}`, `À moins de ${k} km`]) : []),
                      ...(page.stores.length > 1 ? page.stores.map((x) => [`s:${x.id}`, `Clients de : ${x.name}`]) : [])]} /></label>
        </div>
      </Sec>
      <Sec title="4. Exclusions (optionnelles)" sub="Choisissez les clients à exclure de cette automatisation.">
        <div className="grid gap-3 md:grid-cols-2">
          {[['recent_contact', 'Exclure les clients déjà contactés récemment', 'Ne pas envoyer si une notification a été reçue dans les 30 derniers jours'],
            ['active_offer', 'Exclure les clients ayant une offre active', 'Ne pas envoyer si une offre est déjà en cours']].map(([k, l, h]) => (
            <div key={k} className="flex items-start gap-3 rounded-2xl border border-[#E6EEFB] bg-[#FAFCFF] p-3.5">
              <Toggle label={l} on={Boolean(ex[k])} onChange={(v) => setEx({ [k]: v })} />
              <span className="min-w-0"><span className="block text-[12.5px] font-semibold text-[#0B1C3F]">{l}</span><span className="text-[11.5px] text-[#64748B]">{h}</span></span>
            </div>
          ))}
        </div>
      </Sec>
    </Card>
  );

  const Step5Inactive = (
    <Card n={5} title="Planification" sub="Définissez les règles d'envoi de votre automatisation.">
      <Sec title="1. Jours et horaires d'envoi" sub="Choisissez les jours et plages horaires pendant lesquels les notifications seront envoyées.">
        <div className="flex flex-wrap items-end gap-4">
          <div><span className="mb-1.5 block text-[12.5px] font-semibold text-[#0B1C3F]">Jours de la semaine</span>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Jours de la semaine">
              {DAY_NAMES.map((d, i) => {
                const on = dayList.includes(i);
                return (
                  <button key={d} type="button" aria-pressed={on} onClick={() => setInDays(on ? dayList.filter((x) => x !== i) : [...dayList, i])}
                          className={`min-w-[52px] rounded-xl border px-3 py-2.5 text-[13px] font-semibold transition ${on ? 'border-[#1463FF] bg-[#1463FF] text-white' : 'border-[#DCE5F3] bg-white text-[#334155] hover:border-[#BFD3FF]'}`}>{d}</button>
                );
              })}
            </div></div>
          <div><span className="mb-1.5 block text-[12.5px] font-semibold text-[#0B1C3F]">Plage horaire</span>
            <span className="flex items-center gap-2">
              <span className="w-28"><Select label="Début de la plage" value={sc.window_from} onChange={(v) => setIn('schedule', { window: true, window_from: v })} options={HOURS.map((h) => [h, h])} /></span>
              <span className="text-[#64748B]">–</span>
              <span className="w-28"><Select label="Fin de la plage" value={sc.window_to} onChange={(v) => setIn('schedule', { window: true, window_to: v })} options={[...HOURS, '23:59'].map((h) => [h, h])} /></span>
            </span></div>
        </div>
        <p className="mt-3 flex items-center gap-2 rounded-xl bg-[#F1F6FF] px-3 py-2.5 text-[12.5px] text-[#1E3A8A]"><Info size={16} className="shrink-0 text-[#1463FF]" /> Les notifications seront envoyées uniquement les jours et horaires sélectionnés.</p>
      </Sec>
      <Sec title="2. Limite d'envoi par jour (optionnel)" sub="Définissez un nombre maximum de notifications envoyées par jour pour éviter la saturation.">
        <div className="grid items-center gap-3 md:grid-cols-[auto_auto_1fr]">
          <span className="flex items-center gap-3"><Toggle label="Activer une limite d'envoi" on={limitOn} onChange={(v) => setIn('schedule', { daily_limit: v ? 200 : null })} />
            <span className="text-[13px] font-medium text-[#0B1C3F]">Activer une limite d'envoi</span></span>
          <label className="block"><span className="mb-1 block text-[12.5px] font-semibold text-[#0B1C3F]">Nombre maximum par jour</span>
            <Num value={limitOn ? sc.daily_limit : ''} digits={6} min={1} max={100000} label="Nombre maximum par jour" disabled={!limitOn}
                 onChange={(v) => setIn('schedule', { daily_limit: v })} /></label>
          <p className="flex items-start gap-2 rounded-xl bg-[#F1F6FF] px-3 py-2.5 text-[12px] text-[#1E3A8A]"><Info size={15} className="mt-0.5 shrink-0 text-[#1463FF]" />
            Cela permet de lisser l'envoi des notifications sur la journée : les clients restants reçoivent la leur les jours suivants.</p>
        </div>
      </Sec>
      <Sec title="3. Fuseau horaire" sub="Les envois seront effectués selon le fuseau horaire de votre établissement.">
        <span className={`${field} flex max-w-[420px] items-center gap-2.5 bg-[#F8FAFC]`}><Globe size={17} className="text-[#64748B]" /> Europe/Paris ({parisOffset()})</span>
      </Sec>
      <Sec title="Date de fin (optionnelle)" sub="Après cette date, l'automatisation passe « Terminée ».">
        <input type="date" aria-label="Date de fin" className={`${field} max-w-[260px]`} value={sc.valid_to || ''} min={sc.valid_from || undefined}
               onChange={(e) => setIn('schedule', { valid_to: e.target.value })} />
      </Sec>
      {!page.tick && (
        <p className="mt-3 flex items-start gap-2 text-[11.5px] text-[#94A3B8]"><Info size={13} className="mt-0.5 shrink-0" />
          L'envoi à l'heure exacte et l'étalement sur la plage arrivent avec l'envoi programmé toutes les 15 minutes ; en attendant, les messages du jour partent avec l'envoi quotidien du matin.</p>
      )}
    </Card>
  );

  const SumCard = ({ icon: I, title, n, badge, children }) => (
    <div className="rounded-2xl border border-[#E6EEFB] bg-white p-4">
      <div className="mb-2 flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><I size={20} /></span>
        <span className="min-w-0 flex-1 pt-2 text-[14px] font-bold text-[#0B1C3F]">{title}</span>
        {badge}
        {n && can && <button type="button" onClick={() => go(n)} aria-label={`Modifier : ${title}`} className="shrink-0 rounded-xl border border-[#BFD3FF] px-3 py-1.5 text-[12.5px] font-semibold text-[#1463FF]">Modifier</button>}
      </div>
      <div className="text-[12.5px] text-[#334155]">{children}</div>
    </div>
  );
  const [stLabel, stColor] = STATUS[s.status === 'paused' ? 'paused' : s.status === 'draft' ? 'draft' : 'active'];
  const StatusPill = <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[11.5px] font-semibold" style={{ background: `${stColor}1A`, color: stColor }}><span className="h-1.5 w-1.5 rounded-full" style={{ background: stColor }} /> {stLabel}</span>;
  const KV = ({ k, v }) => <span className="flex justify-between gap-3 border-t border-[#EEF2F7] py-1.5 first:border-t-0"><span className="text-[#475569]">{k}</span><span className="text-right font-medium text-[#0B1C3F]">{v}</span></span>;
  const extraChips = [...filterChips(), ...names(f.past_freq || [], PAST_FREQS, '').split(', '), ...names(f.origin || [], ORIGINS, '').split(', '),
    ...names(f.tiers || [], TIERS, '').split(', '), ...names(f.last_offer || [], LAST_OFFER, '').split(', '),
    ...(ex.recent_contact ? ['Sans les clients contactés depuis 30 jours'] : []), ...(ex.active_offer ? ['Sans les clients ayant une offre active'] : [])]
    .filter((x) => x && !/visites$/.test(x));
  const inPreviewExtra = { jours_absence: String(inDays), offre: page.offers[0]?.name || 'notre offre du moment', lien: 'fidclic.com/c/…' };
  const Step6Inactive = (
    <Card n={6} title="Résumé" sub="Vérifiez les paramètres de votre automatisation avant de l'enregistrer.">
      <div className="grid gap-3 md:grid-cols-2">
        <SumCard icon={Target} title="Scénario" badge={StatusPill}>
          <b className="block text-[13.5px] text-[#0B1C3F]">{s.name || m.label}</b>
          <span className="text-[#475569]">{s.description || `Envoyer automatiquement une notification aux clients qui n'ont pas visité votre établissement depuis ${inDays} jours.`}</span>
        </SumCard>
        <SumCard icon={UserX} title="Déclencheur" n={2}>
          <b className="block text-[13.5px] text-[#0B1C3F]">Client inactif depuis {inDays} jours</b>
          <span className="block text-[#475569]">Un client est considéré comme inactif s'il n'a pas visité votre établissement depuis plus de {inDays} jours.</span>
          <span className="mt-1 block text-[#475569]">À partir du {sc.valid_from ? frDate(sc.valid_from) : "jour de l'activation"} · {sendHour}{tr.repeat === 'every' ? ` · relance tous les ${tr.every_days || 30} j` : ' · une fois par absence'}</span>
        </SumCard>
        <SumCard icon={MessageSquare} title="Message" n={3}>
          <span className="mb-2 flex items-center gap-1.5 text-[12.5px] font-medium text-[#0B1C3F]"><Smartphone size={14} /> Notification Wallet</span>
          <span className="flex gap-3">
            {msg.image_url && <img src={msg.image_url} alt="" className="h-20 w-28 shrink-0 rounded-xl object-cover" />}
            <span className="min-w-0 flex-1"><b className="block text-[#0B1C3F]">{msg.title || '—'}</b><span className="block text-[#475569]">{msg.body || '—'}</span>
              {btn.enabled && <span className="mt-1.5 block rounded-lg border border-[#BFD3FF] py-1 text-center text-[12px] font-semibold text-[#1463FF]">{btn.label}</span>}</span>
          </span>
        </SumCard>
        <SumCard icon={Users} title="Ciblage" n={4}>
          <b className="block text-[13.5px] text-[#0B1C3F]">{tg.mode === 'segment' ? `Segment : ${(page.segments.find((x) => x.key === tg.segment) || {}).label || '—'}` : tg.mode === 'wallet' ? 'Clients avec carte Wallet' : 'Tous mes clients'}</b>
          <span className="mt-1.5 block rounded-xl bg-[#F8FAFC] px-3 py-1">
            <KV k="Inactivité depuis :" v={`Plus de ${inDays} jours`} />
            <KV k="Nombre de visites précédentes :" v={(VISITS_MIN.find(([k2]) => k2 === String(f.visits_min ?? '')) || ['', f.visits_min ? `Au moins ${f.visits_min} visites` : 'Toutes'])[1]} />
            <KV k="Dernière visite avant le :" v={cutoffDate} />
          </span>
          {extraChips.length > 0 && <span className="mt-2 flex flex-wrap gap-1.5">{extraChips.map((c) => <span key={c} className="rounded-lg bg-[#F1F5F9] px-2 py-0.5 text-[11.5px] text-[#334155]">{c}</span>)}</span>}
        </SumCard>
        <SumCard icon={CalendarDays} title="Planification" n={5}>
          {[[CalendarDays, "Jours d'envoi :", inDaysText], [Clock, 'Plage horaire :', `${sc.window_from} – ${sc.window_to}`],
            [Globe, 'Fuseau horaire :', `Europe/Paris (${parisOffset()})`], [Bell, "Limite d'envoi par jour :", limitOn ? `${Number(sc.daily_limit).toLocaleString('fr-FR')} notifications maximum` : 'Aucune limite'],
            ...(sc.valid_to ? [[Flag, 'Date de fin :', frDate(sc.valid_to)]] : [])].map(([I, k, v]) => (
            <span key={k} className="flex items-start gap-2.5 py-1"><I size={16} className="mt-0.5 shrink-0 text-[#1463FF]" /><span><b className="block text-[#0B1C3F]">{k}</b>{v}</span></span>
          ))}
        </SumCard>
        <SumCard icon={Eye} title="Aperçu du déclenchement" n={3}>
          <div className="-m-1"><LockScreenPreview shop={page.shop} logo={page.logo_url} title={msg.title} body={msg.body} image={msg.image_url}
                                                   button={btn.enabled ? btn.label : ''} sample={preview?.sample} compact bigImage extra={inPreviewExtra} /></div>
        </SumCard>
      </div>
    </Card>
  );

  const reach = preview?.reachable;
  const res = row?.results;
  const stepPanel = (() => {
    if (step === 2 && s.scenario === 'geo') {
      return (
        <Panel icon={Users} title="Estimation de l'audience">
          <Stat icon={Wallet} label="Clients joignables" value={reach ? reach.total.toLocaleString('fr-FR') : '…'}
                hint={reach ? `${reach.wallet} avec carte Wallet · ${reach.push} avec notifications` : ''} />
          <Stat icon={Footprints} label="Clients détectés près de vos établissements" value={zone ? zone.clients_week.toLocaleString('fr-FR') : '…'}
                hint={zone ? `7 derniers jours · ${zone.clients_today} aujourd'hui (carte ouverte)` : ''} />
        </Panel>
      );
    }
    if (step === 4) {
      return s.scenario === 'geo' ? (
        <Panel icon={Users} title="Résumé du ciblage" lines={[
          ['Type de passants', (PASSANTS.find((x) => x[0] === (tg.passants || 'all')) || PASSANTS[0])[1]],
          ['Tranche d\'âge', names(f.age, AGES, 'Tous les âges')], ['Genre', names(f.gender, GENDERS, 'Tous')],
          ['Type de client', names(f.client_type || [], CLIENT_TYPES, 'Tous')], ['Dernière visite', names(f.last_visit, LAST_VISIT, 'Tous')],
          ['Météo', weatherNames.join(' ou ') || 'Toutes les conditions']]} />
      ) : <Panel icon={Users} title="Résumé du ciblage" lines={[['Ciblage', targetText()], ['Clients ciblés', preview ? preview.count.toLocaleString('fr-FR') : '…']]} />;
    }
    if (step === 5) {
      return s.scenario === 'geo' ? (
        <Panel icon={CalendarDays} title="Résumé de la planification" lines={[['Période', periodText()], ['Jours de diffusion', geoDays()], ['Horaires', slotsText()],
          ['Heures de forte affluence', rushOn.map((r) => `${hLabel(r[2])} – ${hLabel(r[3])}`).join(' / ') || '—'],
          ['Jours fériés', sc.holidays !== false ? 'Oui' : 'Non'], ['Fréquence', `1 fois / ${tr.cooldown_days || 7} j par client`]]} />
      ) : <Panel icon={CalendarDays} title="Résumé de la planification" lines={[['Planification', planText()]]} />;
    }
    if (step === 6) {
      return (
        <>
          {s.scenario === 'geo' && (
            <Panel icon={BarChart3} title="Résultats de l'automatisation">
              {res && res.sent ? (
                <div className="grid grid-cols-3 gap-2 pt-1 text-center">
                  {[['Envoyés', res.sent, 'carte ouverte'], ['Clics', res.clicks, 'sur le bouton'], ['Visites', res.visits_24h, 'dans les 24 h']].map(([l, v, h]) => (
                    <div key={l} className="rounded-xl bg-[#F5F8FF] p-2"><p className="text-[18px] font-extrabold tabular-nums text-[#0B1C3F]">{v.toLocaleString('fr-FR')}</p>
                      <p className="text-[11.5px] font-semibold text-[#475569]">{l}</p><p className="text-[10.5px] text-[#94A3B8]">{h}</p></div>
                  ))}
                </div>
              ) : <p className="text-[12.5px] text-[#475569]">Les résultats réels (messages envoyés, clics, visites dans les 24 h) s'afficheront ici après les premiers envois.</p>}
              <p className="mt-2 text-[11px] text-[#94A3B8]">Les apparitions sur l'écran verrouillé (Wallet) ne sont pas communiquées par Apple et Google : elles ne sont pas comptées.</p>
            </Panel>
          )}
          <section className="rounded-2xl border border-[#BFD3FF] bg-[#F5F8FF] p-4">
            <p className="mb-1 flex items-center gap-2 text-[13.5px] font-bold text-[#0B1C3F]"><Info size={17} className="text-[#1463FF]" /> Prêt à enregistrer ?</p>
            <p className="text-[12.5px] text-[#475569]">{editing ? 'Votre automatisation sera mise à jour et remplacera l\'ancienne version. Les prochaines notifications seront envoyées selon ces nouveaux paramètres.'
              : s.status !== 'paused' ? 'Votre automatisation partira toute seule dès son prochain déclencheur.' : 'Votre automatisation sera enregistrée en pause : activez-la quand vous voulez.'}</p>
          </section>
        </>
      );
    }
    return s.scenario === 'geo' ? null : Recap;
  })();


  // ---- Bienvenue (mockups 2026-10-11): Déclencheur, Message, Résumé ---------------------
  const WTrigger = (
    <Card n={1} title="Déclencheur" sub="Choisissez quand l'automatisation se déclenche.">
      <div className="flex items-start gap-4 rounded-2xl border border-[#2F6BFF] bg-[#F5F8FF] p-4 shadow-[0_0_0_1px_#2F6BFF]">
        <span className="relative flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-white text-[#1463FF]"><Wallet size={26} />
          <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-[#1463FF] text-white"><Plus size={12} /></span></span>
        <span className="min-w-0 flex-1"><span className="block text-[15px] font-bold text-[#0B1C3F]">Après l'ajout de la carte dans Wallet</span>
          <span className="text-[13px] text-[#475569]">La notification est envoyée automatiquement lorsqu'un client ajoute votre carte de fidélité dans Apple Wallet ou Google Wallet.</span></span>
        <CheckCircle2 size={22} className="shrink-0 fill-[#1463FF] text-white" />
      </div>
      <p className="mt-3 flex items-start gap-2 rounded-xl bg-[#F1F6FF] px-3 py-2.5 text-[12px] text-[#334155]"><Info size={15} className="mt-0.5 shrink-0 text-[#1463FF]" />
        <span>Une seule fois par client : ajouter la carte sur un deuxième téléphone, ou la remettre après l'avoir retirée, n'envoie rien de plus. Un client qui garde seulement sa carte en ligne ne reçoit pas ce message.</span></p>
    </Card>
  );
  const WMessageMini = (
    <Card n={2} title="Message" sub="Personnalisez le message qui sera envoyé à vos clients.">
      <Label right={`${msg.title.length}/${TITLE_MAX}`}>Titre de la notification</Label>
      <input ref={titleRef} className={field} value={msg.title} maxLength={TITLE_MAX} onFocus={() => { lastFocus.current = 'title'; }}
             onChange={(e) => setMsg({ title: e.target.value })} placeholder="Bienvenue chez nous 👋 !" />
      <div className="mt-3"><Label right={`${msg.body.length}/${BODY_MAX}`}>Message de la notification</Label></div>
      <textarea ref={bodyRef} className={`${field} min-h-[96px] resize-y`} value={msg.body} maxLength={BODY_MAX}
                onFocus={() => { lastFocus.current = 'body'; }} onChange={(e) => setMsg({ body: e.target.value })}
                placeholder="Votre carte de fidélité est prête. Profitez pleinement de vos avantages." />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {['prénom', 'nom_commerce', 'offre'].map((v) => (
          <button key={v} type="button" onClick={() => insert(`{${v}}`)}
                  className="inline-flex items-center gap-1 rounded-lg border border-[#DCE5F3] px-2.5 py-1 text-[12px] font-semibold text-[#1D4ED8] hover:bg-[#F5F8FF]"><Plus size={12} /> {WELCOME_VAR_LABELS[v]}</button>
        ))}
        <span className="relative">
          <button type="button" onClick={() => setEmoji((x) => (x ? '' : 'open'))}
                  className="inline-flex items-center gap-1 rounded-lg border border-[#DCE5F3] px-2.5 py-1 text-[12px] font-semibold text-[#1D4ED8] hover:bg-[#F5F8FF]"><Plus size={12} /> Emoji</button>
          {emoji && (
            <span className="absolute left-0 top-8 z-20 grid w-64 grid-cols-8 gap-1 rounded-xl border border-[#E2E8F0] bg-white p-2 shadow-xl">
              {EMOJIS.map((e) => <button key={e} type="button" className="rounded p-1 text-[16px] hover:bg-[#F1F5F9]" onClick={() => { insert(e); setEmoji(''); }}>{e}</button>)}
            </span>
          )}
        </span>
      </div>
    </Card>
  );
  const WStep1 = <div className="space-y-4">{WTrigger}{WMessageMini}</div>;
  const WRow = ({ n, icon: I, title, children, action }) => (
    <div className="flex flex-wrap items-start gap-4 rounded-2xl border border-[#E6EEFB] bg-white p-4 sm:flex-nowrap">
      <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-[#EEF4FF] text-[#1463FF]"><I size={26} /></span>
      <span className="min-w-0 flex-1"><span className="block text-[15px] font-bold text-[#1D4ED8]">{n}. {title}</span>{children}</span>
      {action}
    </div>
  );
  const WEdit = (n) => can && <button type="button" onClick={() => go(n)} className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-[#BFD3FF] px-3.5 py-2 text-[13px] font-semibold text-[#1463FF]"><Pencil size={14} /> Modifier</button>;
  const WStep3 = (
    <Card n={3} title="Résumé" sub="Vérifiez les informations de votre automatisation avant de l'enregistrer.">
      <div className="space-y-3">
        <WRow n={1} icon={Wallet} title="Déclencheur" action={WEdit(1)}>
          <b className="block text-[13.5px] text-[#0B1C3F]">Après l'ajout de la carte dans Wallet</b>
          <span className="text-[12.5px] text-[#475569]">La notification est envoyée automatiquement lorsqu'un client ajoute votre carte de fidélité dans Apple Wallet ou Google Wallet.</span>
        </WRow>
        <WRow n={2} icon={MessageSquare} title="Message" action={WEdit(2)}>
          <span className="mt-1.5 block rounded-xl bg-[#F8FAFF] p-3 text-[12.5px]">
            <b className="block text-[#0B1C3F]">Titre de la notification</b><span className="text-[#334155]">{msg.title || '—'}</span>
            <b className="mt-2 block text-[#0B1C3F]">Texte de la notification</b><span className="text-[#334155]">{msg.body || '—'}</span>
            {btn.enabled && <span className="mt-2 block text-[#334155]"><b className="text-[#0B1C3F]">Bouton :</b> {btn.label}</span>}
          </span>
        </WRow>
        <WRow n={3} icon={Power} title="Statut" action={<Toggle label="Activer l'automatisation" on={s.status !== 'paused'} disabled={!can} onChange={(v) => set({ status: v ? 'active' : 'paused' })} />}>
          <span className="mt-1 flex flex-wrap items-center gap-2 text-[12.5px] text-[#475569]">{StatusPill}
            {s.status !== 'paused' ? "La notification sera envoyée automatiquement dès qu'un client ajoute sa carte." : "En pause : aucune notification ne part tant que vous ne l'activez pas."}</span>
        </WRow>
      </div>
    </Card>
  );
  const PreviewTabs = (extraVars, heading = 'Aperçu de la notification') => (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <p className="mb-3 text-[14.5px] font-bold text-[#0B1C3F]">{heading}</p>
      <div className="mb-3 grid grid-cols-2 gap-1 rounded-xl bg-[#F4F7FC] p-1" role="tablist">
        {[['mobile', 'Aperçu sur mobile'], ['wallet', 'Aperçu Wallet']].map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={pvTab === k} onClick={() => setPvTab(k)}
                  className={`rounded-lg py-2 text-[13px] font-semibold transition ${pvTab === k ? 'bg-white text-[#1463FF] shadow-[inset_0_-2px_0_#1463FF]' : 'text-[#475569]'}`}>{l}</button>
        ))}
      </div>
      <LockScreenPreview bare variant={pvTab} shop={page.shop} logo={page.logo_url} title={msg.title} body={msg.body} image={msg.image_url}
                         button={btn.enabled ? btn.label : ''} sample={preview?.sample}
                         extra={extraVars} />
    </section>
  );
  const WPreview = PreviewTabs({ offre: page.offers[0]?.name || 'notre offre du moment', lien: 'fidclic.com/c/…' });

  // ---- Récompense bientôt disponible (mockups 2026-10-11) -----------------------------
  const nr = preview?.near;
  const unitWord = (n) => (near.unit === 'tampons' ? (Number(n) === 1 ? 'tampon' : 'tampons') : near.unit === '€' ? '€' : (Number(n) === 1 ? 'point' : 'points'));
  const seuil = Number(tr.threshold) || 0;
  const eventLabel = near.unit === 'tampons' ? 'Carte de tampons presque complète' : near.unit === '€' ? 'Prochain palier presque atteint' : 'Seuil de points presque atteint';
  const eventShort = near.unit === 'tampons' ? 'tampons presque complets' : near.unit === '€' ? 'palier presque atteint' : 'points presque atteints';
  const exGoal = near.card_goal || (near.tiers.find((t) => t.reward && t.min > 0) || {}).min || 200;
  const NR_VARS = near.unit === 'tampons' ? ['prénom', 'nom_commerce', 'tampons', 'tampons_restants', 'récompense'] : ['prénom', 'nom_commerce', 'points', 'points_restants', 'récompense'];
  const NR_LABELS = { 'prénom': 'Prénom', nom_commerce: 'Nom établissement', points: 'Nombre de points actuels', tampons: 'Tampons actuels',
    points_restants: 'Points restants', tampons_restants: 'Tampons restants', 'récompense': 'Récompense' };
  const nrExtra = { points_restants: `${seuil} ${unitWord(seuil)}`, tampons_restants: `${seuil} ${unitWord(seuil)}`, 'récompense': near.card_reward,
    points: String(Math.max(0, exGoal - seuil)), tampons: String(Math.max(0, exGoal - seuil)) };
  const Step2NR = (
    <Card n={2} title="Déclencheur" sub="Définissez quand l'automatisation se déclenche.">
      {tr.legacy_visits && (
        <p className="mb-3 flex items-start gap-2 rounded-xl bg-[#FFF7ED] px-3 py-2.5 text-[12px] text-[#9A3412]"><Info size={15} className="mt-0.5 shrink-0" />
          <span>Cette automatisation partait à {tr.legacy_visits} visite{tr.legacy_visits > 1 ? 's' : ''} de la récompense. En l'enregistrant, elle passe au seuil ci-dessous ({seuil} {unitWord(seuil)}).</span></p>
      )}
      <div className="rounded-2xl border border-[#E6EEFB] p-4">
        <p className="mb-3 flex items-start gap-3"><Trophy size={28} className="shrink-0 text-[#1463FF]" />
          <span><span className="block text-[14px] font-bold text-[#0B1C3F]">Événement de déclenchement</span>
            <span className="text-[12.5px] text-[#475569]">Choisissez la condition qui déclenche l'envoi de la notification.</span></span></p>
        <Select label="Événement de déclenchement" value="seuil" onChange={() => {}} options={[['seuil', eventLabel]]} />
        <p className="mt-3 flex items-start gap-2.5 rounded-xl bg-[#F1F6FF] px-3 py-2.5 text-[12.5px] text-[#1E3A8A]"><Info size={18} className="mt-0.5 shrink-0 text-[#1463FF]" />
          {near.unit === 'tampons' ? 'La notification sera envoyée automatiquement lorsqu\'il ne manque plus que quelques tampons au client pour compléter sa carte, ou pour atteindre son prochain palier.'
            : near.unit === '€' ? 'Votre carte est une cagnotte : la notification part quand le client approche de son prochain palier (Bronze → Argent → Or → VIP) et de sa récompense.'
            : 'La notification sera envoyée automatiquement lorsqu\'un client atteint un nombre de points proche du seuil de sa prochaine récompense.'}</p>
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="w-full text-[13.5px] font-bold text-[#0B1C3F]">Seuil de déclenchement</span>
          <Num value={tr.threshold} digits={6} min={1} max={100000} label="Seuil de déclenchement" onChange={(v) => setIn('trigger', { threshold: v })} />
          <span className="text-[13px] text-[#0B1C3F]">{unitWord(seuil)} avant la prochaine récompense
            <span className="block text-[12px] text-[#64748B]">(ex : si la récompense est à {exGoal} {unitWord(exGoal)}, l'envoi se fera à {Math.max(0, exGoal - seuil)} {unitWord(exGoal)}).</span></span>
        </div>
      </div>
      <div className="mt-3 rounded-2xl bg-[#F5F8FF] p-4">
        <p className="mb-1 flex items-center gap-2 text-[13.5px] font-bold text-[#0B1C3F]"><Target size={18} className="text-[#1463FF]" /> Exemple de scénario</p>
        <p className="text-[12.5px] text-[#334155]">Exemple : si votre prochaine récompense est à {exGoal} {unitWord(exGoal)} et que le seuil est fixé à {seuil} {unitWord(seuil)}, le message sera envoyé automatiquement lorsque le client atteint {Math.max(0, exGoal - seuil)} {unitWord(exGoal)}.</p>
        <p className="mt-2 text-[11.5px] text-[#64748B]">La « prochaine récompense » est celle qui arrive en premier pour chaque client : la récompense de la carte ({near.card_reward}){near.tiers.some((t) => t.reward) ? ', ou celle de son prochain palier' : ''}. Une fois par récompense : après l'avoir utilisée, le client sera prévenu à nouveau pour la suivante.</p>
      </div>
    </Card>
  );

  const Step4NR = (
    <Card n={4} title="Ciblage" sub="Choisissez les clients qui recevront cette notification.">
      <Sec title="Type de clients" sub="Cette automatisation sera envoyée uniquement aux clients qui remplissent les conditions suivantes.">
        <div className={`grid gap-3 ${tg.mode === 'wallet' ? 'sm:grid-cols-3' : 'sm:grid-cols-2'}`}>
          {[['filtered', 'Tous les clients éligibles', 'Tous les clients qui atteignent le seuil défini.', Users], ['segment', 'Segments spécifiques', 'Envoyer uniquement à certains segments de clients.', Filter],
            ...(tg.mode === 'wallet' ? [['wallet', 'Clients avec carte Wallet', 'Uniquement les clients ayant ajouté leur carte', Wallet]] : [])].map(([k, l, h, I]) => (
            <button key={k} type="button" onClick={() => setIn('targeting', { mode: k })}
                    className={`flex items-start gap-3 rounded-2xl border p-4 text-left transition ${tg.mode === k ? 'border-[#2F6BFF] bg-[#F5F8FF] shadow-[0_0_0_1px_#2F6BFF]' : 'border-[#E2E8F0] hover:border-[#BFD3FF]'}`}>
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><I size={20} /></span>
              <span className="min-w-0 flex-1"><span className="block text-[13.5px] font-bold text-[#0B1C3F]">{l}</span><span className="text-[12px] text-[#64748B]">{h}</span></span>
              <Ticked on={tg.mode === k} />
            </button>
          ))}
        </div>
        {tg.mode === 'segment' && (
          <div className="mt-3 max-h-[220px] space-y-1.5 overflow-y-auto">
            {page.segments.map((x) => (
              <label key={x.key} className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 ${tg.segment === x.key ? 'border-[#2F6BFF] bg-[#F1F6FF]' : 'border-[#E2E8F0]'}`}>
                <input type="radio" name="au-seg-nr" checked={tg.segment === x.key} onChange={() => setIn('targeting', { segment: x.key })} className="accent-[#1463FF]" />
                <span className="flex-1"><span className="block text-[13px] font-semibold text-[#0B1C3F]">{x.label}</span><span className="text-[11.5px] text-[#64748B]">{x.hint}</span></span>
                <span className="text-[12px] font-semibold tabular-nums text-[#475569]">{(x.count ?? 0).toLocaleString('fr-FR')}</span>
              </label>
            ))}
          </div>
        )}
      </Sec>
      <Sec title="Filtres supplémentaires (optionnel)" sub="Affinez votre cible en ajoutant des critères."
           right={<button type="button" onClick={() => setF({ activity: [], visits_min: '', signed_since: '', last_visit: [], stores: [] })} className="inline-flex items-center gap-1.5 rounded-xl border border-[#BFD3FF] px-3 py-1.5 text-[12px] font-semibold text-[#1463FF]"><RotateCcw size={13} /> Réinitialiser</button>}>
        <div className="grid gap-3 md:grid-cols-2">
          <FilterTile icon={User} label="Statut client" wide>
            <Select label="Statut client" value={one(f.activity || [])} onChange={pick('activity')}
                    options={withMulti(f.activity || [], [['', 'Tous les statuts'], ...(page.statuses || []).map((x) => [x.key, x.label])])} />
          </FilterTile>
          <FilterTile icon={ListIcon} label="Nombre de visites" wide>
            <Select label="Nombre de visites" value={String(f.visits_min ?? '')} onChange={(v) => setF({ visits_min: v })}
                    options={[['', 'Tous'], ...visitsOpts.filter(([k]) => k)]} />
          </FilterTile>
          <FilterTile icon={CalendarDays} label="Inscription depuis" wide>
            <span className="flex items-center gap-2">
              <input type="date" aria-label="Inscription depuis" className={`${field} !py-2`} value={f.signed_since || ''} max={new Date().toISOString().slice(0, 10)}
                     onChange={(e) => setF({ signed_since: e.target.value })} />
              {f.signed_since && <button type="button" onClick={() => setF({ signed_since: '' })} aria-label="Toutes les dates" className="rounded-lg p-2 text-[#64748B] hover:bg-[#F1F5F9]"><X size={15} /></button>}
            </span>
            <span className="mt-1 block text-[11px] text-[#94A3B8]">{f.signed_since ? `Inscrits depuis le ${frDate(f.signed_since)}` : 'Toutes les dates'}</span>
          </FilterTile>
          <FilterTile icon={CalendarDays} label="Dernière visite" wide>
            <Select label="Dernière visite" value={one(f.last_visit)} onChange={pick('last_visit')} options={withMulti(f.last_visit, [['', 'Toutes les dates'], ...LAST_VISIT])} />
          </FilterTile>
          {page.stores.length > 1 && (
            <div className="md:col-span-2"><FilterTile icon={Store} label="Secteur / Point de vente (si plusieurs établissements)" wide>
              <Select label="Point de vente" value={f.stores.length === 1 ? f.stores[0] : f.stores.length ? 'multi' : ''}
                      onChange={(v) => v !== 'multi' && setF({ stores: v ? [v] : [] })}
                      options={[['', 'Tous les établissements'], ...(f.stores.length > 1 ? [['multi', `${f.stores.length} établissements`]] : []), ...page.stores.map((x) => [x.id, x.name])]} />
            </FilterTile></div>
          )}
        </div>
        <p className="mt-3 flex items-start gap-2.5 rounded-xl bg-[#F1F6FF] px-3 py-2.5 text-[12.5px] text-[#1E3A8A]"><Info size={17} className="mt-0.5 shrink-0 text-[#1463FF]" />
          Seuls les clients qui atteignent le seuil défini dans le déclencheur recevront cette notification, et qui correspondent aux filtres sélectionnés.</p>
      </Sec>
    </Card>
  );

  const nrLimitOn = sc.daily_limit !== null && sc.daily_limit !== undefined && sc.daily_limit !== '';
  const Step5NR = (
    <Card n={5} title="Planification" sub="Définissez quand la notification sera envoyée.">
      <Sec title="Jours et horaires d'envoi" sub="Choisissez les jours de la semaine et les plages horaires pendant lesquelles la notification sera envoyée.">
        <div className="flex flex-wrap items-end gap-4">
          <div><span className="mb-1.5 block text-[12.5px] font-semibold text-[#0B1C3F]">Jours de la semaine</span>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Jours de la semaine">
              {DAY_NAMES.map((d, i) => {
                const on = dayList.includes(i);
                return <button key={d} type="button" aria-pressed={on} onClick={() => setInDays(on ? dayList.filter((x) => x !== i) : [...dayList, i])}
                               className={`min-w-[52px] rounded-xl border px-3 py-2.5 text-[13px] font-semibold transition ${on ? 'border-[#1463FF] bg-[#1463FF] text-white' : 'border-[#DCE5F3] bg-white text-[#334155] hover:border-[#BFD3FF]'}`}>{d}</button>;
              })}
            </div></div>
          <div><span className="mb-1.5 block text-[12.5px] font-semibold text-[#0B1C3F]">Plage horaire</span>
            <span className="flex items-center gap-2">
              <span className="w-28"><Select label="Début de la plage" value={sc.window_from} onChange={(v) => setIn('schedule', { window: true, window_from: v })} options={HOURS.map((h) => [h, h])} /></span>
              <span className="text-[#64748B]">–</span>
              <span className="w-28"><Select label="Fin de la plage" value={sc.window_to} onChange={(v) => setIn('schedule', { window: true, window_to: v })} options={[...HOURS, '23:59'].map((h) => [h, h])} /></span>
            </span></div>
        </div>
      </Sec>
      <Sec title="Limite d'envoi quotidienne (optionnelle)" sub="Définissez un nombre maximum de notifications à envoyer par jour.">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px] text-[#0B1C3F]">
          <button type="button" onClick={() => setIn('schedule', { daily_limit: null })} className="flex items-center gap-2"><Radio on={!nrLimitOn} /> Aucune limite</button>
          <span className="flex items-center gap-2">
            <button type="button" onClick={() => setIn('schedule', { daily_limit: sc.daily_limit || 500 })} className="flex items-center gap-2"><Radio on={nrLimitOn} /> Limiter à</button>
            <Num value={nrLimitOn ? sc.daily_limit : '500'} digits={6} min={1} max={100000} label="Notifications par jour" disabled={!nrLimitOn} onChange={(v) => setIn('schedule', { daily_limit: v })} />
            notifications par jour</span>
        </div>
        {nrLimitOn && <p className="mt-2 text-[11.5px] text-[#64748B]">Au-delà, les clients suivants reçoivent la leur le prochain jour d'envoi, au début de la plage horaire : personne n'est oublié.</p>}
      </Sec>
      <Sec title="Fuseau horaire" sub="Les notifications seront envoyées selon le fuseau horaire de votre établissement.">
        <span className={`${field} flex max-w-[420px] items-center gap-2.5 bg-[#F8FAFC]`}><Globe size={17} className="text-[#64748B]" /> Europe/Paris ({parisOffset()})</span>
      </Sec>
      <div className="mt-5 rounded-2xl bg-[#F8FAFF] p-4">
        <p className="mb-3 flex items-center gap-2 text-[13.5px] font-bold text-[#0B1C3F]"><CalendarDays size={18} className="text-[#1463FF]" /> Aperçu du planning hebdomadaire</p>
        <div className="grid grid-cols-7 gap-1.5 text-center">
          {DAY_FULL.map((d, i) => {
            const on = dayList.includes(i);
            return (
              <div key={d}><p className="mb-1 text-[11.5px] font-semibold text-[#0B1C3F]">{d}</p>
                <div className={`rounded-xl border px-1 py-2 ${on ? 'border-[#BBF7D0] bg-[#F0FDF4]' : 'border-[#E2E8F0] bg-[#F1F5F9]'}`}>
                  <p className="text-[11px] font-semibold text-[#0B1C3F]">{on ? `${sc.window_from} - ${sc.window_to}` : '—'}</p>
                  <p className={`mt-0.5 flex items-center justify-center gap-1 text-[10.5px] ${on ? 'text-[#15803D]' : 'text-[#94A3B8]'}`}><span className={`h-1.5 w-1.5 rounded-full ${on ? 'bg-[#16A34A]' : 'bg-[#94A3B8]'}`} />{on ? 'Actif' : 'Inactif'}</p>
                </div></div>
            );
          })}
        </div>
      </div>
    </Card>
  );

  const nrTarget = tg.mode === 'segment' ? `Segment : ${(page.segments.find((x) => x.key === tg.segment) || {}).label || '—'}` : tg.mode === 'wallet' ? 'Clients avec carte Wallet' : 'Tous les clients éligibles';
  const nrChips = [...names(f.activity || [], (page.statuses || []).map((x) => [x.key, x.label]), '').split(', '),
    f.visits_min ? `Au moins ${f.visits_min} visite${Number(f.visits_min) > 1 ? 's' : ''}` : '', f.signed_since ? `Inscrits depuis le ${frDate(f.signed_since)}` : '',
    ...names(f.last_visit, LAST_VISIT, '').split(', ').map((x) => (x ? `Dernière visite : ${x.toLowerCase()}` : '')),
    ...page.stores.filter((x) => f.stores.includes(x.id)).map((x) => x.name)].filter(Boolean);
  const nrWhen = `${inDaysText}, ${sc.window_from} - ${sc.window_to}`;
  const NRRow = ({ n, icon: I, title, children }) => (
    <div className="flex flex-wrap items-start gap-4 rounded-2xl border border-[#E6EEFB] bg-white p-4 sm:flex-nowrap">
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><I size={22} /></span>
      <span className="min-w-0 flex-1 text-[12.5px] text-[#334155]"><span className="block text-[14px] font-bold text-[#0B1C3F]">{title}</span>{children}</span>
      {can && <button type="button" onClick={() => go(n)} className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-[#BFD3FF] px-3.5 py-2 text-[13px] font-semibold text-[#1463FF]"><Pencil size={14} /> Modifier</button>}
    </div>
  );
  const Step6NR = (
    <Card n={6} title="Résumé" sub="Vérifiez les paramètres de votre automatisation avant de l'enregistrer.">
      <div className="space-y-3">
        <NRRow n={1} icon={MessageSquare} title="Scénario"><b className="block text-[#0B1C3F]">{s.name || m.label}</b>
          {s.description || 'Notifier automatiquement les clients lorsqu\'ils approchent du seuil de leur prochaine récompense.'}</NRRow>
        <NRRow n={2} icon={Zap} title="Déclencheur"><b className="block text-[#0B1C3F]">{eventLabel}</b>
          La notification est envoyée lorsque le client a atteint le nombre de {near.unit === 'tampons' ? 'tampons' : near.unit === '€' ? '€' : 'points'} défini (ex : {seuil} {unitWord(seuil)} avant la récompense).</NRRow>
        <NRRow n={3} icon={MessageSquare} title="Message"><span className="block"><b className="text-[#0B1C3F]">Titre :</b> {msg.title || '—'}</span>
          <span className="block"><b className="text-[#0B1C3F]">Texte :</b> {msg.body || '—'}</span>
          {btn.enabled && <span className="block"><b className="text-[#0B1C3F]">Bouton :</b> {btn.label}</span>}</NRRow>
        <NRRow n={4} icon={Users} title="Ciblage"><b className="block text-[#0B1C3F]">{nrTarget}</b>
          {nrChips.length ? <span className="mt-1 flex flex-wrap gap-1.5">{nrChips.map((c) => <span key={c} className="rounded-lg bg-[#F1F5F9] px-2 py-0.5 text-[11.5px]">{c}</span>)}</span> : 'Sans filtre supplémentaire.'}</NRRow>
        <NRRow n={5} icon={CalendarDays} title="Planification"><span className="block"><b className="text-[#0B1C3F]">Envoi :</b> {inDaysText} de {sc.window_from} à {sc.window_to}</span>
          <span className="block"><b className="text-[#0B1C3F]">Limite quotidienne :</b> {nrLimitOn ? `${Number(sc.daily_limit).toLocaleString('fr-FR')} notifications` : 'Aucune limite'}</span>
          <span className="block"><b className="text-[#0B1C3F]">Fuseau horaire :</b> Europe/Paris ({parisOffset()})</span></NRRow>
      </div>
    </Card>
  );
  const NRGroup = ({ icon: I, tone, label, n, pctv }) => (
    <div className="flex items-start gap-3 rounded-xl border border-[#E6EEFB] p-3">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full" style={{ background: `${tone}1A`, color: tone }}><I size={18} /></span>
      <span><span className="block text-[12.5px] text-[#475569]">{label}</span><b className="block text-[20px] leading-tight text-[#0B1C3F]">{nf(n)}</b><span className="text-[11.5px] text-[#64748B]">{pctv}%</span></span>
    </div>
  );
  const grp = (k) => (nr?.groups || []).find((x) => x.key === k) || { n: 0, pct: 0 };
  const NRAudience = ({ label }) => (
    <div className="flex flex-wrap items-center gap-4 pt-1">
      <span className="flex items-center gap-3"><Users size={34} className="text-[#1463FF]" />
        <span><b className="block text-[28px] font-extrabold leading-none text-[#0B1C3F]">{nr ? nf(nr.count) : '…'}</b><span className="text-[12.5px] text-[#475569]">{label}</span></span></span>
      <Delta v={nr?.delta} />
    </div>
  );
  const nrPanel = (() => {
    if (step === 2) {
      return (
        <>
          <Panel icon={Trophy} title="Aperçu du déclencheur">
            <div className="mt-2 flex items-start gap-4 rounded-xl bg-[#F8FAFF] p-3">
              <Trophy size={44} className="shrink-0 text-[#7C3AED]" />
              <span className="text-[12.5px] text-[#475569]"><b className="block text-[14px] text-[#1D4ED8]">Déclenchement</b>
                Lorsqu'un client atteint le seuil défini : <b className="text-[#0B1C3F]">« {eventShort} »</b> ({seuil} {unitWord(seuil)} avant sa récompense).</span>
            </div>
          </Panel>
          <Panel icon={Users} title="Estimation de l'audience"><NRAudience label="clients potentiellement concernés" /></Panel>
        </>
      );
    }
    if (step === 3) {
      return (
        <Panel icon={Hash} title="Variables disponibles">
          <div className="flex flex-wrap gap-2 pt-1">{NR_VARS.map((v) => (
            <button key={v} type="button" onClick={() => insert(`{${v}}`)} className="inline-flex items-center gap-1 rounded-xl border border-[#DCE5F3] px-2.5 py-1.5 text-[12px] font-semibold text-[#1D4ED8] hover:bg-[#F5F8FF]"><Plus size={12} /> {NR_LABELS[v]}</button>
          ))}</div>
        </Panel>
      );
    }
    if (step === 4) {
      return (
        <>
          <Panel icon={Users} title="Aperçu de l'audience"><NRAudience label="clients concernés" />
            <p className="mt-1 text-[11.5px] text-[#64748B]">Estimation basée sur vos clients actuels</p></Panel>
          <Panel icon={BarChart3} title="Répartition estimée">
            <div className="grid grid-cols-2 gap-2 pt-1">
              <NRGroup icon={CheckCircle2} tone="#059669" label="Actifs" n={grp('active').n} pctv={grp('active').pct} />
              <NRGroup icon={Clock} tone="#F59E0B" label="À risque" n={grp('risk').n} pctv={grp('risk').pct} />
              <NRGroup icon={Hourglass} tone="#7C3AED" label="Inactifs" n={grp('inactive').n} pctv={grp('inactive').pct} />
              <NRGroup icon={Sparkles} tone="#7C3AED" label="Nouveaux" n={grp('new').n} pctv={grp('new').pct} />
            </div>
            {grp('other').n > 0 && <p className="mt-2 text-[11.5px] text-[#64748B]">Autres statuts (vos statuts personnalisés) : {nf(grp('other').n)} ({grp('other').pct}%)</p>}
          </Panel>
        </>
      );
    }
    if (step === 5) {
      return (
        <Panel icon={CalendarDays} title="Récapitulatif de la planification">
          {[[CalendarDays, "Jours d'envoi", dayList.map((d) => DAY_FULL[d]).join(', ') || '—'], [Clock, 'Plage horaire', `${sc.window_from} - ${sc.window_to}`],
            [BarChart3, 'Limite quotidienne', nrLimitOn ? `${Number(sc.daily_limit).toLocaleString('fr-FR')} par jour` : 'Aucune limite'], [Globe, 'Fuseau horaire', `Europe/Paris (${parisOffset()})`]].map(([I, k, v]) => (
            <span key={k} className="flex items-start gap-3 border-t border-[#EEF2F7] py-2.5 first:border-t-0"><I size={20} className="mt-0.5 shrink-0 text-[#64748B]" />
              <span className="text-[12.5px]"><b className="block text-[#0B1C3F]">{k}</b><span className="text-[#475569]">{v}</span></span></span>
          ))}
        </Panel>
      );
    }
    if (step === 6) {
      return (
        <>
          {PreviewTabs(nrExtra)}
          <Panel icon={Info} title="Informations complémentaires">
            {[[Users, 'Clients concernés', nr ? `${nf(nr.count)} aujourd'hui, selon les filtres sélectionnés` : 'Selon les filtres sélectionnés'], [Clock, "Moment d'envoi", nrWhen],
              [BarChart3, 'Limite quotidienne', nrLimitOn ? `${Number(sc.daily_limit).toLocaleString('fr-FR')} par jour` : 'Aucune limite'], [Globe, 'Fuseau horaire', `Europe/Paris (${parisOffset()})`]].map(([I, k, v]) => (
              <span key={k} className="flex items-start gap-3 border-t border-[#EEF2F7] py-2.5 first:border-t-0"><I size={20} className="mt-0.5 shrink-0 text-[#1463FF]" />
                <span className="text-[12.5px]"><b className="block text-[#0B1C3F]">{k}</b><span className="text-[#475569]">{v}</span></span></span>
            ))}
          </Panel>
        </>
      );
    }
    return null;
  })();
  const NRPratiques = nrOn && step === 5 && (
    <section className="rounded-2xl border border-[#D9F2E3] bg-[#F3FBF6] p-4">
      <p className="mb-2 flex items-center gap-2 text-[14px] font-bold text-[#0B1C3F]"><Lightbulb size={17} className="text-[#059669]" /> Bonnes pratiques</p>
      {['Privilégiez les heures où vos clients sont habituellement actifs.', 'Évitez d\'envoyer trop tôt le matin ou trop tard le soir.',
        'Vous pouvez ajuster les jours et horaires en fonction des performances.', 'Surveillez les résultats et modifiez le planning si besoin.'].map((t) => (
        <p key={t} className="flex items-start gap-2 py-1 text-[12.5px] text-[#14532D]"><Check size={15} className="mt-0.5 shrink-0 text-[#16A34A]" /> {t}</p>
      ))}
    </section>
  );

  // ---- Parrainage (mockups 2026-10-11): Déclencheur, Message (Parrain / Filleul), Résumé ----
  const sidesOn = tr.sides || [];
  const setSideOn = (side, on) => setIn('trigger', { sides: ['parrain', 'filleul'].filter((x) => (x === side ? on : sidesOn.includes(x))) });
  const rc = refCfg || {};
  const setRc = (patch) => { setRefCfg((o) => ({ ...o, ...patch })); setRefDirty(true); };
  const enableProgramme = async () => {
    setBusy('ref'); setError('');
    try {
      const { data: full } = await ownerAPI.referralConfig();
      await ownerAPI.saveReferralConfig({ ...full, enabled: true });
      setRefCfg((o) => ({ ...o, enabled: true }));
    } catch (e) { setError(e?.response?.data?.detail || "Le parrainage n'a pas pu être activé."); } finally { setBusy(''); }
  };
  const RefOff = refCfg && !rc.enabled && (
    <p className="mb-3 flex flex-wrap items-start gap-2 rounded-xl bg-[#FFF7ED] px-3 py-2.5 text-[12.5px] text-[#9A3412]"><AlertTriangle size={16} className="mt-0.5 shrink-0" />
      <span className="min-w-0 flex-1"><b>Le parrainage est désactivé.</b> Aucun point n'est crédité, donc aucun message ne part, même si cette automatisation est active.</span>
      {rc.can_edit && <button type="button" disabled={!!busy} onClick={enableProgramme} className="rounded-lg bg-[#EA580C] px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-60">Activer le parrainage</button>}
    </p>
  );
  const RStep1 = (
    <div className="space-y-4">
      <Card n={1} title="Déclencheur" sub="Choisissez quand l'automatisation se déclenche.">
        {RefOff}
        <div className="flex items-start gap-4 rounded-2xl border border-[#2F6BFF] bg-[#F5F8FF] p-4 shadow-[0_0_0_1px_#2F6BFF]">
          <Users size={34} className="shrink-0 text-[#1463FF]" />
          <span className="min-w-0 flex-1"><span className="block text-[15px] font-bold text-[#0B1C3F]">Un client parraine un ami</span>
            <span className="text-[13px] text-[#475569]">L'automatisation se déclenche lorsque l'un de vos clients partage son QR code de parrainage et que son ami, inscrit grâce à lui, valide sa visite : les points de parrainage sont alors crédités{rc.reward_mode === 'every' ? ' (puis à chacune de ses visites)' : rc.reward_mode === 'first_then' ? ' (un bonus, puis à chacune de ses visites)' : ''}.</span></span>
          <CheckCircle2 size={22} className="shrink-0 fill-[#1463FF] text-white" />
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {[['parrain', 'Message au parrain', 'Le client qui a invité son ami'], ['filleul', 'Message au filleul', "L'ami invité"]].map(([k, l, h]) => (
            <div key={k} className="flex items-center gap-3 rounded-xl border border-[#E6EEFB] p-3">
              <span className="min-w-0 flex-1"><span className="block text-[13px] font-semibold text-[#0B1C3F]">{l}</span><span className="text-[11.5px] text-[#64748B]">{h}</span></span>
              <Toggle label={l} on={sidesOn.includes(k)} onChange={(v) => setSideOn(k, v)} />
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
  const refBtn = refFil ? ((s.message_filleul || {}).button || {}) : btn;
  const setRefBtn = (patch) => (refFil ? setS((o) => ({ ...o, message_filleul: { ...o.message_filleul, button: { ...(o.message_filleul?.button || {}), ...patch } } })) : setBtn(patch));
  const refChips = [...REF_VARS, refFil ? 'parrain' : 'filleul'];
  const RStep2 = (
    <Card n={2} title="Message" sub={`Personnalisez le message qui sera envoyé au client ${refFil ? 'filleul' : 'parrain'}.`}>
      <div className="mb-4 grid grid-cols-2 gap-1 rounded-xl bg-[#F4F7FC] p-1" role="tablist" aria-label="Message">
        {[['parrain', 'Parrain'], ['filleul', 'Filleul']].map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={refSide === k} onClick={() => setRefSide(k)}
                  className={`rounded-lg py-2 text-[13px] font-semibold transition ${refSide === k ? 'bg-white text-[#1463FF] shadow-[inset_0_-2px_0_#1463FF]' : 'text-[#475569]'}`}>
            {l} {!sidesOn.includes(k) && <span className="ml-1 rounded-full bg-[#F1F5F9] px-1.5 py-0.5 text-[10.5px] font-semibold text-[#64748B]">désactivé</span>}</button>
        ))}
      </div>
      <div className="mb-3 flex items-center justify-between rounded-xl border border-[#E6EEFB] px-3 py-2.5">
        <span className="text-[13px] font-semibold text-[#0B1C3F]">Envoyer ce message au {refFil ? 'filleul' : 'parrain'}</span>
        <Toggle label={`Envoyer au ${refFil ? 'filleul' : 'parrain'}`} on={sidesOn.includes(refSide)} onChange={(v) => setSideOn(refSide, v)} />
      </div>
      <Label right={`${(cur.title || '').length}/${TITLE_MAX}`}>Titre de la notification</Label>
      <input ref={titleRef} className={field} value={cur.title || ''} maxLength={TITLE_MAX} onFocus={() => { lastFocus.current = 'title'; }}
             onChange={(e) => setCur({ title: e.target.value })} placeholder={refFil ? FILLEUL_MSG.title : m.title} />
      <div className="mt-3"><Label right={`${(cur.body || '').length}/${BODY_MAX}`}>Texte de la notification</Label></div>
      <textarea ref={bodyRef} className={`${field} min-h-[96px] resize-y`} value={cur.body || ''} maxLength={BODY_MAX}
                onFocus={() => { lastFocus.current = 'body'; }} onChange={(e) => setCur({ body: e.target.value })} placeholder={refFil ? FILLEUL_MSG.body : m.body} />
      <p className="mt-3 text-[13.5px] font-bold text-[#0B1C3F]">Variables disponibles</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {refChips.map((v) => (
          <button key={v} type="button" title={`{${v}}`} onClick={() => insert(`{${v}}`)}
                  className="inline-flex items-center gap-1 rounded-lg bg-[#EEF4FF] px-2.5 py-1 text-[12px] font-semibold text-[#1D4ED8] hover:bg-[#E0EAFF]"><Plus size={12} /> {REF_LABELS[v]}</button>
        ))}
        <span className="relative">
          <button type="button" onClick={() => setEmoji((x) => (x ? '' : 'open'))} className="inline-flex items-center gap-1 rounded-lg bg-[#EEF4FF] px-2.5 py-1 text-[12px] font-semibold text-[#1D4ED8]"><Plus size={12} /> Emoji</button>
          {emoji && (
            <span className="absolute left-0 top-8 z-20 grid w-64 grid-cols-8 gap-1 rounded-xl border border-[#E2E8F0] bg-white p-2 shadow-xl">
              {EMOJIS.map((e) => <button key={e} type="button" className="rounded p-1 text-[16px] hover:bg-[#F1F5F9]" onClick={() => { insert(e); setEmoji(''); }}>{e}</button>)}
            </span>
          )}
        </span>
      </div>
      <div className="mt-4 rounded-2xl border border-[#E6EEFB] p-4">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><Link2 size={18} /></span>
          <span className="min-w-0 flex-1"><span className="block text-[13.5px] font-bold text-[#0B1C3F]">Bouton d'action <span className="font-normal text-[#64748B]">(optionnel)</span></span>
            <span className="text-[12px] text-[#64748B]">S'affiche sur la carte du client quand il ouvre la notification.</span></span>
          <Toggle label="Bouton d'action" on={Boolean(refBtn.enabled)} onChange={(v) => setRefBtn({ enabled: v })} />
        </div>
        {refBtn.enabled && (
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="block"><Label right={`${(refBtn.label || '').length}/${BUTTON_MAX}`}>Texte du bouton</Label>
              <input className={field} value={refBtn.label || ''} maxLength={BUTTON_MAX} onChange={(e) => setRefBtn({ label: e.target.value })} placeholder="Voir mes points" /></label>
            <label className="block"><Label>Lien d'action</Label>
              <Select label="Lien du bouton" value={refBtn.link_type || 'card'} onChange={(v) => setRefBtn({ link_type: v })}
                      options={[['card', 'La carte du client'], ['rewards', 'Page Récompenses'], ['offer', 'Une de vos offres'], ['url', 'Un lien personnalisé']]} /></label>
            {refBtn.link_type === 'offer' && (
              <label className="block sm:col-span-2"><Label>Offre</Label>
                <Select label="Offre" value={refBtn.offer_id || ''} onChange={(v) => setRefBtn({ offer_id: v || null })}
                        options={[['', 'Sélectionner une offre'], ...page.offers.map((o) => [o.id, o.name])]} /></label>
            )}
            {refBtn.link_type === 'url' && (
              <label className="block sm:col-span-2"><Label>Adresse du lien</Label>
                <input className={field} value={refBtn.url || ''} onChange={(e) => setRefBtn({ url: e.target.value })} placeholder="monsite.fr/parrainage" inputMode="url" /></label>
            )}
          </div>
        )}
      </div>
    </Card>
  );
  const pts = (n) => `+${Number(n) || 0} point${Number(n) > 1 ? 's' : ''}`;
  const rewardLine = (side) => {
    const a = side === 'parrain' ? rc.referrer_reward_points : rc.referee_reward_points;
    const b = side === 'parrain' ? rc.referrer_reward_points_next : rc.referee_reward_points_next;
    if (rc.reward_mode === 'every') return `${pts(a)} à la visite qui valide, puis à chaque visite du filleul`;
    if (rc.reward_mode === 'first_then') return `${pts(a)} à la visite qui valide, puis ${pts(b)} à chaque visite du filleul`;
    return `${pts(a)}, une fois`;
  };
  const RRow = ({ icon: I, tone = '#1463FF', title, children, action }) => (
    <div className="flex flex-wrap items-start gap-4 rounded-2xl border border-[#E6EEFB] bg-white p-4 sm:flex-nowrap">
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl" style={{ background: `${tone}14`, color: tone }}><I size={26} /></span>
      <span className="min-w-0 flex-1 text-[12.5px] text-[#334155]"><span className="block text-[15px] font-bold text-[#1D4ED8]">{title}</span>{children}</span>
      {action}
    </div>
  );
  const REdit = (n, side) => can && <button type="button" onClick={() => { if (side) setRefSide(side); go(n); }} className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-[#BFD3FF] px-3.5 py-2 text-[13px] font-semibold text-[#1463FF]"><Pencil size={14} /> Modifier</button>;
  const RStep3 = (
    <Card n={3} title="Résumé" sub="Vérifiez les informations de votre automatisation avant de l'enregistrer.">
      {RefOff}
      <div className="space-y-3">
        <RRow icon={Users} title="Déclencheur" action={REdit(1)}><b className="block text-[#0B1C3F]">Un client parraine un ami.</b>
          La récompense est attribuée après le scan valide de la carte du filleul lors d'un achat ou d'une prestation{Number(rc.minimum_visits_to_earn) > 1 ? ` (à sa ${rc.minimum_visits_to_earn}e visite)` : ''}.</RRow>
        {['parrain', 'filleul'].map((side) => {
          const mm = sideMsg(side);
          return (
            <RRow key={side} icon={side === 'parrain' ? Award : Star} tone={side === 'parrain' ? '#F59E0B' : '#E11D48'} title={`Message — ${side === 'parrain' ? 'Parrain' : 'Filleul'}`}
                  action={REdit(2, side)}>
              {sidesOn.includes(side) ? (<>
                <span className="block"><b className="text-[#0B1C3F]">Titre :</b> {mm.title || '—'}</span>
                <span className="block"><b className="text-[#0B1C3F]">Texte :</b> {mm.body || '—'}</span></>)
                : <span className="text-[#94A3B8]">Désactivé : aucun message au {side}.</span>}
            </RRow>
          );
        })}
        <RRow icon={Euro} tone="#2563EB" title="Récompenses"
              action={rc.can_edit ? <button type="button" onClick={() => setRefEdit((v) => !v)} className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-[#BFD3FF] px-3.5 py-2 text-[13px] font-semibold text-[#1463FF]"><Pencil size={14} /> {refEdit ? 'Fermer' : 'Modifier'}</button> : null}>
          <span className="block"><b className="text-[#0B1C3F]">Parrain :</b> {rewardLine('parrain')}</span>
          <span className="block"><b className="text-[#0B1C3F]">Filleul :</b> {rewardLine('filleul')}</span>
          {!rc.can_edit && <span className="mt-1 block text-[11.5px] text-[#64748B]">Seul le propriétaire peut modifier les récompenses de parrainage.</span>}
          {refEdit && rc.can_edit && (
            <span className="mt-3 grid gap-3 rounded-xl bg-[#F8FAFF] p-3 sm:grid-cols-2">
              <label className="block"><Label>Points du parrain</Label><Num value={String(rc.referrer_reward_points ?? '')} digits={5} min={0} max={10000} label="Points du parrain" onChange={(v) => setRc({ referrer_reward_points: v })} /></label>
              <label className="block"><Label>Points du filleul</Label><Num value={String(rc.referee_reward_points ?? '')} digits={5} min={0} max={10000} label="Points du filleul" onChange={(v) => setRc({ referee_reward_points: v })} /></label>
              <label className="block sm:col-span-2"><Label>Quand créditer</Label>
                <Select label="Quand créditer" value={rc.reward_mode || 'once'} onChange={(v) => setRc({ reward_mode: v })} options={REWARD_MODES} /></label>
              {rc.reward_mode === 'first_then' && (<>
                <label className="block"><Label>Ensuite, parrain (par visite)</Label><Num value={String(rc.referrer_reward_points_next ?? '')} digits={5} min={0} max={10000} label="Ensuite, parrain" onChange={(v) => setRc({ referrer_reward_points_next: v })} /></label>
                <label className="block"><Label>Ensuite, filleul (par visite)</Label><Num value={String(rc.referee_reward_points_next ?? '')} digits={5} min={0} max={10000} label="Ensuite, filleul" onChange={(v) => setRc({ referee_reward_points_next: v })} /></label>
              </>)}
              <label className="block sm:col-span-2"><Label>Visites du filleul avant validation</Label>
                <Num value={String(rc.minimum_visits_to_earn ?? '')} min={1} max={20} label="Visites du filleul avant validation" onChange={(v) => setRc({ minimum_visits_to_earn: v })} /></label>
              <span className="text-[11.5px] text-[#64748B] sm:col-span-2">Les mêmes règles que la page Parrainage : elles y sont mises à jour à l'enregistrement.</span>
            </span>
          )}
        </RRow>
        <RRow icon={Power} tone="#059669" title="Statut" action={<Toggle label="Activer l'automatisation" on={s.status !== 'paused'} disabled={!can} onChange={(v) => set({ status: v ? 'active' : 'paused' })} />}>
          <span className="flex flex-wrap items-center gap-2">{StatusPill}{s.status !== 'paused' ? 'Cette automatisation sera active dès son enregistrement.' : 'En pause : aucun message ne part.'}</span>
        </RRow>
      </div>
    </Card>
  );
  const refExtra = (side) => ({ 'récompense': pts(side === 'parrain' ? rc.referrer_reward_points : rc.referee_reward_points).slice(1),
    lien: 'fidclic.com/c/…', amis_parraines: '3', filleul: 'Marie', parrain: 'Lucas', points_gagnés: String(side === 'parrain' ? rc.referrer_reward_points : rc.referee_reward_points),
    visite_ami: 'est venu' });
  // Apple Wallet: the parrainage rides on the points field's banner (features/automations._deliver)
  const refWallet = (t, b) => `${b} Vous avez maintenant 120 points.`;
  const RPreview = (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <p className="mb-3 text-[14.5px] font-bold text-[#0B1C3F]">Aperçu de la notification</p>
      <div className="mb-3 grid grid-cols-2 gap-1 rounded-xl bg-[#F4F7FC] p-1" role="tablist">
        {[['mobile', 'Aperçu sur mobile'], ['wallet', 'Aperçu Wallet']].map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={pvTab === k} onClick={() => setPvTab(k)}
                  className={`rounded-lg py-2 text-[13px] font-semibold transition ${pvTab === k ? 'bg-white text-[#1463FF] shadow-[inset_0_-2px_0_#1463FF]' : 'text-[#475569]'}`}>{l}</button>
        ))}
      </div>
      <LockScreenPreview bare variant={pvTab} shop={page.shop} logo={page.logo_url} title={cur.title} body={cur.body} image={null}
                         button={refBtn.enabled ? refBtn.label : ''} sample={preview?.sample} extra={refExtra(refSide)} walletText={refWallet} />
    </section>
  );
  const RBoth = (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <p className="mb-3 text-[14.5px] font-bold text-[#0B1C3F]">Aperçu des notifications</p>
      <div className="mb-3 grid grid-cols-2 gap-1 rounded-xl bg-[#F4F7FC] p-1" role="tablist">
        {[['parrain', 'Parrain'], ['filleul', 'Filleul']].map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={refSide === k} onClick={() => setRefSide(k)}
                  className={`rounded-lg py-2 text-[13px] font-semibold transition ${refSide === k ? 'bg-white text-[#1463FF] shadow-[inset_0_-2px_0_#1463FF]' : 'text-[#475569]'}`}>{l}</button>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2">
        {['parrain', 'filleul'].map((side) => (
          <div key={side} className={`${refSide === side ? '' : 'opacity-60'} ${sidesOn.includes(side) ? '' : 'grayscale'}`}>
            <LockScreenPreview bare compact shop={page.shop} logo={page.logo_url} title={sideMsg(side).title} body={sideMsg(side).body}
                               sample={preview?.sample} extra={refExtra(side)} />
          </div>
        ))}
      </div>
    </section>
  );

  // ---- Client inactif: the right column of each step (mockups) -----------------------
  const Delta = ({ v, label = 'par rapport au mois dernier' }) => (v === null || v === undefined ? null : (
    <span className="flex items-start gap-2 border-l border-[#E6EEFB] pl-4">
      <ArrowUp size={20} className={`mt-0.5 shrink-0 ${v >= 0 ? 'text-[#059669]' : 'rotate-180 text-[#DC2626]'}`} />
      <span><b className={`block text-[15px] ${v >= 0 ? 'text-[#059669]' : 'text-[#DC2626]'}`}>{v >= 0 ? '+' : ''}{v}%</b><span className="text-[12px] text-[#475569]">{label}</span></span>
    </span>
  ));
  const Audience = ({ label = 'clients concernés' }) => (
    <div className="flex flex-wrap items-center gap-4">
      <span className="flex items-center gap-3"><Users size={34} className="text-[#1463FF]" />
        <span><b className="block text-[28px] font-extrabold leading-none text-[#0B1C3F]">{ins ? nf(ins.count) : '…'}</b><span className="text-[12.5px] text-[#475569]">{label}</span></span></span>
      <Delta v={ins?.delta} />
    </div>
  );
  const Donut = ({ part, total }) => {
    const r = 34; const c = 2 * Math.PI * r; const pctv = total ? part / total : 0;
    return (
      <svg width="92" height="92" viewBox="0 0 92 92" aria-hidden="true" className="shrink-0">
        <circle cx="46" cy="46" r={r} fill="none" stroke="#E6EEFB" strokeWidth="14" />
        <circle cx="46" cy="46" r={r} fill="none" stroke="#1463FF" strokeWidth="14" strokeDasharray={`${c * pctv} ${c}`} transform="rotate(-90 46 46)" strokeLinecap="butt" />
      </svg>
    );
  };
  const Bars = ({ title, rows }) => (
    <div className="grid grid-cols-[96px_1fr] gap-x-3 border-t border-[#EEF2F7] py-2.5 first:border-t-0">
      <span className="text-[12.5px] font-semibold text-[#0B1C3F]">{title}</span>
      <span className="space-y-1.5">{rows.map(([l, p]) => (
        <span key={l} className="grid grid-cols-[72px_1fr_36px] items-center gap-2 text-[11.5px] text-[#475569]">
          <span>{l}</span><span className="h-2 rounded-full bg-[#E6EEFB]"><span className="block h-2 rounded-full bg-[#1463FF]" style={{ width: `${p}%` }} /></span><span className="text-right tabular-nums">{p}%</span>
        </span>))}</span>
    </div>
  );
  const pctOf = (list, key) => (list || []).find((x) => x.key === key)?.pct ?? 0;
  const impact = ins?.impact;
  const inactivePanel = (() => {
    if (step === 2) {
      return (
        <>
          <Panel icon={UserX} title="Aperçu du déclencheur">
            <div className="mt-2 flex items-start gap-4 rounded-xl bg-[#F8FAFF] p-3">
              <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-[#F1EAFF] text-[#7C3AED]"><CalendarDays size={30} /></span>
              <span className="text-[12.5px] text-[#475569]"><span className="block">Clients inactifs depuis</span>
                <b className="block text-[24px] font-extrabold leading-tight text-[#0B1C3F]">{inDays} jours</b>
                Notification envoyée {sc.valid_from ? `à partir du ${frDate(sc.valid_from)}` : "dès l'activation"} à {sendHour}</span>
            </div>
            <p className="mt-2 text-[12px] text-[#475569]">Les clients inactifs recevront la notification à cette date et heure, selon les jours et horaires définis.</p>
          </Panel>
          <Panel icon={Users} title="Estimation de l'audience"><div className="pt-1"><Audience /></div></Panel>
        </>
      );
    }
    if (step === 3) {
      return (
        <Panel icon={Hash} title="Variables disponibles">
          <div className="flex flex-wrap gap-2 pt-1">{INACTIVE_VARS.map((v) => (
            <button key={v} type="button" onClick={() => insert(`{${v}}`)} className="inline-flex items-center gap-1 rounded-xl border border-[#DCE5F3] px-2.5 py-1.5 text-[12px] font-semibold text-[#1D4ED8] hover:bg-[#F5F8FF]"><Plus size={12} /> {INACTIVE_VAR_LABELS[v]}</button>
          ))}</div>
        </Panel>
      );
    }
    if (step === 4) {
      const kept = ins ? ins.count : 0; const all = ins ? ins.lapsed : 0;
      return (
        <>
          <Panel icon={Users} title="Aperçu de l'audience">
            <div className="pt-1"><Audience label="clients inactifs" /></div>
            <div className="mt-3 flex items-center gap-4">
              <Donut part={kept} total={all} />
              <span className="flex-1 space-y-2 text-[12.5px]">
                <span className="grid grid-cols-[1fr_auto_auto] items-center gap-3"><span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-[#1463FF]" />Inactifs (&gt; {inDays} jours)</span><b className="tabular-nums">{nf(kept)}</b><span className="w-10 text-right text-[#1463FF]">{all ? Math.round(kept / all * 100) : 0}%</span></span>
                <span className="grid grid-cols-[1fr_auto_auto] items-center gap-3 text-[#64748B]"><span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-[#E6EEFB]" />Autres clients (exclus)</span><b className="tabular-nums">{nf(ins?.excluded)}</b><span className="w-10 text-right">{all ? 100 - Math.round(kept / all * 100) : 0}%</span></span>
              </span>
            </div>
          </Panel>
          <Panel icon={BarChart3} title="Répartition de l'audience">
            {ins && ins.count ? (
              <div className="pt-1">
                <Bars title="Âge" rows={AGE_BARS.map(([k, l]) => [l, pctOf(ins.breakdown.age, k)])} />
                <Bars title="Genre" rows={[['Femmes', pctOf(ins.breakdown.gender, 'F')], ['Hommes', pctOf(ins.breakdown.gender, 'M')]]} />
                <Bars title="Canal d'acquisition" rows={CHANNELS.map(([k, l]) => [l, pctOf(ins.breakdown.channel, k)])} />
              </div>
            ) : <p className="pt-1 text-[12.5px] text-[#64748B]">La répartition s'affiche dès qu'au moins un client correspond au ciblage.</p>}
          </Panel>
        </>
      );
    }
    if (step === 5) {
      return (
        <>
          <Panel icon={CalendarDays} title="Aperçu du planning">
            <ol className="relative mt-2 space-y-4 pl-7 before:absolute before:bottom-3 before:left-[9px] before:top-3 before:border-l-2 before:border-dashed before:border-[#BFD3FF]">
              {[[Zap, 'Déclenchement', `Client inactif depuis ${inDays} jours`], [Hourglass, 'Planification', `${inDaysText} · entre ${sc.window_from} et ${sc.window_to}${limitOn ? ` (${Number(sc.daily_limit).toLocaleString('fr-FR')} max/jour)` : ''}`],
                [Smartphone, 'Envoi de la notification', msg.title || '—']].map(([I, t, d]) => (
                <li key={t} className="relative flex items-start gap-3"><span className="absolute -left-7 top-3 h-3 w-3 rounded-full border-2 border-white bg-[#1463FF] shadow" />
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><I size={19} /></span>
                  <span className="min-w-0 text-[12.5px]"><b className="block text-[#0B1C3F]">{t}</b><span className="text-[#475569]">{d}</span></span></li>
              ))}
            </ol>
          </Panel>
          <section className="rounded-2xl border border-[#BFD3FF] bg-[#F5F8FF] p-4">
            <p className="flex items-start gap-3"><Clock size={22} className="mt-0.5 shrink-0 text-[#1463FF]" />
              <span><b className="block text-[13.5px] text-[#0B1C3F]">Prochain envoi estimé</b>
                <b className="block text-[14.5px] text-[#1463FF]">{nextSend || 'Aucun jour d\'envoi à venir'}</b>
                <span className="text-[12px] text-[#475569]">(si des clients inactifs correspondent aux critères)</span></span></p>
          </section>
        </>
      );
    }
    if (step === 6) {
      return (
        <>
          <Panel icon={Power} title="Statut de l'automatisation">
            <div className="mt-2 flex items-center gap-3">
              <Toggle label="Activer l'automatisation" on={s.status !== 'paused'} disabled={!can} onChange={(v) => set({ status: v ? 'active' : 'paused' })} />
              <b className="text-[14px] text-[#0B1C3F]">{s.status !== 'paused' ? "L'automatisation est activée" : "L'automatisation est en pause"}</b>
            </div>
            <p className="mt-1.5 text-[12px] text-[#475569]">{s.status !== 'paused' ? 'Les notifications seront envoyées automatiquement selon les paramètres définis.' : 'Aucune notification ne part tant que vous ne la réactivez pas.'}</p>
          </Panel>
          <Panel icon={TrendingUp} title="Estimation de l'impact">
            <Stat icon={Users} label="clients concernés" value={ins ? nf(ins.count) : '…'} />
            <Stat icon={ArrowUp} label="potentiel de réactivation" value={impact?.rate != null ? `+${Math.round(impact.rate * 100)}%` : '—'}
                  hint={impact?.basis === 'shop' ? `D'après vos ${impact.sends} relances passées` : impact?.basis === 'sector' ? 'Moyenne de commerces de votre secteur' : 'Pas encore assez de relances mesurées'} />
            <Stat icon={Target} label="clients estimés réactivés" value={impact?.reactivated != null ? `~ ${nf(impact.reactivated)}` : '—'} />
            <Stat icon={BarChart3} label="revenu potentiel estimé" value={impact?.revenue != null ? `+${nf(impact.revenue)} €` : '—'}
                  hint={impact?.basket ? `Panier moyen de ces clients : ${impact.basket.toLocaleString('fr-FR')} €` : (impact?.rate != null ? 'Montants des achats inconnus' : '')} />
            <p className="mt-1 text-[11px] text-[#94A3B8]">Réactivé = revenu en caisse dans les 15 jours qui suivent le message. Ce sont des estimations tirées de vrais envois, jamais des chiffres inventés.</p>
          </Panel>
        </>
      );
    }
    return null;
  })();
  const BonnesPratiques = inactiveOn && step === 2 && (
    <section className="rounded-2xl border border-[#D9F2E3] bg-[#F3FBF6] p-4">
      <p className="mb-2 flex items-center gap-2 text-[14px] font-bold text-[#0B1C3F]"><Lightbulb size={17} className="text-[#059669]" /> Bonnes pratiques</p>
      {['Choisissez un délai d\'inactivité adapté à votre secteur (60 à 90 jours).', 'Évitez d\'envoyer vos relances trop tôt.',
        'Testez différents jours et horaires pour identifier le meilleur moment.', 'Analysez les résultats et ajustez si nécessaire.'].map((t) => (
        <p key={t} className="flex items-start gap-2 py-1 text-[12.5px] text-[#14532D]"><Check size={15} className="mt-0.5 shrink-0 text-[#16A34A]" /> {t}</p>
      ))}
    </section>
  );

  const geoNew = s.scenario === 'geo' && !editing;
  const avisNew = s.scenario === 'google_review' && !editing;
  const createLabel = geoNew ? "Activer l'automatisation" : s.scenario === 'google_review' ? "Enregistrer l'automatisation" : "Créer l'automatisation";
  const content = refOn ? [null, RStep1, RStep2, RStep3][Math.min(step, 3)]
    : welcomeOn ? [null, WStep1, Step3, WStep3][Math.min(step, 3)]
    : nrOn ? [null, Step1, Step2NR, Step3, Step4NR, Step5NR, Step6NR][step]
    : inactiveOn ? [null, Step1, Step2Inactive, Step3, Step4Inactive, Step5Inactive, Step6Inactive][step]
    : [null, Step1, s.scenario === 'geo' ? Step2Geo : s.scenario === 'google_review' ? Step2Avis : Step2, Step3, s.scenario === 'geo' ? Step4Geo : Step4, s.scenario === 'geo' ? Step5Geo : s.scenario === 'google_review' ? Step5Avis : Step5, Step6][step];
  // the header's « Désactiver / Activer » and « ••• » (Client inactif mockups)
  const fmtWhen = (iso) => { try { const d = new Date(iso); return `${d.toLocaleDateString('fr-FR')} à ${d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`; } catch { return ''; } };
  const flip = async () => {
    const nextSt = s.status === 'paused' ? 'active' : 'paused';
    if (!editing) { set({ status: nextSt }); return; }
    setBusy('status'); setError('');
    try {
      await ownerAPI.automationStatus(id, nextSt);
      set({ status: nextSt });
      setRow((r) => (r ? { ...r, status: nextSt, updated_at: new Date().toISOString() } : r));
    } catch (e) { setError(e?.response?.data?.detail || "Le statut n'a pas pu être changé."); } finally { setBusy(''); }
  };
  const menuAct = async (what) => {
    setMenuOpen(false);
    if (what === 'draft') { save('draft'); return; }
    setBusy(what); setError('');
    try {
      if (what === 'duplicate') { await ownerAPI.duplicateAutomation(id); navigate('/dashboard/automations', { state: { flash: 'Automatisation dupliquée (en brouillon).' } }); }
      if (what === 'delete') {
        if (!window.confirm('Supprimer cette automatisation ? Ses envois passés restent dans vos statistiques.')) { setBusy(''); return; }
        await ownerAPI.deleteAutomation(id); navigate('/dashboard/automations', { state: { flash: 'Automatisation supprimée.' } });
      }
    } catch (e) { setError(e?.response?.data?.detail || "L'action n'a pas abouti."); setBusy(''); }
  };
  const InactiveHeader = (
    <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div className="flex items-start gap-4">
        <button type="button" onClick={() => navigate('/dashboard/automations')} aria-label="Retour aux automatisations"
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><ArrowLeft size={20} /></button>
        <div>
          <h1 className="text-[25px] font-extrabold leading-tight text-[#0B1C3F]">{editing ? "Modifier l'automatisation" : 'Créer une automatisation'} — {s.name || m.label}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-3 text-[13.5px] text-[#475569]">{StatusPill}
            {editing && row?.updated_at && <span>Dernière modification : {fmtWhen(row.updated_at)}</span>}</p>
        </div>
      </div>
      {can && (
        <div className="flex items-center gap-2">
          <span className="relative">
            <button type="button" aria-label="Plus d'actions" aria-haspopup="menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((v) => !v)}
                    className="flex h-11 w-11 items-center justify-center rounded-xl border border-[#DCE5F3] bg-white text-[#0B1C3F] hover:border-[#BFD3FF]"><MoreHorizontal size={20} /></button>
            {menuOpen && (
              <span role="menu" className="absolute right-0 top-12 z-30 w-60 rounded-xl border border-[#E2E8F0] bg-white p-1.5 shadow-xl">
                <button type="button" role="menuitem" onClick={() => menuAct('draft')} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-[13px] hover:bg-[#F8FAFC]"><Pencil size={15} /> Enregistrer en brouillon</button>
                {editing && <button type="button" role="menuitem" onClick={() => menuAct('duplicate')} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-[13px] hover:bg-[#F8FAFC]"><Copy size={15} /> Dupliquer</button>}
                {editing && <button type="button" role="menuitem" onClick={() => menuAct('delete')} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-[13px] text-[#DC2626] hover:bg-[#FEF2F2]"><Trash2 size={15} /> Supprimer</button>}
              </span>
            )}
          </span>
          <button type="button" disabled={!!busy} onClick={flip}
                  className="inline-flex h-11 items-center gap-2 rounded-xl border border-[#DCE5F3] bg-white px-4 text-[13.5px] font-semibold text-[#0B1C3F] hover:border-[#BFD3FF] disabled:opacity-60">
            {s.status === 'paused' ? <><Play size={16} /> Activer</> : <><Pause size={16} /> Désactiver</>}
          </button>
        </div>
      )}
    </header>
  );
  return (
    <div className="pb-10">
      {inactiveOn || welcomeOn || nrOn || refOn ? InactiveHeader : (
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-4">
          <button type="button" onClick={() => navigate('/dashboard/automations')} aria-label="Retour aux automatisations"
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><ArrowLeft size={18} /></button>
          <div>
            <h1 className="text-[25px] font-extrabold leading-tight text-[#0B1C3F]">{editing ? 'Modifier une automatisation' : geoNew ? 'Créer une automatisation géolocalisée' : avisNew ? "Automatiser une demande d'avis Google" : 'Créer une automatisation'}</h1>
            <p className="text-[13.5px] text-[#475569]">{editing ? 'Modifiez les paramètres de cette automatisation pour mettre à jour vos notifications.'
              : geoNew ? 'Attirez les personnes qui passent devant votre établissement avec une offre au bon moment.'
              : avisNew ? 'Encouragez vos clients satisfaits à laisser un avis sur votre fiche Google et améliorez votre visibilité.' : 'Une notification qui part toute seule, au bon moment, pour fidéliser vos clients.'}</p>
          </div>
        </div>
        {can && (
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={!!busy} onClick={() => save('draft')}
                    className="rounded-xl border border-[#BFD3FF] bg-white px-5 py-3 text-[13px] font-semibold text-[#1463FF] disabled:opacity-60">
              {busy === 'draft' ? 'Enregistrement…' : 'Enregistrer en brouillon'}</button>
            <button type="button" disabled={!!busy} onClick={() => save(s.status === 'paused' ? 'paused' : 'active')}
                    className="rounded-xl bg-[#1463FF] px-5 py-3 text-[13px] font-semibold text-white shadow-[0_14px_30px_-14px_rgba(20,99,255,.8)] disabled:opacity-60">
              {busy && busy !== 'draft' ? 'Enregistrement…' : editing ? 'Enregistrer les modifications' : createLabel}</button>
          </div>
        )}
      </header>
      )}

      <ol className="mb-5 flex items-start overflow-x-auto pb-1">
        {(welcomeOn ? W_STEPS : refOn ? R_STEPS : STEPS).map(([label0, sub], i, list) => {
          const n = i + 1;
          const label = n === 2 && s.scenario === 'geo' ? 'Zone de détection' : label0;
          const done = n < step;
          const subText = inactiveOn || welcomeOn || nrOn || refOn ? '' : n === 1 && done ? m.label : n === 2 && done ? triggerText() : n === 4 && done ? (tg.mode === 'all' ? 'Tous mes clients' : 'Ciblé') : sub;
          return (
            <li key={label} className="flex min-w-0 flex-1 items-start last:flex-none">
              <button type="button" onClick={() => (done ? go(n) : null)} disabled={!done && n !== step}
                      className="flex shrink-0 items-start gap-2 text-left">
                <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[14.5px] font-bold ${n === step ? 'bg-[#1463FF] text-white' : done ? 'bg-[#1463FF] text-white' : 'bg-[#EEF3FB] text-[#1463FF]'}`}>
                  {done ? <Check size={18} /> : n}</span>
                <span className={`hidden pt-1 sm:block ${n === step ? '' : ''}`}>
                  <span className={`block text-[13px] ${n === step ? 'font-bold text-[#1463FF]' : 'font-semibold text-[#0B1C3F]'}`}>{label}</span>
                  {subText && <span className="block max-w-[120px] truncate text-[11.5px] text-[#64748B]">{subText}</span>}
                </span>
              </button>
              {n < list.length && <span className={`mx-2 mt-4 h-[2px] min-w-[12px] flex-1 ${n < step ? 'bg-[#1463FF]' : 'bg-[#DCE5F3]'}`} />}
            </li>
          );
        })}
      </ol>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <fieldset disabled={!can} className="m-0 min-w-0 border-0 p-0">{content}</fieldset>
        <aside className="space-y-4">
          {welcomeOn && WPreview}
          {refOn && (Math.min(step, 3) === 3 ? RBoth : RPreview)}
          {nrOn && step === 3 && PreviewTabs(nrExtra, 'Aperçu du message')}
          {!welcomeOn && !nrOn && !refOn && (!inactiveOn || [1, 3].includes(step)) && <LockScreenPreview shop={page.shop} logo={page.logo_url} title={cur.title} body={cur.body} image={msg.image_url}
                             button={btn.enabled ? btn.label : ''} sample={preview?.sample} compact={step >= 4 && s.scenario !== 'google_review'}
                             bigImage={s.scenario === 'google_review' && step === 3}
                             note={s.scenario === 'geo' ? "Sur l'écran verrouillé, Apple affiche ce message près de votre établissement (Google Wallet, son propre texte). Un appui ouvre la carte, où le message et son bouton s'affichent." : undefined}
                             extra={s.scenario === 'near_reward' ? { visites_restantes: String(tr.visits_left || 1), visite_s: Number(tr.visits_left) > 1 ? 'visites' : 'visite' }
                               : s.scenario === 'tier_up' ? { palier: tr.condition === 'status' ? 'Or' : palierLabel(tr.condition, tiered ? cur.value : tr.threshold),
                                 'récompense': (tiered && cur.reward) || preview?.sample?.next_reward || 'votre récompense' }
                               : s.scenario === 'geo' ? { 'établissement': zoneSpots[0]?.name || page.shop }
                               : inactiveOn ? inPreviewExtra : {}} />}
          {nrOn && step === 1 && PreviewTabs(nrExtra)}
          {welcomeOn || refOn ? null : nrOn ? (step >= 2 ? nrPanel : Recap) : inactiveOn && step >= 2 ? inactivePanel : stepPanel}
          {Conseil}
          {BonnesPratiques}
          {NRPratiques}
        </aside>
      </div>

      {error && <p role="alert" className="mt-4 rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13px] font-medium text-[#B91C1C]">{error}</p>}
      <footer className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#E6EEFB] bg-white p-4">
        {inactiveOn || welcomeOn || nrOn || refOn ? (
          <span className="flex flex-1 flex-wrap items-center justify-between gap-3">
            <button type="button" onClick={() => navigate('/dashboard/automations')}
                    className="rounded-xl border border-[#BFD3FF] px-6 py-2.5 text-[13px] font-semibold text-[#1463FF]">Annuler</button>
            {step > 1 && <button type="button" onClick={() => go(step - 1)}
                    className="ml-auto inline-flex items-center gap-2 rounded-xl border border-[#BFD3FF] px-5 py-2.5 text-[13px] font-semibold text-[#1463FF]"><ArrowLeft size={17} /> Précédent</button>}
          </span>
        ) : (
        <button type="button" onClick={() => (step === 1 ? navigate('/dashboard/automations') : go(step - 1))}
                className="inline-flex items-center gap-2 rounded-xl border border-[#BFD3FF] px-5 py-2.5 text-[13px] font-semibold text-[#1463FF]">
          {step === 1 ? 'Annuler' : <><ArrowLeft size={17} /> Précédent</>}
        </button>
        )}
        {step < lastStep ? (
          <button type="button" onClick={next}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#1463FF] px-6 py-2.5 text-[13.5px] font-semibold text-white shadow-[0_14px_30px_-14px_rgba(20,99,255,.8)]">
            Suivant <ArrowRight size={17} />
          </button>
        ) : can && (
          <button type="button" disabled={!!busy} onClick={() => save(s.status === 'paused' ? 'paused' : 'active')}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#1463FF] px-7 py-3 text-[13.5px] font-semibold text-white shadow-[0_14px_30px_-14px_rgba(20,99,255,.8)] disabled:opacity-60">
            {busy ? <Loader2 size={17} className="animate-spin" /> : !welcomeOn && !nrOn && !refOn && <Check size={17} />} {editing && !nrOn && !refOn ? 'Enregistrer les modifications' : welcomeOn || nrOn || refOn ? "Enregistrer l'automatisation" : createLabel}
          </button>
        )}
      </footer>
    </div>
  );
}
