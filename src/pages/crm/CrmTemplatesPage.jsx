import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Search, Mail, Pencil, Trash2, AlertTriangle, Send, Loader2, Copy } from 'lucide-react';
import { crmAPI } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { Card, Loading, Breadcrumb, Modal, Select, useToast, nf, BLUE, inputCls } from './ui';
import { EmailFields, GmailBanner, toneOf, unfinished } from './emailUi';

/* CRM › Modèles d'emails — no mockup was given for this page: it uses the
   other CRM pages' design. */

export default function CrmTemplatesPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const admin = user?.role === 'super_admin';
  const [d, setD] = useState(null);
  const [status, setStatus] = useState(null);
  const [q, setQ] = useState('');
  const [cat, setCat] = useState('');
  const [modal, setModal] = useState(null);
  const [say, toast] = useToast();
  const load = useCallback(() => {
    crmAPI.emailTemplates({ q }).then(({ data }) => setD(data)).catch(() => setD({ rows: [], variables: [], categories: [] }));
  }, [q]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { crmAPI.emailStatus().then(({ data }) => setStatus(data)).catch(() => {}); }, []);
  const mayEdit = (t) => admin || t.created_by === user?.email;
  const use = async (t) => {
    try { await crmAPI.addSequence({ name: t.name, template_id: t.id }); navigate('/admin/crm/sequences'); }
    catch (e) { say(e?.response?.data?.detail || 'Création impossible.'); }
  };

  if (!d) return <Loading />;
  const rows = d.rows.filter((t) => !cat || t.category === cat);
  return (
    <div className="crm">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Breadcrumb items={[['Super Admin', admin ? '/admin' : null], ['CRM de prospection', '/admin/crm'], ["Modèles d'emails"]]} />
          <h1 className="text-[28px] font-bold leading-tight text-[#0B1C3F]">Modèles d'emails</h1>
          <p className="text-[15px] text-[#475569]">Vos emails types, personnalisés automatiquement pour chaque commerce, à réutiliser dans vos séquences.</p>
        </div>
        <div className="flex gap-2">
          {admin && status?.configured && <button type="button" onClick={() => setModal({ type: 'test' })} className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#DCE3EE] bg-white px-4 text-[13.5px] font-medium text-[#2F6BFF]"><Send size={16} /> Tester Gmail</button>}
          <button type="button" onClick={() => setModal({ type: 'edit', tpl: null })} className="inline-flex h-10 items-center gap-2 rounded-xl px-4 text-[13.5px] font-medium text-white" style={{ background: BLUE }}><Plus size={16} /> Nouveau modèle</button>
        </div>
      </header>
      <GmailBanner status={status} />

      <Card className="mb-4">
        <div className="grid gap-2 sm:grid-cols-[1.6fr_1fr]">
          <label className="relative"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            <input className={`${inputCls} pl-9`} placeholder="Rechercher un modèle, un objet…" value={q} onChange={(e) => setQ(e.target.value)} /></label>
          <Select value={cat} onChange={setCat}><option value="">Toutes les catégories</option>{d.categories.map((c) => <option key={c}>{c}</option>)}</Select>
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
        {rows.map((t) => { const [bg, fg] = toneOf(t.category || t.name); return (
          <Card key={t.id} className="flex flex-col">
            <div className="mb-2 flex items-start gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl" style={{ background: bg, color: fg }}><Mail size={18} /></span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[15px] font-bold text-[#0B1C3F]">{t.name}</p>
                <p className="text-[12px] text-[#64748B]">{t.category && <span className="mr-1.5 rounded px-1.5 py-0.5 font-medium" style={{ background: bg, color: fg }}>{t.category}</span>}par {t.created_by_name}</p>
              </div>
            </div>
            <p className="truncate text-[13px] font-medium text-[#334155]">Objet : {t.subject}</p>
            <p className="mt-1 line-clamp-4 flex-1 whitespace-pre-line text-[12.5px] text-[#64748B]">{t.body}</p>
            {t.unfinished && <p className="mt-2 flex items-center gap-1.5 rounded-lg bg-[#FFF4DB] px-2.5 py-1.5 text-[12px] text-[#92400E]"><AlertTriangle size={13} /> À compléter avant tout envoi</p>}
            <div className="mt-3 grid grid-cols-4 gap-1.5 text-center">
              {[['Envoyés', nf(t.uses)], ['Ouverture', `${t.open_rate}%`], ['Clic', `${t.click_rate}%`], ['Réponse', `${t.reply_rate}%`]].map(([k, v]) => (
                <p key={k} className="rounded-lg bg-[#F8FAFF] py-1.5"><strong className="block text-[13.5px] text-[#0B1C3F]">{t.uses || k === 'Envoyés' ? v : '—'}</strong><span className="text-[10.5px] text-[#64748B]">{k}</span></p>
              ))}
            </div>
            <div className="mt-3 flex gap-2">
              <button type="button" onClick={() => use(t)} className="flex-1 rounded-lg py-2 text-[12.5px] font-semibold text-white" style={{ background: BLUE }}>Utiliser dans une séquence</button>
              {mayEdit(t)
                ? <button type="button" aria-label="Modifier" onClick={() => setModal({ type: 'edit', tpl: t })} className="rounded-lg border border-[#DCE3EE] px-3 text-[#2F6BFF]"><Pencil size={14} /></button>
                : <button type="button" aria-label="Copier" title="Faire une copie à modifier" onClick={() => setModal({ type: 'edit', tpl: { ...t, id: null, name: `${t.name} (copie)` } })} className="rounded-lg border border-[#DCE3EE] px-3 text-[#2F6BFF]"><Copy size={14} /></button>}
              {mayEdit(t) && <button type="button" aria-label="Supprimer" onClick={() => { if (window.confirm(`Supprimer « ${t.name} » ? Les séquences gardent leur propre texte.`)) crmAPI.deleteEmailTemplate(t.id).then(() => { say('Modèle supprimé.'); load(); }).catch((e) => say(e?.response?.data?.detail || 'Suppression impossible.')); }} className="rounded-lg border border-[#FCA5A5] bg-[#FEF2F2] px-3 text-[#E11D48]"><Trash2 size={14} /></button>}
            </div>
            {t.steps > 0 && <p className="mt-2 text-[11.5px] text-[#94A3B8]">Utilisé dans {t.steps} séquence{t.steps > 1 ? 's' : ''}</p>}
          </Card>); })}
        {!rows.length && <Card className="py-12 text-center text-[13px] text-[#64748B] md:col-span-2 2xl:col-span-3">Aucun modèle ici.</Card>}
      </div>

      {toast}
      {modal?.type === 'edit' && <TemplateModal tpl={modal.tpl} variables={d.variables} categories={d.categories} onClose={() => setModal(null)} onSaved={() => { setModal(null); say('Modèle enregistré.'); load(); }} />}
      {modal?.type === 'test' && <TestModal email={user?.email} onClose={() => setModal(null)} onDone={(m) => { setModal(null); say(m); }} />}
    </div>
  );
}

function TemplateModal({ tpl, variables, categories, onClose, onSaved }) {
  const [f, setF] = useState({ name: tpl?.name || '', category: tpl?.category || '', subject: tpl?.subject || '', body: tpl?.body || '' });
  const [err, setErr] = useState('');
  const save = async () => {
    setErr('');
    try { if (tpl?.id) await crmAPI.editEmailTemplate(tpl.id, f); else await crmAPI.addEmailTemplate(f); onSaved(); }
    catch (e) { setErr(e?.response?.data?.detail || 'Enregistrement impossible.'); }
  };
  return (
    <Modal title={tpl?.id ? `Modifier — ${tpl.name}` : 'Nouveau modèle'} onClose={onClose} wide>
      <div className="mb-2 grid gap-2 sm:grid-cols-[1.5fr_1fr]">
        <label><span className="mb-1 block text-[11.5px] text-[#64748B]">Nom du modèle</span><input className={inputCls} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Ex. Relance après salon" /></label>
        <label><span className="mb-1 block text-[11.5px] text-[#64748B]">Catégorie</span><input className={inputCls} list="tpl-cats" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} placeholder="Ex. Relance" />
          <datalist id="tpl-cats">{categories.map((c) => <option key={c} value={c} />)}</datalist></label>
      </div>
      <EmailFields value={f} onChange={(v) => setF({ ...f, subject: v.subject, body: v.body })} variables={variables} />
      <p className="mt-2 text-[12px] text-[#64748B]">Les variables sont remplacées pour chaque commerce ; si une information manque (ex. pas de prénom), elle disparaît proprement. Mentions légales et désinscription sont ajoutées automatiquement.</p>
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{err}</p>}
      <button type="button" disabled={!f.name.trim() || !f.subject.trim() || !f.body.trim()} onClick={save} className="mt-3 w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>
        Enregistrer{unfinished(f.subject, f.body) ? ' (à compléter plus tard)' : ''}</button>
    </Modal>
  );
}

function TestModal({ email, onClose, onDone }) {
  const [to, setTo] = useState(email || '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const go = async () => {
    setBusy(true); setErr('');
    try { await crmAPI.emailTest(to); onDone(`Email de test envoyé à ${to}.`); }
    catch (e) { setErr(e?.response?.data?.detail || 'Envoi impossible.'); setBusy(false); }
  };
  return (
    <Modal title="Tester la connexion Gmail" onClose={onClose}>
      <p className="mb-2 text-[13px] text-[#475569]">Un email de test part du compte Gmail du CRM vers cette adresse.</p>
      <input className={inputCls} value={to} onChange={(e) => setTo(e.target.value)} />
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{err}</p>}
      <button type="button" disabled={busy || !to.includes('@')} onClick={go} className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>{busy && <Loader2 size={15} className="animate-spin" />} Envoyer le test</button>
    </Modal>
  );
}
