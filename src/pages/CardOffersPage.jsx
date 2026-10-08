import React, { useEffect, useMemo, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Gift, Sparkles, ChevronRight, X, ExternalLink, Loader2 } from 'lucide-react';
import api from '../lib/api';
import { ownerLink } from '../lib/myCards';

/**
 * Offres — where « Voir les offres et récompenses » under the Wallet pass
 * lands (iOS 27 featured action, user 2026-10-07: the customer wants the
 * offers, not the whole card page). Only the shop's current offers and the
 * customer's reward progress, in the platform's own look. Reads the same
 * /api/card/{id} the card page reads; opening an offer counts as an open
 * (campaign pixel), its link as a click.
 */
// a campaign written with {first_name} / {prenom} reads with the customer's own
const personal = (text, c = {}) => String(text || '')
  .replace(/\{(first_name|prenom)\}/gi, (c.name || '').split(' ')[0] || '')
  .replace(/\{(name|nom)\}/gi, c.name || '');
const fmtDate = (v) => (v ? new Date(v).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' }) : '');

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
            {item.sent_at && <p className="mt-0.5 text-[12px] text-[#94A3B8]">{fmtDate(item.sent_at)}</p>}
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

export default function CardOffersPage() {
  const { barcodeId } = useParams();
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [open, setOpen] = useState(null);
  const [logoBroken, setLogoBroken] = useState(false);

  useEffect(() => {
    api.get(`/card/${barcodeId}`).then((r) => setData(r.data)).catch(() => setErr('Carte introuvable.'));
  }, [barcodeId]);

  const feed = useMemo(() => {
    const seen = new Set();
    const out = [];
    for (const o of data?.offers || []) {
      if (o.id && !seen.has(o.id)) { seen.add(o.id); out.push({ ...o, _ts: o.kind === 'primary' ? 9e15 : Date.parse(o.sent_at || 0) || 0 }); }
    }
    for (const n of data?.notifications || []) {
      if (n.id && !seen.has(n.id)) {
        seen.add(n.id);
        out.push({ id: n.id, kind: 'campaign', title: n.title, body: n.body || '', image_url: n.image_url, link: n.link,
          sent_at: n.sent_at, _ts: Date.parse(n.sent_at || 0) || 0 });
      }
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
    return <div className="flex min-h-screen items-center justify-center bg-[#F4F7FC] p-6 text-[14px] text-[#64748B]">{err}</div>;
  }
  if (!data) {
    return <div className="flex min-h-screen items-center justify-center bg-[#F4F7FC]"><Loader2 className="animate-spin text-[#2F6BFF]" /></div>;
  }
  const { customer = {}, tenant = {}, card = {} } = data;
  const threshold = Math.max(1, parseInt(card.reward_threshold, 10) || 10);
  const stamps = Math.min(threshold, parseInt(card.stamps_earned, 10) || 0);
  const left = threshold - stamps;
  const first = (customer.name || '').split(' ')[0];
  const shop = card.card_name || tenant.name || '';

  return (
    <div className="min-h-screen bg-[#F4F7FC] font-['Inter',system-ui,sans-serif]">
      <div className="mx-auto max-w-[560px] px-4 pb-10 pt-6">
        <header className="mb-5 flex items-center gap-3">
          {card.logo_url && !logoBroken
            ? <img src={card.logo_url} alt="" onError={() => setLogoBroken(true)} className="h-11 w-11 rounded-xl bg-white object-contain p-1 shadow-sm" />
            : <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#2F6BFF] text-[17px] font-bold text-white">{shop.charAt(0)}</span>}
          <div className="min-w-0">
            <p className="truncate text-[12px] font-semibold uppercase tracking-wide text-[#64748B]">{shop}</p>
            <h1 className="text-[20px] font-bold leading-tight text-[#0B1C3F]">Vos offres{first ? `, ${first}` : ''}</h1>
          </div>
        </header>

        <section className="mb-5 rounded-3xl bg-gradient-to-br from-[#2F6BFF] to-[#1E4FD8] p-5 text-white shadow-[0_18px_40px_-24px_rgba(47,107,255,.9)]">
          <p className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-white/80"><Gift size={14} /> Votre récompense</p>
          <p className="mt-1 text-[17px] font-bold">{card.reward_description || 'Une récompense fidélité'}</p>
          <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-white/25">
            <div className="h-full rounded-full bg-white" style={{ width: `${(stamps / threshold) * 100}%` }} />
          </div>
          <p className="mt-2 text-[13px] text-white/90">
            {left <= 0 ? 'Débloquée : présentez votre carte en caisse !' : `${stamps} / ${threshold} — encore ${left} visite${left > 1 ? 's' : ''}`}
          </p>
        </section>

        <h2 className="mb-2 flex items-center gap-1.5 text-[13px] font-bold uppercase tracking-wide text-[#64748B]"><Sparkles size={14} /> Offres en cours</h2>
        {feed.length === 0 ? (
          <p className="rounded-2xl bg-white p-6 text-center text-[14px] text-[#64748B] shadow-sm">Pas d’offre en ce moment : on vous prévient dès qu’il y en a une.</p>
        ) : (
          <div className="space-y-2.5">
            {feed.map((item) => (
              <button key={item.id} type="button" onClick={() => openItem(item)}
                      className="flex w-full items-center gap-3 rounded-2xl bg-white p-3 text-left shadow-sm transition hover:shadow-md">
                {item.image_url
                  ? <img src={item.image_url} alt="" className="h-16 w-16 shrink-0 rounded-xl object-cover" />
                  : <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><Gift size={22} /></span>}
                <span className="min-w-0 flex-1">
                  <span className="block text-[15px] font-semibold leading-snug text-[#0B1C3F]">{personal(item.title, customer)}</span>
                  {(item.description || item.body) && <span className="mt-0.5 line-clamp-2 block text-[13px] text-[#64748B]">{personal(item.description || item.body, customer)}</span>}
                  {item.kind === 'campaign' && item.sent_at && <span className="mt-1 block text-[11.5px] text-[#94A3B8]">{fmtDate(item.sent_at)}</span>}
                </span>
                <ChevronRight size={18} className="shrink-0 text-[#94A3B8]" />
              </button>
            ))}
          </div>
        )}

        {/* the Wallet tile's owner key goes on to the card (lib/myCards) */}
        <Link to={ownerLink(barcodeId, new URLSearchParams(window.location.search).get('k'))} className="mt-6 block text-center text-[13px] font-semibold text-[#2F6BFF]">Voir ma carte complète</Link>
      </div>
      {open && <OfferSheet item={open} customer={customer} onClose={() => setOpen(null)} />}
    </div>
  );
}
