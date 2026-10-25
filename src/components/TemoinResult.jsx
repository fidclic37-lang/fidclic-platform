import React, { useState } from 'react';
import { FlaskConical, ChevronDown } from 'lucide-react';

/**
 * Groupe témoin (user, 2026-10-25): what one send — or one relance automation,
 * or the period on Analyses — really brought in. The messaged clients'
 * return and spend against the témoin's, 15 days after each message; only the
 * counts, never the témoin's names. `t` is features/temoin.py's figures.
 */
const nf = (n) => new Intl.NumberFormat('fr-FR').format(Math.round(n || 0));
const eur = (n) => new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n || 0);
const pct = (n) => `${String(n ?? 0).replace('.', ',')} %`;
const day = (iso) => (iso ? new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' }) : '');

export function Uplift({ t, big = false }) {
  if (!t || !t.sent?.n || !t.temoin?.n) return null;
  const up = (t.extra_revenue || 0) > 0;
  return (
    <p className={`${big ? 'text-[24px]' : 'text-[19px]'} font-extrabold leading-tight ${up ? 'text-[#059669]' : 'text-[#475569]'}`} data-testid="uplift">
      {up ? `+${eur(t.extra_revenue)} grâce à FidClic` : 'Pas d\'effet mesuré pour l\'instant'}
    </p>
  );
}

export function HowItWorks({ t }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
              className="inline-flex items-center gap-1 text-[13px] font-semibold text-[#6D28D9]">
        Comment c'est calculé ? <ChevronDown size={14} className={open ? 'rotate-180' : ''} />
      </button>
      {open && (
        <div className="mt-2 space-y-1.5 rounded-xl bg-white p-3 text-[13px] leading-snug text-[#334155]" data-testid="temoin-how">
          <p>À chaque campagne groupée et à chaque relance automatique, <b>{t?.share || 15} % des clients</b>, tirés au hasard,
            ne reçoivent pas le message : c'est le <b>groupe témoin</b>. Un nouveau tirage à chaque envoi, personne n'est mis de côté pour de bon.</p>
          <p>{t?.window_days || 15} jours après, on compare : combien sont revenus et combien ils ont dépensé, d'un côté les clients
            qui ont reçu le message, de l'autre le groupe témoin. Les clients qui seraient venus de toute façon sont dans les deux groupes : ils s'annulent.</p>
          {t?.sent?.n > 0 && t?.temoin?.n > 0 && (
            <p>Ici : ({eur(t.sent.per_client)} − {eur(t.temoin.per_client)}) par client × {nf(t.sent.n)} clients
              = <b>{eur(t.extra_revenue)}</b>.</p>
          )}
          <p>Jamais de groupe témoin pour un anniversaire, une récompense, un message de bienvenue ou un message à un seul client.
            Réglage : Paramètres › Notifications.</p>
        </div>
      )}
    </div>
  );
}

export default function TemoinResult({ t, what = 'cet envoi' }) {
  if (!t) return null;
  const c = t.counts || { sent: t.sent?.n, temoin: t.temoin?.n };
  const measured = t.sent?.n > 0 && t.temoin?.n > 0;
  return (
    <div className="rounded-2xl border border-[#E9E3FF] bg-[#F8F6FF] p-4" data-testid="temoin-result">
      <p className="flex items-center gap-2 text-[14.5px] font-bold text-[#0B1C3F]">
        <FlaskConical size={18} className="text-[#7C3AED]" /> Groupe témoin
      </p>
      <p className="mt-1 text-[13px] text-[#475569]">
        {nf(c.sent)} client{c.sent > 1 ? 's' : ''} ont reçu le message · {nf(c.temoin)} en groupe témoin
        ({t.share || 15} %, tirés au hasard, sans message)
      </p>
      {measured ? (
        <>
          <div className="mt-3"><Uplift t={t} /></div>
          <div className="mt-2 grid grid-cols-2 gap-2 text-[13px]">
            <div className="rounded-xl bg-white p-2.5">
              <p className="text-[#64748B]">Avec le message</p>
              <p className="font-bold text-[#0B1C3F]">{pct(t.sent.rate)} revenus</p>
              <p className="text-[#64748B]">{eur(t.sent.per_client)} par client</p>
            </div>
            <div className="rounded-xl bg-white p-2.5">
              <p className="text-[#64748B]">Groupe témoin</p>
              <p className="font-bold text-[#0B1C3F]">{pct(t.temoin.rate)} revenus</p>
              <p className="text-[#64748B]">{eur(t.temoin.per_client)} par client</p>
            </div>
          </div>
          {!t.enough && (
            <p className="mt-2 text-[12.5px] text-[#92400E]">Indicatif : {nf(t.temoin.n)} client{t.temoin.n > 1 ? 's' : ''} témoin{t.temoin.n > 1 ? 's' : ''} seulement,
              il en faut {t.min_hold || 30} pour conclure.</p>
          )}
          {t.pending > 0 && <p className="mt-1 text-[12.5px] text-[#64748B]">{nf(t.pending)} message{t.pending > 1 ? 's' : ''} de moins de {t.window_days} jours, encore en mesure.</p>}
        </>
      ) : (
        <p className="mt-2 text-[13px] text-[#475569]">
          Résultat {t.ready_on ? `le ${day(t.ready_on)}` : `${t.window_days || 15} jours après chaque message`} : on comparera alors les visites
          des deux groupes pour mesurer ce que {what} vous a vraiment rapporté.
        </p>
      )}
      <HowItWorks t={t} />
    </div>
  );
}
