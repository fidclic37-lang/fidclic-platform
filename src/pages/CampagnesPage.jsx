import React, { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Send, Users, Mail, BarChart3, Euro, ArrowRight, Search, Filter, ChevronLeft, ChevronRight, MoreVertical, Loader2,
  CheckCircle2,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { confirmImportant } from '../lib/prefs';
import { eur } from '../lib/money';
import InfoTip from '../components/InfoTip';
import { ResultModal } from '../components/CampaignLearning';
import CampaignWizard, { emptyState } from '../components/campagnes/CampaignWizard';
import CampaignDetail from '../components/campagnes/CampaignDetail';
import { KIND_META, TYPE_ORDER } from '../components/campagnes/kinds';

/**
 * Campagnes — redesigned from the user's mockups (2026-10-10): the five
 * figures of this month « vs. mois précédent », the five types of campaign,
 * and « Vos campagnes récentes » by status. Creating one opens the five-step
 * wizard (components/campagnes/CampaignWizard). The old page stays unrouted
 * as CampagnesPageLegacy.jsx.
 */
const STRIP = {
  sent: { icon: Send, bg: '#EAF1FF', fg: '#2F6BFF' },
  reach: { icon: Users, bg: '#E3F6EC', fg: '#059669' },
  open_rate: { icon: Mail, bg: '#FFECEC', fg: '#EF4444' },
  clicks: { icon: BarChart3, bg: '#F1EAFF', fg: '#7C3AED' },
  revenue: { icon: Euro, bg: '#FFF1DC', fg: '#F59E0B' },
};
const STATUS = {
  live: ['En cours', '#EAF1FF', '#1D4ED8'], ended: ['Terminée', '#E3F6EC', '#047857'],
  scheduled: ['Programmée', '#F1EAFF', '#6D28D9'], cancelled: ['Annulée', '#F1F5F9', '#64748B'],
  draft: ['Brouillon', '#F1F5F9', '#475569'], sending: ["En cours d'envoi", '#EAF1FF', '#1D4ED8'],
};
const TABS = [['all', 'Toutes'], ['live', 'En cours'], ['scheduled', 'Programmées'], ['ended', 'Terminées'], ['cancelled', 'Annulées']];
const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');
const when = (iso, withTime) => {
  if (!iso) return '—';
  const d = new Date(iso);
  const day = `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  return withTime ? `${day} à ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}` : day;
};
const ymd = (iso) => {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

function Stat({ s }) {
  const m = STRIP[s.key] || STRIP.sent;
  const I = m.icon;
  const has = s.delta_pct !== null && s.delta_pct !== undefined;
  const up = (s.delta_pct ?? 0) >= 0;
  return (
    <div className="relative rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <span className={`absolute right-3 top-3 rounded-lg px-2 py-0.5 text-[12px] font-semibold ${has ? (up ? 'bg-[#E3F6EC] text-[#047857]' : 'bg-[#FFECEC] text-[#B91C1C]') : 'bg-[#F1F5F9] text-[#64748B]'}`}>
        {has ? `${up ? '↑ +' : '↓ '}${s.delta_pct}%` : '-'}
      </span>
      <div className="flex items-center gap-3">
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl" style={{ background: m.bg, color: m.fg }}><I size={24} /></span>
        <div className="min-w-0">
          <p className="text-[24px] font-extrabold leading-none tabular-nums text-[#0B1C3F]">
            {s.unit === '€' ? eur(s.value) : `${nf(s.value)}${s.unit || ''}`}
          </p>
          <p className="mt-1 flex items-center gap-1 text-[13.5px] font-medium text-[#334155]">
            {s.label} <InfoTip k={{ sent: 'campaigns_sent', revenue: 'campaign_revenue' }[s.key] || s.key} size={13} />
          </p>
          <p className="text-[12px] text-[#64748B]">Ce mois-ci · vs. mois précédent</p>
        </div>
      </div>
    </div>
  );
}

// the kinds a link may open the composer on (?nouveau=… or a template's own kind)
const KINDS_OK = ['offre', 'nouveaute', 'evenement', 'defi', 'configurer'];

export default function CampagnesPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [flash, setFlash] = useState('');
  const [list, setList] = useState({ rows: [], total: 0, page: 1, pages: 1, counts: {} });
  const [tab, setTab] = useState('all');
  const [search, setSearch] = useState('');
  const [kindFilter, setKindFilter] = useState('');
  const [filterOpen, setFilterOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(5);
  const [listBusy, setListBusy] = useState(false);
  const [menu, setMenu] = useState(null);
  const [resultOf, setResultOf] = useState(null);
  const [detailOf, setDetailOf] = useState(null);       // a row opened
  const [wizard, setWizard] = useState(null);          // { initial, step }

  const load = useCallback(() => {
    ownerAPI.campaignsPage().then(({ data: d }) => { setData(d); setError(''); })
      .catch((e) => setError(e?.response?.data?.detail || 'Impossible de charger la page.'));
  }, []);
  const loadList = useCallback(() => {
    setListBusy(true);
    ownerAPI.campaignsList({ tab, search: search.trim() || undefined, page, per_page: perPage, kind: kindFilter || undefined })
      .then(({ data: d }) => setList(d))
      .catch((e) => setError(e?.response?.data?.detail || 'Impossible de charger les campagnes.'))
      .finally(() => setListBusy(false));
  }, [tab, search, page, perPage, kindFilter]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { const t0 = setTimeout(loadList, search ? 250 : 0); return () => clearTimeout(t0); }, [loadList, search]);

  // Insights / Clients / an alert hand a message over with ?template=: the
  // wizard opens on the message, its audience set.
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const clean = () => {
      const rest = new URLSearchParams(location.search);
      ['template', 'day', 'store', 'from', 'nouveau', 'analyse'].forEach((k) => rest.delete(k));
      navigate({ pathname: location.pathname, search: rest.toString() ? `?${rest}` : '' }, { replace: true });
    };
    // ?nouveau=offre (a dashboard / recommendation « Créer… »): the composer
    // itself, never a page to look for it on (user, 2026-10-23)
    const fresh = params.get('nouveau');
    if (fresh && KINDS_OK.includes(fresh)) { setWizard({ initial: emptyState(fresh), step: 1 }); clean(); return; }
    // ?analyse=<id> (the dashboard's « Analyse détaillée »): that campaign's result
    const shown = params.get('analyse');
    if (shown) { setResultOf(shown); clean(); return; }
    const key = params.get('template');
    if (!key) return;
    ownerAPI.insightTemplate(key, params.get('day'), params.get('store'), params.get('from'))
      .then(({ data: t }) => {
        const st = emptyState(KINDS_OK.includes(t.kind) ? t.kind : 'offre');
        st.title = (t.title || '').slice(0, 50); st.message = (t.message || '').slice(0, 160);
        st.template = /^(client|produit|brain|ia|prc):/.test(key) ? key.split(':')[0] : key;
        // the idea's full key and the surface it was taken from (journal of ideas, 2026-10-29)
        st.recoKey = key; st.recoSurface = params.get('from') || null;
        // a narrower audience is sent by id, never widened to everyone — even
        // when no client matches it today (then the wizard asks for a choice)
        if (t.audience) st.audience = { ...st.audience, mode: 'custom', customer_ids: t.audience.ids || [] };
        else if (t.segment && t.segment !== 'all') st.audience = { ...st.audience, mode: 'segment', segment: t.segment };
        // a store's card counts who came there; only its own members get the message
        if (t.audience?.note) st.audienceNote = t.audience.note;
        if (t.audience && !t.audience.ids?.length) st.notice = t.audience.note || `Modèle chargé — mais aucun client ne correspond à « ${t.audience.label} » pour l'instant.`;
        // a template that leaves the offer to set (a product to put forward) opens on it
        setWizard({ initial: st, step: t.start_step === 1 ? 1 : 2 });
      })
      .catch(() => setError("Ce modèle n'a pas pu être chargé."))
      .finally(() => {
        const rest = new URLSearchParams(location.search);
        ['template', 'day', 'store', 'from'].forEach((k) => rest.delete(k));
        navigate({ pathname: location.pathname, search: rest.toString() ? `?${rest}` : '' }, { replace: true });
      });
  }, [location.search]); // eslint-disable-line react-hooks/exhaustive-deps

  // « Configurer une offre » opens the same wizard: any message outside the
  // four other types (user, 2026-10-10)
  const start = (kind) => setWizard({ initial: emptyState(kind), step: 1 });

  // « Modifier » a draft, a planned or a cancelled campaign
  const edit = async (row) => {
    setMenu(null); setError(''); setDetailOf(null);
    try {
      const { data: d } = await ownerAPI.campaignDraft(row.id);
      const kind = d.kind || 'offre';
      const st = emptyState(kind);
      Object.assign(st, { title: d.title || '', message: d.message || '', details: d.details || '', image: d.image_url || '',
        link: d.link_url || '', draftId: d.id, template: d.template || null, walletPhoto: !!d.wallet_photo,
        recoKey: d.reco_key || null, recoSurface: d.reco_surface || null,
        visibleUntil: d.visible_until || st.visibleUntil });
      if (d.offer) st.offer = { ...st.offer, ...d.offer, discount_type: d.offer.discount_type || null,   // a saved offer with no type keeps none
        discount_value: d.offer.discount_value ?? '', start_date: d.offer.start_date || '', end_date: d.offer.end_date || '',
        time_from: d.offer.time_from || '17:00', time_to: d.offer.time_to || '19:00' };
      if (d.event) st.event = { date: d.event.date || '', time: d.event.time || '', place: d.event.place || '' };
      if (d.defi) st.defi = { ...d.defi, target: String(d.defi.target), reward_valid_days: String(d.defi.reward_valid_days) };
      const sp = d.audience_spec;
      if (sp) st.audience = { ...st.audience, ...sp, customer_ids: sp.customer_ids || [], km: sp.km || 5,
        filters: { ...st.audience.filters, ...(sp.filters || {}) } };
      else if (d.audience?.ids?.length) st.audience = { ...st.audience, mode: 'custom', customer_ids: d.audience.ids };
      else if (d.segment && d.segment !== 'all') st.audience = { ...st.audience, mode: 'segment', segment: d.segment };
      if (d.status === 'scheduled' && d.scheduled_for) {
        const w = new Date(d.scheduled_for);
        Object.assign(st, { sendMode: 'later', date: ymd(d.scheduled_for),
          time: `${String(w.getHours()).padStart(2, '0')}:${String(w.getMinutes()).padStart(2, '0')}` });
      }
      setWizard({ initial: st, step: 1 });
    } catch (e) {
      setError(e?.response?.data?.detail || "Cette campagne n'a pas pu être ouverte."); loadList();
    }
  };
  const cancel = async (row) => {
    setMenu(null);
    if (!confirmImportant(`Annuler l'envoi programmé de « ${row.name} » ?`)) return;
    setDetailOf(null);
    try { await ownerAPI.cancelCampaignSchedule(row.id); setFlash('Envoi annulé : la campagne est dans « Annulées ».'); loadList(); }
    catch (e) { setError(e?.response?.data?.detail || "L'envoi n'a pas pu être annulé."); loadList(); }
  };
  const remove = async (row) => {
    setMenu(null);
    if (!confirmImportant(`Supprimer « ${row.name} » ?`)) return;
    setDetailOf(null);
    try { await ownerAPI.deleteCampaignDraft(row.id); setFlash('Campagne supprimée.'); loadList(); }
    catch (e) { setError(e?.response?.data?.detail || "La campagne n'a pas pu être supprimée."); }
  };

  const shownRows = list.rows;
  const { pages, total } = list;

  return (
    <div className="cg pb-10">
      {detailOf && (
        <CampaignDetail id={detailOf} onClose={() => setDetailOf(null)} onEdit={edit} onCancel={cancel} onDelete={remove}
                        onAnalysis={(id) => setResultOf(id)} />
      )}
      {resultOf && <ResultModal id={resultOf} onClose={() => setResultOf(null)} />}
      {wizard && (
        <CampaignWizard initial={wizard.initial} startStep={wizard.step} page={data}
                        onClose={() => setWizard(null)}
                        onDone={(msg) => { setWizard(null); setFlash(msg); load(); loadList(); }} />
      )}

      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-3 text-[32px] font-extrabold leading-tight text-[#0B1C3F]">
            Campagnes
            <span className="inline-flex items-center gap-1 rounded-full bg-[#E3F6EC] px-2.5 py-0.5 text-[12px] font-bold text-[#047857]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#10B981]" /> LIVE
            </span>
          </h1>
          <p className="mt-1 text-[15px] text-[#475569]">Créez et envoyez des notifications à vos clients pour les faire revenir et augmenter votre chiffre d'affaires.</p>
        </div>
        <button type="button" onClick={() => navigate('/dashboard/campaigns/reports')}
                className="inline-flex items-center gap-2 rounded-xl border border-[#E2E8F0] bg-white px-4 py-3 text-[14px] font-semibold text-[#0B1C3F] shadow-sm">
          <BarChart3 size={18} className="text-[#2F6BFF]" /> Voir les performances
        </button>
      </header>

      {flash && (
        <p role="status" className="mb-4 flex items-center gap-2 rounded-xl bg-[#E3F6EC] px-4 py-3 text-[14px] font-medium text-[#047857]">
          <CheckCircle2 size={16} /> {flash}
          <button type="button" onClick={() => setFlash('')} className="ml-auto text-[13px] underline">Fermer</button>
        </p>
      )}
      {error && <p role="alert" className="mb-4 rounded-xl bg-[#FEF2F2] px-4 py-3 text-[14px] text-[#B91C1C]">{error}</p>}

      <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {(data?.strip || []).map((s) => <Stat key={s.key} s={s} />)}
        {!data && [0, 1, 2, 3, 4].map((i) => <div key={i} className="h-[96px] animate-pulse rounded-2xl bg-white" />)}
      </div>

      <section className="mb-5 rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
        <h2 className="text-[22px] font-extrabold text-[#0B1C3F]">Choisissez le type de campagne</h2>
        <p className="mb-4 text-[14.5px] text-[#475569]">Sélectionnez un modèle adapté à votre objectif. Vous pourrez le personnaliser ensuite.</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {TYPE_ORDER.map((k) => {
            const m = KIND_META[k];
            const I = m.icon;
            return (
              <div key={k} className="group flex h-full flex-col rounded-2xl border border-[#E6EEFB] bg-white p-4 transition hover:border-[#2F6BFF] hover:bg-[#F8FAFF] hover:shadow-[0_14px_30px_-24px_rgba(20,99,255,.7)]">
                <div className="flex flex-1 items-start gap-3">
                  <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl" style={{ background: m.bg, color: m.fg }}><I size={26} /></span>
                  <span className="min-w-0"><span className="block text-[16px] font-bold text-[#0B1C3F]">{m.label}</span>
                    <span className="mt-1 block text-[13px] leading-snug text-[#64748B]">{m.sub}</span></span>
                </div>
                <button type="button" onClick={() => start(k)}
                        className="mt-4 inline-flex items-center justify-center gap-2 rounded-xl border border-[#2F6BFF] py-3 text-[15px] font-semibold text-[#1463FF] transition group-hover:bg-[#1463FF] group-hover:text-white">
                  Choisir <ArrowRight size={17} />
                </button>
              </div>
            );
          })}
        </div>
      </section>

      <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-[22px] font-extrabold text-[#0B1C3F]">Vos campagnes récentes</h2>
          <div className="relative flex items-center gap-2">
            <span className="flex w-[300px] max-w-full items-center gap-2 rounded-xl border border-[#E2E8F0] px-3">
              <Search size={17} className="text-[#64748B]" />
              <input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Rechercher une campagne…"
                     className="min-w-0 flex-1 !border-0 bg-transparent py-2.5 !text-[15px] !shadow-none !outline-none !ring-0" />
            </span>
            <button type="button" aria-label="Filtrer par type" onClick={() => setFilterOpen((v) => !v)}
                    className={`rounded-xl border p-2.5 ${kindFilter ? 'border-[#2F6BFF] bg-[#F1F6FF] text-[#1463FF]' : 'border-[#E2E8F0] text-[#1463FF]'}`}>
              <Filter size={18} />
            </button>
            {filterOpen && (
              <div className="absolute right-0 top-12 z-20 w-56 rounded-xl border border-[#E2E8F0] bg-white p-1.5 shadow-xl">
                {[['', 'Tous les types'], ...['offre', 'nouveaute', 'defi', 'evenement', 'configurer', 'message'].map((k) => [k, KIND_META[k].label])].map(([k, l]) => (
                  <button key={k || 'all'} type="button" onClick={() => { setKindFilter(k); setFilterOpen(false); setPage(1); }}
                          className={`block w-full rounded-lg px-3 py-2 text-left text-[14px] ${kindFilter === k ? 'bg-[#F1F6FF] font-semibold text-[#1463FF]' : 'text-[#0B1C3F] hover:bg-[#F8FAFC]'}`}>{l}</button>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="mb-3 flex flex-wrap gap-2">
          {TABS.map(([k, l]) => (
            <button key={k} type="button" onClick={() => { setTab(k); setPage(1); }}
                    className={`rounded-xl px-4 py-2 text-[14px] font-semibold ${tab === k ? 'bg-[#1463FF] text-white' : 'bg-[#F1F5F9] text-[#334155] hover:bg-[#E8EEF7]'}`}>
              {l}{list.counts?.[k] ? <span className={`ml-1.5 text-[12px] ${tab === k ? 'text-white/80' : 'text-[#64748B]'}`}>{list.counts[k]}</span> : null}
            </button>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] border-collapse">
            <thead>
              <tr className="text-left text-[13px] text-[#475569]">
                {['Nom de la campagne', 'Type', 'Destinataires', "Taux d'ouverture", 'Statut', 'Envoyée le', 'Action', ''].map((h) => (
                  <th key={h} className="px-3 py-3 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {listBusy && !shownRows.length && (
                <tr><td colSpan={8} className="py-10 text-center text-[13px] text-[#64748B]"><Loader2 size={16} className="inline animate-spin" /> Chargement…</td></tr>
              )}
              {!listBusy && !shownRows.length && (
                <tr><td colSpan={8} className="py-10 text-center text-[14px] text-[#64748B]">
                  {search || kindFilter || tab !== 'all' ? 'Aucune campagne ne correspond.' : 'Aucune campagne pour le moment : choisissez un type ci-dessus pour commencer.'}
                </td></tr>
              )}
              {shownRows.map((r) => {
                const m = KIND_META[r.kind] || KIND_META.message;
                const I = m.icon;
                const [sl, sbg, sfg] = STATUS[r.status] || STATUS.draft;
                const editable = ['draft', 'scheduled', 'cancelled'].includes(r.status);
                return (
                  <tr key={r.id} onClick={() => setDetailOf(r.id)} tabIndex={0} aria-label={`Ouvrir la campagne ${r.name}`}
                      onKeyDown={(e) => { if (e.key === 'Enter' && e.target === e.currentTarget) setDetailOf(r.id); }}
                      className="cursor-pointer border-t border-[#EEF2F7] transition hover:bg-[#F8FAFF] focus:bg-[#F8FAFF] focus:outline-none">
                    <td className="px-3 py-3">
                      <span className="flex items-center gap-3">
                        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl" style={{ background: m.bg, color: m.fg }}><I size={20} /></span>
                        <span className="min-w-0"><span className="block max-w-[240px] truncate text-[14.5px] font-bold text-[#0B1C3F]">{r.name}</span>
                          {r.terms && <span className="block max-w-[240px] truncate text-[12px] text-[#64748B]">{r.terms}</span>}</span>
                      </span>
                    </td>
                    <td className="px-3 py-3"><span className="flex items-center gap-2 text-[14px] text-[#475569]">
                      <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ background: m.bg, color: m.fg }}><I size={14} /></span>{r.type_label}</span></td>
                    <td className="px-3 py-3 text-[14px] text-[#475569]">{nf(r.recipients)} client{r.recipients > 1 ? 's' : ''}</td>
                    <td className="px-3 py-3">
                      {r.open_rate == null ? <span className="text-[13px] text-[#94A3B8]">—</span> : (
                        <span className="flex items-center gap-2">
                          <span className="w-10 text-[14px] font-bold tabular-nums text-[#0B1C3F]">{r.open_rate} %</span>
                          <span className="h-2 w-24 overflow-hidden rounded-full bg-[#E8EEF7]">
                            <span className="block h-full rounded-full" style={{ width: `${Math.min(100, r.open_rate)}%`, background: r.open_rate < 50 ? '#F59E0B' : '#2F6BFF' }} />
                          </span>
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <span className="rounded-lg px-2.5 py-1 text-[13px] font-semibold" style={{ background: sbg, color: sfg }} title={r.cancel_reason || undefined}>{sl}</span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-[14px] text-[#475569]">
                      {r.sent_at ? when(r.sent_at) : r.status === 'scheduled' ? when(r.scheduled_for, true) : '—'}
                    </td>
                    <td className="whitespace-nowrap px-3 py-3" onClick={(e) => e.stopPropagation()}>
                      {editable ? (
                        <button type="button" onClick={() => edit(r)} className="inline-flex items-center gap-1.5 text-[14px] font-semibold text-[#1463FF]">Modifier <ArrowRight size={15} /></button>
                      ) : r.sent_at ? (
                        <button type="button" onClick={() => setDetailOf(r.id)} className="inline-flex items-center gap-1.5 text-[14px] font-semibold text-[#1463FF]">Voir les résultats <ArrowRight size={15} /></button>
                      ) : null}
                    </td>
                    <td className="relative px-2 py-3" onClick={(e) => e.stopPropagation()}>
                      <button type="button" aria-label="Plus d'actions" onClick={() => setMenu(menu === r.id ? null : r.id)} className="rounded-lg p-1.5 text-[#0B1C3F] hover:bg-[#F1F5F9]"><MoreVertical size={18} /></button>
                      {menu === r.id && (
                        <div className="absolute right-2 top-11 z-20 w-52 rounded-xl border border-[#E2E8F0] bg-white p-1.5 shadow-xl">
                          {r.sent_at && <button type="button" onClick={() => { setMenu(null); setDetailOf(r.id); }} className="block w-full rounded-lg px-3 py-2 text-left text-[14px] hover:bg-[#F8FAFC]">Voir les résultats</button>}
                          {editable && <button type="button" onClick={() => edit(r)} className="block w-full rounded-lg px-3 py-2 text-left text-[14px] hover:bg-[#F8FAFC]">Modifier</button>}
                          {r.status === 'scheduled' && <button type="button" onClick={() => cancel(r)} className="block w-full rounded-lg px-3 py-2 text-left text-[14px] text-[#B45309] hover:bg-[#FFF7ED]">Annuler l'envoi</button>}
                          {['draft', 'cancelled'].includes(r.status) && <button type="button" onClick={() => remove(r)} className="block w-full rounded-lg px-3 py-2 text-left text-[14px] text-[#DC2626] hover:bg-[#FEF2F2]">Supprimer</button>}
                          {!r.sent_at && !editable && <span className="block px-3 py-2 text-[13px] text-[#94A3B8]">Aucune action</span>}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-[14px] text-[#475569]">
          <span>{total ? `Affichage de ${(page - 1) * perPage + 1} à ${Math.min(page * perPage, total)} sur ${nf(total)} campagne${total > 1 ? 's' : ''}` : ''}</span>
          <span className="flex items-center gap-2">
            <button type="button" aria-label="Page précédente" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="rounded-lg border border-[#E2E8F0] p-2 disabled:opacity-40"><ChevronLeft size={16} /></button>
            {Array.from({ length: Math.min(pages, 5) }, (_, i) => {
              const n = Math.max(1, Math.min(page - 2, pages - 4)) + i;
              return (
                <button key={n} type="button" onClick={() => setPage(n)}
                        className={`h-9 min-w-[36px] rounded-lg border px-2 font-semibold ${n === page ? 'border-[#BFD3FF] bg-[#EAF1FF] text-[#1463FF]' : 'border-[#E2E8F0] text-[#334155]'}`}>{n}</button>
              );
            })}
            <button type="button" aria-label="Page suivante" disabled={page >= pages} onClick={() => setPage((p) => p + 1)} className="rounded-lg border border-[#E2E8F0] p-2 disabled:opacity-40"><ChevronRight size={16} /></button>
            <select aria-label="Campagnes par page" value={perPage} onChange={(e) => { setPerPage(Number(e.target.value)); setPage(1); }}
                    className="ml-2 rounded-lg border border-[#E2E8F0] px-2 py-2 text-[14px] font-semibold">
              {[5, 10, 20].map((n) => <option key={n} value={n}>{n} par page</option>)}
            </select>
          </span>
        </div>
      </section>
    </div>
  );
}
