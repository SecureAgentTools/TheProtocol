"""The first-boot banner, read where a provisioner needs the password it names (V0654 recut, agentvault2-14).

operator_seed (V0654 (aq), CodeQL #381) and prod_seed (V0653 (am) item 4) write a generated first admin password to a
0600 file inside the registry's container and print a banner that names the FILE, never the password. An image older
than V0654 (operator_seed) printed the password itself. The provisioners read that banner from the container's log and
must answer both forms: the older pattern also matches the newer line and took the word "in" for the password, which
handed every operator provisioned on V0654 a wrong first login (V0654's first pair proof, 2026-11-02 22:21Z).

    banner(log_text)            -> ("file", path) | ("printed", password) | None
    from_sdk_container(c, tail) -> (password, how): a docker SDK container; the file is read, then removed
Nothing here prints or logs a password; `how` never carries one.
"""
from __future__ import annotations

import re
from typing import Any, Optional, Tuple

_IN_FILE = re.compile(r"FIRST-BOOT ADMIN PASSWORD: in (/\S+) \(mode 600\)")
_PRINTED = re.compile(r"FIRST-BOOT ADMIN PASSWORD:\s*(\S+)")


def banner(log_text: str) -> Optional[Tuple[str, str]]:
    """What a registry's log says about its first-boot password: ("file", path) when the banner names the 0600 file
    it is in, ("printed", password) when an older image printed it, None when there is no banner. The file form is
    asked first: the older pattern matches it too."""
    text = log_text or ""
    m = _IN_FILE.search(text)
    if m:
        return "file", m.group(1)
    m = _PRINTED.search(text)
    if m:
        return "printed", m.group(1)
    return None


def from_sdk_container(container: Any, tail: int = 5000) -> Tuple[str, str]:
    """(password, how) for a docker SDK container: the file its banner names, read and then removed (the provisioner
    hands the password to the operator's owner once; it does not stay at rest in the container), or the password an
    older image printed. ("", why) when neither can be had."""
    logs = container.logs(tail=tail).decode(errors="replace")
    found = banner(logs)
    if found is None:
        return "", "no first-boot banner in the log"
    kind, value = found
    if kind == "printed":
        return value, "printed in the log (an image older than V0654)"
    code, out = container.exec_run(["cat", value])
    password = (out or b"").decode(errors="replace").strip()
    if code != 0 or not password:
        return "", f"the log names {value}, which could not be read in the container"
    code_rm, _ = container.exec_run(["rm", "-f", value])
    return password, "read from its 0600 file in the container" + (
        "; the file removed" if code_rm == 0 else "; the file could NOT be removed: remove it by hand")
