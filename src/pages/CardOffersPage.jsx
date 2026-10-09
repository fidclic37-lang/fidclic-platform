import React, { useEffect, useMemo, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Gift, Sparkles, ChevronRight, ChevronLeft, X, ExternalLink, Loader2, Tag } from 'lucide-react';
import api from '../lib/api';
import { ownerLink, addMine, keyOf } from '../lib/myCards';
import { cycleVisits, rewardsPending } from '../lib/cardCycle';

/**
 * « Vos offres » — where « Voir les offres et récompenses » under the Wallet
 * pass lands (iOS 27 featured action). Redesigned 2026-10-09 from the user's
 * mockup: the shop's logo and « Vos offres, <prénom> », the reward card with
 * its meter, then the offers running for THIS customer, each with its photo
 * (or a picture of the shop's trade), what it gives and until when.
 * The « Défi en cours » block of the mockup comes with the challenges feature.
 *
 * Reads the same /api/card/{id} the card page reads; opening an offer counts
 * as an open (campaign pixel), its link as a click.
 */
// a campaign written with {first_name} / {prenom} reads with the customer's own
const personal = (text, c = {}) => String(text || '')
  .replace(/\{(first_name|prenom)\}/gi, (c.name || '').split(' ')[0] || '')
  .replace(/\{(name|nom)\}/gi, c.name || '');
const fmtDay = (v) => (v ? new Date(v).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' }) : '');

// The shop's trade (Mon établissement › secteur) gives the pictures when an
// offer has no photo of its own.
const SECTOR_LOOK = {
  cafe: ['☕', 'from-[#F6E7D7] to-[#E9CDAE]'],
  restaurant: ['🍽️', 'from-[#FDE7DF] to-[#F8C9B8]'],
  pizzeria: ['🍕', 'from-[#FFE8D6] to-[#FBC79F]'],
  bakery: ['🥐', 'from-[#FBEFD9] to-[#F1D3A1]'],
  bar: ['🍹', 'from-[#FCE4EF] to-[#F5BFD7]'],
  spa: ['💆', 'from-[#E6F4F1] to-[#BFE3DA]'],
  salon: ['💇', 'from-[#F1E8FB] to-[#D9C6F3]'],
  gym: ['💪', 'from-[#E3EEFF] to-[#BBD3FB]'],
  retail: ['🛍️', 'from-[#EAF1FF] to-[#C9DAFB]'],
};
const lookOf = (sector) => SECTOR_LOOK[sector] || ['🎁', 'from-[#EAF1FF] to-[#C9DAFB]'];

// What the reward is, as a picture: the words of the reward first, then the trade.
const REWARD_PICS = [
  [/dessert|g[âa]teau|p[âa]tisserie|cookie|cr[êe]pe|glace/i, '🍰'],
  [/caf[ée]|coffee|expresso|espresso|cappuccino|latte|th[ée]\b/i, '☕'],
  [/cocktail|bi[èe]re|verre|ap[ée]ro/i, '🍹'],
  [/boisson|soda|jus|smoothie/i, '🥤'],
  [/pizza/i, '🍕'],
  [/burger|sandwich|tacos|kebab/i, '🍔'],
  [/croissant|viennoiserie|pain|baguette/i, '🥐'],
  [/menu|repas|plat|d[ée]jeuner|d[îi]ner/i, '🍽️'],
  [/coupe|brushing|coiffure|barbe/i, '💇'],
  [/massage|soin|manucure/i, '💆'],
  [/%|remise|r[ée]duction|bon d.achat|€/i, '🏷️'],
];
const rewardPic = (text, sector) => (REWARD_PICS.find(([re]) => re.test(text || '')) || [])[1] || lookOf(sector)[0];

// The small badge beside an offer: a discount, something free, or news.
function badgeOf(item) {
  const t = `${item.title || ''} ${item.description || item.body || ''}`;
  if (/%|remise|r[ée]duction|-\s?\d/i.test(t)) return [Tag, 'bg-[#2F6BFF]'];
  if (/offert|gratuit|achet[ée]|cadeau/i.test(t)) return [Gift, 'bg-[#F59E0B]'];
  return [Sparkles, 'bg-[#8B5CF6]'];
}

function OfferSheet({ item, customer = {}, onClose }) {
  const customerId = customer.id;
  const urlMatch = (item.body || '').match(/(https?:\/\/[^\s)]+)/);
  const cta = item.link || (urlMatch ? urlMatch[0] : null);
  return (
    <div role="dialog" aria-modal="true" onClick={onClose}
         className="fixed inset-0 z-50 flex items-end justify-center bg-[#0B1C3F]/50 p-0 sm:items-center sm:p-4">
      <div onClick={(e) => e.stopPropagation()}
           className="max-h-[88vh] w-full max-w-[520px] overflow-y-auto rounded-t-3xl bg-white p-5 shadow-2xl sm:rounded-3xl">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-[19px] font-bold leading-snug text-[#0B1C3F]">{personal(item.title, customer)}</h2>
            {item.valid_until && <p className="mt-0.5 text-[12.5px] text-[#94A3B8]">Valable jusqu’au {fmtDay(item.valid_until)}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Fermer" className="rounded-full p-1.5 text-[#64748B] hover:bg-[#F1F5F9]"><X size={18} /></button>
        </div>
        {item.image_url && <img src={item.image_url} alt="" className="mb-4 w-full rounded-2xl" />}
        {(item.body || item.description) && (
          <p className="whitespace-pre-line text-[14.5px] leading-relaxed text-[#334155]">{personal(item.body || item.description, customer)}</p>
        )}
        {cta && (
          <a href={cta} target="_blank" rel="noreferrer"
             onClick={() => { api.post(`/campaigns/${item.id}/track-click`, null, { params: { customer_id: customerId } }).catch(() => {}); }}
             className="mt-5 flex items-center justify-center gap-2 rounded-2xl bg-[#2F6BFF] px-4 py-3 text-[14px] font-semibold text-white">
            En profiter <ExternalLink size={15} />
          </a>
        )}
      </div>
    </div>
  );
}

function OfferRow({ item, customer, sector, onOpen }) {
  const [broken, setBroken] = useState(false);
  const [Icon, badge] = badgeOf(item);
  const [emoji, tint] = lookOf(sector);
  const text = personal(item.description || item.body, customer).replace(/\s+/g, ' ').trim();
  return (
    <button type="button" onClick={() => onOpen(item)}
            className="flex w-full items-center gap-3 rounded-2xl border border-[#EEF2F7] bg-white p-2.5 text-left shadow-[0_6px_18px_-14px_rgba(15,23,42,.35)] transition hover:border-[#DCE5F2]">
      {item.image_url && !broken
        ? <img src={item.image_url} alt="" onError={() => setBroken(true)} className="h-[76px] w-[76px] shrink-0 rounded-xl object-cover" />
        : <span aria-hidden="true" className={`flex h-[76px] w-[76px] shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${tint} text-[34px]`}>{emoji}</span>}
      <span aria-hidden="true" className={`flex h-8 w-8 shrink-0 items-center justify-center self-start rounded-lg ${badge} mt-1 text-white`}><Icon size={16} /></span>
      <span className="min-w-0 flex-1">
        <span className="line-clamp-2 text-[15.5px] font-bold leading-snug text-[#0B1C3F]">{personal(item.title, customer)}</span>
        {text && text !== personal(item.title, customer) && (
          <span className="mt-0.5 line-clamp-1 text-[13.5px] text-[#475569]">{text}</span>
        )}
        {item.valid_until && <span className="mt-0.5 block whitespace-nowrap text-[12.5px] text-[#94A3B8]">Valable jusqu’au {fmtDay(item.valid_until)}</span>}
      </span>
      <ChevronRight size={20} className="shrink-0 text-[#94A3B8]" />
    </button>
  );
}

const FIRST_OFFERS = 3;

export default function CardOffersPage() {
  const { barcodeId } = useParams();
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [open, setOpen] = useState(null);
  const [all, setAll] = useState(false);
  const [logoBroken, setLogoBroken] = useState(false);
  const [ownerKey, setOwnerKey] = useState(null);

  useEffect(() => {
    // The Wallet tile opens /card/FT-…/offres?k=… (the card's owner key). The
    // card's data answers only to that key since 2026-10-09 (#176), so the
    // key from the link is used — and kept on this phone, then taken out of
    // the address bar. Without it every tile read « Carte introuvable »
    // (Wallet opens Safari, which often had no key stored).
    const bc = String(barcodeId || '').toUpperCase();
    const params = new URLSearchParams(window.location.search);
    const fromLink = params.get('k');
    const key = fromLink || keyOf(bc);
    setOwnerKey(key || null);
    if (fromLink) {
      params.delete('k');
      const q = params.toString();
      window.history.replaceState(null, '', `${window.location.pathname}${q ? `?${q}` : ''}${window.location.hash}`);
    }
    api.get(`/card/${bc}`, key ? { headers: { 'X-Card-Key': key } } : undefined)
      .then((r) => {
        if (fromLink) addMine(bc, fromLink);         // proven by the server's answer
        setData(r.data);
      })
      .catch((e) => setErr(e?.response?.status === 403
        ? 'Ouvrez vos offres depuis votre carte (Wallet, ou le lien reçu par SMS ou e-mail) : elles ne s’affichent que sur votre téléphone.'
        : 'Carte introuvable.'));
  }, [barcodeId]);

  // offers still valid, newest first; the shop's own offer leads
  const feed = useMemo(() => {
    const now = Date.now();
    const seen = new Set();
    const out = [];
    for (const o of data?.offers || []) {
      if (!o.id || seen.has(o.id)) continue;
      if (o.valid_until && Date.parse(o.valid_until) < now) continue;
      seen.add(o.id);
      out.push({ ...o, _ts: o.kind === 'primary' ? 9e15 : Date.parse(o.sent_at || 0) || 0 });
    }
    return out.sort((a, b) => b._ts - a._ts);
  }, [data]);

  const openItem = (item) => {
    setOpen(item);
    if (item.kind === 'campaign' && data?.customer?.id) {
      api.get(`/campaigns/${item.id}/pixel/${data.customer.id}.png`).catch(() => {});
    }
  };

  if (err) {
    return <div className="flex min-h-screen items-center justify-center bg-[#F4F7FC] p-6 text-center text-[14px] text-[#64748B]">{err}</div>;
  }
  if (!data) {
    return <div className="flex min-h-screen items-center justify-center bg-[#F4F7FC]"><Loader2 className="animate-spin text-[#2F6BFF]" /></div>;
  }
  const { customer = {}, tenant = {}, card = {} } = data;
  const threshold = Math.max(1, parseInt(card.reward_threshold, 10) || 10);
  const onCard = Math.min(threshold, cycleVisits(customer));     // THIS card (lib/cardCycle)
  const left = threshold - onCard;
  const pending = rewardsPending(customer);
  const first = (customer.name || '').split(' ')[0];
  // the shop's own name: a card named « Carte fidélité – hfdd » read twice (« Carte fidélité – Carte fidélité – hfdd »)
  const shop = tenant.name || card.card_name || '';
  const reward = card.reward_description || 'Une récompense fidélité';
  const shown = all ? feed : feed.slice(0, FIRST_OFFERS);
  const cardLink = ownerLink(barcodeId, ownerKey);

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#F4F7FC] to-[#EEF3FB] font-['Inter',system-ui,sans-serif]">
      <div className="mx-auto max-w-[560px] px-4 pb-10 pt-5">
        <header className="mb-5 flex items-center gap-3">
          <Link to={cardLink} aria-label="Retour à ma carte" className="-ml-1 rounded-full p-1 text-[#0B1C3F] hover:bg-white/70">
            <ChevronLeft size={28} />
          </Link>
          {card.logo_url && !logoBroken
            ? <img src={card.logo_url} alt="" onError={() => setLogoBroken(true)} className="h-14 w-14 shrink-0 rounded-2xl bg-white object-contain p-1.5 shadow-[0_6px_18px_-10px_rgba(15,23,42,.35)]" />
            : <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-[#2F6BFF] text-[22px] font-bold text-white">{shop.charAt(0)}</span>}
          <div className="min-w-0">
            <p className="truncate text-[12.5px] font-medium uppercase tracking-wide text-[#64748B]">Carte fidélité{shop ? ` – ${shop}` : ''}</p>
            <h1 className="truncate text-[26px] font-extrabold leading-tight tracking-tight text-[#0B1C3F]">Vos offres{first ? `, ${first}` : ''}</h1>
          </div>
        </header>

        <section className="mb-4 overflow-hidden rounded-[28px] bg-gradient-to-br from-[#3B7BFF] via-[#2F6BFF] to-[#1D4FE0] p-5 text-white shadow-[0_22px_44px_-26px_rgba(47,107,255,.95)]">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-1.5 text-[12.5px] font-semibold uppercase tracking-wide text-white/85"><Gift size={16} /> Votre récompense</p>
              <p className="mt-1.5 text-[23px] font-extrabold leading-tight">{reward}</p>
            </div>
            <span aria-hidden="true" className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-white/90 text-[34px] shadow-sm">
              {rewardPic(reward, tenant.sector)}
            </span>
          </div>
          <div className="mt-4 h-3 overflow-hidden rounded-full bg-white/20" role="progressbar"
               aria-valuemin={0} aria-valuemax={threshold} aria-valuenow={onCard} aria-label="Visites sur la carte">
            <div className="h-full rounded-full bg-white/70" style={{ width: `${Math.max(onCard ? 6 : 0, (onCard / threshold) * 100)}%` }} />
          </div>
          <p className="mt-2.5 text-[14.5px] text-white/95">
            {left <= 0
              ? 'Débloquée : présentez votre carte en caisse !'
              : `${onCard} / ${threshold} — encore ${left} visite${left > 1 ? 's' : ''}`}
          </p>
          {pending > 0 && left > 0 && (
            <p className="mt-3 rounded-2xl bg-white/15 px-3 py-2 text-[13.5px] font-semibold">
              🎉 {pending > 1 ? `${pending} récompenses vous attendent` : 'Une récompense vous attend'} en caisse
            </p>
          )}
        </section>

        <section className="rounded-[28px] bg-white/90 p-4 shadow-[0_10px_30px_-22px_rgba(15,23,42,.35)]">
          <div className="mb-3 flex items-center justify-between gap-2 px-1">
            <h2 className="flex items-center gap-2 text-[14px] font-bold uppercase tracking-wide text-[#475569]"><Sparkles size={18} className="text-[#64748B]" /> Offres en cours</h2>
            {feed.length > FIRST_OFFERS && (
              <button type="button" onClick={() => setAll((v) => !v)} className="flex items-center gap-0.5 text-[14px] font-medium text-[#2F6BFF]">
                {all ? 'Voir moins' : `Voir tout (${feed.length})`} <ChevronRight size={16} className={all ? '-rotate-90' : ''} />
              </button>
            )}
          </div>
          {feed.length === 0 ? (
            <p className="rounded-2xl bg-[#F8FAFC] p-6 text-center text-[14px] text-[#64748B]">Pas d’offre en ce moment : on vous prévient dès qu’il y en a une.</p>
          ) : (
            <div className="space-y-3">
              {shown.map((item) => (
                <OfferRow key={item.id} item={item} customer={customer} sector={tenant.sector} onOpen={openItem} />
              ))}
            </div>
          )}
        </section>

        {/* the Wallet tile's owner key goes on to the card (lib/myCards) */}
        <Link to={cardLink} className="mt-6 block text-center text-[13.5px] font-semibold text-[#2F6BFF]">Voir ma carte</Link>
      </div>
      {open && <OfferSheet item={open} customer={customer} onClose={() => setOpen(null)} />}
    </div>
  );
}
