import React, { useEffect, useRef, useState } from 'react';
import { Download, FileText, Paperclip, Smile, X, Loader2, FileSpreadsheet, FileArchive, Film } from 'lucide-react';

/* Shared by the super admin's « Centre de support » and the merchant's
   « Mes demandes » (features/support_center.py). */

export const STATUS_TONE = {
  nouveau: ['#EAF1FF', '#2F6BFF'], en_cours: ['#E6F4FF', '#0B74D1'], en_attente: ['#FFF4DB', '#D97706'],
  urgent: ['#FDECEF', '#E11D48'], resolu: ['#E7F7EE', '#0F8B58'],
};
export const PRIORITY_TONE = { haute: ['#FDECEF', '#E11D48'], normale: ['#FFF4DB', '#D97706'], basse: ['#F1F5F9', '#64748B'] };
export const PRIORITY_BAR = { haute: '#E11D48', normale: '#F59E0B', basse: '#CBD5E1' };
export const TAG_TONE = {
  rose: ['#FDECEF', '#E11D48'], blue: ['#EAF1FF', '#2F6BFF'], green: ['#E7F7EE', '#0F8B58'], amber: ['#FFF4DB', '#D97706'],
  violet: ['#F3EEFF', '#7C3AED'], slate: ['#F1F5F9', '#475569'],
};
const AVATAR_BG = ['#E2462F', '#0B74D1', '#0F8B58', '#F59E0B', '#7C3AED', '#0B1C3F', '#DB2777', '#0EA5E9'];

export const Pill = ({ tone, children, className = '' }) => (
  <span className={`inline-flex items-center whitespace-nowrap rounded-md px-2 py-[3px] text-[11.5px] font-medium ${className}`} style={{ background: tone[0], color: tone[1] }}>{children}</span>
);
export const StatusPill = ({ s, label }) => <Pill tone={STATUS_TONE[s] || STATUS_TONE.nouveau}>{label}</Pill>;

export const initials = (name) => (name || '?').replace(/[^\p{L}\p{N}\s'-]/gu, ' ').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase() || '?';
export const colorOf = (name) => AVATAR_BG[[...(name || '?')].reduce((a, c) => a + c.charCodeAt(0), 0) % AVATAR_BG.length];

export function Avatar({ name, logo, size = 36, color }) {
  const [broken, setBroken] = useState(false);
  if (logo && !broken) {
    return <img src={logo} alt="" onError={() => setBroken(true)} className="shrink-0 rounded-full border border-[#EDF1F7] bg-white object-cover" style={{ width: size, height: size }} />;
  }
  return (
    <span className="flex shrink-0 items-center justify-center rounded-full font-bold text-white" style={{ width: size, height: size, background: color || colorOf(name), fontSize: Math.max(11, size * 0.36) }}>
      {initials(name)}
    </span>
  );
}

export function when(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = (day(now) - day(d)) / 86400000;
  if (diff === 0) return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  if (diff === 1) return 'Hier';
  return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
}
export const clock = (iso) => (iso ? new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) : '');
export const fullDate = (iso) => (iso ? new Date(iso).toLocaleString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '');
export const dayLabel = (iso) => {
  const d = new Date(iso);
  const t = new Date();
  const same = (a, b) => a.toDateString() === b.toDateString();
  if (same(d, t)) return "Aujourd'hui";
  const y = new Date(t); y.setDate(t.getDate() - 1);
  if (same(d, y)) return 'Hier';
  return d.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' });
};
export const size = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1).replace('.', ',')} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
export const errText = (e, fallback) => {
  const d = e?.response?.data?.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d) && d[0]?.msg) return d[0].msg;
  return fallback;
};

/* An attachment: images show a thumbnail; every file downloads with the
   signed-in user's rights (the file route checks who may see it). */
export function Attachment({ a, fetchFile }) {
  const [thumb, setThumb] = useState(null);
  const [busy, setBusy] = useState(false);
  const image = (a.type || '').startsWith('image/');
  useEffect(() => {
    if (!image) return undefined;
    let url = null; let alive = true;
    fetchFile(a.id, true).then(({ data }) => { if (alive) { url = URL.createObjectURL(data); setThumb(url); } }).catch(() => {});
    return () => { alive = false; if (url) URL.revokeObjectURL(url); };
  }, [a.id, image, fetchFile]);
  const download = () => {
    setBusy(true);
    fetchFile(a.id, false).then(({ data }) => {
      const url = URL.createObjectURL(data);
      const el = document.createElement('a'); el.href = url; el.download = a.name; el.click();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    }).catch(() => {}).finally(() => setBusy(false));
  };
  const Icon = /sheet|excel|csv/.test(a.type) ? FileSpreadsheet : /zip/.test(a.type) ? FileArchive : /video/.test(a.type) ? Film : FileText;
  return (
    <div className="flex w-full max-w-[236px] items-center gap-3 rounded-xl border border-[#E6ECF5] bg-white p-2 pr-3 shadow-[0_1px_2px_rgba(11,28,63,.04)]">
      {image && thumb
        ? <button type="button" onClick={() => window.open(thumb, '_blank', 'noopener')} className="h-11 w-14 shrink-0 overflow-hidden rounded-md bg-[#0B1C3F]"><img src={thumb} alt="" className="h-full w-full object-cover" /></button>
        : <span className="flex h-11 w-14 shrink-0 items-center justify-center rounded-md bg-[#F1F5F9] text-[#64748B]"><Icon size={20} /></span>}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[12.5px] font-semibold text-[#0B1C3F]" title={a.name}>{a.name}</span>
        <span className="block text-[11.5px] text-[#64748B]">{size(a.size)}</span>
      </span>
      <button type="button" onClick={download} aria-label={`Télécharger ${a.name}`} className="shrink-0 text-[#2F6BFF] hover:text-[#1E4FD8]">
        {busy ? <Loader2 size={17} className="animate-spin" /> : <Download size={17} />}
      </button>
    </div>
  );
}

const EMOJIS = ['😀', '😊', '🙂', '😉', '😅', '🙏', '👍', '👌', '👏', '🎉', '✅', '❌', '⚠️', '💡', '📎', '📱', '💳', '🎁', '⭐', '❤️', '🔥', '⏳', '📅', '📞', '✉️', '🔒', '🛠️', '📊', '🤝', '👋', '😕', '🙌'];

export function EmojiButton({ onPick }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const out = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', out);
    return () => document.removeEventListener('mousedown', out);
  }, [open]);
  return (
    <span ref={ref} className="relative">
      <button type="button" aria-label="Ajouter un emoji" onClick={() => setOpen((o) => !o)} className="flex h-8 w-8 items-center justify-center rounded-lg text-[#64748B] hover:bg-[#F4F7FC] hover:text-[#0B1C3F]"><Smile size={18} /></button>
      {open && (
        <span className="absolute bottom-10 left-0 z-30 grid w-[248px] grid-cols-8 gap-0.5 rounded-xl border border-[#EDF1F7] bg-white p-2 shadow-lg">
          {EMOJIS.map((e) => <button key={e} type="button" onClick={() => { onPick(e); setOpen(false); }} className="h-7 w-7 rounded-md text-[17px] hover:bg-[#F4F7FC]">{e}</button>)}
        </span>
      )}
    </span>
  );
}

/* Files picked for a message: each one uploads at once, shows its progress,
   and can be removed before sending. */
export function useUploads(uploadFn, max = 5) {
  const [files, setFiles] = useState([]);
  const [error, setError] = useState('');
  const add = (list) => {
    setError('');
    const room = max - files.length;
    [...list].slice(0, Math.max(0, room)).forEach((file) => {
      const key = `${file.name}-${file.size}-${Math.random()}`;
      if (file.size > 10 * 1024 * 1024) { setError(`« ${file.name} » dépasse 10 Mo.`); return; }
      setFiles((f) => [...f, { key, name: file.name, size: file.size, pct: 0 }]);
      uploadFn(file, (ev) => setFiles((f) => f.map((x) => (x.key === key ? { ...x, pct: ev.total ? Math.round((ev.loaded / ev.total) * 100) : 50 } : x))))
        .then(({ data }) => setFiles((f) => f.map((x) => (x.key === key ? { ...x, id: data.id, pct: 100 } : x))))
        .catch((e) => { setFiles((f) => f.filter((x) => x.key !== key)); setError(errText(e, `« ${file.name} » n'a pas pu être ajouté.`)); });
    });
    if (list.length > room) setError(`${max} pièces jointes maximum par message.`);
  };
  const remove = (key) => setFiles((f) => f.filter((x) => x.key !== key));
  const ready = files.every((f) => f.id);
  return { files, add, remove, clear: () => setFiles([]), ids: files.filter((f) => f.id).map((f) => f.id), ready, error, setError };
}

export function AttachButton({ onFiles, disabled }) {
  const ref = useRef(null);
  return (
    <>
      <button type="button" aria-label="Joindre un fichier" disabled={disabled} onClick={() => ref.current?.click()} className="flex h-8 w-8 items-center justify-center rounded-lg text-[#64748B] hover:bg-[#F4F7FC] hover:text-[#0B1C3F] disabled:opacity-40"><Paperclip size={18} /></button>
      <input ref={ref} type="file" multiple hidden accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.zip,.mp4,.mov"
             onChange={(e) => { onFiles(e.target.files); e.target.value = ''; }} />
    </>
  );
}

export function UploadChips({ up }) {
  if (!up.files.length && !up.error) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 px-1 pb-2">
      {up.files.map((f) => (
        <span key={f.key} className="inline-flex max-w-[220px] items-center gap-1.5 rounded-lg border border-[#DCE6FA] bg-[#F5F8FF] px-2 py-1 text-[12px] text-[#0B1C3F]">
          {f.id ? <Paperclip size={13} className="shrink-0 text-[#2F6BFF]" /> : <Loader2 size={13} className="shrink-0 animate-spin text-[#2F6BFF]" />}
          <span className="truncate">{f.name}</span>
          <span className="shrink-0 text-[#64748B]">{f.id ? size(f.size) : `${f.pct}%`}</span>
          <button type="button" aria-label={`Retirer ${f.name}`} onClick={() => up.remove(f.key)} className="shrink-0 text-[#94A3B8] hover:text-[#E11D48]"><X size={13} /></button>
        </span>
      ))}
      {up.error && <span className="text-[12px] text-[#E11D48]">{up.error}</span>}
    </div>
  );
}
