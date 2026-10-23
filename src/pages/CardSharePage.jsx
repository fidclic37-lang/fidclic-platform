import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { QRCodeSVG } from 'qrcode.react';
import { Copy, Check, Share2, Mail, MessageSquare } from 'lucide-react';
import api from '../lib/api';

/* « Partagez la carte » — opened from the back of the Wallet card (user,
   2026-10-23: the customer could not share their own card). The QR is the
   card's public address: a friend who scans it lands on the signup as this
   client's filleul (card QR ownership: never the friend's card, never the
   owner key). Every app to send the link, the phone's own share sheet, copy. */

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

export default function CardSharePage() {
  const { barcodeId } = useParams();
  const bc = String(barcodeId || '').toUpperCase();
  const url = `${window.location.origin}/card/${bc}`;
  const [inv, setInv] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api.get(`/card/${bc}/inviter`).then(({ data }) => setInv(data)).catch(() => setInv({}));
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
    <div className="min-h-screen bg-[#F6F7F9] px-4 py-8">
      <div className="mx-auto max-w-[440px] text-center">
        <h1 className="text-[26px] font-extrabold leading-tight text-[#0B1C3F]">
          {inv?.first_name && <span translate="no" className="notranslate">{inv.first_name}, </span>}
          {inv?.first_name ? 'partagez' : 'Partagez'} votre carte{inv?.enabled ? ' et obtenez des récompenses' : ''}
        </h1>
        {reward && (
          <p className="mt-2 text-[15px] text-[#475569]">
            Pour chaque ami qui crée sa carte{inv?.minimum_visits > 1 ? ` et vient ${inv.minimum_visits} fois` : ' et vient en boutique'} : <b className="text-[#0B1C3F]">{reward}</b> pour vous.
          </p>
        )}
        {shop && <p translate="no" className="notranslate mt-1 text-[13px] font-semibold text-[#64748B]">{shop}</p>}

        <div className="mx-auto mt-6 w-fit rounded-3xl bg-white p-5 shadow-[0_18px_40px_-24px_rgba(11,28,63,.45)]" data-testid="share-qr">
          <QRCodeSVG value={url} size={240} level="M" includeMargin={false} />
        </div>
        <p className="mt-3 text-[13px] text-[#64748B]">Votre ami scanne ce code avec l’appareil photo de son téléphone.</p>

        <div className="mt-6 grid grid-cols-4 gap-3">
          {BRANDS.map(([name, bg, path, href]) => (
            <a key={name} href={href(url, text)} target="_blank" rel="noreferrer" aria-label={`Partager sur ${name}`}
               className="flex flex-col items-center gap-1.5 text-[11.5px] font-medium text-[#334155]">
              <span className="flex h-14 w-14 items-center justify-center rounded-full" style={{ background: bg }}>
                <svg viewBox="0 0 24 24" width="26" height="26" fill="#fff" aria-hidden="true"><path d={path} /></svg>
              </span>
              {name}
            </a>
          ))}
          <a href={`sms:?&body=${encodeURIComponent(`${text} ${url}`)}`} aria-label="Partager par SMS"
             className="flex flex-col items-center gap-1.5 text-[11.5px] font-medium text-[#334155]">
            <span className="flex h-14 w-14 items-center justify-center rounded-full bg-[#34C759]"><MessageSquare size={24} color="#fff" /></span>
            SMS
          </a>
          <a href={`mailto:?subject=${encodeURIComponent(shop ? `Ma carte ${shop}` : 'Ma carte de fidélité')}&body=${encodeURIComponent(`${text}\n${url}`)}`}
             aria-label="Partager par e-mail" className="flex flex-col items-center gap-1.5 text-[11.5px] font-medium text-[#334155]">
            <span className="flex h-14 w-14 items-center justify-center rounded-full bg-[#8E8E93]"><Mail size={24} color="#fff" /></span>
            E-mail
          </a>
        </div>

        <div className="mt-6 flex items-center gap-2 rounded-2xl border border-[#E2E8F0] bg-white p-2 pl-4">
          <span translate="no" className="notranslate min-w-0 flex-1 truncate text-left text-[13.5px] text-[#334155]">{url}</span>
          <button type="button" onClick={copy}
                  className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-xl bg-[#0B1C3F] px-4 text-[13px] font-semibold text-white">
            {copied ? <><Check size={15} /> Copié</> : <><Copy size={15} /> Copier le lien</>}
          </button>
        </div>
        {typeof navigator !== 'undefined' && navigator.share && (
          <button type="button" onClick={native}
                  className="mt-3 inline-flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-[#1463FF] text-[15px] font-semibold text-white">
            <Share2 size={18} /> Partager…
          </button>
        )}
      </div>
    </div>
  );
}
