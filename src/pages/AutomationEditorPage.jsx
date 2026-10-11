import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft, ArrowRight, Check, Pencil, Info, CalendarDays, Clock, Users, Tags, Wallet, User, Smile, Image as ImageIcon,
  X, Loader2, Sparkles, Lightbulb, Power, MessageSquare, RefreshCw, MousePointerClick, MapPin, Euro, Repeat,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import WalletPreview from '../components/automations/WalletPreview';
import {
  ICONS, TONES, VAR_LABELS, DAY_NAMES, GENDERS, AGES, FREQS, SPENT, LAST_VISIT, EXAMPLES,
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
const TITLE_MAX = 60;
const BODY_MAX = 180;
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
  birthday: { offset_days: 0 }, tier_up: {}, welcome: {}, near_reward: { visits_left: 1 }, referral: { side: 'parrain' },
  geo: { cooldown_days: 7 }, google_review: { frequency: 'days', every_days: 30, stop_after_click: true },
  inactive: { days: 30, repeat: 'once', every_days: 30 },
};
const defaults = (sc, meta) => ({
  scenario: sc, name: meta?.label || '', status: 'active',
  trigger: { delay_value: 0, delay_unit: 'hours', ...(TRIGGERS[sc] || {}) },
  message: { title: meta?.title || '', body: meta?.body || '', image_url: null,
    button: { enabled: false, label: meta?.button || '', link_type: 'card', offer_id: null, url: '' } },
  targeting: { mode: 'all', segment: null, filters: { gender: 'all', age: 'all', frequency: 'all', spent: 'all', last_visit: 'all', stores: [] } },
  schedule: { days: 'all', weekdays: [0, 1, 2, 3, 4, 5, 6], hour: '10:00', smart: false,
    window: meta?.kind !== 'time', window_from: '09:00', window_to: '21:00' },
});

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
  <span className="mb-1.5 flex items-center justify-between text-[14px] font-semibold text-[#0B1C3F]">
    <span>{children}</span>{right && <span className="text-[12px] font-normal text-[#64748B]">{right}</span>}
  </span>
);
function Card({ n, title, sub, children }) {
  return (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <header className="mb-4 flex items-start gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[#1463FF] text-[18px] font-bold text-white">{n}</span>
        <div><h2 className="text-[21px] font-extrabold text-[#0B1C3F]">{title}</h2>
          {sub && <p className="text-[14px] text-[#475569]">{sub}</p>}</div>
      </header>
      {children}
    </section>
  );
}
function Option({ on, onClick, icon: I, title, sub, children, disabled }) {
  return (
    <div className={`rounded-2xl border p-4 transition ${on ? 'border-[#2F6BFF] bg-[#F5F8FF]' : 'border-[#E2E8F0] bg-white hover:border-[#BFD3FF]'}`}>
      <button type="button" disabled={disabled} onClick={onClick} className="flex w-full items-start gap-3 text-left">
        {I && <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><I size={22} /></span>}
        <span className="min-w-0 flex-1"><span className="block text-[15px] font-bold text-[#0B1C3F]">{title}</span>
          {sub && <span className="block text-[13px] text-[#64748B]">{sub}</span>}</span>
        <Radio on={on} />
      </button>
      {on && children && <div className="mt-3">{children}</div>}
    </div>
  );
}
function Select({ value, onChange, options, label, disabled }) {
  return (
    <select aria-label={label} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}
            className={`${field} appearance-none bg-[length:14px] bg-[right_12px_center] bg-no-repeat pr-9`}
            style={{ backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%230B1C3F' stroke-width='2.5'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")" }}>
      {options.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
    </select>
  );
}
function Num({ value, onChange, min, max, label, disabled }) {
  return (
    <input inputMode="numeric" aria-label={label} disabled={disabled} value={value ?? ''}
           onChange={(e) => onChange(e.target.value.replace(/\D/g, '').slice(0, 3))}
           onBlur={() => { const n = Number(value); if (value !== '' && Number.isFinite(n)) onChange(String(Math.min(max, Math.max(min, n)))); }}
           className={`${field} w-24 text-center`} />
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
  const titleRef = useRef(null);
  const bodyRef = useRef(null);
  const fileRef = useRef(null);
  const lastFocus = useRef('body');

  useEffect(() => {
    ownerAPI.automations().then(({ data }) => {
      setPage(data);
      const meta = Object.fromEntries(data.scenarios.map((x) => [x.key, x]));
      if (editing) {
        const row = data.rows.find((r) => r.id === id);
        if (!row) { setError('Automatisation introuvable.'); return; }
        const d = defaults(row.scenario, meta[row.scenario]);
        setS({ ...d, name: row.name, status: row.status, trigger: { ...d.trigger, ...row.trigger },
          message: { ...d.message, ...row.message, button: { ...d.message.button, ...(row.message?.button || {}), url: row.message?.button?.url || '' } },
          targeting: { ...d.targeting, ...row.targeting, filters: { ...d.targeting.filters, ...(row.targeting?.filters || {}) } },
          schedule: { ...d.schedule, ...row.schedule, hour: row.schedule?.hour || '10:00' } });
        const q = new URLSearchParams(location.search);
        if (q.get('step')) setStep(Math.min(6, Math.max(1, Number(q.get('step')) || 1)));
      } else {
        const q = new URLSearchParams(location.search);
        const sc = meta[q.get('scenario')] ? q.get('scenario') : 'birthday';
        const d = defaults(sc, meta[sc]);
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
  const timed = m?.kind === 'time';
  const set = (patch) => setS((o) => ({ ...o, ...patch }));
  const setIn = (key, patch) => setS((o) => ({ ...o, [key]: { ...o[key], ...patch } }));
  const setMsg = (patch) => setS((o) => ({ ...o, message: { ...o.message, ...patch } }));
  const setBtn = (patch) => setS((o) => ({ ...o, message: { ...o.message, button: { ...o.message.button, ...patch } } }));
  const setF = (patch) => setS((o) => ({ ...o, targeting: { ...o.targeting, filters: { ...o.targeting.filters, ...patch } } }));

  // ---- the live count (step 4) ---------------------------------------------------
  const tKey = s ? JSON.stringify([s.scenario, s.targeting]) : '';
  useEffect(() => {
    if (!s) return undefined;
    let alive = true;
    const t0 = setTimeout(() => {
      if (s.targeting.mode === 'segment' && !s.targeting.segment) { setPreview({ count: 0, sample: preview?.sample }); return; }
      ownerAPI.automationPreview({ scenario: s.scenario, targeting: s.targeting })
        .then(({ data }) => { if (alive) setPreview(data); }).catch(() => { if (alive) setPreview(null); });
    }, 250);
    return () => { alive = false; clearTimeout(t0); };
  }, [tKey]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error && !s) return <p role="alert" className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[14px] text-[#B91C1C]">{error}</p>;
  if (!s || !page || !m) {
    return <div className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[14px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</div>;
  }

  const tr = s.trigger;
  const msg = s.message;
  const btn = msg.button;
  const tg = s.targeting;
  const f = tg.filters;
  const sc = s.schedule;
  const variables = m.variables || [];

  // ---- the summary lines -----------------------------------------------------------
  const triggerText = () => {
    if (s.scenario === 'birthday') {
      const o = Number(tr.offset_days || 0);
      return o === 0 ? "Date d'anniversaire (le jour même)" : o < 0 ? `${-o} jour${o < -1 ? 's' : ''} avant l'anniversaire` : `${o} jour${o > 1 ? 's' : ''} après l'anniversaire`;
    }
    if (s.scenario === 'near_reward') return `À ${tr.visits_left || 1} visite${Number(tr.visits_left) > 1 ? 's' : ''} de la récompense`;
    if (s.scenario === 'inactive') return `Après ${tr.days || 30} jours sans visite${tr.repeat === 'every' ? `, puis tous les ${tr.every_days || 30} j` : ''}`;
    if (s.scenario === 'referral') return `Récompense de parrainage gagnée · ${tr.side === 'filleul' ? 'au filleul' : 'au parrain'}`;
    if (s.scenario === 'google_review') return tr.frequency === 'every_scan' ? 'Après chaque visite' : tr.frequency === 'once' ? 'Après une visite (une seule fois)' : `Après une visite (au plus tous les ${tr.every_days || 30} j)`;
    if (s.scenario === 'geo') return `Entrée dans la zone (au plus tous les ${tr.cooldown_days || 7} j)`;
    return m.trigger_label;
  };
  const delayText = () => (!timed && s.scenario !== 'geo' && Number(tr.delay_value) > 0
    ? ` · ${tr.delay_value} ${{ minutes: 'min', hours: 'h', days: 'j' }[tr.delay_unit] || 'h'} après` : '');
  const targetText = () => {
    const base = tg.mode === 'wallet' ? 'Clients avec carte Wallet'
      : tg.mode === 'segment' ? `Segment : ${(page.segments.find((x) => x.key === tg.segment) || {}).label || '—'}` : 'Tous mes clients';
    const extra = [f.gender !== 'all' && GENDERS.find((x) => x[0] === f.gender)?.[1], f.age !== 'all' && AGES.find((x) => x[0] === f.age)?.[1],
      f.frequency !== 'all' && FREQS.find((x) => x[0] === f.frequency)?.[1], f.spent !== 'all' && SPENT.find((x) => x[0] === f.spent)?.[1],
      f.last_visit !== 'all' && `Dernière visite : ${LAST_VISIT.find((x) => x[0] === f.last_visit)?.[1]}`,
      f.stores?.length && page.stores.filter((x) => f.stores.includes(x.id)).map((x) => x.name).join(', ')].filter(Boolean);
    return tg.mode === 'all' ? base : [base, ...extra].join(' · ');
  };
  const daysText = () => (sc.days === 'all' ? 'Tous les jours' : sc.days === 'weekdays' ? 'Jours ouvrés'
    : sc.weekdays.map((d) => DAY_NAMES[d]).join(', ') || '—');
  const planText = () => (timed
    ? `${daysText()} à ${sc.smart && page.best_slot ? `${page.best_slot.from} (plage intelligente)` : sc.hour}`
    : `${daysText()} · ${sc.window ? `entre ${sc.window_from} et ${sc.window_to}` : 'immédiat'}`);

  // ---- the checks (the server repeats them) --------------------------------------
  const problem = (n) => {
    if (n === 1 && !s.scenario) return 'Choisissez un scénario.';
    if (n === 2) {
      const num = (v, lo, hi, l) => (!Number.isInteger(Number(v)) || Number(v) < lo || Number(v) > hi ? `${l} : entre ${lo} et ${hi}.` : '');
      if (s.scenario === 'birthday') return num(Math.abs(Number(tr.offset_days || 0)), 0, 30, 'Jours');
      if (s.scenario === 'near_reward') return num(tr.visits_left, 1, 50, 'Visites avant la récompense');
      if (s.scenario === 'inactive') return num(tr.days, 7, 365, 'Jours sans visite') || (tr.repeat === 'every' ? num(tr.every_days, 7, 365, 'Répéter tous les') : '');
      if (s.scenario === 'geo') return num(tr.cooldown_days, 1, 90, 'Délai entre deux messages');
      if (s.scenario === 'google_review' && tr.frequency === 'days') return num(tr.every_days, 1, 365, 'Fréquence');
      if (!timed && s.scenario !== 'geo') return num(tr.delay_value || 0, 0, 365, "Délai d'envoi");
    }
    if (n === 3) {
      if (!msg.title.trim()) return 'Écrivez le titre de la notification.';
      if (!msg.body.trim()) return 'Écrivez le message.';
      if (msg.title.length > TITLE_MAX) return `Titre : ${TITLE_MAX} caractères au maximum.`;
      if (msg.body.length > BODY_MAX) return `Message : ${BODY_MAX} caractères au maximum.`;
      if (btn.enabled) {
        if (!btn.label.trim()) return 'Indiquez le texte du bouton.';
        if (btn.link_type === 'url' && !LINK_RE.test(fullLink(btn.url))) return 'Lien invalide : saisissez une adresse web, par exemple https://monsite.fr.';
        if (btn.link_type === 'offer' && !btn.offer_id) return 'Choisissez une offre.';
        if (btn.link_type === 'google_review' && !page.google_review_ready) return "Ajoutez d'abord votre lien Google (Insights › Avis Google).";
      }
    }
    if (n === 4) {
      if (tg.mode === 'segment' && !tg.segment) return 'Choisissez un segment.';
    }
    if (n === 5) {
      if (sc.days === 'specific' && !sc.weekdays.length) return "Cochez au moins un jour d'envoi.";
      if (!timed && sc.window && sc.window_to <= sc.window_from) return 'La fin de la plage horaire doit être après son début.';
    }
    return '';
  };
  const go = (n) => { setError(''); setStep(n); window.scrollTo({ top: 0, behavior: 'smooth' }); };
  const next = () => { const p = problem(step); if (p) { setError(p); return; } go(step + 1); };

  const body = (status) => ({
    scenario: s.scenario, name: s.name, status,
    trigger: { ...tr, offset_days: Number(tr.offset_days || 0) },
    message: { ...msg, title: msg.title.trim(), body: msg.body.trim(),
      button: { ...btn, url: btn.link_type === 'url' ? fullLink(btn.url) : null, offer_id: btn.link_type === 'offer' ? btn.offer_id : null } },
    targeting: tg.mode === 'all' ? { mode: 'all', segment: null, filters: { gender: 'all', age: 'all', frequency: 'all', spent: 'all', last_visit: 'all', stores: [] } } : tg,
    schedule: { ...sc, hour: timed ? sc.hour : null },
  });
  const save = async (status) => {
    if (status !== 'draft') {
      for (let n = 1; n <= 5; n += 1) { const p = problem(n); if (p) { setError(p); setStep(n); return; } }
    }
    setBusy(status); setError('');
    try {
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
    const cur = msg[which] || '';
    const max = which === 'title' ? TITLE_MAX : BODY_MAX;
    const a = el?.selectionStart ?? cur.length;
    const b = el?.selectionEnd ?? cur.length;
    const nextVal = (cur.slice(0, a) + text + cur.slice(b)).slice(0, max);
    setMsg({ [which]: nextVal });
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
      {editing && <p className="mb-3 flex items-center gap-2 rounded-xl bg-[#F1F6FF] px-3 py-2 text-[13px] text-[#334155]"><Info size={15} className="text-[#1463FF]" /> Le scénario d'une automatisation existante ne change pas : dupliquez-la ou créez-en une nouvelle.</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        {page.scenarios.map((x) => {
          const I = ICONS[x.icon] || MessageSquare;
          const [bg, fg] = TONES[x.tone] || TONES.blue;
          const on = s.scenario === x.key;
          return (
            <button key={x.key} type="button" disabled={editing && !on}
                    onClick={() => { if (!editing && !on) setS({ ...defaults(x.key, x), name: x.label }); }}
                    className={`flex items-start gap-3 rounded-2xl border p-4 text-left transition disabled:opacity-50 ${on ? 'border-[#2F6BFF] bg-[#F5F8FF] shadow-[0_0_0_1px_#2F6BFF]' : 'border-[#E2E8F0] bg-white hover:border-[#BFD3FF]'}`}>
              <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl" style={{ background: bg, color: fg }}><I size={24} /></span>
              <span className="min-w-0 flex-1"><span className="block text-[15.5px] font-bold text-[#0B1C3F]">{x.label}</span>
                <span className="block text-[13px] leading-snug text-[#64748B]">{x.sub}</span></span>
              <Radio on={on} />
            </button>
          );
        })}
      </div>
      <label className="mt-4 block"><Label right={`${s.name.length}/60`}>Nom de l'automatisation</Label>
        <input className={field} value={s.name} maxLength={60} onChange={(e) => set({ name: e.target.value })} placeholder={m.label} /></label>
    </Card>
  );

  const delayBlock = !timed && s.scenario !== 'geo' && (
    <div className="mt-3 flex flex-wrap items-center gap-3 rounded-2xl border border-[#E2E8F0] p-4">
      <span className="flex items-center gap-2 text-[14px] font-semibold text-[#0B1C3F]">Délai d'envoi <span className="font-normal text-[#64748B]">(optionnel)</span>
        <span title="Attendre un peu après l'événement avant d'envoyer (ex. 2 h après la visite pour un avis Google)."><Info size={14} className="text-[#64748B]" /></span></span>
      <span className="flex flex-1 items-center justify-end gap-2">
        <Num value={tr.delay_value ?? 0} min={0} max={365} label="Délai d'envoi" onChange={(v) => setIn('trigger', { delay_value: v })} />
        <span className="w-36"><Select label="Unité du délai" value={tr.delay_unit || 'hours'} onChange={(v) => setIn('trigger', { delay_unit: v })}
                options={[['minutes', 'minute(s)'], ['hours', 'heure(s)'], ['days', 'jour(s)']]} /></span>
        <span className="text-[13px] text-[#64748B]">{Number(tr.delay_value) > 0 ? 'après' : 'Immédiat'}</span>
      </span>
    </div>
  );
  const Step2 = (
    <Card n={2} title="Déclencheur" sub="Définissez quand cette notification doit être envoyée.">
      <div className="mb-3 flex items-start gap-3 rounded-2xl border border-[#2F6BFF] bg-[#F5F8FF] p-4">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white text-[#1463FF]"><ScIcon size={22} /></span>
        <span><span className="block text-[15.5px] font-bold text-[#0B1C3F]">{m.trigger_label}</span>
          <span className="text-[13.5px] text-[#475569]">{{
            birthday: "Le message part automatiquement autour de la date d'anniversaire du client.",
            tier_up: 'Envoyé quand une visite fait passer le client à un palier supérieur (Argent, Or, VIP).',
            welcome: "Envoyé à chaque nouveau client, juste après son inscription.",
            near_reward: 'Envoyé après la visite qui laisse exactement X visites avant la récompense — une fois par carte.',
            referral: 'Envoyé quand des points de parrainage sont gagnés (visite du filleul).',
            geo: "Envoyé quand la carte du client voit qu'il passe près de l'un de vos établissements.",
            google_review: 'Envoyé après une visite, pour demander un avis sur votre page Google.',
            inactive: "Envoyé aux clients qui ne sont pas venus depuis X jours.",
          }[s.scenario]}</span></span>
      </div>
      {s.scenario === 'birthday' && (
        <div className="space-y-3">
          <Option on={Number(tr.offset_days) === 0} onClick={() => setIn('trigger', { offset_days: 0 })} icon={CalendarDays} title="Le jour même" sub="Le jour de l'anniversaire du client.">
            <p className="flex items-center gap-2 rounded-xl bg-[#EEF4FF] px-3 py-2 text-[13px] text-[#1E3A8A]"><Repeat size={14} /> Répétition annuelle : envoyée automatiquement tous les ans à la même date.</p>
          </Option>
          <Option on={Number(tr.offset_days) < 0} onClick={() => setIn('trigger', { offset_days: -3 })} icon={Clock} title="X jours avant l'anniversaire" sub="Envoyez le message quelques jours avant la date d'anniversaire.">
            <span className="flex items-center gap-2 text-[14px]"><Num value={String(Math.abs(Number(tr.offset_days)))} min={1} max={30} label="Jours avant" onChange={(v) => setIn('trigger', { offset_days: -Math.max(1, Number(v) || 1) })} /> jour(s) avant</span>
          </Option>
          <Option on={Number(tr.offset_days) > 0} onClick={() => setIn('trigger', { offset_days: 3 })} icon={CalendarDays} title="X jours après l'anniversaire" sub="Envoyez le message quelques jours après la date d'anniversaire.">
            <span className="flex items-center gap-2 text-[14px]"><Num value={String(Math.abs(Number(tr.offset_days)))} min={1} max={30} label="Jours après" onChange={(v) => setIn('trigger', { offset_days: Math.max(1, Number(v) || 1) })} /> jour(s) après</span>
          </Option>
        </div>
      )}
      {s.scenario === 'near_reward' && (
        <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-[#E2E8F0] p-4 text-[14px]">
          <span className="font-semibold text-[#0B1C3F]">Envoyer quand il reste</span>
          <Num value={tr.visits_left} min={1} max={50} label="Visites restantes" onChange={(v) => setIn('trigger', { visits_left: v })} />
          <span>visite(s) avant la récompense</span>
        </div>
      )}
      {s.scenario === 'inactive' && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-[#E2E8F0] p-4 text-[14px]">
            <span className="font-semibold text-[#0B1C3F]">Aucune visite depuis</span>
            <Num value={tr.days} min={7} max={365} label="Jours sans visite" onChange={(v) => setIn('trigger', { days: v })} /> <span>jours</span>
          </div>
          <Option on={tr.repeat !== 'every'} onClick={() => setIn('trigger', { repeat: 'once' })} icon={RefreshCw} title="Une seule fois par absence" sub="Un message, puis plus rien tant que le client ne revient pas." />
          <Option on={tr.repeat === 'every'} onClick={() => setIn('trigger', { repeat: 'every' })} icon={Repeat} title="Relancer régulièrement" sub="Tant que le client ne revient pas.">
            <span className="flex items-center gap-2 text-[14px]">Tous les <Num value={tr.every_days} min={7} max={365} label="Répéter tous les" onChange={(v) => setIn('trigger', { every_days: v })} /> jours</span>
          </Option>
        </div>
      )}
      {s.scenario === 'referral' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Option on={tr.side !== 'filleul'} onClick={() => setIn('trigger', { side: 'parrain' })} icon={Users} title="Au parrain" sub="Celui qui a invité : son ami est venu, il gagne ses points." />
          <Option on={tr.side === 'filleul'} onClick={() => setIn('trigger', { side: 'filleul' })} icon={User} title="Au filleul" sub="L'ami invité : il gagne ses points grâce à son parrain." />
        </div>
      )}
      {s.scenario === 'geo' && (
        <div className="space-y-3">
          {!page.geo_ready && <p className="rounded-xl bg-[#FFF7ED] px-3 py-2 text-[13px] text-[#9A3412]">Le rappel de proximité est désactivé : activez-le dans Paramètres › Établissement pour que ce message parte.</p>}
          <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-[#E2E8F0] p-4 text-[14px]">
            <span className="font-semibold text-[#0B1C3F]">Au plus un message tous les</span>
            <Num value={tr.cooldown_days} min={1} max={90} label="Délai entre deux messages" onChange={(v) => setIn('trigger', { cooldown_days: v })} /> <span>jours par client</span>
          </div>
        </div>
      )}
      {s.scenario === 'google_review' && (
        <div className="space-y-3">
          {!page.google_review_ready && <p className="rounded-xl bg-[#FFF7ED] px-3 py-2 text-[13px] text-[#9A3412]">Votre lien Google n'est pas encore activé (Insights › Avis Google) : aucune demande ne part sans lui.</p>}
          <Option on={tr.frequency === 'every_scan'} onClick={() => setIn('trigger', { frequency: 'every_scan' })} title="Après chaque visite" />
          <Option on={tr.frequency === 'days'} onClick={() => setIn('trigger', { frequency: 'days' })} title="Au plus une fois tous les X jours">
            <span className="flex items-center gap-2 text-[14px]">Tous les <Num value={tr.every_days} min={1} max={365} label="Tous les X jours" onChange={(v) => setIn('trigger', { every_days: v })} /> jours</span>
          </Option>
          <Option on={tr.frequency === 'once'} onClick={() => setIn('trigger', { frequency: 'once' })} title="Une seule fois par client" />
          <div className="flex items-center justify-between rounded-2xl border border-[#E2E8F0] p-4">
            <span><span className="block text-[14px] font-semibold text-[#0B1C3F]">Arrêter après un clic</span>
              <span className="text-[13px] text-[#64748B]">Ne plus demander à un client qui a déjà ouvert votre page d'avis.</span></span>
            <Toggle label="Arrêter après un clic" on={tr.stop_after_click !== false} onChange={(v) => setIn('trigger', { stop_after_click: v })} />
          </div>
        </div>
      )}
      {delayBlock}
    </Card>
  );

  const Step3 = (
    <Card n={3} title="Message" sub="Personnalisez le contenu de votre notification.">
      <p className="mb-3 inline-flex rounded-xl border border-[#2F6BFF] bg-[#F5F8FF] px-4 py-2 text-[14px] font-semibold text-[#1463FF]">Notification Wallet</p>
      <label className="block"><Label right={`${msg.title.length}/${TITLE_MAX}`}>Titre de la notification</Label>
        <input ref={titleRef} className={field} value={msg.title} maxLength={TITLE_MAX} onFocus={() => { lastFocus.current = 'title'; }}
               onChange={(e) => setMsg({ title: e.target.value })} placeholder={m.title} /></label>
      <label className="mt-3 block"><Label right={`${msg.body.length}/${BODY_MAX}`}>Message</Label>
        <textarea ref={bodyRef} className={`${field} min-h-[96px] resize-y`} value={msg.body} maxLength={BODY_MAX}
                  onFocus={() => { lastFocus.current = 'body'; }} onChange={(e) => setMsg({ body: e.target.value })} placeholder={m.body} /></label>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="text-[13px] text-[#475569]">Variables disponibles :</span>
        {variables.map((v) => (
          <button key={v} type="button" title={VAR_LABELS[v] || v} onClick={() => insert(`{${v}}`)}
                  className="rounded-lg bg-[#EEF4FF] px-2.5 py-1 text-[12.5px] font-semibold text-[#1D4ED8] hover:bg-[#E0EAFF]">{`{${v}}`}</button>
        ))}
        <span className="relative">
          <button type="button" onClick={() => setEmoji((x) => (x ? '' : 'open'))} aria-label="Ajouter un emoji"
                  className="rounded-lg border border-[#E2E8F0] p-1.5 text-[#475569] hover:bg-[#F8FAFC]"><Smile size={16} /></button>
          {emoji && (
            <span className="absolute left-0 top-9 z-20 grid w-64 grid-cols-8 gap-1 rounded-xl border border-[#E2E8F0] bg-white p-2 shadow-xl">
              {EMOJIS.map((e) => <button key={e} type="button" className="rounded p-1 text-[18px] hover:bg-[#F1F5F9]" onClick={() => { insert(e); setEmoji(''); }}>{e}</button>)}
            </span>
          )}
        </span>
      </div>
      <div className="mt-4">
        <Label>Ajouter une image <span className="font-normal text-[#64748B]">(optionnel)</span></Label>
        <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={pickImage} />
        {msg.image_url ? (
          <span className="flex items-center gap-3 rounded-xl border border-[#D9E2F2] p-2">
            <img src={msg.image_url} alt="" className="h-14 w-14 rounded-lg object-cover" />
            <span className="flex-1 text-[13.5px] text-[#0B1C3F]">Image ajoutée</span>
            <button type="button" onClick={() => setMsg({ image_url: null })} className="rounded-lg p-2 text-[#64748B] hover:bg-[#F1F5F9]" aria-label="Retirer l'image"><X size={16} /></button>
          </span>
        ) : (
          <button type="button" onClick={() => fileRef.current?.click()}
                  className="flex w-full items-center justify-center gap-3 rounded-xl border border-dashed border-[#BFD3FF] bg-[#F8FAFF] py-5 text-[#1463FF]">
            <ImageIcon size={22} /><span className="text-left"><span className="block text-[14px] font-semibold">Ajouter une image</span>
              <span className="text-[12px] text-[#64748B]">PNG, JPG (max 2 Mo)</span></span>
          </button>
        )}
      </div>
      <div className="mt-4 rounded-2xl border border-[#E6EEFB] p-4">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#F1EAFF] text-[#7C3AED]"><MousePointerClick size={20} /></span>
          <span className="min-w-0 flex-1"><span className="block text-[15px] font-bold text-[#0B1C3F]">Bouton d'action <span className="font-normal text-[#64748B]">(optionnel)</span></span>
            <span className="text-[13px] text-[#64748B]">Un bouton qui ouvre directement le lien de votre choix : une offre, la carte, votre page d'avis, votre site…</span></span>
          <Toggle label="Bouton d'action" on={btn.enabled} onChange={(v) => setBtn({ enabled: v })} />
        </div>
        {btn.enabled && (
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="block"><Label right={`${btn.label.length}/${BUTTON_MAX}`}>Texte du bouton</Label>
              <input className={field} value={btn.label} maxLength={BUTTON_MAX} onChange={(e) => setBtn({ label: e.target.value })} placeholder="Découvrir ma surprise" /></label>
            <label className="block"><Label>Lien</Label>
              <Select label="Lien du bouton" value={btn.link_type} onChange={(v) => setBtn({ link_type: v })}
                      options={[['card', 'La carte du client / ses récompenses'], ['offer', 'Une de vos offres'], ['google_review', "Votre page d'avis Google"], ['url', 'Un lien personnalisé']]} /></label>
            {btn.link_type === 'offer' && (
              <label className="block sm:col-span-2"><Label>Offre</Label>
                {page.offers.length ? (
                  <Select label="Offre" value={btn.offer_id || ''} onChange={(v) => setBtn({ offer_id: v || null })}
                          options={[['', 'Sélectionner une offre'], ...page.offers.map((o) => [o.id, o.terms ? `${o.name} — ${o.terms}` : o.name])]} />
                ) : <p className="rounded-xl bg-[#FFF7ED] px-3 py-2 text-[13px] text-[#9A3412]">Aucune offre en cours : créez-en une dans Campagnes, ou choisissez un autre lien.</p>}
              </label>
            )}
            {btn.link_type === 'url' && (
              <label className="block sm:col-span-2"><Label>Adresse du lien</Label>
                <input className={field} value={btn.url || ''} onChange={(e) => setBtn({ url: e.target.value })} placeholder="monsite.fr/reservation" inputMode="url" /></label>
            )}
            {btn.link_type === 'google_review' && !page.google_review_ready && (
              <p className="rounded-xl bg-[#FFF7ED] px-3 py-2 text-[13px] text-[#9A3412] sm:col-span-2">Ajoutez d'abord votre lien Google dans Insights › Avis Google.</p>
            )}
          </div>
        )}
      </div>
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
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><I size={20} /></span>
            <span className="min-w-0 flex-1"><span className="block text-[14.5px] font-bold text-[#0B1C3F]">{l}</span><span className="text-[12.5px] text-[#64748B]">{h}</span></span>
            <Radio on={tg.mode === k} />
          </button>
        ))}
      </div>
      {tg.mode === 'segment' && (
        <div className="mt-3 max-h-[220px] space-y-1.5 overflow-y-auto">
          {page.segments.map((x) => (
            <label key={x.key} className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 ${tg.segment === x.key ? 'border-[#2F6BFF] bg-[#F1F6FF]' : 'border-[#E2E8F0]'}`}>
              <input type="radio" name="au-seg" checked={tg.segment === x.key} onChange={() => setIn('targeting', { segment: x.key })} className="accent-[#1463FF]" />
              <span className="flex-1"><span className="block text-[14px] font-semibold text-[#0B1C3F]">{x.label}</span><span className="text-[12px] text-[#64748B]">{x.hint}</span></span>
              <span className="text-[13px] font-semibold tabular-nums text-[#475569]">{(x.count ?? 0).toLocaleString('fr-FR')}</span>
            </label>
          ))}
        </div>
      )}
      <div className="mt-4 flex items-center gap-3 rounded-2xl bg-[#F1F6FF] p-4">
        <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#1463FF] text-white"><Users size={18} /></span>
        <span className="flex-1 text-[14px] font-semibold text-[#0B1C3F]">Clients ciblés aujourd'hui</span>
        <span className="text-[24px] font-extrabold tabular-nums text-[#1463FF]">{preview ? preview.count.toLocaleString('fr-FR') : '…'}</span>
      </div>
      {tg.mode !== 'all' && (
        <div className="mt-4 rounded-2xl bg-[#F8FAFC] p-4">
          <p className="text-[15px] font-bold text-[#0B1C3F]">Filtres optionnels</p>
          <p className="mb-3 text-[13px] text-[#64748B]">Affinez votre ciblage en ajoutant des critères (optionnel).</p>
          <div className="divide-y divide-[#EEF2F7] rounded-xl border border-[#E6EEFB] bg-white">
            {[[User, 'Genre', <Select key="g" label="Genre" value={f.gender} onChange={(v) => setF({ gender: v })} options={GENDERS} />,
              'Renseigné par le client à son inscription.'],
              [Users, 'Âge', <Select key="a" label="Âge" value={f.age} onChange={(v) => setF({ age: v })} options={AGES} />],
              [CalendarDays, 'Fréquence de visite', <Select key="f" label="Fréquence de visite" value={f.frequency} onChange={(v) => setF({ frequency: v })} options={FREQS} />],
              [Euro, 'Montant total des achats', <Select key="s" label="Montant total des achats" value={f.spent} onChange={(v) => setF({ spent: v })} options={SPENT} />],
              [Clock, 'Dernière visite', <Select key="l" label="Dernière visite" value={f.last_visit} onChange={(v) => setF({ last_visit: v })} options={LAST_VISIT} />],
              ...(page.stores.length > 1 ? [[MapPin, 'Localisation', <Select key="st" label="Localisation" value={f.stores[0] || ''}
                onChange={(v) => setF({ stores: v ? [v] : [] })} options={[['', 'Tous mes établissements'], ...page.stores.map((x) => [x.id, x.name])]} />]] : []),
            ].map(([I, l, ctl, hint]) => (
              <div key={l} className="grid items-center gap-2 px-4 py-3 sm:grid-cols-[1fr_1.1fr]">
                <span className="flex items-center gap-3 text-[14px] text-[#0B1C3F]"><I size={18} className="text-[#475569]" />
                  <span>{l}{hint && <span className="block text-[11.5px] text-[#94A3B8]">{hint}</span>}</span></span>
                {ctl}
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );

  const Step5 = (
    <Card n={5} title="Planification" sub="Définissez quand et comment envoyer cette automatisation.">
      <div className="rounded-2xl border border-[#E6EEFB] p-4">
        <p className="flex items-center gap-3 text-[15px] font-bold text-[#0B1C3F]"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><CalendarDays size={20} /></span>
          <span>Période d'envoi<span className="block text-[13px] font-normal text-[#64748B]">Choisissez les jours{timed ? " et l'heure" : ' et les horaires'} d'envoi.</span></span></p>
        <div className="mt-3 flex flex-wrap gap-4">
          {[['all', 'Tous les jours'], ['specific', 'Jours spécifiques'], ['weekdays', 'Jours ouvrés uniquement']].map(([k, l]) => (
            <button key={k} type="button" onClick={() => setIn('schedule', { days: k })} className="flex items-center gap-2 text-[14px] text-[#0B1C3F]">
              <Radio on={sc.days === k} /> {l}
            </button>
          ))}
        </div>
        {sc.days === 'specific' && (
          <div className="mt-3 flex flex-wrap gap-2">
            {DAY_NAMES.map((d, i) => {
              const on = sc.weekdays.includes(i);
              return (
                <button key={d} type="button" onClick={() => setIn('schedule', { weekdays: on ? sc.weekdays.filter((x) => x !== i) : [...sc.weekdays, i].sort() })}
                        className={`rounded-xl border px-3.5 py-2 text-[13.5px] font-semibold ${on ? 'border-[#2F6BFF] bg-[#1463FF] text-white' : 'border-[#E2E8F0] text-[#334155]'}`}>{d}</button>
              );
            })}
          </div>
        )}
        {timed ? (
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="block"><Label>Heure d'envoi</Label>
              <Select label="Heure d'envoi" value={sc.hour} disabled={sc.smart && Boolean(page.best_slot)} onChange={(v) => setIn('schedule', { hour: v })} options={HOURS.map((h) => [h, h])} /></label>
            <label className="block"><Label>Fuseau horaire</Label>
              <input className={field} value="(GMT+1) Paris" disabled readOnly /></label>
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            <div className="flex items-center justify-between gap-3 rounded-xl border border-[#E2E8F0] p-3">
              <span><span className="block text-[14px] font-semibold text-[#0B1C3F]">Envoi immédiat, dans une plage horaire</span>
                <span className="text-[12.5px] text-[#64748B]">Un événement en dehors de la plage (la nuit…) attend son ouverture.</span></span>
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
      <div className="mt-3 rounded-2xl border border-[#E6EEFB] p-4">
        <p className="flex items-center gap-3 text-[15px] font-bold text-[#0B1C3F]"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><RefreshCw size={20} /></span>
          <span>Fréquence<span className="block text-[13px] font-normal text-[#64748B]">{{
            birthday: 'Une fois par an, pour chaque client (répétition annuelle).',
            tier_up: 'À chaque nouveau palier atteint.',
            welcome: 'Une seule fois par client, à son inscription.',
            near_reward: 'Une fois par carte de fidélité.',
            referral: 'À chaque récompense de parrainage gagnée.',
            geo: `Au plus une fois tous les ${tr.cooldown_days || 7} jours par client.`,
            google_review: tr.frequency === 'every_scan' ? 'Après chaque visite.' : tr.frequency === 'once' ? 'Une seule fois par client.' : `Au plus une fois tous les ${tr.every_days || 30} jours.`,
            inactive: tr.repeat === 'every' ? `Tous les ${tr.every_days || 30} jours tant que le client ne revient pas.` : 'Une fois par absence.',
          }[s.scenario]}</span></span></p>
      </div>
      {timed && (
        <div className="mt-3 rounded-2xl border border-[#E6EEFB] p-4">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#F1EAFF] text-[#7C3AED]"><Sparkles size={20} /></span>
            <span className="min-w-0 flex-1"><span className="block text-[15px] font-bold text-[#0B1C3F]">Plage d'envoi intelligente <span className="font-normal text-[#64748B]">(recommandé)</span></span>
              <span className="text-[13px] text-[#64748B]">FidClic envoie le message au moment de la journée où vos clients viennent le plus.</span></span>
            <Toggle label="Plage d'envoi intelligente" disabled={!page.best_slot} on={sc.smart && Boolean(page.best_slot)} onChange={(v) => setIn('schedule', { smart: v })} />
          </div>
          <p className="mt-3 flex items-start gap-2 rounded-xl bg-[#F1F6FF] px-3 py-2 text-[13px] text-[#334155]"><Info size={15} className="mt-0.5 shrink-0 text-[#1463FF]" />
            {page.best_slot ? `D'après vos visites, le créneau ${page.best_slot.label} est celui où vos clients viennent le plus.`
              : "Pas encore assez de visites pour trouver votre meilleur créneau : l'heure choisie s'applique."}</p>
        </div>
      )}
      {!page.tick && (
        <p className="mt-3 flex items-start gap-2 text-[12px] text-[#94A3B8]"><Info size={13} className="mt-0.5 shrink-0" />
          L'envoi à l'heure exacte arrive avec l'envoi programmé toutes les 15 minutes ; en attendant, les messages du jour partent avec l'envoi quotidien du matin.</p>
      )}
    </Card>
  );

  const Row = ({ icon: I, title, sub, children, n }) => (
    <div className="flex flex-wrap items-start gap-3 rounded-2xl border border-[#E6EEFB] p-4 sm:flex-nowrap">
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><I size={22} /></span>
      <span className="min-w-0 flex-1 sm:w-40 sm:flex-none"><span className="block text-[15px] font-bold text-[#0B1C3F]">{title}</span><span className="text-[13px] text-[#64748B]">{sub}</span></span>
      <span className="order-last w-full min-w-0 break-words text-[13.5px] text-[#334155] sm:order-none sm:w-auto sm:flex-1">{children}</span>
      {can && <button type="button" onClick={() => go(n)} aria-label={`Modifier : ${title}`} className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-[#BFD3FF] px-3 py-2 text-[13.5px] font-semibold text-[#1463FF]"><Pencil size={14} /> <span className="hidden sm:inline">Modifier</span></button>}
    </div>
  );
  const Step6 = (
    <Card n={6} title="Résumé" sub="Vérifiez les paramètres de votre automatisation avant de l'enregistrer.">
      <div className="space-y-3">
        <Row n={1} icon={ScIcon} title="Scénario" sub={m.label}>{s.name || m.label}<span className="block text-[#64748B]">{m.sub}</span></Row>
        <Row n={2} icon={CalendarDays} title="Déclencheur" sub={m.trigger_label}>{triggerText()}{delayText()}</Row>
        <Row n={3} icon={MessageSquare} title="Message" sub="Notification Wallet"><b>Titre :</b> {msg.title}<span className="block"><b>Message :</b> {msg.body}</span>
          {btn.enabled && <span className="block"><b>Bouton :</b> {btn.label}</span>}</Row>
        <Row n={4} icon={Users} title="Ciblage" sub={tg.mode === 'all' ? 'Tous mes clients' : tg.mode === 'wallet' ? 'Carte Wallet' : 'Segment'}>
          {targetText()}<span className="block text-[#64748B]">{preview ? `${preview.count.toLocaleString('fr-FR')} client(s) ciblé(s) aujourd'hui` : ''}</span></Row>
        <Row n={5} icon={Clock} title="Planification" sub={timed ? 'À heure fixe' : 'Dès l\'événement'}>{planText()}</Row>
        <div className="flex items-center gap-3 rounded-2xl bg-[#F1FBF5] p-4">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#DCFCE7] text-[#059669]"><Power size={22} /></span>
          <span className="flex-1"><span className="block text-[15px] font-bold text-[#0B1C3F]">Activer l'automatisation</span>
            <span className="text-[13px] text-[#475569]">Les notifications seront envoyées automatiquement selon les paramètres définis.</span></span>
          <Toggle label="Activer l'automatisation" on={s.status !== 'paused'} onChange={(v) => set({ status: v ? 'active' : 'paused' })} disabled={!can} />
        </div>
      </div>
    </Card>
  );

  const tips = [
    [/\{pr[ée]nom\}/.test(msg.title + msg.body), /\{pr[ée]nom\}/.test(msg.title + msg.body) ? 'Le message est clair et personnalisé' : 'Ajoutez {prénom} : un message personnalisé est plus ouvert'],
    [timed ? Boolean(sc.smart && page.best_slot) || Boolean(sc.hour) : true, timed && sc.smart && page.best_slot ? 'Le meilleur moment d\'envoi est sélectionné' : 'Le moment d\'envoi est défini'],
    [Boolean(preview?.count), preview?.count ? 'Le ciblage est adapté' : "Aucun client ne correspond au ciblage aujourd'hui"],
    [btn.enabled, btn.enabled ? 'Le bouton d\'action invite à agir' : 'Vous pouvez ajouter un bouton (offre, carte…) pour booster l\'impact'],
  ];

  const Recap = (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <p className="mb-2 text-[16px] font-bold text-[#0B1C3F]">Récapitulatif de l'automatisation</p>
      {[[ScIcon, 'Scénario', s.name || m.label, tone[1]], [CalendarDays, 'Déclencheur', triggerText() + delayText()], [Users, 'Ciblage', targetText()],
        [MessageSquare, 'Message', msg.title || '—'], [Clock, step >= 5 ? 'Planification' : 'Envoi', step >= 5 ? planText() : (timed ? `À ${sc.hour}` : 'Immédiat')]].map(([I, l, v, c]) => (
        <div key={l} className="flex items-start gap-3 border-t border-[#EEF2F7] py-2.5 first:border-t-0">
          <I size={18} className="mt-0.5 shrink-0" style={{ color: c || '#475569' }} />
          <span className="w-28 shrink-0 text-[13.5px] text-[#475569]">{l}</span>
          <span className="min-w-0 flex-1 break-words text-[13.5px] font-medium text-[#0B1C3F]">{v}</span>
        </div>
      ))}
    </section>
  );

  const content = [null, Step1, Step2, Step3, Step4, Step5, Step6][step];
  return (
    <div className="pb-10">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-4">
          <button type="button" onClick={() => navigate('/dashboard/automations')} aria-label="Retour aux automatisations"
                  className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#1463FF]"><ArrowLeft size={22} /></button>
          <div>
            <h1 className="text-[30px] font-extrabold leading-tight text-[#0B1C3F]">{editing ? 'Modifier une automatisation' : 'Créer une automatisation'}</h1>
            <p className="text-[15px] text-[#475569]">{editing ? 'Modifiez les paramètres de cette automatisation pour mettre à jour vos notifications.' : 'Une notification qui part toute seule, au bon moment, pour fidéliser vos clients.'}</p>
          </div>
        </div>
        {can && (
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={!!busy} onClick={() => save('draft')}
                    className="rounded-xl border border-[#BFD3FF] bg-white px-5 py-3 text-[14.5px] font-semibold text-[#1463FF] disabled:opacity-60">
              {busy === 'draft' ? 'Enregistrement…' : 'Enregistrer en brouillon'}</button>
            <button type="button" disabled={!!busy} onClick={() => save(s.status === 'paused' ? 'paused' : 'active')}
                    className="rounded-xl bg-[#1463FF] px-5 py-3 text-[14.5px] font-semibold text-white shadow-[0_14px_30px_-14px_rgba(20,99,255,.8)] disabled:opacity-60">
              {busy && busy !== 'draft' ? 'Enregistrement…' : editing ? 'Enregistrer les modifications' : "Créer l'automatisation"}</button>
          </div>
        )}
      </header>

      <ol className="mb-5 flex items-start overflow-x-auto pb-1">
        {STEPS.map(([label, sub], i) => {
          const n = i + 1;
          const done = n < step;
          const subText = n === 1 && done ? m.label : n === 2 && done ? triggerText() : n === 4 && done ? (tg.mode === 'all' ? 'Tous mes clients' : 'Ciblé') : sub;
          return (
            <li key={label} className="flex min-w-0 flex-1 items-start last:flex-none">
              <button type="button" onClick={() => (done ? go(n) : null)} disabled={!done && n !== step}
                      className="flex shrink-0 items-start gap-2 text-left">
                <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-[16px] font-bold ${n === step ? 'bg-[#1463FF] text-white' : done ? 'bg-[#1463FF] text-white' : 'bg-[#EEF3FB] text-[#1463FF]'}`}>
                  {done ? <Check size={18} /> : n}</span>
                <span className={`hidden pt-1 sm:block ${n === step ? '' : ''}`}>
                  <span className={`block text-[14px] ${n === step ? 'font-bold text-[#1463FF]' : 'font-semibold text-[#0B1C3F]'}`}>{label}</span>
                  {subText && <span className="block max-w-[120px] truncate text-[12px] text-[#64748B]">{subText}</span>}
                </span>
              </button>
              {n < STEPS.length && <span className={`mx-2 mt-5 h-[2px] min-w-[12px] flex-1 ${n < step ? 'bg-[#1463FF]' : 'bg-[#DCE5F3]'}`} />}
            </li>
          );
        })}
      </ol>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <fieldset disabled={!can} className="m-0 min-w-0 border-0 p-0">{content}</fieldset>
        <aside className="space-y-4">
          <WalletPreview shop={page.shop} logo={page.logo_url} title={msg.title} body={msg.body} image={msg.image_url}
                         button={btn.enabled ? btn.label : ''} sample={preview?.sample}
                         extra={s.scenario === 'near_reward' ? { visites_restantes: String(tr.visits_left || 1), visite_s: Number(tr.visits_left) > 1 ? 'visites' : 'visite' } : {}} />
          {step < 6 ? Recap : (
            <>
              <section className="rounded-2xl border border-[#BBF7D0] bg-[#F0FDF4] p-4">
                <p className="mb-2 flex items-center gap-2 text-[16px] font-bold text-[#047857]"><Lightbulb size={18} /> Conseils FidClic AI</p>
                {tips.map(([ok, t]) => (
                  <p key={t} className={`flex items-start gap-2 py-1 text-[13.5px] ${ok ? 'text-[#14532D]' : 'text-[#9A3412]'}`}>
                    {ok ? <Check size={16} className="mt-0.5 shrink-0 text-[#16A34A]" /> : <Info size={16} className="mt-0.5 shrink-0" />} {t}</p>
                ))}
              </section>
              <section className="rounded-2xl border border-[#BFD3FF] bg-[#F5F8FF] p-4">
                <p className="mb-1 flex items-center gap-2 text-[15px] font-bold text-[#0B1C3F]"><Info size={17} className="text-[#1463FF]" /> Prêt à enregistrer ?</p>
                <p className="text-[13.5px] text-[#475569]">{editing ? 'Votre automatisation sera mise à jour et remplacera l\'ancienne version. Les prochaines notifications seront envoyées selon ces nouveaux paramètres.'
                  : s.status !== 'paused' ? 'Votre automatisation partira toute seule dès son prochain déclencheur.' : 'Votre automatisation sera enregistrée en pause : activez-la quand vous voulez.'}</p>
              </section>
            </>
          )}
        </aside>
      </div>

      {error && <p role="alert" className="mt-4 rounded-xl bg-[#FEF2F2] px-4 py-3 text-[14px] font-medium text-[#B91C1C]">{error}</p>}
      <footer className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#E6EEFB] bg-white p-4">
        <button type="button" onClick={() => (step === 1 ? navigate('/dashboard/automations') : go(step - 1))}
                className="inline-flex items-center gap-2 rounded-xl border border-[#BFD3FF] px-6 py-3 text-[15px] font-semibold text-[#1463FF]">
          {step === 1 ? 'Annuler' : <><ArrowLeft size={17} /> Précédent</>}
        </button>
        {step < 6 ? (
          <button type="button" onClick={next}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#1463FF] px-8 py-3 text-[15px] font-semibold text-white shadow-[0_14px_30px_-14px_rgba(20,99,255,.8)]">
            Suivant <ArrowRight size={17} />
          </button>
        ) : can && (
          <button type="button" disabled={!!busy} onClick={() => save(s.status === 'paused' ? 'paused' : 'active')}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#1463FF] px-7 py-3 text-[15px] font-semibold text-white shadow-[0_14px_30px_-14px_rgba(20,99,255,.8)] disabled:opacity-60">
            {busy ? <Loader2 size={17} className="animate-spin" /> : <Check size={17} />} {editing ? 'Enregistrer les modifications' : "Créer l'automatisation"}
          </button>
        )}
      </footer>
    </div>
  );
}
