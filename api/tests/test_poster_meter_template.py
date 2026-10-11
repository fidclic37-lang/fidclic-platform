"""
iOS 27 poster + Pass Designer template (user, 2026-10-11): the template's own
background gets the tampons meter painted on, every visit's pass carries the
new count, and a business that switched the meter off keeps the template's
background untouched.

Run: cd api && /usr/local/bin/python3 tests/test_poster_meter_template.py
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from features import wallet_passes as WP

RED = (255, 0, 0)
GREY = (90, 90, 90)


def _bg(w: int = 690, h: int = 1010) -> bytes:
    b = io.BytesIO(); Image.new("RGB", (w, h), GREY).save(b, "PNG"); return b.getvalue()


def _files(poster: bool = True) -> dict:
    pj = {"formatVersion": 1, "generic": {}}
    if poster:
        pj["posterGeneric"] = {}
    return {"pass.json": json.dumps(pj).encode(), "background@2x.png": _bg(), "background.png": _bg(345, 505)}


def _payload(stamps: int, show_meter=True, threshold: int = 10) -> dict:
    return {"card": {"brand_color": "#FF0000", "reward_threshold": threshold, "stamps_earned": stamps,
                     "show_meter": show_meter},
            "customer": {"visits": stamps}}


def _segment_rgb(png: bytes, i: int, threshold: int = 10):
    """Colour at the middle of segment i of the meter, at that image's scale."""
    img = Image.open(io.BytesIO(png)).convert("RGB")
    W, H = img.size
    k = W / WP.POSTER_W
    pad, gap = 60 * k, 10 * k
    seg = (W - 2 * pad - gap * (threshold - 1)) / threshold
    x = int(pad + i * (seg + gap) + seg / 2)
    y = int(H * 0.205) + max(1, round(12 * k))
    return img.getpixel((x, y))


def test_meter_painted_on_template_background():
    out = WP.template_poster_with_meter(_files(), _payload(3))
    assert set(out) == {"background@2x.png", "background.png"}, out.keys()
    for name in out:
        assert _segment_rgb(out[name], 0) == RED, name          # stamp 1 earned
        assert _segment_rgb(out[name], 2) == RED, name          # stamp 3 earned
        assert _segment_rgb(out[name], 5) != RED, name          # stamp 6 not yet
        assert Image.open(io.BytesIO(out[name])).size == Image.open(io.BytesIO(_files()[name])).size


def test_next_visit_updates_the_count():
    before = WP.template_poster_with_meter(_files(), _payload(3))["background@2x.png"]
    after = WP.template_poster_with_meter(_files(), _payload(7))["background@2x.png"]
    assert _segment_rgb(before, 5) != RED
    assert _segment_rgb(after, 5) == RED and _segment_rgb(after, 6) == RED
    assert _segment_rgb(after, 7) != RED


def test_meter_off_leaves_template_untouched():
    assert WP.template_poster_with_meter(_files(), _payload(3, show_meter=False)) == {}


def test_no_reward_threshold_no_meter():
    assert WP.template_poster_with_meter(_files(), _payload(3, threshold=0)) == {}


def test_template_without_poster_is_left_alone():
    assert WP.template_poster_with_meter(_files(poster=False), _payload(3)) == {}


def test_pass_files_carries_the_meter(monkeypatch=None):
    """pass_files (what build_pkpass signs and the designer previews) runs it."""
    from features import pass_designer as PD
    files = _files()
    orig_load, orig_tf, orig_bpj = PD.load, WP._template_files, WP.build_pass_json
    PD.load = lambda tid: {"id": "tpl"}
    WP._template_files = lambda tpl, card: {k: v for k, v in files.items() if k != "pass.json"}
    WP.build_pass_json = lambda payload: json.loads(files["pass.json"])
    try:
        on = WP.pass_files({**_payload(4), "tenant": {"id": "t1"}})
        off = WP.pass_files({**_payload(4, show_meter=False), "tenant": {"id": "t1"}})
    finally:
        PD.load, WP._template_files, WP.build_pass_json = orig_load, orig_tf, orig_bpj
    assert _segment_rgb(on["background@2x.png"], 3) == RED
    assert off["background@2x.png"] == files["background@2x.png"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
