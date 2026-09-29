import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Users, Phone, Mail, CalendarDays, FileText, Handshake, Upload, Download, Plus, Search, RotateCcw, SlidersHorizontal,
  MoreHorizontal, MapPin, Globe, Building2, User, Tag, Target, Pencil, Trash2, Clock, Loader2, ExternalLink,
} from 'lucide-react';
import { crmAPI } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import {
  Card, Head, Kpi, Donut, Bars, StageBadge, Avatar, Logo, Select, Loading, Breadcrumb, Pager, useToast, downloadBlob,
  Modal, nf, dayTime, ago, BLUE, inputCls,
} from './ui';
import { ImportModal, ProspectModal } from './modals';
import { TaskModal } from './CrmOverviewPage';

const Instagram = ({ size = 17 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true"><defs><linearGradient id="ig" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stopColor="#F58529" /><stop offset=".5" stopColor="#DD2A7B" /><stop offset="1" stopColor="#8134AF" /></linearGradient></defs>
    <rect x="2" y="2" width="20" height="20" rx="6" fill="url(#ig)" /><circle cx="12" cy="12" r="4.3" fill="none" stroke="#fff" strokeWidth="2" /><circle cx="17.3" cy="6.7" r="1.2" fill="#fff" /></svg>
);
const Facebook = ({ size = 17 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="2" width="20" height="20" rx="5" fill="#1877F2" />
    <path d="M13.2 20v-6.2h2.1l.3-2.5h-2.4V9.8c0-.7.2-1.2 1.2-1.2h1.3V6.4c-.2 0-1-.1-1.9-.1-1.9 0-3.2 1.2-3.2 3.3v1.8H8.5v2.5h2.1V20h2.6z" fill="#fff" /></svg>
);

/* CRM › Prospects — built to the approved mockup: the list, filters, the
   selected business on the right (informations, activities, notes, tasks),
   and the distributions under it. */

const TABS = [['liste', 'Liste des prospects'], ['pipeline', 'Pipeline'], ['calendrier', 'Calendrier'], ['secteurs', 'Secteurs'],
              ['villes', 'Villes'], ['sources', 'Sources']];
const KPI = [['total', 'Prospects total', Users, '#2F6BFF', '#EAF1FF'], ['a_contacter', 'À contacter', Phone, '#F59E0B', '#FFF4DB'],
             ['contacte', 'Contactés', Mail, '#10B981', '#E7F7EE'], ['rdv', 'Rendez-vous prévus', CalendarDays, '#9333EA', '#F3E8FF'],
             ['proposition', 'Propositions envoyées', FileText, '#2F6BFF', '#EAF1FF'], ['signe', 'Signés', Handshake, '#10B981', '#E7F7EE']];

function Detail({ id, ver, meta, onChanged, onEdit, admin, say }) {
  const [p, setP] = useState(null);
  const [tab, setTab] = useState('info');
  const [note, setNote] = useState('');
  const [lost, setLost] = useState(null);
  const [taskModal, setTaskModal] = useState(false);
  const [err, setErr] = useState('');
  const load = useCallback(() => { crmAPI.prospect(id).then(({ data }) => setP(data)).catch(() => setP(false)); }, [id]);
  useEffect(() => { setP(null); setTab('info'); }, [id]);
  useEffect(() => { load(); }, [load, ver]);
  if (p === false) return <Card><p className="text-[13px] text-[#64748B]">Prospect introuvable.</p></Card>;
  if (!p) return <Card><p className="py-10 text-center text-[13px] text-[#64748B]"><Loader2 size={15} className="mr-1 inline animate-spin" /> Chargement…</p></Card>;
  const change = async (fn, ok) => {
    setErr('');
    try { await fn(); say(ok); load(); onChanged(); } catch (e) { setErr(e?.response?.data?.detail || 'Action impossible.'); }
  };
  const setStage = (stage) => (stage === 'perdu' ? setLost('') : change(() => crmAPI.setStage(p.id, stage), 'Étape mise à jour.'));
  const addr = [p.address, [p.postal_code, p.city].filter(Boolean).join(' ')].filter(Boolean).join(', ');
  return (
    <Card className="sticky top-4">
      <div className="flex items-start gap-3">
        <Logo name={p.name} size={52} />
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-[17px] font-bold text-[#0B1C3F]">{p.name} <StageBadge stage={p.stage} label={p.stage_label} /></p>
          <p className="text-[12.5px] text-[#64748B]">{[p.sector, p.city].filter(Boolean).join(' · ') || '—'}</p>
          {p.fidclic && <p className="mt-1 inline-flex rounded-md bg-[#EAF1FF] px-2 py-0.5 text-[11.5px] text-[#2F6BFF]">Sur FidClic · {p.fidclic.status === 'trialing' ? `essai jusqu'au ${p.fidclic.trial_ends_at ? new Date(p.fidclic.trial_ends_at).toLocaleDateString('fr-FR') : '—'}` : p.fidclic.status || 'actif'}</p>}
        </div>
      </div>
      <div className="mt-3 flex gap-2">
        <a href={p.phone ? `tel:${p.phone.replace(/\s/g, '')}` : undefined} aria-disabled={!p.phone} className={`inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-[#DCE3EE] py-2 text-[13px] text-[#2F6BFF] ${p.phone ? '' : 'pointer-events-none opacity-40'}`}><Phone size={14} /> Appeler</a>
        <a href={p.email ? `mailto:${p.email}` : undefined} aria-disabled={!p.email} className={`inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-[#DCE3EE] py-2 text-[13px] text-[#2F6BFF] ${p.email ? '' : 'pointer-events-none opacity-40'}`}><Mail size={14} /> Envoyer un email</a>
        <button type="button" onClick={() => onEdit(p)} aria-label="Modifier" className="rounded-lg border border-[#DCE3EE] px-2.5 text-[#0B1C3F]"><Pencil size={15} /></button>
      </div>
      <nav className="mt-3 flex gap-1 border-b border-[#EDF1F7] text-[12.5px]">
        {[['info', 'Informations'], ['act', `Activités (${p.activities.length})`], ['notes', `Notes (${p.notes.length})`], ['tasks', `Tâches (${p.tasks.length})`]].map(([k, l]) => (
          <button key={k} type="button" onClick={() => setTab(k)} className={`border-b-2 px-2 py-2 ${tab === k ? 'border-[#2F6BFF] text-[#2F6BFF]' : 'border-transparent text-[#64748B]'}`}>{l}</button>
        ))}
      </nav>
      {err && <p className="mt-2 text-[12.5px] text-[#C0392B]">{err}</p>}
      {tab === 'info' && (
        <div className="mt-3 space-y-3 text-[13px]">
          <div>
            <p className="mb-1 font-semibold text-[#0B1C3F]">Contact principal</p>
            <p className="flex items-center gap-2 text-[#334155]"><User size={14} className="text-[#2F6BFF]" /> {p.contact_name || '—'} {p.contact_role && <span className="text-[#94A3B8]">· {p.contact_role}</span>}</p>
            <p className="flex items-center gap-2 text-[#334155]"><Phone size={14} className="text-[#2F6BFF]" /> {p.phone || '—'}</p>
            <p className="flex items-center gap-2 text-[#334155]"><Mail size={14} className="text-[#2F6BFF]" /> {p.email || '—'}</p>
          </div>
          <div>
            <p className="mb-1 font-semibold text-[#0B1C3F]">Détails du commerce</p>
            {[[Tag, 'Secteur', p.sector], [MapPin, 'Adresse', addr], [Building2, 'Taille', `${p.size || 1} établissement${p.size > 1 ? 's' : ''}`], [FileText, 'SIRET', p.siret]].map(([I, k, v]) => (
              <p key={k} className="grid grid-cols-[110px_1fr] gap-2 py-0.5"><span className="flex items-center gap-2 text-[#64748B]"><I size={14} className="text-[#2F6BFF]" />{k}</span><span className="text-[#0B1C3F]">{v || '—'}</span></p>
            ))}
            <p className="grid grid-cols-[110px_1fr] gap-2 py-0.5"><span className="flex items-center gap-2 text-[#64748B]"><Globe size={14} className="text-[#2F6BFF]" />Site web</span>
              {p.website ? <a href={p.website} target="_blank" rel="noopener noreferrer" className="truncate text-[#2F6BFF] underline">{p.website.replace(/^https?:\/\//, '')}</a> : <span>—</span>}</p>
            <p className="grid grid-cols-[110px_1fr] gap-2 py-0.5"><span className="text-[#64748B]">Réseaux sociaux</span><span className="flex gap-2">
              {p.instagram ? <a href={p.instagram} target="_blank" rel="noopener noreferrer" aria-label="Instagram" className="text-[#E1306C]"><Instagram size={17} /></a> : null}
              {p.facebook ? <a href={p.facebook} target="_blank" rel="noopener noreferrer" aria-label="Facebook" className="text-[#1877F2]"><Facebook size={17} /></a> : null}
              {!p.instagram && !p.facebook && '—'}</span></p>
          </div>
          <div>
            <p className="mb-2 font-semibold text-[#0B1C3F]">Statut & suivi</p>
            <div className="grid grid-cols-2 gap-2">
              <Select label="Statut" value={p.stage} onChange={setStage}>
                {(meta?.stages || []).map((s) => <option key={s.key} value={s.key} disabled={p.on_fidclic && ['essai', 'signe'].includes(s.key) && s.key !== p.stage}>{s.label}</option>)}
              </Select>
              <Select label="Assigné à" value={p.assigned_to || ''} onChange={(v) => change(() => crmAPI.editProspect(p.id, { assigned_to: v || null }), 'Assignation enregistrée.')}>
                <option value="">Personne</option>{(meta?.users || []).map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}
              </Select>
              <div>
                <span className="mb-1 block text-[11.5px] text-[#64748B]">Prochaine action</span>
                <button type="button" onClick={() => setTaskModal(true)} className="flex h-10 w-full items-center gap-2 rounded-lg border border-[#DCE3EE] px-2.5 text-left text-[12px] text-[#0B1C3F]">
                  <CalendarDays size={14} className="shrink-0 text-[#2F6BFF]" />
                  <span className="truncate">{p.next_action ? `${new Date(p.next_action.due_at).toLocaleDateString('fr-FR')} · ${p.next_action.label}` : 'Planifier…'}</span>
                </button>
              </div>
              <Select label="Source" value={p.source} onChange={(v) => change(() => crmAPI.editProspect(p.id, { source: v }), 'Source enregistrée.')}>
                {(meta?.sources || []).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
              </Select>
            </div>
            {p.stage === 'perdu' && p.lost_reason && <p className="mt-2 text-[12px] text-[#E11D48]">Motif : {p.lost_reason}</p>}
          </div>
          <button type="button" onClick={() => setTab('act')} className="w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white" style={{ background: BLUE }}>Voir l'historique complet</button>
        </div>
      )}
      {tab === 'act' && (
        <ul className="mt-3 max-h-[480px] space-y-2.5 overflow-y-auto">
          {p.activities.map((a) => (
            <li key={a.id} className="border-l-2 border-[#DCE3EE] pl-3"><p className="text-[13px] text-[#0B1C3F]">{a.text}</p><p className="text-[11.5px] text-[#94A3B8]">{new Date(a.at).toLocaleString('fr-FR')} · {a.by_name || 'FidClic'}</p></li>
          ))}
        </ul>
      )}
      {tab === 'notes' && (
        <div className="mt-3">
          <textarea className={`${inputCls} h-20 py-2`} placeholder="Ajouter une note…" value={note} onChange={(e) => setNote(e.target.value)} />
          <button type="button" disabled={!note.trim()} onClick={() => change(() => crmAPI.addNote(p.id, note).then(() => setNote('')), 'Note ajoutée.')}
                  className="mt-2 rounded-lg px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>Ajouter</button>
          <ul className="mt-3 space-y-2">{p.notes.map((n) => <li key={n.id} className="rounded-lg bg-[#F8FAFF] p-2.5 text-[13px] text-[#334155]">{n.text}<p className="mt-1 text-[11px] text-[#94A3B8]">{new Date(n.at).toLocaleString('fr-FR')}</p></li>)}</ul>
        </div>
      )}
      {tab === 'tasks' && (
        <div className="mt-3">
          <button type="button" onClick={() => setTaskModal(true)} className="w-full rounded-lg border border-dashed border-[#C9D6EA] py-2 text-[12.5px] text-[#2F6BFF]">+ Nouvelle tâche</button>
          <ul className="mt-2 divide-y divide-[#F1F5F9]">{p.tasks.map((t) => (
            <li key={t.id} className="flex items-center gap-2 py-2 text-[13px]">
              <input type="checkbox" checked={t.status === 'terminee'} onChange={() => change(() => crmAPI.editTask(t.id, { status: t.status === 'terminee' ? 'a_faire' : 'terminee' }), 'Tâche mise à jour.')} className="h-4 w-4 accent-[#2F6BFF]" />
              <span className={`flex-1 ${t.status === 'terminee' ? 'text-[#94A3B8] line-through' : 'text-[#0B1C3F]'}`}>{t.title}</span>
              <span className={`text-[12px] ${t.status === 'en_retard' ? 'text-[#E11D48]' : 'text-[#64748B]'}`}>{dayTime(t.due_at)}</span>
            </li>))}</ul>
        </div>
      )}
      {lost !== null && (
        <Modal title="Motif de perte" onClose={() => setLost(null)}>
          <div className="space-y-2">{(meta?.lost_reasons || []).filter((r) => r !== 'Abonnement résilié').map((r) => (
            <button key={r} type="button" onClick={() => { setLost(null); change(() => crmAPI.setStage(p.id, 'perdu', r), 'Marqué comme perdu.'); }}
                    className="block w-full rounded-lg border border-[#DCE3EE] px-3 py-2.5 text-left text-[13.5px] hover:border-[#E11D48]">{r}</button>))}</div>
        </Modal>
      )}
      {taskModal && <TaskModal meta={meta} prospectId={p.id} onClose={() => setTaskModal(false)} onSaved={() => { setTaskModal(false); say('Tâche créée.'); load(); onChanged(); }} />}
    </Card>
  );
}

export default function CrmProspectsPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const admin = user?.role === 'super_admin';
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState('liste');
  const [meta, setMeta] = useState(null);
  const [o, setO] = useState(null);
  const [list, setList] = useState(null);
  const [f, setF] = useState(() => ({ q: params.get('q') || '', sector: '', city: '', stage: params.get('stage') || '', assigned: params.get('assigned') || '', source: '' }));
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(10);
  const [sel, setSel] = useState(params.get('open') || null);
  const [menu, setMenu] = useState(null);
  const [modal, setModal] = useState(null);
  const [ver, setVer] = useState(0);
  const [say, toast] = useToast();

  const loadTop = useCallback(() => {
    crmAPI.meta().then(({ data }) => setMeta(data)).catch(() => {});
    crmAPI.overview({}).then(({ data }) => setO(data)).catch(() => {});
  }, []);
  const loadList = useCallback(() => {
    crmAPI.prospects({ ...f, page, per_page: perPage }).then(({ data }) => {
      setList(data);
      setSel((s) => s || data.rows[0]?.id || null);
    }).catch(() => setList({ rows: [], total: 0, pages: 1 }));
  }, [f, page, perPage]);
  useEffect(() => { loadTop(); }, [loadTop]);
  useEffect(() => { loadList(); }, [loadList]);
  const refresh = (m, detail = false) => { if (m) say(m); loadTop(); loadList(); if (detail) setVer((v) => v + 1); };
  const setFilter = (k) => (v) => { setPage(1); setF({ ...f, [k]: v }); };
  const counts = useMemo(() => Object.fromEntries((o?.funnel || []).map((s) => [s.key, s.count])), [o]);
  const cards = useMemo(() => Object.fromEntries((o?.cards || []).map((c) => [c.key, c])), [o]);

  return (
    <div className="crm" onClick={() => setMenu(null)}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', admin ? '/admin' : null], ['CRM de prospection', '/admin/crm'], ['Prospects']]} />
          <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Prospects</h1>
          <p className="text-[15px] text-[#475569]">Gérez tous vos prospects, suivez leur progression et transformez-les en clients FIDCLIC.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => setModal({ type: 'import' })} className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#2F6BFF] bg-white px-4 text-[13.5px] font-medium text-[#2F6BFF]"><Upload size={16} /> Importer des prospects</button>
          <button type="button" onClick={() => downloadBlob(crmAPI.exportCsv(f), 'prospects.csv')} className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#2F6BFF] bg-white px-4 text-[13.5px] font-medium text-[#2F6BFF]"><Download size={16} /> Exporter</button>
          <button type="button" onClick={() => setModal({ type: 'add' })} className="inline-flex h-10 items-center gap-2 rounded-xl px-4 text-[13.5px] font-medium text-white" style={{ background: BLUE }}><Plus size={16} /> Ajouter un prospect</button>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {KPI.map(([k, label, I, t, b]) => (
          <Kpi key={k} icon={I} tone={t} bg={b} label={label} value={k === 'total' ? (cards.total?.value ?? 0) : (counts[k] ?? 0)}
               delta={{ total: cards.total?.delta, rdv: cards.rdv?.delta, proposition: cards.proposition?.delta, signe: cards.signe?.delta, contacte: cards.contact?.delta }[k]}
               series={{ total: cards.total?.series, rdv: cards.rdv?.series, proposition: cards.proposition?.series, signe: cards.signe?.series, contacte: cards.contact?.series }[k]} />
        ))}
      </div>

      <div className="mt-4 grid items-start gap-4 xl:grid-cols-[1fr_340px]">
        <div className="min-w-0">
          <Card className="p-0">
            <nav className="flex flex-wrap items-center gap-1 border-b border-[#EDF1F7] px-3">
              {TABS.map(([k, l]) => (
                <button key={k} type="button" onClick={() => (k === 'pipeline' || k === 'calendrier' ? navigate(`/admin/crm/${k}`) : setTab(k))}
                        className={`border-b-2 px-3 py-3 text-[13.5px] ${tab === k ? 'border-[#2F6BFF] font-medium text-[#2F6BFF]' : 'border-transparent text-[#0B1C3F] hover:text-[#2F6BFF]'}`}>{l}</button>
              ))}
            </nav>
            <div className="p-4">
              {tab === 'liste' && (
                <>
                  <div className="mb-2 grid gap-2 md:grid-cols-[1.6fr_repeat(5,1fr)]">
                    <label className="relative"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
                      <input className={`${inputCls} pl-9`} placeholder="Rechercher un commerce, un contact, un secteur…" value={f.q} onChange={(e) => setFilter('q')(e.target.value)} /></label>
                    <Select value={f.sector} onChange={setFilter('sector')}><option value="">Tous les secteurs</option>{(meta?.sectors || []).map((s) => <option key={s}>{s}</option>)}</Select>
                    <Select value={f.city} onChange={setFilter('city')}><option value="">Toutes les villes</option>{(meta?.cities || []).map((s) => <option key={s}>{s}</option>)}</Select>
                    <Select value={f.stage} onChange={setFilter('stage')}><option value="">Tous les statuts</option>{(meta?.stages || []).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</Select>
                    <Select value={f.assigned} onChange={setFilter('assigned')}><option value="">Tous les assignés</option><option value="none">Personne</option>{(meta?.users || []).map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}</Select>
                    <Select value={f.source} onChange={setFilter('source')}><option value="">Toutes les sources</option>{(meta?.sources || []).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</Select>
                  </div>
                  <div className="mb-2 flex items-center justify-between text-[12.5px] text-[#64748B]">
                    <span>{nf(list?.total || 0)} prospect{list?.total > 1 ? 's' : ''} trouvé{list?.total > 1 ? 's' : ''}</span>
                    <button type="button" onClick={() => { setPage(1); setParams({}); setF({ q: '', sector: '', city: '', stage: '', assigned: '', source: '' }); }} className="inline-flex items-center gap-1.5 rounded-lg border border-[#DCE3EE] px-3 py-1.5 text-[#2F6BFF]"><RotateCcw size={13} /> Réinitialiser</button>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[1000px] text-[12.5px]">
                      <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">
                        {['#', 'Nom du commerce', 'Secteur', 'Ville', 'Contact', 'Téléphone', 'Statut', 'Prochaine action', 'Assigné à', 'Dernière activité', ''].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
                      <tbody>
                        {!list && <tr><td colSpan={11} className="py-10 text-center text-[#64748B]"><Loader2 size={15} className="mr-1 inline animate-spin" /> Chargement…</td></tr>}
                        {list?.rows.map((p) => (
                          <tr key={p.id} onClick={() => setSel(p.id)} className={`cursor-pointer border-b border-[#F4F7FC] ${sel === p.id ? 'bg-[#F4F8FF]' : 'hover:bg-[#FAFCFF]'}`}>
                            <td className="px-2 py-2.5 text-[#94A3B8]">{p.ref || '—'}</td>
                            <td className="px-2 py-2.5"><span className="flex items-center gap-2.5"><Logo name={p.name} size={30} /><span className="font-semibold text-[#0B1C3F]">{p.name}</span></span></td>
                            <td className="px-2 py-2.5 text-[#475569]">{p.sector || '—'}</td>
                            <td className="px-2 py-2.5 text-[#475569]">{p.city || '—'}</td>
                            <td className="px-2 py-2.5 text-[#475569]">{p.contact_name || '—'}</td>
                            <td className="px-2 py-2.5 text-[#475569]">{p.phone || '—'}</td>
                            <td className="px-2 py-2.5"><StageBadge stage={p.stage} label={p.stage_label} /></td>
                            <td className="px-2 py-2.5 text-[#475569]">{p.next_action ? <>{p.next_action.label}<br /><span className="text-[11px] text-[#94A3B8]">{new Date(p.next_action.due_at).toLocaleDateString('fr-FR')}</span></> : '—'}</td>
                            <td className="px-2 py-2.5"><Avatar name={p.assigned_name} /></td>
                            <td className="px-2 py-2.5 text-[#475569]">{p.last_activity_at ? new Date(p.last_activity_at).toLocaleDateString('fr-FR') : '—'}</td>
                            <td className="relative px-2 py-2.5" onClick={(e) => e.stopPropagation()}>
                              <button type="button" aria-label="Actions" onClick={() => setMenu(menu === p.id ? null : p.id)} className="rounded p-1 text-[#0B1C3F] hover:bg-[#F4F7FC]"><MoreHorizontal size={16} /></button>
                              {menu === p.id && (
                                <span className="absolute right-2 top-full z-20 flex w-44 flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-[0_24px_60px_-28px_rgba(11,28,63,.5)]">
                                  <button type="button" onClick={() => { setMenu(null); setModal({ type: 'edit', prospect: p }); }} className="flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]"><Pencil size={13} /> Modifier</button>
                                  {admin && !p.on_fidclic && <button type="button" onClick={async () => { setMenu(null); if (window.confirm(`Supprimer « ${p.name} » du CRM ?`)) { await crmAPI.deleteProspect(p.id); if (sel === p.id) setSel(null); refresh('Prospect supprimé.'); } }} className="flex items-center gap-2 px-3 py-2 text-left text-[#E11D48] hover:bg-[#FEF2F2]"><Trash2 size={13} /> Supprimer</button>}
                                </span>
                              )}
                            </td>
                          </tr>
                        ))}
                        {list && !list.rows.length && <tr><td colSpan={11} className="py-12 text-center text-[#64748B]">Aucun prospect ne correspond. <button type="button" onClick={() => setModal({ type: 'import' })} className="text-[#2F6BFF] underline">Importer une liste</button></td></tr>}
                      </tbody>
                    </table>
                  </div>
                  {list && <Pager page={page} pages={list.pages} total={list.total} perPage={perPage} onPage={setPage} onPerPage={(n) => { setPerPage(n); setPage(1); }} />}
                </>
              )}
              {tab === 'secteurs' && <Bars rows={o?.sectors || []} />}
              {tab === 'villes' && <Bars rows={o?.cities || []} />}
              {tab === 'sources' && <Donut rows={o?.sources || []} center={nf(cards.total?.value || 0)} sub="prospects" />}
            </div>
          </Card>

          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <Card><Head icon={Target} title="Motifs de perte" /><Donut rows={(o?.lost.reasons || []).map((r) => ({ ...r, key: r.label, pct: o.lost.count ? Math.round((r.count / o.lost.count) * 100) : 0 }))} center={nf(o?.lost.count || 0)} sub="perdus" /></Card>
            <Card><Head icon={Target} title="Sources des prospects" /><Donut rows={o?.sources || []} center={nf(cards.total?.value || 0)} sub="prospects" /></Card>
            <Card><Head icon={Target} title="Répartition par secteur" /><Bars rows={o?.sectors || []} /></Card>
          </div>
        </div>
        <div>{sel ? <Detail id={sel} ver={ver} meta={meta} admin={admin} say={say} onChanged={() => refresh()} onEdit={(p) => setModal({ type: 'edit', prospect: p })} />
          : <Card><p className="py-10 text-center text-[13px] text-[#64748B]">Choisissez un prospect.</p></Card>}</div>
      </div>

      {toast}
      {modal?.type === 'import' && <ImportModal meta={meta} onClose={() => setModal(null)} onDone={(m) => { setModal(null); refresh(m); }} />}
      {modal?.type === 'add' && <ProspectModal meta={meta} onClose={() => setModal(null)} onSaved={(d, m) => { setModal(null); setSel(d.id); refresh(m); }} />}
      {modal?.type === 'edit' && <ProspectModal meta={meta} prospect={modal.prospect} onClose={() => setModal(null)} onSaved={(_, m) => { setModal(null); refresh(m, true); }} />}
    </div>
  );
}
