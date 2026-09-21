import React from 'react';

/**
 * PhoneFrame — hyper-realistic iPhone 15 Pro mock.
 *
 * Used in Card Designer to show the wallet card EXACTLY as it appears in
 * mobile Safari on a real customer's phone. Pixel-accurate chrome:
 *
 *   - Titanium-style outer frame with proper bezels and side buttons
 *     drawn as faint highlights.
 *   - Dynamic Island notch (the rounded-pill cutout).
 *   - Status bar with carrier label, signal bars, 5G label, wifi
 *     icon, and a battery indicator with a 76% fill.
 *   - Time set to "9:41" — Apple's universal demo clock.
 *   - Safari URL bar with the address chip and a faint sub-line
 *     showing the secure-padlock + domain.
 *   - White page surface (Safari default) so the card sits where the
 *     customer will actually see it.
 *   - Home indicator bar at the very bottom, matching modern iPhones.
 *
 * Aspect ratio is now ~1.95:1 (was 2.1:1) so the phone reads as
 * "normal-sized" rather than elongated. The screen is wide enough
 * for a full wallet card without scrolling.
 *
 * Props:
 *   - children: ReactNode — wallet card (or any content)
 *   - width?: number      — frame width in px (default 280)
 *   - time?: string       — clock label
 *   - carrier?: string    — left-side carrier text (default "Orange F")
 *   - url?: string        — Safari address bar URL chip text
 *   - label?: string      — caption rendered under the phone
 */
export default function PhoneFrame({
  children,
  width = 280,
  time = '9:41',
  carrier = 'Orange F',
  url = 'app.fidclic.com',
  label,
}) {
  // Aspect ratio tightened so the phone reads as normal-sized. iPhone 15 Pro
  // body is roughly 2.17:1, but our screen is showing only the card area —
  // we don't need to mimic the full body, just enough chrome to feel real.
  const bodyH = Math.round(width * 1.95);
  const screenW = width - 12;
  const screenH = bodyH - 12;
  return (
    <div className="inline-flex flex-col items-center">
      <div
        style={{
          position: 'relative',
          width,
          height: bodyH,
          padding: 6,
          borderRadius: Math.round(width * 0.16),
          background: 'linear-gradient(180deg, #2A2421 0%, #1A1614 50%, #2A2421 100%)',
          boxShadow:
            '0 0 0 1px rgba(255,255,255,0.04) inset, ' + // subtle bezel highlight
            '0 0 0 1px #0B0908, ' +                       // outer hairline
            '0 22px 50px rgba(0,0,0,0.30), ' +            // big drop shadow
            '0 8px 16px rgba(0,0,0,0.18)',                // mid drop shadow
        }}
      >
        {/* Subtle side-button hints — drawn as 1px lighter strokes on the metal
            frame so the phone looks like an actual device, not a flat rectangle. */}
        <div aria-hidden="true" style={{ position: 'absolute', left: -1, top: '14%', width: 1, height: 30, background: 'rgba(255,255,255,0.08)', borderRadius: 1 }} />
        <div aria-hidden="true" style={{ position: 'absolute', left: -1, top: '22%', width: 1, height: 50, background: 'rgba(255,255,255,0.08)', borderRadius: 1 }} />
        <div aria-hidden="true" style={{ position: 'absolute', left: -1, top: '30%', width: 1, height: 50, background: 'rgba(255,255,255,0.08)', borderRadius: 1 }} />
        <div aria-hidden="true" style={{ position: 'absolute', right: -1, top: '20%', width: 1, height: 70, background: 'rgba(255,255,255,0.08)', borderRadius: 1 }} />

        {/* Screen */}
        <div
          style={{
            width: screenW,
            height: screenH,
            background: '#FFFFFF',
            borderRadius: Math.round(width * 0.13),
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          {/* Dynamic Island notch — pill-shaped centred at the very top */}
          <div
            aria-hidden="true"
            style={{
              position: 'absolute',
              top: 7,
              left: '50%',
              transform: 'translateX(-50%)',
              width: 88,
              height: 24,
              background: '#0B0908',
              borderRadius: 14,
              zIndex: 20,
            }}
          />

          {/* Status bar — left half is carrier+signal; right half is 5G+wifi+battery */}
          <div
            style={{
              position: 'absolute',
              top: 13,
              left: 16,
              right: 16,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              color: '#171412',
              fontFamily: "'Inter', system-ui, sans-serif",
              zIndex: 15,
              fontSize: 12,
              fontWeight: 600,
              letterSpacing: '-0.01em',
            }}
          >
            {/* LEFT: clock */}
            <span style={{ width: 60, paddingLeft: 4 }}>{time}</span>
            {/* RIGHT: signal · 5G · wifi · battery */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              {/* Cellular signal — 4 ascending bars, all solid (full signal) */}
              <svg width="17" height="10" viewBox="0 0 17 10" aria-hidden="true">
                <rect x="0"  y="6.5" width="3" height="3.5" rx="0.6" fill="#171412" />
                <rect x="4"  y="4.5" width="3" height="5.5" rx="0.6" fill="#171412" />
                <rect x="8"  y="2.5" width="3" height="7.5" rx="0.6" fill="#171412" />
                <rect x="12" y="0.5" width="3" height="9.5" rx="0.6" fill="#171412" />
              </svg>
              {/* 5G label — Apple shows this when 5G is reachable */}
              <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '-0.02em' }}>5G</span>
              {/* Wifi — concentric arcs */}
              <svg width="15" height="11" viewBox="0 0 15 11" aria-hidden="true">
                <path d="M7.5 10.2a1.1 1.1 0 100-2.2 1.1 1.1 0 000 2.2zM7.5 6.6a3.3 3.3 0 012.35.97l1.05-1.05a4.8 4.8 0 00-6.8 0L5.15 7.57A3.3 3.3 0 017.5 6.6zm0-3.6a6.9 6.9 0 014.93 2.05l1.05-1.05A8.4 8.4 0 007.5 1.4 8.4 8.4 0 001.52 4l1.05 1.05A6.9 6.9 0 017.5 3z" fill="#171412"/>
              </svg>
              {/* Battery — hollow rounded rectangle + inner fill ~76% + nub on the right */}
              <svg width="26" height="11" viewBox="0 0 26 11" aria-hidden="true">
                <rect x="0.5" y="0.5" width="21" height="10" rx="2.4" fill="none" stroke="#171412" strokeOpacity="0.5" />
                <rect x="2.2" y="2.2" width="15.6" height="6.6" rx="1.2" fill="#171412" />
                <rect x="22.5" y="3.5" width="2" height="4" rx="0.6" fill="#171412" fillOpacity="0.4" />
              </svg>
            </div>
          </div>

          {/* Safari address bar — rounded grey URL chip below the top toolbar. */}
          <div
            style={{
              position: 'absolute',
              top: 38,
              left: 0,
              right: 0,
              padding: '8px 16px 6px',
              background: 'rgba(245,243,239,0.92)',
              backdropFilter: 'blur(8px)',
              borderBottom: '0.5px solid rgba(0,0,0,0.06)',
              zIndex: 5,
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 5,
                background: '#FFFFFF',
                border: '0.5px solid rgba(0,0,0,0.06)',
                borderRadius: 10,
                padding: '5px 10px',
                fontSize: 11,
                color: '#171412',
                fontFamily: "'Inter', system-ui, sans-serif",
                fontWeight: 500,
                letterSpacing: '-0.01em',
              }}
            >
              <svg width="9" height="11" viewBox="0 0 9 11" aria-hidden="true">
                <path d="M2 4.5V3a2.5 2.5 0 015 0v1.5h1v6H1v-6h1zm1 0h3V3a1.5 1.5 0 00-3 0v1.5z" fill="#171412" fillOpacity="0.7"/>
              </svg>
              <span style={{ opacity: 0.92 }}>{url}</span>
              <svg width="10" height="10" viewBox="0 0 12 12" aria-hidden="true" style={{ opacity: 0.5 }}>
                <path d="M10 6a4 4 0 11-1.17-2.83L10 4M10 1.5V4h-2.5" fill="none" stroke="#171412" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
          </div>

          {/* Page content — wallet card sits here on white, exactly like real Safari */}
          <div
            style={{
              position: 'absolute',
              top: 78,
              left: 0,
              right: 0,
              bottom: 28,
              padding: '8px 8px 4px',
              overflow: 'hidden',
            }}
          >
            {children}
          </div>

          {/* Home indicator bar — the thin pill at the bottom of every modern iPhone */}
          <div
            aria-hidden="true"
            style={{
              position: 'absolute',
              bottom: 7,
              left: '50%',
              transform: 'translateX(-50%)',
              width: 100,
              height: 5,
              background: '#171412',
              borderRadius: 3,
              opacity: 0.85,
            }}
          />
        </div>
      </div>

      {label && (
        <p
          style={{
            marginTop: 14,
            fontSize: 11,
            color: 'var(--ink-mute, #8D857D)',
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
            fontWeight: 500,
          }}
        >
          {label}
        </p>
      )}
    </div>
  );
}
