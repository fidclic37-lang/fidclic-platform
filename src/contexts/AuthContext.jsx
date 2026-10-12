import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { ShieldCheck, Loader2 } from 'lucide-react';
import i18n from 'i18next';
import { authAPI, setAuthToken, viewToken, VIEW_KEY } from '../lib/api';
import { applyPrefs } from '../lib/prefs';
import { applyGoogleTranslate } from '../components/GoogleTranslateBridge';

/* 2FA at login (Paramètres › Sécurité): an account with the phone app switched
   on gets a challenge instead of a session. The code is asked here, once for
   every way of signing in (password, Google, Apple), so the login pages need
   not know about it. */
function TwoFactorPrompt({ onSubmit, onCancel }) {
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr('');
    try { await onSubmit(code.trim()); }
    catch (x) { setErr(x?.response?.data?.detail || 'Code incorrect.'); setBusy(false); }
  };
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-[#0B1C3F]/40 p-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-2xl">
        <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><ShieldCheck size={24} /></span>
        <h2 className="text-[18px] font-bold text-[#0B1C3F]">Double authentification</h2>
        <p className="mt-1 text-[13.5px] text-[#475569]">Saisissez le code à 6 chiffres affiché dans votre application d'authentification (ou un code de secours).</p>
        <input autoFocus inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)}
               className="mt-4 h-12 w-full rounded-xl border border-[#DCE3EE] px-4 text-center text-[20px] tracking-[0.3em] text-[#0B1C3F] outline-none focus:border-[#2F6BFF]"
               placeholder="000000" maxLength={12} />
        {err && <p className="mt-2 text-[13px] text-[#C0392B]">{err}</p>}
        <div className="mt-4 flex gap-2">
          <button type="button" onClick={onCancel} className="flex-1 rounded-xl border border-[#DCE3EE] py-2.5 text-[14px]">Annuler</button>
          <button type="submit" disabled={busy || code.trim().length < 6}
                  className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-[#2F6BFF] py-2.5 text-[14px] font-medium text-white disabled:opacity-50">
            {busy && <Loader2 size={15} className="animate-spin" />} Valider
          </button>
        </div>
      </form>
    </div>
  );
}

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [challenge, setChallenge] = useState(null);
  const pending = useRef(null);

  // A 2FA challenge becomes a session once the code is right.
  const secondFactor = (data) => {
    if (!data?.requires_2fa) return Promise.resolve(data);
    return new Promise((resolve, reject) => {
      pending.current = { resolve, reject };
      setChallenge(data.challenge);
    });
  };

  const checkAuth = useCallback(async () => {
    try {
      const res = await authAPI.me();
      setUser(res.data);
      // Paramètres › Préférences — currency, time zone, dates, links…
      applyPrefs(res.data?.preferences || {}, res.data?.currency || 'EUR');
      const lang = res.data?.preferences?.language;
      if (lang && (i18n.resolvedLanguage || i18n.language || 'fr').slice(0, 2) !== lang) {
        i18n.changeLanguage(lang);
        try { applyGoogleTranslate(lang); } catch { /* the bridge may not be loaded yet */ }
      }
      return res.data;
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const login = async (data) => {
    const res = await authAPI.login(data);
    const session = await secondFactor(res.data);
    // Stash the JWT in localStorage so axios interceptor can send it as a
    // Bearer header on every subsequent request — covers the case where
    // the cookie path / SameSite drops the cookie on cross-page POSTs.
    if (session?.access_token) setAuthToken(session.access_token);
    try { sessionStorage.setItem('ft_pick_store', '1'); } catch (_e) { /* ignore */ }   // StoreGate: choose first
    const me = await checkAuth();
    return { ...session, default_page: me?.preferences?.default_page };
  };

  // Register now auto-logs-in server-side (cookie + token in the response)
  // so the new owner lands on step 2 without a second /login round-trip.
  const register = async (data) => {
    const res = await authAPI.register(data);
    if (res.data?.access_token) setAuthToken(res.data.access_token);
    await checkAuth();
    return res.data;
  };

  // Google / Apple: `payload` is { credential } or { id_token, first_name, last_name }.
  const oauthLogin = async (provider, payload) => {
    const res = provider === 'google'
      ? await authAPI.oauthGoogle(payload)
      : await authAPI.oauthApple(payload);
    const session = await secondFactor(res.data);
    if (session?.access_token) setAuthToken(session.access_token);
    try { sessionStorage.setItem('ft_pick_store', '1'); } catch (_e) { /* ignore */ }
    await checkAuth();
    return { ...res.data, ...session };
  };

  const logout = async () => {
    // Leaving a read-only view: forget this tab's token only — never sign the
    // super admin out of their own session.
    if (viewToken()) {
      try { sessionStorage.removeItem(VIEW_KEY); } catch (_e) { /* ignore */ }
      window.close();
      window.location.replace('/admin/commerces');
      return;
    }
    try { await authAPI.logout(); } finally {
      setAuthToken(null);
      setUser(null);
    }
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, oauthLogin, logout, checkAuth }}>
      {children}
      {challenge && (
        <TwoFactorPrompt
          onSubmit={async (code) => {
            const res = await authAPI.login2fa(challenge, code);
            setChallenge(null);
            pending.current?.resolve(res.data);
          }}
          onCancel={() => {
            setChallenge(null);
            pending.current?.reject({ response: { data: { detail: 'Connexion annulée.' } } });
          }} />
      )}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
