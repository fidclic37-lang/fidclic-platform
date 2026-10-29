import React from 'react';

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

/** A link into the composer, saying which surface the idea was taken from. */
export function withFrom(to, surface) {
  if (typeof to !== 'string' || !to.includes('template=') || /[?&]from=/.test(to)) return to;
  return `${to}${to.includes('?') ? '&' : '?'}from=${encodeURIComponent(surface)}`;
}
