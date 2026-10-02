import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Users, Crown, Send, UserPlus, Target, ShoppingBag, MapPin, Gift, Star,
  Upload, Search, Filter, SlidersHorizontal, ChevronDown, ChevronLeft,
  ChevronRight, Mail, MoreVertical, Loader2, Columns3, Download, X, ArrowRight,
  Bookmark, BookmarkPlus, Check, Send as SendIcon,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { perPage as prefPerPage } from '../lib/prefs';
import { useAuth } from '../contexts/AuthContext';
import { usePlanAccess, openUpgrade } from '../components/PlanAccess';

/**
 * Clients — built to the approved mockup.
 *
 * Four figures, eight quick segments, one filtered and paginated table. All of
 * it from /api/owner/clients/*, where the vocabulary is defined once: a client's
 * statut and segment mean the same thing in the figures, on the chips and in
 * their row, because all three are computed in the same place.
 *
 * Nothing here is demo data. A shop with no clients reads zero and says so.
 */
const SEGMENT_ICONS = {
  users: Users, crown: Crown, send: Send, userplus: UserPlus,
  bag: ShoppingBag, pin: MapPin, gift: Gift, star: Star, target: Target,
};
const TONES = {
  blue:   { bg: '#EAF1FF', fg: '#1D4ED8', dot: '#2F6BFF' },
  amber:  { bg: '#FFF7E6', fg: '#B45309', dot: '#F59E0B' },
  rose:   { bg: '#FFF1F3', fg: '#E11D48', dot: '#F43F5E' },
  violet: { bg: '#F3EEFF', fg: '#6D28D9', dot: '#8B5CF6' },
  orange: { bg: '#FFF3E8', fg: '#C2410C', dot: '#F97316' },
  green:  { bg: '#E7F7EE', fg: '#0F8B58', dot: '#10B981' },
  slate:  { bg: '#F1F5F9', fg: '#475569', dot: '#94A3B8' },
};
/* Avatars carry the tier, as they do everywhere else on the platform. */
const TIER = {
  bronze: { bg: '#FBEADC', fg: '#A45C21' },
  silver: { bg: '#EEF1F6', fg: '#5B6577' },
  gold:   { bg: '#FDF2D0', fg: '#A8791A' },
  vip:    { bg: '#EFE8FF', fg: '#6D28D9' },
};

const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');
const money = (n) => `${(n ?? 0).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
const day = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
};

const SPEND_BANDS = [
  { key: '', label: 'Toutes' },
  { key: 'lt50', label: 'Moins de 50 €' },
  { key: '50_150', label: '50 € – 150 €' },
  { key: '150_500', label: '150 € – 500 €' },
  { key: 'gt500', label: 'Plus de 500 €' },
];
const JOINED_BANDS = [
  { key: '', label: 'Toutes' },
  { key: '30d', label: '30 derniers jours' },
  { key: '90d', label: '90 derniers jours' },
  { key: '1y', label: '12 derniers mois' },
];

/* ── pieces ───────────────────────────────────────────────────────────── */
const Avatar = ({ initials, tier, size = 36 }) => {
  const t = TIER[tier] || TIER.bronze;
  return (
    <span className="inline-flex shrink-0 items-center justify-center rounded-full font-bold"
          style={{ width: size, height: size, background: t.bg, color: t.fg, fontSize: size * 0.36 }}>
      {initials}
    </span>
  );
};

const KpiCard = ({ card }) => {
  const Icon = SEGMENT_ICONS[card.icon] || Users;
  const t = TONES[card.tone] || TONES.blue;
  // On "clients inactifs" a fall is the good news, so the colour follows the
  // meaning rather than the sign.
  const good = card.lower_is_better ? (card.delta_pct ?? 0) <= 0 : (card.delta_pct ?? 0) >= 0;
  const up = (card.delta_pct ?? 0) >= 0;
  return (
    <div className="rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <div className="flex items-start gap-4">
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full"
              style={{ background: t.bg, color: t.fg }}>
          <Icon size={22} />
        </span>
        <div className="min-w-0">
          <p className="text-[26px] font-bold leading-none tracking-tight text-[#0B1C3F] tabular-nums">
            {nf(card.value)}
          </p>
          <p className="mt-1.5 text-[12.5px] text-[#64748B]">{card.label}</p>
        </div>
      </div>
      {card.delta_pct === null || card.delta_pct === undefined ? (
        <p className="mt-3 text-[11px] text-[#94A3B8]">{card.note || 'pas encore de comparaison'}</p>
      ) : (
        <div className="mt-3">
          <span className="inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[11.5px] font-semibold"
                style={good ? { background: '#E7F7EE', color: '#0F8B58' } : { background: '#FEECEC', color: '#C0392B' }}>
            {up ? '↑' : '↓'} {up ? '+' : ''}{card.delta_pct}%
          </span>
          <span className="mt-1 block text-[11px] text-[#94A3B8]">{card.note}</span>
        </div>
      )}
    </div>
  );
};

const Select = ({ label, value, onChange, options }) => (
  <label className="block min-w-0">
    <span className="mb-1 block text-[11px] text-[#94A3B8]">{label}</span>
    <div className="relative">
      <select value={value} onChange={(e) => onChange(e.target.value)}
              className="w-full appearance-none rounded-xl border border-[#E6EEFB] bg-white py-2.5 pl-3 pr-8 text-[13px] font-medium text-[#0B1C3F] outline-none focus:border-[#2F6BFF]">
        {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
      </select>
      <ChevronDown size={14} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
    </div>
  </label>
);

/* ── page ─────────────────────────────────────────────────────────────── */
/* ── Contacter ─────────────────────────────────────────────────────────────
   The filter above this page is the whole point of the page, so the message
   goes to what the filter found — not to the ten rows that happen to be on
   screen. The modal says which, and how many, before anything is sent. */
const ComposeModal = ({ count, label, onClose, onSend }) => {
  const [title, setTitle] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const ready = title.trim() && message.trim();

  const send = async () => {
    setBusy(true); setErr('');
    try { await onSend(title.trim(), message.trim()); }
    catch (e) { setErr(e?.response?.data?.detail || "L'envoi n'a pas abouti."); setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0B1C3F]/40 p-4"
         onClick={onClose}>
      <div className="w-full max-w-lg rounded-2xl bg-white p-5 shadow-[0_30px_70px_-30px_rgba(11,28,63,.6)]"
           onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h3 className="text-[16px] font-bold text-[#0B1C3F]">Contacter {label}</h3>
            <p className="text-[12.5px] text-[#64748B]">
              {nf(count)} client{count > 1 ? 's' : ''} recevront ce message.
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-[#94A3B8] hover:text-[#334155]">
            <X size={18} />
          </button>
        </div>

        <label className="mb-1 flex items-center justify-between text-[11.5px] font-medium text-[#475569]">
          Titre <span className="tabular-nums text-[#94A3B8]">{title.length}/50</span>
        </label>
        <input value={title} maxLength={50} onChange={(e) => setTitle(e.target.value)}
               placeholder="☕ Une attention pour vous"
               className="mb-3 w-full rounded-xl border border-[#E6EEFB] px-3 py-2.5 text-[13px] outline-none focus:border-[#2F6BFF]" />

        <label className="mb-1 flex items-center justify-between text-[11.5px] font-medium text-[#475569]">
          Message <span className="tabular-nums text-[#94A3B8]">{message.length}/160</span>
        </label>
        <textarea value={message} maxLength={160} rows={3}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="On vous attend cette semaine !"
                  className="mb-3 w-full resize-none rounded-xl border border-[#E6EEFB] px-3 py-2.5 text-[13px] leading-snug outline-none focus:border-[#2F6BFF]" />

        {err && <p className="mb-3 rounded-xl bg-[#FEECEC] px-3 py-2 text-[12px] text-[#C0392B]">{err}</p>}

        <div className="flex justify-end gap-2.5">
          <button type="button" onClick={onClose}
                  className="rounded-xl border border-[#E6EEFB] px-4 py-2.5 text-[13px] font-semibold text-[#334155]">
            Annuler
          </button>
          <button type="button" onClick={send} disabled={!ready || busy}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white transition hover:bg-[#2559DB] disabled:opacity-50">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <SendIcon size={14} />} Envoyer
          </button>
        </div>
      </div>
    </div>
  );
};

export default function ClientsPage() {
  const { user } = useAuth();
  // « CRM avancé » (Super admin › Plan Limits): without it, the simple list —
  // search, statut and sort; segments and saved filters show the upgrade prompt.
  const access = usePlanAccess();
  const crm = access?.has ? access.has('crm_advanced') : true;
  const crmReady = access?.ready !== false;
  const needCrm = (fn) => (...a) => (crm ? fn(...a) : openUpgrade(access?.locked?.crm_advanced));
  const navigate = useNavigate();
  const [meta, setMeta] = useState(null);
  const [feed, setFeed] = useState({ rows: [], total: 0, pages: 1, page: 1, per_page: 10 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // The Tableau de bord opens this page on a figure's own clients
  // (?segment=loyal, inactive, new, or a « Statut des clients » slice).
  const [urlParams, setUrlParams] = useSearchParams();
  const [segment, setSegmentState] = useState(() => urlParams.get('segment') || 'all');
  const setSegment = (k) => {
    setSegmentState(k);
    if (urlParams.get('segment')) setUrlParams((p) => { p.delete('segment'); return p; }, { replace: true });
  };
  useEffect(() => {
    const k = urlParams.get('segment');
    if (k && k !== segment) { setSegmentState(k); setPage(1); }
  }, [urlParams]); // eslint-disable-line react-hooks/exhaustive-deps
  const [status, setStatus] = useState('');
  const [spend, setSpend] = useState('');
  const [joined, setJoined] = useState('');
  const [typed, setTyped] = useState('');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('recent');
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(() => prefPerPage());
  const [more, setMore] = useState(false);
  const [picked, setPicked] = useState([]);
  const [menuFor, setMenuFor] = useState(null);
  const [exporting, setExporting] = useState(false);
  // Saved segments — a filter combination the merchant named and wants back.
  const [saved, setSaved] = useState([]);
  const [naming, setNaming] = useState(false);
  const [segName, setSegName] = useState('');
  const [compose, setCompose] = useState(null);   // { ids, label } | null
  const [flash, setFlash] = useState('');

  useEffect(() => { ownerAPI.clientsOverview().then(({ data }) => setMeta(data)).catch(() => {}); }, []);

  const loadSaved = useCallback(() => {
    if (!crmReady || !crm) { setSaved([]); return; }       // saved filters: CRM avancé
    ownerAPI.listSavedSegments()
      .then(({ data }) => setSaved(Array.isArray(data) ? data : (data?.segments || [])))
      .catch(() => setSaved([]));
  }, [crm, crmReady]);
  useEffect(() => { loadSaved(); }, [loadSaved]);

  // What the current filter is, in one place: saved as-is, and applied back
  // as-is, so a reloaded segment shows exactly the rows it showed when it was
  // saved.
  const currentFilters = useMemo(() => ({ segment, status, spend, joined, search, sort }),
                                 [segment, status, spend, joined, search, sort]);

  const saveCurrent = async () => {
    const name = segName.trim();
    if (!name) return;
    try {
      await ownerAPI.createSavedSegment({ name, segment, filters: currentFilters });
      setSegName(''); setNaming(false); loadSaved();
      setFlash(`Segment « ${name} » enregistré.`);
    } catch (e) { setError(e?.response?.data?.detail || "Le segment n'a pas pu être enregistré."); }
  };

  const applySaved = (row) => {
    const f = row.filters || {};
    setSegment(f.segment || row.segment || 'all');
    setStatus(f.status || ''); setSpend(f.spend || ''); setJoined(f.joined || '');
    setTyped(f.search || ''); setSearch(f.search || '');
    setSort(f.sort || 'recent');
    setPage(1); setPicked([]);
  };

  const removeSaved = async (id) => {
    try { await ownerAPI.deleteSavedSegment(id); loadSaved(); }
    catch { setError("Le segment n'a pas pu être supprimé."); }
  };

  // Message the SELECTION when there is one, otherwise everyone the filter
  // found — never the page that happens to be on screen.
  const openCompose = async (scope) => {
    if (scope === 'picked') {
      setCompose({ ids: picked, label: `${picked.length} client${picked.length > 1 ? 's' : ''} sélectionné${picked.length > 1 ? 's' : ''}` });
      return;
    }
    try {
      const { data } = await ownerAPI.clientIds({ segment, status, spend, joined, search });
      if (!data.ids?.length) { setError('Aucun client ne correspond à ce filtre.'); return; }
      setCompose({ ids: data.ids, label: activeSegment?.label || 'ce filtre' });
    } catch (e) { setError(e?.response?.data?.detail || 'Impossible de constituer la liste.'); }
  };

  const sendCompose = async (title, message) => {
    await ownerAPI.sendCampaignToGroup({
      customer_ids: compose.ids, name: title, content: message, message,
    });
    setFlash(`Message envoyé à ${nf(compose.ids.length)} client${compose.ids.length > 1 ? 's' : ''}.`);
    setCompose(null); setPicked([]);
  };

  useEffect(() => {
    const id = setTimeout(() => { setSearch(typed.trim()); setPage(1); }, 300);
    return () => clearTimeout(id);
  }, [typed]);

  const params = useMemo(() => ({
    segment, status, spend, joined, search, sort, page, per_page: perPage,
  }), [segment, status, spend, joined, search, sort, page, perPage]);

  const load = useCallback(() => {
    setLoading(true); setError('');
    ownerAPI.clientsList(params)
      .then(({ data }) => setFeed(data))
      .catch((e) => setError(e?.response?.data?.detail || 'Impossible de charger les clients.'))
      .finally(() => setLoading(false));
  }, [params]);
  useEffect(() => { load(); }, [load]);

  const segments = meta?.segments || [];
  const homeSegment = (meta?.home_segments || []).find((s) => s.key === segment);
  const activeSegment = segments.find((s) => s.key === segment) || homeSegment;

  const exportCsv = async () => {
    setExporting(true);
    try {
      const { data: blob } = await ownerAPI.clientsExport({ segment, status, spend, joined, search, sort });
      const url = URL.createObjectURL(new Blob([blob], { type: 'text/csv;charset=utf-8' }));
      const a = document.createElement('a');
      a.href = url; a.download = `fidclic-clients-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch { setError("L'export n'a pas abouti."); }
    finally { setExporting(false); }
  };

  const allPicked = feed.rows.length > 0 && picked.length === feed.rows.length;
  const togglePick = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  const pageNumbers = useMemo(() => {
    const total = feed.pages || 1;
    if (total <= 5) return Array.from({ length: total }, (_, i) => i + 1);
    const start = Math.max(1, Math.min(feed.page - 2, total - 4));
    return Array.from({ length: 5 }, (_, i) => start + i);
  }, [feed.pages, feed.page]);

  return (
    <div className="cl" onClick={() => setMenuFor(null)}>
      {/* header */}
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="flex items-center gap-1.5 text-[11.5px] font-semibold uppercase tracking-[0.1em] text-[#2F6BFF]">
            <Users size={13} /> Clients
          </p>
          <h1 className="mt-1 text-[28px] font-bold leading-tight text-[#0B1C3F]">Clients</h1>
          <p className="text-[13px] text-[#64748B]">
            Gérez vos clients, segmentez-les et activez des campagnes ciblées.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          {/* « Ajouter un client » removed (user, 2026-10-02): it opened the staff
              scan page. Clients join with the shop's QR code; a file is imported. */}
          {/* Importing a file is a shop-wide setting: the owner's. */}
          {user?.role === 'business_owner' && (
            <button type="button" onClick={() => navigate('/dashboard/settings#settings-import')}
                    className="inline-flex items-center gap-2 rounded-xl border border-[#E6EEFB] bg-white px-4 py-2.5 text-[13px] font-semibold text-[#0B1C3F] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
              <Upload size={15} /> Importer
            </button>
          )}
        </div>
      </header>

      {error && <p className="mb-4 rounded-xl bg-[#FEECEC] px-4 py-2.5 text-[12.5px] text-[#C0392B]">{error}</p>}

      {/* the four figures */}
      <div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {(meta?.cards || []).map((c) => <KpiCard key={c.key} card={c} />)}
        {!meta && Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="h-[136px] animate-pulse rounded-2xl border border-[#E6EEFB] bg-white" />
        ))}
      </div>

      {/* quick segments */}
      <section className="mb-4 rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <span className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]">
              <Target size={18} />
            </span>
            <span>
              <span className="block text-[15px] font-bold leading-tight text-[#0B1C3F]">Segments rapides</span>
              <span className="block text-[12.5px] text-[#64748B]">
                Filtrez vos clients par segment pour lancer des actions rapidement.
              </span>
            </span>
          </span>
          <button type="button" onClick={needCrm(() => navigate('/dashboard/segmentation'))}
                  className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-[#2F6BFF] hover:underline">
            Voir tous les segments <ArrowRight size={13} />
          </button>
        </header>
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
          {segments.map((s) => {
            const Icon = SEGMENT_ICONS[s.icon] || Users;
            const t = TONES[s.tone] || TONES.blue;
            const on = segment === s.key;
            return (
              <button key={s.key} type="button"
                      onClick={needCrm(() => { setSegment(s.key); setPage(1); setPicked([]); })}
                      className={`flex items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left transition ${
                        on ? 'border-[#2F6BFF] bg-[#F5F8FF]' : 'border-[#E6EEFB] bg-white hover:border-[#C7DBFF]'}`}>
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
                      style={{ background: t.bg, color: t.fg }}>
                  <Icon size={14} />
                </span>
                <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-[#334155]">{s.label}</span>
                <span className="shrink-0 text-[12.5px] font-bold text-[#0B1C3F] tabular-nums">{nf(s.count)}</span>
              </button>
            );
          })}
        </div>

        {/* Saved segments — a filter combination the merchant named. The eight
            above are ours; these are theirs. */}
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[#EEF3FB] pt-3">
          <span className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-[#64748B]">
            <Bookmark size={13} className="text-[#2F6BFF]" /> Mes segments
          </span>
          {saved.map((row) => (
            <span key={row.id}
                  className="inline-flex items-center gap-1 rounded-full border border-[#E6EEFB] bg-white py-1 pl-3 pr-1">
              <button type="button" onClick={needCrm(() => applySaved(row))}
                      className="text-[12px] font-semibold text-[#334155] hover:text-[#2F6BFF]">
                {row.name}
              </button>
              <button type="button" onClick={() => removeSaved(row.id)} title="Supprimer"
                      className="rounded-full p-1 text-[#94A3B8] transition hover:bg-[#FEECEC] hover:text-[#C0392B]">
                <X size={11} />
              </button>
            </span>
          ))}
          {!saved.length && !naming && (
            <span className="text-[11.5px] italic text-[#94A3B8]">
              Réglez les filtres, puis enregistrez la combinaison pour la retrouver.
            </span>
          )}
          {naming ? (
            <span className="inline-flex items-center gap-1.5">
              <input autoFocus value={segName} onChange={(e) => setSegName(e.target.value)}
                     onKeyDown={(e) => { if (e.key === 'Enter') saveCurrent(); if (e.key === 'Escape') setNaming(false); }}
                     placeholder="Nom du segment" maxLength={60}
                     className="w-44 rounded-full border border-[#2F6BFF] px-3 py-1 text-[12px] outline-none" />
              <button type="button" onClick={saveCurrent} disabled={!segName.trim()}
                      className="rounded-full bg-[#2F6BFF] p-1.5 text-white disabled:opacity-40">
                <Check size={12} />
              </button>
              <button type="button" onClick={() => { setNaming(false); setSegName(''); }}
                      className="rounded-full p-1.5 text-[#94A3B8] hover:text-[#334155]">
                <X size={12} />
              </button>
            </span>
          ) : (
            <button type="button" onClick={needCrm(() => setNaming(true))}
                    className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-dashed border-[#C9DBFB] px-3 py-1 text-[12px] font-semibold text-[#2F6BFF] transition hover:border-[#2F6BFF]">
              <BookmarkPlus size={13} /> Enregistrer ce filtre
            </button>
          )}
        </div>
      </section>

      {flash && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-[#E7F7EE] px-4 py-2.5 text-[12.5px] font-medium text-[#0F8B58]">
          <Check size={15} /> {flash}
          <button type="button" onClick={() => setFlash('')} className="ml-auto text-[#0F8B58]/70 hover:text-[#0F8B58]">
            <X size={14} />
          </button>
        </div>
      )}

      {/* search */}
      <div className="relative mb-4">
        <Search size={16} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
        <input value={typed} onChange={(e) => setTyped(e.target.value)}
               placeholder="Rechercher un client (nom, email, téléphone…)"
               className="w-full rounded-2xl border border-[#E6EEFB] bg-white py-3.5 pl-11 pr-4 text-[13px] text-[#0B1C3F] shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] outline-none placeholder:text-[#94A3B8] focus:border-[#2F6BFF]" />
      </div>

      {/* filters */}
      <section className="mb-4 rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
        <p className="mb-3 flex items-center gap-1.5 text-[12.5px] font-semibold text-[#475569]">
          <Filter size={14} /> Filtres
        </p>
        <div className="grid gap-3 md:grid-cols-[1fr_1fr_1fr_1fr_auto] md:items-end">
          <Select label="Segment" value={segment}
                  onChange={needCrm((v) => { setSegment(v); setPage(1); })}
                  options={segments.map((s) => ({ key: s.key, label: s.key === 'all' ? 'Tous' : s.label }))} />
          <Select label="Statut" value={status}
                  onChange={(v) => { setStatus(v); setPage(1); }}
                  options={[{ key: '', label: 'Tous' },
                            ...(meta?.statuses || []).map((s) => ({ key: s.key, label: s.label }))]} />
          <Select label="Dépenses" value={spend}
                  onChange={needCrm((v) => { setSpend(v); setPage(1); })} options={SPEND_BANDS} />
          <Select label="Date d'inscription" value={joined}
                  onChange={needCrm((v) => { setJoined(v); setPage(1); })} options={JOINED_BANDS} />
          <button type="button" onClick={needCrm(() => setMore((v) => !v))}
                  className="inline-flex h-[42px] items-center justify-center gap-1.5 rounded-xl border border-[#E6EEFB] px-4 text-[13px] font-semibold text-[#475569] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
            <SlidersHorizontal size={14} /> Plus de filtres
          </button>
        </div>
        {more && meta && (
          <div className="mt-3 rounded-xl bg-[#F8FAFF] px-4 py-3">
            <p className="text-[12px] leading-relaxed text-[#475569]">
              <strong>Comment ces segments sont calculés.</strong> Un client est
              <em> fidèle</em> à partir de {meta.definitions.loyal_visits} visites,
              <em> inactif</em> après {meta.definitions.inactive_days} jours sans venir, et
              <em> nouveau</em> pendant ses {meta.definitions.new_days} premiers jours.
              Un <em>gros panier</em> dépense au moins {meta.definitions.big_basket_factor}× le panier
              moyen de votre établissement ({money(meta.shop_average_ticket)}), et un
              <em> client local</em> habite à moins de {meta.definitions.local_km} km.
            </p>
            <button type="button"
                    onClick={() => { setSegment('all'); setStatus(''); setSpend(''); setJoined(''); setTyped(''); setPage(1); }}
                    className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-[#E6EEFB] bg-white px-3 py-1.5 text-[12px] font-semibold text-[#334155] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
              <X size={12} /> Réinitialiser les filtres
            </button>
          </div>
        )}
      </section>

      {/* table */}
      <section className="rounded-2xl border border-[#E6EEFB] bg-white shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
        <header className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
          <h2 className="text-[17px] font-bold text-[#0B1C3F]">
            {nf(feed.total)} client{feed.total > 1 ? 's' : ''}
            {activeSegment && segment !== 'all' && (
              <span className="ml-2 inline-flex items-center gap-1.5 rounded-lg bg-[#EAF1FF] px-2 py-0.5 align-middle text-[12.5px] font-semibold text-[#2F6BFF]">
                {activeSegment.label}
                <button type="button" aria-label="Retirer ce filtre" onClick={() => { setSegment('all'); setPage(1); }} className="text-[#2F6BFF] hover:text-[#0B1C3F]">×</button>
              </span>
            )}
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => openCompose(picked.length ? 'picked' : 'filter')}
                    disabled={!feed.total}
                    className="inline-flex items-center gap-1.5 rounded-xl bg-[#2F6BFF] px-3 py-2 text-[12.5px] font-semibold text-white transition hover:bg-[#2559DB] disabled:opacity-50">
              <Mail size={13} /> Contacter ({nf(picked.length || feed.total)})
            </button>
            <div className="relative">
              <select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }}
                      className="appearance-none rounded-xl border border-[#E6EEFB] bg-white py-2 pl-3 pr-8 text-[12.5px] font-medium text-[#334155] outline-none focus:border-[#2F6BFF]">
                {(meta?.sorts || []).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
              </select>
              <ChevronDown size={14} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            </div>
            <button type="button" onClick={exportCsv} disabled={exporting}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-[#E6EEFB] px-3 py-2 text-[12.5px] font-semibold text-[#334155] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF] disabled:opacity-60">
              {exporting ? <Loader2 size={13} className="animate-spin" /> : <Columns3 size={13} />} Exporter
            </button>
          </div>
        </header>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] border-collapse">
            <thead>
              <tr className="border-y border-[#EEF3FB] bg-[#FAFCFF] text-left">
                <th className="w-10 px-4 py-3">
                  <input type="checkbox" checked={allPicked} aria-label="Tout sélectionner"
                         onChange={() => setPicked(allPicked ? [] : feed.rows.map((r) => r.id))}
                         className="h-4 w-4 accent-[#2F6BFF]" />
                </th>
                {['Client', 'Statut', 'Segment', 'Dernière visite', 'Total dépensé', 'Actions'].map((h, i) => (
                  <th key={h} className={`px-4 py-3 text-[12px] font-semibold text-[#64748B] ${i === 4 ? 'text-right' : ''}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && feed.rows.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-14 text-center text-[13px] text-[#64748B]">
                  <Loader2 size={16} className="mr-2 inline animate-spin" /> Chargement des clients…
                </td></tr>
              )}
              {!loading && feed.rows.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-14 text-center">
                  <p className="text-[13.5px] font-semibold text-[#0B1C3F]">Aucun client ici</p>
                  <p className="mt-1 text-[12.5px] text-[#64748B]">
                    {search || status || spend || joined || segment !== 'all'
                      ? 'Retirez un filtre pour en voir plus.'
                      : 'Vos clients apparaîtront dès la première inscription.'}
                  </p>
                </td></tr>
              )}
              {feed.rows.map((r) => {
                const st = TONES[r.status_tone] || TONES.blue;
                const segTone = TONES[(meta?.segments || []).find((s) => s.key === r.segment)?.tone] || TONES.blue;
                const SegIcon = SEGMENT_ICONS[(meta?.segments || []).find((s) => s.key === r.segment)?.icon] || Users;
                return (
                  <tr key={r.id} className="border-b border-[#F4F7FC] last:border-b-0 transition hover:bg-[#FAFCFF]">
                    <td className="px-4 py-3">
                      <input type="checkbox" checked={picked.includes(r.id)} aria-label={`Sélectionner ${r.name}`}
                             onChange={() => togglePick(r.id)} className="h-4 w-4 accent-[#2F6BFF]" />
                    </td>
                    <td className="px-4 py-3">
                      <span className="flex items-center gap-3">
                        <Avatar initials={r.initials} tier={r.tier} />
                        <span className="min-w-0">
                          <span className="block truncate text-[13.5px] font-semibold text-[#0B1C3F]">{r.name}</span>
                          <span className="block truncate text-[11.5px] text-[#94A3B8]">{r.email || r.phone || '—'}</span>
                        </span>
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11.5px] font-semibold"
                            style={{ background: st.bg, color: st.fg }}>
                        <span className="h-1.5 w-1.5 rounded-full" style={{ background: st.dot }} />
                        {r.status_label}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11.5px] font-semibold"
                            style={{ background: segTone.bg, color: segTone.fg }}>
                        <SegIcon size={12} /> {r.segment_label}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-[12.5px] text-[#475569]">{day(r.last_visit)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-right text-[13px] font-semibold tabular-nums text-[#0B1C3F]">
                      {money(r.spent)}
                    </td>
                    <td className="px-4 py-3">
                      <span className="flex items-center gap-1">
                        <button type="button" aria-label={`Contacter ${r.name}`}
                                onClick={() => navigate('/dashboard/campaigns')}
                                className="flex h-8 w-8 items-center justify-center rounded-lg border border-[#E6EEFB] text-[#475569] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
                          <Mail size={14} />
                        </button>
                        <span className="relative">
                          <button type="button" aria-label="Plus d'actions"
                                  onClick={(e) => { e.stopPropagation(); setMenuFor(menuFor === r.id ? null : r.id); }}
                                  className="flex h-8 w-8 items-center justify-center rounded-lg text-[#94A3B8] transition hover:bg-[#F4F7FC] hover:text-[#0B1C3F]">
                            <MoreVertical size={15} />
                          </button>
                          {menuFor === r.id && (
                            <span onClick={(e) => e.stopPropagation()}
                                  className="absolute right-0 top-full z-20 mt-1 flex w-[200px] flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-[0_24px_60px_-28px_rgba(11,28,63,.5)]">
                              {r.barcode_id && (
                                <a href={`/card/${r.barcode_id}`} target="_blank" rel="noreferrer"
                                   className="px-3 py-2 text-left text-[12.5px] text-[#334155] hover:bg-[#F4F7FC]">
                                  Voir sa carte
                                </a>
                              )}
                              <button type="button" onClick={() => navigate('/dashboard/scan')}
                                      className="px-3 py-2 text-left text-[12.5px] text-[#334155] hover:bg-[#F4F7FC]">
                                Enregistrer une visite
                              </button>
                              <button type="button" onClick={needCrm(() => { setMenuFor(null); setSegment(r.segment); setPage(1); })}
                                      className="px-3 py-2 text-left text-[12.5px] text-[#334155] hover:bg-[#F4F7FC]">
                                Filtrer sur « {r.segment_label} »
                              </button>
                            </span>
                          )}
                        </span>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* pagination */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#EEF3FB] px-5 py-3.5">
          <div className="flex items-center gap-2">
            <button type="button" disabled={feed.page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}
                    className="flex h-8 w-8 items-center justify-center rounded-lg border border-[#E6EEFB] text-[#475569] transition hover:border-[#2F6BFF] disabled:opacity-40">
              <ChevronLeft size={15} />
            </button>
            {pageNumbers.map((n) => (
              <button key={n} type="button" onClick={() => setPage(n)}
                      className={`h-8 min-w-8 rounded-lg px-2 text-[12.5px] font-semibold transition ${
                        n === feed.page ? 'bg-[#2F6BFF] text-white'
                                        : 'border border-[#E6EEFB] text-[#475569] hover:border-[#2F6BFF]'}`}>
                {n}
              </button>
            ))}
            {feed.pages > 5 && feed.page < feed.pages - 2 && (
              <>
                <span className="px-1 text-[12.5px] text-[#94A3B8]">…</span>
                <button type="button" onClick={() => setPage(feed.pages)}
                        className="h-8 min-w-8 rounded-lg border border-[#E6EEFB] px-2 text-[12.5px] font-semibold text-[#475569] hover:border-[#2F6BFF]">
                  {feed.pages}
                </button>
              </>
            )}
            <button type="button" disabled={feed.page >= feed.pages} onClick={() => setPage((p) => p + 1)}
                    className="flex h-8 w-8 items-center justify-center rounded-lg border border-[#E6EEFB] text-[#475569] transition hover:border-[#2F6BFF] disabled:opacity-40">
              <ChevronRight size={15} />
            </button>
          </div>
          <label className="flex items-center gap-2 text-[12.5px] text-[#64748B]">
            Afficher
            <span className="relative">
              <select value={perPage} onChange={(e) => { setPerPage(Number(e.target.value)); setPage(1); }}
                      className="appearance-none rounded-lg border border-[#E6EEFB] bg-white py-1.5 pl-3 pr-8 text-[12.5px] text-[#334155] outline-none focus:border-[#2F6BFF]">
                {[10, 20, 25, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              <ChevronDown size={13} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            </span>
            par page
          </label>
        </div>
      </section>

      {compose && (
        <ComposeModal count={compose.ids.length} label={compose.label}
                      onClose={() => setCompose(null)} onSend={sendCompose} />
      )}
    </div>
  );
}
