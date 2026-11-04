"""
Visit-Frequency Anomaly Detection — additive AI feature module.

Status: 🟡 Stub with spec. Returns realistic mock data; frontend can build against it.
Mounts at: /api/owner/ai/anomaly/*
Collections: reads `visits` only.

Production implementation (estimated 8 hours):
- Compare last week's visits-per-segment vs prior 4-week mean & stddev for the same weekday.
- Flag when current week deviates by > 2σ.
- Segments: by_weekday, by_branch, by_tier, by_postal_code.
- Optional: STL decomposition for trend separation if data is large enough.
- No LLM; pure pandas / statistics. Run as a daily cron and cache results.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Request
from auth import require_role

router = APIRouter(tags=["ai-anomaly"])
_db = None


def init(db):
    global _db
    _db = db


@router.get("/api/owner/ai/anomaly/recent")
def recent_anomalies(request: Request, token_data=Depends(require_role(["business_owner", "manager"], partial_ok=True))):
    # TODO: replace with real σ-based comparison against prior 4 weeks.
    # See module docstring for the production algorithm.
    from features import store_scope as S
    stores = S.visit_filter(S.resolve(token_data, request))   # a manager counts their own store, never the shop's
    visits_last7 = _db.visits.count_documents({
        "tenant_id": token_data.tenant_id, **stores,
        "visit_time": {"$gte": datetime.now(timezone.utc) - timedelta(days=7)},
    })
    visits_prev7 = _db.visits.count_documents({
        "tenant_id": token_data.tenant_id, **stores,
        "visit_time": {
            "$gte": datetime.now(timezone.utc) - timedelta(days=14),
            "$lt": datetime.now(timezone.utc) - timedelta(days=7),
        },
    })
    delta_pct = 0
    if visits_prev7:
        delta_pct = round(((visits_last7 - visits_prev7) / visits_prev7) * 100, 1)
    flag = abs(delta_pct) >= 20
    return {
        "anomalies": [
            {
                "segment": "all_visits_week_over_week",
                "current": visits_last7,
                "previous": visits_prev7,
                "delta_pct": delta_pct,
                "severity": "warning" if flag else "info",
                "headline": (
                    f"Visits {'down' if delta_pct < 0 else 'up'} {abs(delta_pct)}% vs last week"
                    if visits_prev7 else "Not enough history yet."
                ),
            }
        ] if flag or visits_prev7 else [],
        "stub": True,
    }
