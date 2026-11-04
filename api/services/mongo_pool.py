"""
A full connection pool fails one request, not all of them (2026-11-04).

pymongo 4.6.1 handles « waited too long for a connection »
(WaitQueueTimeoutError) like a network error: it clears the whole pool and marks
the database unknown. Every other request of the instance then fails with
« connection pool paused », visits included, and all the connections are opened
again, which is what a loaded Atlas M0 can least afford. The database is fine in
that case, only busy: the request that waited too long gets its 503 and nothing
else changes. Real network errors still go through pymongo.
"""
from pymongo.errors import WaitQueueTimeoutError
from pymongo.topology import Topology

_ORIGINAL = None


def install() -> None:
    global _ORIGINAL
    if _ORIGINAL is not None:
        return
    _ORIGINAL = original = Topology._handle_error

    def _handle_error(self, address, err_ctx):
        if isinstance(err_ctx.error, WaitQueueTimeoutError):
            return None
        return original(self, address, err_ctx)

    Topology._handle_error = _handle_error
