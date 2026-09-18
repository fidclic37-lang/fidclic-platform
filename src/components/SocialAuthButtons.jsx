import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { authAPI } from '../lib/api';

/**
 * SocialAuthButtons — "Continuer avec Google" / "Continuer avec Apple".
 *
 * Shared by /login and /register. Both providers hand the browser a signed
 * ID token; we POST it to /api/auth/oauth/<provider> (features/oauth.py)
 * which verifies it and issues the normal session. Nothing secret lives in
 * the frontend — only the public client IDs, fetched from
 * /api/auth/oauth/config so a provider that isn't configured simply does
 * not render its button (never a dead control).
 *
 * Google: the ID-token flow only works through Google's own rendered
 * button (google.accounts.id.renderButton) — a custom-styled button can't
 * trigger it. We render it full-width, "continue_with", French locale, and
 * wrap it so it sits at the same height as the Apple button.
 * Apple: AppleID.auth.signIn() CAN be called from our own button, in popup
 * mode, so we draw a matching black button ourselves. Apple only sends the
 * user's name on the very first authorisation — we forward it.
 *
 * After login the caller decides where to go: a brand-new account (or one
 * that never finished step 2) goes to /onboarding/entreprise.
 */
const GIS_SRC = 'https://accounts.google.com/gsi/client';
const APPLE_SRC = 'https://appleid.cdn-apple.com/appleauth/static/jsapi/appleid/1/fr-FR/appleid.auth.js';

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
  if (session?.role === 'staff') return navigate('/dashboard/scan');
  if (session?.role === 'business_owner') return navigate('/modules');
  if (session?.role === 'comptable') return navigate('/cabinet');
  return navigate('/dashboard');
}

export default function SocialAuthButtons({ onError }) {
  const { oauthLogin } = useAuth();
  const navigate = useNavigate();
  const [config, setConfig] = useState(null);
  const [busy, setBusy] = useState(null); // 'google' | 'apple' | null
  const googleSlot = useRef(null);

  useEffect(() => {
    let alive = true;
    authAPI.oauthConfig()
      .then((r) => { if (alive) setConfig(r.data || {}); })
      .catch(() => { if (alive) setConfig({}); });
    return () => { alive = false; };
  }, []);

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

  // Google — render the official button into our slot once GIS is loaded.
  useEffect(() => {
    if (!config?.google_client_id || !googleSlot.current) return;
    let cancelled = false;
    loadScript(GIS_SRC).then(() => {
      if (cancelled || !window.google?.accounts?.id) return;
      window.google.accounts.id.initialize({
        client_id: config.google_client_id,
        callback: (resp) => finish('google', { credential: resp.credential }),
        ux_mode: 'popup',
        auto_select: false,
      });
      // Width must be a number in px for GIS — measure the slot.
      const width = Math.min(400, Math.max(200, googleSlot.current.offsetWidth || 320));
      window.google.accounts.id.renderButton(googleSlot.current, {
        type: 'standard', theme: 'outline', size: 'large', shape: 'pill',
        text: 'continue_with', logo_alignment: 'left', locale: 'fr', width,
      });
    }).catch((e) => onError?.(e.message));
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config?.google_client_id]);

  // Apple — init once; the click handler opens the popup.
  useEffect(() => {
    if (!config?.apple_client_id) return;
    loadScript(APPLE_SRC).then(() => {
      window.AppleID?.auth?.init({
        clientId: config.apple_client_id,
        scope: 'name email',
        redirectURI: config.apple_redirect_uri || `${window.location.origin}/login`,
        usePopup: true,
      });
    }).catch((e) => onError?.(e.message));
  }, [config?.apple_client_id, config?.apple_redirect_uri, onError]);

  const handleApple = async () => {
    try {
      const data = await window.AppleID.auth.signIn();
      const idToken = data?.authorization?.id_token;
      if (!idToken) throw new Error("Apple n'a pas renvoyé de jeton.");
      await finish('apple', {
        id_token: idToken,
        first_name: data?.user?.name?.firstName || null,
        last_name: data?.user?.name?.lastName || null,
      });
    } catch (err) {
      // User closed the popup → Apple rejects with {error: 'popup_closed_by_user'}; stay quiet.
      if (err?.error === 'popup_closed_by_user') return;
      onError?.(err?.message || 'Connexion Apple impossible.');
    }
  };

  const hasGoogle = !!config?.google_client_id;
  const hasApple = !!config?.apple_client_id;
  if (config === null || (!hasGoogle && !hasApple)) return null;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 text-[11px] uppercase tracking-widest text-[#A8A29E]">
        <div className="h-px flex-1 bg-[#E7E5E4]" />
        <span>ou</span>
        <div className="h-px flex-1 bg-[#E7E5E4]" />
      </div>

      {hasGoogle && (
        <div className="flex justify-center min-h-[44px]" aria-busy={busy === 'google'}>
          <div ref={googleSlot} className="w-full max-w-[400px] flex justify-center" />
        </div>
      )}

      {hasApple && (
        <button type="button" onClick={handleApple} disabled={busy !== null}
                className="w-full inline-flex items-center justify-center gap-2.5 rounded-full py-3 text-sm font-semibold text-white transition disabled:opacity-60"
                style={{ background: '#000' }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M16.365 1.43c0 1.14-.42 2.08-1.25 2.93-1 1.04-2.2 1.62-3.44 1.52-.16-1.11.34-2.28 1.17-3.12.86-.9 2.32-1.55 3.52-1.33zM20.9 17.07c-.57 1.3-.84 1.88-1.57 3.03-1.02 1.6-2.45 3.6-4.23 3.61-1.58.02-1.99-1.04-4.13-1.02-2.15.01-2.6 1.04-4.18 1.02-1.78-.02-3.14-1.82-4.16-3.42C.8 16.6-.03 12.05 1.63 9.11c1.07-1.9 2.98-3.1 4.8-3.1 1.85 0 3.01 1.03 4.54 1.03 1.49 0 2.4-1.03 4.55-1.03 1.62 0 3.33.88 4.55 2.4-4 2.2-3.35 7.9.83 8.66z"/>
          </svg>
          {busy === 'apple' ? 'Connexion…' : 'Continuer avec Apple'}
        </button>
      )}
    </div>
  );
}
