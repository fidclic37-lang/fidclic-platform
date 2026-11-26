import React, { useMemo, useState } from 'react';
import { Gift, Sparkles, ChevronRight, X, ExternalLink, Tag, Clock, Flame } from 'lucide-react';
import api from '../lib/api';
import { cycleVisits, rewardsPending } from '../lib/cardCycle';
import { liveOffers, personal, rewardPic, badgeKind, sectorLook } from '../lib/cardOffers';
import { pointsBox } from '../lib/cardPage';
import { ParrainageMini, useParrainages } from './CardParrainage';

/**
 * « Vos offres » inside « Ma carte en ligne » — the bottom « Récompenses » tab
 * (round 4, user 2026-11-26: « koi bhi page naya page open na kare »). What
 * the old page (pages/CardOffersPage, kept unrouted for a rollback) showed:
 * the défis running and won, the reward card with its meter, the offers live
 * for THIS customer with their photos, an offer's detail sheet. Drawn in the
 * card's own theme (the .wcp variables of lib/cardTheme).
 *
 * It reads the card page's own GET /api/card/{bc} (`data`) — never fetches
 * the card again. Opening a campaign counts as an open (its pixel), its link
 * as a click (track-click), as on the old page.
 */
const fmtDay = (v) => (v ? new Date(v).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', timeZone: 'Europe/Paris' }) : '');
const BADGE = { discount: Tag, gift: Gift, news: Sparkles };
const FIRST_OFFERS = 3;

function OfferSheet({ item, who, onClose }) {
  const urlMatch = (item.body || '').match(/(https?:\/\/[^\s)]+)/);
  const cta = item.link || (urlMatch ? urlMatch[0] : null);
  const safeCta = cta && /^https?:\/\//i.test(cta) ? cta : null;
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="wcp-offer-title" className="wcp-sheet-back" onClick={onClose} data-testid="offer-sheet">
      <div className="wcp-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="sh">
          <div style={{ minWidth: 0 }}>
            <h2 id="wcp-offer-title">{personal(item.title, who)}</h2>
            {item.terms && <p className="terms">{item.terms}</p>}
            {item.valid_until && <p className="until">{item.valid_from ? `À partir du ${fmtDay(item.valid_from)} · ` : ''}Valable jusqu’au {fmtDay(item.valid_until)}</p>}
          </div>
          <button type="button" className="x" onClick={onClose} aria-label="Fermer"><X size={18} aria-hidden="true" /></button>
        </div>
        {item.image_url && <img src={item.image_url} alt="" className="pic" />}
        {item.details && <p className="txt">{item.details}</p>}
        {(item.body || item.description) && <p className="txt">{personal(item.body || item.description, who)}</p>}
        {safeCta && (
          <a href={safeCta} target="_blank" rel="noopener noreferrer" className="solid wide" style={{ marginTop: 16, minHeight: 48 }}
             onClick={() => { api.post(`/campaigns/${item.id}/track-click`, null, { params: { customer_id: who.id } }).catch(() => {}); }}>
            En profiter <ExternalLink size={15} aria-hidden="true" />
          </a>
        )}
      </div>
    </div>
  );
}

function OfferRow({ item, who, sector, onOpen }) {
  const [broken, setBroken] = useState(false);
  const Icon = BADGE[badgeKind(item)];
  const [emoji, look] = sectorLook(sector);
  const title = personal(item.title, who);
  const text = personal(item.description || item.body, who).replace(/\s+/g, ' ').trim();
  return (
    <button type="button" className="offer" onClick={() => onOpen(item)} data-testid="offer-row">
      {item.image_url && !broken
        ? <img src={item.image_url} alt="" onError={() => setBroken(true)} className="ph" />
        : <span aria-hidden="true" className={`ph pic-${look}`}>{emoji}</span>}
      <span aria-hidden="true" className={`bd ${badgeKind(item)}`}><Icon size={15} /></span>
      <span className="tx">
        <span className="t">{title}</span>
        {text && text !== title && <span className="d">{text}</span>}
        {item.hours_label && <span className="h"><Clock size={12} aria-hidden="true" /> {item.hours_label}</span>}
        {item.valid_until && <span className="u">{item.valid_from ? `À partir du ${fmtDay(item.valid_from)}` : `Valable jusqu’au ${fmtDay(item.valid_until)}`}</span>}
      </span>
      <ChevronRight size={20} className="go" aria-hidden="true" />
    </button>
  );
}

export default function CardOffersContent({ data, barcodeId, onParrainage }) {
  const [open, setOpen] = useState(null);
  const [all, setAll] = useState(false);
  // offers still valid, newest first; the shop's own offer leads — the list
  // the home tile counts in « Mes offres exclusives » (lib/cardOffers)
  const feed = useMemo(() => liveOffers(data), [data]);
  const { customer = {}, tenant = {}, card = {} } = data || {};
  const pending = rewardsPending(customer);
  const box = pointsBox(card, customer);           // the same meter as Accueil, in the programme's words
  const reward = card.reward_description || 'Une récompense fidélité';
  const threshold = Math.max(1, parseInt(card.reward_threshold, 10) || 10);
  // the customer as the variables read them (lib/cardOffers personal)
  const who = { ...customer, _shop: tenant.name || card.card_name || '', _reward: card.reward_description,
    _missing: Math.max(0, threshold - Math.min(threshold, cycleVisits(customer))) };
  const shown = all ? feed : feed.slice(0, FIRST_OFFERS);
  const openItem = (item) => {
    setOpen(item);
    if (item.kind === 'campaign' && customer.id) {
      api.get(`/campaigns/${item.id}/pixel/${customer.id}.png`).catch(() => {});
    }
  };
  const defis = data?.defis || {};
  // « Mes parrainages » in short (the Wallet's rewards button lands here, 2026-11-26)
  const parr = useParrainages(onParrainage ? (barcodeId || customer.barcode_id) : '');

  return (
    <>
      {/* « Défi en cours » (Campagnes › Défi): the soonest end first, then what was won */}
      {(defis.running || []).map((x) => (
        <section key={x.id} className="defi" data-testid="defi-running">
          <p className="k" style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 6 }}><Flame size={16} aria-hidden="true" /> Défi en cours</p>
          <p className="t">{x.title}</p>
          <p className="d">Faites {x.target} visite{x.target > 1 ? 's' : ''}{x.end_date ? ` avant le ${fmtDay(x.end_date)}` : ''}{x.count_mode === 'per_day' ? ' (une par jour)' : ''}</p>
          <div className="bar" role="progressbar" aria-label="Progression du défi" aria-valuemin={0} aria-valuemax={x.target} aria-valuenow={Math.min(x.progress || 0, x.target)}>
            <i style={{ width: `${Math.min(100, ((x.progress || 0) / Math.max(1, x.target)) * 100)}%` }} />
          </div>
          <p className="d num">{Math.min(x.progress || 0, x.target)} / {x.target}{x.days_left != null ? ` · ${x.days_left <= 1 ? 'Dernier jour' : `encore ${x.days_left} jours`}` : ''}</p>
          {x.reward && <p className="d" style={{ fontWeight: 700, opacity: 1 }}>🎁 {x.reward}</p>}
        </section>
      ))}
      {(defis.won || []).map((w) => (
        <section key={w.id} className="defi won" data-testid="defi-won">
          <p className="k" style={{ margin: 0 }}>{w.kind === 'parrainage' ? '🎁 Parrainage' : '🏆 Défi réussi'}</p>
          <p className="t">{w.reward}</p>
          <p className="d">{w.kind === 'parrainage' ? 'Votre récompense de parrainage' : `« ${w.title} »`} — présentez votre carte en caisse{w.expires_at ? `, avant le ${fmtDay(w.expires_at)}` : ''}.</p>
        </section>
      ))}

      <section className="sheet reward" data-testid="offers-reward" aria-labelledby="wcp-reward">
        <div className="rh">
          <div style={{ minWidth: 0, flex: 1 }}>
            <p className="k" style={{ margin: 0 }}><Gift size={15} aria-hidden="true" /> Votre récompense</p>
            <p className="t" id="wcp-reward">{reward}</p>
          </div>
          <span aria-hidden="true" className="pic">{rewardPic(reward, tenant.sector)}</span>
        </div>
        {box.progress != null && (
          <div className="bar" role="progressbar" aria-label="Progression vers la récompense"
               aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(box.progress * 100)}>
            <i style={{ width: `${Math.max(box.progress > 0 ? 4 : 0, box.progress * 100)}%` }} />
          </div>
        )}
        <p className="m num">{box.scale || box.message}</p>
        {pending > 0 && (
          <p className="pend" data-testid="offers-pending">🎉 {pending > 1 ? `${pending} récompenses vous attendent` : 'Une récompense vous attend'} en caisse</p>
        )}
      </section>

      {onParrainage && <ParrainageMini data={parr} onOpen={onParrainage} />}

      <section className="sheet offers" id="wcp-offres" aria-labelledby="wcp-offers-h" data-testid="offers-list">
        <div className="ah">
          <h2 id="wcp-offers-h"><Sparkles size={18} aria-hidden="true" /> Offres en cours</h2>
          {feed.length > FIRST_OFFERS && (
            <button type="button" className="link" onClick={() => setAll((v) => !v)}>
              {all ? 'Voir moins' : `Voir tout (${feed.length})`} <ChevronRight size={16} aria-hidden="true" style={all ? { transform: 'rotate(-90deg)' } : undefined} />
            </button>
          )}
        </div>
        {feed.length === 0 ? (
          <p className="calm" data-testid="offers-empty">Pas d’offre en ce moment : on vous prévient dès qu’il y en a une.</p>
        ) : (
          <div className="olist">
            {shown.map((item) => <OfferRow key={item.id} item={item} who={who} sector={tenant.sector} onOpen={openItem} />)}
          </div>
        )}
      </section>
      {open && <OfferSheet item={open} who={who} onClose={() => setOpen(null)} />}
    </>
  );
}
