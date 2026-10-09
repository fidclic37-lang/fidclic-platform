import React, { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api, { ownerAPI } from '../lib/api';
import { Save, Phone, MapPin, Globe, Share2 } from 'lucide-react';
import LoadingDistraction from '../components/LoadingDistraction';
import { PageHeader, C as C_PS } from '../components/PageShell';
import DaypartConfigCard from '../components/DaypartConfigCard';
import BusinessHoursCard from '../components/BusinessHoursCard';
import AutoCampaignsCard from '../components/AutoCampaignsCard';
import WelcomeBonusCard from '../components/WelcomeBonusCard';
import InactiveCustomerPurgeCard from '../components/InactiveCustomerPurgeCard';
import PointsRuleCard from '../components/PointsRuleCard';
import TeamCard from '../components/TeamCard';
import JoinQRPoster from '../components/JoinQRPoster';
import PhonePushPreview from '../components/PhonePushPreview';
import PendingAutoRunsCard from '../components/PendingAutoRunsCard';
import BillingCard from '../components/BillingCard';
import CatalogManager from '../components/CatalogManager';
import LanguageSwitcher from '../components/LanguageSwitcher';

const SettingsPage = () => {
    const location = useLocation();
    // Smooth-scroll to a section when arriving via the sidebar dropdown.
    // Works on first navigation AND on hash changes within the same page.
    // Uses a small delay so the section's content is mounted before we scroll.
    useEffect(() => {
        if (!location.hash) return;
        const id = location.hash.replace('#', '');
        const tryScroll = (attempt = 0) => {
            const el = document.getElementById(id);
            if (el) {
                el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                return;
            }
            if (attempt < 8) setTimeout(() => tryScroll(attempt + 1), 120);
        };
        tryScroll();
    }, [location.hash, location.pathname]);

    const [settings, setSettings] = useState({
        name: '',
        address: '',
        phone: '',
        website: '',
    });
    const [joinUrl, setJoinUrl] = useState('');
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState(null);
    // Read-only view of the geolocalisation config (set by the super admin only).
    const [geoConfig, setGeoConfig] = useState({
        geo_enabled: false,
        vip_geo_only: false,
        geo_radius_meters: null,
        geo_cooldown_days: null,
    });

    useEffect(() => {
        ownerAPI.getTenant().then(res => {
            if (res.data) {
                setSettings({
                    name: res.data.name || '',
                    address: res.data.address || '',
                    phone: res.data.phone || '',
                    website: res.data.website || '',
                });
                setGeoConfig({
                    geo_enabled: Boolean(res.data.geo_enabled),
                    vip_geo_only: Boolean(res.data.vip_geo_only),
                    geo_radius_meters: res.data.geo_radius_meters ?? null,
                    geo_cooldown_days: res.data.geo_cooldown_days ?? null,
                });
                // Generate join URL from slug
                const slug = res.data.slug || 'your-business';
                setJoinUrl(`${window.location.origin}/join/${slug}`);
            }
            setLoading(false);
        }).catch(console.error);
    }, []);

    const handleChange = (field, value) => {
        setSettings(prev => ({
            ...prev,
            [field]: value
        }));
    };

    const handleSave = async (e) => {
        e.preventDefault();
        setSaving(true);
        setMessage(null);

        try {
            await ownerAPI.updateTenant(settings);
            setMessage({ type: 'success', text: 'Settings saved successfully!' });
            setTimeout(() => setMessage(null), 3000);
        } catch (error) {
            console.error("Failed to save", error);
            setMessage({ type: 'error', text: 'Failed to save settings. Please try again.' });
        } finally {
            setSaving(false);
        }
    };

    const handleCopyUrl = () => {
        navigator.clipboard.writeText(joinUrl);
        setMessage({ type: 'success', text: 'Join URL copied to clipboard!' });
        setTimeout(() => setMessage(null), 2000);
    };

    const channelLinks = [
        { key: 'qr_store',  label: 'In-store QR code',  emoji: '📱', desc: 'Print this URL as a QR code for your counter/menu.' },
        { key: 'instagram', label: 'Instagram',          emoji: '📸', desc: 'Paste as the link in your Instagram bio or stories.' },
        { key: 'facebook',  label: 'Facebook',           emoji: '👥', desc: 'Paste on your Facebook page or post links.' },
        { key: 'tiktok',    label: 'TikTok',             emoji: '🎵', desc: 'Paste as your TikTok profile link.' },
    ];

    const handleCopyChannel = (source) => {
        const url = `${joinUrl}?src=${source}`;
        navigator.clipboard.writeText(url);
        setMessage({ type: 'success', text: `${source} link copied — every signup through it will auto-tag as ${source}.` });
        setTimeout(() => setMessage(null), 2500);
    };

    if (loading) {
        return (
          <div className="py-12 px-4">
            <LoadingDistraction title="Chargement des réglages" message="On charge votre configuration…" />
          </div>
        );
    }

    return (
        <div className="max-w-4xl mx-auto space-y-6">
            <PageHeader
              eyebrow="Configuration"
              title="Settings"
              description="Manage your business profile, customer join link, and delivery preferences."
              role="business_owner"
            />

            <SettingsNavigator />

            {message && (
                <div className={`p-4 rounded-lg border ${message.type === 'success' ? 'bg-[#e8f3e5] border-[#E9E5E0] text-[#2d5016]' : 'bg-red-50 border-red-200 text-red-700'}`}>
                    {message.text}
                </div>
            )}

            <form onSubmit={handleSave} className="space-y-8">

                {/* Business Profile Section */}
                <div id="settings-profile" className="bg-white p-8 rounded-2xl border border-[#E9E5E0] shadow-sm relative overflow-hidden scroll-mt-24">
                    <div className="absolute right-0 top-0 w-32 h-32 bg-[#E3A869]/10 rounded-bl-full pointer-events-none"></div>

                    <div className="flex items-center gap-3 mb-6">
                        <div className="w-10 h-10 rounded-full bg-[#171412] flex items-center justify-center text-[#E3A869]">
                            <MapPin className="w-5 h-5" />
                        </div>
                        <h2 className="text-2xl font-bold font-['Cormorant_Garamond'] text-[#171412]">Business Profile</h2>
                    </div>

                    <div className="space-y-6 max-w-2xl">
                        <div>
                            <label className="block text-sm font-bold text-[#171412] mb-2 uppercase tracking-wide">Business Name</label>
                            <input
                                type="text"
                                value={settings.name}
                                onChange={(e) => handleChange('name', e.target.value)}
                                placeholder="Your business name"
                                className="w-full px-4 py-3 rounded-lg border border-[#E9E5E0] focus:border-[#B85C38] focus:ring-0 outline-none text-[#171412] placeholder-[#A8A29E]"
                            />
                        </div>

                        <div>
                            <label className="block text-sm font-bold text-[#171412] mb-2 uppercase tracking-wide flex items-center gap-2">
                                <Phone className="w-4 h-4" />
                                Phone Number
                            </label>
                            <input
                                type="tel"
                                value={settings.phone}
                                onChange={(e) => handleChange('phone', e.target.value)}
                                placeholder="+33 1 23 45 67 89"
                                className="w-full px-4 py-3 rounded-lg border border-[#E9E5E0] focus:border-[#B85C38] focus:ring-0 outline-none text-[#171412] placeholder-[#A8A29E]"
                            />
                        </div>

                        <div>
                            <label className="block text-sm font-bold text-[#171412] mb-2 uppercase tracking-wide flex items-center gap-2">
                                <MapPin className="w-4 h-4" />
                                Physical Address
                            </label>
                            <input
                                type="text"
                                value={settings.address}
                                onChange={(e) => handleChange('address', e.target.value)}
                                placeholder="Street address, city, postal code"
                                className="w-full px-4 py-3 rounded-lg border border-[#E9E5E0] focus:border-[#B85C38] focus:ring-0 outline-none text-[#171412] placeholder-[#A8A29E]"
                            />
                        </div>

                        <div>
                            <label className="block text-sm font-bold text-[#171412] mb-2 uppercase tracking-wide flex items-center gap-2">
                                <Globe className="w-4 h-4" />
                                Website URL
                            </label>
                            <input
                                type="url"
                                value={settings.website}
                                onChange={(e) => handleChange('website', e.target.value)}
                                placeholder="https://www.yourwebsite.com"
                                className="w-full px-4 py-3 rounded-lg border border-[#E9E5E0] focus:border-[#B85C38] focus:ring-0 outline-none text-[#171412] placeholder-[#A8A29E]"
                            />
                        </div>
                    </div>
                </div>

                {/* Join URL Section */}
                <div id="settings-join" className="bg-white p-8 rounded-2xl border border-[#E9E5E0] shadow-sm relative overflow-hidden scroll-mt-24">
                    <div className="absolute right-0 top-0 w-32 h-32 bg-[#E3A869]/10 rounded-bl-full pointer-events-none"></div>

                    <div className="flex items-center gap-3 mb-6">
                        <div className="w-10 h-10 rounded-full bg-[#171412] flex items-center justify-center text-[#E3A869]">
                            <Share2 className="w-5 h-5" />
                        </div>
                        <h2 className="text-2xl font-bold font-['Cormorant_Garamond'] text-[#171412]">Customer Join Link</h2>
                    </div>

                    <div className="space-y-4 max-w-2xl">
                        <p className="text-sm text-[#57504A]">Share this link with customers to join your loyalty program:</p>
                        <div className="flex items-center gap-3">
                            <div className="flex-1 px-4 py-3 rounded-lg bg-[#F5F4F1] border border-[#E9E5E0] text-sm font-mono text-[#171412] break-all">
                                {joinUrl}
                            </div>
                            <button
                                type="button"
                                onClick={handleCopyUrl}
                                className="px-4 py-3 bg-[#B85C38] text-white rounded-lg hover:bg-[#9C4E2F] font-bold transition-colors"
                            >
                                Copy
                            </button>
                        </div>
                        <p className="text-xs text-[#57504A]">Customers can scan the QR code or click this link to join your program.</p>

                        {/* Print-ready join poster — owner downloads / prints, places on counter, customer scans. */}
                        <JoinQRPoster joinUrl={joinUrl} businessName={settings.name || 'Notre boutique'} />
                    </div>

                    {/* Per-channel pre-tagged links */}
                    <div className="mt-8 pt-6 border-t border-[#E9E5E0]">
                        <h3 className="text-lg font-bold font-['Cormorant_Garamond'] text-[#171412] mb-2">Per-channel links (auto-tagged)</h3>
                        <p className="text-sm text-[#57504A] mb-4">
                            Use these channel-specific URLs so every signup is attributed automatically — no need for the customer to pick a source.
                            Your analytics (Customer Map, Acquisition breakdown, Campaign targeting) will update in real time.
                        </p>
                        <div className="space-y-3 max-w-2xl">
                            {channelLinks.map(({ key, label, emoji, desc }) => {
                                const url = `${joinUrl}?src=${key}`;
                                return (
                                    <div key={key} className="p-3 rounded-lg bg-[#F5F4F1] border border-[#E9E5E0]">
                                        <div className="flex items-start gap-3">
                                            <div className="text-2xl leading-none pt-1">{emoji}</div>
                                            <div className="flex-1 min-w-0">
                                                <div className="font-bold text-[#171412]">{label}</div>
                                                <div className="text-xs text-[#57504A] mb-2">{desc}</div>
                                                <div className="flex items-center gap-2">
                                                    <div className="flex-1 px-3 py-2 rounded bg-white border border-[#E9E5E0] text-xs font-mono text-[#171412] break-all">
                                                        {url}
                                                    </div>
                                                    <button
                                                        type="button"
                                                        onClick={() => handleCopyChannel(key)}
                                                        className="px-3 py-2 bg-[#B85C38] text-white rounded font-bold text-xs hover:bg-[#9C4E2F] transition-colors whitespace-nowrap"
                                                    >
                                                        Copy
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                </div>

                {/* Save Button */}
                <button
                    type="submit"
                    disabled={saving}
                    className="flex items-center gap-2 px-6 py-4 rounded-xl text-white font-bold bg-[#B85C38] hover:bg-[#9C4E2F] disabled:opacity-50 transition-all shadow-md"
                >
                    <Save className="w-5 h-5" />
                    {saving ? 'Saving...' : 'Save Settings'}
                </button>
            </form>

            {/* Geolocalisation — owner-editable, has its own save button. Lives OUTSIDE the
                main form so its slider/enter-key events don't trigger the outer form submit. */}
            <div id="settings-geo" className="scroll-mt-24">
              <OwnerGeoCard initial={geoConfig} />
            </div>

            {/* Additive: configurable Active/Inactive customer definition. */}
            {/* Moved: the client statuses are now Paramètres › Règles clients. The
                old card wrote the same figures by another road; two editors
                for one setting would drift, so this points there instead. */}
            <div id="settings-status" className="scroll-mt-24">
              <Link to="/dashboard/parametres/regles-clients"
                    className="flex items-center justify-between gap-4 rounded-2xl border border-[#E9E5E0] bg-white p-6 hover:border-[#B85C38]">
                <span>
                  <span className="block text-lg font-bold text-[#171412]">Statuts clients</span>
                  <span className="block text-sm text-[#57504A]">Déplacé dans Paramètres › Règles clients.</span>
                </span>
                <span className="text-sm font-bold text-[#B85C38]">Ouvrir →</span>
              </Link>
            </div>

            {/* Additive: editable time-of-day periods (replaces hard-coded breakfast/lunch/dinner). */}
            <div id="settings-dayparts" className="scroll-mt-24"><DaypartConfigCard /></div>

            {/* Additive: weekly schedule + French public holidays + annual closures. */}
            <div id="settings-hours" className="scroll-mt-24"><BusinessHoursCard /></div>

            {/* Paliers live in one place now: Carte de fidélité › Récompenses et
                paliers (QA F21, user 2026-10-09). TierDefinitionCard is kept,
                unmounted. */}

            {/* Additive: welcome message + bonus points on signup. */}
            <div id="settings-welcome" className="scroll-mt-24"><WelcomeBonusCard /></div>

            {/* Review queue — auto-campaigns prepared by the cron, awaiting owner approval. */}
            <div id="settings-auto-pending" className="scroll-mt-24"><PendingAutoRunsCard /></div>

            {/* Additive: auto messages for birthdays + inactive customers. */}
            <div id="settings-auto" className="scroll-mt-24"><AutoCampaignsCard /></div>

            {/* Configurable points-per-euro rule, used by the Scan page. */}
            <div id="settings-language" className="scroll-mt-24"><LanguageSwitcher variant="full" /></div>

            <div id="settings-catalog" className="scroll-mt-24"><CatalogManager /></div>

            <div id="settings-points" className="scroll-mt-24"><PointsRuleCard /></div>

            {/* Staff & manager accounts scoped to this tenant. */}
            <div id="settings-team" className="scroll-mt-24"><TeamCard /></div>

            {/* Item 31 — owner-side cleanup: soft-delete inactive customers (with restore). */}
            <div id="settings-cleanup" className="scroll-mt-24"><InactiveCustomerPurgeCard /></div>

            {/* Subscription billing — Stripe Checkout + Customer Portal. */}
            <div id="settings-billing" className="scroll-mt-24"><BillingCard /></div>
        </div>
    );
};

/* ──────────────────────────────────────────────────────────────────
 * SettingsNavigator — sticky dropdown that lets the owner jump straight
 * to a section instead of scrolling through the whole page.
 * On mobile it stays at the top; on desktop it appears as a select dropdown.
 * ────────────────────────────────────────────────────────────────── */
function SettingsNavigator() {
  const { t } = useTranslation();
  const sections = [
    { id: 'settings-profile',  label: t('settings.section_profile') },
    { id: 'settings-join',     label: t('settings.section_join_link') },
    { id: 'settings-geo',      label: t('settings.section_geo') },
    { id: 'settings-status',   label: t('settings.section_status') },
    { id: 'settings-dayparts', label: t('settings.section_dayparts') },
    { id: 'settings-hours',    label: t('settings.section_hours') },
    { id: 'settings-welcome',  label: t('settings.section_welcome') },
    { id: 'settings-auto-pending', label: t('settings.section_auto_pending') },
    { id: 'settings-auto',     label: t('settings.section_auto') },
    { id: 'settings-language', label: t('settings.section_language') },
    { id: 'settings-catalog',  label: t('settings.section_catalog') },
    { id: 'settings-points',   label: t('settings.section_points') },
    { id: 'settings-team',     label: t('settings.section_team') },
    { id: 'settings-cleanup',  label: t('settings.section_cleanup') },
    { id: 'settings-billing',  label: t('settings.section_billing') },
  ];

  const jumpTo = (id) => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="sticky top-2 z-30 bg-white/90 backdrop-blur rounded-2xl border shadow-sm p-3"
         style={{ borderColor: '#EFE9E0' }}>
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-[10px] font-bold uppercase tracking-widest" style={{ color: '#8D857D' }}>
          Aller à :
        </span>
        {/* Dropdown for mobile / quick jump */}
        <select
          onChange={(e) => e.target.value && jumpTo(e.target.value)}
          className="flex-1 md:flex-none border rounded-lg px-3 py-1.5 text-sm font-medium"
          style={{ borderColor: 'var(--flc-line, #E9E5E0)', background: 'var(--flc-card, #FFFFFF)', minWidth: 220 }}
          defaultValue=""
        >
          <option value="" disabled>Choisir une section…</option>
          {sections.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
        {/* Quick-jump pills (desktop only) */}
        <div className="hidden lg:flex flex-wrap gap-1.5">
          {sections.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => jumpTo(s.id)}
              className="px-2.5 py-1 text-[11px] font-semibold rounded-full border transition hover:bg-[#FAFAF8]"
              style={{ borderColor: 'var(--flc-line, #E9E5E0)', color: '#3D2820' }}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────
 * OwnerGeoCard — owner-editable geolocalisation settings
 *
 * The owner controls:
 *   - geo_enabled (on/off)
 *   - geo_radius_meters (50-2000 m)
 *   - geo_cooldown_days (1-30 days)
 *
 * Audience-scope (vip_geo_only) stays admin-only and is shown read-only here.
 * ────────────────────────────────────────────────────────────────── */
function OwnerGeoCard({ initial }) {
  const [cfg, setCfg] = React.useState(initial || {});
  const [saving, setSaving] = React.useState(false);
  const [savedAt, setSavedAt] = React.useState(null);
  const [err, setErr] = React.useState(null);

  React.useEffect(() => { setCfg(initial || {}); }, [initial]);

  const save = async () => {
    setSaving(true);
    setErr(null);
    try {
      const res = await api.put('/owner/settings/geo', {
        geo_enabled: !!cfg.geo_enabled,
        geo_radius_meters: parseInt(cfg.geo_radius_meters, 10) || 500,
        geo_cooldown_days: parseInt(cfg.geo_cooldown_days, 10) || 1,
      });
      setCfg(res.data || cfg);
      setSavedAt(new Date());
    } catch (e) {
      setErr(e?.response?.data?.detail || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-white p-8 rounded-2xl border border-[#E9E5E0] shadow-sm relative overflow-hidden">
      <div className="flex items-center gap-3 mb-4">
        <div className="w-10 h-10 rounded-full bg-[#171412] flex items-center justify-center text-[#E3A869]">
          <MapPin className="w-5 h-5" />
        </div>
        <h2 className="text-2xl font-bold font-['Cormorant_Garamond'] text-[#171412]">Geolocalisation</h2>
      </div>
      <p className="text-sm text-[#57504A] max-w-2xl mb-6">
        Quand un client équipé de votre carte de fidélité passe dans votre rayon, <b>il</b> reçoit
        une notification push avec une offre personnalisée. Configurez le rayon et la fréquence
        ci-dessous pour adapter la stratégie à votre commerce.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-2xl mb-6">
        {/* Enable / Disable */}
        <label className="p-4 rounded-lg border border-[#E9E5E0] flex items-center justify-between cursor-pointer hover:bg-[#FAFAF8]">
          <div>
            <p className="text-xs font-bold uppercase tracking-wider mb-1 text-[#57504A]">Statut</p>
            <p className="text-base font-bold" style={{ color: cfg.geo_enabled ? '#2d5016' : '#8D857D' }}>
              {cfg.geo_enabled ? '✓ Activé' : '— Désactivé'}
            </p>
          </div>
          <input
            type="checkbox"
            className="w-5 h-5"
            checked={!!cfg.geo_enabled}
            onChange={(e) => setCfg({ ...cfg, geo_enabled: e.target.checked })}
          />
        </label>

        {/* Audience — read-only (admin-only) */}
        <div className="p-4 rounded-lg border border-[#E9E5E0] bg-[#F5F4F1]">
          <p className="text-xs font-bold uppercase tracking-wider mb-1 text-[#96431F]">Audience</p>
          <p className="text-base font-bold text-[#96431F]">
            {cfg.vip_geo_only ? '🎯 VIP uniquement' : (cfg.geo_enabled ? 'Tous les clients' : '—')}
          </p>
          <p className="text-[10px] text-[#8D857D] mt-1">
            Réglage géré par notre équipe — contactez-nous pour ajuster.
          </p>
        </div>

        {/* Radius slider */}
        <div className="p-4 rounded-lg border border-[#E9E5E0] md:col-span-2">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-bold uppercase tracking-wider text-[#57504A]">Rayon de notification</p>
            <span className="text-base font-bold text-[#B85C38]">{cfg.geo_radius_meters || 500} m</span>
          </div>
          <input
            type="range"
            min={50}
            max={2000}
            step={50}
            value={cfg.geo_radius_meters || 500}
            disabled={!cfg.geo_enabled}
            onChange={(e) => setCfg({ ...cfg, geo_radius_meters: parseInt(e.target.value, 10) })}
            className="w-full accent-[#B85C38]"
          />
          <div className="flex justify-between text-[10px] text-[#8D857D] mt-1">
            <span>50 m (très proche)</span>
            <span>2 km (large quartier)</span>
          </div>
        </div>

        {/* Cooldown slider */}
        <div className="p-4 rounded-lg border border-[#E9E5E0] md:col-span-2">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-bold uppercase tracking-wider text-[#57504A]">
              Délai entre deux notifications (par client)
            </p>
            <span className="text-base font-bold text-[#B85C38]">
              {cfg.geo_cooldown_days || 1} jour{(cfg.geo_cooldown_days || 1) > 1 ? 's' : ''}
            </span>
          </div>
          <input
            type="range"
            min={1}
            max={30}
            step={1}
            value={cfg.geo_cooldown_days || 1}
            disabled={!cfg.geo_enabled}
            onChange={(e) => setCfg({ ...cfg, geo_cooldown_days: parseInt(e.target.value, 10) })}
            className="w-full accent-[#B85C38]"
          />
          <div className="flex justify-between text-[10px] text-[#8D857D] mt-1">
            <span>1 jour (intensif)</span>
            <span>30 jours (parcimonieux)</span>
          </div>
        </div>
      </div>

      {/* Live phone preview — what a customer entering the geofence sees on their lock screen. */}
      <div className="max-w-2xl mb-6 rounded-xl border p-4 flex flex-col md:flex-row gap-5 items-center"
           style={{ background: 'color-mix(in srgb, var(--flc-warn, #A8862D) 8%, var(--flc-card, #FFFFFF))', borderColor: '#E3A86955' }}>
        <PhonePushPreview
          businessName="Your shop"
          title="📍 You're just nearby!"
          body={`A treat is waiting if you stop by. (~${cfg.geo_radius_meters || 500} m, triggered ${(cfg.geo_cooldown_days || 1) === 1 ? 'once a day' : `every ${cfg.geo_cooldown_days} days`} max)`}
          primaryColor="#B85C38"
          width={210}
          variant="geo"
          caption="Preview — proximity notification"
        />
        <div className="flex-1 text-sm space-y-2" style={{ color: '#96431F' }}>
          <p className="font-bold">How does it work?</p>
          <p>
            When a customer with your loyalty card (and location permission granted)
            enters the radius you've set, their phone receives this push automatically.
          </p>
          <p>
            <b>The title and message automatically adapt</b> to the radius and cooldown configured above —
            the customer understands the offer instantly, with zero effort.
          </p>
        </div>
      </div>

      {err && <p className="text-sm text-red-600 mb-3">{err}</p>}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="flex items-center gap-2 px-5 py-3 rounded-xl text-white font-bold bg-[#B85C38] hover:bg-[#9C4E2F] disabled:opacity-50 transition-all shadow-md"
        >
          <Save className="w-4 h-4" />
          {saving ? 'Enregistrement…' : 'Enregistrer la géolocalisation'}
        </button>
        {savedAt && (
          <span className="text-xs text-[#4A5D23]">
            ✓ Enregistré à {savedAt.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
      </div>
    </div>
  );
}

export default SettingsPage;
