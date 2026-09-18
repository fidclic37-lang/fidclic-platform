/**
 * MarketingChrome — shared nav, footer and palette for the public marketing
 * pages (landing, /facturation-electronique, /experts-comptables).
 *
 * WHY THIS EXISTS
 *   Each product line deserves a real page, not an anchor buried in the
 *   homepage — an accountant landing on "Experts-comptables" should feel the
 *   whole page was built for them. That means three pages sharing one chrome,
 *   so the header/footer never drift apart. The palette lives here too, so a
 *   future redesign (21st.dev inspiration) changes one file, not three.
 */
import React from 'react';
import { Link, useLocation } from 'react-router-dom';

/** Brand palette — single source of truth for the marketing surfaces. */
export const C = {
  terracotta: '#B85C38',
  ochre: '#E3A869',
  rose: '#D77FA0',
  lavender: '#B85C38',
  sky: '#6BA4D9',
  teal: '#6FA89C',
  sage: '#88B27E',
  coral: '#F08C7A',
  cream: '#FAFAF8',
  sand: '#F5EFE5',
  shellPink: '#FCE3DC',
  blush: '#FBE0E8',
  lilac: '#F0EBF8',
  azure: '#DDEBF6',
  mint: '#DDF1ED',
  meadow: '#E5F0DC',
  butter: '#FDF1DC',
  inkDeep: '#171412',
  inkSoft: '#3D2820',
  inkMute: '#57504A',
  inkFaint: '#8D857D',
  hairline: '#EFE9E0',
};

export const Eyebrow = ({ children, color = C.terracotta, bg = C.shellPink }) => (
  <span className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full text-xs font-bold tracking-wide uppercase"
        style={{ color, background: bg }}>
    {children}
  </span>
);

/**
 * Shared top navigation.
 * `active` highlights the current product page so the visitor always knows
 * which of the three worlds they are standing in.
 */
export function MarketingNav({ active }) {
  const { pathname } = useLocation();
  const cur = active || pathname;
  const link = (to, label, color, dot) => {
    const isActive = cur === to;
    return (
      <Link key={to} to={to}
            className="transition-colors flex items-center gap-1.5"
            style={{ color: isActive ? color : undefined,
                     fontWeight: isActive ? 700 : 500 }}>
        {label}
        {dot && <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />}
      </Link>
    );
  };
  return (
    <nav className="fixed w-full backdrop-blur-md border-b z-50"
         style={{ background: 'rgba(253,251,247,0.85)', borderColor: C.hairline }}>
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
        <div className="hidden md:flex items-center gap-7 font-medium text-sm">
          {link('/', 'Fidélité', C.terracotta)}
          {link('/facturation-electronique', 'Facturation 2026', C.sky, true)}
          {link('/experts-comptables', 'Experts-comptables', C.lavender)}
          <a href="/#pricing" className="hover:text-[#B85C38] transition-colors">Tarifs</a>
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
  );
}

export function MarketingFooter() {
  return (
    <footer className="relative bg-white border-t py-14" style={{ borderColor: C.hairline }}>
      <div aria-hidden="true" className="absolute top-0 left-0 right-0 h-1"
           style={{ background: `linear-gradient(90deg, ${C.terracotta} 0%, ${C.rose} 16%, ${C.lavender} 33%, ${C.sky} 50%, ${C.teal} 66%, ${C.sage} 83%, ${C.ochre} 100%)` }} />
      <div className="max-w-7xl mx-auto px-4" style={{ color: C.inkMute }}>
        <div className="grid md:grid-cols-3 gap-8 mb-10">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <div className="w-9 h-9 rounded-xl flex items-center justify-center text-white font-bold text-xl shadow-lg"
                   style={{ background: `linear-gradient(135deg, ${C.terracotta} 0%, ${C.rose} 100%)` }}>F</div>
              <p className="font-['Cormorant_Garamond'] text-2xl font-bold ft-gradient-text-slow">FidClic</p>
            </div>
            <p className="text-sm">Fidélité et facturation électronique, dans un seul outil pensé pour les TPE françaises.</p>
          </div>
          <div>
            <p className="font-bold text-sm mb-3" style={{ color: C.inkDeep }}>Produits</p>
            <ul className="space-y-2 text-sm">
              <li><Link to="/" className="hover:underline">Programme de fidélité</Link></li>
              <li><Link to="/facturation-electronique" className="hover:underline">Facturation électronique 2026</Link></li>
              <li><Link to="/experts-comptables" className="hover:underline">Espace Cabinet</Link></li>
            </ul>
          </div>
          <div>
            <p className="font-bold text-sm mb-3" style={{ color: C.inkDeep }}>Commencer</p>
            <ul className="space-y-2 text-sm">
              <li><Link to="/register" className="hover:underline">Créer un compte</Link></li>
              <li><Link to="/login" className="hover:underline">Se connecter</Link></li>
              <li><a href="/#pricing" className="hover:underline">Voir les tarifs</a></li>
            </ul>
          </div>
        </div>
        <div className="text-center border-t pt-8" style={{ borderColor: C.hairline }}>
          <p className="text-sm">© {new Date().getFullYear()} FidClic · Conçu en France pour les commerçants français.</p>
          <div className="flex justify-center gap-2 mt-5">
            {[C.terracotta, C.rose, C.lavender, C.sky, C.teal, C.sage, C.ochre].map((c, i) => (
              <span key={i} className="w-1.5 h-1.5 rounded-full" style={{ background: c }} />
            ))}
          </div>
        </div>
      </div>
    </footer>
  );
}

/** Small reusable FAQ accordion used by both product pages. */
export function Faq({ items, accent = C.terracotta }) {
  const [open, setOpen] = React.useState(0);
  return (
    <div className="space-y-3">
      {items.map((it, i) => (
        <div key={it.q} className="rounded-2xl bg-white border overflow-hidden" style={{ borderColor: C.hairline }}>
          <button onClick={() => setOpen(open === i ? -1 : i)}
                  className="w-full flex items-center justify-between gap-4 px-5 py-4 text-left">
            <span className="font-semibold text-[15px]" style={{ color: C.inkDeep }}>{it.q}</span>
            <span className="text-xl leading-none shrink-0" style={{ color: accent }}>{open === i ? '−' : '+'}</span>
          </button>
          {open === i && (
            <div className="px-5 pb-5 text-sm leading-relaxed" style={{ color: C.inkMute }}>{it.a}</div>
          )}
        </div>
      ))}
    </div>
  );
}
