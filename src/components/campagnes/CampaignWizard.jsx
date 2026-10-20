import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  X, Check, ArrowRight, ArrowLeft, Percent, Euro, CalendarDays, Clock, Info, Eye, Pencil, Smile,
  Users, Tags, User, MapPin, Search, Send, Loader2, Image as ImageIcon, Link2, Sparkles, MessageSquare,
  Star, Gift, Store, Trophy, BarChart3, Lightbulb, Zap, ShieldCheck,
} from 'lucide-react';
import { ownerAPI } from '../../lib/api';
import { useResendCheck } from '../ResendCheck';
import ChipEditor from './ChipEditor';
import PhonePreview from './PhonePreview';
import {
  KIND_META, VARIABLES, examplesFor, EMOJIS, dayShort, dayLong, todayYmd, addDays, daysBetween, hh,
} from './kinds';
import TimeInput24 from '../TimeInput24';

/**
 * « Nouvelle notification » — the five-step wizard of the Campagnes mockups
 * (2026-10-10): 1 the offer (by kind), 2 the message, 3 the recipients,
 * 4 when, 5 review and send. « Envoi immédiat » jumps straight to the review;
 * « Planifier » asks a day and an hour (no recurrence), then the review.
 * The server checks everything again (features/campaign_kinds.py).
 */
const STEPS = ['Offre', 'Message', 'Destinataires', 'Planification', 'Aperçu et envoi'];
const VAR_ICON = { user: User, gift: Gift, store: Store, trophy: Trophy, star: Star, chart: BarChart3 };
const VAR_TONE = { blue: ['#E6EEFF', '#2F6BFF'], rose: ['#FFE8EE', '#E11D48'], violet: ['#F1EAFF', '#7C3AED'],
  amber: ['#FFF1DC', '#F59E0B'], green: ['#E3F6EC', '#059669'] };
const TITLE_MAX = 50;
const MSG_MAX = 160;
const LINK_RE = /^https?:\/\/[^\s/?#]+\.[^\s/?#]{2,}(?:[/?#]\S*)?$/i;
const fullLink = (raw) => {
  const s = String(raw || '').trim();
  if (!s) return '';
  return /^[a-z][a-z0-9+.-]*:/i.test(s) ? s : `https://${s.replace(/^\/+/, '')}`;
};
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');
// « Configurer une offre » = any other message: title, description, optional dates/hours, no discount
const OFFERISH = ['offre', 'configurer'];

const field = 'w-full rounded-xl border border-[#D9E2F2] bg-white px-4 py-3 !text-[16px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF] focus:ring-2 focus:ring-[#2F6BFF]/15';
const Label = ({ children, hint }) => (
  <span className="mb-1.5 block text-[14px] font-semibold text-[#0B1C3F]">{children}{hint && <span className="font-normal text-[#64748B]"> {hint}</span>}</span>
);
const Toggle = ({ on, onChange, label }) => (
  <button type="button" role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)}
          className={`relative h-7 w-12 shrink-0 rounded-full transition ${on ? 'bg-[#2F6BFF]' : 'bg-[#D6DEEA]'}`}>
    <span className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition ${on ? 'left-6' : 'left-1'}`} />
  </button>
);

export const emptyState = (kind) => ({
  kind, title: '', message: '', details: '', image: '', link: '',
  // Nothing is chosen for them: « % » used to sit in the field before the
  // merchant had said anything, and a fixed amount still read « % »
  // until they noticed (user, 2026-10-15).
  offer: { discount_type: null, discount_value: '', start_date: '', end_date: '', all_day: true, time_from: '17:00', time_to: '19:00' },
  event: { date: '', time: '', place: '' },
  defi: { target: '3', end_date: '', count_mode: 'per_day', reward: '', reward_valid_days: '30' },
  audience: { mode: 'all', segment: '', customer_ids: [], km: 5, filters: { active: false, inactive: false, new: false, min_points: null } },
  sendMode: null, date: '', time: '14:00', draftId: null, template: null,
  walletPhoto: false,     // the photo on the Wallet card too? (BUG-006, off unless chosen)
});

export default function CampaignWizard({ initial, startStep = 1, page, onClose, onDone }) {
  const [s, setS] = useState(initial);
  const [step, setStep] = useState(startStep);
  const [busy, setBusy] = useState('');
  // one key per wizard: pressed again after an error, the same send is never made twice
  const sendKey = useRef(
    (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`);
  const [error, setError] = useState(initial.notice || '');
  const [preview, setPreview] = useState(null);          // { count, label, zone, sample, ids }
  const [previewErr, setPreviewErr] = useState('');
  const [tab, setTab] = useState('vars');
  const [emoji, setEmoji] = useState(false);
  const [pickQuery, setPickQuery] = useState('');
  const [pickRows, setPickRows] = useState([]);
  const [picked, setPicked] = useState({});              // id → name (custom audience)
  const [objective, setObjective] = useState('');
  const editor = useRef(null);
  const fileRef = useRef(null);
  const [guardResend, resendModal] = useResendCheck();
  const meta = KIND_META[s.kind] || KIND_META.offre;
  const KIcon = meta.icon;
  const set = (patch) => setS((o) => ({ ...o, ...patch }));
  const setIn = (key, patch) => setS((o) => ({ ...o, [key]: { ...o[key], ...patch } }));
  const today = todayYmd();

  // ---- live audience (step 3 onwards) ----------------------------------------
  const audienceBody = useMemo(() => {
    const a = s.audience;
    const f = a.filters;
    const filters = { active: f.active, inactive: f.inactive, new: f.new,
      min_points: f.min_points === '' || f.min_points == null ? null : Number(f.min_points) };
    // « Tous les clients » = everyone: no filter (they stay set for the other modes)
    return { mode: a.mode, segment: a.mode === 'segment' ? a.segment : null,
      customer_ids: a.mode === 'custom' ? a.customer_ids : null, km: a.mode === 'zone' ? Number(a.km) : null,
      filters: a.mode === 'all' ? null : filters };
  }, [s.audience]);
  useEffect(() => {
    const a = s.audience;
    if ((a.mode === 'segment' && !a.segment) || (a.mode === 'custom' && !a.customer_ids.length)) {
      setPreview({ count: 0, label: '', zone: null, sample: null, ids: [] }); setPreviewErr(''); return undefined;
    }
    let alive = true;
    const t0 = setTimeout(() => {
      ownerAPI.campaignAudiencePreview({ audience: audienceBody })
        .then(({ data }) => { if (alive) { setPreview(data); setPreviewErr(''); if (data.names) setPicked((p) => ({ ...data.names, ...p })); } })
        .catch((e) => { if (alive) { setPreview(null); setPreviewErr(e?.response?.data?.detail || 'Destinataires indisponibles.'); } });
    }, 250);
    return () => { alive = false; clearTimeout(t0); };
  }, [audienceBody]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- picking clients one by one --------------------------------------------
  useEffect(() => {
    if (s.audience.mode !== 'custom') return undefined;
    let alive = true;
    const t0 = setTimeout(() => {
      ownerAPI.clientsList({ search: pickQuery.trim() || undefined, per_page: 30, page: 1, sort: 'name' })
        .then(({ data }) => { if (alive) setPickRows(data?.rows || []); })
        .catch(() => { if (alive) setPickRows([]); });
    }, 250);
    return () => { alive = false; clearTimeout(t0); };
  }, [pickQuery, s.audience.mode]);
  const togglePick = (r) => {
    const ids = new Set(s.audience.customer_ids);
    if (ids.has(r.id)) ids.delete(r.id); else ids.add(r.id);
    setPicked((p) => ({ ...p, [r.id]: r.name }));
    setIn('audience', { customer_ids: Array.from(ids) });
  };

  // ---- step 1 checks (the server repeats them) --------------------------------
  const o = s.offer;
  const d = s.defi;
  const offerProblems = () => {
    if (!s.title.trim()) return 'Donnez un titre à votre offre.';
    if (o.discount_value !== '' && o.discount_value != null) {
      const v = Number(String(o.discount_value).replace(',', '.'));
      if (!(v > 0)) return 'La valeur de la réduction doit être positive.';
      if (o.discount_type === 'percent' && v > 100) return 'Une réduction en pourcentage ne dépasse pas 100 %.';
    }
    if (o.start_date && !o.end_date) return 'Indiquez aussi la date de fin.';
    if (o.end_date && o.end_date < (o.start_date || today)) return 'La date de fin est avant la date de début.';
    if (o.end_date && o.end_date < today) return 'La date de fin est déjà passée.';
    if (!o.all_day && (!o.time_from || !o.time_to)) return "Indiquez l'heure de début et de fin.";
    if (!o.all_day && o.time_to <= o.time_from) return "L'heure de fin doit être après l'heure de début.";
    return '';
  };
  const defiProblems = () => {
    if (!s.title.trim()) return 'Donnez un titre au défi.';
    const t = Number(d.target);
    if (!Number.isInteger(t) || t < 1 || t > 100) return 'Nombre de visites : entre 1 et 100.';
    if (!d.end_date) return 'Indiquez la date de fin du défi.';
    if (d.end_date < today) return 'La date de fin est déjà passée.';
    if (d.count_mode === 'per_day' && t > daysBetween(today, d.end_date) + 1) {
      return `Impossible : ${t} visites à une par jour, le défi ne dure que ${daysBetween(today, d.end_date) + 1} jour(s).`;
    }
    if (!d.reward.trim()) return 'Indiquez la récompense.';
    const v = Number(d.reward_valid_days);
    if (!Number.isInteger(v) || v < 1 || v > 365) return 'Validité de la récompense : entre 1 et 365 jours.';
    return '';
  };
  const step1Problem = () => {
    if (OFFERISH.includes(s.kind)) return offerProblems();
    if (s.kind === 'defi') return defiProblems();
    if (!s.title.trim()) return 'Donnez un titre.';
    if (s.kind === 'evenement') {
      if (!s.event.date) return "Indiquez la date de l'événement.";
      if (s.event.date < today) return "La date de l'événement est déjà passée.";
    }
    return '';
  };
  const linkProblem = s.link.trim() && !(LINK_RE.test(fullLink(s.link)) && fullLink(s.link).length <= 500)
    ? 'Lien invalide : saisissez une adresse web, par exemple https://monsite.fr.' : '';
  const step2Problem = () => (!s.message.trim() ? 'Écrivez le message de la notification.'
    : s.message.length > MSG_MAX ? `${MSG_MAX} caractères au maximum.` : linkProblem);
  const step3Problem = () => (previewErr || (s.audience.mode === 'segment' && !s.audience.segment ? 'Choisissez un segment.'
    : s.audience.mode === 'custom' && !s.audience.customer_ids.length ? 'Sélectionnez au moins un client.'
      : preview && preview.count === 0 ? 'Aucun client ne correspond à ces destinataires.' : !preview ? 'Calcul en cours…' : ''));
  const scheduleIso = () => (s.sendMode === 'later' && s.date && s.time ? new Date(`${s.date}T${s.time}:00`).toISOString() : null);
  const step4Problem = () => {
    if (!s.sendMode) return "Choisissez quand envoyer la notification.";
    if (s.sendMode === 'later') {
      if (!s.date || !s.time) return "Indiquez la date et l'heure d'envoi.";
      if (new Date(`${s.date}T${s.time}:00`) <= new Date(Date.now() + 60000)) return "Choisissez un moment à venir.";
      const end = OFFERISH.includes(s.kind) ? o.end_date : s.kind === 'defi' ? d.end_date : s.kind === 'evenement' ? s.event.date : '';
      if (end && s.date > end) return "L'envoi serait après la fin : avancez la date d'envoi.";
    }
    return '';
  };
  const problemOf = (n) => [null, step1Problem, step2Problem, step3Problem, step4Problem, () => ''][n]();

  const go = (n) => { setError(''); setStep(n); };
  const next = () => {
    const p = problemOf(step);
    if (p) { setError(p); return; }
    go(step + 1);
  };

  // ---- what is sent ----------------------------------------------------------
  const body = (mode) => {
    const b = {
      kind: s.kind, title: s.title.trim(), message: s.message.trim(), details: s.details.trim() || null,
      image_url: s.image || null, link_url: fullLink(s.link) || null, push: true, wallet: true,
      wallet_photo: !!(s.image && s.walletPhoto),
      audience: audienceBody, draft: mode === 'draft', schedule_at: mode === 'draft' ? null : scheduleIso(),
      ...(s.draftId ? { draft_id: s.draftId } : {}), ...(s.template ? { template: s.template } : {}),
    };
    if (OFFERISH.includes(s.kind)) {
      const v = s.kind === 'offre' ? String(o.discount_value ?? '').replace(',', '.') : '';
      b.offer = { discount_type: v ? o.discount_type : null, discount_value: v ? Number(v) : null,
        start_date: o.end_date ? (o.start_date || today) : (o.start_date || null), end_date: o.end_date || null,
        all_day: o.all_day, time_from: o.all_day ? null : o.time_from, time_to: o.all_day ? null : o.time_to };
    } else if (s.kind === 'evenement') {
      b.event = { date: s.event.date, time: s.event.time || null, place: s.event.place || null };
    } else if (s.kind === 'defi') {
      b.defi = { target: Number(d.target), end_date: d.end_date, count_mode: d.count_mode, reward: d.reward.trim(),
        reward_valid_days: Number(d.reward_valid_days) };
    }
    return b;
  };

  const submit = async (mode) => {
    setBusy(mode); setError('');
    try {
      let exclude = [];
      if (mode !== 'draft' && s.sendMode === 'now') {
        // « Déjà contactés »: who on the list got a campaign in the last days (components/ResendCheck)
        exclude = await guardResend(preview?.ids ? { customer_ids: preview.ids } : { segment: 'all' });
        if (exclude === null) { setBusy(''); return; }
      }
      const { data: res } = await ownerAPI.composeCampaign({ ...body(mode), ...(exclude.length ? { exclude_ids: exclude } : {}),
        ...(mode !== 'draft' ? { send_key: sendKey.current } : {}) });
      onDone(res.status === 'draft' ? 'Brouillon enregistré.'
        : res.status === 'scheduled' ? `Notification programmée · ${nf(res.audience)} destinataire${res.audience > 1 ? 's' : ''}.`
          : `Notification envoyée à ${nf(res.audience)} client${res.audience > 1 ? 's' : ''}.`);
    } catch (e) {
      setError(e?.response?.data?.detail || "L'envoi n'a pas abouti.");
    } finally { setBusy(''); }
  };

  const generate = async () => {
    setBusy('ai'); setError('');
    try {
      const { data: g } = await ownerAPI.campaignAiDraft({ objective: objective || s.title || meta.label, segment: 'all' });
      set({ message: g.message.slice(0, MSG_MAX), title: s.title || g.title });
    } catch (e) { setError(e?.response?.data?.detail || "L'assistant n'est pas disponible."); } finally { setBusy(''); }
  };

  const pickImage = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 900 * 1024) { setError('Image trop lourde (900 Ko maximum).'); return; }
    const r = new FileReader();
    r.onload = () => set({ image: String(r.result) });
    r.readAsDataURL(f);
  };

  // ---- summary lines ----------------------------------------------------------
  const offerSummary = () => {
    if (OFFERISH.includes(s.kind)) {
      const v = s.kind === 'offre' ? String(o.discount_value ?? '').trim() : '';
      const bits = [];
      if (o.end_date) bits.push(`Du ${dayShort(o.start_date || today)} au ${dayShort(o.end_date)}`);
      if (!o.all_day) bits.push(`${hh(o.time_from)}–${hh(o.time_to)}`);
      if (v) bits.push(o.discount_type === 'percent' ? `Réduction en pourcentage : ${v}%` : `Réduction : ${v} €`);
      return bits.join(' · ') || 'Sans dates : 30 jours sur la carte';
    }
    if (s.kind === 'evenement') return [dayShort(s.event.date), s.event.time && hh(s.event.time), s.event.place].filter(Boolean).join(' · ');
    if (s.kind === 'defi') return `${d.target} visite${Number(d.target) > 1 ? 's' : ''} avant le ${dayShort(d.end_date)} · ${d.reward} · valable ${d.reward_valid_days} j`;
    return s.details ? s.details.slice(0, 80) : 'Nouveauté';
  };
  const whenLabel = () => (s.sendMode === 'later' && s.date ? `${dayShort(s.date)}, ${s.time}` : s.sendMode === 'now' ? 'Envoi immédiat' : '');
  const at = s.sendMode === 'later' && s.date && s.time ? `${s.date}T${s.time}:00` : null;
  const shop = page?.wallet_name || page?.tenant_name;
  const best = page?.best_slot;

  // ---- pieces -----------------------------------------------------------------
  const Stepper = (
    <ol className="mx-auto mb-5 flex max-w-[900px] items-start">
      {STEPS.map((label, i) => {
        const n = i + 1;
        const done = n < step;
        const sub = n === 1 && done ? s.title : n === 3 && done && preview ? `${nf(preview.count)} clients` : n === 4 && done ? whenLabel() : '';
        return (
          <li key={label} className="flex min-w-0 flex-1 items-start last:flex-none">
            <button type="button" onClick={() => (done ? go(n) : null)} disabled={!done}
                    className="flex shrink-0 flex-col items-center text-center sm:w-[110px]">
              <span className={`flex h-10 w-10 items-center justify-center rounded-full text-[16px] font-bold ${
                n === step ? 'bg-[#1463FF] text-white shadow-[0_8px_18px_-8px_rgba(20,99,255,.9)]'
                  : done ? 'bg-[#E6EEFF] text-[#1463FF]' : 'bg-[#EEF3FB] text-[#1463FF]'}`}>
                {done ? <Check size={18} /> : n}
              </span>
              <span className={`mt-1.5 text-[13.5px] ${n === step ? 'font-bold text-[#0B1C3F]' : 'hidden font-medium text-[#475569] sm:block'}`}>
                {n === 1 ? meta.short : label}
              </span>
              {sub && <span className="hidden max-w-[140px] truncate text-[11.5px] text-[#64748B] sm:block">{sub}</span>}
            </button>
            {n < STEPS.length && <span className={`mx-1 mt-5 h-[2px] min-w-[8px] flex-1 sm:mx-0 ${n < step ? 'bg-[#1463FF]' : 'bg-[#DCE5F3]'}`} />}
          </li>
        );
      })}
    </ol>
  );

  const Selected = step >= 2 && step <= 4 && (
    <div className="mb-4 flex flex-wrap items-center gap-3 rounded-2xl bg-[#F1F6FF] p-4">
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl" style={{ background: meta.bg, color: meta.fg }}><KIcon size={24} /></span>
      <div className="min-w-0 flex-1">
        <p className="text-[11.5px] font-semibold uppercase tracking-wide text-[#64748B]">{meta.short} sélectionné{OFFERISH.includes(s.kind) || s.kind === 'defi' ? 'e' : ''}</p>
        <p className="truncate text-[17px] font-bold text-[#0B1C3F]">{s.title}</p>
        <p className="truncate text-[13px] text-[#475569]">{offerSummary()}</p>
      </div>
      <button type="button" onClick={() => go(1)}
              className="inline-flex items-center gap-2 rounded-xl border border-[#BFD3FF] bg-white px-4 py-2.5 text-[14px] font-semibold text-[#1463FF]">
        <Pencil size={15} /> Modifier {OFFERISH.includes(s.kind) ? "l'offre" : s.kind === 'defi' ? 'le défi' : s.kind === 'evenement' ? "l'événement" : 'la nouveauté'}
      </button>
    </div>
  );

  const PreviewSide = (
    <aside className="rounded-2xl bg-[#F4F8FF] p-4">
      <div className="mb-3 flex items-start gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white text-[#2F6BFF]">{step === 1 ? <ShieldCheck size={18} /> : <Eye size={18} />}</span>
        <div>
          <p className="text-[16px] font-bold text-[#0B1C3F]">Aperçu de la notification</p>
          <p className="text-[12.5px] text-[#64748B]">{step === 1 ? 'Voici un exemple de rendu sur téléphone.' : step === 2 ? 'Voici un exemple de rendu sur téléphone avec vos variables.' : 'Voici un exemple de rendu sur téléphone avec vos paramètres.'}</p>
        </div>
      </div>
      <PhonePreview at={at} shop={shop} logo={page?.logo_url} title={s.title || meta.label}
                    message={step >= 2 ? s.message : ''} sample={preview?.sample}
                    icon={s.kind === 'offre' ? <span className="mr-1 text-[#E11D48]">%</span> : null} />
      {step >= 2 && (
        <p className="mt-3 flex items-start gap-2 rounded-xl bg-white/80 p-3 text-[12.5px] text-[#475569]">
          <Info size={15} className="mt-0.5 shrink-0 text-[#2F6BFF]" />
          <span>
            {step === 2 ? 'Les variables seront automatiquement remplacées par les informations de chaque client lors de l\'envoi. '
              : s.sendMode === 'later' && s.date ? <>La notification sera envoyée le <b>{dayLong(`${s.date}T${s.time}:00`)}</b> à <b translate="no" className="notranslate">{s.time}</b> à <b>{nf(preview?.count)} clients</b>. </>
                : s.sendMode === 'now' ? <>La notification sera envoyée <b>immédiatement</b> à <b>{nf(preview?.count)} clients</b>. </>
                  : <>Le message sera envoyé à <b>{nf(preview?.count)} clients</b>. </>}
            Le rendu peut varier selon l'appareil (iOS / Android).
          </span>
        </p>
      )}
    </aside>
  );

  // ---- step 1 -----------------------------------------------------------------
  const days = o.end_date ? daysBetween(o.start_date || today, o.end_date) + 1 : null;
  const Step1 = (
    <Card title={`1. Définissez votre ${OFFERISH.includes(s.kind) ? 'offre' : s.kind === 'defi' ? 'défi' : s.kind === 'evenement' ? 'événement' : 'nouveauté'}`}
          sub={s.kind === 'offre' ? 'Choisissez les détails de votre offre spéciale.' : s.kind === 'configurer' ? 'Un titre, une description et, si besoin, ses dates.' : s.kind === 'defi' ? 'Combien de visites, jusqu\'à quand, pour quelle récompense.'
            : s.kind === 'evenement' ? 'Quand et où a lieu votre événement.' : 'Présentez votre nouveau produit, menu ou service.'}>
      <label className="block">
        <Label>{OFFERISH.includes(s.kind) ? "Titre de l'offre" : s.kind === 'defi' ? 'Titre du défi' : s.kind === 'evenement' ? "Nom de l'événement" : 'Titre'}</Label>
        <input className={field} value={s.title} maxLength={TITLE_MAX} onChange={(e) => set({ title: e.target.value })}
               placeholder={s.kind === 'offre' ? '-20% sur votre prochain achat' : s.kind === 'configurer' ? 'Un café offert pour 2 achetés' : s.kind === 'defi' ? 'Défi de la semaine'
                 : s.kind === 'evenement' ? 'Soirée dégustation' : 'Nouveau menu'} />
        <span className="mt-1 block text-right text-[12px] text-[#64748B]">{s.title.length}/{TITLE_MAX}</span>
      </label>

      {s.kind === 'offre' && (
        <>
          <div className="mt-2 grid gap-4 sm:grid-cols-2">
            <div>
              <Label>Type de réduction</Label>
              <div className="grid grid-cols-2 gap-2">
                {[['percent', 'Pourcentage', Percent], ['amount', 'Montant fixe', Euro]].map(([k, l, I]) => (
                  <button key={k} type="button" onClick={() => setIn('offer', k === o.discount_type ? { discount_type: null, discount_value: '' } : { discount_type: k })}
                          className={`flex items-center justify-center gap-2 rounded-xl border px-3 py-3 text-[14px] font-medium ${
                            o.discount_type === k ? 'border-[#2F6BFF] bg-[#F1F6FF] text-[#1463FF]' : 'border-[#E2E8F0] bg-[#F8FAFC] text-[#475569]'}`}>
                    <I size={18} /> {l}
                  </button>
                ))}
              </div>
            </div>
            {o.discount_type && (
            <label className="block">
              <Label>Valeur de la réduction <span className="font-normal text-[#64748B]">(optionnelle)</span></Label>
              <span className="flex items-stretch overflow-hidden rounded-xl border border-[#D9E2F2] focus-within:border-[#2F6BFF]">
                <input inputMode="decimal" value={o.discount_value} placeholder={o.discount_type === 'percent' ? '20' : '5'}
                       onChange={(e) => setIn('offer', { discount_value: e.target.value.replace(/[^\d,.]/g, '').slice(0, 7) })}
                       className="min-w-0 flex-1 !border-0 bg-transparent px-4 py-3 !text-[16px] !shadow-none !outline-none !ring-0" />
                <span className="m-1.5 flex items-center rounded-lg bg-[#EEF3FB] px-3 font-semibold text-[#0B1C3F]">{o.discount_type === 'percent' ? '%' : '€'}</span>
              </span>
            </label>
            )}
          </div>
        </>
      )}

      {s.kind === 'configurer' && (
        <label className="mt-2 block"><Label hint="(optionnelle)">Description</Label>
          <textarea className={`${field} min-h-[96px]`} maxLength={500} value={s.details}
                    onChange={(e) => set({ details: e.target.value })} placeholder="Ce que vos clients doivent savoir : conditions, produits concernés…" /></label>
      )}

      {OFFERISH.includes(s.kind) && (
        <>
          <div className="mt-4">
            <Label hint="(optionnelle)">Durée de l'offre</Label>
            <div className="grid gap-3 sm:grid-cols-2">
              {[['start_date', 'Date de début'], ['end_date', 'Date de fin']].map(([k, l]) => (
                <label key={k} className="flex items-center gap-3 rounded-xl border border-[#D9E2F2] px-3 py-2">
                  <CalendarDays size={20} className="text-[#0B1C3F]" />
                  <span className="min-w-0 flex-1"><span className="block text-[12px] text-[#64748B]">{l}</span>
                    <input type="date" min={k === 'end_date' ? (o.start_date || today) : today} value={o[k]}
                           onChange={(e) => setIn('offer', { [k]: e.target.value })}
                           className="w-full !border-0 bg-transparent !p-0 !text-[16px] !shadow-none !outline-none !ring-0" /></span>
                </label>
              ))}
            </div>
            <div className="mt-3 flex items-center justify-between rounded-xl border border-[#E2E8F0] px-4 py-3">
              <span><span className="block text-[14px] font-semibold text-[#0B1C3F]">Toute la journée</span>
                <span className="text-[12.5px] text-[#64748B]">Sinon, choisissez les heures (ex. happy hour)</span></span>
              <Toggle on={o.all_day} onChange={(v) => setIn('offer', { all_day: v })} label="Toute la journée" />
            </div>
            {!o.all_day && (
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                {[['time_from', 'Heure de début'], ['time_to', 'Heure de fin']].map(([k, l]) => (
                  <label key={k} className="flex items-center gap-3 rounded-xl border border-[#D9E2F2] px-3 py-2">
                    <Clock size={20} className="text-[#0B1C3F]" />
                    <span className="min-w-0 flex-1"><span className="block text-[12px] text-[#64748B]">{l}</span>
                      <TimeInput24 value={o[k]} onChange={(e) => setIn('offer', { [k]: e.target.value })}
                             className="w-full !border-0 bg-transparent !p-0 !text-[16px] !shadow-none !outline-none !ring-0" /></span>
                  </label>
                ))}
              </div>
            )}
            <p className="mt-3 flex items-center gap-2 rounded-xl bg-[#F1F6FF] px-4 py-3 text-[13.5px] text-[#334155]">
              <Info size={16} className="text-[#1463FF]" />
              {days ? `Cette offre sera valable pendant ${days} jour${days > 1 ? 's' : ''}${o.all_day ? '' : `, de ${hh(o.time_from)} à ${hh(o.time_to)}`}.`
                : 'Sans dates, l\'offre reste 30 jours sur la carte de vos clients.'}
            </p>
          </div>
        </>
      )}

      {s.kind === 'nouveaute' && (
        <>
          <label className="mt-2 block"><Label hint="(optionnelle)">Description</Label>
            <textarea className={`${field} min-h-[96px]`} maxLength={500} value={s.details}
                      onChange={(e) => set({ details: e.target.value })} placeholder="Trois nouveaux plats de saison, à découvrir dès ce soir." /></label>
          <div className="mt-3"><Label hint="(optionnelle)">Photo</Label>
            <ImageField image={s.image} onPick={() => fileRef.current?.click()} onClear={() => set({ image: '' })}
                        walletPhoto={!!s.walletPhoto} onWalletPhoto={(v) => set({ walletPhoto: v })} /></div>
        </>
      )}

      {s.kind === 'evenement' && (
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          <label className="block"><Label>Date</Label>
            <input type="date" min={today} className={field} value={s.event.date} onChange={(e) => setIn('event', { date: e.target.value })} /></label>
          <label className="block"><Label hint="(optionnelle)">Heure</Label>
            <TimeInput24 allowEmpty aria-label="Heure de l’événement" className={field} value={s.event.time} onChange={(e) => setIn('event', { time: e.target.value })} /></label>
          <label className="block sm:col-span-2"><Label hint="(optionnel)">Lieu</Label>
            <input className={field} maxLength={120} value={s.event.place} placeholder="Dans votre boutique"
                   onChange={(e) => setIn('event', { place: e.target.value })} /></label>
          <label className="block sm:col-span-2"><Label hint="(optionnelle)">Description</Label>
            <textarea className={`${field} min-h-[80px]`} maxLength={500} value={s.details} onChange={(e) => set({ details: e.target.value })} /></label>
        </div>
      )}

      {s.kind === 'defi' && (
        <div className="mt-2 grid gap-4 sm:grid-cols-2">
          <label className="block"><Label>Nombre de visites</Label>
            <input inputMode="numeric" className={field} value={d.target} onChange={(e) => setIn('defi', { target: e.target.value.replace(/\D/g, '').slice(0, 3) })} /></label>
          <label className="block"><Label>Date de fin</Label>
            <input type="date" min={today} className={field} value={d.end_date} onChange={(e) => setIn('defi', { end_date: e.target.value })} /></label>
          <div className="sm:col-span-2"><Label>Comment compter les visites</Label>
            <div className="grid gap-2 sm:grid-cols-2">
              {[['per_day', 'Une visite par jour au maximum', 'Revenir deux fois le même jour compte pour une.'],
                ['per_scan', 'Chaque passage compte', 'Chaque scan en caisse est une visite.']].map(([k, l, h]) => (
                <button key={k} type="button" onClick={() => setIn('defi', { count_mode: k })}
                        className={`rounded-xl border p-3 text-left ${d.count_mode === k ? 'border-[#2F6BFF] bg-[#F1F6FF]' : 'border-[#E2E8F0]'}`}>
                  <span className="block text-[14px] font-semibold text-[#0B1C3F]">{l}</span>
                  <span className="text-[12.5px] text-[#64748B]">{h}</span>
                </button>
              ))}
            </div></div>
          <label className="block"><Label>Récompense</Label>
            <input className={field} maxLength={80} value={d.reward} placeholder="1 dessert offert" onChange={(e) => setIn('defi', { reward: e.target.value })} /></label>
          <label className="block"><Label>Récompense valable (jours)</Label>
            <input inputMode="numeric" className={field} value={d.reward_valid_days}
                   onChange={(e) => setIn('defi', { reward_valid_days: e.target.value.replace(/\D/g, '').slice(0, 3) })} /></label>
          {d.end_date && Number(d.target) > 0 && (
            <p className="flex items-center gap-2 rounded-xl bg-[#F1F6FF] px-4 py-3 text-[13.5px] text-[#334155] sm:col-span-2">
              <Info size={16} className="text-[#1463FF]" />
              Vos clients ont jusqu'au {dayShort(d.end_date)} pour faire {d.target} visite{Number(d.target) > 1 ? 's' : ''} ; la récompense reste ensuite valable {d.reward_valid_days || '…'} jours.
            </p>
          )}
        </div>
      )}
    </Card>
  );

  // ---- step 2 -----------------------------------------------------------------
  const Step2 = (
    <Card title="2. Rédigez votre message" sub="Un message court et percutant sera affiché sur le téléphone de vos clients.">
      <Label>Message de la notification</Label>
      <ChipEditor ref={editor} value={s.message} onChange={(v) => set({ message: v })} max={MSG_MAX}
                  placeholder="Bonjour {prénom} ! …" id="cg-message" />
      <p className="mt-1 text-right text-[12px] text-[#64748B]">{s.message.length}/{MSG_MAX}</p>
      <div className="relative">
        <button type="button" onClick={() => setEmoji((v) => !v)}
                className="flex w-full items-center gap-2 rounded-xl border border-[#E2E8F0] px-4 py-3 text-[14px] text-[#0B1C3F] sm:w-1/2">
          <Smile size={18} /> Ajouter un emoji
        </button>
        {emoji && (
          <div className="absolute z-20 mt-2 grid w-[280px] grid-cols-8 gap-1 rounded-xl border border-[#E2E8F0] bg-white p-2 shadow-xl">
            {EMOJIS.map((e) => <button key={e} type="button" className="rounded-lg p-1 text-[20px] hover:bg-[#F1F5F9]"
                                       onClick={() => { editor.current?.insertText(e); setEmoji(false); }}>{e}</button>)}
          </div>
        )}
      </div>
      <div className="mt-3 rounded-2xl border border-[#E6EEFB] bg-[#F8FAFF] p-3">
        <div className="mb-2 flex gap-1 border-b border-[#E6EEFB]">
          {[['vars', 'Variables', Users], ['examples', 'Exemples de messages', Lightbulb], ['ai', 'FidClic IA', Sparkles]].map(([k, l, I]) => (
            <button key={k} type="button" onClick={() => setTab(k)}
                    className={`-mb-px flex items-center gap-2 border-b-2 px-3 py-2 text-[14px] font-semibold ${tab === k ? 'border-[#1463FF] text-[#1463FF]' : 'border-transparent text-[#475569]'}`}>
              <I size={16} /> {l}
            </button>
          ))}
        </div>
        {tab === 'vars' && (
          <>
            <p className="mb-2 text-[13px] text-[#64748B]">Cliquez sur une variable pour l'ajouter à votre message.</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {VARIABLES.map((v) => {
                const I = VAR_ICON[v.icon];
                const [bg, fg] = VAR_TONE[v.tone];
                return (
                  <button key={v.key} type="button" onClick={() => editor.current?.insertToken(v.key)}
                          className="flex items-center gap-2 rounded-xl border border-[#E6EEFB] bg-white px-3 py-2 text-left hover:border-[#BFD3FF]">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg" style={{ background: bg, color: fg }}><I size={16} /></span>
                    <span className="flex-1 text-[13px] font-semibold text-[#0B1C3F]">{v.label}</span>
                    <span className="rounded-md bg-[#F1F5F9] px-1.5 py-0.5 text-[11px] text-[#475569]">{`{${v.key}}`}</span>
                    <span className="flex h-6 w-6 items-center justify-center rounded-md bg-[#1463FF] text-[16px] text-white">+</span>
                  </button>
                );
              })}
            </div>
          </>
        )}
        {tab === 'examples' && (
          <>
            <p className="mb-2 text-[13px] text-[#64748B]">Choisissez un modèle et adaptez-le à votre {meta.short.toLowerCase()}.</p>
            <div className="space-y-2">
              {examplesFor(s.kind, s.title).map((x) => {
                const I = x.icon;
                return (
                  <div key={x.title} onClick={() => set({ message: x.text.slice(0, MSG_MAX) })}
                       className="flex cursor-pointer items-center gap-3 rounded-xl border border-[#E6EEFB] bg-white p-3 hover:border-[#BFD3FF]">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg" style={{ background: x.bg, color: x.tone }}><I size={20} /></span>
                    <span className="min-w-0 flex-1"><span className="block text-[13.5px] font-semibold text-[#0B1C3F]">{x.title}</span>
                      <span className="block text-[13px] text-[#475569]">{x.text}</span></span>
                    <button type="button" onClick={(e) => { e.stopPropagation(); set({ message: x.text.slice(0, MSG_MAX) }); }}
                            className="rounded-lg border border-[#2F6BFF] px-3 py-1.5 text-[13px] font-semibold text-[#1463FF]">Utiliser</button>
                  </div>
                );
              })}
            </div>
          </>
        )}
        {tab === 'ai' && (
          <div className="flex flex-wrap gap-2">
            <input className={`${field} min-w-0 flex-1`} value={objective} placeholder="Ex. faire revenir les clients le mardi"
                   onChange={(e) => setObjective(e.target.value)} />
            <button type="button" onClick={generate} disabled={busy === 'ai'}
                    className="inline-flex items-center gap-2 rounded-xl bg-[#1463FF] px-4 py-3 text-[14px] font-semibold text-white disabled:opacity-60">
              {busy === 'ai' ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />} Rédiger
            </button>
          </div>
        )}
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {s.kind !== 'nouveaute' && (
          <div><Label hint="(optionnelle)">Photo</Label>
            <ImageField image={s.image} onPick={() => fileRef.current?.click()} onClear={() => set({ image: '' })}
                        walletPhoto={!!s.walletPhoto} onWalletPhoto={(v) => set({ walletPhoto: v })} /></div>
        )}
        <label className="block"><Label hint="(optionnel)">Lien</Label>
          <span className="flex items-center gap-2 rounded-xl border border-[#D9E2F2] px-3 focus-within:border-[#2F6BFF]">
            <Link2 size={18} className="text-[#64748B]" />
            <input value={s.link} onChange={(e) => set({ link: e.target.value })} placeholder="monsite.fr/menu"
                   className="min-w-0 flex-1 !border-0 bg-transparent py-3 !text-[16px] !shadow-none !outline-none !ring-0" />
          </span>
          {linkProblem && <span className="mt-1 block text-[12.5px] text-[#DC2626]">{linkProblem}</span>}
        </label>
      </div>
    </Card>
  );

  // ---- step 3 -----------------------------------------------------------------
  const a = s.audience;
  const f = a.filters;
  const MODES = [['all', 'Tous les clients', "Envoyer à l'ensemble de vos clients", Users],
    ['segment', 'Segment de clients', 'Choisir un segment spécifique', Tags],
    ['custom', 'Clients personnalisés', 'Sélectionner manuellement', User],
    ['zone', 'Zone géographique', 'Clients dans une zone définie', MapPin]];
  const Step3 = (
    <Card title="3. Sélectionnez vos destinataires" sub="Choisissez quels clients recevront cette notification.">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {MODES.map(([k, l, h, I]) => (
          <button key={k} type="button" onClick={() => setIn('audience', { mode: k })}
                  className={`flex flex-col items-center gap-1 rounded-2xl border p-4 text-center transition ${a.mode === k ? 'border-[#2F6BFF] bg-[#F1F6FF]' : 'border-[#E2E8F0] bg-white hover:border-[#BFD3FF]'}`}>
            <I size={24} className={a.mode === k ? 'text-[#1463FF]' : 'text-[#0B1C3F]'} />
            <span className={`text-[14px] font-semibold ${a.mode === k ? 'text-[#1463FF]' : 'text-[#0B1C3F]'}`}>{l}</span>
            <span className="text-[12px] leading-snug text-[#64748B]">{h}</span>
          </button>
        ))}
      </div>

      {a.mode === 'segment' && (
        <div className="mt-3 max-h-[220px] space-y-1.5 overflow-y-auto">
          {(page?.segment_options || []).map((x) => (
            <label key={x.key} className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 ${a.segment === x.key ? 'border-[#2F6BFF] bg-[#F1F6FF]' : 'border-[#E2E8F0]'}`}>
              <input type="radio" name="cg-seg" checked={a.segment === x.key} onChange={() => setIn('audience', { segment: x.key })} className="accent-[#1463FF]" />
              <span className="flex-1"><span className="block text-[14px] font-semibold text-[#0B1C3F]">{x.label}</span>
                <span className="text-[12px] text-[#64748B]">{x.hint}</span></span>
              <span className="text-[13px] font-semibold tabular-nums text-[#475569]">{nf(x.count)}</span>
            </label>
          ))}
        </div>
      )}

      {a.mode === 'custom' && (
        <div className="mt-3">
          <span className="flex items-center gap-2 rounded-xl border border-[#D9E2F2] px-3 focus-within:border-[#2F6BFF]">
            <Search size={18} className="text-[#64748B]" />
            <input value={pickQuery} onChange={(e) => setPickQuery(e.target.value)} placeholder="Rechercher un client (nom, téléphone, e-mail, code)…"
                   className="min-w-0 flex-1 !border-0 bg-transparent py-3 !text-[16px] !shadow-none !outline-none !ring-0" />
          </span>
          {!!a.customer_ids.length && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {a.customer_ids.slice(0, 12).map((id) => (
                <span key={id} className="inline-flex items-center gap-1 rounded-full bg-[#E6EEFF] px-2.5 py-1 text-[12.5px] font-medium text-[#1D4ED8]">
                  {picked[id] || 'Client'}
                  <button type="button" aria-label="Retirer" onClick={() => setIn('audience', { customer_ids: a.customer_ids.filter((x) => x !== id) })}><X size={12} /></button>
                </span>
              ))}
              {a.customer_ids.length > 12 && <span className="text-[12.5px] text-[#64748B]">+{a.customer_ids.length - 12}</span>}
              <button type="button" onClick={() => setIn('audience', { customer_ids: [] })} className="text-[12.5px] font-semibold text-[#1463FF]">Tout retirer</button>
            </div>
          )}
          <div className="mt-2 max-h-[220px] overflow-y-auto rounded-xl border border-[#E6EEFB]">
            {pickRows.map((r) => (
              <label key={r.id} className="flex cursor-pointer items-center gap-3 border-b border-[#F1F5F9] px-3 py-2 last:border-b-0 hover:bg-[#F8FAFF]">
                <input type="checkbox" className="h-4 w-4 accent-[#1463FF]" checked={a.customer_ids.includes(r.id)} onChange={() => togglePick(r)} />
                <span className="min-w-0 flex-1"><span translate="no" className="notranslate block truncate text-[14px] font-semibold text-[#0B1C3F]">{r.name}</span>
                  <span className="block truncate text-[12px] text-[#64748B]">{r.phone || r.email || r.barcode_id}</span></span>
              </label>
            ))}
            {!pickRows.length && <p className="p-4 text-center text-[13px] text-[#64748B]">Aucun client trouvé.</p>}
          </div>
        </div>
      )}

      {a.mode === 'zone' && (
        <div className="mt-3 rounded-2xl border border-[#E2E8F0] p-4">
          <div className="flex items-center justify-between">
            <span className="text-[14px] font-semibold text-[#0B1C3F]">Rayon autour de votre boutique</span>
            <span className="rounded-lg bg-[#E6EEFF] px-2.5 py-1 text-[14px] font-bold text-[#1463FF]">{a.km >= 50 ? '50 km et +' : `${a.km} km`}</span>
          </div>
          <input type="range" min="1" max="50" step="1" value={a.km} aria-label="Rayon en kilomètres"
                 onChange={(e) => setIn('audience', { km: Number(e.target.value) })} className="mt-3 w-full accent-[#1463FF]" />
          <div className="flex justify-between text-[11.5px] text-[#64748B]"><span>1 km</span><span>5</span><span>10</span><span>20</span><span>50 km+</span></div>
          {preview?.zone && (
            <div className="mt-3 max-h-[180px] overflow-y-auto rounded-xl border border-[#E6EEFB]">
              {preview.zone.map((r) => (
                <div key={r.id} className="flex items-center justify-between border-b border-[#F1F5F9] px-3 py-2 text-[13.5px] last:border-b-0">
                  <span translate="no" className="notranslate truncate text-[#0B1C3F]">{r.name}</span>
                  <span className="shrink-0 tabular-nums text-[#64748B]">{String(r.km).replace('.', ',')} km</span>
                </div>
              ))}
              {!preview.zone.length && <p className="p-4 text-center text-[13px] text-[#64748B]">Aucun client dans ce rayon.</p>}
            </div>
          )}
        </div>
      )}

      <div className="mt-4 flex items-center gap-3 rounded-2xl bg-[#F1F6FF] p-4">
        <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#1463FF] text-white"><Info size={18} /></span>
        <span className="min-w-0 flex-1"><span className="block text-[14.5px] font-semibold text-[#0B1C3F]">Nombre de destinataires</span>
          <span className="text-[13px] text-[#475569]">{previewErr || preview?.label || '…'}</span></span>
        <span className="text-right"><span className="block text-[26px] font-extrabold leading-none tabular-nums text-[#1463FF]">{preview ? nf(preview.count) : '…'}</span>
          <span className="text-[12px] text-[#64748B]">clients sélectionnés</span></span>
      </div>

      {a.mode !== 'all' && (
        <>
        <h4 className="mt-5 text-[16px] font-bold text-[#0B1C3F]">Filtres optionnels</h4>
        <p className="mb-2 text-[13px] text-[#64748B]">Affinez votre audience avec des critères supplémentaires.</p>
        <div className="divide-y divide-[#EEF2F7] rounded-2xl border border-[#E6EEFB]">
          {[['active', 'Clients actifs uniquement', 'Clients ayant visité récemment', '#10B981'],
            ['inactive', 'Clients inactifs', "Clients qui n'ont pas visité depuis un certain temps", '#F59E0B'],
            ['new', 'Nouveaux clients', 'Clients inscrits récemment', '#2F6BFF']].map(([k, l, h, c]) => (
            <div key={k} className="flex items-center gap-3 px-4 py-3">
              <span className="h-3 w-3 rounded-full" style={{ background: c }} />
              <span className="min-w-0 flex-1"><span className="block text-[14px] font-semibold text-[#0B1C3F]">{l}</span>
                <span className="text-[12.5px] text-[#64748B]">{h}</span></span>
              <Toggle label={l} on={f[k]} onChange={(v) => setIn('audience', { filters: { ...f, [k]: v,
                ...(k === 'active' && v ? { inactive: false } : {}), ...(k === 'inactive' && v ? { active: false } : {}) } })} />
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-3 px-4 py-3">
            <Star size={14} className="text-[#7C3AED]" />
            <span className="min-w-0 flex-1"><span className="block text-[14px] font-semibold text-[#0B1C3F]">Clients avec un minimum de points</span>
              <span className="text-[12.5px] text-[#64748B]">Par exemple : au moins 50 points</span></span>
            {f.min_points != null && (
              <input inputMode="numeric" aria-label="Points minimum" value={f.min_points}
                     onChange={(e) => setIn('audience', { filters: { ...f, min_points: e.target.value.replace(/\D/g, '').slice(0, 7) } })}
                     className="w-24 rounded-lg border border-[#D9E2F2] px-2 py-1.5 text-right !text-[16px]" />
            )}
            <Toggle label="Minimum de points" on={f.min_points != null}
                    onChange={(v) => setIn('audience', { filters: { ...f, min_points: v ? '50' : null } })} />
          </div>
        </div>
        </>
      )}
    </Card>
  );

  // ---- step 4 -----------------------------------------------------------------
  const Step4 = s.sendMode === 'later' ? (
    <Card title="4. Planifiez l'envoi de votre notification" sub="Choisissez la date et l'heure d'envoi.">
      <div className="rounded-2xl border border-[#E6EEFB] p-4">
        <p className="mb-3 text-[16px] font-bold text-[#0B1C3F]">Date et heure d'envoi</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block"><Label>Date d'envoi</Label>
            <input type="date" min={today} className={field} value={s.date} onChange={(e) => set({ date: e.target.value })} /></label>
          <label className="block"><Label>Heure d'envoi</Label>
            <TimeInput24 className={field} value={s.time} onChange={(e) => set({ time: e.target.value })} /></label>
        </div>
      </div>
      <AiTip best={best} title="Recommandation FIDCLIC AI" />
      <button type="button" onClick={() => set({ sendMode: null })} className="mt-3 text-[13px] font-semibold text-[#1463FF]">← Choisir un autre mode d'envoi</button>
    </Card>
  ) : (
    <Card title="4. Choisissez quand envoyer votre notification" sub="Vous pouvez l'envoyer immédiatement ou la planifier pour plus tard.">
      <div className="grid gap-4 sm:grid-cols-2">
        {[['now', 'Envoi immédiat', `La notification sera envoyée tout de suite à ${nf(preview?.count)} clients.`, Send],
          ['later', "Planifier l'envoi", 'Choisissez une date et une heure pour envoyer la notification.', CalendarDays]].map(([k, l, h, I]) => (
          <button key={k} type="button"
                  onClick={() => { if (k === 'now') { setS((x) => ({ ...x, sendMode: 'now' })); go(5); } else set({ sendMode: 'later', date: s.date || today }); }}
                  className={`relative flex flex-col items-center gap-3 rounded-2xl border p-6 text-center transition ${s.sendMode === k ? 'border-[#2F6BFF] bg-[#F1F6FF]' : 'border-[#E2E8F0] hover:border-[#BFD3FF]'}`}>
            <span className={`absolute right-4 top-4 h-6 w-6 rounded-full border-2 ${s.sendMode === k ? 'border-[#1463FF] bg-[radial-gradient(circle,#1463FF_45%,transparent_50%)]' : 'border-[#CBD5E1]'}`} />
            <span className="flex h-20 w-20 items-center justify-center rounded-full bg-[#E6EEFF] text-[#1463FF]"><I size={34} /></span>
            <span className="text-[20px] font-bold text-[#0B1C3F]">{l}</span>
            <span className="text-[14px] text-[#475569]">{h}</span>
          </button>
        ))}
      </div>
    </Card>
  );

  // ---- step 5 -----------------------------------------------------------------
  const Step5 = (
    <Card title="5. Aperçu et envoi" sub={`Vérifiez les détails de votre notification avant de ${s.sendMode === 'later' ? 'la programmer' : "l'envoyer"}.`}>
      <div className="space-y-3">
        <Row icon={KIcon} tone={[meta.bg, meta.fg]} title={meta.short} onEdit={() => go(1)}>
          <p className="truncate text-[16px] font-bold text-[#0B1C3F]">{s.title}</p>
          <p className="truncate text-[13px] text-[#475569]">{offerSummary()}</p>
        </Row>
        <Row icon={MessageSquare} tone={['#EAF1FF', '#2F6BFF']} title="Message" onEdit={() => go(2)}>
          <p className="text-[14px] text-[#334155]">{s.message}</p>
        </Row>
        <Row icon={Users} tone={['#E3F6EC', '#059669']} title="Destinataires" onEdit={() => go(3)}>
          <p className="text-[14px] text-[#334155]">{preview?.label || '—'}{preview && !/^\d/.test(preview.label || '') ? ` (${nf(preview.count)} client${preview.count > 1 ? 's' : ''})` : ''}</p>
        </Row>
        <Row icon={s.sendMode === 'later' ? CalendarDays : Send} tone={['#F1EAFF', '#7C3AED']} title="Planification" onEdit={() => go(4)}>
          {s.sendMode === 'later' ? (
            <>
              <p className="flex items-center gap-2 text-[14px] text-[#334155]"><CalendarDays size={15} /> {dayLong(`${s.date}T${s.time}:00`)} à {s.time}</p>
              <p className="flex items-center gap-2 text-[14px] text-[#334155]"><Send size={15} /> Envoi unique</p>
              {best && <p className="flex items-center gap-2 text-[14px] text-[#334155]"><span>☀️</span> Créneau recommandé : {best.label}</p>}
            </>
          ) : (
            <><p className="flex items-center gap-2 text-[14px] font-semibold text-[#0B1C3F]"><Zap size={15} /> Envoi immédiat</p>
              <p className="text-[13.5px] text-[#475569]">La notification sera envoyée tout de suite après validation.</p></>
          )}
        </Row>
      </div>
      <AiTip best={best}>{s.sendMode === 'now' ? ' Vous avez choisi un envoi immédiat.' : ''}</AiTip>
    </Card>
  );

  const content = [null, Step1, Step2, Step3, Step4, Step5][step];
  return (
    <div role="dialog" aria-modal="true" aria-label={`Nouvelle notification - ${meta.label}`}
         className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[#0B1C3F]/45 p-2 backdrop-blur-[2px] sm:p-6">
      {resendModal}
      <input ref={fileRef} type="file" accept="image/*" hidden onChange={pickImage} />
      <div className="w-full max-w-[1240px] rounded-[28px] bg-white p-4 shadow-2xl sm:px-7 sm:pb-5 sm:pt-7">
        <header className="mb-5 flex items-start gap-4">
          <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl" style={{ background: meta.bg, color: meta.fg }}><KIcon size={30} /></span>
          <div className="min-w-0 flex-1">
            <h2 className="text-[24px] font-extrabold text-[#0B1C3F]">Nouvelle notification <span className="font-bold">- {meta.label}</span></h2>
            <p className="text-[14.5px] text-[#475569]">{step === 5 ? 'Vérifiez les détails de votre campagne avant de l\'envoyer.' : 'Créez et envoyez une notification en quelques étapes simples.'}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Fermer" className="rounded-full p-2 text-[#0B1C3F] hover:bg-[#F1F5F9]"><X size={24} /></button>
        </header>
        {Stepper}
        {Selected}
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
          <div className="min-w-0">{content}</div>
          {PreviewSide}
        </div>
        {error && <p role="alert" className="mt-4 rounded-xl bg-[#FEF2F2] px-4 py-3 text-[14px] font-medium text-[#B91C1C]">{error}</p>}
        {/* one line right under the cards: Annuler / Précédent at the window's
            bottom-left, Suivant just outside the phone box, at its left (user, 2026-10-10) */}
        <footer className="mt-4 flex flex-wrap items-center justify-between gap-3 lg:grid lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)] lg:gap-5">
          <span className="flex flex-wrap items-center gap-3">
            <button type="button" onClick={() => (step === 1 ? onClose() : go(step === 5 && s.sendMode === 'now' ? 4 : step - 1))}
                    className="inline-flex items-center gap-2 rounded-xl border border-[#CBD5E1] px-6 py-3.5 text-[16px] font-semibold text-[#0B1C3F]">
              {step === 1 ? 'Annuler' : <><ArrowLeft size={18} /> Précédent</>}
            </button>
            {step >= 2 && (
              <button type="button" onClick={() => submit('draft')} disabled={!!busy}
                      className="text-[14px] font-semibold text-[#475569] underline-offset-2 hover:underline disabled:opacity-60">
                {busy === 'draft' ? 'Enregistrement…' : 'Enregistrer en brouillon'}
              </button>
            )}
          </span>
          {step < 5 ? (
            (step !== 4 || s.sendMode === 'later') ? (
              <button type="button" onClick={next}
                      className="inline-flex items-center gap-3 justify-self-start rounded-xl bg-[#1463FF] px-8 py-3.5 text-[16px] font-semibold text-white shadow-[0_14px_30px_-14px_rgba(20,99,255,.8)] hover:bg-[#0F54E0]">
                Suivant <ArrowRight size={18} />
              </button>
            ) : <span />
          ) : (
            <button type="button" onClick={() => submit('send')} disabled={!!busy}
                    className="inline-flex items-center gap-3 justify-self-start rounded-xl bg-[#1463FF] px-8 py-3.5 text-[16px] font-semibold text-white shadow-[0_14px_30px_-14px_rgba(20,99,255,.8)] hover:bg-[#0F54E0] disabled:opacity-60">
              {busy === 'send' ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
              {s.sendMode === 'later' ? 'Programmer la notification' : 'Envoyer maintenant'}
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}

function Card({ title, sub, children }) {
  return (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5">
      <h3 className="text-[19px] font-bold text-[#0B1C3F]">{title}</h3>
      {sub && <p className="mb-4 text-[13.5px] text-[#475569]">{sub}</p>}
      {children}
    </section>
  );
}

// « Conseil FIDCLIC AI »: only when the shop's own visits say it (campaigns_page.best_slot)
function AiTip({ best, title = 'Conseil FIDCLIC AI', children }) {
  if (!best) return null;
  return (
    <p className="mt-4 flex items-start gap-3 rounded-2xl bg-[#EEF4FF] p-4 text-[13.5px] text-[#334155]">
      <Info size={22} className="shrink-0 text-[#1463FF]" />
      <span><b className="block text-[15px] text-[#1463FF]">{title}</b>D'après vos données, le créneau {best.from} - {best.to} est celui où vos clients viennent le plus.{children}</span>
    </p>
  );
}

function Row({ icon: I, tone, title, children, onEdit }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-[#E6EEFB] p-3 sm:gap-4 sm:p-4">
      <span className="flex h-10 w-10 shrink-0 sm:h-12 sm:w-12 items-center justify-center rounded-xl" style={{ background: tone[0], color: tone[1] }}><I size={24} /></span>
      <div className="min-w-0 flex-1"><p className="text-[14px] font-bold text-[#0B1C3F]">{title}</p>{children}</div>
      <button type="button" onClick={onEdit} aria-label={`Modifier : ${title}`} className="inline-flex shrink-0 items-center gap-2 rounded-xl border border-[#BFD3FF] p-2.5 text-[14px] font-semibold text-[#1463FF] sm:px-4 sm:py-2">
        <Pencil size={15} /> <span className="hidden sm:inline">Modifier</span>
      </button>
    </div>
  );
}

function ImageField({ image, onPick, onClear, walletPhoto, onWalletPhoto }) {
  return image ? (
    <>
      <span className="flex items-center gap-3 rounded-xl border border-[#D9E2F2] p-2">
        <img src={image} alt="" className="h-14 w-14 rounded-lg object-cover" />
        <span className="flex-1 text-[13.5px] text-[#0B1C3F]">Photo ajoutée</span>
        <button type="button" onClick={onClear} className="rounded-lg px-2 py-1 text-[13px] font-semibold text-[#DC2626]">Retirer</button>
      </span>
      {/* QA BUG-006 (user, 2026-10-13): the owner decides, campaign by campaign,
          whether the photo replaces the card's own picture in the Wallet while
          the campaign runs. Off: it shows in « Mes offres » (the iOS 27 rewards
          button opens it). */}
      {onWalletPhoto && (
        <span className="mt-2 flex items-center gap-3 rounded-xl border border-[#E6EEFB] px-3 py-2.5">
          <span className="min-w-0 flex-1">
            <span className="block text-[13.5px] font-semibold text-[#0B1C3F]">Afficher la photo sur la carte Wallet</span>
            <span className="block text-[12px] text-[#64748B]">
              {walletPhoto ? 'Elle remplace la photo de la carte tant que la campagne dure.'
                : 'La carte garde sa photo ; celle-ci s’affiche dans « Mes offres ».'}
            </span>
          </span>
          <Toggle on={!!walletPhoto} onChange={onWalletPhoto} label="Afficher la photo sur la carte Wallet" />
        </span>
      )}
    </>
  ) : (
    <button type="button" onClick={onPick} className="flex w-full items-center gap-2 rounded-xl border border-dashed border-[#BFD3FF] px-4 py-3 text-[14px] font-semibold text-[#1463FF]">
      <ImageIcon size={18} /> Ajouter une photo
    </button>
  );
}
