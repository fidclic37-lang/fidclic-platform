import React, { useCallback, useEffect, useRef, useState } from 'react';
import { QRCodeCanvas } from 'qrcode.react';
import {
  Users, Link2, QrCode, Share2, Copy, Info, Download, Printer, Store, Settings, CheckCircle2,
  XCircle, Loader2, Mail, MessageSquare, MoreHorizontal, Eye, Pencil, ExternalLink, Gift,
  Star, Cake, Sparkles, X, Check, Coffee, ArrowUp, ArrowDown, RotateCcw,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';

/* Paramètres › Lien d'inscription & QR — the shop's signup link, its QR code,
   what they bring in, and the page a client lands on.

   The link is https://<app>/inscription/<name>. Renaming it keeps every
   older name working (a QR code already printed on a counter must not break),
   so the owner can change it without fear. The QR code carries ?src=qr_store,
   which is how "Scans QR" and the Clients page's acquisition know a signup
   came from the counter; Facebook and Instagram shares carry their own tag. */

const nf = (n) => new Intl.NumberFormat('fr-FR').format(n ?? 0);
const pct = (n, digits = 1) => `${new Intl.NumberFormat('fr-FR', { maximumFractionDigits: digits }).format(n)}`;

function WhatsAppIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
      <circle cx="12" cy="12" r="11" fill="#25D366" />
      <path fill="#fff" d="M16.9 14.3c-.3-.1-1.6-.8-1.8-.9-.2-.1-.4-.1-.6.1l-.8 1c-.1.2-.3.2-.5.1-.3-.1-1.1-.4-2.1-1.3-.8-.7-1.3-1.5-1.4-1.8-.1-.3 0-.4.1-.5l.4-.5.2-.4c.1-.1 0-.3 0-.4l-.8-1.9c-.2-.5-.4-.4-.6-.4h-.5c-.2 0-.4.1-.6.3-.2.2-.8.8-.8 2s.8 2.3.9 2.5c.1.2 1.6 2.5 4 3.5 2 .8 2.4.6 2.8.6.5 0 1.6-.6 1.8-1.3.2-.6.2-1.2.1-1.3 0-.1-.2-.2-.5-.3z" />
    </svg>
  );
}
function FacebookIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
      <circle cx="12" cy="12" r="11" fill="#1877F2" />
      <path fill="#fff" d="M13.3 19v-6h2l.3-2.4h-2.3V9.1c0-.7.2-1.1 1.2-1.1h1.2V5.9c-.2 0-1-.1-1.8-.1-1.8 0-3 1.1-3 3.1v1.8h-2V13h2v6h2.4z" />
    </svg>
  );
}
function InstagramIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
      <defs>
        <linearGradient id="ig-g" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#FEDA75" /><stop offset=".35" stopColor="#FA7E1E" />
          <stop offset=".65" stopColor="#D62976" /><stop offset="1" stopColor="#4F5BD5" />
        </linearGradient>
      </defs>
      <rect x="1.5" y="1.5" width="21" height="21" rx="6" fill="url(#ig-g)" />
      <rect x="6.5" y="6.5" width="11" height="11" rx="3.5" fill="none" stroke="#fff" strokeWidth="1.8" />
      <circle cx="12" cy="12" r="2.6" fill="none" stroke="#fff" strokeWidth="1.8" />
      <circle cx="16.3" cy="7.7" r="1" fill="#fff" />
    </svg>
  );
}
/* Line-drawn leaves for the counter poster, as in the design. */
function Leaves({ className, flip }) {
  return (
    <svg viewBox="0 0 80 90" className={className} aria-hidden="true"
         style={flip ? { transform: 'scaleX(-1)' } : undefined}>
      <g fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
        <path d="M10 85 C 30 60, 42 40, 60 8" />
        <path d="M30 58 C 16 54, 10 44, 12 34 C 24 36, 31 46, 30 58 Z" />
        <path d="M42 38 C 34 30, 34 18, 40 10 C 48 18, 48 30, 42 38 Z" />
        <path d="M36 50 C 48 48, 58 40, 62 30 C 50 30, 40 38, 36 50 Z" />
        <path d="M20 72 C 30 72, 38 66, 42 58 C 32 58, 24 64, 20 72 Z" />
      </g>
    </svg>
  );
}

/* The shop's logo from its Carte de fidélité — its initial when there is
   none, or when the image does not load. */
function ShopLogo({ url, name }) {
  const [broken, setBroken] = useState(false);
  if (url && !broken) {
    return <img src={url} alt="" onError={() => setBroken(true)} className="h-7 w-7 rounded-full object-cover" />;
  }
  return (
    <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#0B1C3F] text-[11px] font-bold text-white">
      {(name || '?').slice(0, 1).toUpperCase()}
    </span>
  );
}

function CardHead({ icon: Icon, title, subtitle, right }) {
  return (
    <div className="mb-4 flex items-start gap-3">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]">
        <Icon size={19} />
      </span>
      <div className="min-w-0 flex-1">
        <h3 className="text-[15.5px] font-bold text-[#0B1C3F]">{title}</h3>
        {subtitle && <p className="mt-0.5 text-[12.5px] leading-snug text-[#64748B]">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

function Kpi({ icon: Icon, label, hint, value, delta, deltaUnit = '%', note }) {
  const up = delta != null && delta >= 0;
  return (
    <div className="flex items-start gap-4 rounded-2xl border border-[#E6EEFB] bg-white p-5">
      <span className="flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]">
        <Icon size={24} />
      </span>
      <div className="min-w-0">
        <p className="text-[13px] font-medium text-[#0B1C3F]">
          {label} {hint && <span className="font-normal text-[#64748B]">{hint}</span>}
        </p>
        <div className="mt-1 flex flex-wrap items-baseline gap-2.5">
          <span className="text-[24px] font-bold leading-none text-[#0B1C3F]">{value}</span>
          {delta != null && (
            <span className={`inline-flex items-center gap-0.5 text-[12px] font-semibold ${up ? 'text-[#0F8B58]' : 'text-[#E11D48]'}`}>
              {up ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
              {up ? '+' : '−'}{pct(Math.abs(delta))}{deltaUnit}
            </span>
          )}
        </div>
        <p className="mt-1.5 text-[12.5px] text-[#64748B]">{note}</p>
      </div>
    </div>
  );
}

/* ------------------------------------------------ Personnaliser la page -- */
function PageModal({ initial, defaults, limits, onClose, onSaved }) {
  const [d, setD] = useState(() => ({
    ...initial, benefits: [...initial.benefits, '', '', '', ''].slice(0, limits.benefits),
  }));
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const save = async (e) => {
    e.preventDefault();
    setSaving(true); setError('');
    try {
      const { data } = await ownerAPI.saveJoinPage({ ...d, benefits: d.benefits.filter((b) => b.trim()) });
      onSaved(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Enregistrement impossible.');
    } finally { setSaving(false); }
  };
  const field = 'w-full rounded-lg border border-[#E2E8F0] px-3 text-[14px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';
  const Counter = ({ v, max }) => <span className="font-normal text-[#94A3B8]">{v.length}/{max}</span>;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0B1C3F]/40 p-4" role="dialog" aria-modal="true"
         aria-label="Personnaliser la page">
      <form onSubmit={save} className="max-h-[92vh] w-full max-w-[520px] overflow-y-auto rounded-2xl bg-white p-6 shadow-[0_40px_90px_-40px_rgba(11,28,63,.6)]">
        <div className="mb-5 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[19px] font-bold text-[#0B1C3F]">Personnaliser la page</h2>
            <p className="text-[13px] text-[#64748B]">Ce que vos clients lisent en ouvrant votre lien.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Fermer"
                  className="flex h-9 w-9 items-center justify-center rounded-lg text-[#64748B] hover:bg-[#F4F7FC]"><X size={18} /></button>
        </div>
        <label className="mb-1.5 flex justify-between text-[13px] font-semibold text-[#334155]">Titre <Counter v={d.title} max={limits.title} /></label>
        <input value={d.title} maxLength={limits.title} onChange={(e) => setD({ ...d, title: e.target.value })} className={`${field} mb-4 h-11`} />
        <label className="mb-1.5 flex justify-between text-[13px] font-semibold text-[#334155]">Sous-titre <Counter v={d.subtitle} max={limits.subtitle} /></label>
        <textarea rows={2} value={d.subtitle} maxLength={limits.subtitle} onChange={(e) => setD({ ...d, subtitle: e.target.value })} className={`${field} mb-4 py-2.5`} />
        <p className="mb-1.5 text-[13px] font-semibold text-[#334155]">Avantages mis en avant</p>
        <div className="mb-4 space-y-2">
          {d.benefits.map((b, i) => (
            <input key={i} value={b} maxLength={limits.benefit} placeholder={`Avantage ${i + 1}`}
                   onChange={(e) => setD({ ...d, benefits: d.benefits.map((x, j) => (j === i ? e.target.value : x)) })}
                   className={`${field} h-10`} />
          ))}
        </div>
        <label className="mb-1.5 flex justify-between text-[13px] font-semibold text-[#334155]">Texte du bouton <Counter v={d.button} max={limits.button} /></label>
        <input value={d.button} maxLength={limits.button} onChange={(e) => setD({ ...d, button: e.target.value })} className={`${field} mb-4 h-11`} />
        {error && <p className="mb-4 rounded-lg bg-[#FEF2F2] px-3 py-2.5 text-[13px] text-[#B91C1C]">{error}</p>}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <button type="button" onClick={() => setD({ ...defaults, benefits: [...defaults.benefits] })}
                  className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[#64748B] hover:text-[#2F6BFF]">
            <RotateCcw size={14} /> Texte par défaut
          </button>
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="h-11 rounded-xl border border-[#E2E8F0] px-5 text-[14px] font-semibold text-[#334155]">Annuler</button>
            <button type="submit" disabled={saving}
                    className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 text-[14px] font-semibold text-white hover:bg-[#2559DB] disabled:opacity-60">
              {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />} Enregistrer
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

/* ------------------------------------------------------------------ page -- */
export default function LienInscriptionPage() {
  const [d, setD] = useState(null);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [draft, setDraft] = useState('');
  const [check, setCheck] = useState({ state: 'idle' });   // idle | checking | ok | taken
  const [savingSlug, setSavingSlug] = useState(false);
  const [editingPage, setEditingPage] = useState(false);
  const slugInput = useRef(null);
  const bigQr = useRef(null);
  const toastTimer = useRef(null);

  const say = (msg) => {
    setToast(msg);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(''), 2600);
  };
  useEffect(() => () => clearTimeout(toastTimer.current), []);

  const load = useCallback(() => {
    ownerAPI.joinLink()
      .then(({ data }) => { setD(data); setDraft(data.shop.slug); setError(''); })
      .catch((e) => setError(e?.response?.data?.detail || 'Impossible de charger votre lien.'));
  }, []);
  useEffect(() => { load(); }, [load]);

  const origin = typeof window !== 'undefined' ? window.location.origin : 'https://app.fidclic.com';
  const host = typeof window !== 'undefined' ? window.location.host : 'app.fidclic.com';
  const slug = d?.shop.slug || '';
  const url = `${origin}/inscription/${slug}`;
  const tagged = (src) => `${url}?src=${src}`;
  const qrUrl = tagged('qr_store');
  const shopName = d?.shop.name || 'Votre commerce';
  const message = `Rejoignez le programme de fidélité de ${shopName} : `;

  // Live availability check for the custom name — a moment after typing stops.
  useEffect(() => {
    if (!d) return undefined;
    const typed = draft.trim();
    if (!typed) { setCheck({ state: 'idle' }); return undefined; }
    setCheck({ state: 'checking' });
    const id = setTimeout(() => {
      ownerAPI.joinSlugCheck(typed)
        .then(({ data }) => setCheck(data.available ? { state: 'ok', slug: data.slug } : { state: 'taken', reason: data.reason }))
        .catch(() => setCheck({ state: 'idle' }));
    }, 350);
    return () => clearTimeout(id);
  }, [draft, d]);

  const copy = async (text, msg = 'Lien copié') => {
    try { await navigator.clipboard.writeText(text); say(msg); }
    catch { say('Copie impossible — sélectionnez le lien à la main.'); }
  };

  const saveSlug = async () => {
    if (check.state !== 'ok') return;
    setSavingSlug(true);
    try {
      const { data } = await ownerAPI.saveJoinSlug(check.slug);
      setD(data); setDraft(data.shop.slug);
      say("Lien mis à jour — l'ancien lien continue de fonctionner.");
    } catch (e) {
      setCheck({ state: 'taken', reason: e?.response?.data?.detail || 'Ce nom ne peut pas être utilisé.' });
    } finally { setSavingSlug(false); }
  };

  const qrDataUrl = () => bigQr.current?.toDataURL('image/png');
  const downloadQr = () => {
    const data = qrDataUrl();
    if (!data) return;
    const a = document.createElement('a');
    a.href = data; a.download = `qr-code-${slug}.png`;
    document.body.appendChild(a); a.click(); a.remove();
    say('QR code téléchargé');
  };
  const printPoster = () => {
    const data = qrDataUrl();
    const w = window.open('', '_blank', 'width=720,height=960');
    if (!w || !data) { say("Autorisez les fenêtres pop-up pour imprimer."); return; }
    const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    w.document.write(`<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>QR code — ${esc(shopName)}</title>
      <style>@page{size:A5;margin:0}*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,sans-serif;-webkit-print-color-adjust:exact;print-color-adjust:exact}
      .p{width:148mm;height:210mm;background:#0B2A5B;color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:18mm}
      .s{font-size:16pt;font-weight:600;margin-bottom:12mm}.t{font-size:26pt;font-weight:800;line-height:1.15;margin:0 0 7mm}
      .u{font-size:12pt;line-height:1.45;opacity:.92;margin:0 0 10mm}.q{background:#fff;border-radius:6mm;padding:5mm}.q img{width:62mm;height:62mm;display:block}
      .f{margin-top:9mm;font-size:9.5pt;opacity:.75}</style></head><body><div class="p">
      <div class="s">${esc(shopName)}</div><h1 class="t">${esc(d.page.title)}</h1>
      <p class="u">Scannez le QR code<br>et profitez d'avantages exclusifs.</p>
      <div class="q"><img src="${data}" alt=""></div><div class="f">${esc(url.replace(/^https?:\/\//, ''))}</div>
      </div><script>window.onload=function(){setTimeout(function(){window.print()},250)}<\/script></body></html>`);
    w.document.close();
  };

  const share = async (kind) => {
    const plain = message + url;
    if (kind === 'whatsapp') window.open(`https://wa.me/?text=${encodeURIComponent(plain)}`, '_blank', 'noopener');
    if (kind === 'email') window.location.href = `mailto:?subject=${encodeURIComponent(`Programme de fidélité — ${shopName}`)}&body=${encodeURIComponent(plain)}`;
    if (kind === 'sms') window.location.href = `sms:?&body=${encodeURIComponent(plain)}`;
    if (kind === 'facebook') window.open(`https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(tagged('facebook'))}`, '_blank', 'noopener');
    if (kind === 'instagram') copy(tagged('instagram'), 'Lien copié — collez-le dans votre bio ou vos stories Instagram.');
    if (kind === 'copy') copy(url);
    if (kind === 'more') {
      if (navigator.share) {
        try { await navigator.share({ title: shopName, text: message, url }); } catch { /* closed */ }
      } else copy(url);
    }
  };

  if (!d) {
    return error ? (
      <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{error}</p>
    ) : (
      <div className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]">
        <Loader2 size={16} className="animate-spin" /> Chargement…
      </div>
    );
  }

  const s = d.stats;
  const since = s.tracking_since
    ? new Date(s.tracking_since).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' }) : null;
  const measured = (note) => (since ? note : 'Mesure lancée à la première visite');
  const cardCls = 'rounded-2xl border border-[#E6EEFB] bg-white p-5';
  const unchanged = draft.trim() && check.slug === slug;

  return (
    <div>
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3.5">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#E6EEFB] text-[#2F6BFF]">
            <Users size={22} />
          </span>
          <div>
            <h2 className="text-[21px] font-bold leading-tight text-[#0B1C3F]">Lien d&apos;inscription &amp; QR</h2>
            <p className="mt-0.5 text-[14px] text-[#475569]">Permettez à vos clients de rejoindre facilement votre programme de fidélité.</p>
          </div>
        </div>
        <a href={`${url}?preview=1`} target="_blank" rel="noreferrer"
           className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#2F6BFF] px-5 text-[14.5px] font-medium text-white shadow-[0_10px_24px_-14px_rgba(47,107,255,.9)] hover:bg-[#2559DB]">
          Aperçu de la page client <ExternalLink size={16} />
        </a>
      </header>

      {/* the four figures */}
      <div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={Users} label="Nouveaux inscrits" hint={`(${s.window_days} jours)`} value={nf(s.new_signups.value)}
             delta={s.new_signups.delta_pct} note={`vs. ${s.window_days} jours précédents`} />
        <Kpi icon={Link2} label="Total des inscrits" value={nf(s.total.value)} note="Depuis le lancement" />
        <Kpi icon={QrCode} label="Scans QR" hint={`(${s.window_days} jours)`} value={nf(s.qr_scans.value)}
             delta={s.qr_scans.delta_pct}
             note={s.qr_scans.delta_pct != null ? `vs. ${s.window_days} jours précédents` : measured(`Mesuré depuis le ${since}`)} />
        <Kpi icon={Share2} label="Taux de conversion"
             value={s.conversion.value == null ? '—' : `${pct(s.conversion.value)}%`}
             delta={s.conversion.delta_pts} deltaUnit=" pt"
             note={s.conversion.value == null ? measured('Pas encore de visite ce mois-ci') : 'Visiteurs → Inscrits'} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-[1fr_1fr_0.82fr]">
        {/* Lien d'inscription */}
        <section className={cardCls}>
          <CardHead icon={Link2} title="Lien d'inscription"
                    subtitle="Copiez et partagez ce lien pour inviter vos clients à rejoindre votre programme." />
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="flex h-11 min-w-0 flex-1 items-center overflow-hidden rounded-lg border border-[#E2E8F0] bg-white">
              <span className="min-w-0 flex-1 truncate px-3 text-[13px] text-[#0B1C3F]">{url}</span>
              <button type="button" onClick={() => copy(url)} aria-label="Copier le lien"
                      className="flex h-full w-11 shrink-0 items-center justify-center border-l border-[#E2E8F0] text-[#2F6BFF] hover:bg-[#F6F9FF]">
                <Copy size={17} />
              </button>
            </div>
            <button type="button"
                    onClick={() => { slugInput.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }); slugInput.current?.focus(); }}
                    className="h-11 shrink-0 rounded-lg bg-[#2F6BFF] px-3.5 text-[12.5px] font-semibold text-white hover:bg-[#2559DB]">
              Personnaliser le lien
            </button>
          </div>
          <div className="mt-5 flex items-center gap-3 rounded-lg bg-[#F2F7FF] px-3.5 py-3">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[#2F6BFF] text-white"><Info size={12} strokeWidth={3} /></span>
            <p className="text-[12px] text-[#1E4FD8]">Vous pouvez personnaliser votre lien pour le rendre plus simple et mémorable.</p>
          </div>
        </section>

        {/* QR Code */}
        <section className={cardCls}>
          <CardHead icon={QrCode} title="QR Code" subtitle="Téléchargez et utilisez votre QR code pour l'afficher en magasin." />
          <div className="flex flex-wrap items-center gap-4">
            <div className="shrink-0 rounded-xl border border-[#EEF3FB] bg-white p-3 shadow-[0_8px_24px_-16px_rgba(11,28,63,.35)]">
              <QRCodeCanvas value={qrUrl} size={128} level="M" />
            </div>
            <div className="flex min-w-[170px] flex-1 flex-col gap-2.5">
              <button type="button" onClick={downloadQr}
                      className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-[#2F6BFF] px-3 text-[12.5px] font-semibold text-white hover:bg-[#2559DB]">
                <Download size={15} /> Télécharger le QR code
              </button>
              <button type="button" onClick={printPoster}
                      className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-[#2F6BFF] bg-white px-3 text-[12.5px] font-semibold text-[#2F6BFF] hover:bg-[#F6F9FF]">
                <Printer size={15} /> Imprimer le QR code
              </button>
              <button type="button" onClick={() => copy(url)}
                      className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-[#E2E8F0] bg-white px-3 text-[12.5px] font-medium text-[#0B1C3F] hover:border-[#C9DBFB]">
                <Pencil size={14} /> Copier le lien
              </button>
            </div>
          </div>
          {/* The high-resolution QR the download and the print use. */}
          <div className="hidden"><QRCodeCanvas ref={bigQr} value={qrUrl} size={1024} level="M" marginSize={2} /></div>
        </section>

        {/* QR à afficher en magasin */}
        <section className={`${cardCls} lg:col-span-2 xl:col-span-1 xl:row-span-2`}>
          <CardHead icon={Store} title="QR Code à afficher en magasin"
                    subtitle="Voici un aperçu de ce que vous pouvez afficher sur vos supports (comptoir, tables, affiches...)." />
          <button type="button" onClick={printPoster} title="Imprimer l'affiche"
                  className="group relative mx-auto block w-full max-w-[250px] overflow-hidden rounded-md bg-[#0B2A5B] px-5 pb-6 pt-6 text-center text-white shadow-[0_18px_40px_-24px_rgba(11,28,63,.9)]">
            <Leaves className="absolute -left-2 bottom-2 h-20 w-16 text-white/35" />
            <Leaves className="absolute -right-1 top-24 h-20 w-16 text-white/30" flip />
            <p className="relative text-[13px] font-semibold">{shopName}</p>
            <p className="relative mx-auto mt-4 max-w-[190px] text-[19px] font-bold leading-[1.2]">{d.page.title}</p>
            <p className="relative mt-4 text-[11.5px] leading-snug text-white/90">Scannez le QR code<br />et profitez d&apos;avantages exclusifs.</p>
            <span className="relative mx-auto mt-4 inline-block rounded-md bg-white p-1.5">
              <QRCodeCanvas value={qrUrl} size={62} level="M" />
            </span>
            <Coffee className="absolute bottom-3 right-4 h-7 w-7 text-white/85" strokeWidth={1.4} />
            <span className="absolute inset-0 flex items-center justify-center bg-[#0B1C3F]/55 text-[13px] font-semibold opacity-0 transition group-hover:opacity-100">
              <Printer size={16} className="mr-2" /> Imprimer l&apos;affiche
            </span>
          </button>
        </section>

        {/* Personnalisation du lien */}
        <section className={cardCls}>
          <CardHead icon={Settings} title="Personnalisation du lien" subtitle="Personnalisez l'URL de votre page d'inscription." />
          <label htmlFor="join-slug" className="mb-2 block text-[13px] font-medium text-[#0B1C3F]">Nom personnalisé</label>
          <div className="flex h-11 overflow-hidden rounded-lg border border-[#E2E8F0] bg-white focus-within:border-[#2F6BFF]">
            <span className="hidden items-center bg-[#F1F5F9] px-3 text-[12.5px] text-[#64748B] sm:flex">{host}/inscription/</span>
            <input id="join-slug" ref={slugInput} value={draft} maxLength={d.limits.slug_max + 10}
                   onChange={(e) => setDraft(e.target.value)}
                   onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); if (!unchanged) saveSlug(); } }}
                   className="min-w-0 flex-1 border-0 px-3 text-[14px] text-[#0B1C3F] outline-none" />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {check.state === 'checking' && (
              <p className="flex items-center gap-2 text-[12.5px] text-[#64748B]"><Loader2 size={14} className="animate-spin" /> Vérification…</p>
            )}
            {check.state === 'ok' && (
              <p className="flex min-w-0 flex-1 items-center gap-2 rounded-lg bg-[#EEFBF3] px-3 py-2.5 text-[12.5px] text-[#0F8B58]">
                <CheckCircle2 size={16} className="shrink-0" />
                <span className="min-w-0 truncate">
                  {unchanged ? 'Votre lien est actif' : 'Votre lien est disponible'} : {origin}/inscription/{check.slug}
                </span>
              </p>
            )}
            {check.state === 'taken' && (
              <p className="flex min-w-0 flex-1 items-center gap-2 rounded-lg bg-[#FEF2F2] px-3 py-2.5 text-[12.5px] text-[#B91C1C]">
                <XCircle size={16} className="shrink-0" /> {check.reason}
              </p>
            )}
            {check.state === 'ok' && !unchanged && (
              <button type="button" onClick={saveSlug} disabled={savingSlug}
                      className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#2F6BFF] px-3.5 text-[12.5px] font-semibold text-white hover:bg-[#2559DB] disabled:opacity-60">
                {savingSlug ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Enregistrer
              </button>
            )}
          </div>
          {check.state === 'ok' && !unchanged && (
            <p className="mt-2 text-[12px] text-[#64748B]">L&apos;ancien lien et les QR codes déjà imprimés continueront de fonctionner.</p>
          )}
        </section>

        {/* Partager le lien */}
        <section className={cardCls}>
          <CardHead icon={Share2} title="Partager le lien" subtitle="Envoyez le lien à vos clients via vos canaux de communication." />
          <div className="grid grid-cols-3 gap-2.5 sm:grid-cols-4">
            {[
              ['whatsapp', 'WhatsApp', <WhatsAppIcon key="w" />],
              ['email', 'Email', <Mail key="e" size={21} className="text-[#2F6BFF]" />],
              ['sms', 'SMS', <MessageSquare key="s" size={21} className="text-[#2F6BFF]" />],
              ['facebook', 'Facebook', <FacebookIcon key="f" />],
              ['instagram', 'Instagram', <InstagramIcon key="i" />],
              ['copy', 'Copier le lien', <Pencil key="c" size={19} className="text-[#0B1C3F]" />],
              ['more', 'Plus', <span key="m" className="flex h-[22px] w-[22px] items-center justify-center rounded-full border-[1.5px] border-[#475569] text-[#475569]"><MoreHorizontal size={13} /></span>],
            ].map(([kind, label, icon]) => (
              <button key={kind} type="button" onClick={() => share(kind)}
                      className="flex h-[62px] flex-col items-center justify-center gap-1.5 rounded-lg border border-[#E6EEFB] bg-white text-[12px] text-[#0B1C3F] transition hover:border-[#C9DBFB] hover:bg-[#F6F9FF]">
                {icon}{label}
              </button>
            ))}
          </div>
        </section>
      </div>

      {/* Aperçu de la page d'inscription */}
      <section className="relative mt-4 overflow-hidden rounded-2xl border border-[#E6EEFB] bg-white">
        <div className="grid gap-6 p-5 lg:grid-cols-[1fr_1.1fr_0.9fr]">
          <div>
            <CardHead icon={Eye} title="Aperçu de la page d'inscription"
                      subtitle="Voici un aperçu de la page que verront vos clients en cliquant sur le lien." />
            <ul className="mt-6 space-y-3.5 pl-11">
              {['Inscription rapide et simple', 'Présentation des avantages', 'Design à votre image', 'Responsive mobile & desktop'].map((x) => (
                <li key={x} className="flex items-center gap-3 text-[14px] text-[#0B1C3F]">
                  <CheckCircle2 size={19} className="shrink-0 fill-[#2F6BFF] text-white" /> {x}
                </li>
              ))}
            </ul>
          </div>

          {/* The phone on the left, the cup beside it on the right — side by
              side as in the design, never on top of each other. The photo
              melts into the card on its left and top edges. */}
          <div className="relative -mb-5 flex min-h-[250px] justify-start pl-[6%]">
            <div aria-hidden="true" className="pointer-events-none absolute bottom-0 right-0 top-2 w-[54%] overflow-hidden">
              <img src="/parametres/join-preview.webp" alt=""
                   onError={(e) => { e.currentTarget.style.display = 'none'; }}
                   className="h-full w-full object-cover object-[62%_55%]" />
              <span className="absolute inset-y-0 left-0 w-2/5 bg-gradient-to-r from-white via-white/70 to-transparent" />
              <span className="absolute inset-x-0 top-0 h-1/4 bg-gradient-to-b from-white to-transparent" />
            </div>
            <div className="relative z-10 mt-1 w-[200px] self-start rounded-t-[30px] border-[7px] border-b-0 border-[#111827] bg-white px-4 pb-4 pt-3 shadow-[0_24px_50px_-26px_rgba(11,28,63,.7)]">
              <span className="absolute left-1/2 top-1.5 h-3.5 w-16 -translate-x-1/2 rounded-full bg-[#111827]" />
              <p className="text-[8px] font-semibold text-[#0B1C3F]">9:41</p>
              <p className="mt-2 text-center text-[8.5px] font-semibold text-[#0B1C3F]">{shopName}</p>
              <div className="mt-1.5 flex justify-center">
                <ShopLogo url={d.shop.logo_url} name={shopName} />
              </div>
              <p className="mt-3 text-center text-[11.5px] font-bold leading-tight text-[#0B1C3F]">{d.page.title}</p>
              <p className="mt-1.5 text-center text-[7.5px] leading-snug text-[#64748B]">{d.page.subtitle}</p>
              <span className="mt-3 block rounded-md bg-[#2F6BFF] py-1.5 text-center text-[8.5px] font-semibold text-white">{d.page.button}</span>
            </div>
          </div>

          <div className="relative flex flex-col">
            <button type="button" onClick={() => setEditingPage(true)}
                    className="inline-flex h-10 items-center gap-2 self-end rounded-lg border border-[#2F6BFF] bg-white px-3.5 text-[12.5px] font-semibold text-[#2F6BFF] hover:bg-[#F6F9FF]">
              <Pencil size={14} /> Personnaliser la page
            </button>
            <ul className="mt-5 space-y-3">
              {d.page.benefits.map((b, i) => {
                const Icon = [Star, Sparkles, Cake, Gift][i % 4];
                return (
                  <li key={b} className="flex items-center gap-2.5 text-[12.5px] text-[#0B1C3F]">
                    <Icon size={16} className="shrink-0 text-[#0B1C3F]" /> {b}
                  </li>
                );
              })}
            </ul>
            <p className="mt-auto pt-6 text-right text-[11px] text-[#64748B]">
              {shopName}{d.shop.city ? <> &nbsp;•&nbsp; {d.shop.city}</> : null}
            </p>
          </div>
        </div>
      </section>

      <div aria-live="polite" className="pointer-events-none fixed bottom-5 left-1/2 z-40 -translate-x-1/2 transition-opacity"
           style={{ opacity: toast ? 1 : 0 }}>
        <span className="inline-flex items-center gap-2 rounded-full bg-[#0B1C3F] px-4 py-2 text-[13px] font-medium text-white shadow-lg">
          <Check size={14} /> {toast}
        </span>
      </div>

      {editingPage && (
        <PageModal initial={d.page} defaults={d.defaults} limits={d.limits}
                   onClose={() => setEditingPage(false)}
                   onSaved={(data) => { setD(data); setEditingPage(false); say('Page mise à jour'); }} />
      )}
    </div>
  );
}
