import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { authAPI } from '../lib/api';

/**
 * SocialAuthButtons — "Continuer avec Google" / "Continuer avec Apple",
 * drawn by us (white pill, brand glyph) so they match the login mockup.
 *
 * Google: Google's ID-token flow only works through Google's own rendered
 * button, so a custom button uses the OAuth2 *token client* instead
 * (google.accounts.oauth2.initTokenClient). It opens Google's account
 * chooser in a popup and hands us an access token; the backend checks with
 * Google that the token was issued for OUR client id and reads the profile.
 * Apple: AppleID.auth.signIn() works from any button (popup mode).
 *
 * The public client IDs come from /api/auth/oauth/config. A provider that
 * isn't configured yet shows its button disabled with a tooltip instead of
 * silently doing nothing — that is what "not configured" looks like, so it
 * can't be mistaken for a broken button.
 */
const GIS_SRC = 'https://accounts.google.com/gsi/client';
const APPLE_SRC = 'https://appleid.cdn-apple.com/appleauth/static/jsapi/appleid/1/fr_FR/appleid.auth.js';

function loadScript(src) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) return resolve();
    const s = document.createElement('script');
    s.src = src; s.async = true; s.defer = true;
    s.onload = resolve; s.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(s);
  });
}

export function routeAfterAuth(navigate, session) {
  if (session?.onboarding_status === 'company') return navigate('/onboarding/entreprise');
  if (session?.role === 'super_admin') return navigate('/admin');
  if (session?.role === 'commercial') return navigate('/admin/crm');
  if (session?.role === 'staff') return navigate('/dashboard/scan');
  if (session?.role === 'business_owner') return navigate('/modules');
  if (session?.role === 'comptable') return navigate('/cabinet');
  // Paramètres › Préférences › Page par défaut.
  return navigate(session?.default_page || '/dashboard');
}

const GoogleGlyph = () => (
  <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
    <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.5l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.3l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z"/>
    <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.6 5.9c4.4-4.1 7-10.1 7-17.6z"/>
    <path fill="#FBBC05" d="M10.5 28.6A14.5 14.5 0 0 1 9.5 24c0-1.6.3-3.1.8-4.6l-7.9-6.1A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.7l7.9-6.1z"/>
    <path fill="#34A853" d="M24 48c6.3 0 11.7-2.1 15.6-5.7l-7.6-5.9c-2.1 1.4-4.8 2.3-8 2.3-6.3 0-11.6-4.1-13.5-9.9l-7.9 6.1C6.5 42.6 14.6 48 24 48z"/>
  </svg>
);

const AppleGlyph = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="#000" aria-hidden="true">
    <path d="M16.365 1.43c0 1.14-.42 2.08-1.25 2.93-1 1.04-2.2 1.62-3.44 1.52-.16-1.11.34-2.28 1.17-3.12.86-.9 2.32-1.55 3.52-1.33zM20.9 17.07c-.57 1.3-.84 1.88-1.57 3.03-1.02 1.6-2.45 3.6-4.23 3.61-1.58.02-1.99-1.04-4.13-1.02-2.15.01-2.6 1.04-4.18 1.02-1.78-.02-3.14-1.82-4.16-3.42C.8 16.6-.03 12.05 1.63 9.11c1.07-1.9 2.98-3.1 4.8-3.1 1.85 0 3.01 1.03 4.54 1.03 1.49 0 2.4-1.03 4.55-1.03 1.62 0 3.33.88 4.55 2.4-4 2.2-3.35 7.9.83 8.66z"/>
  </svg>
);

const Btn = ({ onClick, disabled, title, children }) => (
  <button type="button" onClick={onClick} disabled={disabled} title={title}
          className="flex-1 inline-flex items-center justify-center gap-2.5 rounded-xl border border-[#E1E8F5] bg-white px-4 py-3 text-[14px] font-semibold text-[#0F172A] shadow-[0_1px_2px_rgba(16,24,40,.04)] transition hover:border-[#BFD0F5] hover:bg-[#F8FAFF] disabled:cursor-not-allowed disabled:opacity-50">
    {children}
  </button>
);

export default function SocialAuthButtons({ onError, layout = 'row' }) {
  const { oauthLogin } = useAuth();
  const navigate = useNavigate();
  const [config, setConfig] = useState(null);
  const [busy, setBusy] = useState(null);      // 'google' | 'apple' | null
  const [ready, setReady] = useState({ google: false, apple: false });

  useEffect(() => {
    let alive = true;
    authAPI.oauthConfig()
      .then((r) => { if (alive) setConfig(r.data || {}); })
      .catch(() => { if (alive) setConfig({}); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (config?.google_client_id) {
      loadScript(GIS_SRC).then(() => setReady((r) => ({ ...r, google: !!window.google?.accounts?.oauth2 })))
        .catch((e) => onError?.(e.message));
    }
    if (config?.apple_client_id) {
      loadScript(APPLE_SRC).then(() => {
        window.AppleID?.auth?.init({
          clientId: config.apple_client_id,
          scope: 'name email',
          redirectURI: config.apple_redirect_uri || `${window.location.origin}/login`,
          usePopup: true,
        });
        setReady((r) => ({ ...r, apple: !!window.AppleID?.auth }));
      }).catch((e) => onError?.(e.message));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config?.google_client_id, config?.apple_client_id, config?.apple_redirect_uri]);

  const finish = async (provider, payload) => {
    setBusy(provider);
    try {
      const session = await oauthLogin(provider, payload);
      routeAfterAuth(navigate, session);
    } catch (err) {
      onError?.(err?.response?.data?.detail || err?.message || 'Connexion impossible. Réessayez.');
    } finally {
      setBusy(null);
    }
  };

  const handleGoogle = () => {
    const client = window.google.accounts.oauth2.initTokenClient({
      client_id: config.google_client_id,
      scope: 'openid email profile',
      callback: (resp) => {
        if (resp?.access_token) finish('google', { access_token: resp.access_token });
        else if (resp?.error && resp.error !== 'popup_closed_by_user') onError?.(`Google : ${resp.error}`);
      },
      error_callback: (e) => { if (e?.type !== 'popup_closed') onError?.('Google : connexion annulée.'); },
    });
    client.requestAccessToken();
  };

  const handleApple = async () => {
    try {
      // Fresh nonce per attempt; Apple echoes it inside the id_token and the
      // backend refuses a token whose nonce does not match (no replay).
      const nonce = Array.from(crypto.getRandomValues(new Uint8Array(24)), (b) => b.toString(16).padStart(2, '0')).join('');
      const data = await window.AppleID.auth.signIn({ nonce });
      const idToken = data?.authorization?.id_token;
      if (!idToken) throw new Error("Apple n'a pas renvoyé de jeton.");
      await finish('apple', {
        id_token: idToken,
        nonce,
        first_name: data?.user?.name?.firstName || null,
        last_name: data?.user?.name?.lastName || null,
      });
    } catch (err) {
      if (err?.error === 'popup_closed_by_user') return;
      onError?.(err?.message || 'Connexion Apple impossible.');
    }
  };

  const gOff = !config?.google_client_id;
  const aOff = !config?.apple_client_id;
  const offTip = 'Bientôt disponible — configuration en cours.';

  return (
    <div className={layout === 'row' ? 'flex gap-3' : 'flex flex-col gap-3'}>
      <Btn onClick={handleGoogle} disabled={gOff || !ready.google || busy !== null} title={gOff ? offTip : undefined}>
        <GoogleGlyph /> {busy === 'google' ? 'Connexion…' : 'Continuer avec Google'}
      </Btn>
      <Btn onClick={handleApple} disabled={aOff || !ready.apple || busy !== null} title={aOff ? offTip : undefined}>
        <AppleGlyph /> {busy === 'apple' ? 'Connexion…' : 'Continuer avec Apple'}
      </Btn>
    </div>
  );
}
