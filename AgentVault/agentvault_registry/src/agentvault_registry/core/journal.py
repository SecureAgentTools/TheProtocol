"""§HELLOFRAME (his word 2026-09-19, "Ship without it"): does THIS frame carry the journal?

The journal is theprotocol.cloud's own writing: 46 posts whose text is built into the console and whose figures and
videos (276 MB) sit in the built console's `blog/` directory. A frame stood up from the export is a stranger's frame
under their own domain, and the export leaves those media out, so its console must not offer a journal it cannot show.

The answer is DERIVED from the thing the journal needs: on where the served console carries its media, off where it
does not. Our own frames carry the media and change nothing. The only override is OFF (`JOURNAL_ENABLED=false`, for a
frame that carries the media and does not want the journal): an override to ON would claim a capability its
precondition cannot supply, 46 posts of broken images, so none exists.
"""
import os
from pathlib import Path
from typing import Mapping, Optional

_OFF = ("0", "false", "no", "off")


def journal_media_present(dist_dir: Path) -> bool:
    """True iff the served console's `blog/` directory exists and holds at least one entry."""
    d = Path(dist_dir) / "blog"
    try:
        return d.is_dir() and any(d.iterdir())
    except OSError:
        return False


def journal_enabled(dist_dir: Path, env: Optional[Mapping[str, str]] = None) -> bool:
    """Off when `JOURNAL_ENABLED` says off; otherwise on exactly where the journal's media are served."""
    raw = ((env if env is not None else os.environ).get("JOURNAL_ENABLED") or "").strip().lower()
    if raw in _OFF:
        return False
    return journal_media_present(dist_dir)
