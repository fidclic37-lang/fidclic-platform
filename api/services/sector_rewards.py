"""
The reward a card starts with, by sector (user, 2026-10-05: a gym's card read
« Un café gratuit » — the same default for every shop, whatever it sells).

WHEN IT APPLIES
    Only while the merchant has not chosen a reward themselves:
    `reward_chosen` is set the moment they save one (Carte de fidélité, the
    old designer, or an admin on their behalf). Until then the card carries
    its sector's reward, and follows the sector if it changes.

WHERE IT IS WRITTEN
    onboarding (step 2, the sector is picked) · Établissement (sector changed)
    · once per process for every shop still on an old placeholder (sync_all).
    The reward is stored in card_templates.reward_description, so every reader
    (pass, web card, scan, automatic messages) sees the same words.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

SECTOR_REWARDS: Dict[str, str] = {
    "cafe": "Un café offert",
    "restaurant": "Un dessert offert",
    "pizzeria": "Une pizza offerte",
    "bakery": "Une viennoiserie offerte",
    "bar": "Une boisson offerte",
    "spa": "Un soin offert",
    "salon": "Une coupe offerte",
    "gym": "Une séance offerte",
    "retail": "10 % de remise sur votre prochain achat",
    "other": "Une récompense offerte",
}
FALLBACK = "Une récompense offerte"

# Words that were only ever placeholders: the old one-size-fits-all defaults.
PLACEHOLDERS = {"Un café gratuit", "Une boisson offerte", "Une récompense fidélité",
                "Une récompense", "Récompense fidélité", "Une récompense offerte"}

_synced = False


def default_reward(sector: Optional[str]) -> str:
    return SECTOR_REWARDS.get((sector or "").strip().lower(), FALLBACK)


def is_untouched(tpl: Optional[Dict[str, Any]]) -> bool:
    """The merchant never chose the reward: no template, no reward, or one of
    the placeholders — and they never saved one."""
    tpl = tpl or {}
    if tpl.get("reward_chosen"):
        return False
    reward = (tpl.get("reward_description") or "").strip()
    return not reward or reward in PLACEHOLDERS or reward in SECTOR_REWARDS.values()


def apply(db, tid: str, sector: Optional[str] = None) -> Optional[str]:
    """Give `tid`'s card its sector's reward if the merchant never chose one.
    Returns the reward written, or None when nothing changed."""
    if not tid:
        return None
    if sector is None:
        sector = (db.tenants.find_one({"id": tid}, {"_id": 0, "sector": 1}) or {}).get("sector")
    tpl = db.card_templates.find_one({"tenant_id": tid}) or {}
    if not is_untouched(tpl):
        return None
    reward = default_reward(sector)
    if (tpl.get("reward_description") or "").strip() == reward:
        return None
    db.card_templates.update_one({"tenant_id": tid},
                                 {"$set": {"tenant_id": tid, "reward_description": reward,
                                           "updated_at": datetime.now(timezone.utc)}}, upsert=True)
    return reward


def mark_chosen(db, tid: str) -> None:
    """The merchant saved a reward: from now on it is theirs, never replaced."""
    if tid:
        db.card_templates.update_one({"tenant_id": tid}, {"$set": {"tenant_id": tid, "reward_chosen": True}},
                                     upsert=True)


def on_full_save(db, tid: str, payload: Dict[str, Any], old_tpl: Optional[Dict[str, Any]]) -> None:
    """The old designers save the WHOLE template, model defaults included: a
    placeholder there is not a choice and must not overwrite the card's
    reward; a real, new wording is the merchant's choice."""
    old_tpl = old_tpl or {}
    new = (payload.get("reward_description") or "").strip()
    old = (old_tpl.get("reward_description") or "").strip()
    if new and new not in PLACEHOLDERS and new != old:
        payload["reward_chosen"] = True
        return
    if not new or new in PLACEHOLDERS:
        sector = (db.tenants.find_one({"id": tid}, {"_id": 0, "sector": 1}) or {}).get("sector")
        payload["reward_description"] = old or default_reward(sector)
    if old_tpl.get("reward_chosen"):
        payload["reward_chosen"] = True


def sync_all(db) -> int:
    """Once per process: every shop with a sector whose card still carries a
    placeholder gets its sector's reward. Cheap — it only reads the shops
    whose template has not been chosen."""
    global _synced
    if _synced:
        return 0
    _synced = True
    changed = 0
    try:
        chosen = {t["tenant_id"] for t in db.card_templates.find({"reward_chosen": True}, {"_id": 0, "tenant_id": 1})
                  if t.get("tenant_id")}
        for t in db.tenants.find({"sector": {"$nin": [None, ""]}}, {"_id": 0, "id": 1, "sector": 1}):
            if t.get("id") and t["id"] not in chosen and apply(db, t["id"], t.get("sector")):
                changed += 1
                _refresh_passes(t["id"])
    except Exception as exc:                       # noqa: BLE001 — never block a boot
        print(f"sector_rewards: sync skipped ({exc})")
    return changed


def _refresh_passes(tid: str) -> None:
    """Cards already in a Wallet get the new wording now, not at the next scan."""
    try:
        from features import wallet_passes as W
        if W._db is not None:
            W.notify_tenant(tid)
    except Exception as exc:                       # noqa: BLE001
        print(f"sector_rewards: passes of {tid} not refreshed ({exc})")


def needs_choice(db, tid: str) -> Optional[Dict[str, Any]]:
    """For the dashboard reminder: the reward the card shows today, when the
    merchant has not chosen it yet; None once they have."""
    tpl = db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "reward_description": 1, "reward_chosen": 1}) or {}
    if not is_untouched(tpl):
        return None
    sector = (db.tenants.find_one({"id": tid}, {"_id": 0, "sector": 1}) or {}).get("sector")
    return {"reward": (tpl.get("reward_description") or "").strip() or default_reward(sector)}
