"""§OURSTATE-5e — media, treated as what it actually is.

Accepting uploads turns a chat into a file host attached to a money network,
which is a magnet for people who want free storage, a malware drop, or a way to
put an executable in front of someone mid-negotiation. So this module is mostly
refusals, and each one is deliberate:

  * **A closed type allowlist, not a blocklist.** Images, PDF, plain text and Markdown.
    A blocklist is a promise to have thought of everything.
  * **SVG is refused by name.** It is a script container that browsers render
    as an image, and "it is just a picture" is exactly how it gets through.
  * **Never served inline.** Every download carries
    `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`, so
    a file can never execute against this origin — the origin that holds the
    session that moves money.
  * **Never public.** There is no unguessable-URL tier: every read is
    authenticated and scoped to a participant of that thread.
  * **Not into a REQUEST.** A stranger cannot push a file at you before you
    accept the thread — the same defanging that keeps a `pay.request` inert in
    a pending thread (§6). A file you did not ask for is worse than a card you
    did not ask for.
  * **Bounded.** Per-file size cap and a per-principal daily quota, both env
    tunable, both refusing with the number.
  * **A text file shows its first lines** (V0652 (ae)): the registry writes them
    into the card (at most 600 characters, cut at a line end), at the upload and
    again when the card is posted, from the stored file, so a preview never says
    something its file does not. A binary, or a file that holds a credential's
    shape, gets no preview, and the card says which.

The bytes live on the durable volume, keyed by SHA-256; the database holds the
metadata. A message references an attachment through a `media` CARD, which is a
pointer exactly like `contract.offer` — the registry never inlines bytes into a
message body.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DATA_ROOT = Path(os.getenv("CHAT_MEDIA_ROOT", "/app/data/chat_attachments"))
MAX_BYTES = int(os.getenv("CHAT_MEDIA_MAX_BYTES", str(5 * 1024 * 1024)))       # 5 MB
DAILY_FILES = int(os.getenv("CHAT_MEDIA_DAILY_FILES", "50"))
DAILY_BYTES = int(os.getenv("CHAT_MEDIA_DAILY_BYTES", str(100 * 1024 * 1024)))  # 100 MB

# An ALLOWLIST. Everything absent from it is refused, including every type
# nobody has thought of yet — which is the point of an allowlist.
ALLOWED_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    # V0650 (i): Markdown is text, held to text/plain's rules (no magic number; refused when it sniffs as an image or a
    # PDF), and like every file served only as a download (octet-stream, attachment, nosniff, sandbox), never rendered.
    "text/markdown": ".md",
    # V0652 (ae): JSON and CSV are text too, on the same rules.
    "application/json": ".json",
    "text/csv": ".csv",
}
TEXT_MIME = frozenset({"text/plain", "text/markdown", "application/json", "text/csv"})
# V0652 (ae): the names browsers give the same text types (a .log file arrives as text/x-log on Linux); stored as
# the canonical type.
MIME_ALIASES = {"text/x-log": "text/plain", "text/x-markdown": "text/markdown"}
# Named refusals for the types people will actually try, so the answer is a
# sentence rather than a shrug.
NAMED_REFUSALS = {
    "image/svg+xml": "SVG can carry script — send a PNG or a JPEG",
    "text/html": "HTML is a program here, not a document",
    "application/x-msdownload": "executables are not accepted",
    "application/x-sh": "shell scripts are not accepted",
    "application/zip": "archives are not accepted — send the file itself",
}

# The magic-number check. A client-declared content type is a claim; the first
# bytes are evidence, and a mismatch is refused rather than trusted.
_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
)


def _sniff(data: bytes) -> Optional[str]:
    for sig, mime in _MAGIC:
        if data.startswith(sig):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def safe_filename(name: str) -> str:
    """A display name, stripped of everything that could be a path or a trick.

    The stored path never uses this — it is the SHA-256 — so this is purely
    what a human sees. Directory separators and control characters go anyway:
    a filename is rendered in a browser, and a rendered filename is an
    injection surface like any other.
    """
    base = re.sub(r"[\\/\x00-\x1f]", "", str(name or "").strip())[-120:]
    base = base.replace("..", "_")
    return base or "file"


def _err(status: int, detail: str):
    from .chat_service import ChatError
    return ChatError(status, detail)


async def _quota_used(db: AsyncSession, uploader_key: str) -> tuple[int, int]:
    row = (await db.execute(sa_text("""
        SELECT count(*), COALESCE(sum(bytes), 0)
        FROM chat_attachments
        WHERE uploader_key = :k AND created_at > now() - interval '24 hours'
    """), {"k": uploader_key})).first()
    return int(row[0] or 0), int(row[1] or 0)


async def store(db: AsyncSession, *, conversation_id: str, uploader_key: str,
                filename: str, declared_mime: str, data: bytes,
                thread_state: str) -> dict:
    """Validate, quota, hash, write, record. Returns the attachment row.

    Order matters: every refusal that can be decided WITHOUT touching the disk
    happens first, so a rejected upload costs a hash at most and never leaves a
    file behind. `thread_state` is the THREAD's ('pending' while it is still a
    request, chat_service.thread_is_request), never only the uploader's row.
    """
    if thread_state != "active":
        # The §6 defanging, applied to files: a stranger cannot put anything on
        # your device before you have accepted the conversation.
        raise _err(409, "this conversation is still a request: files can be sent once it is accepted")

    size = len(data or b"")
    if size == 0:
        raise _err(422, "an empty file is not an attachment")
    if size > MAX_BYTES:
        raise _err(413, f"files are limited to {MAX_BYTES // (1024 * 1024)} MB; "
                        f"this one is {size // 1024} KB")

    declared = (declared_mime or "").split(";")[0].strip().lower()
    declared = MIME_ALIASES.get(declared, declared)
    if declared in NAMED_REFUSALS:
        raise _err(415, NAMED_REFUSALS[declared])
    if declared not in ALLOWED_MIME:
        raise _err(415, f"'{declared or 'unknown'}' is not an accepted file type — "
                        f"accepted: {', '.join(sorted(ALLOWED_MIME))}")

    sniffed = _sniff(data)
    if declared in TEXT_MIME:
        # Text has no magic number; refuse anything that sniffs as something
        # else wearing a .txt (or .md) label.
        if sniffed is not None:
            raise _err(415, f"this file says {declared} but its contents are {sniffed}")
    elif sniffed != declared:
        raise _err(415, f"this file says {declared} but its contents are "
                        f"{sniffed or 'not a recognised image or PDF'}")

    files, byts = await _quota_used(db, uploader_key)
    if files >= DAILY_FILES:
        raise _err(429, f"daily limit of {DAILY_FILES} files reached")
    if byts + size > DAILY_BYTES:
        raise _err(429, f"daily upload limit of {DAILY_BYTES // (1024 * 1024)} MB reached")

    digest = hashlib.sha256(data).hexdigest()
    shown = text_preview(data[:PREVIEW_READ], mime=declared, filename=safe_filename(filename),
                         complete=size <= PREVIEW_READ) or {}

    # Dedup INSIDE the thread: the same file sent twice is one blob, two cards.
    existing = (await db.execute(sa_text("""
        SELECT id, filename, mime, bytes, sha256 FROM chat_attachments
        WHERE conversation_id = :c AND sha256 = :s AND deleted_at IS NULL
    """), {"c": conversation_id, "s": digest})).first()
    if existing is not None:
        return {"attachment_id": existing[0], "filename": existing[1], "mime": existing[2],
                "bytes": int(existing[3]), "sha256": existing[4], "deduplicated": True, **shown}

    ext = ALLOWED_MIME[declared]
    folder = DATA_ROOT / conversation_id
    path = folder / f"{digest}{ext}"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        # Written before the row so a row never points at a missing file. The
        # opposite order leaves a card that renders a download that 404s.
        with open(path, "wb") as fh:
            fh.write(data)
        os.chmod(path, 0o640)
    except OSError as e:
        logger.error("[CHATMEDIA] write failed for %s: %s", path, e)
        raise _err(507, "this registry could not store the file just now")

    att_id = str(uuid.uuid4())
    try:
        await db.execute(sa_text("""
            INSERT INTO chat_attachments
              (id, conversation_id, uploader_key, filename, mime, bytes, sha256, storage_path)
            VALUES (:i, :c, :u, :f, :m, :b, :s, :p)
        """), {"i": att_id, "c": conversation_id, "u": uploader_key,
               "f": safe_filename(filename), "m": declared, "b": size,
               "s": digest, "p": str(path)})
        await db.commit()
    except IntegrityError:
        # Raced with an identical upload into the same thread: the other one
        # won, and the file on disk is byte-identical by construction.
        await db.rollback()
        row = (await db.execute(sa_text(
            "SELECT id, filename, mime, bytes, sha256 FROM chat_attachments "
            "WHERE conversation_id = :c AND sha256 = :s"
        ), {"c": conversation_id, "s": digest})).first()
        if row is None:
            raise _err(500, "the upload raced and could not be recovered")
        return {"attachment_id": row[0], "filename": row[1], "mime": row[2],
                "bytes": int(row[3]), "sha256": row[4], "deduplicated": True, **shown}

    return {"attachment_id": att_id, "filename": safe_filename(filename),
            "mime": declared, "bytes": size, "sha256": digest, "deduplicated": False, **shown}


async def fetch(db: AsyncSession, attachment_id: str) -> Optional[dict]:
    """Metadata + path, or None. The CALLER checks participation — this
    function deliberately does not, so there is exactly one place that decides
    who may read a thread's files (the router, with the participant row in
    hand) rather than two that could disagree."""
    row = (await db.execute(sa_text("""
        SELECT id, conversation_id, filename, mime, bytes, storage_path, deleted_at
        FROM chat_attachments WHERE id = :i
    """), {"i": str(attachment_id)})).first()
    if row is None:
        return None
    return {"id": row[0], "conversation_id": row[1], "filename": row[2],
            "mime": row[3], "bytes": int(row[4]), "path": row[5],
            "deleted_at": row[6].isoformat() if row[6] else None}


async def tombstone(db: AsyncSession, attachment_id: str) -> bool:
    """Mark removed and delete the bytes. The ROW survives so a card can render
    "this file was removed" instead of a download that fails."""
    row = await fetch(db, attachment_id)
    if row is None or row["deleted_at"]:
        return False
    try:
        Path(row["path"]).unlink(missing_ok=True)
    except OSError as e:  # noqa: BLE001
        logger.warning("[CHATMEDIA] could not unlink %s: %s", row["path"], e)
    await db.execute(sa_text(
        "UPDATE chat_attachments SET deleted_at = :t WHERE id = :i"),
        {"t": datetime.datetime.now(datetime.timezone.utc), "i": attachment_id})
    await db.commit()
    return True


def media_card(att: dict) -> dict:
    """The POINTER a message carries. No bytes, no data URI, no preview blob:
    a thread read stays the same size no matter what people send. V0652 (ae):
    a text file's card carries its first lines too, bounded (PREVIEW_CHARS)."""
    return {"v": 1, "type": "media", "data": {
        "attachment_id": att["attachment_id"], "name": att["filename"],
        "mime": att["mime"], "bytes": att["bytes"], "sha256": att["sha256"],
        **{k: att[k] for k in PREVIEW_KEYS if k in att},
    }}


# ── V0652 (ae) (order gwo_5b9de9adb052d681ca95853d): a text file's first lines on its card ─────────────────────────
#
# The maintainer (the sessions' room, seq 265): "can you print like a preview from the context of the file on the
# card? ... otherwise i would always have to download it to see whats in it if its an md or txt file or json". The
# registry writes the preview, never the sender: the upload returns a card that carries it, and the post path
# (chat_service.send_message) writes it again from the stored file, so a card cannot show text its file does not
# hold, and a card that points at a file outside its thread shows none.

PREVIEW_CHARS = 600                 # the most a preview shows
PREVIEW_LINES = 16                  # and at most this many lines of it
PREVIEW_READ = 256 * 1024           # what the preview reads of a file (and screens for a credential's shape)
PREVIEW_KINDS = ("markdown", "json", "csv", "log", "text")
PREVIEW_WITHHELD = ("binary", "credential")
PREVIEW_KEYS = ("preview", "preview_kind", "preview_truncated", "preview_withheld")

_KIND_BY_EXT = {".md": "markdown", ".markdown": "markdown", ".json": "json", ".csv": "csv", ".log": "log"}
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")        # a terminal's colour codes, in logs
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")
# a secret-named assignment, as an env file or a YAML file writes one (KEY=value, key: value), its value one word to
# the line's end (so a sentence such as "Password: rotated on Friday" is prose, not a credential)
_ENV_SECRET = re.compile(
    r"(?im)^[ \t]*(?:export[ \t]+)?[a-z0-9_.-]*(?:secret|password|passwd|token|api[_-]?key|private[_-]?key|credential)"
    r"[a-z0-9_.-]*[ \t]*[=:][ \t]*['\"]?[^\s'\"]{6,}['\"]?,?[ \t]*$")


def preview_kind(mime: str, filename: str) -> str:
    """How a text file is shown: markdown rendered, the others in monospace (JSON pretty-printed)."""
    if mime == "text/markdown":
        return "markdown"
    if mime == "application/json":
        return "json"
    if mime == "text/csv":
        return "csv"
    name = (filename or "").lower()
    if name.endswith(".txt"):           # chat_link sends a .md or .json to a registry that refuses it as FILE.md.txt
        name = name[:-4]
    return next((k for ext, k in _KIND_BY_EXT.items() if name.endswith(ext)), "text")


def _decode(head: bytes, complete: bool) -> Optional[str]:
    """The text of a read window, or None when it is not UTF-8. A window that ends inside a character loses only that
    character's bytes; an undecodable byte anywhere else is a binary."""
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    try:
        return head.decode("utf-8")
    except UnicodeDecodeError as e:
        if complete or e.reason != "unexpected end of data" or e.end != len(head) or e.start < len(head) - 3:
            return None
        try:
            return head[:e.start].decode("utf-8")
        except UnicodeDecodeError:
            return None


def _holds_a_credential(text: str) -> bool:
    from ..mcp.audit_sanitizer import _SECRET_KV, _SECRET_SHAPES     # the product's own shapes, one definition
    return (any(rx.search(text) for rx in _SECRET_SHAPES) or bool(_SECRET_KV.search(text))
            or bool(_ENV_SECRET.search(text)))


def _cut(text: str) -> tuple[str, bool]:
    """At most PREVIEW_CHARS characters and PREVIEW_LINES lines, cut at a line end; a first line longer than that is
    cut at a word, else at a character, never between a character and its combining mark."""
    text = text.lstrip("\n")
    lines = text.split("\n")
    kept, used = [], 0
    for line in lines:
        add = len(line) + (1 if kept else 0)
        if len(kept) >= PREVIEW_LINES or used + add > PREVIEW_CHARS:
            break
        kept.append(line)
        used += add
    else:
        return text.rstrip(), False
    if kept and "\n".join(kept).strip():
        return "\n".join(kept).rstrip(), True
    first = text[:PREVIEW_CHARS + 1]
    k = PREVIEW_CHARS
    space = first.rfind(" ", 0, k + 1)
    if space >= PREVIEW_CHARS // 2:
        k = space
    while 0 < k < len(first) and (unicodedata.combining(first[k]) or first[k] in "\u200d\ufe0e\ufe0f"
                                  or first[k - 1] == "\u200d"):
        k -= 1
    return first[:k].rstrip(), True


def text_preview(head: bytes, *, mime: str, filename: str, complete: bool) -> Optional[dict]:
    """The preview fields a text file's card carries, or None for a file that shows none (not text, or blank).

    `head` is the file's first PREVIEW_READ bytes (or all of it: `complete`). A binary or a file shaped like a
    credential gets `preview_withheld` instead, so the card can say why it shows nothing.
    """
    if mime not in TEXT_MIME:
        return None
    text = _decode(head or b"", complete)
    if text is None or "\x00" in text:
        return {"preview_withheld": "binary"}
    text = _ANSI.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    if len(_CONTROL.findall(text[:8192])) > max(8, len(text[:8192]) // 50):
        return {"preview_withheld": "binary"}
    text = _CONTROL.sub("", text)
    if _holds_a_credential(text):
        return {"preview_withheld": "credential"}
    kind = preview_kind(mime, filename)
    if kind == "json" and complete:
        try:
            text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except (ValueError, RecursionError):
            pass                        # not JSON after all: shown as it is
    shown, cut = _cut(text)
    if not shown.strip():
        return None
    return {"preview": shown, "preview_kind": kind, "preview_truncated": bool(cut or not complete)}


def without_preview(card: dict) -> dict:
    """A media card with no preview fields (a new card; the one given is unchanged)."""
    return {**card, "data": {k: v for k, v in (card.get("data") or {}).items() if k not in PREVIEW_KEYS}}


def _read_head(path: str) -> tuple[bytes, bool]:
    with open(path, "rb") as fh:
        head = fh.read(PREVIEW_READ + 1)
    return head[:PREVIEW_READ], len(head) <= PREVIEW_READ


async def ground_card(db: AsyncSession, conversation_id: str, card: dict) -> dict:
    """A media card as it is posted: its preview fields written from the stored file, whatever the sender's card said.
    A card whose attachment is not this thread's (or is gone) carries no preview. Returns a new card."""
    out = without_preview(card)
    data = out["data"]
    att_id = str(data.get("attachment_id") or "")
    if not att_id or len(att_id) > 64:
        return out
    try:
        att = await fetch(db, att_id)
    except Exception as e:  # noqa: BLE001 - a preview is an extra; the message still posts without it
        logger.warning("[CHATMEDIA] preview: attachment read failed: %s", e)
        return out
    if att is None or str(att["conversation_id"]) != str(conversation_id) or att["deleted_at"]:
        return out
    if att["mime"] not in TEXT_MIME:
        return out
    try:
        head, complete = _read_head(att["path"])
    except OSError as e:
        logger.warning("[CHATMEDIA] preview: %s unreadable: %s", att["path"], e)
        return out
    data.update(text_preview(head, mime=att["mime"], filename=att["filename"], complete=complete) or {})
    return out
