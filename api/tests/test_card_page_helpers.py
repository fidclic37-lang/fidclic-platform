"""
The redesigned « Ma carte en ligne » page (2026-11-25) — the pure rules
behind its new fields, one by one:
  • social_url / socials: a handle or a link of that network → one https
    link on that network's own domain, anything else dropped (XSS, other
    domains, spaces, unicode, very long input);
  • first_name: the first word of the name, as written;
  • hero_photo_url: the photo of the iOS 27 poster, in the poster's order,
    never a generated gradient, always a link a plain <img> can load;
  • parse_before / clamp_limit: the activity feed's paging inputs.

Run: cd api && python3 tests/test_card_page_helpers.py
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-card-page-helpers")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    from features import card_page as CP
    from services import media as M

    u = CP.social_url

    print("Instagram")
    check("a handle with @", u("instagram", "@royaltrim") == "https://www.instagram.com/royaltrim")
    check("a handle without @", u("instagram", "royal.trim_37") == "https://www.instagram.com/royal.trim_37")
    check("spaces around are trimmed", u("instagram", "  @royaltrim  ") == "https://www.instagram.com/royaltrim")
    check("a full link", u("instagram", "https://www.instagram.com/royaltrim/") == "https://www.instagram.com/royaltrim")
    check("http → https, no www", u("instagram", "http://instagram.com/royaltrim") == "https://www.instagram.com/royaltrim")
    check("no scheme", u("instagram", "instagram.com/royaltrim") == "https://www.instagram.com/royaltrim")
    check("mixed case host, query string dropped",
          u("instagram", "HTTPS://WWW.Instagram.COM/RoyalTrim?igsh=abc&utm=x#top") == "https://www.instagram.com/RoyalTrim")
    check("m. subdomain", u("instagram", "https://m.instagram.com/royaltrim") == "https://www.instagram.com/royaltrim")
    check("a post link is not a profile → dropped", u("instagram", "https://instagram.com/p/Cxyz123/") is None)
    check("another domain → dropped", u("instagram", "https://evil.com/royaltrim") is None)
    check("look-alike domain → dropped", u("instagram", "https://instagram.com.evil.com/royaltrim") is None)
    check("userinfo trick → dropped", u("instagram", "https://instagram.com@evil.com/royaltrim") is None)
    check("a port → dropped", u("instagram", "https://instagram.com:8443/royaltrim") is None)
    check("javascript: → dropped", u("instagram", "javascript:alert(1)") is None)
    check("JaVaScRiPt: with spaces → dropped", u("instagram", " JaVaScRiPt:alert(document.cookie)") is None)
    check("data: → dropped", u("instagram", "data:text/html,<script>alert(1)</script>") is None)
    check("html in a handle → dropped", u("instagram", '"><img src=x onerror=alert(1)>') is None)
    check("a space inside → dropped", u("instagram", "royal trim") is None)
    check("unicode handle → dropped", u("instagram", "royaltrïm") is None)
    check("unicode look-alike domain → dropped", u("instagram", "https://instаgram.com/royaltrim") is None)
    check("too long a handle (31) → dropped", u("instagram", "a" * 31) is None)
    check("30 chars → kept", u("instagram", "a" * 30) == "https://www.instagram.com/" + "a" * 30)
    check("very long input (10 000 chars) → dropped quickly", u("instagram", "https://instagram.com/" + "a" * 10000) is None)
    check("empty → None", u("instagram", "") is None)
    check("only @ → None", u("instagram", "@") is None)
    check("None → None", u("instagram", None) is None)
    check("a number → None", u("instagram", 12345) is None)
    check("a TikTok link in the Instagram field → dropped", u("instagram", "https://www.tiktok.com/@royaltrim") is None)
    check("backslash trick → dropped", u("instagram", "https://instagram.com\\@evil.com/x") is None)

    print("Facebook")
    check("a page name", u("facebook", "royaltrim37") == "https://www.facebook.com/royaltrim37")
    check("@ handle", u("facebook", "@Royal.Trim") == "https://www.facebook.com/Royal.Trim")
    check("a full link", u("facebook", "https://www.facebook.com/royaltrim37/") == "https://www.facebook.com/royaltrim37")
    check("fb.com", u("facebook", "https://fb.com/royaltrim37") == "https://www.facebook.com/royaltrim37")
    check("m.facebook.com", u("facebook", "m.facebook.com/royaltrim37?ref=bookmarks") == "https://www.facebook.com/royaltrim37")
    check("profile.php?id= keeps its numeric id",
          u("facebook", "https://www.facebook.com/profile.php?id=100089123456789&mibextid=x")
          == "https://www.facebook.com/profile.php?id=100089123456789")
    check("profile.php with a non-numeric id → dropped", u("facebook", "https://facebook.com/profile.php?id=abc") is None)
    check("a dash in a page name", u("facebook", "le-cafe-de-tours") == "https://www.facebook.com/le-cafe-de-tours")
    check("sharer link → dropped", u("facebook", "https://www.facebook.com/sharer/sharer.php?u=https://evil.com") is None)
    check("other domain → dropped", u("facebook", "https://facebook.evil.com/royaltrim") is None)
    check("javascript: → dropped", u("facebook", "javascript://facebook.com/%0aalert(1)") is None)

    print("TikTok")
    check("@ handle", u("tiktok", "@royaltrim") == "https://www.tiktok.com/@royaltrim")
    check("bare handle", u("tiktok", "royal_trim.37") == "https://www.tiktok.com/@royal_trim.37")
    check("a full link", u("tiktok", "https://www.tiktok.com/@royaltrim?lang=fr") == "https://www.tiktok.com/@royaltrim")
    check("a profile link with trailing slash", u("tiktok", "tiktok.com/@RoyalTrim/") == "https://www.tiktok.com/@RoyalTrim")
    check("a video link → its profile", u("tiktok", "https://www.tiktok.com/@royaltrim/video/7312345678901234567")
          == "https://www.tiktok.com/@royaltrim")
    check("a short vm. link (no handle) → dropped", u("tiktok", "https://vm.tiktok.com/ZMabc123/") is None)
    check("a link without @ → dropped", u("tiktok", "https://www.tiktok.com/royaltrim") is None)
    check("25 chars → dropped", u("tiktok", "a" * 25) is None)
    check("other domain → dropped", u("tiktok", "https://tiktok.co/@royaltrim") is None)

    print("Snapchat")
    check("bare handle", u("snapchat", "royaltrim") == "https://www.snapchat.com/add/royaltrim")
    check("@ handle", u("snapchat", "@royal-trim") == "https://www.snapchat.com/add/royal-trim")
    check("an /add/ link", u("snapchat", "https://www.snapchat.com/add/royaltrim?share_id=x")
          == "https://www.snapchat.com/add/royaltrim")
    check("an /@ link", u("snapchat", "https://snapchat.com/@royaltrim") == "https://www.snapchat.com/add/royaltrim")
    check("2 chars → dropped", u("snapchat", "ab") is None)
    check("16 chars → dropped", u("snapchat", "a" * 16) is None)
    check("other path → dropped", u("snapchat", "https://www.snapchat.com/discover/x") is None)
    check("an unknown network → None", u("myspace", "royaltrim") is None)

    print("socials (the list the page shows)")
    s = CP.socials({"snapchat": "royaltrim", "instagram": "@royaltrim", "tiktok": "javascript:alert(1)",
                    "facebook": "https://fb.com/royaltrim37", "website": "x"})
    check(f"order instagram, facebook, tiktok, snapchat; bad TikTok dropped ({s})",
          s == [{"network": "instagram", "url": "https://www.instagram.com/royaltrim"},
                {"network": "facebook", "url": "https://www.facebook.com/royaltrim37"},
                {"network": "snapchat", "url": "https://www.snapchat.com/add/royaltrim"}])
    check("no details → []", CP.socials(None) == [] and CP.socials({}) == [] and CP.socials("x") == [])
    check("all empty → []", CP.socials({"instagram": "", "facebook": " ", "tiktok": None, "snapchat": "@"}) == [])
    every = CP.socials({"instagram": "a", "facebook": "bbbbb", "tiktok": "c", "snapchat": "ddd"})
    check("every url is https", every and all(x["url"].startswith("https://") for x in every))

    print("first_name")
    check("two words", CP.first_name("Marie Dupont") == "Marie")
    check("one word", CP.first_name("Mahdi") == "Mahdi")
    check("extra spaces", CP.first_name("   Jean    Pierre  Martin ") == "Jean")
    check("tab / newline", CP.first_name("\tLéa\nMartin") == "Léa")
    check("kept as written (all caps)", CP.first_name("MAHDI BEN") == "MAHDI")
    check("hyphenated stays whole", CP.first_name("Jean-Luc Picard") == "Jean-Luc")
    check("empty → ''", CP.first_name("") == "" and CP.first_name("   ") == "" and CP.first_name(None) == "")
    check("not a string → ''", CP.first_name(42) == "")
    check("a very long word is capped at 40", len(CP.first_name("A" * 500)) == 40)

    print("hero_photo_url (the poster's photo)")
    h = CP.hero_photo_url
    camp = {"campaign_offer": {"title": "Promo", "image_url": "/api/media/" + "a" * 32, "wallet_photo": True},
            "poster_image_url": "/api/media/" + "b" * 32, "hero_image_url": "/api/media/" + "c" * 32}
    check("1. the live campaign's photo when it is on the Wallet card", h(camp) == "/api/media/" + "a" * 32)
    no_wallet = {**camp, "campaign_offer": {**camp["campaign_offer"], "wallet_photo": False}}
    check("…not when the campaign's photo stays in « Mes offres »", h(no_wallet) == "/api/media/" + "b" * 32)
    check("2. else the « Ajuster » poster image",
          h({"poster_image_url": "https://cdn.exemple.fr/p.jpg", "hero_image_url": "/api/media/" + "c" * 32})
          == "https://cdn.exemple.fr/p.jpg")
    check("3. else the banner (hero_mode image by default)", h({"hero_image_url": "/api/media/" + "c" * 32})
          == "/api/media/" + "c" * 32)
    check("…also in composite mode", h({"hero_mode": "composite", "hero_image_url": "https://x.fr/h.png"}) == "https://x.fr/h.png")
    check("…not when the owner chose the brand colour", h({"hero_mode": "brand", "hero_image_url": "https://x.fr/h.png"}) is None)
    check("nothing → None (never a gradient)", h({}) is None and h(None) is None)
    check("an http:// poster is skipped → the banner",
          h({"poster_image_url": "http://x.fr/p.jpg", "hero_image_url": "https://x.fr/h.png"}) == "https://x.fr/h.png")
    check("javascript: → None", h({"hero_image_url": "javascript:alert(1)"}) is None)
    check("a link that would break out of CSS url() → None", h({"hero_image_url": "https://x.fr/a.png\") ;}"}) is None)
    check("an absolute link to our media stays", h({"hero_image_url": "https://app.fidclic.com/api/media/" + "d" * 32})
          == "https://app.fidclic.com/api/media/" + "d" * 32)
    check("a huge https link (> 2048) → None", h({"hero_image_url": "https://x.fr/" + "a" * 3000}) is None)
    # a data: URL (an old card): moved to the media store, the page gets its public link
    db = mongomock.MongoClient().db
    M.init(db)
    import base64
    png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 2000).decode()
    out = h({"hero_image_url": png})
    check(f"a big data:image → our /api/media link ({out})", isinstance(out, str) and out.startswith("/api/media/")
          and db["media"].count_documents({}) == 1)
    check("…the same picture again → the same link, stored once", h({"hero_image_url": png}) == out
          and db["media"].count_documents({}) == 1)
    tiny = "data:image/png;base64," + base64.b64encode(b"\x89PNG").decode()
    check("a tiny raster data:image stays inline", h({"hero_image_url": tiny}) == tiny)
    check("an svg data: URL → None", h({"hero_image_url": "data:image/svg+xml,<svg onload=alert(1)>"}) is None)
    check("a data:text → None", h({"hero_image_url": "data:text/html,<b>x</b>"}) is None)

    print("parse_before")
    pb = CP.parse_before
    check("Z", pb("2026-11-25T10:00:00Z") == datetime(2026, 11, 25, 10, tzinfo=timezone.utc))
    check("+01:00 (Paris winter)", pb("2026-11-25T11:00:00+01:00") == datetime(2026, 11, 25, 10, tzinfo=timezone.utc))
    check("+02:00 (Paris summer)", pb("2026-07-01T12:00:00+02:00") == datetime(2026, 7, 1, 10, tzinfo=timezone.utc))
    check("an unencoded + (a space) still reads", pb("2026-11-25T11:00:00 01:00") == datetime(2026, 11, 25, 10, tzinfo=timezone.utc))
    check("naive → UTC", pb("2026-11-25T10:00:00") == datetime(2026, 11, 25, 10, tzinfo=timezone.utc))
    check("microseconds kept", pb("2026-11-25T10:00:00.123456Z").microsecond == 123456)
    check("empty / None → None", pb("") is None and pb(None) is None)
    for bad in ("hier", "2026-13-01T00:00:00Z", "1' or '1'='1", "{\"$gt\": 1}", "9" * 500):
        try:
            pb(bad)
            check(f"{bad[:20]!r} → ValueError", False)
        except ValueError:
            check(f"{bad[:20]!r} → ValueError", True)

    print("clamp_limit")
    cl = CP.clamp_limit
    check("default 20", cl(None) == 20)
    check("0 → 1, negative → 1", cl(0) == 1 and cl(-5) == 1)
    check("1 stays 1, 100 stays 100", cl(1) == 1 and cl(100) == 100)
    check("101 → 100, huge → 100", cl(101) == 100 and cl(10 ** 9) == 100)

    print("iso")
    check("aware → Z", CP.iso(datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc)) == "2026-03-29T01:30:00Z")
    check("naive (pymongo) → read as UTC", CP.iso(datetime(2026, 3, 29, 1, 30)) == "2026-03-29T01:30:00Z")
    check("Paris time → UTC", CP.iso(datetime(2026, 3, 29, 3, 30, tzinfo=timezone(timedelta(hours=2))))
          == "2026-03-29T01:30:00Z")
    check("milliseconds kept", CP.iso(datetime(2026, 3, 29, 1, 30, 0, 123000, tzinfo=timezone.utc)) == "2026-03-29T01:30:00.123Z")
    check("a string date (old rows) → parsed", CP.iso("2026-03-29T01:30:00+00:00") == "2026-03-29T01:30:00Z")
    check("garbage → None", CP.iso("x") is None and CP.iso(None) is None)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
