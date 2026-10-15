import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Home, Users, QrCode, Megaphone, Menu } from 'lucide-react';

/* The owner's phone (user, 2026-10-15: « mobile mein ekdm easy, especially
   for scanning »): the four places used every day under the thumb, and the
   scanner in the middle, large — one tap from any page. « Menu » opens the
   full sidebar. Its height is published as --fc-bottom-nav so a page's own
   bottom bar (the till's « Suivant ») sits right above it. */
const H = 64;

export default function BottomNav({ path, onMenu, canScan = true }) {
  useEffect(() => {
    document.documentElement.style.setProperty('--fc-bottom-nav', `${H}px`);
    return () => document.documentElement.style.removeProperty('--fc-bottom-nav');
  }, []);
  const tab = (to, label, Icon, exact = false) => {
    const on = exact ? path === to : path === to || path.startsWith(`${to}/`);
    return (
      <Link to={to} aria-current={on ? 'page' : undefined}
            className={`flex flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-semibold ${on ? 'text-[#1463FF]' : 'text-[#64748B]'}`}>
        <Icon size={21} strokeWidth={on ? 2.4 : 2} />
        {label}
      </Link>
    );
  };
  return (
    <nav aria-label="Navigation principale"
         className="fixed inset-x-0 bottom-0 z-40 border-t border-[#E6EEFB] bg-white/95 backdrop-blur"
         style={{ height: `calc(${H}px + env(safe-area-inset-bottom, 0px))`, paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}>
      <div className="mx-auto flex h-16 max-w-[560px] items-stretch">
        {tab('/dashboard', 'Accueil', Home, true)}
        {tab('/dashboard/customers', 'Clients', Users)}
        <div className="flex flex-1 items-start justify-center">
          {canScan ? (
            <Link to="/dashboard/scan" aria-label="Scanner une carte"
                  className={`flex flex-col items-center justify-center rounded-full text-white ${
                    path === '/dashboard/scan'
                      // on the till itself it stays in the bar: the page's own bar sits right above
                      ? 'mt-1.5 h-[52px] w-[52px] bg-[#1E4FD8]'
                      : '-mt-5 h-[62px] w-[62px] bg-[#1463FF] shadow-[0_12px_26px_-10px_rgba(20,99,255,.9)] ring-4 ring-white'}`}>
              <QrCode size={26} strokeWidth={2.3} />
              <span className="text-[10px] font-bold">Scanner</span>
            </Link>
          ) : <span />}
        </div>
        {tab('/dashboard/campaigns', 'Campagnes', Megaphone)}
        <button type="button" onClick={onMenu} aria-label="Ouvrir le menu"
                className="flex flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-semibold text-[#64748B]">
          <Menu size={21} /> Menu
        </button>
      </div>
    </nav>
  );
}
