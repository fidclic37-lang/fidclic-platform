import React from 'react';

/* =====================================================================
   PAGE SHELL — shared design tokens + reusable layout primitives
   used across every authenticated page (admin, owner, staff).

   Pulls the same color language as the marketing site so the in-app
   surfaces feel like a continuation of the brand rather than a
   separate utilitarian dashboard.
   ===================================================================== */

// Vibrant pastel palette — same tokens used on the landing page so the
// in-app and marketing surfaces share a single visual identity.
// Tokens read CSS variables so every inline style flips with the theme.
// Light = Eclat (flame on gallery white), dark = Minuit Dore (champagne on
// espresso). Values live in index.css under :root and .flc-nuit.
export const C = {
  terracotta:'var(--flc-accent,#C73E2C)', terracottaDeep:'var(--flc-accent-deep,#A82843)',
  ochre:'var(--flc-accent-2,#E8703A)',    amber:'var(--flc-accent-2,#E8703A)',
  rose:'var(--flc-accent,#C73E2C)',       coral:'var(--flc-accent-2,#E8703A)',
  lavender:'var(--flc-accent,#C73E2C)',   lilac:'var(--flc-accent-2,#E8703A)',
  sky:'var(--flc-info,#3568B8)',          azure:'var(--flc-info,#3568B8)',
  teal:'var(--flc-ok,#0F8B58)',           mint:'var(--flc-ok,#0F8B58)',
  sage:'var(--flc-ok,#0F8B58)',           meadow:'var(--flc-ok,#0F8B58)',
  inkDeep:'var(--flc-ink,#191410)',       inkSoft:'var(--flc-ink2,#3A332B)',
  inkMute:'var(--flc-ink3,#524A40)',
  bone:'var(--flc-paper,#FBFAF8)',        cream:'var(--flc-paper2,#F4F1EC)',
  sand:'var(--flc-paper2,#F4F1EC)',
  hairline:'var(--flc-line,#ECE8E2)',
};

// Per-role accent gradient. Drives the brand mark, the active-nav glow,
// the page-header underline, and the primary CTA in any role-scoped page.
// Keeping each role visually distinct helps an admin who's switched
// accounts immediately know which view they're in.
export const ROLE_THEME = {
  super_admin:    { from: C.terracotta, mid: C.rose,     to: C.lavender, label: 'Super Admin',    ring: C.terracotta },
  business_owner: { from: C.ochre,      mid: C.amber,    to: C.terracotta, label: 'Business Owner', ring: C.ochre },
  manager:        { from: C.teal,       mid: C.mint,     to: C.sky,      label: 'Manager',         ring: C.teal },
  staff:          { from: C.sky,        mid: C.azure,    to: C.lavender, label: 'Staff',           ring: C.sky },
  default:        { from: C.terracotta, mid: C.ochre,    to: C.rose,     label: 'FidClic',      ring: C.terracotta },
};

export const themeForRole = (role) => ROLE_THEME[role] || ROLE_THEME.default;

/**
 * PageHeader — the consistent slot at the top of every page.
 * Eyebrow + Cormorant title + Manrope description + optional right-side actions.
 */
export const PageHeader = ({ eyebrow, title, description, actions, role = 'default', live = true }) => {
  const theme = themeForRole(role);
  return (
    <div className="relative mb-6">
      <div className="relative flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {eyebrow && (
            <div
              className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[10px] uppercase tracking-[0.16em] mb-2"
              style={{
                background: 'transparent',
                color: 'var(--ink-mute)',
                fontWeight: 600,
              }}
            >
              {eyebrow}
            </div>
          )}
          <h1
            className="flex items-center gap-3 text-[26px] md:text-[30px] leading-[1.1]"
            style={{
              color: 'var(--ink)',
              fontWeight: 500,
              letterSpacing: '-0.022em',
            }}
          >
            <span>{title}</span>
            {live && (
              <span
                className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] uppercase"
                style={{
                  background: 'var(--tone-success-fill)',
                  color: 'var(--tone-success-ink)',
                  letterSpacing: '0.12em',
                  fontWeight: 600,
                }}
              >
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--tone-success-line)' }}></span>
                Live
              </span>
            )}
          </h1>
          {description && (
            <p className="mt-1.5 text-[13.5px] max-w-2xl" style={{ color: 'var(--ink-mute)', fontWeight: 400 }}>
              {description}
            </p>
          )}
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>
    </div>
  );
};

/**
 * StatCard — modern KPI tile.
 *
 * Variants:
 *   - `accent` (default) → soft tinted background + colored icon chip
 *   - `dark` → premium dark card (use sparingly, ~1 per row max)
 *
 * Always renders the icon as a colored chip in the top-right — clean and
 * scannable in a 4-up KPI row.
 */
export const StatCard = ({
  label,
  value,
  sublabel,
  icon: Icon,
  trend,           // optional: { delta: '+12%', positive: true }
  color = C.terracotta,
  variant = 'accent',
  onClick,
  className = '',
}) => {
  const dark = variant === 'dark';
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag
      onClick={onClick}
      className={`relative w-full text-left p-5 rounded-2xl overflow-hidden transition-all
        ${onClick ? 'cursor-pointer hover:-translate-y-0.5 hover:shadow-lg' : ''}
        ${className}`}
      style={
        dark
          ? {
              background: `linear-gradient(135deg, ${C.inkDeep} 0%, ${C.inkSoft} 100%)`,
              color: 'white',
              boxShadow: '0 1px 2px rgba(28,25,23,0.05)',
            }
          : {
              background: 'var(--flc-card, #FFFFFF)',
              border: `1px solid ${C.hairline}`,
              boxShadow: '0 1px 2px rgba(28,25,23,0.04)',
            }
      }
    >
      {/* Subtle blob in the corner for depth */}
      <div
        aria-hidden="true"
        className="absolute -top-10 -right-10 w-32 h-32 rounded-full blur-2xl opacity-30 pointer-events-none"
        style={{ background: color }}
      />
      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className={`text-[11px] font-bold uppercase tracking-[0.14em] ${dark ? 'text-white/60' : ''}`}
             style={dark ? {} : { color: C.inkMute }}>
            {label}
          </p>
          <p
            className={`mt-2 font-['Cormorant_Garamond'] font-bold leading-none ${dark ? 'text-white' : ''}`}
            style={{ fontSize: 36, color: dark ? '#fff' : C.inkDeep }}
          >
            {value}
          </p>
          {sublabel && (
            <p className={`mt-1.5 text-xs ${dark ? 'text-white/60' : ''}`} style={dark ? {} : { color: C.inkMute }}>
              {sublabel}
            </p>
          )}
          {trend && (
            <div className="mt-2 inline-flex items-center gap-1 text-xs font-semibold"
                 style={{ color: trend.positive ? C.sage : C.terracotta }}>
              <span>{trend.positive ? '↑' : '↓'}</span>
              <span>{trend.delta}</span>
            </div>
          )}
        </div>
        {Icon && (
          <div
            className="shrink-0 w-10 h-10 rounded-xl flex items-center justify-center"
            style={{
              background: dark ? 'rgba(255,255,255,0.08)' : `${color}1A`,
              color: dark ? '#fff' : color,
              border: dark ? '1px solid rgba(255,255,255,0.12)' : `1px solid ${color}33`,
            }}
          >
            <Icon size={18} />
          </div>
        )}
      </div>
    </Tag>
  );
};

/**
 * Section — content wrapper used to group related widgets on a page.
 * Card-like surface with consistent padding, optional header.
 */
export const Section = ({ title, hint, actions, children, className = '' }) => (
  <section
    className={`bg-white border rounded-2xl p-6 ${className}`}
    style={{ borderColor: C.hairline, boxShadow: '0 1px 2px rgba(28,25,23,0.04)' }}
  >
    {(title || actions) && (
      <header className="flex items-start justify-between gap-4 mb-4">
        <div>
          {title && (
            <h2
              className="font-['Cormorant_Garamond'] text-2xl font-semibold leading-tight"
              style={{ color: C.inkDeep }}
            >
              {title}
            </h2>
          )}
          {hint && <p className="mt-1 text-sm" style={{ color: C.inkMute }}>{hint}</p>}
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </header>
    )}
    {children}
  </section>
);

/** PrimaryButton — gradient pill matching the role accent. */
export const PrimaryButton = ({ role = 'default', className = '', children, ...rest }) => {
  const theme = themeForRole(role);
  return (
    <button
      {...rest}
      className={`inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-full text-sm font-semibold text-white transition-all shadow-md hover:-translate-y-0.5 hover:shadow-lg ${className}`}
      style={{ background: `linear-gradient(135deg, ${theme.from} 0%, ${theme.to} 100%)` }}
    >
      {children}
    </button>
  );
};

/** SecondaryButton — outline style for less-prominent actions. */
export const SecondaryButton = ({ className = '', children, ...rest }) => (
  <button
    {...rest}
    className={`inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-full text-sm font-semibold transition-all hover:bg-[${C.cream}] ${className}`}
    style={{
      border: `1px solid ${C.hairline}`,
      color: C.inkSoft,
      background: 'var(--flc-card, #FFFFFF)',
    }}
  >
    {children}
  </button>
);

/** Animated gradient background — subtle moving radial mesh used as the
    page-level body backdrop. Performance is fine; pure CSS keyframes. */
export const AmbientBackdrop = ({ role = 'default' }) => {
  const theme = themeForRole(role);
  return (
    <>
      <style>{`
        @keyframes shellOrb1 { 0%,100% { transform: translate(0,0); } 50% { transform: translate(30px,40px); } }
        @keyframes shellOrb2 { 0%,100% { transform: translate(0,0); } 50% { transform: translate(-40px,-30px); } }
      `}</style>
      <div aria-hidden="true" className="fixed inset-0 pointer-events-none -z-0">
        <div
          className="absolute top-[-10%] right-[-10%] w-[40vw] h-[40vw] rounded-full blur-3xl opacity-15"
          style={{ background: theme.from, animation: 'shellOrb1 18s ease-in-out infinite' }}
        />
        <div
          className="absolute bottom-[-15%] left-[-10%] w-[45vw] h-[45vw] rounded-full blur-3xl opacity-10"
          style={{ background: theme.to, animation: 'shellOrb2 22s ease-in-out infinite' }}
        />
      </div>
    </>
  );
};

export default {
  C, ROLE_THEME, themeForRole,
  PageHeader, StatCard, Section, PrimaryButton, SecondaryButton, AmbientBackdrop,
};
