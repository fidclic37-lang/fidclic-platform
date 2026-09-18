/**
 * AutomationEmpty — dashed CTA tile inviting the owner to create a new
 * automation. Lights up purple on hover.
 */
import React from 'react';
import { Plus } from 'lucide-react';

const AutomationEmpty = ({ onClick, label = 'Créer' }) => (
  <button
    type="button"
    onClick={onClick}
    aria-label={`${label} une automatisation`}
    style={{
      border: '1px dashed var(--flc-line-hi, #C9D6F2)',
      borderRadius: 14,
      padding: 12,
      background: 'transparent',
      color: 'var(--flc-ink3, #524A40)',
      cursor: 'pointer',
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      gap: 6,
      fontSize: 12,
      minHeight: 92,
      font: 'inherit',
      transition: 'border-color 180ms ease, color 180ms ease, background 180ms ease',
    }}
    onMouseEnter={(e) => {
      e.currentTarget.style.borderColor = 'color-mix(in srgb, var(--flc-accent, #C73E2C) 55%, transparent)';
      e.currentTarget.style.color = 'var(--flc-accent-deep, #A82843)';
      e.currentTarget.style.background = 'color-mix(in srgb, var(--flc-accent, #C73E2C) 5%, transparent)';
    }}
    onMouseLeave={(e) => {
      e.currentTarget.style.borderColor = 'var(--flc-line-hi, #C9D6F2)';
      e.currentTarget.style.color = 'var(--flc-ink3, #524A40)';
      e.currentTarget.style.background = 'transparent';
    }}
  >
    <Plus size={16} aria-hidden="true" />
    {label}
  </button>
);

export default AutomationEmpty;
