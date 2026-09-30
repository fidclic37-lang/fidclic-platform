import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, Eye, Loader2, Mail, Plus, Search, Send, Trash2, CheckCircle2, Info } from 'lucide-react';
import { crmAPI } from '../../lib/api';
import { Modal, Select, BLUE, inputCls, nf } from './ui';

/* Shared by Séquences, Modèles d'emails and the one-off « Envoyer un email ». */

export const SECTOR_TONES = [['#FDECEF', '#E11D48'], ['#FFF4DB', '#D97706'], ['#EAF1FF', '#2F6BFF'], ['#F3EEFF', '#7C3AED'],
  ['#E7F7EE', '#0F8B58'], ['#E0F2FE', '#0284C7'], ['#FCE7F3', '#DB2777'], ['#F1F5F9', '#475569']];
export const toneOf = (s) => SECTOR_TONES[[...(s || '')].reduce((a, c) => a + c.charCodeAt(0), 0) % SECTOR_TONES.length];
export const SectorPill = ({ s }) => {
  if (!s) return <span className="rounded-md bg-[#F1F5F9] px-2 py-1 text-[12px] text-[#475569]">Multi-secteurs</span>;
  const [bg, fg] = toneOf(s);
  return <span className="whitespace-nowrap rounded-md px-2 py-1 text-[12px] font-medium" style={{ background: bg, color: fg }}>{s}</span>;
};
export const SEQ_TONE = { active: ['#E7F7EE', '#0F8B58'], pause: ['#FFF4DB', '#D97706'], terminee: ['#EAF1FF', '#2F6BFF'], brouillon: ['#F1F5F9', '#475569'] };
export const SeqStatus = ({ s, label }) => {
  const [bg, fg] = SEQ_TONE[s] || SEQ_TONE.brouillon;
  return <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-1 text-[12px] font-medium" style={{ background: bg, color: fg }}><i className="h-1.5 w-1.5 rounded-full" style={{ background: fg }} />{label}</span>;
};
const TO_FILL = /\[[^\]]*compl[ée]ter[^\]]*\]/i;
export const unfinished = (...t) => t.some((x) => TO_FILL.test(x || ''));

/* Gmail not connected, or refusing the password: said plainly, with the fix. */
export function GmailBanner({ status, onRun, running }) {
  if (!status) return null;
  if (!status.configured) {
    return (
      <div className="mb-4 flex gap-3 rounded-2xl border border-[#FDE68A] bg-[#FFFBEB] p-4 text-[13px] text-[#92400E]">
        <AlertTriangle size={18} className="mt-0.5 shrink-0" />
        <div>
          <p className="font-semibold">Gmail n'est pas encore connecté : aucun email ne part pour l'instant.</p>
          <p className="mt-1">Dans Vercel › Settings › Environment Variables, ajoutez <code>CRM_SMTP_USER</code> (l'adresse Gmail qui envoie) et <code>CRM_SMTP_PASS</code> (son mot de passe d'application : compte Google › Sécurité › Validation en deux étapes › Mots de passe des applications), puis redéployez. Vous pouvez déjà préparer vos séquences.</p>
        </div>
      </div>
    );
  }
  return (
    <div className={`mb-4 flex flex-wrap items-center gap-3 rounded-2xl border px-4 py-2.5 text-[12.5px] ${status.error ? 'border-[#FCA5A5] bg-[#FEF2F2] text-[#B91C1C]' : 'border-[#E6EEFB] bg-white text-[#475569]'}`}>
      {status.error ? <AlertTriangle size={15} /> : <CheckCircle2 size={15} className="text-[#10B981]" />}
      <span className="flex-1">{status.error || <>Envoi depuis <strong className="text-[#0B1C3F]">{status.sender}</strong> · {nf(status.sent_today)} / {nf(status.daily_limit)} emails aujourd'hui{status.replies_error ? ' · lecture des réponses impossible' : ''}</>}</span>
      {onRun && <button type="button" disabled={running} onClick={onRun} className="inline-flex items-center gap-1.5 text-[#2F6BFF] disabled:opacity-50">{running ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />} Envoyer maintenant les emails prévus</button>}
    </div>
  );
}

/* Subject + text with clickable variables, and a preview as the prospect will see it. */
export function EmailFields({ value, onChange, variables = [], prospectId, compact }) {
  const bodyRef = useRef(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const insert = (key) => {
    const el = bodyRef.current; const tag = `{${key}}`;
    if (!el) { onChange({ ...value, body: `${value.body}${tag}` }); return; }
    const a = el.selectionStart ?? value.body.length; const b = el.selectionEnd ?? a;
    onChange({ ...value, body: value.body.slice(0, a) + tag + value.body.slice(b) });
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(a + tag.length, a + tag.length); });
  };
  const show = async () => {
    setBusy(true);
    try { const { data } = await crmAPI.emailPreview({ subject: value.subject, body: value.body, prospect_id: prospectId || null }); setPreview(data); }
    catch { setPreview(null); }
    setBusy(false);
  };
  useEffect(() => { setPreview(null); }, [value.subject, value.body]);
  return (
    <div className="space-y-2">
      <input className={inputCls} placeholder="Objet de l'email" value={value.subject} onChange={(e) => onChange({ ...value, subject: e.target.value })} />
      <textarea ref={bodyRef} className={`${inputCls} ${compact ? 'h-36' : 'h-52'} py-2 leading-relaxed`} placeholder="Texte de l'email" value={value.body} onChange={(e) => onChange({ ...value, body: e.target.value })} />
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11.5px] text-[#64748B]">Insérer :</span>
        {variables.map((v) => <button key={v.key} type="button" title={v.label} onClick={() => insert(v.key)} className="rounded-md bg-[#EAF1FF] px-2 py-0.5 text-[11.5px] font-medium text-[#2F6BFF]">{`{${v.key}}`}</button>)}
        <button type="button" onClick={show} disabled={busy || !value.body} className="ml-auto inline-flex items-center gap-1 text-[12px] text-[#2F6BFF] disabled:opacity-40">{busy ? <Loader2 size={12} className="animate-spin" /> : <Eye size={13} />} Aperçu</button>
      </div>
      {unfinished(value.subject, value.body) && <p className="flex items-center gap-1.5 rounded-lg bg-[#FFF4DB] px-2.5 py-1.5 text-[12px] text-[#92400E]"><AlertTriangle size={13} /> Remplacez les passages [À COMPLÉTER] : ils ne peuvent pas être envoyés tels quels.</p>}
      {preview && (
        <div className="overflow-hidden rounded-xl border border-[#E6EEFB]">
          <p className="border-b border-[#EDF1F7] bg-[#F8FAFF] px-3 py-2 text-[12px] text-[#475569]">Aperçu pour <strong>{preview.prospect}</strong> · Objet : <strong className="text-[#0B1C3F]">{preview.subject}</strong></p>
          <iframe title="Aperçu de l'email" sandbox="" srcDoc={preview.html} className="h-72 w-full bg-white" />
        </div>
      )}
    </div>
  );
}

const newStep = (day) => ({ key: Math.random().toString(36).slice(2), day, time: '09:00', subject: '', body: '', template_id: null });

export function SequenceEditor({ seq, meta, templates, variables, focus, onClose, onSaved }) {
  const [f, setF] = useState({ name: seq?.name || '', sector: seq?.sector || '', target: seq?.target || '', stop_on_reply: seq?.stop_on_reply ?? true });
  const [steps, setSteps] = useState(() => (seq?.steps?.length ? seq.steps.map((s) => ({ ...s, key: s.id })) : [newStep(1)]).concat(focus === 'new' && seq?.steps?.length ? [newStep((seq.steps.at(-1)?.day || 1) + 3)] : []));
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const refs = useRef({});
  useEffect(() => {
    const k = focus === 'new' ? steps.at(-1)?.key : typeof focus === 'number' ? steps[focus]?.key : null;
    if (k) setTimeout(() => refs.current[k]?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 100);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const put = (i, patch) => setSteps(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const applyTpl = (i, id) => { const t = templates.find((x) => x.id === id); if (t) put(i, { template_id: id, subject: t.subject, body: t.body }); };
  const save = async () => {
    setErr(''); setBusy(true);
    const body = { ...f, steps: steps.map(({ key, id, day, time, subject, body: b, template_id }) => ({ id: id || undefined, day: Number(day) || 1, time, subject, body: b, template_id })) };
    try {
      const { data } = seq?.id ? await crmAPI.editSequence(seq.id, body) : await crmAPI.addSequence(body);
      onSaved(data);
    } catch (e) { setErr(e?.response?.data?.detail || 'Enregistrement impossible.'); }
    setBusy(false);
  };
  return (
    <Modal title={seq?.id ? `Modifier — ${seq.name}` : 'Nouvelle séquence d\'emails'} onClose={onClose} wide>
      <div className="grid gap-2 sm:grid-cols-[1.4fr_1fr_1.4fr]">
        <label><span className="mb-1 block text-[11.5px] text-[#64748B]">Nom de la séquence</span><input className={inputCls} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Ex. Restauration — Prise de contact" /></label>
        <Select label="Secteur cible" value={f.sector} onChange={(v) => setF({ ...f, sector: v })}><option value="">Multi-secteurs</option>{[...new Set([...(meta?.sectors || []), ...(f.sector ? [f.sector] : [])])].map((s) => <option key={s}>{s}</option>)}</Select>
        <label><span className="mb-1 block text-[11.5px] text-[#64748B]">Cible (description)</span><input className={inputCls} value={f.target} onChange={(e) => setF({ ...f, target: e.target.value })} placeholder="Ex. Restaurants à Tours" /></label>
      </div>
      <label className="mt-2 flex items-center gap-2 text-[13px] text-[#334155]"><input type="checkbox" checked={f.stop_on_reply} onChange={(e) => setF({ ...f, stop_on_reply: e.target.checked })} className="accent-[#2F6BFF]" /> Arrêter la séquence dès qu'un prospect répond</label>
      <div className="mt-4 space-y-3">
        {steps.map((s, i) => (
          <section key={s.key} ref={(el) => { refs.current[s.key] = el; }} className="rounded-2xl border border-[#E6EEFB] p-3">
            <header className="mb-2 flex flex-wrap items-center gap-2">
              <span className="grid h-7 w-7 place-items-center rounded-full bg-[#EAF1FF] text-[12.5px] font-bold text-[#2F6BFF]">{i + 1}</span>
              <span className="text-[12.5px] text-[#475569]">Jour</span>
              <input type="number" min={1} max={365} value={s.day} onChange={(e) => put(i, { day: e.target.value })} className="h-8 w-16 rounded-lg border border-[#DCE3EE] px-2 text-[13px]" />
              <span className="text-[12.5px] text-[#475569]">à</span>
              <input type="time" value={s.time} onChange={(e) => put(i, { time: e.target.value })} className="h-8 rounded-lg border border-[#DCE3EE] px-2 text-[13px]" />
              <select value={s.template_id || ''} onChange={(e) => applyTpl(i, e.target.value)} className="h-8 min-w-0 flex-1 rounded-lg border border-[#DCE3EE] px-2 text-[12.5px]">
                <option value="">Partir d'un modèle…</option>{templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
              {steps.length > 1 && <button type="button" aria-label="Supprimer l'étape" onClick={() => setSteps(steps.filter((_, j) => j !== i))} className="text-[#94A3B8] hover:text-[#E11D48]"><Trash2 size={15} /></button>}
            </header>
            <EmailFields compact value={s} onChange={(v) => put(i, { subject: v.subject, body: v.body })} variables={variables} />
          </section>
        ))}
        <button type="button" onClick={() => setSteps([...steps, newStep((Number(steps.at(-1)?.day) || 1) + 3)])} className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-[#BFD3FF] py-2.5 text-[13px] text-[#2F6BFF]"><Plus size={15} /> Ajouter une étape</button>
      </div>
      <p className="mt-3 flex items-start gap-1.5 text-[12px] text-[#64748B]"><Info size={13} className="mt-0.5 shrink-0" /> Les jours comptent à partir de l'inscription du prospect dans la séquence ; les heures sont celles de Paris. Chaque email porte automatiquement vos mentions légales et un lien de désinscription.</p>
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{err}</p>}
      <button type="button" disabled={busy || !f.name.trim()} onClick={save} className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>{busy && <Loader2 size={15} className="animate-spin" />} Enregistrer</button>
    </Modal>
  );
}

const WHY = { added: 'seront ajoutés', no_email: 'sans email', opted_out: 'désinscrits', clients: 'déjà clients', lost: 'perdus', already: 'déjà dans cette séquence', other_sequence: 'dans une autre séquence en cours' };

export function EnrollModal({ seq, meta, onClose, onDone }) {
  const [mode, setMode] = useState('filter');
  const [f, setF] = useState({ sector: seq.sector || '', city: '', stage: '' });
  const [dry, setDry] = useState(null);
  const [q, setQ] = useState('');
  const [found, setFound] = useState([]);
  const [picked, setPicked] = useState([]);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const body = mode === 'filter' ? f : { prospect_ids: picked.map((p) => p.id) };
  const ready = mode === 'filter' ? (f.sector || f.city || f.stage) : picked.length;
  useEffect(() => {
    setDry(null);
    if (!ready) return undefined;
    const t = setTimeout(() => crmAPI.enroll(seq.id, { ...body, dry_run: true }).then(({ data }) => setDry(data)).catch(() => {}), 250);
    return () => clearTimeout(t);
  }, [mode, f, picked]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (q.length < 2) { setFound([]); return; }
    crmAPI.prospects({ q, per_page: 8 }).then(({ data }) => setFound(data.rows)).catch(() => {});
  }, [q]);
  const go = async () => {
    setBusy(true); setErr('');
    try { const { data } = await crmAPI.enroll(seq.id, body); onDone(`${data.added} prospect${data.added > 1 ? 's' : ''} ajouté${data.added > 1 ? 's' : ''} à la séquence.`); }
    catch (e) { setErr(e?.response?.data?.detail || 'Ajout impossible.'); setBusy(false); }
  };
  return (
    <Modal title={`Ajouter des prospects — ${seq.name}`} onClose={onClose}>
      <nav className="mb-3 flex gap-1 rounded-xl bg-[#F4F7FC] p-1 text-[13px]">
        {[['filter', 'Par filtre'], ['pick', 'Un par un']].map(([k, l]) => <button key={k} type="button" onClick={() => setMode(k)} className={`flex-1 rounded-lg py-1.5 ${mode === k ? 'bg-white font-semibold text-[#2F6BFF] shadow-sm' : 'text-[#475569]'}`}>{l}</button>)}
      </nav>
      {mode === 'filter' ? (
        <div className="grid gap-2 sm:grid-cols-3">
          <Select label="Secteur" value={f.sector} onChange={(v) => setF({ ...f, sector: v })}><option value="">Tous</option>{(meta?.sectors || []).map((s) => <option key={s}>{s}</option>)}</Select>
          <Select label="Ville" value={f.city} onChange={(v) => setF({ ...f, city: v })}><option value="">Toutes</option>{(meta?.cities || []).map((s) => <option key={s}>{s}</option>)}</Select>
          <Select label="Étape" value={f.stage} onChange={(v) => setF({ ...f, stage: v })}><option value="">Toutes</option>{(meta?.stages || []).filter((s) => !['essai', 'signe', 'perdu'].includes(s.key)).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</Select>
        </div>
      ) : (
        <div>
          <label className="relative block"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" /><input className={`${inputCls} pl-9`} placeholder="Chercher un commerce…" value={q} onChange={(e) => setQ(e.target.value)} /></label>
          {found.filter((p) => !picked.some((x) => x.id === p.id)).map((p) => <button key={p.id} type="button" onClick={() => setPicked([...picked, p])} className="block w-full px-2 py-1.5 text-left text-[13px] hover:bg-[#F4F7FC]">{p.name} <span className="text-[#94A3B8]">{p.city} {p.email ? `· ${p.email}` : '· pas d\'email'}</span></button>)}
          <div className="mt-2 flex flex-wrap gap-1.5">{picked.map((p) => <span key={p.id} className="inline-flex items-center gap-1 rounded-full bg-[#EAF1FF] px-2.5 py-1 text-[12px] text-[#2F6BFF]">{p.name}<button type="button" aria-label="Retirer" onClick={() => setPicked(picked.filter((x) => x.id !== p.id))}>×</button></span>)}</div>
        </div>
      )}
      <div className="mt-3 min-h-[48px] rounded-xl bg-[#F8FAFF] p-3 text-[13px]">
        {!ready ? <span className="text-[#64748B]">Choisissez un filtre ou des commerces.</span> : !dry ? <Loader2 size={14} className="animate-spin text-[#94A3B8]" /> : (
          <>
            <p><strong className="text-[18px] text-[#0F8B58]">{nf(dry.added)}</strong> <span className="text-[#334155]">prospect{dry.added > 1 ? 's' : ''} {WHY.added}</span></p>
            <p className="mt-1 text-[12px] text-[#64748B]">{Object.entries(dry).filter(([k, v]) => k !== 'added' && v).map(([k, v]) => `${v} ${WHY[k]}`).join(' · ') || 'Aucun écarté.'}</p>
          </>
        )}
      </div>
      {seq.status !== 'active' && <p className="mt-2 text-[12px] text-[#92400E]">La séquence n'est pas active : les emails partiront quand vous l'activerez.</p>}
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{err}</p>}
      <button type="button" disabled={busy || !dry?.added} onClick={go} className="mt-3 w-full rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>Ajouter {dry?.added ? nf(dry.added) : ''} prospect{dry?.added > 1 ? 's' : ''}</button>
    </Modal>
  );
}

/* One e-mail to one business, from its call or its card. */
export function ComposeEmail({ prospect, onClose, onSent, initial }) {
  const [status, setStatus] = useState(null);
  const [tpls, setTpls] = useState({ rows: [], variables: [] });
  const [v, setV] = useState({ subject: initial?.subject || '', body: initial?.body || '', template_id: null });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    crmAPI.emailStatus().then(({ data }) => setStatus(data)).catch(() => {});
    crmAPI.emailTemplates().then(({ data }) => setTpls(data)).catch(() => {});
  }, []);
  const send = async () => {
    setErr(''); setBusy(true);
    try { await crmAPI.emailSend({ prospect_id: prospect.id, ...v }); onSent('Email envoyé.'); }
    catch (e) { setErr(e?.response?.data?.detail || 'Envoi impossible.'); setBusy(false); }
  };
  return (
    <Modal title={`Email à ${prospect.name}`} onClose={onClose} wide>
      <GmailBanner status={status} />
      <p className="mb-2 flex items-center gap-2 text-[13px] text-[#334155]"><Mail size={14} className="text-[#2F6BFF]" /> À : <strong>{prospect.email}</strong></p>
      <select value={v.template_id || ''} onChange={(e) => { const t = tpls.rows.find((x) => x.id === e.target.value); setV(t ? { subject: t.subject, body: t.body, template_id: t.id } : { ...v, template_id: null }); }} className={`${inputCls} mb-2`}>
        <option value="">Partir d'un modèle…</option>{tpls.rows.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
      </select>
      <EmailFields value={v} onChange={(x) => setV({ ...v, ...x })} variables={tpls.variables} prospectId={prospect.id} />
      {err && <p className="mt-2 text-[13px] text-[#C0392B]">{err}</p>}
      <button type="button" disabled={busy || !status?.configured || !v.subject.trim() || !v.body.trim() || unfinished(v.subject, v.body)} onClick={send}
              className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>{busy ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />} Envoyer</button>
      <p className="mt-2 text-center text-[11.5px] text-[#94A3B8]">Envoyé depuis votre Gmail, avec vos mentions légales et un lien de désinscription. <Link to="/admin/crm/modeles" className="text-[#2F6BFF]">Gérer les modèles</Link></p>
    </Modal>
  );
}
