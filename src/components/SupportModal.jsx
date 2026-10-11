import { vh } from '../lib/fit';
/**
 * SupportModal — lets a business send a query to the FidClic
 * support team from inside their dashboard.
 *
 * UX:
 *   • Two fields: Subject (single line) + Message (textarea)
 *   • Email field auto-prefilled from the signed-in user (read-only,
 *     so support can reply directly).
 *   • Sending posts to /api/support/contact which:
 *       1. Persists the ticket to MongoDB (always)
 *       2. Forwards to the support inbox via Formsubmit.co (best-effort)
 *   • Always returns success to the user once persisted — they don't
 *     need to know about delivery internals.
 *
 * No external dependencies — uses plain fetch, no UI library.
 */
import React, { useEffect, useRef, useState } from 'react';
import { X, Send, LifeBuoy, CheckCircle2, AlertTriangle } from 'lucide-react';
import { C } from './PageShell';

const MAX_SUBJECT = 200;
const MAX_MESSAGE = 5000;

export default function SupportModal({ open, onClose, defaultEmail = '', tenantSlug = '' }) {
  const [subject, setSubject] = useState('');
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const [result,  setResult]  = useState(null); // { ok: true } | { ok: false, error: string }
  const subjectRef = useRef(null);

  // Reset state every time the modal opens.
  useEffect(() => {
    if (open) {
      setSubject('');
      setMessage('');
      setResult(null);
      setSending(false);
      // Autofocus subject after the modal mounts.
      setTimeout(() => subjectRef.current?.focus(), 50);
    }
  }, [open]);

  // ESC closes the modal.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const canSend = subject.trim().length > 0 && message.trim().length > 0 && !sending;

  const send = async () => {
    if (!canSend) return;
    setSending(true);
    setResult(null);
    try {
      const r = await fetch('/api/support/contact', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          subject:     subject.trim(),
          message:     message.trim(),
          from_email:  defaultEmail || null,
          tenant_slug: tenantSlug   || null,
        }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.detail || `HTTP ${r.status}`);
      }
      setResult({ ok: true });
    } catch (e) {
      setResult({ ok: false, error: e.message || 'Failed to send. Please try again.' });
    } finally {
      setSending(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="support-modal-title"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(28, 25, 23, 0.45)',
        backdropFilter: 'blur(2px)',
        display: 'grid', placeItems: 'center',
        padding: 16,
      }}
    >
      <div
        style={{
          background: 'var(--flc-card, #FFFFFF)',
          borderRadius: 16,
          width: 'min(560px, 100%)',
          maxHeight: `calc(${vh(100)} - 32px)`,
          overflow: 'auto',
          border: `1px solid ${C.hairline}`,
          boxShadow: '0 24px 60px -20px rgba(28, 25, 23, 0.25)',
        }}
      >
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '18px 20px 14px', borderBottom: `1px solid ${C.hairline}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 10,
              background: 'linear-gradient(135deg, rgb(184 92 56 / .15), hsl(295 50% 32% / .15))',
              color: 'hsl(285 45% 35%)',
              display: 'grid', placeItems: 'center',
            }}>
              <LifeBuoy size={18} />
            </div>
            <div>
              <h2 id="support-modal-title" style={{
                margin: 0, fontSize: 16, fontWeight: 600, color: '#171412',
              }}>
                Contact support
              </h2>
              <p style={{ margin: '2px 0 0', fontSize: 12, color: '#8D857D' }}>
                Send us a question — we reply within one business day.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            style={{
              background: 'transparent', border: 'none', cursor: 'pointer',
              color: '#57504A', padding: 6, borderRadius: 8,
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        {result?.ok ? (
          <div style={{ padding: 28, textAlign: 'center' }}>
            <div style={{
              width: 56, height: 56, borderRadius: 99, margin: '0 auto 14px',
              background: 'hsl(105 30% 38% / .12)', color: 'hsl(160 84% 30%)',
              display: 'grid', placeItems: 'center',
            }}>
              <CheckCircle2 size={28} />
            </div>
            <h3 style={{ margin: 0, fontSize: 16, color: '#171412', fontWeight: 600 }}>
              Message sent
            </h3>
            <p style={{ margin: '8px 0 20px', fontSize: 13, color: '#57504A', lineHeight: 1.5 }}>
              Thanks — we'll get back to you at {defaultEmail || 'your registered email'} as soon as possible.
            </p>
            <button
              type="button"
              onClick={onClose}
              style={{
                background: 'var(--flc-cta, linear-gradient(135deg, #E8703A, #C73E2C 55%, #A82843))',
                color: 'var(--flc-on-cta, #FFFFFF)', border: 'none', borderRadius: 10,
                padding: '10px 22px', fontSize: 13, fontWeight: 500,
                cursor: 'pointer',
              }}
            >
              Close
            </button>
          </div>
        ) : (
          <div style={{ padding: 20 }}>
            {/* From (read-only) */}
            {defaultEmail && (
              <div style={{ marginBottom: 12 }}>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: '#57504A', marginBottom: 6 }}>
                  From
                </label>
                <input
                  type="email"
                  value={defaultEmail}
                  readOnly
                  style={{
                    width: '100%', padding: '9px 12px', borderRadius: 8,
                    border: `1px solid ${C.hairline}`, background: '#FBF7EF',
                    color: '#57504A', fontSize: 13, font: 'inherit',
                  }}
                />
              </div>
            )}

            {/* Subject */}
            <div style={{ marginBottom: 12 }}>
              <label htmlFor="support-subject" style={{
                display: 'flex', justifyContent: 'space-between',
                fontSize: 12, fontWeight: 500, color: '#57504A', marginBottom: 6,
              }}>
                <span>Subject</span>
                <span style={{ color: subject.length > MAX_SUBJECT ? '#B85C38' : '#A8A29E', fontWeight: 400 }}>
                  {subject.length}/{MAX_SUBJECT}
                </span>
              </label>
              <input
                ref={subjectRef}
                id="support-subject"
                type="text"
                value={subject}
                onChange={(e) => setSubject(e.target.value.slice(0, MAX_SUBJECT))}
                placeholder="e.g. Trouble with my QR scan setup"
                style={{
                  width: '100%', padding: '10px 12px', borderRadius: 8,
                  border: `1px solid ${C.hairline}`, background: 'var(--flc-card, #FFFFFF)',
                  color: '#171412', fontSize: 13.5, font: 'inherit',
                  outline: 'none',
                }}
                onFocus={(e) => { e.currentTarget.style.borderColor = '#B85C38'; }}
                onBlur={(e)  => { e.currentTarget.style.borderColor = C.hairline; }}
              />
            </div>

            {/* Message */}
            <div style={{ marginBottom: 16 }}>
              <label htmlFor="support-message" style={{
                display: 'flex', justifyContent: 'space-between',
                fontSize: 12, fontWeight: 500, color: '#57504A', marginBottom: 6,
              }}>
                <span>Message</span>
                <span style={{ color: message.length > MAX_MESSAGE ? '#B85C38' : '#A8A29E', fontWeight: 400 }}>
                  {message.length}/{MAX_MESSAGE}
                </span>
              </label>
              <textarea
                id="support-message"
                value={message}
                onChange={(e) => setMessage(e.target.value.slice(0, MAX_MESSAGE))}
                rows={7}
                placeholder="Describe your question or issue in as much detail as possible. Screenshots help — paste a link to any image you've uploaded."
                style={{
                  width: '100%', padding: '10px 12px', borderRadius: 8,
                  border: `1px solid ${C.hairline}`, background: 'var(--flc-card, #FFFFFF)',
                  color: '#171412', fontSize: 13.5, lineHeight: 1.5,
                  font: 'inherit', resize: 'vertical', minHeight: 120,
                  outline: 'none',
                }}
                onFocus={(e) => { e.currentTarget.style.borderColor = '#B85C38'; }}
                onBlur={(e)  => { e.currentTarget.style.borderColor = C.hairline; }}
              />
            </div>

            {/* Error banner */}
            {result?.ok === false && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: 10, borderRadius: 8, marginBottom: 12,
                background: 'hsl(355 60% 48% / .08)', color: 'hsl(352 70% 40%)',
                fontSize: 12.5,
              }}>
                <AlertTriangle size={14} />
                <span>{result.error}</span>
              </div>
            )}

            {/* Actions */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button
                type="button"
                onClick={onClose}
                disabled={sending}
                style={{
                  background: 'transparent', border: `1px solid ${C.hairline}`,
                  color: '#57504A', borderRadius: 10,
                  padding: '9px 16px', fontSize: 13, fontWeight: 500,
                  cursor: sending ? 'not-allowed' : 'pointer', font: 'inherit',
                  opacity: sending ? 0.6 : 1,
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={send}
                disabled={!canSend}
                style={{
                  background: canSend
                    ? 'var(--flc-cta, linear-gradient(135deg, #E8703A, #C73E2C 55%, #A82843))'
                    : '#D6D3D1',
                  color: 'var(--flc-on-cta, #FFFFFF)', border: 'none', borderRadius: 10,
                  padding: '9px 18px', fontSize: 13, fontWeight: 500,
                  cursor: canSend ? 'pointer' : 'not-allowed',
                  display: 'inline-flex', alignItems: 'center', gap: 7,
                  font: 'inherit',
                  boxShadow: canSend ? '0 6px 18px -8px rgb(184 92 56 / .55)' : 'none',
                }}
              >
                <Send size={14} />
                {sending ? 'Sending…' : 'Send message'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
