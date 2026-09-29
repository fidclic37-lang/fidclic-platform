import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Construction } from 'lucide-react';

/**
 * A section that exists in the navigation but whose content is not defined
 * yet. It is deliberately honest: the merchant sees the section they expect,
 * and it says plainly that it is being built rather than faking a feature.
 */
export default function ComingSoonPage({ title, description }) {
  return (
    <div className="lc lc-wrap pb-10">
      <div className="mx-auto max-w-[620px] rounded-2xl border border-[#E6EEFB] bg-white p-10 text-center shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
        <span className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#EAF1FF] text-[#2F6BFF]">
          <Construction size={24} />
        </span>
        <h1 className="text-[22px] font-extrabold tracking-[-0.02em] text-[#0B1C3F]">{title}</h1>
        <p className="mx-auto mt-2 max-w-[440px] text-[13.5px] leading-relaxed text-[#64748B]">{description}</p>
        <p className="mt-4 text-[12.5px] text-[#94A3B8]">Cette section est en cours de construction.</p>
        <Link to="/dashboard" className="mt-6 inline-flex items-center gap-2 rounded-xl border border-[#E1E8F5] px-4 py-2.5 text-[13px] font-semibold text-[#334155] hover:border-[#2F6BFF] hover:text-[#2F6BFF]">
          <ArrowLeft size={15} /> Retour au tableau de bord
        </Link>
      </div>
    </div>
  );
}
