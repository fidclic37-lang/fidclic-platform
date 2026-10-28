"""
Export FEC — Fichier des Écritures Comptables (Livre chapter 5).

Status: 🟢 Core.
Mounts at: /api/cabinet/dossiers/{tid}/fec, /api/owner/facturation/fec
Storage: reads fact_invoices; writes nothing.

WHY THIS EXISTS
    FEC is the ONE file every French accounting product speaks, because the
    DGFiP demands it in any tax audit (art. A47 A-1 LPF): 18 named columns,
    tab-separated, one line per accounting entry. If FidClic can emit a clean
    FEC, a cabinet keeps its Sage/Cegid and lets FidClic feed it — "coexistence,
    not replacement". That is the single feature that opens adoption: we don't
    ask Rousseau to switch her ledger, we become the assistant that types into
    it. Research called re-keying into Sage a 2-days/month intern job; this
    turns it into a 4-minute import.

WHAT WE EMIT
    Only VALIDATED sales invoices (review_status = validated) become entries —
    an unreviewed invoice has no business landing in the books. Each invoice
    becomes a balanced double entry in journal "VE" (ventes):
        DÉBIT  411 Clients                     = TTC
        CRÉDIT 707 Ventes                       = HT      (per VAT rate)
        CRÉDIT 44571 TVA collectée              = VAT     (per VAT rate)
    Débit total == Crédit total, always (the test enforces it).

    Numbers use a comma decimal and no thousands separator (FEC norm);
    the file is tab-separated, one header row + entries, UTF-8.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from auth import require_role

router = APIRouter(tags=["fec"])
_db = None

# The 18 FEC columns, in the mandated order.
FEC_COLUMNS = [
    "JournalCode", "JournalLib", "EcritureNum", "EcritureDate", "CompteNum",
    "CompteLib", "CompAuxNum", "CompAuxLib", "PieceRef", "PieceDate",
    "EcritureLib", "Debit", "Credit", "EcritureLet", "DateLet", "ValidDate",
    "Montantdevise", "Idevise",
]

ACCOUNT_CLIENTS = ("411000", "Clients")
ACCOUNT_TVA = ("445710", "TVA collectée")


def _sales_account(vat_rate: float) -> tuple:
    # One 707 sub-account per rate keeps the ledger readable; a real cabinet
    # remaps these to its own plan comptable, but this is a valid default.
    return ("707000", "Ventes de marchandises")


def init(db):
    global _db
    _db = db


def _now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _fec_date(iso: Optional[str]) -> str:
    """FEC wants YYYYMMDD with no separators."""
    if not iso:
        return _now_compact()
    return str(iso)[:10].replace("-", "")


def _num(x: float) -> str:
    """FEC decimal: comma separator, 2 places, no thousands grouping."""
    return f"{float(x or 0):.2f}".replace(".", ",")


def _aux(buyer: Dict[str, Any]) -> tuple:
    """Auxiliary (client) account — SIREN as the code keeps clients distinct."""
    siren = "".join(ch for ch in str(buyer.get("siren") or "") if ch.isdigit())
    return (("C" + siren) if siren else "CDIVERS",
            (buyer.get("name") or "Client divers")[:100])


def build_fec_lines(invoices: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Turn validated sales invoices into balanced FEC entries."""
    from services import statuses as st
    lines: List[Dict[str, str]] = []
    num = 0
    for inv in invoices:
        inv = st.ensure(inv)
        if inv.get("review_status") != "validated":
            continue
        num += 1
        ecr = f"VE{inv.get('date', '')[:7].replace('-', '')}{num:04d}"
        edate = _fec_date(inv.get("date"))
        pdate = _fec_date(inv.get("date"))
        piece = inv.get("number") or inv["id"][:8]
        lib = f"Facture {piece}"
        aux_num, aux_lib = _aux(inv.get("buyer") or {})
        valid = _fec_date(inv.get("review_updated_at") or inv.get("date"))

        base = {"JournalCode": "VE", "JournalLib": "Ventes",
                "EcritureNum": ecr, "EcritureDate": edate,
                "PieceRef": piece, "PieceDate": pdate, "EcritureLib": lib,
                "EcritureLet": "", "DateLet": "", "ValidDate": valid,
                "Montantdevise": "", "Idevise": ""}

        # DÉBIT 411 — TTC, carries the auxiliary (client) account
        lines.append({**base, "CompteNum": ACCOUNT_CLIENTS[0],
                      "CompteLib": ACCOUNT_CLIENTS[1],
                      "CompAuxNum": aux_num, "CompAuxLib": aux_lib,
                      "Debit": _num(inv.get("total_ttc")), "Credit": "0,00"})

        # CRÉDIT 707 per VAT rate (group the lines) + CRÉDIT 44571 per rate
        by_rate: Dict[float, Dict[str, float]] = {}
        for ln in inv.get("lines", []):
            rate = float(ln.get("vat_rate") or 0)
            ht = float(ln.get("line_total_ht")
                       or float(ln.get("quantity", 1)) * float(ln.get("unit_price", 0)))
            r = by_rate.setdefault(rate, {"ht": 0.0, "vat": 0.0})
            r["ht"] += ht
            r["vat"] += ht * rate / 100.0

        for rate, amt in sorted(by_rate.items()):
            sa_num, sa_lib = _sales_account(rate)
            lines.append({**base, "CompteNum": sa_num, "CompteLib": sa_lib,
                          "CompAuxNum": "", "CompAuxLib": "",
                          "Debit": "0,00", "Credit": _num(round(amt["ht"], 2))})
            if amt["vat"] > 0:
                lines.append({**base, "CompteNum": ACCOUNT_TVA[0],
                              "CompteLib": f"{ACCOUNT_TVA[1]} {rate:g}%",
                              "CompAuxNum": "", "CompAuxLib": "",
                              "Debit": "0,00", "Credit": _num(round(amt["vat"], 2))})
    return lines


def render_fec(lines: List[Dict[str, str]]) -> str:
    """Tab-separated: header + one row per entry line."""
    out = ["\t".join(FEC_COLUMNS)]
    for l in lines:
        out.append("\t".join(l.get(c, "") for c in FEC_COLUMNS))
    return "\n".join(out) + "\n"


def _period(date_from: Any, date_to: Any) -> tuple:
    """The period as plain text — an unresolved Query default (a direct call)
    becomes "" (it used to reach the audit row and make its write fail)."""
    return (date_from if isinstance(date_from, str) else "", date_to if isinstance(date_to, str) else "")


def _audit_export(tenant_id: str, token_data: Any, invoices: List[Dict[str, Any]], date_from: str, date_to: str) -> None:
    from features import audit
    audit.log("fec.exported", tenant_id=tenant_id, actor=token_data, object_kind="tenant", object_id=tenant_id,
              detail={"invoices": len(invoices), "from": date_from, "to": date_to})


def _invoices_for(tenant_id: str, date_from: str, date_to: str) -> List[Dict[str, Any]]:
    date_from, date_to = _period(date_from, date_to)
    q: Dict[str, Any] = {"tenant_id": tenant_id, "review_status": "validated"}
    if date_from or date_to:
        rng = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        q["date"] = rng
    return list(_db.fact_invoices.find(q).sort("date", 1))


def _fec_filename(tenant: Dict[str, Any]) -> str:
    siren = "".join(ch for ch in str(tenant.get("siren") or "") if ch.isdigit()) or "000000000"
    return f"{siren}FEC{_now_compact()}.txt"


# ==========================================================================
# endpoints
# ==========================================================================

@router.get("/api/cabinet/dossiers/{tenant_id}/fec")
def cabinet_fec(tenant_id: str,
                date_from: str = Query("", alias="from"),
                date_to: str = Query("", alias="to"),
                token_data=Depends(require_role(["comptable"]))):
    """Cabinet-side FEC for one client dossier (mandate-scoped)."""
    from features.cabinet import assert_mandate
    assert_mandate(token_data.email, tenant_id)
    tenant = _db.tenants.find_one({"id": tenant_id}) or {}
    date_from, date_to = _period(date_from, date_to)
    invoices = _invoices_for(tenant_id, date_from, date_to)
    body = render_fec(build_fec_lines(invoices))
    _audit_export(tenant_id, token_data, invoices, date_from, date_to)
    return PlainTextResponse(body, headers={
        "Content-Disposition": f'attachment; filename="{_fec_filename(tenant)}"'})


@router.get("/api/owner/facturation/fec")
def owner_fec(date_from: str = Query("", alias="from"),
              date_to: str = Query("", alias="to"),
              token_data=Depends(require_role(["business_owner", "manager"]))):
    """Owner-side FEC for their own company."""
    tenant = _db.tenants.find_one({"id": token_data.tenant_id}) or {}
    date_from, date_to = _period(date_from, date_to)
    invoices = _invoices_for(token_data.tenant_id, date_from, date_to)
    body = render_fec(build_fec_lines(invoices))
    _audit_export(token_data.tenant_id, token_data, invoices, date_from, date_to)
    return PlainTextResponse(body, headers={
        "Content-Disposition": f'attachment; filename="{_fec_filename(tenant)}"'})
