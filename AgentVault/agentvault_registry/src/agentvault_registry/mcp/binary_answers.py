"""§MCPTEST30 (V0640): what an MCP tool answers for a file its route returns (agentvault2-66, on agentvault2-d6's terms).

A developer tool whose route answers a file (an agent package, an onboarding bundle) handed its caller the first 300
characters of the file decoded as text (`{"status": "ok", "raw": ...}`): no MCP caller could ever use the file. It
answers the file's manifest now: its content type, the filename its route named, its size, its entries' names and
sizes for a zip, and its sha256. The content itself (`content_base64`) only where the tool asks for it (generated code:
the agent builder) and only up to CONTENT_CAP_BYTES, the answer saying so above it; a file that can carry a credential
(the onboarding bundle's .env.secret) never travels over MCP and stays on its HTTP route. The MCP audit never keeps the
content (mcp/audit.py drops CONTENT_KEY before it cuts its head).
"""
from __future__ import annotations

import base64
import hashlib
import io
import re
import zipfile
from typing import Any, Dict, List, Optional

CONTENT_KEY = "content_base64"
CONTENT_CAP_BYTES = 2 * 1024 * 1024
FILES_CAP = 200
_ZIP_MAGIC = b"PK\x03\x04"
_TEXTUAL = ("application/json", "application/problem+json", "application/javascript", "application/xml")
_FILENAME = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', re.I)


def is_file(content_type: str, data: bytes) -> bool:
    """Whether a 2xx body is a file to describe rather than text to quote: a zip by its signature, or any content type
    that is neither text nor one of the textual application types."""
    if data[:4] == _ZIP_MAGIC:
        return True
    ct = (content_type or "").split(";")[0].strip().lower()
    return bool(ct) and not ct.startswith("text/") and ct not in _TEXTUAL and not ct.endswith(("+json", "+xml"))


def _filename(disposition: str) -> Optional[str]:
    m = _FILENAME.search(disposition or "")
    return m.group(1).strip() if m else None


def _zip_entries(data: bytes) -> Optional[List[Dict[str, Any]]]:
    """A zip's entries as {name, size}, or None when the body is not a readable zip."""
    if data[:4] != _ZIP_MAGIC:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return [{"name": i.filename, "size": i.file_size} for i in zf.infolist() if not i.is_dir()]
    except (zipfile.BadZipFile, ValueError, OSError):
        return None


def file_manifest(data: bytes, content_type: str, disposition: str = "", *, content: bool = False) -> Dict[str, Any]:
    """The answer for a file: status, content_type, filename, size_bytes, files (a zip's entries) and sha256, in that
    order (a reader keeping the first keys keeps names and sizes); then content_base64 when `content` is asked and the
    file is at most CONTENT_CAP_BYTES, else content_withheld saying why."""
    out: Dict[str, Any] = {"status": "ok", "content_type": (content_type or "application/octet-stream").split(";")[0],
                           "filename": _filename(disposition), "size_bytes": len(data)}
    entries = _zip_entries(data)
    if entries is not None:
        out["files"] = entries[:FILES_CAP]
        if len(entries) > FILES_CAP:
            out["files_total"] = len(entries)
    out["sha256"] = hashlib.sha256(data).hexdigest()
    if not content:
        out["content_withheld"] = ("this file is not sent over MCP (it can carry a credential, such as the agent's "
                                   "secret): download it from its HTTP route")
    elif len(data) > CONTENT_CAP_BYTES:
        out["content_withheld"] = (f"the file is {len(data)} bytes, over the {CONTENT_CAP_BYTES}-byte cap for MCP: "
                                   "download it from its HTTP route")
    else:
        out[CONTENT_KEY] = base64.b64encode(data).decode("ascii")
    return out
