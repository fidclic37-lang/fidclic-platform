import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Users, Activity, TrendingUp, Star, Bell, MapPin,
  Gift, Sparkles, Coffee, Cake, BrainCircuit, Zap,
  Target, AlertTriangle,
} from 'lucide-react';
import { C } from './PageShell';

/**
 * HERO PHONE SHOWCASE — the cinematic four-scene loop on the landing page.
 *
 * One iPhone-style frame at centre that auto-rotates through:
 *   0) Analytics dashboard on the phone
 *   1) Push notifications cascading on the lock screen
 *   2) Apple-Wallet style loyalty card with stamps filling up
 *   3) Geolocation push (a customer is nearby)
 *
 * A subtle "dashboard echo" panel sits behind the phone showing the
 * desktop equivalent of whatever scene is playing — so the viewer
 * understands the app works on both devices without us writing copy.
 *
 * Scene rotation is automatic (~6s per scene) and looped. Click the dots
 * at the bottom to jump to a scene manually.
 *
 * Self-contained component — does not depend on any other landing-page
 * component and does not modify the existing HeroDashboardMockup (kept
 * in LandingPage.jsx for rollback safety).
 */

/**
 * Two-act cinematic loop:
 *   ACT 1 (~6s)  — Floating dashboard panel, no PC frame, just the
 *                  content cycling Analytics → Insights → Settings.
 *   ACT 2 (~6s)  — Phone GLIDES IN slowly + smoothly from the right
 *                  with the Apple Wallet card. The dashboard panel
 *                  drifts a touch to the left + dims to make space.
 *   Loop.
 *
 * No PC mockup, no browser chrome — the dashboard content stands on
 * its own as a soft glassy card, and the phone enters with a long,
 * elegant 1.8s spring rather than a snap.
 */
const HeroPhoneShowcase = () => {
  const PC_TABS = ['analytics', 'insights', 'settings'];
  const [phase, setPhase] = useState('pc');     // 'pc' | 'wallet'
  const [tabIdx, setTabIdx] = useState(0);

  useEffect(() => {
    let timeouts = [];
    const run = () => {
      setPhase('pc');
      setTabIdx(0);
      timeouts.push(setTimeout(() => setTabIdx(1), 3500));
      timeouts.push(setTimeout(() => setTabIdx(2), 7000));
      timeouts.push(setTimeout(() => setPhase('wallet'), 10500));
      // Hold wallet ~7s, then loop. Total cycle ≈ 18s.
      timeouts.push(setTimeout(run, 18000));
    };
    run();
    return () => { timeouts.forEach(clearTimeout); };
  }, []);

  return (
    <div className="relative w-full max-w-[760px] mx-auto" style={{ perspective: '2200px', minHeight: 560 }}>
      {/* Multi-color glow halo behind everything */}
      <div
        aria-hidden="true"
        className="absolute -inset-16 rounded-[60px] opacity-40 blur-3xl pointer-events-none"
        style={{
          background:
            'conic-gradient(from 90deg, ' + C.terracotta + ', ' + C.rose + ', ' + C.lavender + ', ' + C.sky + ', ' + C.teal + ', ' + C.terracotta + ')',
        }}
      />

      {/* Dashboard panel — slides slightly left + softens when phone enters. */}
      <motion.div
        animate={{
          x: phase === 'wallet' ? -120 : 0,
          scale: phase === 'wallet' ? 0.94 : 1,
          opacity: phase === 'wallet' ? 0.78 : 1,
        }}
        transition={{ duration: 1.4, ease: [0.16, 1, 0.3, 1] }}
        className="relative z-10"
      >
        <DashboardPanel tab={PC_TABS[tabIdx]} />
      </motion.div>

      {/* Phone glides in from off-screen right — slow & smooth. */}
      <AnimatePresence>
        {phase === 'wallet' && (
          <motion.div
            key="phone-in"
            initial={{ x: 520, y: 60, rotate: 14, opacity: 0, scale: 0.85 }}
            animate={{ x: 0, y: 0, rotate: 0, opacity: 1, scale: 1 }}
            exit={{ x: 520, opacity: 0, rotate: 10, scale: 0.9, transition: { duration: 1.1, ease: [0.7, 0, 0.84, 0] } }}
            transition={{ duration: 1.8, ease: [0.16, 1, 0.3, 1] }}
            className="absolute z-20"
            style={{ top: 20, right: -10 }}
          >
            <PhoneFrame>
              <SceneWalletCard key="wallet" />
            </PhoneFrame>
          </motion.div>
        )}
      </AnimatePresence>

      <p className="relative text-center text-xs mt-8 font-bold uppercase tracking-widest transition-colors"
         style={{ color: phase === 'wallet' ? C.terracotta : C.lavender }}>
        {phase === 'wallet'
          ? 'Apple Wallet · what your customer holds'
          : 'Owner dashboard · ' + PC_TABS[tabIdx]}
      </p>
    </div>
  );
};

/* ===================================================================== */
/* DASHBOARD PANEL — pure content, no laptop frame. Crossfades tabs.      */
/* Looks like a soft glassy card that floats inside the hero glow.        */
/* ===================================================================== */
const DashboardPanel = ({ tab }) => (
  <div
    className="relative mx-auto rounded-3xl shadow-2xl border overflow-hidden"
    style={{
      width: 560,
      maxWidth: '100%',
      background: 'rgba(255,255,255,0.85)',
      backdropFilter: 'blur(14px)',
      WebkitBackdropFilter: 'blur(14px)',
      borderColor: 'rgba(255,255,255,0.6)',
      transform: 'perspective(2000px) rotateX(2deg)',
      transformStyle: 'preserve-3d',
    }}
  >
    {/* Tiny tab pill row at the top so the tab being shown is obvious */}
    <div className="flex items-center gap-1.5 px-4 py-2.5"
         style={{ borderBottom: '1px solid ' + C.hairline, background: 'rgba(255,255,255,0.55)' }}>
      {['analytics', 'insights', 'settings'].map((t) => (
        <span key={t}
              className="text-[10px] font-bold uppercase tracking-widest px-2.5 py-1 rounded-full transition-all"
              style={{
                background: t === tab ? C.terracotta : 'transparent',
                color: t === tab ? 'white' : C.inkMute,
              }}>
          {t}
        </span>
      ))}
    </div>

    {/* Crossfade between tab contents */}
    <div className="relative" style={{ background: C.cream, minHeight: 280 }}>
      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
          className="p-5"
        >
          {tab === 'analytics' && <PCDashboardAnalytics />}
          {tab === 'insights'  && <PCDashboardInsights />}
          {tab === 'settings'  && <PCDashboardSettings />}
        </motion.div>
      </AnimatePresence>
    </div>
  </div>
);

/* Tiny dashboard mocks rendered inside the laptop. Visually distinct per tab. */
const PCDashboardAnalytics = () => (
  <div>
    <p className="text-[10px] font-bold uppercase tracking-wider mb-2" style={{ color: C.terracotta }}>
      Analytics — overview
    </p>
    <div className="grid grid-cols-4 gap-2 mb-3">
      {[
        { label: 'Customers', value: '1,247', accent: C.terracotta },
        { label: 'Visits',    value: '8,902', accent: C.sage },
        { label: 'Repeat',    value: '92%',   accent: C.ochre },
        { label: 'Wallet',    value: '76%',   accent: C.lavender },
      ].map((kpi) => (
        <div key={kpi.label} className="rounded-md p-2 bg-white border"
             style={{ borderColor: C.hairline }}>
          <p className="text-[8px] uppercase tracking-wide" style={{ color: C.inkFaint }}>{kpi.label}</p>
          <p className="text-base font-bold" style={{ color: C.inkDeep, fontFamily: 'Cormorant Garamond' }}>{kpi.value}</p>
          <div className="mt-1 h-1 rounded-full" style={{ background: kpi.accent + '33' }}>
            <div className="h-full rounded-full" style={{ width: '70%', background: kpi.accent }} />
          </div>
        </div>
      ))}
    </div>
    <div className="rounded-md bg-white border p-2.5" style={{ borderColor: C.hairline }}>
      <p className="text-[9px] font-bold mb-1.5" style={{ color: C.inkSoft }}>Visits · last 12 weeks</p>
      <div className="flex items-end gap-1 h-14">
        {[40,55,38,62,48,72,80,68,85,90,76,92].map((h, i) => (
          <div key={i} className="flex-1 rounded-sm"
               style={{ height: h + '%', background: i === 11 ? C.terracotta : C.terracotta + '88' }} />
        ))}
      </div>
    </div>
  </div>
);

const PCDashboardInsights = () => (
  <div>
    <p className="text-[10px] font-bold uppercase tracking-wider mb-2" style={{ color: C.lavender }}>
      Insights — what to do today
    </p>

    {/* AI-generated insights ribbon — the "headline" recommendation */}
    <div className="rounded-md p-2.5 mb-2 relative overflow-hidden"
         style={{ background: `linear-gradient(135deg, ${C.lavender}18, ${C.terracotta}12)`, border: `1px solid ${C.lavender}55` }}>
      <div className="flex items-start gap-2">
        <span className="text-[14px] leading-none mt-0.5">✨</span>
        <div className="min-w-0 flex-1">
          <p className="text-[9px] font-bold uppercase tracking-widest" style={{ color: C.lavender }}>
            AI insight · top priority
          </p>
          <p className="text-[10px] font-bold mt-0.5" style={{ color: C.inkDeep }}>
            Win back 12 silent gold-tier customers this week
          </p>
          <p className="text-[8px] mt-0.5 leading-snug" style={{ color: C.inkMute }}>
            They averaged €58/visit before going quiet · projected lift: €700+ if you re-engage now.
          </p>
        </div>
      </div>
    </div>

    {/* 4 categorized insights */}
    <div className="grid grid-cols-2 gap-1.5">
      {[
        { dot: C.terracotta, label: 'Churn risk',     title: '45 customers about to leave', sub: 'Silent ≥ 14 days' },
        { dot: C.sage,       label: 'Wins',           title: '12 birthdays this week',      sub: 'Greeting ready to approve' },
        { dot: C.ochre,      label: 'Pattern',        title: 'Mondays are slowest',         sub: '−42% vs. weekend avg' },
        { dot: C.sky,        label: 'Top customer',   title: 'Luc Moreau silent 18d',       sub: '€1,521 lifetime · personal nudge?' },
      ].map((row, i) => (
        <div key={i} className="rounded-md bg-white border p-1.5"
             style={{ borderColor: C.hairline }}>
          <div className="flex items-center gap-1 mb-0.5">
            <span className="w-1.5 h-1.5 rounded-full" style={{ background: row.dot }} />
            <p className="text-[7.5px] font-bold uppercase tracking-widest" style={{ color: row.dot }}>{row.label}</p>
          </div>
          <p className="text-[9.5px] font-bold leading-tight" style={{ color: C.inkDeep }}>{row.title}</p>
          <p className="text-[7.5px] leading-tight mt-0.5" style={{ color: C.inkMute }}>{row.sub}</p>
        </div>
      ))}
    </div>

    {/* Mini AI recap bar */}
    <div className="mt-2 rounded-md p-1.5 flex items-center justify-between"
         style={{ background: C.terracotta + '15', border: `1px solid ${C.terracotta}33` }}>
      <p className="text-[8px] font-bold" style={{ color: C.terracotta }}>
        🧠 AI summary: focus on win-back · est. revenue +€820
      </p>
      <p className="text-[7.5px]" style={{ color: C.inkMute }}>updated 12 min ago</p>
    </div>
  </div>
);

const PCDashboardSettings = () => (
  <div>
    <p className="text-[10px] font-bold uppercase tracking-wider mb-2" style={{ color: C.sage }}>
      Settings — loyalty programme
    </p>
    <div className="grid grid-cols-2 gap-2">
      {[
        { label: 'Points per euro',     value: '10 pts' },
        { label: 'Reward unlocked at',  value: '10 visits' },
        { label: 'Birthday bonus',      value: '+50 pts' },
        { label: 'Geolocation',         value: '500 m · 1 day' },
        { label: 'Active threshold',    value: '≤ 30 days' },
        { label: 'Peak hours',          value: '12pm–2pm' },
      ].map((row) => (
        <div key={row.label} className="rounded-md bg-white border p-2"
             style={{ borderColor: C.hairline }}>
          <p className="text-[8px] uppercase tracking-wide" style={{ color: C.inkFaint }}>{row.label}</p>
          <p className="text-[11px] font-bold" style={{ color: C.inkDeep }}>{row.value}</p>
        </div>
      ))}
    </div>
    <div className="mt-2 rounded-md p-2 flex items-center justify-between"
         style={{ background: C.terracotta + '15', border: '1px solid ' + C.terracotta + '33' }}>
      <p className="text-[9px] font-bold" style={{ color: C.terracotta }}>✓ 23 staff · 4 shops</p>
      <p className="text-[8px]" style={{ color: C.inkMute }}>all operational</p>
    </div>
  </div>
);

/* ===================================================================== */
/* PHONE FRAME — iPhone-like outline with notch and screen area          */
/* ===================================================================== */
const PhoneFrame = ({ children }) => (
  <motion.div
    initial={{ opacity: 0, y: 30, rotateY: -8 }}
    animate={{ opacity: 1, y: 0, rotateY: 0 }}
    transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}
    className="relative"
    style={{
      width: 290,
      height: 600,
      transformStyle: 'preserve-3d',
    }}
  >
    {/* Outer bezel */}
    <div
      className="absolute inset-0 rounded-[44px] shadow-2xl"
      style={{
        background: 'linear-gradient(145deg, #1A1A1F 0%, #2A2A30 50%, #0E0E12 100%)',
        boxShadow: '0 30px 60px -15px rgba(0,0,0,0.4), 0 10px 25px -5px rgba(0,0,0,0.2), inset 0 0 0 2px #303035',
      }}
    />
    {/* Inner screen */}
    <div
      className="absolute rounded-[34px] overflow-hidden"
      style={{
        top: 8, left: 8, right: 8, bottom: 8,
        background: '#FAFAF8',
      }}
    >
      {/* Notch */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 z-30 flex items-center justify-center"
        style={{ width: 100, height: 24, background: '#0E0E12', borderBottomLeftRadius: 14, borderBottomRightRadius: 14 }}>
        <div className="w-2 h-2 rounded-full" style={{ background: '#1A1A1F', boxShadow: '0 0 0 1px #2A2A30' }} />
      </div>

      {/* Status bar */}
      <div className="absolute top-1 left-0 right-0 z-20 flex items-center justify-between px-6 text-[10px] font-bold"
        style={{ color: '#171412' }}>
        <span>9:41</span>
        <span className="invisible">·</span>
        <span className="flex items-center gap-1">
          <SignalDots />
          <BatteryIcon />
        </span>
      </div>

      {/* Scene content area */}
      <div className="absolute inset-0 pt-8">
        {children}
      </div>
    </div>
  </motion.div>
);

const SignalDots = () => (
  <span className="inline-flex items-end gap-[2px]">
    {[3, 5, 7, 9].map((h, i) => (
      <span key={i} className="rounded-sm" style={{ width: 2.5, height: h, background: '#171412' }} />
    ))}
  </span>
);

const BatteryIcon = () => (
  <span className="inline-flex items-center">
    <span className="rounded-[3px]" style={{ width: 18, height: 9, border: '1.2px solid #171412' }}>
      <span className="block rounded-sm" style={{ width: '70%', height: '100%', background: '#171412' }} />
    </span>
    <span className="ml-[1px] rounded-r-[1px]" style={{ width: 1.5, height: 4, background: '#171412' }} />
  </span>
);

/* ===================================================================== */
/* SCENE 1 — ANALYTICS                                                    */
/* ===================================================================== */
const SceneAnalytics = () => (
  <motion.div
    initial={{ opacity: 0, y: 8 }}
    animate={{ opacity: 1, y: 0 }}
    exit={{ opacity: 0, y: -8 }}
    transition={{ duration: 0.5 }}
    className="absolute inset-0 px-3.5 py-3 overflow-hidden flex flex-col gap-2.5"
    style={{ background: 'linear-gradient(180deg, #FAFAF8 0%, #F5F4F1 100%)' }}
  >
    {/* Header */}
    <div className="flex items-center gap-2 mt-1">
      <div className="w-7 h-7 rounded-full flex items-center justify-center text-white text-[10px] font-bold"
        style={{ background: 'linear-gradient(135deg, ' + C.terracotta + ', ' + C.rose + ')' }}>P</div>
      <div className="flex-1 min-w-0">
        <p className="text-[10px] font-bold leading-tight" style={{ color: C.inkDeep }}>Café Lumière</p>
        <p className="text-[8px]" style={{ color: C.inkMute }}>Bonjour Pierre</p>
      </div>
    </div>

    {/* KPIs */}
    <div className="grid grid-cols-2 gap-2">
      <KPI icon={Users}      label="Clients"  target={2847} accent={C.sky}        bg={C.azure} />
      <KPI icon={Activity}   label="Visites"  target={14200} suffix="+" accent={C.sage} bg={C.meadow} />
      <KPI icon={TrendingUp} label="Retour"   target={96}    suffix="%" accent={C.terracotta} bg={C.shellPink} />
      <KPI icon={Star}       label="Note"     target={87}    divisor={10} fixed={1} accent={C.ochre} bg={C.butter} />
    </div>

    {/* Chart */}
    <div className="rounded-xl p-2.5 border" style={{ background: 'white', borderColor: C.hairline }}>
      <p className="text-[8px] font-bold uppercase tracking-wider mb-1" style={{ color: C.inkFaint }}>Visites — 14 derniers jours</p>
      <svg viewBox="0 0 200 50" className="w-full h-12">
        <defs>
          <linearGradient id="hpx" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"  stopColor={C.terracotta} stopOpacity="0.4" />
            <stop offset="100%" stopColor={C.terracotta} stopOpacity="0" />
          </linearGradient>
        </defs>
        <motion.path
          d="M0 38 L15 32 L30 36 L45 24 L60 28 L75 18 L90 22 L105 14 L120 18 L135 10 L150 14 L165 8 L180 12 L195 4"
          fill="none" stroke={C.terracotta} strokeWidth="2" strokeLinecap="round"
          initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 2, delay: 0.3 }}
        />
        <motion.path
          d="M0 38 L15 32 L30 36 L45 24 L60 28 L75 18 L90 22 L105 14 L120 18 L135 10 L150 14 L165 8 L180 12 L195 4 L195 50 L0 50 Z"
          fill="url(#hpx)" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 1, delay: 1.5 }}
        />
      </svg>
    </div>

    {/* Live activity */}
    <div className="rounded-xl p-2.5 border space-y-1.5" style={{ background: 'white', borderColor: C.hairline }}>
      <p className="text-[8px] font-bold uppercase tracking-wider" style={{ color: C.inkFaint }}>Activité en direct</p>
      {[
        { dot: C.sage,     text: 'Sophie M. est passée · +25 pts',  t: 'à l\'instant' },
        { dot: C.lavender, text: 'Antoine L. devient VIP',          t: '2 min' },
        { dot: C.coral,    text: 'Anniversaires · 12 envois',       t: '5 min' },
      ].map((a, i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.6 + i * 0.2 }}
          className="flex items-center gap-1.5 text-[9px]">
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: a.dot }} />
          <span className="flex-1 truncate" style={{ color: C.inkDeep }}>{a.text}</span>
          <span style={{ color: C.inkFaint }}>{a.t}</span>
        </motion.div>
      ))}
    </div>
  </motion.div>
);

const KPI = ({ icon: Icon, label, target, accent, bg, suffix = '', divisor = 1, fixed = 0 }) => {
  const display = useCountUp(target, 1500);
  const formatted = (display / divisor).toFixed(fixed);
  return (
    <div className="rounded-xl p-2 border" style={{ background: 'white', borderColor: C.hairline }}>
      <div className="w-6 h-6 rounded-md flex items-center justify-center mb-1" style={{ background: bg }}>
        <Icon size={11} style={{ color: accent }} />
      </div>
      <p className="text-[8px] font-bold uppercase tracking-wider" style={{ color: C.inkFaint }}>{label}</p>
      <p className="text-[13px] font-bold leading-tight" style={{ color: C.inkDeep }}>
        {formatted}{suffix}
      </p>
    </div>
  );
};

// Hook: smoothly counts up from 0 to `to` over `durationMs`.
const useCountUp = (to, durationMs = 1200) => {
  const [n, setN] = useState(0);
  useEffect(() => {
    const start = performance.now();
    let raf;
    const step = (t) => {
      const p = Math.min(1, (t - start) / durationMs);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - p, 3);
      setN(Math.round(to * eased));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => raf && cancelAnimationFrame(raf);
  }, [to, durationMs]);
  return n;
};

/* ===================================================================== */
/* SCENE 2 — NOTIFICATIONS                                                */
/* ===================================================================== */
const SceneNotifications = () => {
  const items = [
    { icon: Sparkles, tint: C.sage,      title: 'Nouveau client',     body: 'Sophie vient de s\'inscrire — votre 47ᵉ ce mois-ci.' },
    { icon: TrendingUp,tint: C.terracotta, title: 'Gros panier',       body: 'Marie a dépensé 45 €  — palier VIP atteint.' },
    { icon: Cake,     tint: C.rose,      title: 'Anniversaire du jour', body: 'Les 30 ans de Lisa — message prêt à envoyer.' },
    { icon: Bell,     tint: C.lavender,  title: 'Pic du mardi',         body: 'Visites en hausse de 23 % vs mardi dernier.' },
  ];
  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
      className="absolute inset-0 px-3.5 py-3 flex flex-col"
      style={{ background: 'linear-gradient(180deg, #171412 0%, #2A1C2E 100%)' }}
    >
      {/* Lock screen time */}
      <div className="text-center mt-3 mb-4">
        <p className="text-[10px] font-semibold tracking-wider opacity-80" style={{ color: 'white' }}>Mardi 30 Avril</p>
        <p className="text-[44px] font-bold leading-none mt-1" style={{ color: 'white', fontFamily: 'Cormorant Garamond' }}>9:41</p>
      </div>

      {/* Notification stack */}
      <div className="flex flex-col gap-2 px-1">
        {items.map((n, i) => {
          const Icon = n.icon;
          return (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 22, scale: 0.92 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ delay: 0.3 + i * 0.55, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
              className="rounded-2xl px-3 py-2.5 backdrop-blur-md flex items-start gap-2.5"
              style={{
                background: 'rgba(255, 255, 255, 0.85)',
                boxShadow: '0 4px 20px -2px rgba(0,0,0,0.3)',
              }}
            >
              <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
                style={{ background: n.tint, color: 'white' }}>
                <Icon size={13} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[10px] font-bold leading-tight" style={{ color: '#171412' }}>FidClic</p>
                  <p className="text-[8px]" style={{ color: '#57504A' }}>maintenant</p>
                </div>
                <p className="text-[10px] font-semibold mt-0.5" style={{ color: '#171412' }}>{n.title}</p>
                <p className="text-[9px] leading-tight" style={{ color: '#57504A' }}>{n.body}</p>
              </div>
            </motion.div>
          );
        })}
      </div>
    </motion.div>
  );
};

/* ===================================================================== */
/* SCENE 3 — WALLET CARD WITH STAMPS (Apple Wallet stacked-cards look)    */
/* ===================================================================== */
// Elegant palette mirrored from AuchanCard.DEFAULT_LAYOUT — keeps the
// homepage card identical to what a new merchant gets in the designer.
const ELEGANT_HERO = {
  cream: '#FAF5E9',
  cream_deep: '#F1E9D2',
  midnight: '#15233D',
  gold: '#C9A961',
  gold_deep: '#A88947',
  charcoal: '#171412',
};

const SceneWalletCard = () => {
  const target = 7;
  const total = 10;
  const [filled, setFilled] = useState(0);
  useEffect(() => {
    let i = 0;
    const id = setInterval(() => {
      i += 1;
      setFilled(i);
      if (i >= target) clearInterval(id);
    }, 280);
    return () => clearInterval(id);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
      className="absolute inset-0 flex flex-col"
      style={{ background: 'linear-gradient(180deg, #0F0F12 0%, #18181C 100%)' }}
    >
      {/* Apple Wallet header — back chevron, "Wallet" title, ⋯ */}
      <div className="flex items-center justify-between mt-1 px-3 z-30 relative" style={{ height: 26 }}>
        <span className="inline-flex items-center gap-0.5 text-[10px] font-medium" style={{ color: '#FF9F0A' }}>
          <svg width="8" height="11" viewBox="0 0 11 14" fill="none">
            <path d="M9 1L3 7L9 13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Cartes
        </span>
        <span className="text-[11px] font-semibold" style={{ color: 'white' }}>Wallet</span>
        <span className="text-[15px] leading-none" style={{ color: '#FF9F0A' }}>⋯</span>
      </div>

      {/* Stacked cards above the focus card — peek at the top */}
      <FakeStack
        style={{ position: 'absolute', top: 32, left: 18, right: 18, height: 18, transform: 'scale(0.92)' }}
        gradient="linear-gradient(135deg, #1B1F3A 0%, #6B5B95 100%)"
        label="ID"
      />
      <FakeStack
        style={{ position: 'absolute', top: 44, left: 14, right: 14, height: 16, transform: 'scale(0.96)' }}
        gradient="linear-gradient(135deg, #DCB46B 0%, #B8924E 100%)"
        label="DISCOVER"
      />

      {/* The focus card — matches AuchanCard.DEFAULT_LAYOUT (cream + navy + gold) */}
      <motion.div
        initial={{ y: 30, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        className="mx-3 mt-14 rounded-2xl shadow-2xl overflow-hidden relative z-20"
        style={{ background: ELEGANT_HERO.cream, fontFamily: "'Inter', sans-serif" }}
      >
        {/* Card top row — logo placeholder + "PLUS D'INFOS" */}
        <div className="flex items-center justify-between px-3 pt-2.5">
          <div className="rounded-md flex items-center justify-center" style={{ width: 38, height: 18, background: '#E8DFC9' }}>
            <span className="text-[7px] font-semibold uppercase tracking-wider" style={{ color: ELEGANT_HERO.gold_deep }}>logo</span>
          </div>
          <span className="text-[7.5px] font-bold uppercase tracking-widest" style={{ color: ELEGANT_HERO.gold_deep }}>plus d'infos</span>
        </div>

        {/* Midnight banner */}
        <div className="mx-2.5 mt-2 rounded-lg overflow-hidden relative px-3 py-3 text-center"
          style={{ background: 'linear-gradient(135deg, ' + ELEGANT_HERO.midnight + ' 0%, #1F2F4F 100%)' }}>
          <p className="text-[7.5px] font-bold uppercase tracking-widest" style={{ color: ELEGANT_HERO.gold }}>
            Programme fidélité
          </p>
          <p className="text-[8px] mt-1 italic" style={{ color: ELEGANT_HERO.cream_deep, fontFamily: 'Cormorant Garamond' }}>
            Une expérience pensée pour vous
          </p>
          <p className="text-[15px] mt-1 font-bold" style={{ color: 'white', fontFamily: 'Cormorant Garamond' }}>
            Récompense exclusive
          </p>
          <span className="inline-block mt-1 px-2 py-0.5 rounded-full text-[7px] font-bold uppercase tracking-widest"
            style={{ background: ELEGANT_HERO.gold, color: ELEGANT_HERO.midnight }}>
            pour nos membres
          </span>
        </div>

        {/* Greeting + points */}
        <div className="flex justify-between items-end px-3 pt-2.5 pb-1">
          <div>
            <p className="text-[7.5px] font-bold uppercase tracking-widest" style={{ color: ELEGANT_HERO.gold_deep }}>BIENVENUE</p>
            <p className="text-[15px] font-bold leading-tight" style={{ color: ELEGANT_HERO.charcoal, fontFamily: 'Cormorant Garamond' }}>Sophie</p>
          </div>
          <div className="text-right">
            <p className="text-[7.5px] font-bold uppercase tracking-widest" style={{ color: ELEGANT_HERO.gold_deep }}>MES POINTS</p>
            <p className="text-[15px] font-bold leading-tight" style={{ color: ELEGANT_HERO.charcoal, fontFamily: 'Cormorant Garamond' }}>
              {filled * 10} pts
            </p>
          </div>
        </div>

        {/* Stamps grid — gold hexagons fill in animatedly */}
        <div className="px-3 pb-2.5">
          <div className="grid grid-cols-5 gap-1.5">
            {Array.from({ length: total }).map((_, i) => {
              const isFilled = i < filled;
              return (
                <motion.div
                  key={i}
                  initial={false}
                  animate={{ scale: isFilled ? [1, 1.3, 1] : 1 }}
                  transition={{ duration: 0.4 }}
                  className="aspect-square flex items-center justify-center"
                >
                  <svg width="22" height="22" viewBox="0 0 24 24">
                    <polygon
                      points="12,2 21,7 21,17 12,22 3,17 3,7"
                      fill={isFilled ? ELEGANT_HERO.gold : 'transparent'}
                      stroke={isFilled ? ELEGANT_HERO.gold_deep : '#E8DFC9'}
                      strokeWidth="1.4"
                    />
                  </svg>
                </motion.div>
              );
            })}
          </div>
          {/* Progress meter — gold */}
          <div className="mt-2 h-1.5 rounded-full overflow-hidden" style={{ background: '#E8DFC9' }}>
            <motion.div
              className="h-full rounded-full"
              initial={{ width: 0 }}
              animate={{ width: `${(filled / total) * 100}%` }}
              transition={{ duration: 0.4 }}
              style={{ background: 'linear-gradient(90deg, ' + ELEGANT_HERO.gold + ', ' + ELEGANT_HERO.gold_deep + ')' }}
            />
          </div>
          <p className="text-[7.5px] font-semibold mt-1.5 text-center" style={{ color: ELEGANT_HERO.gold_deep }}>
            {filled} / {total} visites
          </p>
        </div>

        {/* Barcode placeholder */}
        <div className="px-3 pb-3 flex justify-center">
          <div className="w-full h-7 flex items-end gap-[1px]" aria-hidden="true">
            {Array.from({ length: 50 }).map((_, i) => (
              <span key={i} style={{
                background: ELEGANT_HERO.charcoal,
                width: 2 + (i % 3),
                height: '100%',
                opacity: 0.85 - (i % 5) * 0.05,
              }} />
            ))}
          </div>
        </div>
      </motion.div>

      {/* Stacked cards below the focus card */}
      <FakeStack
        style={{ position: 'absolute', bottom: 50, left: 14, right: 14, height: 18 }}
        gradient="linear-gradient(135deg, #FF6B35 0%, #F7931E 100%)"
        label="Dunkin'"
        flipped
      />
      <FakeStack
        style={{ position: 'absolute', bottom: 38, left: 18, right: 18, height: 16, transform: 'scale(0.95)' }}
        gradient="linear-gradient(135deg, #2D5F3F 0%, #1F4530 100%)"
        label="Carrefour"
        flipped
      />

      {/* Home indicator */}
      <div className="absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full"
        style={{ width: '32%', height: 3, background: 'rgba(255,255,255,0.4)' }} />
    </motion.div>
  );
};

const FakeStack = ({ style = {}, gradient, label, flipped }) => (
  <div
    aria-hidden="true"
    className="rounded-[10px] flex items-center px-2.5"
    style={{
      background: gradient,
      boxShadow: flipped
        ? '0 -2px 6px rgba(0, 0, 0, 0.25)'
        : '0 2px 6px rgba(0, 0, 0, 0.25)',
      ...style,
    }}
  >
    <span className="text-[6.5px] font-bold uppercase tracking-widest" style={{ color: 'rgba(255,255,255,0.85)' }}>
      {label}
    </span>
  </div>
);

/* ===================================================================== */
/* SCENE 4 — GEOLOCATION                                                  */
/* ===================================================================== */
const SceneGeolocation = () => {
  // Four feature pills cascade in after the map + push notification appear.
  const features = [
    { icon: '📍', title: 'Configurable radius', sub: '50m – 2km' },
    { icon: '👑', title: 'VIP-only opt-in',     sub: 'restrict to top tier' },
    { icon: '⏱',  title: 'Cooldown protection', sub: 'max 1 nudge / X days' },
    { icon: '🤫', title: 'Silent on the back-end', sub: 'no popups, just works' },
  ];

  return (
  <motion.div
    initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
    transition={{ duration: 0.4 }}
    className="absolute inset-0 flex flex-col"
  >
    {/* Stylised map (compact — leaves room for the feature pills below) */}
    <div className="relative overflow-hidden" style={{ height: 200, background: 'linear-gradient(180deg, #DCE9D5 0%, #C9DCC2 100%)' }}>
      <svg className="absolute inset-0 w-full h-full" viewBox="0 0 290 200" preserveAspectRatio="none">
        <g stroke="#FAFAF8" strokeWidth="12" strokeLinecap="round">
          <line x1="-20" y1="60"  x2="320" y2="50" />
          <line x1="-20" y1="140" x2="320" y2="130" />
          <line x1="80" y1="-20" x2="100" y2="220" />
          <line x1="220" y1="-20" x2="200" y2="220" />
        </g>
        <g fill="#F5F4F1">
          <rect x="20" y="20" width="40" height="32" rx="3" />
          <rect x="120" y="70" width="60" height="38" rx="3" />
          <rect x="240" y="20" width="30" height="32" rx="3" />
          <rect x="20" y="160" width="50" height="32" rx="3" />
        </g>
      </svg>

      {/* Café pin */}
      <motion.div
        initial={{ scale: 0, y: -10 }} animate={{ scale: 1, y: 0 }}
        transition={{ delay: 0.3, type: 'spring', stiffness: 300, damping: 20 }}
        className="absolute z-20"
        style={{ left: '50%', top: '38%', transform: 'translate(-50%, -100%)' }}
      >
        <div className="w-10 h-10 rounded-full flex items-center justify-center shadow-xl"
          style={{ background: 'linear-gradient(135deg, ' + C.terracotta + ', ' + C.rose + ')' }}>
          <Coffee size={16} className="text-white" />
        </div>
      </motion.div>

      {/* Customer dot with pulsing proximity ring */}
      <div className="absolute z-10" style={{ left: '34%', top: '64%' }}>
        <motion.div
          className="absolute -inset-5 rounded-full"
          style={{ background: C.sky, opacity: 0.4 }}
          animate={{ scale: [1, 2.4, 1], opacity: [0.5, 0, 0.5] }}
          transition={{ duration: 2, repeat: Infinity }}
        />
        <motion.div
          initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: 0.7 }}
          className="relative w-3.5 h-3.5 rounded-full border-2 border-white shadow-md"
          style={{ background: C.sky }}
        />
      </div>

      {/* Distance label */}
      <motion.div
        initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 1 }}
        className="absolute z-20 px-2 py-0.5 rounded-full text-[8px] font-bold"
        style={{ left: '42%', top: '57%', background: 'white', color: C.inkDeep, boxShadow: '0 2px 8px rgba(0,0,0,0.15)' }}
      >
        100 m
      </motion.div>
    </div>

    {/* Push notification — what THE CUSTOMER receives */}
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 1.2, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className="mx-3 mt-3 rounded-2xl px-3 py-2.5 backdrop-blur-md flex items-start gap-2.5"
      style={{
        background: 'rgba(255, 255, 255, 0.96)',
        boxShadow: '0 4px 20px -2px rgba(0,0,0,0.2)',
      }}
    >
      <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 text-white"
        style={{ background: 'linear-gradient(135deg, ' + C.sky + ', ' + C.lavender + ')' }}>
        <MapPin size={13} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[10px] font-bold leading-tight" style={{ color: '#171412' }}>Café Lumière</p>
          <p className="text-[8px]" style={{ color: '#57504A' }}>maintenant</p>
        </div>
        <p className="text-[10px] font-semibold mt-0.5" style={{ color: '#171412' }}>Vous passez devant&nbsp;?</p>
        <p className="text-[9px] leading-tight" style={{ color: '#57504A' }}>
          5&nbsp;€ offerts sur votre prochain café — passez nous voir.
        </p>
      </div>
    </motion.div>

    {/* Headline + 4 feature pills (cascade in) */}
    <div className="px-3 mt-3 mb-1">
      <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: C.terracotta }}>
        Quand votre VIP passe à côté
      </p>
      <p className="text-[10px] font-semibold mt-0.5 leading-tight" style={{ color: C.inkDeep }}>
        Il reçoit une attention.
      </p>
    </div>

    <div className="grid grid-cols-2 gap-1.5 mx-3 mb-3">
      {features.map((f, i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1.6 + i * 0.18, duration: 0.4 }}
          className="rounded-lg px-2 py-1.5 flex items-start gap-1.5"
          style={{ background: 'white', border: '1px solid ' + C.hairline }}
        >
          <span className="text-[12px] leading-none">{f.icon}</span>
          <div className="min-w-0">
            <p className="text-[8.5px] font-bold leading-tight truncate" style={{ color: C.inkDeep }}>{f.title}</p>
            <p className="text-[7.5px] leading-tight truncate" style={{ color: C.inkMute }}>{f.sub}</p>
          </div>
        </motion.div>
      ))}
    </div>
  </motion.div>
  );
};

/* ===================================================================== */
/* SCENE 5 — AI INTELLIGENCE                                              */
/* ===================================================================== */
const SceneAIIntelligence = () => {
  // Four AI-generated insight cards that cascade in. The first three are
  // proactive recommendations the merchant can act on; the fourth is a
  // predictive churn alert.
  const insights = [
    {
      icon: Target, tone: 'lavender',
      eyebrow: 'Action recommandée',
      title: 'Réveiller 12 clients Or silencieux',
      detail: 'Envoyez «&nbsp;vous nous manquez&nbsp;» — gain projeté +340 € cette semaine.',
      metric: '+340 €',
    },
    {
      icon: TrendingUp, tone: 'sage',
      eyebrow: 'Tendance détectée',
      title: 'Le mardi est votre pic — +23 %',
      detail: 'Renforcez l\'équipe 11h–14h. Poussez l\'offre le lundi soir.',
      metric: '+23 %',
    },
    {
      icon: AlertTriangle, tone: 'terracotta',
      eyebrow: 'Risque de désengagement',
      title: 'Sophie risque de partir d\'ici 9 jours',
      detail: 'Votre meilleure cliente s\'éloigne de son rythme habituel de 6 jours.',
      metric: 'à faire',
    },
    {
      icon: Zap, tone: 'ochre',
      eyebrow: 'Gain rapide',
      title: 'Abaisser le palier Argent à 8 visites',
      detail: 'Promeut 47 clients, augmente la fréquence d\'environ 19 %.',
      metric: '+47',
    },
  ];

  const toneColor = (t) => ({
    lavender: C.lavender, sage: C.sage, terracotta: C.terracotta, ochre: C.ochre,
  }[t] || C.terracotta);

  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
      className="absolute inset-0 px-3.5 py-3 overflow-hidden flex flex-col gap-2"
      style={{ background: 'linear-gradient(180deg, #FAFAF8 0%, #F0EDFA 100%)' }}
    >
      {/* Header — AI assistant identity */}
      <div className="flex items-center gap-2 mt-1">
        <motion.div
          animate={{ rotate: [0, 5, -5, 0] }}
          transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}
          className="w-7 h-7 rounded-lg flex items-center justify-center text-white shrink-0"
          style={{ background: 'linear-gradient(135deg, ' + C.lavender + ', ' + C.terracotta + ')' }}
        >
          <BrainCircuit size={14} />
        </motion.div>
        <div className="flex-1 min-w-0">
          <p className="text-[10px] font-bold leading-tight" style={{ color: C.inkDeep }}>Intelligence IA</p>
          <div className="flex items-center gap-1 mt-0.5">
            <motion.span
              className="block w-1 h-1 rounded-full"
              style={{ background: C.sage }}
              animate={{ opacity: [0.3, 1, 0.3] }}
              transition={{ duration: 1.5, repeat: Infinity }}
            />
            <p className="text-[8px]" style={{ color: C.inkMute }}>En direct · apprend de vos données</p>
          </div>
        </div>
        <span className="text-[8px] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded"
          style={{ background: C.terracotta + '1A', color: C.terracotta }}>
          4 nouv.
        </span>
      </div>

      {/* "Auto-detected today" banner */}
      <motion.div
        initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}
        className="rounded-lg p-2 mt-1"
        style={{
          background: 'linear-gradient(135deg, ' + C.lavender + '12, ' + C.terracotta + '08)',
          border: '1px solid ' + C.lavender + '33',
        }}
      >
        <p className="text-[8px] font-bold uppercase tracking-widest" style={{ color: C.lavender }}>
          ✨ Détection automatique · classée par impact
        </p>
        <p className="text-[9px] mt-0.5" style={{ color: C.inkSoft }}>
          Tendances détectées sur vos 30 derniers jours, triées par revenu projeté.
        </p>
      </motion.div>

      {/* Stack of 4 insight cards — cascade in 0.3s apart */}
      <div className="flex flex-col gap-1.5 mt-1 flex-1 overflow-hidden">
        {insights.map((ins, i) => {
          const Icon = ins.icon;
          const accent = toneColor(ins.tone);
          return (
            <motion.div
              key={i}
              initial={{ opacity: 0, x: -10, scale: 0.96 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              transition={{ delay: 0.4 + i * 0.32, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
              className="rounded-lg p-2 flex gap-2 items-start"
              style={{
                background: 'white',
                border: '1px solid ' + accent + '33',
                boxShadow: '0 1px 3px rgba(28,25,23,0.05)',
              }}
            >
              <div className="w-6 h-6 rounded-md flex items-center justify-center shrink-0"
                style={{ background: accent + '1A', color: accent, border: '1px solid ' + accent + '33' }}>
                <Icon size={11} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-1.5">
                  <p className="text-[7.5px] font-bold uppercase tracking-widest leading-none" style={{ color: accent }}>
                    {ins.eyebrow}
                  </p>
                  <span className="text-[8px] font-bold leading-none" style={{ color: accent }}>
                    {ins.metric}
                  </span>
                </div>
                <p className="text-[10px] font-bold leading-tight mt-0.5" style={{ color: C.inkDeep }}>{ins.title}</p>
                <p className="text-[8.5px] leading-tight mt-0.5" style={{ color: C.inkMute }}>{ins.detail}</p>
              </div>
            </motion.div>
          );
        })}
      </div>

      {/* "Ask anything" prompt at the bottom */}
      <motion.div
        initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 1.9, duration: 0.4 }}
        className="mt-1 rounded-lg px-2 py-1.5 flex items-center gap-2"
        style={{
          background: 'linear-gradient(135deg, ' + C.inkDeep + ' 0%, #2A1C2E 100%)',
          color: 'white',
        }}
      >
        <Sparkles size={11} style={{ color: C.ochre }} />
        <p className="text-[9px] flex-1 truncate">Ask: "Why did Saturday drop?"</p>
        <span className="text-[8px] font-bold opacity-70">⌘K</span>
      </motion.div>
    </motion.div>
  );
};

/* ===================================================================== */
/* DASHBOARD ECHO — soft desktop mockup behind the phone                  */
/* ===================================================================== */
const DashboardEcho = ({ scene }) => (
  <div
    aria-hidden="true"
    className="absolute hidden lg:block"
    style={{
      right: -40, top: 80,
      width: 380, height: 240,
      transform: 'perspective(1500px) rotateY(-12deg) rotateX(4deg)',
      transformStyle: 'preserve-3d',
      opacity: 0.55,
      filter: 'blur(0.4px)',
    }}
  >
    {/* Browser shell */}
    <div className="rounded-xl shadow-xl border w-full h-full overflow-hidden"
      style={{ background: 'white', borderColor: C.hairline }}>
      <div className="flex items-center gap-1.5 px-3 py-2 border-b" style={{ borderColor: C.hairline, background: C.sand }}>
        <span className="w-2 h-2 rounded-full" style={{ background: '#FF5F57' }} />
        <span className="w-2 h-2 rounded-full" style={{ background: '#FEBC2E' }} />
        <span className="w-2 h-2 rounded-full" style={{ background: '#28C840' }} />
        <span className="ml-2 text-[9px] font-mono" style={{ color: C.inkMute }}>app.fidclic.com/{scene}</span>
      </div>
      <AnimatePresence mode="wait">
        <motion.div
          key={scene}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.4 }}
          className="p-3"
          style={{ background: C.cream, height: 'calc(100% - 28px)' }}
        >
          <p className="text-[9px] font-bold uppercase tracking-wider mb-2" style={{ color: C.inkFaint }}>
            {scene === 'analytics'     && 'Tableau de bord · Analytics'}
            {scene === 'notifications' && 'Notifications · Flux en direct'}
            {scene === 'wallet'        && 'Concepteur de carte · Aperçu live'}
            {scene === 'geolocation'   && 'Carte clients · Périmètres'}
            {scene === 'ai'            && 'Insights · Recommandations IA'}
          </p>
          <div className="grid grid-cols-3 gap-1.5">
            {[0,1,2,3,4,5].map((i) => (
              <div key={i} className="rounded-md p-2 border"
                style={{ background: 'white', borderColor: C.hairline, height: 36 }} />
            ))}
          </div>
          <div className="rounded-md mt-2 border" style={{ background: 'white', borderColor: C.hairline, height: 80 }} />
        </motion.div>
      </AnimatePresence>
    </div>
  </div>
);

export default HeroPhoneShowcase;
