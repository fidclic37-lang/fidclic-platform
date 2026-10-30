import React, { useState } from 'react';

/**
 * « La dernière fois : +X € (mesuré avec le groupe témoin) » — what this idea
 * brought the last time it was sent here (user, 2026-10-29). The server
 * writes the sentence (api/features/reco_journal.py `line`); nothing when the
 * idea was never measured.
 */
export default function RecoLastResult({ r, className = '' }) {
  const t = r?.last_result?.text;
  if (!t) return null;
  const won = (r.last_result.euros || 0) > 0;
  return (
    <p data-testid="reco-last" className={`text-[11.5px] leading-snug ${won ? 'text-[#0F8B58]' : 'text-[#64748B]'} ${className}`}>{t}</p>
  );
}

/**
 * « Pourquoi en premier ? » — what the ranking learned for this idea here and
 * from shops like this one (api/features/reco_ranking.py `why`, 2026-10-30).
 */
export function RecoWhy({ r, className = '' }) {
  const [open, setOpen] = useState(false);
  const t = r?.why_rank?.text;
  // « Ce que FidClic IA retient » changed this advice (2026-10-30): said on the card, not behind the toggle
  const said = r?.why_rank?.selon;
  if (!t) return null;
  return (
    <div className={className}>
      {said && <p data-testid="reco-said" className="mb-1 text-[11.5px] font-medium leading-snug text-[#7C3AED]">{said}</p>}
      <button type="button" aria-expanded={open} onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}
              className="text-[11.5px] font-semibold text-[#2F6BFF] hover:underline">Pourquoi en premier ?</button>
      {open && <p data-testid="reco-why" className="mt-1 rounded-lg bg-[#F8FAFF] px-2.5 py-1.5 text-[11.5px] leading-snug text-[#475569]">{t}</p>}
    </div>
  );
}

/** A link into the composer, saying which surface the idea was taken from. */
export function withFrom(to, surface) {
  if (typeof to !== 'string' || !to.includes('template=') || /[?&]from=/.test(to)) return to;
  return `${to}${to.includes('?') ? '&' : '?'}from=${encodeURIComponent(surface)}`;
}
