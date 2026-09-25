"""
Local end-to-end runner — mirrors Vercel's routing on one port, no MongoDB:
  /api/*   → api/server.py (FastAPI) against an in-memory mongomock DB
  /*       → dist/ (run `npx vite build` first), SPA fallback to index.html
Run:  python3 scripts/dev_local.py   →  http://localhost:8765
Nothing here is used in production.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))
os.environ.setdefault("JWT_SECRET", "dev-local-secret")
os.environ.pop("MONGODB_URI", None)

import mongomock
mongomock.patch(servers=(("localhost", 27017),)).start()

from server import app, db                               # noqa: E402
from fastapi.staticfiles import StaticFiles              # noqa: E402
from fastapi.responses import FileResponse               # noqa: E402
from starlette.requests import Request                   # noqa: E402

def _backfill_seed_addresses():
    """The demo tenants predate onboarding, which is what collects the postal
    code — so they have a street but no code, and every page that needs a
    position (Géolocalisation) has nothing to work from locally. Real tenants
    always have one: features/onboarding.py validates five digits before it
    will finish step 2. This only fills the gap in the seed."""
    for slug, postal, city in (("cafe-lumiere", "37000", "Tours"),
                               ("boulangerie-saint-michel", "37100", "Tours")):
        t = db.tenants.find_one({"slug": slug})
        if t and not t.get("postal_code"):
            db.tenants.update_one({"id": t["id"]}, {"$set": {
                "postal_code": postal, "city": city,
                "address": f"{(t.get('address') or '').split(',')[0]}, {postal} {city}".lstrip(", "),
            }})


DIST = os.path.join(ROOT, "dist")
app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")


@app.middleware("http")
async def spa_fallback(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") and not path.startswith("/assets/"):
        candidate = os.path.join(DIST, path.lstrip("/"))
        if path != "/" and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(DIST, "index.html"))
    return await call_next(request)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8765"))
    _backfill_seed_addresses()
    print(f"[dev_local] serving dist/ + api on http://localhost:{port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
