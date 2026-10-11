import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Zap, Plus, Send, Users, Mail, ArrowUp, ArrowDown, Bot, Check, Search, MoreHorizontal, MessageSquare,
  CheckCircle2, Loader2, X, CalendarDays, Lock, Settings2, Sparkles,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { confirmImportant } from '../lib/prefs';
import AutopilotPanel from '../components/AutopilotPanel';
import { ICONS, TONES, STATUS } from '../components/automations/meta';

/**
 * Automatisations — redesigned from the user's mockups (2026-10-11): three
 * figures, the Autopilot banner, « Mes automatisations » (eight scenarios,
 * several of each), and the « Exemples de messages » rail. Creating or editing
 * opens the six-step editor (AutomationEditorPage). The old page stays
 * unrouted as AutomationsPageLegacy.jsx.
 */
const TABS = [['all', 'Toutes'], ['active', 'Actives'], ['paused', 'En pause'], ['draft', 'Brouillons'], ['ended', 'Terminées']];
const SORTS = [['recent', 'Plus récentes'], ['old', 'Plus anciennes'], ['name', 'Nom (A → Z)'], ['reach', 'Plus de clients touchés']];
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');
// the mockup's one-line taglines under each automation's name
const TAGLINE = {
  birthday: 'Souhaitez un joyeux anniversaire', tier_up: 'Félicitez vos clients', welcome: 'Accueillez les nouveaux clients',
  near_reward: 'Motivez la dernière visite', referral: 'Remerciez parrains et filleuls', geo: 'Attirez les clients à proximité',
  google_review: 'Demandez un avis', inactive: 'Relancez les clients inactifs',
  custom: 'Votre message, votre moment',
};

function Kpi({ tone, icon: I, value, label, sub, delta, unit = '%' }) {
  const [bg, fg, tile] = tone;
  const up = (delta ?? 0) >= 0;
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-[#E6EEFB] p-4" style={{ background: bg }}>
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl" style={{ background: tile, color: fg }}><I size={22} /></span>
      <div className="min-w-0">
        <p className="text-[23px] font-extrabold leading-none tabular-nums text-[#0B1C3F]">{value}</p>
        <p className="mt-1 text-[13.5px] font-medium text-[#334155]">{label}</p>
        {sub && <p className="text-[12px] text-[#64748B]">{sub}</p>}
        {delta !== undefined && delta !== null && (
          <p className={`mt-0.5 flex items-center gap-1 text-[12.5px] font-semibold ${up ? 'text-[#047857]' : 'text-[#B91C1C]'}`}>
            {up ? <ArrowUp size={14} /> : <ArrowDown size={14} />}{up ? '+' : ''}{String(delta).replace('.', ',')}{unit}
          </p>
        )}
      </div>
    </div>
  );
}

function AutopilotBanner({ onOpen }) {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => { ownerAPI.autopilot().then(({ data }) => setD(data)).catch(() => setD({ plan_ok: false, can_edit: false, settings: {} })); }, []);
  const on = Boolean(d?.settings?.daily?.enabled || d?.settings?.weekly?.enabled);
  const can = Boolean(d?.plan_ok && d?.can_edit);
  const toggle = async (v) => {
    setBusy(true); setErr('');
    try {
      const cur = d.settings || {};
      const { data } = await ownerAPI.saveAutopilot(v ? { daily: { ...(cur.daily || {}), enabled: true } }
        : { daily: { ...(cur.daily || {}), enabled: false }, weekly: { ...(cur.weekly || {}), enabled: false } });
      setD(data);
    } catch (e) { setErr(e?.response?.data?.detail?.message || e?.response?.data?.detail || "L'Autopilot n'a pas pu être modifié."); }
    finally { setBusy(false); }
  };
  return (
    <section className="mb-5 flex flex-wrap items-center gap-4 rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#F1EAFF] text-[#7C3AED]"><Bot size={28} /></span>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-2 text-[16px] font-extrabold text-[#0B1C3F]">Mode automatique (Autopilot)
          <span className="rounded-lg bg-[#F1EAFF] px-2.5 py-0.5 text-[12px] font-bold text-[#7C3AED]">Pro AI</span></p>
        <p className="text-[13px] text-[#475569]">Laissez FIDCLIC préparer automatiquement des messages selon le comportement de vos clients.</p>
        <p className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-[12.5px] text-[#334155]">
          {['Messages prêts à l\'emploi', 'Basés sur les bonnes pratiques', 'Activables en 1 clic'].map((t) => (
            <span key={t} className="flex items-center gap-1.5"><Check size={15} className="text-[#2F6BFF]" /> {t}</span>))}
        </p>
        {err && <p className="mt-1 text-[12px] text-[#B91C1C]">{err}</p>}
      </div>
      <div className="flex flex-col items-center gap-1">
        {d && !d.plan_ok ? (
          <span className="flex items-center gap-1.5 rounded-xl bg-[#F8FAFC] px-3 py-2 text-[12px] font-semibold text-[#64748B]"><Lock size={14} /> Offre Pro AI</span>
        ) : (
          <>
            <button type="button" role="switch" aria-checked={on} aria-label="Mode automatique" disabled={!can || busy} onClick={() => toggle(!on)}
                    className={`relative h-7 w-12 rounded-full transition disabled:opacity-60 ${on ? 'bg-[#1463FF]' : 'bg-[#D6DEEA]'}`}>
              <span className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition ${on ? 'left-6' : 'left-1'}`} />
            </button>
            <span className={`text-[13px] font-semibold ${on ? 'text-[#1463FF]' : 'text-[#64748B]'}`}>{on ? 'Activé' : 'Désactivé'}</span>
          </>
        )}
        {d?.plan_ok && <button type="button" onClick={onOpen} className="mt-1 inline-flex items-center gap-1 text-[12px] font-semibold text-[#1463FF]"><Settings2 size={13} /> Réglages</button>}
      </div>
    </section>
  );
}

const IDEAS = ['Faire revenir les clients le mardi', 'Remercier après la 5e visite', 'Annoncer notre nouveau menu'];

/* « Besoin d'inspiration ? » — FidClic IA writes the message from the owner's
   objective; « Créer avec ce message » opens the editor on the scenario those
   words point to (user, 2026-10-11 — replaces the « Exemples » rail). */
function InspirationCard({ can, onUse }) {
  const [goal, setGoal] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [res, setRes] = useState(null);
  const write = async (text) => {
    const g = (text ?? goal).trim();
    if (!g) { setErr('Décrivez ce que vous voulez en une phrase.'); return; }
    setGoal(g); setBusy(true); setErr(''); setRes(null);
    try { const { data } = await ownerAPI.automationAiDraft(g); setRes(data); }
    catch (e) { setErr(e?.response?.data?.detail || "FidClic IA ne répond pas pour le moment."); }
    finally { setBusy(false); }
  };
  return (
    <section className="rounded-2xl border border-[#D6E4FF] bg-[#F3F7FF] p-4">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#1463FF] text-white"><Sparkles size={18} /></span>
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 text-[13.5px] font-bold text-[#0B1C3F]">Besoin d'inspiration ?
            <span className="rounded-md bg-[#E6EEFF] px-1.5 py-0.5 text-[11px] font-bold text-[#1463FF]">FidClic IA</span></p>
          <p className="text-[12px] leading-snug text-[#475569]">Dites ce que vous voulez : FidClic IA écrit le message et prépare l'automatisation.</p>
        </div>
      </div>
      {can ? (
        <>
          <textarea value={goal} maxLength={200} rows={2} onChange={(e) => { setGoal(e.target.value); setErr(''); }}
                    placeholder="Ex. faire revenir les clients le mardi"
                    className="mt-3 w-full resize-none rounded-xl border border-[#D9E2F2] bg-white px-3 py-2 !text-[14px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {IDEAS.map((i) => (
              <button key={i} type="button" onClick={() => write(i)} disabled={busy}
                      className="rounded-lg border border-[#D6E4FF] bg-white px-2 py-1 text-[11px] text-[#1D4ED8] hover:bg-[#EEF4FF]">{i}</button>
            ))}
          </div>
          {err && <p role="alert" className="mt-2 text-[12px] text-[#B91C1C]">{err}</p>}
          <button type="button" onClick={() => write()} disabled={busy}
                  className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#1463FF] py-2.5 text-[12.5px] font-semibold text-white disabled:opacity-60">
            {busy ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />} {busy ? 'FidClic IA écrit…' : 'Écrire avec FidClic IA'}
          </button>
          {res && (
            <div className="mt-3 rounded-xl border border-[#E6EEFB] bg-white p-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-[#64748B]">Proposition · {res.scenario_label}</p>
              <p className="mt-1 text-[12.5px] font-bold text-[#0B1C3F]">{res.title}</p>
              <p className="text-[12px] leading-snug text-[#334155]">{res.body}</p>
              <div className="mt-2.5 flex gap-2">
                <button type="button" onClick={() => onUse(res)}
                        className="flex-1 rounded-lg bg-[#1463FF] py-2 text-[12px] font-semibold text-white">Créer avec ce message</button>
                <button type="button" onClick={() => write()} disabled={busy}
                        className="rounded-lg border border-[#BFD3FF] px-3 py-2 text-[12px] font-semibold text-[#1463FF]">Autre idée</button>
              </div>
            </div>
          )}
        </>
      ) : (
        <p className="mt-3 text-[12px] text-[#64748B]">Seuls le propriétaire et les administrateurs créent des automatisations.</p>
      )}
    </section>
  );
}

export default function AutomationsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [d, setD] = useState(null);
  const [error, setError] = useState('');
  const [flash, setFlash] = useState(location.state?.flash || '');
  const [tab, setTab] = useState('all');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('recent');
  const [menu, setMenu] = useState(null);
  const [busyRow, setBusyRow] = useState('');
  const [autopilot, setAutopilot] = useState(false);

  const load = useCallback(() => {
    ownerAPI.automations().then(({ data }) => { setD(data); setError(''); })
      .catch((e) => setError(e?.response?.data?.detail || 'Impossible de charger les automatisations.'));
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (location.state?.flash) navigate(location.pathname, { replace: true, state: null }); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const rows = useMemo(() => {
    let r = (d?.rows || []).filter((x) => tab === 'all' || x.status === tab);
    const q = search.trim().toLowerCase();
    if (q) r = r.filter((x) => `${x.name} ${x.label} ${x.message?.title || ''} ${x.message?.body || ''}`.toLowerCase().includes(q));
    const by = {
      recent: (a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''),
      old: (a, b) => (a.updated_at || '').localeCompare(b.updated_at || ''),
      name: (a, b) => a.name.localeCompare(b.name, 'fr'),
      reach: (a, b) => (b.reach || 0) - (a.reach || 0),
    }[sort];
    return [...r].sort(by);
  }, [d, tab, search, sort]);

  const can = Boolean(d?.can_edit);
  const toggle = async (row) => {
    // « Terminée »: its period is over — the end date is changed in Planification
    if (row.status === 'ended') { navigate(`/dashboard/automations/${row.id}?step=5`); return; }
    setBusyRow(row.id); setError('');
    try {
      await ownerAPI.automationStatus(row.id, row.status === 'active' ? 'paused' : 'active');
      setFlash(row.status === 'active' ? `« ${row.name} » mise en pause.` : `« ${row.name} » activée.`);
      load();
    } catch (e) {
      setError(e?.response?.data?.detail || "Le statut n'a pas pu être changé.");
      if (row.status === 'draft') navigate(`/dashboard/automations/${row.id}`);
    } finally { setBusyRow(''); }
  };
  const duplicate = async (row) => {
    setMenu(null);
    try { await ownerAPI.duplicateAutomation(row.id); setFlash(`Copie de « ${row.name} » créée en brouillon.`); load(); }
    catch (e) { setError(e?.response?.data?.detail || "La copie n'a pas pu être créée."); }
  };
  const remove = async (row) => {
    setMenu(null);
    if (!confirmImportant(`Supprimer l'automatisation « ${row.name} » ? Elle ne partira plus.`)) return;
    try { await ownerAPI.deleteAutomation(row.id); setFlash('Automatisation supprimée.'); load(); }
    catch (e) { setError(e?.response?.data?.detail || "L'automatisation n'a pas pu être supprimée."); }
  };

  const st = d?.stats;

  return (
    <div className="pb-10" onClick={() => setMenu(null)}>
      {autopilot && (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[#0B1C3F]/45 p-3 sm:p-8" onClick={() => setAutopilot(false)}>
          <div className="w-full max-w-4xl rounded-3xl bg-white p-4 shadow-2xl sm:p-6" onClick={(e) => e.stopPropagation()}>
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-[17px] font-extrabold text-[#0B1C3F]">Réglages de l'Autopilot</h2>
              <button type="button" aria-label="Fermer" onClick={() => setAutopilot(false)} className="rounded-full p-2 hover:bg-[#F1F5F9]"><X size={20} /></button>
            </div>
            <AutopilotPanel />
          </div>
        </div>
      )}

      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-4">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#EEF4FF] text-[#1463FF]"><Zap size={22} /></span>
          <div>
            <h1 className="text-[26px] font-extrabold leading-tight text-[#0B1C3F]">Automatisations</h1>
            <p className="text-[13.5px] text-[#475569]">Créez des notifications automatiques pour fidéliser vos clients.</p>
          </div>
        </div>
        {can && (
          <button type="button" onClick={() => navigate('/dashboard/automations/nouvelle')}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#1463FF] px-5 py-2.5 text-[13.5px] font-semibold text-white shadow-[0_14px_30px_-14px_rgba(20,99,255,.8)] hover:bg-[#0F54E0]">
            <Plus size={19} /> Créer une automatisation
          </button>
        )}
      </header>

      {flash && (
        <p role="status" className="mb-4 flex items-center gap-2 rounded-xl bg-[#E3F6EC] px-4 py-3 text-[13px] font-medium text-[#047857]">
          <CheckCircle2 size={16} /> {flash}
          <button type="button" onClick={() => setFlash('')} className="ml-auto text-[12px] underline">Fermer</button>
        </p>
      )}
      {error && <p role="alert" className="mb-4 rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13px] text-[#B91C1C]">{error}</p>}

      <div className="grid gap-5 2xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          <div className="mb-5 grid gap-4 md:grid-cols-3">
            {!d && [0, 1, 2].map((i) => <div key={i} className="h-[112px] animate-pulse rounded-2xl bg-white" />)}
            {st && (
              <>
                <Kpi tone={['#F5F8FF', '#1463FF', '#E1EBFF']} icon={Send} value={nf(st.active)} label="Automatisations actives" sub={`sur ${nf(st.total)} créée${st.total > 1 ? 's' : ''}`} />
                <Kpi tone={['#F2FBF6', '#059669', '#D9F5E6']} icon={Users} value={nf(st.reach)} label="Clients touchés (30 jours)" delta={st.reach_delta} />
                <Kpi tone={['#FFF8EE', '#F59E0B', '#FFE9C7']} icon={Mail} value={`${String(st.open_rate).replace('.', ',')}%`} label="Taux d'ouverture moyen"
                     delta={st.open_delta} unit=" pt" />
              </>
            )}
          </div>

          <AutopilotBanner onOpen={() => setAutopilot(true)} />

          {/* below 1536 px the card sits above the table, full width (no side rail squeezing it) */}
          <div className="mb-5 2xl:hidden">
            <InspirationCard can={can} onUse={(d2) => navigate(`/dashboard/automations/nouvelle?scenario=${d2.scenario}`, { state: { ai: d2 } })} />
          </div>

          <section className="rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-[18px] font-extrabold text-[#0B1C3F]">Mes automatisations</h2>
              <div className="flex flex-wrap items-center gap-2">
                <span className="flex w-[260px] max-w-full items-center gap-2 rounded-xl border border-[#E2E8F0] px-3">
                  <Search size={16} className="text-[#64748B]" />
                  <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Rechercher une automatisation…"
                         className="min-w-0 flex-1 !border-0 bg-transparent py-2.5 !text-[14.5px] !shadow-none !outline-none !ring-0" />
                </span>
                <select aria-label="Trier" value={sort} onChange={(e) => setSort(e.target.value)}
                        className="rounded-xl border border-[#E2E8F0] px-3 py-2.5 text-[13px] font-semibold text-[#0B1C3F]">
                  {SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
              </div>
            </div>
            <div className="mb-2 flex flex-wrap gap-1 border-b border-[#EEF2F7]">
              {TABS.filter(([k]) => k !== 'ended' || d?.counts?.ended).map(([k, l]) => (
                <button key={k} type="button" onClick={() => setTab(k)}
                        className={`-mb-px border-b-2 px-3 py-2.5 text-[13px] font-semibold ${tab === k ? 'border-[#1463FF] text-[#1463FF]' : 'border-transparent text-[#475569] hover:text-[#0B1C3F]'}`}>
                  {l} ({nf(d?.counts?.[k])})
                </button>
              ))}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] table-fixed border-collapse">
                <thead>
                  <tr className="text-left text-[12px] text-[#475569]">
                    {[["Nom de l'automatisation", 'w-[24%]'], ['Déclencheur', 'w-[16%]'], ['Message', 'w-[25%]'], ['Statut', 'w-[14%]'],
                      ['Clients touchés', 'w-[9%]'], ['Ouverture', 'w-[8%]'], ['', 'w-[4%]']].map(([h, w]) => (
                      <th key={h || 'actions'} className={`px-2 py-3 font-medium ${w}`}>{h}</th>))}
                  </tr>
                </thead>
                <tbody>
                  {!d && <tr><td colSpan={7} className="py-10 text-center text-[12px] text-[#64748B]"><Loader2 size={16} className="inline animate-spin" /> Chargement…</td></tr>}
                  {d && !rows.length && (
                    <tr><td colSpan={7} className="py-10 text-center text-[13px] text-[#64748B]">
                      {search || tab !== 'all' ? 'Aucune automatisation ne correspond.' : 'Aucune automatisation : créez la première.'}</td></tr>
                  )}
                  {rows.map((r) => {
                    const I = ICONS[r.icon] || MessageSquare;
                    const [bg, fg] = TONES[r.tone] || TONES.blue;
                    const [sl, sc] = STATUS[r.status] || STATUS.draft;
                    return (
                      <tr key={r.id} onClick={() => navigate(`/dashboard/automations/${r.id}`)} tabIndex={0}
                          onKeyDown={(e) => { if (e.key === 'Enter' && e.target === e.currentTarget) navigate(`/dashboard/automations/${r.id}`); }}
                          aria-label={`Ouvrir ${r.name}`}
                          className="cursor-pointer border-t border-[#EEF2F7] transition hover:bg-[#F8FAFF] focus:bg-[#F8FAFF] focus:outline-none">
                        <td className="px-2 py-3">
                          <span className="flex items-center gap-3">
                            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl" style={{ background: bg, color: fg }}><I size={20} /></span>
                            <span className="min-w-0"><span className="block truncate text-[13px] font-bold text-[#0B1C3F]">{r.name}</span>
                              <span className="block truncate text-[11.5px] text-[#64748B]">{TAGLINE[r.scenario] || r.label}</span></span>
                          </span>
                        </td>
                        <td className="px-2 py-3"><span className="flex items-center gap-2 text-[12px] leading-snug text-[#475569]">
                          <CalendarDays size={16} className="shrink-0 text-[#64748B]" /><span className="min-w-0">{r.trigger_text}</span></span></td>
                        <td className="px-2 py-3"><span className="block min-w-0">
                          <span className="block truncate text-[12.5px] font-semibold text-[#0B1C3F]">{r.message?.title || '—'}</span>
                          <span className="block truncate text-[12px] text-[#64748B]">{r.message?.body}</span></span></td>
                        <td className="px-2 py-3" onClick={(e) => e.stopPropagation()}>
                          <span className="flex items-center gap-2 whitespace-nowrap">
                            <button type="button" role="switch" aria-checked={r.status === 'active'} aria-label={`Activer ${r.name}`}
                                    disabled={!can || busyRow === r.id} onClick={() => toggle(r)}
                                    className={`relative h-6 w-11 shrink-0 rounded-full transition disabled:opacity-60 ${r.status === 'active' ? 'bg-[#1463FF]' : 'bg-[#D6DEEA]'}`}>
                              <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${r.status === 'active' ? 'left-[22px]' : 'left-0.5'}`} />
                            </button>
                            <span className="text-[12px] font-semibold" style={{ color: sc }}>{sl}</span>
                          </span>
                        </td>
                        <td className="px-2 py-3 text-[13px] font-semibold tabular-nums text-[#0B1C3F]">{nf(r.reach)}</td>
                        <td className="px-2 py-3 text-[13px] font-semibold tabular-nums text-[#0B1C3F]">{r.open_rate == null ? <span className="text-[#94A3B8]">—</span> : `${r.open_rate}%`}</td>
                        <td className="relative px-1 py-3" onClick={(e) => e.stopPropagation()}>
                          <button type="button" aria-label="Plus d'actions" onClick={() => setMenu(menu === r.id ? null : r.id)}
                                  className="rounded-lg p-1.5 text-[#1463FF] hover:bg-[#F1F5F9]"><MoreHorizontal size={20} /></button>
                          {menu === r.id && (
                            <div className="absolute right-2 top-11 z-20 w-48 rounded-xl border border-[#E2E8F0] bg-white p-1.5 shadow-xl">
                              <button type="button" onClick={() => navigate(`/dashboard/automations/${r.id}`)} className="block w-full rounded-lg px-3 py-2 text-left text-[13px] hover:bg-[#F8FAFC]">{can ? 'Modifier' : 'Voir'}</button>
                              {can && <button type="button" onClick={() => duplicate(r)} className="block w-full rounded-lg px-3 py-2 text-left text-[13px] hover:bg-[#F8FAFC]">Dupliquer</button>}
                              {can && <button type="button" onClick={() => remove(r)} className="block w-full rounded-lg px-3 py-2 text-left text-[13px] text-[#DC2626] hover:bg-[#FEF2F2]">Supprimer</button>}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <aside className="hidden space-y-4 2xl:block">
          <InspirationCard can={can} onUse={(d2) => navigate(`/dashboard/automations/nouvelle?scenario=${d2.scenario}`, { state: { ai: d2 } })} />
        </aside>
      </div>
    </div>
  );
}
