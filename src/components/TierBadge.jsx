import React from 'react';
import { Crown } from 'lucide-react';

/**
 * Tier badge with color + crown icon.
 * Usage: <TierBadge tier="gold" />  or  <TierBadge tier="silver" size="sm" />
 */
const TIER_STYLES = {
  bronze: {
    bg: 'linear-gradient(135deg, #B85C38 0%, #8C3E22 100%)',
    border: '#8C3E22',
    text: '#FFFFFF',
    crown: '#FFE1B8',
    label: 'Bronze',
  },
  silver: {
    bg: 'linear-gradient(135deg, #D9D9D9 0%, #A8A8A8 100%)',
    border: '#888888',
    text: '#171412',
    crown: '#6B6B6B',
    label: 'Silver',
  },
  gold: {
    bg: 'linear-gradient(135deg, #F5D97A 0%, #D4A574 100%)',
    border: '#B8852C',
    text: '#171412',
    crown: '#8C5C15',
    label: 'Gold',
  },
  vip: {
    // Deep burgundy → black gradient — clearly "above" gold.
    bg: 'linear-gradient(135deg, #96431F 0%, #171412 100%)',
    border: '#171412',
    text: '#F5D97A',
    crown: '#F5D97A',
    label: 'VIP',
  },
};

export default function TierBadge({ tier = 'bronze', size = 'md', showLabel = true }) {
  const key = String(tier || 'bronze').toLowerCase();
  const style = TIER_STYLES[key] || TIER_STYLES.bronze;

  const sizeMap = {
    xs: { pad: '2px 6px', font: '10px', iconSize: 10 },
    sm: { pad: '3px 8px', font: '11px', iconSize: 11 },
    md: { pad: '4px 10px', font: '12px', iconSize: 13 },
    lg: { pad: '6px 14px', font: '14px', iconSize: 16 },
  };
  const sz = sizeMap[size] || sizeMap.md;

  return (
    <span
      className="tier-badge"
      data-tier={key}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        padding: sz.pad,
        background: style.bg,
        border: `1px solid ${style.border}`,
        color: style.text,
        borderRadius: '999px',
        fontSize: sz.font,
        fontFamily: 'Manrope',
        fontWeight: 600,
        textTransform: 'capitalize',
        letterSpacing: '0.02em',
        boxShadow: '0 1px 2px rgba(0,0,0,0.08)',
        whiteSpace: 'nowrap',
      }}
    >
      <Crown size={sz.iconSize} style={{ color: style.crown, fill: style.crown }} strokeWidth={2} />
      {showLabel && <span>{style.label}</span>}
    </span>
  );
}
