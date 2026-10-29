"""
CRM › Appels — every prospecting call, logged by the person who made it.

HOW A CALL IS MADE (decided with the user): from the phone. The app opens
the dialer (tel: link), and once the call is over the result, the duration
and the notes are noted here. A recording can be added if there is one.
« Importer depuis mobile » reads the phone's call-log export (CSV, or the
XML of « SMS Backup & Restore » on Android) and keeps only the numbers of
known prospects — an iPhone cannot export its call log.

    crm_calls            one call, done (« termine ») or planned (« planifie »)
    crm_call_recordings  the audio of a call, when one was uploaded

A planned call is also a task (type « appel ») so it shows in Tâches and in
the Calendrier; noting its result closes that task.

FIGURES
    total       every call on file
    effectués   calls done
    réponses    calls done that someone answered (result ≠ sans réponse)
    RDV         calls that got a meeting
    sans rép.   calls nobody answered
"""
from __future__ import annotations

import csv
from services import safe_csv
import io
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth import require_role, TokenData
from features.platform_access import require_admin
from features import crm as C

router = APIRouter(tags=["crm"])
_db = None

RESULTS = [("rdv_obtenu", "RDV obtenu"), ("interesse", "Intéressé"), ("a_relancer", "À relancer"),
           ("rappel_demande", "Rappel demandé"), ("pas_interesse", "Pas intéressé"), ("sans_reponse", "Sans réponse"),
           ("a_qualifier", "À qualifier")]
RESULT_KEYS = [k for k, _ in RESULTS]
STATUSES = [("termine", "Terminé"), ("planifie", "Planifié")]
TABS = ("effectues", "reponses", "rdv", "sans_reponse")
AUDIO = (".mp3", ".m4a", ".wav", ".ogg", ".aac", ".webm", ".amr", ".3gp")
MAX_AUDIO = 12 * 1024 * 1024
MAX_LOG = 5 * 1024 * 1024


def init(db):
    global _db
    _db = db
    try:
        db.crm_calls.create_index("id", unique=True)
        db.crm_calls.create_index([("at", -1)])
        db.crm_calls.create_index([("prospect_id", 1), ("at", -1)])
        db.crm_call_recordings.create_index("call_id", unique=True)
    except Exception:
        pass


def _dur(sec: int) -> str:
    sec = int(sec or 0)
    return f"{sec // 60} min {sec % 60:02d}"


def _tab_filter(tab: str) -> Dict[str, Any]:
    if tab == "effectues":
        return {"status": "termine"}
    if tab == "reponses":
        return {"status": "termine", "result": {"$ne": "sans_reponse"}}
    if tab == "rdv":
        return {"result": "rdv_obtenu"}
    if tab == "sans_reponse":
        return {"result": "sans_reponse"}
    return {}


def _query(q: str = "", sector: str = "", city: str = "", status: str = "", result: str = "", assigned: str = "",
           prospect_id: str = "") -> Dict[str, Any]:
    f: Dict[str, Any] = {}
    if q or sector or city:
        pf = C._filter(q, sector, city)
        ids = [p["id"] for p in _db.crm_prospects.find(pf, {"id": 1})]
        if q:
            rx = {"$regex": re.escape(q.strip()), "$options": "i"}
            f["$or"] = [{"prospect_id": {"$in": ids}}, {"number": rx}, {"notes": rx}]
        else:
            f["prospect_id"] = {"$in": ids}
    if status:
        f["status"] = status
    if result:
        f["result"] = result
    if assigned:
        f["by"] = assigned
    if prospect_id:
        f["prospect_id"] = prospect_id
    return f


def _view(c: Dict[str, Any], users: Dict[str, Dict[str, Any]], names: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    p = names.get(c.get("prospect_id")) or {}
    u = users.get(c.get("by") or "")
    return {"id": c["id"], "at": C._iso(c.get("at")), "status": c.get("status") or "termine",
            "status_label": dict(STATUSES).get(c.get("status") or "termine"),
            "result": c.get("result"), "result_label": dict(RESULTS).get(c.get("result") or "", "—"),
            "direction": c.get("direction") or "sortant", "number": c.get("number") or p.get("phone") or "",
            "duration_sec": int(c.get("duration_sec") or 0), "duration": _dur(c.get("duration_sec") or 0),
            "notes": c.get("notes") or "", "has_recording": bool(c.get("has_recording")), "task_id": c.get("task_id"),
            "prospect_id": c.get("prospect_id"), "prospect": p.get("name"), "sector": p.get("sector"), "city": p.get("city"),
            "stage": p.get("stage"), "contact": p.get("contact_name"), "contact_role": p.get("contact_role"),
            "phone": p.get("phone"), "email": p.get("email"),
            "address": ", ".join(x for x in (p.get("address"), " ".join(y for y in (p.get("postal_code"), p.get("city")) if y)) if x),
            "by": c.get("by"), "by_name": C._name(u) if u else (c.get("by") or None), "source": c.get("source") or "app"}


def _names(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    ids = list({r.get("prospect_id") for r in rows if r.get("prospect_id")})
    return {p["id"]: p for p in _db.crm_prospects.find({"id": {"$in": ids}}, {**C.PROSPECT_CARD, "stage": 1})}


@router.get("/api/crm/calls")
def list_calls(tab: str = "", q: str = "", sector: str = "", city: str = "", status: str = "", result: str = "",
               assigned: str = "", prospect_id: str = "", page: int = 1, per_page: int = 10,
               token_data: TokenData = Depends(require_admin("crm"))):
    page, per_page = max(1, int(page)), max(1, min(200, int(per_page)))
    base = _query(q, sector, city, status, result, assigned, prospect_id)
    counts = {"all": _db.crm_calls.count_documents(base),
              **{t: _db.crm_calls.count_documents({**base, **_tab_filter(t)}) for t in TABS}}
    f = {**base, **_tab_filter(tab if tab in TABS else "")}
    total = _db.crm_calls.count_documents(f)
    rows = list(_db.crm_calls.find(f, {"_id": 0}).sort([("at", -1), ("id", 1)]).skip((page - 1) * per_page).limit(per_page))
    users = C._users()
    names = _names(rows)
    return {"rows": [_view(r, users, names) for r in rows], "total": total, "counts": counts, "page": page,
            "pages": max(1, -(-total // per_page)), "per_page": per_page}


@router.get("/api/crm/calls/summary")
def calls_summary(token_data: TokenData = Depends(require_admin("crm"))):
    now = C._now()
    allc = list(_db.crm_calls.find({}, {"_id": 0, "at": 1, "status": 1, "result": 1, "by": 1}))
    preds = {"total": lambda c: True, "effectues": lambda c: c.get("status") == "termine",
             "reponses": lambda c: c.get("status") == "termine" and c.get("result") != "sans_reponse",
             "rdv": lambda c: c.get("result") == "rdv_obtenu", "sans_reponse": lambda c: c.get("result") == "sans_reponse"}

    def n(pred, a, b):
        return sum(1 for c in allc if pred(c) and C._aware(c.get("at")) and a <= C._aware(c["at"]) < b)

    month, prev = now - timedelta(days=30), now - timedelta(days=60)
    cards = [{"key": k, "value": sum(1 for c in allc if p(c)), "delta": C._delta(n(p, month, now), n(p, prev, month)),
              "series": C._series(lambda a, b, p=p: n(p, a, b), month, now)} for k, p in preds.items()]
    done = [c for c in allc if c.get("status") == "termine" and c.get("result")]
    results = [{"key": k, "label": l, "count": sum(1 for c in done if c["result"] == k)} for k, l in RESULTS]
    users = C._users()
    per_user: Dict[str, int] = {}
    for c in allc:
        if c.get("status") == "termine" and c.get("by"):
            per_user[c["by"]] = per_user.get(c["by"], 0) + 1
    by_user = sorted(({"label": C._name(users[e]) if e in users else e, "count": v} for e, v in per_user.items()),
                     key=lambda r: -r["count"])[:8]
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    days = [today - timedelta(days=d) for d in range(6, -1, -1)]
    per_day = [{"day": d.date().isoformat(), "effectues": n(preds["effectues"], d, d + timedelta(days=1)),
                "reponses": n(preds["reponses"], d, d + timedelta(days=1))} for d in days]
    for rows in (results, by_user):
        tot = sum(r["count"] for r in rows) or 1
        for r in rows:
            r["pct"] = round(r["count"] / tot * 100)
    return {"cards": cards, "results": results, "by_user": by_user, "per_day": per_day,
            "result_options": [{"key": k, "label": l} for k, l in RESULTS],
            "status_options": [{"key": k, "label": l} for k, l in STATUSES]}


@router.get("/api/crm/calls/{cid}")
def get_call(cid: str, token_data: TokenData = Depends(require_admin("crm"))):
    c = _db.crm_calls.find_one({"id": cid}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Appel introuvable")
    users = C._users()
    history = list(_db.crm_calls.find({"prospect_id": c.get("prospect_id")}, {"_id": 0}).sort("at", -1).limit(50)) \
        if c.get("prospect_id") else [c]
    names = _names(history)
    notes = list(_db.crm_activities.find({"prospect_id": c.get("prospect_id"), "type": "note"}, {"_id": 0}).sort("at", -1).limit(50)) \
        if c.get("prospect_id") else []
    return {**_view(c, users, names), "history": [_view(h, users, names) for h in history],
            "prospect_notes": [{"text": a.get("text"), "at": C._iso(a.get("at")),
                                "by_name": C._name(users[a["by"]]) if a.get("by") in users else a.get("by")} for a in notes]}


class CallIn(BaseModel):
    prospect_id: Optional[str] = None
    status: Optional[str] = None
    result: Optional[str] = None
    at: Optional[str] = None
    duration_sec: Optional[int] = Field(None, ge=0, le=6 * 3600)
    notes: Optional[str] = Field(None, max_length=4000)
    direction: Optional[str] = None
    number: Optional[str] = Field(None, max_length=40)
    by: Optional[str] = None


FUNNEL_BUMP = {"contacte": ("nouveau", "a_contacter"), "rdv": ("nouveau", "a_contacter", "contacte")}


def _after_call(p: Dict[str, Any], result: str, by: str) -> None:
    """A reached prospect is « Contacté »; one who took a meeting is at
    « Rendez-vous ». Only ever forward, never for a business on FidClic."""
    if not p or p.get("tenant_id"):
        return
    to = "rdv" if result == "rdv_obtenu" else ("contacte" if result not in ("sans_reponse", "a_qualifier") else None)
    if to and (p.get("stage") or "nouveau") in FUNNEL_BUMP[to]:
        _db.crm_prospects.update_one({"id": p["id"]}, {"$set": {"stage": to, "updated_at": C._now()}})
        C._log(p["id"], "stage", f"Étape : {dict(C.STAGES)[to]} (après un appel)", by, frm=p.get("stage"), to=to)


def _log_call(c: Dict[str, Any], by: str) -> None:
    if c.get("prospect_id") and c.get("status") == "termine":
        C._log(c["prospect_id"], "call", f"Appel — {dict(RESULTS).get(c.get('result'), '—')} ({_dur(c.get('duration_sec'))})",
               by, at=C._aware(c.get("at")), call_id=c["id"], result=c.get("result"))


@router.post("/api/crm/calls")
def add_call(body: CallIn, token_data: TokenData = Depends(require_admin("crm"))):
    p = _db.crm_prospects.find_one({"id": body.prospect_id}, {"_id": 0}) if body.prospect_id else None
    if not p:
        raise HTTPException(status_code=400, detail="Choisissez le commerce appelé.")
    status = body.status or "termine"
    if status not in dict(STATUSES):
        raise HTTPException(status_code=400, detail="Statut inconnu.")
    at = C._aware(body.at) or C._now()
    by = body.by if body.by and body.by in C._users() else token_data.email
    c = {"id": uuid.uuid4().hex, "prospect_id": p["id"], "status": status, "at": at, "by": by,
         "number": (body.number or p.get("phone") or "").strip(), "direction": body.direction if body.direction in ("sortant", "entrant") else "sortant",
         "notes": (body.notes or "").strip(), "created_at": C._now(), "source": "app"}
    if status == "termine":
        if body.result not in RESULT_KEYS:
            raise HTTPException(status_code=400, detail="Indiquez le résultat de l'appel.")
        planned = _db.crm_calls.find_one({"prospect_id": p["id"], "status": "planifie", "at": {"$lte": C._now() + timedelta(hours=24)}},
                                         {"_id": 0}, sort=[("at", 1)])
        if planned:        # this is the call that was planned: complete it rather than leave it open
            return edit_call(planned["id"], CallIn(result=body.result, duration_sec=body.duration_sec,
                                                   notes=body.notes or planned.get("notes"), at=at.isoformat()), token_data=token_data)
        c.update(result=body.result, duration_sec=int(body.duration_sec or 0))
    else:
        if at < C._now() - timedelta(minutes=5):
            raise HTTPException(status_code=400, detail="Un appel planifié doit être dans le futur.")
        task = {"id": uuid.uuid4().hex, "title": f"Appeler {p.get('name')}", "type": "appel", "priority": "moyenne",
                "due_at": at, "prospect_id": p["id"], "assigned_to": by, "description": c["notes"], "status": "a_faire",
                "duration_min": 15, "confirm_status": "a_confirmer", "created_by": token_data.email, "created_at": C._now()}
        _db.crm_tasks.insert_one(task)
        c["task_id"] = task["id"]
    _db.crm_calls.insert_one(c)
    if status == "termine":
        _log_call(c, token_data.email)
        _after_call(p, c["result"], token_data.email)
    return _view(c, C._users(), _names([c]))


@router.put("/api/crm/calls/{cid}")
def edit_call(cid: str, body: CallIn, token_data: TokenData = Depends(require_admin("crm"))):
    c = _db.crm_calls.find_one({"id": cid}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Appel introuvable")
    d = body.dict(exclude_unset=True)
    sets: Dict[str, Any] = {}
    if "result" in d:
        if d["result"] not in RESULT_KEYS:
            raise HTTPException(status_code=400, detail="Résultat inconnu.")
        sets["result"] = d["result"]
    for k in ("duration_sec", "notes"):
        if k in d and d[k] is not None:
            sets[k] = d[k].strip() if isinstance(d[k], str) else d[k]
    if d.get("at"):
        sets["at"] = C._aware(d["at"]) or c["at"]
    completing = c.get("status") == "planifie" and (d.get("status") == "termine" or "result" in d)
    if completing:
        if not sets.get("result"):
            raise HTTPException(status_code=400, detail="Indiquez le résultat de l'appel.")
        sets["status"] = "termine"
        sets.setdefault("at", C._now())
        if c.get("task_id"):
            _db.crm_tasks.update_one({"id": c["task_id"]}, {"$set": {"status": "terminee", "done_at": C._now()}})
    if sets:
        _db.crm_calls.update_one({"id": cid}, {"$set": sets})
    c = _db.crm_calls.find_one({"id": cid}, {"_id": 0})
    if completing:
        _log_call(c, token_data.email)
        _after_call(_db.crm_prospects.find_one({"id": c.get("prospect_id")}, {"_id": 0}), c["result"], token_data.email)
    return _view(c, C._users(), _names([c]))


@router.delete("/api/crm/calls/{cid}")
def delete_call(cid: str, token_data: TokenData = Depends(require_admin("crm"))):
    c = _db.crm_calls.find_one({"id": cid}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Appel introuvable")
    if token_data.role != "super_admin" and c.get("by") != token_data.email:
        raise HTTPException(status_code=403, detail="Seul l'auteur de l'appel peut le supprimer.")
    _db.crm_calls.delete_one({"id": cid})
    _db.crm_call_recordings.delete_one({"call_id": cid})
    if c.get("task_id") and c.get("status") == "planifie":
        _db.crm_tasks.delete_one({"id": c["task_id"]})
    _db.crm_activities.delete_many({"type": "call", "meta.call_id": cid})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------
@router.post("/api/crm/calls/{cid}/recording")
async def upload_recording(cid: str, file: UploadFile = File(...), token_data: TokenData = Depends(require_admin("crm"))):
    if not _db.crm_calls.find_one({"id": cid}):
        raise HTTPException(status_code=404, detail="Appel introuvable")
    name = (file.filename or "").lower()
    if not name.endswith(AUDIO) and not (file.content_type or "").startswith("audio/"):
        raise HTTPException(status_code=400, detail="Formats acceptés : MP3, M4A, WAV, OGG, AAC.")
    data = await file.read()
    if len(data) > MAX_AUDIO:
        raise HTTPException(status_code=413, detail="Enregistrement trop lourd (12 Mo maximum).")
    if not data:
        raise HTTPException(status_code=400, detail="Fichier vide.")
    ctype = file.content_type if (file.content_type or "").startswith("audio/") else "audio/mpeg"
    _db.crm_call_recordings.replace_one({"call_id": cid}, {"call_id": cid, "data": data, "content_type": ctype,
                                                            "filename": file.filename, "size": len(data),
                                                            "by": token_data.email, "at": C._now()}, upsert=True)
    _db.crm_calls.update_one({"id": cid}, {"$set": {"has_recording": True}})
    return {"ok": True, "size": len(data)}


@router.get("/api/crm/calls/{cid}/recording")
def get_recording(cid: str, token_data: TokenData = Depends(require_admin("crm"))):
    r = _db.crm_call_recordings.find_one({"call_id": cid})
    if not r:
        raise HTTPException(status_code=404, detail="Pas d'enregistrement")
    fn = re.sub(r"[^\w.\-]", "_", r.get("filename") or f"appel-{cid}.mp3")
    return Response(content=bytes(r["data"]), media_type=r.get("content_type") or "audio/mpeg",
                    headers={"Content-Disposition": f'inline; filename="{fn}"', "Cache-Control": "private, no-store"})


@router.delete("/api/crm/calls/{cid}/recording")
def delete_recording(cid: str, token_data: TokenData = Depends(require_admin("crm"))):
    _db.crm_call_recordings.delete_one({"call_id": cid})
    _db.crm_calls.update_one({"id": cid}, {"$set": {"has_recording": False}})
    return {"ok": True}


# ---------------------------------------------------------------------------
# « Importer depuis mobile » — the phone's call log
# ---------------------------------------------------------------------------
_NUM = ("numero", "number", "phone", "telephone", "tel", "numéro", "téléphone", "contact number")
_DATE = ("date", "datetime", "date et heure", "time", "heure", "call date", "start")
_DUR = ("duree", "durée", "duration", "length", "secondes", "seconds")
_TYPE = ("type", "direction", "sens", "call type")


def _secs(v: str) -> int:
    v = (v or "").strip().lower()
    if not v:
        return 0
    if re.fullmatch(r"\d+", v):
        return int(v)
    m = re.fullmatch(r"(?:(\d+):)?(\d+):(\d{1,2})", v)
    if m:
        return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    total = 0
    for n, unit in re.findall(r"(\d+)\s*(h|min|m|s|sec)", v):
        total += int(n) * {"h": 3600, "min": 60, "m": 60, "s": 1, "sec": 1}[unit]
    return total


def _when(v: str) -> Optional[datetime]:
    v = (v or "").strip()
    if re.fullmatch(r"\d{12,13}", v):                      # Android epoch in ms
        return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc)
    if re.fullmatch(r"\d{9,10}", v):
        return datetime.fromtimestamp(int(v), tz=timezone.utc)
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y, %H:%M", "%d-%m-%Y %H:%M", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(v, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return C._aware(v)


def _dir(v: str) -> str:
    v = (v or "").strip().lower()
    if v in ("1", "incoming", "entrant", "entrante", "reçu", "recu", "in"):
        return "entrant"
    if v in ("3", "5", "missed", "manqué", "manque", "rejected", "rejeté", "refusé"):
        return "manque"
    return "sortant"


def parse_call_log(name: str, data: bytes) -> List[Dict[str, Any]]:
    text = data.decode("utf-8-sig", errors="replace")
    out: List[Dict[str, Any]] = []
    if name.endswith(".xml") or text.lstrip().startswith("<"):
        root = ET.fromstring(text)
        for el in root.iter("call"):
            out.append({"number": el.get("number") or "", "at": _when(el.get("date") or ""),
                        "duration_sec": _secs(el.get("duration") or ""), "direction": _dir(el.get("type") or ""),
                        "name": el.get("contact_name") or ""})
        return out
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        return out
    head = [C._fold(h) for h in rows[0]]

    def col(keys):
        for i, h in enumerate(head):
            if any(C._fold(k) == h or C._fold(k) in h.split() for k in keys):
                return i
        return None
    ni, di, du, ti = col(_NUM), col(_DATE), col(_DUR), col(_TYPE)
    if ni is None:
        raise ValueError("colonne « numéro » introuvable")
    for r in rows[1:]:
        g = lambda i: (r[i] if i is not None and i < len(r) else "")   # noqa: E731
        if not C._digits(g(ni)):
            continue
        out.append({"number": g(ni).strip(), "at": _when(g(di)), "duration_sec": _secs(g(du)), "direction": _dir(g(ti)), "name": ""})
    return out


def _prospects_by_number() -> Dict[str, Dict[str, Any]]:
    out = {}
    for p in _db.crm_prospects.find({"phone": {"$nin": [None, ""]}}, {"_id": 0, "id": 1, "name": 1, "phone": 1, "tenant_id": 1, "stage": 1}):
        d = C._digits(p["phone"])
        if len(d) >= 9:
            out[d[-9:]] = p
    return out


@router.post("/api/crm/calls/import/preview")
async def import_calls_preview(file: UploadFile = File(...), token_data: TokenData = Depends(require_admin("crm"))):
    data = await file.read()
    if len(data) > MAX_LOG:
        raise HTTPException(status_code=413, detail="Fichier trop lourd (5 Mo maximum).")
    name = (file.filename or "").lower()
    if not name.endswith((".csv", ".txt", ".tsv", ".xml")):
        raise HTTPException(status_code=400, detail="Formats acceptés : CSV ou XML (journal d'appels).")
    try:
        calls = parse_call_log(name, data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Journal d'appels illisible ({str(exc)[:80]}).")
    known = _prospects_by_number()
    rows, unknown = [], 0
    for c in calls:
        d = C._digits(c["number"])
        p = known.get(d[-9:]) if len(d) >= 9 else None
        if not p or not c.get("at"):
            unknown += 1
            continue
        dup = _db.crm_calls.find_one({"prospect_id": p["id"], "at": {"$gte": c["at"] - timedelta(seconds=90),
                                                                      "$lte": c["at"] + timedelta(seconds=90)}})
        rows.append({"number": c["number"], "at": c["at"].isoformat(), "duration_sec": c["duration_sec"],
                     "duration": _dur(c["duration_sec"]), "direction": c["direction"], "prospect_id": p["id"],
                     "prospect": p["name"], "duplicate": bool(dup),
                     "result": ("rappel_demande" if c["direction"] == "manque"          # they called, nobody picked up
                                else "sans_reponse" if c["duration_sec"] == 0 else "a_qualifier")})
    return {"filename": file.filename, "rows": rows[:2000], "found": len(calls), "unknown": unknown}


class CallImportIn(BaseModel):
    rows: List[Dict[str, Any]]


@router.post("/api/crm/calls/import/commit")
def import_calls_commit(body: CallImportIn, token_data: TokenData = Depends(require_admin("crm"))):
    ids = {p["id"]: p for p in _db.crm_prospects.find({"id": {"$in": [r.get("prospect_id") for r in body.rows]}}, {"_id": 0})}
    created = skipped = 0
    for r in body.rows[:2000]:
        p = ids.get(r.get("prospect_id"))
        at = C._aware(r.get("at"))
        if not p or not at or r.get("duplicate") or _db.crm_calls.find_one(
                {"prospect_id": p["id"], "at": {"$gte": at - timedelta(seconds=90), "$lte": at + timedelta(seconds=90)}}):
            skipped += 1
            continue
        dur = max(0, int(r.get("duration_sec") or 0))
        result = r.get("result") if r.get("result") in RESULT_KEYS else ("sans_reponse" if dur == 0 else "a_qualifier")
        c = {"id": uuid.uuid4().hex, "prospect_id": p["id"], "status": "termine", "at": at, "by": token_data.email,
             "number": str(r.get("number") or "")[:40], "direction": "entrant" if r.get("direction") in ("entrant", "manque") else "sortant",
             "duration_sec": dur, "result": result, "notes": "", "created_at": C._now(), "source": "mobile"}
        _db.crm_calls.insert_one(c)
        _log_call(c, token_data.email)
        created += 1
    return {"created": created, "skipped": skipped}


@router.get("/api/crm/calls/export/csv")
def export_calls(tab: str = "", q: str = "", sector: str = "", city: str = "", status: str = "", result: str = "",
                 assigned: str = "", token_data: TokenData = Depends(require_admin("crm"))):
    f = {**_query(q, sector, city, status, result, assigned), **_tab_filter(tab if tab in TABS else "")}
    rows = list(_db.crm_calls.find(f, {"_id": 0}).sort("at", -1).limit(20000))
    users, names = C._users(), _names(rows)
    buf = io.StringIO()
    w = safe_csv.writer(buf)
    w.writerow(["Date", "Commerce", "Contact", "Numéro", "Durée (s)", "Résultat", "Statut", "Par", "Notes"])
    for r in rows:
        v = _view(r, users, names)
        w.writerow([v["at"], v["prospect"] or "", v["contact"] or "", v["number"], v["duration_sec"], v["result_label"],
                    v["status_label"], v["by_name"] or "", v["notes"].replace("\n", " ")])
    return Response(content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="appels.csv"'})
