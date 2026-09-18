"""
PdpConnector — the single, PA-agnostic gateway for French e-invoicing.
==================================================================

WHY THIS FILE EXISTS
--------------------
FidClic's "Facturation" module never talks to a Plateforme Agréée (PA)
directly. It talks ONLY to the abstract `PdpConnector` below. Today the
connector is backed by B2Brouter (or a Mock for local dev/testing); if we
ever switch to SUPER PDP / Iopole, we swap ONE adapter class and change one
env var — the rest of the app (endpoints, screens, Fiscal Shield) never
changes. This is the "universal remote" pattern: the app presses the same
buttons; only the TV behind them changes.

WHAT LIVES HERE
---------------
1. A normalized status vocabulary (`InvoiceState`) so the app never sees a
   vendor's raw codes (B2Brouter's 200/202/205/210/212, Iopole's, etc.).
2. The abstract `PdpConnector` interface — every method the app can call.
3. `MockPdp` — an in-memory fake PA for dev + for testing the cases the
   B2Brouter *sandbox cannot* (rejection, duplicate, network failure).
4. `B2BrouterPdp` — the real adapter (urllib, stdlib only — no new deps).
5. `IdempotencyGuard` — duplicate-send protection that lives ABOVE the
   connector, so it works no matter which PA we use (B2Brouter does not
   document a single-invoice idempotency key — verified 2026-07).
6. `get_pdp_connector()` — factory that picks Mock vs B2Brouter from env.

CONVENTIONS (match the rest of the codebase)
--------------------------------------------
- Stdlib HTTP only (urllib) — Vercel Python function, no extra requirements.
- No import of server.py (keep this leaf-level and safe; the live platform
  cannot break from adding this file).
- Every public method returns a plain dict; errors are raised as
  `PdpError` with a machine code + human message the UI can show.

ENV VARS (set in Vercel)
------------------------
  PDP_PROVIDER            "mock" (default) | "b2brouter"
  B2BROUTER_API_KEY       test_... (sandbox) or prod_...
  B2BROUTER_API_VERSION   default "2026-03-02" (min for DGFiP)
  B2BROUTER_BASE_URL      default "https://api.b2brouter.net"
  B2BROUTER_WEBHOOK_SECRET  shared secret for webhook HMAC verification
"""

from __future__ import annotations

import os
import json
import hmac
import time
import uuid
import hashlib
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List


# ---------------------------------------------------------------------------
# 1. Normalized vocabulary — the app ONLY ever sees these values.
# ---------------------------------------------------------------------------

class InvoiceState:
    """PA-agnostic lifecycle states. Adapters map vendor codes → these."""
    DRAFT = "draft"          # created, not sent
    SENT = "sent"            # handed to the PA / deposited (DGFiP 200)
    RECEIVED = "received"    # reached recipient PA (DGFiP 202)
    ACCEPTED = "accepted"    # buyer approved (DGFiP 205)
    REFUSED = "refused"      # buyer rejected (DGFiP 210)
    PAID = "paid"            # payment recorded (DGFiP 212)
    ERROR = "error"          # transmission/validation error


# B2Brouter raw state -> our normalized state.
_B2B_STATE_MAP = {
    "new": InvoiceState.DRAFT,
    "draft": InvoiceState.DRAFT,
    "sent": InvoiceState.SENT,
    "registered": InvoiceState.RECEIVED,
    "accepted": InvoiceState.ACCEPTED,
    "approved": InvoiceState.ACCEPTED,
    "refused": InvoiceState.REFUSED,
    "rejected": InvoiceState.REFUSED,
    "paid": InvoiceState.PAID,
    "error": InvoiceState.ERROR,
}

# Transitions arrive ASYNCHRONOUSLY and can land back to back, so a poll may see
# `registered` and `refused` in quick succession. Consumers must treat states as
# a stream, never as a single final read (B2Brouter sandbox docs, 2026-07-23).
ASYNC_STATES = True


class PdpError(Exception):
    """Raised on any PA failure. `code` is machine-readable, `message` human."""
    def __init__(self, code: str, message: str, http_status: Optional[int] = None):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(f"[{code}] {message}")


# ---------------------------------------------------------------------------
# 2. The interface — every method the Facturation module is allowed to call.
# ---------------------------------------------------------------------------

class PdpConnector(ABC):
    """Abstract gateway. The app depends on THIS, never on a concrete PA."""

    # --- issuing ---
    @abstractmethod
    def create_invoice(self, account_id: str, invoice: Dict[str, Any]) -> Dict[str, Any]:
        """Create a draft invoice from our normalized JSON. Returns {id, state}."""

    @abstractmethod
    def validate(self, invoice_id: str) -> Dict[str, Any]:
        """Check format/rules before sending. Returns {valid: bool, errors: []}."""

    @abstractmethod
    def send(self, invoice_id: str) -> Dict[str, Any]:
        """Transmit the invoice. Returns {id, state}."""

    @abstractmethod
    def get_status(self, invoice_id: str) -> Dict[str, Any]:
        """Poll current lifecycle state. Returns {id, state}."""

    @abstractmethod
    def mark_state(self, invoice_id: str, state: str) -> Dict[str, Any]:
        """Set a state we control (e.g. accept/refuse a received invoice, mark paid)."""

    # --- receiving ---
    @abstractmethod
    def list_received(self, account_id: str) -> List[Dict[str, Any]]:
        """Supplier invoices that arrived for this account."""

    # --- e-reporting (B2C / cross-border) ---
    @abstractmethod
    def send_ereporting(self, account_id: str, report: Dict[str, Any]) -> Dict[str, Any]:
        """Push a B2C/simplified transaction into the daily ledger."""

    # --- directory / annuaire ---
    @abstractmethod
    def lookup_directory(self, country: str, identifier: str) -> Dict[str, Any]:
        """Find a buyer's routing info. May be async (returns {pending: true})."""

    # --- compliance activation (France DGFiP) ---
    @abstractmethod
    def activate_compliance(self, account_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Register the company in the PPF Annuaire + create the DGFiP tax-report setting."""

    # --- webhooks ---
    @abstractmethod
    def verify_webhook(self, headers: Dict[str, str], raw_body: bytes) -> bool:
        """Confirm an incoming webhook truly came from the PA (signature check)."""


# ---------------------------------------------------------------------------
# 3. MockPdp — in-memory fake PA. Dev + tests the sandbox can't do.
# ---------------------------------------------------------------------------

class MockPdp(PdpConnector):
    """
    A fake PA that lives entirely in memory. Two jobs:
      - let us build & run the whole Facturation module with NO account/SIREN;
      - simulate the failure paths the B2Brouter sandbox refuses to (rejection,
        duplicate, network timeout) so Fiscal-Shield/rejection-UX gets tested.

    Test hooks (set on the instance):
      force_next_send = "refused" | "error" | "timeout"  -> next send() behaves so
    """

    def __init__(self):
        self._invoices: Dict[str, Dict[str, Any]] = {}
        self._received: Dict[str, List[Dict[str, Any]]] = {}
        self.force_next_send: Optional[str] = None  # test hook
        self.provider: str = "mock"
        self.placeholder: bool = False

    def create_invoice(self, account_id, invoice):
        inv_id = "mock-" + uuid.uuid4().hex[:12]
        rec = {"id": inv_id, "account_id": account_id, "state": InvoiceState.DRAFT,
               "invoice": invoice, "created_at": time.time()}
        self._invoices[inv_id] = rec
        return {"id": inv_id, "state": InvoiceState.DRAFT}

    def validate(self, invoice_id):
        inv = self._invoices.get(invoice_id)
        if not inv:
            raise PdpError("resource_missing", "Invoice not found", 404)
        errors = []
        data = inv["invoice"]
        # Minimal example rules — extend to mirror AFNOR checks later.
        if not data.get("lines"):
            errors.append("no_lines: invoice has no lines")
        if data.get("buyer", {}).get("siren") in (None, "", "000000000"):
            errors.append("bad_siren: buyer SIREN missing/invalid")
        return {"valid": len(errors) == 0, "errors": errors}

    def send(self, invoice_id):
        inv = self._invoices.get(invoice_id)
        if not inv:
            raise PdpError("resource_missing", "Invoice not found", 404)
        # --- test hooks: simulate what the sandbox won't ---
        hook, self.force_next_send = self.force_next_send, None
        if hook == "timeout":
            raise PdpError("network_timeout", "Simulated network timeout", None)
        if hook == "error":
            inv["state"] = InvoiceState.ERROR
            return {"id": invoice_id, "state": InvoiceState.ERROR,
                    "reject_code": "SYNTAX_ERR",
                    "reject_reason": "Format de facture invalide (simulé)"}
        if hook == "refused":
            inv["state"] = InvoiceState.REFUSED
            return {"id": invoice_id, "state": InvoiceState.REFUSED,
                    "reject_code": "ADR_ERR",
                    "reject_reason": "SIREN de l'acheteur introuvable dans l'annuaire (simulé)"}
        inv["state"] = InvoiceState.SENT
        return {"id": invoice_id, "state": InvoiceState.SENT}

    def get_status(self, invoice_id):
        inv = self._invoices.get(invoice_id)
        if not inv:
            raise PdpError("resource_missing", "Invoice not found", 404)
        return {"id": invoice_id, "state": inv["state"]}

    def mark_state(self, invoice_id, state):
        inv = self._invoices.get(invoice_id)
        if not inv:
            raise PdpError("resource_missing", "Invoice not found", 404)
        inv["state"] = state
        return {"id": invoice_id, "state": state}

    def list_received(self, account_id):
        return self._received.get(account_id, [])

    def send_ereporting(self, account_id, report):
        return {"id": "mock-ledger-" + uuid.uuid4().hex[:8], "state": "queued"}

    def lookup_directory(self, country, identifier):
        # Pretend everyone with a 9-digit SIREN is found on Peppol 0225.
        found = country == "fr" and len(str(identifier)) in (9, 14)
        return {"found": found, "transport": "peppol", "scheme": "0225"} if found \
            else {"found": False}

    def activate_compliance(self, account_id, settings):
        return {"status": "registered", "annuaire": "ok",
                "note": "Mock: annuaire propagation instant (real B2Brouter = up to 24h)"}

    def verify_webhook(self, headers, raw_body):
        return True  # Mock trusts everything

    # test helper: inject a supplier invoice into a client's inbox
    def _seed_received(self, account_id, invoice):
        rec = {"id": "mock-rcv-" + uuid.uuid4().hex[:8], "state": InvoiceState.RECEIVED,
               "invoice": invoice}
        self._received.setdefault(account_id, []).append(rec)
        return rec


# ---------------------------------------------------------------------------
# 4. B2BrouterPdp — the real adapter (stdlib urllib only).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 4b. FidClic invoice  ->  B2Brouter JSON shape
#
# WHY THIS EXISTS
# ---------------
# `B2BrouterPdp.create_invoice` used to assume the caller had already produced
# B2Brouter's shape ("the endpoint layer maps our normalized invoice -> this
# shape"). No such mapping was ever written. With PDP_PROVIDER=mock nothing
# broke, because MockPdp accepts any dict — so the gap was invisible in every
# test. Against the real sandbox it fails immediately: B2Brouter needs `contact`
# and `invoice_lines_attributes`, and FidClic stores `buyer` and `lines`.
#
# The mapping belongs HERE, inside the vendor adapter, not in the endpoint layer.
# That is the whole point of the adapter: the app speaks FidClic, the adapter
# speaks B2Brouter, and swapping PA changes one file.
# ---------------------------------------------------------------------------

# UNCL5305 VAT category codes. B2Brouter (and Factur-X / UBL behind it) require
# a category letter, not just a rate: a 0% line that is "exempt" and a 0% line
# that is "reverse charge" are different documents to the tax authority.
# B2Brouter sandbox test recipients (docs: /en/developers/testing/sandbox/,
# last verified 2026-08-24). Outcome is chosen by the IDENTIFIER, so any contact
# carrying one of these GLNs triggers the scenario. Enriched lifecycle applies to
# PEPPOL invoices only; other channels simply succeed at `sent`.
# The sandbox test recipients are GLNs with no French VAT/SIRET of their own, so
# a cin_value must still be supplied for the contact to validate. Any plausible
# value works — the outcome is chosen by pin_value.
SANDBOX_CIN_PLACEHOLDER = "00000000000000"

SANDBOX_RECIPIENTS = {
    "registered":  {"pin_scheme": "0088", "pin_value": "9508397101047"},
    "refused":     {"pin_scheme": "0088", "pin_value": "9506215594996"},
    "no_receiver": {"pin_scheme": "0088", "pin_value": "9500047420799"},
}


VAT_CAT_STANDARD = "S"   # standard rate
VAT_CAT_ZERO     = "Z"   # zero rated
VAT_CAT_EXEMPT   = "E"   # exempt (art. 261 CGI, franchise en base…)
VAT_CAT_REVERSE  = "AE"  # autoliquidation / reverse charge
VAT_CAT_INTRA    = "K"   # intra-community supply
VAT_CAT_EXPORT   = "G"   # export outside the EU

_EU = {
    "at","be","bg","hr","cy","cz","dk","ee","fi","fr","de","gr","hu","ie","it",
    "lv","lt","lu","mt","nl","pl","pt","ro","sk","si","es","se",
}


def _buyer_country(buyer: Dict[str, Any]) -> str:
    """ISO country for the buyer, wherever it happens to be stored."""
    a = buyer.get("address")
    if isinstance(a, dict) and a.get("country"):
        return str(a["country"]).strip().lower()
    return str(buyer.get("country") or "fr").strip().lower()


def _vat_category(line: Dict[str, Any], buyer: Dict[str, Any]) -> str:
    """Pick the UNCL5305 category for one line.

    Explicit wins: if the line or the invoice already carries a category (set by
    the compliance checks in facturation.py), trust it. Otherwise derive from the
    rate and the buyer's country, which is what a French invoice actually depends on.
    """
    explicit = (line.get("vat_category") or "").strip().upper()
    if explicit:
        return explicit

    rate = float(line.get("vat_rate", 20) or 0)
    if rate > 0:
        return VAT_CAT_STANDARD

    # The country can sit at the top level or inside `address`, depending on how
    # the buyer was created. Resolve it the same way _addr does, or an
    # intra-community supply is silently invoiced as domestic zero-rated.
    country = _buyer_country(buyer)
    if buyer.get("reverse_charge") or line.get("reverse_charge"):
        return VAT_CAT_REVERSE
    if country != "fr":
        return VAT_CAT_INTRA if country in _EU else VAT_CAT_EXPORT
    # Domestic 0% — franchise en base or an exemption, never "zero rated" by default.
    return VAT_CAT_EXEMPT if buyer.get("vat_exempt") or line.get("vat_exempt") else VAT_CAT_ZERO


def _pin(buyer: Dict[str, Any]) -> Dict[str, str]:
    """Routing identifier for the annuaire. France uses SIRET, scheme 0009.

    SIREN (9 digits) is accepted under scheme 0002 but routing in the DGFiP
    annuaire is per-establishment, so SIRET is what actually resolves.

    An explicit `pin_scheme` + `pin_value` on the buyer always wins. That escape
    hatch is what makes B2Brouter's documented sandbox test recipients usable:
    they are GLNs under scheme 0088, not French SIRETs, and sandbox picks the
    simulated outcome from the IDENTIFIER, not from the contact record.
    """
    scheme = (buyer.get("pin_scheme") or "").strip()
    value = (buyer.get("pin_value") or "").replace(" ", "")
    if scheme and value:
        return {"pin_scheme": scheme, "pin_value": value}

    siret = (buyer.get("siret") or "").replace(" ", "")
    if siret:
        return {"pin_scheme": "0009", "pin_value": siret}
    siren = (buyer.get("siren") or "").replace(" ", "")
    if siren:
        return {"pin_scheme": "0002", "pin_value": siren}
    # Last resort: derive the SIREN out of a French VAT number.
    #
    # We used to emit {"pin_scheme": "9957", "pin_value": vat} here. That was
    # wrong: 9957 is NOT part of the ICD 6523 list the DGFiP allows for routing
    # identifiers (Annexe 7 v1.9, G1.73 — 0002/0009/0223/0224/0226/0227/0228/
    # 0229/0238). A VAT number is a *tax* identifier (BT-48, tin_value), not a
    # routing address, so it does not belong in pin_* under any scheme.
    #
    # A French VAT number is FR + 2 check chars + the 9-digit SIREN, so when the
    # buyer record has nothing else we can still recover a legitimate 0002 SIREN
    # from it. Anything non-French, we return nothing rather than guess — an
    # empty pin fails loudly at the PA instead of routing to a bad address.
    vat = (buyer.get("vat_number") or "").replace(" ", "").upper()
    if vat.startswith("FR") and len(vat) == 13 and vat[4:].isdigit():
        return {"pin_scheme": "0002", "pin_value": vat[4:]}
    return {}


def _addr(party: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten whichever address shape the record happens to carry."""
    a = party.get("address")
    if isinstance(a, dict):
        street = a.get("street") or a.get("line1") or ""
        return {"address": street,
                "postalcode": a.get("postal_code") or a.get("postalcode") or "",
                "city": a.get("city") or "",
                "country": (a.get("country") or "fr").lower()}
    return {"address": a or party.get("street") or "",
            "postalcode": party.get("postal_code") or party.get("postalcode") or "",
            "city": party.get("city") or "",
            "country": (party.get("country") or "fr").lower()}


def to_b2brouter_invoice(inv: Dict[str, Any]) -> Dict[str, Any]:
    """FidClic invoice document -> the `invoice` object B2Brouter expects.

    Deliberately does NOT set `send_after_import`; the caller decides, because
    create and send are two separate, separately-auditable actions in FidClic.
    """
    buyer = inv.get("buyer") or {}
    lines = inv.get("lines") or []
    is_company = buyer.get("is_company", True)

    contact = {
        "name": buyer.get("legal_name") or buyer.get("name") or "Client",
        **_addr(buyer),
        # peppol is the transport the DGFiP annuaire routes over for B2B.
        "transport_type_code": "peppol" if is_company else "email",
        **_pin(buyer),
    }
    if buyer.get("email"):
        contact["email"] = buyer["email"]

    # A contact carries THREE different identifiers and they are not interchangeable.
    # Discovered by the sandbox returning 422 parameter_blank:
    #   "Contact tin_value or cin_value can't be blank"
    #
    #   pin_value  routing address   — where the document is delivered (BT-49)
    #   tin_value  tax identifier    — VAT number (BT-48)
    #   cin_value  company identifier— legal registration (SIRET / SIREN)
    #
    # At least one of tin_value / cin_value is mandatory. Sending only pin_* is
    # rejected: the network needs to know where to deliver AND who the party
    # legally is. Our v1 sent a `taxcode` field, which B2Brouter simply ignores.
    if buyer.get("vat_number"):
        contact["tin_value"] = buyer["vat_number"].replace(" ", "").upper()
    cin = (buyer.get("siret") or buyer.get("siren") or "").replace(" ", "")
    if cin:
        contact["cin_value"] = cin

    out_lines = []
    for ln in lines:
        qty = float(ln.get("quantity", 1) or 1)
        price = float(ln.get("unit_price", 0) or 0)
        rate = float(ln.get("vat_rate", 20) or 0)
        out_lines.append({
            "description": ln.get("description") or ln.get("label") or "Prestation",
            "quantity": qty,
            "price": round(price, 2),
            "unit": ln.get("unit") or 1,
            "taxes_attributes": [{
                "category": _vat_category(ln, buyer),
                "name": "VAT",
                "percent": rate,
            }],
        })

    payload: Dict[str, Any] = {
        # B2C simplified invoices are e-reporting (Flux 10), not e-invoicing.
        "type": "IssuedInvoice" if is_company else "IssuedSimplifiedInvoice",
        "number": inv.get("number"),
        "date": inv.get("date"),
        "due_date": inv.get("due_date"),
        "terms": "custom",
        "contact": contact,
        "invoice_lines_attributes": out_lines,
    }

    # Optional fields — only sent when present, because B2Brouter rejects nulls
    # on several of them rather than ignoring them.
    if inv.get("purchase_order"):
        payload["buyer_reference"] = inv["purchase_order"]
    if inv.get("notes"):
        payload["notes"] = inv["notes"]
    if inv.get("supply_date"):
        payload["operation_date"] = inv["supply_date"]
    if inv.get("payment_term"):
        payload["payment_terms"] = inv["payment_term"]
    # 2026 mandatory: "type d'operation" (biens / services / mixte).
    if inv.get("operation_category"):
        payload["operation_category"] = inv["operation_category"]

    return payload


class B2BrouterPdp(PdpConnector):
    """
    Talks to the real B2Brouter API. Sandbox vs production is decided purely by
    the API key prefix (test_ -> sandbox, prod_ -> production), same base URL.
    All B2Brouter-specific quirks (endpoints, state names, headers) are hidden
    here so the rest of the app stays PA-agnostic.
    """

    def __init__(self, api_key: str, api_version: str, base_url: str, webhook_secret: str = ""):
        self.api_key = api_key
        self.api_version = api_version
        self.base_url = base_url.rstrip("/")
        self.webhook_secret = webhook_secret
        self.provider: str = "b2brouter"
        self.placeholder: bool = False

    # -- low-level HTTP (urllib, stdlib) --
    def _request(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        url = self.base_url + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-B2B-API-Key", self.api_key)
        req.add_header("X-B2B-API-Version", self.api_version)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode() or "{}"
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            payload = {}
            try:
                payload = json.loads(e.read().decode() or "{}")
            except Exception:
                pass
            err = payload.get("error", {})
            code = err.get("code") if isinstance(err, dict) else str(err)
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise PdpError(code or "http_error", msg or f"HTTP {e.code}", e.code)
        except urllib.error.URLError as e:
            raise PdpError("network_error", f"Network error: {e.reason}", None)

    @staticmethod
    def _norm_state(raw: Optional[str]) -> str:
        """Map a B2Brouter state onto ours.

        Unknown states used to fall through to ERROR. That was wrong twice over:
        B2Brouter has transient in-flight states (sending, processing, ...) that
        our map does not list, so a poll landing mid-transition reported a
        healthy invoice as ERROR — and the webhook handler opens a rejection
        case on ERROR, meaning a false alarm for the cabinet. Caught by the
        app-through-sandbox run: transitions_seen ['error', 'received'] on a
        perfectly good send. Anything we do not recognise is treated as still
        in flight; only an explicit error/refusal is bad news.
        """
        return _B2B_STATE_MAP.get((raw or "").lower(), InvoiceState.SENT)

    def create_invoice(self, account_id, invoice):
        """Accepts a FidClic invoice document and maps it to B2Brouter's shape.

        A payload that already carries `invoice_lines_attributes` is passed
        through untouched, so callers that build the vendor shape themselves
        (the sandbox smoke test, for one) keep working.
        """
        payload = (invoice if "invoice_lines_attributes" in invoice
                   else to_b2brouter_invoice(invoice))
        r = self._request("POST", f"/accounts/{account_id}/invoices",
                          {"invoice": {**payload, "send_after_import": False}})
        inv = r.get("invoice", r)
        return {"id": inv.get("id"), "state": self._norm_state(inv.get("state"))}

    def validate(self, invoice_id):
        r = self._request("GET", f"/invoices/{invoice_id}/validate")
        # B2Brouter returns validation detail; normalize to valid/errors.
        errors = r.get("errors") or []
        return {"valid": len(errors) == 0, "errors": errors}

    def send(self, invoice_id):
        r = self._request("POST", f"/invoices/send_invoice/{invoice_id}")
        inv = r.get("invoice", r)
        return {"id": invoice_id, "state": self._norm_state(inv.get("state"))}

    def get_status(self, invoice_id):
        r = self._request("GET", f"/invoices/{invoice_id}?include=lines")
        inv = r.get("invoice", r)
        out = {"id": invoice_id, "state": self._norm_state(inv.get("state"))}
        # The reason lives on the single-invoice GET as `errors: [{"error": ...}]`
        # (verified against the live sandbox). Without it the cabinet sees
        # "refusée" with no motif — which is exactly the support call we are
        # trying to prevent. `error_code` is not always present; pass what is.
        errs = inv.get("errors") or []
        reasons = [e.get("error") for e in errs
                   if isinstance(e, dict) and e.get("error")]
        if reasons:
            out["reject_reason"] = " · ".join(reasons)
        if inv.get("error_code"):
            out["reject_code"] = inv["error_code"]
        return out

    def mark_state(self, invoice_id, state):
        # our state -> B2Brouter's mark_as vocabulary
        b2b = {InvoiceState.ACCEPTED: "accepted", InvoiceState.REFUSED: "refused",
               InvoiceState.PAID: "paid"}.get(state, state)
        self._request("POST", f"/invoices/{invoice_id}/mark_as", {"state": b2b})
        return {"id": invoice_id, "state": state}

    def list_received(self, account_id):
        r = self._request("GET", f"/accounts/{account_id}/invoices?type=ReceivedInvoice")
        return r.get("invoices", r if isinstance(r, list) else [])

    def send_ereporting(self, account_id, report):
        # B2C simplified invoice -> daily ledger (Flux 10)
        payload = {"invoice": {**report, "type": "IssuedSimplifiedInvoice",
                               "send_after_import": True}}
        r = self._request("POST", f"/accounts/{account_id}/invoices", payload)
        inv = r.get("invoice", r)
        return {"id": inv.get("id"), "state": "queued"}

    def lookup_directory(self, country, identifier):
        # France: scheme 0009 = SIRET. Async: may return 202 + polling url.
        r = self._request("GET", f"/directory/{country}/0009/{identifier}")
        if r.get("polling_url"):
            return {"pending": True, "polling_url": r["polling_url"]}
        return {"found": True, **r}

    def activate_compliance(self, account_id, settings):
        # settings = {code:"dgfip", start_date, type_operation, naf_code, enterprise_size, ...}
        r = self._request("POST", f"/accounts/{account_id}/tax_report_settings",
                          {"tax_report_setting": {"code": "dgfip", **settings}})
        return {"status": "registered", "raw": r,
                "note": "Annuaire propagation can take up to 24h (DGFiP)."}

    def verify_webhook(self, headers, raw_body):
        # Header: X-B2Brouter-Signature: t=<ts>,s=<hmac_sha256 hex>
        sig = headers.get("X-B2Brouter-Signature") or headers.get("x-b2brouter-signature")
        if not sig or not self.webhook_secret:
            return False
        parts = dict(p.split("=", 1) for p in sig.split(",") if "=" in p)
        ts, s = parts.get("t"), parts.get("s")
        if not ts or not s:
            return False
        payload = f"{ts}.".encode() + raw_body
        computed = hmac.new(self.webhook_secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed, s)


# ---------------------------------------------------------------------------
# 5. IdempotencyGuard — duplicate-send protection, PA-independent.
# ---------------------------------------------------------------------------

class IdempotencyGuard:
    """
    Prevents the same invoice being sent twice (network retries, double clicks).
    Lives ABOVE the connector so it works with ANY PA — B2Brouter does not offer
    a single-invoice idempotency key (verified 2026-07). Persist `seen` in Mongo
    in the endpoint layer; this in-memory version is for tests.

    Usage:
        if guard.already_sent(key): return cached
        result = connector.send(id); guard.mark_sent(key, result)
    """
    def __init__(self):
        self._seen: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def make_key(tenant_id: str, invoice_number: str) -> str:
        return f"{tenant_id}:{invoice_number}"

    def already_sent(self, key: str) -> Optional[Dict[str, Any]]:
        return self._seen.get(key)

    def mark_sent(self, key: str, result: Dict[str, Any]) -> None:
        self._seen[key] = result


# ---------------------------------------------------------------------------
# 6. Factory — one place decides which PA backs the app.
# ---------------------------------------------------------------------------

_singleton: Optional[PdpConnector] = None
_tenant_instances: Dict[str, PdpConnector] = {}   # provider name -> connector

# Which PAs FidClic knows how to route to. "mock" and "b2brouter" have real
# adapters; any other name (iopole, pennylane, ...) is accepted for routing and
# backed by a labelled Mock until its concrete adapter is dropped in — the app
# stays PA-agnostic, so adding a real adapter is a one-class change here.
KNOWN_PROVIDERS = ["b2brouter", "iopole", "pennylane", "mock"]


def _build(provider: str) -> PdpConnector:
    """Construct one connector for a given PA provider name (Multi-PA core)."""
    provider = (provider or "mock").lower()
    if provider == "b2brouter":
        key = os.environ.get("B2BROUTER_API_KEY", "")
        if key:
            c: PdpConnector = B2BrouterPdp(
                api_key=key,
                api_version=os.environ.get("B2BROUTER_API_VERSION", "2026-03-02"),
                base_url=os.environ.get("B2BROUTER_BASE_URL", "https://api.b2brouter.net"),
                webhook_secret=os.environ.get("B2BROUTER_WEBHOOK_SECRET", ""),
            )
            c.provider = "b2brouter"
            return c
        c = MockPdp(); c.provider = "b2brouter"; c.placeholder = True
        return c  # safe fallback: no key -> Mock, never crash
    if provider == "mock":
        c = MockPdp(); c.provider = "mock"; c.placeholder = False
        return c
    # Any other named PA: accepted for per-client routing. Backed by a labelled
    # Mock until we integrate that vendor's real adapter (env {PROVIDER}_API_KEY).
    c = MockPdp(); c.provider = provider
    c.placeholder = not bool(os.environ.get(provider.upper() + "_API_KEY", ""))
    return c


def _tenant_provider(tenant) -> Optional[str]:
    if tenant is None:
        return None
    if isinstance(tenant, dict):
        p = tenant.get("pdp_provider")
    else:
        p = getattr(tenant, "pdp_provider", None)
    return (p or "").lower() or None


def get_pdp_connector(tenant=None) -> PdpConnector:
    """
    Return the connector for a given client (tenant) — the Multi-PA router.

    - If the tenant declares its own `pdp_provider` (Client A -> b2brouter,
      Client B -> iopole, ...), route to THAT PA (cached per provider). This is
      Model B: one cabinet, clients on any platform.
    - Otherwise fall back to the app default from env (PDP_PROVIDER, default
      "mock") — unchanged legacy behaviour, backward compatible.
    """
    global _singleton
    prov = _tenant_provider(tenant)
    if prov:
        if prov not in _tenant_instances:
            _tenant_instances[prov] = _build(prov)
        return _tenant_instances[prov]
    if _singleton is not None:
        return _singleton
    _singleton = _build(os.environ.get("PDP_PROVIDER") or "mock")
    return _singleton


def reset_pdp_connector() -> None:
    """Test helper — clears every cached connector so env/config changes apply."""
    global _singleton
    _singleton = None
    _tenant_instances.clear()
