import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { authAPI, setAuthToken } from '../lib/api';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const checkAuth = useCallback(async () => {
    try {
      const res = await authAPI.me();
      setUser(res.data);
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
    // Stash the JWT in localStorage so axios interceptor can send it as a
    // Bearer header on every subsequent request — covers the case where
    // the cookie path / SameSite drops the cookie on cross-page POSTs.
    if (res.data?.access_token) setAuthToken(res.data.access_token);
    await checkAuth();
    return res.data;
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
    if (res.data?.access_token) setAuthToken(res.data.access_token);
    await checkAuth();
    return res.data;
  };

  const logout = async () => {
    try { await authAPI.logout(); } finally {
      setAuthToken(null);
      setUser(null);
    }
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, oauthLogin, logout, checkAuth }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
