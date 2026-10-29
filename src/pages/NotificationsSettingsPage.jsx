import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Bell, Smartphone, BarChart3, Send, CalendarDays, Crown, ArrowUp, ArrowUpRight, ArrowRight, CheckCircle2,
  CreditCard, Info, ShieldCheck, Zap, User, FileText, Eye, Gift, Cake, Moon, Star, Layers, ChevronRight,
  Clock, Users, Tag, Sparkles, PartyPopper, Loader2, Check, X, FlaskConical,
} from 'lucide-react';
import { ownerAPI } from '../lib/api';

/* Paramètres › Notifications — built to the approved mockup (first image).
   The five « Informations importantes » open from the (i) in « À propos »
   (decided with the user). Règles d'envoi carries each business's own limits
   — per client and for the whole shop — enforced by features/send_rules.py. */

const BLUE = '#2F6BFF';
const nf = (n) => (n ?? 0).toLocaleString('fr-FR');
const longDate = (iso) => (iso ? new Date(`${iso}T12:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }) : '—');

const IMPORTANT = [
  'Les notifications sont envoyées uniquement aux clients ayant donné leur consentement.',
  'Elles apparaissent sur le téléphone du client via Apple Wallet ou Google Wallet.',
  'Respectez les limites par client pour éviter la sur-sollicitation.',
  'Les notifications sont incluses dans votre abonnement selon votre plan.',
  'En cas de dépassement de quota, vous pourrez passer à une offre supérieure.',
];

const Card = ({ children, className = '' }) => (
  <section className={`rounded-2xl border border-[#EDF1F7] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)] ${className}`}>{children}</section>
);
const Head = ({ icon: Icon, title, sub, right, tone = BLUE }) => (
  <header className="mb-3 flex items-start gap-3">
    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl" style={{ background: '#EEF4FF', color: tone }}><Icon size={20} /></span>
    <div className="min-w-0 flex-1">
      <h2 className="text-[14.5px] font-bold text-[#0B1C3F]">{title}</h2>
      {sub && <p className="text-[12px] leading-snug text-[#64748B]">{sub}</p>}
    </div>
    {right}
  </header>
);

function Stepper({ value, onChange, disabled, unit = 'notifications' }) {
  return (
    <div className="flex items-stretch gap-2">
      <input type="number" min={0} value={value} disabled={disabled}
             onChange={(e) => onChange(Math.max(0, Number(e.target.value) || 0))}
             className="h-10 w-[88px] rounded-lg border border-[#DCE3EE] bg-white px-3 text-[14px] text-[#0B1C3F] outline-none focus:border-[#2F6BFF] disabled:bg-[#F8FAFC]" />
      <span className="flex h-10 flex-1 items-center rounded-lg bg-[#F4F7FC] px-3 text-[13.5px] text-[#64748B]">{unit}</span>
    </div>
  );
}

function TemoinCard() {
  const [t, setT] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => { ownerAPI.temoinSettings().then(({ data }) => setT(data)).catch(() => {}); }, []);
  if (!t) return null;
  const flip = async () => {
    setBusy(true); setErr('');
    try { const { data } = await ownerAPI.saveTemoin(!t.enabled); setT({ ...t, enabled: data.enabled }); }
    catch (e) { setErr(e?.response?.data?.detail || "Le réglage n'a pas pu être enregistré."); }
    finally { setBusy(false); }
  };
  return (
    <section id="temoin" data-testid="temoin-settings" className="mt-4 rounded-2xl border border-[#E9E3FF] bg-white p-4 shadow-[0_1px_2px_rgba(11,28,63,.03)]">
      <header className="mb-3 flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#F3EEFF] text-[#7C3AED]"><FlaskConical size={20} /></span>
        <div className="min-w-0 flex-1">
          <h2 className="text-[14.5px] font-bold text-[#0B1C3F]">Groupe témoin</h2>
          <p className="text-[12px] leading-snug text-[#64748B]">Mesurer ce que FidClic vous rapporte vraiment, et pas seulement les clients qui seraient venus de toute façon.</p>
        </div>
        <button type="button" role="switch" aria-checked={t.enabled} aria-label="Groupe témoin" disabled={!t.can_edit || busy} onClick={flip}
                className={`relative h-6 w-11 shrink-0 rounded-full transition disabled:opacity-60 ${t.enabled ? 'bg-[#7C3AED]' : 'bg-[#CBD5E1]'}`}>
          <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${t.enabled ? 'left-[22px]' : 'left-0.5'}`} />
        </button>
      </header>
      <div className="grid gap-3 text-[13px] leading-snug text-[#334155] md:grid-cols-3">
        <p><b className="text-[#0B1C3F]">Comment ?</b> À chaque campagne groupée et à chaque relance automatique (clients inactifs, géolocalisation),
          {' '}<b>{t.share} % des clients</b> (au moins {t.min_hold_send || 4}, jamais plus de la moitié), tirés au hasard, ne reçoivent pas le message. Un nouveau tirage à chaque envoi : personne n'est mis de côté pour de bon.</p>
        <p><b className="text-[#0B1C3F]">Pourquoi ?</b> {t.window_days} jours après, FidClic compare leurs visites à celles des clients qui ont reçu le message.
          La différence, c'est ce que le message a vraiment rapporté : « +X € grâce à FidClic » dans Analyses, le détail des campagnes et des automatisations.</p>
        <p><b className="text-[#0B1C3F]">Jamais :</b> anniversaire, récompense, bienvenue, ni un message envoyé à un seul client. Moins de 3 destinataires : personne n'est retenu.
          Les noms du groupe témoin ne sont pas affichés, pour ne pas fausser la mesure.</p>
      </div>
      <p className={`mt-3 rounded-lg px-3 py-2 text-[12.5px] ${t.enabled ? 'bg-[#F5F3FF] text-[#4C1D95]' : 'bg-[#FFF7ED] text-[#9A3412]'}`}>
        {t.enabled ? `Activé : ${t.share} % de chaque envoi groupé forment le groupe témoin.`
          : 'Désactivé : tous vos clients reçoivent chaque message, mais ce que FidClic vous rapporte vraiment n\'est plus mesuré (« pas mesuré »).'}
        {!t.can_edit && ' Seul le propriétaire peut modifier ce réglage.'}
      </p>
      {err && <p role="alert" className="mt-2 text-[12.5px] text-[#B91C1C]">{err}</p>}
    </section>
  );
}

export default function NotificationsSettingsPage() {
  const navigate = useNavigate();
  const [period, setPeriod] = useState('current');
  const [d, setD] = useState(null);
  const [r, setR] = useState(null);
  const [err, setErr] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [info, setInfo] = useState(false);
  const [guide, setGuide] = useState(false);
  const infoRef = useRef(null);

  useEffect(() => {
    ownerAPI.notificationsOverview(period)
      .then(({ data }) => { setD(data); setR((cur) => cur || data.rules); })
      .catch((e) => setErr(e?.response?.data?.detail || 'Impossible de charger les notifications.'));
  }, [period]);
  useEffect(() => {
    if (!info) return undefined;
    const away = (e) => { if (infoRef.current && !infoRef.current.contains(e.target)) setInfo(false); };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [info]);

  if (!d || !r) {
    return err ? <p className="rounded-xl bg-[#FEF2F2] px-4 py-3 text-[13.5px] text-[#B91C1C]">{err}</p>
      : <div key="loading" className="flex items-center justify-center gap-2 rounded-2xl border border-[#E6EEFB] bg-white py-24 text-[13px] text-[#64748B]"><Loader2 size={16} className="animate-spin" /> Chargement…</div>;
  }
  const u = d.usage;
  const unlimited = !u.quota;
  const saveRules = async () => {
    setSaving(true); setErr(''); setSaved(false);
    try { const { data } = await ownerAPI.saveSendRules(r); setR(data.rules); setSaved(true); }
    catch (e) { setErr(e?.response?.data?.detail || "Les règles n'ont pas pu être enregistrées."); }
    finally { setSaving(false); }
  };
  const lim = (n, unit) => (n ? `${nf(n)} / ${unit}` : 'Illimité');
  const AUTO_ICONS = { welcome: [Bell, '#F59E0B'], birthday: [Cake, '#F97316'], inactive: [Moon, '#8B5CF6'], near_reward: [Star, '#A855F7'], others: [Layers, '#2F6BFF'] };
  const TEMPLATES = [
    { icon: Tag, tone: '#F97316', title: 'Offre spéciale', body: '-20% sur votre prochaine visite !', to: '/dashboard/campaigns?template=offre_jour' },
    { icon: Sparkles, tone: '#F59E0B', title: 'Nouveau produit', body: 'Découvrez notre nouveauté', to: '/dashboard/automations' },
    { icon: PartyPopper, tone: '#8B5CF6', title: 'Événement', body: 'Soirée spéciale ce vendredi', to: '/dashboard/automations' },
    { icon: Gift, tone: '#A855F7', title: 'Rappel de points', body: 'Vous avez atteint 200 points !', to: '/dashboard/automations' },
  ];

  return (
    <div className="ntf">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><Bell size={22} /></span>
          <div>
            <h1 className="text-[28px] font-bold leading-tight tracking-[-0.01em] text-[#0B1C3F]">Notifications</h1>
            <p className="text-[15px] text-[#475569]">Gérez toutes les notifications Wallet envoyées à vos clients sur leur téléphone (Apple Wallet et Google Wallet).</p>
          </div>
        </div>
        <button type="button" onClick={() => setGuide(true)}
                className="inline-flex items-center gap-2 rounded-xl border border-[#2F6BFF] bg-white px-4 py-2.5 text-[13px] font-medium text-[#2F6BFF] hover:bg-[#F4F8FF]">
          <Smartphone size={16} /> Voir un guide sur les notifications
        </button>
      </header>
      {err && <p className="mb-4 rounded-xl bg-[#FEF2F2] px-4 py-2.5 text-[13px] text-[#B91C1C]">{err}</p>}

      {/* row 1 */}
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr_0.82fr]">
        <Card>
          <Head icon={BarChart3} title="Utilisation de vos notifications Wallet" sub="Suivez votre consommation et vos limites."
                right={(
                  <select value={period} onChange={(e) => setPeriod(e.target.value)}
                          className="h-9 rounded-lg border border-[#DCE3EE] bg-white px-2.5 text-[12.5px] text-[#0B1C3F]">
                    <option value="current">Période actuelle</option>
                    <option value="previous">Mois précédent</option>
                  </select>
                )} />
          <div className="rounded-xl border border-[#EDF1F7] p-3.5">
            <div className="flex items-center gap-3.5">
              <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#EEF4FF] text-[#2F6BFF]"><Send size={22} /></span>
              <div className="min-w-0 flex-1">
                <p className="text-[13px] text-[#0B1C3F]">Notifications envoyées (Wallet)</p>
                <p className="flex items-baseline justify-between">
                  <span className="text-[18px] font-bold text-[#0B1C3F]">{nf(u.sent)} <span className="font-medium">/ {unlimited ? 'illimité' : nf(u.quota)}</span></span>
                  {!unlimited && <span className="text-[13px] text-[#475569]">{u.pct}%</span>}
                </p>
                <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-[#EEF2F8]">
                  <div className="h-full rounded-full" style={{ width: `${unlimited ? 0 : Math.min(100, u.pct)}%`, background: u.pct >= 90 ? '#E11D48' : BLUE }} />
                </div>
              </div>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <div className="flex items-center gap-3 rounded-xl border border-[#EDF1F7] p-3">
              <Send size={22} className="shrink-0 text-[#2F6BFF]" />
              <div><p className="text-[12px] text-[#0B1C3F]">Notifications restantes</p>
                <p className="text-[16px] font-bold text-[#0B1C3F]">{unlimited ? 'Illimitées' : nf(u.remaining)}</p></div>
            </div>
            <div className="flex items-center gap-3 rounded-xl border border-[#EDF1F7] p-3">
              <CalendarDays size={22} className="shrink-0 text-[#2F6BFF]" />
              <div><p className="text-[12px] text-[#0B1C3F]">Renouvellement du quota</p>
                <p className="text-[14px] font-bold text-[#0B1C3F]">{longDate(u.renews_on)}</p></div>
            </div>
          </div>
        </Card>

        <Card>
          <Head icon={Crown} title="Limites de votre plan" sub="Gérez les limites liées à votre abonnement." />
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-[#E7F7EE] px-3 py-1.5 text-[13px] font-bold text-[#0F8B58]"><Crown size={14} /> Plan {d.plan.label}</span>
            {d.plan.upgrade && (
              <button type="button" onClick={() => navigate('/dashboard/parametres/abonnement')}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-[#2F6BFF] px-3 py-1.5 text-[12.5px] font-medium text-[#2F6BFF]">
                <ArrowUp size={14} /> Passer à une offre supérieure
              </button>
            )}
          </div>
          <ul className="divide-y divide-[#F1F5F9] rounded-xl border border-[#EDF1F7] px-3">
            {[
              [Send, 'Notifications Wallet (total)', d.plan.push_per_month ? `${nf(d.plan.push_per_month)} / mois` : 'Illimitées', !d.plan.push_per_month],
              [CreditCard, 'Notifications par jour', lim(d.plan.shop_day, 'jour'), !d.plan.shop_day, 'Votre limite, réglée dans « Règles d’envoi ».'],
              [Bell, 'Notifications par semaine', lim(d.plan.shop_week, 'semaine'), !d.plan.shop_week, 'Votre limite, réglée dans « Règles d’envoi ».'],
              [Users, 'Destinataires par envoi', 'Illimité', true],
              [Clock, 'Notifications automatiques', 'Illimitées', true],
            ].map(([Icon, label, value, green, tip]) => (
              <li key={label} className="flex items-center gap-3 py-2 text-[13px]">
                <Icon size={16} className="shrink-0 text-[#0B1C3F]" />
                <span className="flex-1 text-[#0B1C3F]">{label}</span>
                <span className={green ? 'text-[#10B981]' : 'text-[#0B1C3F]'}>{value}</span>
                {tip && <span title={tip}><Info size={14} className="text-[#94A3B8]" /></span>}
              </li>
            ))}
          </ul>
        </Card>

        <section className="rounded-2xl border border-[#D5F0E0] bg-[#F1FBF5] p-4">
          <header className="mb-3 flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#DDF4E7] text-[#10B981]"><ArrowUpRight size={22} /></span>
            <h2 className="text-[14.5px] font-bold text-[#0B1C3F]">Besoin de plus de notifications ?</h2>
          </header>
          <p className="mb-3 text-[13px] leading-snug text-[#475569]">Augmentez vos limites pour envoyer plus de notifications et développer votre activité.</p>
          <ul className="mb-4 space-y-1.5">
            {['Plus de notifications par mois', 'Plus de notifications par jour', 'Plus de notifications par semaine', "Plus d'automatisations", 'Fonctionnalités avancées', 'Support prioritaire'].map((x) => (
              <li key={x} className="flex items-center gap-2 text-[13px] text-[#475569]"><CheckCircle2 size={17} className="text-white" fill="#10B981" /> {x}</li>
            ))}
          </ul>
          <button type="button" onClick={() => navigate('/dashboard/parametres/abonnement')}
                  className="flex w-full items-center justify-center gap-2 rounded-xl py-2.5 text-[14px] font-medium text-white" style={{ background: BLUE }}>
            Voir les offres disponibles <ArrowRight size={16} />
          </button>
        </section>
      </div>

      {/* row 2 */}
      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1fr_0.9fr]">
        <Card>
          <Head icon={CreditCard} title="À propos des notifications Wallet"
                sub="Les notifications sont envoyées directement sur le téléphone de vos clients via leur carte de fidélité dans Apple Wallet ou Google Wallet." />
          <div ref={infoRef} className="relative">
            <button type="button" onClick={() => setInfo((v) => !v)} aria-expanded={info}
                    className="flex w-full items-start gap-3 rounded-xl bg-[#F4F7FC] p-3.5 text-left">
              <Info size={20} className="mt-0.5 shrink-0 text-[#2F6BFF]" />
              <span className="text-[12.5px] leading-snug text-[#475569]">
                Les clients reçoivent vos notifications sous forme d'alertes sur leur téléphone, liées à leur carte de fidélité dans Apple Wallet ou Google Wallet.
                <span className="mt-1 block font-semibold text-[#2F6BFF]">Informations importantes {info ? '▴' : '▾'}</span>
              </span>
            </button>
            {info && (
              <div className="absolute left-0 right-0 top-full z-20 mt-2 rounded-xl border border-[#E6EEFB] bg-white p-4 shadow-[0_24px_60px_-28px_rgba(11,28,63,.5)]">
                <p className="mb-2 flex items-center gap-2 text-[13.5px] font-bold text-[#0B1C3F]"><Info size={16} className="text-[#2F6BFF]" /> Informations importantes</p>
                <ul className="space-y-1.5">
                  {IMPORTANT.map((x) => (
                    <li key={x} className="flex items-start gap-2 text-[12.5px] leading-snug text-[#475569]">
                      <CheckCircle2 size={15} className="mt-px shrink-0 text-white" fill="#10B981" /> {x}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Card>

        <Card>
          <Head icon={ShieldCheck} title="Autorisation d'envoi"
                sub="L'envoi de notifications est activé par défaut pour tous vos clients lors de leur inscription. Leur consentement est demandé conformément au RGPD." />
          <div className="flex items-start gap-3 rounded-xl bg-[#EEFAF3] p-3.5">
            <CheckCircle2 size={22} className="mt-0.5 shrink-0 text-white" fill="#10B981" />
            <div className="text-[12.5px] leading-snug">
              <p className="font-medium text-[#0F8B58]">L'envoi de notifications est autorisé</p>
              <p className="text-[#475569]">Seuls les clients ayant donné leur consentement reçoivent des notifications.</p>
              <p className="mt-1 text-[#64748B]">{nf(d.consent.with_consent)} client{d.consent.with_consent > 1 ? 's' : ''} sur {nf(d.consent.total)} ont donné leur consentement
                {d.consent.switched_off ? ` · ${nf(d.consent.switched_off)} ont coupé les notifications` : ''}.</p>
            </div>
          </div>
          <button type="button" onClick={() => navigate('/dashboard/parametres/donnees')}
                  className="mt-3 w-full rounded-xl border border-[#2F6BFF] py-2.5 text-[13px] font-medium text-[#2F6BFF] hover:bg-[#F4F8FF]">
            Voir la gestion du consentement
          </button>
        </Card>

        <Card>
          <Head icon={Zap} title="Notifications automatiques" sub="Gérez les notifications envoyées automatiquement par FIDCLIC." />
          <ul className="space-y-1">
            {d.automatic.map((a) => {
              const [Icon, tone] = AUTO_ICONS[a.key] || [Bell, BLUE];
              return (
                <li key={a.key}>
                  <button type="button" onClick={() => navigate(a.to)} className="flex w-full items-center gap-3 rounded-lg px-1 py-1.5 text-left hover:bg-[#F7FAFF]">
                    <Icon size={18} style={{ color: tone }} className="shrink-0" />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] text-[#0B1C3F]">{a.label}</span>
                      <span className="block truncate text-[11.5px] text-[#64748B]">{a.sub}</span>
                    </span>
                    <span className={`text-[12.5px] ${a.on ? 'text-[#10B981]' : 'text-[#94A3B8]'}`}>{a.on ? 'Activée' : 'Désactivée'}</span>
                    <ChevronRight size={16} className="text-[#0B1C3F]" />
                  </button>
                </li>
              );
            })}
          </ul>
        </Card>
      </div>

      {/* row 3 */}
      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1fr_0.9fr]">
        <Card>
          <Head icon={User} title="Règles d'envoi" sub="Définissez les limites d'envoi pour éviter la sur-sollicitation de vos clients." />
          <fieldset disabled={!d.can_edit} className="m-0 min-w-0 space-y-3 border-0 p-0">
            <p className="text-[12px] font-semibold uppercase tracking-wide text-[#94A3B8]">Par client</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block"><span className="mb-1 block text-[13px] text-[#0B1C3F]">Maximum par jour</span>
                <Stepper value={r.per_client_day} onChange={(v) => setR({ ...r, per_client_day: v })} /></label>
              <label className="block"><span className="mb-1 block text-[13px] text-[#0B1C3F]">Maximum par semaine</span>
                <Stepper value={r.per_client_week} onChange={(v) => setR({ ...r, per_client_week: v })} /></label>
            </div>
            <p className="text-[12px] font-semibold uppercase tracking-wide text-[#94A3B8]">Pour tout le commerce</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block"><span className="mb-1 block text-[13px] text-[#0B1C3F]">Maximum par jour</span>
                <Stepper value={r.shop_day} onChange={(v) => setR({ ...r, shop_day: v })} /></label>
              <label className="block"><span className="mb-1 block text-[13px] text-[#0B1C3F]">Maximum par semaine</span>
                <Stepper value={r.shop_week} onChange={(v) => setR({ ...r, shop_week: v })} /></label>
            </div>
            <p className="flex items-start gap-2 rounded-lg bg-[#F4F7FC] px-3 py-2.5 text-[12px] leading-snug text-[#475569]">
              <Info size={15} className="mt-px shrink-0 text-[#2F6BFF]" />
              Ces limites s'appliquent automatiquement pour tous vos clients. 0 = sans limite. Au-delà, le message part le lendemain
              (anniversaire d'abord). Bienvenue, points, récompense et avis Google ne sont jamais retenus.
            </p>
            {d.can_edit && (
              <div className="flex items-center gap-3">
                <button type="button" onClick={saveRules} disabled={saving}
                        className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-60" style={{ background: BLUE }}>
                  {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Enregistrer les règles
                </button>
                {saved && <span className="text-[12.5px] text-[#0F8B58]">Enregistré.</span>}
              </div>
            )}
          </fieldset>
        </Card>

        <Card>
          <Head icon={FileText} title="Modèles de notifications" sub="Créez et gérez vos modèles de notifications Wallet." />
          <button type="button" onClick={() => navigate('/dashboard/automations')}
                  className="mb-2 flex w-full items-center justify-center gap-2 rounded-xl border border-[#2F6BFF] py-2.5 text-[13px] font-medium text-[#2F6BFF] hover:bg-[#F4F8FF]">
            Voir tous les modèles <ArrowRight size={15} />
          </button>
          <ul className="divide-y divide-[#F1F5F9]">
            {TEMPLATES.map((t) => (
              <li key={t.title}>
                <button type="button" onClick={() => navigate(t.to)} className="flex w-full items-center gap-3 py-2 text-left hover:bg-[#F7FAFF]">
                  <t.icon size={18} style={{ color: t.tone }} className="shrink-0" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] text-[#0B1C3F]">{t.title}</span>
                    <span className="block truncate text-[11.5px] text-[#64748B]">{t.body}</span>
                  </span>
                  <ChevronRight size={16} className="text-[#0B1C3F]" />
                </button>
              </li>
            ))}
          </ul>
        </Card>

        <Card className="bg-[#F8FAFF]">
          <Head icon={Eye} title="Aperçu d'une notification Wallet" sub="Voici un exemple de notification que reçoivent vos clients." tone="#10B981" />
          <div className="mt-4 rounded-2xl bg-white p-3.5 shadow-[0_18px_40px_-20px_rgba(11,28,63,.35)]">
            <div className="flex items-start gap-3">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-xl" style={{ background: BLUE }}>
                {d.preview.logo_url ? <img src={d.preview.logo_url} alt="" className="h-full w-full object-cover" onError={(e) => { e.currentTarget.style.display = 'none'; }} />
                  : <Bell size={20} className="text-white" />}
              </span>
              <div className="min-w-0 flex-1">
                <p className="flex items-center justify-between text-[13px] font-semibold text-[#0B1C3F]">{d.preview.shop}<span className="text-[11px] font-normal text-[#64748B]">maintenant</span></p>
                <p className="text-[12.5px] text-[#0B1C3F]">{d.preview.title}</p>
                <p className="text-[12.5px] text-[#475569]">{d.preview.body}</p>
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* groupe témoin (user, 2026-10-25): what FidClic really brings in, the owner told */}
      <TemoinCard />

      {guide && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#0B1C3F]/30 sm:items-center sm:p-6" onClick={() => setGuide(false)}>
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-t-2xl bg-white p-5 shadow-2xl sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
            <header className="mb-3 flex items-center justify-between">
              <h3 className="text-[16px] font-bold text-[#0B1C3F]">Guide des notifications</h3>
              <button type="button" onClick={() => setGuide(false)} aria-label="Fermer" className="text-[#94A3B8]"><X size={18} /></button>
            </header>
            <ol className="space-y-3 text-[13px] leading-snug text-[#475569]">
              <li><strong className="text-[#0B1C3F]">1. Automatiques.</strong> Bienvenue, anniversaire, récompense proche et avis Google partent seuls — réglez-les dans Automatisations et sur la Carte de fidélité.</li>
              <li><strong className="text-[#0B1C3F]">2. À valider.</strong> Les autres scénarios préparent leurs envois chaque matin ; vous les validez dans Automatisations › À valider.</li>
              <li><strong className="text-[#0B1C3F]">3. Campagnes.</strong> Un message ponctuel à un groupe de clients, depuis la page Campagnes.</li>
              <li><strong className="text-[#0B1C3F]">4. Limites.</strong> Fixez ici combien de messages un client peut recevoir par jour et par semaine. Un message en trop part le lendemain.</li>
              <li><strong className="text-[#0B1C3F]">5. Consentement.</strong> Seuls les clients qui ont accepté reçoivent vos notifications ; ils peuvent les couper depuis leur carte.</li>
            </ol>
          </div>
        </div>
      )}
    </div>
  );
}
