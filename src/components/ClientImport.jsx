import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Upload, FileSpreadsheet, X, Loader2, Check, Mail, Download, AlertTriangle, Info, RefreshCw,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';

/**
 * Clients › Importer — and the invitation emails that follow (user, 2026-10-02).
 *
 * ImportModal: pick a CSV or Excel file → see, line by line, what will happen
 * (new card, already a client, twice in the file, not usable) → confirm the
 * clients agreed, choose whether to email them their card → done. The server
 * re-checks everything (features/client_import.py); this page only shows.
 *
 * InvitationsPanel: how the invitations are doing, the month's email quota,
 * and the relance — prepared for the clients who have not opened their card a
 * week later, sent only when the owner says so.
 */
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');
const BADGE = {
  new: { bg: '#E7F7EE', fg: '#0F8B58' },
  existing: { bg: '#EAF1FF', fg: '#1D4ED8' },
  duplicate: { bg: '#FFF7E6', fg: '#B45309' },
  invalid: { bg: '#FEECEC', fg: '#C0392B' },
};
const TEMPLATE = 'Prénom;Nom;Email;Téléphone;Date de naissance;Code postal\r\nMarie;Dupont;marie.dupont@exemple.fr;0612345678;17/05/1990;37000\r\n';

const Modal = ({ title, sub, onClose, children, footer, wide }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0B1C3F]/40 p-4" onClick={onClose}>
    <div role="dialog" aria-modal="true"
         className={`flex max-h-[90vh] w-full flex-col rounded-2xl bg-white shadow-[0_30px_70px_-30px_rgba(11,28,63,.6)] ${wide ? 'max-w-3xl' : 'max-w-lg'}`}
         onClick={(e) => e.stopPropagation()}>
      <div className="flex items-start justify-between gap-3 border-b border-[#EEF3FB] p-5">
        <div>
          <h3 className="text-[16px] font-bold text-[#0B1C3F]">{title}</h3>
          {sub && <p className="mt-0.5 text-[12.5px] text-[#64748B]">{sub}</p>}
        </div>
        <button type="button" onClick={onClose} aria-label="Fermer" className="text-[#94A3B8] hover:text-[#334155]"><X size={18} /></button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
      {footer && <div className="flex flex-wrap items-center justify-end gap-2 border-t border-[#EEF3FB] p-5">{footer}</div>}
    </div>
  </div>
);

const Btn = ({ primary, children, ...p }) => (
  <button type="button" {...p}
          className={primary
            ? 'inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white transition hover:bg-[#2559DB] disabled:opacity-50'
            : 'inline-flex items-center gap-2 rounded-xl border border-[#E6EEFB] bg-white px-4 py-2.5 text-[13px] font-semibold text-[#334155] transition hover:border-[#BFD3FF] disabled:opacity-50'}>
    {children}
  </button>
);

const Box = ({ tone = 'blue', icon: Icon = Info, children }) => {
  const t = { blue: ['#EFF5FF', '#1E4FD8'], amber: ['#FFF7E6', '#B45309'], red: ['#FEECEC', '#C0392B'], green: ['#E7F7EE', '#0F8B58'] }[tone];
  return (
    <p className="mb-3 flex items-start gap-2 rounded-xl px-3 py-2.5 text-[12.5px] leading-snug" style={{ background: t[0], color: t[1] }}>
      <Icon size={14} className="mt-px shrink-0" /> <span>{children}</span>
    </p>
  );
};

const quotaText = (l) => (l.invites_limit == null ? 'sans limite' : `${nf(l.invites_left)} sur ${nf(l.invites_limit)} restants ce mois`);

/* ── import ─────────────────────────────────────────────────────────────── */
export function ImportModal({ onClose, onDone }) {
  const [step, setStep] = useState('file');          // file → preview → done
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [p, setP] = useState(null);
  const [filter, setFilter] = useState('all');
  const [invite, setInvite] = useState(true);
  const [consent, setConsent] = useState(false);
  const [result, setResult] = useState(null);
  const input = useRef(null);
  const [drag, setDrag] = useState(false);

  const read = async (file) => {
    if (!file) return;
    setBusy(true); setErr('');
    try {
      const { data } = await ownerAPI.clientsImportPreview(file);
      setP({ ...data, filename: file.name });
      setInvite(Boolean(data.mailer_ready && data.with_email));
      setStep('preview');
    } catch (e) {
      setErr(e?.response?.data?.detail || "Le fichier n'a pas pu être lu.");
    } finally { setBusy(false); if (input.current) input.current.value = ''; }
  };

  const template = () => {
    const url = URL.createObjectURL(new Blob(['﻿' + TEMPLATE], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = url; a.download = 'modele-clients-fidclic.csv';
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  };

  const go = async () => {
    setBusy(true); setErr('');
    try {
      const rows = p.rows.filter((r) => r.status === 'new');
      const { data } = await ownerAPI.clientsImportCommit({ rows, consent, invite: invite && p.mailer_ready });
      setResult(data); setStep('done'); onDone?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || "L'import n'a pas abouti.");
    } finally { setBusy(false); }
  };

  if (step === 'file') {
    return (
      <Modal title="Importer des clients" sub="Un fichier CSV ou Excel : chaque client reçoit sa carte de fidélité." onClose={onClose}
             footer={<Btn onClick={onClose}>Annuler</Btn>}>
        {err && <Box tone="red" icon={AlertTriangle}>{err}</Box>}
        <label onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
               onDrop={(e) => { e.preventDefault(); setDrag(false); read(e.dataTransfer.files?.[0]); }}
               className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-6 py-10 text-center transition ${
                 drag ? 'border-[#2F6BFF] bg-[#EFF5FF]' : 'border-[#D9E4F7] hover:border-[#2F6BFF]'}`}>
          {busy ? <Loader2 size={26} className="animate-spin text-[#2F6BFF]" /> : <FileSpreadsheet size={28} className="text-[#2F6BFF]" />}
          <span className="text-[14px] font-semibold text-[#0B1C3F]">{busy ? 'Lecture du fichier…' : 'Choisir un fichier ou le déposer ici'}</span>
          <span className="text-[12px] text-[#64748B]">.csv ou .xlsx · 5 000 clients et 5 Mo au maximum</span>
          <input ref={input} type="file" accept=".csv,.xlsx,.xlsm,text/csv" className="sr-only" disabled={busy}
                 onChange={(e) => read(e.target.files?.[0])} />
        </label>
        <div className="mt-4 rounded-xl bg-[#F5F8FE] p-3.5 text-[12.5px] leading-relaxed text-[#475569]">
          <p className="mb-1 font-semibold text-[#0B1C3F]">Les colonnes reconnues</p>
          Nom (ou Prénom et Nom), Email, Téléphone, Date de naissance, Code postal, Ville — dans n'importe quel
          ordre, en français ou en anglais. Il faut au moins un nom et un email ou un téléphone.
          <button type="button" onClick={template}
                  className="mt-2 flex items-center gap-1.5 font-semibold text-[#2F6BFF] hover:underline">
            <Download size={13} /> Télécharger un modèle
          </button>
        </div>
      </Modal>
    );
  }

  if (step === 'preview') {
    const c = p.counts, l = p.limits;
    const willCreate = l.cards_left == null ? c.new : Math.min(c.new, l.cards_left);
    const emailable = Math.min(p.with_email, willCreate);
    const willEmail = l.invites_left == null ? emailable : Math.min(emailable, l.invites_left);
    const shown = p.rows.filter((r) => filter === 'all' || r.status === filter).slice(0, 200);
    return (
      <Modal wide title={`Vérifier l'import — ${p.filename}`}
             sub={`${nf(p.rows.length)} ligne${p.rows.length > 1 ? 's' : ''} lue${p.rows.length > 1 ? 's' : ''}. Rien n'est créé avant votre confirmation.`}
             onClose={onClose}
             footer={<>
               <Btn onClick={() => { setStep('file'); setP(null); setConsent(false); }}>Changer de fichier</Btn>
               <Btn primary disabled={!willCreate || !consent || busy} onClick={go}>
                 {busy ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
                 Importer {nf(willCreate)} client{willCreate > 1 ? 's' : ''}
               </Btn>
             </>}>
        {err && <Box tone="red" icon={AlertTriangle}>{err}</Box>}
        <div className="mb-3 flex flex-wrap gap-2">
          {[['all', 'Toutes', p.rows.length], ...Object.keys(p.status_labels).map((k) => [k, p.status_labels[k], c[k]])].map(([k, label, n]) => (
            <button key={k} type="button" onClick={() => setFilter(k)}
                    className={`rounded-full border px-3 py-1 text-[12px] font-semibold transition ${
                      filter === k ? 'border-[#2F6BFF] bg-[#EAF1FF] text-[#2F6BFF]' : 'border-[#E6EEFB] text-[#475569] hover:border-[#BFD3FF]'}`}>
              {label} · {nf(n)}
            </button>
          ))}
        </div>

        <div className="mb-4 max-h-[260px] overflow-auto rounded-xl border border-[#E6EEFB]">
          <table className="w-full min-w-[620px] border-collapse text-[12px]">
            <thead className="sticky top-0 bg-[#F5F8FE] text-left text-[11px] text-[#64748B]">
              <tr>{['Ligne', 'Nom', 'Email', 'Téléphone', 'Résultat'].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.line} className="border-t border-[#EEF3FB]">
                  <td className="px-3 py-2 text-[#94A3B8] tabular-nums">{r.line}</td>
                  <td className="px-3 py-2 font-medium text-[#0B1C3F]">{r.name || '—'}</td>
                  <td className="px-3 py-2 text-[#475569]">{r.email || '—'}</td>
                  <td className="px-3 py-2 text-[#475569] tabular-nums">{r.phone || '—'}</td>
                  <td className="px-3 py-2">
                    <span className="rounded-md px-1.5 py-0.5 text-[11px] font-semibold" style={{ background: BADGE[r.status].bg, color: BADGE[r.status].fg }}>
                      {p.status_labels[r.status]}
                    </span>
                    {r.reason && <span className="ml-1.5 text-[11px] text-[#94A3B8]">{r.reason}</span>}
                  </td>
                </tr>
              ))}
              {!shown.length && <tr><td colSpan={5} className="px-3 py-6 text-center text-[#94A3B8]">Aucune ligne.</td></tr>}
            </tbody>
          </table>
        </div>
        {p.rows.filter((r) => filter === 'all' || r.status === filter).length > 200 &&
          <p className="-mt-2 mb-3 text-[11px] text-[#94A3B8]">Les 200 premières lignes sont affichées ; toutes seront importées.</p>}

        {l.cards_left != null && c.new > l.cards_left && (
          <Box tone="amber" icon={AlertTriangle}>
            Votre formule permet encore {nf(l.cards_left)} nouvelle{l.cards_left > 1 ? 's' : ''} carte{l.cards_left > 1 ? 's' : ''} :
            seuls les {nf(l.cards_left)} premiers clients seront importés. Passez à la formule supérieure pour importer les autres.
          </Box>
        )}

        <div className="mb-3 rounded-xl border border-[#E6EEFB] p-3.5">
          <label className={`flex items-start gap-3 ${p.mailer_ready && emailable ? 'cursor-pointer' : 'opacity-60'}`}>
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[#2F6BFF]" checked={invite && p.mailer_ready && emailable > 0}
                   disabled={!p.mailer_ready || !emailable} onChange={(e) => setInvite(e.target.checked)} />
            <span className="text-[12.5px] leading-snug text-[#334155]">
              <span className="flex items-center gap-1.5 font-semibold text-[#0B1C3F]"><Mail size={14} /> Envoyer leur carte par email</span>
              {nf(emailable)} client{emailable > 1 ? 's' : ''} avec un email recevr{emailable > 1 ? 'ont' : 'a'} un lien pour ajouter la carte à
              leur téléphone. Emails d'invitation : {quotaText(l)}.
              {l.invites_left != null && emailable > l.invites_left && (
                <span className="block text-[#B45309]">Seuls {nf(l.invites_left)} emails partiront ce mois-ci ; les autres clients auront leur carte sans email.</span>
              )}
              {!p.mailer_ready && <span className="block text-[#B45309]">L'envoi d'emails n'est pas encore activé sur FidClic : les cartes seront créées sans email.</span>}
            </span>
          </label>
        </div>

        <label className="flex cursor-pointer items-start gap-3 rounded-xl bg-[#F5F8FE] p-3.5">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[#2F6BFF]" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span className="text-[12.5px] leading-snug text-[#334155]">
            Je confirme que ces clients ont accepté de rejoindre mon programme de fidélité et de recevoir ses messages.
            <span className="block text-[11px] text-[#94A3B8]">Obligatoire (RGPD). Chaque email contient un lien pour ne plus en recevoir.</span>
          </span>
        </label>
        {willEmail > 0 && invite && p.mailer_ready && (
          <p className="mt-2 text-[11.5px] text-[#64748B]">{nf(willEmail)} email{willEmail > 1 ? 's' : ''} partir{willEmail > 1 ? 'ont' : 'a'} à la confirmation.</p>
        )}
      </Modal>
    );
  }

  const e = result.emails || {};
  return (
    <Modal title="Import terminé" onClose={onClose} footer={<Btn primary onClick={onClose}>Fermer</Btn>}>
      <Box tone="green" icon={Check}>
        {nf(result.created)} client{result.created > 1 ? 's' : ''} importé{result.created > 1 ? 's' : ''} : leur carte de fidélité est prête.
      </Box>
      {result.over_limit > 0 && (
        <Box tone="amber" icon={AlertTriangle}>
          {nf(result.over_limit)} client{result.over_limit > 1 ? 's' : ''} n'{result.over_limit > 1 ? 'ont' : 'a'} pas été importé{result.over_limit > 1 ? 's' : ''} : la limite de cartes de votre formule est atteinte.
        </Box>
      )}
      {e.mailer_ready === false && <Box tone="amber">Aucun email envoyé : l'envoi d'emails n'est pas encore activé sur FidClic.</Box>}
      {e.sent > 0 && <Box tone="blue" icon={Mail}>{nf(e.sent)} email{e.sent > 1 ? 's' : ''} d'invitation envoyé{e.sent > 1 ? 's' : ''}.</Box>}
      {e.over_quota > 0 && <Box tone="amber">{nf(e.over_quota)} email{e.over_quota > 1 ? 's' : ''} non envoyé{e.over_quota > 1 ? 's' : ''} : quota du mois atteint.</Box>}
      {e.failed > 0 && <Box tone="red" icon={AlertTriangle}>{nf(e.failed)} email{e.failed > 1 ? 's' : ''} n'{e.failed > 1 ? 'ont' : 'a'} pas pu partir.</Box>}
      <p className="text-[12px] text-[#64748B]">
        Les clients qui n'auront pas ouvert leur carte dans 7 jours apparaîtront dans « Invitations », prêts pour une relance que vous déciderez d'envoyer.
      </p>
    </Modal>
  );
}

/* ── invitations + relance ──────────────────────────────────────────────── */
function RelanceModal({ onClose, onSent }) {
  const [d, setD] = useState(null);
  const [picked, setPicked] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    ownerAPI.clientRelanceList()
      .then(({ data }) => { setD(data); setPicked(new Set(data.rows.map((r) => r.id))); })
      .catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger la liste.'));
  }, []);

  const send = async () => {
    setBusy(true); setErr('');
    try {
      const { data } = await ownerAPI.clientRelanceSend([...picked]);
      onSent(data.mailer_ready === false ? "Aucune relance envoyée : l'envoi d'emails n'est pas encore activé."
        : `${nf(data.sent)} relance${data.sent > 1 ? 's' : ''} envoyée${data.sent > 1 ? 's' : ''}${data.over_quota ? ` · ${nf(data.over_quota)} hors quota` : ''}.`);
      onClose();
    } catch (e) { setErr(e?.response?.data?.detail || "L'envoi n'a pas abouti."); setBusy(false); }
  };

  const rows = d?.rows || [];
  const all = rows.length && picked.size === rows.length;
  const left = d?.limits?.invites_left;
  return (
    <Modal title="Relancer les clients qui n'ont pas ouvert leur carte"
           sub={d ? `Invités il y a plus de ${d.relance_after_days} jours, carte jamais ouverte. Rien ne part sans vous.` : ''}
           onClose={onClose}
           footer={<>
             <Btn onClick={onClose}>Annuler</Btn>
             <Btn primary disabled={!picked.size || busy} onClick={send}>
               {busy ? <Loader2 size={14} className="animate-spin" /> : <Mail size={14} />} Envoyer la relance à {nf(picked.size)}
             </Btn>
           </>}>
      {err && <Box tone="red" icon={AlertTriangle}>{err}</Box>}
      {!d ? <p className="flex items-center gap-2 text-[13px] text-[#64748B]"><Loader2 size={14} className="animate-spin" /> Chargement…</p> : (
        <>
          <div className="mb-2 flex items-center justify-between text-[12px]">
            <span className="text-[#64748B]">Emails d'invitation : {quotaText(d.limits)}</span>
            <button type="button" className="font-semibold text-[#2F6BFF] hover:underline"
                    onClick={() => setPicked(all ? new Set() : new Set(rows.map((r) => r.id)))}>{all ? 'Tout décocher' : 'Tout cocher'}</button>
          </div>
          {left != null && picked.size > left && <Box tone="amber">Seules {nf(left)} relances partiront ce mois-ci (quota de votre formule).</Box>}
          <ul className="divide-y divide-[#EEF3FB] rounded-xl border border-[#E6EEFB]">
            {rows.map((r) => (
              <li key={r.id}>
                <label className="flex cursor-pointer items-center gap-3 px-3 py-2.5 hover:bg-[#F5F8FE]">
                  <input type="checkbox" className="h-4 w-4 accent-[#2F6BFF]" checked={picked.has(r.id)}
                         onChange={() => setPicked((s) => { const n = new Set(s); if (n.has(r.id)) n.delete(r.id); else n.add(r.id); return n; })} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-semibold text-[#0B1C3F]">{r.name}</span>
                    <span className="block truncate text-[11.5px] text-[#64748B]">{r.email}</span>
                  </span>
                  <span className="shrink-0 text-[11.5px] text-[#94A3B8]">invité le {new Date(r.invited_at).toLocaleDateString('fr-FR')}</span>
                </label>
              </li>
            ))}
            {!rows.length && <li className="px-3 py-6 text-center text-[12.5px] text-[#94A3B8]">Personne à relancer pour l'instant.</li>}
          </ul>
        </>
      )}
    </Modal>
  );
}

export function InvitationsPanel({ refreshKey, canSend, onSent }) {
  const [d, setD] = useState(null);
  const [open, setOpen] = useState(false);
  const load = useCallback(() => { ownerAPI.clientInvitations().then(({ data }) => setD(data)).catch(() => {}); }, []);
  useEffect(() => { load(); }, [load, refreshKey]);
  if (!d || !d.invited) return null;               // nothing to show before a first invitation
  return (
    <section className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-2xl border border-[#E6EEFB] bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <span className="flex items-center gap-2.5">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><Mail size={17} /></span>
        <span>
          <span className="block text-[14px] font-bold text-[#0B1C3F]">Invitations par email</span>
          <span className="block text-[11.5px] text-[#64748B]">Emails : {quotaText(d.limits)}</span>
        </span>
      </span>
      {[['Invités', d.invited, '#0B1C3F'], ['Carte ouverte', d.opened, '#0F8B58'], ['En attente', d.waiting, '#B45309']].map(([label, n, color]) => (
        <span key={label} className="text-center">
          <span className="block text-[19px] font-extrabold leading-none tabular-nums" style={{ color }}>{nf(n)}</span>
          <span className="text-[11px] text-[#64748B]">{label}</span>
        </span>
      ))}
      <span className="ml-auto flex items-center gap-2">
        {d.relance_ready > 0 ? (
          canSend ? (
            <Btn primary onClick={() => setOpen(true)}><RefreshCw size={14} /> Préparer la relance ({nf(d.relance_ready)})</Btn>
          ) : <span className="text-[12px] text-[#64748B]">{nf(d.relance_ready)} client{d.relance_ready > 1 ? 's' : ''} à relancer</span>
        ) : <span className="text-[12px] text-[#94A3B8]">Relance possible {d.relance_after_days} jours après l'invitation</span>}
      </span>
      {open && <RelanceModal onClose={() => setOpen(false)} onSent={(m) => { onSent?.(m); load(); }} />}
    </section>
  );
}
