import React, { useEffect, useState } from 'react';
import { Camera, Flashlight, Lock } from 'lucide-react';

/**
 * The customer's iPhone, locked, the moment the campaign lands (user,
 * 2026-10-02: « isko aur zyada proper banao »). It shows exactly what each
 * channel puts on the screen:
 *
 *   Notification push   the FidClic app (the card added to the home screen):
 *                       its icon, the title in bold, the message — iOS keeps
 *                       one line of title and four of message.
 *   Carte Wallet        Apple Wallet raising the card's change: the card's
 *                       logo, the commerce's name, then « titre · message »
 *                       (the offer field of the pass, wallet_passes.py).
 *
 * A scheduled campaign shows its own day and hour on the lock screen.
 */
const FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", system-ui, sans-serif';
const DISPLAY = '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Helvetica Neue", system-ui, sans-serif';

const clamp = (lines) => ({ display: '-webkit-box', WebkitLineClamp: lines, WebkitBoxOrient: 'vertical', overflow: 'hidden' });

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30 * 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

const Status = () => (
  <div className="flex items-center gap-[5px]" aria-hidden="true">
    <svg width="16" height="10" viewBox="0 0 16 10" fill="white">
      <rect x="0" y="7" width="3" height="3" rx=".7" /><rect x="4.3" y="5" width="3" height="5" rx=".7" />
      <rect x="8.6" y="2.6" width="3" height="7.4" rx=".7" /><rect x="12.9" y="0" width="3" height="10" rx=".7" />
    </svg>
    <svg width="14" height="10" viewBox="0 0 14 10" fill="white">
      <path d="M7 2.2c2 0 3.8.8 5.1 2l1-1A8.6 8.6 0 0 0 7 .8 8.6 8.6 0 0 0 .9 3.2l1 1A7.2 7.2 0 0 1 7 2.2Zm0 2.9c1.2 0 2.3.5 3.1 1.2l1-1A5.8 5.8 0 0 0 7 3.7a5.8 5.8 0 0 0-4.1 1.6l1 1A4.4 4.4 0 0 1 7 5.1Zm0 2.9c.4 0 .8.2 1.1.4L7 9.6 5.9 8.4c.3-.2.7-.4 1.1-.4Z" />
    </svg>
    <span className="relative inline-block h-[10px] w-[21px] rounded-[3px] border border-white/45 p-[1.2px]">
      <span className="block h-full w-[78%] rounded-[1.5px] bg-white" />
      <span className="absolute -right-[3px] top-[3px] h-[3px] w-[1.5px] rounded-r bg-white/45" />
    </span>
  </div>
);

function AppIcon({ src, letter }) {
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [src]);
  return src && !broken
    ? <img src={src} alt="" onError={() => setBroken(true)} className="h-[32px] w-[32px] shrink-0 rounded-[8px] bg-white object-cover" />
    : <span className="grid h-[32px] w-[32px] shrink-0 place-items-center rounded-[8px] bg-[#1450B8] text-[14px] font-bold text-white">{letter}</span>;
}

const Banner = ({ icon, letter, title, body, ghost, testid }) => (
  <div data-testid={testid}
       className="flex gap-[9px] rounded-[20px] px-[10px] py-[9px] shadow-[0_6px_18px_-10px_rgba(0,0,0,.35)]"
       style={{ background: 'rgba(246,246,250,.78)', backdropFilter: 'blur(18px)', WebkitBackdropFilter: 'blur(18px)' }}>
    <AppIcon src={icon} letter={letter} />
    <div className="min-w-0 flex-1">
      <div className="flex items-baseline gap-2">
        <p className={`min-w-0 flex-1 truncate text-[12.5px] font-semibold leading-[1.25] ${ghost ? 'text-[#1C1C1E]/45' : 'text-[#1C1C1E]'}`}>{title}</p>
        <span className="shrink-0 text-[10.5px] text-[#3C3C43]/60">maintenant</span>
      </div>
      <p className={`mt-[1px] break-words text-[12px] leading-[1.3] ${ghost ? 'text-[#1C1C1E]/45' : 'text-[#1C1C1E]'}`} style={clamp(4)}>{body}</p>
    </div>
  </div>
);

export default function PushPreview({ title, message, image, push = true, wallet = true, walletName, logo, at }) {
  const now = useClock();
  const when = at ? new Date(at) : now;
  const day = when.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' });
  const hour = when.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  const t = title.trim(), m = message.trim();
  const shop = walletName || 'Votre commerce';

  return (
    <div style={{ fontFamily: FONT }}>
      <div className="mx-auto w-[262px] rounded-[46px] bg-[#0B0B0F] p-[8px] shadow-[0_30px_60px_-28px_rgba(11,28,63,.75),inset_0_0_0_1.5px_#2A2A30]">
        <div className="relative flex h-[540px] flex-col overflow-hidden rounded-[38px]"
             style={{ background: 'radial-gradient(120% 70% at 15% 0%, #5B8CFF 0%, transparent 55%), radial-gradient(90% 60% at 100% 100%, #9B5CF6 0%, transparent 60%), linear-gradient(170deg,#1E3FAE 0%,#3B2DB8 48%,#5B21B6 100%)' }}>
          {/* status bar + Dynamic Island */}
          <div className="relative flex h-[34px] items-center justify-between px-[22px] pt-[6px]">
            <span className="w-[42px]" />
            <span className="absolute left-1/2 top-[8px] h-[22px] w-[78px] -translate-x-1/2 rounded-full bg-black" />
            <Status />
          </div>

          {/* lock, date, time */}
          <div className="mt-1.5 flex flex-col items-center text-white">
            <Lock size={12} strokeWidth={2.6} className="opacity-90" />
            <p className="mt-1.5 text-[13px] font-semibold opacity-90" data-testid="push-day">{day}</p>
            <p className="text-[64px] font-semibold leading-[1] tracking-[-0.02em]" style={{ fontFamily: DISPLAY }} data-testid="push-hour">{hour}</p>
          </div>

          {/* notifications, at the bottom as on iOS */}
          <div className="mt-auto space-y-[6px] px-[9px] pb-[12px]">
            {!push && !wallet ? (
              <p className="rounded-[18px] bg-black/25 px-3 py-2.5 text-center text-[11px] leading-snug text-white/90">
                Aucun canal choisi : rien n'arrivera sur le téléphone.
              </p>
            ) : (
              <>
                {wallet && (
                  <Banner testid="push-wallet" icon={logo} letter={shop.charAt(0).toUpperCase()} title={shop}
                          ghost={!t && !m}
                          body={t || m ? [t, m].filter(Boolean).join(' · ') : "L'offre de la carte change : titre · message."} />
                )}
                {push && (
                  <Banner testid="push-push" icon="/icon-192.png" letter="F"
                          ghost={!t && !m}
                          title={t || 'Titre de votre notification'}
                          body={m || 'Le message que vos clients recevront apparaît ici.'} />
                )}
              </>
            )}
          </div>

          {/* flashlight, camera, home bar */}
          <div className="flex items-center justify-between px-[30px] pb-[10px]">
            {[Flashlight, Camera].map((I, i) => (
              <span key={i} className="grid h-[38px] w-[38px] place-items-center rounded-full bg-black/25 text-white"
                    style={{ backdropFilter: 'blur(10px)', WebkitBackdropFilter: 'blur(10px)' }}>
                <I size={16} />
              </span>
            ))}
          </div>
          <span className="mx-auto mb-[7px] block h-[4px] w-[96px] rounded-full bg-white/90" />
        </div>
      </div>
      <p className="mt-2.5 text-center text-[10.5px] leading-snug text-[#94A3B8]">
        Aperçu iPhone, écran verrouillé{at ? ' — à l’heure prévue' : ''}.
      </p>
      {image && (
        <p className="mt-1 text-center text-[10.5px] leading-snug text-[#94A3B8]">
          L'image ne s'affiche pas dans la notification : le client la voit en ouvrant l'offre sur sa carte.
        </p>
      )}
    </div>
  );
}
