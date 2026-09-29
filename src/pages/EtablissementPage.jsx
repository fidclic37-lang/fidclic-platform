import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Store, Save, UploadCloud, Pencil, MapPin, Plus, MoreVertical, X, Check, Loader2,
  Clock, Radar, Landmark, LocateFixed, Info, Trash2,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';

/* Paramètres › Établissement — built to the approved mockup (blocks 1–8),
   plus what lived nowhere else and the user asked to add: the opening hours,
   the proximity reminder's one radius, and the legal information.

   One « Enregistrer les modifications » saves the page. A point de vente is
   edited in its own window. What each role may change comes from the server
   (`can`): the owner everything, an administrateur the legal information and
   its points de vente, a manager nothing. */

const BLUE = '#2F6BFF';
const inputCls = 'h-11 w-full rounded-lg border border-[#DCE3EE] bg-white px-3.5 text-[14.5px] text-[#0B1C3F] outline-none transition placeholder:text-[#94A3B8] focus:border-[#2F6BFF] focus:ring-4 focus:ring-[#2F6BFF]/10 disabled:bg-[#F8FAFC] disabled:text-[#475569]';
const DAYS_FR = { monday: 'Lundi', tuesday: 'Mardi', wednesday: 'Mercredi', thursday: 'Jeudi', friday: 'Vendredi', saturday: 'Samedi', sunday: 'Dimanche' };
const DIALS = [['FR', '🇫🇷', '+33'], ['BE', '🇧🇪', '+32'], ['CH', '🇨🇭', '+41'], ['LU', '🇱🇺', '+352'], ['MC', '🇲🇨', '+377']];

const Block = ({ n, title, children, className = '', action }) => (
  <section className={`rounded-2xl border border-[#EDF1F7] bg-white p-5 shadow-[0_1px_2px_rgba(11,28,63,.03)] ${className}`}>
    <header className="mb-4 flex items-center gap-3">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[15px] font-bold text-white" style={{ background: BLUE }}>{n}</span>
      <h2 className="flex-1 text-[17px] font-bold text-[#0B1C3F]">{title}</h2>
      {action}
    </header>
    {children}
  </section>
);

const Label = ({ children, required, right }) => (
  <span className="mb-1.5 flex items-center justify-between text-[13.5px] text-[#1E293B]">
    <span>{children}{required && <span className="ml-0.5 text-[#E11D48]">*</span>}</span>
    {right && <span className="text-[12px] text-[#94A3B8]">{right}</span>}
  </span>
);

/* A phone number shown as the mockup: flag + dial code, then the number. */
function PhoneField({ value, onChange, disabled }) {
  const found = DIALS.find(([, , d]) => (value || '').startsWith(d)) || DIALS[0];
  const [dial, setDial] = useState(found[2]);
  const rest = (value || '').startsWith(dial) ? value.slice(dial.length).trim() : (value || '').replace(/^\+\d+\s*/, '');
  return (
    <div className="flex h-11 overflow-hidden rounded-lg border border-[#DCE3EE] bg-white focus-within:border-[#2F6BFF]">
      <label className="relative flex items-center gap-1 border-r border-[#EDF1F7] pl-3 pr-2">
        <span className="text-[18px] leading-none">{(DIALS.find(([, , d]) => d === dial) || DIALS[0])[1]}</span>
        <select value={dial} disabled={disabled} aria-label="Indicatif"
                onChange={(e) => { setDial(e.target.value); onChange(`${e.target.value} ${rest}`.trim()); }}
                className="absolute inset-0 cursor-pointer opacity-0">
          {DIALS.map(([k, flag, d]) => <option key={k} value={d}>{flag} {d}</option>)}
        </select>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#334155" strokeWidth="2.5"><path d="m6 9 6 6 6-6" /></svg>
      </label>
      <input className="min-w-0 flex-1 px-3 text-[14.5px] text-[#0B1C3F] outline-none disabled:bg-[#F8FAFC]" disabled={disabled}
             value={`${dial} ${rest}`.trim()} onChange={(e) => onChange(e.target.value)} placeholder={`${dial} 2 47 12 34 56`} />
    </div>
  );
}

/* A Leaflet map (the CDN copy index.html already loads). Draggable when
   `onMove` is given — that is how the owner places the pin. */
function PinMap({ lat, lng, onMove, height = 104, zoom = 15, label }) {
  const box = useRef(null);
  const map = useRef(null);
  const marker = useRef(null);
  useEffect(() => {
    const L = window.L;
    if (!L || !box.current || map.current) return undefined;
    const center = lat != null ? [lat, lng] : [46.6, 2.4];
    map.current = L.map(box.current, { zoomControl: !!onMove, attributionControl: false, scrollWheelZoom: !!onMove,
                                        dragging: !!onMove, doubleClickZoom: !!onMove })
      .setView(center, lat != null ? zoom : 5);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map.current);
    const icon = L.divIcon({ className: '', iconSize: [30, 40], iconAnchor: [15, 38],
      html: `<svg width="30" height="40" viewBox="0 0 24 32"><path d="M12 0C5.4 0 0 5.3 0 11.9 0 20.8 12 32 12 32s12-11.2 12-20.1C24 5.3 18.6 0 12 0z" fill="${BLUE}"/><circle cx="12" cy="12" r="4.6" fill="#fff"/></svg>` });
    marker.current = L.marker(center, { icon, draggable: !!onMove });
    if (lat != null || onMove) marker.current.addTo(map.current);
    if (label && lat != null) marker.current.bindTooltip(label, { permanent: true, direction: 'right', offset: [12, -22], className: 'etab-pin-label' });
    if (onMove) {
      marker.current.on('dragend', () => { const p = marker.current.getLatLng(); onMove(p.lat, p.lng); });
      map.current.on('click', (e) => { marker.current.setLatLng(e.latlng); if (!map.current.hasLayer(marker.current)) marker.current.addTo(map.current); onMove(e.latlng.lat, e.latlng.lng); });
    }
    setTimeout(() => map.current && map.current.invalidateSize(), 60);
    return () => { map.current && map.current.remove(); map.current = null; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!map.current || lat == null) return;
    marker.current.setLatLng([lat, lng]);
    if (!map.current.hasLayer(marker.current)) marker.current.addTo(map.current);
    map.current.setView([lat, lng], Math.max(map.current.getZoom(), onMove ? 16 : zoom));
  }, [lat, lng]); // eslint-disable-line react-hooks/exhaustive-deps
  // `isolate`: Leaflet's panes carry z-indexes up to 1000 — kept inside the
  // map so a window opened above the page is never drawn under it.
  return <div ref={box} style={{ height, isolation: 'isolate' }} className="relative z-0 w-full overflow-hidden rounded-lg bg-[#EAF1FB]" />;
}

/* Place the pin: from the address first, then by dragging. */
function PinModal({ title, address, lat, lng, onClose, onDone }) {
  const [pos, setPos] = useState(lat != null ? { lat, lng } : null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const fromAddress = async () => {
    setBusy(true); setErr('');
    try { const { data } = await ownerAPI.geocodeEtablissement(address); setPos({ lat: data.lat, lng: data.lng }); }
    catch (e) { setErr(e?.response?.data?.detail || 'Adresse introuvable — placez le point sur la carte.'); }
    finally { setBusy(false); }
  };
  useEffect(() => { if (!pos) fromAddress(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Modal title={title} onClose={onClose} wide>
      <p className="mb-3 text-[13px] text-[#64748B]">Déplacez le repère (ou cliquez sur la carte) pour le placer exactement sur votre porte. Le rappel de proximité part de ce point.</p>
      <PinMap lat={pos?.lat} lng={pos?.lng} height={360} onMove={(la, lo) => setPos({ lat: la, lng: lo })} />
      {err && <p className="mt-2 text-[12.5px] text-[#B45309]">{err}</p>}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <button type="button" onClick={fromAddress} disabled={busy}
                className="inline-flex items-center gap-2 text-[13px] font-semibold text-[#2F6BFF] disabled:opacity-60">
          {busy ? <Loader2 size={15} className="animate-spin" /> : <LocateFixed size={15} />} Replacer d'après l'adresse
        </button>
        <div className="flex gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-[#DCE3EE] px-4 py-2.5 text-[13.5px] font-medium text-[#334155]">Annuler</button>
          <button type="button" disabled={!pos} onClick={() => onDone(pos.lat, pos.lng)}
                  className="inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>
            <Check size={15} /> Valider ce point
          </button>
        </div>
      </div>
    </Modal>
  );
}

function Modal({ title, onClose, children, wide }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#0B1C3F]/30 sm:items-center sm:p-6" onClick={onClose}>
      <div className={`max-h-[92vh] w-full ${wide ? 'max-w-2xl' : 'max-w-lg'} overflow-y-auto rounded-t-2xl bg-white p-5 shadow-2xl sm:rounded-2xl`}
           onClick={(e) => e.stopPropagation()}>
        <header className="mb-4 flex items-center justify-between">
          <h3 className="text-[16px] font-bold text-[#0B1C3F]">{title}</h3>
          <button type="button" onClick={onClose} aria-label="Fermer" className="text-[#94A3B8] hover:text-[#0B1C3F]"><X size={18} /></button>
        </header>
        {children}
      </div>
    </div>
  );
}

/* Add or edit a point de vente. */
function StoreModal({ store, onClose, onSaved }) {
  const creating = !store?.id;
  const [f, setF] = useState({ name: store?.name || '', street: store?.street || '', postal_code: store?.postal_code || '',
                                city: store?.city || '', phone: store?.phone || '', lat: store?.lat ?? null, lng: store?.lng ?? null });
  const [pin, setPin] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const save = async () => {
    setBusy(true); setErr('');
    try {
      const body = { ...f };
      if (!creating && store.is_main && store.id === 'main') delete body.name;
      const { data } = creating ? await ownerAPI.addStore(body) : await ownerAPI.editStore(store.id, body);
      onSaved(data, creating ? 'Point de vente ajouté.' : 'Point de vente enregistré.');
    } catch (e) { setErr(e?.response?.data?.detail || "L'enregistrement n'a pas abouti."); }
    finally { setBusy(false); }
  };
  return (
    <Modal title={creating ? 'Ajouter un point de vente' : store.name} onClose={onClose}>
      <div className="space-y-3.5">
        <label className="block"><Label required>Nom</Label>
          <input className={inputCls} value={f.name} maxLength={80} disabled={!creating && store.id === 'main'}
                 onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Le Corner Café Blois" /></label>
        <label className="block"><Label required>Adresse</Label>
          <input className={inputCls} value={f.street} onChange={(e) => setF({ ...f, street: e.target.value })} /></label>
        <div className="grid grid-cols-[1fr_1.4fr] gap-3">
          <label className="block"><Label required>Code postal</Label>
            <input className={inputCls} value={f.postal_code} inputMode="numeric" maxLength={5} onChange={(e) => setF({ ...f, postal_code: e.target.value })} /></label>
          <label className="block"><Label required>Ville</Label>
            <input className={inputCls} value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })} /></label>
        </div>
        <label className="block"><Label>Téléphone</Label>
          <PhoneField value={f.phone} onChange={(v) => setF({ ...f, phone: v })} /></label>
        <div>
          <Label>Point GPS</Label>
          <div className="relative">
            <PinMap lat={f.lat} lng={f.lng} height={120} />
            <button type="button" onClick={() => setPin(true)}
                    className="absolute bottom-2 right-2 z-10 inline-flex items-center gap-1.5 rounded-lg border border-[#2F6BFF] bg-white px-3 py-1.5 text-[12.5px] font-semibold text-[#2F6BFF]">
              <MapPin size={14} /> {f.lat != null ? 'Modifier sur la carte' : 'Placer sur la carte'}
            </button>
          </div>
        </div>
        {err && <p className="text-[12.5px] text-[#C0392B]">{err}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="rounded-lg border border-[#DCE3EE] px-4 py-2.5 text-[13.5px] font-medium text-[#334155]">Annuler</button>
          <button type="button" onClick={save} disabled={busy || (creating && !f.name.trim())}
                  className="inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-[13.5px] font-semibold text-white disabled:opacity-50" style={{ background: BLUE }}>
            {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} Enregistrer
          </button>
        </div>
      </div>
      {pin && (
        <PinModal title="Point GPS du point de vente" address={{ street: f.street, postal_code: f.postal_code, city: f.city }}
                  lat={f.lat} lng={f.lng} onClose={() => setPin(false)}
                  onDone={(la, lo) => { setF({ ...f, lat: la, lng: lo }); setPin(false); }} />
      )}
    </Modal>
  );
}

const readImage = (file, max = 512) => new Promise((resolve, reject) => {
  if (file.size > 2 * 1024 * 1024) { reject(new Error('Le logo dépasse 2 Mo.')); return; }
  const img = new Image();
  const url = URL.createObjectURL(file);
  img.onload = () => {
    const k = Math.min(1, max / Math.max(img.width, img.height));
    const c = document.createElement('canvas');
    c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
    c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
    URL.revokeObjectURL(url);
    resolve(c.toDataURL(file.type === 'image/jpeg' ? 'image/jpeg' : 'image/png', 0.9));
  };
  img.onerror = () => reject(new Error('Image illisible.'));
  img.src = url;
});

export default function EtablissementPage() {
  const [d, setD] = useState(null);
  const [biz, setBiz] = useState(null);
  const [addr, setAddr] = useState(null);
  const [legal, setLegal] = useState(null);
  const [geo, setGeo] = useState(null);
  const [hours, setHours] = useState(null);
  const [annual, setAnnual] = useState([]);
  const [holidays, setHolidays] = useState([]);
  const [dirtyHours, setDirtyHours] = useState({ weekly: false, annual: false, holidays: false });
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState('');
  const [err, setErr] = useState('');
  const [pin, setPin] = useState(false);
  const [store, setStore] = useState(null);
  const [menu, setMenu] = useState(null);
  const file = useRef(null);

  const apply = useCallback((data) => {
    setD(data); setBiz(data.business); setAddr(data.address); setLegal(data.legal); setGeo(data.geo);
  }, []);
  useEffect(() => {
    ownerAPI.etablissement().then(({ data }) => apply(data)).catch((e) => setErr(e?.response?.data?.detail || "Impossible de charger l'établissement."));
    ownerAPI.businessHours().then(({ data }) => {
      setHours(data.weekly_schedule || []); setAnnual(data.annual_closures || []); setHolidays(data.upcoming_holidays || []);
    }).catch(() => setHours([]));
  }, [apply]);
  const say = (m) => { setToast(m); setTimeout(() => setToast(''), 3500); };

  if (!d) {
    return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p>
      : <div className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</div>;
  }
  const can = d.can;
  const anyEdit = can.brand || can.legal || can.geo || can.hours;

  const save = async () => {
    setSaving(true); setErr('');
    try {
      const body = {};
      if (can.brand) {
        body.business = { name: biz.name, phone: biz.phone, email: biz.email, sector: biz.sector, description: biz.description,
                          ...(biz.logo_url !== d.business.logo_url ? { logo_url: biz.logo_url } : {}) };
        body.address = { street: addr.street, postal_code: addr.postal_code, city: addr.city,
                         ...(addr.lat != null ? { lat: addr.lat, lng: addr.lng, pin: addr.pin || 'adresse' } : {}) };
      }
      if (can.legal) body.legal = legal;
      if (can.geo) body.geo = { enabled: geo.enabled, radius_m: geo.radius_m, cooldown_days: geo.cooldown_days };
      const { data } = await ownerAPI.saveEtablissement(body);
      if (can.hours) {
        if (dirtyHours.weekly) await ownerAPI.saveWeeklyHours(hours);
        if (dirtyHours.annual) await ownerAPI.saveAnnualClosures(annual.filter((a) => a.start && a.end));
        if (dirtyHours.holidays) await ownerAPI.saveHolidayClosures(Object.fromEntries(holidays.map((h) => [h.date, !!h.closed])));
        setDirtyHours({ weekly: false, annual: false, holidays: false });
      }
      apply(data);
      say('Modifications enregistrées.');
    } catch (e) { setErr(e?.response?.data?.detail || "L'enregistrement n'a pas abouti."); }
    finally { setSaving(false); }
  };

  const pickLogo = async (e) => {
    const f = e.target.files?.[0]; e.target.value = '';
    if (!f) return;
    try { setBiz({ ...biz, logo_url: await readImage(f) }); } catch (x) { setErr(x.message); }
  };
  const setDay = (i, patch) => { setHours(hours.map((h, j) => (j === i ? { ...h, ...patch } : h))); setDirtyHours({ ...dirtyHours, weekly: true }); };
  const shopLabel = addr.city || biz.name;

  return (
    <div className="etab" onClick={() => setMenu(null)}>
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <span className="mt-0.5 flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><Store size={24} /></span>
          <div>
            <h1 className="text-[28px] font-bold leading-tight tracking-[-0.01em] text-[#0B1C3F]">Établissement</h1>
            <p className="mt-0.5 text-[15px] text-[#475569]">Gérez les informations de votre commerce. Ces informations seront visibles par vos clients.</p>
          </div>
        </div>
        {anyEdit && (
          <button type="button" onClick={save} disabled={saving}
                  className="inline-flex h-11 items-center gap-2.5 rounded-xl px-5 text-[15px] font-medium text-white shadow-[0_10px_24px_-14px_rgba(47,107,255,.9)] disabled:opacity-60"
                  style={{ background: BLUE }}>
            {saving ? <Loader2 size={18} className="animate-spin" /> : <Save size={18} />} Enregistrer les modifications
          </button>
        )}
      </header>
      {!can.brand && (
        <p className="mb-4 flex items-start gap-2 rounded-xl border border-[#E6EEFB] bg-white px-4 py-3 text-[13px] text-[#475569]">
          <Info size={15} className="mt-0.5 shrink-0 text-[#2F6BFF]" />
          {can.legal ? 'Vous pouvez modifier les informations légales et vos points de vente. Le reste est géré par le propriétaire.'
            : 'Ces informations sont gérées par le propriétaire et les administrateurs.'}
        </p>
      )}
      {err && <p className="mb-4 rounded-xl bg-[#FEF2F2] px-4 py-2.5 text-[13px] text-[#B91C1C]">{err}</p>}

      <fieldset disabled={!can.brand} className="m-0 min-w-0 border-0 p-0">
      <div className="grid gap-5 lg:grid-cols-[1.08fr_1fr]">
        {/* 1 */}
        <Block n={1} title="Nom du commerce">
          <label className="block"><Label required right={`${(biz.name || '').length}/100`}>Nom du commerce</Label>
            <input className={inputCls} value={biz.name} maxLength={100} onChange={(e) => setBiz({ ...biz, name: e.target.value })} /></label>
        </Block>

        {/* 2 */}
        <Block n={2} title="Logo">
          <div className="flex gap-4">
            <div className="relative h-[118px] w-[148px] shrink-0 overflow-hidden rounded-xl bg-[#0B0F17]">
              {biz.logo_url ? <img src={biz.logo_url} alt="Logo" className="h-full w-full object-contain"
                                   onError={(e) => { e.currentTarget.style.visibility = 'hidden'; }} />
                : <span className="flex h-full items-center justify-center text-[12px] text-white/60">Aucun logo</span>}
              {can.brand && (
                <button type="button" onClick={() => file.current?.click()} aria-label="Changer le logo"
                        className="absolute bottom-2 right-2 flex h-7 w-7 items-center justify-center rounded-full bg-white text-[#2F6BFF] shadow"><Pencil size={13} /></button>
              )}
            </div>
            <button type="button" onClick={() => file.current?.click()}
                    className="flex flex-1 flex-col items-center justify-center rounded-xl border border-dashed border-[#C9D6EA] bg-[#F8FAFF] px-3 py-3 text-center hover:border-[#2F6BFF]">
              <UploadCloud size={26} className="text-[#2F6BFF]" />
              <span className="mt-1 text-[14.5px] font-semibold text-[#2F6BFF]">Changer le logo</span>
              <span className="text-[11.5px] text-[#64748B]">PNG, JPG (max 2 Mo)</span>
              <span className="text-[11.5px] text-[#64748B]">Recommandé : 512 × 512 px</span>
            </button>
            <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={pickLogo} />
          </div>
          <p className="mt-2 text-[11.5px] text-[#94A3B8]">Le même logo apparaît sur la carte de fidélité de vos clients.</p>
        </Block>

        {/* 3 */}
        <Block n={3} title="Adresse">
          <div className="space-y-3">
            <label className="block"><Label required>Adresse</Label>
              <input className={inputCls} value={addr.street} onChange={(e) => setAddr({ ...addr, street: e.target.value })} /></label>
            <div className="grid grid-cols-[1fr_1.1fr] gap-3">
              <label className="block"><Label required>Code postal</Label>
                <input className={inputCls} value={addr.postal_code} inputMode="numeric" maxLength={5}
                       onChange={(e) => setAddr({ ...addr, postal_code: e.target.value })} /></label>
              <label className="block"><Label required>Ville</Label>
                <input className={inputCls} value={addr.city} onChange={(e) => setAddr({ ...addr, city: e.target.value })} /></label>
            </div>
            <div className="relative">
              <PinMap lat={addr.lat} lng={addr.lng} height={120} label={shopLabel} />
              {can.brand && (
                <button type="button" onClick={(e) => { e.stopPropagation(); setPin(true); }}
                        className="absolute bottom-2.5 right-2.5 z-10 inline-flex items-center gap-2 rounded-xl border border-[#2F6BFF] bg-white px-4 py-2 text-[14px] font-semibold text-[#2F6BFF] shadow-sm">
                  <MapPin size={16} fill={BLUE} className="text-white" /> {addr.lat != null ? 'Modifier sur la carte' : 'Placer sur la carte'}
                </button>
              )}
            </div>
            <p className="text-[11.5px] text-[#94A3B8]">
              {addr.lat == null ? 'Aucun point GPS : placez-le pour activer le rappel de proximité.'
                : addr.pin === 'manuel' ? 'Point GPS placé à la main.' : "Point GPS placé d'après l'adresse."}
            </p>
          </div>
        </Block>

        {/* 4 + 5 */}
        <div className="grid gap-5">
          <Block n={4} title="Téléphone">
            <Label required>Téléphone</Label>
            <PhoneField value={biz.phone} disabled={!can.brand} onChange={(v) => setBiz({ ...biz, phone: v })} />
          </Block>
          <Block n={5} title="Email">
            <label className="block"><Label required>Email</Label>
              <input type="email" className={inputCls} value={biz.email} onChange={(e) => setBiz({ ...biz, email: e.target.value })}
                     placeholder="contact@moncommerce.fr" /></label>
          </Block>
        </div>

        {/* 6 */}
        <Block n={6} title="Secteur d'activité">
          <label className="block"><Label required>Secteur d'activité</Label>
            <div className="relative">
              <select className={`${inputCls} appearance-none pr-9`} value={biz.sector} onChange={(e) => setBiz({ ...biz, sector: e.target.value })}>
                <option value="" disabled>Choisir…</option>
                {d.sectors.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
              <svg className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#0B1C3F" strokeWidth="2.5"><path d="m6 9 6 6 6-6" /></svg>
            </div>
          </label>
        </Block>

        {/* 7 */}
        <Block n={7} title="Informations générales">
          <Label required>Description du commerce</Label>
          <textarea className={`${inputCls} h-auto min-h-[90px] resize-y py-2.5 leading-snug`} maxLength={500} value={biz.description}
                    onChange={(e) => setBiz({ ...biz, description: e.target.value })} placeholder="Ce qui rend votre commerce unique…" />
          <p className="mt-1 text-right text-[12px] text-[#94A3B8]">{(biz.description || '').length}/500</p>
        </Block>
      </div>
      </fieldset>

      {/* 8 */}
      <Block n={8} title="Établissements / points de vente" className="mt-5"
             action={can.brand && (
               <button type="button" onClick={() => setStore({})} disabled={!can.add_store}
                       title={can.add_store ? '' : 'Votre formule ne permet pas plusieurs points de vente.'}
                       className="inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-[13.5px] font-medium text-white disabled:opacity-50" style={{ background: BLUE }}>
                 <Plus size={16} /> Ajouter un point de vente
               </button>
             )}>
        <div className="space-y-2.5">
          {d.stores.map((s) => (
            <div key={s.id} className={`flex items-center gap-4 rounded-xl border border-[#EDF1F7] p-2.5 ${s.status === 'closed' ? 'opacity-60' : ''}`}>
              <span className="flex h-[58px] w-[58px] shrink-0 items-center justify-center overflow-hidden rounded-lg bg-[#0B0F17]">
                {biz.logo_url ? <img src={biz.logo_url} alt="" className="h-full w-full object-contain"
                                     onError={(e) => { e.currentTarget.style.visibility = 'hidden'; }} /> : <Store size={20} className="text-white/70" />}
              </span>
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2 text-[15px] font-bold text-[#0B1C3F]">
                  {s.name}
                  {s.is_main && <span className="rounded-md bg-[#EAF1FF] px-2 py-0.5 text-[12px] font-medium text-[#2F6BFF]">Principal</span>}
                  {s.status === 'closed' && <span className="rounded-md bg-[#F1F5F9] px-2 py-0.5 text-[12px] font-medium text-[#64748B]">Fermé</span>}
                </p>
                <p className="truncate text-[13.5px] text-[#64748B]">{[s.street, [s.postal_code, s.city].filter(Boolean).join(' ')].filter(Boolean).join(', ') || 'Adresse à compléter'}</p>
                <p className="text-[13.5px] text-[#64748B]">{s.phone}</p>
              </div>
              {s.editable && (
                <span className="relative" onClick={(e) => e.stopPropagation()}>
                  <button type="button" aria-label={`Actions — ${s.name}`} onClick={() => setMenu(menu === s.id ? null : s.id)}
                          className="rounded-lg p-2 text-[#0B1C3F] hover:bg-[#F4F7FC]"><MoreVertical size={18} /></button>
                  {menu === s.id && (
                    <span className="absolute right-0 top-full z-20 mt-1 flex w-52 flex-col overflow-hidden rounded-xl border border-[#E6EEFB] bg-white py-1 shadow-[0_24px_60px_-28px_rgba(11,28,63,.5)]">
                      <button type="button" onClick={() => { setMenu(null); setStore(s); }} className="flex items-center gap-2 px-3.5 py-2 text-left text-[13px] text-[#334155] hover:bg-[#F4F7FC]"><Pencil size={14} /> Modifier</button>
                      {can.brand && !s.is_main && (
                        <button type="button" onClick={async () => {
                          setMenu(null);
                          try { const { data } = await ownerAPI.editStore(s.id, { status: s.status === 'closed' ? 'open' : 'closed' }); apply(data); say(s.status === 'closed' ? 'Point de vente rouvert.' : 'Point de vente fermé — ses données sont conservées.'); }
                          catch (e) { setErr(e?.response?.data?.detail || 'Action impossible.'); }
                        }} className={`flex items-center gap-2 px-3.5 py-2 text-left text-[13px] hover:bg-[#F4F7FC] ${s.status === 'closed' ? 'text-[#334155]' : 'text-[#C0392B]'}`}>
                          {s.status === 'closed' ? <><Check size={14} /> Rouvrir</> : <><Trash2 size={14} /> Fermer ce point de vente</>}
                        </button>
                      )}
                    </span>
                  )}
                </span>
              )}
            </div>
          ))}
        </div>
      </Block>

      {/* additions: 9 hours · 10 proximity · 11 legal */}
      <div className="mt-5 grid gap-5 lg:grid-cols-[1.08fr_1fr]">
        <Block n={9} title="Horaires d'ouverture" action={<Clock size={18} className="text-[#94A3B8]" />}>
          {!hours ? <p className="text-[13px] text-[#64748B]"><Loader2 size={14} className="mr-1 inline animate-spin" /> Chargement…</p> : (
            <fieldset disabled={!can.hours} className="m-0 min-w-0 border-0 p-0">
              <div className="divide-y divide-[#F1F5F9]">
                {hours.map((h, i) => (
                  <div key={h.day} className="flex flex-wrap items-center gap-3 py-2">
                    <span className="w-24 text-[14px] font-medium text-[#0B1C3F]">{DAYS_FR[h.day] || h.day}</span>
                    <label className="flex items-center gap-2 text-[13px] text-[#475569]">
                      <input type="checkbox" checked={!h.closed} onChange={(e) => setDay(i, { closed: !e.target.checked })} className="h-4 w-4 accent-[#2F6BFF]" />
                      {h.closed ? 'Fermé' : 'Ouvert'}
                    </label>
                    {!h.closed && (
                      <span className="ml-auto flex items-center gap-2 text-[13px] text-[#64748B]">
                        <input type="time" value={h.open_from || ''} onChange={(e) => setDay(i, { open_from: e.target.value })} className="h-9 rounded-lg border border-[#DCE3EE] px-2 text-[13.5px] text-[#0B1C3F]" />
                        à
                        <input type="time" value={h.open_to || ''} onChange={(e) => setDay(i, { open_to: e.target.value })} className="h-9 rounded-lg border border-[#DCE3EE] px-2 text-[13.5px] text-[#0B1C3F]" />
                      </span>
                    )}
                  </div>
                ))}
              </div>
              <div className="mt-4">
                <p className="mb-2 text-[13.5px] font-semibold text-[#0B1C3F]">Jours fériés fermés</p>
                <div className="flex flex-wrap gap-1.5">
                  {holidays.slice(0, 11).map((h, i) => (
                    <button key={h.date} type="button"
                            onClick={() => { setHolidays(holidays.map((x, j) => (j === i ? { ...x, closed: !x.closed } : x))); setDirtyHours({ ...dirtyHours, holidays: true }); }}
                            className={`rounded-lg border px-2.5 py-1 text-[12px] transition ${h.closed ? 'border-[#2F6BFF] bg-[#EAF1FF] text-[#2F6BFF]' : 'border-[#E6EEFB] text-[#475569]'}`}>
                      {h.name} · {new Date(`${h.date}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })}
                    </button>
                  ))}
                </div>
              </div>
              <div className="mt-4">
                <p className="mb-2 flex items-center justify-between text-[13.5px] font-semibold text-[#0B1C3F]">
                  Fermetures annuelles
                  {can.hours && (
                    <button type="button" onClick={() => { setAnnual([...annual, { start: '', end: '', label: '' }]); setDirtyHours({ ...dirtyHours, annual: true }); }}
                            className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-[#2F6BFF]"><Plus size={14} /> Ajouter</button>
                  )}
                </p>
                {annual.length === 0 && <p className="text-[12.5px] text-[#94A3B8]">Aucune fermeture prévue.</p>}
                {annual.map((a, i) => (
                  <div key={i} className="mb-2 flex flex-wrap items-center gap-2">
                    <input className="h-9 min-w-0 flex-1 rounded-lg border border-[#DCE3EE] px-2.5 text-[13px]" placeholder="Vacances d'août" value={a.label || ''}
                           onChange={(e) => { setAnnual(annual.map((x, j) => (j === i ? { ...x, label: e.target.value } : x))); setDirtyHours({ ...dirtyHours, annual: true }); }} />
                    <input type="date" className="h-9 rounded-lg border border-[#DCE3EE] px-2 text-[13px]" value={a.start || ''}
                           onChange={(e) => { setAnnual(annual.map((x, j) => (j === i ? { ...x, start: e.target.value } : x))); setDirtyHours({ ...dirtyHours, annual: true }); }} />
                    <input type="date" className="h-9 rounded-lg border border-[#DCE3EE] px-2 text-[13px]" value={a.end || ''}
                           onChange={(e) => { setAnnual(annual.map((x, j) => (j === i ? { ...x, end: e.target.value } : x))); setDirtyHours({ ...dirtyHours, annual: true }); }} />
                    {can.hours && (
                      <button type="button" aria-label="Retirer" onClick={() => { setAnnual(annual.filter((_, j) => j !== i)); setDirtyHours({ ...dirtyHours, annual: true }); }}
                              className="text-[#94A3B8] hover:text-[#C0392B]"><X size={16} /></button>
                    )}
                  </div>
                ))}
              </div>
            </fieldset>
          )}
        </Block>

        <div className="grid content-start gap-5">
          <Block n={10} title="Rappel de proximité" action={<Radar size={18} className="text-[#94A3B8]" />}>
            <fieldset disabled={!can.geo} className="m-0 min-w-0 space-y-3.5 border-0 p-0">
              <label className="flex items-center justify-between gap-3">
                <span className="text-[13.5px] text-[#1E293B]">Prévenir un client qui passe près de votre commerce</span>
                <input type="checkbox" checked={geo.enabled} onChange={(e) => setGeo({ ...geo, enabled: e.target.checked })} className="h-5 w-5 accent-[#2F6BFF]" />
              </label>
              <div className={geo.enabled ? '' : 'opacity-50'}>
                <Label right={`${geo.radius_m} m`}>Rayon</Label>
                <input type="range" min={50} max={2000} step={50} value={geo.radius_m} onChange={(e) => setGeo({ ...geo, radius_m: Number(e.target.value) })}
                       className="w-full accent-[#2F6BFF]" />
                <div className="flex justify-between text-[11.5px] text-[#94A3B8]"><span>50 m</span><span>2 km</span></div>
              </div>
              <label className={`block ${geo.enabled ? '' : 'opacity-50'}`}>
                <Label>Délai avant un nouveau rappel (même client)</Label>
                <select className={inputCls} value={geo.cooldown_days} onChange={(e) => setGeo({ ...geo, cooldown_days: Number(e.target.value) })}>
                  {[1, 2, 3, 7, 14, 30].map((n) => <option key={n} value={n}>{n} jour{n > 1 ? 's' : ''}</option>)}
                </select>
              </label>
              <p className="text-[11.5px] leading-snug text-[#94A3B8]">Un seul rayon pour tout : la carte web et le pass Apple Wallet l'utilisent, autour de chaque point de vente placé sur la carte.</p>
            </fieldset>
          </Block>

          <Block n={11} title="Informations légales" action={<Landmark size={18} className="text-[#94A3B8]" />}>
            <fieldset disabled={!can.legal} className="m-0 min-w-0 space-y-3 border-0 p-0">
              <label className="block"><Label>Raison sociale</Label>
                <input className={inputCls} value={legal.legal_name} onChange={(e) => setLegal({ ...legal, legal_name: e.target.value })} /></label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block"><Label right="14 chiffres">SIRET</Label>
                  <input className={inputCls} value={legal.siret} inputMode="numeric" onChange={(e) => setLegal({ ...legal, siret: e.target.value })} /></label>
                <label className="block"><Label>N° de TVA</Label>
                  <input className={inputCls} value={legal.vat_number} placeholder="FR12345678901" onChange={(e) => setLegal({ ...legal, vat_number: e.target.value })} /></label>
              </div>
              <p className="text-[11.5px] text-[#94A3B8]">Utilisées pour vos factures. Non visibles par vos clients.</p>
            </fieldset>
          </Block>
        </div>
      </div>

      <div aria-live="polite" className="pointer-events-none fixed bottom-5 left-1/2 z-40 -translate-x-1/2 transition-opacity" style={{ opacity: toast ? 1 : 0 }}>
        <span className="inline-flex items-center gap-2 rounded-full bg-[#0B1C3F] px-4 py-2 text-[13px] font-medium text-white shadow-lg"><Check size={14} /> {toast}</span>
      </div>

      {pin && (
        <PinModal title="Point GPS de votre commerce" address={{ street: addr.street, postal_code: addr.postal_code, city: addr.city }}
                  lat={addr.lat} lng={addr.lng} onClose={() => setPin(false)}
                  onDone={(la, lo) => { setAddr({ ...addr, lat: la, lng: lo, pin: 'manuel' }); setPin(false); say('Point placé — pensez à enregistrer.'); }} />
      )}
      {store && (
        <StoreModal store={store.id ? store : null} onClose={() => setStore(null)}
                    onSaved={(data, m) => { apply(data); setStore(null); say(m); }} />
      )}
    </div>
  );
}
