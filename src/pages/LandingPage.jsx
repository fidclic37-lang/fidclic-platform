import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion, useInView, useMotionValue, useSpring, useTransform } from 'framer-motion';
import {
  MapPin, BrainCircuit, ScanLine, Smartphone, Settings2, BarChart3,
  Users, TrendingUp, Star, Sparkles, Zap, Target, Megaphone, Gift,
  ChevronRight, Check, ArrowRight, Award, Activity, MessageSquare,
  ReceiptText, ShieldCheck, Building2, FileCheck2, AlertTriangle,
  CalendarClock, FolderKanban, Inbox,
} from 'lucide-react';
import { AuchanPreview, DEFAULT_LAYOUT } from '../components/AuchanCard';
import HeroPhoneShowcase from '../components/HeroPhoneShowcase';
import AppleWalletFrame from '../components/AppleWalletFrame';
// PremiumLoyaltyCard is the same card the Card Designer renders — using it
// here makes the landing demo card visually identical to what a merchant sees
// when designing their own card in /dashboard/card-designer.
import PremiumLoyaltyCard from '../components/PremiumLoyaltyCard';

/* ───────────────────────────────────────────────────────────────────────
 * LandingDemoCard — single source of truth for the demo card props used
 * across the landing page. Wraps PremiumLoyaltyCard with hard-coded
 * "Sophie" sample data so the same card renders in the bento Wallet
 * block AND the big hero showcase below. Tweak this one place to update
 * both surfaces.
 * ─────────────────────────────────────────────────────────────────── */
function LandingDemoCard({ compact = true }) {
  return (
    <PremiumLoyaltyCard
      compact={compact}
      customer={{
        name: 'Sophie Dupont',
        first_name: 'Sophie',
        tier: 'Gold',
        barcode_id: 'FT-A1B2C3D4',
        visits: 7,                // 7/10 stamps — same half-filled state the old card showed
        reward_threshold: 10,
        offers_count: 1,
        birthday: '12/05',
      }}
      tenant={{ name: 'Café Lumière' }}
      card={{
        primary_color: '#B85C38',
        secondary_color: '#9C4427',
        accent_color: '#F4D8A8',
        strip_color: '#1F2937',          // dark navy banner — the "Loyalty program" strip
        strip_text_color: '#FFFFFF',
        strip_title: 'Récompense exclusive',
        strip_subtitle: 'Pour nos membres',
        bottom_greeting_label: 'Bienvenue',
        points_per_visit: 10,
        visits_per_stamp: 1,
        show_qr: true,
        qr_size: 90,
      }}
    />
  );
}

/* =====================================================================
   COLOR SYSTEM — vibrant pastels + saturated accents
   ===================================================================== */
const C = {
  // Brand
  terracotta: '#B85C38',
  ochre:      '#E3A869',
  rose:       '#D77FA0',
  lavender:   '#8B7DC9',
  sky:        '#6BA4D9',
  teal:       '#6FA89C',
  sage:       '#88B27E',
  coral:      '#F08C7A',
  // Pastel surfaces
  cream:      '#FDFBF7',
  sand:       '#F5EFE5',
  shellPink:  '#FCE3DC',
  blush:      '#FBE0E8',
  lilac:      '#F0EBF8',
  azure:      '#DDEBF6',
  mint:       '#DDF1ED',
  meadow:     '#E5F0DC',
  butter:     '#FDF1DC',
  // Ink
  inkDeep:    '#1C1917',
  inkSoft:    '#3D2820',
  inkMute:    '#57534E',
  inkFaint:   '#8B8680',
  hairline:   '#EFE9E0',
};

/* ---------------------------------------------------------------------
   AnimatedNumber — counts up from 0 to target when scrolled into view
   --------------------------------------------------------------------- */
function AnimatedNumber({ to, format = (n) => n.toLocaleString(), duration = 1.6, suffix = '' }) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: '-50px' });
  const [val, setVal] = useState(0);
  useEffect(() => {
    if (!inView) return;
    let raf, start;
    const step = (t) => {
      if (!start) start = t;
      const p = Math.min(1, (t - start) / (duration * 1000));
      const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
      setVal(to * eased);
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [inView, to, duration]);
  return <span ref={ref}>{format(Math.round(val))}{suffix}</span>;
}

/* ---------------------------------------------------------------------
   Reusable: badged eyebrow at the start of a section
   --------------------------------------------------------------------- */
const Eyebrow = ({ children, color = C.terracotta, bg = C.shellPink }) => (
  <span
    className="inline-block px-4 py-1.5 rounded-full text-xs font-bold uppercase tracking-[0.2em] mb-6"
    style={{ backgroundColor: bg, color }}
  >
    {children}
  </span>
);

/* =====================================================================
   ANIMATED HERO DASHBOARD MOCKUP
   Live-feeling product preview that sits next to the hero copy
   ===================================================================== */
function HeroDashboardMockup() {
  return (
    <div className="relative w-full max-w-[640px] mx-auto" style={{ perspective: '1500px' }}>
      {/* Multi-color glow halo behind */}
      <div
        aria-hidden="true"
        className="absolute -inset-12 rounded-[40px] opacity-50 blur-3xl pointer-events-none"
        style={{
          background:
            'conic-gradient(from 90deg, ' + C.terracotta + ', ' + C.rose + ', ' + C.lavender + ', ' + C.sky + ', ' + C.teal + ', ' + C.terracotta + ')',
        }}
      />

      {/* The "browser" frame */}
      <motion.div
        initial={{ opacity: 0, y: 30, rotateX: 10 }}
        animate={{ opacity: 1, y: 0, rotateX: 0 }}
        transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
        className="relative bg-white rounded-2xl shadow-2xl overflow-hidden border"
        style={{ borderColor: C.hairline, transformStyle: 'preserve-3d' }}
      >
        {/* Browser chrome */}
        <div className="flex items-center gap-2 px-4 py-3 border-b" style={{ borderColor: C.hairline, background: C.sand }}>
          <span className="w-3 h-3 rounded-full" style={{ background: '#FF5F57' }} />
          <span className="w-3 h-3 rounded-full" style={{ background: '#FEBC2E' }} />
          <span className="w-3 h-3 rounded-full" style={{ background: '#28C840' }} />
          <span className="ml-3 px-3 py-1 rounded-md text-xs font-mono"
                style={{ background: 'white', color: C.inkMute, border: '1px solid ' + C.hairline }}>
            app.fidclic.com/dashboard
          </span>
        </div>

        {/* Dashboard interior */}
        <div className="p-5 space-y-3" style={{ background: C.cream }}>
          {/* Top row: 4 KPI tiles */}
          <div className="grid grid-cols-4 gap-2">
            {[
              { icon: Users,      label: 'Customers',  value: '2,847', accent: C.sky,       bg: C.azure },
              { icon: Activity,   label: 'Visits',     value: '14.2K', accent: C.sage,      bg: C.meadow },
              { icon: TrendingUp, label: 'Repeat',     value: '96%',   accent: C.terracotta, bg: C.shellPink },
              { icon: Star,       label: 'Rating',     value: '8.7',   accent: C.ochre,     bg: C.butter },
            ].map((k, i) => {
              const Icon = k.icon;
              return (
                <motion.div
                  key={k.label}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.3 + i * 0.08 }}
                  className="rounded-xl p-2.5 border"
                  style={{ background: 'white', borderColor: C.hairline }}
                >
                  <div className="w-7 h-7 rounded-lg flex items-center justify-center mb-1.5" style={{ background: k.bg }}>
                    <Icon size={14} style={{ color: k.accent }} />
                  </div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: C.inkFaint }}>{k.label}</p>
                  <p className="text-base font-bold" style={{ color: C.inkDeep }}>{k.value}</p>
                </motion.div>
              );
            })}
          </div>

          {/* Mid row: chart + tier pie */}
          <div className="grid grid-cols-3 gap-2">
            {/* Visits-over-time chart */}
            <motion.div
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.7 }}
              className="col-span-2 rounded-xl p-3 border"
              style={{ background: 'white', borderColor: C.hairline }}
            >
              <p className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: C.inkFaint }}>
                Visits — last 14 days
              </p>
              <svg viewBox="0 0 200 60" className="w-full h-14">
                <defs>
                  <linearGradient id="lg" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%"  stopColor={C.terracotta} stopOpacity="0.4" />
                    <stop offset="100%" stopColor={C.terracotta} stopOpacity="0" />
                  </linearGradient>
                </defs>
                <motion.path
                  d="M0 45 L15 38 L30 42 L45 30 L60 35 L75 22 L90 28 L105 18 L120 24 L135 14 L150 20 L165 12 L180 16 L195 8"
                  fill="none"
                  stroke={C.terracotta}
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  initial={{ pathLength: 0 }}
                  animate={{ pathLength: 1 }}
                  transition={{ duration: 1.5, delay: 0.9 }}
                />
                <motion.path
                  d="M0 45 L15 38 L30 42 L45 30 L60 35 L75 22 L90 28 L105 18 L120 24 L135 14 L150 20 L165 12 L180 16 L195 8 L195 60 L0 60 Z"
                  fill="url(#lg)"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 1, delay: 1.5 }}
                />
              </svg>
            </motion.div>

            {/* Tier distribution */}
            <motion.div
              initial={{ opacity: 0, x: 10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.85 }}
              className="rounded-xl p-3 border"
              style={{ background: 'white', borderColor: C.hairline }}
            >
              <p className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: C.inkFaint }}>Tiers</p>
              <div className="flex justify-center">
                <svg viewBox="0 0 60 60" className="w-14 h-14">
                  <circle cx="30" cy="30" r="22" fill="none" stroke={C.shellPink} strokeWidth="10" />
                  <motion.circle
                    cx="30" cy="30" r="22" fill="none" stroke={C.terracotta} strokeWidth="10"
                    strokeDasharray="138" strokeDashoffset="69" transform="rotate(-90 30 30)"
                    initial={{ strokeDashoffset: 138 }} animate={{ strokeDashoffset: 69 }}
                    transition={{ duration: 1, delay: 1 }}
                  />
                </svg>
              </div>
              <div className="flex justify-center gap-1 mt-1 text-[9px]" style={{ color: C.inkMute }}>
                <span>Gold</span><span style={{ color: C.inkFaint }}>·</span><span>52%</span>
              </div>
            </motion.div>
          </div>

          {/* Bottom row: live activity feed */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 1 }}
            className="rounded-xl p-3 border space-y-1.5"
            style={{ background: 'white', borderColor: C.hairline }}
          >
            <p className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: C.inkFaint }}>Live activity</p>
            {[
              { dot: C.sage,       text: 'Sophie M. visited · +25 pts',   t: 'now' },
              { dot: C.lavender,   text: 'Antoine L. became VIP',          t: '2m' },
              { dot: C.coral,      text: 'Birthday offer sent · 12 cust.', t: '5m' },
            ].map((a, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, x: -5 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 1.2 + i * 0.15 }}
                className="flex items-center gap-2 text-[11px]"
              >
                <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: a.dot }} />
                <span className="flex-1 truncate" style={{ color: C.inkDeep }}>{a.text}</span>
                <span style={{ color: C.inkFaint }}>{a.t}</span>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </motion.div>

      {/* Floating notification card on top-right */}
      <motion.div
        initial={{ opacity: 0, scale: 0.85, y: -10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 1.4 }}
        className="absolute -right-4 lg:-right-12 top-16 hidden md:flex items-center gap-2 px-4 py-3 rounded-xl shadow-2xl border"
        style={{ background: 'white', borderColor: C.hairline }}
      >
        <div className="w-9 h-9 rounded-lg flex items-center justify-center text-white shrink-0"
             style={{ background: 'linear-gradient(135deg, ' + C.rose + ' 0%, ' + C.lavender + ' 100%)' }}>
          <Gift size={18} />
        </div>
        <div className="text-xs">
          <p className="font-bold" style={{ color: C.inkDeep }}>🎂 Birthday today</p>
          <p style={{ color: C.inkMute }}>Sending offer to <b>Marie D.</b></p>
        </div>
      </motion.div>

      {/* Floating "+€42 in revenue today" pill on bottom-left */}
      <motion.div
        initial={{ opacity: 0, scale: 0.85, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 1.6 }}
        className="absolute -left-4 lg:-left-10 bottom-12 hidden md:flex items-center gap-2 px-4 py-2.5 rounded-full shadow-2xl border"
        style={{ background: 'white', borderColor: C.hairline }}
      >
        <div className="w-2.5 h-2.5 rounded-full animate-pulse" style={{ background: C.sage }} />
        <span className="text-sm font-bold" style={{ color: C.inkDeep }}>+€42 today · live</span>
      </motion.div>

      {/* "VIP unlocked" pill mid-right */}
      <motion.div
        initial={{ opacity: 0, scale: 0.85 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.6, delay: 1.8 }}
        className="absolute right-2 lg:-right-8 bottom-32 hidden lg:flex items-center gap-2 px-4 py-2 rounded-full shadow-xl"
        style={{
          background: 'linear-gradient(135deg, ' + C.lavender + ' 0%, ' + C.rose + ' 100%)',
          color: 'white',
        }}
      >
        <Sparkles size={14} />
        <span className="text-xs font-bold">VIP unlocked</span>
      </motion.div>
    </div>
  );
}

/* =====================================================================
   BENTO FEATURE CARD — varied sizes, colorful surfaces
   ===================================================================== */
function BentoCard({ children, className = '', tint = 'white', border = C.hairline, glow, accent }) {
  // Resolve a faint accent for the second orb (defaults to glow's hue)
  const orb2 = accent || glow || `${C.terracotta}33`;
  return (
    <motion.div
      whileHover={{ y: -4, scale: 1.005 }}
      transition={{ type: 'spring', stiffness: 280, damping: 22 }}
      className={`relative rounded-3xl p-7 border overflow-hidden ${className}`}
      style={{
        // Subtle gradient mesh instead of flat tint — adds depth without busy-ness.
        background: `
          radial-gradient(circle at 100% 0%, ${tint} 0%, transparent 55%),
          radial-gradient(circle at 0% 100%, ${tint} 0%, transparent 55%),
          ${tint}
        `,
        borderColor: border,
      }}
    >
      {/* Top-right glow orb */}
      {glow && (
        <div
          aria-hidden="true"
          className="absolute -top-16 -right-16 w-52 h-52 rounded-full blur-3xl opacity-60 pointer-events-none"
          style={{ background: glow }}
        />
      )}
      {/* Bottom-left soft orb (always present, very subtle) */}
      <motion.div
        aria-hidden="true"
        className="absolute -bottom-20 -left-20 w-44 h-44 rounded-full blur-3xl pointer-events-none"
        style={{ background: orb2, opacity: 0.35 }}
        animate={{ x: [0, 12, 0], y: [0, -8, 0] }}
        transition={{ duration: 14, repeat: Infinity, ease: 'easeInOut' }}
      />
      {/* Floating sparkle dots — three at different rhythms, very small */}
      {[
        { left: '18%', top: '24%', size: 4,  delay: 0,   color: glow || C.ochre },
        { left: '78%', top: '42%', size: 3,  delay: 1.5, color: accent || C.rose },
        { left: '55%', top: '78%', size: 5,  delay: 0.7, color: glow || C.lavender },
      ].map((s, i) => (
        <motion.span
          key={i}
          aria-hidden="true"
          className="absolute rounded-full pointer-events-none"
          style={{
            left: s.left, top: s.top,
            width: s.size, height: s.size,
            background: s.color,
            filter: 'blur(0.5px)',
          }}
          animate={{ opacity: [0.15, 0.7, 0.15], scale: [1, 1.4, 1] }}
          transition={{ duration: 3.5 + i * 0.6, repeat: Infinity, delay: s.delay, ease: 'easeInOut' }}
        />
      ))}
      <div className="relative">{children}</div>
    </motion.div>
  );
}


/* =====================================================================
   MAIN LANDING PAGE
   ===================================================================== */
const LandingPage = () => {
  return (
    <div className="min-h-screen font-['Manrope']" style={{ background: C.cream, color: C.inkDeep }}>

      {/* ───────────── NAVIGATION ───────────── */}
      <nav className="fixed w-full backdrop-blur-md border-b z-50" style={{ background: 'rgba(253,251,247,0.85)', borderColor: C.hairline }}>
        <div aria-hidden="true" className="absolute top-0 left-0 right-0 h-[2px]"
             style={{ background: `linear-gradient(90deg, ${C.terracotta} 0%, ${C.rose} 25%, ${C.lavender} 50%, ${C.sky} 75%, ${C.teal} 100%)` }} />
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center text-white font-bold text-xl shadow-md"
                 style={{ background: `linear-gradient(135deg, ${C.terracotta} 0%, ${C.rose} 100%)` }}>F</div>
            <span className="font-['Cormorant_Garamond'] text-2xl font-bold bg-clip-text text-transparent"
                  style={{ backgroundImage: `linear-gradient(135deg, ${C.terracotta} 0%, ${C.rose} 100%)` }}>
              FidClic
            </span>
          </Link>
          <div className="hidden md:flex items-center gap-8 font-medium text-sm">
            <a href="#features" className="hover:text-[#B85C38] transition-colors">Fonctionnalités</a>
            {/* Two audiences, two DEDICATED pages — not anchors. An accountant
                deserves a page built for them, not a section between loyalty
                blocks. The dot marks the time-sensitive one (Sept 2026). */}
            <Link to="/facturation-electronique" className="hover:text-[#6BA4D9] transition-colors flex items-center gap-1.5">
              Facturation 2026
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: C.sky }} />
            </Link>
            <Link to="/experts-comptables" className="hover:text-[#8B7DC9] transition-colors">Experts-comptables</Link>
            <a href="#how"      className="hover:text-[#B85C38] transition-colors">Comment ça marche</a>
            <a href="#pricing"  className="hover:text-[#B85C38] transition-colors">Tarifs</a>
          </div>
          <div className="flex items-center gap-3">
            <Link to="/login" className="font-medium text-sm hover:text-[#B85C38] transition-colors">Connexion</Link>
            <Link to="/register"
                  className="text-white px-5 py-2 rounded-full text-sm font-semibold shadow-md transition-all hover:shadow-lg hover:-translate-y-0.5"
                  style={{ background: `linear-gradient(135deg, ${C.terracotta} 0%, ${C.rose} 100%)` }}>
              S'inscrire
            </Link>
          </div>
        </div>
      </nav>

      {/* ───────────── HERO — split layout ───────────── */}
      <section className="relative pt-32 pb-20 lg:pt-40 lg:pb-32 overflow-hidden">
        {/* Ambient orbs */}
        <motion.div aria-hidden="true" className="absolute -top-32 -left-32 w-[600px] h-[600px] rounded-full blur-3xl opacity-50 pointer-events-none"
                    style={{ background: `radial-gradient(circle, ${C.shellPink} 0%, transparent 70%)` }}
                    animate={{ x: [0, 60, 0], y: [0, -40, 0] }} transition={{ duration: 22, repeat: Infinity, ease: 'easeInOut' }} />
        <motion.div aria-hidden="true" className="absolute top-1/3 -right-32 w-[500px] h-[500px] rounded-full blur-3xl opacity-50 pointer-events-none"
                    style={{ background: `radial-gradient(circle, ${C.azure} 0%, transparent 70%)` }}
                    animate={{ x: [0, -50, 0], y: [0, 40, 0] }} transition={{ duration: 26, repeat: Infinity, ease: 'easeInOut', delay: 2 }} />
        <motion.div aria-hidden="true" className="absolute bottom-0 left-1/3 w-[420px] h-[420px] rounded-full blur-3xl opacity-40 pointer-events-none"
                    style={{ background: `radial-gradient(circle, ${C.lilac} 0%, transparent 70%)` }}
                    animate={{ x: [0, 30, 0], y: [0, 20, 0] }} transition={{ duration: 28, repeat: Infinity, ease: 'easeInOut', delay: 4 }} />

        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 grid lg:grid-cols-2 gap-12 items-center">
          {/* Left — copy */}
          <div>
            <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}
                        className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/90 backdrop-blur-sm border shadow-sm mb-6"
                        style={{ borderColor: C.hairline }}>
              <span className="flex h-2 w-2 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: C.sage }} />
                <span className="relative inline-flex rounded-full h-2 w-2" style={{ background: C.sage }} />
              </span>
              <span className="text-xs font-bold tracking-widest uppercase" style={{ color: C.inkMute }}>
                <span style={{ color: C.terracotta }}>Plateforme française</span> · Conçue pour les commerçants
              </span>
            </motion.div>

            <motion.h1
              initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7 }}
              className="font-['Cormorant_Garamond'] text-5xl md:text-6xl lg:text-7xl font-bold leading-[1.05] tracking-tight"
            >
              Vos meilleurs clients reviennent <br/>
              <span className="bg-clip-text text-transparent inline-block"
                    style={{
                      backgroundImage: `linear-gradient(110deg, ${C.terracotta} 0%, ${C.ochre} 25%, ${C.rose} 50%, ${C.lavender} 75%, ${C.sky} 100%)`,
                      backgroundSize: '200% auto',
                      animation: 'heroGradient 8s linear infinite',
                    }}>
                sans que vous ayez à y penser.
              </span>
            </motion.h1>

            <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.7, delay: 0.2 }}
                      className="text-lg md:text-xl mt-6 leading-relaxed max-w-xl" style={{ color: C.inkMute }}>
              La carte de fidélité qui vit dans le portefeuille mobile de vos clients,
              et l'intelligence qui les ramène au bon moment, avec le bon message — automatiquement.
            </motion.p>

            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, delay: 0.4 }}
                        className="flex flex-col sm:flex-row gap-3 mt-10">
              <Link to="/register"
                    className="inline-flex items-center justify-center gap-2 text-white px-7 py-4 rounded-full font-semibold text-base shadow-xl transition-all hover:-translate-y-0.5"
                    style={{ background: `linear-gradient(135deg, ${C.terracotta} 0%, ${C.rose} 100%)`, boxShadow: `0 12px 28px ${C.terracotta}40` }}>
                Essai gratuit 30 jours
                <ArrowRight size={18} />
              </Link>
              <a href="#how"
                 className="inline-flex items-center justify-center gap-2 px-7 py-4 rounded-full font-semibold text-base border-2 transition-all hover:bg-white"
                 style={{ borderColor: C.hairline, background: 'rgba(255,255,255,0.6)', color: C.inkDeep }}>
                Voir une démonstration
              </a>
            </motion.div>

            {/* Trust strip */}
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.6, delay: 0.6 }}
                        className="flex items-center gap-4 mt-8 text-sm" style={{ color: C.inkMute }}>
              <div className="flex -space-x-2">
                {[C.rose, C.ochre, C.sage, C.sky].map((bg, i) => (
                  <div key={i} className="w-8 h-8 rounded-full border-2 border-white"
                       style={{ background: `linear-gradient(135deg, ${bg} 0%, ${C.terracotta} 100%)` }} />
                ))}
              </div>
              <span>
                <b style={{ color: C.inkDeep }}>Mise en place en 24h</b> · Sans engagement · RGPD natif
              </span>
            </motion.div>
          </div>

          {/* Right — cinematic phone showcase (4-scene loop) */}
          <div className="relative">
            <HeroPhoneShowcase />
          </div>
        </div>

        <style>{`@keyframes heroGradient { to { background-position: 200% center; } }`}</style>
      </section>

      {/* ───────────── AVANT / APRÈS — emotional reframe ───────────── */}
      <section id="proof" className="relative py-16 border-y" style={{ borderColor: C.hairline, background: 'white' }}>
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-10">
            <p className="text-xs font-bold uppercase tracking-[0.25em]" style={{ color: C.terracotta }}>
              Le quotidien d'un commerçant
            </p>
            <p className="font-['Cormorant_Garamond'] text-2xl md:text-3xl font-bold mt-2" style={{ color: C.inkDeep }}>
              Quatre petits riens qui changent tout.
            </p>
          </div>

          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              {
                before: 'Carte oubliée chez 8 clients sur 10',
                after: 'Carte toujours dans la poche',
                tone: C.sky, bg: C.azure,
              },
              {
                before: 'Anniversaires oubliés',
                after: 'Souhaités automatiquement',
                tone: C.rose, bg: C.shellPink,
              },
              {
                before: 'Aucune idée de qui est parti',
                after: 'Liste claire des clients à reconquérir',
                tone: C.lavender, bg: C.lilac,
              },
              {
                before: 'SMS de masse à 0,08 €',
                after: 'Notifications push à 0 €',
                tone: C.sage, bg: C.meadow,
              },
            ].map((row, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 12 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.45, delay: i * 0.08 }}
                className="rounded-2xl border overflow-hidden"
                style={{ borderColor: C.hairline, background: 'white' }}
              >
                {/* Avant */}
                <div className="px-5 py-4 border-b" style={{ borderColor: C.hairline, background: C.sand }}>
                  <p className="text-[10px] font-bold uppercase tracking-[0.2em] mb-1.5" style={{ color: C.inkFaint }}>
                    Avant
                  </p>
                  <p className="text-sm leading-snug line-through opacity-70" style={{ color: C.inkMute }}>
                    {row.before}
                  </p>
                </div>
                {/* Après */}
                <div className="px-5 py-4" style={{ background: row.bg }}>
                  <p className="text-[10px] font-bold uppercase tracking-[0.2em] mb-1.5" style={{ color: row.tone }}>
                    Avec FidClic
                  </p>
                  <p className="text-sm font-bold leading-snug" style={{ color: C.inkDeep }}>
                    {row.after}
                  </p>
                </div>
              </motion.div>
            ))}
          </div>

          {/* Trust pills below */}
          <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 mt-10 text-xs" style={{ color: C.inkMute }}>
            <span className="flex items-center gap-1.5">
              <Check size={14} style={{ color: C.sage }} /> Conçu en France
            </span>
            <span className="flex items-center gap-1.5">
              <Check size={14} style={{ color: C.sage }} /> Hébergé en France
            </span>
            <span className="flex items-center gap-1.5">
              <Check size={14} style={{ color: C.sage }} /> RGPD natif
            </span>
            <span className="flex items-center gap-1.5">
              <Check size={14} style={{ color: C.sage }} /> Sans application à télécharger
            </span>
          </div>
        </div>
      </section>

      {/* ───────────── PROBLEM / OUTCOME ───────────── */}
      <section className="py-20 lg:py-28">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <Eyebrow color={C.coral} bg={C.shellPink}>Le changement</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold leading-tight">
              La carte en carton d'hier.<br/>
              <span style={{ color: C.terracotta }}>La fidélité d'aujourd'hui.</span>
            </h2>
          </div>
          <div className="grid md:grid-cols-2 gap-6 lg:gap-8">
            {/* Old way */}
            <div className="rounded-3xl p-8 border-2 relative overflow-hidden"
                 style={{ borderColor: C.hairline, background: C.sand }}>
              <span className="inline-block px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider mb-4"
                    style={{ background: 'rgba(140,134,128,0.15)', color: C.inkFaint }}>
                Avant
              </span>
              <h3 className="font-['Cormorant_Garamond'] text-3xl font-bold mb-4" style={{ color: C.inkSoft }}>
                Cartes en carton et tâtonnement
              </h3>
              <ul className="space-y-3 text-sm" style={{ color: C.inkMute }}>
                <li className="flex gap-2">✗ Le client la perd au bout de 3 semaines</li>
                <li className="flex gap-2">✗ Vous ne savez pas qui revient, ni qui ne revient plus</li>
                <li className="flex gap-2">✗ Aucun moyen de relancer les clients endormis</li>
                <li className="flex gap-2">✗ Les anniversaires passent inaperçus</li>
                <li className="flex gap-2">✗ Le marketing, c'est «&nbsp;poster sur Instagram et croiser les doigts&nbsp;»</li>
              </ul>
            </div>
            {/* New way */}
            <div className="rounded-3xl p-8 border-2 relative overflow-hidden"
                 style={{
                   borderColor: C.terracotta + '30',
                   background: `linear-gradient(135deg, ${C.shellPink} 0%, ${C.butter} 50%, ${C.lilac} 100%)`,
                 }}>
              <div aria-hidden="true" className="absolute -top-12 -right-12 w-44 h-44 rounded-full blur-3xl opacity-50"
                   style={{ background: C.rose }} />
              <span className="inline-block px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider mb-4 relative"
                    style={{ background: C.terracotta, color: 'white' }}>
                Avec FidClic
              </span>
              <h3 className="font-['Cormorant_Garamond'] text-3xl font-bold mb-4 relative" style={{ color: C.inkDeep }}>
                Une carte qui travaille pour vous
              </h3>
              <ul className="space-y-3 text-sm relative" style={{ color: C.inkSoft }}>
                <li className="flex gap-2"><Check size={18} style={{ color: C.sage }} /> La carte vit dans Apple Wallet — jamais perdue</li>
                <li className="flex gap-2"><Check size={18} style={{ color: C.sage }} /> Tableau de bord en direct — chaque visite, chaque tampon, chaque euro</li>
                <li className="flex gap-2"><Check size={18} style={{ color: C.sage }} /> Détection des clients endormis, message personnalisé envoyé</li>
                <li className="flex gap-2"><Check size={18} style={{ color: C.sage }} /> Anniversaires souhaités automatiquement — chaque année</li>
                <li className="flex gap-2"><Check size={18} style={{ color: C.sage }} /> L'IA vous dit quels clients contacter cette semaine</li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* ───────────── SECTOR USE-CASES — speaks directly to the visitor ───────────── */}
      <section className="relative py-20 lg:py-28 overflow-hidden"
               style={{ background: `linear-gradient(180deg, ${C.cream} 0%, ${C.sand} 100%)` }}>
        <motion.div aria-hidden="true" className="absolute top-1/3 -left-32 w-[420px] h-[420px] rounded-full blur-3xl opacity-30 pointer-events-none"
                    style={{ background: `radial-gradient(circle, ${C.ochre} 0%, transparent 70%)` }}
                    animate={{ x: [0, 40, 0], y: [0, -30, 0] }} transition={{ duration: 22, repeat: Infinity, ease: 'easeInOut' }} />

        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-14">
            <Eyebrow color={C.ochre} bg={C.butter}>Conçu pour vous</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold leading-tight">
              Quel que soit votre métier,<br/>
              <span style={{ color: C.ochre }}>FidClic s'adapte.</span>
            </h2>
            <p className="text-base mt-5 max-w-2xl mx-auto" style={{ color: C.inkMute }}>
              Restauration, beauté, mode, artisanat, services de quartier — chaque commerçant
              configure FidClic à son rythme et à ses règles. Voici ce que ça donne, concrètement.
            </p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[
              {
                icon: '☕',
                title: 'Café · Bistrot',
                lead: 'Un café avec 800 clients fidèles.',
                story: 'FidClic relance automatiquement les 47 qui ne sont pas revenus depuis 3 semaines. Les anniversaires sont souhaités. Les habitués du midi reçoivent une offre pour le mardi creux.',
                wins: [
                  'Mardis remplis grâce à une campagne ciblée',
                  '+1 visite par mois en moyenne sur les habitués',
                  'Plus aucun anniversaire oublié',
                ],
                color: C.terracotta, bg: C.shellPink,
              },
              {
                icon: '🥐',
                title: 'Boulangerie · Pâtisserie',
                lead: 'Une boulangerie qui voit 400 clients par jour.',
                story: 'Carte tamponnée automatiquement à chaque passage en caisse. Au 10ᵉ tampon, le client reçoit une viennoiserie offerte par notification push. Pas d\'application à installer.',
                wins: [
                  'Adhésion en 2 secondes au comptoir',
                  'Suivi de chaque client sans effort',
                  'Communication directe sans SMS payants',
                ],
                color: C.ochre, bg: C.butter,
              },
              {
                icon: '🍽️',
                title: 'Restaurant · Brasserie',
                lead: 'Un restaurant avec 15 réservations par soir.',
                story: 'Vos meilleurs clients reçoivent une attention pour leur anniversaire. Les habitudes de fréquentation s\'affichent en direct. Les VIP qui passent à proximité reçoivent un mot avant le service.',
                wins: [
                  'Tableau de bord clair, par soir et par table',
                  'VIP reconnus dès l\'arrivée',
                  'Promotions ciblées pour les soirs creux',
                ],
                color: C.lavender, bg: C.lilac,
              },
              {
                icon: '✂️',
                title: 'Salon de coiffure · Barbier',
                lead: 'Un salon avec 200 clientes régulières.',
                story: 'Le rendez-vous mensuel devient une relation suivie. La carte se remplit à chaque visite — au 8ᵉ passage, un soin offert. Les clientes qui n\'ont pas pris rendez-vous depuis 8 semaines reçoivent une relance personnalisée.',
                wins: [
                  'Cycle de fidélité aligné sur le rythme mensuel',
                  'Réactivation des clientes qui s\'éloignent',
                  'Promotions ciblées par type de prestation',
                ],
                color: C.rose, bg: C.blush,
              },
              {
                icon: '👗',
                title: 'Boutique mode · Concept store',
                lead: 'Une boutique avec 1 200 clientes saisonnières.',
                story: 'Les VIP sont prévenues en avant-première lors des nouvelles collections. Les anniversaires donnent droit à un avantage privé. Les clientes qui ont acheté plus de trois fois passent automatiquement au statut Or.',
                wins: [
                  'Avant-premières exclusives pour vos VIP',
                  'Reconnaissance immédiate en magasin',
                  'Suivi du parcours d\'achat sur la durée',
                ],
                color: C.sky, bg: C.azure,
              },
              {
                icon: '🌿',
                title: 'Fleuriste · Boutique cadeau',
                lead: 'Un fleuriste avec 350 clients réguliers.',
                story: 'Les clients qui passent chaque vendredi soir reçoivent une attention. Les anniversaires de mariage, fêtes des mères et grandes occasions sont anticipés par notification push, quelques jours avant la date.',
                wins: [
                  'Rappel automatique des grandes occasions',
                  'Habitudes hebdomadaires reconnues',
                  'Notification push avant chaque date clé',
                ],
                color: C.sage, bg: C.meadow,
              },
            ].map((sector, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: i * 0.1 }}
                whileHover={{ y: -6, scale: 1.01 }}
                className="relative rounded-3xl p-7 border-2 flex flex-col overflow-hidden"
                style={{
                  background: `
                    radial-gradient(circle at 100% 0%, ${sector.bg} 0%, transparent 50%),
                    radial-gradient(circle at 0% 100%, ${sector.bg} 0%, transparent 60%),
                    linear-gradient(135deg, white 0%, #FDFBF7 100%)
                  `,
                  borderColor: `${sector.color}33`,
                  boxShadow: `0 10px 30px -12px ${sector.color}33`,
                }}
              >
                {/* Animated decorative orbs */}
                <motion.div
                  aria-hidden="true"
                  className="absolute -top-12 -right-12 w-32 h-32 rounded-full blur-3xl pointer-events-none"
                  style={{ background: sector.color, opacity: 0.18 }}
                  animate={{ scale: [1, 1.15, 1] }}
                  transition={{ duration: 5 + i * 0.4, repeat: Infinity, ease: 'easeInOut' }}
                />
                <motion.div
                  aria-hidden="true"
                  className="absolute -bottom-16 -left-16 w-32 h-32 rounded-full blur-3xl pointer-events-none"
                  style={{ background: sector.color, opacity: 0.12 }}
                  animate={{ scale: [1, 1.2, 1] }}
                  transition={{ duration: 6 + i * 0.3, repeat: Infinity, ease: 'easeInOut', delay: 1 }}
                />

                <div className="relative flex items-center gap-3 mb-4">
                  <div className="w-12 h-12 rounded-2xl flex items-center justify-center text-2xl shrink-0 shadow-md"
                       style={{
                         background: `linear-gradient(135deg, white 0%, ${sector.bg} 100%)`,
                         border: `1px solid ${sector.color}33`,
                       }}>
                    {sector.icon}
                  </div>
                  <h3 className="font-['Cormorant_Garamond'] text-2xl font-bold" style={{ color: C.inkDeep }}>
                    {sector.title}
                  </h3>
                </div>

                <p className="relative text-sm font-bold italic mb-2" style={{ color: sector.color }}>
                  {sector.lead}
                </p>
                <p className="relative text-sm leading-relaxed mb-5" style={{ color: C.inkSoft }}>
                  {sector.story}
                </p>

                <div className="relative mt-auto pt-4 border-t space-y-2"
                     style={{ borderColor: `${sector.color}22` }}>
                  {sector.wins.map((w, j) => (
                    <div key={j} className="flex items-start gap-2 text-xs" style={{ color: C.inkSoft }}>
                      <span className="w-4 h-4 rounded-full flex items-center justify-center shrink-0 mt-0.5"
                            style={{ background: `${sector.color}1F`, border: `1px solid ${sector.color}55` }}>
                        <Check size={10} style={{ color: sector.color }} strokeWidth={3} />
                      </span>
                      <span className="font-medium">{w}</span>
                    </div>
                  ))}
                </div>
              </motion.div>
            ))}
          </div>

          <p className="text-xs text-center mt-8 italic" style={{ color: C.inkFaint }}>
            Scénarios illustratifs — chaque commerçant configure FidClic selon ses propres règles.
          </p>
        </div>
      </section>

      {/* ───────────── FACTURATION ÉLECTRONIQUE — the 2026 reform hook ─────────────
          Placement is deliberate: this sits right after the sector use-cases and
          before the loyalty feature grid, because the reform is a DEADLINE, and a
          deadline is the strongest reason a TPE clicks today. Design language is
          intentionally the existing pastel/bento system — a 21st.dev-inspired
          redesign can drop in later without touching the copy or the routes. */}
      <section id="facturation" className="relative py-20 lg:py-28 overflow-hidden"
               style={{ background: `linear-gradient(180deg, ${C.cream} 0%, ${C.azure}55 100%)` }}>
        <div aria-hidden="true" className="absolute -top-24 -right-24 w-96 h-96 rounded-full blur-3xl opacity-40"
             style={{ background: `radial-gradient(circle, ${C.sky}66, transparent 70%)` }} />
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative">
          <div className="text-center mb-14">
            <Eyebrow color={C.sky} bg={C.azure}>Nouveau module</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold leading-tight">
              La facturation électronique,<br />
              <span className="bg-clip-text text-transparent"
                    style={{ backgroundImage: `linear-gradient(135deg, ${C.sky} 0%, ${C.lavender} 100%)` }}>
                sans y penser une seule seconde
              </span>
            </h2>
            <p className="mt-5 text-lg max-w-2xl mx-auto" style={{ color: C.inkMute }}>
              Dès le 1<sup>er</sup> septembre 2026, toutes les entreprises doivent pouvoir
              <b> recevoir</b> des factures électroniques. Émission obligatoire pour les TPE
              en septembre 2027. FidClic s'occupe de tout — vous, vous facturez comme avant.
            </p>
          </div>

          {/* deadline strip — urgency without drama */}
          <div className="flex flex-wrap justify-center gap-3 mb-14">
            {[
              { d: '1 sept. 2026', t: 'Réception obligatoire — toutes les entreprises', c: C.terracotta, bg: C.shellPink },
              { d: '1 sept. 2027', t: 'Émission obligatoire — TPE, PME, micro', c: C.lavender, bg: C.lilac },
              { d: '1 janv. 2027', t: 'Fin du régime simplifié de TVA (CA12)', c: C.teal, bg: C.mint },
            ].map((x) => (
              <div key={x.d} className="flex items-center gap-2.5 px-4 py-2.5 rounded-2xl border bg-white/70 backdrop-blur"
                   style={{ borderColor: C.hairline }}>
                <CalendarClock size={16} style={{ color: x.c }} />
                <span className="text-sm font-bold" style={{ color: x.c }}>{x.d}</span>
                <span className="text-sm" style={{ color: C.inkMute }}>{x.t}</span>
              </div>
            ))}
          </div>

          {/* four pillars */}
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-5">
            {[
              { icon: ReceiptText, c: C.sky, bg: C.azure, title: 'Émettre en conforme',
                body: "Vos factures partent au format légal (Factur-X) via une plateforme agréée. Vous remplissez un formulaire simple — le reste est invisible." },
              { icon: Inbox, c: C.teal, bg: C.mint, title: 'Recevoir vos fournisseurs',
                body: "Les factures de vos fournisseurs arrivent directement dans votre espace, classées, prêtes pour votre comptable. Fini les PDF perdus dans les mails." },
              { icon: BarChart3, c: C.lavender, bg: C.lilac, title: 'E-reporting automatique',
                body: "Vos ventes aux particuliers sont transmises à l'administration aux bonnes échéances, sans que vous ayez à y penser." },
              { icon: FileCheck2, c: C.sage, bg: C.meadow, title: 'Avoirs & suivi',
                body: "Une erreur ? On corrige par un avoir, comme la loi l'exige. Et vous suivez chaque facture : envoyée, acceptée, refusée, payée." },
            ].map((f) => {
              const Icon = f.icon;
              return (
                <div key={f.title} className="rounded-3xl p-6 bg-white border transition-all hover:-translate-y-1 hover:shadow-lg"
                     style={{ borderColor: C.hairline }}>
                  <div className="w-11 h-11 rounded-2xl flex items-center justify-center mb-4"
                       style={{ background: f.bg }}>
                    <Icon size={20} style={{ color: f.c }} />
                  </div>
                  <h3 className="font-bold text-lg mb-2" style={{ color: C.inkDeep }}>{f.title}</h3>
                  <p className="text-sm leading-relaxed" style={{ color: C.inkMute }}>{f.body}</p>
                </div>
              );
            })}
          </div>

          {/* Bouclier Fiscal — the differentiator, given its own stage */}
          <div className="mt-8 rounded-3xl border overflow-hidden bg-white" style={{ borderColor: C.hairline }}>
            <div className="grid lg:grid-cols-2">
              <div className="p-8 lg:p-10">
                <Eyebrow color={C.terracotta} bg={C.shellPink}>Exclusivité FidClic</Eyebrow>
                <h3 className="font-['Cormorant_Garamond'] text-3xl font-bold mt-3 mb-3" style={{ color: C.inkDeep }}>
                  Le Bouclier Fiscal
                </h3>
                <p className="text-base leading-relaxed mb-5" style={{ color: C.inkMute }}>
                  Les autres logiciels vous disent « c'est envoyé ». FidClic vous dit
                  <b> « et voici ce qui cloche »</b> : un score de cohérence, mis à jour en continu,
                  avec le détail de chaque point — pour que vous voyiez vos données comme
                  l'administration les verra.
                </p>
                <ul className="space-y-2.5">
                  {[
                    'Factures refusées ou en erreur, repérées immédiatement',
                    'Conformité DGFiP et statut de votre plateforme, en un coup d\'œil',
                    'Cohérence achats / ventes surveillée mois après mois',
                    'Chaque point du score expliqué — jamais de boîte noire',
                  ].map((li) => (
                    <li key={li} className="flex items-start gap-2.5 text-sm" style={{ color: C.inkSoft }}>
                      <Check size={16} className="mt-0.5 shrink-0" style={{ color: C.sage }} />
                      {li}
                    </li>
                  ))}
                </ul>
                <p className="text-xs italic mt-5" style={{ color: C.inkFaint }}>
                  Indicateur informatif de cohérence — ni conseil fiscal, ni ECF.
                </p>
              </div>

              {/* score mockup */}
              <div className="p-8 lg:p-10 flex items-center justify-center"
                   style={{ background: `linear-gradient(135deg, ${C.sand} 0%, ${C.butter}88 100%)` }}>
                <div className="w-full max-w-sm rounded-3xl bg-white border p-6 shadow-sm" style={{ borderColor: C.hairline }}>
                  <div className="flex items-start gap-5">
                    <div className="shrink-0 text-center">
                      <div className="w-24 h-24 rounded-full flex items-center justify-center"
                           style={{ background: `conic-gradient(${C.sage} 86%, ${C.hairline} 0)` }}>
                        <div className="w-[76px] h-[76px] rounded-full bg-white flex flex-col items-center justify-center">
                          <span className="text-2xl font-extrabold" style={{ color: C.sage }}>86</span>
                          <span className="text-[10px]" style={{ color: C.inkFaint }}>/100</span>
                        </div>
                      </div>
                      <div className="mt-2 text-xs font-bold flex items-center justify-center gap-1" style={{ color: C.sage }}>
                        <ShieldCheck size={12} /> Conforme
                      </div>
                    </div>
                    <div className="flex-1">
                      <div className="text-sm font-bold mb-2" style={{ color: C.inkDeep }}>Pourquoi ce score ?</div>
                      {[
                        ['Base', '100', C.inkMute],
                        ['1 facture refusée non corrigée', '−15', C.terracotta],
                        ['Aucune anomalie TVA détectée', '±0', C.sage],
                      ].map(([l, v, col]) => (
                        <div key={l} className="flex items-center justify-between text-xs py-1">
                          <span style={{ color: C.inkMute }}>{l}</span>
                          <span className="font-bold" style={{ color: col }}>{v}</span>
                        </div>
                      ))}
                      <div className="flex items-center justify-between text-xs pt-2 mt-1 border-t"
                           style={{ borderColor: C.hairline }}>
                        <span className="font-bold" style={{ color: C.inkDeep }}>Score</span>
                        <span className="font-bold" style={{ color: C.sage }}>86/100</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="text-center mt-10">
            {/* Primary CTA goes to the FULL page, not to signup: this section is
                a teaser, the deep story lives at /facturation-electronique. */}
            <Link to="/facturation-electronique"
                  className="inline-flex items-center gap-2 text-white px-7 py-3.5 rounded-full font-semibold shadow-md transition-all hover:shadow-lg hover:-translate-y-0.5"
                  style={{ background: `linear-gradient(135deg, ${C.sky} 0%, ${C.lavender} 100%)` }}>
              Tout savoir sur la réforme 2026 <ArrowRight size={18} />
            </Link>
            <p className="text-xs mt-3" style={{ color: C.inkFaint }}>
              Module optionnel — activez-le quand vous voulez, votre programme de fidélité continue sans changement.
            </p>
          </div>
        </div>
      </section>

      {/* ───────────── ESPACE CABINET — the accountant channel ─────────────
          Separate audience, separate section, separate CTA. An accountant who
          lands here should immediately feel this was built for THEM, not for a
          merchant — the whole distribution strategy depends on that. */}
      <section id="cabinet" className="relative py-20 lg:py-28 overflow-hidden"
               style={{ background: `linear-gradient(180deg, #FFFFFF 0%, ${C.lilac}66 100%)` }}>
        <div aria-hidden="true" className="absolute -bottom-32 -left-24 w-[28rem] h-[28rem] rounded-full blur-3xl opacity-40"
             style={{ background: `radial-gradient(circle, ${C.lavender}55, transparent 70%)` }} />
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            {/* copy */}
            <div>
              <Eyebrow color={C.lavender} bg={C.lilac}>Experts-comptables</Eyebrow>
              <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold leading-tight mt-3">
                Tous vos dossiers.<br />
                <span className="bg-clip-text text-transparent"
                      style={{ backgroundImage: `linear-gradient(135deg, ${C.lavender} 0%, ${C.rose} 100%)` }}>
                  Un seul écran.
                </span>
              </h2>
              <p className="mt-5 text-lg leading-relaxed" style={{ color: C.inkMute }}>
                Vos clients seront répartis sur des dizaines de plateformes différentes.
                L'Espace Cabinet vous rend la vue d'ensemble : chaque dossier, son état de
                conformité, ce qui bloque — et qui s'en occupe.
              </p>

              <div className="mt-7 space-y-4">
                {[
                  { icon: FolderKanban, c: C.lavender, bg: C.lilac, t: 'Portefeuille priorisé',
                    d: "Les dossiers à risque remontent en haut, automatiquement. Vous savez en 30 secondes où passer votre journée." },
                  { icon: AlertTriangle, c: C.terracotta, bg: C.shellPink, t: 'Rien ne se perd',
                    d: "Chaque rejet, chaque erreur devient un dossier assigné, avec une échéance — plus jamais noyé dans les emails." },
                  { icon: Users, c: C.teal, bg: C.mint, t: 'Votre équipe, vos accès',
                    d: "Chaque collaborateur ne voit que ses dossiers. Vous, vous voyez tout — y compris qui avance sur quoi." },
                  { icon: FileCheck2, c: C.sage, bg: C.meadow, t: 'Export vers votre logiciel',
                    d: "Gardez votre outil de production. Un export propre au format FEC, et vos écritures sont chez vous." },
                ].map((f) => {
                  const Icon = f.icon;
                  return (
                    <div key={f.t} className="flex gap-4">
                      <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
                           style={{ background: f.bg }}>
                        <Icon size={18} style={{ color: f.c }} />
                      </div>
                      <div>
                        <div className="font-bold text-base" style={{ color: C.inkDeep }}>{f.t}</div>
                        <div className="text-sm mt-0.5 leading-relaxed" style={{ color: C.inkMute }}>{f.d}</div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="mt-8 flex flex-wrap items-center gap-3">
                {/* Straight to the accountant page — their whole story lives there. */}
                <Link to="/experts-comptables"
                      className="inline-flex items-center gap-2 text-white px-7 py-3.5 rounded-full font-semibold shadow-md transition-all hover:shadow-lg hover:-translate-y-0.5"
                      style={{ background: `linear-gradient(135deg, ${C.lavender} 0%, ${C.rose} 100%)` }}>
                  Découvrir l'Espace Cabinet <ArrowRight size={18} />
                </Link>
                <span className="text-sm" style={{ color: C.inkFaint }}>
                  Vos données restent exportables — à tout moment, sans condition.
                </span>
              </div>
            </div>

            {/* dashboard mockup */}
            <div className="relative">
              <div className="rounded-3xl bg-white border shadow-xl overflow-hidden" style={{ borderColor: C.hairline }}>
                <div className="flex items-center gap-2 px-4 py-3 border-b" style={{ background: C.sand, borderColor: C.hairline }}>
                  <div className="w-2.5 h-2.5 rounded-full" style={{ background: C.coral }} />
                  <div className="w-2.5 h-2.5 rounded-full" style={{ background: C.ochre }} />
                  <div className="w-2.5 h-2.5 rounded-full" style={{ background: C.sage }} />
                  <div className="flex-1 text-center text-[11px]" style={{ color: C.inkFaint }}>
                    Espace Cabinet — 45 dossiers
                  </div>
                </div>
                <div className="p-5">
                  <div className="grid grid-cols-3 gap-2.5 mb-4">
                    {[['3', 'Action requise', C.terracotta, C.shellPink],
                      ['9', 'À vérifier', C.ochre, C.butter],
                      ['33', 'Conformes', C.sage, C.meadow]].map(([n, l, c, bg]) => (
                      <div key={l} className="rounded-2xl p-3 text-center" style={{ background: bg }}>
                        <div className="text-xl font-extrabold" style={{ color: c }}>{n}</div>
                        <div className="text-[10px] mt-0.5" style={{ color: C.inkMute }}>{l}</div>
                      </div>
                    ))}
                  </div>
                  <div className="space-y-2">
                    {[
                      ['Café Lumière', '58/100', C.terracotta, '2 factures refusées', 'M'],
                      ['Boulangerie Dupont', '76/100', C.ochre, 'DGFiP non activée', 'L'],
                      ['Salon Élise', '84/100', C.ochre, '3 à revoir', 'M'],
                      ['Garage Martin', '100/100', C.sage, 'Conforme', 'L'],
                    ].map(([name, score, c, note, who]) => (
                      <div key={name} className="flex items-center gap-2.5 rounded-2xl border px-3 py-2.5"
                           style={{ borderColor: C.hairline }}>
                        <span className="w-2 h-2 rounded-full shrink-0" style={{ background: c }} />
                        <div className="flex-1 min-w-0">
                          <div className="text-[13px] font-bold truncate" style={{ color: C.inkDeep }}>{name}</div>
                          <div className="text-[11px]" style={{ color: c }}>{note}</div>
                        </div>
                        <span className="text-[11px] font-bold" style={{ color: c }}>{score}</span>
                        <span className="w-6 h-6 rounded-full text-[10px] font-bold flex items-center justify-center shrink-0"
                              style={{ background: C.lilac, color: C.lavender }}>{who}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              {/* floating badge */}
              <div className="absolute -bottom-4 -right-2 rounded-2xl bg-white border px-4 py-3 shadow-lg hidden sm:block"
                   style={{ borderColor: C.hairline }}>
                <div className="flex items-center gap-2">
                  <Building2 size={16} style={{ color: C.lavender }} />
                  <div>
                    <div className="text-[11px] font-bold" style={{ color: C.inkDeep }}>Un seul login</div>
                    <div className="text-[10px]" style={{ color: C.inkFaint }}>pour tout votre portefeuille</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ───────────── BENTO FEATURE GRID ───────────── */}
      <section id="features" className="relative py-20 lg:py-28" style={{ background: 'white' }}>
        <div aria-hidden="true" className="absolute top-0 left-0 right-0 h-1"
             style={{ background: `linear-gradient(90deg, ${C.terracotta} 0%, ${C.rose} 20%, ${C.lavender} 40%, ${C.sky} 60%, ${C.teal} 80%, ${C.sage} 100%)` }} />
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-14">
            <Eyebrow color={C.lavender} bg={C.lilac}>Fonctionnalités</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold leading-tight">
              Tout ce qu'il faut pour fidéliser,<br/>
              <span style={{ color: C.lavender }}>rien dont vous n'avez pas besoin.</span>
            </h2>
          </div>

          {/* Bento — 6 cards in a varied grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5 auto-rows-fr">
            {/* LARGE — Wallet integration (with real card preview as visual) */}
            <BentoCard className="md:col-span-2 md:row-span-2" tint={C.azure} border={`${C.sky}40`} glow={C.sky + '50'}>
              <div className="grid md:grid-cols-[1.1fr,0.9fr] gap-6 items-stretch">
                {/* LEFT — text */}
                <div>
                  <div className="w-12 h-12 rounded-xl flex items-center justify-center mb-5"
                       style={{ background: 'white', boxShadow: `0 4px 12px ${C.sky}30` }}>
                    <Smartphone size={24} style={{ color: C.sky }} />
                  </div>
                  <h3 className="font-['Cormorant_Garamond'] text-3xl font-bold mb-3" style={{ color: C.inkDeep }}>
                    Apple Wallet & Google Wallet, en natif
                  </h3>
                  <p className="text-base leading-relaxed mb-5" style={{ color: C.inkMute }}>
                    Vos clients ajoutent leur carte en un clic. Elle vit dans leur portefeuille mobile
                    à côté de leurs cartes bancaires. Aucune application à télécharger. Mise à jour en temps réel.
                  </p>
                  <div className="flex items-center gap-3 mt-6">
                    <div className="flex-1 rounded-xl p-3 border" style={{ background: 'white', borderColor: C.hairline }}>
                      <p className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: C.inkFaint }}>Apple Wallet</p>
                      <p className="text-sm font-bold mt-1" style={{ color: C.inkDeep }}>iOS · iPadOS</p>
                    </div>
                    <div className="flex-1 rounded-xl p-3 border" style={{ background: 'white', borderColor: C.hairline }}>
                      <p className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: C.inkFaint }}>Google Wallet</p>
                      <p className="text-sm font-bold mt-1" style={{ color: C.inkDeep }}>Android · Chrome</p>
                    </div>
                  </div>
                </div>

                {/* RIGHT — actual wallet card preview, tilted, with rainbow halo */}
                <div className="relative hidden md:flex items-center justify-center">
                  {/* Conic-gradient rainbow halo behind the card */}
                  <motion.div
                    aria-hidden="true"
                    className="absolute rounded-[40px] blur-2xl pointer-events-none"
                    style={{
                      width: '110%', height: '85%',
                      background: `conic-gradient(from 90deg, ${C.terracotta}, ${C.ochre}, ${C.rose}, ${C.lavender}, ${C.sky}, ${C.teal}, ${C.terracotta})`,
                      opacity: 0.55,
                    }}
                    animate={{ rotate: [0, 360] }}
                    transition={{ duration: 24, repeat: Infinity, ease: 'linear' }}
                  />
                  {/* Floating "live" badge */}
                  <motion.div
                    aria-hidden="true"
                    className="absolute -left-2 top-3 z-10 hidden md:flex items-center gap-1.5 px-2.5 py-1 rounded-full shadow-xl border"
                    style={{ background: 'white', borderColor: C.hairline }}
                    animate={{ y: [0, -6, 0] }}
                    transition={{ duration: 3.6, repeat: Infinity, ease: 'easeInOut' }}
                  >
                    <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: C.sage }} />
                    <span className="text-[9px] font-bold" style={{ color: C.inkDeep }}>Mise à jour live</span>
                  </motion.div>
                  {/* Floating "+25 pts" pill */}
                  <motion.div
                    aria-hidden="true"
                    className="absolute -right-2 bottom-12 z-10 hidden md:flex items-center gap-1 px-2.5 py-1 rounded-full shadow-xl"
                    style={{ background: `linear-gradient(135deg, ${C.terracotta}, ${C.rose})`, color: 'white' }}
                    animate={{ y: [0, 6, 0] }}
                    transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut', delay: 0.6 }}
                  >
                    <Sparkles size={10} />
                    <span className="text-[9px] font-bold">+25 pts</span>
                  </motion.div>
                  {/* The actual card */}
                  <motion.div
                    initial={{ opacity: 0, rotate: 0, y: 10 }}
                    whileInView={{ opacity: 1, rotate: 6, y: 0 }}
                    viewport={{ once: true }}
                    transition={{ duration: 0.6 }}
                    className="relative origin-center"
                    style={{ filter: 'drop-shadow(0 22px 40px rgba(28,25,23,0.28))' }}
                  >
                    {/* Same card the merchant sees in the Card Designer
                        — using LandingDemoCard keeps every demo card on
                        the landing page visually consistent with the
                        actual product. */}
                    <div style={{ width: 260 }}>
                      <LandingDemoCard compact />
                    </div>
                  </motion.div>
                  {/* "Aperçu réel" tag floating below */}
                  <span className="absolute bottom-1 right-2 px-2.5 py-1 rounded-full bg-white/95 backdrop-blur text-[9px] font-bold uppercase tracking-widest border z-10"
                        style={{ color: C.terracotta, borderColor: `${C.terracotta}33`, boxShadow: `0 4px 12px ${C.terracotta}33` }}>
                    Aperçu réel
                  </span>
                </div>
              </div>
            </BentoCard>

            {/* SMALL — Voix de marque (with message-bubble preview) */}
            <BentoCard tint={C.lilac} border={`${C.lavender}40`} glow={C.lavender + '50'}>
              <div className="w-11 h-11 rounded-xl flex items-center justify-center mb-4"
                   style={{ background: 'white', boxShadow: `0 4px 12px ${C.lavender}30` }}>
                <BrainCircuit size={22} style={{ color: C.lavender }} />
              </div>
              <h3 className="text-xl font-bold mb-2" style={{ color: C.inkDeep }}>Voix de marque protégée</h3>
              <p className="text-sm leading-relaxed mb-4" style={{ color: C.inkMute }}>
                Chaque message sonne comme vous. L'IA apprend votre ton à partir de vos anciennes campagnes.
              </p>
              {/* Chat-bubble preview — vivid gradient backdrop with sparkle */}
              <div className="relative rounded-2xl p-3.5 border overflow-hidden"
                   style={{
                     background: `linear-gradient(135deg, white 0%, ${C.lilac} 60%, ${C.shellPink} 100%)`,
                     borderColor: `${C.lavender}55`,
                     boxShadow: `0 6px 20px -8px ${C.lavender}55`,
                   }}>
                <motion.div
                  aria-hidden="true"
                  className="absolute -top-6 -right-6 w-20 h-20 rounded-full blur-2xl opacity-60 pointer-events-none"
                  style={{ background: C.rose }}
                  animate={{ scale: [1, 1.15, 1] }}
                  transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}
                />
                <div className="relative rounded-xl px-3 py-2.5 backdrop-blur-sm"
                     style={{
                       background: `linear-gradient(135deg, ${C.lavender}25 0%, ${C.rose}20 100%)`,
                       border: `1px solid ${C.lavender}33`,
                     }}>
                  <div className="flex items-center gap-1.5 mb-1">
                    <Sparkles size={10} style={{ color: C.lavender }} />
                    <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: C.lavender }}>
                      Votre voix
                    </p>
                  </div>
                  <p className="text-xs leading-snug font-medium" style={{ color: C.inkDeep }}>
                    «&nbsp;Marie, on a remarqué votre absence — un café offert vous attend cette semaine.&nbsp;»
                  </p>
                </div>
              </div>
            </BentoCard>

            {/* SMALL — Sentiment / Avis (with stars + topic bars) */}
            <BentoCard tint={C.shellPink} border={`${C.coral}40`} glow={C.coral + '50'}>
              <div className="w-11 h-11 rounded-xl flex items-center justify-center mb-4"
                   style={{ background: 'white', boxShadow: `0 4px 12px ${C.coral}30` }}>
                <MessageSquare size={22} style={{ color: C.coral }} />
              </div>
              <h3 className="text-xl font-bold mb-2" style={{ color: C.inkDeep }}>Analyse des avis clients</h3>
              <p className="text-sm leading-relaxed mb-4" style={{ color: C.inkMute }}>
                Avis classés par sujet — service, propreté, prix, accueil. Vous voyez ce qui marche, ce qui coince.
              </p>
              {/* Stars + topic distribution — gradient backdrop, twinkling stars */}
              <div className="relative rounded-2xl p-3.5 border overflow-hidden space-y-2.5"
                   style={{
                     background: `linear-gradient(135deg, white 0%, ${C.shellPink} 60%, ${C.butter} 100%)`,
                     borderColor: `${C.coral}55`,
                     boxShadow: `0 6px 20px -8px ${C.coral}55`,
                   }}>
                <motion.div
                  aria-hidden="true"
                  className="absolute -top-6 -left-6 w-20 h-20 rounded-full blur-2xl opacity-60 pointer-events-none"
                  style={{ background: C.ochre }}
                  animate={{ scale: [1, 1.15, 1] }}
                  transition={{ duration: 5, repeat: Infinity, ease: 'easeInOut' }}
                />
                <div className="relative flex items-center justify-between">
                  <div className="flex gap-0.5">
                    {[0,1,2,3,4].map((i) => (
                      <motion.span
                        key={i}
                        animate={{ scale: [1, 1.18, 1] }}
                        transition={{ duration: 2.4, repeat: Infinity, delay: i * 0.18, ease: 'easeInOut' }}
                        style={{ display: 'inline-flex' }}
                      >
                        <Star size={13} fill={C.ochre} stroke={C.ochre} />
                      </motion.span>
                    ))}
                  </div>
                  <span className="text-xs font-bold px-2 py-0.5 rounded-full"
                        style={{ background: 'white', color: C.ochre, border: `1px solid ${C.ochre}55` }}>
                    4,7/5
                  </span>
                </div>
                {[
                  { topic: 'Service',   pct: 92, color: C.sage },
                  { topic: 'Propreté',  pct: 88, color: C.sky },
                  { topic: 'Accueil',   pct: 80, color: C.lavender },
                ].map((t) => (
                  <div key={t.topic} className="relative flex items-center gap-2">
                    <span className="text-[10px] font-bold w-14 shrink-0" style={{ color: C.inkSoft }}>{t.topic}</span>
                    <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.7)' }}>
                      <motion.div
                        initial={{ width: 0 }}
                        whileInView={{ width: `${t.pct}%` }}
                        viewport={{ once: true }}
                        transition={{ duration: 0.9, ease: 'easeOut' }}
                        className="h-full rounded-full"
                        style={{ background: `linear-gradient(90deg, ${t.color}, ${C.terracotta})` }}
                      />
                    </div>
                    <span className="text-[10px] font-bold w-7 text-right" style={{ color: t.color }}>{t.pct}%</span>
                  </div>
                ))}
              </div>
            </BentoCard>

            {/* MEDIUM — Geofence (mini animated map) */}
            <BentoCard tint={C.meadow} border={`${C.sage}40`} glow={C.sage + '50'}>
              <div className="w-11 h-11 rounded-xl flex items-center justify-center mb-4"
                   style={{ background: 'white', boxShadow: `0 4px 12px ${C.sage}30` }}>
                <MapPin size={22} style={{ color: C.sage }} />
              </div>
              <h3 className="text-xl font-bold mb-2" style={{ color: C.inkDeep }}>Offres géolocalisées</h3>
              <p className="text-sm leading-relaxed mb-4" style={{ color: C.inkMute }}>
                Quand un client VIP passe à 500&nbsp;m de votre boutique, il reçoit un mot d'attention.
              </p>
              {/* Mini map with pulsing geofence — vivid gradient base */}
              <div className="relative rounded-2xl border overflow-hidden"
                   style={{
                     background: `linear-gradient(135deg, #E8F4E2 0%, #D4ECCB 50%, #C8E0D8 100%)`,
                     borderColor: `${C.sage}55`,
                     height: 130,
                     boxShadow: `0 6px 20px -8px ${C.sage}66`,
                   }}>
                {/* River accent */}
                <svg className="absolute inset-0 w-full h-full" viewBox="0 0 280 130" preserveAspectRatio="xMidYMid slice">
                  {/* Soft park / river patches */}
                  <path d="M 0 100 Q 90 88 180 102 T 280 96 L 280 130 L 0 130 Z" fill="#BDD9B2" opacity="0.55" />
                  <circle cx="240" cy="30" r="22" fill="#A6CC97" opacity="0.45" />
                  {/* Streets */}
                  <line x1="0" y1="40" x2="280" y2="40" stroke="white" strokeWidth="7" />
                  <line x1="0" y1="80" x2="280" y2="80" stroke="white" strokeWidth="5" />
                  <line x1="100" y1="0" x2="100" y2="130" stroke="white" strokeWidth="6" />
                  <line x1="200" y1="0" x2="200" y2="130" stroke="white" strokeWidth="5" />
                  {/* Buildings */}
                  <rect x="40" y="50" width="40" height="22" fill="white" stroke="#D5D0C9" strokeWidth="1" rx="2" />
                  <rect x="220" y="48" width="34" height="26" fill="white" stroke="#D5D0C9" strokeWidth="1" rx="2" />
                  <rect x="125" y="48" width="28" height="22" fill="white" stroke="#D5D0C9" strokeWidth="1" rx="2" />
                </svg>
                {/* Pulse ring + pin centered */}
                <motion.div
                  aria-hidden="true"
                  className="absolute rounded-full border-2 border-dashed"
                  style={{
                    left: '50%', top: '50%', width: 120, height: 120,
                    transform: 'translate(-50%, -50%)',
                    borderColor: C.sage,
                    background: `radial-gradient(circle, ${C.sage}30 0%, ${C.teal}15 50%, transparent 75%)`,
                  }}
                  animate={{ scale: [1, 1.08, 1], rotate: [0, 360] }}
                  transition={{
                    scale: { duration: 3, repeat: Infinity, ease: 'easeInOut' },
                    rotate: { duration: 60, repeat: Infinity, ease: 'linear' },
                  }}
                />
                <motion.div
                  aria-hidden="true"
                  className="absolute"
                  style={{ left: '50%', top: '50%', transform: 'translate(-50%, -50%)' }}
                  animate={{ y: [0, -3, 0] }}
                  transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
                >
                  <div className="w-8 h-8 rounded-full flex items-center justify-center text-white shadow-xl border-2 border-white"
                       style={{ background: `linear-gradient(135deg, ${C.terracotta}, ${C.rose})` }}>
                    <span className="text-sm">☕</span>
                  </div>
                </motion.div>
                {/* Customer dot moving toward shop */}
                <motion.div
                  aria-hidden="true"
                  className="absolute"
                  initial={{ left: '12%', top: '85%' }}
                  animate={{ left: ['12%', '32%', '50%'], top: ['85%', '70%', '50%'] }}
                  transition={{ duration: 5, repeat: Infinity, repeatType: 'loop', ease: 'easeInOut', repeatDelay: 1 }}
                >
                  <div className="relative -translate-x-1/2 -translate-y-1/2">
                    <span className="absolute -inset-1.5 rounded-full opacity-50 animate-ping" style={{ background: C.sky }} />
                    <div className="relative w-3.5 h-3.5 rounded-full border-2 border-white shadow-md" style={{ background: C.sky }} />
                  </div>
                </motion.div>
                {/* Distance label */}
                <span className="absolute bottom-2.5 right-2.5 px-2.5 py-1 rounded-full text-[10px] font-bold backdrop-blur"
                      style={{ background: 'rgba(255,255,255,0.92)', color: C.sage, border: `1px solid ${C.sage}55`, boxShadow: `0 2px 8px ${C.sage}33` }}>
                  500&nbsp;m
                </span>
                {/* Live indicator */}
                <span className="absolute top-2.5 left-2.5 flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[9px] font-bold backdrop-blur"
                      style={{ background: 'rgba(255,255,255,0.92)', color: C.sage, border: `1px solid ${C.sage}33` }}>
                  <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: C.sage }} />
                  En direct
                </span>
              </div>
            </BentoCard>

            {/* MEDIUM — Campaigns (segment chips preview) */}
            <BentoCard tint={C.butter} border={`${C.ochre}40`} glow={C.ochre + '50'}>
              <div className="w-11 h-11 rounded-xl flex items-center justify-center mb-4"
                   style={{ background: 'white', boxShadow: `0 4px 12px ${C.ochre}30` }}>
                <Megaphone size={22} style={{ color: C.ochre }} />
              </div>
              <h3 className="text-xl font-bold mb-2" style={{ color: C.inkDeep }}>Campagnes ciblées</h3>
              <p className="text-sm leading-relaxed mb-4" style={{ color: C.inkMute }}>
                12 segments en un clic. Habitués du midi, clients endormis, gros paniers — en 30 secondes.
              </p>
              {/* Segment chips — gradient backdrop with floating glow */}
              <div className="relative rounded-2xl p-3.5 border overflow-hidden"
                   style={{
                     background: `linear-gradient(135deg, white 0%, ${C.butter} 60%, ${C.shellPink} 100%)`,
                     borderColor: `${C.ochre}55`,
                     boxShadow: `0 6px 20px -8px ${C.ochre}66`,
                   }}>
                <motion.div
                  aria-hidden="true"
                  className="absolute -bottom-6 -right-6 w-20 h-20 rounded-full blur-2xl opacity-60 pointer-events-none"
                  style={{ background: C.terracotta }}
                  animate={{ scale: [1, 1.2, 1] }}
                  transition={{ duration: 4.5, repeat: Infinity, ease: 'easeInOut' }}
                />
                <div className="relative">
                <p className="text-[9px] font-bold uppercase tracking-widest mb-2" style={{ color: C.inkFaint }}>
                  Choisissez vos clients
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {[
                    { label: '👑 VIP', active: true,  color: C.ochre },
                    { label: '🎂 Anniversaires', active: true, color: C.rose },
                    { label: '☕ Habitués midi', active: false, color: C.sage },
                    { label: '😴 Endormis 30j+', active: true, color: C.lavender },
                    { label: '💎 Gros paniers', active: false, color: C.sky },
                  ].map((s, i) => (
                    <motion.span
                      key={i}
                      initial={{ opacity: 0, scale: 0.92 }}
                      whileInView={{ opacity: 1, scale: 1 }}
                      viewport={{ once: true }}
                      transition={{ delay: i * 0.08, duration: 0.3 }}
                      className="text-[10px] font-bold px-2 py-1 rounded-full"
                      style={{
                        background: s.active ? s.color : `${s.color}18`,
                        color: s.active ? 'white' : s.color,
                        border: `1px solid ${s.color}55`,
                      }}
                    >
                      {s.label}
                    </motion.span>
                  ))}
                </div>
                <div className="flex items-center justify-between mt-3 pt-2.5 border-t" style={{ borderColor: `${C.ochre}33` }}>
                  <span className="text-[10px]" style={{ color: C.inkMute }}>~ <b style={{ color: C.inkDeep }}>184 clients</b> ciblés</span>
                  <motion.span
                    className="text-[10px] font-bold px-2.5 py-1 rounded-full text-white"
                    style={{ background: `linear-gradient(135deg, ${C.terracotta}, ${C.rose})`, boxShadow: `0 4px 12px ${C.terracotta}55` }}
                    animate={{ scale: [1, 1.04, 1] }}
                    transition={{ duration: 2.5, repeat: Infinity, ease: 'easeInOut' }}
                  >
                    Envoyer →
                  </motion.span>
                </div>
                </div>
              </div>
            </BentoCard>

            {/* WIDE — Analytics */}
            <BentoCard className="md:col-span-3" tint={C.cream} border={C.hairline}>
              <div className="grid md:grid-cols-2 gap-6 items-center">
                <div>
                  <div className="w-11 h-11 rounded-xl flex items-center justify-center mb-4"
                       style={{ background: 'white', boxShadow: `0 4px 12px ${C.terracotta}30`, border: `1px solid ${C.hairline}` }}>
                    <BarChart3 size={22} style={{ color: C.terracotta }} />
                  </div>
                  <h3 className="font-['Cormorant_Garamond'] text-2xl md:text-3xl font-bold mb-2" style={{ color: C.inkDeep }}>
                    25+ indicateurs en direct, tous explorables
                  </h3>
                  <p className="text-sm leading-relaxed" style={{ color: C.inkMute }}>
                    Taux de retour. Risque de désengagement. Valeur client. Visites par boutique. Heures de pointe.
                    Cliquez sur n'importe quel chiffre — vous voyez exactement quels clients se cachent derrière.
                  </p>
                </div>
                {/* Mini chart */}
                <div className="rounded-2xl p-4 border" style={{ background: 'white', borderColor: C.hairline }}>
                  <div className="flex items-end justify-between h-24 gap-1.5">
                    {[40, 55, 48, 70, 62, 85, 92, 78, 95, 88, 100, 92].map((h, i) => (
                      <motion.div
                        key={i}
                        initial={{ scaleY: 0 }}
                        whileInView={{ scaleY: 1 }}
                        viewport={{ once: true }}
                        transition={{ delay: i * 0.05, duration: 0.5 }}
                        className="flex-1 rounded-t origin-bottom"
                        style={{
                          height: `${h}%`,
                          background: `linear-gradient(to top, ${C.terracotta}, ${C.rose})`,
                        }}
                      />
                    ))}
                  </div>
                  <div className="flex justify-between mt-2 text-[10px]" style={{ color: C.inkFaint }}>
                    <span>Jan</span><span>Apr</span><span>Aug</span><span>Dec</span>
                  </div>
                </div>
              </div>
            </BentoCard>
          </div>
        </div>
      </section>

      {/* ───────────── CARD PREVIEW ───────────── */}
      <section id="demo" className="relative py-20 lg:py-28 overflow-hidden"
               style={{ background: `linear-gradient(135deg, ${C.cream} 0%, ${C.shellPink} 25%, ${C.lilac} 50%, ${C.azure} 75%, ${C.meadow} 100%)` }}>
        <motion.div aria-hidden="true" className="absolute top-1/4 -left-32 w-[500px] h-[500px] rounded-full blur-3xl opacity-50 pointer-events-none"
                    style={{ background: `radial-gradient(circle, ${C.rose} 0%, transparent 70%)` }}
                    animate={{ x: [0, 40, 0], y: [0, -30, 0] }} transition={{ duration: 24, repeat: Infinity, ease: 'easeInOut' }} />
        <motion.div aria-hidden="true" className="absolute bottom-1/4 -right-32 w-[480px] h-[480px] rounded-full blur-3xl opacity-50 pointer-events-none"
                    style={{ background: `radial-gradient(circle, ${C.lavender} 0%, transparent 70%)` }}
                    animate={{ x: [0, -50, 0], y: [0, 30, 0] }} transition={{ duration: 28, repeat: Infinity, ease: 'easeInOut', delay: 3 }} />

        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 grid lg:grid-cols-2 gap-12 items-center">
          <div>
            <Eyebrow color={C.rose} bg={C.blush}>Côté client</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold leading-tight mb-6">
              La carte que votre client<br/>
              <span style={{ color: C.terracotta }}>garde vraiment.</span>
            </h2>
            <p className="text-lg leading-relaxed mb-6" style={{ color: C.inkMute }}>
              Logo, bannière promotionnelle, message d'accueil, solde de points, progression des tampons, code-barres
              fonctionnel — tout s'affiche en direct depuis vos données. Chaque élément se personnalise depuis
              le Concepteur de carte dans votre tableau de bord.
            </p>
            <div className="space-y-3">
              {[
                { color: C.sage,     text: 'Prénom + anniversaire personnalisés automatiquement' },
                { color: C.lavender, text: 'Bannière — votre visuel, ou un modèle prêt à l\'emploi' },
                { color: C.coral,    text: 'Badge de statut + progression mis à jour en direct' },
                { color: C.sky,      text: 'Code-barres scannable au comptoir, prêt pour vos équipes' },
              ].map((item, i) => (
                <div key={i} className="flex items-center gap-3">
                  <span className="w-2 h-2 rounded-full" style={{ background: item.color }} />
                  <span className="text-sm" style={{ color: C.inkSoft }}>{item.text}</span>
                </div>
              ))}
            </div>
          </div>

          {/* The real production card — sized + themed for the landing page hero shot */}
          <div className="flex justify-center items-center relative">
            <motion.div
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.7 }}
              className="relative"
            >
              {/* Multi-color halo glow behind the card — gives it the premium float */}
              <div
                aria-hidden="true"
                className="absolute -inset-12 rounded-[48px] opacity-50 blur-3xl pointer-events-none"
                style={{
                  background: `conic-gradient(from 90deg, ${C.terracotta}, ${C.ochre}, ${C.rose}, ${C.lavender}, ${C.sky}, ${C.teal}, ${C.terracotta})`,
                }}
              />

              {/* iPhone + Apple Wallet shell — same component used by the
                  card-designer live preview and the hero phone showcase, so
                  the merchant sees the SAME card in three places: hero,
                  this "customer's view" section, and inside the dashboard. */}
              <AppleWalletFrame width={400}>
                {/* Same component used by the Card Designer live preview and
                    by every customer's actual /card/<FT-ID> page — so the
                    merchant sees the SAME card in three places: this hero,
                    the bento above, and inside the dashboard. */}
                <div style={{ width: 336 }}>
                  <LandingDemoCard compact />
                </div>
              </AppleWalletFrame>

              {/* Floating wallet pill below the card */}
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: 0.6 }}
                className="absolute -bottom-5 left-1/2 -translate-x-1/2 px-4 py-1.5 rounded-full bg-white shadow-lg border whitespace-nowrap"
                style={{ borderColor: C.hairline }}
              >
                <p className="text-[10px] font-bold uppercase tracking-[0.2em]" style={{ color: C.inkMute }}>
                  Apple Wallet · Google Wallet
                </p>
              </motion.div>

              {/* Floating accent pills around the card */}
              <motion.div
                aria-hidden="true"
                className="absolute -left-10 top-20 hidden md:flex items-center gap-1.5 px-3 py-1.5 rounded-full shadow-xl border"
                style={{ background: 'white', borderColor: C.hairline }}
                animate={{ y: [0, -6, 0] }}
                transition={{ duration: 3.6, repeat: Infinity, ease: 'easeInOut' }}
              >
                <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: C.sage }} />
                <span className="text-[10px] font-bold" style={{ color: C.inkDeep }}>En direct</span>
              </motion.div>
              <motion.div
                aria-hidden="true"
                className="absolute -right-8 bottom-32 hidden md:flex items-center gap-1.5 px-3 py-1.5 rounded-full shadow-xl"
                style={{ background: `linear-gradient(135deg, ${C.lavender} 0%, ${C.rose} 100%)`, color: 'white' }}
                animate={{ y: [0, 6, 0] }}
                transition={{ duration: 4.2, repeat: Infinity, ease: 'easeInOut', delay: 0.6 }}
              >
                <Sparkles size={10} />
                <span className="text-[10px] font-bold">Statut VIP atteint</span>
              </motion.div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* ───────────── GEOLOCATION DEMO — animated map + push notification ───────────── */}
      <section id="geo" className="relative py-20 lg:py-28 overflow-hidden"
               style={{ background: `linear-gradient(135deg, ${C.cream} 0%, ${C.meadow} 100%)` }}>
        <motion.div aria-hidden="true" className="absolute top-1/3 -left-32 w-[500px] h-[500px] rounded-full blur-3xl opacity-40 pointer-events-none"
                    style={{ background: `radial-gradient(circle, ${C.sage} 0%, transparent 70%)` }}
                    animate={{ x: [0, 50, 0], y: [0, -30, 0] }} transition={{ duration: 24, repeat: Infinity, ease: 'easeInOut' }} />
        <motion.div aria-hidden="true" className="absolute bottom-0 right-0 w-[450px] h-[450px] rounded-full blur-3xl opacity-30 pointer-events-none"
                    style={{ background: `radial-gradient(circle, ${C.teal} 0%, transparent 70%)` }}
                    animate={{ x: [0, -40, 0], y: [0, 30, 0] }} transition={{ duration: 28, repeat: Infinity, ease: 'easeInOut', delay: 3 }} />

        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 grid lg:grid-cols-2 gap-12 items-center">
          {/* LEFT — copy */}
          <div>
            <Eyebrow color={C.sage} bg={C.meadow}>Géolocalisation en temps réel</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold leading-tight mb-6">
              Quand votre VIP passe à côté,<br/>
              <span style={{ color: C.sage }}>il reçoit une attention.</span>
            </h2>
            <p className="text-lg leading-relaxed mb-8" style={{ color: C.inkMute }}>
              Définissez un périmètre autour de votre boutique. Dès qu'un client équipé de sa carte de fidélité
              ouvre son téléphone à portée, une offre personnalisée s'affiche — sans application,
              sans friction. Vous restez présent dans son esprit au bon moment.
            </p>

            <div className="space-y-4">
              {[
                { color: C.sage,     icon: '📍', title: 'Rayon configurable', body: 'De 50&nbsp;m à 2&nbsp;km — vous choisissez. Par défaut 500&nbsp;m, idéal pour le quartier.' },
                { color: C.lavender, icon: '👑', title: 'Réservé aux VIP', body: 'Limitez les notifications à votre meilleur palier — l\'exclusivité que vos clients apprécient.' },
                { color: C.sky,      icon: '⏱', title: 'Anti-spam intégré', body: 'Maximum une notification par client tous les X jours. Vous définissez la cadence.' },
                { color: C.coral,    icon: '🤫', title: 'Discret côté technique', body: 'Aucune demande supplémentaire au client après son inscription. Ça marche, c\'est tout.' },
              ].map((item) => (
                <div key={item.title} className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center text-lg shrink-0"
                       style={{ background: 'white', boxShadow: `0 4px 12px ${item.color}40`, border: `1px solid ${item.color}30` }}>
                    {item.icon}
                  </div>
                  <div>
                    <p className="font-bold text-sm" style={{ color: C.inkDeep }}>{item.title}</p>
                    <p className="text-sm" style={{ color: C.inkMute }}>{item.body}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* RIGHT — animated map demo */}
          <div className="flex justify-center">
            <motion.div
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.7 }}
              className="relative w-full max-w-[460px]"
            >
              {/* Multi-color halo */}
              <div aria-hidden="true" className="absolute -inset-8 rounded-[40px] opacity-40 blur-3xl pointer-events-none"
                   style={{ background: `conic-gradient(from 90deg, ${C.sage}, ${C.teal}, ${C.sky}, ${C.lavender}, ${C.sage})` }} />

              {/* Map "card" */}
              <div className="relative bg-white rounded-3xl shadow-2xl border overflow-hidden"
                   style={{ borderColor: C.hairline, boxShadow: `0 30px 60px -15px rgba(28,25,23,0.30)` }}>
                {/* Map header bar */}
                <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: C.hairline, background: C.sand }}>
                  <span className="text-xs font-bold uppercase tracking-wider" style={{ color: C.inkMute }}>📍 Café Lumière · 14h32</span>
                  <span className="flex items-center gap-1.5 text-xs" style={{ color: C.sage }}>
                    <span className="w-2 h-2 rounded-full animate-pulse" style={{ background: C.sage }} />
                    Périmètre actif
                  </span>
                </div>

                {/* Map canvas with stylized streets */}
                <div className="relative" style={{ height: 380, background: '#E8F0E5' }}>
                  {/* Street grid */}
                  <svg className="absolute inset-0 w-full h-full" viewBox="0 0 460 380" preserveAspectRatio="none">
                    {/* Rivers / parks */}
                    <path d="M 0 280 Q 150 250 300 290 T 460 270 L 460 380 L 0 380 Z" fill="#D5E5CC" opacity="0.6" />
                    <circle cx="380" cy="120" r="50" fill="#C8DEC0" opacity="0.7" />
                    {/* Streets */}
                    <line x1="0" y1="100" x2="460" y2="100" stroke="white" strokeWidth="14" />
                    <line x1="0" y1="200" x2="460" y2="200" stroke="white" strokeWidth="10" />
                    <line x1="0" y1="320" x2="460" y2="320" stroke="white" strokeWidth="8" />
                    <line x1="120" y1="0" x2="120" y2="380" stroke="white" strokeWidth="10" />
                    <line x1="280" y1="0" x2="280" y2="380" stroke="white" strokeWidth="12" />
                    <line x1="380" y1="0" x2="380" y2="380" stroke="white" strokeWidth="8" />
                    {/* Buildings */}
                    <rect x="40" y="120" width="60" height="60" fill="white" stroke="#D5D0C9" strokeWidth="1.5" rx="3" />
                    <rect x="160" y="220" width="80" height="60" fill="white" stroke="#D5D0C9" strokeWidth="1.5" rx="3" />
                    <rect x="320" y="40" width="40" height="40" fill="white" stroke="#D5D0C9" strokeWidth="1.5" rx="3" />
                    <rect x="160" y="40" width="50" height="40" fill="white" stroke="#D5D0C9" strokeWidth="1.5" rx="3" />
                  </svg>

                  {/* The geofence — animated pulsing circle */}
                  <motion.div
                    aria-hidden="true"
                    className="absolute"
                    style={{ left: '52%', top: '52%', transform: 'translate(-50%, -50%)' }}
                  >
                    {/* Outer pulse ring */}
                    <motion.div
                      className="absolute rounded-full"
                      style={{
                        width: 220, height: 220, left: -110, top: -110,
                        background: `radial-gradient(circle, ${C.sage}30 0%, ${C.sage}00 70%)`,
                        border: `2px dashed ${C.sage}`,
                      }}
                      animate={{ scale: [1, 1.08, 1] }}
                      transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
                    />
                    {/* Shop pin */}
                    <div className="absolute" style={{ left: -18, top: -32 }}>
                      <div className="w-9 h-9 rounded-full flex items-center justify-center text-white shadow-xl border-2 border-white"
                           style={{ background: `linear-gradient(135deg, ${C.terracotta}, ${C.rose})` }}>
                        <span className="text-base">☕</span>
                      </div>
                    </div>
                    <span className="absolute text-[10px] font-bold whitespace-nowrap"
                          style={{ left: 24, top: -22, color: C.inkDeep, background: 'white', padding: '2px 6px', borderRadius: 4, border: `1px solid ${C.hairline}` }}>
                      Café Lumière
                    </span>
                  </motion.div>

                  {/* Customer dot — moves into the geofence */}
                  <motion.div
                    aria-hidden="true"
                    className="absolute"
                    initial={{ left: '5%', top: '85%' }}
                    animate={{ left: ['5%', '25%', '40%', '52%'], top: ['85%', '70%', '60%', '52%'] }}
                    transition={{ duration: 5, repeat: Infinity, repeatType: 'loop', ease: 'easeInOut', repeatDelay: 1 }}
                  >
                    <div className="relative -translate-x-1/2 -translate-y-1/2">
                      {/* Pulse ring under customer */}
                      <span className="absolute -inset-2 rounded-full opacity-40 animate-ping" style={{ background: C.sky }} />
                      <div className="relative w-5 h-5 rounded-full border-[3px] border-white shadow-lg" style={{ background: C.sky }} />
                    </div>
                  </motion.div>

                  {/* "Sophie" label that follows the dot — appears mid-journey */}
                  <motion.div
                    aria-hidden="true"
                    className="absolute pointer-events-none"
                    initial={{ left: '5%', top: '79%', opacity: 0 }}
                    animate={{
                      left: ['5%', '25%', '40%', '52%'],
                      top: ['79%', '64%', '54%', '46%'],
                      opacity: [0, 1, 1, 0],
                    }}
                    transition={{ duration: 5, repeat: Infinity, repeatType: 'loop', ease: 'easeInOut', repeatDelay: 1 }}
                  >
                    <span className="text-[10px] font-bold whitespace-nowrap"
                          style={{ color: C.inkDeep, background: 'white', padding: '2px 6px', borderRadius: 4, border: `1px solid ${C.hairline}` }}>
                      Sophie · Gold
                    </span>
                  </motion.div>
                </div>

                {/* Distance / status footer */}
                <div className="px-4 py-3 border-t flex items-center justify-between" style={{ borderColor: C.hairline, background: 'white' }}>
                  <div className="flex items-center gap-2 text-xs" style={{ color: C.inkMute }}>
                    <span className="font-bold" style={{ color: C.sage }}>Rayon 500&nbsp;m</span> · délai 24h
                  </div>
                  <div className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: C.sage }}>
                    <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: C.sage }} />
                    Actif
                  </div>
                </div>
              </div>

              {/* Floating push notification — appears when customer hits the fence */}
              <motion.div
                aria-hidden="true"
                className="absolute -right-4 lg:-right-12 top-32 px-4 py-3 rounded-2xl shadow-2xl border max-w-[260px]"
                style={{ background: 'white', borderColor: C.hairline }}
                initial={{ opacity: 0, scale: 0.85, x: 20 }}
                animate={{ opacity: [0, 0, 0, 1, 1, 0], scale: [0.85, 0.85, 0.85, 1, 1, 0.85], x: [20, 20, 20, 0, 0, 20] }}
                transition={{ duration: 6, repeat: Infinity, ease: 'easeOut', repeatDelay: 0 }}
              >
                <div className="flex items-start gap-2">
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center text-white shrink-0"
                       style={{ background: `linear-gradient(135deg, ${C.terracotta}, ${C.rose})` }}>
                    <span className="text-base">☕</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[10px] font-bold uppercase tracking-wider" style={{ color: C.inkFaint }}>
                      Café Lumière · maintenant
                    </p>
                    <p className="text-sm font-bold leading-tight" style={{ color: C.inkDeep }}>
                      Bonjour Sophie, vous êtes tout près 👋
                    </p>
                    <p className="text-xs mt-1 leading-snug" style={{ color: C.inkMute }}>
                      Un café offert pour notre membre Gold préférée — venez nous voir !
                    </p>
                  </div>
                </div>
              </motion.div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* ───────────── HOW IT WORKS ───────────── */}
      <section id="how" className="py-20 lg:py-28" style={{ background: 'white' }}>
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <Eyebrow color={C.sage} bg={C.meadow}>Comment ça marche</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold leading-tight">
              Opérationnel <span style={{ color: C.sage }}>en un après-midi.</span>
            </h2>
          </div>

          <div className="relative grid md:grid-cols-3 gap-8">
            {/* Connecting dotted line on desktop */}
            <div aria-hidden="true" className="hidden md:block absolute left-0 right-0 top-12 h-0.5"
                 style={{
                   background: `repeating-linear-gradient(90deg, ${C.hairline} 0 8px, transparent 8px 16px)`,
                   marginLeft: '16.66%', marginRight: '16.66%',
                 }} />
            {[
              { n: 1, title: 'Configurez en 5 minutes', body: 'Ajoutez votre commerce, importez votre logo, définissez la récompense — par exemple «&nbsp;10 visites = 1 café offert&nbsp;».', color: C.terracotta, bg: C.shellPink, icon: Settings2 },
              { n: 2, title: 'Vos clients adhèrent', body: 'Ils scannent le QR code au comptoir, leur carte s\'ajoute dans Apple Wallet ou Google Wallet. Aucune application.', color: C.lavender, bg: C.lilac, icon: ScanLine },
              { n: 3, title: 'Le retour s\'installe', body: 'Le tableau de bord montre qui revient. Les relances automatiques réveillent les clients endormis.', color: C.sage, bg: C.meadow, icon: TrendingUp },
            ].map((step) => {
              const Icon = step.icon;
              return (
                <motion.div
                  key={step.n}
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.6, delay: step.n * 0.1 }}
                  whileHover={{ y: -6, scale: 1.01 }}
                  className="relative rounded-3xl p-7 border-2 z-10 overflow-hidden"
                  style={{
                    background: `
                      radial-gradient(circle at 100% 0%, ${step.bg} 0%, transparent 55%),
                      radial-gradient(circle at 0% 100%, ${step.bg} 0%, transparent 65%),
                      linear-gradient(135deg, white 0%, #FDFBF7 100%)
                    `,
                    borderColor: `${step.color}40`,
                    boxShadow: `0 12px 32px -14px ${step.color}55`,
                  }}
                >
                  {/* Decorative accent orbs */}
                  <motion.div
                    aria-hidden="true"
                    className="absolute -top-16 -right-16 w-40 h-40 rounded-full blur-3xl pointer-events-none"
                    style={{ background: step.color, opacity: 0.18 }}
                    animate={{ scale: [1, 1.15, 1] }}
                    transition={{ duration: 5 + step.n * 0.5, repeat: Infinity, ease: 'easeInOut' }}
                  />
                  {/* Big numeric watermark */}
                  <span
                    aria-hidden="true"
                    className="absolute -bottom-4 right-4 font-['Cormorant_Garamond'] font-bold leading-none pointer-events-none select-none"
                    style={{
                      fontSize: 160,
                      color: `${step.color}12`,
                    }}
                  >
                    {step.n}
                  </span>

                  <div className="relative flex items-center gap-3 mb-5">
                    <div className="w-14 h-14 rounded-2xl flex items-center justify-center text-white font-['Cormorant_Garamond'] text-3xl font-bold shadow-lg"
                         style={{
                           background: `linear-gradient(135deg, ${step.color} 0%, ${C.rose} 100%)`,
                           boxShadow: `0 8px 20px -6px ${step.color}80`,
                         }}>
                      {step.n}
                    </div>
                    <div className="w-11 h-11 rounded-xl flex items-center justify-center"
                         style={{
                           background: `linear-gradient(135deg, white 0%, ${step.bg} 100%)`,
                           border: `1px solid ${step.color}33`,
                         }}>
                      <Icon size={20} style={{ color: step.color }} />
                    </div>
                  </div>
                  <h3 className="relative text-xl font-bold mb-2" style={{ color: C.inkDeep }}>{step.title}</h3>
                  <p className="relative text-sm leading-relaxed" style={{ color: C.inkSoft }}>{step.body}</p>
                </motion.div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ───────────── TESTIMONIALS ───────────── */}
      <section className="relative py-20 lg:py-28 overflow-hidden"
               style={{ background: `linear-gradient(135deg, ${C.cream}, ${C.butter} 50%, ${C.shellPink})` }}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-14">
            <Eyebrow color={C.ochre} bg={C.butter}>Pourquoi ça fonctionne</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold leading-tight">
              Trois bénéfices que <span style={{ color: C.ochre }}>vos clients ressentent.</span>
            </h2>
            <p className="text-sm mt-4 italic" style={{ color: C.inkFaint }}>
              Témoignages illustratifs — basés sur les retours de nos commerçants pilotes.
            </p>
          </div>
          <div className="grid md:grid-cols-3 gap-6">
            {[
              {
                quote: '«&nbsp;En trois mois, j\'ai vu mon taux de retour grimper de manière nette. Et le plus beau&nbsp;? Je n\'ai littéralement rien fait — FidClic gère les anniversaires et les relances tout seul.&nbsp;»',
                name: 'Une gérante de café',
                role: 'Restauration · 1 boutique',
                location: 'Île-de-France',
                color: C.terracotta, bg: C.shellPink,
              },
              {
                quote: '«&nbsp;Avant, je tamponnais des cartes en carton. Aujourd\'hui, je sais exactement combien de clients viendront vendredi soir, qui ils sont, et quel message a bien fonctionné la semaine dernière.&nbsp;»',
                name: 'Un propriétaire de boulangerie',
                role: 'Artisanat · 1 boutique',
                location: 'Auvergne-Rhône-Alpes',
                color: C.lavender, bg: C.lilac,
              },
              {
                quote: '«&nbsp;On a déployé FidClic dans plusieurs boutiques. Les visites répétées ont clairement décollé. Le retour sur investissement est arrivé en quelques semaines.&nbsp;»',
                name: 'Une responsable marketing',
                role: 'Réseau · plusieurs boutiques',
                location: 'France',
                color: C.sage, bg: C.meadow,
              },
            ].map((t, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
                transition={{ duration: 0.5, delay: i * 0.1 }}
                whileHover={{ y: -6, scale: 1.01 }}
                className="rounded-3xl p-7 relative overflow-hidden border-2"
                style={{
                  background: `
                    radial-gradient(circle at 100% 0%, ${t.bg} 0%, transparent 50%),
                    radial-gradient(circle at 0% 100%, ${t.bg} 0%, transparent 60%),
                    linear-gradient(135deg, white 0%, #FDFBF7 100%)
                  `,
                  borderColor: `${t.color}33`,
                  boxShadow: `0 14px 36px -14px ${t.color}55`,
                }}
              >
                {/* Animated decorative orbs */}
                <motion.div
                  aria-hidden="true"
                  className="absolute -top-14 -right-14 w-44 h-44 rounded-full blur-3xl pointer-events-none"
                  style={{ background: t.color, opacity: 0.22 }}
                  animate={{ scale: [1, 1.18, 1] }}
                  transition={{ duration: 6 + i * 0.5, repeat: Infinity, ease: 'easeInOut' }}
                />
                <motion.div
                  aria-hidden="true"
                  className="absolute -bottom-16 -left-16 w-40 h-40 rounded-full blur-3xl pointer-events-none"
                  style={{ background: t.color, opacity: 0.14 }}
                  animate={{ scale: [1, 1.12, 1] }}
                  transition={{ duration: 7 + i * 0.4, repeat: Infinity, ease: 'easeInOut', delay: 1 }}
                />
                {/* Big quote watermark */}
                <span aria-hidden="true"
                      className="absolute font-['Cormorant_Garamond'] font-bold leading-none pointer-events-none select-none"
                      style={{
                        top: -28, left: 18,
                        fontSize: 160,
                        color: `${t.color}1A`,
                      }}>
                  "
                </span>

                <div className="relative">
                  {/* 5 sparkling stars */}
                  <div className="flex gap-0.5 mb-4">
                    {[0,1,2,3,4].map((s) => (
                      <motion.span
                        key={s}
                        animate={{ scale: [1, 1.15, 1] }}
                        transition={{ duration: 2.4, repeat: Infinity, delay: s * 0.18, ease: 'easeInOut' }}
                        style={{ display: 'inline-flex' }}
                      >
                        <Star size={16} fill={C.ochre} stroke={C.ochre} />
                      </motion.span>
                    ))}
                  </div>
                  <p className="text-base leading-relaxed mb-6 font-medium" style={{ color: C.inkSoft }}>{t.quote}</p>
                  <div className="flex items-center gap-3 pt-4 border-t" style={{ borderColor: `${t.color}22` }}>
                    <div className="w-12 h-12 rounded-full flex items-center justify-center text-white font-bold text-xl shadow-lg"
                         style={{
                           background: `linear-gradient(135deg, ${t.color} 0%, ${C.rose} 100%)`,
                           boxShadow: `0 6px 16px -4px ${t.color}80`,
                         }}>
                      {['☕','🥐','✨'][i]}
                    </div>
                    <div>
                      <p className="font-bold text-sm" style={{ color: C.inkDeep }}>{t.name}</p>
                      <p className="text-xs font-medium" style={{ color: t.color }}>{t.role}</p>
                      <p className="text-xs" style={{ color: C.inkFaint }}>{t.location}</p>
                    </div>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ───────────── PRICING ───────────── */}
      <section id="pricing" className="relative py-20 lg:py-28 overflow-hidden">
        <motion.div aria-hidden="true" className="absolute top-0 left-1/4 w-[400px] h-[400px] rounded-full blur-3xl opacity-30 pointer-events-none"
                    style={{ background: `radial-gradient(circle, ${C.azure} 0%, transparent 70%)` }} />
        <motion.div aria-hidden="true" className="absolute bottom-0 right-1/4 w-[400px] h-[400px] rounded-full blur-3xl opacity-30 pointer-events-none"
                    style={{ background: `radial-gradient(circle, ${C.lilac} 0%, transparent 70%)` }} />
        <div className="relative max-w-7xl mx-auto px-4">
          <div className="text-center mb-16">
            <Eyebrow color={C.sage} bg={C.meadow}>Tarifs</Eyebrow>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-5xl font-bold leading-tight mb-4">
              Un prix simple, sans surprise.
            </h2>
            <p className="text-lg max-w-2xl mx-auto" style={{ color: C.inkMute }}>
              Sans engagement. Sans frais de mise en service. Essai gratuit de 30 jours sur tous les plans.
            </p>
          </div>
          <div className="grid lg:grid-cols-3 gap-8 max-w-5xl mx-auto items-stretch">
            {/* ─────── PLAN BASIC — friendly sky/azure light card ─────── */}
            <motion.div
              initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
              transition={{ duration: 0.5 }}
              whileHover={{ y: -6, scale: 1.01 }}
              className="relative rounded-3xl p-10 border-2 flex flex-col overflow-hidden"
              style={{
                background: `
                  radial-gradient(circle at 100% 0%, ${C.azure} 0%, transparent 55%),
                  radial-gradient(circle at 0% 100%, ${C.mint} 0%, transparent 60%),
                  linear-gradient(135deg, white 0%, #FDFBF7 100%)
                `,
                borderColor: `${C.sky}55`,
                boxShadow: `0 16px 40px -16px ${C.sky}55`,
              }}
            >
              <motion.div aria-hidden="true"
                className="absolute -top-16 -right-16 w-44 h-44 rounded-full blur-3xl pointer-events-none"
                style={{ background: C.sky, opacity: 0.22 }}
                animate={{ scale: [1, 1.15, 1] }} transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut' }} />
              <motion.div aria-hidden="true"
                className="absolute -bottom-20 -left-20 w-48 h-48 rounded-full blur-3xl pointer-events-none"
                style={{ background: C.teal, opacity: 0.16 }}
                animate={{ scale: [1, 1.1, 1] }} transition={{ duration: 7, repeat: Infinity, ease: 'easeInOut', delay: 1 }} />

              <span className="relative inline-block self-start px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-[0.18em] mb-5"
                    style={{ background: `linear-gradient(135deg, ${C.azure}, ${C.mint})`, color: C.sky, border: `1px solid ${C.sky}33` }}>
                Découverte
              </span>
              <h3 className="relative text-xl font-bold mb-2" style={{ color: C.inkDeep }}>Plan Basic</h3>
              <p className="relative text-5xl font-bold mb-6 leading-none">
                <span className="bg-clip-text text-transparent"
                      style={{ backgroundImage: `linear-gradient(135deg, ${C.sky}, ${C.teal})` }}>
                  39&nbsp;€
                </span>
                <span className="text-base font-medium" style={{ color: C.inkMute }}> /mois</span>
              </p>
              <ul className="relative mb-8 space-y-3 flex-1 text-sm" style={{ color: C.inkSoft }}>
                {['Jusqu\'à 500 clients',
                  'Carte mobile (Apple & Google Wallet)',
                  'Notifications push illimitées',
                  'Tableau de bord complet',
                  'Auto-anniversaires & relances',
                  'Assistant IA — 200 questions/mois'].map((f, i) => (
                  <li key={i} className="flex gap-2 items-start">
                    <span className="w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5"
                          style={{ background: `${C.sky}1F`, border: `1px solid ${C.sky}55` }}>
                      <Check size={11} style={{ color: C.sky }} strokeWidth={3} />
                    </span>
                    <span className="font-medium">{f}</span>
                  </li>
                ))}
              </ul>
              <Link to="/register"
                    className="relative block text-center w-full font-semibold px-6 py-4 rounded-2xl transition-all hover:shadow-lg"
                    style={{
                      background: `linear-gradient(135deg, ${C.sky}, ${C.teal})`,
                      color: 'white',
                      boxShadow: `0 8px 20px -6px ${C.sky}66`,
                    }}>
                Démarrer gratuitement
              </Link>
            </motion.div>

            {/* ─────── PLAN OR — royal gold dark card ─────── */}
            <motion.div
              initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
              transition={{ duration: 0.5, delay: 0.1 }}
              whileHover={{ y: -10, scale: 1.02 }}
              className="text-white p-10 rounded-3xl shadow-2xl relative lg:-translate-y-4 flex flex-col overflow-hidden"
              style={{
                background: `
                  radial-gradient(circle at 50% 0%, #2A1F12 0%, transparent 50%),
                  linear-gradient(155deg, #1C1408 0%, #2A1F12 50%, #1C1408 100%)
                `,
                border: `1px solid ${C.ochre}66`,
                boxShadow: `0 24px 60px -20px rgba(201,169,97,0.55), 0 0 0 1px ${C.ochre}33 inset`,
              }}
            >
              {/* Glowing orbs */}
              <motion.div aria-hidden="true"
                className="absolute -top-24 -right-24 w-72 h-72 rounded-full blur-3xl pointer-events-none"
                style={{ background: '#C9A961', opacity: 0.45 }}
                animate={{ scale: [1, 1.2, 1] }} transition={{ duration: 7, repeat: Infinity, ease: 'easeInOut' }} />
              <motion.div aria-hidden="true"
                className="absolute -bottom-24 -left-24 w-72 h-72 rounded-full blur-3xl pointer-events-none"
                style={{ background: C.terracotta, opacity: 0.30 }}
                animate={{ scale: [1, 1.15, 1] }} transition={{ duration: 8, repeat: Infinity, ease: 'easeInOut', delay: 1.5 }} />

              {/* Ornate corner shimmer */}
              <motion.div aria-hidden="true"
                className="absolute top-6 right-6 pointer-events-none"
                animate={{ rotate: [0, 360], opacity: [0.4, 0.9, 0.4] }}
                transition={{ rotate: { duration: 16, repeat: Infinity, ease: 'linear' }, opacity: { duration: 4, repeat: Infinity, ease: 'easeInOut' } }}
              >
                <Sparkles size={18} style={{ color: '#FFD7A8' }} />
              </motion.div>

              {/* "Le plus choisi" floating ribbon */}
              <div className="absolute -top-4 left-1/2 -translate-x-1/2 text-white text-xs font-bold px-5 py-1.5 rounded-full shadow-xl tracking-wider whitespace-nowrap"
                   style={{
                     background: `linear-gradient(135deg, ${C.terracotta}, #FFD7A8 50%, ${C.ochre})`,
                     boxShadow: `0 8px 24px -4px rgba(201,169,97,0.6)`,
                   }}>
                ⭐ LE PLUS CHOISI
              </div>

              {/* Crown badge */}
              <div className="relative flex items-center gap-2 mb-3 mt-2">
                <div className="w-10 h-10 rounded-xl flex items-center justify-center text-xl shadow-lg"
                     style={{
                       background: `linear-gradient(135deg, #FFD7A8, ${C.ochre} 60%, #8C6B36)`,
                       boxShadow: `0 4px 16px -4px ${C.ochre}88, 0 0 0 1px rgba(255,215,168,0.4) inset`,
                     }}>
                  👑
                </div>
                <h3 className="text-xl font-bold" style={{ fontFamily: 'Cormorant Garamond' }}>Plan Or</h3>
              </div>

              <p className="relative text-6xl font-bold mb-6 leading-none" style={{ fontFamily: 'Cormorant Garamond' }}>
                <span className="bg-clip-text text-transparent"
                      style={{
                        backgroundImage: `linear-gradient(135deg, #FFE5BC 0%, #FFD7A8 30%, ${C.ochre} 60%, #8C6B36 100%)`,
                        filter: 'drop-shadow(0 2px 8px rgba(201,169,97,0.5))',
                      }}>
                  79&nbsp;€
                </span>
                <span className="text-base text-white/55 font-medium"> /mois</span>
              </p>

              <ul className="relative mb-8 space-y-3 flex-1 text-white/85 text-sm">
                {['Jusqu\'à 2 000 clients',
                  'Tout du plan Basic, plus :',
                  'Campagnes ciblées illimitées',
                  'Newsletter mensuelle automatique',
                  'Réponses aux avis (assistées par IA)',
                  'Assistant IA — 350 questions/mois',
                  'Support prioritaire'].map((f, i) => (
                  <li key={i} className="flex gap-2 items-start">
                    <span className="w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5"
                          style={{ background: 'rgba(201,169,97,0.18)', border: '1px solid rgba(201,169,97,0.5)' }}>
                      <Check size={11} style={{ color: '#FFD7A8' }} strokeWidth={3} />
                    </span>
                    <span className="font-medium">{f}</span>
                  </li>
                ))}
              </ul>

              <Link to="/register"
                    className="relative block text-center w-full font-bold px-6 py-4 rounded-2xl transition-all hover:-translate-y-0.5"
                    style={{
                      background: `linear-gradient(135deg, #FFD7A8 0%, ${C.ochre} 50%, #8C6B36 100%)`,
                      color: '#1C1408',
                      boxShadow: '0 12px 28px -6px rgba(201,169,97,0.7), 0 0 0 1px rgba(255,215,168,0.6) inset',
                    }}>
                Choisir le plan Or
              </Link>
            </motion.div>

            {/* ─────── PLAN VIP — platinum elegant card ─────── */}
            <motion.div
              initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
              transition={{ duration: 0.5, delay: 0.2 }}
              whileHover={{ y: -6, scale: 1.01 }}
              className="text-white p-10 rounded-3xl shadow-2xl relative flex flex-col overflow-hidden"
              style={{
                background: `
                  radial-gradient(circle at 100% 0%, #2A2540 0%, transparent 55%),
                  radial-gradient(circle at 0% 100%, #181425 0%, transparent 65%),
                  linear-gradient(155deg, #0E0B1A 0%, #1A1530 50%, #0E0B1A 100%)
                `,
                border: `1px solid rgba(220,220,235,0.25)`,
                boxShadow: `0 24px 60px -20px rgba(155,127,184,0.55), 0 0 0 1px rgba(220,220,235,0.15) inset`,
              }}
            >
              {/* Iridescent glow orbs */}
              <motion.div aria-hidden="true"
                className="absolute -top-24 -right-24 w-72 h-72 rounded-full blur-3xl pointer-events-none"
                style={{ background: C.lavender, opacity: 0.45 }}
                animate={{ scale: [1, 1.18, 1] }} transition={{ duration: 8, repeat: Infinity, ease: 'easeInOut' }} />
              <motion.div aria-hidden="true"
                className="absolute -bottom-24 -left-24 w-72 h-72 rounded-full blur-3xl pointer-events-none"
                style={{ background: C.sky, opacity: 0.30 }}
                animate={{ scale: [1, 1.12, 1] }} transition={{ duration: 9, repeat: Infinity, ease: 'easeInOut', delay: 2 }} />
              {/* Floating star */}
              <motion.div aria-hidden="true"
                className="absolute top-6 right-6 pointer-events-none"
                animate={{ rotate: [0, 360], opacity: [0.5, 1, 0.5] }}
                transition={{ rotate: { duration: 20, repeat: Infinity, ease: 'linear' }, opacity: { duration: 4, repeat: Infinity, ease: 'easeInOut' } }}
              >
                <Sparkles size={18} style={{ color: '#E5E0F5' }} />
              </motion.div>

              {/* Premium ribbon */}
              <div className="absolute -top-4 left-1/2 -translate-x-1/2 text-xs font-bold px-5 py-1.5 rounded-full shadow-xl tracking-[0.18em] whitespace-nowrap"
                   style={{
                     background: `linear-gradient(135deg, #E5E0F5 0%, #C5BCDE 50%, #8B7DC9)`,
                     color: '#0E0B1A',
                     boxShadow: '0 8px 24px -4px rgba(139,125,201,0.6)',
                   }}>
                💎 PLATINE
              </div>

              {/* Diamond badge */}
              <div className="relative flex items-center gap-2 mb-3 mt-2">
                <div className="w-10 h-10 rounded-xl flex items-center justify-center text-xl shadow-lg"
                     style={{
                       background: `linear-gradient(135deg, #E5E0F5, #C5BCDE 50%, #8B7DC9)`,
                       boxShadow: '0 4px 16px -4px rgba(139,125,201,0.7), 0 0 0 1px rgba(229,224,245,0.5) inset',
                     }}>
                  💎
                </div>
                <h3 className="text-xl font-bold" style={{ fontFamily: 'Cormorant Garamond' }}>Plan VIP</h3>
              </div>

              <p className="relative text-6xl font-bold mb-6 leading-none" style={{ fontFamily: 'Cormorant Garamond' }}>
                <span className="bg-clip-text text-transparent"
                      style={{
                        backgroundImage: `linear-gradient(135deg, #FFFFFF 0%, #E5E0F5 30%, ${C.lavender} 65%, #5E527C 100%)`,
                        filter: 'drop-shadow(0 2px 10px rgba(229,224,245,0.5))',
                      }}>
                  149&nbsp;€
                </span>
                <span className="text-base text-white/55 font-medium"> /mois</span>
              </p>

              <ul className="relative mb-8 space-y-3 flex-1 text-white/85 text-sm">
                {['Clients illimités',
                  'Multi-boutiques (jusqu\'à 15)',
                  'Toutes les fonctionnalités Or',
                  'Optimiseur de paliers de fidélité',
                  'Assistant IA — 600 questions/mois',
                  'Manager de compte dédié'].map((f, i) => (
                  <li key={i} className="flex gap-2 items-start">
                    <span className="w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5"
                          style={{ background: 'rgba(229,224,245,0.15)', border: '1px solid rgba(229,224,245,0.4)' }}>
                      <Check size={11} style={{ color: '#E5E0F5' }} strokeWidth={3} />
                    </span>
                    <span className="font-medium">{f}</span>
                  </li>
                ))}
              </ul>

              <Link to="/register"
                    className="relative block text-center w-full font-bold px-6 py-4 rounded-2xl transition-all hover:-translate-y-0.5"
                    style={{
                      background: `linear-gradient(135deg, #FFFFFF 0%, #E5E0F5 50%, #8B7DC9 100%)`,
                      color: '#0E0B1A',
                      boxShadow: '0 12px 28px -6px rgba(139,125,201,0.7), 0 0 0 1px rgba(255,255,255,0.6) inset',
                    }}>
                Passer en VIP
              </Link>
            </motion.div>
          </div>

          {/* ───── MULTI-STORE CONTACT CTA ───── */}
          <div className="mt-16 max-w-5xl mx-auto">
            <div className="rounded-3xl p-[2px] shadow-2xl"
                 style={{ background: `linear-gradient(135deg, ${C.terracotta} 0%, ${C.ochre} 20%, ${C.rose} 40%, ${C.lavender} 60%, ${C.sky} 80%, ${C.teal} 100%)` }}>
              <div className="rounded-[22px] overflow-hidden relative"
                   style={{ background: `linear-gradient(135deg, ${C.inkDeep} 0%, ${C.inkSoft} 60%, #2A1C2E 100%)` }}>
                <div aria-hidden="true" className="absolute -top-24 -right-24 w-72 h-72 rounded-full blur-3xl opacity-30 pointer-events-none"
                     style={{ background: C.ochre }} />
                <div aria-hidden="true" className="absolute -bottom-24 -left-24 w-72 h-72 rounded-full blur-3xl opacity-25 pointer-events-none"
                     style={{ background: C.lavender }} />

                <div className="relative grid lg:grid-cols-5 gap-10 p-10 md:p-14 items-center">
                  {/* Left: copy */}
                  <div className="lg:col-span-3">
                    <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-bold uppercase tracking-widest mb-5"
                         style={{ background: 'rgba(255,255,255,0.08)', color: C.ochre, border: '1px solid rgba(255,255,255,0.15)' }}>
                      <Sparkles size={14} /> Réseau · Multi-boutiques · Franchise
                    </div>
                    <h3 className="font-['Cormorant_Garamond'] text-3xl md:text-4xl text-white font-bold leading-tight mb-4">
                      Plusieurs boutiques&nbsp;?<br/>
                      <span className="bg-clip-text text-transparent inline-block"
                            style={{ backgroundImage: `linear-gradient(110deg, ${C.terracotta}, ${C.ochre}, ${C.rose}, ${C.lavender}, ${C.sky})`, backgroundSize: '200% auto', animation: 'heroGradient 8s linear infinite' }}>
                        Une plateforme pour tout votre réseau.
                      </span>
                    </h3>
                    <p className="text-base md:text-lg leading-relaxed mb-7" style={{ color: '#D4C8B5' }}>
                      Si vous gérez 2 boutiques ou plus et souhaitez déployer FidClic sur l'ensemble — base clients partagée,
                      analytics par boutique, campagnes centralisées — parlons-en. Nous adaptons le tarif et l'accompagnement à votre réseau.
                    </p>

                    {/* Feature pills */}
                    <div className="grid sm:grid-cols-3 gap-3 mb-8">
                      {[
                        { icon: Users, label: 'Base clients unifiée', color: C.sky, bg: 'rgba(74,144,226,0.12)' },
                        { icon: BarChart3, label: 'Analytics par boutique', color: C.lavender, bg: 'rgba(155,127,184,0.15)' },
                        { icon: Award, label: 'Accompagnement dédié', color: C.ochre, bg: 'rgba(212,165,116,0.15)' },
                      ].map(({ icon: Icon, label, color, bg }) => (
                        <div key={label} className="flex items-center gap-2 px-3 py-2.5 rounded-xl border"
                             style={{ background: bg, borderColor: 'rgba(255,255,255,0.08)' }}>
                          <Icon size={16} style={{ color }} />
                          <span className="text-xs font-semibold text-white/90">{label}</span>
                        </div>
                      ))}
                    </div>

                    <div className="flex flex-col sm:flex-row gap-3">
                      <a href="mailto:contact@fidclic.com?subject=Demande%20de%20d%C3%A9ploiement%20multi-boutiques"
                         className="inline-flex items-center justify-center gap-2 text-white px-7 py-4 rounded-full text-base font-semibold transition-all shadow-xl hover:-translate-y-0.5"
                         style={{ background: `linear-gradient(135deg, ${C.terracotta} 0%, ${C.rose} 100%)` }}>
                        Nous contacter <ArrowRight size={18} />
                      </a>
                      <a href="tel:+33123456789"
                         className="inline-flex items-center justify-center gap-2 px-7 py-4 rounded-full text-base font-semibold border transition-all hover:bg-white/10"
                         style={{ borderColor: 'rgba(255,255,255,0.25)', color: 'white' }}>
                        <Smartphone size={16} /> Prendre rendez-vous
                      </a>
                    </div>
                    <p className="text-xs mt-4" style={{ color: 'rgba(255,255,255,0.5)' }}>
                      Réponse sous 24h · Français &amp; anglais
                    </p>
                  </div>

                  {/* Right: stylized stat card */}
                  <div className="lg:col-span-2 relative">
                    <div className="relative rounded-2xl p-6 md:p-7 border overflow-hidden"
                         style={{ background: 'rgba(255,255,255,0.04)', borderColor: 'rgba(255,255,255,0.1)', backdropFilter: 'blur(8px)' }}>
                      <div aria-hidden="true" className="absolute inset-0 opacity-30 pointer-events-none"
                           style={{ background: `radial-gradient(circle at 30% 0%, ${C.terracotta}33 0%, transparent 60%), radial-gradient(circle at 80% 100%, ${C.lavender}33 0%, transparent 60%)` }} />
                      <p className="text-xs font-bold uppercase tracking-widest mb-4 relative" style={{ color: C.ochre }}>Plan Réseau</p>
                      <p className="text-4xl font-bold relative leading-tight">
                        <span className="bg-clip-text text-transparent"
                              style={{ backgroundImage: `linear-gradient(135deg, #FFD7A8, ${C.ochre})` }}>
                          Tarif sur mesure
                        </span>
                      </p>
                      <p className="text-xs mb-5 relative mt-2" style={{ color: 'rgba(255,255,255,0.55)' }}>
                        Adapté au nombre de boutiques et au volume clients — parlons-en.
                      </p>
                      <div className="space-y-2.5 relative">
                        {[
                          'Jusqu\'à 50 000 clients',
                          'Campagnes illimitées',
                          'Tableau de bord multi-boutiques',
                          'Assistant IA — usage personnalisé',
                          'Support prioritaire · SLA garanti',
                        ].map((line) => (
                          <div key={line} className="flex items-center gap-2 text-sm text-white/85">
                            <Check size={15} style={{ color: C.ochre }} /> {line}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ───────────── FINAL CTA ───────────── */}
      <section className="py-16 lg:py-24 max-w-5xl mx-auto px-4">
        <div className="rounded-3xl p-[2px] shadow-xl"
             style={{ background: `linear-gradient(135deg, ${C.terracotta} 0%, ${C.rose} 25%, ${C.lavender} 50%, ${C.sky} 75%, ${C.teal} 100%)` }}>
          <div className="rounded-[22px] overflow-hidden p-10 md:p-16 text-center"
               style={{ background: `linear-gradient(135deg, ${C.inkDeep} 0%, ${C.inkSoft} 50%, #2A1C2E 100%)` }}>
            <h2 className="font-['Cormorant_Garamond'] text-4xl md:text-6xl text-white font-bold leading-tight mb-6">
              Vos clients sont déjà sur leur téléphone.<br/>
              <span className="bg-clip-text text-transparent inline-block"
                    style={{ backgroundImage: `linear-gradient(110deg, ${C.terracotta}, ${C.ochre}, ${C.rose}, ${C.lavender}, ${C.sky})`, backgroundSize: '200% auto', animation: 'heroGradient 6s linear infinite' }}>
                Votre carte de fidélité y a sa place.
              </span>
            </h2>
            <p className="text-lg max-w-2xl mx-auto mb-10" style={{ color: '#D4C8B5' }}>
              Essai gratuit 30 jours. Aucune carte bancaire demandée. Mise en place accompagnée.
              Résiliation en un clic — vous gardez vos données.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Link to="/register"
                    className="inline-flex items-center justify-center gap-2 text-white px-8 py-4 rounded-full text-base font-semibold transition-all shadow-2xl hover:-translate-y-0.5"
                    style={{ background: `linear-gradient(135deg, ${C.terracotta} 0%, ${C.rose} 100%)` }}>
                Démarrer mon essai gratuit <ArrowRight size={18} />
              </Link>
              <a href="mailto:contact@fidclic.com"
                 className="inline-flex items-center justify-center px-8 py-4 rounded-full text-base font-semibold border transition-all hover:bg-white/10"
                 style={{ borderColor: 'rgba(255,255,255,0.25)', color: 'white' }}>
                Parler à un humain
              </a>
            </div>
            <p className="text-xs mt-6" style={{ color: 'rgba(255,255,255,0.55)' }}>
              01&nbsp;23&nbsp;45&nbsp;67&nbsp;89 · contact@fidclic.com
            </p>
          </div>
        </div>
      </section>

      {/* ───────────── FOOTER ───────────── */}
      <footer className="relative bg-white border-t py-14" style={{ borderColor: C.hairline }}>
        <div aria-hidden="true" className="absolute top-0 left-0 right-0 h-1"
             style={{ background: `linear-gradient(90deg, ${C.terracotta} 0%, ${C.rose} 16%, ${C.lavender} 33%, ${C.sky} 50%, ${C.teal} 66%, ${C.sage} 83%, ${C.ochre} 100%)` }} />
        <div className="max-w-7xl mx-auto px-4 text-center" style={{ color: C.inkMute }}>
          <div className="flex items-center justify-center gap-2 mb-4">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center text-white font-bold text-xl shadow-lg"
                 style={{ background: `linear-gradient(135deg, ${C.terracotta} 0%, ${C.rose} 100%)` }}>
              F
            </div>
            <p className="font-['Cormorant_Garamond'] text-2xl font-bold ft-gradient-text-slow">FidClic</p>
          </div>
          <p className="text-sm">© {new Date().getFullYear()} FidClic · Conçu en France pour les commerçants français.</p>
          <div className="flex justify-center gap-2 mt-6">
            {[C.terracotta, C.rose, C.lavender, C.sky, C.teal, C.sage, C.ochre].map((c, i) => (
              <span key={i} className="w-1.5 h-1.5 rounded-full" style={{ background: c }} />
            ))}
          </div>
        </div>
      </footer>
    </div>
  );
};

export default LandingPage;
