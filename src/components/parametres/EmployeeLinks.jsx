import React, { useCallback, useEffect, useRef, useState } from 'react';
import { QRCodeCanvas } from 'qrcode.react';
import {
  BadgeCheck, Copy, Crown, Loader2, Mail, Pencil, QrCode, Send, Trash2, TrendingUp, UserPlus, X,
} from 'lucide-react';
import { ownerAPI } from '../../lib/api';

/**
 * « Liens d'inscription par employé » — Paramètres › Lien d'inscription.
 *
 * The owner writes an employee down (a name; an e-mail and a phone if they
 * want), FidClic gives them a link and a QR of their own, and every client who
 * signs up through them is theirs — here, in Clients, and in Analyses, where
 * the employee is a source by name.
 *
 * Permission « employee_links » (Paramètres › Équipe & accès › Rôles):
 *   view  an employee sees their own link, their QR and the whole leaderboard
 *   edit  …and writes the records and sends the e-mails
 * `can_edit` and `mine` come from the server — this component only draws them.
 */
const nf = (n) => new Intl.NumberFormat('fr-FR').format(n || 0);
// Le chiffre d'affaires a été retiré du classement (user, 2026-10-16) : ce qui
// compte ici est qui amène les clients. L'API le calcule toujours
// (leaderboard().revenue), si on veut le remettre un jour.
const MEASURES = [
  ['month', 'Ce mois-ci', (r) => nf(r.month)],
  ['total', 'Depuis le début', (r) => nf(r.total)],
];

function Field({ label, value, onChange, placeholder, type = 'text', required = false, autoFocus = false }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[12.5px] font-medium text-[#0B1C3F]">
        {label}{required ? '' : <span className="font-normal text-[#94A3B8]"> (facultatif)</span>}
      </span>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
             autoFocus={autoFocus} required={required}
             className="h-10 w-full rounded-lg border border-[#E2E8F0] px-3 text-[13.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]" />
    </label>
  );
}

function AgentModal({ agent, onClose, onSave, busy, error }) {
  const [f, setF] = useState({ name: agent?.name || '', email: agent?.email || '', phone: agent?.phone || '' });
  return (
    <div role="dialog" aria-modal="true" aria-label={agent ? 'Modifier un employé' : 'Ajouter un employé'}
         onClick={onClose} className="fixed inset-0 z-50 flex items-center justify-center bg-[#0B1C3F]/45 p-4">
      <form onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => { e.preventDefault(); onSave(f); }}
            className="w-full max-w-[420px] rounded-2xl bg-white p-5 shadow-[0_32px_80px_-32px_rgba(11,28,63,.6)]">
        <div className="mb-4 flex items-start justify-between gap-3">
          <h3 className="text-[16px] font-bold text-[#0B1C3F]">
            {agent ? "Modifier l'employé" : 'Ajouter un employé'}
          </h3>
          <button type="button" onClick={onClose} aria-label="Fermer" className="text-[#94A3B8] hover:text-[#0B1C3F]">
            <X size={18} />
          </button>
        </div>
        <div className="space-y-3">
          <Field label="Nom" required autoFocus value={f.name} onChange={(v) => setF({ ...f, name: v })}
                 placeholder="Marie Dupont" />
          <Field label="E-mail" type="email" value={f.email} onChange={(v) => setF({ ...f, email: v })}
                 placeholder="marie@exemple.fr" />
          <Field label="Téléphone" value={f.phone} onChange={(v) => setF({ ...f, phone: v })}
                 placeholder="06 12 34 56 78" />
        </div>
        <p className="mt-3 text-[11.5px] text-[#64748B]">
          L&apos;e-mail sert à lui envoyer son lien et son QR code d&apos;ici, et à lui montrer son
          propre lien s&apos;il a un accès à FidClic.
        </p>
        {error && <p className="mt-3 rounded-lg bg-[#FEF2F2] px-3 py-2 text-[12.5px] text-[#B91C1C]">{error}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onClose}
                  className="h-10 rounded-lg border border-[#E2E8F0] px-4 text-[13px] font-medium text-[#334155]">Annuler</button>
          <button type="submit" disabled={busy || !f.name.trim()}
                  className="inline-flex h-10 items-center gap-2 rounded-lg bg-[#2F6BFF] px-4 text-[13px] font-semibold text-white disabled:opacity-50">
            {busy && <Loader2 size={14} className="animate-spin" />} {agent ? 'Enregistrer' : "Créer le lien"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default function EmployeeLinks({ cardCls, CardHead, say, icons }) {
  const { Link2, Users } = icons;
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [modal, setModal] = useState(null);         // {agent} | 'new'
  const [busy, setBusy] = useState(false);
  const [modalErr, setModalErr] = useState('');
  const [picked, setPicked] = useState([]);         // ids chosen for the e-mail
  const [sending, setSending] = useState(false);
  const [measure, setMeasure] = useState('month');
  const [qrFor, setQrFor] = useState(null);
  const qr = useRef(null);

  const load = useCallback(() => {
    ownerAPI.signupAgents()
      .then(({ data }) => { setD(data); setErr(''); })
      .catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger les liens employés.'));
  }, []);
  useEffect(() => { load(); }, [load]);

  // a QR is drawn off screen at full size, then saved
  useEffect(() => {
    if (!qrFor) return;
    const png = qr.current?.toDataURL('image/png');
    if (png) {
      const a = document.createElement('a');
      a.href = png; a.download = `qr-${qrFor.word}.png`;
      document.body.appendChild(a); a.click(); a.remove();
      say('QR code téléchargé');
    }
    setQrFor(null);
  }, [qrFor]); // eslint-disable-line react-hooks/exhaustive-deps

  const copy = async (text, msg) => {
    try { await navigator.clipboard.writeText(text); say(msg); }
    catch { say('Copie impossible — sélectionnez le lien à la main.'); }
  };

  const save = async (f) => {
    setBusy(true); setModalErr('');
    try {
      const body = { name: f.name.trim(), email: f.email.trim() || null, phone: f.phone.trim() || null };
      const { data } = modal === 'new'
        ? await ownerAPI.addSignupAgent(body)
        : await ownerAPI.editSignupAgent(modal.agent.id, body);
      setD(data); setModal(null);
      say(modal === 'new' ? 'Lien employé créé' : 'Employé modifié');
    } catch (e) {
      setModalErr(e?.response?.data?.detail || "L'enregistrement n'a pas abouti.");
    } finally { setBusy(false); }
  };

  const archive = async (a) => {
    try {
      const { data } = await ownerAPI.archiveSignupAgent(a.id);
      setD(data); setPicked((p) => p.filter((x) => x !== a.id));
      say(`${a.name} archivé — son lien ne fonctionne plus, ses clients gardent son nom.`);
    } catch (e) { say(e?.response?.data?.detail || "L'archivage n'a pas abouti."); }
  };

  const restore = async (a) => {
    try {
      const { data } = await ownerAPI.editSignupAgent(a.id, { archived: false });
      setD(data); say(`${a.name} réactivé — son lien refonctionne.`);
    } catch (e) { say(e?.response?.data?.detail || "La réactivation n'a pas abouti."); }
  };

  const send = async () => {
    setSending(true);
    try {
      const { data } = await ownerAPI.sendSignupAgentLinks(picked);
      setD(data); setPicked([]);
      const miss = (data.no_email || []).length;
      say(`${data.sent} e-mail${data.sent > 1 ? 's' : ''} envoyé${data.sent > 1 ? 's' : ''}`
        + (miss ? ` · ${miss} sans adresse e-mail` : ''));
    } catch (e) { say(e?.response?.data?.detail || "L'envoi n'a pas abouti."); }
    finally { setSending(false); }
  };

  if (err) return <p className={`${cardCls} mt-4 text-[13px] text-[#B91C1C]`}>{err}</p>;
  if (!d) {
    return (
      <div className={`${cardCls} mt-4 flex items-center justify-center gap-2 py-16 text-[13px] text-[#64748B]`}>
        <Loader2 size={16} className="animate-spin" /> Chargement…
      </div>
    );
  }

  const canEdit = !!d.can_edit;
  const live = (d.agents || []).filter((a) => !a.archived);
  const archived = (d.agents || []).filter((a) => a.archived);
  const board = d.leaderboard || [];
  const ranked = measure === 'month' ? board
    : [...board].sort((x, y) => (y[measure] || 0) - (x[measure] || 0) || x.name.localeCompare(y.name));
  const fmt = MEASURES.find(([k]) => k === measure)[2];
  const pickable = live.filter((a) => a.email);

  return (
    <>
      <section className={`${cardCls} mt-4`}>
        <CardHead icon={Link2} title="Un lien par employé"
                  subtitle="Chaque employé a son propre lien et son propre QR code. Le client qui s'inscrit avec est compté pour lui — dans la fiche du client, dans les sources et dans le classement ci-dessous."
                  right={canEdit && (
                    <button type="button" onClick={() => { setModalErr(''); setModal('new'); }}
                            className="inline-flex h-10 shrink-0 items-center gap-2 rounded-lg bg-[#2F6BFF] px-3.5 text-[13px] font-semibold text-white hover:bg-[#2559DB]">
                      <UserPlus size={15} /> Ajouter un employé
                    </button>
                  )} />

        {live.length === 0 && (
          <p className="rounded-xl border border-dashed border-[#C9DBFB] bg-[#F6F9FF] px-4 py-6 text-center text-[13px] text-[#475569]">
            {canEdit
              ? "Aucun employé pour l'instant. Ajoutez-en un : il recevra son lien et son QR code, et vous saurez qui amène vos clients."
              : "Aucun lien employé n'a encore été créé dans ce commerce."}
          </p>
        )}

        <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-3">
          {live.map((a) => {
            const isMine = d.mine && a.id === d.mine;
            return (
              <div key={a.id}
                   className={`rounded-xl border p-3 ${isMine ? 'border-[#2F6BFF] bg-[#F6F9FF]' : 'border-[#E6EEFB]'}`}>
                <div className="flex items-start gap-2.5">
                  {canEdit && a.email && (
                    <input type="checkbox" checked={picked.includes(a.id)} aria-label={`Choisir ${a.name}`}
                           onChange={(e) => setPicked((p) => (e.target.checked ? [...p, a.id] : p.filter((x) => x !== a.id)))}
                           className="mt-1 h-4 w-4 shrink-0 accent-[#2F6BFF]" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-1.5 truncate text-[13.5px] font-semibold text-[#0B1C3F]">
                      {a.name}
                      {isMine && <span className="shrink-0 rounded-full bg-[#2F6BFF] px-1.5 py-0.5 text-[10px] font-bold text-white">Vous</span>}
                    </p>
                    <p className="truncate text-[11.5px] text-[#64748B]">
                      {a.email || a.phone || 'Aucun contact enregistré'}
                    </p>
                    <p className="mt-1 truncate text-[11.5px] text-[#2F6BFF]" title={a.link}>
                      {a.link.replace(/^https?:\/\//, '')}
                    </p>
                    {a.sent_at && (
                      <p className="mt-0.5 flex items-center gap-1 text-[11px] text-[#0F8B58]">
                        <BadgeCheck size={12} /> Lien envoyé le{' '}
                        {new Date(a.sent_at).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' })}
                      </p>
                    )}
                  </div>
                </div>
                <div className="mt-2.5 flex items-center gap-1">
                  <button type="button" onClick={() => copy(a.link, `Lien de ${a.name} copié`)}
                          aria-label={`Copier le lien de ${a.name}`}
                          className="flex h-8 w-8 items-center justify-center rounded-lg text-[#2F6BFF] hover:bg-white"><Copy size={15} /></button>
                  <button type="button" onClick={() => setQrFor(a)} aria-label={`QR code de ${a.name}`}
                          className="flex h-8 w-8 items-center justify-center rounded-lg text-[#2F6BFF] hover:bg-white"><QrCode size={15} /></button>
                  {canEdit && (
                    <>
                      <button type="button" onClick={() => { setModalErr(''); setModal({ agent: a }); }}
                              aria-label={`Modifier ${a.name}`}
                              className="flex h-8 w-8 items-center justify-center rounded-lg text-[#475569] hover:bg-white"><Pencil size={14} /></button>
                      <button type="button" onClick={() => archive(a)} aria-label={`Archiver ${a.name}`}
                              className="flex h-8 w-8 items-center justify-center rounded-lg text-[#B91C1C] hover:bg-white"><Trash2 size={14} /></button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {canEdit && live.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl bg-[#F6F9FF] px-3.5 py-3">
            <Mail size={16} className="shrink-0 text-[#2F6BFF]" />
            <p className="min-w-0 flex-1 text-[12px] text-[#1E4FD8]">
              {picked.length
                ? `${picked.length} employé${picked.length > 1 ? 's' : ''} choisi${picked.length > 1 ? 's' : ''} — ils recevront leur lien, leur QR code et à quoi il sert.`
                : `Cochez les employés pour leur envoyer leur lien par e-mail. ${pickable.length} sur ${live.length} ont une adresse.`}
              {!d.mail_ready && " L'envoi d'e-mails n'est pas encore configuré sur ce commerce."}
            </p>
            <button type="button" onClick={send} disabled={!picked.length || sending || !d.mail_ready}
                    className="inline-flex h-9 shrink-0 items-center gap-2 rounded-lg bg-[#2F6BFF] px-3.5 text-[12.5px] font-semibold text-white disabled:opacity-50">
              {sending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />} Envoyer par e-mail
            </button>
          </div>
        )}

        {archived.length > 0 && (
          <details className="mt-3">
            <summary className="cursor-pointer text-[12.5px] font-semibold text-[#475569]">
              {archived.length} employé{archived.length > 1 ? 's' : ''} archivé{archived.length > 1 ? 's' : ''}
            </summary>
            <div className="mt-2 space-y-1.5">
              {archived.map((a) => (
                <div key={a.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-[#E6EEFB] px-3 py-2">
                  <span className="min-w-0 flex-1 truncate text-[12.5px] text-[#64748B]">
                    {a.name} — lien désactivé, ses clients gardent son nom
                  </span>
                  {canEdit && (
                    <button type="button" onClick={() => restore(a)}
                            className="h-8 rounded-lg border border-[#2F6BFF] px-2.5 text-[12px] font-semibold text-[#2F6BFF]">Réactiver</button>
                  )}
                </div>
              ))}
            </div>
          </details>
        )}
        {qrFor && <div className="hidden"><QRCodeCanvas ref={qr} value={qrFor.link} size={1024} level="M" marginSize={2} /></div>}
      </section>

      {/* Classement */}
      <section className={`${cardCls} mt-4`}>
        <CardHead icon={TrendingUp} title="Classement de l'équipe"
                  subtitle="Qui amène les clients : les inscrits de ce mois-ci, ou le total depuis le début."
                  right={(
                    <div role="group" aria-label="Classer par" className="flex shrink-0 gap-1 rounded-lg bg-[#F1F5F9] p-1">
                      {MEASURES.map(([k, lab]) => (
                        <button key={k} type="button" onClick={() => setMeasure(k)}
                                aria-pressed={measure === k}
                                className={`rounded-md px-2.5 py-1.5 text-[12px] font-semibold ${measure === k ? 'bg-white text-[#0B1C3F] shadow-sm' : 'text-[#64748B]'}`}>
                          {lab}
                        </button>
                      ))}
                    </div>
                  )} />
        {ranked.length === 0 ? (
          <p className="py-6 text-center text-[13px] text-[#64748B]">
            Le classement apparaîtra dès qu&apos;un employé aura un lien.
          </p>
        ) : (
          <ol className="space-y-1.5">
            {ranked.map((r, i) => {
              const isMine = d.mine && r.agent_id === d.mine;
              return (
                <li key={r.agent_id}
                    className={`flex items-center gap-3 rounded-xl border px-3 py-2.5 ${isMine ? 'border-[#2F6BFF] bg-[#F6F9FF]' : 'border-[#E6EEFB]'}`}>
                  <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[12px] font-bold ${
                    i === 0 ? 'bg-[#FEF3C7] text-[#92400E]' : 'bg-[#F1F5F9] text-[#475569]'}`}>
                    {i === 0 ? <Crown size={14} /> : i + 1}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5 truncate text-[13.5px] font-semibold text-[#0B1C3F]">
                      {r.name}
                      {isMine && <span className="shrink-0 rounded-full bg-[#2F6BFF] px-1.5 py-0.5 text-[10px] font-bold text-white">Vous</span>}
                      {r.archived && <span className="shrink-0 text-[11px] font-normal text-[#94A3B8]">(archivé)</span>}
                    </span>
                    <span className="block truncate text-[11.5px] text-[#64748B]">{r.word}</span>
                  </span>
                  <span className="hidden shrink-0 gap-4 text-right sm:flex">
                    {MEASURES.map(([k, lab, f]) => (
                      <span key={k} className={k === measure ? 'text-[#0B1C3F]' : 'text-[#94A3B8]'}>
                        <span className="block text-[10.5px] uppercase tracking-wide">{lab}</span>
                        <span className="block text-[14px] font-bold">{f(r)}</span>
                      </span>
                    ))}
                  </span>
                  <span className="shrink-0 text-[15px] font-bold text-[#0B1C3F] sm:hidden">{fmt(r)}</span>
                </li>
              );
            })}
          </ol>
        )}
        <p className="mt-3 flex items-center gap-1.5 text-[11.5px] text-[#94A3B8]">
          <Users size={13} /> Les clients effacés ne comptent pas. Le mois est le mois civil, heure de Paris.
        </p>
      </section>

      {modal && (
        <AgentModal agent={modal === 'new' ? null : modal.agent} busy={busy} error={modalErr}
                    onClose={() => setModal(null)} onSave={save} />
      )}
    </>
  );
}
