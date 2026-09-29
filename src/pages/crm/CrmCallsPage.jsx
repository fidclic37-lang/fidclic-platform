import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import {
  Phone, PhoneCall, PhoneMissed, PhoneIncoming, Users, CalendarCheck, XCircle, Download, Plus, ChevronDown, Search, Smartphone,
  MoreHorizontal, Play, Pause, Mail, MapPin, User, Clock, CalendarDays, ListPlus, Trash2, Upload, X, Loader2, Target, BarChart3,
  CheckCircle2, Mic, ExternalLink,
} from 'lucide-react';
import { crmAPI } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { Card, Head, Kpi, Donut, Bars, Avatar, Logo, Select, Loading, Breadcrumb, Pager, Modal, useToast, downloadBlob, nf, BLUE, inputCls } from './ui';
import { TaskModal } from './CrmOverviewPage';
import { ComposeEmail } from './emailUi';

/* CRM › Appels — built to the approved mockup. Calls are made from the
   phone (tel: link) and their result is noted here. */

const RESULT_TONE = {
  rdv_obtenu: ['#E7F7EE', '#0F8B58'], interesse: ['#EAF1FF', '#2F6BFF'], a_relancer: ['#FFF4DB', '#D97706'],
  rappel_demande: ['#FFF4DB', '#C2410C'], pas_interesse: ['#FDECEF', '#E11D48'], sans_reponse: ['#FDECEF', '#E11D48'],
  a_qualifier: ['#F1F5F9', '#475569'],
};
const ResultPill = ({ k, label }) => {
  const [bg, fg] = RESULT_TONE[k] || ['#F1F5F9', '#94A3B8'];
  return <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-1 text-[12px] font-medium" style={{ background: bg, color: fg }}><i className="h-1.5 w-1.5 rounded-full" style={{ background: fg }} />{label}</span>;
};
const StatusPill = ({ s, label }) => (
  <span className={`whitespace-nowrap rounded-md px-2 py-1 text-[12px] font-medium ${s === 'planifie' ? 'bg-[#EAF1FF] text-[#2F6BFF]' : 'bg-[#E7F7EE] text-[#0F8B58]'}`}>{label}</span>
);
const TABS = [['', 'Tous les appels', 'all'], ['effectues', 'Appels effectués', 'effectues'], ['reponses', 'Réponses', 'reponses'], ['rdv', 'RDV obtenus', 'rdv'], ['sans_reponse', 'Sans réponse', 'sans_reponse']];
const when = (iso) => { const d = new Date(iso); return [d.toLocaleDateString('fr-FR'), d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })]; };
const mmss = (s) => `${Math.floor((s || 0) / 60)}:${String(Math.floor((s || 0) % 60)).padStart(2, '0')}`;

export default function CrmCallsPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const admin = user?.role === 'super_admin';
  const [meta, setMeta] = useState(null);
  const [sum, setSum] = useState(null);
  const [list, setList] = useState(null);
  const [tab, setTab] = useState('');
  const [f, setF] = useState({ q: '', sector: '', city: '', status: '', result: '', assigned: '' });
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(10);
  const [selId, setSelId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [modal, setModal] = useState(null);
  const [menu, setMenu] = useState(false);
  const [rowMenu, setRowMenu] = useState(null);
  const [say, toast] = useToast();

  const loadList = useCallback(() => {
    crmAPI.callsSummary().then(({ data }) => setSum(data)).catch(() => {});
    crmAPI.calls({ ...f, tab, page, per_page: perPage }).then(({ data }) => {
      setList(data); setSelId((s) => (s && data.rows.some((r) => r.id === s) ? s : data.rows[0]?.id || null));
    }).catch(() => setList({ rows: [], total: 0, counts: {}, pages: 1 }));
  }, [f, tab, page, perPage]);
  useEffect(() => { loadList(); }, [loadList]);
  useEffect(() => { crmAPI.meta().then(({ data }) => setMeta(data)).catch(() => {}); }, []);
  const loadDetail = useCallback(() => {
    if (!selId) { setDetail(null); return; }
    crmAPI.call(selId).then(({ data }) => setDetail(data)).catch(() => setDetail(null));
  }, [selId]);
  useEffect(() => { loadDetail(); }, [loadDetail]);
  const refresh = (m) => { if (m) say(m); loadList(); loadDetail(); };
  const act = async (fn, m) => { try { await fn(); refresh(m); } catch (e) { say(e?.response?.data?.detail || 'Action impossible.'); } };
  const setFilter = (k) => (v) => { setPage(1); setF({ ...f, [k]: v }); };

  if (!sum || !list) return <Loading />;
  const K = Object.fromEntries(sum.cards.map((c) => [c.key, c]));
  const d = detail;
  const totalDone = sum.results.reduce((s, r) => s + r.count, 0);
  const dayLabel = (iso) => ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam'][new Date(iso).getDay()];

  return (
    <div className="crm" onClick={() => { setMenu(false); setRowMenu(null); }}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', admin ? '/admin' : null], ['CRM de prospection', '/admin/crm'], ['Appels']]} />
          <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Appels</h1>
          <p className="text-[15px] text-[#475569]">Passez, suivez et analysez tous vos appels de prospection.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => setModal({ type: 'import' })} className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#2F6BFF] bg-white px-4 text-[13.5px] font-medium text-[#2F6BFF]"><Smartphone size={16} /> Importer depuis mobile</button>
          <button type="button" onClick={() => downloadBlob(crmAPI.exportCalls({ ...f, tab }), 'appels.csv').catch(() => say('Export impossible.'))} className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#DCE3EE] bg-white px-4 text-[13.5px] font-medium text-[#2F6BFF]"><Download size={16} /> Exporter</button>
          <span className="relative" onClick={(e) => e.stopPropagation()}>
            <button type="button" onClick={() => setMenu((v) => !v)} className="inline-flex h-10 items-center gap-2 rounded-xl px-4 text-[13.5px] font-medium text-white" style={{ background: BLUE }}><Plus size={16} /> Passer un appel <ChevronDown size={15} /></button>
            {menu && (
              <span className="absolute right-0 top-full z-30 mt-1 flex w-60 flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-[0_24px_60px_-28px_rgba(11,28,63,.5)]">
                <button type="button" onClick={() => { setMenu(false); setModal({ type: 'call', mode: 'dial' }); }} className="flex items-center gap-2 px-3.5 py-2 text-left text-[13px] hover:bg-[#F4F7FC]"><PhoneCall size={14} className="text-[#2F6BFF]" /> Appeler un commerce</button>
                <button type="button" onClick={() => { setMenu(false); setModal({ type: 'call', mode: 'log' }); }} className="flex items-center gap-2 px-3.5 py-2 text-left text-[13px] hover:bg-[#F4F7FC]"><CheckCircle2 size={14} className="text-[#10B981]" /> Noter un appel déjà passé</button>
                <button type="button" onClick={() => { setMenu(false); setModal({ type: 'call', mode: 'plan' }); }} className="flex items-center gap-2 px-3.5 py-2 text-left text-[13px] hover:bg-[#F4F7FC]"><CalendarDays size={14} className="text-[#8B5CF6]" /> Planifier un appel</button>
              </span>
            )}
          </span>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
        <Kpi icon={Phone} tone="#2F6BFF" bg="#EAF1FF" value={nf(K.total.value)} label="Appels total" delta={K.total.delta} series={K.total.series} />
        <Kpi icon={PhoneCall} tone="#10B981" bg="#E7F7EE" value={nf(K.effectues.value)} label="Appels effectués" delta={K.effectues.delta} series={K.effectues.series} />
        <Kpi icon={Users} tone="#2F6BFF" bg="#EAF1FF" value={nf(K.reponses.value)} label="Réponses" delta={K.reponses.delta} series={K.reponses.series} />
        <Kpi icon={CalendarCheck} tone="#F59E0B" bg="#FFF4DB" value={nf(K.rdv.value)} label="RDV obtenus" delta={K.rdv.delta} series={K.rdv.series} />
        <Kpi icon={XCircle} tone="#E11D48" bg="#FDECEF" value={nf(K.sans_reponse.value)} label="Sans réponse" delta={K.sans_reponse.delta} series={K.sans_reponse.series} />
      </div>

      <div className="mt-4 grid items-start gap-4 xl:grid-cols-[1fr_330px]">
        <div className="min-w-0">
          <Card className="p-0">
            <nav className="flex flex-wrap gap-1 border-b border-[#EDF1F7] px-3">
              {TABS.map(([k, l, c]) => (
                <button key={l} type="button" onClick={() => { setPage(1); setTab(k); }} className={`border-b-2 px-3 py-3 text-[13.5px] ${tab === k ? 'border-[#2F6BFF] font-medium text-[#2F6BFF]' : 'border-transparent text-[#0B1C3F]'}`}>{l} ({nf(list.counts[c] || 0)})</button>
              ))}
            </nav>
            <div className="p-4">
              <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                <label className="relative"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
                  <input className={`${inputCls} pl-9`} placeholder="Rechercher un commerce, un contact, un numéro…" value={f.q} onChange={(e) => setFilter('q')(e.target.value)} /></label>
                <Select value={f.sector} onChange={setFilter('sector')}><option value="">Tous les secteurs</option>{(meta?.sectors || []).map((s) => <option key={s}>{s}</option>)}</Select>
                <Select value={f.city} onChange={setFilter('city')}><option value="">Toutes les villes</option>{(meta?.cities || []).map((s) => <option key={s}>{s}</option>)}</Select>
                <Select value={f.status} onChange={setFilter('status')}><option value="">Tous les statuts</option>{sum.status_options.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</Select>
                <Select value={f.result} onChange={setFilter('result')}><option value="">Tous les résultats</option>{sum.result_options.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</Select>
                <Select value={f.assigned} onChange={setFilter('assigned')}><option value="">Tous les users</option>{(meta?.users || []).map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}</Select>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[840px] text-[12.5px]">
                  <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">{['Date / Heure', 'Commerce', 'Contact', 'Numéro', 'Durée', 'Résultat', 'Statut', 'Assigné à', '', ''].map((h, i) => <th key={i} className="px-2 py-2 font-medium">{i === 8 ? <Mic size={13} aria-label="Enregistrement" /> : h}</th>)}</tr></thead>
                  <tbody>
                    {list.rows.map((r) => { const [dd, tt] = when(r.at); const missed = r.result === 'sans_reponse'; const I = r.status === 'planifie' ? CalendarDays : r.direction === 'entrant' ? PhoneIncoming : missed ? PhoneMissed : Phone; return (
                      <tr key={r.id} onClick={() => setSelId(r.id)} className={`cursor-pointer border-b border-[#F4F7FC] ${selId === r.id ? 'bg-[#F4F8FF]' : 'hover:bg-[#FAFCFF]'}`}>
                        <td className="px-2 py-2"><span className="flex items-center gap-2"><I size={15} className={missed ? 'text-[#E11D48]' : r.status === 'planifie' ? 'text-[#8B5CF6]' : 'text-[#10B981]'} /><span className="leading-tight text-[#475569]">{dd}<br />{tt}</span></span></td>
                        <td className="px-2 py-2"><span className="flex items-center gap-2"><Logo name={r.prospect || '?'} size={26} /><span className="max-w-[140px] truncate font-medium text-[#0B1C3F]">{r.prospect || '—'}</span></span></td>
                        <td className="max-w-[110px] truncate px-2 py-2 text-[#475569]">{r.contact || '—'}</td>
                        <td className="whitespace-nowrap px-2 py-2 text-[#475569]">{r.number || '—'}</td>
                        <td className="whitespace-nowrap px-2 py-2 text-[#475569]">{r.status === 'planifie' ? '—' : r.duration}</td>
                        <td className="px-2 py-2">{r.result ? <ResultPill k={r.result} label={r.result_label} /> : '—'}</td>
                        <td className="px-2 py-2"><StatusPill s={r.status} label={r.status_label} /></td>
                        <td className="max-w-[120px] px-2 py-2"><Avatar name={r.by_name} size={22} /></td>
                        <td className="px-2 py-2">{r.has_recording ? <span className="grid h-7 w-7 place-items-center rounded-full bg-[#EAF1FF] text-[#2F6BFF]"><Play size={12} /></span> : <span className="text-[#CBD5E1]">—</span>}</td>
                        <td className="relative px-2 py-2" onClick={(e) => e.stopPropagation()}>
                          <button type="button" aria-label="Actions" onClick={() => setRowMenu(rowMenu === r.id ? null : r.id)} className="rounded p-1 hover:bg-[#F4F7FC]"><MoreHorizontal size={16} /></button>
                          {rowMenu === r.id && (
                            <span className="absolute right-2 top-full z-20 flex w-48 flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-lg">
                              {r.status === 'planifie' && <button type="button" onClick={() => setModal({ type: 'call', mode: 'log', call: r })} className="px-3 py-2 text-left hover:bg-[#F4F7FC]">Noter le résultat</button>}
                              {r.status !== 'planifie' && <button type="button" onClick={() => setModal({ type: 'edit', call: r })} className="px-3 py-2 text-left hover:bg-[#F4F7FC]">Modifier</button>}
                              {r.phone && <a href={`tel:${r.phone}`} onClick={() => setModal({ type: 'call', mode: 'dial', prospect: { id: r.prospect_id, name: r.prospect, phone: r.phone } })} className="px-3 py-2 hover:bg-[#F4F7FC]">Rappeler</a>}
                              <button type="button" onClick={() => { if (window.confirm('Supprimer cet appel ?')) act(() => crmAPI.deleteCall(r.id), 'Appel supprimé.'); }} className="px-3 py-2 text-left text-[#E11D48] hover:bg-[#FEF2F2]">Supprimer</button>
                            </span>
                          )}
                        </td>
                      </tr>); })}
                    {!list.rows.length && <tr><td colSpan={10} className="py-12 text-center text-[#64748B]">Aucun appel ici. Cliquez sur « Passer un appel » pour commencer.</td></tr>}
                  </tbody>
                </table>
              </div>
              <Pager page={page} pages={list.pages} total={list.total} perPage={perPage} onPage={setPage} onPerPage={(n) => { setPerPage(n); setPage(1); }} what="appels" />
            </div>
          </Card>

          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <Card><Head icon={Target} title="Répartition des résultats" /><Donut rows={sum.results.filter((r) => r.count)} center={nf(totalDone)} sub="appels" /></Card>
            <Card><Head icon={Users} title="Appels par utilisateur" />{sum.by_user.length ? <Bars rows={sum.by_user} /> : <p className="py-8 text-center text-[13px] text-[#94A3B8]">Aucun appel noté.</p>}</Card>
            <Card>
              <Head icon={BarChart3} title="Appels par jour" sub="7 derniers jours" />
              <div className="mb-1 flex gap-4 text-[12px] text-[#475569]"><span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-[#2F6BFF]" />Appels effectués</span><span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-[#10B981]" />Réponses</span></div>
              <div className="h-[170px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={sum.per_day.map((x) => ({ ...x, j: dayLabel(x.day) }))} margin={{ top: 8, right: 8, left: -24, bottom: 0 }}>
                    <CartesianGrid stroke="#EEF2F7" vertical={false} />
                    <XAxis dataKey="j" tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} />
                    <Tooltip formatter={(v, k) => [v, k === 'effectues' ? 'Appels effectués' : 'Réponses']} />
                    <Line type="monotone" dataKey="effectues" stroke="#2F6BFF" strokeWidth={2} dot={{ r: 3 }} />
                    <Line type="monotone" dataKey="reponses" stroke="#10B981" strokeWidth={2} dot={{ r: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>
        </div>

        <Card className="xl:sticky xl:top-4">
          <Head title="Détails de l'appel" right={d && <button type="button" aria-label="Fermer" onClick={() => setSelId(null)} className="text-[#94A3B8]"><X size={16} /></button>} />
          {!d ? <p className="py-10 text-center text-[13px] text-[#64748B]">Choisissez un appel.</p> : <CallDetail d={d} meta={meta} navigate={navigate} act={act} say={say} refresh={refresh} setModal={setModal} />}
        </Card>
      </div>

      {toast}
      {modal?.type === 'call' && <CallModal meta={meta} mode={modal.mode} call={modal.call} prospect={modal.prospect} results={sum.result_options}
                                            onClose={() => setModal(null)} onSaved={(c, m) => { setModal(null); setSelId(c.id); refresh(m); if (c.result === 'rdv_obtenu') setModal({ type: 'task', preset: { type: 'rdv', title: 'Rendez-vous', prospect_id: c.prospect_id, prospect: c.prospect } }); }} />}
      {modal?.type === 'edit' && <EditCallModal call={modal.call} results={sum.result_options} onClose={() => setModal(null)} onSaved={() => { setModal(null); refresh('Appel modifié.'); }} />}
      {modal?.type === 'task' && <TaskModal meta={meta} preset={modal.preset} onClose={() => setModal(null)} onSaved={() => { setModal(null); say(modal.preset?.type === 'rdv' ? 'Rendez-vous créé — il est dans le calendrier.' : 'Tâche créée.'); }} />}
      {modal?.type === 'lost' && (
        <Modal title={`Motif de perte — ${modal.name}`} onClose={() => setModal(null)}>
          <div className="space-y-2">{(meta?.lost_reasons || []).filter((r) => r !== 'Abonnement résilié').map((r) => (
            <button key={r} type="button" onClick={() => { setModal(null); act(() => crmAPI.setStage(modal.pid, 'perdu', r), 'Prospect marqué comme perdu.'); }}
                    className="block w-full rounded-lg border border-[#DCE3EE] px-3 py-2.5 text-left text-[13.5px] hover:border-[#E11D48]">{r}</button>))}</div>
        </Modal>
      )}
      {modal?.type === 'email' && <ComposeEmail prospect={modal.prospect} onClose={() => setModal(null)} onSent={(m) => { setModal(null); refresh(m); }} />}
      {modal?.type === 'import' && <ImportCallsModal onClose={() => setModal(null)} onDone={(m) => { setModal(null); refresh(m); }} />}
    </div>
  );
}

function CallDetail({ d, meta, navigate, act, say, refresh, setModal }) {
  const [tab, setTab] = useState('info');
  const [note, setNote] = useState('');
  const fileRef = useRef(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setTab('info'); setNote(''); }, [d.id]);
  const upload = async (file) => {
    if (!file) return;
    setBusy(true);
    try { await crmAPI.uploadRecording(d.id, file); refresh('Enregistrement ajouté.'); }
    catch (e) { say(e?.response?.data?.detail || 'Envoi impossible.'); }
    setBusy(false);
  };
  const stage = meta?.stages?.find((s) => s.key === d.stage)?.label;
  return (
    <div className="space-y-3 text-[13px]">
      <div className="flex items-center gap-3">
        <Logo name={d.prospect || '?'} size={48} />
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-2"><span className="truncate text-[15px] font-bold text-[#0B1C3F]">{d.prospect}</span>{stage && <span className="shrink-0 rounded-md bg-[#FFF4DB] px-1.5 py-0.5 text-[11px] text-[#D97706]">{stage}</span>}</p>
          <p className="text-[12px] text-[#64748B]">{[d.sector, d.city].filter(Boolean).join(' · ')}</p>
        </div>
      </div>
      <div className="grid grid-cols-[1fr_1.4fr_auto] gap-2">
        {d.phone ? <a href={`tel:${d.phone}`} onClick={() => setModal({ type: 'call', mode: 'dial', prospect: { id: d.prospect_id, name: d.prospect, phone: d.phone } })} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-[#DCE3EE] py-2 text-[12.5px] text-[#2F6BFF]"><Phone size={13} /> Rappeler</a>
          : <span className="rounded-lg border border-[#EDF1F7] py-2 text-center text-[12px] text-[#94A3B8]">Pas de n°</span>}
        {d.email ? <button type="button" onClick={() => setModal({ type: 'email', prospect: { id: d.prospect_id, name: d.prospect, email: d.email } })} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-[#DCE3EE] py-2 text-[12.5px] text-[#2F6BFF]"><Mail size={13} /> Envoyer un email</button>
          : <span className="rounded-lg border border-[#EDF1F7] py-2 text-center text-[12px] text-[#94A3B8]">Pas d'email</span>}
        <button type="button" onClick={() => navigate(`/admin/crm/prospects?open=${d.prospect_id}`)} aria-label="Ouvrir le prospect" className="rounded-lg border border-[#DCE3EE] px-2.5 text-[#2F6BFF]"><ExternalLink size={14} /></button>
      </div>
      <nav className="flex gap-1 border-b border-[#EDF1F7]">
        {[['info', 'Informations'], ['hist', `Historique (${d.history.length})`], ['notes', `Notes (${d.prospect_notes.length})`]].map(([k, l]) => (
          <button key={k} type="button" onClick={() => setTab(k)} className={`border-b-2 px-2 py-2 text-[12.5px] ${tab === k ? 'border-[#2F6BFF] font-medium text-[#2F6BFF]' : 'border-transparent text-[#475569]'}`}>{l}</button>
        ))}
      </nav>
      {tab === 'info' && (
        <>
          <div className="space-y-1.5">
            <p className="font-semibold text-[#0B1C3F]">Contact</p>
            <p className="flex items-center gap-2"><User size={13} className="text-[#2F6BFF]" />{[d.contact, d.contact_role && `(${d.contact_role})`].filter(Boolean).join(' ') || '—'}</p>
            <p className="flex items-center gap-2"><Phone size={13} className="text-[#2F6BFF]" />{d.number || '—'}</p>
            <p className="flex items-center gap-2"><Mail size={13} className="text-[#2F6BFF]" /><span className="truncate">{d.email || '—'}</span></p>
            <p className="flex items-start gap-2"><MapPin size={13} className="mt-0.5 shrink-0 text-[#2F6BFF]" /><span>{d.address || '—'}{d.address && <><br /><a href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(d.address)}`} target="_blank" rel="noreferrer" className="text-[12px] text-[#2F6BFF] underline">Voir sur Google Maps</a></>}</span></p>
          </div>
          <div className="space-y-1.5">
            <p className="font-semibold text-[#0B1C3F]">Détails de l'appel</p>
            <p className="flex items-center gap-2"><CalendarDays size={13} className="text-[#2F6BFF]" />{new Date(d.at).toLocaleDateString('fr-FR')} à {new Date(d.at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}</p>
            {d.status !== 'planifie' && <p className="flex items-center gap-2"><Clock size={13} className="text-[#2F6BFF]" />{d.duration}</p>}
            <p className="flex items-center gap-2"><User size={13} className="text-[#2F6BFF]" />{d.by_name || '—'} {d.result ? <ResultPill k={d.result} label={d.result_label} /> : <StatusPill s={d.status} label={d.status_label} />}</p>
            {d.source === 'mobile' && <p className="text-[11.5px] text-[#94A3B8]">Importé depuis le téléphone</p>}
          </div>
          {d.status === 'planifie' ? (
            <button type="button" onClick={() => setModal({ type: 'call', mode: 'log', call: d })} className="flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-[13px] font-semibold text-white" style={{ background: BLUE }}><CheckCircle2 size={15} /> Noter le résultat</button>
          ) : (
            <div>
              <p className="mb-1.5 font-semibold text-[#0B1C3F]">Enregistrement</p>
              {d.has_recording ? <Player callId={d.id} onDelete={() => act(() => crmAPI.deleteRecording(d.id), 'Enregistrement supprimé.')} />
                : (
                  <>
                    <input ref={fileRef} type="file" accept="audio/*,.m4a,.mp3,.wav,.ogg,.aac,.amr,.3gp" className="hidden" onChange={(e) => upload(e.target.files?.[0])} />
                    <button type="button" disabled={busy} onClick={() => fileRef.current?.click()} className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-[#BFD3FF] py-2.5 text-[12.5px] text-[#2F6BFF]">{busy ? <Loader2 size={14} className="animate-spin" /> : <Mic size={14} />} Ajouter un enregistrement (facultatif)</button>
                  </>
                )}
            </div>
          )}
          <div>
            <p className="mb-1.5 font-semibold text-[#0B1C3F]">Notes</p>
            <p className="min-h-[44px] whitespace-pre-wrap rounded-lg border border-[#EDF1F7] p-2.5 text-[#334155]">{d.notes || <span className="text-[#94A3B8]">Aucune note sur cet appel.</span>}</p>
          </div>
        </>
      )}
      {tab === 'hist' && (
        <ul className="max-h-[360px] space-y-2 overflow-y-auto">
          {d.history.map((h) => (
            <li key={h.id} className={`rounded-lg border p-2 ${h.id === d.id ? 'border-[#BFD3FF] bg-[#F4F8FF]' : 'border-[#EDF1F7]'}`}>
              <p className="flex items-center justify-between gap-2"><span className="text-[12px] text-[#475569]">{new Date(h.at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })} · {h.by_name}</span>{h.result ? <ResultPill k={h.result} label={h.result_label} /> : <StatusPill s={h.status} label={h.status_label} />}</p>
              {h.notes && <p className="mt-1 text-[12px] text-[#334155]">{h.notes}</p>}
            </li>
          ))}
        </ul>
      )}
      {tab === 'notes' && (
        <div className="space-y-2">
          <textarea className={`${inputCls} h-16 py-2`} placeholder="Ajouter une note sur ce commerce…" value={note} onChange={(e) => setNote(e.target.value)} />
          <button type="button" disabled={!note.trim()} onClick={() => act(() => crmAPI.addNote(d.prospect_id, note.trim()), 'Note ajoutée.')} className="w-full rounded-lg py-2 text-[12.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>Ajouter la note</button>
          <ul className="max-h-[280px] space-y-2 overflow-y-auto">{d.prospect_notes.map((n, i) => (
            <li key={i} className="rounded-lg border border-[#EDF1F7] p-2"><p className="text-[11.5px] text-[#64748B]">{new Date(n.at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })} · {n.by_name}</p><p className="mt-0.5 whitespace-pre-wrap text-[#334155]">{n.text}</p></li>))}
          </ul>
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        <button type="button" onClick={() => setModal({ type: 'task', preset: { type: 'appel', title: `Rappeler ${d.prospect}`, prospect_id: d.prospect_id, prospect: d.prospect } })} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-[#DCE3EE] py-2 text-[12.5px] text-[#2F6BFF]"><ListPlus size={13} /> Ajouter une tâche</button>
        <button type="button" onClick={() => setModal({ type: 'task', preset: { type: 'rdv', title: 'Rendez-vous', prospect_id: d.prospect_id, prospect: d.prospect } })} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-[#DCE3EE] py-2 text-[12.5px] text-[#2F6BFF]"><CalendarDays size={13} /> Créer un RDV</button>
      </div>
      {d.stage !== 'perdu' && !['essai', 'signe'].includes(d.stage) && (
        <button type="button" onClick={() => setModal({ type: 'lost', pid: d.prospect_id, name: d.prospect })} className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#FDECEF] py-2.5 text-[12.5px] font-medium text-[#E11D48]"><Trash2 size={13} /> Marquer comme perdu</button>
      )}
    </div>
  );
}

/* The recording, fetched with the session (it is private), then played here. */
function Player({ callId, onDelete }) {
  const [url, setUrl] = useState(null);
  const [playing, setPlaying] = useState(false);
  const [t, setT] = useState(0);
  const [len, setLen] = useState(0);
  const [rate, setRate] = useState(1);
  const a = useRef(null);
  useEffect(() => {
    let u; setUrl(null); setPlaying(false); setT(0);
    crmAPI.recording(callId).then(({ data }) => { u = URL.createObjectURL(data); setUrl(u); }).catch(() => {});
    return () => { if (u) URL.revokeObjectURL(u); };
  }, [callId]);
  if (!url) return <p className="flex items-center gap-2 text-[12px] text-[#64748B]"><Loader2 size={13} className="animate-spin" /> Chargement…</p>;
  return (
    <div className="flex items-center gap-2 rounded-lg border border-[#EDF1F7] p-2">
      <audio ref={a} src={url} onTimeUpdate={(e) => setT(e.target.currentTime)} onLoadedMetadata={(e) => setLen(Number.isFinite(e.target.duration) ? e.target.duration : 0)} onEnded={() => setPlaying(false)} />
      <button type="button" aria-label={playing ? 'Pause' : 'Lecture'} onClick={() => { if (playing) a.current.pause(); else a.current.play(); setPlaying(!playing); }} className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-white" style={{ background: BLUE }}>{playing ? <Pause size={13} /> : <Play size={13} />}</button>
      <span className="text-[11.5px] text-[#475569]">{mmss(t)} / {mmss(len)}</span>
      <input type="range" min={0} max={len || 1} step={0.1} value={t} onChange={(e) => { a.current.currentTime = Number(e.target.value); setT(Number(e.target.value)); }} className="min-w-0 flex-1 accent-[#2F6BFF]" aria-label="Position" />
      <button type="button" onClick={() => { const r = rate === 1 ? 1.5 : rate === 1.5 ? 2 : 1; a.current.playbackRate = r; setRate(r); }} className="rounded border border-[#DCE3EE] px-1.5 py-0.5 text-[11px]">{rate}x</button>
      <a href={url} download={`appel-${callId}`} aria-label="Télécharger" className="text-[#2F6BFF]"><Download size={14} /></a>
      <button type="button" aria-label="Supprimer l'enregistrement" onClick={() => { if (window.confirm("Supprimer l'enregistrement ?")) onDelete(); }} className="text-[#94A3B8] hover:text-[#E11D48]"><Trash2 size={13} /></button>
    </div>
  );
}

/* One modal, three uses: call now (dialer + stopwatch), note a past call,
   plan a call. Completing a planned call opens it on « log ». */
function CallModal({ meta, mode: initial, call, prospect, results, onClose, onSaved }) {
  const [mode, setMode] = useState(initial);
  const [p, setP] = useState(call ? { id: call.prospect_id, name: call.prospect, phone: call.phone } : prospect || null);
  const [q, setQ] = useState('');
  const [found, setFound] = useState([]);
  const [f, setF] = useState({ result: '', min: '', sec: '', notes: call?.notes || '', when: '', by: '' });
  const [file, setFile] = useState(null);
  const [start, setStart] = useState(null);
  const [tick, setTick] = useState(0);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (p || q.length < 2) { setFound([]); return; }
    crmAPI.prospects({ q, per_page: 6 }).then(({ data }) => setFound(data.rows)).catch(() => {});
  }, [q, p]);
  useEffect(() => { if (!start) return undefined; const i = setInterval(() => setTick((x) => x + 1), 1000); return () => clearInterval(i); }, [start]);
  const elapsed = start ? Math.floor((Date.now() - start) / 1000) : 0;
  const hangUp = () => { const s = elapsed; setStart(null); setF((x) => ({ ...x, min: String(Math.floor(s / 60)), sec: String(s % 60) })); setMode('log'); };
  const save = async () => {
    setErr(''); setBusy(true);
    const dur = (Number(f.min) || 0) * 60 + (Number(f.sec) || 0);
    try {
      let c;
      if (mode === 'plan') {
        if (!f.when) throw new Error('Choisissez la date et l\'heure.');
        ({ data: c } = await crmAPI.addCall({ prospect_id: p?.id, status: 'planifie', at: new Date(f.when).toISOString(), notes: f.notes, ...(f.by ? { by: f.by } : {}) }));
      } else if (call?.status === 'planifie') {
        ({ data: c } = await crmAPI.editCall(call.id, { result: f.result, duration_sec: dur, notes: f.notes, status: 'termine' }));
      } else {
        ({ data: c } = await crmAPI.addCall({ prospect_id: p?.id, result: f.result, duration_sec: dur, notes: f.notes }));
      }
      if (file && c?.id) await crmAPI.uploadRecording(c.id, file);
      onSaved(c, mode === 'plan' ? 'Appel planifié — il est dans le calendrier.' : 'Appel enregistré.');
    } catch (e) { setErr(e?.response?.data?.detail || e.message || 'Enregistrement impossible.'); }
    setBusy(false);
  };
  const title = mode === 'plan' ? 'Planifier un appel' : mode === 'dial' ? 'Appeler un commerce' : call?.status === 'planifie' ? 'Résultat de l\'appel' : 'Noter un appel';
  void tick;
  return (
    <Modal title={title} onClose={onClose}>
      <div className="space-y-3">
        <div>
          <span className="mb-1 block text-[11.5px] text-[#64748B]">Commerce</span>
          {p ? (
            <p className="flex items-center justify-between rounded-lg bg-[#F4F7FC] px-3 py-2 text-[13px]"><span><strong>{p.name}</strong> {p.phone && <span className="text-[#64748B]">· {p.phone}</span>}</span>
              {!call && <button type="button" className="text-[12px] text-[#2F6BFF]" onClick={() => { setP(null); setStart(null); }}>Changer</button>}</p>
          ) : (
            <>
              <input autoFocus className={inputCls} placeholder="Chercher un commerce…" value={q} onChange={(e) => setQ(e.target.value)} />
              {found.map((x) => <button key={x.id} type="button" onClick={() => { setP({ id: x.id, name: x.name, phone: x.phone }); setQ(''); }} className="block w-full px-2 py-1.5 text-left text-[13px] hover:bg-[#F4F7FC]">{x.name} <span className="text-[#94A3B8]">{x.city}{x.phone ? ` · ${x.phone}` : ''}</span></button>)}
            </>
          )}
        </div>

        {mode === 'dial' && p && (
          p.phone ? (
            <div className="rounded-xl border border-[#E6EEFB] bg-[#F8FAFF] p-4 text-center">
              {!start ? (
                <>
                  <a href={`tel:${p.phone}`} onClick={() => setStart(Date.now())} className="inline-flex items-center gap-2 rounded-xl px-5 py-3 text-[15px] font-semibold text-white" style={{ background: '#10B981' }}><PhoneCall size={18} /> Appeler {p.phone}</a>
                  <p className="mt-2 text-[12px] text-[#64748B]">Sur ordinateur, composez le numéro sur votre téléphone puis cliquez sur « Démarrer le chrono ».</p>
                  <button type="button" onClick={() => setStart(Date.now())} className="mt-1 text-[12.5px] text-[#2F6BFF]">Démarrer le chrono</button>
                </>
              ) : (
                <>
                  <p className="text-[28px] font-bold tabular-nums text-[#0B1C3F]">{mmss(elapsed)}</p>
                  <p className="mb-3 text-[12px] text-[#64748B]">Appel en cours…</p>
                  <button type="button" onClick={hangUp} className="inline-flex items-center gap-2 rounded-xl bg-[#E11D48] px-5 py-2.5 text-[14px] font-semibold text-white"><Phone size={16} className="rotate-[135deg]" /> Raccroché — noter le résultat</button>
                </>
              )}
              <button type="button" onClick={() => setMode('log')} className="mt-3 block w-full text-[12px] text-[#94A3B8]">Pas de réponse ? Noter directement</button>
            </div>
          ) : <p className="rounded-lg bg-[#FFF4DB] px-3 py-2 text-[12.5px] text-[#92400E]">Ce commerce n'a pas de numéro. Ajoutez-le dans sa fiche prospect.</p>
        )}

        {mode === 'log' && (
          <>
            <div>
              <span className="mb-1.5 block text-[11.5px] text-[#64748B]">Résultat</span>
              <div className="flex flex-wrap gap-1.5">
                {results.filter((r) => r.key !== 'a_qualifier').map((r) => { const [bg, fg] = RESULT_TONE[r.key]; const on = f.result === r.key; return (
                  <button key={r.key} type="button" onClick={() => setF({ ...f, result: r.key, ...(r.key === 'sans_reponse' ? { min: '0', sec: '0' } : {}) })}
                          className="rounded-lg border px-2.5 py-1.5 text-[12.5px] font-medium" style={on ? { background: fg, color: '#fff', borderColor: fg } : { background: bg, color: fg, borderColor: 'transparent' }}>{r.label}</button>); })}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <label><span className="mb-1 block text-[11.5px] text-[#64748B]">Durée — minutes</span><input type="number" min={0} className={inputCls} value={f.min} onChange={(e) => setF({ ...f, min: e.target.value })} /></label>
              <label><span className="mb-1 block text-[11.5px] text-[#64748B]">secondes</span><input type="number" min={0} max={59} className={inputCls} value={f.sec} onChange={(e) => setF({ ...f, sec: e.target.value })} /></label>
            </div>
            <label className="block"><span className="mb-1 block text-[11.5px] text-[#64748B]">Enregistrement (facultatif)</span>
              <span className="flex items-center gap-2 rounded-lg border border-dashed border-[#BFD3FF] px-3 py-2 text-[12.5px] text-[#2F6BFF]"><Upload size={14} /> {file ? file.name : 'Choisir un fichier audio'}<input type="file" accept="audio/*,.m4a,.mp3,.wav,.ogg,.aac,.amr,.3gp" className="hidden" onChange={(e) => setFile(e.target.files?.[0] || null)} /></span></label>
          </>
        )}

        {mode === 'plan' && (
          <div className="grid grid-cols-2 gap-2">
            <label><span className="mb-1 block text-[11.5px] text-[#64748B]">Date et heure</span><input type="datetime-local" className={inputCls} value={f.when} onChange={(e) => setF({ ...f, when: e.target.value })} /></label>
            <Select label="Qui appelle" value={f.by} onChange={(v) => setF({ ...f, by: v })}><option value="">Moi</option>{(meta?.users || []).filter((u) => u.active).map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}</Select>
          </div>
        )}

        {mode !== 'dial' && <textarea className={`${inputCls} h-20 py-2`} placeholder={mode === 'plan' ? 'Objet de l\'appel (facultatif)' : 'Notes — ce qui a été dit, la suite…'} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />}
        {err && <p className="text-[13px] text-[#C0392B]">{err}</p>}
        {mode !== 'dial' && (
          <button type="button" disabled={busy || !p || (mode === 'log' && !f.result)} onClick={save} className="flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>
            {busy && <Loader2 size={15} className="animate-spin" />}{mode === 'plan' ? 'Planifier' : 'Enregistrer l\'appel'}</button>
        )}
        {mode === 'log' && f.result === 'rdv_obtenu' && <p className="text-center text-[12px] text-[#0F8B58]">Après l'enregistrement, vous pourrez fixer la date du rendez-vous.</p>}
      </div>
    </Modal>
  );
}

function EditCallModal({ call, results, onClose, onSaved }) {
  const [f, setF] = useState({ result: call.result, min: String(Math.floor(call.duration_sec / 60)), sec: String(call.duration_sec % 60), notes: call.notes });
  const [err, setErr] = useState('');
  const save = async () => {
    try { await crmAPI.editCall(call.id, { result: f.result, duration_sec: (Number(f.min) || 0) * 60 + (Number(f.sec) || 0), notes: f.notes }); onSaved(); }
    catch (e) { setErr(e?.response?.data?.detail || 'Enregistrement impossible.'); }
  };
  return (
    <Modal title={`Modifier l'appel — ${call.prospect}`} onClose={onClose}>
      <div className="space-y-3">
        <Select label="Résultat" value={f.result} onChange={(v) => setF({ ...f, result: v })}>{results.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}</Select>
        <div className="grid grid-cols-2 gap-2">
          <label><span className="mb-1 block text-[11.5px] text-[#64748B]">Minutes</span><input type="number" min={0} className={inputCls} value={f.min} onChange={(e) => setF({ ...f, min: e.target.value })} /></label>
          <label><span className="mb-1 block text-[11.5px] text-[#64748B]">Secondes</span><input type="number" min={0} max={59} className={inputCls} value={f.sec} onChange={(e) => setF({ ...f, sec: e.target.value })} /></label>
        </div>
        <textarea className={`${inputCls} h-24 py-2`} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="Notes" />
        {err && <p className="text-[13px] text-[#C0392B]">{err}</p>}
        <button type="button" onClick={save} className="w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white" style={{ background: BLUE }}>Enregistrer</button>
      </div>
    </Modal>
  );
}

function ImportCallsModal({ onClose, onDone }) {
  const [pv, setPv] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const pick = async (file) => {
    if (!file) return;
    setErr(''); setBusy(true);
    try { const { data } = await crmAPI.callsImportPreview(file); setPv(data); }
    catch (e) { setErr(e?.response?.data?.detail || 'Fichier illisible.'); }
    setBusy(false);
  };
  const fresh = pv?.rows.filter((r) => !r.duplicate) || [];
  const commit = async () => {
    setBusy(true);
    try { const { data } = await crmAPI.callsImportCommit(fresh); onDone(`${data.created} appel${data.created > 1 ? 's' : ''} importé${data.created > 1 ? 's' : ''}.`); }
    catch (e) { setErr(e?.response?.data?.detail || 'Import impossible.'); setBusy(false); }
  };
  return (
    <Modal title="Importer depuis mobile" onClose={onClose} wide={!!pv}>
      {!pv ? (
        <div className="space-y-3 text-[13px] text-[#334155]">
          <p>Importez le <strong>journal d'appels</strong> de votre téléphone : seuls les numéros de vos prospects sont gardés, les autres appels sont ignorés.</p>
          <ul className="list-disc space-y-1 pl-5 text-[12.5px] text-[#475569]">
            <li><strong>Android</strong> : l'app gratuite « SMS Backup &amp; Restore » → Sauvegarder → Journal d'appels. Envoyez-vous le fichier <code>calls-….xml</code>.</li>
            <li>Ou n'importe quel fichier <strong>CSV</strong> avec au moins une colonne « Numéro » (et si possible Date, Durée, Type).</li>
            <li><strong>iPhone</strong> : Apple ne permet pas d'exporter le journal d'appels — notez vos appels ici après les avoir passés.</li>
          </ul>
          <label className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed border-[#BFD3FF] bg-[#F8FAFF] py-8 text-[#2F6BFF]">
            {busy ? <Loader2 size={22} className="animate-spin" /> : <Upload size={22} />}<span className="font-medium">Choisir le fichier (CSV ou XML)</span>
            <input type="file" accept=".csv,.txt,.tsv,.xml" className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
          </label>
          {err && <p className="text-[13px] text-[#C0392B]">{err}</p>}
        </div>
      ) : (
        <div className="space-y-3 text-[13px]">
          <p className="text-[#334155]"><strong>{pv.found}</strong> appels lus · <strong className="text-[#0F8B58]">{fresh.length}</strong> avec vos prospects à importer · {pv.rows.length - fresh.length} déjà présents · {pv.unknown} numéros inconnus ignorés</p>
          <div className="max-h-[50vh] overflow-auto rounded-lg border border-[#EDF1F7]">
            <table className="w-full text-[12.5px]">
              <thead className="sticky top-0 bg-[#F8FAFF] text-left text-[#64748B]"><tr>{['Date', 'Commerce', 'Numéro', 'Durée', 'Sens', 'Résultat'].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>{pv.rows.map((r, i) => (
                <tr key={i} className={`border-t border-[#F1F5F9] ${r.duplicate ? 'opacity-40' : ''}`}>
                  <td className="px-2 py-1.5">{new Date(r.at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })}</td><td className="px-2 py-1.5 font-medium">{r.prospect}</td>
                  <td className="px-2 py-1.5">{r.number}</td><td className="px-2 py-1.5">{r.duration}</td>
                  <td className="px-2 py-1.5">{r.direction === 'entrant' ? 'Entrant' : r.direction === 'manque' ? 'Manqué' : 'Sortant'}</td>
                  <td className="px-2 py-1.5">{r.duplicate ? 'Déjà présent' : ({ sans_reponse: 'Sans réponse', rappel_demande: 'Rappel demandé', a_qualifier: 'À qualifier' })[r.result]}</td>
                </tr>))}
                {!pv.rows.length && <tr><td colSpan={6} className="py-8 text-center text-[#64748B]">Aucun appel avec un numéro de vos prospects.</td></tr>}
              </tbody>
            </table>
          </div>
          <p className="text-[12px] text-[#64748B]">Les appels décrochés arrivent « À qualifier » : ouvrez-les ensuite pour noter le résultat.</p>
          {err && <p className="text-[13px] text-[#C0392B]">{err}</p>}
          <div className="flex gap-2">
            <button type="button" onClick={() => setPv(null)} className="flex-1 rounded-lg border border-[#DCE3EE] py-2.5 text-[13.5px]">Autre fichier</button>
            <button type="button" disabled={busy || !fresh.length} onClick={commit} className="flex-1 rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>Importer {fresh.length} appel{fresh.length > 1 ? 's' : ''}</button>
          </div>
        </div>
      )}
    </Modal>
  );
}
