import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { chartAnimation } from '../lib/chartAnimation';
import {
  ArrowLeft, ChevronRight, Store, Plus, Box, Boxes, Star, BarChart3, ShoppingCart, Eye, Coins,
  Search, ChevronDown, ArrowUpDown, ArrowDown, ArrowUp, Pencil, MoreHorizontal, X, Check, Loader2,
  Copy, ImagePlus, ImageOff, Power, Trash2, Package, Camera, Tag,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';

/* Catalogue produits — the shop's products, their categories, and what sells.

   "Ventes" are the quantities staff pick at the till on the Scan page, over
   the chosen period (30 days unless the Plus vendus / Statistiques tabs say
   otherwise). A product switched off here is no longer offered at the till.
   "Produits les plus vendus" is how few products make 80 % of those sales. */

const TONES = {
  blue:   { bg: '#EAF1FF', fg: '#2F6BFF' },
  orange: { bg: '#FFF3E8', fg: '#E8741A' },
  violet: { bg: '#F3EEFF', fg: '#7C3AED' },
  green:  { bg: '#E7F7EE', fg: '#10A36B' },
  rose:   { bg: '#FFF1F3', fg: '#E11D48' },
  amber:  { bg: '#FFF7E6', fg: '#D97706' },
  teal:   { bg: '#E6FAF7', fg: '#0D9488' },
  slate:  { bg: '#F1F5F9', fg: '#64748B' },
};
const NONE = 'Sans catégorie';
const PER_PAGE = 20;
const SORTS = [
  { key: 'sales', label: 'Plus vendus' },
  { key: 'price', label: 'Prix' },
  { key: 'name', label: 'Nom' },
  { key: 'recent', label: 'Plus récents' },
  { key: 'revenue', label: "Chiffre d'affaires" },
];
const PERIOD_LABEL = { 7: '7 derniers jours', 30: '30 derniers jours', 90: '90 derniers jours', 365: '12 derniers mois' };
const eur = (n) => `${new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n ?? 0)} €`;
const nf = (n) => new Intl.NumberFormat('fr-FR').format(n ?? 0);

/* A photo, shrunk in the browser before it travels: 480 px on the long side,
   JPEG — a few dozen kilobytes, whatever the phone took. */
function shrink(file, max = 480) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Lecture impossible'));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error('Image illisible'));
      img.onload = () => {
        const k = Math.min(1, max / Math.max(img.width, img.height));
        const c = document.createElement('canvas');
        c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
        const g = c.getContext('2d');
        g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height);
        g.drawImage(img, 0, 0, c.width, c.height);
        resolve(c.toDataURL('image/jpeg', 0.82));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

function Toggle({ on, onChange, label, green = true }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)}
      className="relative h-[24px] w-[42px] shrink-0 rounded-full transition-colors"
      style={{ background: on ? (green ? '#16A34A' : '#2F6BFF') : '#D5DCE6' }}>
      <span className="absolute top-[3px] h-[18px] w-[18px] rounded-full bg-white shadow transition-all" style={{ left: on ? 21 : 3 }} />
    </button>
  );
}

function Pill({ name, color }) {
  const t = TONES[color] || TONES.slate;
  return (
    <span className="inline-flex max-w-full items-center truncate rounded-md px-2.5 py-1 text-[12.5px] font-medium"
          style={{ background: t.bg, color: t.fg }}>
      {name || NONE}
    </span>
  );
}

function Thumb({ p, size = 'h-12 w-16' }) {
  const [broken, setBroken] = useState(false);
  const t = TONES[p.color] || TONES.slate;
  if (p.image_url && !broken) {
    return <img src={p.image_url} alt="" onError={() => setBroken(true)} className={`${size} shrink-0 rounded-lg object-cover`} />;
  }
  return (
    <span className={`${size} flex shrink-0 items-center justify-center rounded-lg`} style={{ background: t.bg, color: t.fg }}>
      <Package size={20} />
    </span>
  );
}

function Select({ label, value, onChange, children, className = '', icon }) {
  return (
    <label className={`block ${className}`}>
      {label && <span className="mb-1.5 block text-[13px] font-medium text-[#0B1C3F]">{label}</span>}
      <span className="relative block">
        <select value={value} onChange={(e) => onChange(e.target.value)}
                className="h-10 w-full appearance-none rounded-lg border border-[#E2E8F0] bg-white pl-3 pr-9 text-[13.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]">
          {children}
        </select>
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[#334155]">{icon || <ChevronDown size={16} />}</span>
      </span>
    </label>
  );
}

function Modal({ title, subtitle, onClose, children, width = 'max-w-[520px]', footer }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0B1C3F]/40 p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className={`max-h-[92vh] w-full ${width} overflow-y-auto rounded-2xl bg-white p-6 shadow-[0_40px_90px_-40px_rgba(11,28,63,.6)]`}>
        <div className="mb-5 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[19px] font-bold text-[#0B1C3F]">{title}</h2>
            {subtitle && <p className="mt-0.5 text-[13px] text-[#64748B]">{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Fermer"
                  className="flex h-9 w-9 items-center justify-center rounded-lg text-[#64748B] hover:bg-[#F4F7FC]"><X size={18} /></button>
        </div>
        {children}
        {footer}
      </div>
    </div>
  );
}

const btnPrimary = 'inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-[#2F6BFF] px-5 text-[14px] font-semibold text-white hover:bg-[#2559DB] disabled:opacity-60';
const btnGhost = 'inline-flex h-11 items-center justify-center gap-2 rounded-xl border border-[#E2E8F0] bg-white px-5 text-[14px] font-semibold text-[#334155] hover:border-[#C9DBFB]';
const field = 'h-11 w-full rounded-lg border border-[#E2E8F0] px-3 text-[14px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';

/* ------------------------------------------------------ product editor -- */
function ProductModal({ product, categories, limits, onClose, onSaved, onImport }) {
  const [d, setD] = useState(() => ({
    name: product?.name || '', subtitle: product?.subtitle || '', category: product?.category || '',
    price: product ? String(product.price).replace('.', ',') : '', active: product ? product.active : true,
  }));
  const [photo, setPhoto] = useState(null);        // a new data URL, or null
  const [dropPhoto, setDropPhoto] = useState(false);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const file = useRef(null);
  const preview = photo || (!dropPhoto && product?.image_url) || null;

  const pick = async (f) => {
    if (!f) return;
    try { setPhoto(await shrink(f)); setDropPhoto(false); } catch (e) { setError(e.message); }
  };
  const save = async (e) => {
    e.preventDefault();
    const price = Number(String(d.price).replace(',', '.'));
    if (!d.name.trim()) { setError('Donnez un nom au produit.'); return; }
    if (!Number.isFinite(price) || price < 0) { setError('Indiquez un prix valide.'); return; }
    setSaving(true); setError('');
    try {
      const body = { ...d, price };
      let res = product ? await ownerAPI.updateProduct(product.id, body) : await ownerAPI.createProduct(body);
      const id = product?.id || res.data.id;
      if (photo) res = await ownerAPI.setProductImage(id, photo);
      else if (dropPhoto && product?.image_url) res = await ownerAPI.deleteProductImage(id);
      onSaved(res.data, product ? 'Produit mis à jour' : 'Produit ajouté');
    } catch (err) {
      setError(err?.response?.data?.detail || 'Enregistrement impossible.');
    } finally { setSaving(false); }
  };

  return (
    <Modal title={product ? 'Modifier le produit' : 'Ajouter un produit'} onClose={onClose}
           subtitle={product ? null : 'Il sera proposé à la caisse (page Scan) dès son ajout.'}>
      <form onSubmit={save}>
        <div className="mb-4 flex items-center gap-4">
          <button type="button" onClick={() => file.current?.click()}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => { e.preventDefault(); pick(e.dataTransfer.files?.[0]); }}
                  className="flex h-24 w-32 shrink-0 items-center justify-center overflow-hidden rounded-xl border-2 border-dashed border-[#C9DBFB] bg-[#F6F9FF] text-[#2F6BFF]">
            {preview ? <img src={preview} alt="" className="h-full w-full object-cover" />
              : <span className="flex flex-col items-center gap-1 text-[12px] font-semibold"><ImagePlus size={22} /> Ajouter une photo</span>}
          </button>
          <div className="text-[12.5px] text-[#64748B]">
            <p>JPEG, PNG ou WebP. Elle est réduite automatiquement.</p>
            <div className="mt-2 flex gap-3">
              <button type="button" onClick={() => file.current?.click()} className="font-semibold text-[#2F6BFF] hover:underline">
                {preview ? 'Changer' : 'Choisir une photo'}
              </button>
              {preview && (
                <button type="button" onClick={() => { setPhoto(null); setDropPhoto(true); }} className="font-semibold text-[#E11D48] hover:underline">
                  Retirer
                </button>
              )}
            </div>
          </div>
          <input ref={file} type="file" accept="image/jpeg,image/png,image/webp" className="hidden"
                 onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ''; }} />
        </div>

        <label className="mb-1.5 flex justify-between text-[13px] font-semibold text-[#334155]">
          Nom du produit * <span className="font-normal text-[#94A3B8]">{d.name.length}/{limits.name}</span>
        </label>
        <input value={d.name} maxLength={limits.name} onChange={(e) => setD({ ...d, name: e.target.value })}
               placeholder="Ex. Café Latte" className={`${field} mb-4`} />
        <label className="mb-1.5 block text-[13px] font-semibold text-[#334155]">Description courte</label>
        <input value={d.subtitle} maxLength={limits.subtitle} onChange={(e) => setD({ ...d, subtitle: e.target.value })}
               placeholder="Ex. Boisson chaude" className={`${field} mb-4`} />
        <div className="mb-4 grid gap-4 sm:grid-cols-[1fr_140px]">
          <div>
            <label className="mb-1.5 block text-[13px] font-semibold text-[#334155]">Catégorie</label>
            <input list="catalogue-categories" value={d.category} maxLength={limits.category}
                   onChange={(e) => setD({ ...d, category: e.target.value })}
                   placeholder="Choisir ou créer" className={field} />
            <datalist id="catalogue-categories">
              {categories.map((c) => <option key={c.name} value={c.name} />)}
            </datalist>
          </div>
          <div>
            <label className="mb-1.5 block text-[13px] font-semibold text-[#334155]">Prix *</label>
            <div className="flex h-11 overflow-hidden rounded-lg border border-[#E2E8F0] focus-within:border-[#2F6BFF]">
              <input inputMode="decimal" value={d.price} onChange={(e) => setD({ ...d, price: e.target.value })}
                     placeholder="0,00" className="min-w-0 flex-1 border-0 px-3 text-[14px] text-[#0B1C3F] outline-none" />
              <span className="flex items-center bg-[#F1F5F9] px-3 text-[13px] text-[#64748B]">€</span>
            </div>
          </div>
        </div>
        <div className="mb-5 flex items-center justify-between rounded-xl border border-[#EEF3FB] px-4 py-3">
          <div>
            <p className="text-[13.5px] font-semibold text-[#0B1C3F]">Produit actif</p>
            <p className="text-[12px] text-[#64748B]">Inactif, il n&apos;est plus proposé à la caisse.</p>
          </div>
          <Toggle on={d.active} onChange={(v) => setD({ ...d, active: v })} label="Produit actif" />
        </div>
        {error && <p className="mb-4 rounded-lg bg-[#FEF2F2] px-3 py-2.5 text-[13px] text-[#B91C1C]">{error}</p>}
        <div className="flex flex-wrap items-center justify-between gap-2">
          {!product && onImport ? (
            <button type="button" onClick={onImport} className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[#2F6BFF] hover:underline">
              <Camera size={15} /> Importer depuis une photo du menu
            </button>
          ) : <span />}
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className={btnGhost}>Annuler</button>
            <button type="submit" disabled={saving} className={btnPrimary}>
              {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />} {product ? 'Enregistrer' : 'Ajouter'}
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}

/* ------------------------------------------------- import from a menu photo -- */
function MenuImportModal({ onClose, onDone }) {
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const file = useRef(null);
  const read = async (f) => {
    if (!f) return;
    setBusy(true); setError('');
    try {
      const dataUrl = await new Promise((resolve, reject) => {
        const r = new FileReader(); r.onload = () => resolve(r.result); r.onerror = reject; r.readAsDataURL(f);
      });
      const res = await ownerAPI.parseMenuFromPhoto(dataUrl, f.type, 'fr');
      const items = Array.isArray(res?.data?.items) ? res.data.items : [];
      if (!items.length) setError('Aucun produit détecté. Essayez une photo plus nette.');
      setRows(items.map((it) => ({ keep: true, name: String(it.name || '').trim(),
        price: String(it.price ?? '').replace('.', ','), category: it.category || '' })));
    } catch (e) {
      setError(e?.response?.data?.detail?.message || e?.response?.data?.detail || "L'analyse de la photo a échoué.");
    } finally { setBusy(false); }
  };
  const importNow = async () => {
    const items = rows.filter((r) => r.keep && r.name.trim()).map((r) => ({
      name: r.name.trim(), price: Number(String(r.price).replace(',', '.')) || 0, category: r.category.trim(), active: true }));
    if (!items.length) return;
    setBusy(true); setError('');
    try {
      const { data } = await ownerAPI.importProducts(items);
      onDone(data, `${data.added} produit${data.added > 1 ? 's' : ''} ajouté${data.added > 1 ? 's' : ''}`);
    } catch (e) { setError(e?.response?.data?.detail || 'Import impossible.'); setBusy(false); }
  };
  const set = (i, patch) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <Modal title="Importer depuis une photo du menu" onClose={onClose} width="max-w-[640px]"
           subtitle="Prenez votre menu en photo : les produits sont lus pour vous, vous vérifiez avant d'ajouter.">
      {!rows && (
        <button type="button" onClick={() => file.current?.click()} disabled={busy}
                className="flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed border-[#C9DBFB] bg-[#F6F9FF] py-10 text-[13.5px] font-semibold text-[#2F6BFF]">
          {busy ? <Loader2 size={24} className="animate-spin" /> : <Camera size={26} />}
          {busy ? 'Lecture du menu…' : 'Choisir ou prendre une photo'}
        </button>
      )}
      <input ref={file} type="file" accept="image/*" capture="environment" className="hidden"
             onChange={(e) => { read(e.target.files?.[0]); e.target.value = ''; }} />
      {rows && rows.length > 0 && (
        <div className="max-h-[50vh] space-y-2 overflow-y-auto pr-1">
          {rows.map((r, i) => (
            <div key={i} className="grid grid-cols-[22px_1fr_90px_1fr] items-center gap-2">
              <input type="checkbox" checked={r.keep} onChange={(e) => set(i, { keep: e.target.checked })} className="h-4 w-4 accent-[#2F6BFF]" />
              <input value={r.name} onChange={(e) => set(i, { name: e.target.value })} className={`${field} h-10`} />
              <input value={r.price} onChange={(e) => set(i, { price: e.target.value })} className={`${field} h-10`} />
              <input value={r.category} onChange={(e) => set(i, { category: e.target.value })} placeholder="Catégorie" className={`${field} h-10`} />
            </div>
          ))}
        </div>
      )}
      {error && <p className="mt-4 rounded-lg bg-[#FEF2F2] px-3 py-2.5 text-[13px] text-[#B91C1C]">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" onClick={onClose} className={btnGhost}>Annuler</button>
        {rows && rows.length > 0 && (
          <button type="button" onClick={importNow} disabled={busy} className={btnPrimary}>
            {busy ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
            Ajouter {rows.filter((r) => r.keep).length} produit{rows.filter((r) => r.keep).length > 1 ? 's' : ''}
          </button>
        )}
      </div>
    </Modal>
  );
}

function Confirm({ title, body, cta = 'Supprimer', onCancel, onConfirm, children }) {
  return (
    <Modal title={title} onClose={onCancel} width="max-w-[440px]">
      <p className="text-[13.5px] leading-relaxed text-[#475569]">{body}</p>
      {children}
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" onClick={onCancel} className={btnGhost}>Annuler</button>
        <button type="button" onClick={onConfirm}
                className="inline-flex h-11 items-center rounded-xl bg-[#EF4444] px-5 text-[14px] font-semibold text-white hover:bg-[#DC2626]">{cta}</button>
      </div>
    </Modal>
  );
}

function CategoryModal({ category, palette, limits, onClose, onSaved }) {
  const [name, setName] = useState(category?.name || '');
  const [color, setColor] = useState(category?.color || palette[0]);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const save = async (e) => {
    e.preventDefault();
    setSaving(true); setError('');
    try {
      const res = category
        ? await ownerAPI.updateCategory({ old_name: category.name, name, color })
        : await ownerAPI.createCategory({ name, color });
      onSaved(res.data, category ? 'Catégorie mise à jour' : 'Catégorie ajoutée');
    } catch (err) { setError(err?.response?.data?.detail || 'Enregistrement impossible.'); setSaving(false); }
  };
  return (
    <Modal title={category ? 'Modifier la catégorie' : 'Nouvelle catégorie'} onClose={onClose} width="max-w-[440px]"
           subtitle={category ? 'Ses produits suivent le nouveau nom.' : null}>
      <form onSubmit={save}>
        <label className="mb-1.5 block text-[13px] font-semibold text-[#334155]">Nom</label>
        <input value={name} maxLength={limits.category} onChange={(e) => setName(e.target.value)} className={`${field} mb-4`} placeholder="Ex. Boissons chaudes" />
        <p className="mb-1.5 text-[13px] font-semibold text-[#334155]">Couleur</p>
        <div className="mb-5 flex flex-wrap gap-2">
          {palette.map((k) => (
            <button key={k} type="button" onClick={() => setColor(k)} aria-label={k}
                    className="flex h-9 items-center rounded-md border-2 px-2.5 text-[12px] font-medium"
                    style={{ background: TONES[k].bg, color: TONES[k].fg, borderColor: color === k ? TONES[k].fg : 'transparent' }}>
              {name || 'Aperçu'}
            </button>
          ))}
        </div>
        {error && <p className="mb-4 rounded-lg bg-[#FEF2F2] px-3 py-2.5 text-[13px] text-[#B91C1C]">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className={btnGhost}>Annuler</button>
          <button type="submit" disabled={saving} className={btnPrimary}>
            {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />} Enregistrer
          </button>
        </div>
      </form>
    </Modal>
  );
}

/* ----------------------------------------------------------- row menu -- */
function RowMenu({ p, onAction }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);
  const item = (icon, label, key, danger) => (
    <button type="button" key={key} onClick={() => { setOpen(false); onAction(key, p); }}
            className={`flex w-full items-center gap-2.5 px-3.5 py-2 text-left text-[13px] hover:bg-[#F6F9FF] ${danger ? 'text-[#E11D48]' : 'text-[#0B1C3F]'}`}>
      {icon}{label}
    </button>
  );
  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-label={`Plus d'actions — ${p.name}`}
              className="flex h-9 w-9 items-center justify-center rounded-lg text-[#0B1C3F] hover:bg-[#F4F7FC]">
        <MoreHorizontal size={20} />
      </button>
      {open && (
        <div className="absolute right-0 top-10 z-20 w-56 overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-[0_18px_40px_-20px_rgba(11,28,63,.45)]">
          {item(<Copy size={15} />, 'Dupliquer', 'duplicate')}
          {item(<ImagePlus size={15} />, p.image_url ? 'Changer la photo' : 'Ajouter une photo', 'photo')}
          {p.image_url && item(<ImageOff size={15} />, 'Retirer la photo', 'drop-photo')}
          {item(<Power size={15} />, p.active ? 'Désactiver' : 'Activer', 'toggle')}
          {item(<Trash2 size={15} />, 'Supprimer', 'delete', true)}
        </div>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- tabs -- */
function PeriodSelect({ days, periods, onChange }) {
  return (
    <Select value={days} onChange={(v) => onChange(Number(v))} className="w-[190px]">
      {periods.map((p) => <option key={p} value={p}>{PERIOD_LABEL[p] || `${p} jours`}</option>)}
    </Select>
  );
}

function TopTab({ d, onDays }) {
  const ranked = [...d.products].filter((p) => p.sales > 0).sort((a, b) => b.sales - a.sales).slice(0, 10);
  const total = d.products.reduce((s, p) => s + p.sales, 0);
  const max = ranked[0]?.sales || 1;
  return (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-[16px] font-bold text-[#0B1C3F]">Produits les plus vendus</h3>
          <p className="text-[13px] text-[#64748B]">
            {d.kpis.top > 0 ? `${d.kpis.top} produit${d.kpis.top > 1 ? 's' : ''} font 80 % de vos ventes.` : 'Classement par quantités vendues à la caisse.'}
          </p>
        </div>
        <PeriodSelect days={d.days} periods={d.periods} onChange={onDays} />
      </div>
      {!ranked.length ? (
        <div className="rounded-xl border border-dashed border-[#E6EEFB] px-6 py-12 text-center text-[13.5px] text-[#64748B]">
          Aucune vente sur la période. Les ventes viennent des produits choisis à la caisse (page Scan).
        </div>
      ) : (
        <ol className="divide-y divide-[#EEF3FB]">
          {ranked.map((p, i) => (
            <li key={p.id} className="flex flex-wrap items-center gap-4 py-3">
              <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[13px] font-bold ${i < 3 ? 'bg-[#2F6BFF] text-white' : 'bg-[#F1F5F9] text-[#475569]'}`}>{i + 1}</span>
              <Thumb p={p} size="h-11 w-14" />
              <div className="min-w-[160px] flex-1">
                <p className="text-[14.5px] font-bold text-[#0B1C3F]">{p.name}</p>
                <Pill name={p.category} color={p.color} />
              </div>
              <div className="min-w-[180px] flex-[1.4]">
                <div className="h-2.5 overflow-hidden rounded-full bg-[#EEF3FB]">
                  <div className="h-full rounded-full bg-[#2F6BFF]" style={{ width: `${(p.sales / max) * 100}%` }} />
                </div>
                <p className="mt-1 text-[12px] text-[#64748B]">{total ? Math.round((p.sales / total) * 100) : 0} % des ventes</p>
              </div>
              <div className="w-24 text-right"><p className="text-[15px] font-bold text-[#0B1C3F]">{nf(p.sales)}</p><p className="text-[12px] text-[#64748B]">ventes</p></div>
              <div className="w-28 text-right"><p className="text-[15px] font-bold text-[#0B1C3F]">{eur(p.revenue)}</p><p className="text-[12px] text-[#64748B]">CA</p></div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function StatsTab({ d, onDays }) {
  const s = d.stats;
  const delta = s.prev_sales ? Math.round(((s.sales - s.prev_sales) / s.prev_sales) * 100) : null;
  const byCat = [...d.categories].filter((c) => c.revenue > 0).sort((a, b) => b.revenue - a.revenue);
  const maxCat = byCat[0]?.revenue || 1;
  const rows = [...d.products].sort((a, b) => b.revenue - a.revenue);
  const series = s.daily.map((x) => ({ ...x, label: new Date(x.date).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }) }));
  const tile = (icon, label, value, extra) => (
    <div className="flex items-center gap-4 rounded-2xl border border-[#E6EEFB] bg-white p-5">
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]">{icon}</span>
      <div><p className="text-[22px] font-bold leading-tight text-[#0B1C3F]">{value}</p><p className="text-[13px] text-[#475569]">{label} {extra}</p></div>
    </div>
  );
  return (
    <div className="space-y-4">
      <div className="flex justify-end"><PeriodSelect days={d.days} periods={d.periods} onChange={onDays} /></div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {tile(<ShoppingCart size={22} />, 'Articles vendus', nf(s.sales), delta != null && (
          <span className={`ml-1 inline-flex items-center text-[12px] font-semibold ${delta >= 0 ? 'text-[#0F8B58]' : 'text-[#E11D48]'}`}>
            {delta >= 0 ? <ArrowUp size={12} /> : <ArrowDown size={12} />}{Math.abs(delta)} %
          </span>))}
        {tile(<Coins size={22} />, "Chiffre d'affaires produits", eur(s.revenue))}
        {tile(<Box size={22} />, 'Produits vendus', `${s.sold_products} / ${d.kpis.total}`)}
        {tile(<Tag size={22} />, 'Prix moyen vendu', eur(s.avg_sold_price))}
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5">
          <h3 className="mb-4 text-[15.5px] font-bold text-[#0B1C3F]">Ventes par jour</h3>
          <div className="h-[240px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={series} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="#EEF3FB" />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#94A3B8' }} axisLine={false} tickLine={false} minTickGap={24} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#94A3B8' }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: '#F4F7FC' }} formatter={(v, k) => (k === 'sales' ? [nf(v), 'Ventes'] : [eur(v), 'CA'])} />
                <Bar isAnimationActive={chartAnimation()} dataKey="sales" fill="#2F6BFF" radius={[4, 4, 0, 0]} maxBarSize={18} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
        <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5">
          <h3 className="mb-4 text-[15.5px] font-bold text-[#0B1C3F]">CA par catégorie</h3>
          {!byCat.length ? <p className="py-10 text-center text-[13px] text-[#64748B]">Aucune vente sur la période.</p> : (
            <ul className="space-y-3.5">
              {byCat.map((c) => (
                <li key={c.name}>
                  <div className="mb-1 flex justify-between text-[13px]"><Pill name={c.name} color={c.color} /><span className="font-semibold text-[#0B1C3F]">{eur(c.revenue)}</span></div>
                  <div className="h-2 overflow-hidden rounded-full bg-[#EEF3FB]">
                    <div className="h-full rounded-full" style={{ width: `${(c.revenue / maxCat) * 100}%`, background: (TONES[c.color] || TONES.slate).fg }} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <section className="overflow-hidden rounded-2xl border border-[#E6EEFB] bg-white">
        <h3 className="px-5 pt-5 text-[15.5px] font-bold text-[#0B1C3F]">Détail par produit</h3>
        <div className="overflow-x-auto p-5 pt-3">
          <table className="w-full min-w-[640px] text-[13.5px]">
            <thead><tr className="border-b border-[#EEF3FB] text-left text-[12.5px] font-medium text-[#64748B]">
              <th className="py-2.5 font-medium">Produit</th><th className="font-medium">Catégorie</th>
              <th className="text-right font-medium">Ventes</th><th className="text-right font-medium">CA</th><th className="text-right font-medium">Part du CA</th>
            </tr></thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id} className="border-b border-[#F4F7FC]">
                  <td className="py-2.5 font-semibold text-[#0B1C3F]">{p.name}</td>
                  <td><Pill name={p.category} color={p.color} /></td>
                  <td className="text-right">{nf(p.sales)}</td>
                  <td className="text-right">{eur(p.revenue)}</td>
                  <td className="text-right text-[#64748B]">{s.revenue ? Math.round((p.revenue / s.revenue) * 100) : 0} %</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function CategoriesTab({ d, onEdit, onDelete, onAdd, onOpen }) {
  const uncategorised = d.products.filter((p) => !p.category).length;
  return (
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-[16px] font-bold text-[#0B1C3F]">Catégories</h3>
          <p className="text-[13px] text-[#64748B]">Regroupez vos produits — la couleur suit le produit partout.</p>
        </div>
        <button type="button" onClick={onAdd} className={btnPrimary}><Plus size={16} /> Nouvelle catégorie</button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {d.categories.map((c) => {
          const t = TONES[c.color] || TONES.slate;
          return (
            <div key={c.name} className="rounded-xl border border-[#E6EEFB] p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl" style={{ background: t.bg, color: t.fg }}><Boxes size={19} /></span>
                  <div className="min-w-0">
                    <p className="truncate text-[14.5px] font-bold text-[#0B1C3F]">{c.name}</p>
                    <p className="text-[12.5px] text-[#64748B]">{c.count} produit{c.count > 1 ? 's' : ''} · {c.active_count} actif{c.active_count > 1 ? 's' : ''}</p>
                  </div>
                </div>
                <div className="flex shrink-0 gap-1">
                  <button type="button" onClick={() => onEdit(c)} aria-label={`Modifier ${c.name}`} className="flex h-8 w-8 items-center justify-center rounded-lg border border-[#E2E8F0] text-[#0B1C3F] hover:border-[#2F6BFF] hover:text-[#2F6BFF]"><Pencil size={14} /></button>
                  <button type="button" onClick={() => onDelete(c)} aria-label={`Supprimer ${c.name}`} className="flex h-8 w-8 items-center justify-center rounded-lg border border-[#FECACA] bg-[#FEF2F2] text-[#EF4444]"><Trash2 size={14} /></button>
                </div>
              </div>
              <div className="mt-3 flex items-center justify-between border-t border-[#F4F7FC] pt-3 text-[12.5px]">
                <span className="text-[#475569]"><b className="text-[#0B1C3F]">{nf(c.sales)}</b> ventes · <b className="text-[#0B1C3F]">{eur(c.revenue)}</b></span>
                <button type="button" onClick={() => onOpen(c.name)} className="font-semibold text-[#2F6BFF] hover:underline">Voir les produits</button>
              </div>
            </div>
          );
        })}
        {!d.categories.length && <p className="text-[13px] text-[#64748B]">Aucune catégorie pour l&apos;instant.</p>}
      </div>
      {uncategorised > 0 && (
        <p className="mt-4 text-[12.5px] text-[#64748B]">{uncategorised} produit{uncategorised > 1 ? 's' : ''} sans catégorie — <button type="button" onClick={() => onOpen(NONE)} className="font-semibold text-[#2F6BFF] hover:underline">les voir</button>.</p>
      )}
    </section>
  );
}

/* --------------------------------------------------------------- page -- */
export default function CataloguePage() {
  const navigate = useNavigate();
  const [d, setD] = useState(null);
  const [days, setDays] = useState(30);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('all');
  const [q, setQ] = useState('');
  const [cat, setCat] = useState('');
  const [status, setStatus] = useState('');
  const [sort, setSort] = useState('sales');
  const [dir, setDir] = useState('desc');
  const [page, setPage] = useState(1);
  const [picked, setPicked] = useState(() => new Set());
  const [editing, setEditing] = useState(null);         // null | {} (new) | product
  const [importing, setImporting] = useState(false);
  const [confirm, setConfirm] = useState(null);
  const [catEdit, setCatEdit] = useState(null);         // null | {} | category
  const [catDelete, setCatDelete] = useState(null);
  const [moveTo, setMoveTo] = useState('');
  const [toast, setToast] = useState('');
  const toastTimer = useRef(null);
  const photoFor = useRef(null);
  const photoInput = useRef(null);

  const say = (m) => { setToast(m); clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => setToast(''), 2600); };
  useEffect(() => () => clearTimeout(toastTimer.current), []);

  const load = useCallback((n = days) => {
    ownerAPI.cataloguePage(n)
      .then(({ data }) => { setD(data); setError(''); })
      .catch((e) => setError(e?.response?.data?.detail || 'Impossible de charger le catalogue.'));
  }, [days]);
  useEffect(() => { load(days); }, [days]); // eslint-disable-line react-hooks/exhaustive-deps

  const apply = (data, msg) => { setD(data); if (msg) say(msg); };
  const run = async (fn, msg) => {
    try { const { data } = await fn(); apply(data, msg); return true; }
    catch (e) { say(e?.response?.data?.detail || 'Action impossible.'); return false; }
  };
  // Mutations answer with the 30-day view; re-read when another period is shown.
  useEffect(() => { if (d && d.days !== days) load(days); }, [d, days, load]);

  const colourOf = useMemo(() => Object.fromEntries((d?.categories || []).map((c) => [c.name, c.color])), [d]);

  const rows = useMemo(() => {
    if (!d) return [];
    const needle = q.trim().toLowerCase();
    const out = d.products.filter((p) => (!needle || `${p.name} ${p.subtitle} ${p.category}`.toLowerCase().includes(needle))
      && (!cat || (cat === NONE ? !p.category : p.category === cat))
      && (!status || (status === 'active' ? p.active : !p.active)));
    const key = { sales: (p) => p.sales, price: (p) => p.price, name: (p) => p.name.toLowerCase(),
      recent: (p) => p.created_at, revenue: (p) => p.revenue }[sort];
    out.sort((a, b) => {
      const x = key(a), y = key(b);
      const c = x < y ? -1 : x > y ? 1 : 0;
      return dir === 'asc' ? c : -c;
    });
    return out;
  }, [d, q, cat, status, sort, dir]);
  useEffect(() => { setPage(1); }, [q, cat, status, sort, dir]);
  const pages = Math.max(1, Math.ceil(rows.length / PER_PAGE));
  const shown = rows.slice((page - 1) * PER_PAGE, page * PER_PAGE);
  const allShown = shown.length > 0 && shown.every((p) => picked.has(p.id));

  const sortBy = (key) => {
    if (sort === key) setDir(dir === 'desc' ? 'asc' : 'desc');
    else { setSort(key); setDir(key === 'name' ? 'asc' : 'desc'); }
  };
  const togglePick = (id) => setPicked((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  const onRowAction = async (key, p) => {
    if (key === 'duplicate') run(() => ownerAPI.duplicateProduct(p.id), 'Produit dupliqué');
    if (key === 'photo') { photoFor.current = p.id; photoInput.current?.click(); }
    if (key === 'drop-photo') run(() => ownerAPI.deleteProductImage(p.id), 'Photo retirée');
    if (key === 'toggle') setActive(p, !p.active);
    if (key === 'delete') setConfirm({ title: `Supprimer « ${p.name} » ?`, body: 'Il ne sera plus proposé à la caisse. Les ventes passées restent dans vos statistiques.',
      go: () => run(() => ownerAPI.deleteProduct(p.id), 'Produit supprimé') });
  };
  const setActive = (p, on) => {
    // Optimistic: the switch moves at once, the server confirms.
    setD((prev) => ({ ...prev, products: prev.products.map((x) => (x.id === p.id ? { ...x, active: on } : x)) }));
    run(() => ownerAPI.bulkProducts({ ids: [p.id], action: on ? 'activate' : 'deactivate' }), on ? 'Produit activé' : 'Produit désactivé')
      .then((ok) => { if (!ok) load(); });
  };
  const bulk = async (action, category) => {
    const ids = [...picked];
    if (action === 'delete') {
      setConfirm({ title: `Supprimer ${ids.length} produit${ids.length > 1 ? 's' : ''} ?`, body: 'Ils ne seront plus proposés à la caisse.',
        go: async () => { if (await run(() => ownerAPI.bulkProducts({ ids, action }), 'Produits supprimés')) setPicked(new Set()); } });
      return;
    }
    if (await run(() => ownerAPI.bulkProducts({ ids, action, category }), 'Modifications enregistrées')) setPicked(new Set());
  };

  if (!d) {
    return (
      <div className="ct">
        {error ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{error}</p> : (
          <div className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]">
            <Loader2 size={16} className="animate-spin" /> Chargement…
          </div>
        )}
      </div>
    );
  }

  const TABS = [
    { key: 'all', label: 'Tous les produits', icon: Box },
    { key: 'categories', label: 'Catégories', icon: Boxes },
    { key: 'top', label: 'Produits les plus vendus', icon: Star },
    { key: 'stats', label: 'Statistiques', icon: BarChart3 },
  ];
  const kpi = (icon, tone, value, label) => (
    <div className="flex items-center gap-5 rounded-2xl border border-[#E6EEFB] bg-white px-5 py-5">
      <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl" style={{ background: TONES[tone].bg, color: TONES[tone].fg }}>{icon}</span>
      <div><p className="text-[26px] font-bold leading-none text-[#0B1C3F]">{value}</p><p className="mt-1.5 text-[14px] text-[#475569]">{label}</p></div>
    </div>
  );
  const headSort = (key, label) => {
    const on = sort === key;
    return (
      <button type="button" onClick={() => sortBy(key)}
              className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 font-medium ${on ? 'bg-[#EAF1FF] text-[#2F6BFF]' : 'text-[#0B1C3F] hover:bg-[#F4F7FC]'}`}>
        {label}{on && (dir === 'desc' ? <ArrowDown size={14} /> : <ArrowUp size={14} />)}
      </button>
    );
  };

  return (
    <div className="ct">
      <nav className="mb-3 flex items-center gap-2 text-[14px] text-[#475569]" aria-label="Fil d'Ariane">
        <button type="button" onClick={() => navigate(-1)} aria-label="Retour" className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-white"><ArrowLeft size={18} /></button>
        <Link to="/dashboard" className="hover:text-[#2F6BFF]">{d.shop || 'Mon commerce'}</Link>
        <ChevronRight size={15} className="text-[#94A3B8]" />
        <span>Catalogue produits</span>
      </nav>

      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <span className="mt-1 flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#E6EEFB] text-[#2F6BFF]"><Store size={24} /></span>
          <div>
            <h1 className="text-[30px] font-bold leading-tight tracking-[-0.01em] text-[#0B1C3F]">Catalogue produits</h1>
            <p className="mt-1 text-[15.5px] text-[#475569]">Gérez vos produits et services. Ces informations seront utilisées pour vos campagnes et vos insights.</p>
          </div>
        </div>
        <button type="button" onClick={() => setEditing({})}
                className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#2F6BFF] px-6 text-[15.5px] font-medium text-white shadow-[0_10px_24px_-14px_rgba(47,107,255,.9)] hover:bg-[#2559DB]">
          <Plus size={18} /> Ajouter un produit
        </button>
      </header>

      <div className="mb-5 grid grid-cols-2 overflow-hidden rounded-2xl border border-[#E6EEFB] bg-white md:grid-cols-4" role="tablist">
        {TABS.map((t) => {
          const on = tab === t.key; const Icon = t.icon;
          return (
            <button key={t.key} type="button" role="tab" aria-selected={on} onClick={() => setTab(t.key)}
                    className={`relative flex h-[52px] items-center justify-center gap-2.5 text-[14.5px] transition ${on ? 'font-medium text-[#2F6BFF]' : 'text-[#0B1C3F] hover:bg-[#F8FAFF]'}`}>
              <Icon size={18} strokeWidth={on ? 2.2 : 1.8} /> {t.label}
              {on && <span className="absolute bottom-0 left-2 right-2 h-[2.5px] rounded-full bg-[#2F6BFF]" />}
            </button>
          );
        })}
      </div>

      {tab === 'all' && (
        <>
          <div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {kpi(<Box size={26} />, 'blue', nf(d.kpis.total), 'Produits au total')}
            {kpi(<ShoppingCart size={26} />, 'green', nf(d.kpis.top), 'Produits les plus vendus')}
            {kpi(<Eye size={26} />, 'orange', nf(d.kpis.inactive), 'Produits inactifs')}
            {kpi(<Coins size={26} />, 'violet', eur(d.kpis.avg_price), 'Prix moyen')}
          </div>

          <section className="rounded-2xl border border-[#E6EEFB] bg-white p-4 sm:p-5">
            <div className="mb-4 flex flex-wrap items-end gap-4">
              <label className="relative min-w-[220px] flex-[1.6]">
                <Search size={17} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[#64748B]" />
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher un produit..."
                       className="h-11 w-full rounded-lg bg-[#F4F7FC] pl-10 pr-3 text-[14px] text-[#0B1C3F] outline-none placeholder:text-[#64748B] focus:ring-2 focus:ring-[#2F6BFF]/20" />
              </label>
              <Select label="Catégorie" value={cat} onChange={setCat} className="min-w-[170px] flex-1">
                <option value="">Toutes les catégories</option>
                {d.categories.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
                <option value={NONE}>{NONE}</option>
              </Select>
              <Select label="Statut" value={status} onChange={setStatus} className="min-w-[150px] flex-1">
                <option value="">Tous</option><option value="active">Actifs</option><option value="inactive">Inactifs</option>
              </Select>
              <label className="block min-w-[170px] flex-1">
                <span className="mb-1.5 block text-[13px] font-medium text-[#0B1C3F]">Trier par</span>
                <span className="flex h-10 overflow-hidden rounded-lg border border-[#E2E8F0] bg-white focus-within:border-[#2F6BFF]">
                  <select value={sort} onChange={(e) => { setSort(e.target.value); setDir(e.target.value === 'name' ? 'asc' : 'desc'); }}
                          className="min-w-0 flex-1 appearance-none bg-transparent pl-3 text-[13.5px] text-[#0B1C3F] outline-none">
                    {SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                  </select>
                  <button type="button" onClick={() => setDir(dir === 'desc' ? 'asc' : 'desc')} aria-label="Inverser l'ordre"
                          className="flex w-10 items-center justify-center text-[#334155] hover:text-[#2F6BFF]"><ArrowUpDown size={16} /></button>
                </span>
              </label>
            </div>

            {picked.size > 0 && (
              <div className="mb-3 flex flex-wrap items-center gap-2 rounded-xl bg-[#EFF5FF] px-4 py-2.5 text-[13px]">
                <b className="mr-2 text-[#0B1C3F]">{picked.size} sélectionné{picked.size > 1 ? 's' : ''}</b>
                <button type="button" onClick={() => bulk('activate')} className="rounded-lg bg-white px-3 py-1.5 font-semibold text-[#0B1C3F] hover:text-[#2F6BFF]">Activer</button>
                <button type="button" onClick={() => bulk('deactivate')} className="rounded-lg bg-white px-3 py-1.5 font-semibold text-[#0B1C3F] hover:text-[#2F6BFF]">Désactiver</button>
                <select value="" onChange={(e) => e.target.value && bulk('category', e.target.value === NONE ? '' : e.target.value)}
                        className="h-8 rounded-lg border-0 bg-white px-2 text-[13px] font-semibold text-[#0B1C3F]">
                  <option value="">Changer de catégorie…</option>
                  {d.categories.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
                  <option value={NONE}>{NONE}</option>
                </select>
                <button type="button" onClick={() => bulk('delete')} className="rounded-lg bg-white px-3 py-1.5 font-semibold text-[#E11D48]">Supprimer</button>
                <button type="button" onClick={() => setPicked(new Set())} className="ml-auto text-[#64748B] hover:text-[#0B1C3F]" aria-label="Tout désélectionner"><X size={16} /></button>
              </div>
            )}

            <div className="overflow-x-auto rounded-xl border border-[#EEF3FB]">
              <table className="w-full min-w-[900px] text-[14px]">
                <thead>
                  <tr className="border-b border-[#EEF3FB] text-left text-[13.5px] text-[#0B1C3F]">
                    <th className="w-12 py-3 pl-4">
                      <input type="checkbox" aria-label="Tout sélectionner" checked={allShown}
                             onChange={() => setPicked((prev) => { const n = new Set(prev); shown.forEach((p) => (allShown ? n.delete(p.id) : n.add(p.id))); return n; })}
                             className="h-[18px] w-[18px] cursor-pointer rounded accent-[#2F6BFF]" />
                    </th>
                    <th className="py-3 pl-2 font-medium">{headSort('name', 'Produit')}</th>
                    <th className="py-3 font-medium">Catégorie</th>
                    <th className="py-3 font-medium">{headSort('price', 'Prix')}</th>
                    <th className="py-3 font-medium" title={`Ventes des ${PERIOD_LABEL[d.days] || `${d.days} derniers jours`}`}>{headSort('sales', 'Ventes')}</th>
                    <th className="py-3 font-medium">Statut</th>
                    <th className="py-3 pr-4 text-center font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((p) => (
                    <tr key={p.id} className="border-b border-[#F1F5F9] last:border-0 hover:bg-[#FAFCFF]">
                      <td className="py-2 pl-4">
                        <input type="checkbox" aria-label={`Sélectionner ${p.name}`} checked={picked.has(p.id)} onChange={() => togglePick(p.id)}
                               className="h-[18px] w-[18px] cursor-pointer rounded accent-[#2F6BFF]" />
                      </td>
                      <td className="py-2 pl-2">
                        <div className="flex items-center gap-3.5">
                          <Thumb p={p} />
                          <div className="min-w-0">
                            <p className="truncate text-[15px] font-bold text-[#0B1C3F]">{p.name}</p>
                            {p.subtitle && <p className="truncate text-[13px] text-[#64748B]">{p.subtitle}</p>}
                          </div>
                        </div>
                      </td>
                      <td className="py-2"><Pill name={p.category} color={colourOf[p.category] || p.color} /></td>
                      <td className="py-2 text-[#0B1C3F]">{eur(p.price)}</td>
                      <td className="py-2 pl-2 text-[#0B1C3F]">{nf(p.sales)}</td>
                      <td className="py-2"><Toggle on={p.active} onChange={(v) => setActive(p, v)} label={`Activer ${p.name}`} /></td>
                      <td className="py-2 pr-4">
                        <div className="flex items-center justify-center gap-4">
                          <button type="button" onClick={() => setEditing(p)} aria-label={`Modifier ${p.name}`}
                                  className="flex h-10 w-10 items-center justify-center rounded-lg border border-[#E2E8F0] bg-white text-[#0B1C3F] hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
                            <Pencil size={17} />
                          </button>
                          <RowMenu p={p} onAction={onRowAction} />
                        </div>
                      </td>
                    </tr>
                  ))}
                  {!shown.length && (
                    <tr><td colSpan={7} className="px-6 py-14 text-center text-[14px] text-[#64748B]">
                      {d.products.length ? 'Aucun produit ne correspond à ces filtres.' : (
                        <span>Votre catalogue est vide. <button type="button" onClick={() => setEditing({})} className="font-semibold text-[#2F6BFF] hover:underline">Ajoutez un produit</button> ou{' '}
                          <button type="button" onClick={() => setImporting(true)} className="font-semibold text-[#2F6BFF] hover:underline">importez votre menu en photo</button>.</span>
                      )}
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
            {pages > 1 && (
              <div className="mt-4 flex items-center justify-between text-[13px] text-[#64748B]">
                <span>{rows.length} produits</span>
                <div className="flex gap-1.5">
                  {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
                    <button key={n} type="button" onClick={() => setPage(n)}
                            className={`h-8 min-w-8 rounded-lg px-2.5 font-semibold ${n === page ? 'bg-[#2F6BFF] text-white' : 'border border-[#E2E8F0] bg-white text-[#0B1C3F]'}`}>{n}</button>
                  ))}
                </div>
              </div>
            )}
          </section>
        </>
      )}

      {tab === 'categories' && (
        <CategoriesTab d={d} onAdd={() => setCatEdit({})} onEdit={(c) => setCatEdit(c)}
                       onDelete={(c) => { setMoveTo(''); setCatDelete(c); }}
                       onOpen={(name) => { setCat(name); setTab('all'); }} />
      )}
      {tab === 'top' && <TopTab d={d} onDays={setDays} />}
      {tab === 'stats' && <StatsTab d={d} onDays={setDays} />}

      <input ref={photoInput} type="file" accept="image/jpeg,image/png,image/webp" className="hidden"
             onChange={async (e) => {
               const f = e.target.files?.[0]; e.target.value = '';
               if (!f || !photoFor.current) return;
               try { const url = await shrink(f); run(() => ownerAPI.setProductImage(photoFor.current, url), 'Photo mise à jour'); }
               catch (err) { say(err.message); }
             }} />

      <div aria-live="polite" className="pointer-events-none fixed bottom-5 left-1/2 z-40 -translate-x-1/2 transition-opacity" style={{ opacity: toast ? 1 : 0 }}>
        <span className="inline-flex items-center gap-2 rounded-full bg-[#0B1C3F] px-4 py-2 text-[13px] font-medium text-white shadow-lg"><Check size={14} /> {toast}</span>
      </div>

      {editing && (
        <ProductModal product={editing.id ? editing : null} categories={d.categories} limits={d.limits}
                      onClose={() => setEditing(null)}
                      onImport={() => { setEditing(null); setImporting(true); }}
                      onSaved={(data, msg) => { apply(data, msg); setEditing(null); }} />
      )}
      {importing && <MenuImportModal onClose={() => setImporting(false)} onDone={(data, msg) => { apply(data, msg); setImporting(false); }} />}
      {confirm && (
        <Confirm title={confirm.title} body={confirm.body} onCancel={() => setConfirm(null)}
                 onConfirm={() => { const go = confirm.go; setConfirm(null); go(); }} />
      )}
      {catEdit && (
        <CategoryModal category={catEdit.name ? catEdit : null} palette={d.palette} limits={d.limits}
                       onClose={() => setCatEdit(null)} onSaved={(data, msg) => { apply(data, msg); setCatEdit(null); }} />
      )}
      {catDelete && (
        <Confirm title={`Supprimer « ${catDelete.name} » ?`}
                 body={catDelete.count ? `Ses ${catDelete.count} produit${catDelete.count > 1 ? 's' : ''} ne sont pas supprimés : choisissez où les ranger.` : 'Cette catégorie ne contient aucun produit.'}
                 onCancel={() => setCatDelete(null)}
                 onConfirm={() => { const c = catDelete; setCatDelete(null); run(() => ownerAPI.deleteCategory(c.name, moveTo), 'Catégorie supprimée'); }}>
          {catDelete.count > 0 && (
            <Select label="Déplacer les produits vers" value={moveTo} onChange={setMoveTo} className="mt-4">
              <option value="">{NONE}</option>
              {d.categories.filter((c) => c.name !== catDelete.name).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </Select>
          )}
        </Confirm>
      )}
    </div>
  );
}
