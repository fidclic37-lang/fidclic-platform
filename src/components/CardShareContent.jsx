import React, { useEffect, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { Copy, Check, Share2, Mail, MessageSquare } from 'lucide-react';
import api from '../lib/api';

/* « Parrainage » inside « Ma carte en ligne » (round 4, user 2026-11-26: no
   page opens another page) — the home's « Parrainer un proche » and the old
   /card/{bc}/partager address. Everything the old page did (pages/
   CardSharePage, kept unrouted for a rollback): the QR of the card's PUBLIC
   address — a friend who scans it lands on the signup as this client's
   filleul (card QR ownership: never the friend's card, never the owner key) —
   every app to send the link, the phone's share sheet, copy; the words from
   GET /api/card/{bc}/inviter. In the card's theme (.wcp variables). */

const BRANDS = [
  // [name, background, svg path (24×24), href(url, text)]
  ['WhatsApp', '#25D366', 'M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2Zm5.4 14.1c-.2.6-1.3 1.2-1.8 1.2-.5.1-1 .2-3.3-.7-2.8-1.1-4.6-4-4.7-4.2-.1-.2-1.1-1.5-1.1-2.9s.7-2 1-2.3c.2-.3.5-.3.7-.3h.5c.2 0 .4 0 .6.5l.8 2c.1.2.1.4 0 .5l-.4.6-.4.4c-.1.1-.3.3-.1.6.2.3.8 1.3 1.7 2.1 1.2 1 2.1 1.3 2.4 1.5.3.1.5.1.6-.1l.9-1.1c.2-.3.4-.2.6-.1l1.9.9c.3.1.5.2.5.3.1.2.1.8-.2 1.4Z',
    (u, t) => `https://wa.me/?text=${encodeURIComponent(`${t} ${u}`)}`],
  ['Messenger', '#0866FF', 'M12 2C6.4 2 2 6.1 2 11.6c0 2.9 1.2 5.4 3.1 7.1V22l2.8-1.5c1.2.3 2.5.5 4.1.5 5.6 0 10-4.1 10-9.4S17.6 2 12 2Zm1 12.6-2.6-2.7-5 2.7 5.5-5.8 2.6 2.7 4.9-2.7-5.4 5.8Z',
    (u) => `fb-messenger://share/?link=${encodeURIComponent(u)}`],
  ['Facebook', '#1877F2', 'M14 8h3V4h-3c-2.8 0-4 1.7-4 4.3V10H7v4h3v8h4v-8h3l1-4h-4V8.6c0-.4.3-.6.6-.6Z',
    (u) => `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(u)}`],
  ['X', '#000000', 'M17.8 3h3.1l-6.8 7.7L22 21h-6.2l-4.9-6.3L5.3 21H2.2l7.2-8.3L2 3h6.4l4.4 5.8L17.8 3Zm-1.1 16.2h1.7L7.3 4.7H5.5l11.2 14.5Z',
    (u, t) => `https://x.com/intent/post?text=${encodeURIComponent(t)}&url=${encodeURIComponent(u)}`],
  ['Telegram', '#2AABEE', 'M21.9 4.3 18.7 19c-.2 1-.9 1.3-1.8.8l-4.8-3.6-2.3 2.2c-.3.3-.5.5-1 .5l.3-4.9 8.9-8c.4-.3-.1-.5-.6-.2L6.4 12.6 1.7 11.2c-1-.3-1-1 .2-1.5L20.5 2.5c.9-.3 1.6.2 1.4 1.8Z',
    (u, t) => `https://t.me/share/url?url=${encodeURIComponent(u)}&text=${encodeURIComponent(t)}`],
];

export default function CardShareContent({ barcodeId, qrInk = '#111111' }) {
  const bc = String(barcodeId || '').toUpperCase();
  // the card's PUBLIC address: no owner key, no ?vue=, nothing of this phone
  const url = `${window.location.origin}/card/${encodeURIComponent(bc)}`;
  const [inv, setInv] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let alive = true;
    api.get(`/card/${bc}/inviter`).then(({ data }) => { if (alive) setInv(data || {}); }).catch(() => { if (alive) setInv({}); });
    return () => { alive = false; };
  }, [bc]);

  const shop = inv?.store?.name || inv?.business_name || '';
  const reward = inv?.enabled && inv?.referrer_reward ? inv.referrer_reward : '';
  const text = shop
    ? `Rejoins-moi chez ${shop} : crée ta carte de fidélité${inv?.enabled && inv?.referee_reward ? ` et reçois ${inv.referee_reward}` : ''} !`
    : 'Crée ta carte de fidélité avec mon lien !';
  const copy = async () => {
    try { await navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch (_e) { /* ignore */ }
  };
  const native = async () => {
    try { await navigator.share({ title: shop || 'Ma carte de fidélité', text, url }); } catch (_e) { /* cancelled */ }
  };

  return (
    <div className="share" data-testid="share-view">
      <section className="sheet sec" style={{ textAlign: 'center' }}>
        <h2 className="sh-t" style={{ justifyContent: 'center' }}>
          {inv?.first_name && <span translate="no" className="notranslate">{inv.first_name}, </span>}
          {inv?.first_name ? 'partagez' : 'Partagez'} votre carte{inv?.enabled ? ' et obtenez des récompenses' : ''}
        </h2>
        {reward && (
          <p className="sh-d" data-testid="share-reward">
            Pour chaque ami qui crée sa carte{inv?.minimum_visits > 1 ? ` et vient ${inv.minimum_visits} fois` : ' et vient en boutique'} : <b>{reward}</b> pour vous.
          </p>
        )}
        <div className="qr" data-testid="share-qr">
          <QRCodeSVG value={url} size={220} level="M" includeMargin={false} fgColor={qrInk} bgColor="#ffffff" />
        </div>
        <p className="sh-d">Votre ami scanne ce code avec l’appareil photo de son téléphone.</p>
      </section>

      <section className="sheet sec">
        <div className="apps">
          {BRANDS.map(([name, bg, path, href]) => (
            <a key={name} href={href(url, text)} target="_blank" rel="noopener noreferrer" aria-label={`Partager sur ${name}`}>
              <span className="ap" style={{ background: bg }}>
                <svg viewBox="0 0 24 24" width="24" height="24" fill="#fff" aria-hidden="true"><path d={path} /></svg>
              </span>
              {name}
            </a>
          ))}
          <a href={`sms:?&body=${encodeURIComponent(`${text} ${url}`)}`} aria-label="Partager par SMS">
            <span className="ap" style={{ background: '#34C759' }}><MessageSquare size={22} color="#fff" aria-hidden="true" /></span>
            SMS
          </a>
          <a href={`mailto:?subject=${encodeURIComponent(shop ? `Ma carte ${shop}` : 'Ma carte de fidélité')}&body=${encodeURIComponent(`${text}\n${url}`)}`}
             aria-label="Partager par e-mail">
            <span className="ap" style={{ background: '#8E8E93' }}><Mail size={22} color="#fff" aria-hidden="true" /></span>
            E-mail
          </a>
        </div>
        <div className="copyrow">
          <span translate="no" className="notranslate u" data-testid="share-url">{url}</span>
          <button type="button" onClick={copy} className="solid">
            {copied ? <><Check size={15} aria-hidden="true" /> Copié</> : <><Copy size={15} aria-hidden="true" /> Copier le lien</>}
          </button>
        </div>
        {typeof navigator !== 'undefined' && navigator.share && (
          <button type="button" onClick={native} className="solid wide" style={{ marginTop: 10, minHeight: 48 }}>
            <Share2 size={18} aria-hidden="true" /> Partager…
          </button>
        )}
      </section>
    </div>
  );
}
