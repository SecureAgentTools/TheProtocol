"""V0662, item 14 (order gwo_d721ad2f8118863d62815103): a card's icon, fetched once by the registry and served from its
own origin.

A card's iconUrl is an address its developer wrote, or a peer relayed. Bound straight to an image, every reader's
browser dialled it. Now the registry reads the address from the card it holds, fetches it through the one outbound
guard (core/outbound_guard, site card_icon), keeps what it made of it in Redis, and serves that at
GET /api/v1/agent-cards/{did}/icon (routers/card_icons); the console draws card icons only from there
(services/agentAvatar.cardIconSrc).

What is served is never the bytes as they came:
  - a raster (PNG, JPEG, GIF, WebP or ICO, told by its bytes, never by a header) is decoded and written again as a PNG
    of at most ICON_SIDE px a side; an image that declares more than MAX_SOURCE_PIXELS is refused before it is decoded,
    and the decoder is offered those five formats only (never one that runs a renderer, like EPS);
  - an SVG is parsed with no DTD, no entities and no network, then rebuilt from an allowlist of drawing elements:
    no script, no event handler, no reference outside the document, no style that loads or escapes anything;
  - a body over MAX_BYTES is refused while it streams, and a whole fetch is bounded by FETCH_TOTAL_SEC.
The cache keys on the address (a changed iconUrl is a new fetch); a failure is kept for FAIL_CACHE_SEC so a broken
icon is not fetched on every page view, and a reader that finds another worker fetching waits for it. Without Redis
nothing is fetched: one outbound request per page view per reader is what this exists to stop.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import io
import json
import logging
import os
import re
import urllib.parse
from typing import Any, Awaitable, Callable, NamedTuple, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

SITE = "card_icon"


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, "") or default))
    except ValueError:
        return default


MAX_BYTES = _env_int("CARD_ICON_MAX_BYTES", 256 * 1024)      # what is read from the source, before any decoding
MAX_SOURCE_PIXELS = 4096 * 4096                                  # what a raster may declare before it is decoded
ICON_SIDE = 256                                                  # the longest side of what is served
CACHE_SEC = _env_int("CARD_ICON_CACHE_SEC", 24 * 3600)
FAIL_CACHE_SEC = _env_int("CARD_ICON_FAIL_CACHE_SEC", 15 * 60)
FETCH_TIMEOUT_SEC = 8.0
FETCH_TOTAL_SEC = 15.0
MAX_REDIRECTS = 2
LOCK_SEC = 25                                                    # longer than a whole fetch
WAIT_SEC = 20.0                                                  # how long a second reader waits for the first
POLL_SEC = 0.25
_KEY_PREFIX = "registry:cardicon:v1:"
_USER_AGENT = "TheProtocol-Registry card-icon fetcher"


class Icon(NamedTuple):
    body: bytes
    content_type: str


class IconUnavailable(Exception):
    """The icon cannot be served here; `reason` is a short word the route repeats."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --- the card's address ------------------------------------------------------------------------------------------

def icon_address(card_data: Any) -> Optional[str]:
    """The icon a card names (A2A's iconUrl; icon_url as some cards spell it), trimmed; None when it names none."""
    if not isinstance(card_data, dict):
        return None
    for key in ("iconUrl", "icon_url"):
        v = card_data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def native_card_stmt(did: str):
    from sqlalchemy import select
    from .. import models
    return (select(models.AgentCard.card_data)
            .where(models.AgentCard.agent_did == did, models.AgentCard.is_active.is_(True))
            .limit(1))


def mirror_card_stmt(did: str):
    """A mirrored card keeps its DID inside card_data. A containment test is what the GIN index on card_data serves;
    a ->> comparison would read every card."""
    from sqlalchemy import select
    from .. import models
    return (select(models.AgentCard.card_data)
            .where(models.AgentCard.card_data.contains({"did": did}), models.AgentCard.is_active.is_(True))
            .order_by(models.AgentCard.updated_at.desc())
            .limit(1))


async def card_icon_address(db: Any, did: str) -> Optional[Tuple[str, bool]]:
    """(the icon address, whether the card is this registry's own) for the active card with this DID, or None."""
    from .home_extensions import is_native
    card = (await db.execute(native_card_stmt(did))).scalar_one_or_none()
    if card is None:
        card = (await db.execute(mirror_card_stmt(did))).scalar_one_or_none()
    address = icon_address(card)
    if address is None:
        return None
    return address, is_native(card)


# --- what is served ----------------------------------------------------------------------------------------------

def _looks_like_svg(data: bytes) -> bool:
    head = data[:1024].lstrip(b"\xef\xbb\xbf \t\r\n")
    return head.startswith(b"<") and b"<svg" in data[:4096].lower()


_RASTER_FORMATS = ["PNG", "JPEG", "GIF", "WEBP", "ICO"]


def _raster(data: bytes) -> Icon:
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(data), formats=_RASTER_FORMATS)      # lazy: reads the header only
    except Image.DecompressionBombError:   # Pillow's own refusal of a header far past its limit, at open
        raise IconUnavailable("too_many_pixels")
    except Exception:  # noqa: BLE001 — not one of the five formats, or not an image at all
        raise IconUnavailable("not_an_image")
    try:
        w, h = img.size
        if w <= 0 or h <= 0 or w * h > MAX_SOURCE_PIXELS:
            raise IconUnavailable("too_many_pixels")
        try:
            img.seek(0)                    # an animation: its first frame
            img.load()
            img = img.convert("RGBA")
            img.thumbnail((ICON_SIDE, ICON_SIDE))
            out = io.BytesIO()
            img.save(out, "PNG", optimize=True)
        except IconUnavailable:
            raise
        except Exception:  # noqa: BLE001 — a header that promised an image the data cannot keep
            raise IconUnavailable("not_an_image")
        return Icon(out.getvalue(), "image/png")
    finally:
        try:
            img.close()
        except Exception:  # noqa: BLE001
            pass


_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"
_XML_NS = "http://www.w3.org/XML/1998/namespace"
# drawing only: no script, foreignObject, image, a, iframe, animate/set (an animation can rewrite an href), metadata
_SVG_ELEMENTS = frozenset({
    "svg", "g", "defs", "symbol", "use", "title", "desc", "style",
    "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "text", "tspan", "textPath",
    "linearGradient", "radialGradient", "stop", "pattern", "clipPath", "mask", "marker",
    "filter", "feGaussianBlur", "feOffset", "feBlend", "feColorMatrix", "feComposite", "feFlood", "feMerge",
    "feMergeNode", "feDropShadow", "feMorphology",
})
_CSS_URL = re.compile(r"url\(\s*(['\"]?)([^)'\"]*)")


def _css_ok(text: str) -> bool:
    """A style may only point inside the document (url(#id)). An escape could hide anything, so none is taken."""
    t = text.lower()
    if "\\" in t or "@import" in t or "expression(" in t or "javascript:" in t or "-moz-binding" in t \
            or "behavior:" in t:
        return False
    return all(m.group(2).strip().startswith("#") for m in _CSS_URL.finditer(t))


def _attr_ok(local: str, ns: Optional[str], value: str) -> bool:
    if ns not in (None, _XLINK_NS, _XML_NS):
        return False
    if local.lower().startswith("on"):
        return False
    v = value.strip().lower()
    if local == "href":
        return v.startswith("#")
    if "javascript:" in v or "data:" in v:
        return False
    if local == "style" or "url(" in v:
        return _css_ok(value)
    return True


def sanitise_svg(data: bytes) -> bytes:
    """The SVG rebuilt from the allowlist, or IconUnavailable('svg_refused')."""
    from lxml import etree
    low = data.lower()
    if b"<!doctype" in low or b"<!entity" in low:
        raise IconUnavailable("svg_refused")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False,
                             huge_tree=False, remove_comments=True, remove_pis=True)
    try:
        root = etree.fromstring(data, parser)
    except Exception:  # noqa: BLE001 — not well-formed
        raise IconUnavailable("svg_refused")
    q = etree.QName(root)
    if q.namespace != _SVG_NS or q.localname != "svg":
        raise IconUnavailable("svg_refused")
    doomed = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            doomed.append(el)
            continue
        eq = etree.QName(el)
        if eq.namespace != _SVG_NS or eq.localname not in _SVG_ELEMENTS:
            doomed.append(el)
            continue
        if eq.localname == "style" and not _css_ok(el.text or ""):
            doomed.append(el)
            continue
        for name in list(el.attrib):
            aq = etree.QName(name)
            if not _attr_ok(aq.localname, aq.namespace, el.attrib[name]):
                del el.attrib[name]
    for el in doomed:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
    out = etree.tostring(root, encoding="utf-8")
    if len(out) > MAX_BYTES:
        raise IconUnavailable("too_large")
    return out


def normalise(data: bytes) -> Icon:
    """What this registry serves for the bytes a card's icon address gave; IconUnavailable when it serves nothing."""
    if not data:
        raise IconUnavailable("not_an_image")
    if len(data) > MAX_BYTES:
        raise IconUnavailable("too_large")
    if _looks_like_svg(data):
        return Icon(sanitise_svg(data), "image/svg+xml")
    return _raster(data)


def decode_data_url(url: str) -> bytes:
    """The bytes of a data: address (base64 or percent-encoded); nothing is fetched."""
    if len(url) > MAX_BYTES * 4 // 3 + 256:
        raise IconUnavailable("too_large")
    head, sep, payload = url.partition(",")
    if not sep or not head.lower().startswith("data:"):
        raise IconUnavailable("malformed")
    try:
        if head.lower().endswith(";base64"):
            return base64.b64decode(payload, validate=False)
        return urllib.parse.unquote_to_bytes(payload)
    except (binascii.Error, ValueError):
        raise IconUnavailable("malformed")


# --- the fetch ---------------------------------------------------------------------------------------------------

async def _fetch(url: str, inner: Optional[httpx.AsyncBaseTransport]) -> bytes:
    from ..core.outbound_guard import HOP_EXTENSION, guarded_client
    async with guarded_client(SITE, inner=inner, timeout=FETCH_TIMEOUT_SEC, verify=True) as client:
        request = client.build_request("GET", url, headers={"Accept": "image/*", "User-Agent": _USER_AGENT})
        for hop in range(MAX_REDIRECTS + 1):
            response = await client.send(request, stream=True)
            try:
                if response.is_redirect:
                    nxt = response.next_request
                    if nxt is None:
                        raise IconUnavailable(f"http_{response.status_code}")
                    if hop == MAX_REDIRECTS:
                        raise IconUnavailable("redirect_limit")
                    nxt.extensions = {**nxt.extensions, HOP_EXTENSION: "redirect"}
                    request = nxt
                    continue
                if response.status_code != 200:
                    raise IconUnavailable(f"http_{response.status_code}")
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > MAX_BYTES:
                    raise IconUnavailable("too_large")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise IconUnavailable("too_large")
                return bytes(body)
            finally:
                await response.aclose()
    raise IconUnavailable("redirect_limit")   # not reached: the loop returns or raises


async def fetch_icon(url: str, *, inner: Optional[httpx.AsyncBaseTransport] = None) -> bytes:
    """The bytes at a card's icon address, fetched through the outbound guard; IconUnavailable(reason) otherwise.
    `inner` is the connection layer under the guard (the tests' transport); the guard decides and pins every hop."""
    from ..core.outbound_guard import OutboundRefused
    scheme = url.split(":", 1)[0].strip().lower() if ":" in url else ""
    if scheme not in ("http", "https"):
        raise IconUnavailable("scheme")
    try:
        return await asyncio.wait_for(_fetch(url, inner), FETCH_TOTAL_SEC)
    except IconUnavailable:
        raise
    except OutboundRefused as e:
        raise IconUnavailable(f"refused_{e.reason}")
    except (asyncio.TimeoutError, httpx.TimeoutException):
        raise IconUnavailable("timeout")
    except httpx.HTTPError:
        raise IconUnavailable("unreachable")


# --- the cache ---------------------------------------------------------------------------------------------------

def cache_key(url: str) -> str:
    return _KEY_PREFIX + hashlib.sha256(url.encode("utf-8", "surrogatepass")).hexdigest()


def _entry(raw: Any) -> Optional[dict]:
    if raw is None:
        return None
    try:
        return json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw)
    except Exception:  # noqa: BLE001 — a value this module did not write: fetch again
        return None


def _icon_of(entry: dict) -> Icon:
    if "fail" in entry:
        raise IconUnavailable(str(entry["fail"]))
    return Icon(base64.b64decode(entry["b64"]), str(entry["ct"]))


async def redis_handle() -> Any:
    """The registry's one shared Redis handle (background_tasks.leader), or None."""
    try:
        from ..background_tasks.leader import get_redis
        return await get_redis()
    except Exception:  # noqa: BLE001
        return None


async def icon_for_url(url: str, *, redis: Any,
                       fetch: Optional[Callable[[str], Awaitable[bytes]]] = None) -> Icon:
    """The icon this registry serves for `url`, from the cache or made once; IconUnavailable(reason) otherwise."""
    if redis is None:
        raise IconUnavailable("cache_unavailable")
    key = cache_key(url)
    lock = key + ":lock"
    try:
        hit = _entry(await redis.get(key))
        if hit is not None:
            return _icon_of(hit)
        mine = await redis.set(lock, "1", nx=True, ex=LOCK_SEC)
    except IconUnavailable:
        raise
    except Exception:  # noqa: BLE001 — Redis answered with an error: the same as no Redis
        raise IconUnavailable("cache_unavailable")
    if not mine:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + WAIT_SEC
        while loop.time() < deadline:
            await asyncio.sleep(POLL_SEC)
            try:
                hit = _entry(await redis.get(key))
            except Exception:  # noqa: BLE001
                raise IconUnavailable("cache_unavailable")
            if hit is not None:
                return _icon_of(hit)
        raise IconUnavailable("busy")
    try:
        try:
            if url[:5].lower() == "data:":
                raw = decode_data_url(url)
            else:
                raw = await (fetch or fetch_icon)(url)
            icon = normalise(raw)
        except IconUnavailable as e:
            await redis.set(key, json.dumps({"fail": e.reason}), ex=FAIL_CACHE_SEC)
            logger.info("[card_icon] not served (%s), kept for %ss", e.reason, FAIL_CACHE_SEC)
            raise
        await redis.set(key, json.dumps({"ct": icon.content_type, "b64": base64.b64encode(icon.body).decode()}),
                        ex=CACHE_SEC)
        return icon
    finally:
        try:
            await redis.delete(lock)
        except Exception:  # noqa: BLE001 — the lock expires on its own
            pass
