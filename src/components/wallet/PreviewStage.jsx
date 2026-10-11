import React from 'react';

/**
 * The Carte de fidélité redesign's preview stage (user, 2026-10-11 mockups):
 * the Apple / Google switch, the « iOS 27 / iOS 26 et avant » buttons, and an
 * iPhone frame around the pass the server built — one iPhone at a time.
 */

// the marks used by the wallet switch — glyphs, not the companies' artwork
export const AppleMark = ({ size = 18, className = '' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className={className}>
    <path d="M16.37 12.6c-.02-2.3 1.88-3.4 1.96-3.46-1.07-1.56-2.73-1.78-3.32-1.8-1.41-.14-2.76.83-3.48.83-.72 0-1.82-.81-3-.79-1.54.02-2.96.9-3.76 2.28-1.6 2.78-.41 6.9 1.15 9.16.76 1.1 1.67 2.34 2.86 2.3 1.15-.05 1.58-.74 2.97-.74 1.38 0 1.78.74 2.99.72 1.24-.02 2.02-1.12 2.77-2.23.87-1.28 1.23-2.52 1.25-2.58-.03-.01-2.39-.92-2.41-3.65zM14.1 5.86c.63-.77 1.06-1.83.94-2.9-.91.04-2.02.61-2.67 1.37-.58.67-1.1 1.76-.96 2.8 1.02.08 2.06-.52 2.69-1.27z" />
  </svg>
);

export const GoogleWalletMark = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
    <rect x="2" y="4" width="20" height="5" rx="2.2" fill="#EA4335" />
    <rect x="2" y="7.5" width="20" height="5" rx="2.2" fill="#FBBC04" />
    <rect x="2" y="11" width="20" height="5" rx="2.2" fill="#34A853" />
    <path d="M2 15.2c0-1 .8-1.7 1.8-1.7h4.6c1.1 0 1.6.9 3.6.9s2.5-.9 3.6-.9h4.6c1 0 1.8.7 1.8 1.7v2.6c0 1.2-1 2.2-2.2 2.2H4.2C3 20 2 19 2 17.8z" fill="#4285F4" />
  </svg>
);

/** Apple Wallet / Google Wallet — two equal halves, the chosen one blue. */
export function WalletSwitch({ value, onChange }) {
  const opts = [['apple', 'Apple Wallet', <AppleMark key="a" size={19} />], ['google', 'Google Wallet', <GoogleWalletMark key="g" size={21} />]];
  return (
    <div className="grid grid-cols-2 gap-1 rounded-2xl border border-[#E6EEFB] bg-[#F4F7FC] p-1">
      {opts.map(([k, label, icon]) => (
        <button key={k} type="button" onClick={() => onChange(k)} aria-pressed={value === k}
                className={`flex h-12 items-center justify-center gap-2.5 rounded-xl text-[14px] font-semibold transition ${value === k
                  ? 'bg-[#2F6BFF] text-white shadow-[0_10px_22px_-12px_rgba(47,107,255,.9)]'
                  : 'text-[#334155] hover:bg-white'}`}>
          {icon} {label}
        </button>
      ))}
    </div>
  );
}

/** « iOS 27 · Nouveau » / « iOS 26 et avant » — the version the iPhone shows. */
export function VersionSwitch({ views, value, onChange }) {
  return (
    <div className={`grid gap-3 ${views.length > 1 ? 'grid-cols-2' : 'grid-cols-1'}`}>
      {views.map((v) => {
        const on = v.key === value;
        return (
          <button key={v.key} type="button" onClick={() => onChange(v.key)} aria-pressed={on}
                  className={`flex items-center gap-3 rounded-2xl border px-4 py-3 text-left transition ${on
                    ? 'border-[#2F6BFF] bg-[#F2F7FF] shadow-[0_0_0_1px_#2F6BFF_inset]'
                    : 'border-[#E6EEFB] bg-[#F8FAFF] hover:border-[#B9CCF5]'}`}>
            <AppleMark size={26} className="shrink-0 text-[#0B1C3F]" />
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-2">
                <span className={`text-[15px] font-semibold ${on ? 'text-[#2F6BFF]' : 'text-[#0B1C3F]'}`}>{v.title}</span>
                {v.badge && <span className="rounded-full bg-[#2F6BFF] px-2 py-0.5 text-[10.5px] font-bold text-white">{v.badge}</span>}
              </span>
              <span className={`block text-[12.5px] ${on ? 'text-[#2F6BFF]' : 'text-[#64748B]'}`}>{v.sub}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** An iPhone around the pass, at a real iPhone's proportions (393 × 852 pt).
 *  `chrome="ios26"` draws Wallet's pass screen as iOS 26 shows it (checked on
 *  device screenshots, 2026-10-11): dark background, a round glass « ✕ » at
 *  the top left, share and « ••• » top right, the pass at ~88 % of the screen
 *  width right under them. `screenW` tells the caller how wide the screen is. */
export const screenWidth = (width) => width - 2 * (9 * width / 300);

export function IphoneFrame({ children, width = 300, chrome = 'none', dark = false }) {
  const s = width / 300;
  const pad = 9 * s;
  const screenW = width - 2 * pad;
  const screenH = screenW * (852 / 393);
  const night = dark || chrome === 'ios26';
  const ink = night ? '#FFFFFF' : '#0B0B0F';
  const glass = { background: 'rgba(255,255,255,.14)', backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
    boxShadow: 'inset 0 0 0 0.5px rgba(255,255,255,.22)' };
  return (
    <div className="relative mx-auto" style={{ width }}>
      <div className="relative rounded-[48px] bg-[#1B1D22] shadow-[0_30px_60px_-30px_rgba(11,28,63,.55)]" style={{ padding: pad }}>
        <div className="relative overflow-hidden" style={{ height: screenH, borderRadius: 40 * s, background: night ? '#000' : '#F2F2F7' }}>
          <div className="flex items-center justify-between font-semibold"
               style={{ height: 46 * s, padding: `0 ${26 * s}px`, fontSize: 14 * s, color: ink }}>
            <span>9:41</span>
            <span className="flex items-center gap-1" aria-hidden="true">
              <svg width={17 * s} height={11 * s} viewBox="0 0 17 11" fill="currentColor"><rect x="0" y="7" width="3" height="4" rx=".7" /><rect x="4.5" y="5" width="3" height="6" rx=".7" /><rect x="9" y="2.5" width="3" height="8.5" rx=".7" /><rect x="13.5" y="0" width="3" height="11" rx=".7" /></svg>
              <svg width={15 * s} height={11 * s} viewBox="0 0 15 11" fill="currentColor"><path d="M7.5 2.2c2.1 0 4 .8 5.4 2.1l1.1-1.1A9.2 9.2 0 0 0 7.5.6 9.2 9.2 0 0 0 1 3.2l1.1 1.1a7.6 7.6 0 0 1 5.4-2.1zm0 3.1c1.2 0 2.4.5 3.2 1.3l1.1-1.1a6.1 6.1 0 0 0-8.6 0l1.1 1.1c.8-.8 2-1.3 3.2-1.3zm0 3.1c.4 0 .7.1 1 .4L7.5 9.9 6.5 8.8c.3-.3.6-.4 1-.4z" /></svg>
              <svg width={25 * s} height={12 * s} viewBox="0 0 25 12" fill="none"><rect x=".5" y=".5" width="21" height="11" rx="3.2" stroke="currentColor" opacity=".4" /><rect x="2" y="2" width="18" height="8" rx="2" fill="currentColor" /><rect x="23" y="4" width="1.6" height="4" rx=".8" fill="currentColor" opacity=".45" /></svg>
            </span>
          </div>
          <div className="absolute left-1/2 -translate-x-1/2 rounded-full bg-black" style={{ top: 10 * s, width: 96 * s, height: 28 * s }} />
          {chrome === 'ios26' && (
            <div className="flex items-center justify-between" style={{ padding: `${2 * s}px ${14 * s}px ${8 * s}px`, color: '#fff' }} aria-hidden="true">
              <span className="flex items-center justify-center rounded-full" style={{ width: 38 * s, height: 38 * s, ...glass }}>
                <svg width={15 * s} height={15 * s} viewBox="0 0 16 16" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M3 3l10 10M13 3L3 13" /></svg>
              </span>
              <span className="flex items-center rounded-full" style={{ height: 38 * s, padding: `0 ${13 * s}px`, gap: 16 * s, ...glass }}>
                <svg width={15 * s} height={17 * s} viewBox="0 0 16 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M8 11V1.5M4.5 5 8 1.5 11.5 5M5 7.5H3.5A1.5 1.5 0 0 0 2 9v6.5A1.5 1.5 0 0 0 3.5 17h9a1.5 1.5 0 0 0 1.5-1.5V9a1.5 1.5 0 0 0-1.5-1.5H11" /></svg>
                <svg width={17 * s} height={4 * s} viewBox="0 0 17 4" fill="currentColor"><circle cx="2" cy="2" r="1.8" /><circle cx="8.5" cy="2" r="1.8" /><circle cx="15" cy="2" r="1.8" /></svg>
              </span>
            </div>
          )}
          <div className="flex justify-center" style={{ padding: `${(chrome === 'ios26' ? 2 : 8) * s}px 0 ${18 * s}px` }}>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}

/** The little dots under the iPhone: one per view, the current one blue. */
export function Dots({ views, value, onChange }) {
  if (views.length < 2) return null;
  return (
    <div className="mt-4 flex items-center justify-center gap-2">
      {views.map((v) => (
        <button key={v.key} type="button" onClick={() => onChange(v.key)} aria-label={v.title}
                className={`h-2.5 w-2.5 rounded-full transition ${v.key === value ? 'bg-[#2F6BFF]' : 'bg-[#CBD5E1] hover:bg-[#94A3B8]'}`} />
      ))}
    </div>
  );
}
