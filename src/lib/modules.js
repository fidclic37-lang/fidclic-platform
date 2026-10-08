/**
 * Which FidClic modules the platform shows.
 *
 * E-invoicing (Facturation électronique: the module chooser, /facturation,
 * the public /facturation-electronique and /experts-comptables pages, the
 * accountants' signup) is hidden for now — user, 2026-10-08: « hide it from
 * the platform, code rakho, future mein dekhenge ». All its code stays; set
 * this to true to bring it back.
 */
export const EINVOICING_VISIBLE = false;

// Where an owner lands after logging in: the module chooser when there is a
// choice to make, the loyalty dashboard otherwise.
export const OWNER_HOME = EINVOICING_VISIBLE ? '/modules' : '/dashboard';
