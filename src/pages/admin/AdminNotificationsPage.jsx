import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { BellRing, Send, Search, Store, Mail, MailX, Check, Undo2, Info, AlertTriangle, History } from 'lucide-react';
import { noticesAPI } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { can } from '../../lib/perms';
import { protectNames } from '../../lib/translator';
import { Card, Head, Loading, Breadcrumb, Modal, useToast, nf } from '../crm/ui';

/* Super admin › Notifications (user, 2026-11-11). FidClic writes to ONE
   business, several, or all of them — « Tous les commerces » is a choice, never
   the default. The message lands in the bell of the business's people (owner,
   administrateur, manager), and in the owner's mailbox when asked. Never to a
   business's customers: that is done from its own account (« Accéder au
   compte »). Server: api/features/admin_notices.py. */

const STATUS = {
  abonne: ['Abonné', '#E7F7EE', '#0F8B58'], essai: ['Essai', '#EAF1FF', '#2F6BFF'], impaye: ['Impayé', '#FFF4DB', '#B45309'],
  non_converti: ['Non converti', '#F1F5F9', '#475569'], resilie: ['Résilié', '#FDECEF', '#E11D48'],
};
const FILTERS = [['all', 'Tous'], ['abonne', 'Abonnés'], ['essai', 'Essai'], ['impaye', 'Impayés'], ['non_converti', 'Non convertis'], ['resilie', 'Résiliés']];
const LINKS = [['', 'Aucun lien'], ['/dashboard', 'Tableau de bord'], ['/dashboard/aide', "Besoin d'aide ?"], ['/dashboard/settings', 'Paramètres']];
const TITLE_MAX = 120;
const BODY_MAX = 2000;
const when = (s) => (s ? new Date(s).toLocaleString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Europe/Paris' }) : '');

function Badge({ s }) {
  const [label, bg, fg] = STATUS[s] || [s || '—', '#F1F5F9', '#475569'];
  return <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: bg, color: fg }}>{label}</span>;
}

function Preview({ title, body, level }) {
  const important = level === 'important';
  const I = important ? AlertTriangle : Info;
  return (
    <div className="rounded-xl border border-[#E6EEFB] bg-[#FAFCFF] p-3">
      <p className="mb-2 text-[11.5px] font-semibold uppercase tracking-wide text-[#94A3B8]">Aperçu dans la cloche du commerce</p>
      <div className="flex items-start gap-2.5 rounded-xl bg-white p-3 shadow-[0_1px_2px_rgba(11,28,63,.06)]">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full" style={{ background: important ? '#FFF4DB' : '#EAF1FF', color: important ? '#B45309' : '#2F6BFF' }}><I size={15} /></span>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold text-[#2F6BFF]" translate="no">FidClic</p>
          <p className="break-words text-[13.5px] font-semibold text-[#0B1C3F]">{title || 'Titre du message'}</p>
          <p className="whitespace-pre-line break-words text-[12.5px] text-[#475569]">{body || 'Votre message…'}</p>
        </div>
      </div>
    </div>
  );
}

function Composer({ shops, onSent, say }) {
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [level, setLevel] = useState('info');
  const [link, setLink] = useState('');
  const [email, setEmail] = useState(false);
  const [everyone, setEveryone] = useState(false);
  const [picked, setPicked] = useState(() => new Set());
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState('all');
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const shown = useMemo(() => {
    const k = q.trim().toLowerCase();
    return shops.filter((s) => (filter === 'all' || s.status === filter)
      && (!k || `${s.name} ${s.city || ''} ${s.sector || ''}`.toLowerCase().includes(k)));
  }, [shops, q, filter]);
  const targets = everyone ? shops : shops.filter((s) => picked.has(s.id));
  const mails = targets.filter((s) => s.has_email).length;
  const toggle = (id) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const ready = title.trim() && body.trim() && title.length <= TITLE_MAX && body.length <= BODY_MAX && targets.length > 0;

  const send = async () => {
    setBusy(true); setErr('');
    try {
      const { data } = await noticesAPI.send({
        title, body, level, email, link: link || null,
        ...(everyone ? { all: true } : { tenant_ids: [...picked] }),
      });
      say(`Envoyé à ${nf(data.businesses)} commerce${data.businesses > 1 ? 's' : ''}${email ? ` · ${nf(data.emailed)} email${data.emailed > 1 ? 's' : ''}` : ''}.`);
      setTitle(''); setBody(''); setLevel('info'); setLink(''); setEmail(false); setEveryone(false); setPicked(new Set()); setConfirm(false);
      onSent();
    } catch (e) {
      const d = e?.response?.data?.detail;
      setErr(typeof d === 'string' ? d : (Array.isArray(d) ? d.map((x) => x.msg).join(' · ') : "L'envoi a échoué."));
      setConfirm(false);
    } finally { setBusy(false); }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[1.05fr_1fr]">
      <Card>
        <Head icon={Send} title="Nouveau message" sub="Aux commerces choisis : dans leur cloche, et par email si vous le cochez." />
        <label className="mb-1 flex justify-between text-[12.5px] font-medium text-[#0B1C3F]" htmlFor="nt-title">Titre <span className={`tabular-nums ${title.length > TITLE_MAX ? 'text-[#E11D48]' : 'text-[#94A3B8]'}`}>{title.length}/{TITLE_MAX}</span></label>
        <input id="nt-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ex. Maintenance ce soir de 22:00 à 22:30"
               className="mb-3 h-10 w-full rounded-xl border border-[#DCE3EE] px-3 text-[13.5px] outline-none focus:border-[#2F6BFF]" />
        <label className="mb-1 flex justify-between text-[12.5px] font-medium text-[#0B1C3F]" htmlFor="nt-body">Message <span className={`tabular-nums ${body.length > BODY_MAX ? 'text-[#E11D48]' : 'text-[#94A3B8]'}`}>{body.length}/{BODY_MAX}</span></label>
        <textarea id="nt-body" value={body} onChange={(e) => setBody(e.target.value)} rows={5} placeholder="Votre message aux commerçants…"
                  className="mb-3 w-full rounded-xl border border-[#DCE3EE] px-3 py-2 text-[13.5px] outline-none focus:border-[#2F6BFF]" />
        <div className="mb-3 grid gap-3 sm:grid-cols-2">
          <div>
            <p className="mb-1 text-[12.5px] font-medium text-[#0B1C3F]">Niveau</p>
            <div className="flex gap-1.5" role="radiogroup" aria-label="Niveau">
              {[['info', 'Information'], ['important', 'Important']].map(([k, l]) => (
                <button key={k} type="button" role="radio" aria-checked={level === k} onClick={() => setLevel(k)}
                        className={`h-9 flex-1 rounded-xl border text-[12.5px] font-medium ${level === k ? 'border-[#2F6BFF] bg-[#EAF1FF] text-[#2F6BFF]' : 'border-[#DCE3EE] bg-white text-[#475569]'}`}>{l}</button>
              ))}
            </div>
          </div>
          <div>
            <label className="mb-1 block text-[12.5px] font-medium text-[#0B1C3F]" htmlFor="nt-link">Bouton vers</label>
            <select id="nt-link" value={link} onChange={(e) => setLink(e.target.value)} className="h-9 w-full rounded-xl border border-[#DCE3EE] bg-white px-2 text-[12.5px]">
              {LINKS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
        </div>
        <label className="mb-4 flex items-center gap-2 text-[13px] text-[#0B1C3F]">
          <input type="checkbox" checked={email} onChange={(e) => setEmail(e.target.checked)} className="h-4 w-4 accent-[#2F6BFF]" />
          Envoyer aussi par email au propriétaire
        </label>
        <Preview title={title} body={body} level={level} />
        {err && <p className="mt-3 rounded-xl bg-[#FEF2F2] px-3 py-2 text-[13px] text-[#B91C1C]">{err}</p>}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <p className="text-[12.5px] text-[#64748B]" data-testid="notice-summary">
            {targets.length ? `${nf(targets.length)} commerce${targets.length > 1 ? 's' : ''}${email ? ` · ${nf(mails)} email${mails > 1 ? 's' : ''}` : ''}` : 'Aucun commerce choisi'}
          </p>
          <button type="button" disabled={!ready || busy} onClick={() => setConfirm(true)}
                  className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 text-[13.5px] font-semibold text-white disabled:opacity-40"><Send size={15} /> Envoyer</button>
        </div>
      </Card>

      <Card className="flex min-w-0 flex-col">
        <Head icon={Store} title="Destinataires" sub="Un commerce, plusieurs, ou tous." />
        <div className="mb-3 flex gap-1.5" role="radiogroup" aria-label="Destinataires">
          <button type="button" role="radio" aria-checked={!everyone} onClick={() => setEveryone(false)}
                  className={`h-9 flex-1 rounded-xl border text-[12.5px] font-medium ${!everyone ? 'border-[#2F6BFF] bg-[#EAF1FF] text-[#2F6BFF]' : 'border-[#DCE3EE] text-[#475569]'}`}>Commerces choisis ({nf(picked.size)})</button>
          <button type="button" role="radio" aria-checked={everyone} onClick={() => setEveryone(true)}
                  className={`h-9 flex-1 rounded-xl border text-[12.5px] font-medium ${everyone ? 'border-[#2F6BFF] bg-[#EAF1FF] text-[#2F6BFF]' : 'border-[#DCE3EE] text-[#475569]'}`}>Tous les commerces ({nf(shops.length)})</button>
        </div>
        {everyone ? (
          <p className="rounded-xl bg-[#FFF8EC] px-3 py-2.5 text-[13px] text-[#B45309]">Le message ira aux {nf(shops.length)} commerces ouverts aujourd'hui. Un commerce qui s'inscrit plus tard ne le recevra pas.</p>
        ) : (
          <>
            <div className="mb-2 flex items-center gap-2 rounded-xl border border-[#DCE3EE] px-3">
              <Search size={15} className="text-[#94A3B8]" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Chercher un commerce, une ville, un secteur" aria-label="Chercher un commerce"
                     className="h-9 min-w-0 flex-1 text-[13px] outline-none" />
            </div>
            <div className="mb-2 flex flex-wrap gap-1.5">
              {FILTERS.map(([k, l]) => (
                <button key={k} type="button" onClick={() => setFilter(k)}
                        className={`rounded-full px-2.5 py-1 text-[12px] ${filter === k ? 'bg-[#0B1C3F] text-white' : 'bg-[#F1F5F9] text-[#475569]'}`}>{l}</button>
              ))}
            </div>
            <div className="mb-2 flex items-center justify-between text-[12px]">
              <button type="button" onClick={() => setPicked((p) => new Set([...p, ...shown.map((s) => s.id)]))} className="font-medium text-[#2F6BFF]">Cocher les {nf(shown.length)} affichés</button>
              {picked.size > 0 && <button type="button" onClick={() => setPicked(new Set())} className="text-[#64748B]">Tout décocher</button>}
            </div>
            <ul className="max-h-[430px] flex-1 space-y-1 overflow-y-auto" data-testid="notice-targets">
              {shown.map((s) => (
                <li key={s.id}>
                  <label className={`flex cursor-pointer items-center gap-2.5 rounded-xl border px-3 py-2 ${picked.has(s.id) ? 'border-[#BFD3FF] bg-[#F4F8FF]' : 'border-[#F1F5F9] hover:bg-[#FAFCFF]'}`}>
                    <input type="checkbox" checked={picked.has(s.id)} onChange={() => toggle(s.id)} className="h-4 w-4 accent-[#2F6BFF]" aria-label={s.name} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-semibold text-[#0B1C3F]" translate="no">{s.name}</span>
                      <span className="block truncate text-[11.5px] text-[#64748B]">{[s.city, s.stores > 1 ? `${s.stores} boutiques` : null, s.plan].filter(Boolean).join(' · ')}</span>
                    </span>
                    <Badge s={s.status} />
                    {s.has_email ? <Mail size={14} className="text-[#94A3B8]" aria-label="Email du propriétaire connu" />
                      : <MailX size={14} className="text-[#E11D48]" aria-label="Pas d'email du propriétaire" />}
                  </label>
                </li>
              ))}
              {!shown.length && <li className="py-8 text-center text-[13px] text-[#94A3B8]">Aucun commerce ne correspond.</li>}
            </ul>
          </>
        )}
      </Card>

      {confirm && (
        <Modal title="Envoyer ce message ?" onClose={() => !busy && setConfirm(false)}>
          <p className="text-[13.5px] text-[#0B1C3F]">« <b>{title.trim()}</b> » ira dans la cloche de <b>{everyone ? `tous les commerces (${nf(targets.length)})` : `${nf(targets.length)} commerce${targets.length > 1 ? 's' : ''}`}</b>{email ? <>, et par email à <b>{nf(mails)}</b> propriétaire{mails > 1 ? 's' : ''}</> : null}.</p>
          {!everyone && targets.length <= 8 && <p className="mt-2 text-[12.5px] text-[#64748B]" translate="no">{targets.map((s) => s.name).join(', ')}</p>}
          <p className="mt-2 text-[12.5px] text-[#64748B]">Les clients de ces commerces ne reçoivent rien.</p>
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" onClick={() => setConfirm(false)} disabled={busy} className="h-9 rounded-xl border border-[#DCE3EE] px-4 text-[13px]">Annuler</button>
            <button type="button" onClick={send} disabled={busy} className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#2F6BFF] px-4 text-[13px] font-semibold text-white disabled:opacity-50"><Check size={14} /> Confirmer l'envoi</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function HistoryList({ rows, editable, onWithdraw }) {
  const [ask, setAsk] = useState(null);
  return (
    <Card className="mt-4">
      <Head icon={History} title="Messages envoyés" sub="Retirer un message l'enlève de la cloche des commerces (un email déjà parti reste parti)." />
      {!rows.length && <p className="py-8 text-center text-[13px] text-[#94A3B8]">Aucun message envoyé pour l'instant.</p>}
      <ul className="divide-y divide-[#F1F5F9]" data-testid="notice-history">
        {rows.map((n) => (
          <li key={n.id} className="flex flex-wrap items-start gap-3 py-3">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full" style={{ background: n.level === 'important' ? '#FFF4DB' : '#EAF1FF', color: n.level === 'important' ? '#B45309' : '#2F6BFF' }}>
              {n.level === 'important' ? <AlertTriangle size={15} /> : <Info size={15} />}
            </span>
            <div className="min-w-0 flex-1">
              <p className="break-words text-[13.5px] font-semibold text-[#0B1C3F]">{n.title}
                {n.withdrawn_at && <span className="ml-2 rounded-full bg-[#F1F5F9] px-2 py-0.5 text-[11px] font-medium text-[#64748B]">Retiré</span>}</p>
              <p className="line-clamp-2 whitespace-pre-line break-words text-[12.5px] text-[#475569]">{n.body}</p>
              <p className="mt-1 text-[11.5px] text-[#94A3B8]">
                <span translate="no">{when(n.created_at)}</span> · {n.by} · {n.all ? `Tous les commerces (${nf(n.businesses)})` : <span translate="no">{n.to_names.join(', ')}{n.more ? ` +${nf(n.more)}` : ''}</span>}
                {n.email && ` · ${nf(n.emailed)} email${n.emailed > 1 ? 's' : ''}`}
              </p>
            </div>
            {editable && !n.withdrawn_at && (
              <button type="button" onClick={() => setAsk(n)} className="inline-flex h-8 items-center gap-1 rounded-lg border border-[#DCE3EE] px-2.5 text-[12px] text-[#475569]"><Undo2 size={13} /> Retirer</button>
            )}
          </li>
        ))}
      </ul>
      {ask && (
        <Modal title="Retirer ce message ?" onClose={() => setAsk(null)}>
          <p className="text-[13.5px]">« <b>{ask.title}</b> » disparaîtra de la cloche des {nf(ask.businesses)} commerce{ask.businesses > 1 ? 's' : ''}.</p>
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" onClick={() => setAsk(null)} className="h-9 rounded-xl border border-[#DCE3EE] px-4 text-[13px]">Annuler</button>
            <button type="button" onClick={() => { onWithdraw(ask.id); setAsk(null); }} className="h-9 rounded-xl bg-[#E11D48] px-4 text-[13px] font-semibold text-white">Retirer</button>
          </div>
        </Modal>
      )}
    </Card>
  );
}

export default function AdminNotificationsPage() {
  const { user } = useAuth();
  const editable = can(user, 'notifications', 'edit');
  const [shops, setShops] = useState(null);
  const [rows, setRows] = useState([]);
  const [err, setErr] = useState('');
  const [say, node] = useToast();

  const load = useCallback(() => {
    Promise.all([noticesAPI.targets(), noticesAPI.list()])
      .then(([t, h]) => {
        const list = t.data?.businesses || [];
        protectNames(list.map((s) => s.name).filter(Boolean));
        setShops(list); setRows(h.data?.notices || []); setErr('');
      })
      .catch((e) => setErr(e?.response?.data?.detail || 'La page n\'a pas pu être chargée.'));
  }, []);
  useEffect(() => { load(); }, [load]);

  const withdraw = async (id) => {
    try { await noticesAPI.withdraw(id); say('Message retiré.'); load(); } catch (e) { say(e?.response?.data?.detail || 'Échec.'); }
  };

  return (
    <div className="mx-auto max-w-[1400px] p-4 sm:p-6">
      {node}
      <Breadcrumb items={[['Super Admin', '/admin'], ['Notifications']]} />
      <div className="mb-4 flex items-center gap-2.5">
        <BellRing size={22} className="text-[#2F6BFF]" />
        <div>
          <h1 className="text-[22px] font-bold text-[#0B1C3F]">Notifications</h1>
          <p className="text-[13px] text-[#64748B]">Écrire aux commerçants. Pour écrire aux clients d'un commerce, passez par son compte (« Accéder au compte »).</p>
        </div>
      </div>
      {err && <p className="mb-3 rounded-xl bg-[#FEF2F2] px-3 py-2 text-[13px] text-[#B91C1C]">{err}</p>}
      {!shops && !err && <Loading />}
      {shops && editable && <Composer shops={shops} onSent={load} say={say} />}
      {shops && !editable && <p className="rounded-xl bg-[#F4F7FC] px-3 py-2.5 text-[13px] text-[#475569]">Votre rôle permet de voir les messages envoyés, pas d'en écrire.</p>}
      {shops && <HistoryList rows={rows} editable={editable} onWithdraw={withdraw} />}
    </div>
  );
}
