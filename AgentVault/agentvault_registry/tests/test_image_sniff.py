"""§DEPS (2026-09-28): core/image_sniff.py answers what imghdr answered, so the registry-card uploads accept and refuse
exactly as before once the interpreter no longer has imghdr (removed in Python 3.13).

The fixed answers below were read from imghdr.what on Python 3.11 (2026-09-28); where imghdr still exists (3.11, 3.12)
every header is compared with imghdr.what itself again. A JPEG that imghdr never recognised (an ICC-profile FF D8 FF E2
start) stays unrecognised: the upload rule does not widen with the interpreter.
"""
from __future__ import annotations

import importlib.util
import sys
import warnings

import pytest

from agentvault_registry.core.image_sniff import sniff_image_format

PNG = b"\211PNG\r\n\032\n" + b"\x00" * 24
JFIF = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 20
EXIF = b"\xff\xd8\xff\xe1\x00\x10Exif\x00" + b"\x00" * 20
RAW_JPEG = b"\xff\xd8\xff\xdb" + b"\x00" * 28
ICC_JPEG = b"\xff\xd8\xff\xe2\x0c\x58ICC_PROFILE" + b"\x00" * 16
CORPUS = {
    "png": (PNG, "png"), "jfif": (JFIF, "jpeg"), "exif": (EXIF, "jpeg"), "raw_jpeg": (RAW_JPEG, "jpeg"),
    "icc_jpeg": (ICC_JPEG, None), "gif87": (b"GIF87a" + b"\x00" * 26, "gif"), "gif89": (b"GIF89a" + b"\x00" * 26, "gif"),
    "tiff_mm": (b"MM\x00*" + b"\x00" * 28, "tiff"), "tiff_ii": (b"II*\x00" + b"\x00" * 28, "tiff"),
    "rgb": (b"\001\332" + b"\x00" * 30, "rgb"), "pbm": (b"P1\n1 1\n1\n", "pbm"), "pgm": (b"P5 1 1 255\n\x00", "pgm"),
    "ppm": (b"P6\t1 1 255\n\x00\x00\x00", "ppm"), "p7": (b"P7\n", None), "rast": (b"\x59\xA6\x6A\x95" + b"\x00" * 28, "rast"),
    "xbm": (b"#define w 1\n", "xbm"), "bmp": (b"BM" + b"\x00" * 30, "bmp"),
    "webp": (b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 16, "webp"), "exr": (b"\x76\x2f\x31\x01" + b"\x00" * 28, "exr"),
    "svg": (b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', None), "empty": (b"", None), "short": (b"P", None),
}


@pytest.mark.parametrize("name", sorted(CORPUS))
def test_the_fixed_answers(name):
    raw, want = CORPUS[name]
    assert sniff_image_format(raw) == want


def test_it_is_imghdr_where_imghdr_exists_and_imghdr_is_gone_only_from_3_13():
    # never a skip (the build's skip ceiling counts them): where imghdr exists every header is compared with it, and
    # where it does not, the interpreter must be one that removed it
    if importlib.util.find_spec("imghdr") is None:
        assert sys.version_info >= (3, 13), sys.version
        return
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import imghdr
    differ = {n: (sniff_image_format(raw), imghdr.what(None, h=raw)) for n, (raw, _) in CORPUS.items()
              if sniff_image_format(raw) != imghdr.what(None, h=raw)}
    assert differ == {}


def test_only_png_and_jpeg_pass_the_upload_rule():
    from agentvault_registry.routers.admin_registry_card import _ICON_ALLOWED_FORMATS
    passed = sorted(n for n, (raw, _) in CORPUS.items() if sniff_image_format(raw) in _ICON_ALLOWED_FORMATS)
    assert passed == ["exif", "jfif", "png", "raw_jpeg"]
