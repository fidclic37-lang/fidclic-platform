import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { eur } from '../lib/money';

/**
 * The « Évolution du chiffre d'affaires » / « Nouveaux clients » chart, shared
 * by the Tableau de bord and Analyses so the two behave the same (user,
 * 2026-10-16: « should behave identically »).
 *
 * Reading a point:
 *   • hover (or keyboard focus) → a card follows the cursor's column and
 *     leaves when the cursor does;
 *   • click → the same card stays, with the day's whole story and a way out
 *     (✕, Échap, or a click anywhere else).
 *
 * The chart is SVG in a viewBox, so the card is placed in percentages of the
 * box — no measuring, correct at every width.
 */
const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');
const dayLabel = (iso) => { const d = new Date(iso); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; };
const pointLabel = (p) => p.label || dayLabel(p.date);
const fullLabel = (p) => {
  if (p.label) return p.label;                       // an hour slot carries its own
  const d = new Date(p.date);
  return Number.isNaN(d.getTime()) ? p.date
    : d.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' });
};

/** The lines under the headline figure: what the day was worth, in context. */
function storyOf(point, series, isMoney, unit) {
  const fmt = (v) => (isMoney ? eur(v) : nf(v));
  const values = series.map((p) => p.value || 0);
  const total = values.reduce((a, b) => a + b, 0);
  const avg = values.length ? total / values.length : 0;
  const rows = [];
  if (total > 0) rows.push([`Part de la période`, `${Math.round(((point.value || 0) / total) * 100)} %`]);
  if (avg > 0) {
    const diff = Math.round((((point.value || 0) - avg) / avg) * 100);
    rows.push(['Par rapport à la moyenne', `${diff > 0 ? '+' : ''}${diff} % (moy. ${fmt(Math.round(avg))})`]);
  }
  if (point.visits !== undefined && point.visits !== null) {
    rows.push(['Visites', nf(point.visits)]);
    if (isMoney && point.visits > 0) rows.push(['Panier moyen', eur((point.value || 0) / point.visits)]);
  }
  if (!rows.length) rows.push([unit, fmt(point.value || 0)]);
  return rows;
}

const TrendChart = ({
  series, kind = 'line', money: isMoney = false, height = 200,
  unit = 'Total', openLabel, onOpen, empty = 'Aucune donnée sur la période.',
}) => {
  const gid = useId().replace(/[^a-zA-Z0-9]/g, '');
  const pts = useMemo(() => series || [], [series]);
  const [hover, setHover] = useState(null);           // index under the cursor
  const [pinned, setPinned] = useState(null);         // index clicked
  const box = useRef(null);

  // A pinned card is dismissed like any popover: Échap, or a click outside.
  useEffect(() => {
    if (pinned === null) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') setPinned(null); };
    const onDown = (e) => { if (box.current && !box.current.contains(e.target)) setPinned(null); };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('mousedown', onDown); };
  }, [pinned]);

  // The series can change under a pinned card (the owner switches period).
  useEffect(() => { setPinned(null); setHover(null); }, [pts]);

  const W = 620, PAD_L = kind === 'bar' ? 34 : 46, PAD_B = 24, PAD_T = 10, PAD_R = 8;
  const H = height;
  const max = Math.max(1, ...pts.map((p) => p.value || 0));
  const top = kind === 'bar'
    ? Math.max(1, Math.ceil(max / 10) * 10 || max)
    : (() => {
      const stepSize = Math.pow(10, Math.max(0, String(Math.round(max)).length - 1)) / 2 || 1;
      return Math.max(stepSize, Math.ceil(max / stepSize) * stepSize);
    })();
  const iw = W - PAD_L - PAD_R, ih = H - PAD_T - PAD_B;
  const slot = pts.length ? iw / pts.length : iw;
  const x = (i) => (kind === 'bar'
    ? PAD_L + (i + 0.5) * slot
    : PAD_L + (pts.length <= 1 ? iw / 2 : (i / (pts.length - 1)) * iw));
  const y = (v) => PAD_T + ih - ((v || 0) / top) * ih;
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ');
  const bw = pts.length ? Math.max(2, slot * 0.6) : 0;
  const idx = pts.length <= 1 ? [0]
    : [0, Math.round((pts.length - 1) / 3), Math.round((pts.length - 1) * 2 / 3), pts.length - 1];

  if (!pts.length) return <p className="py-12 text-center text-[13px] text-[#94A3B8]">{empty}</p>;

  const active = pinned !== null ? pinned : hover;
  const point = active === null ? null : pts[active];
  // The card sits above the point, and flips to the other side near an edge.
  const leftPct = active === null ? 0 : (x(active) / W) * 100;
  const flip = leftPct > 62;

  return (
    <div ref={box} className="relative" style={{ height }} data-testid="trend-chart">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }}
           onMouseLeave={() => setHover(null)}>
        <defs>
          <linearGradient id={`tc${gid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2F6BFF" stopOpacity="0.26" />
            <stop offset="100%" stopColor="#2F6BFF" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {[0, top / 2, top].map((v) => (
          <g key={v}>
            <line x1={PAD_L} x2={W - PAD_R} y1={y(v)} y2={y(v)} stroke="#EEF3FB" />
            <text x={PAD_L - 8} y={y(v) + 4} textAnchor="end" fontSize="10.5" fill="#94A3B8">
              {isMoney ? `${nf(Math.round(v))} €` : nf(Math.round(v))}
            </text>
          </g>
        ))}

        {kind === 'line' ? (
          <>
            <path d={`${line} L${x(pts.length - 1).toFixed(1)},${PAD_T + ih} L${x(0).toFixed(1)},${PAD_T + ih} Z`}
                  fill={`url(#tc${gid})`} />
            <path d={line} fill="none" stroke="#2F6BFF" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />
          </>
        ) : (
          pts.map((p, i) => (
            <rect key={p.date} x={x(i) - bw / 2} y={y(p.value)} width={bw}
                  height={Math.max(0, PAD_T + ih - y(p.value))} rx="2.5"
                  fill={active === i ? '#1D4FD8' : '#2F6BFF'} />
          ))
        )}

        {/* the point under the cursor: a guide line and a bigger dot */}
        {active !== null && (
          <g pointerEvents="none">
            <line x1={x(active)} x2={x(active)} y1={PAD_T} y2={PAD_T + ih} stroke="#2F6BFF" strokeOpacity="0.35"
                  strokeDasharray="3 3" />
            {kind === 'line' && (
              <circle cx={x(active)} cy={y(point.value)} r="5" fill="#2F6BFF" stroke="#fff" strokeWidth="2" />
            )}
          </g>
        )}

        {kind === 'line' && pts.map((p, i) => (
          <circle key={p.date} cx={x(i)} cy={y(p.value)} r="2.6" fill="#fff" stroke="#2F6BFF" strokeWidth="1.8"
                  pointerEvents="none" />
        ))}

        {idx.map((i) => (
          <text key={i} x={x(i)} y={H - 5} fontSize="10.5" fill="#94A3B8"
                textAnchor={i === 0 ? 'start' : i === pts.length - 1 ? 'end' : 'middle'}>
            {pointLabel(pts[i])}
          </text>
        ))}

        {/* The whole column answers to the cursor, not the 2.6 px dot. */}
        {pts.map((p, i) => (
          <rect key={`hit-${p.date}`} x={PAD_L + i * slot} y={PAD_T} width={slot} height={ih}
                fill="transparent" tabIndex={0} role="button"
                aria-label={`${fullLabel(p)} : ${isMoney ? eur(p.value) : nf(p.value)}`}
                style={{ cursor: 'pointer', outline: 'none' }}
                onMouseEnter={() => setHover(i)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover((h) => (h === i ? null : h))}
                onClick={() => setPinned((v) => (v === i ? null : i))}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setPinned((v) => (v === i ? null : i)); }
                }} />
        ))}
      </svg>

      {point && (
        <div className="pointer-events-none absolute z-20"
             style={{ left: `${leftPct}%`, top: 6, transform: `translateX(${flip ? '-100%' : '0'})`,
                      paddingLeft: flip ? 0 : 10, paddingRight: flip ? 10 : 0 }}>
          <div data-testid={pinned !== null ? 'trend-detail' : 'trend-tip'}
               className={`${pinned !== null ? 'pointer-events-auto' : ''} min-w-[168px] rounded-xl border border-[#E6EDF8] bg-white p-3 shadow-[0_10px_30px_-12px_rgba(15,34,80,.35)]`}>
            <div className="flex items-start gap-3">
              <div>
                <p className="text-[11px] font-medium text-[#94A3B8] first-letter:uppercase">{fullLabel(point)}</p>
                <p className="text-[17px] font-bold tabular-nums text-[#0B1C3F]">
                  {isMoney ? eur(point.value) : nf(point.value)}
                </p>
              </div>
              {pinned !== null && (
                <button type="button" onClick={() => setPinned(null)} aria-label="Fermer"
                        className="ml-auto rounded-md p-0.5 text-[#94A3B8] hover:bg-[#F2F6FD] hover:text-[#0B1C3F]">
                  <X size={14} />
                </button>
              )}
            </div>
            {pinned !== null ? (
              <>
                <dl className="mt-2 space-y-1 border-t border-[#EEF3FB] pt-2">
                  {storyOf(point, pts, isMoney, unit).map(([k, v]) => (
                    <div key={k} className="flex items-baseline justify-between gap-4">
                      <dt className="text-[11.5px] text-[#64748B]">{k}</dt>
                      <dd className="text-[12px] font-semibold tabular-nums text-[#0B1C3F]">{v}</dd>
                    </div>
                  ))}
                </dl>
                {onOpen && openLabel && (
                  <button type="button" onClick={() => { setPinned(null); onOpen(point); }}
                          className="mt-2 w-full rounded-lg bg-[#2F6BFF] px-2 py-1.5 text-[12px] font-semibold text-white hover:bg-[#1D4FD8]">
                    {openLabel}
                  </button>
                )}
              </>
            ) : (
              <p className="mt-1 text-[10.5px] text-[#94A3B8]">Cliquez pour le détail</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default TrendChart;
