import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Send, Users, Mail, BarChart3, Euro, Clock, Star, Gift, Plus, ChevronRight,
  Zap, Image as ImageIcon, Link2, Calendar, Loader2, Info, Sparkles, Check,
  Bell, X, CheckCircle2,
} from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ownerAPI } from '../lib/api';
import { confirmImportant } from '../lib/prefs';
import { useResendCheck } from '../components/ResendCheck';
import InfoTip from '../components/InfoTip';
import PushPreview from '../components/PushPreview';
import { ResultChip, ResultModal, ComposerTips, LearningPanel } from '../components/CampaignLearning';

/**
 * Campagnes — the composer, built to the approved design.
 *
 * Three steps, one panel: who, what, when. The count under the audience cards
 * is the count that is sent to, and the phone on the right is the message as
 * the customer will actually receive it — same title, same body, same order.
 *
 * Two figures carry the server's own caveat in print: an "ouverture" is a card
 * opened within 72 h of the send (a wallet push returns no read receipt), and
 * "CA généré" is the recipients' spend in the days after it.
 */
const ICONS = {
  send: Send, users: Users, mail: Mail, chart: BarChart3, euro: Euro,
  clock: Clock, star: Star, gift: Gift,
};
const TONES = [
  { bg: '#EAF1FF', fg: '#1D4ED8' },
  { bg: '#E7F7EE', fg: '#0F8B58' },
  { bg: '#FFF1F3', fg: '#E11D48' },
  { bg: '#F3EEFF', fg: '#6D28D9' },
  { bg: '#FFF7E6', fg: '#B45309' },
];
const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');
const money = (n) => `${(n ?? 0).toLocaleString('fr-FR', { maximumFractionDigits: 2 })} €`;
const dayLabel = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
};
const STATUS = {
  sent: { label: 'Terminée', bg: '#E7F7EE', fg: '#0F8B58' },
  sending: { label: 'En cours', bg: '#EAF1FF', fg: '#1D4ED8' },
  scheduled: { label: 'Planifiée', bg: '#FFF7E6', fg: '#B45309' },
  draft: { label: 'Brouillon', bg: '#EEF2F8', fg: '#475569' },
};

const Panel = ({ children, className = '' }) => (
  <section className={`rounded-2xl border border-[#E6EEFB] bg-white shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] ${className}`}>
    {children}
  </section>
);

const Note = ({ children }) => (
  <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-snug text-[#94A3B8]">
    <Info size={12} className="mt-px shrink-0" /> {children}
  </p>
);

/* ── the five figures ─────────────────────────────────────────────────── */
const Stat = ({ s, i }) => {
  const Icon = ICONS[s.icon] || BarChart3;
  const t = TONES[i % TONES.length];
  const up = (s.delta_pct ?? 0) >= 0;
  return (
    <div className="rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl"
              style={{ background: t.bg, color: t.fg }}>
          <Icon size={18} />
        </span>
        <div className="min-w-0">
          <p className="flex items-center gap-1 text-[11.5px] leading-tight text-[#64748B]">
            {s.label} <InfoTip k={{ sent: 'campaigns_sent', revenue: 'campaign_revenue' }[s.key] || s.key} size={12} />
          </p>
          <p className="mt-0.5 whitespace-nowrap text-[21px] font-bold leading-none text-[#0B1C3F] tabular-nums">
            {s.unit === '€' ? money(s.value) : `${nf(s.value)}${s.unit || ''}`}
          </p>
          {s.delta_pct !== null && s.delta_pct !== undefined ? (
            <p className="mt-1 text-[11px] font-semibold"
               style={{ color: up ? '#0F8B58' : '#C0392B' }}>
              {up ? '↑ +' : '↓ '}{s.delta_pct}% <span className="font-normal text-[#94A3B8]">vs mois dernier</span>
            </p>
          ) : (
            <p className="mt-1 text-[11px] text-[#94A3B8]">pas de mois précédent</p>
          )}
        </div>
      </div>
    </div>
  );
};

/* ── page ─────────────────────────────────────────────────────────────── */
// « Ajouter un lien » (QA UX09): a web address, said at once when it is not
// one. « monsite.fr » gets its https:// — the server applies the same rule
// (campaigns_page.clean_link) and the customer's card only opens http(s).
const LINK_RE = /^https?:\/\/[^\s/?#]+\.[^\s/?#]{2,}(?:[/?#]\S*)?$/i;
function fullLink(raw) {
  const s = String(raw || '').trim();
  if (!s) return '';
  return /^[a-z][a-z0-9+.-]*:/i.test(s) ? s : `https://${s.replace(/^\/+/, '')}`;
}
function linkProblem(raw) {
  const s = fullLink(raw);
  if (!s) return '';
  return LINK_RE.test(s) && s.length <= 500 ? '' : 'Lien invalide : saisissez une adresse web, par exemple https://monsite.fr.';
}

export default function CampagnesPage() {
  const navigate = useNavigate();
  const fileRef = useRef(null);

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [flash, setFlash] = useState('');

  const [step, setStep] = useState(1);
  const [guardResend, resendModal] = useResendCheck();
  const [resultOf, setResultOf] = useState(null);       // a sent campaign's id, its result open
  const [segment, setSegment] = useState('all');
  // An audience handed over by Insights (clients within 2 km, one-time new
  // clients…) that none of the four cards names. Its members were resolved
  // by the server, so the send goes to exactly those people.
  const [custom, setCustom] = useState(null);
  // The recommendation this draft came from, sent with the campaign so the
  // recommendation can make way for the next one once it has been used.
  const [fromTemplate, setFromTemplate] = useState(null);
  const [title, setTitle] = useState('');
  const [message, setMessage] = useState('');
  const [image, setImage] = useState('');
  const [link, setLink] = useState('');
  const [showLink, setShowLink] = useState(false);
  const [later, setLater] = useState(false);
  const [date, setDate] = useState('');
  const [time, setTime] = useState('10:00');
  const [push, setPush] = useState(true);
  const [wallet, setWallet] = useState(true);
  const [busy, setBusy] = useState('');
  const [objective, setObjective] = useState('');
  const [aiError, setAiError] = useState('');
  // The draft open in the composer (« Reprendre », QA F02): saving or
  // sending it replaces it instead of adding a second campaign.
  const [draftId, setDraftId] = useState(null);
  const [editKind, setEditKind] = useState('draft');    // 'draft' · 'scheduled' (« Modifier » a planned one)

  const load = useCallback(() => {
    setLoading(true);
    ownerAPI.campaignsPage()
      .then(({ data: d }) => { setData(d); setError(''); })
      .catch((e) => setError(e?.response?.data?.detail || 'Impossible de charger la page.'))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  // "Utiliser ce modèle" / "Relancer ces clients" on Insights land here with
  // ?template=<key>. The copy comes from the server — one source for the page
  // that suggests it and the composer that sends it. The parameter is dropped
  // once applied, so a reload never writes over what the merchant has edited.
  // Read on every change of the address, not only on arrival: the bell's
  // « Envoyer une campagne » opened while already on Campagnes must work too.
  const location = useLocation();
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const key = params.get('template');
    if (!key) return;
    // An alert of the bell names its establishment (?store=) and where it
    // came from (?from=alerte): its clients are that establishment's.
    const source = { alerte: 'depuis une alerte', clients: 'depuis Clients' }[params.get('from')] || 'proposé par Insights';
    ownerAPI.insightTemplate(key, params.get('day'), params.get('store'))
      .then(({ data: t }) => {
        setTitle(t.title || ''); setMessage(t.message || ''); setFromTemplate(key.startsWith('client:') ? 'client' : key);
        setSegment(t.segment || 'all');
        setCustom(t.audience && t.audience.ids?.length ? { ...t.audience, source } : null);
        setStep(2);
        setFlash(t.audience && !t.audience.ids?.length
          ? `Modèle chargé — mais aucun client ne correspond à « ${t.audience.label} » pour l'instant.`
          : 'Modèle chargé : relisez le message, puis envoyez.');
        setTimeout(() => document.getElementById('cg-composer')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 150);
      })
      .catch(() => setError("Ce modèle n'a pas pu être chargé."))
      .finally(() => {
        const rest = new URLSearchParams(location.search);
        ['template', 'day', 'store', 'from'].forEach((k) => rest.delete(k));
        const q = rest.toString();
        navigate({ pathname: location.pathname, search: q ? `?${q}` : '', hash: location.hash }, { replace: true });
      });
  }, [location.search]); // eslint-disable-line react-hooks/exhaustive-deps

  const limits = data?.limits || { title: 50, message: 160 };
  const segments = data?.segments || [];
  const chosen = useMemo(() => (custom
    ? { key: 'custom', label: custom.label, count: custom.ids.length }
    : segments.find((s) => s.key === segment)), [segments, segment, custom]);
  const linkError = linkProblem(link);
  const ready = title.trim() && message.trim() && !linkError;

  const scheduleAt = () => {
    if (!later || !date) return null;
    return new Date(`${date}T${time || '10:00'}:00`).toISOString();
  };

  const submit = async (mode) => {
    // Paramètres › Préférences › Confirmation des actions importantes.
    const now = mode !== 'draft' && !scheduleAt();
    if (now && !confirmImportant('Envoyer cette campagne maintenant ?')) return;
    setBusy(mode); setError('');
    try {
      // « Déjà contactés »: who on the list got a campaign in the last days —
      // the owner picks who gets this one too (components/ResendCheck).
      let exclude = [];
      if (now) {
        exclude = await guardResend(custom ? { customer_ids: custom.ids } : { segment });
        if (exclude === null) { setBusy(''); return; }
      }
      const { data: res } = await ownerAPI.composeCampaign({
        title: title.trim(), message: message.trim(), segment,
        ...(custom ? { customer_ids: custom.ids } : {}),
        ...(exclude.length ? { exclude_ids: exclude } : {}),
        ...(fromTemplate ? { template: fromTemplate } : {}),
        image_url: image || null, link_url: fullLink(link) || null,
        schedule_at: mode === 'draft' ? null : scheduleAt(),
        push, wallet, draft: mode === 'draft',
        ...(draftId ? { draft_id: draftId } : {}),
      });
      setFlash(
        res.status === 'draft' ? 'Brouillon enregistré.'
          : res.status === 'scheduled'
            ? `Planifiée pour ${dayLabel(res.scheduled_for)} · ${nf(res.audience)} destinataires.`
            : `Envoyée à ${nf(res.audience)} client${res.audience > 1 ? 's' : ''}.`);
      setTitle(''); setMessage(''); setImage(''); setLink(''); setShowLink(false);
      setLater(false); setDate(''); setStep(1); setCustom(null); setFromTemplate(null); setDraftId(null); setEditKind('draft');
      load();
    } catch (e) {
      setError(e?.response?.data?.detail || "L'envoi n'a pas abouti.");
    } finally { setBusy(''); }
  };

  // « Reprendre » a draft: back into the composer, as it was saved.
  const resumeDraft = async (id) => {
    setError('');
    try {
      const { data: d } = await ownerAPI.campaignDraft(id);
      setTitle(d.title || ''); setMessage(d.message || ''); setImage(d.image_url || '');
      setLink(d.link_url || ''); setShowLink(!!d.link_url);
      setSegment(d.segment || 'all');
      setCustom(d.audience?.ids?.length ? { ...d.audience, source: 'liste du brouillon' } : null);
      setPush(d.push !== false); setWallet(d.wallet !== false);
      setFromTemplate(d.template || null);
      if (d.status === 'scheduled' && d.scheduled_for) {
        // the planned day and hour, in the owner's time
        const w = new Date(d.scheduled_for);
        const p2 = (n) => String(n).padStart(2, '0');
        setLater(true);
        setDate(`${w.getFullYear()}-${p2(w.getMonth() + 1)}-${p2(w.getDate())}`);
        setTime(`${p2(w.getHours())}:${p2(w.getMinutes())}`);
      } else {
        setLater(false); setDate('');
      }
      setEditKind(d.status === 'scheduled' ? 'scheduled' : 'draft');
      setDraftId(d.id); setStep(2);
      setFlash(d.status === 'scheduled'
        ? 'Campagne planifiée ouverte : modifiez-la, puis cliquez sur « Planifier » (ou « Envoyer » pour l\'envoyer tout de suite).'
        : 'Brouillon repris : modifiez-le, puis enregistrez ou envoyez.');
      setTimeout(() => document.getElementById('cg-composer')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100);
    } catch (e) {
      setError(e?.response?.data?.detail || "Ce brouillon n'a pas pu être ouvert.");
      load();
    }
  };

  const deleteDraft = async (r) => {
    if (!confirmImportant(`Supprimer le brouillon « ${r.name} » ?`)) return;
    setError('');
    try {
      await ownerAPI.deleteCampaignDraft(r.id);
      if (draftId === r.id) {
        setDraftId(null); setEditKind('draft'); setTitle(''); setMessage(''); setImage(''); setLink(''); setShowLink(false);
        setStep(1); setCustom(null); setFromTemplate(null);
      }
      setFlash('Brouillon supprimé.');
      load();
    } catch (e) {
      setError(e?.response?.data?.detail || "Le brouillon n'a pas pu être supprimé.");
    }
  };

  // « Annuler l'envoi »: it does not leave; it goes back to the drafts.
  const cancelSchedule = async (r) => {
    if (!confirmImportant(`Annuler l'envoi planifié de « ${r.name} » ? Elle restera dans vos brouillons.`)) return;
    setError('');
    try {
      await ownerAPI.cancelCampaignSchedule(r.id);
      if (draftId === r.id) { setEditKind('draft'); setLater(false); setDate(''); }
      setFlash('Envoi annulé : la campagne est dans vos brouillons.');
      load();
    } catch (e) {
      setError(e?.response?.data?.detail || "L'envoi n'a pas pu être annulé.");
      load();
    }
  };

  const leaveDraft = () => {
    setDraftId(null); setEditKind('draft'); setTitle(''); setMessage(''); setImage(''); setLink(''); setShowLink(false);
    setStep(1); setCustom(null); setFromTemplate(null); setLater(false); setDate('');
  };

  const generate = async () => {
    setBusy('ai'); setAiError('');
    try {
      const { data: d } = await ownerAPI.campaignAiDraft({ objective, segment });
      setTitle(d.title); setMessage(d.message); setStep(2);
    } catch (e) {
      setAiError(e?.response?.data?.detail || "L'assistant n'est pas disponible.");
    } finally { setBusy(''); }
  };

  const pickImage = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 900 * 1024) { setError('Image trop lourde (900 Ko maximum).'); return; }
    const r = new FileReader();
    r.onload = () => setImage(String(r.result));
    r.readAsDataURL(f);
  };

  if (loading && !data) {
    return (
      <div key="loading" className="cg flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]">
        <Loader2 size={16} className="animate-spin" /> Chargement…
      </div>
    );
  }

  const SHORTCUTS = [
    { icon: Send, title: 'Envoyer une notification', sub: 'Créez et envoyez une campagne en quelques clics.',
      go: () => document.getElementById('cg-composer')?.scrollIntoView({ behavior: 'smooth', block: 'start' }) },
    { icon: Zap, title: 'Automatiser', sub: 'Activez des scénarios pour relancer vos clients automatiquement.',
      go: () => navigate('/dashboard/automations') },
    { icon: BarChart3, title: 'Voir les performances', sub: 'Le rapport de vos campagnes, mois par mois : ce qu\'elles ont vraiment rapporté.',
      go: () => navigate('/dashboard/campaigns/reports') },
  ];

  return (
    <div className="cg">
      {resendModal}
      {resultOf && <ResultModal id={resultOf} onClose={() => setResultOf(null)} />}
      {/* the five figures */}
      <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {(data?.strip || []).map((s, i) => <Stat key={s.key} s={s} i={i} />)}
      </div>

      <header className="mb-4">
        <h1 className="flex flex-wrap items-center gap-2 text-[27px] font-bold leading-tight text-[#0B1C3F]">
          Campagnes
          <span className="inline-flex items-center gap-1 rounded-md bg-[#E7F7EE] px-2 py-0.5 text-[11px] font-bold text-[#0F8B58]">
            <span className="h-1.5 w-1.5 rounded-full bg-[#10B981]" /> LIVE
          </span>
        </h1>
        <p className="text-[13px] text-[#64748B]">
          Faites revenir vos clients avec des messages simples et personnalisés.
        </p>
      </header>

      <div className="mb-4 grid gap-3 lg:grid-cols-3">
        {SHORTCUTS.map(({ icon: Icon, title: t, sub, go }) => (
          <button key={t} type="button" onClick={go}
                  className="group flex items-start gap-3 rounded-2xl border border-[#E6EEFB] bg-white p-4 text-left shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] transition hover:border-[#2F6BFF]">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]">
              <Icon size={18} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[13.5px] font-bold text-[#0B1C3F]">{t}</span>
              <span className="mt-0.5 block text-[11.5px] leading-snug text-[#64748B]">{sub}</span>
            </span>
            <ChevronRight size={16} className="mt-1 shrink-0 text-[#94A3B8] transition group-hover:text-[#2F6BFF]" />
          </button>
        ))}
      </div>

      {flash && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-[#E7F7EE] px-4 py-2.5 text-[12.5px] font-medium text-[#0F8B58]">
          <CheckCircle2 size={15} /> {flash}
          <button type="button" onClick={() => setFlash('')} className="ml-auto text-[#0F8B58]/70 hover:text-[#0F8B58]">
            <X size={14} />
          </button>
        </div>
      )}
      {error && (
        <div className="mb-4 rounded-xl bg-[#FEECEC] px-4 py-2.5 text-[12.5px] text-[#C0392B]">{error}</div>
      )}

      {/* composer */}
      <Panel className="mb-4 p-5" >
        <div id="cg-composer" className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <h2 className="flex flex-wrap items-center gap-2 text-[17px] font-bold text-[#0B1C3F]">
            {!draftId ? 'Nouvelle notification' : editKind === 'scheduled' ? 'Campagne planifiée' : 'Brouillon'}
            {draftId && (
              <button type="button" onClick={leaveDraft}
                      className="rounded-md bg-[#EEF2F8] px-2 py-0.5 text-[11px] font-semibold text-[#475569] hover:bg-[#E2E8F0]">
                {editKind === 'scheduled' ? 'Fermer sans modifier' : 'Fermer le brouillon'}
              </button>
            )}
          </h2>
          <ol className="flex items-center gap-2">
            {['Destinataires', 'Message', 'Envoyer'].map((s, i) => {
              const n = i + 1, on = step === n, done = step > n;
              return (
                <li key={s} className="flex items-center gap-1.5">
                  <span className={`flex h-[22px] w-[22px] items-center justify-center rounded-full text-[11px] font-bold ${
                    on ? 'bg-[#2F6BFF] text-white' : done ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#EEF2F8] text-[#94A3B8]'}`}>
                    {done ? <Check size={12} /> : n}
                  </span>
                  <span className={`text-[12px] ${on ? 'font-semibold text-[#0B1C3F]' : 'text-[#94A3B8]'}`}>{s}</span>
                </li>
              );
            })}
          </ol>
        </div>

        <div className="grid gap-5 lg:grid-cols-[1fr_1.1fr_auto]">
          {/* 1 — audience */}
          <div>
            <p className="text-[13px] font-bold text-[#0B1C3F]">1. Choisissez vos destinataires</p>
            <p className="mb-3 text-[11.5px] text-[#64748B]">Sélectionnez une audience pour votre notification.</p>
            {custom && (
              <div className="mb-2.5 flex items-start gap-2.5 rounded-xl border border-[#2F6BFF] bg-[#F6F9FF] p-3">
                <Users size={16} className="mt-0.5 shrink-0 text-[#2F6BFF]" />
                <span className="min-w-0 flex-1">
                  <span className="block text-[12.5px] font-semibold text-[#0B1C3F]">{custom.label}</span>
                  {custom.hint && <span className="block text-[10.5px] text-[#94A3B8]">{custom.hint}</span>}
                  <span className="mt-1 block text-[11px] font-medium text-[#64748B]">
                    {nf(custom.ids.length)} client{custom.ids.length > 1 ? 's' : ''} · {custom.source || 'proposé par Insights'}
                  </span>
                </span>
                <button type="button" onClick={() => setCustom(null)} title="Choisir une autre audience"
                        className="shrink-0 text-[#94A3B8] hover:text-[#334155]">
                  <X size={14} />
                </button>
              </div>
            )}
            <div className="grid grid-cols-2 gap-2.5">
              {segments.map((s) => {
                const Icon = ICONS[s.icon] || Users;
                const on = !custom && segment === s.key;
                return (
                  <button key={s.key} type="button"
                          onClick={() => { setCustom(null); setSegment(s.key); setStep((v) => Math.max(v, 1)); }}
                          className={`rounded-xl border p-3 text-left transition ${
                            on ? 'border-[#2F6BFF] bg-[#F6F9FF]' : 'border-[#E6EEFB] bg-white hover:border-[#C9DBFB]'}`}>
                    <span className="flex items-start justify-between">
                      <Icon size={16} className={on ? 'text-[#2F6BFF]' : 'text-[#94A3B8]'} />
                      <span className={`flex h-4 w-4 items-center justify-center rounded-full border ${
                        on ? 'border-[#2F6BFF] bg-[#2F6BFF]' : 'border-[#CBD5E1]'}`}>
                        {on && <Check size={10} className="text-white" />}
                      </span>
                    </span>
                    <span className="mt-2 block text-[12.5px] font-semibold leading-tight text-[#0B1C3F]">{s.label}</span>
                    {s.hint && <span className="block text-[10.5px] text-[#94A3B8]">{s.hint}</span>}
                    <span className="mt-1 block text-[11px] font-medium text-[#64748B]">
                      {nf(s.count)} client{s.count > 1 ? 's' : ''}
                    </span>
                  </button>
                );
              })}
            </div>
            <button type="button" onClick={() => navigate('/dashboard/segmentation')}
                    className="mt-2.5 flex w-full items-center gap-2.5 rounded-xl border border-dashed border-[#C9DBFB] bg-white p-3 text-left transition hover:border-[#2F6BFF]">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#EAF1FF] text-[#2F6BFF]">
                <Plus size={14} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[12.5px] font-semibold text-[#0B1C3F]">Créer un segment</span>
                <span className="block text-[10.5px] text-[#94A3B8]">Ciblez vos clients selon vos propres critères</span>
              </span>
              <ChevronRight size={15} className="shrink-0 text-[#94A3B8]" />
            </button>
            <p className="mt-3 inline-flex items-center gap-2 rounded-xl bg-[#EAF1FF] px-3 py-2 text-[12px] font-semibold text-[#1D4ED8]">
              <Users size={14} /> {nf(chosen?.count || 0)} client{(chosen?.count || 0) > 1 ? 's' : ''} sélectionné{(chosen?.count || 0) > 1 ? 's' : ''}
            </p>
          </div>

          {/* 2 — message */}
          <div>
            <p className="text-[13px] font-bold text-[#0B1C3F]">2. Rédigez votre message</p>
            <p className="mb-3 text-[11.5px] text-[#64748B]">Un message court et percutant suffit.</p>

            <label className="mb-1 flex items-center justify-between text-[11.5px] font-medium text-[#475569]">
              Titre de la notification
              <span className="tabular-nums text-[#94A3B8]">{title.length}/{limits.title}</span>
            </label>
            <input value={title} maxLength={limits.title}
                   onChange={(e) => { setTitle(e.target.value); setStep((v) => Math.max(v, 2)); }}
                   placeholder="☕ -20% sur votre prochain café"
                   className="mb-3 w-full rounded-xl border border-[#E6EEFB] bg-white px-3 py-2.5 text-[13px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />

            <label className="mb-1 flex items-center justify-between text-[11.5px] font-medium text-[#475569]">
              Message
              <span className="tabular-nums text-[#94A3B8]">{message.length}/{limits.message}</span>
            </label>
            <textarea value={message} maxLength={limits.message} rows={3}
                      onChange={(e) => { setMessage(e.target.value); setStep((v) => Math.max(v, 2)); }}
                      placeholder={'On vous attend !\nProfitez-en cette semaine.'}
                      className="mb-3 w-full resize-none rounded-xl border border-[#E6EEFB] bg-white px-3 py-2.5 text-[13px] leading-snug text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />
            {/* Advice from what this shop's campaigns taught (components/CampaignLearning). */}
            <ComposerTips title={title} message={message} segment={custom ? 'custom' : segment}
                          image={image} link={link.trim()} scheduleAt={scheduleAt()} />

            <div className="mb-3 grid gap-2.5 sm:grid-cols-2">
              <button type="button" onClick={() => fileRef.current?.click()}
                      className="flex items-center gap-2 rounded-xl border border-[#E6EEFB] bg-white px-3 py-2.5 text-left transition hover:border-[#2F6BFF]">
                <ImageIcon size={15} className="shrink-0 text-[#94A3B8]" />
                <span className="min-w-0">
                  <span className="block truncate text-[12px] font-medium text-[#334155]">
                    {image ? 'Image ajoutée' : 'Ajouter une image'}
                  </span>
                  <span className="block text-[10px] text-[#94A3B8]">(optionnelle)</span>
                </span>
                {image && (
                  <X size={14} className="ml-auto shrink-0 text-[#94A3B8] hover:text-[#C0392B]"
                     onClick={(e) => { e.stopPropagation(); setImage(''); }} />
                )}
              </button>
              <input ref={fileRef} type="file" accept="image/*" hidden onChange={pickImage} />

              <button type="button" onClick={() => setShowLink((v) => !v)}
                      className="flex items-center gap-2 rounded-xl border border-[#E6EEFB] bg-white px-3 py-2.5 text-left transition hover:border-[#2F6BFF]">
                <Link2 size={15} className="shrink-0 text-[#94A3B8]" />
                <span className="min-w-0">
                  <span className="block truncate text-[12px] font-medium text-[#334155]">
                    {link ? 'Lien ajouté' : 'Ajouter un lien'}
                  </span>
                  <span className="block text-[10px] text-[#94A3B8]">(optionnel)</span>
                </span>
              </button>
            </div>
            {showLink && (
              <div className="mb-3">
                <input value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://monsite.fr/offre"
                       inputMode="url" autoComplete="url" aria-invalid={!!linkError}
                       onBlur={() => { if (!linkProblem(link)) setLink(fullLink(link)); }}
                       className={`w-full rounded-xl border bg-white px-3 py-2.5 text-[13px] outline-none ${
                         linkError ? 'border-[#E5484D] focus:border-[#E5484D]' : 'border-[#E6EEFB] focus:border-[#2F6BFF]'}`} />
                {linkError && <p className="mt-1 text-[11.5px] text-[#C0392B]">{linkError}</p>}
              </div>
            )}

            <div className="rounded-xl border border-[#E6EEFB] p-3">
              <p className="mb-2 flex items-center gap-1.5 text-[12.5px] font-bold text-[#0B1C3F]">
                <Calendar size={14} className="text-[#2F6BFF]" /> Planification
              </p>
              <div className="mb-2 flex flex-wrap gap-4 text-[12.5px]">
                {[['Envoyer maintenant', false], ['Planifier pour plus tard', true]].map(([lab, v]) => (
                  <label key={lab} className="flex cursor-pointer items-center gap-1.5 text-[#334155]">
                    <input type="radio" checked={later === v} onChange={() => setLater(v)}
                           className="h-3.5 w-3.5 accent-[#2F6BFF]" />
                    {lab}
                  </label>
                ))}
              </div>
              {later && (
                <div className="grid grid-cols-2 gap-2.5">
                  <input type="date" value={date} min={new Date().toISOString().slice(0, 10)}
                         onChange={(e) => setDate(e.target.value)}
                         className="rounded-xl border border-[#E6EEFB] bg-white px-3 py-2 text-[12.5px] outline-none focus:border-[#2F6BFF]" />
                  <input type="time" value={time} onChange={(e) => setTime(e.target.value)}
                         className="rounded-xl border border-[#E6EEFB] bg-white px-3 py-2 text-[12.5px] outline-none focus:border-[#2F6BFF]" />
                </div>
              )}
            </div>

            <div className="mt-3 rounded-xl border border-[#E6EEFB] p-3">
              <p className="mb-2 text-[12.5px] font-bold text-[#0B1C3F]">Canaux</p>
              {[['Notification push', push, setPush, 'Sur le téléphone, tout de suite.'],
                ['Carte Wallet', wallet, setWallet, "Devient l'offre de la carte ; Apple Wallet prévient le client."],
              ].map(([lab, val, set, hint]) => (
                <label key={lab} className="mb-1.5 flex cursor-pointer items-start gap-2 last:mb-0">
                  <input type="checkbox" checked={val} onChange={(e) => set(e.target.checked)}
                         className="mt-0.5 h-3.5 w-3.5 accent-[#2F6BFF]" />
                  <span>
                    <span className="block text-[12.5px] font-medium text-[#334155]">{lab}</span>
                    <span className="block text-[10.5px] leading-snug text-[#94A3B8]">{hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>

          {/* 3 — preview */}
          <div className="lg:w-[262px]">
            <PushPreview title={title} message={message} image={image} push={push} wallet={wallet}
                         walletName={data?.wallet_name || data?.tenant_name} logo={data?.logo_url} at={scheduleAt()} />
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-2.5 border-t border-[#EEF3FB] pt-4">
          <button type="button" disabled={!ready || !!busy} onClick={() => submit('draft')}
                  className="rounded-xl border border-[#E6EEFB] px-4 py-2.5 text-[13px] font-semibold text-[#334155] transition hover:border-[#2F6BFF] disabled:opacity-50">
            {busy === 'draft' ? <Loader2 size={14} className="animate-spin" /> : 'Enregistrer comme brouillon'}
          </button>
          <button type="button" disabled={!ready} onClick={() => setStep(3)}
                  className="ml-auto rounded-xl border border-[#E6EEFB] px-4 py-2.5 text-[13px] font-semibold text-[#334155] transition hover:border-[#2F6BFF] disabled:opacity-50">
            Visualiser l'aperçu
          </button>
          <button type="button" disabled={!ready || !!busy} onClick={() => submit('send')}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 py-2.5 text-[13px] font-semibold text-white transition hover:bg-[#2559DB] disabled:opacity-50">
            {busy === 'send' ? <Loader2 size={15} className="animate-spin" />
              : later ? <Calendar size={15} /> : <Send size={15} />}
            {later ? 'Planifier' : 'Envoyer'} <ChevronRight size={15} />
          </button>
        </div>

        {step === 3 && ready && (
          <div className="mt-4 rounded-xl bg-[#F6F9FF] p-4">
            <p className="mb-1.5 text-[12.5px] font-bold text-[#0B1C3F]">Récapitulatif</p>
            <ul className="space-y-1 text-[12.5px] text-[#475569]">
              <li>· <strong className="text-[#0B1C3F]">{nf(chosen?.count || 0)}</strong> destinataires — {chosen?.label}</li>
              <li>· Canaux : {[push && 'push', wallet && 'wallet'].filter(Boolean).join(' + ') || 'aucun'}</li>
              <li>· {later && date ? `Planifiée pour le ${date} à ${time}` : 'Envoi immédiat'}</li>
            </ul>
          </div>
        )}
      </Panel>

      <LearningPanel />

      {/* recent + assistant */}
      <div className="grid gap-4 xl:grid-cols-[1.7fr_1fr]">
        <Panel className="p-5">
          <h2 className="mb-3 text-[15px] font-bold text-[#0B1C3F]">Vos dernières notifications</h2>
          {data?.recent?.length ? (
            <>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[620px] border-collapse">
                  <thead>
                    <tr className="border-b border-[#EEF3FB] text-left">
                      {['Nom de la campagne', 'Audience', 'Envoyées', "Taux d'ouverture", 'Effet', 'Statut', 'Action'].map((h, i) => (
                        <th key={h} className={`px-2 py-2.5 text-[11.5px] font-semibold text-[#64748B] ${i >= 2 && i <= 3 ? 'text-right' : ''}`}
                            title={h === 'Effet' ? 'Clients revenus en plus de ceux qui seraient venus de toute façon' : undefined}>
                          {h === 'Effet' ? <span className="inline-flex items-center gap-1">{h} <InfoTip k="effect" size={12} /></span> : h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent.map((r) => {
                      const st = STATUS[r.status] || STATUS.draft;
                      return (
                        <tr key={r.id} className="border-b border-[#F4F7FC] last:border-b-0">
                          <td className="px-2 py-3">
                            <span className="flex items-center gap-2.5">
                              {r.image_url
                                ? <img src={r.image_url} alt="" className="h-8 w-8 shrink-0 rounded-lg object-cover" />
                                : <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#EAF1FF] text-[#2F6BFF]"><Bell size={14} /></span>}
                              <span className="min-w-0">
                                {r.status === 'draft' || r.status === 'scheduled' ? (
                                  <button type="button" onClick={() => resumeDraft(r.id)}
                                          title={r.status === 'draft' ? 'Reprendre ce brouillon' : 'Modifier cette campagne planifiée'}
                                          className="block max-w-full truncate text-left text-[12.5px] font-semibold text-[#0B1C3F] hover:text-[#2F6BFF] hover:underline">
                                    {r.name}
                                  </button>
                                ) : <span className="block truncate text-[12.5px] font-semibold text-[#0B1C3F]">{r.name}</span>}
                                <span className="block truncate text-[10.5px] text-[#94A3B8]">{r.subtitle}</span>
                              </span>
                            </span>
                          </td>
                          <td className="px-2 py-3">
                            <span className="block text-[12px] text-[#475569]">{r.audience}</span>
                            <span className="block text-[10.5px] text-[#94A3B8]">{nf(r.audience_count)} clients</span>
                          </td>
                          {/* nothing sent yet (draft, scheduled): no count, no rate (QA F03) */}
                          <td className="px-2 py-3 text-right text-[12.5px] tabular-nums text-[#475569]">{r.sent == null ? '—' : nf(r.sent)}</td>
                          <td className="px-2 py-3 text-right text-[12.5px] font-semibold tabular-nums text-[#0B1C3F]">{r.open_rate == null ? '—' : `${r.open_rate}%`}</td>
                          <td className="px-2 py-3"><ResultChip result={r.result} /></td>
                          <td className="px-2 py-3">
                            <span className="rounded-md px-2 py-0.5 text-[11px] font-semibold"
                                  style={{ background: st.bg, color: st.fg }}>{st.label}</span>
                          </td>
                          <td className="px-2 py-3">
                            {r.status === 'sent' ? (
                              <button type="button" onClick={() => setResultOf(r.id)}
                                      className="inline-flex items-center gap-1 text-[12px] font-semibold text-[#2F6BFF] hover:underline">
                                Voir les résultats <ChevronRight size={13} />
                              </button>
                            ) : r.status === 'draft' ? (
                              <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                                <button type="button" onClick={() => resumeDraft(r.id)}
                                        className="text-[12px] font-semibold text-[#2F6BFF] hover:underline">
                                  Reprendre
                                </button>
                                <button type="button" onClick={() => deleteDraft(r)}
                                        className="text-[12px] font-semibold text-[#C0392B] hover:underline">
                                  Supprimer
                                </button>
                              </span>
                            ) : r.status === 'scheduled' ? (
                              <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                                <button type="button" onClick={() => resumeDraft(r.id)}
                                        className="text-[12px] font-semibold text-[#2F6BFF] hover:underline">
                                  Modifier
                                </button>
                                <button type="button" onClick={() => cancelSchedule(r)}
                                        className="text-[12px] font-semibold text-[#C0392B] hover:underline">
                                  Annuler l'envoi
                                </button>
                              </span>
                            ) : <span className="text-[11.5px] text-[#94A3B8]">—</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <Note>{data.open_note}</Note>
            </>
          ) : (
            <p className="py-12 text-center text-[13px] text-[#64748B]">
              Vous n'avez encore envoyé aucune notification. Composez la première ci-dessus.
            </p>
          )}
        </Panel>

        <Panel className="p-5">
          <p className="mb-1 flex flex-wrap items-center gap-2">
            <Sparkles size={16} className="text-[#8B5CF6]" />
            <span className="text-[14.5px] font-bold text-[#0B1C3F]">FidClic AI vous aide</span>
            <span className="rounded-md bg-[#F3EEFF] px-1.5 py-0.5 text-[10.5px] font-bold text-[#6D28D9]">Nouveau</span>
          </p>
          <p className="mb-3 text-[12px] leading-snug text-[#64748B]">
            Besoin d'une idée ? Décrivez votre objectif et FidClic rédige le message pour vous.
          </p>
          <input value={objective} onChange={(e) => setObjective(e.target.value)}
                 placeholder="Faire revenir les clients inactifs"
                 className="mb-2.5 w-full rounded-xl border border-[#E6EEFB] bg-white px-3 py-2.5 text-[12.5px] outline-none focus:border-[#8B5CF6]" />
          <button type="button" onClick={generate} disabled={!objective.trim() || busy === 'ai'}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#8B5CF6] px-4 py-2.5 text-[12.5px] font-semibold text-white transition hover:bg-[#7C3AED] disabled:opacity-50">
            {busy === 'ai' ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            Générer avec l'IA
          </button>
          {aiError && <p className="mt-2 text-[11.5px] text-[#C0392B]">{aiError}</p>}
          <p className="mb-1.5 mt-4 text-[11.5px] font-semibold text-[#475569]">Exemples d'objectifs :</p>
          <ul className="space-y-1.5">
            {['Faire revenir les clients inactifs', 'Promouvoir une offre spéciale',
              'Anniversaire client', 'Augmenter la fréquentation en magasin'].map((x) => (
              <li key={x}>
                <button type="button" onClick={() => setObjective(x)}
                        className="flex items-start gap-1.5 text-left text-[12px] text-[#475569] hover:text-[#2F6BFF]">
                  <Check size={12} className="mt-0.5 shrink-0 text-[#10B981]" /> {x}
                </button>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
