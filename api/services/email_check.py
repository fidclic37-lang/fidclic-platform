"""
Is this e-mail address real enough to sign up with? (user, 2026-10-04/05:
« email ekdm proper hona chahiye … kuch bhi arbitrary allowed nhi »)

THE CHECKS, in order — each one answers in French, with a fix when there is one
    1. shape     local@domain.tld, no spaces, no double dots, a real TLD
    2. typo      @gmial.com, @hotmial.fr… → « Vouliez-vous dire …@gmail.com ? »
    3. throwaway yopmail, mailinator & co. are refused
    4. domain    the domain must receive mail: an MX record (or, as RFC 5321
                 allows, an A record) — asked over DNS-over-HTTPS (Cloudflare,
                 then Google), no extra dependency. A business's own domain
                 (contact@boulangerie-paul.fr) is fine as long as it receives mail.

WHAT IT CANNOT KNOW
    Whether the mailbox itself exists (abc123@gmail.com passes): only a code
    sent to it proves that — the verification step, not this module.

SAFETY
    DNS unreachable or slow → the address is ACCEPTED (fail-open): a resolver
    hiccup must never stop a real sign-up. Answers are cached per domain.
"""
from __future__ import annotations

import re
import time
from typing import Dict, Optional, Tuple

_SHAPE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$")

# The common slips, on the domains French shops actually use.
TYPOS: Dict[str, str] = {
    "gmial.com": "gmail.com", "gmai.com": "gmail.com", "gamil.com": "gmail.com", "gnail.com": "gmail.com",
    "gmail.co": "gmail.com", "gmail.fr": "gmail.com", "gmaill.com": "gmail.com", "gmal.com": "gmail.com",
    "gmail.con": "gmail.com", "gmail.cm": "gmail.com", "gmail.om": "gmail.com", "gmali.com": "gmail.com",
    "hotmial.com": "hotmail.com", "hotmai.com": "hotmail.com", "hotmail.con": "hotmail.com",
    "hotmial.fr": "hotmail.fr", "hotmal.fr": "hotmail.fr", "homail.fr": "hotmail.fr",
    "outlok.com": "outlook.com", "outloo.com": "outlook.com", "outlook.con": "outlook.com", "outlok.fr": "outlook.fr",
    "yaho.com": "yahoo.com", "yahooo.com": "yahoo.com", "yahoo.con": "yahoo.com", "yaho.fr": "yahoo.fr",
    "orange.com": "orange.fr", "oranje.fr": "orange.fr", "wanado.fr": "wanadoo.fr", "wannadoo.fr": "wanadoo.fr",
    "free.com": "free.fr", "sfr.com": "sfr.fr", "laposte.com": "laposte.net", "lapost.net": "laposte.net",
    "icloud.fr": "icloud.com", "iclod.com": "icloud.com", "icoud.com": "icloud.com",
}

DISPOSABLE = {
    "yopmail.com", "yopmail.fr", "yopmail.net", "cool.fr.nf", "jetable.fr.nf", "courriel.fr.nf", "moncourrier.fr.nf",
    "jetable.org", "mailinator.com", "mailinator.net", "guerrillamail.com", "guerrillamail.net", "guerrillamail.org",
    "sharklasers.com", "grr.la", "10minutemail.com", "10minutemail.net", "temp-mail.org", "tempmail.com",
    "tempmail.net", "tempmailo.com", "temp-mail.io", "trashmail.com", "trashmail.fr", "trashmail.net",
    "maildrop.cc", "getnada.com", "nada.email", "dispostable.com", "throwawaymail.com", "fakeinbox.com",
    "mohmal.com", "emailondeck.com", "mintemail.com", "spamgourmet.com", "tmail.ws", "mailnesia.com",
    "mytemp.email", "tempr.email", "discard.email", "burnermail.io", "33mail.com", "mailcatch.com",
    "spambox.us", "mailpoof.com", "emailfake.com", "fakemail.net", "inboxkitten.com", "tempinbox.com",
    "minuteinbox.com", "byom.de", "harakirimail.com", "mail.tm", "spam4.me", "getairmail.com",
}

TIMEOUT_S = 3.0
_CACHE: Dict[str, Tuple[float, Optional[bool]]] = {}
_TTL = 6 * 3600


def _doh(name: str, rtype: str) -> Optional[dict]:
    import httpx
    for url in ("https://cloudflare-dns.com/dns-query", "https://dns.google/resolve"):
        try:
            r = httpx.get(url, params={"name": name, "type": rtype}, timeout=TIMEOUT_S,
                          headers={"accept": "application/dns-json"})
            if r.status_code == 200:
                return r.json()
        except Exception:
            continue
    return None


def domain_receives_mail(domain: str) -> Optional[bool]:
    """True: MX (or A) found. False: the domain doesn't exist or has neither.
    None: couldn't ask — the caller lets the address through."""
    hit = _CACHE.get(domain)
    if hit and hit[0] > time.time():
        return hit[1]
    verdict: Optional[bool] = None
    mx = _doh(domain, "MX")
    if mx is not None:
        if mx.get("Status") == 3:                         # NXDOMAIN
            verdict = False
        elif any(a.get("type") == 15 for a in mx.get("Answer") or []):
            # A « null MX » (RFC 7505: "0 .") means the domain refuses mail.
            hosts = [str(a.get("data", "")).strip() for a in mx["Answer"] if a.get("type") == 15]
            verdict = any(h not in ("0 .", "0.") for h in hosts)
        else:
            a = _doh(domain, "A")
            if a is not None:
                verdict = any(x.get("type") == 1 for x in a.get("Answer") or [])
    _CACHE[domain] = (time.time() + (_TTL if verdict is not None else 300), verdict)
    return verdict


def check(email: str, dns: bool = True) -> Dict[str, Optional[str]]:
    """{ok, reason, suggestion}. `reason` is the French sentence to show."""
    e = (email or "").strip().lower()
    if not e:
        return {"ok": False, "reason": "L'adresse e-mail est requise.", "suggestion": None}
    if " " in e or ".." in e or not _SHAPE.match(e) or e.split("@")[0].startswith(".") or e.split("@")[0].endswith("."):
        return {"ok": False, "reason": "Adresse e-mail invalide. Exemple : prenom.nom@gmail.com", "suggestion": None}
    local, domain = e.rsplit("@", 1)
    if domain in TYPOS:
        fix = f"{local}@{TYPOS[domain]}"
        return {"ok": False, "reason": f"Vouliez-vous dire {fix} ?", "suggestion": fix}
    if domain in DISPOSABLE or any(domain.endswith("." + d) for d in DISPOSABLE):
        return {"ok": False, "reason": "Les adresses e-mail jetables ne sont pas acceptées. Utilisez votre adresse habituelle.",
                "suggestion": None}
    if dns and domain_receives_mail(domain) is False:
        return {"ok": False, "reason": f"Le domaine « {domain} » ne reçoit pas d'e-mails. Vérifiez l'adresse.",
                "suggestion": None}
    return {"ok": True, "reason": None, "suggestion": None}
