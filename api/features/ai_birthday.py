"""
Hyper-Personalized Birthday Messages — additive AI feature module.

Status: 🟡 Stub with spec. Returns mock copy; needs LLM to ship.
Mounts at: /api/owner/ai/birthday/*
Collections: reads `customers`, `visits`. Writes to `birthday_offers`.

Production implementation (estimated 6 hours):
- Daily cron finds customers whose `birthday` (MM-DD) matches today.
- For each, look up their top 3 ordered items / favorite items from visit
  history (requires items to be tracked on visits — currently they aren't,
  so fallback to "your usual".)
- Call LLM (Claude Haiku or GPT-4o-mini) once per customer with:
    {customer_name, business_name, favorite_items, brand_voice}
- Returns ~80 char personalized message.
- Cost: ~€0.0005 per message → €0.05 per 100 birthdays.
"""
from __future__ import annotations
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from auth import require_role

router = APIRouter(tags=["ai-birthday"])
_db = None


def init(db):
    global _db
    _db = db


@router.get("/api/owner/ai/birthday/today")
def todays_birthdays(request: Request, token_data=Depends(require_role(["business_owner", "manager"], partial_ok=True))):
    from features import store_scope as S
    mmdd = datetime.now(ZoneInfo("Europe/Paris")).strftime("%m-%d")      # the shop's day, not UTC's
    customers = list(_db.customers.find({
        **S.customer_filter(S.resolve(token_data, request)),             # this store's clients, never a deleted one
        "birthday": mmdd,
    }).limit(200))
    out = []
    for c in customers:
        out.append({
            "customer_id": c["id"],
            "name": c.get("name"),
            "tier": c.get("tier"),
            # TODO: replace with LLM-generated personalized message
            "draft_message": f"Joyeux anniversaire {(c.get('name') or '').split(' ')[0]} ! "
                             f"Votre boisson favorite est offerte aujourd'hui. 🎂",
            "stub": True,
        })
    return {"count": len(out), "birthdays": out}
