import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import {
  Palette, Image as ImageIcon, Barcode, MousePointerClick, ListTree, Upload, RotateCcw, Save, Loader2,
  Plus, Trash2, ArrowUp, ArrowDown, Check, ChevronDown, Smartphone, LayoutTemplate, Fingerprint,
  Copy, Bell, Rows3, ImagePlus,
} from 'lucide-react';
import { ownerAPI } from '../../lib/api';
import PassPreview, { PassBack, NEW_CODES } from './PassPreview';
import FeaturedActionsEditor from './FeaturedActionsEditor';
import GoogleDesignEditor from './GoogleDesignEditor';
import GoogleWalletPreview from './GoogleWalletPreview';
import PosterCropper from '../PosterCropper';
import { WalletSwitch, VersionSwitch, IphoneFrame, Dots, screenWidth } from './PreviewStage';
import { fitRect } from '../../lib/fit';
import { STYLES, GROUPS, IMAGES, ICON_IMAGE, FIELD_VARS, TRANSIT, ALIGN, rgbToHex, hexToRgb } from './walletLook';

/**
 * CardDesigner — Apple's Pass Designer, inside the Carte de fidélité page
 * (user, 2026-10-07: every Pass Designer option, working, with the preview
 * live next to it). The design is a pass.json template, the same as an
 * imported .pkpasstemplate: style, iOS 26 fallback, colours, images, barcode
 * + fallback, fields mixing the shop's text and the customer's own values
 * ({prenom}, {points}…), featured actions. The server fills it per customer
 * (api/features/pass_designer); the preview is that server's output for a
 * sample customer, so what is drawn here is what lands in Wallet.
 *
 * One place for the whole card (user, 2026-10-07): the « Identité » tab
 * holds the shop's name, colours, logo, banner and welcome text (the iOS 26
 * card, the customer's web page, Google Wallet), and the preview shows iOS 27,
 * iOS 26 and the customer's web card side by side, live.
 *
 * Props: edit (owner), types (featured action types), formats (barcodes),
 * actions + onActionsChange (the card's buttons, kept by the page),
 * identityPanel (the page's identity fields), previewCard (the page's unsaved
 * card fields, for the preview), clientPreview (the web card, drawn by the
 * page), externalDirty + onSaveAll (one save for the page and the design),
 * onDirtyChange(bool), onSaved(). The ref exposes save() and reset().
 *
 * variant « v2 » (Carte de fidélité redesign, user 2026-10-11): the editor and
 * the preview each in their own card, the Apple / Google switch as two big
 * buttons, and one iPhone at a time chosen with « iOS 27 / iOS 26 et avant »
 * (the customer's web card is the third view). Same editor, same data.
 * `inspectorOverride` (v2): another step's content in the left column while
 * the editor stays mounted, hidden — the live preview keeps showing, and the
 * design's unsaved edits survive the step change (user, 2026-10-11).
 */
const STYLE_KEYS = STYLES.map((s) => s.key);
const PHONE_W = 300;      // the v2 preview's iPhone — a normal iPhone's size (user, 2026-10-12: « thoda chhota »)
const styleOf = (p) => STYLE_KEYS.find((k) => p && typeof p[k] === 'object');
const IMG_RE = /^(background|primaryLogo|logo|icon|thumbnail|strip|footer)(@[23]x)?\.png$/;
const baseOf = (name) => name.replace(/(@[23]x)?\.png$/, '');
const imgName = (images, base) => Object.keys(images).find((n) => baseOf(n) === base);
// the @3x pixels each image is made at (Apple's points × 3)
const IMG_PX = { background: [1035, 1515], strip: [1125, 432], thumbnail: [270, 270], logo: [480, 150],
  primaryLogo: [480, 150], icon: [87, 87], footer: [858, 45] };
const FALLBACKS = [
  ['fidclic', 'Carte FidClic actuelle (bannière, logo, couleur)'],
  ['generic', 'Générée depuis ce design : Generic'],
  ['storeCard', 'Générée depuis ce design : Store Card'],
  ['coupon', 'Générée depuis ce design : Coupon'],
  ['eventTicket', 'Générée depuis ce design : Event Ticket'],
];

// Moving to another style keeps every field: those with no slot there go to the back.
function convertStyle(block = {}, from, to) {
  const g = (k) => block[k] || [];
  const boarding = to === 'boardingPass';
  const prim = from === 'posterGeneric' ? g('primaryFields') : [...g('primaryFields'), ...g('secondaryFields')];
  const foot = from === 'posterGeneric' ? g('footerFields') : g('auxiliaryFields');
  const head = g('headerFields');
  let out;
  let spill = [];
  if (to === 'posterGeneric') {
    out = { headerFields: head.slice(0, 1), primaryFields: prim.slice(0, 4), footerFields: foot.slice(0, 2) };
    spill = [...head.slice(1), ...prim.slice(4), ...foot.slice(2)];
  } else {
    const n1 = boarding ? 2 : 1;
    const n2 = boarding ? 5 : 4;
    out = { headerFields: head.slice(0, 3), primaryFields: prim.slice(0, n1), secondaryFields: prim.slice(n1, n1 + n2),
      auxiliaryFields: foot.slice(0, n2) };
    spill = [...head.slice(3), ...prim.slice(n1 + n2), ...foot.slice(n2)];
    if (boarding) out.transitType = block.transitType || 'PKTransitTypeGeneric';
  }
  out.backFields = [...g('backFields'), ...spill.map((f) => ({ ...f, textAlignment: undefined }))];
  return out;
}

const readFile = (f) => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(f); });

// fit an upload into its slot's @3x size (contain), PNG keeps transparency
async function fitImage(file, base) {
  const url = await readFile(file);
  const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });
  const [mw, mh] = IMG_PX[base] || [1125, 1515];
  const k = Math.min(1, mw / img.width, mh / img.height);
  const c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(img.width * k)); c.height = Math.max(1, Math.round(img.height * k));
  c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
  return c.toDataURL('image/png');
}

const Btn = ({ children, primary, className = '', ...p }) => (
  <button type="button" {...p}
          className={`inline-flex items-center justify-center gap-1.5 rounded-xl px-3.5 py-2 text-[12.5px] font-semibold transition disabled:opacity-50 ${primary ? 'bg-[#2F6BFF] text-white shadow-[0_8px_18px_-10px_rgba(47,107,255,.9)] hover:bg-[#2559DB]' : 'border border-[#E1E8F5] bg-white text-[#334155] hover:border-[#2F6BFF] hover:text-[#2F6BFF]'} ${className}`}>
    {children}
  </button>
);
const Lbl = ({ children, hint }) => (
  <p className="mb-1 text-[12px] font-semibold text-[#334155]">{children}{hint && <span className="ml-1 font-normal text-[#94A3B8]">{hint}</span>}</p>
);
const inputCls = 'w-full rounded-lg border border-[#E1E8F5] bg-white px-3 py-2 text-[12.5px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]';
const Toggle = ({ on, onChange, label, hint }) => (
  <label className="flex cursor-pointer items-start justify-between gap-3 py-1.5">
    <span className="min-w-0"><span className="block text-[12.5px] font-semibold text-[#334155]">{label}</span>
      {hint && <span className="block text-[11.5px] text-[#94A3B8]">{hint}</span>}</span>
    <span onClick={(e) => { e.preventDefault(); onChange(!on); }}
          className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition ${on ? 'bg-[#2F6BFF]' : 'bg-[#CBD5E1]'}`}>
      <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition ${on ? 'left-[18px]' : 'left-0.5'}`} />
    </span>
  </label>
);

function ColorRow({ label, value, onChange, optional, hint }) {
  const on = !!value;
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="min-w-0"><span className="block text-[12.5px] font-semibold text-[#334155]">{label}</span>
        {hint && <span className="block text-[11.5px] text-[#94A3B8]">{hint}</span>}</span>
      <span className="flex shrink-0 items-center gap-2">
        {optional && (
          <button type="button" onClick={() => onChange(on ? '' : 'rgb(0,0,0)')} className="text-[11.5px] font-semibold text-[#2F6BFF]">
            {on ? 'Retirer' : 'Choisir'}
          </button>
        )}
        {(on || !optional) && (
          <input type="color" value={rgbToHex(value || 'rgb(0,0,0)')} onChange={(e) => onChange(hexToRgb(e.target.value))}
                 className="h-8 w-10 cursor-pointer rounded-md border border-[#E1E8F5] bg-white p-0.5" />
        )}
      </span>
    </div>
  );
}

function FieldRow({ f, group, onChange, onRemove, onMove, first, last, disabled, note }) {
  const [open, setOpen] = useState(false);
  const insert = (v) => onChange({ ...f, value: `${f.value || ''}${v}` });
  return (
    <div className="rounded-xl border border-[#E6EEFB] bg-white p-2.5">
      <div className="flex items-start gap-2">
        <div className="grid min-w-0 flex-1 grid-cols-1 gap-1.5 sm:grid-cols-[1fr_1.4fr]">
          <input className={inputCls} value={f.label || ''} placeholder="Libellé (facultatif)" disabled={disabled}
                 onChange={(e) => onChange({ ...f, label: e.target.value })} />
          <div className="flex gap-1">
            <input className={inputCls} value={f.value ?? ''} placeholder="Texte ou donnée client" disabled={disabled}
                   onChange={(e) => onChange({ ...f, value: e.target.value })} />
            <select value="" disabled={disabled} onChange={(e) => e.target.value && insert(e.target.value)}
                    title="Insérer une donnée du client"
                    className="w-10 shrink-0 cursor-pointer rounded-lg border border-[#E1E8F5] bg-[#F7FAFF] text-center text-[12px] text-[#2F6BFF]">
              <option value="">＋</option>
              {FIELD_VARS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
        </div>
        <div className="flex shrink-0 flex-col">
          <button type="button" disabled={disabled || first} onClick={() => onMove(-1)} aria-label="Monter" className="rounded p-0.5 text-[#64748B] disabled:opacity-30"><ArrowUp size={13} /></button>
          <button type="button" disabled={disabled || last} onClick={() => onMove(1)} aria-label="Descendre" className="rounded p-0.5 text-[#64748B] disabled:opacity-30"><ArrowDown size={13} /></button>
        </div>
        <button type="button" disabled={disabled} onClick={onRemove} aria-label="Supprimer le champ" className="shrink-0 rounded p-1 text-[#E5484D] hover:bg-[#FEF2F2]"><Trash2 size={14} /></button>
      </div>
      {note && <p className="mt-1.5 rounded-lg bg-[#FFF7E6] px-2 py-1 text-[11.5px] text-[#92400E]">{note}</p>}
      <button type="button" onClick={() => setOpen((o) => !o)} className="mt-1 inline-flex items-center gap-1 text-[11.5px] font-semibold text-[#64748B]">
        Options <ChevronDown size={12} className={open ? 'rotate-180' : ''} />
      </button>
      {open && (
        <div className="mt-1.5 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div>
            <Lbl hint="%@ = la nouvelle valeur">Message de notification</Lbl>
            <input className={inputCls} value={f.changeMessage || ''} placeholder="ex. Vous avez maintenant %@ points" disabled={disabled}
                   onChange={(e) => onChange({ ...f, changeMessage: e.target.value.includes('%@') || !e.target.value ? e.target.value : `${e.target.value} %@` })} />
          </div>
          {!['primaryFields', 'backFields'].includes(group) && (
            <div>
              <Lbl>Alignement</Lbl>
              <select className={inputCls} value={f.textAlignment || ''} disabled={disabled}
                      onChange={(e) => onChange({ ...f, textAlignment: e.target.value || undefined })}>
                {ALIGN.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
          )}
          {group === 'backFields' && (
            <Toggle on={!!(f.dataDetectorTypes || []).length} label="Liens cliquables"
                    hint="Téléphone, adresse, lien et date deviennent actifs"
                    onChange={(v) => onChange({ ...f, dataDetectorTypes: v ? ['PKDataDetectorTypePhoneNumber', 'PKDataDetectorTypeLink', 'PKDataDetectorTypeAddress', 'PKDataDetectorTypeCalendarEvent'] : undefined })} />
          )}
          <p className="text-[11px] text-[#94A3B8] sm:col-span-2">Clé : {f.key}</p>
        </div>
      )}
    </div>
  );
}

const CardDesigner = forwardRef(function CardDesigner({
  edit = true, types = [], formats = [], actions = [], onActionsChange, onSaved,
  identityPanel = null, previewCard = {}, clientPreview = null, externalDirty = false, onSaveAll, onDirtyChange,
  googleDesign = {}, onGoogleChange, googleLinks = [], onGoogleLinksChange, variant = 'classic', inspectorOverride = null,
  onPosterDesign,
}, ref) {
  const v2 = variant === 'v2';
  const [view, setView] = useState('ios27');
  // v2: the preview follows the scroll beside a long column (Paramètres).
  // CSS sticky cannot: the layout's <main> is overflow:auto but the window
  // scrolls, so the preview is moved by hand, within its column.
  const gridRef = useRef(null);
  const stageRef = useRef(null);
  useEffect(() => {
    if (!v2) return undefined;
    let raf = 0;
    const place = () => {
      raf = 0;
      const grid = gridRef.current; const st = stageRef.current;
      if (!grid || !st) return;
      const g = fitRect(grid);
      const side = fitRect(st).left - g.left > 40;            // two columns, not stacked
      const room = grid.offsetHeight - st.offsetHeight;
      const y = side && room > 0 ? Math.max(0, Math.min(room, 16 - g.top)) : 0;
      st.style.transform = y ? `translateY(${Math.round(y)}px)` : '';
    };
    const on = () => { if (!raf) raf = requestAnimationFrame(place); };
    window.addEventListener('scroll', on, true);
    window.addEventListener('resize', on);
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(on) : null;
    if (ro && gridRef.current) ro.observe(gridRef.current);
    on();
    return () => { window.removeEventListener('scroll', on, true); window.removeEventListener('resize', on); ro && ro.disconnect(); if (raf) cancelAnimationFrame(raf); };
  }, [v2]);
  // Apple and Google build their cards differently: one switch, two editors
  // (user, 2026-10-08), the identity tab and the save shared
  const [wallet, setWallet] = useState('apple');
  const [gPreview, setGPreview] = useState(null);
  const [gState, setGState] = useState('');
  const gSeq = useRef(0);
  const [status, setStatus] = useState('loading');      // loading | empty | ready
  const [d, setD] = useState(null);                       // { name, pass, options, images, shown, source }
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState('identite');
  const [preview, setPreview] = useState(null);
  const [pvState, setPvState] = useState('');
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState(null);
  const [crop, setCrop] = useState(null);
  const [showBack, setShowBack] = useState(false);
  const folderRef = useRef(null);
  const filesRef = useRef(null);
  const seq = useRef(0);

  const init = (data, saved) => {
    const shown = data.image_data || {};
    const images = {};
    Object.keys(shown).forEach((n) => { images[n] = saved ? 'saved' : shown[n]; });
    setD({ name: data.name || 'Mon design', pass: data.pass, options: data.options || {}, images, shown, source: data.source || 'editor' });
    setStatus('ready');
  };
  const load = () => ownerAPI.passDesignerFull()
    .then((r) => (r.data?.active ? init(r.data, true) : setStatus('empty')))
    .catch(() => setStatus('empty'));
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { onDirtyChange && onDirtyChange(dirty); }, [dirty]); // eslint-disable-line react-hooks/exhaustive-deps

  // live preview: the server builds the pass from the unsaved design and the
  // page's unsaved card fields (no design yet: FidClic's own card)
  const ready = status === 'ready' && d;
  const pvKey = status === 'loading' ? '' : JSON.stringify({ c: previewCard, a: actions, ...(ready ? { p: d.pass, o: d.options,
    i: Object.entries(d.images).map(([n, v]) => [n, v === 'saved' ? 's' : v.length]) } : {}) });
  useEffect(() => {
    if (!pvKey) return undefined;
    const my = ++seq.current;
    setPvState('loading');
    const t = setTimeout(() => {
      ownerAPI.walletPreview({ card: { ...previewCard, featured_actions: actions }, visits: 3,
        design: ready ? { pass: d.pass, images: d.images, options: d.options } : {} })
        .then((r) => { if (my === seq.current) { setPreview(r.data); setPvState(''); } })
        .catch(() => { if (my === seq.current) setPvState('error'); });
    }, 300);   // the server keeps composed images: a short wait is enough
    return () => clearTimeout(t);
  }, [pvKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Google's live preview: the class + object the server would send
  const gKey = wallet === 'google' ? JSON.stringify(previewCard) : '';
  useEffect(() => {
    if (!gKey) return undefined;
    const my = ++gSeq.current;
    setGState('loading');
    const t = setTimeout(() => {
      ownerAPI.googlePreview({ card: previewCard, visits: 3 })
        .then((r) => { if (my === gSeq.current) { setGPreview(r.data); setGState(''); } })
        .catch(() => { if (my === gSeq.current) setGState('error'); });
    }, 400);
    return () => clearTimeout(t);
  }, [gKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // « Copier depuis Apple »: the Apple design's colour, code, values and back
  // rows as the Google card's starting point
  const copyFromApple = () => {
    const pj = preview?.pass_json || {};
    const VAR = { '{prenom}': 'name', '{nom}': 'name', '{tampons}': 'stamps', '{points}': 'points', '{statut}': 'tier',
      '{offre}': 'offer', '{recompense}': 'reward', '{visites}': 'visits', '{carte}': 'card' };
    const blk = ready ? (d.pass[styleOf(d.pass)] || {}) : {};
    const keys = [];
    ['headerFields', 'primaryFields', 'secondaryFields', 'auxiliaryFields', 'footerFields'].forEach((g) => (blk[g] || []).forEach((f) => {
      const k = VAR[String(f.value || '').trim()];
      if (k && !keys.includes(k)) keys.push(k);
    }));
    const pick = keys.length ? keys : ['stamps', 'points', 'tier'];
    const rows = [];
    for (let i = 0; i < pick.length && rows.length < 3; i += 2) rows.push(pick.slice(i, i + 2));
    const CODE = { PKBarcodeFormatQR: 'QR_CODE', PKBarcodeFormatAztec: 'AZTEC', PKBarcodeFormatPDF417: 'PDF_417',
      PKBarcodeFormatCode128: 'CODE_128', PKBarcodeFormatCode39: 'CODE_39', PKBarcodeFormatEAN13: 'EAN_13', PKBarcodeFormatCodabar: 'CODABAR' };
    onGoogleChange && onGoogleChange({
      bg_color: pj.backgroundColor ? rgbToHex(pj.backgroundColor) : undefined,
      barcode: CODE[(pj.barcodes || [])[0]?.format] || 'QR_CODE',
      rows, hero: 'fidclic', logo: 'round',
      details: (blk.backFields || []).filter((f) => f.label && f.value).slice(0, 6).map((f) => ({ label: String(f.label), value: String(f.value) })),
    });
    const withUrl = (actions || []).filter((a) => /^https:\/\//.test(a.url || ''));
    if (withUrl.length && onGoogleLinksChange) {
      onGoogleLinksChange(withUrl.slice(0, 3).map((a) => ({ label: types.find((t) => t.type === a.type)?.label || a.type, uri: a.url })));
    }
  };

  const change = (fn) => { setD((cur) => fn(cur)); setDirty(true); setMsg(null); };
  const style = d ? styleOf(d.pass) : null;
  const block = (d && style && d.pass[style]) || {};
  const setPass = (patch) => change((cur) => ({ ...cur, pass: { ...cur.pass, ...patch } }));
  const setBlock = (patch) => change((cur) => ({ ...cur, pass: { ...cur.pass, [style]: { ...cur.pass[style], ...patch } } }));
  const setOpt = (patch) => change((cur) => ({ ...cur, options: { ...cur.options, ...patch } }));

  const changeStyle = (to) => change((cur) => {
    const from = styleOf(cur.pass);
    const next = { ...cur.pass };
    const conv = convertStyle(next[from], from, to);
    STYLE_KEYS.forEach((k) => delete next[k]);
    next[to] = conv;
    return { ...cur, pass: next };
  });

  const setImage = (base, dataUrl) => change((cur) => {
    const images = { ...cur.images };
    const shown = { ...cur.shown };
    Object.keys(images).filter((n) => baseOf(n) === base).forEach((n) => { delete images[n]; delete shown[n]; });
    if (dataUrl) { images[`${base}@3x.png`] = dataUrl; shown[`${base}@3x.png`] = dataUrl; }
    return { ...cur, images, shown };
  });
  const pickImage = async (base, file) => {
    if (!file) return;
    if (['background', 'strip'].includes(base)) {
      const [w, h] = base === 'strip' ? (style === 'eventTicket' ? [1125, 294] : [1125, 432]) : (style === 'eventTicket' ? [540, 660] : [1035, 1515]);
      const url = await new Promise((resolve) => setCrop({ file, w, h, base, resolve }));
      if (url) setImage(base, url);
      return;
    }
    setImage(base, await fitImage(file, base));
  };

  const start = async () => {
    setBusy('start');
    try { const r = await ownerAPI.passDesignerStarter(); init(r.data, false); setDirty(true); } finally { setBusy(''); }
  };
  const save = async () => {
    if (!d || !dirty) return;
    setBusy('save'); setMsg(null);
    try {
      await ownerAPI.importPassDesigner({ name: d.name, pass_json: JSON.stringify(d.pass), images: d.images,
        options: d.options, featured_actions: actions, source: 'editor' });
      await load();
      setDirty(false);
      setMsg({ ok: true, text: 'Design enregistré · les cartes déjà dans Wallet se mettent à jour' });
      onSaved && onSaved();
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || 'Enregistrement impossible.' });
      throw e;
    } finally { setBusy(''); }
  };
  // A poster design (user, 2026-10-12): the page's « Image de fond » and
  // « Bande du bas » are this design's too — it draws iOS 27 with ITS
  // background and footer colour, so the page sets them here as well.
  const posterDesign = Boolean(ready && style === 'posterGeneric');
  const footerNow = posterDesign ? (d.pass.footerBackgroundColor || '') : null;
  useEffect(() => {
    onPosterDesign && onPosterDesign(posterDesign ? { footer: footerNow } : null);
  }, [posterDesign, footerNow]); // eslint-disable-line react-hooks/exhaustive-deps
  useImperativeHandle(ref, () => ({
    save,
    reset: () => { setDirty(false); return load(); },
    setPosterFooter: (rgb) => { if (posterDesign) setPass({ footerBackgroundColor: rgb || undefined }); },
  }));
  const remove = async () => {
    if (!window.confirm('Revenir au design FidClic ? Ce design sera retiré des cartes de vos clients.')) return;
    setBusy('remove');
    try { await ownerAPI.removePassDesigner(); setD(null); setPreview(null); setDirty(false); setStatus('empty'); onSaved && onSaved(); }
    finally { setBusy(''); }
  };

  // Pass Designer's own template: a .pkpasstemplate folder (dropped or
  // picked) or its .zip
  const importTemplate = async (fileList, folderName = '') => {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    setBusy('import'); setMsg(null);
    try {
      const zip = files.find((f) => /\.zip$/i.test(f.name));
      if (zip) {
        await ownerAPI.importPassDesigner({ zip: await readFile(zip) });
      } else {
        const passFile = files.find((f) => f.name === 'pass.json');
        if (!passFile) throw new Error('Le fichier pass.json du modèle est introuvable.');
        const images = {};
        for (const f of files.filter((x) => IMG_RE.test(x.name))) images[f.name] = await readFile(f);
        const folder = (folderName || (files[0].webkitRelativePath || '').split('/')[0]).replace(/\.pkpasstemplate$/i, '');
        await ownerAPI.importPassDesigner({ name: folder || 'Modèle Pass Designer', pass_json: await passFile.text(), images, source: 'import' });
      }
      await load();
      setDirty(false);
      setMsg({ ok: true, text: 'Modèle importé : modifiez-le ici, l’aperçu suit.' });
      onSaved && onSaved();
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || e?.message || 'Import impossible.' });
    } finally { setBusy(''); }
  };
  const dropTemplate = async (e) => {
    e.preventDefault();
    const entry = Array.from(e.dataTransfer?.items || []).map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).find(Boolean);
    if (entry && entry.isDirectory) {
      const entries = await new Promise((res) => entry.createReader().readEntries(res, () => res([])));
      const files = await Promise.all(entries.filter((x) => x.isFile).map((x) => new Promise((res) => x.file(res, () => res(null)))));
      return importTemplate(files.filter(Boolean), entry.name);
    }
    return importTemplate(e.dataTransfer?.files);
  };
  const importBox = (
    <div className="rounded-xl border border-dashed border-[#B9CCF5] bg-[#F8FAFF] p-3" onDragOver={(e) => e.preventDefault()} onDrop={dropTemplate}>
      <p className="text-[12.5px] font-semibold text-[#334155]">Importer un modèle Apple « Pass Designer »</p>
      <p className="mt-0.5 text-[11.5px] text-[#64748B]">Glissez le .pkpasstemplate depuis le Finder dans ce cadre, ou choisissez le dossier ou son .zip.</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <Btn disabled={!edit || !!busy} onClick={() => folderRef.current?.click()}><Upload size={13} /> {busy === 'import' ? 'Import…' : 'Dossier'}</Btn>
        <Btn disabled={!edit || !!busy} onClick={() => filesRef.current?.click()}>.zip</Btn>
      </div>
      <input ref={folderRef} type="file" className="hidden" webkitdirectory="" directory="" onChange={(e) => { importTemplate(e.target.files); e.target.value = ''; }} />
      <input ref={filesRef} type="file" className="hidden" multiple accept=".zip,.json,.png,application/zip,application/json,image/png"
             onChange={(e) => { importTemplate(e.target.files); e.target.value = ''; }} />
    </div>
  );

  if (status === 'loading') {
    return <div className="flex items-center gap-2 py-8 text-[13px] text-[#64748B]"><Loader2 size={15} className="animate-spin" /> Chargement du design…</div>;
  }
  const startBox = (
    <div className="grid gap-3">
      <div className="rounded-xl border border-[#E6EEFB] bg-[#FAFCFF] p-4">
        <p className="text-[13.5px] font-bold text-[#0B1C3F]">Concevez votre carte comme dans Pass Designer</p>
        <p className="mt-1 text-[12.5px] text-[#64748B]">
          Style, couleurs, images, code-barres, boutons et champs, avec l’aperçu iOS 27 et iOS 26 en direct.
          Les données de chaque client (prénom, points, tampons, offre…) se remplissent toutes seules.
        </p>
        <Btn primary className="mt-3" disabled={!edit || !!busy} onClick={start}>
          {busy === 'start' ? <Loader2 size={14} className="animate-spin" /> : <LayoutTemplate size={14} />} Créer mon design à partir de ma carte actuelle
        </Btn>
      </div>
      {importBox}
    </div>
  );

  const groups = GROUPS[style] || [];
  const imgs = !ready ? [] : [...(IMAGES[style] || []), ...(style === 'posterGeneric' && d.options.fallback !== 'fidclic'
    ? [d.options.fallback === 'storeCard' || d.options.fallback === 'coupon' ? ['strip', 'Bannière (iOS 26)', '375 × 144 pt'] : ['thumbnail', 'Vignette (iOS 26)', '90 × 90 pt']]
    : []), ICON_IMAGE]
    .filter((x, i, a) => a.findIndex((y) => y[0] === x[0]) === i)
    // the logo and the poster's photo are set once, in « Identité » (user,
    // 2026-10-12: « images se htao »): the server draws the design with them
    .filter(([base]) => !['logo', 'primaryLogo'].includes(base) && !(base === 'background' && style === 'posterGeneric'));
  const bc = (ready && (d.pass.barcodes || [])[0]) || { format: 'PKBarcodeFormatQR' };
  const ios27Only = (f) => formats.find((x) => x.format === f)?.ios27_only;
  const styles = preview?.styles || [];
  const fbStyle = styles.find((s2) => s2 !== 'posterGeneric');
  const G_TABS = [['identite', 'Identité', Fingerprint], ['g_couleur', 'Couleur et logo', Palette], ['g_banniere', 'Bannière', ImagePlus],
    ['g_lignes', 'Lignes', Rows3], ['g_code', 'Code-barres', Barcode], ['g_details', 'Détails et liens', ListTree], ['g_notif', 'Notifications', Bell]];
  // « Champs » right after Identité: it is the card's text (user, 2026-10-12)
  const TABS = wallet === 'google' ? G_TABS : [['identite', 'Identité', Fingerprint], ['champs', 'Champs', ListTree],
    ['style', 'Style', Palette], ['images', 'Images', ImageIcon], ['code', 'Code-barres', Barcode],
    ['boutons', 'Boutons', MousePointerClick]];

  // ── v2: one iPhone at a time, picked with the version buttons ──
  const pj = preview?.pass_json;
  const appleViews = [];
  if (pj) {
    const poster = styles.includes('posterGeneric');
    const newCode = !poster && NEW_CODES.has((pj.barcodes || [])[0]?.format);
    appleViews.push({ key: 'ios27', title: 'iOS 27', badge: 'Nouveau',
      sub: poster ? 'Design moderne (Poster)' : 'Même carte que sur iOS 26',
      render: (w) => <PassPreview pj={pj} style={poster ? 'posterGeneric' : styles[0]} images={preview.images} actions={poster ? preview.actions : []} width={w} /> });
    const old = poster ? fbStyle : styles[0];
    if (old) {
      appleViews.push({ key: 'ios26', title: 'iOS 26 et avant', sub: newCode ? 'Code de secours' : 'Design classique', chrome: 'ios26',
        render: (w) => <PassPreview pj={pj} style={old} images={preview.images} width={w} legacy={poster || newCode} /> });
    }
  }
  const dotViews = [...appleViews, ...(clientPreview ? [{ key: 'web', title: 'Page web du client', render: () => clientPreview }] : [])];
  const current = dotViews.find((x) => x.key === view) || dotViews[0];
  const stageState = wallet === 'google' ? gState : pvState;
  const stage = (
    <div ref={stageRef} className="min-w-0 rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] sm:p-6">
      <header className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[19px] font-bold tracking-[-0.01em] text-[#0B1C3F]">
            {wallet === 'google' ? 'Aperçu de la carte Google Wallet' : 'Aperçu de la carte sur iPhone'}
          </h2>
          <p className="mt-0.5 text-[13px] text-[#64748B]">
            {wallet === 'google' ? 'Prévisualisez le design de votre carte de fidélité.'
              : 'Voyez exactement comment votre carte apparaîtra dans Apple Wallet selon la version d’iOS.'}
          </p>
        </div>
        {stageState === 'loading' && <Loader2 size={16} className="mt-1 shrink-0 animate-spin text-[#94A3B8]" />}
        {stageState === 'error' && <span className="mt-1 shrink-0 text-[11.5px] text-[#B91C1C]">Aperçu indisponible</span>}
      </header>
      {wallet === 'google' ? (
        gPreview ? (
          <div className="flex flex-col items-center py-2">
            <GoogleWalletPreview data={gPreview} width={320} />
            {!gPreview.configured && (
              <p className="mt-4 max-w-[360px] text-center text-[11.5px] text-[#B45309]">
                Les clients pourront ajouter cette carte dès que l’accès émetteur Google Wallet sera validé.
              </p>
            )}
            <p className="mt-2 text-center text-[11px] text-[#94A3B8]">
              Exemple : {gPreview.sample?.name} — construit par le serveur, comme la vraie carte Google.
            </p>
          </div>
        ) : (
          <div className="flex h-72 items-center justify-center text-[12.5px] text-[#94A3B8]">{gState === 'error' ? 'Aperçu indisponible' : 'Chargement de l’aperçu…'}</div>
        )
      ) : preview && current ? (
        <>
          {appleViews.length > 0 && <VersionSwitch views={appleViews} value={current.key} onChange={setView} />}
          <div className="mt-5">
            {/* the pass at ~88 % of the screen's width, as Wallet shows it */}
            <IphoneFrame width={PHONE_W} chrome={current.chrome || 'none'}>
              {current.key === 'web'
                ? <div style={{ width: Math.round(screenWidth(PHONE_W) * 0.9) }}>{current.render()}</div>
                : current.render(Math.round(screenWidth(PHONE_W) * 0.88))}
            </IphoneFrame>
            <Dots views={dotViews} value={current.key} onChange={setView} />
            <p className="mt-2 text-center text-[11.5px] font-semibold text-[#64748B]">{current.title}</p>
          </div>
          {current.key !== 'web' && (
            <>
              <button type="button" onClick={() => setShowBack((b) => !b)}
                      className="mx-auto mt-3 flex items-center gap-1 text-[12px] font-semibold text-[#2F6BFF]">
                Au dos de la carte <ChevronDown size={14} className={showBack ? 'rotate-180' : ''} />
              </button>
              {showBack && <div className="mx-auto mt-2 max-w-[340px]"><PassBack pj={pj} style={styles[0]} /></div>}
              <p className="mt-2 text-center text-[11px] text-[#94A3B8]">
                Exemple : {preview.sample?.name}, {preview.sample?.visits} visites — construit par le serveur, comme le vrai pass.
              </p>
            </>
          )}
        </>
      ) : (
        <div className="flex h-72 items-center justify-center text-[12.5px] text-[#94A3B8]">Chargement de l’aperçu…</div>
      )}
    </div>
  );

  return (
    <div ref={gridRef} className={v2 ? 'grid items-start gap-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]' : 'grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]'}>
      {/* ── the inspector (or, in v2, another step's content over it) ── */}
      {v2 && inspectorOverride && <div className="min-w-0 space-y-4">{inspectorOverride}</div>}
      <div className={v2 ? `min-w-0 rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] sm:p-6${inspectorOverride ? ' hidden' : ''}` : 'min-w-0'}>
        {v2 && (
          <header className="mb-4">
            <h2 className="text-[19px] font-bold tracking-[-0.01em] text-[#0B1C3F]">Design de la carte</h2>
            <p className="mt-0.5 text-[13px] text-[#64748B]">Personnalisez l’apparence de votre carte de fidélité.</p>
          </header>
        )}
        {v2 ? (
          <div className="mb-4"><WalletSwitch value={wallet} onChange={(k) => { setWallet(k); setTab('identite'); }} /></div>
        ) : (
        <div className="mb-3 inline-flex rounded-xl bg-[#F1F5F9] p-1">
          {[['apple', 'Apple Wallet'], ['google', 'Google Wallet']].map(([k, label]) => (
            <button key={k} type="button" onClick={() => { setWallet(k); setTab('identite'); }}
                    className={`rounded-lg px-4 py-1.5 text-[12.5px] font-semibold transition ${wallet === k ? 'bg-[#2F6BFF] text-white shadow-[0_6px_14px_-8px_rgba(47,107,255,.9)]' : 'text-[#64748B]'}`}>
              {label}
            </button>
          ))}
        </div>
        )}
        {wallet === 'apple' && ready && (
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <input className={`${inputCls} max-w-[240px] font-semibold`} value={d.name} disabled={!edit}
                   onChange={(e) => change((cur) => ({ ...cur, name: e.target.value }))} aria-label="Nom du design" />
            {dirty && <span className="rounded-full bg-[#FFF7E6] px-2 py-0.5 text-[11px] font-semibold text-[#B45309]">Non enregistré</span>}
          </div>
        )}
        <div className="mb-3 flex flex-wrap gap-1 rounded-xl bg-[#F1F5F9] p-1">
          {TABS.map(([k, label, Icon]) => (
            <button key={k} type="button" onClick={() => setTab(k)}
                    className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12.5px] font-semibold transition ${tab === k ? 'bg-white text-[#2F6BFF] shadow-sm' : 'text-[#64748B]'}`}>
              <Icon size={13} /> {label}
            </button>
          ))}
        </div>
        {tab === 'identite' && (
          <div>
            <p className="mb-3 text-[12px] text-[#64748B]">
              Le nom, les couleurs, le logo et la bannière de votre carte : ceux de la carte iOS 26 et avant,
              de la page web de vos clients et de Google Wallet.
            </p>
            {identityPanel}
          </div>
        )}
        {wallet === 'google' && tab !== 'identite' && (
          <>
            <GoogleDesignEditor tab={tab} value={googleDesign} disabled={!edit}
                                onChange={(patch) => onGoogleChange && onGoogleChange(patch)}
                                links={googleLinks} onLinksChange={(rows) => onGoogleLinksChange && onGoogleLinksChange(rows)}
                                rowFields={gPreview?.row_fields || {}} codes={gPreview?.codes || {}} />
            <Btn className="mt-4" disabled={!edit} onClick={copyFromApple}><Copy size={13} /> Copier depuis le design Apple</Btn>
          </>
        )}
        {wallet === 'apple' && tab !== 'identite' && !ready && startBox}
        {wallet === 'apple' && ready && (
        <fieldset disabled={!edit} className="m-0 min-w-0 border-0 p-0">
          {tab === 'style' && (
            <div className="space-y-4">
              <div>
                <Lbl>Style de la carte</Lbl>
                <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                  {STYLES.map((s2) => (
                    <button key={s2.key} type="button" onClick={() => style !== s2.key && changeStyle(s2.key)} title={s2.hint}
                            className={`rounded-lg border px-2.5 py-2 text-left text-[12px] font-semibold ${style === s2.key ? 'border-[#2F6BFF] bg-[#EAF1FF] text-[#2F6BFF]' : 'border-[#E6EEFB] bg-white text-[#334155] hover:border-[#2F6BFF]'}`}>
                      {s2.label}
                      <span className="mt-0.5 block text-[10.5px] font-normal leading-snug text-[#94A3B8]">{s2.hint}</span>
                    </button>
                  ))}
                </div>
              </div>
              {style === 'boardingPass' && (
                <div>
                  <Lbl>Transport</Lbl>
                  <select className={inputCls} value={block.transitType || 'PKTransitTypeGeneric'} onChange={(e) => setBlock({ transitType: e.target.value })}>
                    {TRANSIT.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
              )}
              {style === 'posterGeneric' && (
                <div>
                  <Lbl hint="les iPhone qui n’ont pas encore iOS 27">Carte pour iOS 26 et avant</Lbl>
                  <select className={inputCls} value={d.options.fallback || 'fidclic'} onChange={(e) => setOpt({ fallback: e.target.value })}>
                    {d.options.fallback === 'template' && <option value="template">Celle du modèle importé</option>}
                    {FALLBACKS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
              )}
              {/* « Texte du logo » is gone: the shop's name is set in Identité (user, 2026-10-12) */}
              <div className="rounded-xl border border-[#E6EEFB] px-3 py-1">
                <ColorRow label="Couleur du texte" value={d.pass.foregroundColor} onChange={(v) => setPass({ foregroundColor: v })} />
                <ColorRow label="Couleur de fond" value={d.pass.backgroundColor} onChange={(v) => setPass({ backgroundColor: v })}
                          hint={style === 'posterGeneric' ? 'Le poster montre son image ; ce fond sert à la carte iOS 26' : undefined} />
                <ColorRow label="Couleur des libellés" value={d.pass.labelColor} optional onChange={(v) => setPass({ labelColor: v })}
                          hint="Sans couleur, Wallet la choisit" />
                {['storeCard', 'coupon', 'eventTicket'].includes(style) || ['storeCard', 'coupon'].includes(d.options.fallback) ? (
                  <ColorRow label="Libellés sur la bannière" value={d.pass.stripColor} optional onChange={(v) => setPass({ stripColor: v })} />
                ) : null}
                {style === 'posterGeneric' && (
                  <ColorRow label="Fond du pied" value={d.pass.footerBackgroundColor} optional onChange={(v) => setPass({ footerBackgroundColor: v })}
                            hint="Remplace la matière floutée sous les champs" />
                )}
              </div>
              {style === 'posterGeneric' && (
                <div className="rounded-xl border border-[#E6EEFB] px-3 py-1">
                  <Toggle on={!d.pass.suppressHeaderDarkening} label="Assombrir le haut de l’image"
                          hint="Garde le logo et l’en-tête lisibles sur une photo claire"
                          onChange={(v) => setPass({ suppressHeaderDarkening: !v })} />
                  <Toggle on={!!d.pass.useAutomaticColors} label="Couleurs automatiques"
                          hint="Wallet calcule le texte et les libellés depuis l’image"
                          onChange={(v) => setPass({ useAutomaticColors: v })} />
                </div>
              )}
            </div>
          )}

          {tab === 'images' && (
            <>
            <p className="mb-3 rounded-xl border border-[#E6EEFB] bg-[#F8FAFF] px-3 py-2 text-[12px] text-[#475569]">
              Le logo et l’image de fond (avec « Ajuster ») se règlent dans{' '}
              <button type="button" onClick={() => setTab('identite')} className="font-semibold text-[#2F6BFF]">Identité</button> :
              une seule fois, pour toutes les versions de la carte.
            </p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {imgs.map(([base, label, size]) => {
                const n = imgName(d.shown, base);
                return (
                  <div key={base} className="rounded-xl border border-[#E6EEFB] p-3">
                    <p className="text-[12.5px] font-semibold text-[#334155]">{label}</p>
                    <p className="text-[11px] text-[#94A3B8]">{size}{base === 'icon' ? ' · sinon votre logo' : ''}</p>
                    <div className="mt-2 flex h-24 items-center justify-center overflow-hidden rounded-lg bg-[repeating-conic-gradient(#EEF2F9_0%_25%,#fff_0%_50%)] bg-[length:14px_14px]">
                      {n ? <img src={d.shown[n]} alt="" className="max-h-full max-w-full object-contain" /> : <span className="text-[11.5px] text-[#94A3B8]">Aucune</span>}
                    </div>
                    <div className="mt-2 flex gap-2">
                      <label className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-[#E1E8F5] px-2.5 py-1.5 text-[12px] font-semibold text-[#334155] hover:border-[#2F6BFF]">
                        <Upload size={12} /> {n ? 'Changer' : 'Ajouter'}
                        <input type="file" accept="image/*" className="hidden" onChange={(e) => { pickImage(base, e.target.files?.[0]); e.target.value = ''; }} />
                      </label>
                      {n && <button type="button" onClick={() => setImage(base, null)} className="rounded-lg px-2 text-[12px] font-semibold text-[#E5484D] hover:bg-[#FEF2F2]">Retirer</button>}
                    </div>
                  </div>
                );
              })}
            </div>
            </>
          )}

          {tab === 'code' && (
            <div className="space-y-4">
              <div>
                <Lbl>Format</Lbl>
                <select className={inputCls} value={bc.format} onChange={(e) => setPass({ barcodes: [{ ...bc, format: e.target.value }] })}>
                  {formats.map((f) => <option key={f.format} value={f.format}>{f.label}{f.ios27_only ? ' — iOS 27' : ''}</option>)}
                </select>
                <p className="mt-1 text-[11.5px] text-[#94A3B8]">
                  QR, PDF417 et Aztec portent le lien de la carte (un téléphone l’ouvre) ; Code 128 et Code 39 le numéro FT-… ;
                  EAN-13, ITF et Codabar un code de chiffres. La caisse FidClic lit les huit.
                </p>
              </div>
              <div>
                <Lbl hint="ce que lisent les iPhone sans iOS 27">Code de secours</Lbl>
                <select className={inputCls} value={d.options.barcode_fallback || ''} onChange={(e) => setOpt({ barcode_fallback: e.target.value || undefined })}>
                  <option value="">{ios27Only(bc.format) ? 'QR code (automatique)' : 'Aucun (le format choisi marche partout)'}</option>
                  {formats.filter((f) => !f.ios27_only && f.format !== bc.format).map((f) => <option key={f.format} value={f.format}>{f.label}</option>)}
                </select>
              </div>
              <div>
                <Lbl>Texte sous le code</Lbl>
                <select className={inputCls} value={d.options.alt_text || 'card'} onChange={(e) => setOpt({ alt_text: e.target.value })}>
                  <option value="card">Le numéro de carte du client</option>
                  <option value="custom">Un texte à moi</option>
                  <option value="none">Rien</option>
                </select>
                {d.options.alt_text === 'custom' && (
                  <input className={`${inputCls} mt-1.5`} value={d.options.alt_custom || ''} placeholder="ex. Membre {prenom}"
                         onChange={(e) => setOpt({ alt_custom: e.target.value })} />
                )}
              </div>
            </div>
          )}

          {tab === 'boutons' && (
            <div>
              <p className="mb-2 text-[12px] text-[#64748B]">Sous la carte, sur iOS 27. Chaque clic est compté dans vos statistiques Wallet.</p>
              <FeaturedActionsEditor types={types} value={actions} disabled={!edit}
                                     onChange={(rows) => { onActionsChange && onActionsChange(rows); setMsg(null); }} />
            </div>
          )}

          {tab === 'champs' && (
            <div className="space-y-4">
              <p className="text-[12px] text-[#64748B]">
                Écrivez le texte de votre commerce, ou insérez avec ＋ une donnée du client : elle est remplie pour chacun.
                Un champ qui ne contient que {'{offre}'} n’apparaît que pendant une campagne.
              </p>
              {[...groups, ['backFields', 'Au dos (⋯ › Détails du pass)', 99]].map(([g, label, max]) => {
                const rows = block[g] || [];
                const set = (next) => setBlock({ [g]: next });
                // what the card really shows (user, 2026-10-12: « ek field hai lekin
                // usme changes krne se kuch dikhta hi nhi ») — read off the preview
                const pjb = pvState ? null : (preview?.pass_json || {})[style];
                const shown = pjb ? new Set(['headerFields', 'primaryFields', 'secondaryFields', 'auxiliaryFields', 'footerFields', 'backFields']
                  .flatMap((k) => (pjb[k] || []).map((x) => x.key))) : null;
                const keyOf = (x, i) => String(x.key || '').trim().replace(/[^A-Za-z0-9_]/g, '_') || `${g.slice(0, -6)}${i + 1}`;
                const why = (x, i) => {
                  if (!shown || shown.has(keyOf(x, i))) return null;
                  const v = String(x.value || '');
                  if (!v.trim() && !String(x.label || '').trim()) return 'Champ vide : il n’apparaît pas.';
                  if (/\{points\}/i.test(v) && previewCard.programme === 'stamps') return 'Pas sur la carte : programme Tampons, les points ne s’affichent pas (Paramètres › Type de programme).';
                  if (/\{(tampons|jauge|stamps)\}/i.test(v) && previewCard.programme && previewCard.programme !== 'stamps') return 'Pas sur la carte : programme à points, sans tampons.';
                  if (/\{(offre|offer)\}/i.test(v)) return 'Visible seulement pendant une campagne.';
                  if (/\{(recompense|reward)\}/i.test(v)) return 'Pas sur la carte : la récompense est réglée « Au dos » ou « Non » (Paramètres › Récompense).';
                  return 'Pas affiché sur la carte.';
                };
                // what FidClic adds to this group, set elsewhere
                const added = g === 'primaryFields' && pjb ? (pjb.primaryFields || []).filter((x) => ['jauge', 'reward'].includes(x.key)
                  && !rows.some((r, i) => keyOf(r, i) === x.key)) : [];
                return (
                  <div key={g}>
                    <div className="mb-1.5 flex items-center justify-between">
                      <p className="text-[12.5px] font-bold text-[#0B1C3F]">{label} <span className="font-normal text-[#94A3B8]">{max < 99 ? `${rows.length}/${max}` : ''}</span></p>
                      <button type="button" disabled={rows.length >= max}
                              onClick={() => set([...rows, { key: `${g.replace('Fields', '')}_${Date.now().toString(36)}`, label: '', value: '' }])}
                              className="inline-flex items-center gap-1 text-[12px] font-semibold text-[#2F6BFF] disabled:opacity-40"><Plus size={13} /> Ajouter</button>
                    </div>
                    <div className="space-y-1.5">
                      {rows.map((f, i) => (
                        <FieldRow key={f.key} f={f} group={g} first={i === 0} last={i === rows.length - 1} note={why(f, i)}
                                  onChange={(nf) => set(rows.map((x, j) => (j === i ? nf : x)))}
                                  onRemove={() => set(rows.filter((_, j) => j !== i))}
                                  onMove={(dir) => { const n = [...rows]; [n[i], n[i + dir]] = [n[i + dir], n[i]]; set(n); }} />
                      ))}
                      {added.map((x) => (
                        <div key={x.key} className="rounded-xl border border-dashed border-[#B9CCF5] bg-[#F8FAFF] px-3 py-2">
                          <p className="text-[12px] text-[#334155]">
                            <span className="font-semibold">{x.label}</span>{' '}<span translate="no">{String(x.value)}</span>
                          </p>
                          <p className="mt-0.5 text-[11px] text-[#64748B]">
                            Ajouté par FidClic, sur la carte de chaque client. Réglage : Paramètres › {x.key === 'jauge' ? 'Type de programme et Forme des tampons' : 'Récompense'}.
                          </p>
                        </div>
                      ))}
                      {!rows.length && !added.length && <p className="text-[11.5px] text-[#94A3B8]">Aucun champ.</p>}
                    </div>
                    {g === 'backFields' && (
                      <p className="mt-1.5 text-[11.5px] text-[#94A3B8]">
                        FidClic ajoute ensuite au dos : l’offre du moment (c’est elle qui envoie la notification d’une campagne),
                        la prochaine récompense, le programme, le lien de la carte en ligne, votre adresse, téléphone et site.
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </fieldset>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-[#EEF2F9] pt-4">
          <Btn primary disabled={!edit || !!busy || !(dirty || externalDirty)} onClick={() => (onSaveAll ? onSaveAll() : save())}>
            {busy === 'save' ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} Enregistrer
          </Btn>
          {ready && <Btn disabled={!edit || !!busy} onClick={remove}><RotateCcw size={13} /> Revenir au design FidClic</Btn>}
          {msg && <span className={`text-[12px] ${msg.ok ? 'text-[#15803D]' : 'text-[#B91C1C]'}`}>{msg.ok ? <Check size={13} className="mr-1 inline" /> : '⚠ '}{msg.text}</span>}
        </div>
        {ready && <div className="mt-4">{importBox}</div>}
      </div>

      {/* ── the live preview ── */}
      {v2 ? stage : (
      <div className="min-w-0 rounded-2xl bg-[#F7FAFF] p-4">
        <div className="mb-3 flex items-center justify-between">
          <p className="inline-flex items-center gap-1.5 text-[12.5px] font-bold text-[#0B1C3F]"><Smartphone size={14} /> Aperçu en direct</p>
          {(wallet === 'google' ? gState : pvState) === 'loading' && <Loader2 size={14} className="animate-spin text-[#94A3B8]" />}
          {(wallet === 'google' ? gState : pvState) === 'error' && <span className="text-[11.5px] text-[#B91C1C]">Aperçu indisponible</span>}
        </div>
        {wallet === 'google' ? (
          gPreview ? (
            <>
              <GoogleWalletPreview data={gPreview} width={240} />
              {!gPreview.configured && (
                <p className="mt-3 text-center text-[11.5px] text-[#B45309]">
                  Les clients pourront ajouter cette carte dès que l’accès émetteur Google Wallet sera validé.
                </p>
              )}
              <p className="mt-2 text-center text-[11px] text-[#94A3B8]">
                Exemple : {gPreview.sample?.name} — construit par le serveur, comme la vraie carte Google.
              </p>
            </>
          ) : (
            <div className="flex h-64 items-center justify-center text-[12.5px] text-[#94A3B8]">{gState === 'error' ? 'Aperçu indisponible' : 'Chargement de l’aperçu…'}</div>
          )
        ) : preview ? (
          <>
            <div className="flex flex-wrap justify-center gap-5">
              {styles.includes('posterGeneric') ? (
                <>
                  <div>
                    <p className="mb-1.5 text-center text-[11px] font-semibold text-[#64748B]">iOS 27</p>
                    <PassPreview pj={preview.pass_json} style="posterGeneric" images={preview.images} actions={preview.actions} width={230} />
                  </div>
                  {fbStyle && (
                    <div>
                      <p className="mb-1.5 text-center text-[11px] font-semibold text-[#64748B]">iOS 26 et avant</p>
                      <PassPreview pj={preview.pass_json} style={fbStyle} images={preview.images} width={230} legacy />
                    </div>
                  )}
                </>
              ) : NEW_CODES.has((preview.pass_json.barcodes || [])[0]?.format) ? (
                <>
                  <div>
                    <p className="mb-1.5 text-center text-[11px] font-semibold text-[#64748B]">iOS 27</p>
                    <PassPreview pj={preview.pass_json} style={styles[0]} images={preview.images} width={230} />
                  </div>
                  <div>
                    <p className="mb-1.5 text-center text-[11px] font-semibold text-[#64748B]">iOS 26 et avant (code de secours)</p>
                    <PassPreview pj={preview.pass_json} style={styles[0]} images={preview.images} width={230} legacy />
                  </div>
                </>
              ) : (
                <div>
                  <p className="mb-1.5 text-center text-[11px] font-semibold text-[#64748B]">Tous les iPhone</p>
                  <PassPreview pj={preview.pass_json} style={styles[0]} images={preview.images} width={260} />
                </div>
              )}
            </div>
            <button type="button" onClick={() => setShowBack((b) => !b)}
                    className="mx-auto mt-3 flex items-center gap-1 text-[12px] font-semibold text-[#2F6BFF]">
              Au dos de la carte <ChevronDown size={14} className={showBack ? 'rotate-180' : ''} />
            </button>
            {showBack && <div className="mt-2"><PassBack pj={preview.pass_json} style={styles[0]} /></div>}
            <p className="mt-2 text-center text-[11px] text-[#94A3B8]">
              Exemple : {preview.sample?.name}, {preview.sample?.visits} visites — construit par le serveur, comme le vrai pass.
            </p>
            {clientPreview && (
              <div className="mt-5 border-t border-[#E6EEFB] pt-4">
                <p className="mb-2 text-center text-[11px] font-semibold text-[#64748B]">Page web du client (lien de la carte, Google Wallet)</p>
                <div className="mx-auto" style={{ width: 260 }}>{clientPreview}</div>
              </div>
            )}
          </>
        ) : (
          <div className="flex h-64 items-center justify-center text-[12.5px] text-[#94A3B8]">Chargement de l’aperçu…</div>
        )}
      </div>
      )}

      {crop && (
        <PosterCropper file={crop.file} outW={crop.w} outH={crop.h} guides={crop.base === 'background' && style === 'posterGeneric'}
                       title={crop.base === 'strip' ? 'Cadrer la bannière' : 'Cadrer l’image de fond'}
                       onDone={(url) => { crop.resolve(url); setCrop(null); }}
                       onCancel={() => { crop.resolve(null); setCrop(null); }} />
      )}
    </div>
  );
});

export default CardDesigner;
