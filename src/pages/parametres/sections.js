import {
  Users, QrCode, UserCog, ShieldCheck, Wallet, Languages, Bell, Lock, Store,
} from 'lucide-react';

/* Paramètres — the eight sub-pages, in the sidebar's order. One list, read by
   the sidebar and by the page itself, so the two can never disagree.

   `legacy` is where the same settings live on the older all-in-one page
   (/dashboard/settings) until each sub-page is built — nothing the owner can
   set today goes out of reach in the meantime. */
export const PARAMETRES_SECTIONS = [
  { slug: 'etablissement', label: 'Établissement', icon: Store,
    title: 'Établissement',
    subtitle: 'Gérez les informations de votre commerce.' },
  { slug: 'regles-clients', label: 'Règles clients', icon: Users,
    title: 'Règles clients',
    subtitle: 'Définissez comment FidClic classe automatiquement vos clients.' },
  { slug: 'lien-inscription', label: "Lien d'inscription & QR", icon: QrCode,
    title: "Lien d'inscription & QR code",
    subtitle: 'Là où vos clients créent leur carte — au comptoir ou sur vos réseaux.',
    legacy: 'settings-join' },
  { slug: 'equipe', label: 'Équipe & accès', icon: UserCog,
    title: 'Équipe & accès',
    subtitle: 'Donnez un accès à vos collaborateurs, chacun selon son rôle.' },
  { slug: 'donnees', label: 'Données & confidentialité', icon: ShieldCheck,
    title: 'Données & confidentialité',
    subtitle: 'Vos obligations RGPD et le nettoyage de votre fichier clients.',
    legacy: 'settings-cleanup' },
  { slug: 'abonnement', label: 'Abonnement & facturation', icon: Wallet,
    title: 'Abonnement & facturation',
    subtitle: 'Votre formule, votre essai et vos factures.',
    legacy: 'settings-billing' },
  { slug: 'preferences', label: 'Préférences', icon: Languages,
    title: 'Préférences',
    subtitle: 'Langue et formats d’affichage de votre espace.',
    legacy: 'settings-language' },
  { slug: 'notifications', label: 'Notifications', icon: Bell,
    title: 'Notifications',
    subtitle: 'Qui envoie, par quels canaux, et combien de messages au maximum.' },
  { slug: 'securite', label: 'Sécurité', icon: Lock,
    title: 'Sécurité',
    subtitle: 'Protégez l’accès à votre compte.' },
];

/* What each role sees of Paramètres. Administrateurs and managers manage
   their team here, and see their establishments (an administrateur edits its
   points de vente and the legal information; a manager reads). The shop-wide
   settings stay with the Propriétaire. */
export const sectionsFor = (role) => (role === 'business_owner'
  ? PARAMETRES_SECTIONS
  : PARAMETRES_SECTIONS.filter((s) => s.slug === 'equipe' || s.slug === 'etablissement'));

export const PARAMETRES_BASE = '/dashboard/parametres';
export const sectionPath = (slug) => `${PARAMETRES_BASE}/${slug}`;
