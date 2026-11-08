"""
The PRIVATE Vercel Blob store of the warehouse (features/warehouse, user
2026-11-04). The pictures' store (services/media) is public — anyone with a
URL reads it — so the shops' full history lives in a second store, private:
every read needs the token, which only the server has.

Plain REST over httpx, as services/media does (no SDK in Python):
    put     PUT  https://vercel.com/api/blob/?pathname=<path>
    get     GET  https://<store>.private.blob.vercel-storage.com/<path>
    delete  POST https://vercel.com/api/blob/delete  {"urls": [...]}
all with « authorization: Bearer <token> ». The token is
vercel_blob_rw_<storeId>_<secret>; its env var is
WAREHOUSE_BLOB_READ_WRITE_TOKEN (the store connected with the prefix
WAREHOUSE_BLOB, so it never mixes with the pictures' BLOB_READ_WRITE_TOKEN).

A read either returns the bytes, None when the file is not there, or raises
BlobError — a store that is down is never mistaken for an empty one.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode

TOKEN_ENV = "WAREHOUSE_BLOB_READ_WRITE_TOKEN"
API = "https://vercel.com/api/blob"
API_VERSION = "12"
TIMEOUT_S = 20.0
_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,499}$")


class BlobError(Exception):
    pass


def _http(method: str, url: str, headers: Dict[str, str], body: Optional[bytes] = None,
          timeout: float = TIMEOUT_S) -> Tuple[int, bytes]:
    import httpx
    r = httpx.request(method, url, headers=headers, content=body, timeout=timeout, follow_redirects=True)
    return r.status_code, r.content


def _token() -> Optional[str]:
    return (os.environ.get(TOKEN_ENV) or "").strip() or None


def store_id() -> Optional[str]:
    parts = (_token() or "").split("_")
    if len(parts) >= 5 and parts[0] == "vercel" and parts[1] == "blob" and parts[3]:
        return parts[3].lower()
    return None


def configured() -> bool:
    return store_id() is not None


def _check(path: str) -> str:
    if not isinstance(path, str) or not _PATH.match(path) or ".." in path or "//" in path:
        raise ValueError(f"invalid blob path: {path[:40]!r}")
    return path


def _headers(**extra: str) -> Dict[str, str]:
    return {"authorization": f"Bearer {_token()}", "x-api-version": API_VERSION,
            "x-vercel-blob-store-id": store_id() or "", **extra}


def put(path: str, data: bytes, content_type: str = "application/octet-stream") -> bool:
    """Write (or overwrite) one private file; False when it did not land."""
    _check(path)
    if not configured():
        return False
    try:
        status, text = _http("PUT", f"{API}/?{urlencode({'pathname': path})}",
                             _headers(**{"x-vercel-blob-access": "private", "x-add-random-suffix": "0",
                                         "x-allow-overwrite": "1", "x-content-type": content_type}), data)
    except Exception as exc:
        print(f"blob_private: put failed ({type(exc).__name__})")
        return False
    if status >= 300:
        print(f"blob_private: put refused ({status} {text[:200]!r})")
        return False
    return True


def get(path: str) -> Optional[bytes]:
    _check(path)
    if not configured():
        raise BlobError("no private store")
    try:
        status, body = _http("GET", f"https://{store_id()}.private.blob.vercel-storage.com/{quote(path)}",
                             {"authorization": f"Bearer {_token()}"})
    except Exception as exc:
        raise BlobError(type(exc).__name__) from exc
    if status == 404:
        return None
    if status >= 300:
        raise BlobError(f"status {status}")
    return body


def delete(paths: List[str]) -> bool:
    paths = [_check(p) for p in paths]
    if not paths or not configured():
        return not paths
    urls = [f"https://{store_id()}.private.blob.vercel-storage.com/{quote(p)}" for p in paths]
    try:
        status, text = _http("POST", f"{API}/delete", _headers(**{"content-type": "application/json"}),
                             json.dumps({"urls": urls}).encode())
    except Exception as exc:
        print(f"blob_private: delete failed ({type(exc).__name__})")
        return False
    return status < 300
