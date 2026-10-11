import { vh } from '../lib/fit';
import React, { useState, useEffect, useRef } from 'react';
import { Send, Plus, Filter, Users, MessageSquare, Clock, CheckCircle2, AlertCircle, Megaphone, Eye, AlertTriangle, TrendingUp, Zap, ChevronDown, ChevronUp, CalendarClock, Trash2, Pencil, X, Sparkles, BellRing } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { ownerAPI } from '../lib/api';
import api from '../lib/api';
import NumberInput from '../components/NumberInput';
import { PageHeader, C as C_PS } from '../components/PageShell';
import CampaignAudienceBuilder from '../components/CampaignAudienceBuilder';
import PhonePushPreview from '../components/PhonePushPreview';
import { renderTokens, SAMPLE_CUSTOMER, TOKEN_HELP } from '../lib/tokens';
import DecimalInput from '../components/DecimalInput';

/**
 * ReEnableNotificationsButton — Strategy 2 (SMS re-enablement campaign).
 *
 * Opens a confirmation modal showing the current notification-subscription
 * stats for this tenant. If the owner confirms, fires SMS to every
 * customer without an active push subscription, asking them to enable.
 * Uses the backend endpoint /api/owner/notifications/re-enablement.
 */
function ReEnableNotificationsButton() {
  const [open, setOpen]   = useState(false);
  const [stats, setStats] = useState(null);
  const [sending, setSending] = useState(false);
  const [result, setResult]   = useState(null);

  // Fetch stats lazily — only when the modal opens.
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setStats(null); setResult(null);
    api.get('/owner/notifications/subscription-stats')
      .then((r) => { if (alive) setStats(r.data); })
      .catch(() => { if (alive) setStats({ error: true }); });
    return () => { alive = false; };
  }, [open]);

  const send = async () => {
    setSending(true); setResult(null);
    try {
      const r = await api.post('/owner/notifications/re-enablement', {});
      setResult(r.data);
    } catch (e) {
      setResult({ error: e?.response?.data?.detail || 'Send failed' });
    } finally { setSending(false); }
  };

  const estCost = stats ? (stats.not_subscribed * 0.06).toFixed(2) : '0.00';

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-full text-sm font-semibold transition-all shadow-sm hover:-translate-y-0.5"
        style={{ background: 'var(--flc-card, #FFFFFF)', color: '#B85C38', border: '1px solid rgb(184 92 56 / .35)' }}
        title="Send SMS to customers who don't receive push notifications, asking them to enable"
      >
        <BellRing size={14} /> Re-enable notifications
      </button>

      {open && (
        <div
          role="dialog" aria-modal="true"
          onMouseDown={(e) => { if (e.target === e.currentTarget) setOpen(false); }}
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(28,25,23,.45)', backdropFilter: 'blur(2px)',
            display: 'grid', placeItems: 'center', padding: 16,
          }}
        >
          <div style={{
            background: 'var(--flc-card, #FFFFFF)', borderRadius: 16,
            width: 'min(520px, 100%)', maxHeight: `calc(${vh(100)} - 32px)`, overflow: 'auto',
            border: '1px solid #E9E5E0',
            boxShadow: '0 24px 60px -20px rgba(28,25,23,.25)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                          padding: '18px 22px', borderBottom: '1px solid #E9E5E0' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ width: 36, height: 36, borderRadius: 10,
                              background: 'rgb(184 92 56 / .12)', color: '#B85C38',
                              display: 'grid', placeItems: 'center' }}>
                  <BellRing size={18} />
                </div>
                <div>
                  <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#171412', fontFamily: 'Manrope' }}>
                    Re-enable notifications
                  </h2>
                  <p style={{ margin: '2px 0 0', fontSize: 12, color: '#8D857D' }}>
                    SMS to customers without push enabled
                  </p>
                </div>
              </div>
              <button onClick={() => setOpen(false)} aria-label="Close"
                style={{ background: 'transparent', border: 'none', cursor: 'pointer',
                         color: '#57504A', padding: 6 }}>
                <X size={18} />
              </button>
            </div>

            <div style={{ padding: 22 }}>
              {result?.error && (
                <div style={{ padding: 12, borderRadius: 8,
                              background: 'hsl(355 60% 48% / .08)', color: 'hsl(355 70% 38%)',
                              fontSize: 13, marginBottom: 12 }}>
                  {result.error}
                </div>
              )}
              {result && !result.error ? (
                <div>
                  <div style={{
                    padding: 16, borderRadius: 10, marginBottom: 14,
                    background: 'hsl(150 55% 40% / .10)', border: '1px solid hsl(150 55% 40% / .25)',
                  }}>
                    <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'hsl(150 70% 26%)' }}>
                      ✓ {result.sent} SMS envoyés
                    </p>
                    <p style={{ margin: '6px 0 0', fontSize: 12.5, color: '#3F3A36', lineHeight: 1.5 }}>
                      Coût estimé : <strong>€{result.estimated_cost_eur}</strong><br/>
                      {result.skipped_no_phone > 0 && <>Ignorés (pas de numéro) : {result.skipped_no_phone}<br/></>}
                      {result.failed_count > 0 && <>Échecs : {result.failed_count}</>}
                    </p>
                  </div>
                  <p style={{ margin: '0 0 14px', fontSize: 12.5, color: '#57504A', lineHeight: 1.5 }}>
                    Conversion attendue : 25-40% des SMS livrés activeront les notifications dans les 7 prochains jours.
                    Vous pouvez relancer dans 30-60 jours.
                  </p>
                  <button onClick={() => setOpen(false)} style={{
                    width: '100%', padding: '10px 16px', borderRadius: 10,
                    background: 'linear-gradient(135deg, hsl(285 50% 48%) 0%, hsl(295 55% 36%) 60%, hsl(310 50% 30%) 100%)',
                    color: '#FFFFFF', border: 'none', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope',
                  }}>
                    Fermer
                  </button>
                </div>
              ) : stats === null ? (
                <p key="loading" style={{ margin: 0, fontSize: 13, color: '#8D857D' }}>Chargement des statistiques…</p>
              ) : stats.error ? (
                <p style={{ margin: 0, fontSize: 13, color: '#B85C38' }}>Impossible de charger les statistiques.</p>
              ) : (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 18 }}>
                    <div style={{ padding: 12, borderRadius: 8, background: '#FBF7EF', border: '1px solid #E9E5E0' }}>
                      <p style={{ margin: 0, fontSize: 10, color: '#8D857D', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>Total clients</p>
                      <p style={{ margin: '4px 0 0', fontSize: 22, fontWeight: 700, color: '#171412', fontFamily: 'Georgia, serif' }}>{stats.total}</p>
                    </div>
                    <div style={{ padding: 12, borderRadius: 8, background: 'hsl(150 55% 40% / .08)', border: '1px solid hsl(150 55% 40% / .25)' }}>
                      <p style={{ margin: 0, fontSize: 10, color: 'hsl(150 70% 26%)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>Abonnés push</p>
                      <p style={{ margin: '4px 0 0', fontSize: 22, fontWeight: 700, color: 'hsl(150 70% 26%)', fontFamily: 'Georgia, serif' }}>{stats.subscribed}</p>
                      <p style={{ margin: '2px 0 0', fontSize: 10, color: '#57504A' }}>{stats.subscribed_pct}%</p>
                    </div>
                    <div style={{ padding: 12, borderRadius: 8, background: 'hsl(355 60% 48% / .08)', border: '1px solid hsl(355 60% 48% / .25)' }}>
                      <p style={{ margin: 0, fontSize: 10, color: 'hsl(355 70% 38%)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>Sans push</p>
                      <p style={{ margin: '4px 0 0', fontSize: 22, fontWeight: 700, color: 'hsl(355 70% 38%)', fontFamily: 'Georgia, serif' }}>{stats.not_subscribed}</p>
                    </div>
                  </div>

                  <p style={{ margin: '0 0 12px', fontSize: 13, color: '#3F3A36', lineHeight: 1.55 }}>
                    Envoyer un SMS aux <strong>{stats.not_subscribed} clients sans notifications</strong> avec un lien pour activer
                    leurs notifications. Conversion attendue : 25-40%.
                  </p>
                  <div style={{
                    padding: 10, borderRadius: 8, marginBottom: 14,
                    background: 'hsl(42 78% 52% / .10)', border: '1px solid hsl(42 78% 52% / .25)',
                    fontSize: 12.5, color: '#3F3A36',
                  }}>
                    <strong>Coût estimé : €{estCost}</strong> ({stats.not_subscribed} × €0.06 par SMS)
                  </div>

                  <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                    <button onClick={() => setOpen(false)} disabled={sending} style={{
                      background: 'transparent', border: '1px solid #E9E5E0',
                      color: '#57504A', borderRadius: 10,
                      padding: '9px 16px', fontSize: 13, fontWeight: 500,
                      cursor: sending ? 'not-allowed' : 'pointer', fontFamily: 'Manrope',
                    }}>
                      Annuler
                    </button>
                    <button onClick={send} disabled={sending || stats.not_subscribed === 0} style={{
                      background: stats.not_subscribed > 0
                        ? 'linear-gradient(135deg, hsl(285 50% 48%) 0%, hsl(295 55% 36%) 60%, hsl(310 50% 30%) 100%)'
                        : '#D6D3D1',
                      color: '#FFFFFF', border: 'none', borderRadius: 10,
                      padding: '9px 18px', fontSize: 13, fontWeight: 600,
                      cursor: stats.not_subscribed > 0 && !sending ? 'pointer' : 'not-allowed',
                      display: 'inline-flex', alignItems: 'center', gap: 7, fontFamily: 'Manrope',
                      boxShadow: stats.not_subscribed > 0 ? '0 6px 18px -8px rgb(184 92 56 / .55)' : 'none',
                    }}>
                      <Send size={14} />
                      {sending ? 'Envoi en cours…' : `Envoyer ${stats.not_subscribed} SMS`}
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default function CampaignsPage() {
  const { t } = useTranslation();
  const [campaigns, setCampaigns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  // When set, the composer is editing an existing draft instead of creating
  // a new campaign. The id is sent to PUT /owner/campaigns/{id} on save.
  const [editingCampaignId, setEditingCampaignId] = useState(null);
  const [sendConfirmation, setSendConfirmation] = useState(null);
  const [previewCount, setPreviewCount] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  // --- Live token preview context (see src/lib/tokens.js) ------------------
  // The composer body keeps its raw {tokens} — the server substitutes them
  // per-recipient at send time. Only the phone preview resolves them locally,
  // against a real customer when we have one, otherwise a labelled sample.
  // Nothing here changes the payload that gets sent.
  const [previewCustomer, setPreviewCustomer] = useState(SAMPLE_CUSTOMER);
  const [previewTenant, setPreviewTenant] = useState({});
  const [previewCardTemplate, setPreviewCardTemplate] = useState({});
  const [selectedCampaignTab, setSelectedCampaignTab] = useState('by-filter'); // 'by-filter' or 'by-customers'
  const [campaignCustomers, setCampaignCustomers] = useState('');
  const [viewingTrackingId, setViewingTrackingId] = useState(null);
  const [trackingData, setTrackingData] = useState(null);
  const [trackingLoading, setTrackingLoading] = useState(false);
  // Item 23 — AI analyzer state (per-campaign).
  const [aiAnalysis, setAiAnalysis] = useState({});      // { [campaignId]: { bullets, used_ai, model } }
  const [aiAnalysisLoading, setAiAnalysisLoading] = useState({}); // { [campaignId]: boolean }

  const runAiAnalysis = async (campaignId) => {
    setAiAnalysisLoading((m) => ({ ...m, [campaignId]: true }));
    try {
      const r = await ownerAPI.aiAnalyzeCampaign(campaignId);
      setAiAnalysis((m) => ({ ...m, [campaignId]: r.data }));
    } catch (e) {
      setAiAnalysis((m) => ({ ...m, [campaignId]: { bullets: ['Analysis failed: ' + (e?.response?.data?.detail || e.message)], used_ai: false } }));
    } finally {
      setAiAnalysisLoading((m) => ({ ...m, [campaignId]: false }));
    }
  };

  // --- Scheduling state (composer modal) ---
  const [sendMode, setSendMode] = useState('now'); // 'now' | 'schedule'
  const [scheduleAt, setScheduleAt] = useState('');      // yyyy-MM-ddTHH:mm, local TZ
  const [scheduleRecurrence, setScheduleRecurrence] = useState(''); // '' | daily | weekly | monthly
  const [scheduledCampaigns, setScheduledCampaigns] = useState([]);
  const [scheduledLoading, setScheduledLoading] = useState(false);

  // --- Quick Send (filter-and-send on the main page) ---
  const [quickOpen, setQuickOpen] = useState(false);
  const [quickName, setQuickName] = useState('');
  const [quickSource, setQuickSource] = useState('push');
  const [quickMessage, setQuickMessage] = useState('');
  const [quickFilters, setQuickFilters] = useState({
    tiers: [],
    minPoints: 0,
    minVisits: 0,
    postalCodes: '',
    minAmountPaid: 0,
  });
  const [quickPreviewCount, setQuickPreviewCount] = useState(null);
  const [quickPreviewLoading, setQuickPreviewLoading] = useState(false);
  const [quickSending, setQuickSending] = useState(false);

  // Form state
  const [formData, setFormData] = useState({
    campaignName: '',
    message: '',
    source: 'push',
    image_url: '',         // Optional hero image for the campaign
    filters: {
      tiers: [],
      minPoints: 0,
      minVisits: 0,
      postalCodes: '',
      minAmountPaid: 0,
    },
  });
  const [imageUploading, setImageUploading] = useState(false);
  const [imageError, setImageError] = useState('');

  // Compresses + reads the picked image into a base64 data URL we can stash on
  // the campaign doc directly. Keeps payload under ~1.5 MB so Vercel's body
  // limit isn't hit. Mirrors the helper used in the Card Designer.
  const readImageFile = (file) => new Promise((resolve, reject) => {
    if (!file) return reject(new Error('No file'));
    if (!file.type?.startsWith('image/')) return reject(new Error('Not an image'));
    if (file.size > 5 * 1024 * 1024) return reject(new Error('Image is over 5 MB. Pick a smaller one.'));
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error('Read failed'));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error('Image decode failed'));
      img.onload = () => {
        const longest = Math.max(img.width, img.height);
        const maxSide = 1200;
        const scale = longest > maxSide ? maxSide / longest : 1;
        const w = Math.round(img.width * scale);
        const h = Math.round(img.height * scale);
        const canvas = document.createElement('canvas');
        canvas.width = w; canvas.height = h;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, w, h);
        const mime = file.type === 'image/png' ? 'image/png' : 'image/jpeg';
        let q = 0.85;
        let dataUrl = canvas.toDataURL(mime, q);
        while (dataUrl.length > 1_500_000 && q > 0.5 && mime === 'image/jpeg') {
          q -= 0.1;
          dataUrl = canvas.toDataURL(mime, q);
        }
        resolve(dataUrl);
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });

  const handleImageUpload = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setImageError('');
    try {
      setImageUploading(true);
      const dataUrl = await readImageFile(file);
      setFormData((prev) => ({ ...prev, image_url: dataUrl }));
    } catch (ex) {
      setImageError(ex?.message || 'Upload failed');
    } finally {
      setImageUploading(false);
    }
  };

  // Reference data the phone preview needs: the tenant (for {business_name}),
  // the card template (for {points_to_next_reward}) and one real customer to
  // render against. All best-effort — any failure leaves the sample in place.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [tRes, cRes] = await Promise.allSettled([
        ownerAPI.getTenant(),
        ownerAPI.getCardTemplate(),
      ]);
      if (cancelled) return;
      if (tRes.status === 'fulfilled') setPreviewTenant(tRes.value?.data || {});
      if (cRes.status === 'fulfilled') setPreviewCardTemplate(cRes.value?.data || {});
    })();
    return () => { cancelled = true; };
  }, []);

  // The reference customer is fetched LAZILY, the first time the composer
  // opens, because GET /owner/customers returns the whole list — not something
  // to pull on every page mount just to render a preview name. A handoff that
  // already supplied preview_customer, or a tenant with no customers at all,
  // skips the call entirely.
  const previewCustomerFetched = useRef(false);
  useEffect(() => {
    if (!showCreateModal || previewCustomerFetched.current) return;
    if (previewCustomer && !previewCustomer.__sample) return;
    previewCustomerFetched.current = true;
    let cancelled = false;
    (async () => {
      try {
        const r = await ownerAPI.getCustomers({});
        const rows = Array.isArray(r?.data) ? r.data : (r?.data?.customers || []);
        if (!cancelled && rows.length) setPreviewCustomer(rows[0]);
      } catch (_e) { /* no customers yet -> labelled sample stays */ }
    })();
    return () => { cancelled = true; };
  }, [showCreateModal]);

  // Load campaigns + scheduled list on mount. Also pick up any handoff from
  // Customer Map (a list of customer IDs the user wants to campaign to).
  useEffect(() => {
    fetchCampaigns();
    fetchScheduled();
    try {
      const raw = sessionStorage.getItem('campaignHandoff');
      if (raw) {
        const handoff = JSON.parse(raw);
        sessionStorage.removeItem('campaignHandoff');

        // Two distinct handoff shapes:
        //   1. Customer Map: customer_ids list → "by-customers" composer mode
        //   2. AI Suggestion: filter object → "by-filter" mode pre-filled with
        //      the suggested name + body + audience filter
        if (handoff && Array.isArray(handoff.customer_ids) && handoff.customer_ids.length) {
          setSelectedCampaignTab('by-customers');
          setCampaignCustomers(handoff.customer_ids.join('\n'));
          // When the sending page knew exactly which customers these are, it
          // ships one of them along so the preview renders real values instead
          // of the generic sample.
          if (handoff.preview_customer) setPreviewCustomer(handoff.preview_customer);
          setFormData((prev) => ({
            ...prev,
            campaignName: handoff.suggested_name || 'Ciblage carte',
            message: handoff.suggested_message || handoff.suggested_body || '',
            source: handoff.suggested_source || handoff.source || 'push',
          }));
          setShowCreateModal(true);
        } else if (handoff && (handoff.suggested_body || handoff.suggested_name)) {
          // AI suggestion handoff — translate the audience filter to formData
          // shape so the by-filter composer opens with the right segment.
          const f = handoff.filter || {};
          setSelectedCampaignTab('by-filter');
          setFormData((prev) => ({
            ...prev,
            campaignName: handoff.suggested_name || '',
            message: handoff.suggested_body || handoff.suggested_message || '',
            source: handoff.suggested_source || 'push',
            filters: {
              tiers: f.tier ? [f.tier] : [],
              minPoints: 0,
              minVisits: f.min_visits || 0,
              postalCodes: '',
              minAmountPaid: 0,
            },
          }));
          setShowCreateModal(true);
        }
      }
    } catch (_e) { /* ignore */ }
  }, []);

  const fetchScheduled = async () => {
    try {
      setScheduledLoading(true);
      const res = await ownerAPI.listScheduled();
      setScheduledCampaigns(res.data?.scheduled || []);
    } catch (_e) { /* non-fatal */ } finally {
      setScheduledLoading(false);
    }
  };

  const cancelScheduled = async (id) => {
    if (!window.confirm('Cancel this scheduled campaign?')) return;
    try {
      await ownerAPI.deleteScheduled(id);
      await fetchScheduled();
    } catch (e) {
      alert('Failed to cancel: ' + (e?.response?.data?.detail || e.message));
    }
  };

  const fetchCampaigns = async () => {
    try {
      setLoading(true);
      const response = await ownerAPI.getCampaigns();
      setCampaigns(response.data || []);
    } catch (error) {
      console.error('Error fetching campaigns:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }));
  };

  const handleFilterChange = (filterName, value) => {
    setFormData((prev) => ({
      ...prev,
      filters: {
        ...prev.filters,
        [filterName]: value,
      },
    }));
  };

  const handleTierChange = (tier) => {
    setFormData((prev) => ({
      ...prev,
      filters: {
        ...prev.filters,
        tiers: prev.filters.tiers.includes(tier)
          ? prev.filters.tiers.filter((t) => t !== tier)
          : [...prev.filters.tiers, tier],
      },
    }));
  };

  const buildFilterPayload = () => {
    return {
      tiers: formData.filters.tiers.length > 0 ? formData.filters.tiers : undefined,
      minPoints: formData.filters.minPoints > 0 ? formData.filters.minPoints : undefined,
      minVisits: formData.filters.minVisits > 0 ? formData.filters.minVisits : undefined,
      postalCodes: formData.filters.postalCodes ? formData.filters.postalCodes.split(',').map((code) => code.trim()) : undefined,
      minAmountPaid: formData.filters.minAmountPaid > 0 ? formData.filters.minAmountPaid : undefined,
    };
  };

  const previewSegment = async () => {
    try {
      setPreviewLoading(true);
      const filters = buildFilterPayload();
      const response = await api.post('/owner/campaigns/preview-segment', { filters });
      setPreviewCount(response.data.count || 0);
    } catch (error) {
      console.error('Error previewing segment:', error);
      setPreviewCount(0);
    } finally {
      setPreviewLoading(false);
    }
  };

  // Open the composer pre-filled with an existing draft so the user can edit it.
  const openEditDraft = (campaign) => {
    setEditingCampaignId(campaign.id);
    setSelectedCampaignTab('by-filter');     // editing = filter-based audience
    setCampaignCustomers('');
    const f = campaign.filters || {};
    setFormData({
      campaignName: campaign.name || '',
      message: campaign.content || campaign.message || '',
      source: campaign.source || 'push',
      image_url: campaign.image_url || '',
      filters: {
        tiers: Array.isArray(f.tiers) ? f.tiers : (f.tier ? [f.tier] : []),
        minPoints: Number(f.min_points || f.minPoints || 0) || 0,
        minVisits: Number(f.min_visits || f.minVisits || 0) || 0,
        postalCodes: Array.isArray(f.postal_codes)
          ? f.postal_codes.join(',')
          : (f.postal_code || f.postalCodes || ''),
        minAmountPaid: Number(f.min_amount_paid || f.minAmountPaid || 0) || 0,
      },
    });
    setImageError('');
    setSendMode('now');
    setScheduleAt('');
    setScheduleRecurrence('');
    setShowCreateModal(true);
  };

  const handleCreateCampaign = async () => {
    if (!formData.campaignName.trim() || !formData.message.trim()) {
      alert('Please fill in campaign name and message');
      return;
    }
    // Validate schedule if scheduling
    if (sendMode === 'schedule') {
      if (!scheduleAt) {
        alert('Please pick a date/time to schedule.');
        return;
      }
      const when = new Date(scheduleAt);
      if (isNaN(when.getTime()) || when.getTime() <= Date.now() - 60_000) {
        alert('Please pick a date/time in the future.');
        return;
      }
    }

    try {
      // Edit-an-existing-draft path. Skips the "send to group" / "schedule"
      // branches entirely — those are creation-only flows.
      if (editingCampaignId) {
        await ownerAPI.updateCampaign(editingCampaignId, {
          name: formData.campaignName,
          content: formData.message,
          source: formData.source || 'push',
          filters: buildFilterPayload(),
          image_url: formData.image_url || '',
        });
        resetForm();
        setEditingCampaignId(null);
        setShowCreateModal(false);
        await fetchCampaigns();
        return;
      }
      if (sendMode === 'schedule') {
        // Scheduled campaign — queue it. The daily cron (or on-demand runner)
        // will dispatch it when run_at is reached.
        if (selectedCampaignTab === 'by-customers') {
          alert('Scheduled sends currently support filter-based audiences only. Switch to "By Filter" to schedule.');
          return;
        }
        const payload = {
          name: formData.campaignName,
          content: formData.message,
          source: formData.source || 'push',
          filters: buildFilterPayload(),
          run_at: new Date(scheduleAt).toISOString(),
          recurrence: scheduleRecurrence || undefined,
        };
        await ownerAPI.scheduleCampaign(payload);
        await fetchScheduled();
      } else if (selectedCampaignTab === 'by-filter') {
        // Original filter-based flow (send now)
        const payload = {
          name: formData.campaignName,
          message: formData.message,
          source: formData.source || 'push',
          filters: buildFilterPayload(),
          image_url: formData.image_url || undefined,
        };
        await api.post('/owner/campaigns', payload);
      } else {
        // Send directly to selected customers. Campaign Map handoff sends
        // customer IDs; manual entry may send names or emails. We accept both
        // via the same endpoint and let the server reconcile.
        const customerList = campaignCustomers
          .split('\n')
          .map(s => s.trim())
          .filter(s => s.length > 0);

        if (customerList.length === 0) {
          alert('Please enter at least one customer');
          return;
        }

        // Heuristic: if it looks like a UUID-ish ID list (letters+digits+dashes,
        // no spaces, >12 chars), send as customer_ids — otherwise as names.
        const looksLikeIds = customerList.every(
          (s) => /^[a-zA-Z0-9_-]{10,}$/.test(s) && !s.includes('@')
        );
        const body = {
          name: formData.campaignName,
          content: formData.message,
          source: formData.source || 'push',
          image_url: formData.image_url || undefined,
        };
        if (looksLikeIds) body.customer_ids = customerList;
        else body.customer_names = customerList;

        await ownerAPI.sendCampaignToGroup(body);
      }

      resetForm();
      setCampaignCustomers('');
      setSelectedCampaignTab('by-filter');
      setShowCreateModal(false);
      await fetchCampaigns();
    } catch (error) {
      console.error('Error creating campaign:', error);
      alert('Failed to ' + (sendMode === 'schedule' ? 'schedule' : 'create') + ' campaign: ' + (error?.response?.data?.detail || error.message));
    }
  };

  const fetchCampaignTracking = async (campaignId) => {
    try {
      setTrackingLoading(true);
      const res = await ownerAPI.getCampaignTracking(campaignId);
      setTrackingData(res.data);
    } catch (error) {
      console.error('Error fetching tracking:', error);
      alert('Failed to load campaign details');
    } finally {
      setTrackingLoading(false);
    }
  };

  const handleSendCampaign = (campaign) => {
    setSendConfirmation(campaign);
  };

  const confirmSendCampaign = async () => {
    try {
      await api.post(`/owner/campaigns/${sendConfirmation.id}/send`);
      setSendConfirmation(null);
      await fetchCampaigns();
    } catch (error) {
      console.error('Error sending campaign:', error);
      alert('Failed to send campaign');
    }
  };

  const resetForm = () => {
    setFormData({
      campaignName: '',
      message: '',
      source: 'push',
      image_url: '',
      filters: {
        tiers: [],
        minPoints: 0,
        minVisits: 0,
        postalCodes: '',
        minAmountPaid: 0,
      },
    });
    setImageError('');
    setPreviewCount(null);
    setSendMode('now');
    setScheduleAt('');
    setScheduleRecurrence('');
    setEditingCampaignId(null);
  };

  // ---- Quick Send helpers ----
  const buildQuickFilterPayload = () => ({
    tiers: quickFilters.tiers.length > 0 ? quickFilters.tiers : undefined,
    minPoints: quickFilters.minPoints > 0 ? quickFilters.minPoints : undefined,
    minVisits: quickFilters.minVisits > 0 ? quickFilters.minVisits : undefined,
    postalCodes: quickFilters.postalCodes
      ? quickFilters.postalCodes.split(',').map((c) => c.trim()).filter(Boolean)
      : undefined,
    minAmountPaid: quickFilters.minAmountPaid > 0 ? quickFilters.minAmountPaid : undefined,
  });

  const quickPreview = async () => {
    try {
      setQuickPreviewLoading(true);
      const res = await api.post('/owner/campaigns/preview-segment', {
        filters: buildQuickFilterPayload(),
      });
      setQuickPreviewCount(res.data.count || 0);
    } catch (e) {
      setQuickPreviewCount(0);
    } finally {
      setQuickPreviewLoading(false);
    }
  };

  const quickToggleTier = (tier) => {
    setQuickFilters((prev) => ({
      ...prev,
      tiers: prev.tiers.includes(tier) ? prev.tiers.filter((t) => t !== tier) : [...prev.tiers, tier],
    }));
  };

  const quickSend = async () => {
    if (!quickName.trim() || !quickMessage.trim()) {
      alert('Please fill in a campaign name and message.');
      return;
    }
    if (quickPreviewCount === 0) {
      alert('No customers match these filters. Adjust them and try again.');
      return;
    }
    const recipients = quickPreviewCount != null ? quickPreviewCount : '(unknown — preview first)';
    if (!window.confirm(`Send "${quickName}" to ${recipients} customer(s) now?`)) return;
    try {
      setQuickSending(true);
      const created = await api.post('/owner/campaigns', {
        name: quickName,
        message: quickMessage,
        filters: buildQuickFilterPayload(),
        source: quickSource || 'push',
      });
      const id = created?.data?.id || created?.data?._id;
      if (id) {
        await api.post(`/owner/campaigns/${id}/send`);
      }
      setQuickName('');
      setQuickMessage('');
      setQuickFilters({
        tiers: [],
        minPoints: 0,
        minVisits: 0,
        postalCodes: '',
        minAmountPaid: 0,
      });
      setQuickPreviewCount(null);
      setQuickOpen(false);
      await fetchCampaigns();
      alert('Campaign sent.');
    } catch (e) {
      console.error('Quick send error:', e);
      alert('Failed to send: ' + (e?.response?.data?.detail || e?.message || 'unknown error'));
    } finally {
      setQuickSending(false);
    }
  };

  const getStatusBadge = (status) => {
    const statusStyles = {
      draft: 'bg-gray-200 text-gray-800',
      sent: 'bg-green-200 text-green-800',
      scheduled: 'bg-blue-200 text-blue-800',
    };
    return (
      <span className={`px-2 py-1 text-sm font-medium rounded ${statusStyles[status] || 'bg-gray-200 text-gray-800'}`}>
        {status.charAt(0).toUpperCase() + status.slice(1)}
      </span>
    );
  };

  const getFilterBadges = (campaign) => {
    const badges = [];
    if (campaign.filters?.tiers?.length > 0) {
      campaign.filters.tiers.forEach((tier) => {
        badges.push(`${tier[0].toUpperCase() + tier.slice(1)} Tier`);
      });
    }
    if (campaign.filters?.minPoints > 0) {
      badges.push(`Min ${campaign.filters.minPoints} Points`);
    }
    if (campaign.filters?.minVisits > 0) {
      badges.push(`Min ${campaign.filters.minVisits} Visits`);
    }
    if (campaign.filters?.minAmountPaid > 0) {
      badges.push(`Min €${campaign.filters.minAmountPaid}`);
    }
    return badges;
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Outbound"
        title={t('campaigns.title')}
        description={t('campaigns.subtitle')}
        role="business_owner"
        actions={
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <ReEnableNotificationsButton />
            <button
              onClick={() => setShowCreateModal(true)}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full text-sm font-semibold text-white transition-all shadow-md hover:-translate-y-0.5"
              style={{ background: `linear-gradient(135deg, ${C_PS.ochre} 0%, ${C_PS.terracotta} 100%)` }}
            >
              <Plus size={16} /> New Campaign
            </button>
          </div>
        }
      />

      {/* Main Content */}
      <div>

        {/* ============= Quick Send panel ============= */}
        <div className="mb-6 rounded-lg border" style={{ borderColor: 'var(--flc-line, #E9E5E0)', backgroundColor: 'var(--flc-card, #FAFAF8)' }}>
          <button
            onClick={() => setQuickOpen((v) => !v)}
            className="w-full flex items-center justify-between p-4 hover:bg-[#F5F4F1] transition rounded-lg"
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-[#B85C38]/10 flex items-center justify-center">
                <Zap size={20} style={{ color: '#B85C38' }} />
              </div>
              <div className="text-left">
                <p className="font-semibold text-[#171412]" style={{ fontFamily: 'Manrope' }}>
                  Quick Send — Filter customers and send in one shot
                </p>
                <p className="text-xs text-[#57504A]">
                  Pick filters, preview how many customers match, write your message, hit send. No drafts.
                </p>
              </div>
            </div>
            {quickOpen ? <ChevronUp size={20} style={{ color: '#57504A' }} /> : <ChevronDown size={20} style={{ color: '#57504A' }} />}
          </button>

          {quickOpen && (
            <div className="p-4 border-t" style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                <div>
                  <label className="block text-xs font-semibold text-[#57504A] uppercase mb-1">Campaign Name</label>
                  <input
                    type="text"
                    value={quickName}
                    onChange={(e) => setQuickName(e.target.value)}
                    placeholder="e.g. Weekend Offer"
                    className="w-full px-3 py-2 border rounded-lg"
                    style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-[#57504A] uppercase mb-1">Message</label>
                  <input
                    type="text"
                    value={quickMessage}
                    onChange={(e) => setQuickMessage(e.target.value)}
                    placeholder="Hi {first_name}, 20% off this Saturday..."
                    className="w-full px-3 py-2 border rounded-lg"
                    style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}
                  />
                </div>
              </div>

              <div className="mb-4">
                <label className="block text-xs font-semibold text-[#57504A] uppercase mb-1">
                  Channel / Source
                  <span className="ml-2 normal-case text-[10px] text-[#8D857D] font-normal">
                    (tags this campaign so you can see its performance per channel)
                  </span>
                </label>
                <div className="flex flex-wrap gap-2">
                  {[
                    // Only the channels FidClic actually delivers on today.
                    // EMAIL channel hidden — re-enable by uncommenting the line below.
                    { key: 'push', label: 'Wallet Push' },
                    // { key: 'email', label: 'Email' },
                    { key: 'other', label: 'Other' },
                  ].map((s) => (
                    <button
                      key={s.key}
                      type="button"
                      onClick={() => setQuickSource(s.key)}
                      className={`px-3 py-1 text-xs rounded-full border transition ${
                        quickSource === s.key
                          ? 'bg-[#B85C38] text-white border-[#B85C38]'
                          : 'bg-white text-[#57504A] border-[#E9E5E0] hover:border-[#B85C38]'
                      }`}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
                {/* Tiers */}
                <div>
                  <label className="block text-xs font-semibold text-[#57504A] uppercase mb-1">Tiers</label>
                  <div className="flex gap-2">
                    {['bronze', 'silver', 'gold'].map((tier) => (
                      <button
                        key={tier}
                        type="button"
                        onClick={() => quickToggleTier(tier)}
                        className={`px-2 py-1 text-xs rounded border ${
                          quickFilters.tiers.includes(tier)
                            ? 'bg-[#B85C38] text-white border-[#B85C38]'
                            : 'bg-white text-[#57504A] border-[#E9E5E0]'
                        }`}
                      >
                        {tier[0].toUpperCase() + tier.slice(1)}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Min Points */}
                <div>
                  <label className="block text-xs font-semibold text-[#57504A] uppercase mb-1">Min Points</label>
                  <NumberInput
                    min={0}
                    value={quickFilters.minPoints}
                    onChange={(n) => setQuickFilters({ ...quickFilters, minPoints: n || 0 })}
                    className="w-full px-2 py-1.5 border rounded-lg text-sm"
                    style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}
                  />
                </div>

                {/* Min Visits */}
                <div>
                  <label className="block text-xs font-semibold text-[#57504A] uppercase mb-1">Min Visits</label>
                  <NumberInput
                    min={0}
                    value={quickFilters.minVisits}
                    onChange={(n) => setQuickFilters({ ...quickFilters, minVisits: n || 0 })}
                    className="w-full px-2 py-1.5 border rounded-lg text-sm"
                    style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}
                  />
                </div>

                {/* Postal Codes */}
                <div>
                  <label className="block text-xs font-semibold text-[#57504A] uppercase mb-1">Postal Codes</label>
                  <input
                    type="text"
                    value={quickFilters.postalCodes}
                    onChange={(e) => setQuickFilters({ ...quickFilters, postalCodes: e.target.value })}
                    placeholder="75001,75002"
                    className="w-full px-2 py-1.5 border rounded-lg text-sm"
                    style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}
                  />
                </div>

                {/* Min Amount Paid */}
                <div>
                  <label className="block text-xs font-semibold text-[#57504A] uppercase mb-1">Min Paid (€)</label>
                  <NumberInput
                    min={0}
                    step={0.01}
                    value={quickFilters.minAmountPaid}
                    onChange={(n) => setQuickFilters({ ...quickFilters, minAmountPaid: n || 0 })}
                    className="w-full px-2 py-1.5 border rounded-lg text-sm"
                    style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}
                  />
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <button
                  onClick={quickPreview}
                  disabled={quickPreviewLoading}
                  className="px-4 py-2 border rounded-lg text-sm font-semibold flex items-center gap-2"
                  style={{ borderColor: '#B85C38', color: '#B85C38' }}
                >
                  <Filter size={16} />
                  {quickPreviewLoading ? 'Previewing…' : 'Preview matches'}
                </button>
                {quickPreviewCount !== null && (
                  <span className="text-sm text-[#57504A]">
                    Will reach <span className="font-bold text-[#B85C38]">{quickPreviewCount}</span> customer{quickPreviewCount === 1 ? '' : 's'}
                  </span>
                )}
                <div className="flex-1" />
                <button
                  onClick={quickSend}
                  disabled={quickSending}
                  className="px-5 py-2 rounded-lg text-sm font-semibold text-white flex items-center gap-2 disabled:opacity-50"
                  style={{ backgroundColor: '#B85C38' }}
                >
                  <Send size={16} />
                  {quickSending ? 'Sending…' : `Send to ${quickPreviewCount ?? '…'} now`}
                </button>
              </div>
              <p className="text-xs text-[#57504A] mt-3">
                Quick Send creates the campaign and fires it immediately. For scheduled sends or drafts, use "New Campaign" in the header.
              </p>
            </div>
          )}
        </div>
        {/* ============= /Quick Send panel ============= */}

        {/* ============= Card overlay panel ============= */}
        <CardOverlayPanel />
        {/* ============= /Card overlay panel ============= */}

        {/* Per-channel performance summary */}
        {!loading && campaigns.length > 0 && (() => {
          const sent = campaigns.filter((c) => c.status === 'sent');
          if (sent.length === 0) return null;
          const perSource = {};
          sent.forEach((c) => {
            const src = c.source || 'push';
            if (!perSource[src]) perSource[src] = { count: 0, delivered: 0, opens: 0, visits: 0 };
            const row = perSource[src];
            row.count += 1;
            row.delivered += c.delivered_count || 0;
            row.opens += c.opens_unique || 0;
            row.visits += c.visits_from_campaign || 0;
          });
          const rows = Object.entries(perSource).sort((a, b) => b[1].delivered - a[1].delivered);
          return (
            <div className="mb-6 border rounded-xl p-5 bg-white" style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-xl font-bold" style={{ fontFamily: 'Cormorant Garamond', color: '#171412' }}>
                  Campaign performance by channel
                </h2>
                <span className="text-xs text-[#8D857D]">
                  How each publishing channel is performing — openings and visits in absolute numbers and %.
                </span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
                {rows.map(([src, row]) => {
                  const openPct = row.delivered > 0 ? Math.round((row.opens / row.delivered) * 100) : 0;
                  const visitPct = row.delivered > 0 ? Math.round((row.visits / row.delivered) * 100) : 0;
                  const label = src === 'push' ? 'Wallet Push' : src[0].toUpperCase() + src.slice(1);
                  return (
                    <div key={src} className="p-3 rounded-lg border" style={{ borderColor: 'var(--flc-line, #E9E5E0)', backgroundColor: 'var(--flc-card, #FAFAF8)' }}>
                      <p className="text-xs font-semibold text-[#B85C38] uppercase tracking-wider">{label}</p>
                      <p className="text-2xl font-bold text-[#171412]">{row.count}</p>
                      <p className="text-[11px] text-[#8D857D]">campaigns · {row.delivered} delivered</p>
                      <div className="mt-2 text-xs text-[#57504A] space-y-0.5">
                        <div>Opens: <b>{row.opens}</b> <span className="text-[#8D857D]">({openPct}%)</span></div>
                        <div>Visits: <b>{row.visits}</b> <span className="text-[#8D857D]">({visitPct}%)</span></div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })()}

        {/* Scheduled campaigns — upcoming sends with cancel controls */}
        {scheduledCampaigns.length > 0 && (
          <div className="mb-6 border rounded-xl p-5 bg-white" style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <CalendarClock size={18} style={{ color: '#B85C38' }} />
                <h2 className="text-xl font-bold" style={{ fontFamily: 'Cormorant Garamond', color: '#171412' }}>
                  Scheduled campaigns ({scheduledCampaigns.length})
                </h2>
              </div>
              <button
                onClick={fetchScheduled}
                disabled={scheduledLoading}
                className="text-xs text-[#B85C38] font-semibold hover:underline disabled:opacity-50"
              >
                {scheduledLoading ? 'Refreshing…' : 'Refresh'}
              </button>
            </div>
            <div className="space-y-2">
              {scheduledCampaigns
                .filter((s) => s.status === 'scheduled')
                .sort((a, b) => new Date(a.run_at) - new Date(b.run_at))
                .map((s) => {
                  const when = s.run_at ? new Date(s.run_at) : null;
                  const whenLabel = when && !isNaN(when)
                    ? when.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
                    : '—';
                  return (
                    <div key={s.id} className="p-3 rounded-lg bg-[#F5F4F1] border border-[#E9E5E0] flex items-center justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-semibold text-[#171412] truncate">{s.name}</span>
                          <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full bg-[#B85C38] text-white">
                            {s.source || 'push'}
                          </span>
                          {s.recurrence && (
                            <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full bg-[#E3A869] text-white">
                              Repeats {s.recurrence}
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-[#57504A] mt-0.5">
                          <CalendarClock size={11} className="inline -mt-0.5 mr-1" />
                          Fires {whenLabel}
                        </p>
                        {s.content && (
                          <p className="text-xs text-[#8D857D] mt-1 line-clamp-1">{s.content}</p>
                        )}
                      </div>
                      <button
                        onClick={() => cancelScheduled(s.id)}
                        className="px-3 py-1.5 rounded border border-red-300 text-red-700 text-xs font-semibold flex items-center gap-1 hover:bg-red-50"
                        title="Cancel this scheduled campaign"
                      >
                        <Trash2 size={12} /> Cancel
                      </button>
                    </div>
                  );
                })}
            </div>
          </div>
        )}

        {/* Unread Campaign Warnings */}
        {!loading && campaigns.length > 0 && (() => {
          const lowOpenRateCampaigns = campaigns.filter(
            c => c.status === 'sent' &&
            c.delivered_count > 0 &&
            ((c.opens_unique || 0) / (c.delivered_count || 1)) * 100 < 15
          );
          return lowOpenRateCampaigns.length > 0 ? (
            <div className="mb-6 p-4 rounded-lg border-l-4 bg-amber-50" style={{ borderColor: '#E3A869' }}>
              <div className="flex items-start gap-3">
                <AlertTriangle size={20} style={{ color: '#E3A869' }} className="flex-shrink-0 mt-0.5" />
                <div>
                  <p className="font-semibold text-[#171412]">Tip: Campaigns with catchy subject lines get 2-3x more opens.</p>
                  <p className="text-sm text-[#57504A]">Try making your next subject more personal.</p>
                </div>
              </div>
            </div>
          ) : null;
        })()}

        {loading ? (
          <div className="text-center py-12">
            <p style={{ color: '#57504A', fontFamily: 'Manrope' }}>Loading campaigns...</p>
          </div>
        ) : campaigns.length === 0 ? (
          <div className="text-center py-12">
            <Megaphone size={48} style={{ color: '#B85C38', margin: '0 auto 16px' }} />
            <p style={{ color: '#57504A', fontFamily: 'Manrope' }} className="text-lg">
              No campaigns yet. Create your first campaign to get started.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {campaigns.map((campaign) => {
              const filterBadges = getFilterBadges(campaign);
              return (
                <div
                  key={campaign.id}
                  className="border rounded-lg overflow-hidden transition hover:shadow-md"
                  style={{ borderColor: 'var(--flc-line, #E9E5E0)', backgroundColor: 'var(--flc-card, #FAFAF8)' }}
                >
                  {/* Hero image strip — appears at top of the card if the campaign has one */}
                  {campaign.image_url && (
                    <div className="relative h-40 overflow-hidden border-b" style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}>
                      <img
                        src={campaign.image_url}
                        alt=""
                        className="w-full h-full object-cover"
                      />
                      <div className="absolute inset-0 bg-gradient-to-t from-black/30 to-transparent pointer-events-none" />
                      <div className="absolute top-3 left-3 px-2.5 py-1 rounded-full bg-white/90 backdrop-blur-sm text-[10px] font-bold uppercase tracking-wider"
                           style={{ color: '#96431F' }}>
                        📸 With image
                      </div>
                    </div>
                  )}
                <div className="p-6">
                  <div className="flex justify-between items-start mb-4">
                    <div className="flex-1">
                      <h3 className="text-2xl font-bold mb-2" style={{ fontFamily: 'Cormorant Garamond', color: '#171412' }}>
                        {campaign.name}
                      </h3>
                      <div className="flex items-center gap-3 flex-wrap">
                        {getStatusBadge(campaign.status)}
                        {campaign.source && (
                          <span
                            className="px-2 py-0.5 text-xs rounded-full font-semibold capitalize"
                            style={{
                              backgroundColor:
                                campaign.source === 'push' ? 'var(--flc-paper2, #F5F4F1)'
                                : campaign.source === 'email' ? '#E8F5E9'
                                : '#F5F4F0',
                              color: '#171412',
                            }}
                          >
                            {campaign.source === 'push' ? 'Wallet Push' : campaign.source}
                          </span>
                        )}
                        <div style={{ color: '#57504A', fontFamily: 'Manrope', fontSize: '14px' }} className="flex items-center gap-4">
                          <span className="flex items-center gap-1">
                            <Users size={16} />
                            {campaign.targeted_count || campaign.targetedCount || 0} targeted
                          </span>
                          {campaign.status === 'sent' && (
                            <span className="flex items-center gap-1">
                              <CheckCircle2 size={16} />
                              {campaign.delivered_count || campaign.deliveredCount || 0} delivered
                            </span>
                          )}
                          <span className="flex items-center gap-1">
                            <Clock size={16} />
                            {new Date(campaign.created_at || campaign.createdAt).toLocaleDateString()}
                          </span>
                        </div>
                      </div>
                    </div>
                    {campaign.status === 'draft' && (
                      <div className="flex items-center gap-2 ml-4">
                        <button
                          onClick={() => openEditDraft(campaign)}
                          className="flex items-center gap-2 px-4 py-2 rounded-lg font-semibold transition border"
                          style={{ borderColor: '#B85C38', color: '#B85C38', backgroundColor: 'var(--flc-card, #FAFAF8)' }}
                          title="Edit this draft before sending"
                        >
                          <Pencil size={16} />
                          Edit
                        </button>
                        <button
                          onClick={() => handleSendCampaign(campaign)}
                          className="flex items-center gap-2 px-4 py-2 rounded-lg font-semibold text-white transition"
                          style={{ backgroundColor: '#B85C38' }}
                        >
                          <Send size={18} />
                          Send
                        </button>
                      </div>
                    )}
                  </div>

                  {/* Tracking Stats */}
                  {campaign.status === 'sent' && (
                    <div className="mb-4 grid grid-cols-2 md:grid-cols-4 gap-3">
                      <div className="p-3 rounded bg-[#F5F4F1]">
                        <p className="text-xs text-[#8D857D]" style={{ fontFamily: 'Manrope' }}>Sent to</p>
                        <p className="text-lg font-bold text-[#171412]">{campaign.targeted_count || 0}</p>
                      </div>
                      <div className="p-3 rounded bg-[#F5F4F1]">
                        <p className="text-xs text-[#8D857D]" style={{ fontFamily: 'Manrope' }}>Delivered</p>
                        <p className="text-lg font-bold text-[#171412]">{campaign.delivered_count || 0}</p>
                      </div>
                      <div className="p-3 rounded bg-[#F5F4F1]">
                        <p className="text-xs text-[#8D857D]" style={{ fontFamily: 'Manrope' }}>Opened</p>
                        <p className="text-lg font-bold text-[#171412]">
                          {campaign.delivered_count > 0
                            ? Math.round(((campaign.opens_unique || 0) / campaign.delivered_count) * 100)
                            : 0}%
                        </p>
                      </div>
                      <div className="p-3 rounded bg-[#F5F4F1]">
                        <p className="text-xs text-[#8D857D]" style={{ fontFamily: 'Manrope' }}>Visits after</p>
                        <p className="text-lg font-bold text-[#171412]">
                          {campaign.delivered_count > 0
                            ? Math.round(((campaign.visits_from_campaign || 0) / campaign.delivered_count) * 100)
                            : 0}%
                        </p>
                      </div>
                    </div>
                  )}

                  {/* Item 22 — revenue + lift roll-up. Visible only when the campaign has been sent. */}
                  {campaign.status === 'sent' && campaign.performance && (
                    <div className="mb-4 grid grid-cols-2 md:grid-cols-3 gap-3">
                      <div className="p-3 rounded-lg" style={{ background: 'linear-gradient(135deg, #4A5D2315 0%, #4A5D2305 100%)', border: '1px solid #4A5D2333' }}>
                        <p className="text-[10px] font-bold uppercase tracking-wider" style={{ color: '#4A5D23' }}>€ generated</p>
                        <p className="text-xl font-bold mt-0.5" style={{ color: '#171412', fontFamily: 'Cormorant Garamond' }}>
                          €{(campaign.performance.revenue_attributed || 0).toLocaleString()}
                        </p>
                        <p className="text-[10px] mt-0.5" style={{ color: '#8D857D' }}>
                          {campaign.performance.attributed_visits} visites × €{campaign.performance.avg_ticket} avg
                        </p>
                      </div>
                      <div className="p-3 rounded-lg" style={{ background: 'linear-gradient(135deg, #B85C3815 0%, #B85C3805 100%)', border: '1px solid #B85C3833' }}>
                        <p className="text-[10px] font-bold uppercase tracking-wider" style={{ color: '#B85C38' }}>Incremental visits</p>
                        <p className="text-xl font-bold mt-0.5" style={{ color: '#171412', fontFamily: 'Cormorant Garamond' }}>
                          {campaign.performance.lift_visits >= 0 ? '+' : ''}{campaign.performance.lift_visits}
                        </p>
                        <p className="text-[10px] mt-0.5" style={{ color: '#8D857D' }}>
                          vs {campaign.performance.baseline_visits} avant l'envoi
                        </p>
                      </div>
                      <div className="p-3 rounded-lg" style={{ background: 'linear-gradient(135deg, #E3A86915 0%, #E3A86905 100%)', border: '1px solid #E3A86933' }}>
                        <p className="text-[10px] font-bold uppercase tracking-wider" style={{ color: '#96431F' }}>Lift</p>
                        <p className="text-xl font-bold mt-0.5" style={{ color: '#171412', fontFamily: 'Cormorant Garamond' }}>
                          {campaign.performance.lift_pct === null
                            ? 'Net new'
                            : `${campaign.performance.lift_pct >= 0 ? '+' : ''}${campaign.performance.lift_pct}%`}
                        </p>
                        <p className="text-[10px] mt-0.5" style={{ color: '#8D857D' }}>
                          incremental vs baseline
                        </p>
                      </div>
                    </div>
                  )}

                  {/* Item 23 — AI analyzer. Single button toggles a 3-bullet recap from Gemini (free tier) or a heuristic fallback. */}
                  {campaign.status === 'sent' && (
                    <div className="mb-4">
                      {!aiAnalysis[campaign.id] ? (
                        <button
                          onClick={() => runAiAnalysis(campaign.id)}
                          disabled={!!aiAnalysisLoading[campaign.id]}
                          className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full transition font-semibold"
                          style={{
                            background: aiAnalysisLoading[campaign.id] ? '#E9E5E0' : 'linear-gradient(135deg, #B85C38 0%, #B85C38 100%)',
                            color: 'white',
                            opacity: aiAnalysisLoading[campaign.id] ? 0.7 : 1,
                          }}
                        >
                          <Zap size={13} />
                          {aiAnalysisLoading[campaign.id] ? 'Analyse en cours…' : 'Pourquoi ça a marché ? (IA)'}
                        </button>
                      ) : (
                        <div
                          className="rounded-xl p-4"
                          style={{ background: 'linear-gradient(135deg, #B85C3810 0%, #B85C3805 100%)', border: '1px solid #B85C3844' }}
                        >
                          <div className="flex items-center justify-between mb-2">
                            <p className="text-xs font-bold uppercase tracking-wider flex items-center gap-1.5" style={{ color: '#5E527C' }}>
                              <Zap size={12} /> Analyse IA · {aiAnalysis[campaign.id].used_ai ? aiAnalysis[campaign.id].model : 'heuristique'}
                            </p>
                            <button
                              onClick={() => runAiAnalysis(campaign.id)}
                              className="text-[10px] underline"
                              style={{ color: '#5E527C' }}
                              disabled={!!aiAnalysisLoading[campaign.id]}
                            >
                              {aiAnalysisLoading[campaign.id] ? '…' : 'Refaire'}
                            </button>
                          </div>
                          <ul className="space-y-1.5">
                            {(aiAnalysis[campaign.id].bullets || []).map((b, i) => (
                              <li key={i} className="text-sm flex gap-2" style={{ color: '#171412' }}>
                                <span style={{ color: '#B85C38', fontWeight: 700 }}>•</span>
                                <span>{b}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Message preview — content is the canonical field on the
                      backend; legacy clients used `message`, so fall through. */}
                  <div className="mb-4 p-4 rounded whitespace-pre-wrap" style={{ backgroundColor: 'var(--flc-paper2, #F5F4F1)' }}>
                    <p style={{ color: '#57504A', fontFamily: 'Manrope' }} className="text-sm">
                      {campaign.content || campaign.message || <span className="italic text-[#8D857D]">(no message yet)</span>}
                    </p>
                  </div>

                  {/* Filter badges */}
                  {filterBadges.length > 0 && (
                    <div className="flex flex-wrap gap-2 mb-4">
                      {filterBadges.map((badge, idx) => (
                        <span
                          key={idx}
                          className="px-3 py-1 text-sm rounded-full"
                          style={{ backgroundColor: '#E3A869', color: '#FAFAF8', fontFamily: 'Manrope' }}
                        >
                          {badge}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* View Details Button */}
                  {campaign.status === 'sent' && (
                    <button
                      onClick={() => {
                        setViewingTrackingId(campaign.id);
                        fetchCampaignTracking(campaign.id);
                      }}
                      className="flex items-center gap-2 px-3 py-2 rounded text-sm font-semibold text-[#B85C38] hover:bg-[#F5F4F1] transition"
                    >
                      <Eye size={16} />
                      View details
                    </button>
                  )}
                </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Create Campaign Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-2xl w-full max-h-screen overflow-y-auto" style={{ backgroundColor: 'var(--flc-card, #FAFAF8)' }}>
            <div className="border-b p-6 relative" style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}>
              <button
                type="button"
                aria-label="Close"
                onClick={() => setShowCreateModal(false)}
                className="absolute top-4 right-4 w-9 h-9 rounded-full flex items-center justify-center transition hover:bg-[#F5F4F1]"
                style={{ color: '#57504A' }}
              >
                <X size={20} />
              </button>
              <h2 className="text-3xl font-bold pr-12" style={{ fontFamily: 'Cormorant Garamond', color: '#171412' }}>
                {editingCampaignId ? 'Edit Draft' : 'Create New Campaign'}
              </h2>
              {editingCampaignId && (
                <p className="text-sm text-[#57504A] mt-1" style={{ fontFamily: 'Manrope' }}>
                  Updating an unsent draft. Changes don't fire until you hit Send on the campaign card.
                </p>
              )}
            </div>

            <div className="p-6 space-y-6">
              {/* Campaign Name */}
              <div>
                <label className="block text-sm font-semibold mb-2" style={{ color: '#171412', fontFamily: 'Manrope' }}>
                  Campaign Name
                </label>
                <input
                  type="text"
                  name="campaignName"
                  value={formData.campaignName}
                  onChange={handleInputChange}
                  placeholder="e.g. Summer Promo"
                  className="w-full px-4 py-2 border rounded-lg"
                  style={{ borderColor: 'var(--flc-line, #E9E5E0)', color: '#171412' }}
                />
              </div>

              {/* Message */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="block text-sm font-semibold" style={{ color: '#171412', fontFamily: 'Manrope' }}>
                    Message
                  </label>
                  <button
                    type="button"
                    onClick={() => {
                      const url = window.prompt('Paste a link (Instagram, menu PDF, RSVP form, etc.):', 'https://');
                      if (!url) return;
                      const trimmed = url.trim();
                      if (!/^https?:\/\//i.test(trimmed)) {
                        alert('Link must start with https:// or http://');
                        return;
                      }
                      const cur = formData.message || '';
                      const sep = cur.endsWith(' ') || cur.endsWith('\n') || cur === '' ? '' : ' ';
                      setFormData((prev) => ({ ...prev, message: `${cur}${sep}${trimmed}` }));
                    }}
                    className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest transition"
                    style={{ background: `${C_PS.terracotta}1A`, color: C_PS.terracotta, border: `1px solid ${C_PS.terracotta}33` }}
                  >
                    🔗 Add link
                  </button>
                </div>
                {/* Editor + live phone preview side-by-side. Owner sees exactly
                    what the customer's lock-screen notification will look like
                    while typing. */}
                <div className="grid md:grid-cols-[1fr_auto] gap-4 items-start">
                  <div className="min-w-0">
                    <textarea
                      name="message"
                      value={formData.message}
                      onChange={handleInputChange}
                      placeholder="Your campaign message — paste any URL or @handle and it'll auto-link."
                      rows={5}
                      className="w-full px-4 py-2 border rounded-lg"
                      style={{ borderColor: 'var(--flc-line, #E9E5E0)', color: '#171412', fontFamily: 'Manrope' }}
                    />
                    <p className="text-[10px] mt-1.5" style={{ color: C_PS.inkMute }}>
                      Pro tip: paste a full <code>https://…</code> URL or an <code>@handle</code> — it becomes a clickable link automatically.
                    </p>
                    {/* Token chips — tap to insert. The message keeps the raw
                        {token}; the phone on the right shows it resolved
                        against a real customer, so the owner can read the
                        message the way the recipient will. */}
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {TOKEN_HELP.map((tk) => (
                        <button
                          key={tk.token}
                          type="button"
                          title={tk.label}
                          onClick={() => setFormData((prev) => ({ ...prev, message: (prev.message || '') + tk.token }))}
                          className="px-2 py-0.5 rounded-full border text-[10px]"
                          style={{ borderColor: '#E9E5E0', color: '#57504A', background: '#FFFFFF', fontFamily: 'ui-monospace, monospace' }}
                        >
                          {tk.token}
                        </button>
                      ))}
                    </div>
                  </div>
                  <PhonePushPreview
                    businessName={previewTenant.campaign_sender_name || previewTenant.name || formData.campaignName || 'Your shop'}
                    title={renderTokens(formData.campaignName || '', previewCustomer, previewTenant, previewCardTemplate)}
                    body={renderTokens(formData.message || '', previewCustomer, previewTenant, previewCardTemplate)}
                    primaryColor={C_PS.terracotta}
                    width={210}
                    caption={previewCustomer?.__sample
                      ? 'Aperçu — exemple : Sophie Martin'
                      : `Aperçu pour ${previewCustomer?.name || 'un client'}`}
                  />
                </div>
              </div>

              {/* Channel / Source */}
              <div>
                <label className="block text-sm font-semibold mb-2" style={{ color: '#171412', fontFamily: 'Manrope' }}>
                  Channel / Source
                  <span className="ml-2 text-xs text-[#8D857D] font-normal">
                    Where this campaign is published — used to measure per-channel performance.
                  </span>
                </label>
                <div className="flex flex-wrap gap-2">
                  {[
                    // Only the channels FidClic actually delivers on today.
                    // EMAIL channel hidden — re-enable by uncommenting the line below.
                    { key: 'push', label: 'Wallet Push' },
                    // { key: 'email', label: 'Email' },
                    { key: 'other', label: 'Other' },
                  ].map((s) => (
                    <button
                      key={s.key}
                      type="button"
                      onClick={() => setFormData((prev) => ({ ...prev, source: s.key }))}
                      className={`px-3 py-1 text-xs rounded-full border transition ${
                        (formData.source || 'push') === s.key
                          ? 'bg-[#B85C38] text-white border-[#B85C38]'
                          : 'bg-white text-[#57504A] border-[#E9E5E0] hover:border-[#B85C38]'
                      }`}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Hero image — optional photo that appears in email + on the wallet card news feed */}
              <div className="border-t pt-6" style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}>
                <label className="block text-sm font-semibold mb-1" style={{ color: '#171412', fontFamily: 'Manrope' }}>
                  📸 Hero image <span className="font-normal text-[#8D857D]">— optional, but doubles open rates</span>
                </label>
                <p className="text-xs text-[#57504A] mb-3" style={{ fontFamily: 'Manrope' }}>
                  Upload a photo (max 5 MB) — it appears at the top of the email and on the customer's wallet card news feed.
                </p>

                {formData.image_url ? (
                  // Image preview state
                  <div className="rounded-xl overflow-hidden border-2 relative group"
                       style={{ borderColor: '#E3A869' }}>
                    <img
                      src={formData.image_url}
                      alt="Campaign hero"
                      className="w-full h-48 object-cover"
                    />
                    <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-all flex items-center justify-center gap-2 opacity-0 group-hover:opacity-100">
                      <label className="px-3 py-2 rounded-lg bg-white text-[#171412] font-semibold text-xs cursor-pointer hover:bg-[#F5F4F1]">
                        Replace
                        <input type="file" accept="image/*" onChange={handleImageUpload} className="hidden" />
                      </label>
                      <button
                        type="button"
                        onClick={() => setFormData((p) => ({ ...p, image_url: '' }))}
                        className="px-3 py-2 rounded-lg bg-red-500 text-white font-semibold text-xs hover:bg-red-600"
                      >
                        Remove
                      </button>
                    </div>
                    <div className="absolute top-2 left-2 px-2 py-1 rounded-full bg-white/90 backdrop-blur-sm text-[10px] font-bold uppercase tracking-wider"
                         style={{ color: '#96431F' }}>
                      ✓ Image attached
                    </div>
                  </div>
                ) : (
                  // Upload prompt state
                  <label
                    className="block rounded-xl border-2 border-dashed cursor-pointer transition-all hover:border-[#B85C38] hover:bg-[#F6E9E2]"
                    style={{ borderColor: '#E3A869', background: '#FEFBF2' }}
                  >
                    <input
                      type="file"
                      accept="image/*"
                      onChange={handleImageUpload}
                      className="hidden"
                      disabled={imageUploading}
                    />
                    <div className="px-6 py-10 text-center">
                      <div className="w-14 h-14 rounded-full mx-auto mb-3 flex items-center justify-center"
                           style={{ background: 'linear-gradient(135deg, #FDF1DC, #E3A869)' }}>
                        <span className="text-2xl">📸</span>
                      </div>
                      <p className="text-sm font-semibold mb-1" style={{ color: '#96431F' }}>
                        {imageUploading ? 'Uploading…' : 'Click to upload a photo'}
                      </p>
                      <p className="text-xs" style={{ color: '#8B6914' }}>
                        JPG, PNG, GIF — max 5 MB. Auto-compressed to fit the email.
                      </p>
                    </div>
                  </label>
                )}
                {imageError && (
                  <p className="text-xs text-red-600 mt-2 font-semibold">⚠ {imageError}</p>
                )}
              </div>

              {/* Send timing — Send now vs. Schedule for later */}
              <div className="border-t pt-6" style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}>
                <label className="block text-sm font-semibold mb-3" style={{ color: '#171412', fontFamily: 'Manrope' }}>
                  When should this go out?
                </label>
                <div className="flex gap-2 mb-3">
                  <button
                    type="button"
                    onClick={() => setSendMode('now')}
                    className={`px-4 py-2 rounded-lg text-sm font-semibold border flex items-center gap-2 transition ${
                      sendMode === 'now' ? 'bg-[#B85C38] text-white border-[#B85C38]' : 'bg-white text-[#57504A] border-[#E9E5E0]'
                    }`}
                  >
                    <Send size={14} /> Send now
                  </button>
                  <button
                    type="button"
                    onClick={() => setSendMode('schedule')}
                    className={`px-4 py-2 rounded-lg text-sm font-semibold border flex items-center gap-2 transition ${
                      sendMode === 'schedule' ? 'bg-[#B85C38] text-white border-[#B85C38]' : 'bg-white text-[#57504A] border-[#E9E5E0]'
                    }`}
                  >
                    <CalendarClock size={14} /> Schedule for later
                  </button>
                </div>
                {sendMode === 'schedule' && (
                  <div className="p-4 rounded-lg bg-[#F5F4F1] border border-[#E9E5E0] space-y-3">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-semibold text-[#57504A] uppercase mb-1">Send date & time</label>
                        <input
                          type="datetime-local"
                          value={scheduleAt}
                          onChange={(e) => setScheduleAt(e.target.value)}
                          className="w-full px-3 py-2 rounded border border-[#E9E5E0] text-sm bg-white"
                        />
                        <p className="text-[11px] text-[#8D857D] mt-1">Local time — stored as UTC on the server.</p>
                      </div>
                      <div>
                        <label className="block text-xs font-semibold text-[#57504A] uppercase mb-1">Repeat (optional)</label>
                        <select
                          value={scheduleRecurrence}
                          onChange={(e) => setScheduleRecurrence(e.target.value)}
                          className="w-full px-3 py-2 rounded border border-[#E9E5E0] text-sm bg-white"
                        >
                          <option value="">No — one-off send</option>
                          <option value="daily">Every day</option>
                          <option value="weekly">Every week</option>
                          <option value="monthly">Every month</option>
                        </select>
                      </div>
                    </div>
                    <p className="text-xs text-[#57504A]">
                      {scheduleRecurrence
                        ? `The campaign will fire at the chosen time and repeat ${scheduleRecurrence}. Cancel anytime from "Scheduled campaigns".`
                        : 'The campaign will fire at the chosen time and then finish.'}
                    </p>
                  </div>
                )}
              </div>

              {/* Unified Audience Builder — replaces the old "By filter" / "By selected
                  customers" tab UI. Lets the owner pick specific customers via search
                  (no manual typing of details) and/or apply every filter dimension in
                  one place, with a live preview count. */}
              <CampaignAudienceBuilder
                formData={formData}
                setFormData={setFormData}
                campaignCustomers={campaignCustomers}
                setCampaignCustomers={setCampaignCustomers}
                setSelectedCampaignTab={setSelectedCampaignTab}
              />
            </div>

            {/* Modal Footer */}
            <div className="border-t p-6 flex justify-end gap-3" style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}>
              <button
                onClick={() => {
                  setShowCreateModal(false);
                  resetForm();
                }}
                className="px-6 py-2 rounded-lg font-semibold border transition"
                style={{ borderColor: 'var(--flc-line, #E9E5E0)', color: '#57504A' }}
              >
                Cancel
              </button>
              <button
                onClick={handleCreateCampaign}
                className="px-6 py-2 rounded-lg font-semibold text-white transition flex items-center gap-2"
                style={{ backgroundColor: '#B85C38' }}
              >
                {editingCampaignId
                  ? (<><Pencil size={16} /> Save Draft</>)
                  : sendMode === 'schedule'
                    ? (<><CalendarClock size={16} /> Schedule Campaign</>)
                    : 'Create Campaign'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Send Confirmation Modal */}
      {sendConfirmation && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-2xl w-full" style={{ backgroundColor: 'var(--flc-card, #FAFAF8)' }}>
            <div className="border-b p-6" style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}>
              <h2 className="text-3xl font-bold flex items-center gap-3" style={{ fontFamily: 'Cormorant Garamond', color: '#171412' }}>
                <AlertCircle size={32} style={{ color: '#B85C38' }} />
                Send Campaign
              </h2>
            </div>

            <div className="p-6 space-y-4">
              <div>
                <p className="text-sm font-semibold mb-2" style={{ color: '#57504A', fontFamily: 'Manrope' }}>
                  Campaign Name
                </p>
                <p className="text-lg" style={{ color: '#171412', fontFamily: 'Manrope' }}>
                  {sendConfirmation.name}
                </p>
              </div>

              <div>
                <p className="text-sm font-semibold mb-2" style={{ color: '#57504A', fontFamily: 'Manrope' }}>
                  Message
                </p>
                <div className="p-4 rounded" style={{ backgroundColor: 'var(--flc-paper2, #F5F4F1)' }}>
                  <p style={{ color: '#171412', fontFamily: 'Manrope' }}>
                    {sendConfirmation.message}
                  </p>
                </div>
              </div>

              <div className="p-4 rounded border" style={{ borderColor: '#E3A869', backgroundColor: 'var(--flc-paper2, #F5F4F1)' }}>
                <p className="font-semibold" style={{ color: '#171412', fontFamily: 'Manrope' }}>
                  This will be sent to <span style={{ color: '#B85C38' }}>{sendConfirmation.targeted_count || sendConfirmation.targetedCount || 0}</span> customers
                </p>
              </div>
            </div>

            <div className="border-t p-6 flex justify-end gap-3" style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}>
              <button
                onClick={() => setSendConfirmation(null)}
                className="px-6 py-2 rounded-lg font-semibold border transition"
                style={{ borderColor: 'var(--flc-line, #E9E5E0)', color: '#57504A' }}
              >
                Cancel
              </button>
              <button
                onClick={confirmSendCampaign}
                className="flex items-center gap-2 px-6 py-2 rounded-lg font-semibold text-white transition"
                style={{ backgroundColor: '#B85C38' }}
              >
                <Send size={18} />
                Confirm Send
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tracking Details Drawer */}
      {viewingTrackingId && trackingData && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-2xl w-full max-h-screen overflow-y-auto" style={{ backgroundColor: 'var(--flc-card, #FAFAF8)' }}>
            <div className="border-b p-6" style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}>
              <div className="flex items-center justify-between">
                <h2 className="text-3xl font-bold" style={{ fontFamily: 'Cormorant Garamond', color: '#171412' }}>
                  Campaign Tracking
                </h2>
                <button
                  onClick={() => {
                    setViewingTrackingId(null);
                    setTrackingData(null);
                  }}
                  className="text-[#8D857D] hover:text-[#171412] text-2xl"
                >
                  ×
                </button>
              </div>
            </div>

            <div className="p-6 space-y-6">
              {/* Tracking Summary — both raw count AND percentage so the
                  numbers always tell the full story. The opens/visits totals
                  are derived server-side from the per-recipient state, so
                  whatever the recipients list shows is exactly what these
                  tiles aggregate to (no more drift). */}
              {(() => {
                const targeted = trackingData.targeted_count || 0;
                const delivered = trackingData.delivered_count || 0;
                const opens = trackingData.opens_unique ?? trackingData.opens_after_count ?? 0;
                const visits = trackingData.visits_from_campaign ?? trackingData.visits_after_count ?? 0;
                const denom = delivered || (trackingData.recipients?.length || 0);
                const openPct = denom > 0 ? Math.round((opens / denom) * 100) : 0;
                const visitPct = denom > 0 ? Math.round((visits / denom) * 100) : 0;
                return (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <div className="p-3 rounded" style={{ backgroundColor: 'var(--flc-paper2, #F5F4F1)' }}>
                      <p className="text-xs text-[#8D857D]" style={{ fontFamily: 'Manrope' }}>Sent to</p>
                      <p className="text-2xl font-bold text-[#171412]">{targeted}</p>
                      <p className="text-[10px] text-[#8D857D] mt-0.5">recipients targeted</p>
                    </div>
                    <div className="p-3 rounded" style={{ backgroundColor: 'var(--flc-paper2, #F5F4F1)' }}>
                      <p className="text-xs text-[#8D857D]" style={{ fontFamily: 'Manrope' }}>Delivered</p>
                      <p className="text-2xl font-bold text-[#171412]">{delivered}</p>
                      <p className="text-[10px] text-[#8D857D] mt-0.5">
                        {targeted > 0 ? `${Math.round((delivered / targeted) * 100)}% of targeted` : '—'}
                      </p>
                    </div>
                    <div className="p-3 rounded" style={{ backgroundColor: 'var(--flc-paper2, #F5F4F1)' }}>
                      <p className="text-xs text-[#8D857D]" style={{ fontFamily: 'Manrope' }}>Opened</p>
                      <p className="text-2xl font-bold text-[#171412]">
                        {opens}<span className="text-base text-[#8D857D] font-normal"> / {denom}</span>
                      </p>
                      <p className="text-[10px] text-[#4A5D23] mt-0.5 font-semibold">{openPct}% open rate</p>
                    </div>
                    <div className="p-3 rounded" style={{ backgroundColor: 'var(--flc-paper2, #F5F4F1)' }}>
                      <p className="text-xs text-[#8D857D]" style={{ fontFamily: 'Manrope' }}>Visits after (15d)</p>
                      <p className="text-2xl font-bold text-[#171412]">
                        {visits}<span className="text-base text-[#8D857D] font-normal"> / {denom}</span>
                      </p>
                      <p className="text-[10px] text-[#B85C38] mt-0.5 font-semibold">{visitPct}% conversion</p>
                    </div>
                  </div>
                );
              })()}

              {/* Recipients List */}
              <div>
                <h3 className="text-xl font-bold mb-3" style={{ fontFamily: 'Cormorant Garamond', color: '#171412' }}>
                  Recipients
                </h3>
                <div className="space-y-2 max-h-96 overflow-y-auto">
                  {(trackingData.recipients || []).map((recipient, idx) => (
                    <div key={idx} className="p-3 rounded flex items-center justify-between" style={{ backgroundColor: 'var(--flc-paper2, #F5F4F1)' }}>
                      <div>
                        <p className="font-semibold text-[#171412]">{recipient.customer_name || 'Unknown'}</p>
                        <p className="text-xs text-[#8D857D]">{recipient.email}</p>
                      </div>
                      <div className="flex items-center gap-4">
                        <span className="flex items-center gap-1 text-sm">
                          {recipient.opened ? <CheckCircle2 size={16} style={{ color: '#4A5D23' }} /> : <AlertCircle size={16} style={{ color: '#8D857D' }} />}
                          <span style={{ color: recipient.opened ? '#4A5D23' : '#8D857D' }}>{recipient.opened ? 'Opened' : 'Not opened'}</span>
                        </span>
                        <span className="flex items-center gap-1 text-sm">
                          {recipient.visited ? <CheckCircle2 size={16} style={{ color: '#4A5D23' }} /> : <AlertCircle size={16} style={{ color: '#8D857D' }} />}
                          <span style={{ color: recipient.visited ? '#4A5D23' : '#8D857D' }}>{recipient.visited ? 'Visited' : 'No visit'}</span>
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Toolbar */}
              <div className="pt-4 border-t flex gap-3" style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}>
                <button
                  className="flex-1 px-4 py-2 rounded-lg border font-semibold transition"
                  style={{ borderColor: '#B85C38', color: '#B85C38' }}
                  onClick={() => alert('Follow-up to non-openers feature would be implemented here')}
                >
                  Follow-up to non-openers
                </button>
                <button
                  className="flex-1 px-4 py-2 rounded-lg border font-semibold transition"
                  style={{ borderColor: '#B85C38', color: '#B85C38' }}
                  onClick={() => alert('Follow-up to non-visitors feature would be implemented here')}
                >
                  Follow-up to non-visitors
                </button>
              </div>
            </div>

            <div className="border-t p-6" style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}>
              <button
                onClick={() => {
                  setViewingTrackingId(null);
                  setTrackingData(null);
                }}
                className="w-full px-6 py-2 rounded-lg font-semibold text-white transition"
                style={{ backgroundColor: '#B85C38' }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * CardOverlayPanel — push a per-customer middle-band overlay to a filtered
 * segment. The overlay replaces the global card's promotional band on each
 * matching customer's wallet for the configured expiry window. Optionally
 * fires a web-push so the customers see the offer arrive.
 *
 * UI is intentionally compact — collapsible panel matching the Quick Send
 * look-and-feel directly above it.
 */
function CardOverlayPanel() {
  const [open, setOpen] = useState(false);
  const [activeCount, setActiveCount] = useState(null);
  // Targeting filters — same vocabulary as Quick Send
  const [tier, setTier] = useState('');
  const [minVisits, setMinVisits] = useState('');
  const [minAmount, setMinAmount] = useState('');
  const [inactiveMin, setInactiveMin] = useState('');
  const [inactiveMax, setInactiveMax] = useState('');
  // Overlay fields
  const [stripTitle, setStripTitle] = useState('Offre exclusive');
  const [stripSubtitle, setStripSubtitle] = useState('Réservée à votre profil');
  const [stripColor, setStripColor] = useState('#171412');
  const [stripTextColor, setStripTextColor] = useState('#F4D8A8');
  const [offerText, setOfferText] = useState('-30%');
  const [offerSubtext, setOfferSubtext] = useState('Sur tout le magasin');
  const [expiresDays, setExpiresDays] = useState(14);
  const [sendPush, setSendPush] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState('');

  useEffect(() => {
    let alive = true;
    ownerAPI.getActiveCardOverrideCount?.()
      .then((r) => { if (alive) setActiveCount(r?.data?.active_count ?? 0); })
      .catch(() => { /* silent */ });
    return () => { alive = false; };
  }, []);

  const send = async () => {
    setBusy(true); setErr(''); setResult(null);
    try {
      const filters = {};
      if (tier) filters.tier = tier;
      if (minVisits) filters.min_visits = Number(minVisits);
      if (minAmount) filters.min_amount_paid = Number(minAmount);
      if (inactiveMin) filters.inactive_days_min = Number(inactiveMin);
      if (inactiveMax) filters.inactive_days_max = Number(inactiveMax);
      const payload = {
        filters,
        override: {
          strip_title: stripTitle || undefined,
          strip_subtitle: stripSubtitle || undefined,
          strip_color: stripColor || undefined,
          strip_text_color: stripTextColor || undefined,
          show_offer_box: !!offerText,
          offer_box_text: offerText || undefined,
          offer_box_subtext: offerSubtext || undefined,
        },
        expires_in_days: Number(expiresDays) || 14,
        send_push: sendPush,
      };
      const r = await ownerAPI.pushCardOverride(payload);
      setResult(r?.data || null);
      // Refresh the active counter
      ownerAPI.getActiveCardOverrideCount?.()
        .then((rr) => setActiveCount(rr?.data?.active_count ?? 0));
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || 'Échec de l\'envoi');
    } finally {
      setBusy(false);
    }
  };

  const clearAll = async () => {
    if (!window.confirm('Effacer tous les overlays actifs ? Les cartes reviendront au design global.')) return;
    setBusy(true);
    try {
      await ownerAPI.clearAllCardOverrides();
      setActiveCount(0);
    } finally { setBusy(false); }
  };

  return (
    <div className="mb-6 rounded-lg border" style={{ borderColor: 'var(--flc-line, #E9E5E0)', backgroundColor: 'var(--flc-card, #FAFAF8)' }}>
      <button onClick={() => setOpen((v) => !v)} className="w-full flex items-center justify-between p-4 hover:bg-[#F5F4F1] transition rounded-lg">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-[#96431F]/10 flex items-center justify-center">
            <Sparkles size={20} style={{ color: '#96431F' }} />
          </div>
          <div className="text-left">
            <p className="text-sm font-bold" style={{ color: '#171412' }}>
              Push offer over the card — filtered overlay
            </p>
            <p className="text-xs" style={{ color: '#8D857D' }}>
              Replace the middle band of the wallet card for a specific customer segment, then auto-expire.
              {activeCount > 0 && <span className="ml-2 text-[#96431F] font-semibold">· {activeCount} actifs</span>}
            </p>
          </div>
        </div>
        <ChevronDown size={18} className={`transition-transform ${open ? 'rotate-180' : ''}`} style={{ color: '#8D857D' }} />
      </button>

      {open && (
        <div className="p-4 border-t space-y-4" style={{ borderColor: 'var(--flc-line, #E9E5E0)' }}>
          {/* Targeting */}
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-[#96431F] mb-2">1. Cible (filtres)</p>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
              <select value={tier} onChange={(e) => setTier(e.target.value)}
                      className="px-3 py-2 rounded-lg border border-[#E9E5E0] text-sm">
                <option value="">Tous palliers</option>
                <option value="bronze">Bronze</option>
                <option value="silver">Silver</option>
                <option value="gold">Gold</option>
                <option value="vip">VIP</option>
              </select>
              <input type="number" min="0" placeholder="Min visites" value={minVisits}
                     onChange={(e) => setMinVisits(e.target.value)}
                     className="px-3 py-2 rounded-lg border border-[#E9E5E0] text-sm" />
              <DecimalInput placeholder="Min € payés" value={minAmount}
                     onChange={setMinAmount}
                     className="px-3 py-2 rounded-lg border border-[#E9E5E0] text-sm" />
              <input type="number" min="0" placeholder="Inactifs depuis (j)" value={inactiveMin}
                     onChange={(e) => setInactiveMin(e.target.value)}
                     className="px-3 py-2 rounded-lg border border-[#E9E5E0] text-sm" />
              <input type="number" min="0" placeholder="Inactifs jusqu'à (j)" value={inactiveMax}
                     onChange={(e) => setInactiveMax(e.target.value)}
                     className="px-3 py-2 rounded-lg border border-[#E9E5E0] text-sm" />
            </div>
          </div>

          {/* Overlay content */}
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-[#96431F] mb-2">2. Bande promo qui apparaîtra sur leur carte</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-2">
              <input type="text" placeholder="Titre de la bande" value={stripTitle}
                     onChange={(e) => setStripTitle(e.target.value)}
                     className="px-3 py-2 rounded-lg border border-[#E9E5E0] text-sm" />
              <input type="text" placeholder="Sous-titre" value={stripSubtitle}
                     onChange={(e) => setStripSubtitle(e.target.value)}
                     className="px-3 py-2 rounded-lg border border-[#E9E5E0] text-sm" />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-2">
              <input type="text" placeholder="Encart offre (ex: -30%)" value={offerText}
                     onChange={(e) => setOfferText(e.target.value)}
                     className="px-3 py-2 rounded-lg border border-[#E9E5E0] text-sm" />
              <input type="text" placeholder="Sous-texte offre" value={offerSubtext}
                     onChange={(e) => setOfferSubtext(e.target.value)}
                     className="px-3 py-2 rounded-lg border border-[#E9E5E0] text-sm" />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              <label className="text-xs flex items-center gap-2">
                Couleur fond
                <input type="color" value={stripColor} onChange={(e) => setStripColor(e.target.value)} className="w-10 h-8 rounded" />
              </label>
              <label className="text-xs flex items-center gap-2">
                Couleur texte
                <input type="color" value={stripTextColor} onChange={(e) => setStripTextColor(e.target.value)} className="w-10 h-8 rounded" />
              </label>
              <label className="text-xs flex items-center gap-2">
                Expire après (j)
                <input type="number" min="1" max="365" value={expiresDays}
                       onChange={(e) => setExpiresDays(e.target.value)}
                       className="flex-1 px-2 py-1 rounded border border-[#E9E5E0] text-sm" />
              </label>
            </div>
          </div>

          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={sendPush} onChange={(e) => setSendPush(e.target.checked)} />
            Envoyer aussi une notification push (les clients voient l'offre arriver tout de suite)
          </label>

          {/* Result + error banners */}
          {result && (
            <div className="rounded-lg bg-green-50 border border-green-200 text-green-800 px-3 py-2 text-xs">
              ✓ Overlay déposé sur <b>{result.overlaid}</b> client{result.overlaid > 1 ? 's' : ''}.
              {result.pushed > 0 && <> Push envoyé à <b>{result.pushed}</b>.</>}
              {result.skipped > 0 && <> ({result.skipped} sans push abonné)</>}
              {result.wallet_passes_updated > 0 && (
                <> Cartes Wallet mises à jour : <b>{result.wallet_passes_updated}</b>.</>
              )}
              {result.expires_at && <> Expire le {new Date(result.expires_at).toLocaleDateString('fr-FR')}.</>}
            </div>
          )}
          {err && (
            <div className="rounded-lg bg-red-50 border border-red-200 text-red-800 px-3 py-2 text-xs">{err}</div>
          )}

          <div className="flex items-center justify-between">
            <button onClick={clearAll} disabled={busy || (activeCount ?? 0) === 0}
                    className="text-xs text-[#8D857D] hover:underline disabled:opacity-40">
              Effacer tous les overlays actifs
            </button>
            <button onClick={send} disabled={busy}
                    className="px-4 py-2 rounded-full text-sm font-semibold text-white shadow disabled:opacity-50"
                    style={{ background: 'linear-gradient(135deg, #96431F 0%, #5C3E66 100%)' }}>
              {busy ? 'Envoi…' : 'Pousser l\'offre sur les cartes'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
