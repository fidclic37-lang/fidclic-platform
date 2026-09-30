"""
Factures FidClic → commerçant, and the Abonnement & facturation page.

WHAT IS INVOICED
    Each subscription payment Stripe reports (invoice.paid) becomes one
    FidClic invoice for the business that paid. Nothing is invented: amounts
    come from Stripe. Where Stripe carries no tax line, the amount paid is read
    as TTC and split at the issuer's VAT rate.

THE ISSUER
    The seller's legal identity is set once by the super-admin
    (/api/admin/invoicing/issuer — decided with the user). Until it is
    complete, payments are recorded and wait; the moment it is complete,
    every waiting payment is invoiced, oldest first, and from then on each
    new payment is invoiced as it arrives.

FRENCH INVOICE RULES (CGI art. 242 nonies A, C. com. L441-9)
    - a unique number in one continuous, chronological series per year
      (FAC-2026-0001, -0002 …), taken atomically, never reused;
    - the issue date, the period of service, the operation category
      (prestation de services);
    - the seller: name, legal form and share capital, head-office address,
      SIREN and RCS, intra-EU VAT number;
    - the buyer: name, address, SIREN/SIRET and VAT number when known;
    - per line: description, quantity, unit price HT, VAT rate; totals HT,
      VAT, TTC — or "TVA non applicable, art. 293 B du CGI" for an issuer
      under the franchise;
    - payment date and method; late-payment penalties (three times the
      legal interest rate) and the 40 € fixed recovery indemnity; no discount
      for early payment.
    An issued invoice is frozen: issuer and buyer are copied onto it, so a
    later change of address never rewrites an old invoice.

Mounts at:
    GET  /api/owner/billing/overview           → the page's Aperçu
    GET  /api/owner/invoices                   → the list
    GET  /api/owner/invoices/{id}/pdf          → the PDF
    POST /api/owner/billing/cancel | /resume   → résiliation (end of period)
    GET/PUT /api/admin/invoicing/issuer        → super-admin
    GET  /api/admin/invoicing/invoices         → super-admin: every invoice
"""
from __future__ import annotations

import io
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth import require_role, TokenData

router = APIRouter(tags=["invoices"])
from features.platform_access import require_admin
_db = None

ISSUER_KEY = "invoice_issuer"
ISSUER_REQUIRED = ("legal_name", "legal_form", "share_capital", "address", "postal_code", "city",
                   "siren", "rcs_city")
PLAN_FEATURE_LIST = {
    "silver": ["Carte de fidélité digitale (Wallet)", "Campagnes push", "Récompenses et paliers",
               "Scan en caisse", "Support par e-mail"],
    "gold": ["Gestion complète de votre programme de fidélité", "Campagnes et automatisations",
             "Push classique et Wallet", "Segmentation avancée", "Géolocalisation", "Parrainage",
             "Analyses détaillées"],
    "vip": ["Gestion complète de votre programme de fidélité", "Campagnes et automatisations",
            "Push classique et Wallet", "Segmentation avancée", "Insights et recommandations IA",
            "Géolocalisation", "Plusieurs établissements", "Support prioritaire"],
    "franchise": ["Tout Pro AI, pour tout votre réseau", "Tous vos établissements, une seule carte",
                  "Limites adaptées à votre réseau", "Tableau de bord par établissement et global",
                  "Accompagnement dédié", "Prix sur devis"],
}


def init(db):
    global _db
    _db = db
    try:
        db.fidclic_invoices.create_index("number", unique=True, partialFilterExpression={"number": {"$type": "string"}})
        db.fidclic_invoices.create_index("stripe_invoice_id", unique=True,
                                         partialFilterExpression={"stripe_invoice_id": {"$type": "string"}})
        db.fidclic_invoices.create_index([("tenant_id", 1), ("issued_at", -1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc)
    if isinstance(v, str) and v:
        try:
            p = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return p if p.tzinfo else p.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _money(x: float) -> float:
    return round(float(x) + 1e-9, 2)


# ---------------------------------------------------------------------------
# The issuer
# ---------------------------------------------------------------------------
def issuer() -> Dict[str, Any]:
    doc = _db.platform_settings.find_one({"key": ISSUER_KEY}, {"_id": 0}) or {}
    data = doc.get("value") or {}
    return {"legal_name": "", "legal_form": "", "share_capital": "", "address": "", "postal_code": "", "city": "",
            "country": "France", "siren": "", "rcs_city": "", "vat_number": "", "vat_applicable": True,
            "vat_rate": 20.0, "email": "", "phone": "", "website": "", "iban": "", "prefix": "FAC", **data}


def issuer_complete(i: Optional[Dict[str, Any]] = None) -> bool:
    i = i or issuer()
    if not all(str(i.get(k) or "").strip() for k in ISSUER_REQUIRED):
        return False
    return (not i.get("vat_applicable")) or bool(str(i.get("vat_number") or "").strip())


# ---------------------------------------------------------------------------
# Recording a payment, issuing an invoice
# ---------------------------------------------------------------------------
def _buyer(tenant: Dict[str, Any]) -> Dict[str, Any]:
    street = tenant.get("street") or (tenant.get("address") or "").split(",")[0].strip()
    return {"name": tenant.get("legal_name") or tenant.get("name") or "",
            "trade_name": tenant.get("name") or "", "address": street,
            "postal_code": tenant.get("postal_code") or "", "city": tenant.get("city") or "",
            "country": {"FR": "France", "BE": "Belgique", "CH": "Suisse", "LU": "Luxembourg", "MC": "Monaco"}
                       .get((tenant.get("country") or "FR").upper(), tenant.get("country") or "France"),
            "siret": tenant.get("siret") or "", "vat_number": tenant.get("vat_number") or "",
            "email": tenant.get("email") or tenant.get("contact_email") or ""}


def record_payment(tenant_id: str, obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """From a Stripe invoice.paid object. Idempotent on the Stripe id."""
    sid = obj.get("id")
    if sid and _db.fidclic_invoices.find_one({"stripe_invoice_id": sid}):
        return None
    tenant = _db.tenants.find_one({"id": tenant_id}) or {}
    cents = lambda k: (obj.get(k) or 0) / 100.0                       # noqa: E731
    lines = []
    for ln in ((obj.get("lines") or {}).get("data") or []):
        period = ln.get("period") or {}
        lines.append({"description": ln.get("description") or "Abonnement FidClic",
                      "quantity": int(ln.get("quantity") or 1),
                      "amount": (ln.get("amount") or 0) / 100.0,
                      "start": _aware(period.get("start")), "end": _aware(period.get("end"))})
    row = {
        "id": str(uuid.uuid4()), "tenant_id": tenant_id, "stripe_invoice_id": sid,
        "status": "awaiting_issuer", "paid_at": _aware((obj.get("status_transitions") or {}).get("paid_at")) or _now(),
        "amount_paid": cents("amount_paid"), "subtotal": cents("subtotal") if obj.get("subtotal") is not None else None,
        "tax": cents("tax") if obj.get("tax") is not None else None, "currency": (obj.get("currency") or "eur").upper(),
        "lines": lines, "plan": tenant.get("plan"),
        "payment_method": obj.get("payment_method_label") or "Carte bancaire (Stripe)",
        "created_at": _now(),
    }
    _db.fidclic_invoices.insert_one(row)
    if issuer_complete():
        return issue(row["id"])
    return row


def _next_number(prefix: str, year: int) -> str:
    from pymongo import ReturnDocument
    doc = _db.invoice_counters.find_one_and_update({"key": f"{prefix}-{year}"}, {"$inc": {"seq": 1}},
                                                   upsert=True, return_document=ReturnDocument.AFTER)
    return f"{prefix}-{year}-{int(doc['seq']):04d}"


def issue(row_id: str) -> Optional[Dict[str, Any]]:
    """Give a recorded payment its number and freeze its parties and totals."""
    row = _db.fidclic_invoices.find_one({"id": row_id}, {"_id": 0})
    if not row or row.get("number"):
        return row
    i = issuer()
    if not issuer_complete(i):
        return row
    tenant = _db.tenants.find_one({"id": row["tenant_id"]}) or {}
    rate = float(i.get("vat_rate") or 20.0) if i.get("vat_applicable") else 0.0
    ttc = _money(row.get("amount_paid") or 0)
    if row.get("tax") and row.get("subtotal") is not None:
        ht, vat = _money(row["subtotal"]), _money(row["tax"])
    elif rate:
        ht = _money(ttc / (1 + rate / 100))
        vat = _money(ttc - ht)
    else:
        ht, vat = ttc, 0.0
    # Lines at their share of the HT total (Stripe lines carry what was paid).
    total_lines = sum(ln["amount"] for ln in row.get("lines") or []) or ttc
    lines = []
    for ln in row.get("lines") or [{"description": "Abonnement FidClic", "quantity": 1, "amount": ttc}]:
        share = (ln["amount"] / total_lines) if total_lines else 1
        line_ht = _money(ht * share)
        q = max(1, int(ln.get("quantity") or 1))
        lines.append({"description": ln.get("description") or "Abonnement FidClic", "quantity": q,
                      "unit_ht": _money(line_ht / q), "total_ht": line_ht, "vat_rate": rate,
                      "start": ln.get("start"), "end": ln.get("end")})
    at = _now()
    year = (_aware(row.get("paid_at")) or at).year
    number = _next_number(i.get("prefix") or "FAC", year)
    _db.fidclic_invoices.update_one({"id": row_id, "number": {"$exists": False}}, {"$set": {
        "number": number, "status": "paid", "issued_at": at,
        "issuer": {k: i.get(k) for k in ("legal_name", "legal_form", "share_capital", "address", "postal_code",
                                         "city", "country", "siren", "rcs_city", "vat_number", "vat_applicable",
                                         "email", "phone", "website", "iban")},
        "buyer": _buyer(tenant), "lines_issued": lines,
        "total_ht": ht, "total_vat": vat, "total_ttc": ttc, "vat_rate": rate,
    }})
    return _db.fidclic_invoices.find_one({"id": row_id}, {"_id": 0})


def issue_waiting() -> int:
    n = 0
    for row in _db.fidclic_invoices.find({"number": {"$exists": False}}, {"_id": 0, "id": 1}).sort("paid_at", 1):
        if (issue(row["id"]) or {}).get("number"):
            n += 1
    return n


# ---------------------------------------------------------------------------
# The PDF
# ---------------------------------------------------------------------------
def _eur(x: float) -> str:
    return f"{x:,.2f} €".replace(",", " ").replace(".", ",")


def _d(v: Any) -> str:
    v = _aware(v)
    return v.strftime("%d/%m/%Y") if v else "—"


def render_pdf(inv: Dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    fonts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
    try:
        pdfmetrics.registerFont(TTFont("DV", os.path.join(fonts, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DVB", os.path.join(fonts, "DejaVuSans-Bold.ttf")))
        R, B = "DV", "DVB"
    except Exception:
        R, B = "Helvetica", "Helvetica-Bold"

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    blue, ink, mute = colors.HexColor("#2F6BFF"), colors.HexColor("#0B1C3F"), colors.HexColor("#64748B")
    s, b = inv.get("issuer") or {}, inv.get("buyer") or {}
    x0, y = 18 * mm, H - 20 * mm

    c.setFillColor(blue); c.setFont(B, 20); c.drawString(x0, y, "FIDCLIC")
    c.setFillColor(ink); c.setFont(B, 16); c.drawRightString(W - x0, y, "FACTURE")
    c.setFont(R, 9.5); c.setFillColor(mute)
    c.drawRightString(W - x0, y - 14, f"N° {inv['number']}")
    c.drawRightString(W - x0, y - 26, f"Date d'émission : {_d(inv.get('issued_at'))}")
    c.drawRightString(W - x0, y - 38, f"Date de paiement : {_d(inv.get('paid_at'))}")

    def block(x, top, title, lines_):
        c.setFillColor(ink); c.setFont(B, 9.5); c.drawString(x, top, title)
        c.setFont(R, 9); c.setFillColor(colors.HexColor("#334155"))
        yy = top - 13
        for t in lines_:
            if t:
                c.drawString(x, yy, t); yy -= 12
        return yy

    seller = [s.get("legal_name"),
              f"{s.get('legal_form') or ''} au capital de {s.get('share_capital') or ''}".strip(),
              s.get("address"), f"{s.get('postal_code') or ''} {s.get('city') or ''}".strip(), s.get("country"),
              f"SIREN {s.get('siren')} — RCS {s.get('rcs_city')}" if s.get("siren") else "",
              f"N° TVA : {s.get('vat_number')}" if s.get("vat_number") else "",
              s.get("email"), s.get("phone")]
    buyer = [b.get("name"), b.get("trade_name") if b.get("trade_name") != b.get("name") else "",
             b.get("address"), f"{b.get('postal_code') or ''} {b.get('city') or ''}".strip(), b.get("country"),
             f"SIRET : {b.get('siret')}" if b.get("siret") else "",
             f"N° TVA : {b.get('vat_number')}" if b.get("vat_number") else "", b.get("email")]
    y1 = block(x0, y - 62, "Émetteur", seller)
    y2 = block(W / 2 + 6 * mm, y - 62, "Client", buyer)
    y = min(y1, y2) - 14

    c.setFont(R, 9); c.setFillColor(mute)
    c.drawString(x0, y, "Catégorie de l'opération : prestation de services")
    y -= 20

    cols = [x0, 112 * mm, 130 * mm, 152 * mm, W - x0]
    c.setFillColor(colors.HexColor("#EEF4FF")); c.rect(x0, y - 4, W - 2 * x0, 16, fill=1, stroke=0)
    c.setFillColor(ink); c.setFont(B, 9)
    c.drawString(cols[0] + 4, y + 1, "Désignation")
    c.drawRightString(cols[2] - 4, y + 1, "Qté")
    c.drawRightString(cols[3] - 4, y + 1, "PU HT")
    c.drawRightString(cols[3] + 16 * mm, y + 1, "TVA")
    c.drawRightString(cols[4] - 4, y + 1, "Total HT")
    y -= 18
    c.setFont(R, 9)
    for ln in inv.get("lines_issued") or []:
        c.setFillColor(ink)
        c.drawString(cols[0] + 4, y, (ln.get("description") or "")[:70])
        if ln.get("start") and ln.get("end"):
            c.setFillColor(mute); c.drawString(cols[0] + 4, y - 11, f"Période du {_d(ln['start'])} au {_d(ln['end'])}")
            c.setFillColor(ink)
        c.drawRightString(cols[2] - 4, y, str(ln.get("quantity") or 1))
        c.drawRightString(cols[3] - 4, y, _eur(ln.get("unit_ht") or 0))
        c.drawRightString(cols[3] + 16 * mm, y, f"{ln.get('vat_rate') or 0:g} %")
        c.drawRightString(cols[4] - 4, y, _eur(ln.get("total_ht") or 0))
        y -= 28
    c.setStrokeColor(colors.HexColor("#E6EEFB")); c.line(x0, y + 10, W - x0, y + 10)

    tx = 130 * mm
    for label, val, bold in (("Total HT", inv.get("total_ht") or 0, False),
                             (f"TVA {inv.get('vat_rate') or 0:g} %", inv.get("total_vat") or 0, False),
                             ("Total TTC", inv.get("total_ttc") or 0, True)):
        c.setFont(B if bold else R, 10 if bold else 9.5); c.setFillColor(ink)
        c.drawString(tx, y - 4, label); c.drawRightString(W - x0, y - 4, _eur(val)); y -= 16
    if not s.get("vat_applicable"):
        c.setFont(R, 8.5); c.setFillColor(mute); c.drawString(tx, y - 4, "TVA non applicable, art. 293 B du CGI"); y -= 14
    paid_txt = f"Payée le {_d(inv.get('paid_at'))} — {inv.get('payment_method') or 'Carte bancaire'}"
    c.setFillColor(colors.HexColor("#E7F7EE"))
    c.roundRect(x0, y - 22, pdfmetrics.stringWidth(paid_txt, B, 9) + 14, 18, 4, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#0F8B58")); c.setFont(B, 9)
    c.drawString(x0 + 7, y - 16, paid_txt)
    y -= 44

    c.setFont(R, 7.8); c.setFillColor(mute)
    legal = ["Paiement à réception. Pas d'escompte pour paiement anticipé.",
             "En cas de retard de paiement : pénalités au taux de trois fois le taux d'intérêt légal, et indemnité "
             "forfaitaire pour frais de recouvrement de 40 € (C. com. art. L441-10 et D441-5).",
             f"{s.get('legal_name') or ''} — {s.get('legal_form') or ''} au capital de {s.get('share_capital') or ''} — "
             f"SIREN {s.get('siren') or ''} — RCS {s.get('rcs_city') or ''}"
             + (f" — TVA {s.get('vat_number')}" if s.get("vat_number") else "")]
    for t in legal:
        for chunk in re.findall(r".{1,120}(?:\s|$)", t):
            c.drawString(x0, y, chunk.strip()); y -= 10
    c.setFont(R, 7.5); c.drawRightString(W - x0, 12 * mm, f"Facture {inv['number']} — page 1/1")
    c.showPage(); c.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Owner endpoints
# ---------------------------------------------------------------------------
def _public(inv: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": inv["id"], "number": inv.get("number"), "status": inv.get("status"),
            "issued_at": (_aware(inv.get("issued_at")) or _now()).isoformat() if inv.get("issued_at") else None,
            "paid_at": _aware(inv.get("paid_at")).isoformat() if inv.get("paid_at") else None,
            "total_ttc": inv.get("total_ttc", inv.get("amount_paid")), "total_ht": inv.get("total_ht"),
            "plan": inv.get("plan")}


@router.get("/api/owner/invoices")
def list_invoices(token_data: TokenData = Depends(require_role(["business_owner"]))):
    rows = list(_db.fidclic_invoices.find({"tenant_id": token_data.tenant_id}, {"_id": 0}).sort("paid_at", -1))
    return {"invoices": [_public(r) for r in rows], "issuer_ready": issuer_complete()}


@router.get("/api/owner/invoices/{inv_id}/pdf")
def invoice_pdf(inv_id: str, token_data: TokenData = Depends(require_role(["business_owner"]))):
    inv = _db.fidclic_invoices.find_one({"id": inv_id, "tenant_id": token_data.tenant_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    if not inv.get("number"):
        raise HTTPException(status_code=409, detail="Cette facture est en cours d'émission.")
    return Response(content=render_pdf(inv), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{inv["number"]}.pdf"'})


def _payment_method(tenant: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The card on file — read from Stripe, kept a few hours."""
    cached = tenant.get("payment_method_cache") or {}
    at = _aware(cached.get("at"))
    if at and _now() - at < timedelta(hours=6):
        return cached.get("card")
    try:
        from features import billing as BL
        if not BL.is_configured() or not tenant.get("stripe_customer_id"):
            return None
        cust = BL.stripe.Customer.retrieve(tenant["stripe_customer_id"],
                                           expand=["invoice_settings.default_payment_method"])
        pm = ((cust.get("invoice_settings") or {}).get("default_payment_method") or {})
        card = pm.get("card") or {}
        out = {"brand": card.get("brand"), "last4": card.get("last4"),
               "exp": f"{int(card['exp_month']):02d}/{card['exp_year']}" if card.get("exp_month") else None} if card else None
        _db.tenants.update_one({"id": tenant["id"]}, {"$set": {"payment_method_cache": {"at": _now(), "card": out}}})
        return out
    except Exception as exc:
        print(f"invoices: payment method unavailable ({exc})")
        return None


@router.get("/api/owner/billing/overview")
def billing_overview(token_data: TokenData = Depends(require_role(["business_owner"]))):
    import server as core
    from features import billing as BL
    from features import plans_public as PP
    tid = token_data.tenant_id
    tenant = _db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    plan = tenant.get("plan") or "silver"
    f = core.features_for(tenant)
    usage = PP.owner_usage(token_data=token_data)
    stores = len([b for b in tenant.get("branches") or [] if b.get("status") != "closed"]) or 1
    renew = _aware(tenant.get("subscription_period_end")) or _aware(tenant.get("trial_ends_at"))
    latest = _db.fidclic_invoices.find_one({"tenant_id": tid}, {"_id": 0}, sort=[("paid_at", -1)])
    catalogue = []
    asked = _db.upgrade_requests.find_one({"tenant_id": tid, "requested_plan": "franchise", "status": "pending"})
    for key in ("silver", "gold", "vip", "franchise"):
        pf = core.features_for(tenant) if key == plan == "franchise" else core.get_plan_features(key)
        quote = key == "franchise"
        catalogue.append({"key": key, "label": pf.get("label"), "price": None if quote and key != plan else pf.get("price"),
                          "on_quote": quote, "requested": bool(asked) if quote else False,
                          "features": PLAN_FEATURE_LIST.get(key, []), "current": key == plan,
                          "limits": {"max_customers": pf.get("max_customers"), "push_per_month": pf.get("push_per_month"),
                                     "campaigns_per_month": pf.get("campaigns_per_month"),
                                     "establishments": pf.get("establishments"), "staff_accounts": pf.get("staff_accounts")}})
    return {
        "configured": BL.is_configured(),
        "plan": {"key": plan, "label": f.get("label"), "price": f.get("price") or None, "on_quote": plan == "franchise",
                 "features": PLAN_FEATURE_LIST.get(plan, [])},
        "status": tenant.get("subscription_status") or ("trialing" if tenant.get("trial_ends_at") else None),
        "cancel_at_period_end": bool(tenant.get("subscription_cancel_at_period_end")),
        "renews_on": renew.isoformat() if renew else None,
        "days_left": max(0, (renew.date() - _now().date()).days) if renew else None,
        "usage": [
            {"key": "new_cards", "label": "Cartes de fidélité créées", **usage["new_cards"]},
            {"key": "campaigns", "label": "Campagnes envoyées", **usage["campaigns"]},
            {"key": "customers", "label": "Clients actifs", **usage["customers"]},
            {"key": "establishments", "label": "Établissements", "used": stores,
             "limit": f.get("establishments") or None},
        ],
        "payment_method": _payment_method(tenant),
        "latest_invoice": _public(latest) if latest else None,
        "catalogue": catalogue,
        "buyer": _buyer(tenant),
    }


class CancelIn(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


def _subscription(tenant: Dict[str, Any]):
    from features import billing as BL
    if not BL.is_configured():
        raise HTTPException(status_code=503, detail="Le paiement en ligne n'est pas encore activé. Contactez le support FidClic.")
    if not tenant.get("stripe_subscription_id"):
        raise HTTPException(status_code=400, detail="Aucun abonnement payant à résilier.")
    return BL


@router.post("/api/owner/billing/cancel")
def cancel(body: CancelIn, token_data: TokenData = Depends(require_role(["business_owner"]))):
    """Résiliation at the end of the paid period — access stays until then."""
    tenant = _db.tenants.find_one({"id": token_data.tenant_id}) or {}
    BL = _subscription(tenant)
    BL.stripe.Subscription.modify(tenant["stripe_subscription_id"], cancel_at_period_end=True)
    _db.tenants.update_one({"id": tenant["id"]}, {"$set": {"subscription_cancel_at_period_end": True,
                                                           "cancel_reason": body.reason, "cancel_requested_at": _now()}})
    return {"cancel_at_period_end": True}


@router.post("/api/owner/billing/resume")
def resume(token_data: TokenData = Depends(require_role(["business_owner"]))):
    tenant = _db.tenants.find_one({"id": token_data.tenant_id}) or {}
    BL = _subscription(tenant)
    BL.stripe.Subscription.modify(tenant["stripe_subscription_id"], cancel_at_period_end=False)
    _db.tenants.update_one({"id": tenant["id"]}, {"$set": {"subscription_cancel_at_period_end": False}})
    return {"cancel_at_period_end": False}


# ---------------------------------------------------------------------------
# Super-admin: the issuer
# ---------------------------------------------------------------------------
class IssuerIn(BaseModel):
    legal_name: str = Field("", max_length=160)
    legal_form: str = Field("", max_length=40)
    share_capital: str = Field("", max_length=40)
    address: str = Field("", max_length=160)
    postal_code: str = Field("", max_length=10)
    city: str = Field("", max_length=80)
    country: str = Field("France", max_length=40)
    siren: str = ""
    rcs_city: str = Field("", max_length=60)
    vat_number: str = Field("", max_length=20)
    vat_applicable: bool = True
    vat_rate: float = Field(20.0, ge=0, le=30)
    email: str = Field("", max_length=120)
    phone: str = Field("", max_length=30)
    website: str = Field("", max_length=120)
    iban: str = Field("", max_length=40)
    prefix: str = Field("FAC", max_length=8)


@router.get("/api/admin/invoicing/issuer")
def get_issuer(token_data: TokenData = Depends(require_admin("facturation"))):
    i = issuer()
    return {"issuer": i, "complete": issuer_complete(i), "required": list(ISSUER_REQUIRED),
            "waiting": _db.fidclic_invoices.count_documents({"number": {"$exists": False}})}


@router.put("/api/admin/invoicing/issuer")
def put_issuer(body: IssuerIn, token_data: TokenData = Depends(require_admin("facturation"))):
    data = body.model_dump()
    data["siren"] = re.sub(r"\D", "", data["siren"])
    if data["siren"] and len(data["siren"]) != 9:
        raise HTTPException(status_code=400, detail="Le SIREN compte 9 chiffres.")
    if not re.fullmatch(r"[A-Z]{1,8}", (data["prefix"] or "FAC").upper()):
        raise HTTPException(status_code=400, detail="Préfixe : lettres uniquement.")
    data["prefix"] = (data["prefix"] or "FAC").upper()
    data["vat_number"] = data["vat_number"].replace(" ", "").upper()
    _db.platform_settings.update_one({"key": ISSUER_KEY}, {"$set": {"key": ISSUER_KEY, "value": data,
                                                                    "updated_at": _now(),
                                                                    "updated_by": getattr(token_data, "email", None)}},
                                     upsert=True)
    issued = issue_waiting() if issuer_complete(data) else 0
    return {**get_issuer(token_data=token_data), "issued_now": issued}


@router.get("/api/admin/invoicing/invoices")
def admin_invoices(token_data: TokenData = Depends(require_admin("facturation"))):
    rows = list(_db.fidclic_invoices.find({}, {"_id": 0}).sort("paid_at", -1).limit(500))
    names = {t["id"]: t.get("name") for t in _db.tenants.find({}, {"_id": 0, "id": 1, "name": 1})}
    return {"invoices": [{**_public(r), "tenant": names.get(r["tenant_id"], r["tenant_id"])} for r in rows]}


@router.get("/api/admin/invoicing/invoices/{inv_id}/pdf")
def admin_invoice_pdf(inv_id: str, token_data: TokenData = Depends(require_admin("facturation"))):
    inv = _db.fidclic_invoices.find_one({"id": inv_id}, {"_id": 0})
    if not inv or not inv.get("number"):
        raise HTTPException(status_code=404, detail="Facture introuvable")
    return Response(content=render_pdf(inv), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{inv["number"]}.pdf"'})
