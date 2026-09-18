#!/usr/bin/env python3
"""Watchdog rules. Pure functions, no I/O, so every case is cheap to assert."""
import sys, os, importlib.util
from datetime import datetime, timezone, timedelta

spec = importlib.util.spec_from_file_location(
    "wd", os.path.join(os.path.dirname(__file__), "..", "features", "facture_watchdog.py"))
wd = importlib.util.module_from_spec(spec); spec.loader.exec_module(wd)

NOW = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
P = F = 0
def ck(name, cond, got=None):
    global P, F
    if cond: P += 1; print(f"  ok   {name}")
    else:    F += 1; print(f"  FAIL {name}" + (f"  got={got!r}" if got is not None else ""))

def inv(state, days_ago, **kw):
    at = (NOW - timedelta(days=days_ago)).isoformat()
    d = {"id": "i1", "number": "2026-0148", "tenant_id": "t1", "total_ttc": 4800.0,
         "channel": "e-invoicing", "state": state,
         "lifecycle": [{"family": "pa", "state": state, "at": at}]}
    d.update(kw)
    return d

print("\nFacture watchdog")

# --- Case C: the scenario this module exists for ---
f = wd.evaluate(inv("sent", 64), NOW)          # 12 March -> 15 May
ck("sent for 64 days is flagged", f is not None)
ck("kind is sent_not_confirmed", f and f["kind"] == "sent_not_confirmed", f and f["kind"])
ck("severity high", f and f["severity"] == "high")
ck("French detail names the invoice", f and "2026-0148" in f["detail_fr"])
ck("action tells the practice what to do next", f and "annuaire" in f["action_fr"])

# --- thresholds ---
ck("sent for 1 day is NOT flagged", wd.evaluate(inv("sent", 1), NOW) is None)
ck("sent for 3 days IS flagged", wd.evaluate(inv("sent", 3), NOW) is not None)
ck("registered for 10 days is NOT flagged", wd.evaluate(inv("registered", 10), NOW) is None)
f2 = wd.evaluate(inv("registered", 20), NOW)
ck("registered for 20 days IS flagged", f2 and f2["kind"] == "no_buyer_response", f2 and f2["kind"])
ck("silence is not acceptance", f2 and "ne vaut pas acceptation" in f2["action_fr"])

# --- final states are never nagged ---
for st in ("accepted", "refused", "paid", "cancelled"):
    ck(f"{st} is never flagged", wd.evaluate(inv(st, 400), NOW) is None)
ck("draft is never flagged", wd.evaluate(inv("draft", 400), NOW) is None)

# --- overdue outranks everything, because it costs money ---
f3 = wd.evaluate(inv("registered", 3, due_date="2026-04-01"), NOW)
ck("overdue wins over the age rule", f3 and f3["kind"] == "overdue_unpaid", f3 and f3["kind"])
ck("overdue is high severity", f3 and f3["severity"] == "high")
ck("paid is never overdue", wd.evaluate(inv("paid", 3, due_date="2026-01-01"), NOW) is None)

# --- a channel that can never answer ---
f4 = wd.evaluate(inv("sent", 9, channel="email"), NOW)
ck("email channel gets its own finding", f4 and f4["kind"] == "blind_channel_unverified", f4 and f4["kind"])
ck("email finding says no acknowledgement will come",
   f4 and "Aucun accusé" in f4["action_fr"])
ck("email under threshold is quiet", wd.evaluate(inv("sent", 3, channel="email"), NOW) is None)

# --- timestamp shapes this codebase has actually written ---
ck("Z-suffixed timestamps parse",
   wd.evaluate({**inv("sent", 0), "lifecycle": [{"at": "2026-01-01T00:00:00Z", "state": "sent"}]}, NOW) is not None)
ck("falls back to updated_at when lifecycle is empty",
   wd.evaluate({**inv("sent", 0), "lifecycle": [], "updated_at": "2026-01-01T00:00:00Z"}, NOW) is not None)
ck("no timestamp at all does not crash",
   wd.evaluate({"id": "x", "state": "sent", "lifecycle": []}, NOW) is None)
ck("latest lifecycle entry wins, not the first",
   wd.evaluate({**inv("sent", 400), "lifecycle": [
       {"at": (NOW - timedelta(days=400)).isoformat(), "state": "draft"},
       {"at": (NOW - timedelta(days=1)).isoformat(), "state": "sent"}]}, NOW) is None)

# --- pa.state takes precedence over the legacy mirror ---
ck("pa.state is read in preference to state",
   wd.evaluate({**inv("sent", 400), "pa": {"state": "paid"}}, NOW) is None)

# --- ordering: money and age first ---
batch = [inv("registered", 20, id="a", total_ttc=100.0),
         inv("sent", 30, id="b", total_ttc=9000.0),
         inv("paid", 99, id="c")]
res = wd.scan(batch, NOW)
ck("scan drops final states", len(res) == 2, len(res))
ck("highest severity and value first", res[0]["kind"] == "sent_not_confirmed", res[0]["kind"])

print(f"\n{'='*46}\nPASSED: {P}   FAILED: {F}")
sys.exit(1 if F else 0)
