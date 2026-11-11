"""
Samsung Wallet (user, 2026-11-11: « samsung wallet ka integration krna hai »).

FidClic is a Samsung Wallet partner (Business Account FIDCLIC). One Wallet card
in the Partners Portal — « FidClic », [Wallet] Loyalty › Others, Default layout —
carries every shop's card: each card's data says whose shop it is (name, logo,
colours, banner), read off the SAME pass Apple and Google get
(wallet_passes.build_pass_json), so the stamps, the offer and the QR the till
scans are the same on every phone.

How a card gets to a Galaxy phone (Samsung's « Data Fetch Link »):

    https://a.swallet.link/atw/v3/{certificateId}/{cardId}#Clip?pdata={refId}

The card page opens that link; Samsung then asks us for the card:

    GET  /api/samsung-wallet/cards/{cardId}/{refId}           Get Card Data
    POST /api/samsung-wallet/cards/{cardId}/{refId}?cc2=&event=   Send Card State
                                                           (ADDED, DELETED, …)

`refId` is ours: one per card, random, kept on the customer (`samsung_ref`) —
Samsung asks it to be « in a form that cannot be inferred »; it is the only
thing that opens a card's data, like the owner key of the card page.

When a card changes (a scan, a campaign, the design), Samsung is told with an
Update Notification and fetches the card again:

    POST {callback or https://tsapi-card.walletsvc.samsung.com}/{cc2}/wltex/cards/{cardId}/updates
    Authorization: Bearer <JWS RS256 signed with our key — cty AUTH, ver 3,
                   certificateId, partnerId, utc; claims API {method, path}, refId>
    x-smcs-partner-id, x-request-id

Environment (Partners Portal values; the key and Samsung's certificate stay
out of git — website_antiG/.secrets/samsung-wallet):

    SAMSUNG_WALLET_PARTNER_ID     4164397867037138496
    SAMSUNG_WALLET_CARD_ID        3jina31gjvr00
    SAMSUNG_WALLET_CERT_ID        XVli
    SAMSUNG_WALLET_PRIVATE_KEY    our RSA key (PEM, or the PEM base64-encoded)
    SAMSUNG_WALLET_SAMSUNG_CERT   Samsung's certificate (PEM or base64) — kept
                                  for when Samsung's own calls get verified
    SAMSUNG_WALLET_AUTH_PATH_CC2  "0" to sign the path without its /{cc2}
                                  (Samsung's docs show both; default with)

Samsung documents no way to check that the two calls above come from
Samsung: the refId is the lock, a callback host is only kept when it is
Samsung's own (*.walletsvc.samsung.com, https), and a card state changes only
our own « linked » line — never a visit, a reward or money.
"""
from __future__ import annotations

import base64
import html
import json
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter()
_db = None

CARD_TYPE, CARD_SUBTYPE = "loyalty", "others"
PUBLIC_HOST = "https://tsapi-card.walletsvc.samsung.com"
EVENTS = {"ADDED", "UPDATED", "DELETED", "PROVISIONED"}
_REF_OK = re.compile(r"^[A-Za-z0-9_-]{16,32}$")
_CC2_OK = re.compile(r"^[A-Za-z]{2}$")
MAX_LOCATIONS = 10
LOCATIONS_MAX_CHARS = 1024
LOG_DAYS = 30


def init(db) -> None:
    global _db
    _db = db
    try:
        db.customers.create_index("samsung_ref", unique=True, sparse=True)
        # Samsung asks for a card after every change: its trace is kept 30 days
        db.samsung_wallet_log.create_index("at", expireAfterSeconds=LOG_DAYS * 86400)
        db.samsung_wallet_log.create_index([("customer_id", 1), ("at", -1)])
    except Exception as exc:                       # noqa: BLE001 — an index never stops the start
        print(f"samsung_wallet: index skipped ({exc})")


def _database():
    if _db is not None:
        return _db
    import server as core
    return core.db


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------
def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def partner_id() -> str:
    return _env("SAMSUNG_WALLET_PARTNER_ID")


def card_id() -> str:
    return _env("SAMSUNG_WALLET_CARD_ID")


def cert_id() -> str:
    return _env("SAMSUNG_WALLET_CERT_ID")


def configured() -> bool:
    """The button shows once the portal's three ids are set."""
    return bool(partner_id() and card_id() and cert_id())


def _pem(name: str) -> Optional[str]:
    raw = _env(name)
    if not raw:
        return None
    if "-----BEGIN" in raw:
        return raw.replace("\\n", "\n")
    try:
        return base64.b64decode(raw).decode()
    except Exception:                              # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# the card's refId and its link
# ---------------------------------------------------------------------------
def ref_for(cust: Dict[str, Any]) -> str:
    """This card's refId — made once, kept. Random (22 url-safe characters):
    nothing about the card or the client can lead to it."""
    if cust.get("samsung_ref"):
        return cust["samsung_ref"]
    db = _database()
    for _ in range(3):
        ref = secrets.token_urlsafe(16)            # 22 characters, ≤ Samsung's 32
        res = db.customers.update_one({"id": cust["id"], "samsung_ref": {"$exists": False}},
                                      {"$set": {"samsung_ref": ref}})
        if res.modified_count:
            return ref
        again = db.customers.find_one({"id": cust["id"]}, {"_id": 0, "samsung_ref": 1}) or {}
        if again.get("samsung_ref"):               # a second tap made it first
            return again["samsung_ref"]
    raise HTTPException(status_code=500, detail="Samsung Wallet : identifiant de carte indisponible.")


def add_link(cust: Dict[str, Any]) -> str:
    return f"https://a.swallet.link/atw/v3/{cert_id()}/{card_id()}#Clip?pdata={ref_for(cust)}"


def held(c: Dict[str, Any]) -> bool:
    """In a Samsung Wallet now: Samsung said ADDED and no DELETED since."""
    added, removed = _aware(c.get("samsung_added_at")), _aware(c.get("samsung_removed_at"))
    return bool(added) and not (removed and removed > added)


def _aware(d: Any) -> Optional[datetime]:
    if not isinstance(d, datetime):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# the card data (Get Card Data answer)
# ---------------------------------------------------------------------------
def _cut(v: Any, n: int) -> str:
    s = str(v if v is not None else "").strip()
    return s if len(s) <= n else s[: max(0, n - 1)] + "…"


_URL = re.compile(r"^https?://\S+$")


def notice_html(back: List[Dict[str, Any]], limit: int = 5000) -> str:
    """The back of the card, as Samsung's noticeDesc (HTML): every row the
    Apple pass carries on its back, the owner's own rows included (horaires,
    « Prendre rendez-vous »…). The owner's text is escaped; a value that is a
    link becomes a link."""
    parts: List[str] = []
    for f in back:
        label, value = str(f.get("label") or "").strip(), str(f.get("value") or "").strip()
        if not value:
            continue
        if _URL.match(value):
            text = html.escape(label or value)
            body = f'<a href="{html.escape(value, quote=True)}">{text}</a>'
            parts.append(body)
        else:
            body = html.escape(value).replace("\n", "<br>")
            parts.append(f"<b>{html.escape(label)}</b><br>{body}" if label else body)
    out = ""
    for p in parts:                                    # whole rows only
        nxt = (out + "<br><br>" + p) if out else p
        if len(nxt) > limit:
            break
        out = nxt
    return out


def _geofence(radius: Any) -> str:
    try:
        r = float(radius or 100)
    except (TypeError, ValueError):
        r = 100.0
    return str(int(min(500, max(100, round(r / 100.0) * 100))))


def locations_for(pj: Dict[str, Any], tenant: Dict[str, Any]) -> Optional[str]:
    """The Géolocalisation automation's places (the pass's `locations`, set
    only while its rules hold for this client), as Samsung's `locations`: a
    JSON string ≤ 1024 characters, 10 places at most, each with Samsung's
    radius (100…500 m) and the automation's words."""
    spots = [l for l in (pj.get("locations") or []) if l.get("latitude") is not None and l.get("longitude") is not None]
    if not spots:
        return None
    name = _cut(tenant.get("name") or "Boutique", 40)
    address = _cut(tenant.get("address") or tenant.get("name") or "France", 120)
    out: List[Dict[str, Any]] = []
    for l in spots[:MAX_LOCATIONS]:
        row = {"lat": round(float(l["latitude"]), 6), "lng": round(float(l["longitude"]), 6), "name": name,
               "address": address, "geofenceType": _geofence(l.get("maxDistance")),
               "message": _cut(l.get("relevantText") or name, 120)}
        if len(json.dumps(out + [row], ensure_ascii=False)) > LOCATIONS_MAX_CHARS:
            row["message"] = _cut(row["message"], 40)
            row["address"] = _cut(row["address"], 40)
            if len(json.dumps(out + [row], ensure_ascii=False)) > LOCATIONS_MAX_CHARS:
                break
        out.append(row)
    return json.dumps(out, ensure_ascii=False) if out else None


def _ms(d: Any) -> int:
    a = _aware(d)
    return int((a or datetime.now(timezone.utc)).timestamp() * 1000)


def _https(u: str) -> str:
    return u if u.startswith("https://") else ""


def card_data(payload: Dict[str, Any], ref: str) -> Dict[str, Any]:
    """{"card": …} for Samsung, read off the pass Apple gets."""
    from features import wallet_passes as W
    from features import store_cards as _SC
    from services import card_owner as CO

    @_SC.payload_store
    def build(payload: Dict[str, Any]) -> Dict[str, Any]:
        cust, tenant, card = payload["customer"], payload["tenant"], payload["card"]
        pj = W.build_pass_json(payload)
        sc = (pj.get("storeCard") or pj.get("generic") or {})
        fields = {f["key"]: f for grp in ("headerFields", "primaryFields", "secondaryFields", "auxiliaryFields")
                  for f in sc.get(grp, [])}
        back = [f for f in sc.get("backFields", []) if f.get("key") not in ("card",)]
        serial = cust["barcode_id"]
        org = pj.get("organizationName") or tenant.get("name") or "FidClic"
        colors = W.derive_colors(card)
        fg = colors.get("foregroundColor", "")
        light = "255, 255, 255" in fg or fg.lower() in ("#ffffff", "rgb(255,255,255)")
        progress = fields.get("stamps") or fields.get("reward") or fields.get("points")
        balance = progress.get("value") if progress else None
        if fields.get("stamps") and not re.search(r"\d+\s*/\s*\d+", str(balance or "")):
            filled, total = W._stamp_state(payload)
            balance = f"{filled} / {total}"
        tier = (fields.get("tier") or {}).get("value") or next(
            (f["value"] for f in back if f.get("key") == "tier_back"), None)
        member = (fields.get("member") or {}).get("value") or cust.get("name")
        page = CO.owner_url(W._site_url(), serial)
        logo = _https(W._gw_image_url(tenant["id"], "logo", card))
        strip = (f"{W._site_url()}/api/card/{serial}/wallet-strip.png"
                 f"?v={int(cust.get('visits') or 0)}-{int(time.time()) // 3600}"
                 f"-{(card.get('campaign_offer') or {}).get('id') or 0}")
        attrs: Dict[str, Any] = {
            "title": _cut(org, 32),
            "providerName": _cut(org, 32),
            "merchantName": _cut(org, 32),
            "subtitle1": _cut(member, 32) if member else None,
            "logoImage": logo,
            "appLinkLogo": logo or f"{W._site_url()}/favicon.png",
            "appLinkName": "Ma carte",
            "appLinkData": _cut(page, 256),
            "summaryUrl": _cut(page, 256),
            "bgColor": colors.get("surface_hex"),
            "fontColor": "light" if light else "dark",
            "blinkColor": colors.get("brand_hex"),
            "bgImage": _https(strip),
            "balance": _cut(balance, 32) if balance not in (None, "") else None,
            "level": _cut(tier, 16) if tier else None,
            "barcode.value": W.barcode_message("PKBarcodeFormatQR", serial),
            "barcode.serialType": "QRCODE",
            "barcode.ptFormat": "QRCODESERIAL",
            "barcode.ptSubFormat": "QR_CODE",
            "barcode.errorCorrectionLevel": "M",
            "noticeDesc": notice_html(back),
            "locations": locations_for(pj, tenant),
        }
        cs = {k: v for k, v in (("call", tenant.get("phone")), ("website", tenant.get("website"))) if v}
        if cs.get("website") and not str(cs["website"]).startswith(("http://", "https://")):
            cs["website"] = f"https://{cs['website']}"
        if cs:
            attrs["csInfo"] = json.dumps(cs, ensure_ascii=False)
        attrs = {k: v for k, v in attrs.items() if v not in (None, "")}
        return {"card": {"type": CARD_TYPE, "subType": CARD_SUBTYPE, "data": [{
            "refId": ref, "createdAt": _ms(cust.get("created_at")),
            "updatedAt": max(_ms(cust.get("updated_at")), _ms(None)), "language": "fr", "attributes": attrs}]}}

    return build(payload)


def _customer_by_ref(ref: str) -> Optional[Dict[str, Any]]:
    if not isinstance(ref, str) or not _REF_OK.match(ref):
        return None
    return _database().customers.find_one({"samsung_ref": ref})


@router.get("/api/samsung-wallet/cards/{cid}/{ref}")
def get_card_data(cid: str, ref: str, request: Request, fields: Optional[str] = None):
    """Samsung asks for the card. 204 when there is none to give (Samsung's
    « card doesn't exist »): another card id, an unknown refId, a deleted
    client, a shop whose plan has no Wallet."""
    from features import wallet_passes as W
    if not configured() or cid != card_id():
        return Response(status_code=204)
    cust = _customer_by_ref(ref)
    if not cust or cust.get("deleted_at") or not W._wallet_in_plan(cust.get("barcode_id")):
        return Response(status_code=204)
    _note(cust, "fetched", request)
    payload = W._card_payload(cust["barcode_id"])
    return card_data(payload, ref)


@router.post("/api/samsung-wallet/cards/{cid}/{ref}")
async def send_card_state(cid: str, ref: str, request: Request, cc2: str = "", event: str = ""):
    """Samsung tells us a card was added, updated or deleted. Always 200 —
    Samsung only needs to know we heard; what we keep is checked first."""
    if not configured() or cid != card_id():
        return Response(status_code=200)
    ev = (event or "").strip().upper()
    if ev not in EVENTS:
        return Response(status_code=200)
    cust = _customer_by_ref(ref)
    if not cust:
        return Response(status_code=200)
    try:
        body = await request.json()
    except Exception:                              # noqa: BLE001 — the body is optional
        body = {}
    now = datetime.now(timezone.utc)
    sets: Dict[str, Any] = {"samsung_last_event": {"event": ev, "at": now}}
    if _CC2_OK.match(cc2 or ""):
        sets["samsung_cc2"] = cc2.lower()
    cb = body.get("callback") if isinstance(body, dict) else None
    if _samsung_host(cb):
        sets["samsung_callback"] = cb.rstrip("/")
    if ev == "ADDED":
        sets["samsung_added_at"] = now
    elif ev == "DELETED":
        sets["samsung_removed_at"] = now
    _database().customers.update_one({"id": cust["id"]}, {"$set": sets})
    _note(cust, ev.lower(), request)
    if ev in ("ADDED", "DELETED"):
        try:                                       # Historique: Samsung says so, so it is the client's phone
            import server as core
            core.log_card_event(cust, "Carte ajoutée à Samsung Wallet" if ev == "ADDED"
                                else "Carte retirée de Samsung Wallet", by="le client", at=now)
        except Exception as exc:                   # noqa: BLE001
            print(f"samsung_wallet: card event not logged ({exc})")
    return Response(status_code=200)


def _samsung_host(url: Any) -> bool:
    """A callback we may call later: https, on Samsung's walletsvc domain only
    (anything else would make our server call an address someone typed)."""
    if not isinstance(url, str) or len(url) > 1024:
        return False
    try:
        u = urlparse(url)
    except Exception:                              # noqa: BLE001
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and not u.username and not u.password and \
        (host == "walletsvc.samsung.com" or host.endswith(".walletsvc.samsung.com"))


def _note(cust: Dict[str, Any], kind: str, request: Optional[Request]) -> None:
    """A line of the card's Samsung history (what Samsung asked, and whether
    its Authorization header was there) — to trace a card that won't add."""
    try:
        _database().samsung_wallet_log.insert_one({
            "tenant_id": cust.get("tenant_id"), "customer_id": cust.get("id"), "kind": kind,
            "auth": bool(request and request.headers.get("authorization")),
            "request_id": (request.headers.get("x-request-id") or "")[:40] if request else "",
            "at": datetime.now(timezone.utc)})
    except Exception:                              # noqa: BLE001 — a log never breaks a call
        pass


# ---------------------------------------------------------------------------
# telling Samsung a card changed (Update Notification)
# ---------------------------------------------------------------------------
_KEY_CACHE: Dict[str, Any] = {}


def _signing_key():
    """Our RSA key, read once per value: reading it checks the whole key
    (~100 ms), and every scan of a Samsung card signs a token (load lab
    2026-11-11: read each time, those scans took 3 s)."""
    from cryptography.hazmat.primitives import serialization
    pem = _pem("SAMSUNG_WALLET_PRIVATE_KEY")
    if not pem:
        return None
    if pem in _KEY_CACHE:
        return _KEY_CACHE[pem]
    try:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
    except Exception as exc:                       # noqa: BLE001
        print(f"samsung_wallet: private key unreadable ({exc})")
        return None
    _KEY_CACHE.clear()                             # one key at a time
    _KEY_CACHE[pem] = key
    return key


def auth_token(method: str, path: str, ref: Optional[str] = None) -> Optional[str]:
    """Samsung's REST API Authorization token: a JWS signed with our key."""
    import jwt
    key = _signing_key()
    if key is None:
        return None
    headers = {"alg": "RS256", "cty": "AUTH", "ver": "3", "certificateId": cert_id(),
               "partnerId": partner_id(), "utc": int(time.time() * 1000)}
    claims: Dict[str, Any] = {"API": {"method": method, "path": path}}
    if ref:
        claims["refId"] = ref
    return jwt.encode(claims, key, algorithm="RS256", headers=headers)


def _post(url: str, headers: Dict[str, str], body: Dict[str, Any]) -> int:
    """One call to Samsung (replaced in tests). Returns the HTTP status."""
    import httpx
    r = httpx.post(url, headers=headers, json=body, timeout=4.0)
    return r.status_code


def notify(serials: Iterable[str]) -> Dict[str, Any]:
    """Tell Samsung these cards changed — only the cards Samsung holds now.
    Best effort: a scan never waits on Samsung beyond its few seconds."""
    serials = [s for s in dict.fromkeys(serials) if s]
    if not serials or not configured():
        return {"sent": 0}
    db = _database()
    rows = list(db.customers.find({"barcode_id": {"$in": serials}, "samsung_ref": {"$exists": True}},
                                  {"_id": 0, "id": 1, "samsung_ref": 1, "samsung_added_at": 1, "samsung_removed_at": 1,
                                   "samsung_cc2": 1, "samsung_callback": 1}))
    sent, errors = 0, []
    for c in rows:
        if not held(c):
            continue
        cc2 = c.get("samsung_cc2") if _CC2_OK.match(c.get("samsung_cc2") or "") else "fr"
        host = c.get("samsung_callback") if _samsung_host(c.get("samsung_callback")) else PUBLIC_HOST
        path = f"/{cc2}/wltex/cards/{card_id()}/updates"
        signed = path if os.getenv("SAMSUNG_WALLET_AUTH_PATH_CC2", "1") != "0" else f"/wltex/cards/{card_id()}/updates"
        result: Dict[str, Any] = {"at": datetime.now(timezone.utc)}
        try:
            tok = auth_token("POST", signed, c["samsung_ref"])
            if not tok:
                raise RuntimeError("clé privée Samsung absente")
            status = _post(host + path, {"Authorization": f"Bearer {tok}", "x-smcs-partner-id": partner_id(),
                                         "x-smcs-cc2": cc2, "x-request-id": uuid.uuid4().hex,
                                         "Content-Type": "application/json"},
                           {"card": {"type": CARD_TYPE, "data": [{"refId": c["samsung_ref"], "state": "UPDATED"}]}})
            result["status"] = status
            sent += 1 if 200 <= int(status) < 300 else 0
        except Exception as exc:                   # noqa: BLE001
            result["error"] = str(exc)[:200]
            errors.append(result["error"])
        try:
            db.customers.update_one({"id": c["id"]}, {"$set": {"samsung_last_update": result}})
        except Exception:                          # noqa: BLE001
            pass
    return {"sent": sent, "errors": errors[:3]}


def stats(tenant_id: str) -> Dict[str, Any]:
    """For the owner's Wallet page: how many cards Samsung Wallet holds."""
    rows = _database().customers.find({"tenant_id": tenant_id, "samsung_added_at": {"$exists": True}},
                                      {"_id": 0, "samsung_added_at": 1, "samsung_removed_at": 1})
    return {"configured": configured(), "cards": sum(1 for c in rows if held(c))}
