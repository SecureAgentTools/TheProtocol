"""§SOVKIT S5 (2026-09-14) — a standup that names no --directory-upstream reads the frame's OWN Directory leg.

Measured on orchard (the first frame stood up with the kit): the driver's "one flag writes all three or none" rule
(§FRAMELIC) blanked the template's DIRECTORY_MTLS_URL / DIRECTORY_PUBLIC_URL / DISCOVERY_VIA_DIRECTORY because the runner
passes no flag, so the registry proxy answered `configured: false` beside a healthy in-frame index. The default is now the
frame's own mTLS leg; a caller that names another index keeps it; the https-only refusal still applies to both.
"""
from __future__ import annotations

import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import standup_driver as drv  # noqa: E402


def test_no_flag_means_the_frames_own_leg():
    args = types.SimpleNamespace(name="orchard", directory_upstream="")
    assert drv.kit_directory_default(args) == "https://orchard-directory-nginx:8443"
    assert args.directory_upstream == "https://orchard-directory-nginx:8443"


def test_a_named_index_is_kept():
    args = types.SimpleNamespace(name="orchard", directory_upstream="https://directory-nginx:8443")
    assert drv.kit_directory_default(args) == "https://directory-nginx:8443"


def test_the_env_mutation_writes_all_three_from_that_one_value():
    src = pathlib.Path(drv.__file__).read_text()
    assert '("FT_REG_DIRECTORY_MTLS_URL", args.directory_upstream or "")' in src
    assert '("FT_REG_DIRECTORY_PUBLIC_URL", "/api/v1/public/directory" if args.directory_upstream else "")' in src
    assert '("FT_REG_DISCOVERY_VIA_DIRECTORY", "true" if args.directory_upstream else "false")' in src
    assert "kit_directory_default(args)" in src.split("def main():", 1)[1], "main() no longer applies the default"
