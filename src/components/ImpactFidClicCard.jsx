import React from 'react';
import { Sparkles, Send, Users, Gift } from 'lucide-react';
import InfoTip from './InfoTip';
import { eur } from '../lib/money';

/**
 * « Impact FidClic » — the revenue FidClic's own actions brought back, drawn
 * from the user's mockup (2026-10-10), the same on the Tableau de bord and in
 * Analyses. The three tiles only SAY what brings it (campaigns, the visits
 * they generate, parrainage): they are not buttons, and the card is not a
 * link. What is counted is explained by the (i).
 */
const TILES = [
  { icon: Send, label: 'Campagnes' },
  { icon: Users, label: 'Visites générées' },
  { icon: Gift, label: 'Parrainage' },
];

// the rising bars of the mockup — decoration only
function Growth() {
  return (
    <svg aria-hidden="true" viewBox="0 0 150 130" className="pointer-events-none h-full w-full">
      <defs>
        <linearGradient id="ifc-bar" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#93B4FF" />
          <stop offset="1" stopColor="#DCE7FF" />
        </linearGradient>
        <linearGradient id="ifc-side" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#6F95F2" />
          <stop offset="1" stopColor="#B9CCF8" />
        </linearGradient>
        <linearGradient id="ifc-arrow" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#A5B8FF" stopOpacity="0.2" />
          <stop offset="1" stopColor="#2F6BFF" />
        </linearGradient>
      </defs>
      {[[22, 78, 46], [58, 62, 62], [94, 38, 86]].map(([x, y, h]) => (
        <g key={x} opacity="0.95">
          <path d={`M${x} ${y} l18 -7 l14 6 l-18 7 z`} fill="#E4ECFF" />
          <rect x={x} y={y} width="14" height={h} fill="url(#ifc-bar)" />
          <path d={`M${x + 14} ${y} l18 -7 v${h} l-18 7 z`} fill="url(#ifc-side)" opacity="0.75" />
        </g>
      ))}
      <path d="M6 96 C 48 80, 88 54, 132 14" fill="none" stroke="url(#ifc-arrow)" strokeWidth="4" strokeLinecap="round" />
      <path d="M118 12 L136 10 L131 28 Z" fill="#2F6BFF" />
    </svg>
  );
}

export default function ImpactFidClicCard({ value, className = '' }) {
  const n = Number(value) || 0;
  return (
    <section aria-label="Impact FidClic"
             className={`relative overflow-hidden rounded-2xl border border-[#C9D5FB] bg-gradient-to-br from-white via-white to-[#F3F1FF] p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] ${className}`}>
      <div className="flex items-start gap-3.5">
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#F1EDFF] text-[#7C3AED]">
          <Sparkles size={22} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="flex items-center gap-2 text-[21px] font-bold leading-tight text-[#0B1C3F]">
            Impact FidClic <InfoTip k="impact" size={15} />
          </h2>
          <p className="mt-1 text-[13.5px] text-[#64748B]">Chiffre d'affaires attribué aux actions FidClic</p>
        </div>
        <span className="shrink-0 rounded-full bg-[#DFF6EA] px-4 py-1.5 text-[22px] font-extrabold leading-none tabular-nums text-[#0F8B58]">
          + {eur(n)}
        </span>
      </div>
      <div className="relative mt-5 flex items-end gap-3">
        <ul className="relative z-10 grid flex-1 grid-cols-3 gap-2.5 sm:max-w-[420px]">
          {TILES.map(({ icon: Icon, label }) => (
            <li key={label}
                className="flex cursor-default select-none flex-col items-center justify-center gap-2 rounded-xl bg-white/95 px-2 py-3.5 text-center shadow-[0_6px_18px_-12px_rgba(15,23,42,.35)]">
              <Icon size={22} className="text-[#2F6BFF]" aria-hidden="true" />
              <span className="text-[12.5px] font-medium leading-tight text-[#334155]">{label}</span>
            </li>
          ))}
        </ul>
        <div className="pointer-events-none hidden h-[104px] w-[130px] shrink-0 sm:block">
          <Growth />
        </div>
      </div>
    </section>
  );
}
