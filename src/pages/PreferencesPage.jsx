import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Settings, Globe, Clock, CalendarDays, Coins, Mail, SlidersHorizontal, RotateCcw, Eye, Check, Loader2, Lock,
  LayoutList,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { applyPrefs, allCurrencies, allTimezones, tzLabel, symbolFor } from '../lib/prefs';
import { applyGoogleTranslate } from '../components/GoogleTranslateBridge';

/* Paramètres › Préférences — built to the approved mockup, without
   « Préférences d'affichage » (removed by the user). Each change is saved at
   once and applied to the app (src/lib/prefs.js). Language, time zone, dates,
   e-mails and navigation are this account's; the currency is the business's
   (the owner chooses it, every currency in the world). */

const BLUE = '#2F6BFF';
const LANGS = [['fr', '🇫🇷', 'Français'], ['en', '🇬🇧', 'English'], ['ar', '🇸🇦', 'العربية']];
const DATE_FORMATS = [['dmy', '31/12/2026 (JJ/MM/AAAA)'], ['mdy', '12/31/2026 (MM/JJ/AAAA)'], ['ymd', '2026-12-31 (AAAA-MM-JJ)'], ['dmy_dot', '31.12.2026 (JJ.MM.AAAA)']];
const PAGES = [['/dashboard', 'Tableau de bord'], ['/dashboard/analytics', 'Analyses'], ['/dashboard/customers', 'Clients'],
               ['/dashboard/campaigns', 'Campagnes'], ['/dashboard/scan', 'Scan'], ['/dashboard/insights', 'Insights'], ['/dashboard/card', 'Carte de fidélité']];
const EMAILS = [['billing', 'Emails de facturation', 'Factures, confirmations de paiement, renouvellement.'],
                ['product', 'Nouveautés produit', 'Actualités, nouvelles fonctionnalités.'],
                ['tips', 'Conseils et bonnes pratiques', 'Guides, tutoriels, recommandations.'],
                ['alerts', 'Alertes importantes', 'Sécurité, maintenance, informations critiques.'],
                ['marketing', 'Emails marketing', 'Offres, événements, promotions.']];

const Card = ({ children, className = '' }) => (
  <section className={`rounded-2xl border border-[#EDF1F7] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)] ${className}`}>{children}</section>
);
const Head = ({ icon: Icon, title, sub, tone = BLUE, bg = '#EEF4FF' }) => (
  <header className="mb-4 flex items-start gap-3">
    <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl" style={{ background: bg, color: tone }}><Icon size={22} /></span>
    <div className="min-w-0 flex-1">
      <h2 className="text-[15.5px] font-bold text-[#0B1C3F]">{title}</h2>
      {sub && <p className="text-[12.5px] leading-snug text-[#64748B]">{sub}</p>}
    </div>
  </header>
);
const Select = ({ value, onChange, children, disabled, className = '' }) => (
  <div className={`relative ${className}`}>
    <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}
            className="h-11 w-full appearance-none rounded-lg border border-[#DCE3EE] bg-white pl-3 pr-9 text-[14px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF] disabled:bg-[#F8FAFC]">
      {children}
    </select>
    <svg className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#0B1C3F" strokeWidth="2.5"><path d="m6 9 6 6 6-6" /></svg>
  </div>
);
const Switch = ({ on, onChange, label }) => (
  <button type="button" role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)}
          className={`relative h-7 w-[50px] shrink-0 rounded-full transition ${on ? 'bg-[#2F6BFF]' : 'bg-[#DFE6F1]'}`}>
    <span className={`absolute top-[3px] h-[22px] w-[22px] rounded-full bg-white shadow transition-all ${on ? 'left-[25px]' : 'left-[3px]'}`} />
  </button>
);
const Example = ({ children }) => <p className="mt-2 rounded-lg bg-[#F4F7FC] px-3 py-2.5 text-[13px] text-[#475569]">Exemple : {children}</p>;

function dateExample(fmt, tz) {
  const d = new Date(Date.UTC(2026, 8, 28, 10, 0));
  const p = new Intl.DateTimeFormat('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: tz }).formatToParts(d)
    .reduce((a, x) => ({ ...a, [x.type]: x.value }), {});
  return { dmy: `${p.day}/${p.month}/${p.year}`, mdy: `${p.month}/${p.day}/${p.year}`, ymd: `${p.year}-${p.month}-${p.day}`, dmy_dot: `${p.day}.${p.month}.${p.year}` }[fmt];
}
function moneyExample(code) {
  try { return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: code }).format(1234.56); } catch { return `1 234,56 ${code}`; }
}

export default function PreferencesPage() {
  const { i18n } = useTranslation();
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [toast, setToast] = useState('');
  const [busy, setBusy] = useState(false);
  const currencies = useMemo(() => allCurrencies(), []);
  const zones = useMemo(() => allTimezones(), []);

  useEffect(() => {
    ownerAPI.preferences().then(({ data }) => setD(data)).catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger vos préférences.'));
  }, []);
  const say = (m) => { setToast(m); setTimeout(() => setToast(''), 2500); };

  const save = async (patch) => {
    setErr('');
    const before = d;
    setD((cur) => ({ ...cur, preferences: { ...cur.preferences, ...(patch.emails ? { emails: { ...cur.preferences.emails, ...patch.emails } } : patch) },
                     ...(patch.currency ? { currency: patch.currency } : {}) }));
    try {
      const { data } = await ownerAPI.savePreferences(patch);
      setD(data);
      applyPrefs(data.preferences, data.currency);
      if (patch.language) { i18n.changeLanguage(patch.language); try { applyGoogleTranslate(patch.language); } catch { /* ignore */ } }
      if (patch.currency) { window.location.reload(); return; }
      say('Enregistré');
    } catch (e) { setD(before); setErr(e?.response?.data?.detail || "L'enregistrement n'a pas abouti."); }
  };

  if (!d) {
    return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p>
      : <div className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</div>;
  }
  const p = d.preferences;
  const cur = currencies.find((c) => c.code === d.currency) || { code: d.currency, name: d.currency, symbol: symbolFor(d.currency) };
  const lang = LANGS.find(([k]) => k === p.language) || LANGS[0];

  return (
    <div className="prefs">
      <header className="mb-4 flex items-start gap-3">
        <span className="mt-0.5 flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><Settings size={24} /></span>
        <div>
          <h1 className="text-[28px] font-bold leading-tight tracking-[-0.01em] text-[#0B1C3F]">Préférences</h1>
          <p className="text-[15px] text-[#475569]">Personnalisez l'expérience FIDCLIC selon vos besoins.</p>
        </div>
      </header>
      {err && <p className="mb-4 rounded-xl bg-[#FEF2F2] px-4 py-2.5 text-[13px] text-[#B91C1C]">{err}</p>}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <Head icon={Globe} title="Langue" sub="Choisissez la langue de l'interface." />
          <div className="relative">
            <span className="pointer-events-none absolute left-3 top-1/2 z-10 -translate-y-1/2 text-[18px]">{lang[1]}</span>
            <Select value={p.language} onChange={(v) => save({ language: v })} className="[&_select]:pl-10">
              {LANGS.map(([k, , label]) => <option key={k} value={k}>{label}</option>)}
            </Select>
          </div>
        </Card>
        <Card>
          <Head icon={Clock} title="Fuseau horaire" sub="Définissez votre fuseau horaire pour un affichage correct des dates et heures." />
          <Select value={p.timezone} onChange={(v) => save({ timezone: v })}>
            {zones.map((z) => <option key={z} value={z}>{tzLabel(z)}</option>)}
          </Select>
        </Card>
        <Card>
          <Head icon={CalendarDays} title="Format de date" sub="Choisissez le format d'affichage des dates." />
          <Select value={p.date_format} onChange={(v) => save({ date_format: v })}>
            {DATE_FORMATS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </Select>
          <Example>{dateExample(p.date_format, p.timezone)}</Example>
        </Card>

        <Card>
          <Head icon={Coins} title="Format monétaire" sub="Choisissez la devise et le format d'affichage des montants." />
          <Select value={d.currency} disabled={!d.can_edit_currency} onChange={(v) => save({ currency: v })}>
            {currencies.map((c) => <option key={c.code} value={c.code}>{c.name} ({c.symbol}) - {c.code}</option>)}
          </Select>
          <Example>{moneyExample(cur.code)}</Example>
          <p className="mt-2 flex items-start gap-1.5 text-[11.5px] leading-snug text-[#94A3B8]">
            {!d.can_edit_currency && <Lock size={12} className="mt-px shrink-0" />}
            {d.can_edit_currency ? 'La devise de votre commerce, pour toute votre équipe. Vos montants ne sont pas convertis : seul leur affichage change. Votre abonnement FidClic reste en euros.'
              : 'La devise du commerce est choisie par le propriétaire.'}
          </p>
        </Card>

        <Card className="lg:col-span-2">
          <Head icon={Mail} title="Emails administratifs" sub="Gérez les emails que vous recevez de FIDCLIC." />
          <ul className="grid gap-x-8 sm:grid-cols-2">
            {EMAILS.map(([k, title, sub]) => (
              <li key={k} className="flex items-center gap-3 border-b border-[#F1F5F9] py-3 last:border-0">
                <div className="min-w-0 flex-1"><p className="text-[14px] text-[#0B1C3F]">{title}</p><p className="text-[12.5px] text-[#64748B]">{sub}</p></div>
                <Switch on={!!p.emails[k]} label={title} onChange={(v) => save({ emails: { [k]: v } })} />
              </li>
            ))}
          </ul>
        </Card>

        <Card>
          <Head icon={SlidersHorizontal} title="Préférences générales" sub="Réglages supplémentaires de l'application." />
          <div className="space-y-3">
            <label className="flex items-center justify-between gap-3 text-[13.5px] text-[#0B1C3F]">Nombre d'éléments par page
              <Select value={p.per_page} onChange={(v) => save({ per_page: Number(v) })} className="w-44">
                {[10, 20, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select></label>
            <label className="flex items-center justify-between gap-3 text-[13.5px] text-[#0B1C3F]">Page par défaut
              <Select value={p.default_page} onChange={(v) => save({ default_page: v })} className="w-44">
                {PAGES.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </Select></label>
            <label className="flex items-center justify-between gap-3 text-[13.5px] text-[#0B1C3F]">Ouverture des liens
              <Select value={p.link_target} onChange={(v) => save({ link_target: v })} className="w-44">
                <option value="same">Dans le même onglet</option><option value="new">Dans un nouvel onglet</option>
              </Select></label>
            <div className="flex items-center gap-3 pt-1">
              <div className="min-w-0 flex-1"><p className="text-[13.5px] text-[#0B1C3F]">Confirmation des actions importantes</p>
                <p className="text-[12px] text-[#64748B]">Afficher une confirmation avant les actions sensibles (suppression, envoi…).</p></div>
              <Switch on={p.confirm_actions} label="Confirmation des actions importantes" onChange={(v) => save({ confirm_actions: v })} />
            </div>
          </div>
        </Card>

        <section className="flex flex-col rounded-2xl border border-[#EDF1F7] bg-[#F8FAFF] p-4">
          <Head icon={RotateCcw} title="Réinitialiser certaines préférences" sub="Vous pouvez réinitialiser vos préférences de langue, de dates, d'emails et de navigation à leur valeur par défaut." />
          <button type="button" disabled={busy} onClick={async () => {
            setBusy(true);
            try { const { data } = await ownerAPI.resetPreferences(); setD(data); applyPrefs(data.preferences, data.currency);
              i18n.changeLanguage(data.preferences.language); try { applyGoogleTranslate(data.preferences.language); } catch { /* ignore */ }
              say('Préférences réinitialisées'); }
            catch { setErr('La réinitialisation a échoué.'); }
            finally { setBusy(false); }
          }} className="mt-auto flex w-full items-center justify-center gap-2 rounded-xl border border-[#9DB6E8] bg-white py-2.5 text-[13.5px] font-medium text-[#0B1C3F] disabled:opacity-50">
            {busy ? <Loader2 size={15} className="animate-spin" /> : <RotateCcw size={15} />} Réinitialiser les préférences
          </button>
        </section>

        <section className="rounded-2xl border border-[#D5F0E0] bg-[#F1FBF5] p-4">
          <Head icon={Eye} title="Aperçu des paramètres" sub="Voici un aperçu de vos paramètres actuels." tone="#10B981" bg="#DDF4E7" />
          <ul className="space-y-2 rounded-xl bg-white/70 p-3 text-[13px]">
            {[[Globe, 'Langue', lang[2]], [Clock, 'Fuseau horaire', tzLabel(p.timezone)], [CalendarDays, 'Format de date', dateExample(p.date_format, p.timezone)],
              [Coins, 'Format monétaire', `${cur.code} (${cur.symbol})`], [LayoutList, 'Éléments par page', p.per_page]].map(([Icon, k, v]) => (
              <li key={k} className="flex items-center gap-2.5">
                <Icon size={15} className="text-[#0B1C3F]" /><span className="flex-1 text-[#0B1C3F]">{k}</span><span className="text-[#2F6BFF]">{v}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <div aria-live="polite" className="pointer-events-none fixed bottom-5 left-1/2 z-40 -translate-x-1/2 transition-opacity" style={{ opacity: toast ? 1 : 0 }}>
        <span className="inline-flex items-center gap-2 rounded-full bg-[#0B1C3F] px-4 py-2 text-[13px] font-medium text-white shadow-lg"><Check size={14} /> {toast}</span>
      </div>
    </div>
  );
}
