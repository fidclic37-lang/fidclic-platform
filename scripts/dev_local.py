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

from server import app                                   # noqa: E402
from fastapi.staticfiles import StaticFiles              # noqa: E402
from fastapi.responses import FileResponse               # noqa: E402
from starlette.requests import Request                   # noqa: E402

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
    print(f"[dev_local] serving dist/ + api on http://localhost:{port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
