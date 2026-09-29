import React from 'react';
import { Link } from 'react-router-dom';
import { Hammer, ArrowRight } from 'lucide-react';
import { Breadcrumb } from './ui';

/* A CRM section whose page arrives in the next update — the menu already
   lists it so the structure matches the approved mockup. */
export default function CrmSoonPage({ title, text }) {
  return (
    <div className="crm">
      <Breadcrumb items={[['CRM de prospection', '/admin/crm'], [title]]} />
      <h1 className="text-[28px] font-bold text-[#0B1C3F]">{title}</h1>
      <div className="mt-4 flex flex-col items-center rounded-2xl border border-[#E6EEFB] bg-white px-6 py-16 text-center">
        <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#EAF1FF] text-[#2F6BFF]"><Hammer size={26} /></span>
        <p className="max-w-md text-[14px] text-[#475569]">{text}</p>
        <p className="mt-4 rounded-full bg-[#F4F7FC] px-3.5 py-1.5 text-[12.5px] font-medium text-[#475569]">Arrive dans la prochaine mise à jour du CRM.</p>
        <Link to="/admin/crm/prospects" className="mt-4 inline-flex items-center gap-1.5 text-[13px] font-semibold text-[#2F6BFF]">Aller aux prospects <ArrowRight size={14} /></Link>
      </div>
    </div>
  );
}
