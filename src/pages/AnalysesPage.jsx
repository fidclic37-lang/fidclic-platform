import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BarChart3, Users, Activity, Send, Crown, AlertTriangle, ShoppingBag,
  MousePointerClick, ShoppingCart, Star, MessageSquare, Repeat, Gift, UserPlus,
  ChevronRight, Download, Loader2, Info, Sparkles,
  FlaskConical,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import PeriodMenu, { periodDays, validPeriod } from '../components/PeriodMenu';
import { flash } from '../lib/flash';
import InfoTip from '../components/InfoTip';
import ImpactFidClicCard from '../components/ImpactFidClicCard';
import { Uplift, HowItWorks } from '../components/TemoinResult';
import TrendChart from '../components/TrendChart';
import ProductReturnBlock from '../components/ProductReturnBlock';
import { eur } from '../lib/money';

/**
 * Analyses — eight tabs over one window, built to the approved design.
 *
 * One tab is fetched at a time: they share a reader on the server but the page
 * only pays for the one on screen.
 *
 * Nothing is painted in. A panel with no rows behind it says so rather than
 * drawing a plausible chart, and the two figures that could be read as more
 * than they are — attributed revenue and the retention rate — carry the
 * server's own caveat underneath them.
 */
const ICONS = {
  users: Users, activity: Activity, send: Send, crown: Crown, alert: AlertTriangle,
  bag: ShoppingBag, chart: BarChart3, click: MousePointerClick, cart: ShoppingCart,
  star: Star, message: MessageSquare, repeat: Repeat, gift: Gift, userplus: UserPlus,
  sparkles: Sparkles,
};
const TONES = {
  blue:   { bg: '#EAF1FF', fg: '#1D4ED8', dot: '#2F6BFF' },
  green:  { bg: '#E7F7EE', fg: '#0F8B58', dot: '#10B981' },
  amber:  { bg: '#FFF7E6', fg: '#B45309', dot: '#F59E0B' },
  violet: { bg: '#F3EEFF', fg: '#6D28D9', dot: '#8B5CF6' },
  slate:  { bg: '#EEF2F8', fg: '#475569', dot: '#94A3B8' },
  rose:   { bg: '#FFF1F3', fg: '#E11D48', dot: '#F43F5E' },
};
const TONE_ORDER = ['blue', 'green', 'amber', 'violet', 'rose', 'slate'];

const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');
// 93,10 € — cents keep two digits (lib/money)
const money = eur;
const fullDate = (iso) => { const d = new Date(iso); return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`; };

// What a figure opens: a page (`to`), another tab (`tab`) or a panel of this one (`anchor`).
const OpenCtx = createContext(() => {});


// The design's tab names, and the anchors other pages link to (« Voir mes avis »).
const HASH_TABS = { reviews: 'avis', avis: 'avis', campaigns: 'campagnes', campagnes: 'campagnes',
  loyalty: 'fidelisation', fidelisation: 'fidelisation', products: 'produits', produits: 'produits',
  acquisition: 'acquisition', vue: 'vue', overview: 'vue',
  // Panels of the overview: the page opens on it and scrolls to the panel.
  impact: 'vue', moments: 'vue', hours: 'vue', comportement: 'vue', behaviour: 'vue' };
// Old links to the « Moments de visite » / « Comportement » tabs land on their panels.
const HASH_ANCHORS = { impact: 'impact', moments: 'moments', hours: 'moments',
  comportement: 'comportement', behaviour: 'comportement' };
const tabFromHash = () => HASH_TABS[(window.location.hash || '').replace('#', '').toLowerCase()] || 'vue';

/* ── pieces ───────────────────────────────────────────────────────────── */
// Each panel's « ? » (lib/metricHelp), found from its title.
const PANEL_HELP = {
  "Évolution du chiffre d'affaires": 'revenue', 'Évolution du nombre de clients': 'new_clients',
  'Segmentation comportementale': 'segmentation', 'Statut des clients': 'segmentation',
  'Panier moyen par client': 'basket_bands', 'Produits les plus populaires': 'products', 'Tous les produits': 'products',
  'Performance des campagnes': 'sales', 'Répartition par palier': 'tiers', "Heures d'affluence": 'hours',
  'Visites par jour de la semaine': 'weekdays', 'Origine des nouveaux clients': 'sources',
  'Données géographiques': 'places', 'Acquisition de nouveaux clients': 'new_clients',
};
// The tab on screen: the same figure name can mean something else on another tab.
const TabCtx = createContext('vue');
const STAT_ALIAS = { sent: 'campaigns_sent' };

const Panel = ({ title, note, children, className = '', help, id }) => (
  <section id={id} className={`scroll-mt-24 rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] ${className}`}>
    {title && (
      <h2 className="mb-4 flex items-center gap-1.5 text-[15px] font-bold text-[#0B1C3F]">
        {title} {(help || PANEL_HELP[title]) && <InfoTip k={help || PANEL_HELP[title]} />}
      </h2>
    )}
    {children}
    {note && (
      <p className="mt-3 flex items-start gap-1.5 text-[11px] leading-snug text-[#94A3B8]">
        <Info size={12} className="mt-px shrink-0" /> {note}
      </p>
    )}
  </section>
);

const Empty = ({ message }) => (
  <div className="rounded-2xl border border-dashed border-[#D9E4F7] bg-white px-6 py-16 text-center">
    <p className="mx-auto max-w-md text-[13px] text-[#64748B]">{message}</p>
  </div>
);

// The figures read big; « CA FidClic » in green (user, 2026-10-02). A figure
// that counts something opens it.
const Stat = ({ s, i = 0 }) => {
  const open = useContext(OpenCtx);
  const tab = useContext(TabCtx);
  const Icon = ICONS[s.icon] || BarChart3;
  const t = s.highlight ? TONES.green : TONES[TONE_ORDER[i % TONE_ORDER.length]];
  const good = s.lower_is_better ? (s.delta_pct ?? 0) <= 0 : (s.delta_pct ?? 0) >= 0;
  const up = (s.delta_pct ?? 0) >= 0;
  const target = s.to || s.tab || s.anchor;
  const go = () => target && open(s);
  return (
    <div data-stat={s.key} role={target ? 'button' : undefined} tabIndex={target ? 0 : undefined} onClick={go}
         onKeyDown={(e) => { if (e.key === 'Enter') go(); }}
         title={target ? 'Voir le détail' : undefined}
         className={`h-full rounded-2xl border bg-white p-4 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)] transition ${
           s.highlight ? 'border-[#BEE9D2]' : 'border-[#E6EEFB]'} ${
           target ? 'cursor-pointer hover:border-[#BFD3FF] hover:shadow-[0_18px_40px_-28px_rgba(47,107,255,.45)]' : ''}`}>
      <span className="mb-2 flex h-9 w-9 items-center justify-center rounded-xl"
            style={{ background: t.bg, color: t.fg }}>
        <Icon size={17} />
      </span>
      <p className="whitespace-nowrap text-[23px] font-extrabold leading-none tabular-nums"
         style={{ color: s.highlight ? '#0F8B58' : '#0B1C3F' }}>
        {s.unit === '€' ? money(s.value) : `${nf(s.value)}${s.unit || ''}`}
      </p>
      <p className="mt-1 flex items-center gap-1 text-[11.5px] font-medium leading-tight text-[#64748B]">
        {s.label} <InfoTip k={STAT_ALIAS[s.key] || s.key} page={tab} size={12} />
      </p>
      {s.hint && <p className="mt-0.5 text-[10.5px] leading-tight text-[#94A3B8]">{s.hint}</p>}
      {s.delta_pct !== null && s.delta_pct !== undefined && (
        <span className="mt-1.5 inline-flex rounded-md px-1.5 py-0.5 text-[11px] font-semibold"
              style={good ? { background: '#E7F7EE', color: '#0F8B58' } : { background: '#FEECEC', color: '#C0392B' }}>
          {up ? '↑ +' : '↓ '}{s.delta_pct}%
        </span>
      )}
    </div>
  );
};

const Total = ({ value, delta }) => (
  <p className="mb-2 flex items-baseline gap-2">
    <span className="text-[21px] font-bold text-[#0B1C3F] tabular-nums">{value}</span>
    {delta !== null && delta !== undefined && (
      <span className="rounded-md px-1.5 py-0.5 text-[11px] font-semibold"
            style={delta >= 0 ? { background: '#E7F7EE', color: '#0F8B58' }
                              : { background: '#FEECEC', color: '#C0392B' }}>
        {delta >= 0 ? `↑ +${delta}%` : `↓ ${delta}%`}
      </span>
    )}
  </p>
);

/* The strips run from two cards (Acquisition) to seven (Vue d'ensemble), so
   the column count follows the card count — a fixed seven-column grid would
   leave the tail of the shorter strips empty, and a plain flex row would
   stretch a lone wrapped card across the full width. The classes are spelled
   out so Tailwind keeps them. */
const COLS = {
  1: 'grid-cols-1',
  2: 'grid-cols-1 sm:grid-cols-2',
  3: 'grid-cols-1 sm:grid-cols-3',
  4: 'grid-cols-2 lg:grid-cols-4',
  5: 'grid-cols-2 lg:grid-cols-5',
  6: 'grid-cols-2 lg:grid-cols-3 xl:grid-cols-6',
  7: 'grid-cols-2 lg:grid-cols-4 xl:grid-cols-7',
};

// A strip may come in rows (`row` on each figure): the overview puts the
// money on the first and the visits and clients on the second.
const Strip = ({ items }) => {
  const rows = [];
  items.forEach((s) => {
    const r = s.row || 1;
    (rows[r - 1] = rows[r - 1] || []).push(s);
  });
  let n = 0;
  return rows.filter(Boolean).map((row, ri) => (
    <div key={ri} className={`mb-3 grid gap-3 last:mb-4 ${COLS[row.length] || COLS[4]}`}>
      {row.map((s) => <Stat key={s.key} s={s} i={n++} />)}
    </div>
  ));
};

// Évolution du CA / des clients — the very chart of the Tableau de bord, so
// survol and clic read the same here (user, 2026-10-16).
const Line = ({ to, openLabel, ...rest }) => {
  const open = useContext(OpenCtx);
  return <TrendChart height={190} empty="Aucune donnée."
                     openLabel={to ? openLabel : undefined}
                     onOpen={to ? () => open({ to }) : undefined} {...rest} />;
};

const Bars = ({ items, money: isMoney }) => {
  const max = Math.max(1, ...items.map((i) => i.value ?? i.count ?? 0));
  return (
    <ul className="space-y-2.5">
      {items.map((i, n) => {
        const v = i.value ?? i.count ?? 0;
        return (
          <li key={i.label || i.name} className={`flex items-center gap-3 text-[12.5px] ${i.onClick ? 'cursor-pointer rounded-lg hover:bg-[#F6F9FF]' : ''}`}
              {...(i.onClick ? { onClick: i.onClick, role: 'button', tabIndex: 0, title: i.title || 'Voir ces clients',
                                 onKeyDown: (e) => { if (e.key === 'Enter') i.onClick(); } } : {})}>
            <span className={`w-24 shrink-0 truncate sm:w-40 ${i.onClick ? 'text-[#2F6BFF] underline-offset-2 hover:underline' : 'text-[#475569]'}`} title={i.label || i.name}>{i.label || i.name}</span>
            <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-[#EEF3FB]">
              <span className="block h-full rounded-full"
                    style={{ width: `${(v / max) * 100}%`, background: TONES[TONE_ORDER[n % 6]].dot }} />
            </span>
            <span className="w-16 shrink-0 text-right font-semibold text-[#0B1C3F] tabular-nums">
              {isMoney ? money(v) : nf(v)}
            </span>
          </li>
        );
      })}
    </ul>
  );
};

const HoursGrid = ({ hours }) => (
  <>
    <div className="overflow-x-auto">
      <table className="w-full min-w-[360px] border-separate" style={{ borderSpacing: '3px' }}>
        <thead>
          <tr><th />{hours.slots.map((s) => (
            <th key={s} className="pb-1 text-[9.5px] font-medium text-[#94A3B8]">{s}</th>))}
          </tr>
        </thead>
        <tbody>
          {hours.weekdays.map((wd, r) => (
            <tr key={wd}>
              <td className="pr-2 text-right text-[10.5px] font-medium text-[#94A3B8]">{wd}</td>
              {hours.grid[r].map((n, c) => (
                <td key={c} className="h-7 rounded"
                    style={{ background: n ? `rgba(47,107,255,${0.15 + (n / (hours.peak || 1)) * 0.85})` : '#F4F7FC' }}
                    title={`${wd} ${hours.slots[c]} — ${n} visite${n > 1 ? 's' : ''}`} />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-[#94A3B8]">
      <span>Faible affluence</span>
      <span className="h-2 w-20 rounded-full" style={{ background: 'linear-gradient(to right,#F4F7FC,#2F6BFF)' }} />
      <span>Forte affluence</span>
    </div>
    {hours.outside > 0 && (
      <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-snug text-[#94A3B8]">
        <Info size={12} className="mt-px shrink-0" />
        La grille couvre {hours.covers}. {nf(hours.outside)} visite{hours.outside > 1 ? 's ont' : ' a'} eu
        lieu en dehors de ces horaires.
      </p>
    )}
  </>
);

const Donut = ({ mix, unit = 'Clients' }) => {
  const open = useContext(OpenCtx);
  const R = 52, C = 2 * Math.PI * R;
  let off = 0;
  return (
    <div className="flex flex-wrap items-center gap-6">
      <div className="relative shrink-0">
        <svg width="146" height="146" viewBox="0 0 146 146">
          <circle cx="73" cy="73" r={R} fill="none" stroke="#EEF3FB" strokeWidth="20" />
          {mix.slices.filter((s) => s.count > 0).map((s) => {
            const len = mix.total ? (s.count / mix.total) * C : 0;
            const el = <circle key={s.key} cx="73" cy="73" r={R} fill="none"
                               stroke={TONES[s.tone]?.dot || '#2F6BFF'} strokeWidth="20"
                               strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-off}
                               transform="rotate(-90 73 73)" />;
            off += len;
            return el;
          })}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-[21px] font-bold leading-none text-[#0B1C3F] tabular-nums">{nf(mix.total)}</span>
          <span className="text-[10.5px] text-[#64748B]">{unit}</span>
        </div>
      </div>
      <ul className="min-w-[180px] flex-1 space-y-2.5">
        {mix.slices.map((s) => {
          const row = (
            <>
              <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: TONES[s.tone]?.dot }} />
              <span className="min-w-0 flex-1 truncate text-[#334155]">{s.label}</span>
              {s.segment && <span className="shrink-0 text-[#94A3B8] tabular-nums">{nf(s.count)}</span>}
              <span className="w-10 shrink-0 text-right font-bold text-[#0B1C3F] tabular-nums">{s.pct}%</span>
              {s.segment && <ChevronRight size={14} className="shrink-0 text-[#94A3B8]" />}
            </>
          );
          // A slice of the clients donut opens those very clients.
          return (
            <li key={s.key}>
              {s.segment ? (
                <button type="button" onClick={() => open({ to: `/dashboard/customers?segment=${s.segment}` })}
                        className="flex w-full items-center gap-2.5 rounded-lg px-1 py-0.5 text-left text-[12.5px] transition hover:bg-[#F5F8FE]">
                  {row}
                </button>
              ) : <div className="flex items-center gap-2.5 text-[12.5px]">{row}</div>}
            </li>
          );
        })}
      </ul>
    </div>
  );
};

/* « Impact FidClic »: the card from the mockup (2026-10-10, the same as the
   Tableau de bord's), and beside it what brought the revenue, source by source. */
const ImpactPanel = ({ imp }) => (
  <div id="impact" className="mb-4 grid scroll-mt-24 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
    <ImpactFidClicCard value={imp.revenue} />
    <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
      <h3 className="text-[15px] font-bold text-[#0B1C3F]">Détail par source</h3>
      <p className="mt-1 text-[12.5px] text-[#475569]">
        <b className="text-[#0B1C3F]">{imp.share_pct}%</b> de votre chiffre d'affaires ({money(imp.revenue_total)})
        {' · '}<b className="text-[#0B1C3F] tabular-nums">{nf(imp.visits)}</b> visite{imp.visits > 1 ? 's' : ''} ramenée{imp.visits > 1 ? 's' : ''}
      </p>
      <ul className="mt-3 space-y-3">
        {imp.sources.map((x) => (
          <li key={x.key} className="text-[12.5px]">
            <div className="mb-1 flex items-center gap-2">
              <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: TONES[x.tone]?.dot }} />
              <span className="flex-1 font-medium text-[#334155]">{x.label}</span>
              <span className="text-[#94A3B8] tabular-nums">{nf(x.visits)} visite{x.visits > 1 ? 's' : ''}</span>
              <span className="w-24 text-right font-bold text-[#0B1C3F] tabular-nums">{money(x.revenue)}</span>
              <span className="w-10 text-right text-[#64748B] tabular-nums">{x.pct}%</span>
            </div>
            <span className="block h-2 overflow-hidden rounded-full bg-[#EEF3FB]">
              <span className="block h-full rounded-full" style={{ width: `${x.pct}%`, background: TONES[x.tone]?.dot }} />
            </span>
          </li>
        ))}
      </ul>
      {imp.attendus?.visits > 0 && (
        <div data-testid="attendus" className="mt-4 rounded-xl bg-[#F6F8FB] px-3 py-2.5 text-[12.5px]">
          <div className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-[#CBD5E1]" />
            <span className="flex-1 font-medium text-[#334155]">Attendus de toute façon</span>
            <span className="text-[#94A3B8] tabular-nums">{nf(imp.attendus.visits)} visite{imp.attendus.visits > 1 ? 's' : ''}</span>
            <span className="w-24 text-right font-bold text-[#64748B] tabular-nums">{money(imp.attendus.revenue)}</span>
          </div>
          <p className="mt-1 text-[11.5px] leading-snug text-[#64748B]">Après un message sans groupe témoin (anniversaire, offre, un seul client…),
            ces clients sont venus dans leur rythme habituel : ils seraient venus de toute façon. Pas comptés dans le CA FidClic.</p>
        </div>
      )}
      <p className="mt-4 flex items-start gap-1.5 text-[11px] leading-snug text-[#94A3B8]">
        <Info size={12} className="mt-px shrink-0" /> {imp.note}
      </p>
    </section>
  </div>
);

/* « Ce que FidClic vous rapporte vraiment » (user, 2026-10-25): the groupe
   témoin's answer for the period — the messaged clients against the 15 %
   kept out at random, 15 days after each send. */
const pctFr = (n) => `${String(n ?? 0).replace('.', ',')} %`;
const UpliftPanel = ({ u }) => {
  const measured = u.sent?.n > 0 && u.temoin?.n > 0;
  return (
    <section id="temoin" data-testid="uplift-panel" className="mb-4 rounded-2xl border border-[#E9E3FF] bg-[#F8F6FF] p-5">
      <h3 className="flex items-center gap-2 text-[15px] font-bold text-[#0B1C3F]"><FlaskConical size={18} className="text-[#7C3AED]" /> Ce que FidClic vous rapporte vraiment</h3>
      {!u.enabled && !measured ? (
        <p className="mt-2 text-[13px] text-[#9A3412]">Pas mesuré : le groupe témoin est désactivé (Paramètres › Notifications). Le CA FidClic ci-dessus compte
          aussi les clients qui seraient venus de toute façon.</p>
      ) : measured ? (
        <>
          <div className="mt-2"><Uplift t={u} big /></div>
          <p className="mt-1 text-[12.5px] text-[#475569]">
            Sur la période : {pctFr(u.sent.rate)} des {nf(u.sent.n)} clients messagés sont revenus, contre {pctFr(u.temoin.rate)} des {nf(u.temoin.n)} clients
            du groupe témoin ({u.share} % tirés au hasard, sans message).
          </p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {[['campagnes', 'Campagnes'], ['automatisations', 'Relances automatiques']].map(([k, l]) => {
              const b = u.by?.[k];
              const ok = b?.sent?.n > 0 && b?.temoin?.n > 0;
              return (
                <div key={k} className="rounded-xl bg-white p-3 text-[12.5px]">
                  <p className="font-semibold text-[#334155]">{l}</p>
                  {ok ? <><p className={`text-[16px] font-extrabold ${b.extra_revenue > 0 ? 'text-[#059669]' : 'text-[#475569]'}`}>
                    {b.extra_revenue > 0 ? `+${money(b.extra_revenue)}` : 'Pas d\'effet mesuré'}</p>
                    <p className="text-[#64748B]">{pctFr(b.sent.rate)} revenus avec le message · {pctFr(b.temoin.rate)} sans</p></>
                    : <p className="text-[#64748B]">Pas encore mesuré sur la période.</p>}
                </div>
              );
            })}
          </div>
          {!u.enough && <p className="mt-2 text-[12.5px] text-[#92400E]">Indicatif : {nf(u.temoin.n)} clients témoins seulement, il en faut {u.min_hold} pour conclure.</p>}
        </>
      ) : (
        <p className="mt-2 text-[13px] text-[#475569]">Pas encore de mesure sur la période : le résultat arrive {u.window_days} jours après chaque envoi avec groupe témoin
          {u.pending ? ` (${nf(u.pending)} message${u.pending > 1 ? 's' : ''} en cours de mesure)` : ''}.</p>
      )}
      {measured && u.pending > 0 && <p className="mt-1 text-[12px] text-[#64748B]">{nf(u.pending)} message{u.pending > 1 ? 's' : ''} de moins de {u.window_days} jours, encore en mesure.</p>}
      <HowItWorks t={u} />
    </section>
  );
};

/* ── tabs ─────────────────────────────────────────────────────────────── */
const TabVue = ({ d }) => (
  <>
    <Strip items={d.strip} />
    {d.impact && <ImpactPanel imp={d.impact} />}
    {d.impact?.uplift && <UpliftPanel u={d.impact.uplift} />}
    <div className="mb-4 grid gap-4 lg:grid-cols-2">
      <Panel title="Évolution du chiffre d'affaires">
        <Total value={money(d.revenue_total)} delta={d.revenue_delta} />
        <Line series={d.revenue_series} money unit="Chiffre d'affaires" />
      </Panel>
      <Panel title="Évolution du nombre de clients">
        <Total value={nf(d.new_total)} delta={d.new_delta} />
        <Line series={d.new_series} unit="Nouveaux clients"
              to="/dashboard/customers?segment=new" openLabel="Voir ces nouveaux clients" />
      </Panel>
    </div>
    {d.moments && <MomentsPanels d={d.moments} />}
    <div id="comportement" className="mb-4 grid scroll-mt-24 gap-4 lg:grid-cols-2">
      {/* The same four groups as the Clients page and the Tableau de bord (the
          shop's Règles clients); each opens its clients. */}
      <Panel title="Segmentation comportementale">
        {d.status_mix.total ? <Donut mix={d.status_mix} />
          : <p className="py-10 text-center text-[12.5px] text-[#94A3B8]">Aucun client pour l'instant.</p>}
        {d.avg_visits && (
          <p className="mt-4 border-t border-[#EEF3FB] pt-3 text-[12.5px] text-[#64748B]">
            Moyenne de <strong className="text-[#0B1C3F]">{nf(d.avg_visits.lifetime)}</strong> visites par client
            depuis l'inscription · <strong className="text-[#0B1C3F]">{nf(d.avg_visits.period)}</strong> sur la période choisie.
          </p>
        )}
      </Panel>
      {d.basket_bands && (
        <Panel title="Panier moyen par client"
               note="Ce qu'un client dépense en moyenne par visite, depuis son inscription. Clients venus au moins une fois.">
          <Bars items={d.basket_bands.map((b) => ({ label: b.label, value: b.count }))} />
        </Panel>
      )}
    </div>
    <Panel title="Produits les plus populaires">
      {d.products.length ? <Bars items={d.products.map((p) => ({ name: p.name, value: p.sales }))} />
        : <p className="py-8 text-center text-[12.5px] text-[#94A3B8]">
            Les produits apparaîtront quand vos scans enregistreront les articles.
          </p>}
    </Panel>
  </>
);

const TabCampagnes = ({ d }) => d.empty ? <Empty message={d.message} /> : (
  <>
    <Strip items={d.strip} />
    <Panel title="Performance des campagnes" note={d.note}>
      <div className="mb-4 flex flex-wrap items-baseline gap-2 rounded-xl bg-[#EAF1FF] px-4 py-3">
        <span className="text-[12.5px] text-[#1D4ED8]">Chiffre d'affaires attribué aux campagnes</span>
        <span className="ml-auto text-[19px] font-bold text-[#0B1C3F] tabular-nums">{money(d.revenue_attributed)}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse">
          <thead>
            <tr className="border-b border-[#EEF3FB] text-left">
              {['#', 'Campagne', 'Statut', 'Touchés', 'Ouvertures', 'Clics', 'Ventes', 'Conversion', 'CA généré'].map((h, i) => (
                <th key={h} className={`px-3 py-2.5 text-[11.5px] font-semibold text-[#64748B] ${i > 2 ? 'text-right' : ''}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {d.table.map((t, i) => (
              <tr key={t.id} className="border-b border-[#F4F7FC] last:border-b-0">
                <td className="px-3 py-3">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#EAF1FF] text-[10.5px] font-bold text-[#2F6BFF]">{i + 1}</span>
                </td>
                <td className="px-3 py-3 text-[12.5px] font-medium text-[#0B1C3F]">{t.name}</td>
                <td className="px-3 py-3">
                  <span className="rounded-md bg-[#E7F7EE] px-2 py-0.5 text-[11px] font-semibold text-[#0F8B58]">
                    {t.status === 'sent' ? 'Envoyée' : t.status}
                  </span>
                </td>
                <td className="px-3 py-3 text-right text-[12.5px] tabular-nums text-[#475569]">{nf(t.reach)}</td>
                <td className="px-3 py-3 text-right text-[12.5px] tabular-nums text-[#475569]">{nf(t.opens)}</td>
                <td className="px-3 py-3 text-right text-[12.5px] tabular-nums text-[#475569]">{nf(t.clicks)}</td>
                <td className="px-3 py-3 text-right text-[12.5px] tabular-nums text-[#475569]">{nf(t.sales)}</td>
                <td className="px-3 py-3 text-right text-[12.5px] font-semibold tabular-nums text-[#0B1C3F]">{t.conversion}%</td>
                <td className="px-3 py-3 text-right text-[12.5px] font-semibold tabular-nums text-[#0B1C3F]">{money(t.revenue)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  </>
);

const TabFidelisation = ({ d }) => d.empty ? <Empty message={d.message} /> : (
  <>
    <Strip items={d.strip} />
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel title="Répartition par palier" note={d.retention_note}>
        <Bars items={d.tiers.map((t) => ({ label: t.label, value: t.count }))} />
      </Panel>
      <Panel title="Statut des clients"><Donut mix={d.status_mix} /></Panel>
    </div>
  </>
);

const TabAvis = ({ d }) => d.empty ? <Empty message={d.message} /> : (
  <>
    <Strip items={d.strip} />
    <div className="mb-4 grid gap-4 lg:grid-cols-2">
      <Panel title="Répartition des notes">
        <ul className="space-y-2.5">
          {d.histogram.map((h) => (
            <li key={h.stars} className="flex items-center gap-3 text-[12.5px]">
              <span className="flex w-12 shrink-0 items-center gap-1 text-[#475569]">
                {h.stars} <Star size={11} className="text-[#F59E0B]" />
              </span>
              <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-[#EEF3FB]">
                <span className="block h-full rounded-full bg-[#F59E0B]" style={{ width: `${h.pct}%` }} />
              </span>
              <span className="w-12 shrink-0 text-right font-semibold text-[#0B1C3F] tabular-nums">{h.pct}%</span>
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title="Sujets évoqués">
        {d.topics.length ? <Bars items={d.topics.map((t) => ({ label: t.name, value: t.count }))} />
          : <p className="py-8 text-center text-[12.5px] text-[#94A3B8]">Aucun sujet identifié.</p>}
      </Panel>
    </div>
    <Panel title="Derniers avis">
      <ul className="space-y-3">
        {d.recent.map((r, i) => (
          <li key={i} className="rounded-xl border border-[#E6EEFB] p-3">
            <p className="flex items-center gap-1.5 text-[12.5px] font-semibold text-[#0B1C3F]">
              <Star size={13} className="text-[#F59E0B]" /> {r.rating} / 5
              <span className="ml-auto text-[11px] font-normal text-[#94A3B8]">{fullDate(r.at)}</span>
            </p>
            {r.text && <p className="mt-1 text-[12.5px] leading-snug text-[#475569]">« {r.text} »</p>}
          </li>
        ))}
      </ul>
    </Panel>
  </>
);

// When people come: the hours grid and the weekdays, with the busiest of each.
const MomentsPanels = ({ d }) => (
  <div id="moments" className="mb-4 grid scroll-mt-24 gap-4 lg:grid-cols-2">
    <Panel title="Heures d'affluence"><HoursGrid hours={d.hours} /></Panel>
    <Panel id="weekdays" title="Visites par jour de la semaine"
           note={'Toutes les visites de la période choisie, additionnées par jour de la semaine\u00a0: sur 30 jours, «\u00a0Lundi\u00a0» compte les visites des 4 ou 5 lundis de ces 30 jours.'}>
      <Bars items={d.weekday_bars} />
      {d.total > 0 ? (
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          <div className="rounded-xl bg-[#EAF1FF] p-3">
            <p className="text-[11px] text-[#1D4ED8]">Jour le plus fréquenté</p>
            <p className="text-[15px] font-bold text-[#0B1C3F]">
              {d.best_day.label} · {nf(d.best_day.visits)} visite{d.best_day.visits > 1 ? 's' : ''}
            </p>
          </div>
          {d.best_slot && (
            <div className="rounded-xl bg-[#E7F7EE] p-3">
              <p className="text-[11px] text-[#0F8B58]">Créneau le plus chargé</p>
              <p className="text-[15px] font-bold text-[#0B1C3F]">{d.best_slot.label}</p>
            </div>
          )}
        </div>
      ) : <p className="mt-4 text-[12.5px] text-[#94A3B8]">Aucune visite sur cette période.</p>}
    </Panel>
  </div>
);

const TabMoments = ({ d }) => d.empty ? <Empty message={d.message} /> : <MomentsPanels d={d} />;

// « Produits qui font revenir » at the top (user, 2026-10-31), above the table
const TabProduits = ({ d }) => d.empty ? <><ProductReturnBlock /><Empty message={d.message} /></> : (
  <>
    <Strip items={d.strip} />
    <ProductReturnBlock />
    <Panel title="Tous les produits">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] border-collapse">
          <thead>
            <tr className="border-b border-[#EEF3FB] text-left">
              {['#', 'Produit', 'Ventes', 'Part', 'CA généré'].map((h, i) => (
                <th key={h} className={`px-3 py-2.5 text-[11.5px] font-semibold text-[#64748B] ${i > 1 ? 'text-right' : ''}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {d.products.map((p, i) => (
              <tr key={p.name} className="border-b border-[#F4F7FC] last:border-b-0">
                <td className="px-3 py-2.5">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#EAF1FF] text-[10.5px] font-bold text-[#2F6BFF]">{i + 1}</span>
                </td>
                <td className="px-3 py-2.5 text-[12.5px] font-medium text-[#0B1C3F]">{p.name}</td>
                <td className="px-3 py-2.5 text-right text-[12.5px] tabular-nums text-[#475569]">{nf(p.sales)}</td>
                <td className="px-3 py-2.5 text-right text-[12.5px] tabular-nums text-[#475569]">{p.share}%</td>
                <td className="px-3 py-2.5 text-right text-[12.5px] font-semibold tabular-nums text-[#0B1C3F]">{money(p.revenue)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  </>
);

const TabAcquisition = ({ d }) => {
  // each source opens its clients on the Clients page — filter set, ready to
  // contact (user, 2026-10-08)
  const navigate = useNavigate();
  return d.empty ? <Empty message={d.message} /> : (
  <>
    <Strip items={d.strip} />
    <div className="mb-4 grid gap-4 lg:grid-cols-2">
      <Panel title="Origine des nouveaux clients" note={d.window_note}>
        <Bars items={d.sources.map((s) => ({ label: s.name, value: s.count,
                                             ...(s.key ? { onClick: () => navigate(`/dashboard/customers?source=${s.key}`),
                                                           title: `Voir les clients venus par ${s.name}` } : {}) }))} />
        <p className="mt-2 text-[11.5px] text-[#94A3B8]">Cliquez une source pour voir ses clients et les contacter.</p>
      </Panel>
      <Panel title="Données géographiques">
        {/* a bar opens that area's clients (user, 2026-10-21) */}
        <Bars items={d.places.map((p) => ({ label: p.name, value: p.count,
                                            ...(p.segment ? { onClick: () => navigate(`/dashboard/customers?segment=${encodeURIComponent(p.segment)}`),
                                                              title: `Voir les clients de ${p.name}` } : {}) }))} />
        <p className="mt-2 text-[11.5px] text-[#94A3B8]">Cliquez une zone pour voir ses clients et les contacter.</p>
      </Panel>
    </div>
    <Panel title="Acquisition de nouveaux clients"><Line series={d.new_series} unit="Nouveaux clients" /></Panel>
  </>
);
};

const TabComportement = ({ d }) => d.empty ? <Empty message={d.message} /> : (
  <>
    <Strip items={d.strip} />
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel title="Segmentation comportementale">
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          {d.frequency.map((f) => {
            const t = TONES[f.tone] || TONES.blue;
            return (
              <div key={f.key} className="rounded-xl p-3 text-center" style={{ background: t.bg }}>
                <p className="text-[19px] font-bold leading-none text-[#0B1C3F] tabular-nums">{nf(f.count)}</p>
                <p className="mt-1 text-[11px] font-semibold leading-tight" style={{ color: t.fg }}>{f.label}</p>
                <p className="mt-0.5 text-[10px] leading-tight text-[#94A3B8]">{f.hint}</p>
              </div>
            );
          })}
        </div>
        <p className="mt-4 text-[12.5px] text-[#64748B]">
          Moyenne de <strong className="text-[#0B1C3F]">{d.avg_visits}</strong> visites par client.
        </p>
      </Panel>
      <Panel title="Panier moyen par client">
        <Bars items={d.basket_bands.map((b) => ({ label: b.label, value: b.count }))} />
      </Panel>
    </div>
  </>
);

const RENDERERS = {
  vue: TabVue, campagnes: TabCampagnes, fidelisation: TabFidelisation, avis: TabAvis,
  moments: TabMoments, produits: TabProduits, acquisition: TabAcquisition,
  comportement: TabComportement,
};

/* ── page ─────────────────────────────────────────────────────────────── */
const PERIOD_KEY = 'fidclic:an_period';

export default function AnalysesPage() {
  const navigate = useNavigate();
  // The tab follows the address (#avis…), so « Voir mes avis » lands on the reviews.
  const [tab, setTabState] = useState(tabFromHash);
  const setTab = useCallback((key) => {
    setTabState(key);
    try { window.history.replaceState({}, '', `${window.location.pathname}${window.location.search}#${key}`); } catch (_e) { /* ignore */ }
  }, []);
  useEffect(() => {
    const onHash = () => setTabState(tabFromHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  // The period: « Aujourd'hui », a preset, or one the merchant typed — kept
  // for the next visit.
  const [period, setPeriodState] = useState(() => {
    // The Tableau de bord sends its own period along (« Impact FidClic »).
    const fromUrl = new URLSearchParams(window.location.search).get('period');
    if (validPeriod(fromUrl)) return fromUrl;
    try {
      const stored = localStorage.getItem(PERIOD_KEY);
      if (validPeriod(stored)) return stored;
    } catch (_e) { /* private window */ }
    return '30';
  });
  const setPeriod = useCallback((token) => {
    const next = validPeriod(token) ? token : '30';
    setPeriodState(next);
    try { localStorage.setItem(PERIOD_KEY, next); } catch (_e) { /* ignore */ }
  }, []);
  const days = periodDays(period);
  const [payload, setPayload] = useState(null);
  const [tabs, setTabs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [exporting, setExporting] = useState(false);

  const load = useCallback(() => {
    setLoading(true); setError('');
    ownerAPI.analyses({ tab, days })
      .then(({ data }) => { setPayload(data); if (data.tabs) setTabs(data.tabs); })
      .catch((e) => setError(e?.response?.data?.detail || 'Impossible de charger les analyses.'))
      .finally(() => setLoading(false));
  }, [tab, days]);
  useEffect(() => { load(); }, [load]);

  const exportCsv = async () => {
    setExporting(true);
    try {
      const { data: blob } = await ownerAPI.analysesExport({ days });
      const url = URL.createObjectURL(new Blob([blob], { type: 'text/csv;charset=utf-8' }));
      const a = document.createElement('a');
      a.href = url; a.download = `fidclic-analyses-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch { setError("L'export n'a pas abouti."); }
    finally { setExporting(false); }
  };

  const Renderer = RENDERERS[payload?.tab] || TabVue;

  // Arriving on #impact (or an old #moments / #comportement link): once the
  // overview is drawn, bring that panel into view.
  useEffect(() => {
    const anchor = HASH_ANCHORS[(window.location.hash || '').replace('#', '').toLowerCase()];
    if (payload?.tab === 'vue' && anchor) {
      document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [payload]);

  // Arriving from a figure of the Tableau de bord (?focus=revenue): that same
  // figure is brought on screen and pulses for ~2 s, then the parameter goes.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const key = params.get('focus');
    if (!key || !payload) return;
    const t = window.setTimeout(() => {
      flash(document.querySelector(`[data-stat="${CSS.escape(key)}"]`));
      params.delete('focus');
      const q = params.toString();
      window.history.replaceState(window.history.state, '', `${window.location.pathname}${q ? `?${q}` : ''}${window.location.hash}`);
    }, 150);
    return () => window.clearTimeout(t);
  }, [payload]);

  // A figure opens a page, another tab, or a panel further down this one.
  const open = useCallback((s) => {
    if (s.to) navigate(s.to);
    else if (s.tab) { setTab(s.tab); window.scrollTo({ top: 0, behavior: 'smooth' }); }
    // A panel of this page: brought on screen and highlighted for ~2 s.
    else if (s.anchor) flash(document.getElementById(s.anchor), { block: 'center' });
  }, [navigate, setTab]);

  return (
    <div className="an">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#EAF1FF] text-[#2F6BFF]">
            <BarChart3 size={22} />
          </span>
          <div>
            <h1 className="text-[23px] font-bold leading-tight text-[#0B1C3F]">Analyses</h1>
            <p className="text-[13px] text-[#64748B]">
              Analysez vos performances et découvrez des opportunités pour développer votre activité.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <PeriodMenu value={period} onChange={setPeriod} busy={loading} lead />
          <button type="button" onClick={exportCsv} disabled={exporting}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#2F6BFF] px-4 py-2.5 text-[13px] font-semibold text-white transition hover:bg-[#2559DB] disabled:opacity-60">
            {exporting ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />} Exporter le rapport
          </button>
        </div>
      </header>

      <nav className="mb-4 flex gap-1 overflow-x-auto border-b border-[#E6EEFB]">
        {tabs.map((t) => {
          const on = tab === t.key;
          return (
            <button key={t.key} type="button" onClick={() => setTab(t.key)}
                    className={`shrink-0 border-b-2 px-3.5 py-2.5 text-[13px] font-semibold transition ${
                      on ? 'border-[#2F6BFF] text-[#2F6BFF]'
                         : 'border-transparent text-[#64748B] hover:text-[#334155]'}`}>
              {t.label}
            </button>
          );
        })}
      </nav>

      {error && <p className="mb-4 rounded-xl bg-[#FEECEC] px-4 py-2.5 text-[12.5px] text-[#C0392B]">{error}</p>}

      {loading && !payload ? (
        <div key="loading" className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-20 text-[13px] text-[#64748B]">
          <Loader2 size={16} className="animate-spin" /> <span>Chargement des analyses…</span>
        </div>
      ) : payload ? (
        <div key="data" className={loading ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
          <OpenCtx.Provider value={open}>
            <TabCtx.Provider value={payload.tab}>
              <Renderer d={payload.data} />
            </TabCtx.Provider>
          </OpenCtx.Provider>
        </div>
      ) : null}
    </div>
  );
}
