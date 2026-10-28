import React, { useCallback, useEffect, useState } from 'react';
import { canEdit } from '../lib/pagePerms';
import { useNavigate } from 'react-router-dom';
import {
  BarChart3, Download, TrendingUp, TrendingDown, Rocket, Target, ArrowRight,
  Lightbulb, ClipboardCheck, Megaphone, Crosshair, Star, Check, Loader2, X,
  Clock, MapPin, Heart, Bell, CreditCard, ShoppingCart, Repeat, Gift, Cake,
  Utensils, Sparkles, CalendarDays, Info, Leaf, PartyPopper,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

/**
 * Insights — « Faites grandir votre commerce », built to the approved mockup.
 *
 * Every shelf comes from a library larger than what is shown, ranked on the
 * shop's own data and sector by /api/owner/insights/page. The page adds no
 * figures of its own: each impact is either calculated from the shop's clients
 * or a sector estimate, and it says which, right under the number.
 *
 * Buttons navigate, pre-fill the campaign composer, or switch on something the
 * merchant can see and switch off on its own page. Nothing here sends.
 */
const TONES = {
  green:  { bg: '#E7F7EE', fg: '#0F8B58', dot: '#10B981' },
  blue:   { bg: '#EAF1FF', fg: '#1D4ED8', dot: '#2F6BFF' },
  violet: { bg: '#F3EEFF', fg: '#6D28D9', dot: '#8B5CF6' },
  amber:  { bg: '#FFF7E6', fg: '#B45309', dot: '#F59E0B' },
  rose:   { bg: '#FFF1F3', fg: '#E11D48', dot: '#F43F5E' },
};
const CHIP_ICONS = {
  ventes: Star, fidelisation: Star, acquisition: Star, automne: Leaf,
  evenement: PartyPopper, hiver: Star, printemps: Leaf, ete: Star,
};
const ITEM_ICONS = {
  cart: ShoppingCart, bell: Bell, repeat: Repeat, pin: MapPin, clock: Clock,
  cake: Cake, utensils: Utensils, sparkles: Sparkles, card: CreditCard,
  star: Star, gift: Gift, heart: Heart,
};
const nf = (n) => (n ?? 0).toLocaleString('fr-FR', { maximumFractionDigits: 0 });

const Panel = ({ id, children, className = '' }) => (
  <section id={id}
           className={`scroll-mt-24 rounded-2xl border border-[#E6EEFB] bg-white shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] ${className}`}>
    {children}
  </section>
);

const PanelHead = ({ icon: Icon, title, sub, more, expanded, onMore }) => (
  <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
    <div className="flex items-start gap-3">
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]">
        <Icon size={21} />
      </span>
      <div>
        <h2 className="text-[16px] font-bold leading-tight text-[#0B1C3F]">{title}</h2>
        <p className="text-[12.5px] text-[#64748B]">{sub}</p>
      </div>
    </div>
    {onMore && (
      <button type="button" onClick={onMore}
              className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-[#2F6BFF] hover:underline">
        {expanded ? 'Voir moins' : more} <ArrowRight size={13} className={expanded ? '-rotate-90' : ''} />
      </button>
    )}
  </header>
);

/* The one mockup "photo" that is a logo: drawn, never generated. */
const GoogleG = ({ size = 40 }) => (
  <svg width={size} height={size} viewBox="0 0 48 48" aria-label="Google">
    <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
    <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
    <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z" />
    <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
  </svg>
);

const Thumb = ({ item, size = 64, tone = 'blue' }) => {
  if (item.image === 'google') {
    return (
      <span className="flex shrink-0 items-center justify-center rounded-xl bg-white"
            style={{ width: size, height: size }}>
        <GoogleG size={size * 0.62} />
      </span>
    );
  }
  if (item.image) {
    return (
      <img src={`/insights/${item.image}.webp`} alt="" loading="lazy"
           className="shrink-0 rounded-xl object-cover"
           style={{ width: size, height: size }} />
    );
  }
  // No photo for this item (a sector or season the mockup does not show):
  // a tile in the category's colour, never a broken image.
  const Icon = ITEM_ICONS[item.icon] || Sparkles;
  const t = TONES[item.category?.tone || tone] || TONES.blue;
  return (
    <span className="flex shrink-0 items-center justify-center rounded-xl"
          style={{ width: size, height: size, background: t.bg, color: t.fg }}>
      <Icon size={size * 0.4} />
    </span>
  );
};

const Chip = ({ category }) => {
  const t = TONES[category.tone] || TONES.blue;
  const Icon = CHIP_ICONS[category.key] || Star;
  return (
    <span className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.06em]"
          style={{ background: t.bg, color: t.fg }}>
      <Icon size={10} strokeWidth={2.5} /> {category.label}
    </span>
  );
};

/* The impact, and — right under it — where it comes from. As in the design,
   a long unit ("de nouveaux clients") drops to a smaller size so the figure
   itself stays on one line; a short one ("de CA") keeps the figure's size.
   Three kinds (sector playbooks, 2026-10-28): « calcule » on the shop's
   clients, « source » a published figure with its link, « conseil » advice
   with no number — no sector estimate is ever shown. */
const Impact = ({ impact }) => {
  if (!impact) return null;
  if (impact.kind === 'conseil') {
    return (
      <div className="min-w-0">
        <p className="text-[11.5px] text-[#64748B]">Impact</p>
        <p className="text-[13px] font-semibold leading-tight text-[#94A3B8]">Conseil</p>
        <p className="mt-0.5 truncate text-[10px] text-[#94A3B8]" title={impact.basis}>Pas de chiffre sourcé</p>
      </div>
    );
  }
  if (impact.kind === 'source') {
    return (
      <div className="min-w-0">
        <p className="text-[11.5px] text-[#64748B]">Chiffre clé</p>
        <p className="text-[13px] font-bold leading-tight text-[#0F8B58]" title={impact.text}>{impact.label}</p>
        <a href={impact.url} target="_blank" rel="noopener noreferrer"
           className="mt-0.5 block truncate text-[10px] text-[#2F6BFF] hover:underline" title={impact.text}>
          Source : {impact.basis}
        </a>
      </div>
    );
  }
  // Split before the unit — "+10 à 20%" | "de nouveaux clients" — never inside the range.
  const m = /^(.+?[%€\d])\s+(de .+|avis|nouveaux clients)$/.exec(impact.label || '');
  const long = m && m[2].length > 8;
  return (
  <div className="min-w-0">
    <p className="text-[11.5px] text-[#64748B]">Impact estimé</p>
    <p className="text-[15px] font-bold leading-tight text-[#0F8B58]">
      {long ? <>{m[1]} <span className="text-[11px] font-semibold">{m[2]}</span></> : impact.label}
    </p>
    <p className="mt-0.5 truncate text-[10px] text-[#94A3B8]" title={impact.basis}>Calculé sur vos clients</p>
  </div>
  );
};

const Difficulty = ({ d }) => {
  const t = TONES[d.tone] || TONES.green;
  return (
    <div>
      <p className="text-[11.5px] text-[#64748B]">Difficulté</p>
      <p className="mt-0.5 flex items-center gap-1.5 text-[12px] font-semibold text-[#334155]">
        <span className="flex gap-0.5">
          {[0, 1, 2].map((i) => (
            <span key={i} className="h-2 w-2 rounded-full"
                  style={{ background: i < d.filled ? t.dot : '#E2E8F0' }} />
          ))}
        </span>
        {d.label}
      </p>
    </div>
  );
};

const CtaButton = ({ item, onAct, busy, full = false }) => {
  if (item.done) {
    return (
      <span className={`inline-flex items-center justify-center gap-1.5 rounded-xl border border-[#BFE9D2] bg-[#E7F7EE] px-4 py-2 text-[12.5px] font-semibold text-[#0F8B58] ${full ? 'w-full' : ''}`}>
        <Check size={14} /> {item.cta.done_label || 'Fait'}
      </span>
    );
  }
  return (
    <button type="button" onClick={() => onAct(item)} disabled={busy}
            className={`inline-flex items-center justify-center gap-1.5 rounded-xl border border-[#2F6BFF] bg-white px-4 py-2 text-[12.5px] font-semibold text-[#2F6BFF] transition hover:bg-[#F6F9FF] disabled:opacity-50 ${full ? 'w-full' : 'min-w-[112px]'}`}>
      {busy && <Loader2 size={13} className="animate-spin" />}
      {item.cta.label}
    </button>
  );
};

/* ── modals ───────────────────────────────────────────────────────────── */
const Modal = ({ title, sub, onClose, children }) => (
  <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[#0B1C3F]/40 p-4 py-16">
    <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-[0_40px_90px_-40px_rgba(11,28,63,.6)]">
      <header className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[17px] font-bold text-[#0B1C3F]">{title}</h3>
          {sub && <p className="mt-0.5 text-[12.5px] leading-snug text-[#64748B]">{sub}</p>}
        </div>
        <button type="button" onClick={onClose} className="text-[#94A3B8] hover:text-[#334155]">
          <X size={18} />
        </button>
      </header>
      {children}
    </div>
  </div>
);

const GoalModal = ({ current, onClose, onSaved }) => {
  const [value, setValue] = useState(current ? String(Math.round(current)) : '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const save = async () => {
    const n = Number(String(value).replace(/\s/g, '').replace(',', '.'));
    if (!Number.isFinite(n) || n < 0) { setErr('Indiquez un montant en euros.'); return; }
    setBusy(true); setErr('');
    try { await ownerAPI.setHomeGoal({ monthly_revenue_goal: n }); onSaved(n); }
    catch (e) { setErr(e?.response?.data?.detail || "L'objectif n'a pas pu être enregistré."); setBusy(false); }
  };
  return (
    <Modal title="Objectif du mois" onClose={onClose}
           sub="Le même objectif est suivi sur le Tableau de bord et la Segmentation.">
      <label className="mb-1 block text-[12px] font-medium text-[#475569]">Chiffre d'affaires visé ce mois-ci</label>
      <div className="mb-3 flex items-center gap-2">
        <input autoFocus inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)}
               onKeyDown={(e) => { if (e.key === 'Enter') save(); }}
               className="w-full rounded-xl border border-[#E6EEFB] px-3 py-2.5 text-[14px] tabular-nums outline-none focus:border-[#2F6BFF]" />
        <span className="text-[14px] font-semibold text-[#64748B]">€</span>
      </div>
      {err && <p className="mb-3 rounded-xl bg-[#FEECEC] px-3 py-2 text-[12px] text-[#C0392B]">{err}</p>}
      <div className="flex justify-end gap-2.5">
        <button type="button" onClick={onClose}
                className="rounded-xl border border-[#E6EEFB] px-4 py-2.5 text-[13px] font-semibold text-[#334155]">Annuler</button>
        <button type="button" onClick={save} disabled={busy}
                className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white disabled:opacity-50">
          {busy && <Loader2 size={14} className="animate-spin" />} Enregistrer
        </button>
      </div>
    </Modal>
  );
};

const GoogleModal = ({ current, onClose, onSaved }) => {
  const [url, setUrl] = useState(current || '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const save = async () => {
    setBusy(true); setErr('');
    try { await ownerAPI.setGoogleReview({ url: url.trim(), enabled: true }); onSaved(); }
    catch (e) { setErr(e?.response?.data?.detail || "Le lien n'a pas pu être enregistré."); setBusy(false); }
  };
  return (
    <Modal title="Collectez plus d'avis Google" onClose={onClose}
           sub="Quand un client note sa visite 8/10 ou plus sur sa carte, il est invité à laisser un avis sur votre fiche Google. Un client mécontent n'est jamais redirigé : son avis reste privé, pour vous.">
      <label className="mb-1 block text-[12px] font-medium text-[#475569]">Lien d'avis de votre fiche Google</label>
      <input autoFocus value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://g.page/r/…/review"
             className="mb-2 w-full rounded-xl border border-[#E6EEFB] px-3 py-2.5 text-[13px] outline-none focus:border-[#2F6BFF]" />
      <p className="mb-3 flex items-start gap-1.5 text-[11.5px] leading-snug text-[#94A3B8]">
        <Info size={12} className="mt-px shrink-0" />
        Google Business Profile → « Demander des avis » → copiez le lien.
      </p>
      {err && <p className="mb-3 rounded-xl bg-[#FEECEC] px-3 py-2 text-[12px] text-[#C0392B]">{err}</p>}
      <div className="flex justify-end gap-2.5">
        <button type="button" onClick={onClose}
                className="rounded-xl border border-[#E6EEFB] px-4 py-2.5 text-[13px] font-semibold text-[#334155]">Annuler</button>
        <button type="button" onClick={save} disabled={busy || !url.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white disabled:opacity-50">
          {busy && <Loader2 size={14} className="animate-spin" />} Activer
        </button>
      </div>
    </Modal>
  );
};

/* ── page ─────────────────────────────────────────────────────────────── */
export default function InsightsGrowthPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  // Switching an automation on or setting the Google review link changes the
  // whole shop: the owner's to do.
  const owner = canEdit(user, 'automations');   // its CTAs switch automations on (permissions, 2026-10-22)
  const [d, setD] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [flash, setFlash] = useState('');
  const [open, setOpen] = useState({});
  const [busyKey, setBusyKey] = useState('');
  const [modal, setModal] = useState(null);
  const [exporting, setExporting] = useState(false);

  const load = useCallback(() => {
    ownerAPI.insightsPage()
      .then(({ data }) => { setD(data); setError(''); })
      .catch((e) => setError(e?.response?.data?.detail || 'Impossible de charger les recommandations.'))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const scrollTo = (id) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });

  const act = async (item) => {
    const cta = item.cta;
    if (cta.kind === 'template') { navigate(`/dashboard/campaigns?template=${encodeURIComponent(cta.template)}`); return; }
    if (cta.kind === 'navigate') { navigate(cta.to); return; }
    if (cta.kind === 'scroll') { scrollTo(cta.target); return; }
    if ((cta.kind === 'google_review' || cta.kind === 'activate') && !owner) {
      setFlash('Cette action concerne tout le commerce : demandez au propriétaire de l\u2019activer.');
      return;
    }
    if (cta.kind === 'google_review') { setModal('google'); return; }
    if (cta.kind === 'activate') {
      setBusyKey(item.key);
      try {
        await ownerAPI.activateInsight(cta.action);
        setFlash(`« ${item.title} » est activée. Vous pouvez la modifier dans Automatisations.`);
        load();
      } catch (e) { setError(e?.response?.data?.detail || "L'activation n'a pas abouti."); }
      finally { setBusyKey(''); }
    }
  };

  const exportPdf = async () => {
    setExporting(true);
    try {
      const { data: blob } = await ownerAPI.insightsExport();
      const url = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }));
      const a = document.createElement('a');
      a.href = url; a.download = `fidclic-recommandations-${new Date().toISOString().slice(0, 10)}.pdf`;
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch { setError("L'export n'a pas abouti."); }
    finally { setExporting(false); }
  };

  const shelf = (key) => (open[key] ? d?.[key]?.all : d?.[key]?.shown) || [];
  const toggle = (key) => (d?.[key]?.more ? () => setOpen((o) => ({ ...o, [key]: !o[key] })) : null);

  if (loading && !d) {
    return (
      <div key="loading" className="ig flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]">
        <Loader2 size={16} className="animate-spin" /> Chargement des recommandations…
      </div>
    );
  }

  const hero = d?.hero || {};
  const goal = d?.goal || {};
  const up = hero.direction !== 'down';

  return (
    <div className="ig">
      {/* header */}
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-[11.5px] font-bold uppercase tracking-[0.12em] text-[#2F6BFF]">
            <span className="inline-flex items-center gap-1.5"><BarChart3 size={13} /> Insights</span>
            <span className="inline-flex items-center gap-1 rounded-md bg-[#E7F7EE] px-1.5 py-0.5 text-[10.5px] font-bold text-[#0F8B58]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#10B981]" /> LIVE
            </span>
          </p>
          <h1 className="mt-1 text-[30px] font-bold leading-tight text-[#0B1C3F]">Faites grandir votre commerce</h1>
          <p className="mt-1 max-w-3xl text-[13.5px] leading-snug text-[#64748B]">
            Des recommandations personnalisées pour attirer plus de clients, les faire revenir et augmenter votre
            chiffre d'affaires. FidClic analyse vos données et les meilleures pratiques du marché pour vous guider.
          </p>
        </div>
        <button type="button" onClick={exportPdf} disabled={exporting}
                className="inline-flex shrink-0 items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 py-3 text-[13.5px] font-semibold text-white transition hover:bg-[#2559DB] disabled:opacity-60">
          {exporting ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
          Exporter les recommandations
        </button>
      </header>

      {flash && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-[#E7F7EE] px-4 py-2.5 text-[12.5px] font-medium text-[#0F8B58]">
          <Check size={15} /> {flash}
          <button type="button" onClick={() => setFlash('')} className="ml-auto opacity-70 hover:opacity-100"><X size={14} /></button>
        </div>
      )}
      {error && <p className="mb-4 rounded-xl bg-[#FEECEC] px-4 py-2.5 text-[12.5px] text-[#C0392B]">{error}</p>}

      {/* trend + goal */}
      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        <Panel className="!border-[#D7E6FF] !bg-[#F2F7FF] p-5">
          <div className="flex items-center gap-4">
            <span className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-full text-white ${up ? 'bg-[#2F6BFF]' : 'bg-[#F59E0B]'}`}>
              {up ? <TrendingUp size={26} /> : <TrendingDown size={26} />}
            </span>
            <div className="min-w-0">
              <p className="text-[16px] font-bold text-[#0B1C3F]">{hero.title}</p>
              {hero.chip && (
                <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[13px] text-[#334155]">
                  <span className="rounded-md px-1.5 py-0.5 text-[13px] font-bold"
                        style={up ? { background: '#E7F7EE', color: '#0F8B58' } : { background: '#FEECEC', color: '#C0392B' }}>
                    {hero.chip}
                  </span>
                  {hero.chip_text}
                </p>
              )}
              <p className="mt-1 flex items-center gap-1.5 text-[12.5px] text-[#475569]">
                {hero.text?.replace(' 🚀', '')}
                {up && hero.direction === 'up' && <Rocket size={14} className="text-[#F97316]" />}
              </p>
            </div>
          </div>
        </Panel>

        <Panel className="p-5">
          <div className="flex items-start gap-3.5">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-[#FFF1F3] text-[#E11D48]">
              <Target size={22} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-start justify-between gap-2">
                <p className="text-[14px] font-bold text-[#0B1C3F]">Objectif du mois</p>
{user?.role !== 'manager' && (
                                <button type="button" onClick={() => setModal('goal')}
                        className="rounded-lg border border-[#E6EEFB] px-2.5 py-1 text-[11.5px] font-semibold text-[#2F6BFF] transition hover:border-[#2F6BFF]">
                  {goal.is_set ? "Modifier l'objectif" : 'Fixer un objectif'}
                </button>
                )}
              </div>
              {goal.is_set ? (
                <>
                  <p className="text-[24px] font-bold leading-tight text-[#0B1C3F] tabular-nums">{nf(goal.target)} €</p>
                  <div className="mt-2 flex items-center gap-2.5">
                    <span className="h-2 flex-1 overflow-hidden rounded-full bg-[#EEF3FB]">
                      <span className="block h-full rounded-full bg-[#2F6BFF]" style={{ width: `${goal.pct || 0}%` }} />
                    </span>
                    <span className="shrink-0 text-[12px] font-bold text-[#2F6BFF] tabular-nums">{goal.pct || 0}%</span>
                  </div>
                  <p className="mt-2 text-[12px] text-[#64748B]">
                    {goal.remaining > 0
                      ? <>Il vous manque {nf(goal.remaining)} € pour atteindre votre objectif.</>
                      : <>Objectif atteint — {nf(goal.reached)} € ce mois-ci.</>}
                  </p>
                </>
              ) : (
                <p className="mt-1 text-[12.5px] leading-snug text-[#64748B]">
                  Fixez un objectif de chiffre d'affaires : la page suivra votre progression tout au long du mois.
                </p>
              )}
              <button type="button" onClick={() => scrollTo('opportunites')}
                      className="mt-2 inline-flex items-center gap-1 text-[12.5px] font-semibold text-[#2F6BFF] hover:underline">
                Voir nos recommandations pour l'atteindre <ArrowRight size={13} />
              </button>
            </div>
          </div>
        </Panel>
      </div>

      {/* opportunités */}
      <Panel id="opportunites" className="mb-4 p-5">
        <PanelHead icon={Lightbulb} title="Opportunités pour votre commerce"
                   sub={d?.activity?.key && d.activity.key !== 'autre'
                     ? `Des leviers de croissance identifiés pour votre activité : ${d.activity.label}.`
                     : 'Des leviers de croissance identifiés spécialement pour vous.'}
                   more="Voir toutes les opportunités" expanded={open.opportunities}
                   onMore={toggle('opportunities')} />
        <div className="grid gap-3 lg:grid-cols-3">
          {shelf('opportunities').map((o) => (
            <div key={o.key} className="flex flex-col rounded-2xl border border-[#E6EEFB] p-4">
              <div className="mb-2 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <Chip category={o.category} />
                  <p className="mt-2 text-[15px] font-bold leading-snug text-[#0B1C3F]">{o.title}</p>
                </div>
                <Thumb item={o} size={68} />
              </div>
              <p className="mb-3 flex-1 text-[12px] leading-snug text-[#64748B]">{o.body}</p>
              <div className="mb-3 grid grid-cols-2 gap-3">
                <Impact impact={o.impact} />
                <Difficulty d={o.difficulty} />
              </div>
              <CtaButton item={o} onAct={act} full busy={busyKey === o.key} />
            </div>
          ))}
        </div>
      </Panel>

      {/* actions */}
      <Panel id="actions" className="mb-4 p-5">
        <PanelHead icon={ClipboardCheck} title="Actions recommandées cette semaine"
                   sub="Des actions concrètes et prêtes à l'emploi pour obtenir des résultats rapidement."
                   more="Voir toutes les actions" expanded={open.actions} onMore={toggle('actions')} />
        <div className="space-y-2.5">
          {shelf('actions').map((a, i) => (
            <div key={a.key} className="flex flex-wrap items-center gap-4 rounded-2xl border border-[#E6EEFB] p-3.5 lg:flex-nowrap">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#2F6BFF] text-[12.5px] font-bold text-white">
                {i + 1}
              </span>
              <Thumb item={a} size={68} />
              <div className="min-w-[220px] flex-1">
                <p className="text-[14px] font-bold text-[#0B1C3F]">{a.title}</p>
                <p className="mt-0.5 text-[12px] leading-snug text-[#64748B]">{a.body}</p>
                <span className="mt-1.5 inline-flex items-center gap-1 rounded-md bg-[#EAF1FF] px-2 py-0.5 text-[11px] font-semibold text-[#1D4ED8]">
                  <Check size={11} strokeWidth={3} /> {a.benefit}
                </span>
              </div>
              <div className="w-[150px] shrink-0"><Impact impact={a.impact} /></div>
              <div className="w-[150px] shrink-0">
                <p className="whitespace-nowrap text-[11.5px] text-[#64748B]">Temps de mise en place</p>
                <p className="text-[14px] font-bold text-[#0B1C3F]">{a.setup}</p>
              </div>
              <div className="shrink-0"><CtaButton item={a} onAct={act} busy={busyKey === a.key} /></div>
            </div>
          ))}
        </div>
      </Panel>

      {/* idées de campagnes */}
      <Panel className="mb-4 p-5">
        <PanelHead icon={Megaphone} title="Idées de campagnes"
                   sub="Des campagnes prêtes à l'emploi, adaptées à votre activité et à la saison."
                   more="Voir toutes les campagnes" expanded={open.ideas} onMore={toggle('ideas')} />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {shelf('ideas').map((x) => (
            <div key={x.key} className="flex flex-col rounded-2xl border border-[#E6EEFB] p-3.5">
              <div className="mb-3 flex flex-1 items-start gap-3">
                <Thumb item={x} size={72} />
                <div className="min-w-0">
                  <Chip category={x.category} />
                  <p className="mt-1.5 text-[14px] font-bold leading-snug text-[#0B1C3F]">{x.title}</p>
                  <p className="mt-0.5 text-[11.5px] leading-snug text-[#64748B]">{x.body}</p>
                  {x.fact && (
                    <p className="mt-1 text-[10.5px] leading-snug text-[#0F8B58]" title={x.fact.text}>
                      {x.fact.short} ·{' '}
                      <a href={x.fact.url} target="_blank" rel="noopener noreferrer" className="text-[#2F6BFF] hover:underline">
                        {x.fact.source} ({x.fact.year})
                      </a>
                    </p>
                  )}
                </div>
              </div>
              <CtaButton item={x} onAct={act} full />
            </div>
          ))}
        </div>
      </Panel>

      {/* conseils */}
      <Panel className="mb-4 p-5">
        <PanelHead icon={Crosshair} title="Conseils personnalisés pour vous"
                   sub="Des recommandations basées sur votre secteur, votre zone et la saison."
                   more="Voir tous les conseils" expanded={open.tips} onMore={toggle('tips')} />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {shelf('tips').map((t) => {
            const Icon = ITEM_ICONS[t.icon] || Lightbulb;
            return (
              <div key={t.key} className="flex items-start gap-3 rounded-2xl border border-[#E6EEFB] p-3.5">
                <Icon size={22} className="mt-0.5 shrink-0 text-[#2F6BFF]" />
                <div className="min-w-0">
                  <p className="text-[13px] font-bold text-[#0B1C3F]">{t.title}</p>
                  <p className="mt-0.5 text-[11.5px] leading-snug text-[#64748B]">{t.body}</p>
                </div>
              </div>
            );
          })}
        </div>
        {d?.impact_note && (
          <p className="mt-4 flex items-start gap-1.5 text-[11px] leading-snug text-[#94A3B8]">
            <Info size={12} className="mt-px shrink-0" /> {d.impact_note}
          </p>
        )}
      </Panel>

      {/* accompagnement */}
      <section className="flex flex-wrap items-center gap-5 rounded-2xl border border-[#D7E6FF] bg-gradient-to-r from-[#EAF1FF] to-[#F5F8FF] p-6">
        <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-[#2F6BFF] text-white">
          <Target size={30} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[18px] font-bold text-[#0B1C3F]">Un accompagnement sur mesure</p>
          <p className="mt-0.5 text-[13px] text-[#475569]">
            Notre équipe vous aide à mettre en place ces recommandations et à atteindre vos objectifs.
          </p>
        </div>
        {/* Not wired yet, on purpose: the booking destination is still to be
            decided. When it is, set the onClick here — nothing else changes. */}
        <button type="button" onClick={() => {}}
                className="inline-flex shrink-0 items-center gap-2 rounded-xl bg-[#2F6BFF] px-6 py-3.5 text-[14px] font-semibold text-white transition hover:bg-[#2559DB]">
          <CalendarDays size={17} /> Réserver un appel gratuit
        </button>
      </section>

      {modal === 'goal' && (
        <GoalModal current={goal.target} onClose={() => setModal(null)}
                   onSaved={() => { setModal(null); setFlash('Objectif enregistré.'); load(); }} />
      )}
      {modal === 'google' && (
        <GoogleModal current={d?.google_review?.url} onClose={() => setModal(null)}
                     onSaved={() => {
                       setModal(null);
                       setFlash('Invitations aux avis Google activées : vos clients satisfaits verront le lien après leur note.');
                       load();
                     }} />
      )}
    </div>
  );
}
