"""
Facturation électronique (French e-invoicing) — owner-facing API.

Status: 🟡 In progress (Step 3 of the module build).
Mounts at: /api/owner/facturation/*   (+ public webhook /api/facturation/webhook)
Storage: Mongo collections fact_invoices, fact_received_invoices, fact_ereports,
         fact_credit_notes, fact_coherence_checks; tenant doc facturation_* fields.

Why this exists:
  FidClic's second module. Lets a merchant issue/receive compliant e-invoices,
  do B2C e-reporting, correct via credit notes, and see a "Bouclier Fiscal"
  coherence indicator — all through the PA-agnostic PdpConnector (Mock by
  default; B2Brouter when env is set). Nothing here talks to a PA directly.

Safety:
  - Gated: every route requires the tenant to have `facturation_enabled=True`,
    so loyalty-only tenants never touch this code path.
  - Registered via features/_loader.py; a failure here cannot take down the app.

Legal:
  The coherence score is an INFORMATIONAL consistency indicator, NOT tax advice
  and NOT an ECF (Examen de Conformité Fiscale). The UI carries that disclaimer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from auth import require_role, get_current_user_data

import os

from services.pdp_connector import (
    get_pdp_connector, InvoiceState, IdempotencyGuard, PdpError, KNOWN_PROVIDERS,
    MockPdp,
)
from services import statuses as st
from services.statuses import ReviewStatus, PaymentStatus, ExportStatus
import models as m


def _audit(*args, **kwargs):
    """Thin wrapper so a missing/failed audit module can never break invoicing."""
    try:
        from features import audit
        audit.log(*args, **kwargs)
    except Exception:
        pass


def _open_case(*args, **kwargs):
    """Raise an Exception-Centre case, never letting it break the caller.

    The whole point of a case is to catch a failure — so it must not itself be
    able to cause one.
    """
    try:
        from features import exceptions_centre
        return exceptions_centre.open_case(*args, **kwargs)
    except Exception:
        return None

router = APIRouter(tags=["facturation"])
_db = None
_guard = IdempotencyGuard()


def init(db):
    global _db
    _db = db


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _tenant(tenant_id: str) -> Dict[str, Any]:
    t = _db.tenants.find_one({"id": tenant_id}) if _db is not None else None
    if not t:
        raise HTTPException(404, "Tenant not found")
    return t


def _require_facturation(token_data) -> Dict[str, Any]:
    """Resolve tenant AND enforce the facturation entitlement gate."""
    t = _tenant(token_data.tenant_id)
    if not t.get("facturation_enabled"):
        raise HTTPException(403, "Le module Facturation n'est pas activé pour ce compte.")
    return t


def _tenant_for_actor(token_data, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """Resolve WHICH company this action is for, and prove the caller may act on it.

    Owners/managers act on their own tenant, full stop. An accountant may act
    ON BEHALF OF a client — but only one they hold an ACTIVE mandate for, and
    only when they name the client explicitly (`tenant_id`), so an accountant
    can never act "by accident" on the wrong dossier.

    Why let the cabinet act at all: in real life the accountant is the one who
    remembers the e-reporting deadline, not the restaurant owner. Blocking them
    would just push the work back into email.
    """
    if getattr(token_data, "role", None) == "comptable":
        if not tenant_id:
            raise HTTPException(422, "tenant_id requis : précisez le dossier client.")
        from features.cabinet import assert_mandate      # lazy: leaf-module independence
        assert_mandate(getattr(token_data, "email", ""), tenant_id)
        t = _tenant(tenant_id)
        if not t or not t.get("facturation_enabled"):
            raise HTTPException(403, "Le module Facturation n'est pas activé pour ce client.")
        return t
    return _require_facturation(token_data)


def _acting_note(token_data, tenant: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Audit detail marking an action performed by a cabinet for a client.

    Without this the log would read as if the business owner did it, which is
    exactly the ambiguity the audit trail exists to remove.
    """
    if getattr(token_data, "role", None) == "comptable":
        return {"on_behalf_of": tenant.get("legal_name") or tenant.get("name"),
                "by_cabinet_user": getattr(token_data, "email", None)}
    return None


def _assert_invoice_compliant(tenant: Dict[str, Any], buyer: Dict[str, Any],
                              body: Dict[str, Any], lines: List[Dict[str, Any]]) -> None:
    """Refuse to create an invoice that is not legally complete.

    Every rule here maps to a real requirement (art. 242 nonies A CGI, art.
    L441-9 Code de commerce, plus the 2026 reform additions). Blocking at
    creation is deliberate: an invoice that leaves the building non-compliant
    comes back as a rejection, a support case and a resend.
    """
    errors: List[str] = []

    # The buyer record arrives in two shapes and the checks must accept both,
    # because the PDP mapper (services.pdp_connector._addr / to_b2brouter_invoice)
    # already does: `name` or `legal_name`, and `address` as a plain string or a
    # structured dict. Treating address as a string here crashed with 500 on
    # every structured-address invoice — found by the failure-path e2e run.
    if not ((buyer.get("name") or buyer.get("legal_name") or "").strip()):
        errors.append("Le nom du client est obligatoire.")

    addr = buyer.get("address")
    if isinstance(addr, dict):
        has_addr = bool((addr.get("street") or addr.get("line1") or "").strip()
                        and (addr.get("city") or "").strip())
    else:
        has_addr = bool((addr or "").strip())
    if not has_addr:
        errors.append("L'adresse du client est obligatoire.")

    if buyer.get("is_company", True):
        siren = "".join(ch for ch in str(buyer.get("siren") or "") if ch.isdigit())
        if not siren:
            # A SIRET is SIREN + 5-digit NIC, so a record carrying only the
            # SIRET still identifies the company. Same derivation the annuaire
            # uses; requiring a separate siren field was a false rejection.
            siret = "".join(ch for ch in str(buyer.get("siret") or "") if ch.isdigit())
            if len(siret) == 14:
                siren = siret[:9]
        if len(siren) != 9:
            errors.append("Le SIREN du client est obligatoire pour une facture B2B (réforme 2026).")
        elif not _luhn_ok(siren):
            errors.append("Le SIREN du client est invalide (clé de contrôle).")

    if not body.get("date"):
        errors.append("La date d'émission est obligatoire.")
    if not body.get("supply_date"):
        errors.append("La date de vente ou de prestation est obligatoire.")
    if not body.get("due_date"):
        errors.append("La date d'échéance est obligatoire.")
    if body.get("due_date") and body.get("date") and body["due_date"] < body["date"]:
        errors.append("L'échéance ne peut pas précéder la date d'émission.")
    if not body.get("operation_category"):
        errors.append("La catégorie d'opération est obligatoire (réforme 2026).")

    usable = [l for l in lines
              if str(l.get("description") or "").strip()
              and float(l.get("unit_price") or 0) > 0]
    if not usable:
        errors.append("Au moins une ligne avec une description et un montant est requise.")

    # Franchise en base: charging VAT is not a formatting slip, it is illegal.
    if tenant.get("vat_regime") == "franchise":
        if any(float(l.get("vat_rate") or 0) > 0 for l in lines):
            errors.append("En franchise en base, aucune TVA ne peut être facturée.")

    if errors:
        raise HTTPException(422, " ".join(errors))


def _compute_totals(lines: List[Dict[str, Any]]) -> Dict[str, float]:
    ht = vat = 0.0
    for ln in lines:
        line_ht = float(ln.get("quantity", 1)) * float(ln.get("unit_price", 0))
        ln["line_total_ht"] = round(line_ht, 2)
        ht += line_ht
        vat += line_ht * float(ln.get("vat_rate", 20)) / 100.0
    return {"total_ht": round(ht, 2), "total_vat": round(vat, 2),
            "total_ttc": round(ht + vat, 2)}


def _public(inv: Dict[str, Any]) -> Dict[str, Any]:
    """Strip Mongo internals and guarantee the four status families exist.

    Legacy rows only carry `state`; st.ensure() derives the rest on read so no
    migration downtime is needed (see services/statuses.py).
    """
    if inv is None:
        return inv
    inv.pop("_id", None)
    return st.ensure(inv)


def compute_bouclier(tenant: Dict[str, Any]) -> Dict[str, Any]:
    """Single source of truth for the Bouclier Fiscal score.

    Transparent, per-invoice rules with an itemised `breakdown` so the number
    is never a black box:
      - each issued invoice stuck in ERROR/REFUSED and NOT yet corrected by an
        avoir (credit note) costs points (capped) -> red
      - DGFiP compliance not activated -> amber
      - no supplier (received) invoice imported yet -> amber
    A refused invoice that HAS a linked avoir is considered corrected and no
    longer penalises the score (this is what makes "create an avoir" verifiable).
    Also returns channel counts (B2B e-invoicing vs B2C e-reporting).
    """
    tid = tenant["id"]
    issued = [st.ensure(i) for i in _db.fact_invoices.find({"tenant_id": tid})]
    received = _db.fact_received_invoices.count_documents({"tenant_id": tid})
    credit_notes = list(_db.fact_credit_notes.find({"tenant_id": tid}))
    credited_ids = {cn.get("original_invoice_id") for cn in credit_notes}

    # pa_status is the source of truth post-S1 (st.ensure backfills legacy rows).
    refused = [i for i in issued if i.get("pa_status") in (InvoiceState.ERROR, InvoiceState.REFUSED)]
    uncorrected = [i for i in refused if i.get("id") not in credited_ids]
    corrected = [i for i in refused if i.get("id") in credited_ids]

    einvoicing = sum(1 for i in issued if i.get("channel") == "e-invoicing"
                     or (i.get("channel") is None and (i.get("buyer") or {}).get("is_company", True)))
    ereporting = len(issued) - einvoicing

    alerts: List[Dict[str, Any]] = []
    breakdown: List[Dict[str, Any]] = []
    score = 100

    if uncorrected:
        pts = min(len(uncorrected) * 15, 45)
        score -= pts
        alerts.append({"level": "red",
                       "message": f"{len(uncorrected)} facture(s) refusée(s) ou en erreur à corriger.",
                       "fix_action": "review_rejected"})
        breakdown.append({"level": "red",
                          "label": f"{len(uncorrected)} facture(s) refusée(s) non corrigée(s)",
                          "points": -pts})
    if corrected:
        breakdown.append({"level": "green",
                          "label": f"{len(corrected)} facture(s) refusée(s) corrigée(s) par avoir",
                          "points": 0})
    if not tenant.get("dgfip_activated"):
        score -= 20
        alerts.append({"level": "amber",
                       "message": "Conformité DGFiP non activée — activez pour émettre.",
                       "fix_action": "activate_dgfip"})
        breakdown.append({"level": "amber", "label": "Conformité DGFiP non activée", "points": -20})
    if received == 0:
        score -= 8
        alerts.append({"level": "amber",
                       "message": "Aucune facture fournisseur reçue — importez ou photographiez (OCR) "
                                  "vos justificatifs, même les tickets de caisse des grandes surfaces.",
                       "fix_action": None})
        breakdown.append({"level": "amber", "label": "Aucune facture fournisseur importée", "points": -8})

    # Terrain (août 2026) — la signature des ventes en espèces non déclarées :
    # les ACHATS restent élevés (souvent payés en partie par carte pour « faire
    # justifié ») pendant que les VENTES DÉCLARÉES restent basses. Si le total
    # des achats approche/dépasse un seuil du total des ventes déclarées, la
    # cohérence devient implausible pour quasi tous les secteurs. Indicateur
    # informatif, PAS une accusation — le seuil est réglable par dossier
    # (tenant.achats_ventes_seuil, défaut 0.80).
    achats_ttc = sum(float(r.get("total_ttc") or 0)
                     for r in _db.fact_received_invoices.find({"tenant_id": tid}))
    ventes_ttc = sum(float(i.get("total_ttc") or 0) for i in issued)
    for er in _db.fact_ereports.find({"tenant_id": tid}):
        for v in (er.get("totals_by_vat") or {}).values():
            ventes_ttc += float(v or 0)
    # NAF-aware version when possible: the SIMULATED AUDIT (reconstitution).
    # achats × coefficient sectoriel = CA attendu ; declared below the band's
    # low end → the gap an inspector would presume. Falls back to the plain
    # 80 % ratio when no NAF/coefficient is available.
    recon = None
    try:
        from features import coefficients as coefs
        recon = coefs.reconstitution(_db, tenant)
    except Exception:
        recon = None
    if recon is not None:
        if recon["flag"]:
            score -= 12
            alerts.append({"level": "amber",
                           "message": (f"Reconstitution simulée ({recon['coefficient']['label']}) : "
                                       f"vos achats de {recon['achats']:.0f} € impliquent un CA attendu de "
                                       f"{recon['expected_min']:.0f}–{recon['expected_max']:.0f} € ; "
                                       f"CA déclaré : {recon['declared']:.0f} €. "
                                       "Toutes les ventes (y compris en espèces) sont-elles déclarées ?"),
                           "fix_action": None})
            breakdown.append({"level": "amber",
                              "label": f"Écart de reconstitution ~{recon['gap']:.0f} € "
                                       f"({recon['coefficient']['source']})",
                              "points": -12})
        achats_ttc = 0  # handled — skip the generic ratio below
    try:
        seuil_av = float(tenant.get("achats_ventes_seuil") or 0.80)
    except (TypeError, ValueError):
        seuil_av = 0.80
    if achats_ttc > 0 and ventes_ttc > 0 and achats_ttc > ventes_ttc * seuil_av:
        score -= 12
        ratio_pct = round(achats_ttc / ventes_ttc * 100)
        alerts.append({"level": "amber",
                       "message": f"Achats élevés ({ratio_pct} % des ventes déclarées) — "
                                  "toutes les ventes (y compris en espèces) sont-elles déclarées ?",
                       "fix_action": None})
        breakdown.append({"level": "amber",
                          "label": f"Ratio achats/ventes déclarées implausible ({ratio_pct} %)",
                          "points": -12})

    score = max(0, score)
    reds = sum(1 for a in alerts if a["level"] == "red")
    ambers = sum(1 for a in alerts if a["level"] == "amber")
    band = "red" if reds else ("amber" if ambers else "green")
    if not breakdown:
        breakdown.append({"level": "green", "label": "Aucune anomalie détectée", "points": 0})

    return {
        "score": score, "band": band, "alerts": alerts, "breakdown": breakdown,
        "counts": {
            "issued": len(issued), "received": received,
            "einvoicing": einvoicing, "ereporting": ereporting,
            "credit_notes": len(credit_notes),
            "refused": len(refused), "refused_open": len(uncorrected),
            # S1: per-family workload counters — the cabinet dashboard uses
            # these to show "kitna kaam pending hai" without extra queries.
            "unreviewed": sum(1 for i in issued
                              if i.get("review_status") == ReviewStatus.UNREVIEWED),
            "pending_validation": sum(1 for i in issued
                                      if i.get("review_status") == ReviewStatus.PENDING_VALIDATION),
            "ready_to_export": sum(1 for i in issued
                                   if i.get("export_status") == ExportStatus.READY),
            "unpaid": sum(1 for i in issued
                          if i.get("payment_status") in (PaymentStatus.UNPAID,
                                                         PaymentStatus.OVERDUE)),
        },
    }


# --------------------------------------------------------------------------
# availability & opt-in (ungated — used by the module chooser)
# --------------------------------------------------------------------------

@router.get("/api/owner/facturation/availability")
def facturation_availability(token_data=Depends(require_role(["business_owner", "manager"]))):
    """Ungated: tells the module chooser whether this tenant has Facturation on.
    Never 403s — loyalty-only tenants get {enabled: false}."""
    t = _tenant(token_data.tenant_id)
    return {
        "enabled": bool(t.get("facturation_enabled")),
        "plan": t.get("facturation_plan"),
        "legal_name": t.get("legal_name"),
        "siren": t.get("siren"),
        "dgfip_activated": bool(t.get("dgfip_activated")),
    }


@router.post("/api/owner/facturation/enable")
def facturation_enable(body: Dict[str, Any],
                       token_data=Depends(require_role(["business_owner"]))):
    """Turn the Facturation module ON for this tenant (simulates the purchase —
    standalone or add-on). Optionally captures legal identity at the same time.
    Stripe billing wiring comes later; for now this is the opt-in switch."""
    t = _tenant(token_data.tenant_id)

    # Server-side identity validation. The form checks the same things, but a
    # browser can be bypassed — and a bad SIREN/SIRET here means every future
    # invoice gets rejected by the Annuaire, which is far more expensive than
    # a 422 right now.
    siren = _digits(body.get("siren"))
    siret = _digits(body.get("siret"))
    if siren:
        if len(siren) != 9 or not _luhn_ok(siren):
            raise HTTPException(422, "SIREN invalide (9 chiffres, clé de contrôle).")
    if siret:
        if len(siret) != 14:
            raise HTTPException(422, "SIRET invalide (14 chiffres attendus).")
        if siren and not siret.startswith(siren):
            raise HTTPException(422, "Le SIRET doit commencer par le SIREN.")
        # La Poste (356000000…) is the documented exception to the Luhn rule.
        if not siret.startswith("356000000") and not _luhn_ok(siret):
            raise HTTPException(422, "SIRET invalide (clé de contrôle incorrecte).")
    vat = (body.get("vat_number") or "").replace(" ", "").upper()
    if vat and siren:
        expected = _derive_vat(siren)
        if vat != expected:
            raise HTTPException(422, f"N° de TVA incohérent avec le SIREN. Attendu : {expected}")

    upd: Dict[str, Any] = {
        "facturation_enabled": True,
        "facturation_plan": body.get("plan") or "addon",
    }
    for f in ("legal_name", "legal_form", "naf_code", "enterprise_size",
              "vat_regime", "business_profile"):
        if body.get(f):
            upd[f] = body[f]
    if siren:
        upd["siren"] = siren
    if siret:
        upd["siret"] = siret
    if vat:
        upd["vat_number"] = vat
    _db.tenants.update_one({"id": t["id"]}, {"$set": upd})
    _audit("facturation.enabled", tenant_id=t["id"], actor=token_data,
           object_kind="tenant", object_id=t["id"],
           after={k: upd[k] for k in ("siren", "siret", "vat_regime", "business_profile")
                  if k in upd})
    return {"ok": True, "enabled": True, "plan": upd["facturation_plan"]}


def _digits(v) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _luhn_ok(num: str) -> bool:
    """Luhn checksum — the key digit built into every SIREN and SIRET."""
    total, double = 0, False
    for ch in reversed(num):
        d = int(ch)
        if double:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        double = not double
    return total % 10 == 0


def _derive_vat(siren: str) -> str:
    """FR + key + SIREN, where key = (12 + 3 × (SIREN mod 97)) mod 97."""
    key = (12 + 3 * (int(siren) % 97)) % 97
    return f"FR{key:02d}{siren}"


# --------------------------------------------------------------------------
# status & activation
# --------------------------------------------------------------------------

@router.get("/api/owner/facturation/status")
def facturation_status(token_data=Depends(require_role(["business_owner", "manager"]))):
    t = _require_facturation(token_data)
    tid = t["id"]
    return {
        "enabled": True,
        "legal_name": t.get("legal_name"),
        "siren": t.get("siren"),
        "siret": t.get("siret"),
        "vat_regime": t.get("vat_regime"),
        "dgfip_activated": bool(t.get("dgfip_activated")),
        "annuaire_status": t.get("annuaire_status"),
        "provider": type(get_pdp_connector(t)).__name__,
        "pa_provider": getattr(get_pdp_connector(t), "provider", "mock"),
        "counts": compute_bouclier(t)["counts"],
    }


@router.get("/api/facturation/pa-providers")
def pa_providers():
    """The list of PAs a client can be routed to (Model B — Multi-PA)."""
    return {"providers": KNOWN_PROVIDERS}


@router.post("/api/owner/facturation/set-pa")
def set_pa(body: Dict[str, Any],
           token_data=Depends(require_role(["business_owner", "manager", "comptable"]))):
    """Choose which Plateforme Agréée a given client (dossier) is on.

    Model B: each client keeps ITS OWN platform. A cabinet can set a different PA
    per dossier; FidClic routes every operation to the right one automatically.
    """
    t = _tenant_for_actor(token_data, body.get("tenant_id"))
    provider = (body.get("pdp_provider") or "").strip().lower()
    if provider not in KNOWN_PROVIDERS:
        raise HTTPException(422, f"Plateforme inconnue. Choix: {', '.join(KNOWN_PROVIDERS)}.")
    upd: Dict[str, Any] = {"pdp_provider": provider}
    if body.get("pdp_account_id"):
        upd["pdp_account_id"] = str(body["pdp_account_id"])
    _db.tenants.update_one({"id": t["id"]}, {"$set": upd})
    _audit("facturation.pa_set", tenant_id=t["id"], actor=token_data,
           object_kind="tenant", object_id=t["id"], after={"pdp_provider": provider})
    return {"ok": True, "pa_provider": provider,
            "pa_account_id": upd.get("pdp_account_id") or t.get("pdp_account_id") or t["id"]}


@router.post("/api/owner/facturation/activate")
def facturation_activate(body: Dict[str, Any],
                         token_data=Depends(require_role(["business_owner", "manager", "comptable"]))):
    """Register the company with the PA / DGFiP (PPF Annuaire + tax-report setting).

    An accountant may activate FOR a mandated client (tenant_id in body) —
    in practice the cabinet is the one tracking the deadline, so both sides
    get the lever and the audit records who actually pulled it.
    """
    t = _tenant_for_actor(token_data, body.get("tenant_id"))
    if not t.get("facturation_enabled"):
        raise HTTPException(403, "Module Facturation non activé pour ce dossier.")
    conn = get_pdp_connector(t)
    # allow setting the client's PA at activation time (Model B — per-client PA)
    prov = (body.get("pdp_provider") or "").strip().lower()
    if prov:
        _db.tenants.update_one({"id": t["id"]}, {"$set": {"pdp_provider": prov}})
        t["pdp_provider"] = prov
        conn = get_pdp_connector(t)
    if body.get("pdp_account_id"):
        _db.tenants.update_one({"id": t["id"]}, {"$set": {"pdp_account_id": body["pdp_account_id"]}})
        t["pdp_account_id"] = body["pdp_account_id"]
    settings = {
        "start_date": body.get("start_date") or "2026-09-01",
        "type_operation": body.get("type_operation") or "services",
        "naf_code": body.get("naf_code") or t.get("naf_code") or "",
        "enterprise_size": body.get("enterprise_size") or t.get("enterprise_size") or "pme",
        "email": body.get("email"),
    }
    try:
        res = conn.activate_compliance(t.get("pdp_account_id") or t["id"], settings)
    except PdpError as e:
        raise HTTPException(502, f"Activation PA échouée: {e.message}")
    _db.tenants.update_one({"id": t["id"]}, {"$set": {
        "dgfip_activated": True,
        "annuaire_status": res.get("annuaire") or res.get("status") or "pending",
        "dgfip_start_date": settings["start_date"],
    }})
    _audit("facturation.dgfip_activated", tenant_id=t["id"], actor=token_data,
           object_kind="tenant", object_id=t["id"],
           after={"start_date": settings["start_date"]},
           detail=_acting_note(token_data, t))
    return {"ok": True, "result": res}


# --------------------------------------------------------------------------
# issued invoices
# --------------------------------------------------------------------------

@router.get("/api/owner/facturation/invoices")
def list_invoices(token_data=Depends(require_role(["business_owner", "manager"]))):
    t = _require_facturation(token_data)
    docs = list(_db.fact_invoices.find({"tenant_id": t["id"]}).sort("created_at", -1).limit(500))
    return {"invoices": [_public(d) for d in docs]}


@router.post("/api/owner/facturation/invoices")
def create_invoice(body: Dict[str, Any],
                   token_data=Depends(require_role(["business_owner", "manager", "comptable"]))):
    """Create a draft invoice. Pass send=true to also transmit immediately.

    An accountant may create FOR a client by passing `tenant_id` — the mandate
    is verified and the action is recorded as done on their behalf.
    """
    t = _tenant_for_actor(token_data, body.get("tenant_id"))
    lines = body.get("lines") or []
    if not lines:
        raise HTTPException(422, "Au moins une ligne est requise.")
    buyer = body.get("buyer") or {}

    # Mandatory content of a French invoice. The form checks the same rules for
    # instant feedback, but a browser can be bypassed — and an invoice missing a
    # legal mention is either rejected by the recipient's platform or found
    # non-compliant in an audit years later.
    _assert_invoice_compliant(t, buyer, body, lines)

    totals = _compute_totals(lines)
    channel = "e-reporting" if not buyer.get("is_company", True) else "e-invoicing"
    inv = {
        "id": _new_id(),
        "tenant_id": t["id"],
        "number": body.get("number") or _next_number(t["id"]),
        "buyer": buyer,
        "lines": lines,
        "date": body.get("date"),
        "supply_date": body.get("supply_date"),          # date de la vente/prestation
        "due_date": body.get("due_date"),
        "payment_term": body.get("payment_term"),
        "operation_category": body.get("operation_category"),   # 2026 mandatory
        "vat_on_debits": bool(body.get("vat_on_debits")),
        "purchase_order": body.get("purchase_order"),
        "notes": body.get("notes"),
        "legal_mentions": body.get("legal_mentions") or [],
        # Snapshot of the seller AT ISSUE TIME: an invoice must stay readable
        # exactly as it was sent, even if the company later changes address.
        "seller": {
            "legal_name": t.get("legal_name") or t.get("name"),
            "legal_form": t.get("legal_form"),
            "siren": t.get("siren"), "siret": t.get("siret"),
            "vat_number": t.get("vat_number"), "naf_code": t.get("naf_code"),
            "vat_regime": t.get("vat_regime"),
        },
        **totals,
        # Four independent status families (see services/statuses.py).
        **st.defaults(),
        "state": InvoiceState.DRAFT,     # legacy mirror — remove after 1 release
        "channel": channel,
        "lifecycle": [{"family": "pa", "state": InvoiceState.DRAFT, "at": _now()}],
        "created_by": getattr(token_data, "email", None),
        "created_at": _now(),
        "updated_at": _now(),
    }
    _db.fact_invoices.insert_one(dict(inv))
    _audit("invoice.created", tenant_id=t["id"], actor=token_data,
           object_kind="invoice", object_id=inv["id"],
           after={"number": inv["number"], "total_ttc": inv["total_ttc"],
                  "channel": channel},
           detail=_acting_note(token_data, t))
    if body.get("send"):
        return _do_send(t, inv, simulate=body.get("simulate"), actor=token_data)
    return {"invoice": _public(inv)}


@router.post("/api/owner/facturation/invoices/{invoice_id}/send")
def send_invoice(invoice_id: str,
                 token_data=Depends(require_role(["business_owner", "manager", "comptable"]))):
    inv, tenant_id = _resolve_invoice_for_actor(invoice_id, token_data)
    t = _tenant(tenant_id)
    return _do_send(t, inv, actor=token_data)


def _do_send(t: Dict[str, Any], inv: Dict[str, Any], simulate: Optional[str] = None,
             actor=None) -> Dict[str, Any]:
    """Idempotent send: same tenant+number never transmits twice.
    `simulate` (TEST, Mock only): 'reject' | 'error' | 'timeout' forces that outcome
    so the rejection/error UX can be tested without a real PA."""
    key = IdempotencyGuard.make_key(t["id"], inv["number"])
    cached = _guard.already_sent(key)
    if cached:
        return {"invoice": _public(inv), "idempotent": True, "result": cached}
    conn = get_pdp_connector(t)   # Model B: route to THIS client's PA
    # TEST hook: only the in-memory Mock supports forced outcomes.
    # Map the API vocabulary ('reject') to the Mock's ('refused').
    if simulate and hasattr(conn, "force_next_send"):
        conn.force_next_send = {"reject": "refused"}.get(simulate, simulate)
    account_id = t.get("pdp_account_id") or t["id"]
    try:
        created = conn.create_invoice(account_id, inv)
        pdp_id = created.get("id")
        result = conn.send(pdp_id)
    except PdpError as e:
        _update_state(inv["id"], InvoiceState.ERROR, code=e.code, reason=e.message)
        _open_case(t["id"], "send_error",
                   detail_fr=f"Facture {inv.get('number')} : {e.message}",
                   related_kind="invoice", related_id=inv["id"],
                   related_ref=inv.get("number"), technical_ref=str(e.code))
        raise HTTPException(502, f"Envoi échoué: {e.message}")
    _guard.mark_sent(key, result)
    if result.get("state") in (InvoiceState.REFUSED, InvoiceState.ERROR):
        _open_case(t["id"], "pa_rejection",
                   detail_fr=(f"Facture {inv.get('number')} refusée par la plateforme"
                              + (f" : {result.get('reject_reason')}" if result.get("reject_reason") else "")),
                   related_kind="invoice", related_id=inv["id"],
                   related_ref=inv.get("number"),
                   technical_ref=result.get("reject_code"))
    _update_state(inv["id"], result.get("state", InvoiceState.SENT),
                  pdp_id=result.get("id") or pdp_id,
                  code=result.get("reject_code"), reason=result.get("reject_reason"))
    _audit("invoice.sent", tenant_id=t["id"], actor=actor,
           object_kind="invoice", object_id=inv["id"],
           after={"pa_status": result.get("state", InvoiceState.SENT)},
           detail={"number": inv.get("number"), "provider": type(conn).__name__,
                   "reject_code": result.get("reject_code"),
                   **(_acting_note(actor, t) or {})})
    inv = _db.fact_invoices.find_one({"id": inv["id"]})
    return {"invoice": _public(inv), "result": result}


@router.get("/api/owner/facturation/invoices/{invoice_id}")
def get_invoice(invoice_id: str,
                token_data=Depends(require_role(["business_owner", "manager"]))):
    t = _require_facturation(token_data)
    inv = _db.fact_invoices.find_one({"id": invoice_id, "tenant_id": t["id"]})
    if not inv:
        raise HTTPException(404, "Facture introuvable.")
    # refresh live status if it was already transmitted
    if inv.get("pdp_invoice_id") and inv.get("state") not in (InvoiceState.DRAFT,):
        try:
            st = get_pdp_connector(t).get_status(inv["pdp_invoice_id"])
            if st.get("state") and st["state"] != inv.get("state"):
                # Carry the motif with the state. The connector surfaces it from
                # the PA's errors payload; dropping it here left refusals with
                # no reason on screen (found by the app-through-sandbox run).
                _update_state(invoice_id, st["state"],
                              code=st.get("reject_code"),
                              reason=st.get("reject_reason"))
                inv = _db.fact_invoices.find_one({"id": invoice_id})
        except PdpError:
            pass
    return {"invoice": _public(inv)}


@router.post("/api/owner/facturation/invoices/{invoice_id}/review")
def set_review_status(invoice_id: str, body: Dict[str, Any],
                      token_data=Depends(require_role(["business_owner", "manager", "comptable"]))):
    """Move an invoice through the ACCOUNTING REVIEW state-machine.

    Completely independent of the PA lifecycle: a refused invoice can still be
    reviewed (and then corrected by an avoir), which was impossible while a
    single `state` field existed.

    body: {target: pending_validation|validated|correction_required|unreviewed,
           account_code?, vat_rate?, comment?}
    """
    inv, tenant_id = _resolve_invoice_for_actor(invoice_id, token_data)
    inv = st.ensure(inv)
    target = (body.get("target") or "").strip()
    two_step = bool((_db.tenants.find_one({"id": tenant_id}) or {}).get("require_two_step_review"))
    if not st.review_transition_allowed(inv["review_status"], target, two_step):
        raise HTTPException(
            409,
            f"Transition impossible: {inv['review_status']} → {target}"
            + (" (validation en deux étapes requise)" if two_step else ""),
        )

    # ---- S10: four-eyes (quatre yeux), threshold-based ----------------------
    # A cabinet reviewer may not validate an invoice THEY prepared when it is
    # at or above the cabinet's seuil. Below the seuil self-validation is
    # allowed but permanently marked auto_validated — visible, not hidden.
    # Real cabinets work exactly this way: not everything is double-checked,
    # only what is big or risky; "everything" would deadlock a 2-person firm.
    # Business owners validating their own company's invoices are out of
    # scope — the rule protects the CABINET's chain of responsibility.
    auto_validated = False
    # S11 HARD RULE — the agent NEVER validates. No threshold, no exception,
    # checked before anything else so no code path below can soften it.
    try:
        from features.cabinet_os import is_agent_email
        if target == "validated" and is_agent_email(getattr(token_data, "email", None)):
            raise HTTPException(403, "L'agent FidClic ne valide jamais — une personne doit examiner ce travail.")
    except HTTPException:
        raise
    except Exception:
        pass
    if target == "validated":
        reviewer = getattr(token_data, "email", None)
        preparer = inv.get("created_by")
        if reviewer and preparer and reviewer == preparer:
            mem = None
            try:
                from features.cabinet_os import current_membership
                mem = current_membership(reviewer)
            except Exception:
                mem = None      # not cabinet staff (business owner) → rule doesn't apply
            if mem:
                cab = _db.cabinets.find_one({"id": mem["cabinet_id"]}) or {}
                seuil = float((cab.get("settings") or {}).get("review_threshold_eur", 1000))
                if float(inv.get("total_ttc") or 0) >= seuil:
                    raise HTTPException(
                        409,
                        f"Quatre yeux : cette facture ({inv.get('total_ttc')} € TTC) dépasse le "
                        f"seuil de {seuil:g} € — elle doit être validée par une autre personne "
                        f"que celle qui l'a préparée.")
                auto_validated = True

    upd: Dict[str, Any] = {
        "review_status": target,
        "review_updated_at": _now(),
        "review_updated_by": getattr(token_data, "email", None),
        # Validation makes an entry exportable; un-validating pulls it back
        # (unless it already left for the accounting software).
        "export_status": st.export_status_for_review(target, inv["export_status"]),
        "updated_at": _now(),
    }
    if auto_validated:
        upd["auto_validated"] = True
    for f in ("account_code", "vat_rate", "comment"):
        if body.get(f) is not None:
            upd[f"review_{f}" if f == "comment" else f] = body[f]
    _db.fact_invoices.update_one({"id": invoice_id}, {
        "$set": upd,
        "$push": {"lifecycle": {"family": "review", "state": target, "at": _now(),
                                "by": getattr(token_data, "email", None)}},
    })
    _audit("invoice.review_changed", tenant_id=tenant_id, actor=token_data,
           object_kind="invoice", object_id=invoice_id,
           before={"review_status": inv["review_status"]},
           after={"review_status": target, "export_status": upd["export_status"]},
           detail={"number": inv.get("number"),
                   **({"auto_validated": True} if auto_validated else {})})
    return {"invoice": _public(_db.fact_invoices.find_one({"id": invoice_id}))}


@router.post("/api/owner/facturation/invoices/{invoice_id}/payment")
def set_payment_status(invoice_id: str, body: Dict[str, Any],
                       token_data=Depends(require_role(["business_owner", "manager", "comptable"]))):
    """Record payment reality (unpaid / partially_paid / paid / overdue / disputed).

    v1 is manual. From Zone 4 (banking) this becomes DERIVED from allocations
    and this endpoint stays only for disputes and manual overrides — which is
    why the amount is stored, not just the label.
    """
    inv, _ = _resolve_invoice_for_actor(invoice_id, token_data)
    inv = st.ensure(inv)
    target = (body.get("status") or "").strip()
    valid = {PaymentStatus.UNPAID, PaymentStatus.PARTIALLY_PAID, PaymentStatus.PAID,
             PaymentStatus.OVERDUE, PaymentStatus.DISPUTED}
    if target not in valid:
        raise HTTPException(422, f"Statut de paiement invalide: {target}")
    amount = body.get("amount_paid")
    upd: Dict[str, Any] = {"payment_status": target, "updated_at": _now()}
    if amount is not None:
        upd["amount_paid"] = float(amount)
    if body.get("dispute_reason"):
        upd["dispute_reason"] = body["dispute_reason"]
    _db.fact_invoices.update_one({"id": invoice_id}, {
        "$set": upd,
        "$push": {"lifecycle": {"family": "payment", "state": target, "at": _now(),
                                "by": getattr(token_data, "email", None)}},
    })
    _audit("invoice.payment_changed", tenant_id=inv["tenant_id"], actor=token_data,
           object_kind="invoice", object_id=invoice_id,
           before={"payment_status": inv["payment_status"]},
           after={"payment_status": target, "amount_paid": amount},
           detail={"number": inv.get("number")})
    return {"invoice": _public(_db.fact_invoices.find_one({"id": invoice_id}))}


def _resolve_invoice_for_actor(invoice_id: str, token_data):
    """Find an invoice the caller is actually allowed to touch.

    Owners/managers are scoped to their own tenant. A comptable is scoped to
    the tenants they hold an ACTIVE mandate for — the check lives in
    features.cabinet (single source of truth) and is imported lazily to keep
    these two leaf-modules independent at import time.
    """
    role = getattr(token_data, "role", None)
    if role == "comptable":
        inv = _db.fact_invoices.find_one({"id": invoice_id})
        if not inv:
            raise HTTPException(404, "Facture introuvable.")
        from features.cabinet import assert_mandate      # lazy: avoid load-order coupling
        assert_mandate(getattr(token_data, "email", ""), inv["tenant_id"])
        return inv, inv["tenant_id"]
    t = _require_facturation(token_data)
    inv = _db.fact_invoices.find_one({"id": invoice_id, "tenant_id": t["id"]})
    if not inv:
        raise HTTPException(404, "Facture introuvable.")
    return inv, t["id"]


@router.post("/api/owner/facturation/invoices/{invoice_id}/credit-note")
def create_credit_note(invoice_id: str, body: Dict[str, Any],
                       token_data=Depends(require_role(["business_owner", "manager", "comptable"]))):
    """Correct/cancel a prior invoice with an avoir (credit note).

    Open to the accountant too: fixing a rejected invoice is precisely their
    job, and forcing them to ask the client to click it would put the fix back
    into email — the exact loop this product exists to break.
    """
    orig, tenant_id = _resolve_invoice_for_actor(invoice_id, token_data)
    t = _tenant(tenant_id)
    amount_ht = float(body.get("amount_ht", orig.get("total_ht", 0)))
    amount_vat = float(body.get("amount_vat", orig.get("total_vat", 0)))
    cn = {
        "id": _new_id(),
        "tenant_id": t["id"],
        "original_invoice_id": invoice_id,
        "original_number": orig.get("number"),
        "buyer": orig.get("buyer"),
        "number": body.get("number") or ("AV-" + orig["number"]),
        "amount_ht": amount_ht,
        "amount_vat": amount_vat,
        "amount_ttc": round(amount_ht + amount_vat, 2),
        "reason": body.get("reason"),
        "state": InvoiceState.DRAFT,
        "created_at": _now(),
    }
    _db.fact_credit_notes.insert_one(dict(cn))
    _audit("credit_note.created", tenant_id=t["id"], actor=token_data,
           object_kind="credit_note", object_id=cn["id"],
           after={"number": cn["number"], "amount_ttc": cn["amount_ttc"]},
           detail={"corrects": orig.get("number"), "reason": cn.get("reason"),
                   **(_acting_note(token_data, t) or {})})
    return {"credit_note": _public(cn)}


@router.get("/api/owner/facturation/credit-notes")
def list_credit_notes(token_data=Depends(require_role(["business_owner", "manager"]))):
    """All avoirs (credit notes) issued, newest first."""
    t = _require_facturation(token_data)
    docs = list(_db.fact_credit_notes.find({"tenant_id": t["id"]}).sort("created_at", -1).limit(500))
    return {"credit_notes": [_public(d) for d in docs]}


# --------------------------------------------------------------------------
# received invoices
# --------------------------------------------------------------------------

@router.get("/api/owner/facturation/received")
def list_received(token_data=Depends(require_role(["business_owner", "manager"]))):
    t = _require_facturation(token_data)
    docs = list(_db.fact_received_invoices.find({"tenant_id": t["id"]}).sort("received_at", -1).limit(500))
    return {"received": [_public(d) for d in docs]}


@router.post("/api/owner/facturation/received/sync")
def sync_received(body: Dict[str, Any],
                  token_data=Depends(require_role(["business_owner", "manager", "comptable"]))):
    """Pull supplier invoices from THIS client's PA into FidClic.

    Model B: the connector is chosen per client, so this works no matter which
    PA the client is on. This is the 'pull' complement to the webhook 'push' —
    together they guarantee every client's incoming invoices reach the cabinet,
    regardless of platform.
    """
    t = _tenant_for_actor(token_data, body.get("tenant_id"))
    conn = get_pdp_connector(t)
    account_id = t.get("pdp_account_id") or t["id"]
    try:
        items = conn.list_received(account_id)
    except PdpError as e:
        raise HTTPException(502, f"Synchronisation impossible: {e.message}")
    new = 0
    for it in items:
        rid = it.get("id") or _new_id()
        if _db.fact_received_invoices.find_one({"tenant_id": t["id"], "pdp_received_id": rid}):
            continue
        src = it.get("invoice") or {}
        supplier = src.get("supplier") or src.get("seller") or {}
        ht = float(src.get("total_ht") or 0)
        vat = float(src.get("total_vat") or round(ht * 0.20, 2))
        _db.fact_received_invoices.insert_one({
            "id": _new_id(), "tenant_id": t["id"], "pdp_received_id": rid,
            "supplier": {"name": supplier.get("name") or "Fournisseur",
                         "siren": supplier.get("siren") or "", "is_company": True},
            "number": src.get("number") or "",
            "total_ht": ht, "total_vat": vat, "total_ttc": round(ht + vat, 2) or float(src.get("total_ttc") or 0),
            "state": it.get("state") or InvoiceState.RECEIVED,
            "source": "pa_sync", "received_at": _now()})
        new += 1
    return {"ok": True, "synced": new, "pa_provider": getattr(conn, "provider", "mock")}


@router.post("/api/owner/facturation/received/seed-test")
def seed_test_received(body: Dict[str, Any],
                       token_data=Depends(require_role(["business_owner", "manager", "comptable"]))):
    """TEST-ONLY: inject a fake supplier invoice so the purchases side of the
    Bouclier Fiscal (and the Reçues list) can be exercised with the Mock PA."""
    t = _require_facturation(token_data)
    ht = float(body.get("total_ht", 800))
    vat = round(ht * 0.20, 2)
    rec = {
        "id": _new_id(), "tenant_id": t["id"],
        "supplier": {"name": body.get("supplier_name", "Fournisseur Test SARL"),
                     "siren": body.get("siren", "444444444"), "is_company": True},
        "number": body.get("number", "F-SUP-001"),
        "total_ht": ht, "total_vat": vat, "total_ttc": round(ht + vat, 2),
        "state": InvoiceState.RECEIVED,
        "received_at": _now(),
    }
    _db.fact_received_invoices.insert_one(dict(rec))
    return {"received": _public(rec)}


@router.post("/api/owner/facturation/received/{rid}/mark")
def mark_received(rid: str, body: Dict[str, Any],
                  token_data=Depends(require_role(["business_owner", "manager"]))):
    t = _require_facturation(token_data)
    state = body.get("state")
    if state not in (InvoiceState.ACCEPTED, InvoiceState.REFUSED, InvoiceState.PAID):
        raise HTTPException(422, "État invalide.")
    _db.fact_received_invoices.update_one(
        {"id": rid, "tenant_id": t["id"]}, {"$set": {"state": state}})
    return {"ok": True, "state": state}


# --------------------------------------------------------------------------
# e-reporting (B2C)
# --------------------------------------------------------------------------

@router.post("/api/owner/facturation/ereporting")
def send_ereporting(body: Dict[str, Any],
                    token_data=Depends(require_role(["business_owner", "manager", "comptable"]))):
    """Transmit B2C sales data for a period.

    Either side can trigger it: the legal obligation sits with the BUSINESS, but
    in practice the accountant is the one tracking the deadline. Pass tenant_id
    to act for a client (mandate verified, recorded as on-behalf-of).
    """
    t = _tenant_for_actor(token_data, body.get("tenant_id"))
    report = {
        "id": _new_id(),
        "tenant_id": t["id"],
        "period_start": body.get("period_start"),
        "period_end": body.get("period_end"),
        "totals_by_vat": body.get("totals_by_vat") or {},
        "state": "pending",
        "created_at": _now(),
    }
    try:
        res = get_pdp_connector(t).send_ereporting(t.get("pdp_account_id") or t["id"], report)
        report["state"] = res.get("state", "queued")
        report["pdp_report_id"] = res.get("id")
    except PdpError as e:
        report["state"] = "error"
        report["error"] = e.message
    _db.fact_ereports.insert_one(dict(report))
    _audit("ereporting.sent", tenant_id=t["id"], actor=token_data,
           object_kind="ereport", object_id=report["id"],
           after={"state": report["state"], "period_start": report.get("period_start"),
                  "period_end": report.get("period_end")},
           detail=_acting_note(token_data, t))
    return {"ereport": _public(report)}


# --------------------------------------------------------------------------
# Bouclier Fiscal — coherence indicator (informational, not tax advice)
# --------------------------------------------------------------------------

@router.get("/api/owner/facturation/coherence")
def coherence(token_data=Depends(require_role(["business_owner", "manager"]))):
    """Fiscal Shield v1 — a starter rule-based consistency check.
    Real 3-way (sales/purchases/CA3) coherence lands in a later step; this v1
    flags the obvious issues we already have data for."""
    t = _require_facturation(token_data)
    tid = t["id"]
    b = compute_bouclier(t)

    result = {"id": _new_id(), "tenant_id": tid,
              "score": b["score"], "band": b["band"],
              "alerts": b["alerts"], "breakdown": b["breakdown"], "counts": b["counts"],
              "created_at": _now(),
              "disclaimer": "Indicateur informatif de cohérence — ni conseil fiscal, ni ECF."}
    _db.fact_coherence_checks.insert_one(dict(result))
    return _public(result)


# --------------------------------------------------------------------------
# webhook (public — the PA calls us; no auth, signature-verified)
# --------------------------------------------------------------------------

@router.post("/api/facturation/webhook")
async def facturation_webhook(request: Request):
    raw = await request.body()
    try:
        import json as _json
        event = _json.loads(raw.decode() or "{}")
    except Exception:
        raise HTTPException(400, "Bad payload")
    # Accept the payload shapes we may receive:
    #   flat            {"invoice_id": .., "state": ..}          (MockPdp, tests)
    #   nested invoice  {"invoice": {"id": .., "state": ..}}
    #   B2Brouter live  {"account_id": .., "object": {"object": "invoice",
    #                    "id": .., "state": ..}}                 (verified shape
    #                    from their Flux-10 webhook docs; issued_invoice.state_change
    #                    follows the same envelope)
    obj = event.get("object") if isinstance(event.get("object"), dict) else {}
    pdp_id = (event.get("invoice_id")
              or (event.get("invoice") or {}).get("id")
              or obj.get("id"))
    raw_state = (event.get("state")
                 or (event.get("invoice") or {}).get("state")
                 or obj.get("state"))

    # SECURITY — verify against the connector of the invoice's OWN tenant.
    #
    # The previous code called get_pdp_connector() with no tenant, which
    # resolves to the app-wide default: MockPdp unless PDP_PROVIDER is set,
    # and MockPdp.verify_webhook returns True for everything. Net effect: a
    # public, unauthenticated endpoint where anyone who knew a pdp_invoice_id
    # could flip that invoice's state with a bare curl. Found while preparing
    # the real-webhook test; the parse had to move above the check because the
    # tenant is only knowable from the payload.
    #
    # Looking the invoice up before verifying does not weaken anything: the
    # lookup has no side effects, and signature verification still gates every
    # write. An unknown pdp_id gets a 200 (idempotent no-op) only AFTER the
    # signature check against the strictest available connector.
    inv = _db.fact_invoices.find_one({"pdp_invoice_id": pdp_id}) if pdp_id else None
    if inv:
        t = _db.tenants.find_one({"id": inv["tenant_id"]})
        conn = get_pdp_connector(t)
    else:
        conn = get_pdp_connector()
    if isinstance(conn, MockPdp) and not os.environ.get("FACTURATION_ALLOW_MOCK_WEBHOOK"):
        # A Mock connector cannot authenticate anything. Refusing here closes
        # the open-door default in production; local test runs opt in via env.
        raise HTTPException(401, "Webhook verification unavailable for this tenant")
    if not conn.verify_webhook(dict(request.headers), raw):
        raise HTTPException(401, "Invalid webhook signature")

    if pdp_id and raw_state:
        # A live PA sends its RAW vendor state ('registered', ...), not ours.
        # Writing it straight to the DB skipped the registered->received mapping
        # and left states no screen understands. Normalize through the tenant's
        # own connector when it knows how; Mock/tests already send ours.
        norm = getattr(conn, "_norm_state", None)
        state = norm(raw_state) if callable(norm) else raw_state
        # `inv` was already looked up above for connector resolution.
        if inv:
            _update_state(inv["id"], state)
            # A rejection arriving asynchronously is exactly the one that used
            # to vanish into an inbox — so it becomes a case here too.
            if state in (InvoiceState.REFUSED, InvoiceState.ERROR):
                _open_case(inv["tenant_id"], "pa_rejection",
                           detail_fr=f"Facture {inv.get('number')} refusée (notification plateforme)",
                           related_kind="invoice", related_id=inv["id"],
                           related_ref=inv.get("number"),
                           technical_ref=event.get("reject_code"))
    return {"received": True}


# --------------------------------------------------------------------------
# tiny utils
# --------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    from uuid import uuid4
    return str(uuid4())


def _next_number(tenant_id: str) -> str:
    n = _db.fact_invoices.count_documents({"tenant_id": tenant_id}) + 1
    year = datetime.now(timezone.utc).year
    return f"FAC-{year}-{n:04d}"


def _update_state(invoice_id: str, state: str, pdp_id: Optional[str] = None,
                  code: Optional[str] = None, reason: Optional[str] = None) -> None:
    """Update the PA lifecycle status ONLY (pa_status).

    Review / payment / export statuses live their own lives and are never
    touched here — that separation is the whole point of the S1 refactor.
    `state` is still written as a legacy mirror for one release so a rollback
    remains possible; readers should use pa_status.

    One exception: the PA telling us "paid" (DGFiP 212) is genuine payment
    evidence, so we let it seed payment_status too — but never downgrade a
    payment status that was already set by the cabinet.
    """
    upd: Dict[str, Any] = {
        "pa_status": state,
        "state": state,              # legacy mirror — remove after 1 release
        "updated_at": _now(),
    }
    if state == InvoiceState.PAID:
        inv = _db.fact_invoices.find_one({"id": invoice_id}) or {}
        if st.ensure(dict(inv)).get("payment_status") != PaymentStatus.PAID:
            upd["payment_status"] = PaymentStatus.PAID
    if pdp_id:
        upd["pdp_invoice_id"] = pdp_id
    if code:
        upd["reject_code"] = code
    if reason:
        upd["reject_reason"] = reason
    _db.fact_invoices.update_one({"id": invoice_id}, {
        "$set": upd,
        "$push": {"lifecycle": {"family": "pa", "state": state, "at": _now()}},
    })
