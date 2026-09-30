import React, { useEffect, useRef, useState } from 'react';
import { UploadCloud, FileText, Loader2, Check, UserPlus, Copy, Power } from 'lucide-react';
import { crmAPI } from '../../lib/api';
import { Modal, StageBadge, inputCls, Select, nf, BLUE } from './ui';

/* Import: a file of any usual kind (CSV, Excel, PDF, Word, TXT, MD, JSON…
   — read without any language model), a
   preview of what each row becomes (created / updated, and the stage it
   gets — a business on FidClic takes its real one), then « Importer ». */
export function ImportModal({ meta, onClose, onDone }) {
  const input = useRef(null);
  const [file, setFile] = useState(null);
  const [prev, setPrev] = useState(null);
  const [keep, setKeep] = useState({});
  const [source, setSource] = useState('import');
  const [assign, setAssign] = useState('');
  const [city, setCity] = useState('');
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');

  const read = async (f) => {
    setFile(f); setErr(''); setPrev(null); setBusy('read');
    try {
      const { data } = await crmAPI.importPreview(f);
      setPrev(data); setKeep(Object.fromEntries(data.rows.map((_, i) => [i, true]))); setCity(data.suggested_city || '');
    } catch (e) { setErr(e?.response?.data?.detail || 'Fichier illisible.'); }
    finally { setBusy(''); }
  };
  const commit = async () => {
    setBusy('commit'); setErr('');
    try {
      const rows = prev.rows.filter((_, i) => keep[i]);
      const { data } = await crmAPI.importCommit({ rows, source, assign_to: assign || null, filename: file?.name, default_city: city || null });
      onDone(`${nf(data.created)} ajouté(s), ${nf(data.updated)} mis à jour${data.linked ? `, ${nf(data.linked)} relié(s) à FidClic` : ''}.`);
    } catch (e) { setErr(e?.response?.data?.detail || "L'import n'a pas abouti."); setBusy(''); }
  };
  const n = prev ? prev.rows.filter((_, i) => keep[i]).length : 0;

  return (
    <Modal title="Importer des commerces" onClose={onClose} wide>
      {!prev ? (
        <div>
          <button type="button" onClick={() => input.current?.click()}
                  onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files[0]) read(e.dataTransfer.files[0]); }}
                  className="flex w-full flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-[#C9D6EA] bg-[#F8FAFF] px-6 py-12 text-center hover:border-[#2F6BFF]">
            {busy === 'read' ? <Loader2 size={30} className="animate-spin text-[#2F6BFF]" /> : <UploadCloud size={34} className="text-[#2F6BFF]" />}
            <span className="text-[15px] font-semibold text-[#0B1C3F]">{busy === 'read' ? 'Lecture du fichier…' : 'Déposez un fichier ou cliquez pour choisir'}</span>
            <span className="text-[12.5px] text-[#64748B]">Excel (XLSX, XLS), CSV, PDF, Word (DOCX), LibreOffice (ODS, ODT), TXT, MD, JSON, HTML, vCard — 8 Mo maximum</span>
          </button>
          <input ref={input} type="file" accept=".csv,.tsv,.txt,.md,.markdown,.pdf,.xlsx,.xlsm,.xls,.ods,.odt,.docx,.json,.html,.htm,.vcf,.rtf,text/*,application/pdf,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.oasis.opendocument.spreadsheet" className="hidden" onChange={(e) => { if (e.target.files[0]) read(e.target.files[0]); e.target.value = ''; }} />
          <ul className="mt-4 space-y-1.5 text-[12.5px] text-[#475569]">
            <li>• <strong>Tableaux</strong> (Excel, CSV, PDF, Word, Markdown…) : colonnes reconnues par leur titre — Commerce / Établissement / Restaurant, Secteur / Segment, Adresse, Ville, Code postal, Contact, Téléphone, Email, SIRET, Statut… Plusieurs tableaux dans un fichier : tous sont lus, même sur plusieurs pages.</li>
            <li>• <strong>Texte libre</strong> (TXT, MD, PDF) : un commerce par bloc ; e-mails, téléphones, SIRET, codes postaux et liens sont repérés automatiquement.</li>
            <li>• Un commerce <strong>présent deux fois dans le fichier</strong> n'est importé qu'une fois.</li>
            <li>• Un commerce <strong>déjà inscrit sur FidClic</strong> prend son vrai statut (en essai, signé…). Un commerce déjà présent est mis à jour, jamais dupliqué.</li>
          </ul>
          {err && <p className="mt-3 text-[13px] text-[#C0392B]">{err}</p>}
        </div>
      ) : (
        <div>
          <div className="mb-3 flex flex-wrap items-end gap-3">
            <p className="text-[13.5px] text-[#0B1C3F]"><span className="flex items-center gap-2"><FileText size={16} className="text-[#2F6BFF]" /> {file?.name} — <strong>{nf(prev.total)} commerce(s)</strong> reconnu(s)</span>
              {prev.duplicates_in_file > 0 && <span className="mt-0.5 block text-[12px] text-[#64748B]">{nf(prev.duplicates_in_file)} doublon(s) dans le fichier fusionné(s)</span>}</p>
            <label className="w-48"><span className="mb-1 block text-[11.5px] text-[#64748B]">Ville par défaut{prev.no_city ? ` (${nf(prev.no_city)} sans ville)` : ''}</span>
              <input className={inputCls} value={city} onChange={(e) => setCity(e.target.value)} placeholder="Ex. Tours" /></label>
            <Select label="Source" value={source} onChange={setSource} className="ml-auto w-44">
              {(meta?.sources || []).filter((s) => s.key !== 'inscription').map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </Select>
            <Select label="Assigner à" value={assign} onChange={setAssign} className="w-48">
              <option value="">Personne</option>
              {(meta?.users || []).filter((u) => u.active).map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}
            </Select>
          </div>
          <div className="max-h-[50vh] overflow-auto rounded-xl border border-[#EDF1F7]">
            <table className="w-full min-w-[860px] text-[12.5px]">
              <thead className="sticky top-0 bg-[#F8FAFF] text-left text-[#64748B]">
                <tr><th className="w-8 px-2 py-2"><input type="checkbox" checked={n === prev.rows.length} onChange={(e) => setKeep(Object.fromEntries(prev.rows.map((_, i) => [i, e.target.checked])))} /></th>
                  {['Commerce', 'Secteur', 'Adresse · Ville', 'Contact', 'Téléphone', 'Email', 'Statut', 'Action'].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr>
              </thead>
              <tbody>
                {prev.rows.map((r, i) => (
                  <tr key={i} className={`border-t border-[#F1F5F9] ${keep[i] ? '' : 'opacity-40'}`}>
                    <td className="px-2 py-2"><input type="checkbox" checked={!!keep[i]} onChange={(e) => setKeep({ ...keep, [i]: e.target.checked })} /></td>
                    <td className="px-2 py-2 font-medium text-[#0B1C3F]">{r.name}</td>
                    <td className="px-2 py-2 text-[#475569]">{r.sector || '—'}</td>
                    <td className="px-2 py-2 text-[#475569]">
                      {r.address || '—'}
                      <span className="block text-[11.5px]">{r.city ? [r.postal_code, r.city].filter(Boolean).join(' ') : city ? <span className="text-[#94A3B8]">{city} (par défaut)</span> : ''}</span>
                    </td>
                    <td className="px-2 py-2 text-[#475569]">{r.contact_name || '—'}</td>
                    <td className="px-2 py-2 text-[#475569]">{r.phone || '—'}</td>
                    <td className="px-2 py-2 text-[#475569]">{r.email || '—'}</td>
                    <td className="px-2 py-2"><StageBadge stage={r.stage} label={r.stage_label} /></td>
                    <td className="px-2 py-2 text-[11.5px] text-[#64748B]">{r.action === 'create' ? 'Ajout' : 'Mise à jour'} · {r.why}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {err && <p className="mt-3 text-[13px] text-[#C0392B]">{err}</p>}
          <div className="mt-4 flex justify-between gap-2">
            <button type="button" onClick={() => { setPrev(null); setFile(null); }} className="rounded-lg border border-[#DCE3EE] px-4 py-2.5 text-[13.5px]">Autre fichier</button>
            <button type="button" disabled={!n || busy === 'commit'} onClick={commit}
                    className="inline-flex items-center gap-2 rounded-lg px-5 py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>
              {busy === 'commit' ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} Importer {nf(n)} commerce(s)
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

/* Add or edit a prospect. */
export function ProspectModal({ meta, prospect, onClose, onSaved }) {
  const [f, setF] = useState(() => ({
    name: '', sector: '', city: '', postal_code: '', address: '', contact_name: '', contact_role: '', phone: '', email: '',
    website: '', instagram: '', facebook: '', siret: '', source: 'google', assigned_to: '', stage: 'nouveau',
    ...(prospect || {}), assigned_to: prospect?.assigned_to || '',
  }));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const set = (k) => (e) => setF({ ...f, [k]: e.target ? e.target.value : e });
  const save = async () => {
    setBusy(true); setErr('');
    const body = { ...f, assigned_to: f.assigned_to || null };
    ['id', 'ref', 'stage_label', 'source_label', 'assigned_name', 'on_fidclic', 'tenant_id', 'next_action', 'last_action',
     'last_activity_at', 'created_at', 'notes', 'activities', 'tasks', 'fidclic', 'lost_reason'].forEach((k) => delete body[k]);
    if (prospect?.id) delete body.stage;
    try {
      const { data } = prospect?.id ? await crmAPI.editProspect(prospect.id, body) : await crmAPI.addProspect(body);
      onSaved(data, prospect?.id ? 'Prospect enregistré.' : 'Prospect ajouté.');
    } catch (e) { setErr(e?.response?.data?.detail || "L'enregistrement n'a pas abouti."); setBusy(false); }
  };
  const field = (k, label, props = {}) => (
    <label className="block"><span className="mb-1 block text-[12px] text-[#475569]">{label}</span>
      <input className={inputCls} value={f[k] || ''} onChange={set(k)} {...props} /></label>
  );
  return (
    <Modal title={prospect?.id ? prospect.name : 'Ajouter un prospect'} onClose={onClose}>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">{field('name', 'Nom du commerce *')}</div>
        <label className="block"><span className="mb-1 block text-[12px] text-[#475569]">Secteur</span>
          <input className={inputCls} list="crm-sectors" value={f.sector || ''} onChange={set('sector')} />
          <datalist id="crm-sectors">{(meta?.sectors || []).map((s) => <option key={s} value={s} />)}</datalist></label>
        {field('siret', 'SIRET')}
        {field('address', 'Adresse')}
        <div className="grid grid-cols-[1fr_1.4fr] gap-2">{field('postal_code', 'Code postal')}{field('city', 'Ville')}</div>
        {field('contact_name', 'Contact')}{field('contact_role', 'Fonction')}
        {field('phone', 'Téléphone')}{field('email', 'Email', { type: 'email' })}
        {field('website', 'Site web')}{field('instagram', 'Instagram')}
        <Select label="Source" value={f.source} onChange={(v) => setF({ ...f, source: v })}>
          {(meta?.sources || []).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
        </Select>
        <Select label="Assigné à" value={f.assigned_to} onChange={(v) => setF({ ...f, assigned_to: v })}>
          <option value="">Personne</option>
          {(meta?.users || []).filter((u) => u.active).map((u) => <option key={u.email} value={u.email}>{u.name}</option>)}
        </Select>
        {!prospect?.id && (
          <Select label="Étape" value={f.stage} onChange={(v) => setF({ ...f, stage: v })}>
            {(meta?.stages || []).filter((s) => !['essai', 'signe', 'perdu'].includes(s.key)).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </Select>
        )}
      </div>
      {err && <p className="mt-3 text-[13px] text-[#C0392B]">{err}</p>}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-lg border border-[#DCE3EE] px-4 py-2.5 text-[13.5px]">Annuler</button>
        <button type="button" disabled={busy || !f.name.trim()} onClick={save}
                className="inline-flex items-center gap-2 rounded-lg px-5 py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} Enregistrer
        </button>
      </div>
    </Modal>
  );
}

/* The sales team — super admin only. */
export function TeamModal({ onClose, onChanged }) {
  const [rows, setRows] = useState(null);
  const [f, setF] = useState({ email: '', first_name: '', last_name: '' });
  const [cred, setCred] = useState(null);
  const [err, setErr] = useState('');
  const load = () => crmAPI.team().then(({ data }) => setRows(data.members)).catch(() => setRows([]));
  useEffect(() => { load(); }, []);
  const add = async () => {
    setErr('');
    try { const { data } = await crmAPI.addMember(f); setCred(data.credentials); setF({ email: '', first_name: '', last_name: '' }); load(); onChanged?.(); }
    catch (e) { setErr(e?.response?.data?.detail || 'Création impossible.'); }
  };
  return (
    <Modal title="Équipe commerciale" onClose={onClose}>
      <p className="mb-3 text-[12.5px] text-[#64748B]">Un compte « Commercial » voit uniquement le CRM de prospection.</p>
      <ul className="mb-4 divide-y divide-[#F1F5F9]">
        {(rows || []).map((m) => (
          <li key={m.email} className="flex items-center gap-3 py-2">
            <div className="min-w-0 flex-1"><p className="text-[13.5px] text-[#0B1C3F]">{m.name} <span className="text-[11.5px] text-[#94A3B8]">{m.role === 'super_admin' ? 'Super admin' : 'Commercial'}</span></p>
              <p className="truncate text-[12px] text-[#64748B]">{m.email} · {nf(m.prospects)} prospect(s)</p></div>
            {m.role === 'commercial' && (
              <button type="button" onClick={() => crmAPI.memberStatus(m.email, !m.active).then(() => { load(); onChanged?.(); })}
                      className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-[12px] ${m.active ? 'border-[#FCA5A5] text-[#E11D48]' : 'border-[#86EFAC] text-[#0F8B58]'}`}>
                <Power size={12} /> {m.active ? 'Désactiver' : 'Réactiver'}
              </button>
            )}
          </li>
        ))}
      </ul>
      {cred ? (
        <div className="space-y-2 rounded-xl bg-[#F4F7FC] p-3">
          <p className="text-[13px] text-[#0B1C3F]">Compte créé. Transmettez ces identifiants — ils ne seront plus affichés.</p>
          <p className="font-mono text-[13px]">{cred.email}<br />{cred.password}</p>
          <button type="button" onClick={() => navigator.clipboard?.writeText(`${cred.email}\n${cred.password}`)} className="inline-flex items-center gap-1.5 rounded-lg border border-[#DCE3EE] bg-white px-3 py-1.5 text-[12.5px]"><Copy size={13} /> Copier</button>
          <button type="button" onClick={() => setCred(null)} className="ml-2 text-[12.5px] text-[#2F6BFF]">Ajouter un autre</button>
        </div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          <input className={inputCls} placeholder="Prénom" value={f.first_name} onChange={(e) => setF({ ...f, first_name: e.target.value })} />
          <input className={inputCls} placeholder="Nom" value={f.last_name} onChange={(e) => setF({ ...f, last_name: e.target.value })} />
          <input className={`${inputCls} sm:col-span-2`} placeholder="email@fidclic.com" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
          {err && <p className="text-[13px] text-[#C0392B] sm:col-span-2">{err}</p>}
          <button type="button" disabled={!f.email} onClick={add}
                  className="inline-flex items-center justify-center gap-2 rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50 sm:col-span-2" style={{ background: BLUE }}>
            <UserPlus size={15} /> Créer le compte commercial
          </button>
        </div>
      )}
    </Modal>
  );
}
