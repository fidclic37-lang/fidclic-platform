import React, { useEffect, useState } from 'react';
import { Coins, ShieldCheck } from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { C } from './PageShell';
import DecimalInput from './DecimalInput';

/**
 * PointsRuleCard — owner control for the points-per-euro rule.
 *
 * Backed by /owner/card-template (CardTemplate.points_per_euro).
 * The Scan page reads this same field on load so the cashier always
 * sees the current rate.
 */
const PointsRuleCard = ({ id }) => {
  const [tpl, setTpl] = useState(null);
  const [mode, setMode] = useState('per_visit');  // 'per_visit' | 'per_euro'
  const [rate, setRate] = useState(10);
  const [perVisit, setPerVisit] = useState(10);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const r = await ownerAPI.getCardTemplate();
        setTpl(r.data || {});
        setMode((r.data?.points_mode || 'per_visit').toLowerCase());
        setRate(Number(r.data?.points_per_euro ?? 10));
        setPerVisit(Number(r.data?.points_per_visit ?? 10));
      } catch (e) {
        setError(e?.response?.data?.detail || e.message || 'Chargement échoué');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const save = async () => {
    setSaving(true);
    setError('');
    setSaved(false);
    try {
      const next = {
        ...(tpl || {}),
        points_mode: mode,
        points_per_euro: Number(rate) || 0,
        points_per_visit: Number(perVisit) || 0,
      };
      await ownerAPI.saveCardTemplate(next);
      setTpl(next);
      setSaved(true);
      setTimeout(() => setSaved(false), 2400);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Échec de la sauvegarde');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <section
        className="rounded-2xl p-6"
        style={{ background: 'var(--flc-card, #FFFFFF)', border: `1px solid ${C.hairline}` }}
      >
        <p className="text-sm" style={{ color: C.inkMute }}>Chargement de la règle de points…</p>
      </section>
    );
  }

  return (
    <section
      id={id}
      className="rounded-2xl p-6 space-y-4"
      style={{
        background: 'var(--flc-card, #FFFFFF)',
        border: `1px solid ${C.hairline}`,
        boxShadow: '0 1px 2px rgba(28,25,23,0.04)',
      }}
    >
      <header className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-2xl font-semibold flex items-center gap-2"
              style={{ fontFamily: 'Cormorant Garamond', color: C.inkDeep }}>
            <Coins size={20} style={{ color: C.terracotta }} /> Règle de points
          </h2>
          <p className="text-sm mt-1" style={{ color: C.inkMute }}>
            Décidez combien de points le client gagne pour chaque euro dépensé.
            La page de scan utilise ce taux automatiquement.
          </p>
        </div>
      </header>

      {/* Mode toggle — owner picks how points are awarded */}
      <div>
        <p className="text-xs font-bold uppercase tracking-wider mb-2" style={{ color: C.inkMute }}>
          Comment attribuer les points ?
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => setMode('per_visit')}
            className="text-left p-3 rounded-xl transition"
            style={{
              background: mode === 'per_visit' ? 'color-mix(in srgb, var(--flc-accent, #C73E2C) 12%, var(--flc-card, #FFFFFF))' : 'var(--flc-card, #FFFFFF)',
              border: `2px solid ${mode === 'per_visit' ? C.terracotta : C.hairline}`,
            }}
          >
            <p className="text-sm font-bold" style={{ color: C.inkDeep }}>
              📌 Forfait par visite
            </p>
            <p className="text-xs mt-1" style={{ color: C.inkMute }}>
              Toujours <b>{perVisit || 0}</b> points par scan, peu importe le montant.
              Simple et prévisible.
            </p>
          </button>
          <button
            type="button"
            onClick={() => setMode('per_euro')}
            className="text-left p-3 rounded-xl transition"
            style={{
              background: mode === 'per_euro' ? 'color-mix(in srgb, var(--flc-accent, #C73E2C) 12%, var(--flc-card, #FFFFFF))' : 'var(--flc-card, #FFFFFF)',
              border: `2px solid ${mode === 'per_euro' ? C.terracotta : C.hairline}`,
            }}
          >
            <p className="text-sm font-bold" style={{ color: C.inkDeep }}>
              💶 Selon le montant dépensé
            </p>
            <p className="text-xs mt-1" style={{ color: C.inkMute }}>
              <b>{rate || 0}</b> points par euro. Récompense les gros paniers.
            </p>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Points per euro */}
        <label className={'block ' + (mode === 'per_euro' ? '' : 'opacity-50')}>
          <span className="text-xs font-bold uppercase tracking-wider" style={{ color: C.inkMute }}>
            Points par euro dépensé {mode === 'per_euro' ? '(actif)' : '(inactif)'}
          </span>
          <div className="flex items-center gap-2 mt-1">
            <DecimalInput
              value={rate}
              onChange={setRate}
              className="w-32 px-3 py-2 rounded-lg border text-base font-bold"
              style={{ borderColor: C.hairline, color: C.inkDeep }}
            />
            <span className="text-sm" style={{ color: C.inkMute }}>points / €</span>
          </div>
          <p className="text-[11px] mt-1.5" style={{ color: C.inkMute }}>
            Exemple : à <b>{rate || 0}</b> points/€, un café à 4,50 € donne{' '}
            <b style={{ color: C.terracotta }}>{Math.floor(4.5 * (Number(rate) || 0))} points</b>.
          </p>
        </label>

        {/* Points per visit */}
        <label className={'block ' + (mode === 'per_visit' ? '' : 'opacity-50')}>
          <span className="text-xs font-bold uppercase tracking-wider" style={{ color: C.inkMute }}>
            Points par visite {mode === 'per_visit' ? '(actif)' : '(de secours)'}
          </span>
          <div className="flex items-center gap-2 mt-1">
            <input
              type="number"
              min="0"
              value={perVisit}
              onChange={(e) => setPerVisit(e.target.value)}
              className="w-32 px-3 py-2 rounded-lg border text-base font-bold"
              style={{ borderColor: C.hairline, color: C.inkDeep }}
            />
            <span className="text-sm" style={{ color: C.inkMute }}>points / visite</span>
          </div>
          <p className="text-[11px] mt-1.5" style={{ color: C.inkMute }}>
            {mode === 'per_visit'
              ? 'Mode actif — chaque scan crédite ce nombre de points.'
              : 'Utilisé quand aucun montant n\'est saisi.'}
          </p>
        </label>
      </div>

      <div className="flex items-center gap-3 pt-2">
        <button
          onClick={save}
          disabled={saving}
          className="px-4 py-2 rounded-lg text-sm font-semibold text-white transition disabled:opacity-60"
          style={{ background: C.terracotta }}
        >
          {saving ? 'Enregistrement…' : 'Enregistrer'}
        </button>
        {saved && (
          <span className="inline-flex items-center gap-1.5 text-xs" style={{ color: C.sage }}>
            <ShieldCheck size={13} /> Enregistré — la page Scan utilise déjà le nouveau taux.
          </span>
        )}
        {error && <span className="text-xs" style={{ color: C.terracotta }}>⚠ {error}</span>}
      </div>
    </section>
  );
};

export default PointsRuleCard;
