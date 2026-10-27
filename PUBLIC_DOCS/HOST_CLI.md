<!-- GENERATED from AgentVault/agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/assets/docs/operator/12_host_cli.md by scripts/distribution/gen_public_docs.py. Edit that file, not this copy: the export refuses a copy that differs from its source. -->

# Operator Guide: The `tp` Host CLI
**Audience**: Federated and standalone registry operators (self-hosted), and frame operators (`--frame`)
**Prerequisite**: A running operator stack and its `.env.operator`, or a frame stack directory
**Checked against the source**: 2026-10-16 (`tools/operator-cli/`, CLI version 1.1.7); the commands that changed in
1.1.8 again 2026-10-22 (the frame kit 1.0.0-beta.22)

---

## 1. What It Is

`tp-operator` is a command-line tool for the machine that runs your stack. It acts on an operator stack (the
directory that holds `.env.operator` and its compose file) or, with `--frame`, on a frame stack directory. For the
local stack it drives `docker compose`: status, logs, restarts, backups, restores and updates. For federation tasks it
calls your parent frame: the licence, your agents' SPIRE entries, the network counts.

Two entry points run the same commands:

- **`tp-operator <command>`**: the operator CLI.
- **`tp operator <command>`**: the same commands under the umbrella binary `tp`, which adds `tp mcp` (section 8).
  Its `tp developer` and `tp admin` groups only answer `ping` and `version` so far.

The CLI runs a stack, it does not create one: the first run is still `./operator-setup.sh`, which writes
`.env.operator`.

**Install it from the source.** The CLI ships as source in the open-source release and in the frame kit, under
`tools/operator-cli/`. The operator bundle a frame hands you holds the compose file, the env generator and the SPIRE
and nginx files, not the CLI. With Python 3.11 or newer:

```bash
pip install ./tools/operator-cli        # installs the tp-operator and tp commands
tp-operator version
```

Or build the two single-file binaries with PyInstaller, on a machine of the architecture you will run them on
(PyInstaller does not cross-compile). `tp mcp serve` needs the `mcp` package: `requirements.txt` lists it, and an
installed CLI gets it with the `mcp` extra (`pip install './tools/operator-cli[mcp]'`):

```bash
cd tools/operator-cli
pip install -r requirements.txt pyinstaller
pyinstaller tp-operator.spec            # dist/tp-operator
pyinstaller tp.spec                     # dist/tp
install -m 0755 dist/tp-operator dist/tp /usr/local/bin/
```

---

## 2. Auth Model

The commands that call your parent frame read `FEDERATION_LICENSE_KEY` from `.env.operator` and send it as
`X-Federation-License`. There is no password prompt and no developer login. The parent is the first of
`CENTRAL_REGISTRY_URL` and `MAINFRAME_PROXY_URL` that your env sets, else `https://api.theprotocol.cloud`;
`TP_OPERATOR_MAINFRAME_URL` in the shell that runs the CLI overrides them.

`license verify` and `sync` make their call through your registry instead. The CLI runs it inside your registry
container (`docker compose exec`), which reaches the parent the way your registry reaches it for its own calls: over
the parent's mTLS federation lane, presenting your registry's certificate. The licence presented is the one in
`.env.operator`, handed to the container on its standard input and never on a command line. When your registry knows
no federation lane for its parent, the call goes to the parent URL above instead. Both need the registry container
running, on an image that has the federation lane (V0614 or later); on an older image they say so and fail.

Two things to know about the parent's side:

- **Some parent endpoints check no licence.** `/health`, `/api/v1/federation/info` and
  `/api/v1/federation/network-stats` are public, so an answer from them proves the parent is up, not that your
  licence is valid.
- **A frame built from the frame template clears the licence header on its public address.** That includes the
  production frames. The commands that carry the licence (`license verify`, `license rotate`, `spire enroll`,
  `spire revoke`) and `sync` therefore go over the federation lane, through your registry; only while your registry
  does not know the lane yet do they fall back to the parent URL, where that address answers 401.

The `bundle` commands (section 7) authenticate with a developer API key instead.

Most commands also append one JSON line to `~/.tp-operator/audit.log` (no secrets; rotated at 16 MB, four
generations kept). With `TP_OPERATOR_REMOTE_AUDIT=true` they post the same record to the parent's
`/api/v1/federation/cli-audit` as well, best effort.

---

## 3. Local Stack Operations

| Command | What it does |
|---------|-------------|
| `status [--detail]` | Runs `docker compose ps` and gives each service a verdict: red when it is not running or reports unhealthy, yellow while its health check is starting, green otherwise. The stack takes its worst service's verdict (red when there are no services). Exits 0, 1 or 2 for green, yellow or red. `--detail` adds each service's start time and restart count. |
| `health [--strict]` | Probes your parent frame's `/health`. `--include-federation` adds `/api/v1/federation/info`, `--include-eventstore` adds the parent's ledger reading (`/api/v1/public/supply-invariant`, green only when it reads `OK`), `--strict` adds both. Exits 0 or 2. |
| `logs <service> [--tail N] [-f] [--since ...]` | `docker compose logs` for one service, the last 100 lines unless `--tail` says otherwise. An operator stack's services are `registry`, `teg-layer`, `db`, `teg-db`, `redis`, `pgbouncer`, `nginx-federation`, `spire-agent` and `cert-writer`; a frame's are named `<frame>-registry`, `<frame>-teg` and so on. |
| `restart [<service>] [--apply-env-changes] [--no-wait]` | `docker compose restart` for one service, or for the whole stack when you name none. `--apply-env-changes` recreates instead, so edited env values take effect: a named service with `docker compose up -d --no-deps --no-build --force-recreate <service>` (never its dependencies), the whole stack with `docker compose up -d --force-recreate`. It then waits up to two minutes for the service (or every service) to be healthy and fails when it is not; `--no-wait` returns at once. |
| `start` / `stop` | `docker compose up -d` / `docker compose down`. |
| `doctor` | Reports the Docker daemon, the free disk in GB, how many services run, whether a licence is present and whether the parent's `/health` answers. Paste its output into a support ticket. With `--frame`, the frame checks of section 6a. Always exits 0. |
| `validate-config [--proposed PATH]` | Checks `.env.operator`, or a file you are about to use: twelve required keys (the ones `generate-operator-env.sh` writes), that `API_KEY_SECRET` equals `TEG_REGISTRY_JWT_SECRET`, leftover example mail values, and a licence set while `MINTING_AUTHORITY` is not `disabled`. Exits 0, 1 or 2 for pass, warn or fail. |
| `version` | Prints the CLI and schema versions, for example `tp-operator 1.1.8 (schema 1.0.0)`. |

`restart`, `start` and `stop` ask you to type `yes` unless you pass the global `--yes`. Every command that changes
the stack takes a per-stack lock, so two of them never run on one stack at once.

---

## 4. Federation Operations

| Command | What it does |
|---------|-------------|
| `peers` | Prints the parent frame's network counts from `/api/v1/federation/network-stats`: registries, agents (local, network-wide, active), paid services, the network health and the last global sync. It lists no individual peers. |
| `sync` | Asks your parent frame to run its federation sync cycle now: `POST /api/v1/federation/sync/trigger` through your registry, on the parent's federation lane, where the parent accepts your registry's certificate as a peer registry (it never accepts a licence for this). The parent then pulls the agent cards of its peers, yours among them. It runs at most one cycle every 30 seconds and refuses the others with 429. Exits 0 when the parent ran the cycle and 3 when it refused, printing its reason. Your registry's own sync still runs on its interval (`FEDERATION_SYNC_INTERVAL_SECONDS`). |
| `license show` | Prints the local summary from `.env.operator`: `OPERATOR_DID`, `FEDERATION_OPERATOR_DID`, whether a licence is set and its first 12 characters, the parent URL, and whether the stack counts as standalone. Never the whole key. |
| `license verify` | Asks your parent frame to check the licence in `.env.operator`. Through your registry, on the parent's federation lane, it reads the last lines of your registry's own log (`GET /api/v1/federation/operator-self/logs`), a route that checks the licence before it answers anything. VERIFIED only when the parent found the licence active. A revoked, suspended or unknown key (403), a licence the parent never received (401), a licence no operator of the parent holds (404) and no answer at all are UNVERIFIED, with the parent's reason. Exits 2 unless verified, and when no licence is set. |
| `license rotate [--reason ...]` | Asks the parent for a new key (`POST /api/v1/federation/license/rotate-self`) once you type `CONFIRM-ROTATE`. Reasons: `leak_suspected`, `scheduled_rotation` (the default) or `post_incident`. The old key stops working at once. The CLI writes the new key into `.env.operator` and keeps the old file beside it as `.env.operator.bak-pre-rotate-<time>`; run `restart --apply-env-changes` so the registry and the TEG start with the new key. The parent must allow self-service rotation (`FEDERATION_LICENSE_ROTATE_SELF_ENABLED`, off by default, else 503), and the header limit of section 2 applies. |

---

## 5. Agent mTLS (`spire`)

Your agents' SPIRE entries (the IRONHAND agent identities) live on your parent frame's SPIRE server. These commands
ask the parent to manage them:

| Command | What it does |
|---------|-------------|
| `spire list` | Prints the parent's list of revoked identities (`GET /api/v1/agent/revoked-identities`). Despite its name it does not list your enrolled agents. |
| `spire enroll <agent-did> [--parent-fingerprint FP]` | Asks the parent to create the agent's SPIRE entry under your SPIRE agent (`POST /api/v1/federation/ironhand/register-agent-proxy`, through your registry on the federation lane) and prints the agent's SPIFFE ID. The fingerprint comes from `--parent-fingerprint` or `OPERATOR_SPIRE_AGENT_FINGERPRINT` in `.env.operator`; the CLI refuses without one. The parent refuses for an agent of its own. |
| `spire revoke <agent-did>` | Asks the parent to delete that entry (`POST /api/v1/federation/ironhand/delete-agent-proxy`, the same way) once you type `yes`. A certificate already issued stays valid until it expires, at most 30 minutes later. |

`enroll` and `revoke` carry the licence over the federation lane (section 2), and any answer but 200 exits 3 with the
parent's reason. An agent usually enrolls through its own registry instead (`POST /api/v1/agent/enable-mtls`), which
reaches the parent the same way.

---

## 6. Disaster Recovery & Updates

**`backup [--out PATH]`** writes one archive, by default `./operator-backup-<name>-<time>.tar.gz`:

- `.env.operator`, the `spire/` and `nginx/` directories, and `pgbouncer.ini`, `userlist.txt`, the compose files and
  `VERSION` where present;
- `pg_dump -Fc` dumps of the registry database and the TEG database;
- `MANIFEST.json`, with a SHA-256 for every entry.

A failed dump fails the backup: no archive is written without both dumps. The archive holds `.env.operator`, so it is
written at mode 600, beside its name first and then renamed, and an interrupted run never leaves a partial archive
under that name. It is a federated operator's
shape, whose ledger lives at its parent frame: a standalone stack's own event store database (`es-db`) is not in it.
Dump that one yourself, for example
`docker compose -f docker-compose.standalone.yml --env-file .env.operator exec -T es-db pg_dump -U eventstore -Fc event_store > event_store.dump`.
`--include-volumes` changes nothing for an operator.

**`restore <archive>`** asks you to type `CONFIRM-RESTORE` (or takes `--yes`), then:

1. checks every SHA-256 in the manifest;
2. refuses an archive whose operator DID is not yours (`OPERATOR_DID`), unless `--force-cross-operator`;
3. takes a pre-restore backup into the stack directory (`pre-restore-<time>.tar.gz`);
4. runs `docker compose down` and puts back `.env.operator`, the configuration files, `spire/` and `nginx/`;
5. starts the two databases, restores both dumps (`pg_restore --clean --if-exists --no-owner`) and brings the stack up.

It does not wait for the registry's health: run `status` afterwards. `--rebuild-volumes` and `--skip-env-restore`
are accepted and change nothing.

**`update`** checks for a new release (the default, `--check-only`), schedules one, or applies one:

- **Check.** The CLI reads the signed release channel (`RELEASE_CHANNEL_URL`, default
  `https://theprotocol.cloud/downloads/frame-kit/latest.json`), verifies its Ed25519 signature against the key it
  carries (`RELEASE_CHANNEL_PUBKEY_B64` overrides it), and compares the releases with your version: the `VERSION`
  file in the stack directory, else the `VERSION=` line of `.env.operator`. A document that is not published, not
  signed or altered reads as an unavailable channel, and nothing else happens; until a release is published there,
  that is what the check reports.
- **Schedule.** `--schedule <ISO 8601 time>` creates a transient systemd timer (`tp-update-<name>`) that runs
  `--yes update --apply --to-version <version>` at that time; `--cancel-schedule` removes it. It needs `systemd-run`.
- **Apply.** `--apply [--to-version X] [--allow-major] [--no-auto-rollback]` asks you to type `CONFIRM-UPDATE`,
  refuses a change of major version without `--allow-major` and a version the verified channel does not list, takes
  a pre-update backup (`pre-update-<time>.tar.gz`), pulls the release's images by the digests the channel names and
  tags them on this host, writes the release into `.env.operator` (`VERSION`, the image prefix, and `IMAGE_TAG` where
  the file has one), runs `docker compose up -d --remove-orphans`, and waits up to two minutes for every service to
  run (and be healthy where it has a health check). If they do not, it restores the pre-update backup,
  `.env.operator` included, unless you passed `--no-auto-rollback`. Only on success does it write the target
  version into the `VERSION` file.

Without a verified channel, `--to-version` is a tag you vouch for: a local build of that tag is used as it is,
anything else is pulled by that tag. A frame updates with the kit's `frame-update.py` instead (operator chapter 16),
which pulls by digest too.

### 6a. Frames (`--frame <stack dir>`)

`--frame` points a command at a **frame** instead of an operator: a stack directory the frame standup built, holding
`.env.frame-test`, `docker-compose.frame-test.yml` and the standup's run record `hetzner-demo-run.json`, which names
the frame. A directory missing any of the three is refused with a sentence naming what is missing. The kit's
`frame-up.py` prints the directory it created (`<stack root>/<frame>-<timestamp>`). `--frame` is a global flag, so it
goes before the command: `tp-operator --frame /opt/theprotocol/stack/my-frame-1790000000 doctor`.

**`backup`** writes one archive with mode 600, because it carries the frame's secrets (by default
`./frame-backup-<frame>-<time>.tar.gz`):

- the stack directory (backup and temporary files skipped);
- three `pg_dump -Fc` dumps: the registry, the TEG and the **event store**, which is the frame's ledger;
- the two named volumes that hold the frame's identity: the registry's signing key and the SPIRE server's data (a new
  CA would be a new trust root for every federated peer);
- `MANIFEST.json`, with a SHA-256 for every entry and each database's migration head.

A frame whose env and containers name fewer than three databases, or whose compose names neither volume, is refused
rather than half backed up. When only one of the two volumes exists, the backup goes ahead and warns that the missing
state is not in the archive. `--include-volumes` is implied for frames.

**`restore <archive>`** replaces the frame's three databases and two volumes, and refuses before touching anything
when the archive does not fit:

1. verifies every SHA-256 in the manifest, and that the archive is a frame backup;
2. refuses an archive whose trust domain is not this frame's, unless `--force-cross-frame`;
3. refuses a frame whose standup declared it production, unless `--i-mean-production`;
4. takes a pre-restore backup of the frame as it is (`pre-restore-<time>.tar.gz` in the stack directory);
5. stops the registry, TEG, event store, pgbouncer, cert-writer, SPIRE agent and SPIRE server;
6. restores the event store first, then the TEG, then the registry, each in one transaction;
7. replaces the two volumes, starts the stack and waits up to seven minutes for the registry's `/health`.

It asks you to type `CONFIRM-RESTORE` unless the global `--yes` is set.

**`doctor`** runs read-only checks and gives each row a verdict: `ok`, `warn` or `fail`, or `not-measured` when the
probe could not decide. The run's verdict is `fail` if any row fails, else `warn` if any row warns, else `ok`; a
`not-measured` row changes neither, so read those rows yourself. The command exits 0 either way, so scripts read
`.verdict` from `--json`. The checks reach the registry on the loopback port the standup publishes; without one the
run stops after `registry-health`.

| Row | What it asks |
|-----|--------------|
| `docker-daemon`, `disk-free-gb`, `services-running` | the host and the stack (less than 60 GB free warns) |
| `posture` | the frame's declared environment and trust domain |
| `registry-health`, `public-rails` | `/health`, and five public reads that must answer 200 |
| `card-version` | the signed registry card's version against the version inside the running image |
| `policy-hash` | the card's policy hash against the compliance endpoint's (it may sign in with the frame admin credential named in the stack's env to read it) |
| `limiter-posture` | the rate limit an outside caller meets: 1200 on a production frame, bypassed on a sandbox frame |
| `xff-appended-element` | that the registry logs the address the proxy appends to `X-Forwarded-For`, not the one the caller wrote |
| `supply-delta` | the event store's supply audit: delta 0 and status OK |
| `auditor-verdict` | the independent auditor's verdict for this frame (`TP_AUDITOR_URL`, default `http://127.0.0.1:8045`: point it at your frame's auditor) |
| `replication` | cross-frame peers and foreign events in the ledger (none: standalone, or not yet federated) |
| `scrape-targets` | that Prometheus scrapes the frame's registry, TEG and event store (`TP_PROMETHEUS_URL`, default `http://127.0.0.1:9090`) |
| `status-history` | that the public status page has a metrics job and known days for every own component |
| `bundle-roots` | how many trust roots the registry's SVID bundle holds (the watcher's first poll comes 30 minutes after boot; earlier reads say `not-measured`) |
| `observability-env` | that `PROMETHEUS_URL` and `VICTORIA_METRICS_URL` are set |

---

## 7. Agent Bundles (`bundle`)

The commands for signed `.tpb` agent bundles authenticate with a developer API key, not the licence: `--api-key`,
else `TP_BUNDLE_API_KEY`, else the file `registry-auth/.api-key` in the stack directory. They call your stack's own
registry, where your developers and agents live (`TP_OPERATOR_REGISTRY_URL`, else the host port your compose
publishes the registry on), so the key must be one issued there; an `https` address is verified.

```
bundle list [--kind snapshot|template|migration] [--no-official]
bundle create --agent-did <did> [--agent-did <did> ...] [--kind snapshot|template|migration]
              [--name ...] [--description ...] [--visibility private|org|public] [--no-cicd] [--no-sign] [--out file.tpb]
bundle download <bundle-id> [--out file.tpb]
bundle restore <file.tpb> [--conflict skip|rename|overwrite] [--mode copy|mirror] [--no-cicd] [--idempotency-key KEY]
bundle verify <file.tpb>
bundle quota <developer-id>        # an admin's key
```

The defaults: `create` makes a private, signed snapshot with CI/CD pipelines included; `download` writes
`./bundle.tpb`; `restore` renames on conflict and copies, and prints each restored agent's `client_secret` once.
`bundle verify` runs offline: it checks the file's structure (a `manifest.json`, a `README.md`, at least one agent
file), prints the signature's header and, for a signed bundle, checks that the manifest and the agent files are the
ones the signature covers, so a file changed after signing fails. It does not check the signature itself, which
needs the signer's public key, and says so. `--dry-run` prints what `create`, `restore` and `download` would do
instead of doing it.

---

## 8. MCP Server Mode

`tp mcp serve [--operator NAME] [--log-file PATH]` runs a stdio MCP server named `tp-host-cli`, so an MCP client
such as Claude Code can run your host operations. It exposes 21 tools in three tiers:

- **Read-only** (10): `tp_status`, `tp_health`, `tp_logs`, `tp_peers`, `tp_doctor`, `tp_validate_config`,
  `tp_version`, `tp_license_show`, `tp_license_verify`, `tp_spire_list`.
- **Changing, run with `--yes`** (8): `tp_sync`, `tp_spire_enroll`, `tp_spire_revoke`, `tp_start`, `tp_stop`,
  `tp_restart`, `tp_backup`, `tp_update_check`.
- **Destructive, refused unless the call carries `confirm: true`** (3): `tp_update_apply`, `tp_license_rotate`,
  `tp_restore`.

Each call runs `tp operator --json ... <command>` as a subprocess (60 seconds for a read-only tool, 300 for the
others) and returns its JSON. The server finds the `tp` binary through `TP_BIN`, then `/usr/local/bin/tp`, then the
`PATH`. `tp_backup` and `tp_restore` also take a `frame` argument (a frame stack directory) for the frame backup and
restore of section 6a; `tp_restore` cannot pass `--force-cross-frame` or `--i-mean-production`, so it never restores
over a production frame. `tp mcp tools` lists the tools, `tp mcp version` prints the version and the tool counts.
To wire it into a client, see operator chapter 13.

---

## 9. Global Flags

Global flags belong to `tp-operator` itself, so they go **before** the command (`tp-operator --json status`, not
`tp-operator status --json`). Under the umbrella binary they follow `operator`: `tp operator --json status`.

```
--config PATH         the .env.operator to use
--operator NAME       an operator directory by name (see below)
--frame PATH          a frame stack directory instead of an operator (section 6a)
--all-operators       every operator directory the CLI discovers
--json                JSON output (also the default when CI, GITHUB_ACTIONS or GITLAB_CI is true, or TP_OPERATOR_JSON=1)
--quiet               plain text without colour; it does not silence the output
--no-color            plain text without colour
--yes / -y            answer the confirmation prompts
--dry-run             print what a changing command would do, and stop (restore and update --apply
                      still ask first; the bundle commands ignore it)
--timeout SECONDS     accepted but not used: each command has its own fixed HTTP timeout
--verbose / -v        accepted but not used
--version             print the CLI version and exit
```

Without `--config`, `--operator` or `--frame`, a command takes `$TP_OPERATOR_HOME/.env.operator`, else
`./.env.operator`, else the one operator directory it discovers under `/opt/theprotocol/stack` (`cloud-op-*`); with
several it asks for `--operator` or `--all-operators`. `--operator` accepts a name, `op-<name>`, the directory name or
an absolute path, and also matches the `REGISTRY_NAME` in each discovered env.

Tab completion: `tp-operator --install-completion`, or `tp-operator --show-completion` to print the script for your
shell.

---

## 10. Exit Codes

| Code | When |
|------|------|
| 0 | Success. `doctor`, `peers` and `update --check-only` always exit 0: read their JSON. |
| 1 | `status` found a service starting (yellow); `validate-config` found a warning; the stack could not be found or is locked by another command; a Docker Compose step failed; an update failed its health check and was rolled back |
| 2 | `status` found a service down or unhealthy (red); `health` found a probe failing; `validate-config` found a failure; `license verify` did not verify; you declined a `restore`, `update`, `license rotate` or `spire revoke` confirmation; the CLI refused a backup or restore; a rollback failed; a `bundle` request was refused; a usage error |
| 3 | The parent refused a licence rotation, a SPIRE call or a `sync` |
| 4 | No `FEDERATION_LICENSE_KEY` for a licence rotation |
| 5 | Docker unreachable, or `update --schedule` without `systemd-run` |
| 6 | `docker compose pull` failed during `update --apply` |
| 130 | `logs` interrupted (Ctrl-C) |

---

## 11. Where `tp` comes from, and the runner beside it

`tp` lives in the source release at `tools/operator-cli/`: the `tp_operator` package, the two entry points
`tp_cli.py` and `tp_operator_cli.py`, a `pyproject.toml` and the PyInstaller specs that build the two binaries
(section 1).

Beside it, `tools/frame-runner/` is the host service that Frame Management provisions frames through (operator
chapter 11): a root service on a local unix socket with a closed set of operations. Its policy file
(`frame-runner.json.example` ships; the service reads `/etc/theprotocol/frame-runner.json` at start) has an `images`
block that allowlists, by tag, every image a runner-built frame may use: `registry`, `teg`, `event_store`, `auditor`
and `directory`. A request must name an allowlisted registry and TEG image; one that names no event store image gets
the first `event_store` entry, and the first `auditor` and `directory` entries are always the ones used. Name each
entry by an explicit version tag, never `:latest`: a tag is a name, an allowlist entry is a decision.

## 12. Cron One-Liners

cron starts in your home directory, so name the stack with `--config` (or `--operator`).

```bash
# Daily 03:00 backup (the archive holds .env.operator: keep it private)
0 3 * * * umask 077; tp-operator --config /srv/my-operator/.env.operator backup --out /opt/backups/$(date +\%Y\%m\%d).tar.gz

# Daily 03:30 backup of a frame (the archive is written with mode 600)
30 3 * * * tp-operator --frame /opt/theprotocol/stack/my-frame-1790000000 backup --out /opt/backups/frame-$(date +\%Y\%m\%d).tar.gz

# Every 5 min: alert when the stack is not green
*/5 * * * * tp-operator --config /srv/my-operator/.env.operator --json status | jq -e '.verdict == "green"' || /usr/local/bin/alert.sh

# Weekly: tell me when a release is out
0 9 * * 1 tp-operator --config /srv/my-operator/.env.operator --json update | jq -e '.update_available' && /usr/local/bin/notify.sh
```
