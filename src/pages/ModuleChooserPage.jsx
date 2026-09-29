import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sparkles, ReceiptText, ArrowRight, Lock } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { facturationAPI } from '../lib/api';

/**
 * ModuleChooserPage — the post-login "which module?" screen (Option A).
 *
 * Shows two products of the FidClic suite:
 *   1. CRM + Fidélité  (always available)  -> /dashboard
 *   2. Facturation électronique            -> /facturation (if enabled)
 *                                           or an "activate" prompt (if not)
 *
 * Facturation can be bought standalone or as an add-on; until the tenant
 * opts in, the second card invites them to discover/activate it.
 * Loyalty-only tenants therefore still see (and can upsell into) Facturation.
 *
 * Design: Saint-Germain palette — cream canvas, aubergine accents, elegant
 * serif headings — matching the rest of the dashboard.
 */
export default function ModuleChooserPage() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [facturationEnabled, setFacturationEnabled] = useState(null); // null = loading

  useEffect(() => {
    let alive = true;
    facturationAPI.availability()
      .then((r) => { if (alive) setFacturationEnabled(!!r.data?.enabled); })
      .catch(() => { if (alive) setFacturationEnabled(false); });
    return () => { alive = false; };
  }, []);

  const goFacturation = () => {
    if (facturationEnabled) navigate('/facturation');
    else navigate('/facturation'); // FacturationHome renders the activation gate
  };

  return (
    <div
      className="min-h-screen flex flex-col"
      style={{
        background:
          'radial-gradient(1200px 500px at 85% -10%, rgba(201,162,39,.07), transparent 60%),' +
          'radial-gradient(1000px 500px at -10% 110%, rgba(107,46,90,.06), transparent 60%), #FBF7EF',
      }}
    >
      {/* Top bar */}
      <header className="flex items-center justify-between px-6 py-4">
        <div
          className="font-['Cormorant_Garamond'] text-2xl font-bold"
          style={{ color: '#6B2E5A' }}
        >
          FidClic
        </div>
        <button
          onClick={() => { logout(); navigate('/login'); }}
          className="text-sm text-[#57534E] hover:text-[#1C1917] transition-colors"
        >
          Se déconnecter
        </button>
      </header>

      {/* Center */}
      <main className="flex-1 flex flex-col items-center justify-center px-4 pb-16">
        <div className="text-center mb-10">
          <h1
            className="font-['Playfair_Display'] text-3xl md:text-4xl font-bold mb-2"
            style={{ color: '#1C1917' }}
          >
            Bonjour{user?.name ? `, ${user.name}` : ''} 👋
          </h1>
          <p className="text-[#57534E] text-sm md:text-base">
            Choisissez l'espace dans lequel vous souhaitez travailler.
          </p>
        </div>

        <div className="grid gap-6 w-full max-w-3xl md:grid-cols-2">
          {/* Card 1 — CRM + Fidélité */}
          <button
            onClick={() => navigate(user?.preferences?.default_page || '/dashboard')}
            className="group text-left rounded-3xl bg-white border transition-all hover:-translate-y-1"
            style={{
              borderColor: '#ECE3D2',
              boxShadow:
                '0 1px 2px rgba(45,35,24,.04), 0 12px 32px -20px rgba(45,35,24,.18)',
            }}
          >
            <div className="p-7">
              <div
                className="w-12 h-12 rounded-2xl flex items-center justify-center mb-5"
                style={{ background: 'linear-gradient(135deg,#7A3E70,#4E1F44)' }}
              >
                <Sparkles size={22} color="#fff" />
              </div>
              <h2 className="text-xl font-bold mb-1" style={{ color: '#1C1917' }}>
                CRM + Fidélité
              </h2>
              <p className="text-sm text-[#57534E] mb-5">
                Cartes de fidélité, campagnes, analytics, programme de récompenses.
              </p>
              <span
                className="inline-flex items-center gap-1.5 text-sm font-semibold"
                style={{ color: '#6B2E5A' }}
              >
                Ouvrir l'espace
                <ArrowRight size={16} className="group-hover:translate-x-0.5 transition-transform" />
              </span>
            </div>
          </button>

          {/* Card 2 — Facturation */}
          <button
            onClick={goFacturation}
            className="group text-left rounded-3xl bg-white border transition-all hover:-translate-y-1"
            style={{
              borderColor: '#ECE3D2',
              boxShadow:
                '0 1px 2px rgba(45,35,24,.04), 0 12px 32px -20px rgba(45,35,24,.18)',
            }}
          >
            <div className="p-7">
              <div
                className="w-12 h-12 rounded-2xl flex items-center justify-center mb-5"
                style={{ background: 'linear-gradient(135deg,#2F6FB3,#1E4E86)' }}
              >
                <ReceiptText size={22} color="#fff" />
              </div>
              <div className="flex items-center gap-2 mb-1">
                <h2 className="text-xl font-bold" style={{ color: '#1C1917' }}>
                  Facturation électronique
                </h2>
                {facturationEnabled === false && (
                  <span
                    className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full"
                    style={{ background: 'rgba(201,162,39,.15)', color: '#8A6D12' }}
                  >
                    <Lock size={10} /> À activer
                  </span>
                )}
              </div>
              <p className="text-sm text-[#57534E] mb-5">
                Factures conformes (réforme 2026), e-reporting, et le Bouclier Fiscal.
              </p>
              <span
                className="inline-flex items-center gap-1.5 text-sm font-semibold"
                style={{ color: '#2F6FB3' }}
              >
                {facturationEnabled ? "Ouvrir l'espace" : 'Découvrir & activer'}
                <ArrowRight size={16} className="group-hover:translate-x-0.5 transition-transform" />
              </span>
            </div>
          </button>
        </div>

        <p className="text-xs text-[#8B8680] mt-8 text-center max-w-md">
          Vous pourrez changer d'espace à tout moment.
        </p>
      </main>
    </div>
  );
}
