import React, { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import api from '../lib/api';
import { addMine, keyOf, ownerLink } from '../lib/myCards';
import { here as walletPlace, safariLink } from '../lib/iosSafari';
import { addPageHref, passHref, waitForAppleAdd } from '../lib/walletOpen';
import { ADDED_HINT } from '../components/WalletButtons';

/**
 * /card/<id>/ajouter?k=<key> — « Ajouter à Apple Wallet », in one go (user,
 * 2026-11-25: from Chrome it was the old card page, a tap, « Ouvrir dans
 * Safari », another tap…). Chrome and the apps' own browsers send the client
 * here, in Safari: the page checks the key, then shows the Wallet sheet by
 * itself. The key is the one in the link, held by the page — never only the
 * phone's memory (Soan, Royal Trim Liberté, 2026-11-25: gone by the tap, five
 * « Ajouter » refused). Once the iPhone has the card: « Carte ajoutée », and
 * the card's « Bienvenue » banner opens it (no web page may open Wallet).
 */
const CARD = /^FT-[A-Z0-9]+$/;

export default function AppleWalletAddPage() {
  const params = useParams();
  const bc = String(params.barcodeId || '').trim().toUpperCase();
  // the key, only READ while rendering: React may throw a first render away
  // and render again (CI, 2026-11-25: the address bar already emptied, the
  // page said « lien invalide »). It leaves the address bar after the render.
  const [key] = useState(() => {
    try {
      return (new URLSearchParams(window.location.search).get('k') || '').trim() || keyOf(bc) || '';
    } catch (_e) { return ''; }
  });
  useEffect(() => {
    try {
      const q = new URLSearchParams(window.location.search);
      if (!q.has('k')) return;
      q.delete('k');
      const rest = q.toString();
      window.history.replaceState(window.history.state, '', `${window.location.pathname}${rest ? `?${rest}` : ''}`);
    } catch (_e) { /* the key stays in the bar: harmless */ }
  }, []);
  const place = walletPlace();
  const valid = CARD.test(bc) && Boolean(key);
  // checking · ready · added · bad
  const [view, setView] = useState(valid ? 'checking' : 'bad');
  const waiting = useRef(false);
  const gone = useRef(false);
  useEffect(() => { gone.current = false; return () => { gone.current = true; }; }, []);   // mounted again: alive again

  const pass = valid ? passHref(bc, key) : null;

  const waitForWallet = () => {
    if (waiting.current) return;
    waiting.current = true;
    waitForAppleAdd({
      ask: () => api.get(`/card/${bc}/apple-wallet/added`, { params: { k: key } }).then((r) => r.data?.added === true),
      hidden: () => document.hidden,
      cancelled: () => gone.current,
    }).then((added) => {
      waiting.current = false;
      if (added && !gone.current) setView('added');
    });
  };
  const addNow = () => {
    if (!pass) return;
    window.location.href = pass;          // Safari: the Wallet sheet
    waitForWallet();
  };

  useEffect(() => {
    if (!valid) return undefined;
    let alive = true;
    // the key is checked before anything opens: a wrong link says so in a
    // sentence, never Safari's raw error page
    api.get(`/card/${bc}/apple-wallet/added`, { params: { k: key } })
      .then(() => {
        if (!alive) return;
        addMine(bc, key);                  // this phone holds the card
        setView('ready');
        if (place === 'safari') addNow();
      })
      .catch((e) => {
        if (!alive) return;
        const s = e?.response?.status;
        setView(s === 403 || s === 404 || s === 401 ? 'bad' : 'ready');
      });
    return () => { alive = false; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const pill = 'inline-flex h-14 w-full items-center justify-center gap-2.5 rounded-2xl text-[16px] font-semibold transition hover:opacity-90';
  const appleButton = (href, onClick) => (
    <a href={href} onClick={onClick} className={`${pill} bg-black text-white shadow-[0_14px_30px_-14px_rgba(11,28,63,.55)]`}>
      <svg width="24" height="19" viewBox="0 0 24 20" aria-hidden="true">
        <rect x="1" y="1" width="22" height="18" rx="3" fill="#fff" />
        <rect x="1" y="4" width="22" height="4" fill="#F59E0B" /><rect x="1" y="8" width="22" height="4" fill="#22C55E" />
        <rect x="1" y="12" width="22" height="7" rx="2" fill="#3B82F6" />
      </svg>
      Ajouter à Apple Wallet
    </a>
  );
  const myCard = valid ? (
    <Link to={ownerLink(bc, key)} className="mt-3 inline-block text-[14px] font-semibold text-[#1D4ED8]">Voir ma carte</Link>
  ) : null;

  let body;
  if (view === 'bad') {
    body = (
      <>
        <p className="text-[16px] font-semibold text-[#171412]">Ce lien ne permet pas d'ajouter la carte.</p>
        <p className="mt-2 text-[14px] leading-relaxed text-[#57534E]">
          Ouvrez votre carte depuis le lien reçu à votre inscription, ou demandez-la au commerce.
        </p>
      </>
    );
  } else if (view === 'checking') {
    body = <div className="mx-auto h-14 w-full animate-pulse rounded-2xl bg-[#E8EDF5]" aria-label="Chargement" />;
  } else if (view === 'added') {
    body = (
      <div data-testid="apple-wallet-added" role="status">
        <p className="text-[17px] font-semibold text-[#15803D]">✓ Carte ajoutée à Apple Wallet</p>
        <p className="mt-2 text-[14px] leading-relaxed text-[#334155]">{ADDED_HINT}</p>
        {myCard}
      </div>
    );
  } else if (place === 'safari') {
    body = (
      <>
        <p className="mb-4 text-[14px] leading-relaxed text-[#57534E]">Touchez « Ajouter » en haut à droite de votre carte.</p>
        {appleButton(pass, (e) => { e.preventDefault(); addNow(); })}
        {myCard}
      </>
    );
  } else if (place === 'other') {
    body = (
      <>
        <p className="mb-4 text-[14px] leading-relaxed text-[#57534E]">Votre carte s'ajoute depuis Safari.</p>
        {appleButton(safariLink(addPageHref(window.location.origin, bc, key)))}
        {myCard}
      </>
    );
  } else {
    body = (
      <>
        <p className="text-[14px] leading-relaxed text-[#57534E]">Apple Wallet s'ouvre sur un iPhone.</p>
        {myCard}
      </>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#FAFAF8] px-4">
      <div className="w-full max-w-sm rounded-2xl border border-[#E9E5E0] bg-white p-7 text-center">
        <h1 className="mb-4 text-[20px] font-bold text-[#171412]">Votre carte dans Apple Wallet</h1>
        {body}
      </div>
    </div>
  );
}
