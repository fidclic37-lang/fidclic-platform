import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import {
  Mail, Send, MailOpen, MousePointerClick, Reply, Plus, ChevronDown, Search, MoreHorizontal, FileText, Pencil, Copy, X,
  CalendarDays, Play, Pause, Square, Trash2, UserPlus, Target, BarChart3, AlertTriangle, Users,
} from 'lucide-react';
import { crmAPI } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { Card, Head, Kpi, Donut, Avatar, Select, Loading, Breadcrumb, Pager, Modal, useToast, nf, BLUE, inputCls } from './ui';
import { GmailBanner, SequenceEditor, EnrollModal, SectorPill, SeqStatus, toneOf } from './emailUi';

/* CRM › Séquences d'emails — built to the approved mockup. */

const TABS = [['', 'Toutes les séquences', 'all'], ['active', 'Actives', 'active'], ['pause', 'En pause', 'pause'], ['terminee', 'Terminées', 'terminee'], ['brouillon', 'Brouillons', 'brouillon']];
const STEP_ICONS = [[MailOpen, '#2F6BFF', '#EAF1FF'], [Mail, '#0F8B58', '#E7F7EE'], [FileText, '#D97706', '#FFF4DB'], [Target, '#E11D48', '#FDECEF'], [CalendarDays, '#7C3AED', '#F3EEFF']];
const ENR_TONE = { en_cours: ['#EAF1FF', '#2F6BFF'], termine: ['#E7F7EE', '#0F8B58'], repondu: ['#E7F7EE', '#0F8B58'], desinscrit: ['#F1F5F9', '#475569'], arrete: ['#F1F5F9', '#475569'], erreur: ['#FDECEF', '#E11D48'] };
const short = (iso) => (iso ? new Date(iso).toLocaleDateString('fr-FR') : '—');

export default function CrmSequencesPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const admin = user?.role === 'super_admin';
  const [meta, setMeta] = useState(null);
  const [status, setStatus] = useState(null);
  const [sum, setSum] = useState(null);
  const [list, setList] = useState(null);
  const [tpls, setTpls] = useState({ rows: [], variables: [] });
  const [tab, setTab] = useState('');
  const [f, setF] = useState({ q: '', sector: '', status: '', created_by: '' });
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(10);
  const [selId, setSelId] = useState(null);
  const [d, setD] = useState(null);
  const [modal, setModal] = useState(null);
  const [menu, setMenu] = useState(null);
  const [running, setRunning] = useState(false);
  const [say, toast] = useToast();

  const loadList = useCallback(() => {
    crmAPI.sequences({ ...f, tab, page, per_page: perPage }).then(({ data }) => {
      setList(data); setSelId((s) => (s && data.rows.some((r) => r.id === s) ? s : data.rows[0]?.id || null));
      crmAPI.sequencesSummary().then(({ data: x }) => setSum(x)).catch(() => {});
      crmAPI.emailStatus().then(({ data: x }) => setStatus(x)).catch(() => {});
    }).catch(() => setList({ rows: [], total: 0, counts: {}, pages: 1, sectors: [] }));
  }, [f, tab, page, perPage]);
  useEffect(() => { loadList(); }, [loadList]);
  useEffect(() => {
    crmAPI.meta().then(({ data }) => setMeta(data)).catch(() => {});
    crmAPI.emailTemplates().then(({ data }) => setTpls(data)).catch(() => {});
  }, []);
  const loadDetail = useCallback(() => {
    if (!selId) { setD(null); return; }
    crmAPI.sequence(selId).then(({ data }) => setD(data)).catch(() => setD(null));
  }, [selId]);
  useEffect(() => { loadDetail(); }, [loadDetail]);
  const refresh = (m) => { if (m) say(m); loadList(); loadDetail(); };
  const act = async (fn, m) => { try { await fn(); refresh(m); } catch (e) { say(e?.response?.data?.detail || 'Action impossible.'); } };
  const setFilter = (k) => (v) => { setPage(1); setF({ ...f, [k]: v }); };
  const run = async () => {
    setRunning(true);
    try { const { data } = await crmAPI.runSequences(); refresh(`${data.sent || 0} email${data.sent > 1 ? 's' : ''} envoyé${data.sent > 1 ? 's' : ''}${data.replies ? ` · ${data.replies} réponse${data.replies > 1 ? 's' : ''} reçue${data.replies > 1 ? 's' : ''}` : ''}.`); }
    catch (e) { say(e?.response?.data?.detail || 'Envoi impossible.'); }
    setRunning(false);
  };
  const createFrom = async (body, focus) => {
    try { const { data } = await crmAPI.addSequence(body); setSelId(data.id); refresh(); setModal({ type: 'edit', seq: data, focus }); }
    catch (e) { say(e?.response?.data?.detail || 'Création impossible.'); }
  };
  const tplName = (id) => tpls.rows.find((t) => t.id === id)?.name;

  if (!list || !sum) return <Loading />;
  const K = Object.fromEntries(sum.cards.map((c) => [c.key, c]));
  const seqMenu = (s, close) => (
    <>
      {s.status !== 'active' && s.status !== 'terminee' && <button type="button" onClick={() => { close(); act(() => crmAPI.sequenceStatus(s.id, 'active'), 'Séquence activée.'); }} className="flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]"><Play size={13} /> Activer</button>}
      {s.status === 'active' && <button type="button" onClick={() => { close(); act(() => crmAPI.sequenceStatus(s.id, 'pause'), 'Séquence en pause.'); }} className="flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]"><Pause size={13} /> Mettre en pause</button>}
      {s.status !== 'terminee' && s.status !== 'brouillon' && <button type="button" onClick={() => { close(); if (window.confirm('Terminer la séquence ? Plus aucun email ne partira.')) act(() => crmAPI.sequenceStatus(s.id, 'terminee'), 'Séquence terminée.'); }} className="flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]"><Square size={13} /> Terminer</button>}
      <button type="button" onClick={() => { close(); act(async () => { const { data } = await crmAPI.duplicateSequence(s.id); setSelId(data.id); }, 'Séquence dupliquée.'); }} className="flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F4F7FC]"><Copy size={13} /> Dupliquer</button>
      <button type="button" onClick={() => { close(); if (window.confirm(`Supprimer « ${s.name} » ?`)) act(() => crmAPI.deleteSequence(s.id), 'Séquence supprimée.'); }} className="flex items-center gap-2 px-3 py-2 text-left text-[#E11D48] hover:bg-[#FEF2F2]"><Trash2 size={13} /> Supprimer</button>
    </>
  );
  const dayLabel = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });

  return (
    <div className="crm" onClick={() => setMenu(null)}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', admin ? '/admin' : null], ['CRM de prospection', '/admin/crm'], ["Séquences d'emails"]]} />
          <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Séquences d'emails</h1>
          <p className="text-[15px] text-[#475569]">Créez des séquences automatisées pour contacter vos prospects et augmenter votre taux de réponse.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => setModal({ type: 'presets' })} className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#2F6BFF] bg-white px-4 text-[13.5px] font-medium text-[#2F6BFF]"><FileText size={16} /> Créer depuis un modèle</button>
          <span className="relative" onClick={(e) => e.stopPropagation()}>
            <button type="button" onClick={() => setMenu(menu === 'new' ? null : 'new')} className="inline-flex h-10 items-center gap-2 rounded-xl px-4 text-[13.5px] font-medium text-white" style={{ background: BLUE }}><Plus size={16} /> Nouvelle séquence d'emails <ChevronDown size={15} /></button>
            {menu === 'new' && (
              <span className="absolute right-0 top-full z-30 mt-1 flex w-64 flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 text-[13px] shadow-[0_24px_60px_-28px_rgba(11,28,63,.5)]">
                <button type="button" onClick={() => { setMenu(null); setModal({ type: 'edit', seq: null }); }} className="px-3.5 py-2 text-left font-semibold text-[#2F6BFF] hover:bg-[#F4F7FC]">Séquence vierge</button>
                {sum.presets.map((p) => <button key={p.key} type="button" onClick={() => { setMenu(null); createFrom({ preset: p.key }); }} className="px-3.5 py-2 text-left hover:bg-[#F4F7FC]">{p.name}</button>)}
                <button type="button" onClick={() => { setMenu(null); navigate('/admin/crm/modeles'); }} className="border-t border-[#EDF1F7] px-3.5 py-2 text-left text-[#475569] hover:bg-[#F4F7FC]">Gérer les modèles d'emails</button>
              </span>
            )}
          </span>
        </div>
      </header>

      <GmailBanner status={status} onRun={status?.configured ? run : null} running={running} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
        <Kpi icon={Mail} tone="#2F6BFF" bg="#EAF1FF" value={nf(K.active.value)} label="Séquences actives" delta={K.active.delta} series={K.active.series || []} />
        <Kpi icon={Send} tone="#F59E0B" bg="#FFF4DB" value={nf(K.sent.value)} label="Emails envoyés" delta={K.sent.delta} series={K.sent.series} />
        <Kpi icon={MailOpen} tone="#10B981" bg="#E7F7EE" value={`${K.open_rate.value}%`} label="Taux d'ouverture" delta={K.open_rate.delta} series={K.open_rate.series} />
        <Kpi icon={MousePointerClick} tone="#2F6BFF" bg="#EAF1FF" value={`${K.click_rate.value}%`} label="Taux de clic" delta={K.click_rate.delta} series={K.click_rate.series} />
        <Kpi icon={Reply} tone="#E11D48" bg="#FDECEF" value={`${K.reply_rate.value}%`} label="Taux de réponse" delta={K.reply_rate.delta} series={K.reply_rate.series} />
      </div>

      <div className="mt-4 grid items-start gap-4 xl:grid-cols-[1fr_340px]">
        <Card className="min-w-0 p-0">
          <nav className="flex flex-wrap gap-1 border-b border-[#EDF1F7] px-3">
            {TABS.map(([k, l, c]) => (
              <button key={l} type="button" onClick={() => { setPage(1); setTab(k); }} className={`border-b-2 px-3 py-3 text-[13.5px] ${tab === k ? 'border-[#2F6BFF] font-medium text-[#2F6BFF]' : 'border-transparent text-[#0B1C3F]'}`}>{l} ({nf(list.counts[c] || 0)})</button>
            ))}
          </nav>
          <div className="p-4">
            <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-[1.5fr_1fr_1fr_1fr]">
              <label className="relative"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
                <input className={`${inputCls} pl-9`} placeholder="Rechercher une séquence…" value={f.q} onChange={(e) => setFilter('q')(e.target.value)} /></label>
              <Select value={f.sector} onChange={setFilter('sector')}><option value="">Tous les secteurs</option>{(list.sectors || []).map((s) => <option key={s}>{s}</option>)}</Select>
              <Select value={f.status} onChange={setFilter('status')}><option value="">Tous les statuts</option><option value="active">Active</option><option value="pause">En pause</option><option value="terminee">Terminée</option><option value="brouillon">Brouillon</option></Select>
              <Select value={f.created_by} onChange={setFilter('created_by')}><option value="">Tous les utilisateurs</option>{(meta?.users || []).map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}</Select>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] text-[12.5px]">
                <thead><tr className="border-b border-[#EDF1F7] text-left text-[#64748B]">{['Nom de la séquence', 'Secteur cible', "Nb d'emails", 'Prospects', 'Ouverts', 'Clics', 'Réponses', 'Statut', 'Dernière activité', 'Créée par', ''].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
                <tbody>
                  {list.rows.map((s) => { const [bg, fg] = toneOf(s.sector || s.name); return (
                    <tr key={s.id} onClick={() => setSelId(s.id)} className={`cursor-pointer border-b border-[#F4F7FC] ${selId === s.id ? 'bg-[#F4F8FF]' : 'hover:bg-[#FAFCFF]'}`}>
                      <td className="px-2 py-2.5"><span className="flex items-center gap-2"><span className="grid h-6 w-6 shrink-0 place-items-center rounded-md" style={{ background: bg, color: fg }}><Mail size={13} /></span><span className="max-w-[190px] truncate font-medium text-[#0B1C3F]">{s.name}</span></span></td>
                      <td className="px-2 py-2.5"><SectorPill s={s.sector} /></td>
                      <td className="px-2 py-2.5 text-center">{s.steps_count}</td>
                      <td className="px-2 py-2.5 text-center">{nf(s.prospects)}</td>
                      <td className="px-2 py-2.5">{s.sent ? `${s.open_rate}%` : '—'}</td>
                      <td className="px-2 py-2.5">{s.sent ? `${s.click_rate}%` : '—'}</td>
                      <td className="px-2 py-2.5">{s.sent ? `${s.reply_rate}%` : '—'}</td>
                      <td className="px-2 py-2.5"><SeqStatus s={s.status} label={s.status_label} /></td>
                      <td className="px-2 py-2.5 text-[#475569]">{short(s.last_activity_at)}</td>
                      <td className="px-2 py-2.5"><span title={s.created_by_name} className="text-[#475569]">{(s.created_by_name || '').split(' ').map((w) => w[0]).join('').slice(0, 3).toUpperCase()}</span></td>
                      <td className="relative px-2 py-2.5" onClick={(e) => e.stopPropagation()}>
                        <button type="button" aria-label="Actions" onClick={() => setMenu(menu === s.id ? null : s.id)} className="rounded p-1 hover:bg-[#F4F7FC]"><MoreHorizontal size={16} /></button>
                        {menu === s.id && <span className="absolute right-2 top-full z-20 flex w-48 flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-lg">{seqMenu(s, () => setMenu(null))}</span>}
                      </td>
                    </tr>); })}
                  {!list.rows.length && <tr><td colSpan={11} className="py-12 text-center text-[#64748B]">Aucune séquence ici. Créez-en une depuis un modèle pour démarrer vite.</td></tr>}
                </tbody>
              </table>
            </div>
            <Pager page={page} pages={list.pages} total={list.total} perPage={perPage} onPage={setPage} onPerPage={(n) => { setPerPage(n); setPage(1); }} what="séquences" />
          </div>
        </Card>

        <Card className="xl:sticky xl:top-4">
          <Head title="Détails de la séquence" right={d && <button type="button" aria-label="Fermer" onClick={() => setSelId(null)} className="text-[#94A3B8]"><X size={16} /></button>} />
          {!d ? <p className="py-10 text-center text-[13px] text-[#64748B]">Choisissez une séquence.</p>
            : <Detail d={d} tplName={tplName} menu={menu} setMenu={setMenu} seqMenu={seqMenu} setModal={setModal} act={act} />}
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card>
          <Head icon={BarChart3} title="Performance globale" sub="7 derniers jours" />
          <div className="mb-1 flex flex-wrap gap-3 text-[12px] text-[#475569]">
            <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-[#2F6BFF]" />Taux d'ouverture <strong>{sum.overall.open_rate}%</strong></span>
            <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-[#10B981]" />Taux de clic <strong>{sum.overall.click_rate}%</strong></span>
            <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-[#A855F7]" />Taux de réponse <strong>{sum.overall.reply_rate}%</strong></span>
          </div>
          <div className="h-[190px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={sum.performance.map((x) => ({ ...x, j: dayLabel(x.day) }))} margin={{ top: 8, right: 8, left: -22, bottom: 0 }}>
                <CartesianGrid stroke="#EEF2F7" vertical={false} />
                <XAxis dataKey="j" tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} />
                <YAxis unit="%" tick={{ fontSize: 11, fill: '#64748B' }} axisLine={false} tickLine={false} />
                <Tooltip formatter={(v, k) => [`${v}%`, { open_rate: "Taux d'ouverture", click_rate: 'Taux de clic', reply_rate: 'Taux de réponse' }[k]]} />
                <Line type="monotone" dataKey="open_rate" stroke="#2F6BFF" strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="click_rate" stroke="#10B981" strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="reply_rate" stroke="#A855F7" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card><Head icon={Target} title="Répartition par secteur" sub="emails envoyés, 30 jours" /><Donut rows={sum.by_sector} center={nf(sum.by_sector.reduce((a, r) => a + r.count, 0))} sub="emails envoyés" /></Card>
        <Card>
          <Head icon={FileText} title="Modèles d'emails populaires" right={<button type="button" onClick={() => navigate('/admin/crm/modeles')} className="rounded-lg border border-[#DCE3EE] px-2.5 py-1 text-[12px] text-[#2F6BFF]">Voir tous</button>} />
          <ul className="space-y-2.5">
            {sum.templates.map((t) => (
              <li key={t.id} className="flex items-center gap-3 text-[13px]">
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-[#EAF1FF] text-[#2F6BFF]"><Mail size={14} /></span>
                <span className="min-w-0 flex-1"><span className="block truncate font-medium text-[#0B1C3F]">{t.name}</span>
                  <span className="text-[11.5px] text-[#64748B]">{t.uses ? <>Ouverture <strong className="text-[#0F8B58]">{t.open_rate}%</strong> · utilisé {nf(t.uses)} fois</> : t.unfinished ? <span className="text-[#D97706]">À compléter avant envoi</span> : 'Pas encore utilisé'}</span></span>
                <button type="button" onClick={() => createFrom({ name: t.name, template_id: t.id }, 0)} className="rounded-lg border border-[#DCE3EE] px-2.5 py-1 text-[12px] text-[#2F6BFF]">Utiliser</button>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      {toast}
      {modal?.type === 'edit' && <SequenceEditor seq={modal.seq} focus={modal.focus} meta={meta} templates={tpls.rows} variables={tpls.variables} onClose={() => setModal(null)} onSaved={(s) => { setModal(null); setSelId(s.id); refresh('Séquence enregistrée.'); }} />}
      {modal?.type === 'enroll' && <EnrollModal seq={modal.seq} meta={meta} onClose={() => setModal(null)} onDone={(m) => { setModal(null); refresh(m); }} />}
      {modal?.type === 'presets' && (
        <Modal title="Créer depuis un modèle" onClose={() => setModal(null)}>
          <div className="space-y-2">
            {sum.presets.map((p) => (
              <button key={p.key} type="button" onClick={() => { setModal(null); createFrom({ preset: p.key }); }} className="block w-full rounded-xl border border-[#DCE3EE] p-3 text-left hover:border-[#2F6BFF]">
                <p className="font-semibold text-[#0B1C3F]">{p.name}</p><p className="text-[12.5px] text-[#64748B]">{p.description}</p>
              </button>
            ))}
            <p className="pt-1 text-[12px] text-[#64748B]">La séquence est créée en brouillon : relisez-la, adaptez-la, puis activez-la.</p>
          </div>
        </Modal>
      )}
    </div>
  );
}

function Detail({ d, tplName, menu, setMenu, seqMenu, setModal, act }) {
  const [tab, setTab] = useState('steps');
  useEffect(() => { setTab('steps'); }, [d.id]);
  const [bg, fg] = toneOf(d.sector || d.name);
  const todo = d.steps.some((s) => s.unfinished);
  return (
    <div className="space-y-3 text-[13px]">
      <div className="flex items-start gap-3">
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl" style={{ background: bg, color: fg }}><CalendarDays size={22} /></span>
        <div className="min-w-0 flex-1">
          <p className="flex items-start justify-between gap-2"><span className="font-bold text-[#0B1C3F]">{d.name}</span><SeqStatus s={d.status} label={d.status_label} /></p>
          <p className="text-[12px] text-[#64748B]">{d.steps_count} email{d.steps_count > 1 ? 's' : ''} · Créée le {short(d.created_at)}</p>
          {d.target && <p className="text-[12px] text-[#64748B]">Cible : {d.target}</p>}
        </div>
      </div>
      <div className="grid grid-cols-[1fr_1fr_auto] gap-2">
        <button type="button" onClick={() => setModal({ type: 'edit', seq: d })} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-[#DCE3EE] py-2 text-[12.5px] text-[#2F6BFF]"><Pencil size={13} /> Modifier</button>
        {d.status === 'active' ? <button type="button" onClick={() => act(() => crmAPI.sequenceStatus(d.id, 'pause'), 'Séquence en pause.')} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-[#DCE3EE] py-2 text-[12.5px] text-[#D97706]"><Pause size={13} /> Pause</button>
          : d.status !== 'terminee' ? <button type="button" onClick={() => act(() => crmAPI.sequenceStatus(d.id, 'active'), 'Séquence activée.')} className="inline-flex items-center justify-center gap-1.5 rounded-lg py-2 text-[12.5px] font-semibold text-white" style={{ background: '#10B981' }}><Play size={13} /> Activer</button>
            : <button type="button" onClick={() => act(() => crmAPI.duplicateSequence(d.id), 'Séquence dupliquée.')} className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-[#DCE3EE] py-2 text-[12.5px] text-[#2F6BFF]"><Copy size={13} /> Dupliquer</button>}
        <span className="relative" onClick={(e) => e.stopPropagation()}>
          <button type="button" aria-label="Plus d'actions" onClick={() => setMenu(menu === 'detail' ? null : 'detail')} className="h-full rounded-lg border border-[#DCE3EE] px-2.5 text-[#2F6BFF]"><MoreHorizontal size={15} /></button>
          {menu === 'detail' && <span className="absolute right-0 top-full z-20 mt-1 flex w-48 flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-lg">{seqMenu(d, () => setMenu(null))}</span>}
        </span>
      </div>
      {todo && <p className="flex items-center gap-1.5 rounded-lg bg-[#FFF4DB] px-2.5 py-1.5 text-[12px] text-[#92400E]"><AlertTriangle size={13} /> Une étape contient encore [À COMPLÉTER].</p>}
      <nav className="flex gap-1 border-b border-[#EDF1F7]">
        {[['steps', `Étapes (${d.steps.length})`], ['stats', 'Statistiques'], ['people', `Prospects (${nf(d.prospects)})`]].map(([k, l]) => (
          <button key={k} type="button" onClick={() => setTab(k)} className={`border-b-2 px-2 py-2 text-[12.5px] ${tab === k ? 'border-[#2F6BFF] font-medium text-[#2F6BFF]' : 'border-transparent text-[#475569]'}`}>{l}</button>
        ))}
      </nav>
      {tab === 'steps' && (
        <>
          <ol className="relative space-y-1 before:absolute before:bottom-4 before:left-[17px] before:top-4 before:w-px before:bg-[#E6EEFB]">
            {d.steps.map((s, i) => { const [I, c, b] = STEP_ICONS[i % STEP_ICONS.length]; return (
              <li key={s.id} className="relative flex items-start gap-3 rounded-lg p-1.5 hover:bg-[#FAFCFF]">
                <span className="z-10 grid h-9 w-9 shrink-0 place-items-center rounded-lg" style={{ background: b, color: c }}><I size={16} /></span>
                <button type="button" onClick={() => setModal({ type: 'edit', seq: d, focus: i })} className="min-w-0 flex-1 text-left">
                  <p className="truncate font-semibold text-[#0B1C3F]">{i + 1}. {tplName(s.template_id) || s.subject || 'Sans objet'}</p>
                  <p className="text-[11.5px] text-[#64748B]">Jour {s.day} - {s.time}{s.sent ? ` · ${nf(s.sent)} envoyés` : ''}</p>
                  <p className={`truncate text-[12px] ${s.unfinished ? 'text-[#D97706]' : 'text-[#475569]'}`}>{s.subject}</p>
                </button>
              </li>); })}
            {!d.steps.length && <li className="py-4 text-center text-[#94A3B8]">Aucune étape.</li>}
          </ol>
          {d.status !== 'terminee' && <button type="button" onClick={() => setModal({ type: 'edit', seq: d, focus: 'new' })} className="flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-[13px] font-semibold text-white" style={{ background: BLUE }}><Plus size={15} /> Ajouter une étape</button>}
        </>
      )}
      {tab === 'stats' && (
        <div className="space-y-2">
          <div className="grid grid-cols-4 gap-1.5 text-center">
            {[['Envoyés', nf(d.sent)], ['Ouverts', `${d.open_rate}%`], ['Clics', `${d.click_rate}%`], ['Réponses', `${d.reply_rate}%`]].map(([k, v]) => (
              <p key={k} className="rounded-lg bg-[#F8FAFF] py-2"><strong className="block text-[15px] text-[#0B1C3F]">{v}</strong><span className="text-[11px] text-[#64748B]">{k}</span></p>
            ))}
          </div>
          <table className="w-full text-[12px]">
            <thead><tr className="text-left text-[#64748B]"><th className="py-1 font-medium">Étape</th><th className="font-medium">Env.</th><th className="font-medium">Ouv.</th><th className="font-medium">Clic</th><th className="font-medium">Rép.</th></tr></thead>
            <tbody>{d.steps.map((s, i) => <tr key={s.id} className="border-t border-[#F1F5F9]"><td className="py-1.5">{i + 1}. J{s.day}</td><td>{nf(s.sent)}</td><td>{s.open_rate}%</td><td>{s.click_rate}%</td><td>{s.reply_rate}%</td></tr>)}</tbody>
          </table>
          <p className="text-[11.5px] text-[#94A3B8]">Les ouvertures sont approximatives : certaines messageries bloquent ou pré-chargent les images.</p>
        </div>
      )}
      {tab === 'people' && (
        <div className="space-y-2">
          {d.status !== 'terminee' && <button type="button" onClick={() => setModal({ type: 'enroll', seq: d })} className="flex w-full items-center justify-center gap-2 rounded-lg border border-[#2F6BFF] py-2 text-[12.5px] font-medium text-[#2F6BFF]"><UserPlus size={14} /> Ajouter des prospects</button>}
          <ul className="max-h-[380px] space-y-1.5 overflow-y-auto">
            {d.enrollments.map((e) => { const [b, c] = ENR_TONE[e.status] || ENR_TONE.arrete; return (
              <li key={e.id} className="flex items-center gap-2 rounded-lg border border-[#EDF1F7] p-2">
                <span className="min-w-0 flex-1"><span className="block truncate font-medium text-[#0B1C3F]">{e.prospect}</span>
                  <span className="text-[11.5px] text-[#64748B]">{e.status === 'en_cours' ? `Étape ${e.step + 1}/${d.steps.length} · ${e.next_at ? new Date(e.next_at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : ''}` : e.reason || `${e.sent} envoyé${e.sent > 1 ? 's' : ''}`}</span></span>
                <span className="rounded-md px-1.5 py-0.5 text-[11px] font-medium" style={{ background: b, color: c }}>{e.status_label}</span>
                {e.status === 'en_cours' && <button type="button" aria-label="Arrêter pour ce prospect" title="Arrêter pour ce prospect" onClick={() => act(() => crmAPI.stopEnrollment(d.id, e.id), 'Arrêté pour ce prospect.')} className="text-[#94A3B8] hover:text-[#E11D48]"><Square size={13} /></button>}
              </li>); })}
            {!d.enrollments.length && <li className="flex flex-col items-center gap-1 py-6 text-center text-[#94A3B8]"><Users size={18} />Aucun prospect dans cette séquence.</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
