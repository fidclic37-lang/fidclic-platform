import React, { useEffect, useState } from 'react';
import { Sparkles, ArrowRight, X } from 'lucide-react';
import { ownerAPI } from '../lib/api';

/**
 * AiRecommendationBanner — the "notre recommandation IA pour vous" panel that
 * lives at the bottom of the Analytics page in the premium reference design.
 *
 * Pulls the top proactive alert from /owner/insights/alerts and turns it
 * into a one-line recommendation + a CTA. If the alert has a campaign
 * suggestion, the CTA opens the composer pre-filled. Otherwise it links to
 * the relevant settings section.
 *
 * Quiet by default — if there's no alert worth surfacing, the banner
 * renders nothing instead of a cheerful "nothing to do" empty state. The
 * point is "I am useful when I appear" — not background noise.
 *
 * Props:
 *   - onOpenComposer?: ({ segment, presetName, presetContent }) => void
 *                      — called when the CTA is "lancer une campagne".
 */
export default function AiRecommendationBanner({ onOpenComposer }) {
  const [alert, setAlert] = useState(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    let cancelled = false;
    ownerAPI.getProactiveAlerts?.()
      .then((r) => {
        if (cancelled) return;
        const list = Array.isArray(r?.data?.alerts) ? r.data.alerts : (Array.isArray(r?.data) ? r.data : []);
        // Pick the highest-priority alert that has a meaningful CTA.
        const top = list.find((a) => a?.recommendation || a?.suggested_campaign || a?.estimated_lift) || list[0];
        if (top) setAlert(top);
      })
      .catch(() => { /* silent — banner just stays hidden */ });
    return () => { cancelled = true; };
  }, []);

  if (hidden || !alert) return null;

  const title = alert.title || alert.recommendation || 'Recommandation IA';
  const body = alert.message || alert.body || alert.subtitle || '';
  const lift = alert.estimated_lift || alert.expected_lift;
  const suggestedCampaign = alert.suggested_campaign || null;

  const onCta = () => {
    if (suggestedCampaign && onOpenComposer) {
      onOpenComposer({
        segment: suggestedCampaign.segment || { type: 'all' },
        presetName: suggestedCampaign.name || title,
        presetContent: suggestedCampaign.content || body,
      });
    } else if (alert.cta_url) {
      window.location.href = alert.cta_url;
    }
  };

  return (
    <div
      className="relative rounded-2xl p-5 sm:p-6 mb-6 flex flex-col sm:flex-row items-start sm:items-center gap-4"
      style={{
        background: 'linear-gradient(135deg, #EAF0FF 0%, #F3F6FF 100%)',
        border: '1px solid #C7D7FF',
      }}
    >
      <button
        type="button"
        onClick={() => setHidden(true)}
        aria-label="Masquer"
        className="absolute top-3 right-3 text-[#1D4ED8] hover:text-[#0F172A] p-1"
      >
        <X size={14} />
      </button>

      <div
        className="shrink-0 w-12 h-12 rounded-xl flex items-center justify-center"
        style={{ background: '#2F6BFF', color: '#FFFFFF' }}
      >
        <Sparkles size={22} />
      </div>

      <div className="flex-1 min-w-0">
        <p
          className="text-[11px] font-bold uppercase tracking-[0.18em] mb-1"
          style={{ color: '#1D4ED8' }}
        >
          Notre recommandation IA pour vous
        </p>
        <p
          className="text-base sm:text-lg leading-snug"
          style={{
            color: '#0F172A',
            fontFamily: "'Cormorant Garamond', Georgia, serif",
            fontWeight: 600,
            letterSpacing: '-0.01em',
          }}
        >
          {title}
        </p>
        {body && (
          <p className="text-sm mt-1 leading-relaxed" style={{ color: '#334155' }}>
            {body}
            {lift && (
              <span
                className="ml-2 inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold"
                style={{ background: '#2F6BFF', color: '#FFFFFF' }}
              >
                {lift}
              </span>
            )}
          </p>
        )}
      </div>

      <div className="flex flex-col sm:flex-row gap-2 sm:items-center w-full sm:w-auto shrink-0">
        {alert.secondary_cta_label && alert.secondary_cta_url && (
          <a
            href={alert.secondary_cta_url}
            className="px-4 py-2 rounded-lg text-sm font-medium hover:bg-white/60 transition-colors"
            style={{ color: '#1D4ED8' }}
          >
            {alert.secondary_cta_label}
          </a>
        )}
        <button
          type="button"
          onClick={onCta}
          className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-colors"
          style={{ background: '#2F6BFF', color: '#FFFFFF' }}
        >
          {alert.cta_label || (suggestedCampaign ? 'Lancer la campagne' : 'Voir les suggestions')}
          <ArrowRight size={14} />
        </button>
      </div>
    </div>
  );
}
