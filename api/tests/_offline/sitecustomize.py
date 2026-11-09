"""Loaded by every API test file that scripts/run_api_tests.py starts (this
folder is first on PYTHONPATH): the tests run offline (PR #454).

A lookup of any host but this machine is refused at once — the « unreachable »
a laptop without network gets — so a test reads the same on the CI, which has
the internet, as on a laptop, which may not. Each refused host is written to
$FIDCLIC_OFFLINE_LOG (file and host) for the runner to name; the fix is a stub
in that test, never the network.

Proxy variables are dropped: through a proxy only the proxy's own address
would be looked up, and the real host would slip past.
"""
import os
import socket
import sys

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)

_LOG = os.environ.get("FIDCLIC_OFFLINE_LOG")
_LOCAL = {"localhost", "localhost.localdomain", "ip6-localhost", "::1", "0.0.0.0", "", "test", "testserver"}
_lookup = socket.getaddrinfo


def _is_local(host) -> bool:
    if host is None:
        return True
    h = (host.decode() if isinstance(host, bytes) else str(host)).strip("[]").lower()
    return h in _LOCAL or h.startswith("127.") or h.endswith(".localhost")


def _offline_getaddrinfo(host, *args, **kwargs):
    if _is_local(host):
        return _lookup(host, *args, **kwargs)
    h = host.decode() if isinstance(host, bytes) else str(host)
    if _LOG:
        try:
            with open(_LOG, "a") as f:
                f.write(f"{os.path.basename(sys.argv[0]) if sys.argv else '?'}\t{h}\n")
        except OSError:
            pass
    raise socket.gaierror(socket.EAI_NONAME, f"offline test run: {h} is not looked up (tests/_offline)")


socket.getaddrinfo = _offline_getaddrinfo
