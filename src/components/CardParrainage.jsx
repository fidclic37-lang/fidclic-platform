import React, { useEffect, useState } from 'react';
import { Users, Gift, Stamp, Star, Check, Clock, Link2, ChevronRight } from 'lucide-react';
import api from '../lib/api';
import { amountText, meWhen, friendWhen, earnedStat, friendLine, showRewards, statusNote } from '../lib/parrainage';
import './CardParrainage.css';

/* « Mes parrainages » on « Ma carte en ligne » (user, 2026-11-26), in the
   FidClic logo colours (blue, yellow, white) whatever the card's theme:
     ParrainageFull  the Parrainage view (home « Parrainer un proche »), above
                     the QR and the share apps of CardShareContent
     ParrainageMini  the Récompenses tab (the Wallet's rewards button), a
                     summary that opens the Parrainage view
   Data: GET /api/card/{bc}/parrainages — what the shop gives each side and
   every friend this card invited, « Récompensé » / « En attente » exactly as
   the referral rows say. */

export function useParrainages(barcodeId) {
  const bc = String(barcodeId || '').toUpperCase();
  const [p, setP] = useState(null);
  useEffect(() => {
    if (!bc) return undefined;
    let alive = true;
    api.get(`/card/${encodeURIComponent(bc)}/parrainages`)
      .then(({ data }) => { if (alive) setP(data || {}); })
      .catch(() => { if (alive) setP({ failed: true }); });
    return () => { alive = false; };
  }, [bc]);
  return p;
}

const KIND_ICON = { stamps: Stamp, points: Star, offer: Gift };

function GiftArt() {
  return (
    <svg className="fcp-art" viewBox="0 0 132 118" aria-hidden="true" focusable="false">
      <ellipse cx="70" cy="110" rx="58" ry="7" fill="#DCE6F8" />
      <rect x="14" y="44" width="62" height="60" rx="8" fill="#fff" stroke="#C9D8F2" />
      <rect x="10" y="34" width="70" height="16" rx="5" fill="#fff" stroke="#C9D8F2" />
      <rect x="38" y="34" width="14" height="70" fill="#1450B8" />
      <path d="M45 34c-10-18-30-16-26-4 2 6 14 5 26 4Zm0 0c10-18 30-16 26-4-2 6-14 5-26 4Z" fill="#1450B8" />
      <rect x="80" y="66" width="42" height="40" rx="7" fill="#fff" stroke="#C9D8F2" />
      <rect x="77" y="59" width="48" height="12" rx="4" fill="#fff" stroke="#C9D8F2" />
      <rect x="96" y="59" width="10" height="47" fill="#F8B008" />
      <path d="M101 59c-7-12-21-11-18-3 1.5 4 10 3.5 18 3Zm0 0c7-12 21-11 18-3-1.5 4-10 3.5-18 3Z" fill="#F8B008" />
      <g transform="rotate(-14 66 60)">
        <rect x="56" y="52" width="22" height="28" rx="5" fill="#F8B008" />
        <circle cx="67" cy="58" r="2.4" fill="#fff" />
        <text x="67" y="74" textAnchor="middle" fontSize="12" fontWeight="800" fill="#0B2A66" fontFamily="system-ui">%</text>
      </g>
      <path d="M112 18l4-9M120 26l9-4M106 14l-1-8" stroke="#1450B8" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function ParrainageFull({ data: p, onInvite }) {
  if (!p || p.failed) return null;
  const rewards = showRewards(p);
  const earned = earnedStat(p);
  const EarnIcon = KIND_ICON[p.me?.kind] || Gift;
  const friends = Array.isArray(p.friends) ? p.friends : [];
  return (
    <div className="fcp" data-testid="parrainage">
      <section className="fcp-card fcp-hero" aria-labelledby="fcp-h">
        <span className="fcp-pill"><Users size={15} aria-hidden="true" /><Gift size={15} aria-hidden="true" />Parrainage</span>
        <h2 id="fcp-h">Le plaisir se partage.<b>Les récompenses aussi.</b></h2>
        <p>
          {rewards
            ? 'Invitez un ami à rejoindre notre programme de fidélité et gagnez tous les deux une récompense.'
            : 'Invitez un ami à rejoindre notre programme de fidélité.'}
        </p>
        <GiftArt />
      </section>

      {rewards && (
        <div className="fcp-sides" data-testid="parrainage-rewards">
          <div className="fcp-side">
            <span className="fcp-ico"><Users size={20} aria-hidden="true" /></span>
            <div>
              <small>Vous gagnez</small>
              <strong data-testid="parrainage-me">{amountText(p.me) || '—'}</strong>
              {p.me?.label && <em>{meWhen(p)}</em>}
            </div>
          </div>
          <span className="fcp-sep" aria-hidden="true" />
          <div className="fcp-side">
            <span className="fcp-ico"><Gift size={20} aria-hidden="true" /></span>
            <div>
              <small>Votre ami gagne</small>
              <strong data-testid="parrainage-friend">{amountText(p.friend) || '—'}</strong>
              {p.friend?.label && <em>{friendWhen(p)}</em>}
            </div>
          </div>
        </div>
      )}

      <section className="fcp-card fcp-mine" aria-labelledby="fcp-mine-h">
        <h3 id="fcp-mine-h"><Users size={19} aria-hidden="true" />Mes parrainages</h3>
        <div className="fcp-stats">
          <div className="fcp-stat a">
            <Users size={22} aria-hidden="true" />
            <div><b data-testid="parrainage-invited">{p.invited || 0}</b><span>{(p.invited || 0) > 1 ? 'Amis invités' : 'Ami invité'}</span></div>
          </div>
          <div className={`fcp-stat b${earned.mixed ? ' mixed' : ''}`}>
            <EarnIcon size={22} aria-hidden="true" />
            <div><b data-testid="parrainage-earned">{earned.value}</b><span>{earned.label}</span></div>
          </div>
        </div>

        <h4>Mes invitations</h4>
        <div className="fcp-list" data-testid="parrainage-list">
          {friends.length === 0 && (
            <p className="fcp-empty">Aucun ami invité pour l’instant. Partagez votre carte : vos invitations apparaîtront ici.</p>
          )}
          {friends.map((f, i) => {
            const done = f.status === 'rewarded';
            const name = f.first_name || 'Un ami';
            return (
              <div key={i} className={`fcp-row${done ? '' : ' wait'}`} data-testid="parrainage-row" data-status={f.status}>
                <span className="fcp-av" aria-hidden="true">{(f.first_name || '?').slice(0, 1).toUpperCase()}</span>
                <div className="fcp-who">
                  <b translate="no" className="notranslate">{name}</b>
                  <span>{friendLine(f)}</span>
                </div>
                {done
                  ? <span className="fcp-tag ok"><Check size={13} strokeWidth={3} aria-hidden="true" />Récompensé</span>
                  : <span className="fcp-tag wait"><Clock size={13} strokeWidth={2.4} aria-hidden="true" />En attente</span>}
              </div>
            );
          })}
          {p.more > 0 && <p className="fcp-empty">… et {p.more} autre{p.more > 1 ? 's' : ''} invitation{p.more > 1 ? 's' : ''}.</p>}
        </div>

        <button type="button" className="fcp-cta" onClick={onInvite} data-testid="parrainage-invite">
          <Link2 size={18} aria-hidden="true" />Inviter un ami
        </button>
        {rewards && friends.length > 0 && <p className="fcp-how">{statusNote(p)}</p>}
      </section>
    </div>
  );
}

export function ParrainageMini({ data: p, onOpen }) {
  if (!p || p.failed) return null;
  if (!p.enabled && !(p.invited > 0)) return null;     // no programme and no history: nothing to say
  const earned = earnedStat(p);
  return (
    <section className="fcp fcp-card fcp-mini" data-testid="parrainage-mini">
      <button type="button" className="fcp-mini-top" onClick={onOpen}>
        <span className="fcp-ico"><Users size={20} aria-hidden="true" /></span>
        <span className="fcp-mini-t">
          <b>Parrainage</b>
          {showRewards(p) && p.me?.label
            ? <span>Vous : <strong>{amountText(p.me)}</strong> {meWhen(p)}</span>
            : <span>Vos invitations et leur statut</span>}
        </span>
        <span className="fcp-go">Voir <ChevronRight size={15} aria-hidden="true" /></span>
      </button>
      <div className="fcp-mini-stats">
        <span className="a"><b>{p.invited || 0}</b>{(p.invited || 0) > 1 ? 'Amis invités' : 'Ami invité'}</span>
        <span className={`b${earned.mixed ? ' mixed' : ''}`}><b>{earned.value}</b>{earned.label}</span>
        <span className="c"><b>{p.pending || 0}</b>En attente</span>
      </div>
    </section>
  );
}
