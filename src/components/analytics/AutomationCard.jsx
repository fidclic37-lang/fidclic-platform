/**
 * AutomationCard — single automation strip card.
 *
 * Props:
 *   icon:     lucide-react component (e.g. Gift, Clock, Crown)
 *   title:    short title ("Anniversaire")
 *   subtitle: counts / status text ("23 envois ce mois")
 *   status:   'active' | 'paused' | 'draft' — drives the pill colour
 *   accent:   'purple' | 'cyan' | 'pink' | 'emerald' | 'orange' | 'amber'
 *             — drives the icon tint
 *   onClick:  optional click handler
 */
import React from 'react';

const ACCENT = {
  purple:  '#2F6BFF',
  cyan:    '#0EA5E9',
  pink:    '#EC4899',
  emerald: '#16A34A',
  orange:  '#F97316',
  amber:   '#F59E0B',
};

const STATUS_PILL = {
  active:  { fg: 'var(--flc-ok, #0F8B58)', bg: 'color-mix(in srgb, var(--flc-ok, #0F8B58) 14%, transparent)', label: 'Actif' },
  paused:  { fg: 'var(--flc-warn, #A8862D)',  bg: 'color-mix(in srgb, var(--flc-warn, #A8862D) 14%, transparent)',  label: 'Pause' },
  draft:   { fg: 'var(--flc-ink3, #524A40)', bg: 'color-mix(in srgb, var(--flc-ink3, #524A40) 20%, transparent)', label: 'Brouillon' },
};

const AutomationCard = ({
  icon: Icon,
  title,
  subtitle,
  status = 'active',
  accent = 'purple',
  onClick,
}) => {
  const tone = STATUS_PILL[status] || STATUS_PILL.active;
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag
      type={onClick ? 'button' : undefined}
      onClick={onClick}
      style={{
        background: 'var(--flc-card, #FFFFFF)',
        border: '1px solid var(--flc-line, #ECE3D2)',
        borderRadius: 14,
        padding: 12,
        textAlign: 'left',
        color: 'var(--flc-ink, #191410)',
        cursor: onClick ? 'pointer' : 'default',
        font: 'inherit',
        transition: 'transform 150ms cubic-bezier(.2,.7,.3,1), border-color 150ms ease',
      }}
      onMouseEnter={(e) => {
        if (onClick) {
          e.currentTarget.style.transform = 'translateY(-1px)';
          e.currentTarget.style.borderColor = 'var(--flc-line-hi, #D9D3CA)';
        }
      }}
      onMouseLeave={(e) => {
        if (onClick) {
          e.currentTarget.style.transform = '';
          e.currentTarget.style.borderColor = 'var(--flc-line, #ECE3D2)';
        }
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        {Icon ? (
          <Icon size={18} aria-hidden="true" style={{ color: ACCENT[accent] || ACCENT.purple }} />
        ) : <span />}
        <span
          style={{
            fontSize: 9.5, fontWeight: 500, padding: '2px 7px', borderRadius: 99,
            color: tone.fg, background: tone.bg, letterSpacing: '0.02em',
          }}
        >
          {tone.label}
        </span>
      </div>
      <div style={{ fontSize: 12, fontWeight: 500, lineHeight: 1.3 }}>{title}</div>
      {subtitle && (
        <div style={{ fontSize: 10.5, color: 'var(--flc-ink3, #524A40)', marginTop: 2 }}>{subtitle}</div>
      )}
    </Tag>
  );
};

export default AutomationCard;
