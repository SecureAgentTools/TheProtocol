"""§FEFRAME W2 — the console's <head> and web manifest name the frame that serves them.

Before W2 every registry served the same built index.html: title "TheProtocol — Sovereign AI Agent Registry", a
canonical of https://theprotocol.cloud/ and an og:url of https://api.theprotocol.cloud/ui, so a link to ASIA's or an
operator's console previewed (and was indexed) as the flagship, and every installed PWA was called "TheProtocol —
POCKET FRAME" whichever registry it came from. The frame manifest's `self` block (core/federation_view.py) now
renders, per registry: <title>, the description, the canonical link, og:* and twitter:* tags, and a
<meta name="tp-frame-theme"> the console reads before it mounts (the frame's own theme without a flash; a person's
saved choice still wins); and the web manifest's name and description.

Pure (strings in, strings out): a tag the build no longer carries is skipped, never invented; a `self` block without
a display name leaves the page as built. tests/test_frame_head.py.
"""
from __future__ import annotations

import html as _html
import json
import re
from typing import Any, Dict, Mapping, Optional

BRAND = "TheProtocol"


def _attr(v: str) -> str:
    return _html.escape(v, quote=True)


def head_facts(me: Optional[Mapping[str, Any]]) -> Optional[Dict[str, str]]:
    """The values the head is rendered from, or None when the manifest names no registry."""
    if not isinstance(me, Mapping):
        return None
    name = str(me.get("display_name") or me.get("name") or "").strip()
    if not name:
        return None
    console = str(me.get("console_url") or me.get("public_url") or "").rstrip("/")
    public = str(me.get("public_url") or console or "").rstrip("/")
    unit = str(me.get("currency_name") or me.get("currency") or "").strip()
    role = "cloud operator" if me.get("role") == "operator" else "sovereign registry"
    desc = f"{name}: a {role} of the {BRAND} federation" + (f", settling in {unit}" if unit else "") + \
           ". Agents with their own identity, a ledger anyone can audit, and a federation of independent frames."
    theme = str(me.get("theme") or "").strip().lower()
    return {
        "title": f"{name} — {BRAND}",
        "description": desc,
        "canonical": f"{console}/" if console else "",
        "og_url": f"{console}/" if console else "",
        "og_image": f"{public}/static/og-image.jpg" if public else "",
        "theme": theme if theme in ("neural", "sovereign") else "",
        "name": name,
    }


def _sub_attr(html: str, tag_re: str, attr: str, value: str) -> str:
    """Replace `attr="..."` inside the first tag matching `tag_re` (a regex for the tag's opening, without `>`)."""
    if not value:
        return html
    m = re.search(tag_re + r"[^>]*>", html)
    if not m:
        return html
    tag = m.group(0)
    new_tag, n = re.subn(rf'{attr}="[^"]*"', f'{attr}="{_attr(value)}"', tag, count=1)
    if not n:
        return html
    return html[:m.start()] + new_tag + html[m.end():]


def render_index(html: str, me: Optional[Mapping[str, Any]]) -> str:
    f = head_facts(me)
    if not f:
        return html
    out = re.sub(r"<title>[^<]*</title>", f"<title>{_html.escape(f['title'])}</title>", html, count=1)
    out = _sub_attr(out, r'<meta\s+name="description"', "content", f["description"])
    out = _sub_attr(out, r'<link\s+rel="canonical"', "href", f["canonical"])
    out = _sub_attr(out, r'<meta\s+property="og:title"', "content", f["title"])
    out = _sub_attr(out, r'<meta\s+property="og:description"', "content", f["description"])
    out = _sub_attr(out, r'<meta\s+property="og:url"', "content", f["og_url"])
    out = _sub_attr(out, r'<meta\s+property="og:image"', "content", f["og_image"])
    out = _sub_attr(out, r'<meta\s+name="twitter:title"', "content", f["title"])
    out = _sub_attr(out, r'<meta\s+name="twitter:description"', "content", f["description"])
    out = _sub_attr(out, r'<meta\s+name="twitter:image"', "content", f["og_image"])
    if f["theme"] and 'name="tp-frame-theme"' not in out:
        out = out.replace("</title>", f'</title>\n    <meta name="tp-frame-theme" content="{_attr(f["theme"])}">', 1)
    return out


def render_webmanifest(raw: str, me: Optional[Mapping[str, Any]]) -> str:
    """The built web manifest with this frame's name; anything unreadable is returned as built."""
    f = head_facts(me)
    if not f:
        return raw
    try:
        m = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(m, dict):
        return raw
    m["name"] = f"{f['name']} — {BRAND} POCKET FRAME"
    m["description"] = f["description"]
    return json.dumps(m, ensure_ascii=False)
