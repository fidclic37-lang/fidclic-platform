import React from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';
import { Settings2, ArrowRight } from 'lucide-react';
import { sectionsFor, sectionPath } from './parametres/sections';
import { useAuth } from '../contexts/AuthContext';
import ReglesClientsPage from './ReglesClientsPage';
import LienInscriptionPage from './LienInscriptionPage';
import EquipeAccesPage from './EquipeAccesPage';
import EtablissementPage from './EtablissementPage';
import NotificationsSettingsPage from './NotificationsSettingsPage';

/* Paramètres — one page with a tab per sub-page, built like Analyses. The tab
   lives in the URL (/dashboard/parametres/<tab>) so a sub-page can be linked
   to and survives a reload.

   Sub-pages whose design has not arrived yet show an empty state; where the
   same settings exist on the older all-in-one page, it links straight to
   them so nothing goes out of reach in the meantime. */
const PAGES = { etablissement: EtablissementPage, 'regles-clients': ReglesClientsPage,
                'lien-inscription': LienInscriptionPage, equipe: EquipeAccesPage,
                notifications: NotificationsSettingsPage };

function EmptySection({ section }) {
  const Icon = section.icon;
  return (
    <div className="flex flex-col items-center rounded-2xl border border-[#E6EEFB] bg-white px-6 py-16 text-center">
      <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#EAF1FF] text-[#2F6BFF]">
        <Icon size={26} />
      </span>
      <h2 className="text-[19px] font-bold text-[#0B1C3F]">{section.title}</h2>
      <p className="mt-1 max-w-md text-[13.5px] text-[#64748B]">{section.subtitle}</p>
      <p className="mt-5 rounded-full bg-[#F4F7FC] px-3.5 py-1.5 text-[12.5px] font-medium text-[#475569]">
        Cette page arrive bientôt.
      </p>
      {section.legacy && (
        <Link to={`/dashboard/settings#${section.legacy}`}
              className="mt-4 inline-flex items-center gap-1.5 text-[13px] font-semibold text-[#2F6BFF] hover:underline">
          En attendant, ces réglages sont ici <ArrowRight size={14} />
        </Link>
      )}
    </div>
  );
}

export default function ParametresPage() {
  const { section: slug } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const sections = sectionsFor(user?.role);
  const section = sections.find((s) => s.slug === slug);
  if (!section) return <Navigate to={sectionPath(sections[0].slug)} replace />;
  const Page = PAGES[section.slug];

  return (
    <div className="pm">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#EAF1FF] text-[#2F6BFF]">
            <Settings2 size={22} />
          </span>
          <div>
            <h1 className="text-[23px] font-bold leading-tight text-[#0B1C3F]">Paramètres</h1>
            <p className="text-[13px] text-[#64748B]">
              Configurez votre espace : vos clients, votre équipe, votre abonnement et vos préférences.
            </p>
          </div>
        </div>
        {user?.role === 'business_owner' && (
          <Link to="/dashboard/settings"
                className="inline-flex items-center gap-1.5 rounded-xl border border-[#E6EEFB] bg-white px-3.5 py-2.5 text-[12.5px] font-medium text-[#334155] hover:border-[#C9DBFB] hover:text-[#2F6BFF]">
            Tous les anciens réglages <ArrowRight size={14} />
          </Link>
        )}
      </header>

      <nav className="mb-5 flex gap-1 overflow-x-auto border-b border-[#E6EEFB]" role="tablist">
        {sections.map((s) => {
          const on = s.slug === section.slug;
          return (
            <button key={s.slug} type="button" role="tab" aria-selected={on}
                    onClick={() => navigate(sectionPath(s.slug))}
                    className={`shrink-0 border-b-2 px-3.5 py-2.5 text-[13px] font-semibold transition ${
                      on ? 'border-[#2F6BFF] text-[#2F6BFF]'
                         : 'border-transparent text-[#64748B] hover:text-[#334155]'}`}>
              {s.label}
            </button>
          );
        })}
      </nav>

      {Page ? <Page /> : <EmptySection section={section} />}
    </div>
  );
}
