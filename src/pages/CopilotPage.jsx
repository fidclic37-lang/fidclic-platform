import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { openUpgrade } from '../components/PlanAccess';
import {
  Sparkle, CircleCheck, BarChart3, TrendingUp, Heart, Zap, ArrowUp, Users, UserPlus,
  RefreshCcw, Gift, Star, MoreHorizontal, Send, Megaphone, Target, ChevronRight,
  ChevronDown, AlertTriangle, Sun, ShoppingBag, CalendarDays, Maximize2, Minimize2,
  Loader2, X, Check, Lightbulb, Euro, Cake, Repeat, GraduationCap, MapPin, Settings2,
  ArrowRight, Info, MessageSquare,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

/**
 * FidClic IA Copilote — built to the approved mockup.
 *
 * Every figure comes from /api/owner/copilot/page, computed on the shop's own
 * rows; where the server cannot compute one it sends null and the page shows
 * "—". Buttons open something the merchant confirms: the composer pre-filled,
 * an approval dialog, a settings page. The chat answers; it never acts.
 */
const TONES = {
  blue:   { bg: '#EAF1FF', fg: '#2F6BFF' },
  green:  { bg: '#E7F7EE', fg: '#0F8B58' },
  violet: { bg: '#F3EEFF', fg: '#7C3AED' },
  amber:  { bg: '#FFF7E6', fg: '#D97706' },
  rose:   { bg: '#FFF1F3', fg: '#E11D48' },
  slate:  { bg: '#EEF2F8', fg: '#64748B' },
};
const ICONS = {
  users: Users, gift: Gift, star: Star, alert: AlertTriangle, cake: Cake, repeat: Repeat,
  graduation: GraduationCap, pin: MapPin, sun: Sun, bag: ShoppingBag, chart: BarChart3,
  euro: Euro, visits: TrendingUp, reactivated: RefreshCcw, bolt: Zap,
};
const nf = (n) => (n ?? 0).toLocaleString('fr-FR', { maximumFractionDigits: 0 });
const eur = (n, d = 0) => `${(n ?? 0).toLocaleString('fr-FR', { minimumFractionDigits: d, maximumFractionDigits: d })} €`;
const SHADOW = 'shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]';

const Panel = ({ id, children, className = '' }) => (
  <section id={id} className={`scroll-mt-24 rounded-2xl border border-[#E6EEFB] bg-white ${SHADOW} ${className}`}>
    {children}
  </section>
);

const Select = ({ value, onChange, options, small }) => (
  <span className="relative inline-block">
    <select value={value} onChange={(e) => onChange(Number(e.target.value))}
            className={`appearance-none rounded-lg border border-[#E6EEFB] bg-white pl-3 pr-7 font-medium text-[#334155] outline-none focus:border-[#2F6BFF] ${small ? 'py-1 text-[11px]' : 'py-1.5 text-[12px]'}`}>
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
    <ChevronDown size={12} className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
  </span>
);

const Modal = ({ title, onClose, children, wide }) => (
  <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[#0B1C3F]/40 p-4 py-12">
    <div className={`w-full ${wide ? 'max-w-3xl' : 'max-w-md'} rounded-2xl bg-white p-5 shadow-[0_40px_90px_-40px_rgba(11,28,63,.6)]`}>
      <header className="mb-4 flex items-start justify-between gap-3">
        <h3 className="text-[17px] font-bold text-[#0B1C3F]">{title}</h3>
        <button type="button" onClick={onClose} className="text-[#94A3B8] hover:text-[#334155]"><X size={18} /></button>
      </header>
      {children}
    </div>
  </div>
);

/* ── the growth gauge ─────────────────────────────────────────────────── */
const Gauge = ({ pct }) => {
  const r = 70, c = Math.PI * r;
  const fill = pct == null ? 0 : Math.max(0, Math.min(100, pct)) / 100;
  return (
    <svg viewBox="0 0 180 100" className="w-[190px]">
      <defs>
        <linearGradient id="cpGauge" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#10B981" /><stop offset="100%" stopColor="#2F6BFF" />
        </linearGradient>
      </defs>
      <path d="M20 90 A70 70 0 0 1 160 90" fill="none" stroke="#EEF3FB" strokeWidth="13" strokeLinecap="round" />
      <path d="M20 90 A70 70 0 0 1 160 90" fill="none" stroke="url(#cpGauge)" strokeWidth="13"
            strokeLinecap="round" strokeDasharray={`${c * fill} ${c}`} />
    </svg>
  );
};

/* ── the mini bar charts under each activity figure ──────────────────── */
const BAR_COLORS = { blue: ['#9DBBFF', '#2F6BFF'], green: ['#86E0B6', '#10B981'],
                     violet: ['#C9B6FF', '#8B5CF6'], amber: ['#FFD59A', '#F59E0B'] };
const Bars = ({ series, tone }) => {
  const max = Math.max(1, ...series);
  const [lo, hi] = BAR_COLORS[tone] || BAR_COLORS.blue;
  return (
    <div className="mt-2 flex h-[54px] items-end gap-[3px]">
      {series.map((v, i) => (
        <span key={i} className="flex-1 rounded-t-[3px]"
              style={{ height: `${Math.max(6, (v / max) * 100)}%`, background: i >= series.length - 3 ? hi : lo }} />
      ))}
    </div>
  );
};

/* ── the robot ────────────────────────────────────────────────────────── */
const HeroPill = ({ icon: Icon, tone, label }) => (
  <span className="flex items-center gap-2 rounded-xl bg-white/95 px-3 py-2 text-[11.5px] font-semibold text-[#0B1C3F] shadow-[0_10px_24px_-14px_rgba(11,28,63,.45)]">
    <Icon size={16} style={{ color: TONES[tone].fg }} /> {label}
  </span>
);

/* ── a recommendation card ────────────────────────────────────────────── */
const RecCard = ({ r, n, onAct, onFeedback, onMore }) => {
  const [menu, setMenu] = useState(false);
  const t = TONES[r.tone] || TONES.blue;
  const Icon = ICONS[r.icon] || Sparkle;
  return (
    <div className="relative flex flex-col rounded-2xl border border-[#E6EEFB] p-3.5">
      <div className="mb-2.5 flex items-center gap-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#2F6BFF] text-[12px] font-bold text-white">{n}</span>
        <span className="rounded-md px-2 py-0.5 text-[10.5px] font-semibold" style={{ background: t.bg, color: t.fg }}>{r.chip}</span>
        <button type="button" onClick={() => setMenu((m) => !m)} aria-label="Options"
                className="ml-auto rounded-md p-1 text-[#94A3B8] hover:bg-[#F4F7FC] hover:text-[#334155]">
          <MoreHorizontal size={16} />
        </button>
        {menu && (
          <span className="absolute right-3 top-10 z-20 w-44 overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-[0_18px_40px_-20px_rgba(11,28,63,.4)]">
            {[['not_relevant', 'Pas pertinent'], ['later', 'Plus tard (7 jours)']].map(([k, l]) => (
              <button key={k} type="button" onClick={() => { setMenu(false); onFeedback(r, k); }}
                      className="block w-full px-3 py-2 text-left text-[12.5px] text-[#334155] hover:bg-[#F6F9FF]">{l}</button>
            ))}
          </span>
        )}
      </div>
      <div className="mb-3 flex items-start gap-2.5">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl" style={{ background: t.bg, color: t.fg }}>
          <Icon size={19} />
        </span>
        <div className="min-w-0">
          <p className="text-[14px] font-bold leading-tight text-[#0B1C3F]">{r.title}</p>
          <p className="mt-0.5 text-[11.5px] leading-snug text-[#64748B]">{r.body}</p>
        </div>
      </div>
      <div className="mb-3 mt-auto rounded-xl bg-[#F8FAFF] px-3 py-2">
        <p className="mb-1 text-center text-[11px] text-[#64748B]">Impact estimé</p>
        <div className="flex items-center justify-center gap-3">
          {r.metrics.map((m, i) => {
            const MI = ICONS[m.icon] || BarChart3;
            return (
              <React.Fragment key={i}>
                {i > 0 && <span className="h-4 w-px bg-[#E2E8F0]" />}
                <span className="flex items-center gap-1.5 text-[12.5px] font-bold text-[#0B1C3F]">
                  <MI size={14} className={i === 0 ? 'text-[#10B981]' : 'text-[#7C3AED]'} /> {m.label}
                </span>
              </React.Fragment>
            );
          })}
        </div>
      </div>
      <div className="flex gap-2">
        <button type="button" onClick={() => onAct(r)}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-[#2F6BFF] px-3 py-2.5 text-[13px] font-semibold text-white transition hover:bg-[#2559DB]">
          {r.kind === 'campaign' ? <Send size={14} /> : r.kind === 'suggestion' ? <Star size={14} /> : <Gift size={14} />}
          {r.cta.label}
        </button>
        <button type="button" onClick={() => onMore(r)} aria-label="Plus d'actions"
                className="rounded-xl border border-[#E6EEFB] px-3 text-[#2F6BFF] transition hover:border-[#2F6BFF]">
          <MoreHorizontal size={16} />
        </button>
      </div>
    </div>
  );
};

/* ── page ─────────────────────────────────────────────────────────────── */
export default function CopilotPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [d, setD] = useState(null);
  const [horizon, setHorizon] = useState(30);
  const [days, setDays] = useState(7);
  const [error, setError] = useState('');
  const [flash, setFlash] = useState('');
  const [modal, setModal] = useState(null);       // {type, ...}
  const [busy, setBusy] = useState('');
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState('');
  const [thinking, setThinking] = useState(false);
  const [bigChat, setBigChat] = useState(false);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  const firstName = useMemo(() => {
    const raw = user?.first_name || user?.name || (user?.email || '').split('@')[0] || '';
    // "demo.owner@…" → "Demo": an e-mail local part is not a first name.
    const first = String(raw).trim().split(/[\s._-]+/)[0] || '';
    return first ? first.charAt(0).toUpperCase() + first.slice(1) : '';
  }, [user]);

  const load = useCallback(() => {
    ownerAPI.copilotPage({ horizon, days })
      .then(({ data }) => { setD(data); setError(''); })
      .catch((e) => setError(e?.response?.data?.detail || 'Impossible de charger FidClic IA.'));
  }, [horizon, days]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    ownerAPI.copilotChatHistory().then(({ data }) => setMessages(data.messages || [])).catch(() => {});
  }, []);
  useEffect(() => { listRef.current?.scrollTo({ top: 1e6, behavior: 'smooth' }); }, [messages, thinking]);

  /* what a button does — the same four kinds everywhere on the page */
  const run = (cta, key) => {
    if (!cta) return;
    if (key) ownerAPI.copilotFeedback(key, 'accepted').catch(() => {});
    if (cta.kind === 'template') {
      const q = new URLSearchParams({ template: cta.template });
      if (cta.day !== undefined && cta.day !== null) q.set('day', String(cta.day));
      navigate(`/dashboard/campaigns?${q.toString()}`);
    } else if (cta.kind === 'navigate') navigate(cta.to);
    else if (cta.kind === 'suggestion') setModal({ type: 'suggestion', rec: cta.rec });
    else if (cta.kind === 'google_review') setModal({ type: 'google' });
    else if (cta.kind === 'activate') activate(cta.action);
  };

  const act = (r) => {
    if (r.kind === 'suggestion') { ownerAPI.copilotFeedback(r.key, 'accepted').catch(() => {}); setModal({ type: 'suggestion', rec: r }); return; }
    run(r.cta, r.key);
  };

  const activate = async (action) => {
    setBusy(action);
    try { await ownerAPI.activateInsight(action); setFlash('Offre anniversaire activée — modifiable dans Automatisations.'); load(); }
    catch (e) { setError(e?.response?.data?.detail || "L'activation n'a pas abouti."); }
    finally { setBusy(''); }
  };

  const feedback = async (r, kind) => {
    try {
      await ownerAPI.copilotFeedback(r.key, kind);
      setFlash(kind === 'later' ? `« ${r.title} » reviendra dans 7 jours.` : `« ${r.title} » ne vous sera plus proposée. FidClic IA en tient compte.`);
      load();
    } catch { setError("Votre retour n'a pas pu être enregistré."); }
  };

  // The one Autopilot (Automatisations › Autopilot): this switch turns its
  // daily and weekly campaigns on or off; their days and times are set there.
  const toggleAutopilot = async () => {
    if (d.plan.autopilot_plan_ok === false) {
      openUpgrade({ feature: 'ai', label: 'Autopilot', message: "L'Autopilot est inclus dans l'offre Pro AI.", upgrade: { label: 'Pro AI' } });
      return;
    }
    setBusy('autopilot');
    try {
      const { data } = await ownerAPI.copilotAutopilot(!d.plan.autopilot);
      setFlash(data.autopilot
        ? `Autopilot activé : ${data.prepared} campagne${data.prepared > 1 ? 's' : ''} préparée${data.prepared > 1 ? 's' : ''}, à valider dans Automatisations. Rien n'est envoyé sans votre validation.`
        : 'Autopilot désactivé.');
      load();
    } catch (e) { setError(e?.response?.data?.detail?.message || e?.response?.data?.detail || "L'Autopilot n'a pas pu être changé."); }
    finally { setBusy(''); }
  };

  // The plan's steps are prepared when the owner asks.
  const preparePlan = async () => {
    setBusy('prepare');
    try {
      const { data } = await ownerAPI.copilotPreparePlan();
      setFlash(data.prepared ? `${data.prepared} étape${data.prepared > 1 ? 's' : ''} préparée${data.prepared > 1 ? 's' : ''} : cliquez sur une étape « Préparée » pour la valider.`
        : 'Les étapes du plan sont déjà prêtes.');
      load();
    } catch (e) { setError(e?.response?.data?.detail || "Les étapes n'ont pas pu être préparées."); }
    finally { setBusy(''); }
  };

  const approve = async (step) => {
    setBusy(step.id);
    try {
      const { data } = await ownerAPI.copilotApprove(step.id);
      setModal(null);
      setFlash(data.status === 'sent' ? `« ${step.title} » envoyée à ${nf(data.audience)} clients.`
        : `« ${step.title} » programmée pour le ${new Date(data.scheduled_for).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' })}.`);
      load();
    } catch (e) { setError(e?.response?.data?.detail || "La validation n'a pas abouti."); setModal(null); }
    finally { setBusy(''); }
  };

  const ask = async (text) => {
    const q = (text ?? draft).trim();
    if (!q) return;
    setDraft('');
    setMessages((m) => [...m, { role: 'user', text: q }]);
    setThinking(true);
    try {
      const { data } = await ownerAPI.copilotChat(q);
      setMessages((m) => [...m, { role: 'assistant', text: data.reply, actions: data.actions || [] }]);
    } catch (e) {
      setMessages((m) => [...m, { role: 'assistant', text: e?.response?.data?.detail || "Je n'ai pas pu répondre. Réessayez dans un instant.", actions: [] }]);
    } finally { setThinking(false); }
  };

  if (!d) {
    return (
      <div className="cp flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]">
        {error || <><Loader2 size={16} className="animate-spin" /> FidClic IA analyse votre commerce…</>}
      </div>
    );
  }

  const g = d.growth;
  const growthRows = { visits: 'green', new: 'blue', reactivated: 'violet', retention: 'amber' };
  const recs = d.recommendations;
  const PROMPT_ICONS = [TrendingUp, RefreshCcw, GraduationCap, BarChart3, Gift, MessageSquare];

  const chat = (
    <Panel className={`flex flex-col p-4 ${bigChat ? 'h-full' : ''}`}>
      <header className="mb-3 flex items-center gap-2">
        <Sparkle size={18} className="text-[#2F6BFF]" />
        <h2 className="min-w-0 truncate text-[14px] font-bold text-[#0B1C3F]">Discutez avec votre IA Copilote</h2>
        <span className={`ml-auto inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-[10.5px] font-semibold ${d.assistant.online ? 'bg-[#E7F7EE] text-[#0F8B58]' : 'bg-[#EEF2F8] text-[#64748B]'}`}
              title={d.assistant.online ? undefined : 'Le modèle de langage n\'est pas configuré : les réponses viennent directement de vos données.'}>
          <span className={`h-1.5 w-1.5 rounded-full ${d.assistant.online ? 'bg-[#10B981]' : 'bg-[#94A3B8]'}`} />
          {d.assistant.online ? 'En ligne' : 'Mode données'}
        </span>
        {/* named after what it does now (QA R7 F38: « Agrandir » also on the button that reduces) */}
        <button type="button" onClick={() => setBigChat((b) => !b)} aria-label={bigChat ? 'Réduire' : 'Agrandir'}
                title={bigChat ? 'Réduire' : 'Agrandir'} aria-expanded={bigChat}
                className="rounded-md p-1 text-[#64748B] hover:bg-[#F4F7FC]">
          {bigChat ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
        </button>
      </header>

      <div ref={listRef} className={`space-y-3 overflow-y-auto pr-1 ${bigChat ? 'flex-1' : 'max-h-[420px]'}`}>
        <div className="flex items-start gap-2.5">
          <img src="/copilot/robot-avatar.webp" alt="" className="h-12 w-12 shrink-0 object-contain" />
          <div className="space-y-2">
            <div className="rounded-2xl rounded-tl-md bg-[#EEF3FF] px-3.5 py-2.5 text-[12.5px] leading-snug text-[#1E293B]">
              <p className="font-bold text-[#0B1C3F]">Bonjour {firstName || 'à vous'} ! 👋</p>
              Je suis votre IA Copilote. J'analyse vos données en temps réel et je vous propose des actions
              concrètes pour faire grandir votre commerce.
            </div>
            <div className="inline-block rounded-2xl bg-[#EEF3FF] px-3.5 py-2 text-[12.5px] text-[#1E293B]">
              Que souhaitez-vous faire aujourd'hui ?
            </div>
          </div>
        </div>
        {messages.map((m, i) => (
          m.role === 'user' ? (
            <div key={i} className="flex justify-end">
              <span className="max-w-[85%] rounded-2xl rounded-tr-md bg-[#2F6BFF] px-3.5 py-2 text-[12.5px] text-white">{m.text}</span>
            </div>
          ) : (
            <div key={i} className="flex items-start gap-2.5">
              <img src="/copilot/robot-avatar.webp" alt="" className="h-8 w-8 shrink-0 object-contain" />
              <div className="min-w-0 max-w-[88%]">
                <div className="whitespace-pre-line rounded-2xl rounded-tl-md bg-[#EEF3FF] px-3.5 py-2.5 text-[12.5px] leading-snug text-[#1E293B]">{m.text}</div>
                {m.actions?.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {m.actions.map((a, j) => (
                      <button key={j} type="button" onClick={() => run(a, a.key)}
                              className="inline-flex items-center gap-1 rounded-lg bg-[#2F6BFF] px-2.5 py-1.5 text-[11.5px] font-semibold text-white hover:bg-[#2559DB]">
                        {a.label} <ArrowRight size={12} />
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )
        ))}
        {thinking && (
          <div className="flex items-center gap-2 pl-10 text-[12px] text-[#64748B]"><Loader2 size={13} className="animate-spin" /> FidClic IA réfléchit…</div>
        )}
      </div>

      <div className={`mt-3 flex flex-wrap gap-2 ${messages.length ? '' : 'flex-col items-start'}`}>
        {d.assistant.prompts.map((p, i) => {
          const PI = PROMPT_ICONS[i] || MessageSquare;
          const other = i === d.assistant.prompts.length - 1;
          return (
            <button key={p} type="button" disabled={thinking}
                    onClick={() => (other ? inputRef.current?.focus() : ask(p))}
                    className="inline-flex items-center gap-2 rounded-xl border border-[#D7E3FB] bg-white px-3 py-1.5 text-[12px] font-medium text-[#1D4ED8] transition hover:border-[#2F6BFF] disabled:opacity-50">
              <PI size={14} /> {p}
            </button>
          );
        })}
      </div>

      <form onSubmit={(e) => { e.preventDefault(); ask(); }} className="mt-3 flex items-center gap-2">
        <input ref={inputRef} value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={500}
               placeholder="Posez votre question..."
               className="min-w-0 flex-1 rounded-xl border border-[#E6EEFB] px-3.5 py-2.5 text-[13px] outline-none focus:border-[#2F6BFF]" />
        <button type="submit" disabled={!draft.trim() || thinking} aria-label="Envoyer"
                className="flex h-10 w-11 shrink-0 items-center justify-center rounded-xl bg-[#2F6BFF] text-white transition hover:bg-[#2559DB] disabled:opacity-50">
          <Send size={17} />
        </button>
      </form>
    </Panel>
  );

  return (
    <div className="cp">
      {flash && (
        <div className="mb-3 flex items-center gap-2 rounded-xl bg-[#E7F7EE] px-4 py-2.5 text-[12.5px] font-medium text-[#0F8B58]">
          <Check size={15} /> {flash}
          <button type="button" onClick={() => setFlash('')} className="ml-auto opacity-70 hover:opacity-100"><X size={14} /></button>
        </div>
      )}
      {error && <p className="mb-3 rounded-xl bg-[#FEECEC] px-4 py-2.5 text-[12.5px] text-[#C0392B]">{error}</p>}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        {/* ── left column ── */}
        <div className="min-w-0 space-y-4">
          <header>
            <div className="flex items-center gap-3">
              <Sparkle size={44} strokeWidth={2.2} className="shrink-0 text-[#2F6BFF]" />
              <div className="min-w-0">
                <h1 className="flex flex-wrap items-center gap-2.5 text-[32px] font-bold leading-tight text-[#0B1C3F]">
                  FidClic IA Copilote
                  <span className="rounded-lg bg-[#2F6BFF] px-2.5 py-0.5 text-[12px] font-bold tracking-wide text-white">BETA</span>
                </h1>
                <p className="text-[15px] text-[#475569]">Votre assistant stratégique qui transforme vos données en croissance.</p>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {['Analyse vos données', 'Identifie des opportunités', 'Recommande des actions', 'Mesure les résultats', "S'adapte à votre activité"].map((c) => (
                <span key={c} className="inline-flex items-center gap-1.5 rounded-lg border border-[#E6EEFB] bg-white px-2.5 py-1.5 text-[11.5px] font-medium text-[#334155]">
                  <CircleCheck size={14} className="text-[#10B981]" /> {c}
                </span>
              ))}
            </div>
          </header>

          {/* hero */}
          <section className="relative overflow-hidden rounded-2xl border border-[#DCE3FF] p-6"
                   style={{ background: 'linear-gradient(110deg,#E4E3FF 0%,#E3EBFF 45%,#DCE8FF 100%)' }}>
            <div className="relative z-10 max-w-[420px]">
              <p className="text-[27px] font-bold leading-tight text-[#0B1C3F]">Bonjour {firstName || 'à vous'} ! 👋</p>
              <p className="mt-1 text-[23px] font-bold leading-tight text-[#0B1C3F]">
                Aujourd'hui, <span className="text-[#2F6BFF]">voici comment faire grandir votre commerce.</span>
              </p>
              <p className="mt-3 text-[13.5px] leading-snug text-[#334155]">
                J'ai analysé vos ventes, vos clients et le marché.<br />
                Voici les opportunités les plus impactantes pour vous.
              </p>
            </div>
            <Sparkle size={26} className="absolute left-[47%] top-[22%] hidden text-[#2F6BFF] lg:block" fill="#2F6BFF" />
            <img src="/copilot/robot-hero.webp" alt="" className="pointer-events-none absolute bottom-[-6px] right-[190px] hidden h-[200px] object-contain md:block" />
            <div className="absolute right-4 top-1/2 hidden -translate-y-1/2 flex-col gap-2 md:flex">
              <HeroPill icon={BarChart3} tone="green" label="Plus de clients" />
              <HeroPill icon={TrendingUp} tone="blue" label="Plus de revenus" />
              <HeroPill icon={Heart} tone="rose" label="Clients plus fidèles" />
              <HeroPill icon={Zap} tone="amber" label="Actions simples" />
            </div>
          </section>

          {/* recommendations */}
          <Panel className="p-4">
            <header className="mb-3 flex flex-wrap items-center gap-2">
              <Sparkle size={18} className="text-[#2F6BFF]" />
              <h2 className="text-[15px] font-bold text-[#0B1C3F]">Mes 3 recommandations prioritaires</h2>
              {recs.total > 0 && (
                <button type="button" onClick={() => setModal({ type: 'recs' })}
                        className="ml-auto text-[12.5px] font-semibold text-[#2F6BFF] hover:underline">
                  Voir toutes ({recs.total})
                </button>
              )}
            </header>
            {recs.top.length ? (
              <div className="grid gap-3 lg:grid-cols-3">
                {recs.top.map((r, i) => (
                  <RecCard key={r.key} r={r} n={i + 1} onAct={act} onFeedback={feedback}
                           onMore={(x) => setModal({ type: 'more', rec: x })} />
                ))}
              </div>
            ) : (
              <p className="py-10 text-center text-[13px] text-[#64748B]">
                Pas encore assez de données pour recommander une action. Les recommandations apparaîtront
                dès vos premières visites enregistrées.
              </p>
            )}
          </Panel>

          <div className="grid gap-4 lg:grid-cols-[1.25fr_1fr]">
            {/* activity */}
            <Panel className="p-4">
              <header className="mb-3 flex flex-wrap items-center gap-2">
                <Send size={17} className="text-[#2F6BFF]" />
                <h2 className="text-[15px] font-bold text-[#0B1C3F]">Analyse de votre activité</h2>
                <span className="ml-auto">
                  <Select small value={days} onChange={setDays}
                          options={[[7, '7 derniers jours'], [30, '30 derniers jours'], [90, '90 derniers jours']]} />
                </span>
              </header>
              <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                {d.activity.cards.map((c) => (
                  <div key={c.key} className="rounded-xl border border-[#EEF3FB] p-2.5">
                    <p className="truncate text-[10.5px] text-[#64748B]">{c.label}</p>
                    <p className="whitespace-nowrap text-[16px] font-bold leading-tight text-[#0B1C3F] tabular-nums">
                      {c.unit === '€' ? eur(c.value, c.key === 'basket' ? 2 : 0) : nf(c.value)}
                    </p>
                    {c.delta != null ? (
                      <span className="mt-1 inline-block rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold"
                            style={c.delta >= 0 ? { background: '#E7F7EE', color: '#0F8B58' } : { background: '#FEECEC', color: '#C0392B' }}>
                        {c.delta >= 0 ? '+ ' : '- '}{Math.abs(c.delta)}%
                      </span>
                    ) : <span className="mt-1 inline-block text-[10.5px] text-[#94A3B8]">—</span>}
                    <Bars series={c.series} tone={c.tone} />
                  </div>
                ))}
              </div>
            </Panel>

            {/* opportunities */}
            <Panel className="p-4">
              <header className="mb-2 flex items-center gap-2">
                <Settings2 size={17} className="text-[#2F6BFF]" />
                <h2 className="text-[15px] font-bold text-[#0B1C3F]">Opportunités détectées par l'IA</h2>
                {d.opportunities.total > 4 && (
                  <button type="button" onClick={() => setModal({ type: 'opps' })}
                          className="ml-auto text-[12px] font-semibold text-[#2F6BFF] hover:underline">Voir toutes</button>
                )}
              </header>
              {d.opportunities.top.length ? (
                <ul className="divide-y divide-[#EEF3FB]">
                  {d.opportunities.top.map((o) => {
                    const t = TONES[o.tone] || TONES.blue;
                    const Icon = ICONS[o.icon] || Target;
                    return (
                      <li key={o.key}>
                        <button type="button" onClick={() => run(o.cta)}
                                className="flex w-full items-center gap-2.5 py-2 text-left hover:bg-[#FAFBFF]">
                          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl" style={{ background: t.bg, color: t.fg }}>
                            <Icon size={17} />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-[12.5px] font-bold text-[#0B1C3F]">{o.title}</span>
                            <span className="block truncate text-[11px] text-[#64748B]">{o.body}</span>
                          </span>
                          <span className="shrink-0 text-right">
                            <span className="block text-[13px] font-bold text-[#0F8B58] tabular-nums">+{nf(o.potential)} €</span>
                            <span className="block text-[10px] text-[#94A3B8]">potentiel</span>
                          </span>
                          <ChevronRight size={15} className="shrink-0 text-[#94A3B8]" />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="py-8 text-center text-[12.5px] text-[#64748B]">Aucune opportunité détectée pour l'instant.</p>
              )}
            </Panel>
          </div>

          {/* plan — the whole shop's, the owner's; elsewhere a note says where it lives */}
          {d.plan.available === false ? (
          <Panel id="plan" className="p-4">
            <header className="mb-2 flex items-center gap-2">
              <CalendarDays size={18} className="text-[#2F6BFF]" />
              <h2 className="text-[15px] font-bold text-[#0B1C3F]">Plan d'action automatique sur 7 jours</h2>
            </header>
            <p className="flex items-start gap-1.5 text-[12.5px] leading-snug text-[#64748B]">
              <Info size={14} className="mt-px shrink-0" /> {d.plan.note}
            </p>
          </Panel>
          ) : (
          <Panel id="plan" className="p-4">
            <header className="mb-3 flex flex-wrap items-center gap-2">
              <CalendarDays size={18} className="text-[#2F6BFF]" />
              <h2 className="text-[15px] font-bold text-[#0B1C3F]">Plan d'action automatique sur 7 jours</h2>
              <span className="ml-auto inline-flex items-center gap-2 text-[12px] text-[#334155]">
                <span className={`h-2 w-2 rounded-full ${d.plan.autopilot ? 'bg-[#10B981]' : 'bg-[#CBD5E1]'}`} />
                Mode Autopilot
                <button type="button" onClick={toggleAutopilot} disabled={busy === 'autopilot'} role="switch"
                        aria-checked={d.plan.autopilot}
                        title="L'Autopilot prépare une campagne chaque jour et chaque semaine ; rien n'est envoyé sans votre validation."
                        className={`relative h-6 w-11 rounded-full transition ${d.plan.autopilot ? 'bg-[#2F6BFF]' : 'bg-[#CBD5E1]'}`}>
                  <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${d.plan.autopilot ? 'left-[22px]' : 'left-0.5'}`} />
                </button>
              </span>
              <button type="button" onClick={() => navigate('/dashboard/automations#autopilot')}
                      className="text-[12.5px] font-semibold text-[#6D28D9] hover:underline">Régler l'Autopilot</button>
              <button type="button" onClick={preparePlan} disabled={busy === 'prepare'}
                      className="text-[12.5px] font-semibold text-[#2F6BFF] hover:underline disabled:opacity-50">Préparer les étapes</button>
              <button type="button" onClick={() => setModal({ type: 'plan' })}
                      className="text-[12.5px] font-semibold text-[#2F6BFF] hover:underline">Modifier le plan</button>
            </header>
            <div className="flex items-stretch gap-1 overflow-x-auto pb-1">
              {d.plan.steps.map((s, i) => {
                const t = TONES[s.tone] || TONES.blue;
                const SIcon = s.kind === 'analysis' ? Target : s.kind === 'setup' ? Star : [RefreshCcw, Users, Megaphone][i % 3];
                const clickable = s.can_approve || s.kind !== 'campaign';
                return (
                  <React.Fragment key={s.id}>
                    {i > 0 && <ChevronRight size={16} className="mt-7 shrink-0 text-[#94A3B8]" />}
                    <button type="button" disabled={!clickable}
                            onClick={() => (s.can_approve ? setModal({ type: 'approve', step: s }) : run(s.cta))}
                            className="flex min-w-[150px] flex-1 items-start gap-2.5 rounded-xl border border-[#E6EEFB] p-2.5 text-left transition hover:border-[#C7DBFF] disabled:cursor-default">
                      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full" style={{ background: t.bg, color: t.fg }}>
                        <SIcon size={16} />
                      </span>
                      <span className="min-w-0">
                        <span className="block text-[12.5px] font-bold text-[#0B1C3F]">{s.when}</span>
                        <span className="block truncate text-[11.5px] text-[#64748B]">{s.title}</span>
                        <span className="mt-1.5 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold"
                              style={{ background: t.bg, color: t.fg }}>
                          {s.status === 'À faire' || s.status === 'Envoyée' || s.status === 'Activée' ? <Check size={11} strokeWidth={3} /> : <ArrowRight size={11} />}
                          {s.status}
                        </span>
                      </span>
                    </button>
                  </React.Fragment>
                );
              })}
            </div>
            <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-snug text-[#94A3B8]">
              <Info size={12} className="mt-px shrink-0" />
              « Préparer les étapes » rédige les campagnes du plan ; rien n'est envoyé tant que vous n'avez pas validé
              l'étape. {d.plan.autopilot ? "L'Autopilot est actif : ses campagnes du jour et de la semaine vous attendent dans Automatisations." : ''}
            </p>
          </Panel>
          )}
        </div>

        {/* ── right column ── */}
        <div className="min-w-0 space-y-4">
          <Panel className="p-4">
            <header className="mb-2 flex flex-wrap items-center gap-2">
              <h2 className="text-[14px] font-bold text-[#0B1C3F] sm:whitespace-nowrap">Votre potentiel de croissance ce mois</h2>
              <span className="ml-auto">
                <Select small value={horizon} onChange={setHorizon}
                        options={[[7, '7 prochains jours'], [30, '30 prochains jours'], [90, '90 prochains jours']]} />
              </span>
            </header>
            <div className="flex items-center gap-3">
              <div className="relative flex shrink-0 flex-col items-center">
                <Gauge pct={g.pct} />
                <div className="-mt-12 text-center">
                  <p className="text-[32px] font-bold leading-none text-[#0B1C3F] tabular-nums">{g.pct == null ? '—' : `+${g.pct}%`}</p>
                  <p className="mt-1 text-[11.5px] text-[#475569]">de chiffre d'affaires estimé</p>
                  <p className="mt-2 text-[12px] text-[#475569]">Soit environ <strong className="text-[#0F8B58]">+{eur(g.euros)}</strong></p>
                </div>
              </div>
              <ul className="min-w-0 flex-1 divide-y divide-[#EEF3FB]">
                {g.rows.map((r) => {
                  const tone = growthRows[r.key] || 'blue';
                  const t = TONES[tone];
                  const Icon = ICONS[r.icon] || UserPlus;
                  return (
                    <li key={r.key} className="flex items-center gap-2.5 py-2">
                      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg" style={{ background: t.bg, color: t.fg }}>
                        <Icon size={17} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[15px] font-bold leading-tight tabular-nums" style={{ color: t.fg }}>
                          {r.value == null ? '—' : `+${nf(r.value)}${r.unit || ''}`}
                        </span>
                        <span className="block text-[11px] text-[#64748B]">{r.label}</span>
                      </span>
                      {r.value != null && r.value > 0 && <ArrowUp size={15} className="shrink-0 text-[#10B981]" />}
                    </li>
                  );
                })}
              </ul>
            </div>
            <p className="mt-2 flex items-start gap-1.5 text-[10.5px] leading-snug text-[#94A3B8]">
              <Info size={11} className="mt-px shrink-0" /> {g.note}
            </p>
          </Panel>

          {!bigChat && chat}

          <Panel className="p-4">
            <header className="mb-2.5 flex items-center gap-2">
              <Lightbulb size={18} className="text-[#2F6BFF]" />
              <h2 className="text-[14px] font-bold text-[#0B1C3F]">Ce que FidClic IA apprend pour vous</h2>
            </header>
            <ul className="space-y-2">
              {d.learning.map((l) => (
                <li key={l} className="flex items-center gap-2.5 text-[12.5px] text-[#334155]">
                  <CircleCheck size={17} className="shrink-0 fill-[#10B981] text-white" /> {l}
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>

      {bigChat && (
        <div className="fixed inset-0 z-40 flex items-stretch justify-center bg-[#0B1C3F]/40 p-4 md:p-10">
          <div className="flex w-full max-w-3xl">{chat}</div>
        </div>
      )}

      {/* ── modals ── */}
      {modal?.type === 'recs' && (
        <Modal wide title={`Toutes les recommandations (${recs.total})`} onClose={() => setModal(null)}>
          <div className="grid gap-3 sm:grid-cols-2">
            {recs.all.map((r, i) => (
              <RecCard key={r.key} r={r} n={i + 1} onAct={(x) => { setModal(null); act(x); }}
                       onFeedback={feedback} onMore={(x) => setModal({ type: 'more', rec: x })} />
            ))}
          </div>
        </Modal>
      )}
      {modal?.type === 'opps' && (
        <Modal wide title="Toutes les opportunités détectées" onClose={() => setModal(null)}>
          <ul className="divide-y divide-[#EEF3FB]">
            {d.opportunities.all.map((o) => (
              <li key={o.key}>
                <button type="button" onClick={() => { setModal(null); run(o.cta); }}
                        className="flex w-full items-center gap-3 py-2.5 text-left hover:bg-[#FAFBFF]">
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-bold text-[#0B1C3F]">{o.title}</span>
                    <span className="block text-[11.5px] text-[#64748B]">{o.body}</span>
                  </span>
                  <span className="text-[13px] font-bold text-[#0F8B58]">+{nf(o.potential)} €</span>
                  <ChevronRight size={15} className="text-[#94A3B8]" />
                </button>
              </li>
            ))}
          </ul>
        </Modal>
      )}
      {modal?.type === 'more' && (
        <Modal title={modal.rec.title} onClose={() => setModal(null)}>
          <div className="space-y-2">
            {modal.rec.cta.kind === 'template' && (
              <button type="button" onClick={() => { setModal(null); run(modal.rec.cta, modal.rec.key); }}
                      className="flex w-full items-center gap-2 rounded-xl border border-[#E6EEFB] px-3 py-2.5 text-left text-[13px] font-medium text-[#334155] hover:border-[#2F6BFF]">
                <Send size={15} className="text-[#2F6BFF]" /> Personnaliser le message avant l'envoi
              </button>
            )}
            <button type="button" onClick={() => { setModal(null); navigate('/dashboard/segmentation'); }}
                    className="flex w-full items-center gap-2 rounded-xl border border-[#E6EEFB] px-3 py-2.5 text-left text-[13px] font-medium text-[#334155] hover:border-[#2F6BFF]">
              <Users size={15} className="text-[#2F6BFF]" /> Voir les segments de clients
            </button>
            {[['later', 'Me le rappeler dans 7 jours'], ['not_relevant', 'Ne plus me proposer']].map(([k, l]) => (
              <button key={k} type="button" onClick={() => { setModal(null); feedback(modal.rec, k); }}
                      className="flex w-full items-center gap-2 rounded-xl border border-[#E6EEFB] px-3 py-2.5 text-left text-[13px] font-medium text-[#334155] hover:border-[#2F6BFF]">
                <X size={15} className="text-[#94A3B8]" /> {l}
              </button>
            ))}
            <p className="pt-1 text-[11px] text-[#94A3B8]">
              {modal.rec.audience ? `${nf(modal.rec.audience)} clients concernés · ` : ''}impact calculé sur vos propres clients.
            </p>
          </div>
        </Modal>
      )}
      {modal?.type === 'suggestion' && (
        <Modal title={modal.rec.title} onClose={() => setModal(null)}>
          <p className="mb-4 text-[13px] leading-snug text-[#334155]">{modal.rec.detail || modal.rec.body}</p>
          <div className="flex justify-end gap-2.5">
            <button type="button" onClick={() => setModal(null)}
                    className="rounded-xl border border-[#E6EEFB] px-4 py-2.5 text-[13px] font-semibold text-[#334155]">Fermer</button>
            <button type="button" onClick={() => { setModal(null); navigate(modal.rec.cta.to || '/dashboard/card'); }}
                    className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white">
              Configurer ma carte <ArrowRight size={14} />
            </button>
          </div>
        </Modal>
      )}
      {modal?.type === 'approve' && (
        <Modal title={`Valider « ${modal.step.title} »`} onClose={() => setModal(null)}>
          <p className="mb-4 text-[13px] leading-snug text-[#334155]">
            {modal.step.when === "Aujourd'hui"
              ? <>La campagne sera <strong>envoyée maintenant</strong> à {nf(modal.step.audience)} clients (notification push + carte Wallet).</>
              : <>La campagne sera <strong>programmée</strong> pour {modal.step.when.toLowerCase() === 'demain' ? 'demain' : `le ${modal.step.when}`} et envoyée à {nf(modal.step.audience)} clients.</>}
          </p>
          <div className="flex flex-wrap justify-end gap-2.5">
            <button type="button" onClick={() => { const s = modal.step; setModal(null); run(s.cta); }}
                    className="rounded-xl border border-[#E6EEFB] px-4 py-2.5 text-[13px] font-semibold text-[#334155]">Modifier le message</button>
            <button type="button" onClick={() => approve(modal.step)} disabled={busy === modal.step.id}
                    className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white disabled:opacity-50">
              {busy === modal.step.id && <Loader2 size={14} className="animate-spin" />}
              {modal.step.when === "Aujourd'hui" ? 'Envoyer maintenant' : 'Programmer'}
            </button>
          </div>
        </Modal>
      )}
      {modal?.type === 'plan' && (
        <PlanEditor plan={d.plan} recs={recs.all} onClose={() => setModal(null)}
                    onSaved={(msg) => { setModal(null); setFlash(msg); load(); }} />
      )}
      {modal?.type === 'google' && (
        <GoogleModal onClose={() => setModal(null)}
                     onSaved={() => { setModal(null); setFlash('Invitations aux avis Google activées.'); load(); }} />
      )}
    </div>
  );
}

/* ── "Modifier le plan" ───────────────────────────────────────────────── */
const DAY_LABELS = ["Aujourd'hui", 'Demain', 'J+2', 'J+3', 'J+4', 'J+5', 'J+6'];
function PlanEditor({ plan, recs, onClose, onSaved }) {
  const start = new Date(`${plan.start}T12:00:00`);
  const offsetOf = (iso) => Math.round((new Date(`${iso}T12:00:00`) - start) / 86400000);
  const [steps, setSteps] = useState(() => plan.steps.map((s) => ({ key: s.key, title: s.title, offset: offsetOf(s.date) })));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const addable = recs.filter((r) => r.kind !== 'suggestion' && !steps.some((s) => s.key === r.key));
  const save = async () => {
    setBusy(true); setErr('');
    try { await ownerAPI.copilotEditPlan(steps.map(({ key, offset }) => ({ key, offset }))); onSaved('Plan mis à jour.'); }
    catch (e) { setErr(e?.response?.data?.detail || "Le plan n'a pas pu être enregistré."); setBusy(false); }
  };
  const rebuild = async () => {
    setBusy(true);
    try { await ownerAPI.copilotRebuildPlan(); onSaved('Nouveau plan généré à partir de vos données du jour.'); }
    catch { setErr("Le plan n'a pas pu être régénéré."); setBusy(false); }
  };
  return (
    <Modal title="Modifier le plan" onClose={onClose}>
      <ul className="mb-3 space-y-2">
        {steps.map((s, i) => (
          <li key={s.key} className="flex items-center gap-2 rounded-xl border border-[#E6EEFB] p-2.5">
            <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-[#0B1C3F]">{s.title}</span>
            <Select small value={s.offset} onChange={(v) => setSteps((a) => a.map((x, j) => (j === i ? { ...x, offset: v } : x)))}
                    options={DAY_LABELS.map((l, k) => [k, l])} />
            <button type="button" onClick={() => setSteps((a) => a.filter((_, j) => j !== i))} aria-label="Retirer"
                    className="rounded-md p-1 text-[#94A3B8] hover:bg-[#FEECEC] hover:text-[#C0392B]"><X size={14} /></button>
          </li>
        ))}
      </ul>
      {addable.length > 0 && (
        <div className="mb-3">
          <p className="mb-1.5 text-[11.5px] font-medium text-[#64748B]">Ajouter une étape</p>
          <div className="flex flex-wrap gap-1.5">
            {addable.map((r) => (
              <button key={r.key} type="button"
                      onClick={() => setSteps((a) => [...a, { key: r.key, title: r.title, offset: Math.min(6, a.length) }])}
                      className="rounded-lg border border-[#D7E3FB] px-2.5 py-1 text-[11.5px] font-medium text-[#1D4ED8] hover:border-[#2F6BFF]">
                + {r.title}
              </button>
            ))}
          </div>
        </div>
      )}
      {err && <p className="mb-3 rounded-xl bg-[#FEECEC] px-3 py-2 text-[12px] text-[#C0392B]">{err}</p>}
      <div className="flex flex-wrap justify-between gap-2.5">
        <button type="button" onClick={rebuild} disabled={busy}
                className="rounded-xl border border-[#E6EEFB] px-3 py-2.5 text-[12.5px] font-semibold text-[#334155]">Régénérer le plan</button>
        <button type="button" onClick={save} disabled={busy || !steps.length}
                className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white disabled:opacity-50">
          {busy && <Loader2 size={14} className="animate-spin" />} Enregistrer
        </button>
      </div>
    </Modal>
  );
}

function GoogleModal({ onClose, onSaved }) {
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const save = async () => {
    setBusy(true); setErr('');
    try { await ownerAPI.setGoogleReview({ url: url.trim(), enabled: true }); onSaved(); }
    catch (e) { setErr(e?.response?.data?.detail || "Le lien n'a pas pu être enregistré."); setBusy(false); }
  };
  return (
    <Modal title="Collecter des avis Google" onClose={onClose}>
      <p className="mb-3 text-[12.5px] leading-snug text-[#64748B]">
        Un client qui note sa visite 8/10 ou plus est invité à laisser un avis sur votre fiche Google.
        Un client mécontent n'est jamais redirigé.
      </p>
      <input autoFocus value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://g.page/r/…/review"
             className="mb-3 w-full rounded-xl border border-[#E6EEFB] px-3 py-2.5 text-[13px] outline-none focus:border-[#2F6BFF]" />
      {err && <p className="mb-3 rounded-xl bg-[#FEECEC] px-3 py-2 text-[12px] text-[#C0392B]">{err}</p>}
      <div className="flex justify-end gap-2.5">
        <button type="button" onClick={onClose} className="rounded-xl border border-[#E6EEFB] px-4 py-2.5 text-[13px] font-semibold text-[#334155]">Annuler</button>
        <button type="button" onClick={save} disabled={busy || !url.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white disabled:opacity-50">
          {busy && <Loader2 size={14} className="animate-spin" />} Activer
        </button>
      </div>
    </Modal>
  );
}
