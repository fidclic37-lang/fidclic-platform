"""
Rapport de vos campagnes — the month's campaigns, measured (user, 2026-10-02).
Pro AI only.

WHEN
    The owner picks the day of the month (1–28; 16 by default). On that day the
    daily cron writes the report of the month before — once per month. A
    campaign is only counted once its WINDOW_DAYS are over: picked before the
    16th, the last sends of the month are listed « pas encore mesurables »
    with the day their result comes, and left out of the totals.

WHAT
    · the month: campaigns sent, clients touched, clients back, clients
      expected anyway (their own habit — features/campaign_learning.py), the
      difference (« effet FidClic »), the money of the clients back, and the
      month's CA FidClic (features/fidclic_impact.py);
    · against the month before;
    · the best and the weakest campaigns, and every campaign in a table;
    · the Autopilot's month (prepared, validated, skipped, expired);
    · what works here (« ce qui marche chez vous ») and what to do next month.

WHERE
    Page « Rapports » under Campagnes, the bell (until opened, 7 days), a PDF,
    and an email to the owner with the PDF attached — when the owner keeps
    « email » on and Brevo is switched on.

Mounts at:
    GET  /api/owner/campaign-reports                 settings + every report
    PUT  /api/owner/campaign-reports/settings        owner: day, email
    POST /api/owner/campaign-reports/generate        owner: last month's, now
    GET  /api/owner/campaign-reports/{month}         one report (YYYY-MM)
    GET  /api/owner/campaign-reports/{month}/pdf
"""
from __future__ import annotations

import base64
import html
import io
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth import require_role
from models import TokenData

router = APIRouter(tags=["campagnes"])
_db = None

PARIS = ZoneInfo("Europe/Paris")
READERS = ["business_owner", "administrateur", "manager"]
DEFAULT_DAY = 16
BELL_DAYS = 7
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def init(db):
    global _db
    _db = db
    try:
        db.campaign_reports.create_index([("tenant_id", 1), ("month", 1)], unique=True)
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def plan_ok(tid: str) -> bool:
    from features import autopilot as AP
    return AP.plan_ok(tid)


def settings(tid: str) -> Dict[str, Any]:
    doc = _db.campaign_report_settings.find_one({"tenant_id": tid}, {"_id": 0}) or {}
    return {"day": int(doc.get("day") or DEFAULT_DAY), "email": doc.get("email", True) is not False}


def label(month: str) -> str:
    y, m = month.split("-")
    return f"{MONTHS[int(m) - 1]} {y}"


def _bounds(month: str) -> Tuple[datetime, datetime]:
    y, m = (int(x) for x in month.split("-"))
    start = datetime(y, m, 1, tzinfo=PARIS)
    end = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=PARIS)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def previous_month(at: datetime) -> str:
    first = at.astimezone(PARIS).date().replace(day=1)
    last = first - timedelta(days=1)
    return f"{last.year}-{last.month:02d}"


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------
def _totals(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    done = [r for r in rows if r["mature"]]
    came = sum(r["came"] for r in done)
    expected = sum(r["expected"] for r in done)
    return {"campaigns": len(rows), "measured": len(done), "touched": sum(r["n"] for r in done),
            "came": came, "expected": round(expected, 1), "extra": round(came - expected, 1),
            "revenue": round(sum(r["revenue"] for r in done), 2)}


def _campaign_rows(tid: str, month: str, at: datetime) -> List[Dict[str, Any]]:
    from features import campaign_learning as CL
    start, end = _bounds(month)
    rows = []
    for c in _db.campaigns.find({"tenant_id": tid, "status": "sent", "sent_at": {"$gte": start, "$lt": end}}, {"_id": 0}):
        m = CL.measure(tid, c, at)
        if not m:
            continue
        sent_at = _aware(c.get("sent_at"))
        rows.append({
            "id": c.get("id"), "name": c.get("name") or "Campagne", "content": c.get("content") or "",
            "sent_at": sent_at.isoformat() if sent_at else None,
            "audience": c.get("audience_label") or c.get("segment") or "",
            "autopilot": str(c.get("template") or "").startswith("autopilot"),
            "n": m["n"], "came": m["came"], "expected": m["expected"],
            "extra": round(m["came"] - m["expected"], 1), "revenue": m["revenue"], "mature": m["mature"],
            "ready_on": (sent_at + timedelta(days=CL.WINDOW_DAYS)).astimezone(PARIS).date().isoformat() if sent_at else None,
        })
    rows.sort(key=lambda r: r["sent_at"] or "")
    return rows


def _fidclic_ca(tid: str, month: str) -> float:
    from features import fidclic_impact as FI
    start, end = _bounds(month)
    rows = list(_db.visits.find({"tenant_id": tid, "visit_time": {"$gte": start, "$lt": end}},
                                {"_id": 0, "customer_id": 1, "amount_paid": 1, "visit_time": 1}))
    FI.init(_db)
    return FI.impact(tid, rows)["revenue"]


def _autopilot(tid: str, month: str) -> Dict[str, int]:
    out = {"prepared": 0, "sent": 0, "skipped": 0, "expired": 0}
    for p in _db.autopilot_proposals.find({"tenant_id": tid, "for_date": {"$regex": f"^{month}"}},
                                          {"_id": 0, "status": 1}):
        st = p.get("status")
        if st == "empty":
            continue
        out["prepared"] += 1
        if st in ("sent", "scheduled"):
            out["sent"] += 1
        elif st in out:
            out[st] += 1
    return out


def _advice(tid: str, totals: Dict[str, Any], learn: List[Dict[str, Any]], auto: Dict[str, int]) -> List[str]:
    from features import clients_page as CP, customer_rules as R
    out = []
    best_offer = next((f for f in learn if f["dimension"] == "offer" and f["better"] and f["value"] != "aucune"), None)
    if best_offer:
        out.append(f"Misez sur ce qui marche chez vous : {best_offer['label'][0].lower() + best_offer['label'][1:]}.")
    worst = next((f for f in learn if not f["better"] and f["dimension"] == "offer"), None)
    if worst:
        out.append(f"Évitez plutôt : {worst['label'][0].lower() + worst['label'][1:]}.")
    best_time = next((f for f in learn if f["better"] and f["dimension"] in ("day", "week", "slot")), None)
    if best_time:
        out.append(f"Envoyez de préférence {best_time['label'][0].lower() + best_time['label'][1:]}.")
    if not totals["campaigns"]:
        out.append("Aucune campagne ce mois-ci : l'Autopilot peut en préparer chaque jour et chaque semaine, à valider.")
    if auto["expired"]:
        out.append(f"{auto['expired']} campagne{'s' if auto['expired'] > 1 else ''} de l'Autopilot "
                   f"{'ont' if auto['expired'] > 1 else 'a'} expiré sans être validée{'s' if auto['expired'] > 1 else ''} : "
                   "pensez à les valider depuis la cloche.")
    rules = R.load(tid)
    now = _now()
    inactive = sum(1 for c in _db.customers.find({"tenant_id": tid, "deleted_at": None}, CP.FIELDS)
                   if CP.is_inactive(c, now, rules))
    if inactive:
        out.append(f"{inactive} clients sont inactifs aujourd'hui : une relance ce mois-ci vaut la peine.")
    return out[:5]


def build(tid: str, month: str, at: Optional[datetime] = None) -> Dict[str, Any]:
    from features import campaign_learning as CL
    at = at or _now()
    rows = _campaign_rows(tid, month, at)
    totals = _totals(rows)
    y, m = (int(x) for x in month.split("-"))
    prev = f"{y - (m == 1)}-{(m - 2) % 12 + 1:02d}"
    prev_totals = _totals(_campaign_rows(tid, prev, at))
    measured = [r for r in rows if r["mature"] and r["n"] >= 5]
    learn = CL.learnings(tid, at)["learnings"]
    auto = _autopilot(tid, month)
    tenant = _db.tenants.find_one({"id": tid}, {"_id": 0, "name": 1}) or {}
    return {
        "month": month, "label": label(month), "shop": tenant.get("name") or "Votre commerce",
        "generated_at": at.isoformat(), "window_days": CL.WINDOW_DAYS,
        "totals": totals, "previous": {**prev_totals, "label": label(prev)},
        "fidclic_ca": _fidclic_ca(tid, month),
        # « Le mieux » = brought clients on top of the expected ones; never a
        # campaign that did worse than expected, whatever the month looked like.
        "best": sorted([r for r in measured if r["extra"] >= 1], key=lambda r: -r["extra"])[:3],
        "weakest": sorted([r for r in measured if r["extra"] < 1], key=lambda r: r["extra"])[:3],
        "campaigns": rows,
        "pending": [r for r in rows if not r["mature"]],
        "autopilot": auto,
        "learnings": [f["sentence"] for f in learn[:4]],
        "advice": _advice(tid, totals, learn, auto),
        "method": (f"Une campagne est mesurée {CL.WINDOW_DAYS} jours après son envoi : les clients revenus sont "
                   "comparés à ceux qui seraient venus de toute façon, d'après leurs habitudes des 6 derniers mois."),
    }


def generate(tid: str, month: str, at: Optional[datetime] = None, force: bool = False) -> Dict[str, Any]:
    at = at or _now()
    old = _db.campaign_reports.find_one({"tenant_id": tid, "month": month}, {"_id": 0})
    if old and not force:
        return old
    doc = {"id": (old or {}).get("id") or str(uuid.uuid4()), "tenant_id": tid, "month": month,
           "generated_at": at, "data": build(tid, month, at), "seen": False}
    _db.campaign_reports.update_one({"tenant_id": tid, "month": month}, {"$set": doc}, upsert=True)
    return _db.campaign_reports.find_one({"tenant_id": tid, "month": month}, {"_id": 0})


# ---------------------------------------------------------------------------
# PDF and email
# ---------------------------------------------------------------------------
def _money(x: float) -> str:
    return f"{x:,.2f} €".replace(",", " ").replace(".", ",")


def _num(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def render_pdf(data: Dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ink, muted, blue, green = (colors.HexColor(c) for c in ("#0B1C3F", "#64748B", "#2F6BFF", "#0F8B58"))
    base = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=base["Title"], fontName="Helvetica-Bold", fontSize=20, textColor=ink, alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, textColor=ink, spaceBefore=10, spaceAfter=5)
    body = ParagraphStyle("b", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5, textColor=ink, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=muted, leading=11)
    big = ParagraphStyle("big", parent=body, fontName="Helvetica-Bold", fontSize=15, textColor=ink, leading=18)
    esc = lambda s: html.escape(str(s if s is not None else ""))
    t, p = data["totals"], data["previous"]

    story = [Paragraph("Rapport de vos campagnes", h1),
             Paragraph(esc(f"{data['shop']} — {data['label']}"), small), Spacer(1, 5 * mm)]
    tiles = [("Campagnes", str(t["campaigns"])), ("Clients touchés", str(t["touched"])),
             ("Clients revenus", str(t["came"])), ("Venus en plus grâce aux messages", ("+" if t["extra"] >= 0 else "") + _num(t["extra"])),
             ("CA des clients revenus", _money(t["revenue"])), ("CA FidClic du mois", _money(data["fidclic_ca"]))]
    grid = [[Paragraph(f"{esc(v)}", big) for _, v in tiles[:3]], [Paragraph(esc(k), small) for k, _ in tiles[:3]],
            [Paragraph(f"{esc(v)}", big) for _, v in tiles[3:]], [Paragraph(esc(k), small) for k, _ in tiles[3:]]]
    g = Table(grid, colWidths=[60 * mm] * 3)
    g.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 1), (-1, 1), 8)]))
    story += [g, Paragraph(esc(f"Le mois d'avant ({p['label']}) : {p['campaigns']} campagnes, {p['came']} clients revenus, "
                               f"{('+' if p['extra'] >= 0 else '') + _num(p['extra'])} en plus grâce aux messages."), small)]
    if data["pending"]:
        story.append(Paragraph(esc(f"{len(data['pending'])} campagne(s) pas encore mesurable(s) : leur résultat arrive "
                                   f"{data['window_days']} jours après l'envoi, elles ne sont pas comptées."), small))

    def table(title, rows):
        if not rows:
            return
        story.append(Paragraph(esc(title), h2))
        head = ["Campagne", "Date", "Touchés", "Revenus", "Attendus", "En plus", "CA"]
        cells = [[Paragraph(f"<b>{esc(h)}</b>", small) for h in head]]
        for r in rows:
            d = (r["sent_at"] or "")[:10]
            cells.append([Paragraph(esc(r["name"]) + (" <font color='#6D28D9'>· Autopilot</font>" if r["autopilot"] else ""), body),
                          Paragraph(esc(f"{d[8:10]}/{d[5:7]}"), small), Paragraph(str(r["n"]), small),
                          Paragraph(str(r["came"]) if r["mature"] else "—", small),
                          Paragraph(_num(round(r["expected"], 1)) if r["mature"] else "—", small),
                          Paragraph(((("+" if r["extra"] >= 0 else "") + _num(r["extra"])) if r["mature"] else "en cours"), small),
                          Paragraph(_money(r["revenue"]) if r["mature"] else "—", small)])
        tb = Table(cells, colWidths=[62 * mm, 15 * mm, 17 * mm, 17 * mm, 18 * mm, 18 * mm, 25 * mm])
        tb.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.6, blue),
                                ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#E6EEFB")),
                                ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(tb)

    table("Les campagnes qui ont le mieux marché", data["best"])
    table("Les plus faibles", data["weakest"])
    table("Toutes les campagnes du mois", data["campaigns"])
    a = data["autopilot"]
    if a["prepared"]:
        story += [Paragraph("Autopilot", h2), Paragraph(esc(
            f"{a['prepared']} campagnes préparées : {a['sent']} validées, {a['skipped']} ignorées, {a['expired']} expirées."), body)]
    if data["learnings"]:
        story.append(Paragraph("Ce qui marche chez vous", h2))
        story += [Paragraph("• " + esc(s), body) for s in data["learnings"]]
    if data["advice"]:
        story.append(Paragraph("Pour le mois prochain", h2))
        story += [Paragraph("• " + esc(s), body) for s in data["advice"]]
    story += [Spacer(1, 4 * mm), Paragraph(esc(data["method"]), small)]

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm,
                      bottomMargin=16 * mm, title=f"Rapport de vos campagnes — {data['label']}").build(story)
    return buf.getvalue()


def email(tid: str, report: Dict[str, Any]) -> Dict[str, Any]:
    """The report to the shop's owner, PDF attached — when emails are on."""
    from services import mailer
    if not settings(tid)["email"]:
        return {"sent": False, "reason": "owner_off"}
    key = mailer._api_key()
    if not key:
        return {"sent": False, "reason": "mailer_disabled"}
    owners = [u["email"] for u in _db.users.find({"tenant_id": tid, "role": "business_owner"}, {"_id": 0, "email": 1})
              if u.get("email")]
    if not owners:
        return {"sent": False, "reason": "no_owner"}
    d, t = report["data"], report["data"]["totals"]
    base = __import__("os").getenv("PUBLIC_APP_URL", "https://app.fidclic.com").rstrip("/")
    body = (f"<p>Bonjour,</p><p>Voici le rapport de vos campagnes de <b>{html.escape(d['label'])}</b> "
            f"chez {html.escape(d['shop'])} :</p><ul>"
            f"<li>{t['campaigns']} campagnes, {t['touched']} clients touchés</li>"
            f"<li>{t['came']} clients revenus, dont <b>{('+' if t['extra'] >= 0 else '') + _num(t['extra'])}</b> grâce aux messages</li>"
            f"<li>{_money(t['revenue'])} de CA des clients revenus · CA FidClic du mois : {_money(d['fidclic_ca'])}</li></ul>"
            + "".join(f"<p>• {html.escape(a)}</p>" for a in d["advice"][:3])
            + f"<p><a href=\"{base}/dashboard/campaigns/reports?month={d['month']}\">Voir le rapport complet</a> — "
              "le PDF est joint.</p><p>— FidClic</p>")
    try:
        mailer._post({"sender": {"email": mailer.SENDER_EMAIL, "name": "FidClic"},
                      "to": [{"email": e} for e in owners],
                      "subject": f"Rapport de vos campagnes — {d['label']}",
                      "htmlContent": body,
                      "attachment": [{"name": f"rapport-campagnes-{d['month']}.pdf",
                                      "content": base64.b64encode(render_pdf(d)).decode()}]}, key)
        return {"sent": True, "to": len(owners)}
    except Exception as exc:                                  # noqa: BLE001
        return {"sent": False, "reason": str(exc)[:160]}


# ---------------------------------------------------------------------------
# The cron and the bell
# ---------------------------------------------------------------------------
def due(tid: str, at: datetime) -> Optional[str]:
    """Last month's report, if its day has come this month and it is not written."""
    day = settings(tid)["day"]
    if at.astimezone(PARIS).day < day:
        return None
    month = previous_month(at)
    return None if _db.campaign_reports.find_one({"tenant_id": tid, "month": month}) else month


def run(now: Optional[datetime] = None) -> Dict[str, int]:
    now = now or _now()
    out = {"written": 0, "emailed": 0}
    for t in _db.tenants.find({"is_active": {"$ne": False}}, {"_id": 0, "id": 1}):
        tid = t.get("id")
        try:
            if not tid or not plan_ok(tid):
                continue
            month = due(tid, now)
            if not month:
                continue
            rep = generate(tid, month, now)
            out["written"] += 1
            res = email(tid, rep)
            _db.campaign_reports.update_one({"tenant_id": tid, "month": month},
                                            {"$set": {"email": res, "emailed_at": now if res.get("sent") else None}})
            out["emailed"] += bool(res.get("sent"))
        except Exception as exc:
            print(f"campaign report: {tid} failed ({exc})")
    return out


def alerts(tid: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or _now()
    out = []
    for r in _db.campaign_reports.find({"tenant_id": tid, "seen": False,
                                        "generated_at": {"$gte": now - timedelta(days=BELL_DAYS)}}, {"_id": 0}):
        t = r["data"]["totals"]
        out.append({"id": f"report:{r['month']}", "severity": "warning",
                    "title": f"Votre rapport de campagnes de {r['data']['label']} est prêt",
                    "body": f"{t['campaigns']} campagnes, {t['came']} clients revenus "
                            f"({('+' if t['extra'] >= 0 else '') + _num(t['extra'])} grâce aux messages).",
                    "metric": str(t["campaigns"]),
                    "action": {"href": f"/dashboard/campaigns/reports?month={r['month']}", "label": "Voir le rapport"}})
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def _locked():
    raise HTTPException(status_code=403, detail={"code": "PLAN_LOCKED", "feature": "campaign_reports",
                                                 "message": "Le rapport mensuel des campagnes est inclus dans l'offre Pro AI."})


@router.get("/api/owner/campaign-reports")
def list_reports(token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    tid = token_data.tenant_id
    s = settings(tid)
    today = _now().astimezone(PARIS).date()
    nxt = today.replace(day=s["day"]) if today.day < s["day"] else \
        (today.replace(day=1) + timedelta(days=32)).replace(day=s["day"])
    reports = [{"month": r["month"], "label": r["data"]["label"], "generated_at": _aware(r["generated_at"]).isoformat(),
                "totals": r["data"]["totals"], "seen": r.get("seen", False), "email": r.get("email")}
               for r in _db.campaign_reports.find({"tenant_id": tid}, {"_id": 0}).sort("month", -1)]
    return {"plan_ok": plan_ok(tid), "settings": s, "reports": reports, "next_on": nxt.isoformat(),
            "can_edit": token_data.role == "business_owner", "last_month": previous_month(_now()),
            "last_month_label": label(previous_month(_now()))}


class ReportSettings(BaseModel):
    day: int = Field(DEFAULT_DAY, ge=1, le=28)
    email: bool = True


@router.put("/api/owner/campaign-reports/settings")
def put_settings(body: ReportSettings, token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    if not plan_ok(tid):
        _locked()
    _db.campaign_report_settings.update_one({"tenant_id": tid}, {"$set": {"tenant_id": tid, "day": body.day,
                                                                         "email": body.email}}, upsert=True)
    return list_reports(token_data=token_data)


class GenerateIn(BaseModel):
    month: Optional[str] = None


@router.post("/api/owner/campaign-reports/generate")
def generate_now(body: GenerateIn = None, token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    if not plan_ok(tid):
        _locked()
    month = (body.month if body and body.month else None) or previous_month(_now())
    if not MONTH_RE.match(month) or month >= f"{_now().astimezone(PARIS).year}-{_now().astimezone(PARIS).month:02d}":
        raise HTTPException(status_code=400, detail="Choisissez un mois terminé.")
    rep = generate(tid, month, force=True)
    return {"month": month, "data": rep["data"]}


@router.get("/api/owner/campaign-reports/{month}")
def get_report(month: str, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    tid = token_data.tenant_id
    if not plan_ok(tid):
        _locked()
    r = _db.campaign_reports.find_one({"tenant_id": tid, "month": month}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Pas de rapport pour ce mois.")
    if token_data.role == "business_owner" and not r.get("seen"):
        _db.campaign_reports.update_one({"tenant_id": tid, "month": month}, {"$set": {"seen": True}})
    return {"month": month, "data": r["data"], "email": r.get("email")}


@router.get("/api/owner/campaign-reports/{month}/pdf")
def report_pdf(month: str, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    tid = token_data.tenant_id
    if not plan_ok(tid):
        _locked()
    r = _db.campaign_reports.find_one({"tenant_id": tid, "month": month}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Pas de rapport pour ce mois.")
    return Response(content=render_pdf(r["data"]), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="rapport-campagnes-{month}.pdf"'})
