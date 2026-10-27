"""§OURSTATE-5e — media, treated as what it actually is.

Accepting uploads turns a chat into a file host attached to a money network,
which is a magnet for people who want free storage, a malware drop, or a way to
put an executable in front of someone mid-negotiation. So this module is mostly
refusals, and each one is deliberate:

  * **A closed type allowlist, not a blocklist.** Images, PDF, and plain text.
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

The bytes live on the durable volume, keyed by SHA-256; the database holds the
metadata. A message references an attachment through a `media` CARD, which is a
pointer exactly like `contract.offer` — the registry never inlines bytes into a
message body.
"""
from __future__ import annotations

import datetime
import hashlib
import logging
import os
import re
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
}
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
    if declared in NAMED_REFUSALS:
        raise _err(415, NAMED_REFUSALS[declared])
    if declared not in ALLOWED_MIME:
        raise _err(415, f"'{declared or 'unknown'}' is not an accepted file type — "
                        f"accepted: {', '.join(sorted(ALLOWED_MIME))}")

    sniffed = _sniff(data)
    if declared == "text/plain":
        # Text has no magic number; refuse anything that sniffs as something
        # else wearing a .txt label.
        if sniffed is not None:
            raise _err(415, f"this file says text/plain but its contents are {sniffed}")
    elif sniffed != declared:
        raise _err(415, f"this file says {declared} but its contents are "
                        f"{sniffed or 'not a recognised image or PDF'}")

    files, byts = await _quota_used(db, uploader_key)
    if files >= DAILY_FILES:
        raise _err(429, f"daily limit of {DAILY_FILES} files reached")
    if byts + size > DAILY_BYTES:
        raise _err(429, f"daily upload limit of {DAILY_BYTES // (1024 * 1024)} MB reached")

    digest = hashlib.sha256(data).hexdigest()

    # Dedup INSIDE the thread: the same file sent twice is one blob, two cards.
    existing = (await db.execute(sa_text("""
        SELECT id, filename, mime, bytes, sha256 FROM chat_attachments
        WHERE conversation_id = :c AND sha256 = :s AND deleted_at IS NULL
    """), {"c": conversation_id, "s": digest})).first()
    if existing is not None:
        return {"attachment_id": existing[0], "filename": existing[1], "mime": existing[2],
                "bytes": int(existing[3]), "sha256": existing[4], "deduplicated": True}

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
                "bytes": int(row[3]), "sha256": row[4], "deduplicated": True}

    return {"attachment_id": att_id, "filename": safe_filename(filename),
            "mime": declared, "bytes": size, "sha256": digest, "deduplicated": False}


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
    a thread read stays the same size no matter what people send."""
    return {"v": 1, "type": "media", "data": {
        "attachment_id": att["attachment_id"], "name": att["filename"],
        "mime": att["mime"], "bytes": att["bytes"], "sha256": att["sha256"],
    }}
