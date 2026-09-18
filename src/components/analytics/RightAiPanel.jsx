/**
 * RightAiPanel — sticky right rail matching the V2 mockup.
 *
 *  ┌─ AI Copilot card (purple glow) ─────────────┐
 *  │ AI Copilot   [BETA]                          │
 *  │ Score de croissance                          │
 *  │ ●──────────   82  /100                       │
 *  │ Excellent                                     │
 *  │ ↑ 12 pts vs mois précédent                    │
 *  │ [ Voir le diagnostic complet ]                │
 *  └──────────────────────────────────────────────┘
 *  ┌─ Insights IA ────────────────────────────────┐
 *  │ ✦  N insight rows                             │
 *  │ Voir tous les insights →                      │
 *  └──────────────────────────────────────────────┘
 *  ┌─ Actions rapides ────────────────────────────┐
 *  │ Créer une campagne          ↗                 │
 *  │ Segmenter des clients       ↗                 │
 *  │ Exporter un rapport         ↗                 │
 *  │ Activer le mode auto        ↗                 │
 *  └──────────────────────────────────────────────┘
 *  ┌─ Assistant IA ───────────────────────────────┐
 *  │ Posez une question sur vos données…     ↗     │
 *  └──────────────────────────────────────────────┘
 */
import React from 'react';
import { Sparkles, ChevronRight, MessageSquarePlus, Users, Download, Zap, ArrowUpRight } from 'lucide-react';
import ScoreWidget from './ScoreWidget';

const Card = ({ children, glow = false, style = {} }) => (
  <div
    className={`av2-card${glow ? ' av2-glow' : ''}`}
    style={{ padding: 14, ...style }}
  >
    {children}
  </div>
);

const SectionTitle = ({ children, action }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
    <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--flc-ink, #191410)' }}>{children}</span>
    {action}
  </div>
);

const InsightItem = ({ text, cta, onClick }) => (
  <div style={{ display: 'flex', gap: 10, padding: '10px 0', borderTop: '1px solid var(--flc-line, #E6EAF2)' }}>
    <div
      aria-hidden="true"
      style={{
        flexShrink: 0, width: 26, height: 26, borderRadius: 8,
        background: 'color-mix(in srgb, var(--flc-accent, #C73E2C) 15%, transparent)',
        display: 'grid', placeItems: 'center',
        color: 'var(--flc-accent-deep, #A82843)',
      }}
    >
      <Sparkles size={13} />
    </div>
    <div style={{ minWidth: 0, fontSize: 11.5, lineHeight: 1.45 }}>
      <div style={{ color: 'var(--flc-ink2, #3A332B)' }}>{text}</div>
      {cta && (
        <button
          type="button"
          onClick={onClick}
          style={{
            background: 'transparent', border: '1px solid var(--flc-line, #ECE3D2)',
            borderRadius: 8, padding: '4px 9px', marginTop: 6, cursor: 'pointer',
            color: 'var(--flc-ink, #191410)', font: 'inherit', fontSize: 11, fontWeight: 500,
            transition: 'background 150ms ease',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = 'color-mix(in srgb, var(--flc-accent, #C73E2C) 8%, transparent)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
        >
          {cta}
        </button>
      )}
    </div>
  </div>
);

const QuickAction = ({ icon: Icon, label, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    style={{
      display: 'flex', alignItems: 'center', gap: 10,
      width: '100%', textAlign: 'left',
      padding: '9px 10px',
      background: 'transparent', border: 'none', cursor: 'pointer',
      color: 'var(--flc-ink2, #3A332B)', font: 'inherit', fontSize: 12,
      borderRadius: 8,
      transition: 'background 150ms ease, color 150ms ease',
    }}
    onMouseEnter={(e) => {
      e.currentTarget.style.background = 'color-mix(in srgb, var(--flc-accent, #C73E2C) 8%, transparent)';
      e.currentTarget.style.color = 'var(--flc-ink, #191410)';
    }}
    onMouseLeave={(e) => {
      e.currentTarget.style.background = 'transparent';
      e.currentTarget.style.color = 'var(--flc-ink2, #3A332B)';
    }}
  >
    <Icon size={14} aria-hidden="true" style={{ color: 'var(--flc-accent-deep, #A82843)', flexShrink: 0 }} />
    <span style={{ flex: 1 }}>{label}</span>
    <ChevronRight size={14} aria-hidden="true" style={{ color: 'var(--flc-ink3, #524A40)', flexShrink: 0 }} />
  </button>
);

const scoreLabel = (n) => {
  if (n >= 80) return 'Excellent';
  if (n >= 60) return 'Bon';
  if (n >= 40) return 'Moyen';
  if (n > 0)   return 'À améliorer';
  return '—';
};

const RightAiPanel = ({
  score = 82,
  scoreDelta = 12,
  insights = [],
  onDiagnostic,
  onAction,
  onAssistantSubmit,
  onAllInsights,
}) => {
  const [draft, setDraft] = React.useState('');

  const handleAssistant = (e) => {
    e?.preventDefault?.();
    const text = (draft || '').trim();
    if (!text) return;
    if (onAssistantSubmit) onAssistantSubmit(text);
    setDraft('');
  };

  return (
    <>
      {/* AI Copilot — score + diagnostic CTA */}
      <Card glow>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 500, color: 'var(--flc-ink, #191410)' }}>
            <Sparkles size={14} aria-hidden="true" style={{ color: 'var(--flc-accent-deep, #A82843)' }} />
            AI Copilot
          </span>
          <span
            style={{
              fontSize: 9, fontWeight: 700, letterSpacing: '0.1em',
              color: 'var(--flc-accent-deep, #A82843)',
              background: 'color-mix(in srgb, var(--flc-accent, #C73E2C) 15%, transparent)',
              border: '1px solid color-mix(in srgb, var(--flc-accent, #C73E2C) 35%, transparent)',
              padding: '2px 6px', borderRadius: 99,
            }}
          >
            BETA
          </span>
        </div>
        <div style={{ fontSize: 11, color: 'var(--flc-ink3, #524A40)', marginBottom: 8 }}>
          Score de croissance
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          <ScoreWidget score={score} delta={null} denominator="100" />
        </div>
        <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--flc-ok, #0F8B58)', marginBottom: 4 }}>
          {scoreLabel(score)}
        </div>
        {scoreDelta != null && isFinite(scoreDelta) && (
          <div style={{ fontSize: 11, color: 'var(--flc-ink2, #3A332B)', marginBottom: 10 }}>
            <span style={{ color: scoreDelta >= 0 ? 'var(--flc-ok, #0F8B58)' : 'var(--flc-risk, #C22F45)' }}>
              {scoreDelta >= 0 ? '↑' : '↓'} {Math.abs(scoreDelta)} pts
            </span>{' '}
            vs mois précédent
          </div>
        )}
        <button
          type="button"
          onClick={onDiagnostic}
          style={{
            width: '100%', padding: '8px 12px',
            background: 'var(--flc-card, #FFFFFF)',
            border: '1px solid var(--flc-line, #ECE3D2)',
            borderRadius: 9,
            color: 'var(--flc-ink, #191410)', cursor: 'pointer',
            font: 'inherit', fontSize: 12, fontWeight: 500,
            transition: 'background 150ms ease',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = 'color-mix(in srgb, var(--flc-accent, #C73E2C) 10%, transparent)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--flc-card, #FFFFFF)'; }}
        >
          Voir le diagnostic complet
        </button>
      </Card>

      {/* Insights IA */}
      <Card>
        <SectionTitle
          action={
            <button
              type="button"
              onClick={onAllInsights}
              style={{
                background: 'transparent', border: 'none', cursor: 'pointer',
                color: 'var(--flc-accent-deep, #A82843)', font: 'inherit', fontSize: 11, fontWeight: 500,
                padding: 0,
              }}
            >
              Voir tous →
            </button>
          }
        >
          Insights IA
        </SectionTitle>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {insights.length === 0 ? (
            <div style={{ fontSize: 11.5, color: 'var(--flc-ink3, #524A40)', padding: '8px 0' }}>
              Aucun insight pour cette période.
            </div>
          ) : insights.map((it, i) => (
            <InsightItem
              key={i}
              text={it.text}
              cta={it.cta}
              onClick={it.onClick}
            />
          ))}
        </div>
      </Card>

      {/* Actions rapides */}
      <Card>
        <SectionTitle>Actions rapides</SectionTitle>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <QuickAction icon={MessageSquarePlus} label="Créer une campagne"     onClick={() => onAction?.('new-campaign')} />
          <QuickAction icon={Users}              label="Segmenter des clients" onClick={() => onAction?.('segment-customers')} />
          <QuickAction icon={Download}           label="Exporter un rapport"   onClick={() => onAction?.('export-report')} />
          <QuickAction icon={Zap}                label="Activer le mode auto"  onClick={() => onAction?.('auto-mode')} />
        </div>
      </Card>

      {/* Assistant IA */}
      <Card>
        <SectionTitle>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <Sparkles size={13} aria-hidden="true" style={{ color: 'var(--flc-accent-deep, #A82843)' }} />
            Assistant IA
          </span>
        </SectionTitle>
        <form onSubmit={handleAssistant}>
          <label htmlFor="av2-assistant-input" style={{ position: 'absolute', left: -10000 }}>
            Question à l'assistant
          </label>
          <div
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '9px 11px',
              background: 'var(--flc-card, #FFFFFF)',
              border: '1px solid var(--flc-line, #ECE3D2)',
              borderRadius: 9,
            }}
          >
            <input
              id="av2-assistant-input"
              type="text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Posez une question sur vos données…"
              style={{
                flex: 1, minWidth: 0,
                background: 'transparent', border: 'none', outline: 'none',
                color: 'var(--flc-ink, #191410)', font: 'inherit', fontSize: 11.5,
              }}
            />
            <button
              type="submit"
              aria-label="Envoyer la question"
              style={{
                background: 'transparent', border: 'none', cursor: 'pointer',
                color: 'var(--flc-accent-deep, #A82843)', padding: 0,
                display: 'grid', placeItems: 'center',
              }}
            >
              <ArrowUpRight size={14} aria-hidden="true" />
            </button>
          </div>
        </form>
      </Card>
    </>
  );
};

export default RightAiPanel;
