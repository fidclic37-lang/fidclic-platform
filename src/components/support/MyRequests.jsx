import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Inbox, Plus, Send, Loader2, Star, ChevronRight, MessageSquareText, X, CheckCheck } from 'lucide-react';
import { mySupportAPI } from '../../lib/api';
import {
  StatusPill, Avatar, when, clock, fullDate, dayLabel, errText, Attachment, EmojiButton, useUploads, AttachButton, UploadChips,
} from '../../pages/admin/support/shared';

/* « Besoin d'aide ? » › « Mes demandes » — the merchant's side of the super
   admin's « Centre de support » (features/support_center.py): every
   request, the whole conversation with FidClic's team (never its internal
   notes), replies with attachments, and the 1–5 rating once resolved. The
   same answers also arrive by email. */

const fetchFile = (id, inline) => mySupportAPI.file(id, inline);
const MERCHANT_TONE = { nouveau: 'nouveau', en_cours: 'en_cours', en_attente: 'en_attente', resolu: 'resolu' };

function Sheet({ title, onClose, children, wide }) {
  useEffect(() => {
    const k = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#0B1C3F]/35 sm:items-center sm:p-6" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}
           className={`flex max-h-[94vh] w-full flex-col overflow-hidden rounded-t-2xl bg-white shadow-2xl sm:rounded-2xl ${wide ? 'max-w-3xl' : 'max-w-lg'}`}>
        <header className="flex items-center gap-3 border-b border-[#EEF2F8] px-5 py-4">
          <h3 className="min-w-0 flex-1 truncate text-[16px] font-bold text-[#0B1C3F]">{title}</h3>
          <button type="button" onClick={onClose} aria-label="Fermer" className="rounded-lg p-1 text-[#94A3B8] hover:text-[#0B1C3F]"><X size={19} /></button>
        </header>
        {children}
      </div>
    </div>
  );
}

export function NewRequest({ onClose, onDone }) {
  const [form, setForm] = useState({ subject: '', category: 'autre', body: '' });
  const [cats, setCats] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const up = useUploads(mySupportAPI.upload);
  useEffect(() => { mySupportAPI.tickets().then(({ data }) => setCats(data.categories || [])).catch(() => {}); }, []);
  const submit = () => {
    if (!form.subject.trim() || !form.body.trim()) { setErr("L'objet et le message sont obligatoires."); return; }
    setBusy(true); setErr('');
    mySupportAPI.create({ ...form, attachments: up.ids }).then(({ data }) => onDone(data.id))
      .catch((e) => setErr(errText(e, "La demande n'a pas pu être envoyée."))).finally(() => setBusy(false));
  };
  const field = 'w-full rounded-xl border border-[#DCE6F5] bg-white px-3 text-[13.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';
  return (
    <Sheet title="Écrire à l'équipe FidClic" onClose={onClose}>
      <div className="space-y-3 overflow-y-auto px-5 py-4">
        <p className="text-[12.5px] text-[#64748B]">Nous vous répondons ici, dans « Mes demandes », et par email — en général sous 24h.</p>
        <label className="block"><span className="mb-1 block text-[12.5px] font-medium text-[#475569]">Objet</span>
          <input value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} maxLength={200} placeholder="Ex. Ma carte ne s'ajoute pas à Apple Wallet" className={`${field} h-11`} /></label>
        <label className="block"><span className="mb-1 block text-[12.5px] font-medium text-[#475569]">Sujet</span>
          <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className={`${field} h-11`}>
            {cats.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select></label>
        <div>
          <span className="mb-1 block text-[12.5px] font-medium text-[#475569]">Message</span>
          <div className="rounded-xl border border-[#DCE6F5] focus-within:border-[#2F6BFF]">
            <textarea value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} rows={6} maxLength={10000}
                      placeholder="Décrivez votre situation : ce que vous faisiez, ce qui s'affiche, depuis quand…" className="block w-full resize-y rounded-xl bg-transparent px-3 py-2.5 text-[13.5px] text-[#0B1C3F] outline-none" />
            <UploadChips up={up} />
            <div className="flex items-center px-2 pb-2"><AttachButton onFiles={up.add} /><span className="text-[11.5px] text-[#94A3B8]">Captures, PDF… (10 Mo max par fichier)</span></div>
          </div>
        </div>
        {err && <p className="text-[12.5px] text-[#E11D48]">{err}</p>}
      </div>
      <footer className="flex justify-end gap-2 border-t border-[#EEF2F8] px-5 py-3">
        <button type="button" onClick={onClose} className="h-10 rounded-xl border border-[#DCE6F5] px-4 text-[13px] text-[#475569]">Annuler</button>
        <button type="button" onClick={submit} disabled={busy || !up.ready} className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 text-[13.5px] font-semibold text-white disabled:opacity-60">
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />} Envoyer
        </button>
      </footer>
    </Sheet>
  );
}

function Rating({ id, onDone }) {
  const [stars, setStars] = useState(0);
  const [hover, setHover] = useState(0);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const send = () => {
    if (!stars) { setErr('Choisissez une note.'); return; }
    setBusy(true);
    mySupportAPI.rate(id, { stars, comment }).then(onDone).catch((e) => setErr(errText(e, 'Note non enregistrée.'))).finally(() => setBusy(false));
  };
  return (
    <div className="rounded-2xl border border-[#FDE7B0] bg-[#FFFBEF] p-4">
      <p className="text-[13.5px] font-semibold text-[#0B1C3F]">Votre demande est résolue. Comment s'est passé l'échange ?</p>
      <div className="mt-2 flex gap-1" onMouseLeave={() => setHover(0)}>
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" aria-label={`${n} étoile${n > 1 ? 's' : ''}`} onMouseEnter={() => setHover(n)} onClick={() => { setStars(n); setErr(''); }}>
            <Star size={28} className={(hover || stars) >= n ? 'fill-[#F59E0B] text-[#F59E0B]' : 'text-[#E2C68A]'} />
          </button>
        ))}
      </div>
      <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} maxLength={1000} placeholder="Un commentaire ? (facultatif)"
                className="mt-2 block w-full rounded-xl border border-[#F3DFA9] bg-white px-3 py-2 text-[13px] outline-none focus:border-[#F59E0B]" />
      {err && <p className="mt-1 text-[12px] text-[#E11D48]">{err}</p>}
      <button type="button" onClick={send} disabled={busy} className="mt-2 inline-flex h-9 items-center gap-2 rounded-xl bg-[#F59E0B] px-4 text-[13px] font-semibold text-white disabled:opacity-60">
        {busy && <Loader2 size={14} className="animate-spin" />} Envoyer ma note
      </button>
    </div>
  );
}

function Thread({ id, onClose, onChanged }) {
  const [d, setD] = useState(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const up = useUploads(mySupportAPI.upload);
  const end = useRef(null);
  const area = useRef(null);
  const load = useCallback((quiet) => mySupportAPI.ticket(id).then(({ data }) => { setD(data); if (!quiet) onChanged(); })
    .catch((e) => setErr(errText(e, 'Demande introuvable.'))), [id, onChanged]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { const t = setInterval(() => { if (!document.hidden) load(true); }, 12000); return () => clearInterval(t); }, [load]);
  const count = d?.messages.length || 0;
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }); }, [count]);
  const groups = useMemo(() => {
    const out = [];
    (d?.messages || []).forEach((m) => {
      const day = new Date(m.created_at).toDateString();
      if (!out.length || out[out.length - 1].day !== day) out.push({ day, at: m.created_at, items: [] });
      out[out.length - 1].items.push(m);
    });
    return out;
  }, [d]);
  const insert = (s) => { const el = area.current; const a = el?.selectionStart ?? text.length; setText(text.slice(0, a) + s + text.slice(el?.selectionEnd ?? a)); };
  const send = () => {
    if (busy || (!text.trim() && !up.ids.length) || !up.ready) return;
    setBusy(true); setErr('');
    mySupportAPI.send(id, { body: text, attachments: up.ids }).then(() => { setText(''); up.clear(); load(); })
      .catch((e) => setErr(errText(e, "Le message n'a pas pu être envoyé."))).finally(() => setBusy(false));
  };
  const t = d?.ticket;
  return (
    <Sheet title={t ? t.subject : 'Demande'} onClose={onClose} wide>
      {!d ? (
        <div className="flex items-center justify-center gap-2 py-16 text-[13px] text-[#64748B]">{err || <><Loader2 size={15} className="animate-spin" /> Chargement…</>}</div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 border-b border-[#EEF2F8] px-5 py-2.5 text-[12.5px] text-[#64748B]">
            <StatusPill s={MERCHANT_TONE[t.status] || 'nouveau'} label={t.status_label} />
            <span>{t.category_label}</span><span>·</span><span>ouverte le {fullDate(t.created_at)}</span>
          </div>
          <div className="flex-1 space-y-4 overflow-y-auto bg-[#FBFCFF] px-5 py-4">
            {groups.map((g) => (
              <div key={g.day} className="space-y-4">
                <p className="text-center text-[11.5px] font-medium uppercase tracking-[.04em] text-[#94A3B8]">{dayLabel(g.at)}</p>
                {g.items.map((m) => {
                  const mine = m.author_type === 'merchant';
                  return (
                    <div key={m.id} className={`flex gap-2.5 ${mine ? 'flex-row-reverse' : ''}`}>
                      {mine ? <Avatar name={m.author_name} size={32} color="#0B1C3F" /> : <Avatar name="FidClic" size={32} color="#2F6BFF" />}
                      <div className="min-w-0 max-w-[84%]">
                        <p className={`mb-1 text-[12px] text-[#94A3B8] ${mine ? 'text-right' : ''}`}>
                          <strong className="font-semibold text-[#0B1C3F]">{mine ? 'Vous' : `${m.author_name} · Support FidClic`}</strong> · {clock(m.created_at)}
                        </p>
                        <div className={`rounded-2xl px-4 py-3 text-[13.5px] leading-[1.55] ${mine ? 'bg-[#2F6BFF] text-white' : 'border border-[#EAF0F8] bg-white text-[#1E293B]'}`}>
                          {m.body && <p className="whitespace-pre-wrap break-words">{m.body}</p>}
                          {m.attachments?.length > 0 && <div className="mt-2 flex flex-wrap gap-2">{m.attachments.map((a) => <Attachment key={a.id} a={a} fetchFile={fetchFile} />)}</div>}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ))}
            {!d.messages.length && <p className="py-8 text-center text-[13px] text-[#64748B]">Aucun message pour le moment.</p>}
            {t.can_rate && <Rating id={id} onDone={() => load()} />}
            {t.rating?.stars && (
              <p className="mx-auto flex w-fit items-center gap-1.5 rounded-full bg-[#FFF8E6] px-3 py-1.5 text-[12.5px] text-[#92400E]">
                <CheckCheck size={14} /> Merci pour votre note : {'★'.repeat(t.rating.stars)}{'☆'.repeat(5 - t.rating.stars)}
              </p>
            )}
            <div ref={end} />
          </div>
          <div className="border-t border-[#EEF2F8] px-4 pb-3 pt-2.5">
            {t.status === 'resolu' && <p className="mb-1.5 text-[11.5px] text-[#64748B]">Le problème revient ? Écrivez simplement : la demande sera rouverte.</p>}
            <div className="rounded-xl border border-[#DCE6F5] bg-white focus-within:border-[#2F6BFF]">
              <textarea ref={area} value={text} onChange={(e) => setText(e.target.value)} rows={2} maxLength={10000}
                        onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send(); }}
                        placeholder="Écrivez votre message…" className="block w-full resize-y rounded-xl bg-transparent px-3 py-2.5 text-[13.5px] text-[#0B1C3F] outline-none" />
              <UploadChips up={up} />
              <div className="flex items-center gap-1 px-2 pb-2">
                <AttachButton onFiles={up.add} />
                <EmojiButton onPick={insert} />
                <button type="button" onClick={send} disabled={busy || (!text.trim() && !up.ids.length) || !up.ready}
                        className="ml-auto inline-flex h-9 items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 text-[13px] font-semibold text-white disabled:opacity-50">
                  {busy ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />} Envoyer
                </button>
              </div>
            </div>
            {err && <p className="mt-1 text-[12px] text-[#E11D48]">{err}</p>}
          </div>
        </>
      )}
    </Sheet>
  );
}

export default function MyRequests({ newOpen, setNewOpen }) {
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState(null);
  const [all, setAll] = useState(false);
  const openId = params.get('ticket');
  const load = useCallback(() => mySupportAPI.tickets().then(({ data }) => setRows(data.rows)).catch(() => setRows([])), []);
  useEffect(() => { load(); const t = setInterval(() => { if (!document.hidden) load(); }, 30000); return () => clearInterval(t); }, [load]);
  const open = (id) => setParams((p) => { p.set('ticket', id); return p; });
  const close = () => { setParams((p) => { p.delete('ticket'); return p; }); load(); };
  const shown = all ? rows || [] : (rows || []).slice(0, 5);
  const unread = (rows || []).reduce((a, r) => a + (r.unread ? 1 : 0), 0);
  return (
    <section id="mes-demandes" className="mt-5 rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <header className="mb-3 flex flex-wrap items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><Inbox size={19} /></span>
        <div className="min-w-0 flex-1">
          <h2 className="flex items-center gap-2 text-[15px] font-bold leading-tight text-[#0B1C3F]">Mes demandes
            {unread > 0 && <span className="rounded-full bg-[#2F6BFF] px-2 py-0.5 text-[11px] font-semibold text-white">{unread} nouvelle{unread > 1 ? 's' : ''} réponse{unread > 1 ? 's' : ''}</span>}
          </h2>
          <p className="mt-0.5 text-[12.5px] text-[#64748B]">Vos échanges avec l'équipe FidClic. Les réponses arrivent aussi par email.</p>
        </div>
        <button type="button" onClick={() => setNewOpen(true)} className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 text-[13px] font-semibold text-white"><Plus size={16} /> Nouvelle demande</button>
      </header>
      {!rows ? (
        <div className="flex items-center justify-center gap-2 py-8 text-[13px] text-[#64748B]"><Loader2 size={15} className="animate-spin" /> Chargement…</div>
      ) : !rows.length ? (
        <div className="rounded-xl border border-dashed border-[#D9E4F7] px-4 py-8 text-center">
          <MessageSquareText size={22} className="mx-auto text-[#94A3B8]" />
          <p className="mt-2 text-[13px] font-medium text-[#0B1C3F]">Aucune demande pour le moment</p>
          <p className="mt-1 text-[12.5px] text-[#64748B]">Une question que l'assistant ne règle pas ? Écrivez-nous.</p>
        </div>
      ) : (
        <ul className="divide-y divide-[#F1F5F9]">
          {shown.map((r) => (
            <li key={r.id}>
              <button type="button" onClick={() => open(r.id)} className="flex w-full items-center gap-3 rounded-xl px-2 py-3 text-left hover:bg-[#F8FAFF]">
                <span className="min-w-0 flex-1">
                  <span className={`block truncate text-[13.5px] text-[#0B1C3F] ${r.unread ? 'font-bold' : 'font-semibold'}`}>{r.subject}</span>
                  <span className="block truncate text-[12.5px] text-[#64748B]">{r.category_label} · {r.preview}</span>
                </span>
                <span className="flex shrink-0 flex-col items-end gap-1">
                  <span className="text-[11.5px] text-[#64748B]">{when(r.last_message_at)}</span>
                  <StatusPill s={MERCHANT_TONE[r.status] || 'nouveau'} label={r.status_label} />
                </span>
                {r.unread > 0 ? <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[#2F6BFF] text-[10.5px] font-bold text-white">{r.unread}</span>
                  : r.can_rate ? <Star size={17} className="shrink-0 text-[#F59E0B]" aria-label="À noter" /> : <ChevronRight size={17} className="shrink-0 text-[#CBD5E1]" />}
              </button>
            </li>
          ))}
        </ul>
      )}
      {rows && rows.length > 5 && <button type="button" onClick={() => setAll((a) => !a)} className="mt-2 text-[12.5px] font-medium text-[#2F6BFF] hover:underline">{all ? 'Voir moins' : `Voir les ${rows.length} demandes`}</button>}
      {openId && <Thread id={openId} onClose={close} onChanged={load} />}
      {newOpen && <NewRequest onClose={() => setNewOpen(false)} onDone={(id) => { setNewOpen(false); load(); open(id); }} />}
    </section>
  );
}
