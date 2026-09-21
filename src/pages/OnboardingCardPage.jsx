import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ArrowRight, Check } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { onboardingAPI } from '../lib/api';
import OnboardingShell from '../components/OnboardingShell';

/**
 * OnboardingCardPage — step 3 of 3 ("Configuration carte").
 *
 * The lightest useful version of the card designer: pick the card colour,
 * say what the reward is and after how many stamps. Saved through the same
 * /api/owner/card-template endpoint the full designer uses, so everything
 * chosen here is editable later in Card Designer. Skippable — the trial has
 * already started at step 2, nothing here blocks the owner.
 */
const COLOURS = [
  { key: 'navy',   hex: '#0B1C3F', accent: '#F5A623' },
  { key: 'blue',   hex: '#2F6BFF', accent: '#FFD166' },
  { key: 'green',  hex: '#0F766E', accent: '#FDE68A' },
  { key: 'plum',   hex: '#6B21A8', accent: '#F9A8D4' },
  { key: 'coffee', hex: '#5C3A21', accent: '#E8C39E' },
  { key: 'black',  hex: '#111827', accent: '#D4AF37' },
];

const OnboardingCardPage = () => {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [tpl, setTpl] = useState(null);
  const [colour, setColour] = useState(COLOURS[0]);
  const [reward, setReward] = useState('');
  const [stamps, setStamps] = useState(10);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    onboardingAPI.cardTemplate().then((r) => {
      const d = r.data || {};
      setTpl(d);
      setReward(d.reward_description || '');
      setStamps(Number(d.reward_threshold_stamps) || 10);
      const found = COLOURS.find((c) => c.hex.toLowerCase() === String(d.bronze_design?.primary_color || '').toLowerCase());
      if (found) setColour(found);
    }).catch(() => setTpl({}));
  }, []);

  const finish = async (save) => {
    setError('');
    if (save) {
      if (!reward.trim()) return setError(t('card_step.reward_required'));
      setSaving(true);
      try {
        const design = (d) => ({ ...(d || {}), primary_color: colour.hex, accent_color: colour.accent, text_color: '#FFFFFF' });
        await onboardingAPI.saveCardTemplate({
          ...tpl,
          reward_description: reward.trim(),
          reward_threshold_stamps: Math.max(1, Math.min(50, Number(stamps) || 10)),
          bronze_design: design(tpl?.bronze_design),
        });
      } catch (err) {
        setSaving(false);
        return setError(err?.response?.data?.detail || err?.message || t('onboarding.failed'));
      }
    }
    navigate('/modules', { replace: true });
  };

  const shop = user?.tenant_name || 'FidClic';
  return (
    <OnboardingShell step={3}>
      <div className="mt-7 text-center">
        <h1 className="text-[30px] font-extrabold tracking-[-0.02em] text-[#0B1C3F]">{t('card_step.title')}</h1>
        <p className="mt-2 text-[15px] text-[#4B5C7A]">{t('card_step.subtitle')}</p>
      </div>
      {error && <div className="mt-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">⚠ {error}</div>}

      {/* live preview */}
      <div className="mx-auto mt-7 w-full max-w-[360px] rounded-2xl p-5 text-white shadow-[0_18px_40px_-20px_rgba(11,28,63,.6)]"
           style={{ background: `linear-gradient(135deg, ${colour.hex} 0%, ${colour.hex}CC 100%)` }}>
        <div className="flex items-center justify-between">
          <span className="text-[17px] font-extrabold tracking-wide">{shop}</span>
          <span className="text-[11px] uppercase tracking-widest opacity-80">{t('card_step.preview_label')}</span>
        </div>
        <div className="mt-6 flex items-end justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-widest opacity-80">{t('card_step.preview_points')}</div>
            <div className="text-[30px] font-extrabold leading-none">0 / {stamps || 10}</div>
          </div>
          <div className="rounded-lg bg-white p-1.5">
            <div className="h-12 w-12 rounded-sm" style={{ background: 'repeating-linear-gradient(90deg,#0B1C3F 0 3px,#fff 3px 6px), repeating-linear-gradient(0deg,#0B1C3F 0 3px,#fff 3px 6px)', backgroundBlendMode: 'multiply' }} />
          </div>
        </div>
        <div className="mt-4 text-[13px]" style={{ color: colour.accent }}>🎁 {reward.trim() || t('card_step.reward_placeholder')}</div>
      </div>

      <div className="mt-7 space-y-5">
        <div>
          <p className="mb-2 text-[14px] font-semibold text-[#0B1C3F]">{t('card_step.colour')}</p>
          <div className="flex flex-wrap gap-3">
            {COLOURS.map((c) => (
              <button key={c.key} type="button" onClick={() => setColour(c)} aria-label={c.key}
                      className={`flex h-11 w-11 items-center justify-center rounded-full ring-offset-2 transition ${colour.key === c.key ? 'ring-2 ring-[#2F6BFF]' : 'hover:scale-105'}`}
                      style={{ background: c.hex }}>
                {colour.key === c.key && <Check size={18} className="text-white" />}
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-[1fr_140px]">
          <div>
            <label className="mb-1.5 block text-[14px] font-semibold text-[#0B1C3F]">{t('card_step.reward')}</label>
            <input type="text" value={reward} onChange={(e) => setReward(e.target.value)} placeholder={t('card_step.reward_placeholder')}
                   className="w-full rounded-xl border border-[#E1E8F5] px-4 py-3 text-[15px] outline-none focus:border-[#2F6BFF] focus:ring-4 focus:ring-[#2F6BFF]/10" />
          </div>
          <div>
            <label className="mb-1.5 block text-[14px] font-semibold text-[#0B1C3F]">{t('card_step.stamps')}</label>
            <input type="number" min="1" max="50" value={stamps} onChange={(e) => setStamps(e.target.value)}
                   className="w-full rounded-xl border border-[#E1E8F5] px-4 py-3 text-[15px] outline-none focus:border-[#2F6BFF] focus:ring-4 focus:ring-[#2F6BFF]/10" />
          </div>
        </div>

        <button type="button" onClick={() => finish(true)} disabled={saving}
                className="inline-flex w-full items-center justify-center gap-3 rounded-2xl py-4 text-[17px] font-semibold text-white transition hover:-translate-y-0.5 disabled:opacity-60"
                style={{ background: '#0A6CFF', boxShadow: '0 12px 28px -12px rgba(10,108,255,.6)' }}>
          {saving ? t('auth.creating') : <>{t('card_step.finish')} <ArrowRight size={20} /></>}
        </button>
        <button type="button" onClick={() => finish(false)} className="block w-full text-center text-[14px] font-medium text-[#64748B] hover:text-[#0B1C3F]">
          {t('card_step.skip')}
        </button>
      </div>
    </OnboardingShell>
  );
};
export default OnboardingCardPage;
