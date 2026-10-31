import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, ShoppingBag, CalendarClock, Euro, Repeat, Store, Sparkles, Send, ChevronDown, Zap, TrendingDown, TrendingUp, Magnet } from 'lucide-react';
import { ownerAPI } from '../lib/api';

/* « Profil client » (FidClic IA, user 2026-10-24): what the client brain
   learned from this client's visits — what they take, when, how much, how
   often, when they should be back, where they stand now, and the one thing
   worth sending. Nothing leaves from here: « Préparer le message » opens the
   composer pre-filled, the owner edits and sends. */

const TZ = 'Europe/Paris';
const eur = (n) => `${new Intl.NumberFormat('fr-FR', { maximumFractionDigits: n >= 10 ? 0 : 2 }).format(n ?? 0)} €`;
const short = (iso) => (iso ? new Date(iso).toLocaleDateString('fr-FR', { timeZone: TZ, day: 'numeric', month: 'short' }) : '');

const STATUS = {
  a_l_heure: { bg: '#E7F7EE', fg: '#0F7A45', dot: '#10B981' },
  en_retard: { bg: '#FFF4DB', fg: '#92400E', dot: '#F59E0B' },
  decroche: { bg: '#FEECEC', fg: '#B42318', dot: '#EF4444' },
  trop_tot: { bg: '#F1F5F9', fg: '#475569', dot: '#94A3B8' },
};

const PR_TONE = {
  aimant: { bg: '#ECFDF3', fg: '#0F7A45' },
  neutre: { bg: '#F4F7FC', fg: '#475569' },
  one_shot: { bg: '#FFF7ED', fg: '#B45309' },
};

const Row = ({ icon: Icon, label, children, testid }) => (
  <div className="flex gap-3 py-2.5" data-testid={testid}>
    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#F1F5FF] text-[#2F6BFF]"><Icon size={14} /></span>
    <div className="min-w-0 flex-1">
      <p className="text-[11.5px] font-semibold uppercase tracking-[0.04em] text-[#94A3B8]">{label}</p>
      <div className="text-[13.5px] text-[#0B1C3F]">{children}</div>
    </div>
  </div>
);

export default function ClientProfile({ clientId }) {
  const navigate = useNavigate();
  const [d, setD] = useState(null);
  const [error, setError] = useState('');
  const [how, setHow] = useState(false);

  useEffect(() => {
    let alive = true;
    setD(null);
    ownerAPI.clientProfil(clientId)
      .then(({ data }) => { if (alive) { setD(data); setError(''); } })
      .catch((e) => { if (alive) setError(e?.response?.data?.detail || "Le profil n'a pas pu être chargé."); });
    return () => { alive = false; };
  }, [clientId]);

  if (error) return <p className="rounded-lg bg-[#FEF2F2] px-3 py-2.5 text-[13px] text-[#B91C1C]">{error}</p>;
  if (!d) return <p className="flex items-center gap-2 text-[13px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</p>;

  const st = STATUS[d.status.key] || STATUS.trop_tot;
  const offer = d.offer || {};
  const items = d.habits.items || [];

  return (
    <div className="space-y-4" data-testid="client-profile">
      {/* where they stand, who they are */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[12px] font-semibold"
              style={{ background: st.bg, color: st.fg }} data-testid="profile-status">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: st.dot }} />
          {d.status.label}{d.status.late_days ? ` de ${d.status.late_days} jour${d.status.late_days > 1 ? 's' : ''}` : ''}
        </span>
        <span className="rounded-md bg-[#EEF2FF] px-2.5 py-1 text-[12px] font-semibold text-[#4338CA]" data-testid="profile-kind">{d.profile.label}</span>
        {d.tags.map((t) => (
          <span key={t} className="rounded-md bg-[#F8FAFC] px-2.5 py-1 text-[12px] font-medium text-[#475569] ring-1 ring-[#E2E8F0]">{t}</span>
        ))}
      </div>

      {/* the next visit — a window, never a date */}
      <div className="rounded-2xl border border-[#E6EEFB] bg-[#F8FAFF] p-4" data-testid="profile-next">
        <p className="text-[12px] font-semibold text-[#64748B]">Prochaine visite</p>
        {d.next ? (
          <>
            <p className="mt-0.5 text-[18px] font-bold text-[#0B1C3F]">
              {d.status.key === 'a_l_heure' ? `Entre le ${short(d.next.from)} et le ${short(d.next.to)}` : `Attendue entre le ${short(d.next.from)} et le ${short(d.next.to)}`}
            </p>
            {d.status.key !== 'a_l_heure' && d.status.silent_days != null && (
              <p className="text-[12.5px] text-[#92400E]">Pas venu depuis {d.status.silent_days} jours.</p>
            )}
            {d.next.confidence != null && (
              <div className="mt-2.5 flex items-center gap-2.5">
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-[#E6EEFB]">
                  <span className="block h-full rounded-full bg-[#2F6BFF]" style={{ width: `${d.next.confidence}%` }} />
                </span>
                <span className="text-[12px] font-semibold tabular-nums text-[#334155]">Confiance {d.next.confidence} %</span>
              </div>
            )}
          </>
        ) : (
          <p className="mt-0.5 text-[14px] text-[#475569]">
            {d.visits === 0 ? 'Pas encore venu en boutique.'
              : `Trop tôt pour savoir : venu ${d.days} jour${d.days > 1 ? 's' : ''} différent${d.days > 1 ? 's' : ''}, il en faut 3 pour connaître son rythme.`}
          </p>
        )}
      </div>

      <div className="divide-y divide-[#F1F5FB] rounded-2xl border border-[#EEF3FB] px-4">
        <Row icon={ShoppingBag} label="D'habitude" testid="profile-habits">
          {items.length ? (
            <ul className="space-y-0.5">
              {items.slice(0, 3).map((it) => (
                <li key={it.name} className="flex justify-between gap-3">
                  <span translate="no" className="notranslate truncate font-semibold">{it.name}</span>
                  <span className="shrink-0 text-[12.5px] text-[#64748B]">{it.visits} fois sur {d.habits.visits_with_items}</span>
                </li>
              ))}
            </ul>
          ) : <span className="text-[#94A3B8]">Aucun produit enregistré à ses passages.</span>}
        </Row>
        <Row icon={CalendarClock} label="Quand" testid="profile-when">
          {d.when.weekday || d.when.hours || d.when.slot
            ? [d.when.weekday && `Le ${d.when.weekday}`, d.when.hours || d.when.slot].filter(Boolean).join(' · ')
            : <span className="text-[#94A3B8]">Pas encore d&apos;habitude nette.</span>}
        </Row>
        <Row icon={Euro} label="Panier" testid="profile-basket">
          {d.basket
            ? <>~{eur(d.basket.usual)}{d.basket.low !== d.basket.high && <span className="text-[#64748B]"> (de {eur(d.basket.low)} à {eur(d.basket.high)})</span>}</>
            : <span className="text-[#94A3B8]">Aucun montant saisi.</span>}
        </Row>
        <Row icon={Repeat} label="Rythme" testid="profile-rhythm">
          {d.rhythm ? (
            <>
              <span className="font-semibold">{d.rhythm.text[0].toUpperCase() + d.rhythm.text.slice(1)}</span>
              {d.rhythm.trend_label && d.rhythm.trend !== 'stable' && (
                <span className={`ml-2 inline-flex items-center gap-1 text-[12.5px] font-semibold ${d.rhythm.trend === 'baisse' ? 'text-[#B42318]' : 'text-[#0F7A45]'}`}>
                  {d.rhythm.trend === 'baisse' ? <TrendingDown size={13} /> : <TrendingUp size={13} />} {d.rhythm.trend_label}
                </span>
              )}
            </>
          ) : <span className="text-[#94A3B8]">Connu à partir de 3 jours de visite.</span>}
        </Row>
        {d.store && <Row icon={Store} label="Établissement habituel"><span translate="no" className="notranslate">{d.store}</span></Row>}
        {/* « Produits qui font revenir » (Pro AI): the kind of each of their products */}
        {d.produits?.tags?.length > 0 && (
          <Row icon={Magnet} label="Ses produits" testid="profile-products">
            <span className="flex flex-wrap gap-1.5">
              {d.produits.tags.map((t) => (
                <span key={t.name} className="rounded-md px-2 py-0.5 text-[12px] font-medium"
                      style={{ background: PR_TONE[t.bucket]?.bg, color: PR_TONE[t.bucket]?.fg }}>
                  <span translate="no" className="notranslate">{t.name}</span> ({t.label})
                </span>
              ))}
            </span>
          </Row>
        )}
      </div>

      {d.produits?.suggest && (
        <div className="rounded-2xl border border-[#CDEFD9] bg-[#F3FCF6] p-4" data-testid="profile-product-suggest">
          <p className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-[#0F8B58]"><Magnet size={13} /> À proposer</p>
          <p className="mt-1 text-[15px] font-bold text-[#0B1C3F]"><span translate="no" className="notranslate">{d.produits.suggest.name}</span></p>
          {d.produits.suggest.back != null && (
            <p className="text-[12.5px] text-[#475569]">Après ce produit, {d.produits.suggest.back} clients sur 10 reviennent. Il ne l&apos;a jamais pris.</p>
          )}
          <button type="button" data-testid="profile-product-cta"
                  onClick={() => navigate(`/dashboard/campaigns?template=${encodeURIComponent(d.produits.suggest.template)}&from=clients`)}
                  className="mt-3 inline-flex h-10 items-center gap-2 rounded-xl bg-[#0F8B58] px-4 text-[13px] font-semibold text-white hover:bg-[#0C7449]">
            <Send size={14} /> Contacter
          </button>
        </div>
      )}

      {/* the one thing worth doing */}
      <div className="rounded-2xl border border-[#DCD3FF] bg-[#FAF8FF] p-4" data-testid="profile-offer">
        <p className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-[#5B3FD6]"><Sparkles size={13} /> Offre suggérée</p>
        <p className="mt-1 text-[15px] font-bold text-[#0B1C3F]">{offer.label}</p>
        {offer.when && <p className="text-[12.5px] font-semibold text-[#475569]">À envoyer : {offer.when}</p>}
        <p className="mt-1.5 text-[13px] leading-relaxed text-[#475569]"><b className="text-[#334155]">Pourquoi ? </b>{offer.why}</p>
        {offer.template && (
          <button type="button" data-testid="profile-offer-cta"
                  onClick={() => navigate(`/dashboard/campaigns?template=${encodeURIComponent(offer.template)}&from=clients`)}
                  className="mt-3 inline-flex h-10 items-center gap-2 rounded-xl bg-[#5B3FD6] px-4 text-[13px] font-semibold text-white hover:bg-[#4C32C0]">
            <Send size={14} /> Préparer le message
          </button>
        )}
        {offer.template && <p className="mt-1.5 text-[11.5px] text-[#94A3B8]">Rien n&apos;est envoyé sans votre validation.</p>}
      </div>

      {d.caisse && (
        <p className="flex items-start gap-2 rounded-xl bg-[#F8FAFC] px-3 py-2.5 text-[12.5px] text-[#475569]">
          <Zap size={14} className="mt-0.5 shrink-0 text-[#5B3FD6]" />
          <span>À la caisse, l&apos;équipe voit : <b className="text-[#334155]">{d.caisse}</b></span>
        </p>
      )}

      <div>
        <button type="button" onClick={() => setHow(!how)} aria-expanded={how}
                className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-[#2F6BFF]">
          Comment c&apos;est calculé ? <ChevronDown size={14} className={how ? 'rotate-180' : ''} />
        </button>
        {how && <p className="mt-1.5 text-[12.5px] leading-relaxed text-[#64748B]">{d.how}</p>}
      </div>
    </div>
  );
}
