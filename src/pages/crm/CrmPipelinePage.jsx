import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Plus, Upload, CalendarDays, Lock, Loader2 } from 'lucide-react';
import { crmAPI } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { Card, Select, Loading, Breadcrumb, Avatar, Logo, Modal, useToast, nf, BLUE, STAGE_TONE, inputCls } from './ui';
import { ImportModal, ProspectModal } from './modals';

/* CRM › Pipeline — every prospect in its stage's column. Drag a card to
   another column to move it (a business on FidClic follows its account and
   cannot be moved by hand). No mockup was
   given for this page: it uses the other CRM pages' design. */

export default function CrmPipelinePage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const admin = user?.role === 'super_admin';
  const [d, setD] = useState(null);
  const [meta, setMeta] = useState(null);
  const [f, setF] = useState({ q: '', sector: '', city: '', assigned: '', source: '' });
  const [drag, setDrag] = useState(null);
  const [over, setOver] = useState(null);
  const [lost, setLost] = useState(null);
  const [modal, setModal] = useState(null);
  const [err, setErr] = useState('');
  const [say, toast] = useToast();

  const load = useCallback(() => {
    crmAPI.pipeline(f).then(({ data }) => setD(data)).catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger le pipeline.'));
  }, [f]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { crmAPI.meta().then(({ data }) => setMeta(data)).catch(() => {}); }, []);

  const move = async (card, stage, reason) => {
    setErr('');
    try { await crmAPI.setStage(card.id, stage, reason); say(`${card.name} → ${meta?.stages.find((s) => s.key === stage)?.label}`); load(); }
    catch (e) { setErr(e?.response?.data?.detail || 'Déplacement impossible.'); }
  };
  const drop = (stage) => {
    setOver(null);
    if (!drag || drag.stage === stage) return;
    if (stage === 'perdu') { setLost({ card: drag }); return; }
    move(drag, stage);
  };

  if (!d) return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p> : <Loading />;
  return (
    <div className="crm">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', admin ? '/admin' : null], ['CRM de prospection', '/admin/crm'], ['Pipeline']]} />
          <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Pipeline</h1>
          <p className="text-[15px] text-[#475569]">Faites avancer vos prospects d'une étape à l'autre, jusqu'à la signature.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => setModal({ type: 'import' })} className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#2F6BFF] bg-white px-4 text-[13.5px] font-medium text-[#2F6BFF]"><Upload size={16} /> Importer</button>
          <button type="button" onClick={() => setModal({ type: 'add' })} className="inline-flex h-10 items-center gap-2 rounded-xl px-4 text-[13.5px] font-medium text-white" style={{ background: BLUE }}><Plus size={16} /> Ajouter un prospect</button>
        </div>
      </header>

      <Card className="mb-4">
        <div className="grid gap-2 md:grid-cols-[1.6fr_repeat(4,1fr)_auto] md:items-center">
          <label className="relative"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            <input className={`${inputCls} pl-9`} placeholder="Rechercher un commerce, un contact…" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} /></label>
          <Select value={f.sector} onChange={(v) => setF({ ...f, sector: v })}><option value="">Tous les secteurs</option>{(meta?.sectors || []).map((s) => <option key={s}>{s}</option>)}</Select>
          <Select value={f.city} onChange={(v) => setF({ ...f, city: v })}><option value="">Toutes les villes</option>{(meta?.cities || []).map((s) => <option key={s}>{s}</option>)}</Select>
          <Select value={f.assigned} onChange={(v) => setF({ ...f, assigned: v })}><option value="">Tous les assignés</option><option value="none">Personne</option>{(meta?.users || []).map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}</Select>
          <Select value={f.source} onChange={(v) => setF({ ...f, source: v })}><option value="">Toutes les sources</option>{(meta?.sources || []).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</Select>
          <p className="text-right text-[12.5px] text-[#64748B]">{nf(d.total)} prospects · conversion <strong className="text-[#0F8B58]">{d.conversion ?? '—'}%</strong></p>
        </div>
      </Card>
      {err && <p className="mb-3 rounded-xl bg-[#FEF2F2] px-4 py-2.5 text-[13px] text-[#B91C1C]">{err}</p>}

      <div className="flex gap-3 overflow-x-auto pb-3">
        {d.columns.map((c) => {
          const [bg, fg] = STAGE_TONE[c.key];
          return (
            <section key={c.key} onDragOver={(e) => { e.preventDefault(); setOver(c.key); }} onDragLeave={() => setOver(null)} onDrop={() => drop(c.key)}
                     className={`flex w-[270px] shrink-0 flex-col rounded-2xl border bg-white transition ${over === c.key ? 'border-[#2F6BFF] shadow-[0_0_0_3px_rgba(47,107,255,.15)]' : 'border-[#EDF1F7]'}`}>
              <header className="flex items-center justify-between rounded-t-2xl px-3 py-2.5" style={{ background: bg }}>
                <span className="text-[13px] font-semibold" style={{ color: fg }}>{c.label}</span>
                <span className="rounded-full bg-white px-2 py-0.5 text-[12px] font-semibold text-[#0B1C3F]">{nf(c.count)}</span>
              </header>
              <div className="max-h-[70vh] min-h-[120px] space-y-2 overflow-y-auto p-2">
                {c.rows.map((p) => (
                  <article key={p.id} draggable={!p.on_fidclic} onDragStart={() => setDrag(p)} onDragEnd={() => setDrag(null)}
                           onClick={() => navigate(`/admin/crm/prospects?open=${p.id}`)}
                           className={`${p.on_fidclic ? 'cursor-pointer' : 'cursor-grab active:cursor-grabbing'} rounded-xl border border-[#EDF1F7] bg-white p-2.5 shadow-[0_1px_2px_rgba(11,28,63,.04)] hover:border-[#2F6BFF]`}>
                    <p className="flex items-center gap-2"><Logo name={p.name} size={26} /><span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-[#0B1C3F]">{p.name}</span>
                      {p.on_fidclic && <Lock size={12} className="shrink-0 text-[#94A3B8]" title="Sur FidClic : suit son abonnement" />}</p>
                    <p className="mt-1 truncate text-[11.5px] text-[#64748B]">{[p.sector, p.city].filter(Boolean).join(' · ') || '—'}</p>
                    {p.next_action && <p className="mt-1.5 flex items-center gap-1 text-[11.5px] text-[#475569]"><CalendarDays size={12} className="text-[#2F6BFF]" /> {new Date(p.next_action.due_at).toLocaleDateString('fr-FR')} · {p.next_action.label}</p>}
                    <div className="mt-2 flex items-center justify-between"><Avatar name={p.assigned_name} size={20} />{c.key === 'perdu' && p.lost_reason && <span className="text-[11px] text-[#E11D48]">{p.lost_reason}</span>}</div>
                  </article>
                ))}
                {c.count > c.rows.length && (
                  <button type="button" onClick={() => navigate(`/admin/crm/prospects?stage=${c.key}`)} className="w-full py-1.5 text-[12px] text-[#2F6BFF]">Voir les {nf(c.count)} →</button>
                )}
                {!c.count && <p className="py-6 text-center text-[12px] text-[#94A3B8]">Déposez un prospect ici</p>}
              </div>
            </section>
          );
        })}
      </div>

      {toast}
      {lost && (
        <Modal title={`Motif de perte — ${lost.card.name}`} onClose={() => setLost(null)}>
          <div className="space-y-2">{(meta?.lost_reasons || []).filter((r) => r !== 'Abonnement résilié').map((r) => (
            <button key={r} type="button" onClick={() => { const c = lost.card; setLost(null); move(c, 'perdu', r); }}
                    className="block w-full rounded-lg border border-[#DCE3EE] px-3 py-2.5 text-left text-[13.5px] hover:border-[#E11D48]">{r}</button>))}</div>
        </Modal>
      )}
      {modal?.type === 'import' && <ImportModal meta={meta} onClose={() => setModal(null)} onDone={(m) => { setModal(null); say(m); load(); }} />}
      {modal?.type === 'add' && <ProspectModal meta={meta} onClose={() => setModal(null)} onSaved={(_, m) => { setModal(null); say(m); load(); }} />}
    </div>
  );
}
