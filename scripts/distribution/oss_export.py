#!/usr/bin/env python3
"""§OSSDRY (2026-09-13) + §OSSRC (2026-09-14): the fresh-history export.

The pushed history of this tree carries key and credential files, so the OSS cut is a FRESH-HISTORY EXPORT
(memory `project_oss_launch_roadmap_2026-07-02`, still the plan of record): a curated file set copied into a
NEW `git init`, gated for secret absence, pushed to a PRIVATE repo. Nothing here publishes anything.

    python3 scripts/distribution/oss_export.py --out /root/oss-export-dryrun/<ts> --stack-ref <ref> [--av-ref <sha>]
                                               [--push theprotocol/oss-export-dryrun] [--selftest] [--from-tree]
                                               [--author "Name <address>"] [--signoff] [--message "..."]

The three commit flags (2026-09-26, for the day the code base opens) only change the fresh-history commit: who it is by
(author and committer), a Signed-off-by line for that identity, and its message. The tree is the same with or without
them. Without them the commit is the one this script always wrote, byte for byte, which is what publish.py checks: an
export with another message is not a publishable kit (its commit no longer says it was gated).

§OSSRC: the export is taken from COMMITS. The stack paths come from `git archive <stack-ref>`, the AgentVault
paths from `git -C AgentVault archive <av-ref>`, and av-ref defaults to the AgentVault commit the stack commit
PINS (its gitlink), so one stack commit names the whole release. An uncommitted edit or an untracked file cannot
ride in (the 09-13 export walked the working tree, and another session's untracked mail templates would have
shipped). The one exception is the short list of gitignored artifacts an image needs and no commit holds (the 13
compiled circuit artifacts, the 5 runtime files): they are carried from the working tree only where the commit
has no copy, their digest is logged, and G5 counts them. `--from-tree` keeps the 09-13 behaviour, for comparison.

What ships (the release set of the roadmap, re-read 2026-09-13):
  AgentVault/{agentvault_registry, agentvault_teg_layer_mvp, agentvault_library, agentvault_circuit_registry (source AND the
  compiled artifacts under target/, count-gated: a clean checkout carries none, §ZKPACIR), agentvault_server_sdk, agentvault_cli,
  .forgejo, .dockerignore (the build context's own ignore file, §OSSRC)}
  agentvault-event-store · identity-fabric (re-audited: no private keys) · directory · theprotocol-sdk · PUBLIC_DOCS ·
  scripts/distribution · scripts/hetzner_demo + templates/frame-test + sidecars (the one-command frame standup) ·
  the root legal set (README, LICENSE, LICENSING, CONTRIBUTING, DCO, CLA (superseded, kept with its banner), SECURITY,
  CODE_OF_CONDUCT, .env.example) · .github (§EXPORTIP 2026-09-29: the public repository's issue and pull-request
  templates and its secret-free CI; the parked .github/workflows-oss-launch draft does not ship)
What never ships: PRODUCTION_DOCS, CLAUDE.md, sessionlogs2026, scratchpad, monitoring, Agents, docker-certs, every .env
that is not an example, every *.bak* and *.prev-*, node_modules, dist, __pycache__, the FE's built assets (built from
source), and the journal's media (the console's public/blog: our own posts' figures and videos).

Gates over the export tree (every one has a CONTROL that must fire on a planted specimen, or it is decoration):
  G1 the literal denylist (TP_SECRET_DENYLIST, out of repo) — none may appear in any file
  G2 secret SHAPES: a PEM private key body, an `avreg_` API key, a `dpt_` pull token, a `tp_fed_` licence key
  G3 known key FILE paths: *.key, *-key.pem, token-signing.key, mcp-registry-key.pem, dummy_upstream_ca.key, docker-certs/
  G4 a long hex literal ASSIGNED to a secret-named variable or key (INTERNAL_API_KEY=<64 hex>, "api_key": "<hex>")
  G5 the export must carry >= 13 circuit artifacts and the 5 gitignored runtime files the registry image needs
  G6 every file the export holds is in its commit: a shipped .gitignore may hide a carried artifact (force-added by
     name) and nothing else (§OSSRC: agentvault_registry/.gitignore kept the 5 runtime files out of every clone)
  G7 every file that starts with #! is committed executable (100755): both source repos were committed under
     core.fileMode=false, which never records the bit, so a clean clone could run none of their scripts
  G8 (§HELLOFRAME 2026-09-18) the LIVE census: every secret-named env value of every RUNNING container on the build
     host, and every password component of every DSN/URL in any env value, must be absent from the tree. Read from
     `docker inspect` in-process, compared in-process, never written or printed (a denylist that hardcodes a live
     secret is the leak; G1's file holds what a pre-commit must refuse, this holds what is live right now). A host
     where docker cannot be asked refuses the export: NOT MEASURED is not passed.
  G10 (§HELLOFRAME 2026-09-19, his word "Ship without it") the journal's media: nothing under the console's
     public/blog ships. The same predicate as the copy (JOURNAL_MEDIA); a frame without the media offers no journal
     (AgentVault core/journal.py), so a stranger's console never shows our posts or their broken images.
  G13 (§EXPORTIP 2026-09-29) a public IPv4 address: none may stand except the public resolvers and the documentation
     examples, a lock file's version strings, and what the maintainer's allowlist (TP_EXPORT_IP_ALLOW, out of repo)
     binds to one path. It ran by hand before; on 2026-09-27 it caught this host's address in a test fixture.
  G14 (§DOCSOURCE 2026-10-16) PUBLIC_DOCS at the exported stack commit equals its generation from the one doc source
     (the console's doc folder at the AgentVault commit the stack pins; scripts/distribution/gen_public_docs.py):
     a hand edit, a page the source dropped or a stale copy refuses, and a check that cannot run is NOT MEASURED.
The export mode has its own control in --selftest: an untracked file and an uncommitted edit must stay out.
"""
from __future__ import annotations
import argparse, fnmatch, hashlib, ipaddress, os, re, shutil, subprocess, sys, tarfile, time, json
from pathlib import Path

ROOT = Path("/opt/theprotocol/stack/Agentvault2")
AV = ROOT / "AgentVault"
DENYLIST = Path(os.getenv("TP_SECRET_DENYLIST", "/root/.tp_secret_denylist.txt"))

AV_SHIP = [  # relative to the AgentVault repository
    "agentvault_registry", "agentvault_teg_layer_mvp", "agentvault_library", "agentvault_circuit_registry",
    "agentvault_server_sdk", "agentvault_cli", ".forgejo", "pyproject.toml", "README.md", "LICENSE",
    # §OSSRC: without the context's own ignore file the registry image built from the 09-13 export carried
    # node_modules (640 MB) and e2e screenshots
    ".dockerignore",
    # §LEGALKIT 2026-09-21: the repository's own CONTRIBUTING (a pointer to the root guide), SECURITY and CLA (both
    # byte-identical with the root copies); its README names them, so an export without them pointed at nothing
    "CONTRIBUTING.md", "SECURITY.md", "CLA.md",
]
STACK_SHIP = [  # relative to the stack repository
    "agentvault-event-store", "identity-fabric", "directory", "theprotocol-sdk", "PUBLIC_DOCS",
    "scripts/distribution", "scripts/hetzner_demo", "templates/frame-test", "sidecars",
    # §SOVKIT (his word 2026-09-14: "do opa auditor directory and cli runner for the export"): the `tp` host CLI, the
    # frame runner (the host service Frame Management provisions through) and the solo auditor the frame kit ships;
    # OPA's policies ride in identity-fabric/, the Directory in directory/, the kit's files in templates/frame-test/kit.
    "tools/operator-cli", "tools/frame-runner", "Agents/TheAuditor",
    # §DEPS (2026-09-30): the auditor installs its pins from a second build context (`COPY --from=constraints py314.txt`),
    # so the kit carries that file and build.sh passes it; without it the kit build stops at the auditor
    "Agents/_constraints",
    # §HELLOFRAME: the cert-writer image (six sidecars of a federated frame run it) and the nginx entrypoint every mTLS
    # terminator mounts; the rest of nginx/ is this host's vhosts and never ships
    "nginx/Dockerfile.cert-writer", "nginx/cert-writer.sh", "nginx/nginx-entrypoint.sh",
    # §AGORASIM-2 (his words 2026-09-22: "update the sim so anyone can easily onboard it when standing up the export
    # framekit"): the market simulation engine scripts/distribution/frame-sim.py drives (every knob derived from the
    # frame's own answers; the production tables inside it are never used when frame-sim names the network)
    "scripts/sim_eigentrust.py",
    # §OSSRC: DCO.md is the contribution terms CONTRIBUTING.md links to; the 09-13 set shipped CLA.md without it
    "README.md", "LICENSE", "LICENSING.md", "CONTRIBUTING.md", "DCO.md", "CLA.md", "SECURITY.md", "CODE_OF_CONDUCT.md",
    # §REVIEWLANE (2026-09-26): the maintainer's half of CONTRIBUTING (how a change is reviewed, by whom, how long)
    "REVIEWING.md",
    ".env.example",
    # §EXPORTIP (2026-09-29, the 09-27 GitHub handover section 5): the public repository's issue forms, its pull-request
    # template (the DCO sign-off and the CLA line) and its CI (the maintainer's secret-free gates on this tree's layout).
    # Named one by one: .github/workflows-oss-launch is a parked draft and stays home.
    ".github/ISSUE_TEMPLATE", ".github/PULL_REQUEST_TEMPLATE.md", ".github/workflows",
    # §LICENSING (2026-09-30, REVIEW_2026-09-30_LICENSING.md): the attribution file, the licence map in the form scanners
    # read and the texts it names; scripts/distribution/reuse_lint.sh checks the export against them
    "NOTICE", "REUSE.toml", "LICENSES",
]
SHIP = [f"AgentVault/{p}" for p in AV_SHIP] + STACK_SHIP
# §HELLOFRAME (his word 2026-09-19 on the export's journal: "Ship without it"): the journal's media, 276 MB of our own
# posts' figures and videos, stay home. The console offers no journal where they are absent (AgentVault
# core/journal.py). One predicate for the copy (NEVER) and for G10, so the gate asks the question the copy answered.
JOURNAL_MEDIA = ["**/new_registry_frontend/public/blog", "**/new_registry_frontend/public/blog/**"]
# path patterns never copied (matched against the path relative to the source root, with fnmatch on every prefix)
NEVER = [
    *JOURNAL_MEDIA,
    # a dated backup beside the file it replaced (the console's public/ carried three og-image *.prev-2026-04-23)
    "**/*.prev-*",
    "**/node_modules", "**/node_modules/**", "**/__pycache__", "**/__pycache__/**", "**/.pytest_cache/**", "**/htmlcov/**",
    "**/*.bak*", "**/*.orig", "**/*~", "**/.git", "**/.git/**", "**/dist/**", "**/*.egg-info/**", "**/.venv/**", "**/build/**",
    "**/docker-certs/**", "**/*.key", "**/*-key.pem", "**/token-signing.key", "**/mcp-registry-key.pem", "**/dummy_upstream_ca.key",
    "**/.env", "**/.env.*", "**/*.secret", "**/*.secret.*", "**/sessionlogs*/**", "**/scratchpad/**", "**/hetznerlogs/**",
    "**/FORENSIC/**", "**/docs_compiled_txt/**", "**/backups/**", "**/*.tar.gz", "**/*.pem.bak*",
    "sidecars/sidecars.json", "**/frames/frames.json", "**/wt/**", "**/wt2/**", "**/*.log",
    # §SOVKIT: the auditor's TRACKED sandbox database and any other sqlite file; a retired frontend copy; PyInstaller output
    "**/data-sandbox/**", "**/*.db", "**/frontend.bak-*/**", "**/*.egg-info", "**/.pytest_cache",
    # §HELLOFRAME: the FE root's private drivers (blog screenshots, a gate, a prod diagnostic) log in as our admin against
    # our nodes; they are this host's tooling, not the product (they carried the retired Commander password until 09-18)
    "**/new_registry_frontend/shot_*.mjs", "**/new_registry_frontend/diag_prod.mjs",
    # §FEFRAME W0 (2026-09-30): EVERY root gate, not one by name: gate_gc3.mjs carried the retired Commander password in an
    # obfuscated form ('…'.replace()) and shipped because only gate_gc2 was listed; plus the deep-link probe in src/,
    # which reads a secret file of this host.
    "**/new_registry_frontend/gate_*.mjs", "**/new_registry_frontend/src/probe_deeplink.mjs",
    # §FRESHREADER (2026-09-21), planned at §BATCH3 item 1 (Private_Surface_Excision.md) and never wired: the only file that
    # names this network's dial topology (the host's IP twelve times) and the test that reads it stay private. The public
    # canary runner then finds no map and uses its documented bearer fallback.
    "**/agentvault_registry/config/canary_mtls_map.mainnet-2026.json", "**/agentvault_registry/tests/test_canary_mtls_map.py",
]
# §HELLOFRAME (his word 2026-09-19: "we dont ship screenshots"): captures of our own consoles are exports of our data.
# The 09-18 export carried 83 e2e screenshots of admin pages (one showed the Commander's audit log), a Playwright report
# and five loose captures at the frontend's root. A path is a screenshot when any directory on it is a capture folder, or
# when it is an image at the frontend's root or named for what it is; the app's own images live under public/ and
# src/assets/ and never match. One predicate for the copy and for G9, so the gate asks the question the copy answered.
SCREENSHOT_DIRS = frozenset({"e2e-screenshots", "playwright-report", "test-results", "TempScreenshots", "screenshots"})
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
FRONTEND_ROOT = "static/new_registry_frontend"


def is_screenshot(rel: str) -> bool:
    parts = rel.split("/")
    if any(p in SCREENSHOT_DIRS for p in parts):
        return True
    name = parts[-1].lower()
    if not name.endswith(IMAGE_SUFFIXES):
        return False
    return "/".join(parts[:-1]).endswith(FRONTEND_ROOT) or "screenshot" in name


ALLOW_EVEN_IF_NEVER = [".env.example", "**/env.directory.example", "**/env.directory.sandbox.example", "**/sidecars.json.example", "**/*.env.tmpl", "**/*.example"]
RUNTIME_FILES = ["AgentVault/agentvault_registry/config/postgresql/init-users.sql", "AgentVault/agentvault_registry/downloads/README.md",
                 "AgentVault/agentvault_registry/downloads/mcp-stdio-bridge-admin.js", "AgentVault/agentvault_registry/downloads/mcp-stdio-bridge.js",
                 "AgentVault/agentvault_registry/downloads/operator-CLAUDE.md"]

SHAPES = {
    # a PEM header followed by a base64 BODY: a docstring that quotes the header line alone is not a key
    "pem_private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----\s*\n[A-Za-z0-9+/=\r\n ]{40,}"),
    "avreg_api_key": re.compile(rb"\bavreg_[A-Za-z0-9_-]{24,}"),
    "dpt_pull_token": re.compile(rb"\bdpt_[0-9a-f]{40,}"),
    "tp_fed_licence": re.compile(rb"\btp_fed_[0-9a-f]{40,}"),
    # a long hex literal assigned to a secret-named variable or key. No prefix of any real key lives here:
    # a denylist that hardcodes the secret IS the leak; the live values are G1's, read from outside the repo.
    "hex_secret_assignment": re.compile(rb"(?i)\b[A-Z_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|INTERNAL_KEY)[A-Z_]*\b[\"']?\s*[:=]\s*[\"']?[0-9a-f]{40,}\b"),
}
TEXT_MAX = 8 * 1024 * 1024
# G8: which env variable NAMES carry an opaque secret (their whole value is a literal to refuse), and the password
# component of any DSN or URL (`scheme://user:PASSWORD@host`), taken from EVERY value, secret-named or not
SECRET_VAR = re.compile(r"(?i)(API_KEY|SECRET|TOKEN|PASSWORD|PASSPHRASE|_KEY$|_KEY_|^KEY_|PASS_|_PASS$|CREDENTIAL|LICENSE_KEY|LICENCE_KEY|SIGNING_KEY|PRIVATE_KEY)")
URL_PASSWORD = re.compile(r'://[^:/@\s]*:([^@\s"]{12,})@')
LIVE_MIN = 16
# a variable whose NAME says its value is an address, a label or a knob, whatever else the name carries
NOT_SECRET_VAR = re.compile(r"(?i)_(SERVICE|ISSUER|URL|URI|HOST|PATH|FILE|DIR|NAME|ID|MODE|ENABLED|AUDIENCE|ALGORITHM|REALM|HEADER|TYPE|PREFIX|TTL|MINUTES|SECONDS|DAYS|HOURS|COUNT|LIMIT|LENGTH|VERSION)$|EXPIR")
_HOSTNAME = re.compile(r"(?i)^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_WORDS = re.compile(r"^[A-Za-z][A-Za-z _-]*$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
# the product's own rule (teg_core_service/core/internal_auth.py::looks_like_placeholder, §MONEY-M3a): a value that
# carries one of these words is a marker, never a credential; the retirement marker config.py ships by design sits
# in the retiring nodes' env and is refused by admin_key_ok(), so G8 must read it the same way
PLACEHOLDER_WORDS = ('change', 'default', 'deprecated', 'retired', 'placeholder', 'example', 'sample', 'dummy', 'changeme')


def secret_like(v: str) -> bool:
    """what G8 refuses as a whole value: long, opaque, and not an address, a label, a path, a URL, a flag or a number"""
    if len(v) < LIVE_MIN or any(c.isspace() for c in v) or v.startswith("/") or "://" in v:
        return False
    if v.lower() in ("true", "false") or v.replace(".", "").isdigit():
        return False
    if _HOSTNAME.match(v) or _WORDS.match(v) or _EMAIL.match(v):
        return False
    low = v.lower()
    if any(w in low for w in PLACEHOLDER_WORDS):
        return False
    return True


def live_env_values(log) -> "list[tuple[str, str, bytes]] | None":
    """G8's population: (container, VAR, value) for every running container, read in ONE docker inspect. Returns None
    when docker cannot be asked (the caller refuses: NOT MEASURED is not passed). Nothing here is printed or stored."""
    try:
        ids = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True, timeout=60).stdout.split()
        if not ids:
            return []
        out = subprocess.run(["docker", "inspect", "--format", "{{.Name}}\t{{json .Config.Env}}", *ids],
                             capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    return live_values_from_inspect(out.stdout)


def live_values_from_inspect(text: str) -> list:
    vals = []
    for line in text.splitlines():
        name, _, env_json = line.partition("\t")
        name = name.lstrip("/")
        try:
            env = json.loads(env_json) or []
        except ValueError:
            continue
        for kv in env:
            k, _, v = kv.partition("=")
            if SECRET_VAR.search(k) and not NOT_SECRET_VAR.search(k) and secret_like(v):
                vals.append((name, k, v.encode()))
            for m in URL_PASSWORD.finditer(v):
                vals.append((name, k, m.group(1).encode()))
    return vals


def live_regex(live):
    """one alternation over the distinct live values (longest first), and the owner of each: names only"""
    by = {}
    for name, k, v in live or []:
        by.setdefault(v, f"{name}:{k}")
    if not by:
        return None, by
    alts = sorted(by, key=len, reverse=True)
    return re.compile(b"|".join(re.escape(v) for v in alts)), by


def matches(rel: str, patterns) -> bool:
    parts = rel.split("/")
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat):
            return True
        for i in range(1, len(parts) + 1):
            if fnmatch.fnmatch("/".join(parts[:i]), pat):
                return True
    return False


# ── §OSSRC: the source of the export is a pair of commits ──────────────────────────────────────────────────────────────

def _git(args, cwd) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def resolve_refs(stack_ref: str, av_ref: str, root: Path = ROOT):
    """The stack commit, and the AgentVault commit: the one given, else the gitlink the stack commit pins."""
    stack_sha = _git(["rev-parse", "--verify", f"{stack_ref}^{{commit}}"], root)
    if av_ref:
        return stack_sha, _git(["rev-parse", "--verify", f"{av_ref}^{{commit}}"], root / "AgentVault"), False
    entry = _git(["ls-tree", stack_sha, "AgentVault"], root).split()
    if len(entry) < 3 or entry[1] != "commit":  # "<mode> commit <sha>\tAgentVault"
        raise SystemExit(f"[export] REFUSED: stack commit {stack_sha[:12]} pins no AgentVault commit ({entry})")
    try:
        _git(["cat-file", "-e", f"{entry[2]}^{{commit}}"], root / "AgentVault")
    except subprocess.CalledProcessError:
        raise SystemExit(f"[export] REFUSED: the pinned AgentVault commit {entry[2][:12]} is not in the local repository")
    return stack_sha, entry[2], True


def archive_into(repo: Path, commit: str, paths, dest: Path, prefix: str = "") -> None:
    """`git archive <commit> -- <paths>` extracted under dest/prefix: only committed content can arrive.
    A path the commit does not hold makes git archive fail, and the export refuses rather than ship less."""
    target = dest / prefix if prefix else dest
    target.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(["git", "archive", "--format=tar", commit, "--", *paths], cwd=repo,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    unreadable = None
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tf:
            tf.extractall(target, filter="data")
    except tarfile.ReadError as e:  # an empty stream: git archive failed before writing; its status decides below
        unreadable = e
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        raise SystemExit(f"[export] REFUSED: git archive failed in {repo} at {commit[:12]}: {err.strip()[-300:]}")
    if unreadable is not None:
        raise SystemExit(f"[export] REFUSED: git archive in {repo} at {commit[:12]} produced no readable archive: {unreadable}")


def carry_ignored(stage: Path, log, root: Path = ROOT) -> list:
    """The gitignored artifacts an image needs and no commit holds, from the working tree, only where the commit
    has no copy. Logged with a digest; G5 counts them in the export."""
    cands = list(RUNTIME_FILES)
    circuits = root / "AgentVault" / "agentvault_circuit_registry"
    if circuits.is_dir():
        cands += sorted(str(p.relative_to(root)) for p in circuits.rglob("*")
                        if p.is_file() and "target" in p.relative_to(root).parts and ".bak" not in p.name)
    carried, digest, scripts = [], hashlib.sha256(), 0
    for rel in cands:
        src, dst = root / rel, stage / rel
        if dst.exists() or not src.is_file():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        body = src.read_bytes()
        # G7: no commit holds these, so the export decides their mode: a #! file is executable, like every tracked script
        if body[:2] == b"#!":
            os.chmod(dst, 0o755); scripts += 1
        digest.update(rel.encode() + b"\0" + body)
        carried.append(rel)
    log(f"[carry] {len(carried)} gitignored artifact(s) carried from the working tree (sha256 {digest.hexdigest()[:16]}), {scripts} #! script(s) among them marked executable (G7)")
    return carried


def copy_tree(out: Path, log, src_root: Path = ROOT) -> dict:
    n_files, n_skipped, n_never, n_shots = 0, 0, 0, 0
    for item in SHIP:
        src = src_root / item
        if not src.exists():
            log(f"  !! not in the source, skipped: {item}"); n_skipped += 1; continue
        if src.is_file():
            (out / item).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, out / item); n_files += 1; continue
        for dirpath, dirnames, filenames in os.walk(src):
            rel_dir = str(Path(dirpath).relative_to(src_root))
            dirnames[:] = [d for d in dirnames if not matches(f"{rel_dir}/{d}", NEVER) or matches(f"{rel_dir}/{d}", ALLOW_EVEN_IF_NEVER)]
            n_shots += sum(len(fs) for d in dirnames if d in SCREENSHOT_DIRS for _, _, fs in os.walk(os.path.join(dirpath, d)))
            dirnames[:] = [d for d in dirnames if d not in SCREENSHOT_DIRS]
            for fn in filenames:
                rel = f"{rel_dir}/{fn}"
                if matches(rel, NEVER) and not matches(rel, ALLOW_EVEN_IF_NEVER):
                    n_never += 1; continue
                if is_screenshot(rel):
                    n_shots += 1; continue
                dst = out / rel; dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(dirpath + "/" + fn, dst); n_files += 1
                except OSError as e:
                    log(f"  !! copy failed {rel}: {e}")
    return {"files": n_files, "ship_items_missing": n_skipped, "never_matched": n_never, "screenshots_dropped": n_shots}


def carried_path(rel: str) -> bool:
    """A path the export carries from the working tree on purpose: a runtime file, or a compiled circuit artifact."""
    return rel in RUNTIME_FILES or (rel.startswith("AgentVault/agentvault_circuit_registry/") and "/target/" in f"/{rel}")


DRYRUN_AUTHOR = ("oss-export-dryrun", "oss@theprotocol.cloud")
AUTHOR_RE = re.compile(r"^\s*([^<>\n]*[^<>\s])\s*<([^<>\s@]+@[^<>\s@]+\.[^<>\s@]+)>\s*$")


def parse_author(text: str) -> tuple:
    """--author "Name <address>": exactly one name and one address, or a ValueError naming what was given."""
    m = AUTHOR_RE.match(text or "")
    if not m:
        raise ValueError(f'--author wants "Name <address>", got {text!r}')
    return m.group(1), m.group(2)


def commit_export(out: Path, message: str, log, author: tuple = DRYRUN_AUTHOR, signoff: bool = False) -> tuple:
    """git init + a commit of EVERY file the export holds (G6). A .gitignore that ships inside the export
    (agentvault_registry's ignores `downloads/` and `*.sql`) kept the carried runtime files out of the commits, so a
    clone lacked what the export directory had and G5, which counts the directory, could not see it. Carried artifacts
    are force-added by name; any OTHER file a shipped .gitignore hides refuses the export, because nobody decided whether
    it ships. Paths are read NUL-separated so git's quoting of unusual names cannot fake a difference."""
    g = lambda *a, **k: subprocess.run(["git", "-c", "core.fileMode=true", "-c", f"user.name={author[0]}", "-c", f"user.email={author[1]}", *a], cwd=out, **k)
    g("init", "-q", "-b", "main", check=True)
    g("add", "-A", check=True)
    on_disk = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file() and p.relative_to(out).parts[0] != ".git")
    tracked = set(x for x in g("ls-files", "-z", capture_output=True, text=True, check=True).stdout.split("\0") if x)
    hidden = [r for r in on_disk if r not in tracked]
    unexpected = [r for r in hidden if not carried_path(r)]
    if unexpected:
        return False, f"G6: a shipped .gitignore hides {len(unexpected)} file(s) that are not carried artifacts, e.g. {unexpected[:5]}"
    if hidden:
        g("add", "-f", "--", *hidden, check=True)
        log(f"[export] force-added {len(hidden)} carried artifact(s) a shipped .gitignore hides")
    tracked = set(x for x in g("ls-files", "-z", capture_output=True, text=True, check=True).stdout.split("\0") if x)
    missing = [r for r in on_disk if r not in tracked]
    if missing:
        return False, f"G6: {len(missing)} file(s) still not in the commit, e.g. {missing[:5]}"
    # G7: a file that starts with #! is run as ./name from a clone, so it must be committed 100755. Both source repos
    # were committed under core.fileMode=false, which never records the bit: every script arrived 100644 and the
    # README's ./operator-setup.sh could not run in a clean clone (§OSSRC proof, 2026-09-14). The fix belongs in the
    # source repo (`git update-index --chmod=+x`), so this refuses rather than setting the bit here.
    not_exec, n_exec = [], 0
    for row in g("ls-files", "-s", "-z", capture_output=True, text=True, check=True).stdout.split("\0"):
        meta, _, rel = row.partition("\t")
        if not rel:
            continue
        if meta.split(" ", 1)[0] == "100755":
            n_exec += 1
        elif (out / rel).is_file() and not (out / rel).is_symlink():
            with open(out / rel, "rb") as fh:
                if fh.read(2) == b"#!":
                    not_exec.append(rel)
    if not_exec:
        return False, f"G7: {len(not_exec)} file(s) start with #! but are not executable in the commit, e.g. {not_exec[:5]}"
    g("commit", "-q", *(["--signoff"] if signoff else []), "-m", message, check=True)
    log(f"[export] fresh history: 1 commit, {len(tracked)} files = every file the export holds (G6), {n_exec} executable, no #! file without its bit (G7)")
    return True, ""


# G11 (§TESTBED P0 c, 2026-09-19): a secret-named key with a LITERAL value in a shipped config file. G8 catches values
# that are live in a running container; a secret that is live somewhere else (a mailbox, a third-party account) is
# invisible to it, and one sat in docker-compose.local.yml from 2026-08-05 into the beta.5 kit. The rule reads keys by
# NAME and values by SHAPE, and a hit names the file, the line and the key, never the value.
# §LEGALKIT (2026-09-20): a Playwright spec carried a personal mailbox AND a password as TS constants; G2 knows no such shape
# and G11 only read config files. The spec and e2e trees are config in the sense that matters: a *_PASSWORD = "..." line there is a literal.
G11_FILES = ["**/*.yml", "**/*.yaml", "**/*.env.example", "**/*.env.tmpl", "**/*.env.sample", "**/env.example",
             "**/e2e/**/*.ts", "**/*.spec.ts", "**/*.spec.js", "**/tests/**/*.py"]
G11_KEY = re.compile(rb"^\s*(?:export\s+)?(?:const|let|var)?\s*-?\s*[\"']?([A-Za-z0-9_.-]*(?:PASSWORD|PASSWD|SECRET|TOKEN(?![A-Za-z])|PRIVATE_KEY|API_KEY)[A-Za-z0-9_.-]*)[\"']?\s*[:=]\s*(.*?)\s*,?\s*;?\s*$", re.I)
G11_MARKERS = ("change", "example", "placeholder", "dummy", "sample", "your", "xxx", "insecure", "not-for", "notfor",
               "replace", "fake", "dev", "test", "local", "default", "redacted", "unset", "none", "null")
G11_LOCAL_DEFAULTS = {"postgres", "password", "changeme", "admin", "secret", "registry", "agentvault", "guest"}
# a key that NAMES a secret's context rather than holding one (the image registry's token SERVICE and ISSUER are labels)
# G12 (§LEGALKIT, 2026-09-20): a personal detail of the software's author in the export. The legal pages, the mail
# footer, security.txt and the API metadata now render the provider from each frame's env, so NOTHING shipped may
# carry the author's address, mailboxes, venue or authority. Two halves: SHAPES that no shipped file should carry
# (a mailbox at a consumer provider, the theprotocol suite mode as a literal), and a REFERENCE SET read at export
# time from the facts file OUTSIDE every repository (values never printed, never committed). The author's NAME is
# allowed (authorship credit, bylines).
G12_FACTS_FILE = Path(os.getenv("LEGAL_FACTS_FILE", "/opt/theprotocol/stack/Agentvault2/sessionlogs2026/provider_facts.env"))
G12_SHAPES = {
    "consumer_mailbox": re.compile(rb"[A-Za-z0-9._%+-]+@(?:gmail|googlemail|gmx|web|outlook|hotmail|yahoo|proton|protonmail|icloud)\.[a-z]{2,}", re.I),
    "theprotocol_mode_literal": re.compile(rb"LEGAL_SUITE_MODE\s*[:=]\s*[\"']?theprotocol"),
}
G11_CODE_FILES = ["**/*.ts", "**/*.js", "**/*.py"]
G12_MAILBOX_ALLOWED = ["SECURITY.md", "CONTRIBUTING.md", "CLA.md", "README.md", "LICENSING.md", "REVIEWING.md", "PUBLIC_DOCS/**",
                       "**/downloads/*.md", "**/content/compliance/*.md",
                       # the AgentVault repository ships its own copies of the four (§LEGALKIT 2026-09-21: its README
                       # names the security mailbox exactly as the root README does); a mailbox only, never an address
                       "AgentVault/README.md", "AgentVault/SECURITY.md", "AgentVault/CONTRIBUTING.md", "AgentVault/CLA.md"]
G12_REFERENCE_KEYS = ("LEGAL_PROVIDER_STREET", "LEGAL_PROVIDER_POSTAL_CODE", "LEGAL_CONTACT_EMAIL", "LEGAL_PRIVACY_EMAIL",
                      "LEGAL_SECURITY_EMAIL", "LEGAL_SUPPORT_EMAIL", "LEGAL_VENUE", "LEGAL_SUPERVISORY_AUTHORITY")


def g12_reference() -> list:
    """The author's details, read from the facts file at export time; [] when it is not there (shapes still run)."""
    if not G12_FACTS_FILE.exists():
        return []
    vals, kv = [], {}
    for line in G12_FACTS_FILE.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        k, v = line.split("=", 1); kv[k.strip()] = v.strip()
    for k in G12_REFERENCE_KEYS:
        v = kv.get(k, "")
        if k == "LEGAL_PROVIDER_POSTAL_CODE":
            continue  # a bare postal code is five digits: it fires on astronomical tables (Cesium's IAU2006 data carries 83395)
        if len(v) >= 5:
            vals.append(v.encode("utf-8"))
    if kv.get("LEGAL_PROVIDER_POSTAL_CODE") and kv.get("LEGAL_PROVIDER_CITY"):
        vals.append(f"{kv['LEGAL_PROVIDER_POSTAL_CODE']} {kv['LEGAL_PROVIDER_CITY']}".encode("utf-8"))  # the pair is the detail
    return vals


G11_LABEL_KEY = re.compile(rb"(_SERVICE|_ISSUER|_REALM|_URL|_URI|_ENDPOINT|_HOST|_TYPE|_NAME|_HEADER|_PATH|_FILE|_DIR|_TTL|"
                           rb"_EXPIRE[A-Z_]*|_ALGORITHM|_ALG|_LENGTH|_MODE|_ENABLED|_ID)$", re.I)


def g11_literal(value: bytes) -> bool:
    """True when a secret-named key's value is a literal that could be a real secret."""
    # a dict or object entry ends in a comma (`"tokens_issued": "1000000.0",`): the comma is not part of the value,
    # and with it the quote stripping left a quote behind and a supply figure read as a secret (measured 2026-09-20)
    v = value.split(b" #", 1)[0].strip().rstrip(b",").strip().strip(b"\"'").strip()
    if not v or v in (b"|", b">", b"~"):
        return False
    low = v.lower().decode("utf-8", "replace")
    if "${" in low or "{{" in low or "$(" in low or low.startswith(("<", "*", "&", "!", "[", "{")):
        return False                      # interpolated, templated, a placeholder, a YAML anchor/tag/list/map
    if low in ("true", "false", "yes", "no", "on", "off") or low.replace(".", "", 1).isdigit():
        return False
    if low.startswith(("/", "./", "../", "~/")):
        return False                      # a path to a secret file, not the secret
    if low.startswith(("http://", "https://")) and "@" not in low.split("//", 1)[1].split("/", 1)[0]:
        return False                      # an address with no credentials in it
    if any(m in low for m in G11_MARKERS) or low in G11_LOCAL_DEFAULTS:
        return False
    return len(low) >= 6


# G13 (§EXPORTIP, 2026-09-29; the 09-27 GitHub handover § 5): a public IPv4 address in the export. The scan ran by hand on
# 09-21 and 09-27, and on 09-27 it found this host's address back in a test fixture (§INGRESS404), which is why it is a
# gate now: it refuses the next one without anyone remembering to look. What may stand is the 09-21 baseline
# (FINDINGS_2026-09-21_RELEASECHANNEL § 12, his answers that evening): the public resolvers used on purpose and the
# documentation examples, anywhere; version strings in lock files (in a lock file only a URL's host counts: a package
# version with four parts is quiet there, `https://<address>/` is not); and each address the maintainer's allowlist binds to
# a path (the journal's captions, his rule "the journal stays"). The allowlist lives OUTSIDE the export, like G1's
# denylist, so the gate never ships the addresses it permits; without it those addresses fire and the export refuses:
# stricter, never quieter. Private, loopback, link-local, shared and documentation ranges (192.0.2.0/24,
# 198.51.100.0/24, 203.0.113.0/24) are not public, so a test fixture should use those.
G13_ANYWHERE = frozenset({"1.1.1.1", "8.8.8.8", "9.9.9.9", "93.184.216.34", "1.2.3.4"})
G13_ALLOW_FILE = Path(os.getenv("TP_EXPORT_IP_ALLOW", "/opt/theprotocol/stack/Agentvault2/sessionlogs2026/export_ip_allow.txt"))
G13_LOCK_FILES = ["**/poetry.lock", "**/uv.lock", "**/Cargo.lock", "**/yarn.lock", "**/package-lock.json", "**/pnpm-lock.yaml"]
# four dotted numbers that are not part of a longer dotted run (an OID such as 1.3.6.1.4.1 never matches)
G13_IPV4 = re.compile(rb"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d|\.\d)")


def g13_allowlist(path: "Path | None" = None) -> dict:
    """{address: [path globs]} from the maintainer's allowlist: one `<address> <glob>` per line, '#' starts a comment."""
    path = path or G13_ALLOW_FILE
    allow = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            addr, _, glob = line.split("#", 1)[0].strip().partition(" ")
            if addr and glob.strip():
                allow.setdefault(addr, []).append(glob.strip())
    return allow


def g13_public_ipv4(rel: str, data: bytes, allow: dict) -> list:
    """The public IPv4 addresses in one file that no rule permits, each once."""
    lock = matches(rel, G13_LOCK_FILES)
    found = []
    for m in G13_IPV4.finditer(data):
        if lock and data[max(0, m.start() - 2):m.start()] != b"//" and data[max(0, m.start() - 1):m.start()] != b"@":
            continue
        addr = m.group(0).decode()
        try:
            ip = ipaddress.IPv4Address(addr)
        except ValueError:
            continue                                  # an octet above 255: a version string, not an address
        # multicast names a group, not a host (the registry's own _address_is_internal calls 224.0.0.1 internal)
        public = ip.is_global and not ip.is_multicast
        if public and addr not in G13_ANYWHERE and addr not in found and not matches(rel, allow.get(addr, [])):
            found.append(addr)
    return found


def public_docs_drift(stack_ref: str) -> list:
    """G14: every way the committed PUBLIC_DOCS differs from its generation; a check that cannot run is a hit."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import gen_public_docs
        return gen_public_docs.check(stack_ref)
    except (Exception, SystemExit) as exc:  # the generator exits on an unreadable pin or content map
        return [f"NOT MEASURED at {stack_ref[:12]}: {type(exc).__name__}: {str(exc)[:200]}"]


def gate(out: Path, log, live=None) -> dict:
    """Every gate returns its hits; the caller refuses on any. The denylist is read by NAME; no value is ever printed.
    `live` is G8's population ((container, VAR, value) tuples); None means ask docker, [] means an empty census."""
    hits = {"G1_denylist": [], "G2_shape": [], "G3_keyfile": [], "G4_hex_secret": [], "G8_live_env": [], "G9_screenshots": [],
            "G10_journal_media": [], "G11_secret_literal": [], "G12_provider_detail": [], "G13_public_ipv4": []}
    g12_ref = g12_reference()
    g13_allow = g13_allowlist()
    hits["_g13_allowlist_entries"] = sum(len(v) for v in g13_allow.values())
    hits["_g12_reference_loaded"] = len(g12_ref)
    if live is None:
        live = live_env_values(log)
    live_rx, live_by = live_regex(live)
    hits["_live_values"] = None if live is None else len(live_by)
    literals = []
    if DENYLIST.exists():
        literals = [l.strip().encode() for l in DENYLIST.read_text().splitlines() if l.strip() and not l.startswith("#")]
    else:
        log(f"  !! denylist {DENYLIST} is not readable: G1 cannot run (NOT MEASURED, not passed)")
    for dirpath, dirnames, filenames in os.walk(out):
        if "/.git" in dirpath or dirpath.endswith("/.git"):
            continue
        for fn in filenames:
            p = Path(dirpath) / fn; rel = str(p.relative_to(out))
            if is_screenshot(rel):
                hits["G9_screenshots"].append(rel)
            if matches(rel, JOURNAL_MEDIA):
                hits["G10_journal_media"].append(rel)
            if matches(rel, ["**/*.key", "**/*-key.pem", "**/token-signing.key", "**/mcp-registry-key.pem", "**/dummy_upstream_ca.key", "**/docker-certs/**", "**/.env", "**/.env.*"]) and not matches(rel, ALLOW_EVEN_IF_NEVER):
                hits["G3_keyfile"].append(rel)
            try:
                if p.stat().st_size > TEXT_MAX: continue
                data = p.read_bytes()
            except OSError:
                continue
            for lit in literals:
                if lit and lit in data:
                    hits["G1_denylist"].append(f"{rel} (literal #{literals.index(lit) + 1})")
            for name, rx in SHAPES.items():
                m = rx.search(data)
                if m:
                    (hits["G4_hex_secret"] if name == "hex_secret_assignment" else hits["G2_shape"]).append(f"{rel} ({name})")
            if live_rx is not None:
                m = live_rx.search(data)
                if m:
                    hits["G8_live_env"].append(f"{rel} (a value present in the env of {live_by.get(m.group(0), '?')})")
            for name, rx in G12_SHAPES.items():
                if rx.search(data):
                    hits["G12_provider_detail"].append(f"{rel} ({name})")
            for addr in g13_public_ipv4(rel, data, g13_allow):
                hits["G13_public_ipv4"].append(f"{rel} ({addr})")
            for i, ref in enumerate(g12_ref):
                if ref in data and not (b"@" in ref and matches(rel, G12_MAILBOX_ALLOWED)):
                    # a MAILBOX of the author may stand where it is the SOFTWARE's contact (the security policy,
                    # the contribution terms, the public docs, the operator manual, the author's own compliance
                    # self-assessment); an address, a venue or an authority may stand nowhere
                    hits["G12_provider_detail"].append(f"{rel} (reference #{i + 1})")
                    break
            if matches(rel, G11_FILES):
                for n, line in enumerate(data.splitlines(), 1):
                    if b"# g11:" in line:
                        continue          # a reviewed literal: the annotation says why it may ship (a local dev default)
                    m = G11_KEY.match(line)
                    if m and matches(rel, G11_CODE_FILES) and not m.group(2).lstrip().startswith((b"'", b'"', b"`")):
                        continue          # in code only a QUOTED value is a literal: `token = await ...` is an expression
                    if m and not G11_LABEL_KEY.search(m.group(1)) and g11_literal(m.group(2)):
                        hits["G11_secret_literal"].append(f"{rel}:{n} ({m.group(1).decode('utf-8', 'replace')})")
    circuits = sum(1 for _ in (out / "AgentVault/agentvault_circuit_registry").rglob("*") if "target" in _.parts and _.is_file()) if (out / "AgentVault/agentvault_circuit_registry").exists() else 0
    runtime_missing = [f for f in RUNTIME_FILES if not (out / f).exists()]
    hits["G5_carry"] = ([f"circuit artifacts {circuits} < 13"] if circuits < 13 else []) + [f"runtime file missing: {f}" for f in runtime_missing]
    hits["_denylist_literals"] = len(literals); hits["_circuit_artifacts"] = circuits
    return hits


def selftest(log) -> bool:
    """The controls: a planted specimen of every class must FIRE."""
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "AgentVault/agentvault_circuit_registry/x/target").mkdir(parents=True)
        for i in range(13): (t / f"AgentVault/agentvault_circuit_registry/x/target/a{i}.json").write_text("{}")
        for f in RUNTIME_FILES: (t / f).parent.mkdir(parents=True, exist_ok=True); (t / f).write_text("x")
        clean = gate(t, log, live=[]); ok &= all(not v for k, v in clean.items() if not k.startswith("_"))
        log(f"  control 0 (a clean tree passes every gate): {'ok' if ok else 'FAILED ' + str(clean)}")
        specimens = {
            "G2_shape": ("planted/key.txt", b"avreg_" + b"A" * 40),
            "G2_shape_pem": ("planted/x.txt", b"-----BEGIN " + b"PRIVATE KEY-----\n" + b"MIIE" + b"A" * 60 + b"\n"),
            "G3_keyfile": ("planted/server.key", b"not even a key"),
            "G4_hex_secret": ("planted/n.txt", b"INTERNAL_" + b"API_KEY=" + b"0123456789abcdef" * 4),
            "G12_provider_detail": ("planted/notes.md", b"contact me at some.person@" + b"gmail.com for the keys"),
            "G12_provider_detail_mode": ("planted/frame.env.tmpl", b"LEGAL_SUITE" + b"_MODE=theprotocol\n"),
            "G11_secret_literal_spec": ("planted/e2e/x.spec.ts", b"const AGENTLESS_PASS" + b"WORD = 'Tr0ub4dor-and-" + b"z" * 8 + b"'\n"),
            "G11_secret_literal": ("planted/docker-compose.x.yml",
                                   b"services:\n  a:\n    environment:\n      MAIL_PASS" + b"WORD: Tr0ub4dor-and-" + b"z" * 8 + b"\n"),
        }
        for name, (rel, body) in specimens.items():
            p = t / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(body)
            h = gate(t, log, live=[]); key = name.split("_pem")[0].split("_mode")[0].split("_spec")[0]
            fired = bool(h.get(key))
            log(f"  control {name}: {'FIRED' if fired else 'DID NOT FIRE'}"); ok &= fired
            p.unlink()
        # G12 quiet: the author's name (authorship credit) and a synthetic example address do not fire; the
        # reference set fires only on the author's real details, which this control never writes
        p = t / "planted/credit.md"; p.write_text("Copyright (C) 2026 Raphael Zbigniew Jeziorny. Example: 1 Example Road, 12345 Exampletown, legal@your.example\n")
        h = gate(t, log, live=[]); quiet = not h["G12_provider_detail"]; p.unlink()
        log(f"  control G12 quiet (the author's name and a synthetic example address): {'ok' if quiet else 'FAILED ' + str(h['G12_provider_detail'])}"); ok &= quiet
        if G12_FACTS_FILE.exists():
            ref = g12_reference()
            if ref:
                p = t / "planted/ref.txt"; p.write_bytes(b"x " + ref[0] + b" y"); h = gate(t, log, live=[]); fired = bool(h["G12_provider_detail"]); p.unlink()
                log(f"  control G12 reference (the first fact, never printed): {'FIRED' if fired else 'DID NOT FIRE'}"); ok &= fired
        # G11 quiet: an interpolation, a key that labels a secret's context, a reviewed annotation and a placeholder
        p = t / "planted/docker-compose.q.yml"; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x:\n  MAIL_PASSWORD: ${MAIL_PASSWORD:-}\n  REGISTRY_AUTH_TOKEN_SERVICE: Docker registry\n"
                     "  DB_PASSWORD: s3cr3t-value-here   # g11: local dev default\n  API_KEY: change-me\n")
        h = gate(t, log, live=[]); quiet = not h["G11_secret_literal"]; p.unlink()
        log(f"  control G11 quiet (interpolated, a label key, a reviewed annotation, a placeholder): "
            f"{'ok' if quiet else 'FAILED ' + str(h['G11_secret_literal'])}"); ok &= quiet
        # G11 in code: a supply figure under a `tokens_*` key with a trailing comma is quiet; a quoted credential under
        # a token key with the same trailing comma FIRES (both shapes measured in the tree, 2026-09-20)
        p = t / "planted/tests/unit/t_fixture.py"; p.parent.mkdir(parents=True, exist_ok=True)   # the tests glob wants a subdirectory, like the tree's
        p.write_text('def _p():\n    return {\n        "tokens_issued": "1000000.0",\n        "tokens_fees": "500.0",\n    }\n')
        h = gate(t, log, live=[]); quiet = not h["G11_secret_literal"]; p.unlink()
        log(f"  control G11 quiet (supply figures under tokens_* keys, trailing commas): {'ok' if quiet else 'FAILED ' + str(h['G11_secret_literal'])}"); ok &= quiet
        p.write_text('def _p():\n    return {\n        "api_token": "k9v2q8x1m4z7p3w6r5t8y1u4",\n    }\n')
        h = gate(t, log, live=[]); fired = bool(h["G11_secret_literal"]); p.unlink()
        log(f"  control G11 code literal with a trailing comma: {'FIRED' if fired else 'DID NOT FIRE'}"); ok &= fired
        # G13: a public address in a fixture FIRES; the documentation, private, loopback and shared ranges, an allowed
        # resolver, an OID, an octet above 255 and a lock file's version string stay quiet; an address the allowlist binds
        # to one path is quiet there and FIRES anywhere else. Every address is built here, so this file holds none.
        pub = ".".join(["8", "8", "4", "4"])
        p = t / "planted/tests/test_dial.py"; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"PEER = 'https://{pub}:8443/'\n"); h = gate(t, log, live=[]); fired = h["G13_public_ipv4"] == [f"planted/tests/test_dial.py ({pub})"]; p.unlink()
        log(f"  control G13_public_ipv4 (a public address in a test fixture): {'FIRED' if fired else 'DID NOT FIRE ' + str(h['G13_public_ipv4'])}"); ok &= fired
        quiet_text = " ".join([".".join(q) for q in (["203", "0", "113", "10"], ["198", "51", "100", "7"], ["192", "0", "2", "1"],
                                                   ["10", "0", "0", "1"], ["172", "16", "0", "7"], ["192", "168", "1", "1"],
                                                   ["127", "0", "0", "1"], ["100", "64", "0", "1"], ["1", "1", "1", "1"],
                                                   ["224", "0", "0", "1"],
                                                   ["1", "3", "6", "1", "4", "1", "311"], ["300", "1", "2", "3"])])
        p.write_text(f"# {quiet_text}\n"); lk = t / "planted/app/poetry.lock"; lk.parent.mkdir(parents=True, exist_ok=True)
        lk.write_text('version = "' + ".".join(["8", "3", "0", "3"]) + '"\n{file = "pkg-' + ".".join(["8", "3", "0", "3"]) + '.tar.gz"}\n')
        h = gate(t, log, live=[]); quiet = not h["G13_public_ipv4"]
        log(f"  control G13 quiet (documentation, private, loopback, shared, multicast, a resolver, an OID, octet > 255, a lock version): {'ok' if quiet else 'FAILED ' + str(h['G13_public_ipv4'])}"); ok &= quiet
        lk.write_text('source = "https://' + pub + '/simple"\n'); h = gate(t, log, live=[]); fired = h["G13_public_ipv4"] == [f"planted/app/poetry.lock ({pub})"]; lk.unlink(); p.unlink()
        log(f"  control G13 lock file (an address as a URL's host): {'FIRED' if fired else 'DID NOT FIRE ' + str(h['G13_public_ipv4'])}"); ok &= fired
        allow_dir = Path(tempfile.mkdtemp())      # outside the scanned tree, like the real allowlist
        allow_file = allow_dir / "allow.txt"; allow_file.write_text(f"{pub} **/views/Journal.vue   # a caption\n")
        keep, globals()["G13_ALLOW_FILE"] = G13_ALLOW_FILE, allow_file
        try:
            j = t / "planted/views/Journal.vue"; j.parent.mkdir(parents=True, exist_ok=True); j.write_text(f"<p>seen from {pub}</p>\n")
            h = gate(t, log, live=[]); quiet = not h["G13_public_ipv4"] and h["_g13_allowlist_entries"] == 1
            log(f"  control G13 allowlist (the bound path is quiet): {'ok' if quiet else 'FAILED ' + str(h['G13_public_ipv4'])}"); ok &= quiet
            o = t / "planted/views/Other.vue"; o.write_text(f"<p>{pub}</p>\n")
            h = gate(t, log, live=[]); fired = h["G13_public_ipv4"] == [f"planted/views/Other.vue ({pub})"]; o.unlink(); j.unlink()
            log(f"  control G13 allowlist elsewhere (the same address outside its path): {'FIRED' if fired else 'DID NOT FIRE ' + str(h['G13_public_ipv4'])}"); ok &= fired
        finally:
            globals()["G13_ALLOW_FILE"] = keep; shutil.rmtree(allow_dir, ignore_errors=True)
        # G14: a hand-edited copy, a page the source dropped and a file nobody generates FIRE; the hand-kept files and an
        # identical copy stay quiet; a stack ref the check cannot read is NOT MEASURED, which refuses as a hit
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import gen_public_docs as gpd
        gen = {"README.md": b"index", "00_QUICKSTART.md": b"generated"}
        same = dict(gen, LICENSE=b"cc-by")
        quiet = gpd.differences(gen, same) == []
        log(f"  control G14 quiet (an identical copy beside the hand-kept LICENSE): {'ok' if quiet else 'FAILED'}"); ok &= quiet
        for what, actual in (("a hand edit", dict(same, **{"00_QUICKSTART.md": b"edited by hand"})),
                             ("a page the source dropped", dict(same, **{"OLD_PAGE.md": b"stale"})),
                             ("a generated page missing", {"README.md": b"index"})):
            fired = bool(gpd.differences(gen, actual))
            log(f"  control G14 ({what}): {'FIRED' if fired else 'DID NOT FIRE'}"); ok &= fired
        unreadable = public_docs_drift("0" * 40)
        fired = len(unreadable) == 1 and unreadable[0].startswith("NOT MEASURED")
        log(f"  control G14 (a stack ref the check cannot read is NOT MEASURED, a hit): {'FIRED' if fired else 'DID NOT FIRE ' + str(unreadable)}"); ok &= fired
        if DENYLIST.exists():
            lits = [l.strip() for l in DENYLIST.read_text().splitlines() if l.strip() and not l.startswith("#")]
            if lits:
                p = t / "planted/d.txt"; p.write_text("x " + lits[0] + " y"); h = gate(t, log, live=[]); fired = bool(h["G1_denylist"]); p.unlink()
                log(f"  control G1_denylist (the first literal, never printed): {'FIRED' if fired else 'DID NOT FIRE'}"); ok &= fired
        # G8: a planted live value (built here, never a real one) must fire, a file without it must not, and the
        # password component of a DSN inside a JSON value must be extracted
        planted = [("selftest-container", "PLANTED_SECRET", b"selftest" + b"9" * 20)]
        p = t / "planted/live.txt"; p.write_text("config = 'selftest" + "9" * 20 + "'"); h = gate(t, log, live=planted); fired = bool(h["G8_live_env"]); p.unlink()
        log(f"  control G8_live_env (a planted live value in a file): {'FIRED' if fired else 'DID NOT FIRE'}"); ok &= fired
        p.write_text("config = 'selftest" + "8" * 20 + "'"); h = gate(t, log, live=planted); quiet = not h["G8_live_env"]; p.unlink()
        log(f"  control G8 quiet (a different value does not fire): {'ok' if quiet else 'FAILED'}"); ok &= quiet
        env = ["DATABASE_URL=postgresql://u:pw1234567890abcdef@h/db", "EXTRA_JSON=" + json.dumps({"dsn": "postgresql://x:jsonpw123456789@h/db"}),
               "REGISTRY_SIGNING_KEY_PATH=/app/keys/a.pem", "TEG_TOKEN_SIGNING_KEY=abcdef0123456789abcdef", "TOKEN_EXPIRE_MINUTES=30",
               "DOCKER_TOKEN_SERVICE=images.example.cloud", "DOCKER_TOKEN_ISSUER=Example-Registry-Token-Issuer", "API_KEY_SECRET=this-service-reads-no-api-key-secret",
               "ADMIN_EMAIL_TOKEN=someone@example.cloud", "MAIL_PASSWORD=Tr0ub4dor&3-and-twenty-more",
               "TEG_ADMIN_API_KEY=shared-secret-retired-2026-06-17-marker-not-a-key-0"]
        ex = live_values_from_inspect("/c1\t" + json.dumps(env))
        got = sorted(v.decode() for _, _, v in ex)
        held = got == ["Tr0ub4dor&3-and-twenty-more", "abcdef0123456789abcdef", "jsonpw123456789", "pw1234567890abcdef"]
        log(f"  control G8 extraction (DSN passwords incl. inside JSON, an opaque key, a real password; a path, a short value, a hostname, a label, an email, a retirement marker stay out): {'ok' if held else 'FAILED ' + str(got)}"); ok &= held
        # G9: a capture folder, a loose capture at the frontend's root and a file named for what it is must fire; the app's
        # own images (public/, src/assets/) and the standup's theme marks must stay quiet
        fe = "AgentVault/agentvault_registry/src/agentvault_registry/static/new_registry_frontend"
        for rel in (f"{fe}/e2e-screenshots/audit.png", f"{fe}/playwright-report/data/x.png", f"{fe}/aw2_arcs.png", "planted/admin-screenshot.jpg"):
            p = t / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"\x89PNG")
            h = gate(t, log, live=[]); fired = rel in h["G9_screenshots"]; p.unlink()
            log(f"  control G9_screenshots ({rel.split('/')[-2]}/{rel.split('/')[-1]}): {'FIRED' if fired else 'DID NOT FIRE'}"); ok &= fired
        for rel in (f"{fe}/public/assets/logo.png", f"{fe}/public/blog/p1.jpg", f"{fe}/src/assets/images/a.png", "scripts/hetzner_demo/assets/protocol-mark-neural.png"):
            p = t / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"\x89PNG")
            h = gate(t, log, live=[]); quiet = not h["G9_screenshots"]; p.unlink()
            log(f"  control G9 quiet ({rel.split('/')[-2]}/{rel.split('/')[-1]}): {'ok' if quiet else 'FAILED'}"); ok &= quiet
        # G10: a journal figure must fire; the console's other public images and the journal's own view must stay quiet
        for rel in (f"{fe}/public/blog/p46-1-lead.jpg", f"{fe}/public/blog/videos/v.mp4"):
            p = t / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"\xff\xd8")
            h = gate(t, log, live=[]); fired = rel in h["G10_journal_media"]; p.unlink()
            log(f"  control G10_journal_media ({rel.split('/')[-2]}/{rel.split('/')[-1]}): {'FIRED' if fired else 'DID NOT FIRE'}"); ok &= fired
        shutil.rmtree(t / f"{fe}/public/blog", ignore_errors=True)
        for rel in (f"{fe}/public/assets/logo.png", f"{fe}/src/views/BlogView.vue", f"{fe}/public/og-image.png"):
            p = t / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"x")
            h = gate(t, log, live=[]); quiet = not h["G10_journal_media"]; p.unlink()
            log(f"  control G10 quiet ({rel.split('/')[-2]}/{rel.split('/')[-1]}): {'ok' if quiet else 'FAILED'}"); ok &= quiet
        # the copy's side of the same predicate: a journal figure and a dated backup are NEVER copied; a public image is
        held = matches(f"{fe}/public/blog/p1.jpg", NEVER) and matches(f"{fe}/public/og-image.jpg.prev-2026-04-23", NEVER) \
            and not matches(f"{fe}/public/og-image.jpg", NEVER) and not matches(f"{fe}/src/views/BlogView.vue", NEVER)
        log(f"  control copy (journal media and dated backups stay home, the console's own files ship): {'ok' if held else 'FAILED'}"); ok &= held
        shutil.rmtree(t / "AgentVault/agentvault_circuit_registry"); h = gate(t, log, live=[]); fired = bool(h["G5_carry"]); log(f"  control G5_carry (no artifacts): {'FIRED' if fired else 'DID NOT FIRE'}"); ok &= fired
    # §OSSRC: the export reads commits. An untracked file and an uncommitted edit in the working tree must stay out,
    # and a path the commit does not hold must refuse rather than ship less.
    with tempfile.TemporaryDirectory() as td:
        r = Path(td) / "repo"; (r / "shipped").mkdir(parents=True)
        g = lambda *x: subprocess.run(["git", *x], cwd=r, check=True, capture_output=True)
        g("init", "-q"); (r / "shipped/committed.txt").write_text("as committed")
        g("add", "-A"); g("-c", "user.name=selftest", "-c", "user.email=selftest@example.com", "commit", "-q", "-m", "fixture")
        (r / "shipped/untracked.txt").write_text("never committed"); (r / "shipped/committed.txt").write_text("edited, not committed")
        dest = Path(td) / "stage"
        archive_into(r, "HEAD", ["shipped"], dest)
        body = (dest / "shipped/committed.txt").read_text() if (dest / "shipped/committed.txt").exists() else None
        held = body == "as committed" and not (dest / "shipped/untracked.txt").exists()
        log(f"  control commits-only (an untracked file and an uncommitted edit stay out): {'ok' if held else 'FAILED ' + repr(body)}")
        ok &= held
        try:
            archive_into(r, "HEAD", ["not-in-the-commit"], Path(td) / "stage2"); refused = False
        except SystemExit:
            refused = True
        log(f"  control missing path (git archive refuses, the export does not ship less): {'FIRED' if refused else 'DID NOT FIRE'}")
        ok &= refused
    # §OSSRC G6: a shipped .gitignore must not keep a carried artifact out of the commit, nor silently hide anything else
    with tempfile.TemporaryDirectory() as td:
        o = Path(td) / "export"; (o / "AgentVault/agentvault_registry/downloads").mkdir(parents=True)
        (o / "AgentVault/agentvault_registry/.gitignore").write_text("downloads/\n*.sql\n")
        (o / RUNTIME_FILES[1]).write_text("carried")
        (o / "AgentVault/agentvault_registry/ships.txt").write_text("ships")
        ok1, why1 = commit_export(o, "selftest", lambda s: None)
        committed = subprocess.run(["git", "ls-files", "-z"], cwd=o, capture_output=True, text=True).stdout.split("\0")
        held = ok1 and RUNTIME_FILES[1] in committed
        log(f"  control G6 carried (a shipped .gitignore hides a carried file; it is committed anyway): {'ok' if held else 'FAILED ' + why1}")
        ok &= held
        o2 = Path(td) / "export2"; (o2 / "x").mkdir(parents=True)
        (o2 / "x/.gitignore").write_text("*.cfg\n"); (o2 / "x/hidden.cfg").write_text("nobody decided")
        ok2, why2 = commit_export(o2, "selftest", lambda s: None)
        fired = (not ok2) and why2.startswith("G6")
        log(f"  control G6 unexpected (a hidden file that is not a carried artifact refuses): {'FIRED' if fired else 'DID NOT FIRE'}")
        ok &= fired
    # §OSSRC G7: a file that starts with #! must be committed executable, and one that has its bit must keep it
    with tempfile.TemporaryDirectory() as td:
        o3 = Path(td) / "export3"; (o3 / "bin").mkdir(parents=True)
        (o3 / "bin/run.sh").write_text("#!/bin/sh\necho ok\n"); os.chmod(o3 / "bin/run.sh", 0o644)
        ok3, why3 = commit_export(o3, "selftest", lambda s: None)
        fired = (not ok3) and why3.startswith("G7")
        log(f"  control G7 (a #! file committed 100644 refuses): {'FIRED' if fired else 'DID NOT FIRE ' + why3}"); ok &= fired
        o4 = Path(td) / "export4"; (o4 / "bin").mkdir(parents=True)
        (o4 / "bin/run.sh").write_text("#!/bin/sh\necho ok\n"); os.chmod(o4 / "bin/run.sh", 0o755)
        (o4 / "bin/notes.txt").write_text("not a script"); os.chmod(o4 / "bin/notes.txt", 0o644)
        ok4, why4 = commit_export(o4, "selftest", lambda s: None)
        rows = subprocess.run(["git", "ls-files", "-s"], cwd=o4, capture_output=True, text=True).stdout.splitlines()
        modes = {r.split("\t", 1)[1]: r.split(" ", 1)[0] for r in rows if "\t" in r}
        held = ok4 and modes.get("bin/run.sh") == "100755" and modes.get("bin/notes.txt") == "100644"
        log(f"  control G7 executable (a #! file with its bit is committed 100755, a text file stays 100644): {'ok' if held else 'FAILED ' + why4 + ' ' + str(modes)}"); ok &= held
        # a carried artifact no commit holds takes its mode from the export: #! executable, anything else unchanged
        root, stage = Path(td) / "tree", Path(td) / "stage5"
        for rel, body in ((RUNTIME_FILES[3], "#!/usr/bin/env node\n"), (RUNTIME_FILES[1], "# readme\n")):
            (root / rel).parent.mkdir(parents=True, exist_ok=True); (root / rel).write_text(body); os.chmod(root / rel, 0o640)
        carry_ignored(stage, lambda s: None, root=root)
        held = bool(os.stat(stage / RUNTIME_FILES[3]).st_mode & 0o100) and not os.stat(stage / RUNTIME_FILES[1]).st_mode & 0o100
        log(f"  control G7 carried (a carried #! artifact is marked executable, a carried text file is not): {'ok' if held else 'FAILED'}"); ok &= held
    # the commit flags (2026-09-26): without them the commit is byte for byte the one written before they existed (the
    # dates pinned, the old command line run by hand as the reference); with them it carries exactly the identity, the
    # Signed-off-by trailer and the message passed, over the same tree. The identity here is a synthetic one.
    pinned = {"GIT_AUTHOR_DATE": "2026-09-26T12:00:00+00:00", "GIT_COMMITTER_DATE": "2026-09-26T12:00:00+00:00"}
    saved = {k: os.environ.get(k) for k in pinned}
    os.environ.update(pinned)
    try:
        with tempfile.TemporaryDirectory() as td:
            def fixture(name):
                d = Path(td) / name; (d / "bin").mkdir(parents=True)
                (d / "README.md").write_text("fixture\n"); (d / "bin/run.sh").write_text("#!/bin/sh\necho ok\n"); os.chmod(d / "bin/run.sh", 0o755)
                return d
            cat = lambda d: subprocess.run(["git", "cat-file", "commit", "HEAD"], cwd=d, capture_output=True, check=True).stdout
            fmt = lambda d, f: subprocess.run(["git", "log", "-1", f"--format={f}"], cwd=d, capture_output=True, text=True, check=True).stdout.strip()
            plain, before = fixture("plain"), fixture("before")
            ok5, _why5 = commit_export(plain, "fixture message", lambda s: None)
            for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "fixture message"]):
                subprocess.run(["git", "-c", "core.fileMode=true", "-c", "user.name=oss-export-dryrun", "-c", "user.email=oss@theprotocol.cloud", *args],
                               cwd=before, check=True, capture_output=True)
            held = ok5 and cat(plain) == cat(before)
            log(f"  control commit default (no flags: byte-identical to the commit written before the flags): {'ok' if held else 'FAILED'}"); ok &= held
            flagged = fixture("flagged")
            ok6, _why6 = commit_export(flagged, "A first public commit", lambda s: None, author=parse_author("Ada Example <ada@example.org>"), signoff=True)
            held = (ok6 and fmt(flagged, "%T") == fmt(plain, "%T")
                    and fmt(flagged, "%an <%ae>|%cn <%ce>") == "Ada Example <ada@example.org>|Ada Example <ada@example.org>"
                    and fmt(flagged, "%B") == "A first public commit\n\nSigned-off-by: Ada Example <ada@example.org>")
            log(f"  control commit flags (author, committer, trailer and message as passed; the same tree): {'ok' if held else 'FAILED'}"); ok &= held
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    for bad in ("Ada Example", "<ada@example.org>", "Ada <ada>", "Ada Example <ada@example.org> and more", "Ada <a@b@example.org>"):
        try:
            parse_author(bad); fired = False
        except ValueError:
            fired = True
        log(f"  control --author {bad!r} refused: {'FIRED' if fired else 'DID NOT FIRE'}"); ok &= fired
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=f"/root/oss-export-dryrun/{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}")
    ap.add_argument("--stack-ref", default="", help="the stack commit to export (REQUIRED: an export never takes HEAD by default; "
                                                   "master's checkout can lack the source production runs, 2026-10-25)")
    ap.add_argument("--av-ref", default="", help="the AgentVault commit (default: the one the stack commit pins)")
    ap.add_argument("--from-tree", action="store_true", help="the 09-13 behaviour: copy the WORKING TREE (for comparison only)")
    ap.add_argument("--push", default="", help="owner/repo on git.theprotocol.cloud (PRIVATE; created when absent)")
    ap.add_argument("--push-branch", default="main", help="branch the export is force-pushed to (default main; name another to keep main's record)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--author", default="", help='"Name <address>" the fresh-history commit is by (author and committer); default the dry-run identity')
    ap.add_argument("--signoff", action="store_true", help="add a Signed-off-by line for that identity (git commit --signoff)")
    ap.add_argument("--message", default="", help="the commit message; default the dry-run message publish.py reads "
                                                   "(an export with another message is not a publishable kit)")
    a = ap.parse_args()
    log = lambda s: print(s, flush=True)
    if a.selftest:
        ok = selftest(log); log(f"[selftest] {'PASS' if ok else 'FAIL'}"); return 0 if ok else 2
    try:
        author = parse_author(a.author) if a.author else DRYRUN_AUTHOR
    except ValueError as exc:
        log(f"[export] REFUSED: {exc}"); return 2
    if a.message and not a.message.strip():
        log("[export] REFUSED: --message is blank"); return 2
    # agentvault2-aa 2026-10-25 (agentvault2-d6's ask, agentvault2-69's catch): the stack ref is named, never HEAD by default.
    # Stack master lacked the source production runs (kit/beta23 49 commits ahead, the essec4 store among them), so a
    # default export would have shipped older store and kit code without a word.
    if not a.from_tree and not a.stack_ref.strip():
        log("[export] REFUSED: name the stack commit with --stack-ref <ref> (no default: the checkout's HEAD can lack the "
            "source production runs; nothing written)"); return 2
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True); os.chmod(out, 0o700)
    log(f"[export] -> {out}")
    stage = None
    if a.from_tree:
        src_root, source = ROOT, "the working tree (--from-tree: uncommitted and untracked files ride in)"
    else:
        stack_sha, av_sha, pinned = resolve_refs(a.stack_ref, a.av_ref)
        log(f"[export] stack ref given: {a.stack_ref} = {stack_sha}")
        stage = out.parent / f".{out.name}.stage"
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True); os.chmod(stage, 0o700)
        archive_into(ROOT, stack_sha, STACK_SHIP, stage)
        archive_into(AV, av_sha, AV_SHIP, stage, prefix="AgentVault")
        carry_ignored(stage, log)
        src_root = stage
        source = f"stack {stack_sha[:12]} + AgentVault {av_sha[:12]}" + (" (the commit the stack pins)" if pinned else " (given)")
    log(f"[export] source: {source}")
    try:
        stats = copy_tree(out, log, src_root)
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
    log(f"[export] copied files={stats['files']} never_matched={stats['never_matched']} ship_items_missing={stats['ship_items_missing']} screenshots_dropped={stats['screenshots_dropped']}")
    if stats["ship_items_missing"]:
        log("[export] REFUSED: a ship item is missing from the source; nothing is committed"); return 3
    hits = gate(out, log)
    hits["G14_public_docs"] = public_docs_drift(stack_sha if not a.from_tree else "HEAD")
    for k, v in hits.items():
        if k.startswith("_"): continue
        log(f"[gate] {k}: {len(v)} hit(s)" + (f" e.g. {v[:5]}" if v else ""))
    log(f"[gate] G12 reference set loaded: {hits.get('_g12_reference_loaded', 0)} value(s) (from the facts file outside the repositories; 0 means shapes only)")
    log(f"[gate] G13 allowlist: {hits.get('_g13_allowlist_entries', 0)} address/path binding(s) (from {G13_ALLOW_FILE}, outside the repositories; 0 means none may stand)")
    log(f"[gate] denylist literals checked: {hits['_denylist_literals']} · live env values censused (G8): {hits['_live_values'] if hits['_live_values'] is not None else 'NOT MEASURED (docker could not be asked)'} · circuit artifacts carried: {hits['_circuit_artifacts']}")
    bad = {k: v for k, v in hits.items() if not k.startswith("_") and v}
    if bad or hits["_denylist_literals"] == 0 or hits["_live_values"] is None:
        log("[export] REFUSED: the tree is not clean (or G1/G8 could not run); nothing is committed"); return 3
    # §TESTBED P5 (2026-09-19): the release's own file digests, so a kit build can say whether its tree differs from this
    # release (build.sh -> kit_provenance.py -> image labels and /health). Written after the gates (it holds only
    # digests and paths) and committed with the release; the kit is a git archive of that commit.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import kit_provenance
    log(f"[export] {kit_provenance.MANIFEST}: {kit_provenance.write_manifest(str(out))} file digests")
    if a.author or a.signoff or a.message:
        log(f"[export] commit identity: {author[0]} <{author[1]}>" + (", Signed-off-by" if a.signoff else "")
            + (", the message given" if a.message else ""))
    committed, why = commit_export(out, a.message or f"OSS export dry-run {out.name}: the curated release set from {source}, gated for secret absence (fresh history)",
                                   log, author=author, signoff=a.signoff)
    if not committed:
        log(f"[export] REFUSED: {why}"); return 3
    if a.push:
        tok = None
        # the file's shape was READ before this parser was written (a key part, a ':' separator, the value):
        # the api token line starts with `api_token` and the value is everything after the first separator
        for line in open("/root/.forgejo_admin.secret.txt"):
            key, sep, val = line.partition(":") if ":" in line else line.partition("=")
            if sep and key.strip().lower().startswith("api_token") and val.strip():
                tok = val.strip()
        if not tok:
            log("[push] REFUSED: no api_token line in the admin secret file"); return 4
        owner, repo = a.push.split("/", 1)
        import urllib.request, urllib.error
        req = urllib.request.Request(f"https://git.theprotocol.cloud/api/v1/repos/{owner}/{repo}", headers={"Authorization": f"token {tok}"})
        try:
            urllib.request.urlopen(req, timeout=20); log(f"[push] repo {a.push} exists")
        except urllib.error.HTTPError as e:
            if e.code != 404: raise
            body = json.dumps({"name": repo, "private": True, "default_branch": "main", "description": "OSS export DRY RUN (fresh history; private; deleted or kept on his word)"}).encode()
            req = urllib.request.Request(f"https://git.theprotocol.cloud/api/v1/orgs/{owner}/repos", data=body, method="POST", headers={"Authorization": f"token {tok}", "Content-Type": "application/json"})
            r = json.load(urllib.request.urlopen(req, timeout=30)); log(f"[push] created PRIVATE repo {a.push} (private={r.get('private')})")
        r2 = json.load(urllib.request.urlopen(urllib.request.Request(f"https://git.theprotocol.cloud/api/v1/repos/{owner}/{repo}", headers={"Authorization": f"token {tok}"}), timeout=20))
        if not r2.get("private"):
            log("[push] REFUSED: the target repo is not private"); return 4
        url = f"https://oauth2:{tok}@git.theprotocol.cloud/{owner}/{repo}.git"
        r = subprocess.run(["git", "push", "-q", url, f"main:{a.push_branch}", "--force"], cwd=out, capture_output=True, text=True)
        log(f"[push] rc={r.returncode} branch={a.push_branch} {'pushed' if r.returncode == 0 else r.stderr.replace(tok or 'x', '***')[-200:]}")
        return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
