import React, { useEffect, useRef, useState } from 'react';
import { COUNTRIES, flagOf, country, onlyDigits, splitPhone, joinPhone, phoneError } from '../lib/phone';

/**
 * PhoneField — the one phone input of every signup form (user, 2026-10-09):
 * a country picked from the list (France first), then digits only. « # »,
 * « * », letters and spaces never get in; a pasted or autofilled « +33 6 … »
 * lands in the right country. France: 0 then 9 digits.
 *
 * Props:
 *   value / onChange(value)  — the stored form: « 0612345678 », « +447700900123 »
 *   inputClassName           — the <input>'s classes (each form keeps its look)
 *   selectClassName          — classes of the country picker (« 🇫🇷 +33 »)
 *   id, required, autoComplete, placeholder, aria-* — passed to the <input>
 *
 * The parent shows the rule (phoneValueError(value)) under the field, where
 * its own layout wants it, and checks it again before sending.
 */
export const phoneValueError = (value) => {
  const { iso, national } = splitPhone(value);
  return phoneError(iso, national);
};

export default function PhoneField({
  value, onChange, inputClassName = '', selectClassName = '',
  placeholder, autoComplete = 'tel', ...rest
}) {
  const start = splitPhone(value);
  const [iso, setIso] = useState(start.iso);
  const [national, setNational] = useState(start.national);
  const last = useRef(value);

  // a value set from outside (a form reset, a loaded fiche) takes over
  useEffect(() => {
    if (value !== last.current) {
      const s = splitPhone(value, iso);
      setIso(s.iso);
      setNational(s.national);
      last.current = value;
    }
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

  const emit = (nextIso, nextNational) => {
    const v = joinPhone(nextIso, nextNational);
    last.current = v;
    onChange(v);
  };

  const take = (raw) => {
    const text = String(raw ?? '');
    if (/^\s*(\+|00)/.test(text)) {               // pasted or autofilled with its country
      const s = splitPhone(text.trim(), iso);
      setIso(s.iso);
      setNational(s.national);
      emit(s.iso, s.national);
      return;
    }
    let digits = onlyDigits(text);
    if (iso === 'FR') digits = digits.slice(0, 10);
    else digits = digits.slice(0, 14);
    setNational(digits);
    emit(iso, digits);
  };

  return (
    <div className="flex min-w-0 flex-1 items-stretch">
      {/* closed: just « 🇫🇷 +33 »; open: the whole list with names */}
      <div className={`relative flex items-center ${selectClassName}`}>
        <span aria-hidden="true" className="pointer-events-none whitespace-nowrap">
          {`${flagOf(iso)} +${country(iso).dial}`} <span className="text-[10px] opacity-60">▾</span>
        </span>
        {/* 16px: iPhone Safari zooms into any smaller field */}
        <select
          aria-label="Pays de l'indicatif"
          value={iso}
          onChange={(e) => { setIso(e.target.value); emit(e.target.value, national); }}
          className="absolute inset-0 h-full w-full cursor-pointer !text-[16px] opacity-0"
        >
          {COUNTRIES.map(([code, name, dial]) => (
            <option key={code} value={code}>{`${flagOf(code)} ${name} (+${dial})`}</option>
          ))}
        </select>
      </div>
      <input
        type="tel"
        inputMode="tel"
        data-keep-zeros=""
        autoComplete={autoComplete}
        placeholder={placeholder || (iso === 'FR' ? '06 12 34 56 78' : `Numéro sans +${country(iso).dial}`)}
        {...rest}
        value={national}
        onChange={(e) => take(e.target.value)}
        className={inputClassName}
      />
    </div>
  );
}
