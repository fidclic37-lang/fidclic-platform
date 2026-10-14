"""
iOS 27 poster + Pass Designer template.

Until 2026-10-11 the tampons meter was painted onto the template's background.
Since the user's call that day (« tampon meter to be below the qr code, so
that it will not interfere with anything in the bg image of the card »), nothing is painted on a
poster: the template's background goes out untouched, and the tampons are the
{jauge} text field Wallet writes under the QR. The full behaviour is covered by
tests/test_card_poster_jauge.py; this file keeps the template's side.

Run: cd api && /usr/local/bin/python3 tests/test_poster_meter_template.py
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from features import pass_designer as PD
from features import wallet_passes as WP

GREY = (90, 90, 90)


def _bg(w: int = 690, h: int = 1010) -> bytes:
    b = io.BytesIO(); Image.new("RGB", (w, h), GREY).save(b, "PNG"); return b.getvalue()


def _files() -> dict:
    pj = {"formatVersion": 1, "generic": {}, "posterGeneric": {}}
    return {"pass.json": json.dumps(pj).encode(), "background@2x.png": _bg(), "background.png": _bg(345, 505)}


def _payload(stamps: int, show_meter=True, threshold: int = 10) -> dict:
    return {"card": {"brand_color": "#FF0000", "reward_threshold": threshold, "stamps_earned": stamps,
                     "show_meter": show_meter},
            "customer": {"visits": stamps}, "tenant": {"id": "t1"}}


def test_template_background_is_never_painted():
    files = _files()
    orig_load, orig_tf, orig_bpj = PD.load, WP._template_files, WP.build_pass_json
    PD.load = lambda tid: {"id": "tpl"}
    WP._template_files = lambda tpl, card: {k: v for k, v in files.items() if k != "pass.json"}
    WP.build_pass_json = lambda payload: json.loads(files["pass.json"])
    try:
        for stamps in (0, 4, 10):
            out = WP.pass_files(_payload(stamps))
            assert out["background@2x.png"] == files["background@2x.png"], stamps
            assert out["background.png"] == files["background.png"], stamps
    finally:
        PD.load, WP._template_files, WP.build_pass_json = orig_load, orig_tf, orig_bpj


def test_jauge_placeholder_fills_and_notifies():
    rows = [{"key": "JAUGE", "label": "TAMPONS · {tampons}", "value": "{jauge}"}]
    out = PD._fields(rows, {"stamps": "3 / 10", "meter": "●●●○○○○○○○"})
    assert out[0]["value"] == "●●●○○○○○○○"
    assert out[0]["label"] == "TAMPONS · 3 / 10"
    assert "%@" in out[0]["changeMessage"]


def test_painted_poster_meter_is_gone():
    assert not hasattr(WP, "template_poster_with_meter")
    assert not hasattr(WP, "_paint_poster_meter")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
