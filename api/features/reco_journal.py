"""
Le journal des recommandations (user, 2026-10-29, PR-A of « salaah ka
record + seekhti ranking »): every idea FidClic IA shows, on every surface,
and what became of it — so the ranking (PR-B) can learn from each data point.

    shown      the idea was on a page the owner opened: Copilote, Insights,
               Tableau de bord, « FidClic IA a repéré » — rank, € and clients
    opened     its « Créer la campagne » opened the composer (?from= says where)
    dismissed / later / accepted   the Copilote's own buttons
    sent       read from the campaigns: each keeps `reco_key` (and where it
               came from) — sent now, scheduled or by the Autopilot alike
    result     the groupe témoin's answer for that campaign, 15 days after

One row per (shop, idea, surface, kind, Paris day, store view), its count `n`
incremented: a page view is one upsert per idea, never a growing log. No
client id is kept. Writing NEVER breaks a page: any failure is swallowed.

The owner reads, on the card, « La dernière fois : +X € (mesuré avec le
groupe témoin) »; the super admin reads adoption, acceptance, execution and
ROI (GET /api/admin/ai/recos).
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from features.platform_access import require_admin
from models import TokenData

router = APIRouter(tags=["reco-journal"])
_db = None
PARIS = ZoneInfo("Europe/Paris")

SURFACES = {"copilote", "insights", "dashboard", "repere", "clients", "segmentation", "alerte", "autopilot", "autre"}
KINDS = {"shown", "opened", "dismissed", "later", "accepted"}
# « Contacter » one client is not an idea (its key names a client)
ONE_CLIENT = ("client", "brain")
FAMILIES = ("produit", "seg")          # « produit:Coupe » → « produit » in the super admin's table
RESULT_TTL_S = 600


def init(db):
    global _db
    _db = db
    try:
        _db.reco_events.create_index([("tenant_id", 1), ("key", 1), ("surface", 1), ("kind", 1), ("day", 1),
                                      ("store_key", 1)])
        _db.reco_events.create_index([("day", 1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            p = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return p if p.tzinfo else p.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def day_of(at: datetime) -> str:
    return at.astimezone(PARIS).date().isoformat()


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


# ---------------------------------------------------------------------------
# keys
# ---------------------------------------------------------------------------
def clean(key: Any) -> Optional[str]:
    """An idea's key, or None for a message to one client / nothing."""
    k = str(key or "").strip()[:80]
    if not k or k.split(":")[0] in ONE_CLIENT:
        return None
    return k


def key_of(item: Dict[str, Any]) -> Optional[str]:
    """The key an idea goes by on every surface: the composer template its
    button opens, else its own key."""
    if not isinstance(item, dict):
        return None
    cta = item.get("cta") if isinstance(item.get("cta"), dict) else {}
    if cta.get("kind") == "template" and cta.get("template"):
        return clean(cta["template"])
    if item.get("template"):
        return clean(item["template"])
    to = item.get("to")
    if isinstance(to, str) and "template=" in to:
        t = (parse_qs(urlparse(to).query).get("template") or [None])[0]
        if t:
            return clean(t)
    return clean(item.get("key"))


def reco_of(c: Dict[str, Any]) -> Optional[str]:
    """Which idea a campaign came from: its reco_key, else (older campaigns,
    the Autopilot) its template."""
    return clean(c.get("reco_key")) or clean(c.get("template"))


def surface_of(v: Any) -> str:
    s = str(v or "").strip().lower()
    return s if s in SURFACES else "autre"


def family(key: str) -> str:
    head = key.split(":")[0]
    return head if head in FAMILIES else key


# ---------------------------------------------------------------------------
# writing — never in the way
# ---------------------------------------------------------------------------
def _write(ops: List[Any]) -> None:
    if ops:
        _db.reco_events.bulk_write(ops, ordered=False)


def _sector(tid: str) -> Optional[str]:
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "sector": 1}) or {}
    return str(t.get("sector") or "").strip().lower() or None


def _op(tid: str, key: str, surface: str, kind: str, store_key: str, at: datetime,
        extra: Optional[Dict[str, Any]] = None, rank: Optional[int] = None, sector: Optional[str] = None):
    from pymongo import UpdateOne
    upd: Dict[str, Any] = {"$inc": {"n": 1}, "$set": {"last_at": at, "sector": sector, **(extra or {})},
                           "$setOnInsert": {"first_at": at}}
    if rank is not None:
        upd["$min"] = {"rank": rank}
    return UpdateOne({"tenant_id": tid, "key": key, "surface": surface, "kind": kind,
                      "day": day_of(at), "store_key": store_key}, upd, upsert=True)


def shown(tid: Optional[str], surface: str, items: Iterable[Dict[str, Any]], store_key: str = "all",
          at: Optional[datetime] = None) -> None:
    """The ideas a page shows, in their order (1 = first)."""
    try:
        if not tid:
            return
        at = at or _now()
        sector = _sector(tid)
        ops, seen = [], set()
        for rank, item in enumerate(items or [], 1):
            k = key_of(item)
            if not k or k in seen:
                continue
            seen.add(k)
            worth = (item.get("worth") or {}).get("euros") if isinstance(item.get("worth"), dict) else item.get("worth_eur")
            extra = {"worth_eur": _num(worth), "audience": int(_num(item.get("audience") or item.get("count")) or 0)}
            ops.append(_op(tid, k, surface_of(surface), "shown", store_key or "all", at, extra, rank, sector))
        _write(ops)
    except Exception as exc:                            # never in the way of a page
        print(f"reco_journal: shown not recorded ({exc})")


def event(tid: Optional[str], key: Any, kind: str, surface: Any, store_key: str = "all",
          at: Optional[datetime] = None) -> None:
    try:
        k = clean(key)
        if not tid or not k or kind not in KINDS:
            return
        _write([_op(tid, k, surface_of(surface), kind, store_key or "all", at or _now(), sector=_sector(tid))])
    except Exception as exc:
        print(f"reco_journal: {kind} not recorded ({exc})")


# ---------------------------------------------------------------------------
# what an idea brought — the groupe témoin, per campaign
# ---------------------------------------------------------------------------
_SENT_FIELDS = {"_id": 0, "id": 1, "tenant_id": 1, "sent_at": 1, "reco_key": 1, "template": 1, "reco_surface": 1,
                "recipient_ids": 1, "holdout_ids": 1, "reco_result": 1}


def _sent(q: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for c in _db.campaigns.find({**q, "status": "sent"}, _SENT_FIELDS):
        if _aware(c.get("sent_at")) and reco_of(c):
            out.append(c)
    return out


def _result(c: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """What the témoin says of one campaign. Once its 15 days are over the
    answer is final: kept on the campaign (`reco_result`), never recounted."""
    from features import temoin as T
    at = _aware(c["sent_at"])
    base = {"campaign_id": c.get("id"), "sent_at": at.isoformat(), "surface": c.get("reco_surface")}
    if isinstance(c.get("reco_result"), dict):
        return {**base, **c["reco_result"]}
    try:
        b = T.campaign_block(c["tenant_id"], c, now)
    except Exception:
        return {**base, "measured": False, "error": True}
    if not b:                                       # sent without a témoin: never measurable
        res: Dict[str, Any] = {"measured": False}
    else:
        res = {"measured": True, "enough": bool(b.get("enough")), "pending": int(b.get("pending") or 0),
               "extra_revenue": b.get("extra_revenue"), "points": b.get("points"), "ready_on": b.get("ready_on")}
    if not res.get("pending"):
        try:
            _db.campaigns.update_one({"id": c.get("id"), "tenant_id": c.get("tenant_id")},
                                     {"$set": {"reco_result": res, "reco_result_at": now}})
        except Exception:
            pass
    return {**base, **res}


_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def outcomes(tid: str, now: Optional[datetime] = None, fresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """Each idea's latest campaign at this shop, and what the témoin says of it."""
    cached = now is None and not fresh            # a page's « now »: ten minutes of memory
    now = now or _now()
    hit = _cache.get(tid)
    if cached and hit and time.monotonic() - hit[0] < RESULT_TTL_S:
        return hit[1]
    latest: Dict[str, Dict[str, Any]] = {}
    for c in _sent({"tenant_id": tid}):
        k = reco_of(c)
        if k not in latest or _aware(c["sent_at"]) > _aware(latest[k]["sent_at"]):
            latest[k] = c
    out = {k: _result(c, now) for k, c in latest.items()}
    if cached:
        _cache[tid] = (time.monotonic(), out)
    return out


def _eur(n: float) -> str:
    return f"{round(n):,}".replace(",", " ")


def line(o: Optional[Dict[str, Any]]) -> Optional[str]:
    """The owner's one line on the card — only what the témoin can say."""
    if not o or "enough" not in o:
        return None
    if int(o.get("pending") or 0) > 0:
        at = _aware(o.get("sent_at"))
        if not at:
            return None
        ready = at + timedelta(days=15)
        return f"Envoyée le {at.astimezone(PARIS):%d/%m}, résultat le {ready.astimezone(PARIS):%d/%m}"
    if not o.get("enough"):
        return "La dernière fois : trop peu de clients témoins pour conclure"
    x = _num(o.get("extra_revenue"))
    if x is None or x <= 0:
        return "La dernière fois : pas de gain mesuré"
    return f"La dernière fois : +{_eur(x)} € (mesuré avec le groupe témoin)"


def attach(tid: Optional[str], items: Iterable[Dict[str, Any]]) -> None:
    """Puts `last_result` on each idea of a page that has one. Never raises."""
    try:
        if not tid:
            return
        res = outcomes(tid)
        for item in items or []:
            o = res.get(key_of(item) or "")
            text = line(o)
            if text:
                item["last_result"] = {"text": text, "euros": o.get("extra_revenue") if o.get("enough") else None,
                                       "sent_at": o.get("sent_at")}
    except Exception as exc:
        print(f"reco_journal: results not attached ({exc})")


# ---------------------------------------------------------------------------
# Super admin › FIDCLIC AI › Recommandations
# ---------------------------------------------------------------------------
def _pct(a: int, b: int) -> Optional[int]:
    return round(100 * a / b) if b else None


def kpis(since: datetime, until: datetime, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or _now()
    d0, d1 = day_of(since), day_of(until)
    shown_p, opened_p = set(), set()
    by_key: Dict[str, Dict[str, set]] = defaultdict(lambda: {"shown": set(), "opened": set()})
    by_surface: Dict[str, Dict[str, set]] = defaultdict(lambda: {"shown": set(), "opened": set()})
    # grouped in the database: one row per shop × idea × surface × kind, not per day
    groups = _db.reco_events.aggregate([
        {"$match": {"day": {"$gte": d0, "$lte": d1}}},
        {"$group": {"_id": {"t": "$tenant_id", "k": "$key", "s": "$surface", "kind": "$kind"}}},
    ])
    for g in groups:
        r = g.get("_id") or {}
        t, k = r.get("t"), clean(r.get("k"))
        r = {"surface": r.get("s"), "kind": r.get("kind")}
        if not t or not isinstance(t, str) or not k:
            continue
        s = surface_of(r.get("surface"))
        if r.get("kind") == "shown":
            shown_p.add((t, k))
            by_key[family(k)]["shown"].add(t)
            by_surface[s]["shown"].add((t, k))
        elif r.get("kind") in ("opened", "accepted"):
            opened_p.add((t, k))
            by_key[family(k)]["opened"].add(t)
            by_surface[s]["opened"].add((t, k))
    # « Contacter (N) » keeps sent_at as ISO text, the composer as a date: both read
    sent = _sent({"$or": [{"sent_at": {"$gte": since, "$lte": until}},
                          {"sent_at": {"$gte": since.isoformat(), "$lte": until.isoformat()}}]})
    sent_p = {(c["tenant_id"], reco_of(c)) for c in sent}
    res = [(c, _result(c, now)) for c in sent]
    done = [(c, r) for c, r in res if r.get("measured") and r.get("enough") and not r.get("pending")]
    euros = round(sum(_num(r.get("extra_revenue")) or 0.0 for _c, r in done), 2)
    k_sent: Dict[str, int] = defaultdict(int)
    k_meas: Dict[str, int] = defaultdict(int)
    k_eur: Dict[str, float] = defaultdict(float)
    s_sent: Dict[str, int] = defaultdict(int)
    for c in sent:
        k_sent[family(reco_of(c))] += 1
        s_sent[surface_of(c.get("reco_surface"))] += 1
    for c, r in done:
        k_meas[family(reco_of(c))] += 1
        k_eur[family(reco_of(c))] += _num(r.get("extra_revenue")) or 0.0
    tenants = {t for t, _k in shown_p | opened_p | sent_p}
    sectors = {t["id"]: str(t.get("sector") or "autre").strip().lower() or "autre"
               for t in _db.tenants.find({"id": {"$in": list(tenants)}}, {"_id": 0, "id": 1, "sector": 1})}
    by_sector: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"shown": set(), "opened": set(), "sent": 0, "euros": 0.0})
    for t, k in shown_p:
        by_sector[sectors.get(t, "autre")]["shown"].add(t)
    for t, k in opened_p:
        by_sector[sectors.get(t, "autre")]["opened"].add(t)
    for c in sent:
        by_sector[sectors.get(c["tenant_id"], "autre")]["sent"] += 1
    for c, r in done:
        by_sector[sectors.get(c["tenant_id"], "autre")]["euros"] += _num(r.get("extra_revenue")) or 0.0
    shops_shown = {t for t, _k in shown_p}
    shops_opened = {t for t, _k in opened_p}
    keys = set(by_key) | set(k_sent)
    return {
        "since": since.isoformat(), "until": until.isoformat(),
        "totals": {"shops_shown": len(shops_shown), "shops_opened": len(shops_opened),
                   "adoption_pct": _pct(len(shops_opened & shops_shown), len(shops_shown)),
                   "shown": len(shown_p), "opened": len(opened_p), "acceptance_pct": _pct(len(opened_p & shown_p), len(shown_p)),
                   "sent": len(sent), "execution_pct": min(100, _pct(len(sent_p), len(opened_p)) or 0) if opened_p else None,
                   "measured": len(done), "euros": euros, "euros_per_send": round(euros / len(done), 2) if done else None},
        "by_key": sorted(({"key": k, "shops_shown": len(by_key[k]["shown"]) if k in by_key else 0,
                           "shops_opened": len(by_key[k]["opened"]) if k in by_key else 0,
                           "sent": k_sent.get(k, 0), "measured": k_meas.get(k, 0), "euros": round(k_eur.get(k, 0.0), 2)}
                          for k in keys), key=lambda r: (-r["euros"], -r["shops_shown"], r["key"])),
        "by_surface": sorted(({"surface": s, "shown": len(v["shown"]), "opened": len(v["opened"]),
                               "acceptance_pct": _pct(len(v["opened"]), len(v["shown"])), "sent": s_sent.get(s, 0)}
                              for s, v in list(by_surface.items()) + [(s, {"shown": set(), "opened": set()})
                                                                      for s in s_sent if s not in by_surface]),
                             key=lambda r: -r["shown"]),
        "by_sector": sorted(({"sector": s, "shops_shown": len(v["shown"]), "shops_opened": len(v["opened"]),
                              "adoption_pct": _pct(len(v["opened"]), len(v["shown"])), "sent": v["sent"],
                              "euros": round(v["euros"], 2)} for s, v in by_sector.items()),
                            key=lambda r: -r["shops_shown"]),
    }


@router.get("/api/admin/ai/recos")
def admin_recos(days: int = Query(30, ge=1, le=365), token_data: TokenData = Depends(require_admin("ai"))):
    until = _now()
    return kpis(until - timedelta(days=days), until)
