"""§DEPS (2026-09-28): the image-type sniff the registry-card uploads ask, without `imghdr` (removed in Python 3.13).

Every test below is imghdr's own (the Python 3.11 source), byte for byte and in its order, so an upload is accepted or
refused exactly as before: JPEG is 'JFIF' or 'Exif' at bytes 6-10 or a raw FF D8 FF DB start, PNG is the 8-byte
signature. The other names only feed a refusal's message. tests/test_image_sniff.py compares it with imghdr wherever the
interpreter still has it.
"""
from __future__ import annotations

from typing import Optional


def sniff_image_format(h: bytes) -> Optional[str]:
    """imghdr.what(None, h=h): the format name, or None."""
    if h[6:10] in (b"JFIF", b"Exif") or h[:4] == b"\xff\xd8\xff\xdb":
        return "jpeg"
    if h.startswith(b"\211PNG\r\n\032\n"):
        return "png"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if h[:2] in (b"MM", b"II"):
        return "tiff"
    if h.startswith(b"\001\332"):
        return "rgb"
    if len(h) >= 3 and h[0] == ord(b"P") and h[2] in b" \t\n\r":
        if h[1] in b"14":
            return "pbm"
        if h[1] in b"25":
            return "pgm"
        if h[1] in b"36":
            return "ppm"
    if h.startswith(b"\x59\xA6\x6A\x95"):
        return "rast"
    if h.startswith(b"#define "):
        return "xbm"
    if h.startswith(b"BM"):
        return "bmp"
    if h.startswith(b"RIFF") and h[8:12] == b"WEBP":
        return "webp"
    if h.startswith(b"\x76\x2f\x31\x01"):
        return "exr"
    return None
