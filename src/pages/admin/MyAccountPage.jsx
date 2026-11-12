import React from 'react';
import { UserRound } from 'lucide-react';
import { Breadcrumb } from '../crm/ui';
import MyAccount from './settings/MyAccount';

/* /admin/moi — « Mes paramètres » for every member of FidClic's team, whatever
   their role opens (the Paramètres page shows the same as its third tab). */
export default function MyAccountPage() {
  return (
    <div className="mx-auto max-w-[1400px] p-4 sm:p-6">
      <Breadcrumb items={[['Super Admin', '/admin'], ['Mes paramètres']]} />
      <div className="mb-4 flex items-center gap-2.5">
        <UserRound size={22} className="text-[#2F6BFF]" />
        <div>
          <h1 className="text-[22px] font-bold text-[#0B1C3F]">Mes paramètres</h1>
          <p className="text-[13px] text-[#64748B]">Votre profil, votre mot de passe, la 2FA, vos appareils et vos alertes.</p>
        </div>
      </div>
      <MyAccount />
    </div>
  );
}
