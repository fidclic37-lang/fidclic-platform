import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  MapPin, Download, Car, Bike, Footprints, Map as MapIcon, List as ListIcon,
  Calendar, ChevronDown, Users, Loader2, Percent, Target, BarChart3, Info,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import GeoCatchmentMap from '../components/GeoCatchmentMap';

/**
 * Géolocalisation clients — built to the approved mockups.
 *
 * Two readings of the same client base, switched independently:
 *   • Zone de chalandise — d'où viennent vos clients (distance rings)
 *   • Isochrones — qui peut venir en 5 / 15 / 25 / 35 min (travel-time bands)
 * Either alone, or both at once, which is the third layout: filled rings with
 * the time bands dashed over them, and a combined breakdown beside.
 *
 * Every figure is counted from this merchant's own clients. The two
 * approximations behind the map — a client's position and the travel time —
 * are stated under it rather than hidden; see api/features/geolocation.py.
 */
const TONE = {
  rose:   { bg: '#FFF1F3', fg: '#E11D48', dot: '#F43F5E', soft: '#FFE4E9' },
  amber:  { bg: '#FFF7ED', fg: '#C2410C', dot: '#F59E0B', soft: '#FFEDD5' },
  blue:   { bg: '#EFF6FF', fg: '#1D4ED8', dot: '#3B82F6', soft: '#DBEAFE' },
  violet: { bg: '#F5F3FF', fg: '#6D28D9', dot: '#8B5CF6', soft: '#EDE9FE' },
};
const MODE_ICONS = { car: Car, bike: Bike, walk: Footprints };

const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const prettyDay = (iso) => { const d = new Date(iso); return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`; };
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');

/* ── shell pieces ─────────────────────────────────────────────────────── */
const Panel = ({ title, action, children, className = '' }) => (
  <section className={`rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] ${className}`}>
    <header className="mb-4 flex items-center justify-between gap-3">
      <h2 className="flex items-center gap-2 text-[14px] font-bold text-[#0B1C3F]">
        <span className="flex h-5 w-5 items-center justify-center rounded-md bg-[#EAF1FF] text-[#2F6BFF]">
          <MapPin size={12} />
        </span>
        {title}
      </h2>
      {action}
    </header>
    {children}
  </section>
);

const SeeMore = ({ onClick, label = 'Voir plus' }) => (
  <button type="button" onClick={onClick}
          className="shrink-0 text-[12px] font-semibold text-[#2F6BFF] transition hover:underline">
    {label}
  </button>
);

const ToggleCard = ({ icon: Icon, title, subtitle, on, onChange, tone = 'blue' }) => (
  <button
    type="button" onClick={() => onChange(!on)} aria-pressed={on}
    className={`flex w-full items-center gap-3.5 rounded-2xl border p-4 text-left transition ${
      on ? 'border-[#C7DBFF] bg-[#F5F8FF] shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]'
         : 'border-[#E6EEFB] bg-white'}`}
  >
    <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${
      on ? '' : 'opacity-45'}`}
          style={{ background: on ? (tone === 'violet' ? '#EDE9FE' : '#DCE8FF') : '#EEF2F8',
                   color: on ? (tone === 'violet' ? '#6D28D9' : '#2F6BFF') : '#94A3B8' }}>
      <Icon size={21} />
    </span>
    <span className="min-w-0 flex-1">
      <span className={`block text-[14.5px] font-bold ${on ? 'text-[#0B1C3F]' : 'text-[#94A3B8]'}`}>{title}</span>
      <span className={`block text-[12.5px] ${on ? 'text-[#64748B]' : 'text-[#A9B6CA]'}`}>{subtitle}</span>
    </span>
    <span className={`relative h-6 w-11 shrink-0 rounded-full transition ${on ? '' : 'bg-[#DFE6F1]'}`}
          style={on ? { background: tone === 'violet' ? '#7C5CFF' : '#2F6BFF' } : undefined}>
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${on ? 'left-[22px]' : 'left-0.5'}`} />
    </span>
  </button>
);

const Segmented = ({ options, value, onChange }) => (
  <div className="flex overflow-hidden rounded-xl border border-[#E6EEFB] bg-white">
    {options.map((o) => {
      const Icon = o.icon;
      const on = value === o.key;
      return (
        <button
          key={o.key} type="button" onClick={() => onChange(o.key)}
          className={`flex flex-1 items-center justify-center gap-2 px-3 py-2.5 text-[13px] font-semibold transition ${
            on ? 'bg-[#2F6BFF] text-white' : 'text-[#475569] hover:bg-[#F4F7FC]'}`}
        >
          {Icon && <Icon size={15} />} {o.label}
        </button>
      );
    })}
  </div>
);

const PeriodPicker = ({ from, to, onChange }) => {
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  useEffect(() => {
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, []);
  const preset = (days) => {
    const end = new Date(); const start = new Date();
    start.setDate(end.getDate() - (days - 1));
    onChange(ymd(start), ymd(end)); setOpen(false);
  };
  return (
    <div className="relative" ref={box}>
      <button type="button" onClick={() => setOpen((v) => !v)}
              className="flex w-full items-center gap-2 rounded-xl border border-[#E6EEFB] bg-white px-3 py-2.5 text-left text-[13px] text-[#0B1C3F] transition hover:border-[#2F6BFF]">
        <Calendar size={15} className="shrink-0 text-[#2F6BFF]" />
        <span className="min-w-0 flex-1 truncate">{prettyDay(from)} – {prettyDay(to)}</span>
        <ChevronDown size={15} className="shrink-0 text-[#94A3B8]" />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-[600] mt-2 w-[300px] rounded-xl border border-[#E6EEFB] bg-white p-3 shadow-[0_24px_60px_-28px_rgba(11,28,63,.5)]">
          <div className="flex flex-wrap gap-1.5">
            {[['7 jours', 7], ['30 jours', 30], ['90 jours', 90], ['12 mois', 365]].map(([l, d]) => (
              <button key={d} type="button" onClick={() => preset(d)}
                      className="rounded-lg border border-[#E6EEFB] px-2.5 py-1 text-[12px] font-medium text-[#334155] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
                {l}
              </button>
            ))}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <label className="block">
              <span className="mb-1 block text-[11px] font-semibold text-[#64748B]">Du</span>
              <input type="date" value={from} max={to} onChange={(e) => onChange(e.target.value, to)}
                     className="w-full rounded-lg border border-[#E6EEFB] px-2 py-1.5 text-[12.5px] outline-none focus:border-[#2F6BFF]" />
            </label>
            <label className="block">
              <span className="mb-1 block text-[11px] font-semibold text-[#64748B]">Au</span>
              <input type="date" value={to} min={from} onChange={(e) => onChange(from, e.target.value)}
                     className="w-full rounded-lg border border-[#E6EEFB] px-2 py-1.5 text-[12.5px] outline-none focus:border-[#2F6BFF]" />
            </label>
          </div>
        </div>
      )}
    </div>
  );
};

/* ── data pieces ──────────────────────────────────────────────────────── */
const CountCard = ({ tone, heading, sub, clients }) => {
  const t = TONE[tone] || TONE.blue;
  return (
    <div className="rounded-xl p-3.5" style={{ background: t.bg }}>
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-white"
              style={{ color: t.fg }}>
          <Car size={14} />
        </span>
        <span className="min-w-0">
          <span className="block text-[12.5px] font-bold leading-tight" style={{ color: t.fg }}>{heading}</span>
          {sub && <span className="block text-[11px] leading-tight" style={{ color: t.fg, opacity: 0.8 }}>{sub}</span>}
        </span>
      </div>
      <p className="flex items-center gap-1.5">
        <Users size={15} style={{ color: t.dot }} />
        <span className="text-[21px] font-bold leading-none tabular-nums" style={{ color: t.fg }}>{nf(clients)}</span>
      </p>
      <p className="mt-0.5 text-[11px]" style={{ color: t.fg, opacity: 0.75 }}>clients</p>
    </div>
  );
};

/** Donut, drawn as plain SVG — one ring, one number in the middle. */
const Donut = ({ slices, total, caption }) => {
  const R = 54, C = 2 * Math.PI * R;
  let offset = 0;
  const drawn = slices.filter((s) => s.value > 0);
  return (
    <div className="flex items-center gap-5">
      <div className="relative shrink-0">
        <svg width="140" height="140" viewBox="0 0 140 140" role="img" aria-label={caption}>
          <circle cx="70" cy="70" r={R} fill="none" stroke="#EEF3FB" strokeWidth="22" />
          {drawn.map((s) => {
            const len = total ? (s.value / total) * C : 0;
            const el = (
              <circle key={s.key} cx="70" cy="70" r={R} fill="none"
                      stroke={TONE[s.tone]?.dot || '#3B82F6'} strokeWidth="22"
                      strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-offset}
                      transform="rotate(-90 70 70)" />
            );
            offset += len;
            return el;
          })}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-[19px] font-bold leading-none text-[#0B1C3F] tabular-nums">{nf(total)}</span>
          <span className="text-[10.5px] leading-tight text-[#64748B]">clients</span>
          <span className="text-[10.5px] leading-tight text-[#64748B]">au total</span>
        </div>
      </div>
      <ul className="min-w-0 flex-1 space-y-2">
        {slices.map((s) => (
          <li key={s.key} className="flex items-center gap-2 text-[12.5px]">
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: TONE[s.tone]?.dot }} />
            <span className="min-w-0 flex-1 truncate text-[#334155]">{s.label}</span>
            <span className="shrink-0 font-bold text-[#0B1C3F] tabular-nums">
              {total ? Math.round((s.value / total) * 100) : 0} %
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
};

/** The combined view's two-circle diagram — sized and labelled from real counts. */
const Venn = ({ left, right, both }) => (
  <div className="flex items-center justify-center py-1">
    <div className="relative flex items-center" style={{ height: 150 }}>
      <div className="flex h-[132px] w-[132px] flex-col items-center justify-center rounded-full text-center"
           style={{ background: 'rgba(244,63,94,.18)', border: '1px solid rgba(244,63,94,.35)' }}>
        <span className="px-3 text-[11px] font-semibold leading-tight text-[#9F1239]">Zone de chalandise</span>
        <span className="text-[17px] font-bold text-[#9F1239] tabular-nums">{nf(left)}</span>
        <span className="text-[10.5px] text-[#9F1239]">clients</span>
      </div>
      <div className="z-10 -mx-8 flex h-[92px] w-[92px] flex-col items-center justify-center rounded-full text-center"
           style={{ background: 'rgba(139,92,246,.5)' }}>
        <span className="text-[16px] font-bold leading-none text-white tabular-nums">{nf(both)}</span>
        <span className="text-[10px] leading-tight text-white">clients</span>
        <span className="text-[10px] leading-tight text-white">communs</span>
      </div>
      <div className="flex h-[132px] w-[132px] flex-col items-center justify-center rounded-full text-center"
           style={{ background: 'rgba(59,130,246,.18)', border: '1px solid rgba(59,130,246,.35)' }}>
        <span className="px-3 text-[11px] font-semibold leading-tight text-[#1D4ED8]">Isochrones</span>
        <span className="text-[17px] font-bold text-[#1D4ED8] tabular-nums">{nf(right)}</span>
        <span className="text-[10.5px] text-[#1D4ED8]">clients</span>
      </div>
    </div>
  </div>
);

const CommuneColumn = ({ tone, title, rows, offset = 0 }) => {
  const t = TONE[tone] || TONE.blue;
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-center gap-2 rounded-lg px-2.5 py-2" style={{ background: t.bg }}>
        <span className="flex h-5 w-5 items-center justify-center rounded-md bg-white" style={{ color: t.fg }}>
          <Car size={11} />
        </span>
        <span className="text-[12.5px] font-bold" style={{ color: t.fg }}>{title}</span>
      </div>
      {rows.length === 0 && <p className="px-2.5 py-3 text-[12px] text-[#94A3B8]">Aucune commune</p>}
      {rows.map((r, i) => (
        <div key={r.name} className="flex items-center gap-2 px-2.5 py-[7px]">
          <span className="flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white"
                style={{ background: t.dot }}>
            {offset + i + 1}
          </span>
          <span className="min-w-0 flex-1 truncate text-[12.5px] text-[#334155]" title={r.name}>{r.name}</span>
          <span className="shrink-0 text-[12.5px] font-semibold text-[#0B1C3F] tabular-nums">{nf(r.clients)}</span>
        </div>
      ))}
    </div>
  );
};

/* ── page ─────────────────────────────────────────────────────────────── */
const todayISO = ymd(new Date());
const startISO = (() => { const d = new Date(); d.setDate(d.getDate() - 20); return ymd(d); })();

export default function GeolocationPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [catchOn, setCatchOn] = useState(true);
  const [isoOn, setIsoOn] = useState(false);
  const [view, setView] = useState('map');
  const [from, setFrom] = useState(startISO);
  const [to, setTo] = useState(todayISO);
  const [mode, setMode] = useState('car');
  const [scope, setScope] = useState('local');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true); setError('');
    ownerAPI.geoCatchment({ from, to, mode, scope })
      .then(({ data: d }) => { if (alive) setData(d); })
      .catch((e) => { if (alive) setError(e?.response?.data?.detail || 'Impossible de charger la carte.'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [from, to, mode, scope]);

  // Both off leaves nothing to read, so switching one off switches the other on.
  const toggleCatch = (next) => { setCatchOn(next); if (!next && !isoOn) setIsoOn(true); };
  const toggleIso = (next) => { setIsoOn(next); if (!next && !catchOn) setCatchOn(true); };

  const zones = data?.catchment?.zones || [];
  const bands = data?.isochrones?.bands || [];
  const communes = data?.communes || { zones: {}, bands: {}, combined: [] };
  const both = catchOn && isoOn;

  const subtitle = both
    ? 'Visualisez les zones accessibles selon la zone de chalandise et le temps de trajet pour mieux cibler vos campagnes et identifier de nouvelles opportunités.'
    : catchOn
      ? "Visualisez les zones accessibles selon la zone de chalandise pour mieux cibler vos campagnes et identifier de nouvelles opportunités."
      : 'Visualisez les zones accessibles selon le temps de trajet pour mieux cibler vos campagnes et identifier de nouvelles opportunités.';

  const exportCsv = async () => {
    setExporting(true);
    try {
      const { data: blob } = await ownerAPI.geoExport({ from, to, mode, scope });
      const url = URL.createObjectURL(new Blob([blob], { type: 'text/csv;charset=utf-8' }));
      const a = document.createElement('a');
      a.href = url; a.download = `fidclic-geolocalisation-${from}-${to}.csv`;
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch {
      setError("L'export n'a pas abouti. Réessayez dans un instant.");
    } finally { setExporting(false); }
  };

  const precisionNote = useMemo(() => {
    const p = data?.precision || {};
    const total = Object.values(p).reduce((a, b) => a + b, 0);
    if (!total) return null;
    const exact = p.gps || 0;
    const coarse = p.department || 0;
    return { total, exact, coarse, pct: Math.round((exact / total) * 100) };
  }, [data]);

  const actions = [
    {
      icon: MapPin, tone: 'blue', title: 'Lancer une campagne géolocalisée',
      body: both
        ? `Ciblez les clients dans la zone 1 et à moins de ${bands[1]?.minutes ?? 15} min.`
        : catchOn
          ? `Ciblez les clients dans la zone 1 — ${nf(zones[0]?.clients)} clients.`
          : `Ciblez les clients à moins de ${bands[0]?.minutes ?? 5} min.`,
      cta: 'Créer', go: () => navigate('/dashboard/campaigns'),
    },
    {
      icon: Percent, tone: 'amber', title: 'Créer une offre spéciale',
      body: catchOn
        ? `Attirez de nouveaux clients dans la zone 2 — ${nf(zones[1]?.clients)} clients.`
        : `Attirez de nouveaux clients à moins de ${bands[1]?.minutes ?? 15} min.`,
      cta: 'Configurer', go: () => navigate('/dashboard/card'),
    },
    {
      icon: Target, tone: 'rose', title: 'Analyser les zones à fort potentiel',
      body: catchOn
        ? `Développez votre visibilité dans la zone 3 — ${nf(zones[2]?.clients)} clients.`
        : `Développez votre visibilité dans la zone ${bands[2]?.minutes ?? 25}–${bands[3]?.minutes ?? 35} min.`,
      cta: 'Analyser', go: () => navigate('/dashboard/analytics'),
    },
  ];

  return (
    <div className="geo">
      {/* header */}
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#2F6BFF] text-white">
            <MapPin size={22} />
          </span>
          <div className="max-w-3xl">
            <h1 className="text-[23px] font-bold leading-tight text-[#2F6BFF]">Géolocalisation clients</h1>
            <p className="text-[13px] leading-snug text-[#475569]">{subtitle}</p>
          </div>
        </div>
        <button type="button" onClick={exportCsv} disabled={exporting}
                className="inline-flex items-center gap-2 rounded-xl border border-[#E6EEFB] bg-white px-4 py-2.5 text-[13px] font-semibold text-[#0B1C3F] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF] disabled:opacity-60">
          {exporting ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />} Exporter la carte
        </button>
      </header>

      {/* the two readings + the view switch */}
      <div className="mb-4 grid gap-4 xl:grid-cols-[1fr_1fr_auto]">
        <ToggleCard icon={MapPin} title="Zone de chalandise" subtitle="D'où viennent vos clients ?"
                    on={catchOn} onChange={toggleCatch} />
        <ToggleCard icon={Car} title="Isochrones" subtitle="Qui peut venir en 5, 15, 25, 35 min ?"
                    on={isoOn} onChange={toggleIso} tone="violet" />
        <div className="flex items-center gap-3">
          <span className="text-[13px] font-semibold text-[#475569]">Vue :</span>
          <Segmented
            options={[{ key: 'map', label: 'Carte', icon: MapIcon }, { key: 'list', label: 'Liste', icon: ListIcon }]}
            value={view} onChange={setView}
          />
        </div>
      </div>

      {/* filters */}
      <div className="mb-4 grid gap-4 lg:grid-cols-[1fr_1.2fr_1.4fr]">
        <label className="block">
          <span className="mb-1.5 block text-[12px] font-semibold text-[#475569]">Période</span>
          <PeriodPicker from={from} to={to} onChange={(f, t) => { setFrom(f); setTo(t); }} />
        </label>
        <label className="block">
          <span className="mb-1.5 block text-[12px] font-semibold text-[#475569]">Mode de transport</span>
          <Segmented
            options={(data?.modes || []).map((m) => ({ key: m.key, label: m.label, icon: MODE_ICONS[m.key] }))}
            value={mode} onChange={setMode}
          />
        </label>
        <label className="block">
          <span className="mb-1.5 block text-[12px] font-semibold text-[#475569]">Zone géographique</span>
          <div className="relative">
            <select value={scope} onChange={(e) => setScope(e.target.value)}
                    className="w-full appearance-none rounded-xl border border-[#E6EEFB] bg-white py-2.5 pl-3 pr-9 text-[13px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]">
              {(data?.scopes || [{ key: 'local', label: 'Tours et alentours' }]).map((s) => (
                <option key={s.key} value={s.key}>{s.label}</option>
              ))}
            </select>
            <ChevronDown size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
          </div>
        </label>
      </div>

      {error && <p className="mb-4 rounded-xl bg-[#FEECEC] px-4 py-2.5 text-[12.5px] text-[#C0392B]">{error}</p>}

      {loading && !data && (
        <div className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-20 text-[13px] text-[#64748B]">
          <Loader2 size={16} className="animate-spin" /> Calcul de vos zones…
        </div>
      )}

      {data && view === 'map' && (
        <>
          <div className="grid items-start gap-4 xl:grid-cols-[1.55fr_1fr]">
            <div>
              <GeoCatchmentMap data={data} showCatchment={catchOn} showIsochrones={isoOn} mode={mode} />
              {precisionNote && (
                <p className="mt-2 flex items-start gap-1.5 px-1 text-[11.5px] leading-snug text-[#94A3B8]">
                  <Info size={13} className="mt-px shrink-0" />
                  <span>
                    {precisionNote.pct}&nbsp;% des clients sont placés à leur position exacte ; les autres au centre
                    de leur code postal{precisionNote.coarse ? `, dont ${nf(precisionNote.coarse)} au centre de leur département` : ''}.
                    {isoOn && ' Les temps de trajet sont estimés à ' + (data.speed_kmh) + ' km/h, sans calcul d’itinéraire.'}
                  </span>
                </p>
              )}
            </div>

            <div className="grid gap-4">
              <Panel title={both ? 'Nombre de clients'
                                 : catchOn ? 'Nombre de clients par zone de chalandise'
                                           : 'Nombre de clients par tranche de temps'}
                     action={<SeeMore onClick={() => setView('list')} />}>
                {both && <p className="mb-2 text-[12px] font-semibold text-[#64748B]">Par zone de chalandise</p>}
                {catchOn && (
                  <div className="grid grid-cols-3 gap-2.5">
                    {zones.map((z) => (
                      <CountCard key={z.key} tone={z.tone} heading={z.label}
                                 sub={both ? null : `${z.from_km}–${z.to_km} km`} clients={z.clients} />
                    ))}
                  </div>
                )}
                {both && <p className="mb-2 mt-4 text-[12px] font-semibold text-[#64748B]">Par temps de trajet (isochrones)</p>}
                {isoOn && (
                  <div className={`grid gap-2.5 ${both ? 'grid-cols-4' : 'grid-cols-4'}`}>
                    {bands.map((b) => (
                      <CountCard key={b.minutes} tone={b.tone} heading={`${b.minutes} min`}
                                 sub={both ? null : `≈ ${b.radius_km} km`} clients={b.clients} />
                    ))}
                  </div>
                )}
              </Panel>

              <Panel title={both ? 'Répartition des clients (vue combinée)'
                                 : catchOn ? 'Répartition des clients'
                                           : 'Répartition des clients par temps de trajet'}
                     action={<SeeMore onClick={() => setView('list')} />}>
                {both ? (
                  <Venn left={data.combined.catchment_total} right={data.combined.isochrone_total}
                        both={data.combined.both} />
                ) : catchOn ? (
                  <Donut total={data.catchment.total} caption="Répartition par zone"
                         slices={zones.map((z) => ({ key: z.key, tone: z.tone, label: z.label, value: z.clients }))} />
                ) : (
                  <Donut total={data.isochrones.total} caption="Répartition par temps de trajet"
                         slices={bands.map((b) => ({ key: b.minutes, tone: b.tone, label: `${b.minutes} min`, value: b.clients }))} />
                )}
              </Panel>
            </div>
          </div>

          {/* bottom row */}
          <div className="mt-4 grid items-start gap-4 xl:grid-cols-[1.55fr_1fr]">
            <Panel title={both ? 'Top communes (vue combinée)'
                               : catchOn ? 'Top communes par zone'
                                         : 'Top communes par tranche de temps'}
                   action={<SeeMore onClick={() => setView('list')} label="Voir toutes" />}>
              {both ? (
                <div className="grid gap-x-6 gap-y-0 sm:grid-cols-3">
                  {[0, 5, 10].map((off) => (
                    <div key={off}>
                      {(communes.combined || []).slice(off, off + 5).map((r, i) => (
                        <div key={r.name} className="flex items-center gap-2 py-[7px]">
                          <span className="flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white"
                                style={{ background: off === 0 ? TONE.rose.dot : off === 5 ? TONE.amber.dot : TONE.blue.dot }}>
                            {off + i + 1}
                          </span>
                          <span className="min-w-0 flex-1 truncate text-[12.5px] text-[#334155]">{r.name}</span>
                          <span className="shrink-0 text-[12.5px] font-semibold text-[#0B1C3F] tabular-nums">{nf(r.clients)}</span>
                        </div>
                      ))}
                    </div>
                  ))}
                  {(communes.combined || []).length === 0 && (
                    <p className="py-4 text-[12.5px] text-[#94A3B8]">Aucune commune sur cette période.</p>
                  )}
                </div>
              ) : catchOn ? (
                <div className="grid gap-x-5 sm:grid-cols-3">
                  {zones.map((z) => (
                    <CommuneColumn key={z.key} tone={z.tone} title={z.label}
                                   rows={communes.zones?.[z.key] || []} />
                  ))}
                </div>
              ) : (
                <div className="grid gap-x-5 sm:grid-cols-4">
                  {bands.map((b) => (
                    <CommuneColumn key={b.minutes} tone={b.tone} title={`${b.minutes} min`}
                                   rows={communes.bands?.[String(b.minutes)] || []} />
                  ))}
                </div>
              )}
            </Panel>

            <Panel title="Actions recommandées"
                   action={<SeeMore onClick={() => navigate('/dashboard/campaigns')} label="Voir toutes" />}>
              <div className="space-y-1">
                {actions.map((a) => {
                  const t = TONE[a.tone];
                  const Icon = a.icon;
                  return (
                    <div key={a.title} className="flex items-center gap-3 rounded-xl px-1 py-2.5">
                      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl"
                            style={{ background: t.bg, color: t.fg }}>
                        <Icon size={17} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[12.5px] font-bold leading-tight text-[#0B1C3F]">{a.title}</span>
                        <span className="block text-[11.5px] leading-tight text-[#64748B]">{a.body}</span>
                      </span>
                      <button type="button" onClick={a.go}
                              className="shrink-0 rounded-lg border border-[#E6EEFB] px-3 py-1.5 text-[12px] font-semibold text-[#334155] transition hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
                        {a.cta}
                      </button>
                    </div>
                  );
                })}
              </div>
            </Panel>
          </div>
        </>
      )}

      {data && view === 'list' && (
        <Panel title="Toutes les communes"
               action={<SeeMore onClick={() => setView('map')} label="Revenir à la carte" />}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] border-collapse">
              <thead>
                <tr className="border-b border-[#EEF3FB] text-left">
                  {['#', 'Commune', 'Clients', 'Part'].map((h, i) => (
                    <th key={h} className={`px-3 py-2.5 text-[12px] font-semibold uppercase tracking-[0.04em] text-[#64748B] ${i > 1 ? 'text-right' : ''}`}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(communes.combined || []).map((r, i) => (
                  <tr key={r.name} className="border-b border-[#F4F7FC] last:border-b-0">
                    <td className="px-3 py-2.5 text-[12.5px] text-[#94A3B8] tabular-nums">{i + 1}</td>
                    <td className="px-3 py-2.5 text-[13px] font-medium text-[#0B1C3F]">{r.name}</td>
                    <td className="px-3 py-2.5 text-right text-[12.5px] tabular-nums text-[#334155]">{nf(r.clients)}</td>
                    <td className="px-3 py-2.5 text-right text-[12.5px] font-semibold tabular-nums text-[#0B1C3F]">
                      {data.catchment.total ? Math.round((r.clients / data.catchment.total) * 100) : 0} %
                    </td>
                  </tr>
                ))}
                {(communes.combined || []).length === 0 && (
                  <tr><td colSpan={4} className="px-3 py-10 text-center text-[13px] text-[#64748B]">
                    Aucune commune sur cette période.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {data && data.positioned === false && (
        <div className="mt-4 rounded-2xl border border-dashed border-[#D9E4F7] bg-white px-5 py-8 text-center">
          <p className="text-[13.5px] font-semibold text-[#0B1C3F]">Nous ne connaissons pas encore votre adresse</p>
          <p className="mx-auto mt-1 max-w-md text-[12.5px] text-[#64748B]">
            Renseignez l'adresse de votre établissement pour calculer vos zones de chalandise et vos temps de trajet.
          </p>
          {/* The shop's address is a shop-wide setting: the owner's. */}
          {user?.role === 'business_owner' ? (
            <button type="button" onClick={() => navigate('/dashboard/settings')}
                    className="mt-3 rounded-lg bg-[#2F6BFF] px-4 py-2 text-[12.5px] font-semibold text-white">
              Ouvrir les paramètres
            </button>
          ) : (
            <p className="mt-3 text-[12.5px] text-[#64748B]">Demandez au propriétaire de renseigner l&apos;adresse.</p>
          )}
        </div>
      )}
    </div>
  );
}
