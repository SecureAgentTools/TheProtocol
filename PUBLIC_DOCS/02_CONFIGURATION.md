<!-- GENERATED from AgentVault/agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/assets/docs/operator/02_configuration.md by scripts/distribution/gen_public_docs.py. Edit that file, not this copy: the export refuses a copy that differs from its source. -->

# Configuration: Environment Variable Reference

**Audience**: anyone who runs a registry and changes its settings
**Checked against the source**: 2026-10-16 (the registry's `config.py` and its `os.getenv` reads, the TEG's settings, the
event store; the frame kit 1.0.0-beta.20: both `generate-operator-env.sh`, the operator and standalone composes and the
frame template `templates/frame-test/frame-test.env.tmpl`); the two generators, the values the kit writes and the
template at the end again 2026-10-22 (the frame kit 1.0.0-beta.22)

Each table gives the **code default** (what the software does when the variable is unset) and, where the kit writes a
different value, that value too. Values marked **secret** are credentials: keep them out of version control, chat and
screenshots.

**Where the values live.** A standalone registry reads `scripts/distribution/.env.operator`. A cloud operator's
`.env.operator` is written by its frame when the frame provisions it, on the frame's host: the frame-scope switches
follow the frame, and the operator-scope switches are the ones chosen in the application. A frame reads
`<stack>/.env.frame-test`, written by `frame-up.py`: a line named `FT_REG_<NAME>` is a value the frame's compose maps into
the registry's environment, and any other line reaches the registry through the env file. In every compose a value
written in `environment:` beats the env file, and a changed value takes effect when the container is recreated:

```bash
docker compose -f <compose file> --env-file <env file> up -d --no-deps --force-recreate <service>
```

**Reading a registry's switches without a shell**: `GET /api/v1/public/env-catalog` lists every switch of the
configuration catalog with its options, its scope (`operator` or `frame`) and this registry's current option, and says
whether that option was set or is the code default. `GET /api/v1/public/registry-config` gives the switches the console
reads (`staking_enabled`, `fiat_onramp_enabled`, `genesis_grant_amount` and others).

---

## Generating Your Environment File

On a standalone registry, `operator-setup.sh` writes the file for you:

```bash
./operator-setup.sh <registry-name> standalone
```

It asks before it overwrites an existing `.env.operator`, then runs `generate-operator-env.sh <registry-name>`, which
writes `.env.operator` in the current directory at mode 600 and keeps standard output empty (its progress goes to
standard error). You can run the generator yourself: `./generate-operator-env.sh <registry-name>`; the older form with
`> .env.operator` leaves the same file. The file carries secrets: never commit it.

The generator writes:

- `REGISTRY_NAME`, and an `OPERATOR_DID` of the form `did:theprotocol:operator-<16 hex characters>`
- three database passwords (48 hex characters each)
- the registry's signing secret and the TEG's keys (64 hex characters each), the event store's internal key, and the
  ledger broker's password and record key
- `ALLOWED_ORIGINS=["http://localhost:8000"]` and a random `FEDERATION_HEALTH_CHECK_SECRET`, the two values the
  registry's production checks ask of a standalone registry once `BASE_URL` is public (put your address in the list)
- the switches listed in the template at the end of this page

An operator bundle carries a different generator, the one the frame's provisioner runs: it writes `.env.operator`,
`pgbouncer.ini` and `userlist.txt` itself, in the current directory, with matching database passwords. Under an
operator name that does not start with `cloud-op-`, it also writes the operator's Redis passwords and proxy trust
secrets, `redis-users.acl` and the markers in the two terminator configurations; a cloud operator's frame writes those
itself. Like the standalone generator, it keeps standard output empty.

---

## Environment Variables by Category

### Identity

| Variable | Code default | Kit | Description |
|----------|--------------|-----|-------------|
| `REGISTRY_NAME` | `AgentVault Registry` | the name you give the generator | The prefix of every container name (`<name>-registry`), the slug of the first admin's address (`admin@<name>.dev`) and the registry's own name. |
| `OPERATOR_DID` | unset | `did:theprotocol:operator-<hex>` | A non-empty value marks the registry as a cloud operator for its licence handling: it asks its frame for its licence and shows it on its card. The standalone generator writes one as well, though a standalone registry has no frame to ask. |
| `TRUST_DOMAIN` | unset | `<name>.local` | Standalone compose only: passed to the registry as `SPIRE_TRUST_DOMAIN` and `DID_ISSUER_NAMESPACE` (`operator.local` when unset). The registry signs its card under it and issues its agents' DIDs under it. Set your DNS name; `.local` suits a local trial only. |
| `DID_ISSUER_NAMESPACE` | unset | a frame: its trust domain | The namespace in new agent DIDs (`did:theprotocol:<namespace>:<uuid>`; unset, `did:theprotocol:<uuid>`). A registry whose namespace is not its `SPIRE_TRUST_DOMAIN` refuses to start. |
| `FIRST_ADMIN_EMAIL`, `FIRST_ADMIN_PASSWORD`, `FIRST_ADMIN_NAME` | unset | not written | The first admin the registry creates on its first start. Unset: `admin@<name>.dev` with a random password printed once to the log. The password is a **secret**. |

### Images and Host Port

| Variable | Default | Description |
|----------|---------|-------------|
| `IMAGE_REGISTRY` | `theprotocol` | The prefix of the application images in the standalone compose, and the prefix `build.sh` tags with. `theprotocol` is a local name, so the default runs what you built. |
| `IMAGES_PREFIX` | `images.theprotocol.cloud` | The same prefix in the operator compose. The frame's provisioner writes the frame's own image host, or the local prefix of a frame whose images are local tags. |
| `VERSION` | `stable` | The image tag, in both composes. `build.sh` tags every build with the kit's version, `latest` and `stable`; the provisioner writes the version its frame runs. |
| `REGISTRY_HTTP_PORT` | `8000` | Standalone compose: the host port of the registry's plain HTTP. The container still listens on 8000. |

The generator writes none of these; add them to `.env.operator` only to change a default.

### Database Passwords

| Variable | Generated | Description |
|----------|-----------|-------------|
| `PG_PASS_REGISTRY` | 48 hex characters | **Secret.** The registry database's password. |
| `PG_PASS_TEG` | 48 hex characters | **Secret.** The TEG database's password. |
| `PG_PASS_EVENT_STORE` | 48 hex characters | **Secret.** The event store database's password (standalone only). |

PostgreSQL takes a password when it first creates its data directory. Changing one later means changing it inside the
database as well (and, on an operator, in `pgbouncer.ini` and `userlist.txt`), or recreating the volume.

### Security Keys

Services authenticate to each other by certificate wherever the stack has an identity fabric: an operator's and a
frame's containers hold SPIFFE SVIDs that SPIRE renews, and their gateways verify them. The generated keys that still
matter:

| Variable | Generated | Description |
|----------|-----------|-------------|
| `API_KEY_SECRET` | 64 hex characters | **Secret.** Signs every JWT the registry issues: developer and agent access tokens, refresh tokens and the partial token of a two-factor login. API keys do not depend on it: they are random and stored hashed. In production the registry refuses a value containing `test`, `example`, `demo` or `sample`. |
| `TEG_REGISTRY_JWT_SECRET` | the same value as `API_KEY_SECRET` | **Secret.** The composes pass it to the TEG (as `REGISTRY_SERVICE_TOKEN`). Keep it equal to `API_KEY_SECRET` and rotate the two together. |
| `TEG_TOKEN_SIGNING_KEY` | 64 hex characters | **Secret.** Signs the TEG's own access tokens. Required: the TEG refuses to start without a value of at least 32 characters. |
| `TEG_AVTP_SYSTEM_API_KEY` | 64 hex characters | **Secret.** The TEG's system key (`AVTP_SYSTEM_API_KEY` inside the TEG). Required, at least 32 characters. |
| `TEG_ADMIN_API_KEY` | 64 hex characters | **Secret.** On a standalone registry, how the registry authenticates its admin calls to the TEG (treasury, enforcement), which travel over the stack's private network. On an operator or a frame the TEG takes internal callers by SVID only (`TEG_MTLS_REQUIRED=true`) and does not consult the key. |
| `EVENT_STORE_INTERNAL_API_KEY` | 64 hex characters | **Secret.** Standalone only: the registry, the TEG and the auditor present it to their own event store. The operator compose carries no store key: an operator writes to its frame's ledger with its SVID. |

`SECRET_KEY` and `JWT_SECRET_KEY` are still generated and passed to the registry, which reads neither.

### Federation

| Variable | Code default | Kit | Description |
|----------|--------------|-----|-------------|
| `EVENT_STORE_URL` | `http://localhost:8200` | operator: the frame's ledger gateway; standalone: `http://event-store:8200` | Where the registry writes its events. The provisioner writes the frame's own gateway into an operator's compose. |
| `FEDERATION_LICENSE_KEY` | unset | written by the provisioner, or by `frame-federate.py` on a frame | **Secret.** The licence this registry holds from its frame or network. It rides the calls a licence authorizes: an operator's self-service calls to its frame (logs, restart, agent mTLS enrollment), federation sync and cross-registry transfers. |
| `FEDERATION_SYNC_INTERVAL_SECONDS` | `600` | `30` | Seconds between federation sync cycles. Lower means fresher peer data and more traffic. |
| `FEDERATION_REQUIRE_PEER_SPIFFE_BIND` | `false` | `true` (operator compose and frame template) | A federation caller's SPIFFE ID must be bound to an active peer row. |
| `BILATERAL_PEER_URL` | unset | written by the provisioner | The federation address the signed card publishes for peers to dial, such as `https://<host>:8443`. |
| `FEDERATION_BASE_URL` | unset | `https://nginx-federation:8443` | The stack's own federation terminator, an internal address. Leave it unless you change the terminator. |
| `CROSS_TEG_ENABLED` (TEG) | `false` | `true` on operators and frames | The TEG's cross-registry transfers. |
| `ALLOWED_ORIGINS` | `["*"]` | a frame: its console; standalone: `["http://localhost:8000"]` | Browser origins added to the CORS allowlist. The allowlist is otherwise derived every 60 seconds from this registry's own addresses and every active peer's console. With a public `BASE_URL`, the registry refuses to start while this is the wildcard. |
| `CORS_ALLOW_ALL_ORIGINS` | `false` | not written | `true` answers every origin (without credentials). Peers' consoles need no wildcard: they are on the derived allowlist. |
| `EVENTSTORE_MTLS_REQUIRED` (event store) | `true` | a frame: `true` | The event store's own switch: writes need mutual TLS through the frame's terminator, and a federation licence header is refused. On an operator's registry it changes nothing; the frame's store enforces it. |
| `EVENTSTORE_INTERNAL_KEY_WRITES` (event store) | unset | the standalone compose: `allow` | `allow` lets the internal key write to the store while mutual TLS is required. A standalone stack needs it (chapter 00): its store has no TLS terminator in front of it. |

The registry reads neither `KAFKA_ENABLED` nor `KAFKA_BOOTSTRAP_SERVERS`: it writes its events to the event store over
HTTPS, and only the event store talks to the ledger's broker. The generators still write both; they are harmless. The
same holds for `EVENT_STORE_ENABLED`, which the provisioner and the frame template write and nothing reads.

### Units and Fees

| Variable | Code default | Kit | Description |
|----------|--------------|-----|-------------|
| `FRAME_CURRENCY` | unset: the code's historical default, `FRAME_CURRENCY=AVT` | a frame: its `--ticker`; an operator: its frame's | The unit's ticker on the card, the console, mails and messages. A standalone registry should set its own. |
| `MINTING_AUTHORITY` | TEG: `teg-layer-a` | operator: `disabled`; standalone and frame: `teg-layer` | The TEG issues only when this equals its `TEG_ID`. The registry also reads `disabled` as "this registry is a cloud operator". |
| `TEG_ID` (TEG) | `teg-layer-a` | standalone and frame: `teg-layer` | This TEG's identifier. |
| `GENESIS_GRANT_ENABLED` | `true` | `true` | A developer's first agent receives a starting grant on creation, paid from the registry's own accounts. Later agents report `not_first_agent`. |
| `GENESIS_GRANT_AMOUNT` | `1000.0` | `5000.0` (both generators and the operator compose); a frame: `1000.0`; a provisioned operator: its frame's amount | The grant, in the registry's unit. Read only while `GENESIS_GRANT_ENABLED` is true: with the grant off, a changed amount has no effect and nothing reports it. |
| `NETWORK_PROFILE` | unset | a frame: `lowsupply-2026` | A file of money amounts (the reputation bond, the treasury floor below which genesis grants wait, the issuance and transfer caps, an operator's starting treasury). A value set in the environment wins over the profile. |
| `DEFAULT_FEE_RATE`, `MAX_FEE_RATE` | unset | not written (kits up to 1.0.0-beta.20 wrote `0.5`, `5.0`) | No service reads them; an older `.env.operator` may still carry them. Fees come from the frame policy document (`transaction_fees.*`), and the signed registry card (`/.well-known/registry-card.json`) states the rates in force. |
| `VELOCITY_SNAPSHOT_INTERVAL_SECONDS` | `3600` | unset | How often the registry computes each sender's velocity index for the last completed hour (the Dynamic Fee in chapter 04). |
| `VELOCITY_MIN_ACTIVE_SENDERS` | `10` | unset | Below this many senders in an hour every velocity index is 0, so every transfer pays the base rate. |
| `VELOCITY_BASELINE_MIN_VOLUME` | `100` | unset | The least baseline, in the registry's unit: the median of an hour's volumes counts as at least this much. |
| `VELOCITY_SATURATION_RATIO` | `100` | unset | How many times the baseline a sender must move in an hour to reach index 1, the maximum rate. |

### Email (SMTP)

| Variable | Code default | Kit | Description |
|----------|--------------|-----|-------------|
| `MAIL_SERVER` | unset | `smtp.example.com` | The SMTP host. The kit's value is a placeholder: pick a mail posture (below) before real users register. |
| `MAIL_PORT` | `587` | `587` | 587 for STARTTLS, 465 for TLS. |
| `MAIL_USERNAME` | unset | `noreply@example.com` | The SMTP login. |
| `MAIL_PASSWORD` | unset | `CHANGE_ME` | **Secret.** The SMTP password. |
| `MAIL_FROM` | unset | `noreply@example.com` | The sender address. |
| `MAIL_FROM_NAME` | `TheProtocol` | the registry name | The sender's display name. |
| `MAIL_STARTTLS` / `MAIL_SSL_TLS` | `True` / `False` | same | For port 465 set `MAIL_SSL_TLS=True` and `MAIL_STARTTLS=False`. |
| `MAIL_DISABLED` | `false` | not written | Declares that this registry sends no mail: every send is logged and skipped. In production it cannot stand beside a configured SMTP account. |
| `MAIL_RELAY_PARENT_URL`, `MAIL_RELAY_LICENSE` | unset | not written | The relay posture: the parent sends verification and password-reset mail for this registry (**secret** licence). |
| `PUBLIC_UI_URL` | unset | written by the provisioner and the frame template | The console a person uses, such as `https://registry.example.org`. |

Mail carries account verification, password resets and notifications. The addresses involved are easy to confuse:

| Variable | Answers | Used for |
|----------|---------|----------|
| `BASE_URL` | where this registry's API is, as an outside caller types it (code default `http://localhost:8000`) | API links; a value that is not `localhost` switches on the production checks |
| `PUBLIC_URL` | the registry's public web address | the address on its card |
| `PUBLIC_UI_URL` | the console a **person** uses | every link a person follows: verification, password reset, the console link, invitations |
| `BILATERAL_PEER_URL` | the federation lane | what peers dial |

A link a person follows uses `PUBLIC_UI_URL`, else the origin of `BASE_URL` or `PUBLIC_URL`; loopback values never count.
With none of them set, a mailed link falls back to the raw `BASE_URL`, which names `localhost`: set `PUBLIC_UI_URL` or
`BASE_URL` before anyone else registers.

::: warn Sessions are per host
A link that lands someone on a different host name than the one they registered on signs them in there. Back on the
site they typed, they are signed out, which reads as "the link did not work". Point `PUBLIC_UI_URL` at the console
people use.
:::

**Pick exactly one of three mail postures.** The one broken combination is a registry that demands verification and
cannot send it: every self-registered account is then locked out until an admin verifies it by hand.

1. **direct**: real SMTP settings above, `REQUIRE_EMAIL_VERIFICATION=true`. The normal choice.
2. **relay**: no SMTP credential of your own; the parent frame sends verification and password-reset mail through
   `MAIL_RELAY_PARENT_URL` and `MAIL_RELAY_LICENSE` (the parent must accept relays). Other mail is skipped in this
   posture.
3. **none**: `MAIL_DISABLED=true` with `MAIL_USERNAME` left empty, `REQUIRE_EMAIL_VERIFICATION=false` and
   `BETA_INVITE_REQUIRED=true`. With verification off, invite codes are the remaining gate; never run with neither.

### Monitoring

| Variable | Default | Description |
|----------|---------|-------------|
| `GRAFANA_ADMIN_PASSWORD` | generated (32 hex characters) | **Secret.** Required by `docker-compose.monitoring.yml`, which refuses to start Grafana without it. |
| `PROMETHEUS_HTTP_PORT`, `ALERTMANAGER_HTTP_PORT`, `GRAFANA_HTTP_PORT` | `9090`, `9093`, `3000` | The monitoring compose's host ports, on loopback only. |
| `AUDITOR_HTTP_PORT` | `8045` | The standalone auditor's host port, on loopback only. |
| `METRICS_ENABLED` | `true` | Whether the registry serves `GET /metrics`. `false` (or `0`, `no`, `off`) removes the route: it answers `404` to everyone, your own Prometheus included (chapter 06). |
| `PROMETHEUS_URL` | `http://agentvault-prometheus:9090` | Where the registry's status page reads per-day availability. The default is a container name the kit does not use: beside the kit's monitoring compose set `http://prometheus:9090`. Unreachable means no history bars. |

### Feature Flags

| Variable | Code default | Kit | Description |
|----------|--------------|-----|-------------|
| `BETA_INVITE_REQUIRED` | `false` | `false` | Registration requires an invite code. |
| `ENABLE_PROJECTION_SNAPSHOTS` | off | `true` | Allows `POST /api/v1/admin/projection-snapshot`, which posts the TEG's balances to the ledger as a baseline. |
| `AUDITED_BALANCE_ENABLED` (TEG) | `true` | `true` | Before a transfer, the TEG refuses an account whose balance differs from its audited copy. |
| `COCKPIT_DESK_ENABLED` | `false` | a frame: `true` | The arrangeable operator desk. Off, the desk's route and its menu entry are gone. |
| `SPAWN_WALLET_ANCHOR_MODE` | `off` | a frame: `on` | `on`: a spawned child agent holds no wallet and spends its parent's. |
| `STATUS_DATA_DIR` | `/app/data` | | Where the public status page keeps its incidents and uptime rollup. The operator compose mounts a volume there; the standalone compose does not, so a standalone registry's status history resets when its container is recreated. |
| `RELEASE_CHANNEL_CHECK_ENABLED` | `false` | a frame: `true` | Reads the signed release channel every 6 hours and tells the admins once when a newer release is out (chapter 16). |

### Agent Authorization, Liability and Policy

These decide what agents may do and who answers for it. Each code default is the setting that changes nothing; a frame
the kit stands up starts with most of them on. Turn them on deliberately, and read the chapter before you do.

| Variable | Code default | Kit frame | Description |
|----------|--------------|-----------|-------------|
| `AGENT_RBAC_MODE` | `off` | `enforce` | `off`, `shadow` or `enforce`. Per-agent roles and permissions. `shadow` decides and records without refusing. |
| `AGENT_DELEGATION_MODE` | `off` | `enforce` | `off`, `shadow` or `enforce`. Delegation grants and capability permits. |
| `CAPABILITY_CIRCUIT_BREAKER_ENABLED` | `false` | `true` | Revokes a capability permit and its whole subtree after 5 misuse denials in 5 minutes. Acts only with `AGENT_DELEGATION_MODE=enforce`; denials for expiry, budget or uses never count. |
| `LIABILITY_MODE` | `off` | `enforce` | `off`, `shadow` or `enforce`. The Cockpit Card gate: it can only refuse, before any escrow, so it never moves value. |
| `LIABILITY_PRESENCE_THRESHOLD_AVT` | `0` | | Amount at or above which an action pauses for a live human presence confirmation. `0` turns the step-up off. |
| `REPUTATION_BOND_MODE` | `off` | `enforce` | `off`, `shadow` or `enforce`. The bond as the gate to providing services. `shadow` ranks bonded providers first and counts what it would refuse; `enforce` refuses an unbonded provider at discovery, listing, pricing, Guild bids, contract acceptance and A2A authorization, never at settlement. The production frames run `enforce`. |
| `REPUTATION_BOND_AMOUNT` | `50` | `250` (the network profile) | The bond held in escrow per provider, in the frame's unit. Read from the environment, then the network profile, then the frame policy document (`enforcement.reputation_bond_min_avt`); the network sets its floor at 50. `GET /api/v1/reputation-bond/config` serves the value in force. |
| `REPUTATION_BOND_TREASURY_BACKSTOP` | `false` | `true` | Lets an owner ask the treasury to underwrite a bond without moving units. Such a bond holds the treasury's own units: forfeiting it moves nothing, releasing it pays nobody, and it never makes its owner a member. |
| `REPUTATION_BOND_MIN_TRANSACTIONS`, `_MIN_AGE_DAYS`, `_MIN_RATED_PEERS`, `_MIN_TRUST_PERCENTILE` | `10`, `30`, `3`, `50` | | Maturity conditions, all required, each overriding the policy document's `enforcement.bond_maturity_*` value: satisfactory interactions, days since the lock, distinct rating peers owned by other developers, and a standing at or above that percentile of the frame's ranked agents (waived while fewer than 10 agents are ranked). `REPUTATION_BOND_MATURITY_RELEASES_PERCENT` (`60`, held to 0 to 80) is the share a matured bond pays back, after `REPUTATION_BOND_RELEASE_COOLDOWN_DAYS` (`7`). |
| `ENFORCEMENT_SLASH_MODE` | `cache` | `enforce` | `cache`, `shadow` or `enforce`. Whether a slash moves units down the `slash_waterfall` policy (bond, then lock, then liquid balance). Only `enforce` moves value; `shadow` plans and records; `cache` writes the registry's cached balance only. |
| `AGENT_XREG_DELEGATION_ENABLED` | `false` | `true` | Cross-registry delegation. Must be `true` on both the issuing and the receiving registry. |
| `IRONHAND_INLINE_SVID_ENABLED` | `false` | `true` | Issues short-lived X.509 SVIDs inline to agents on infrastructure you do not run. |
| `IRONHAND_INLINE_SVID_TTL_SECONDS` | `1800` | | The lifetime of those SVIDs. |
| `TEG_TESTING_FAUCET_ENABLED` (TEG) | `false` | not written | The TEG's test faucet: 1,000 units from the treasury per call, to any agent the caller names, with no authentication. Leave it off outside a throwaway frame. |

> **`AGENT_RBAC_MODE` and `AGENT_DELEGATION_MODE` must always move together.** With `enforce` and `off`, the
> registry never consults capability-permit checks, so an agent whose authority comes from a capability permit keeps
> only its role set (often empty) and is refused. Never change one alone.

> Before enforcing RBAC on an existing registry, confirm your agents carry roles. An agent with no role resolves to
> `{read.profile, enforcement.self}` and can do nothing economic. Run `shadow` first and read the denial feed
> (`GET /api/v1/agents/{did}/authz/denials`): that is what shadow mode is for.

### Cross-Currency Transfers

A frame holds the FX booth: `FX_ENABLED` (default `false`, a frame-scope switch) turns on its swap booth and reserves.
A cloud operator holds no booth of its own. When its frame runs one, the provisioner writes `FX_ROUTE_ENABLED=true` and
the gateway settings (`FX_ROUTE_GATEWAY_REGISTRY_ID`, `FX_ROUTE_GATEWAY_ROUTER_DID`, `FX_ROUTE_GATEWAY_TEG_ID`), and the
operator hands a cross-currency transfer to its frame's booth. Without a route, a cross-currency transfer answers 409
naming the disabled booth, and nothing moves; same-currency transfers are unaffected. A standalone registry has one unit
and no booth. Chapter 11 describes cross-frame FX.

### Compliance and Cosmetics

| Variable | Code default | Kit | Description |
|----------|--------------|-----|-------------|
| `JURISDICTION_MODE` | `off` | a frame: `shadow` | `off`, `shadow` or `enforce`. Checks actions against the frame's declared jurisdiction profile: `shadow` logs and counts, `enforce` refuses with 403. An entry of the regulatory-authorization rail carries its own mode, and an entry-level `enforce` applies even while this is `shadow`. |
| `REGAUTH_COUNTERSIGN_WATCH_ENABLED` | `true` | | A watcher that tells you when a countersigned contract behind a regulatory authorization stops being valid. |
| `REGAUTH_COUNTERSIGN_WATCH_INTERVAL` | `120` | | Seconds between its cycles. |
| `FLARE_LOCAL_PURCHASE_ENABLED` | `false` | a frame: `true` | Sells cosmetic flare tiers for the registry's own units. Off, the catalog says the shop is closed and a purchase answers 503. |
| `FLARE_SHOP_PRICES` | unset | | A JSON object of per-tier prices. An unknown tier or a price of zero or less is ignored; a malformed value leaves the defaults in force. |
| `OPA_ENABLED` / `OPA_ENFORCE` | `false` / `false` | `true` / `false` (standalone compose and a frame) | Open Policy Agent. With `OPA_ENABLED` alone, every authorization decision is mirrored to OPA and recorded beside the registry's own (shadow). `OPA_ENFORCE` counts only with `OPA_ENABLED`; OPA can then turn an allow into a refusal, never a refusal into an allow. |

---

## PgBouncer Configuration

On an operator, the generator writes `pgbouncer.ini` and `userlist.txt` (both mode 600) with the same database
passwords as `.env.operator`:

```ini
[databases]
agentvault_registry = host=db port=5432 dbname=agentvault_registry user=registry password=<PG_PASS_REGISTRY>
teg_layer = host=teg-db port=5432 dbname=teg_layer user=teg password=<PG_PASS_TEG> pool_size=200

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = scram-sha-256
auth_file = /etc/pgbouncer/userlist.txt
pool_mode = transaction
max_client_conn = 800
default_pool_size = 150
reserve_pool_size = 10
ignore_startup_parameters = extra_float_digits,options
```

| Setting | Value | Description |
|---------|-------|-------------|
| `pool_mode` | `transaction` | A server connection returns to the pool after each transaction; the workers share them. |
| `auth_type` | `scram-sha-256` | Every client presents its password; `userlist.txt` holds the two. |
| `max_client_conn` | `800` | Client connections the pooler accepts. |
| `default_pool_size` | `150` | Server connections per database and user; the TEG's database has its own `pool_size=200`. |

If you change a database password, change it in all three places. On a standalone registry the pooler is configured in
the compose instead (`POOL_MODE=transaction`, `MAX_CLIENT_CONN=200`, `DEFAULT_POOL_SIZE=20`) and serves the registry's
database only; the TEG connects to its database directly.

---

## Redis Configuration

```
redis-server --maxmemory 128mb --maxmemory-policy allkeys-lru
```

| Setting | Value | Description |
|---------|-------|-------------|
| `maxmemory` | `128mb` | Memory before eviction. |
| `maxmemory-policy` | `allkeys-lru` | Evict the least recently used keys when memory is full. |
| Database | `0` | One database for the registry and the TEG (a frame gives its registry, its event store and its TEG a database each). |

On an operator, Redis also loads an access list (`redis-users.acl`, written by the provisioner, or by the bundle's
generator on an operator's own host) with one user each for
the registry and the TEG (`REDIS_PASSWORD_REGISTRY`, `REDIS_PASSWORD_TEG`, **secret**); the default user may only answer
the health check. A standalone Redis has no access list.

Redis carries the leader election that runs each background task once, the rate limiter's counters, the WebSocket
broadcasts across workers and, on an operator, the queue that batches transfers on their way to the TEG.

---

## Registry Service Configuration

The compose sets these for the registry; they rarely need changing:

| Variable | Operator compose | Standalone compose | Description |
|----------|------------------|--------------------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://registry:<pass>@pgbouncer:6432/agentvault_registry` | the same | The registry's database, through the pooler. |
| `DATABASE_URL_SYNC` | `postgresql://registry:<pass>@pgbouncer:6432/agentvault_registry` | the same | The same database for the synchronous paths (migrations). |
| `TEG_API_BASE_URL` | `https://nginx-teg:8443` | unset (`http://teg-layer:8080`) | Where the registry calls the TEG: through its mTLS terminator on an operator. |
| `TEG_LAYER_URL` | `http://teg-layer:8080` | the same | The TEG's own address, read by the stack health probes. |
| `REDIS_URL` | `redis://registry:<REDIS_PASSWORD_REGISTRY>@redis:6379/0` | `redis://redis:6379/0` | Redis. |
| `SPIFFE_ENDPOINT_SOCKET` | `unix:///opt/spire/sockets/agent.sock` | unset | The SPIRE agent's socket. |
| `REGISTRY_PROXY_TRUST_SECRET` | written by the provisioner or the bundle's generator | unset | **Secret.** The marker `nginx-federation` adds to every call it forwards. Unset or shorter than 32 characters, the registry ignores forwarded certificates: it refuses rather than trusts. |

The number of workers is on each compose's command line (`--workers 8` on an operator, `4` standalone). The composes
also set `UVICORN_WORKERS`, which none of the services reads.

---

## TEG Layer Configuration

| Variable | Operator compose | Standalone compose | Description |
|----------|------------------|--------------------|-------------|
| `DATABASE_URL` | `postgresql://teg:<pass>@pgbouncer:6432/teg_layer` | `postgresql://teg:<pass>@teg-db:5432/teg_layer` | The TEG's database. |
| `REGISTRY_URL` | `http://registry:8000` | the same | Where the TEG reads the event emission policies. |
| `ADMIN_API_KEY` | `<TEG_ADMIN_API_KEY>` | the same | The admin key; see `TEG_ADMIN_API_KEY` above. |
| `MINTING_AUTHORITY` | `disabled` | `teg-layer` | Issuance; see Units and Fees. |
| `TEG_MTLS_REQUIRED` | `true` | unset (`false`) | Internal callers authenticate by SVID only; the shared key no longer counts. |
| `TEG_PROXY_TRUST_SECRET` | written by the provisioner or the bundle's generator | unset | **Secret.** The marker `nginx-teg` and `nginx-federation` add to forwarded calls. |
| `TRUSTED_SPIFFE_DOMAINS` | `${TEG_TRUSTED_SPIFFE_DOMAINS}`, empty | unset | The trust domains whose callers the TEG accepts; empty means its own frame's domain only. |
| `REDIS_URL` | `redis://teg:<REDIS_PASSWORD_TEG>@redis:6379/0` | unset | Leader election for the TEG's own sweepers. |

The TEG also runs `--workers 8` on an operator and `4` standalone.

---

## Authentication Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `90` | The lifetime of an access JWT, in minutes. |
| `BOOTSTRAP_TOKEN_LIFETIME` | `300` | The lifetime of a bootstrap token, in seconds. |
| `EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS` | `24` | How long a verification link stays valid. |
| `REQUIRE_EMAIL_VERIFICATION` | `true` | Off, a new developer is verified on registration; on, a login answers 403 until the mailed link is followed. |
| `REQUIRE_ADMIN_2FA` | `false` | An account with admin rights that has not set up two-factor authentication cannot sign in with its password, and none of its credentials (API keys, MCP connectors, sessions) reaches an admin route or an admin tool until 2FA is on. Its other use is unchanged. |

---

## Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_DEFAULT` | `1200/minute` | The limit every route has, per client address: the last address your proxy appended, which a caller cannot forge. |
| `SANDBOX_BYPASS_RATE_LIMIT` | unset | `true` switches the limiter off. For a test frame that sweeps every endpoint, never for a registry people use. |

Many routes carry a tighter limit of their own in the code (a login, for instance), counted per verified account or
agent once its credential has been checked. Calls between the stack's own containers are exempt. The limiter keeps its
counters in Redis, so a limit holds across workers.

`RATE_LIMIT_BYPASS_KEYS` (comma-separated API keys) does not lift the limit: a request that presents one of these keys in
`X-Api-Key` counts in a bucket of its own instead of its address's, under the same limit.

---

## Secret Rotation Guidance

### When to Rotate

| Trigger | Action |
|---------|--------|
| Suspected compromise | Rotate the `API_KEY_SECRET` / `TEG_REGISTRY_JWT_SECRET` pair (every issued JWT stops working: developers and agents sign in again) and revoke the API keys involved (API keys do not depend on the pair). On a standalone registry rotate `TEG_ADMIN_API_KEY` and `EVENT_STORE_INTERNAL_API_KEY` too. |
| Personnel change | The same pair, and on a standalone registry `TEG_ADMIN_API_KEY` |
| Routine | The pair |

Service certificates need no manual rotation: SPIRE renews the SVIDs.

### How to Rotate

1. Generate a new value: `openssl rand -hex 32`.
2. Write it into `.env.operator`, on the host that runs the stack.
3. Recreate the containers that read it:
   ```bash
   docker compose -f docker-compose.standalone.yml --env-file .env.operator up -d --no-deps --force-recreate registry teg-layer
   ```
   On an operator, the compose is `docker-compose.operator.yml`, and the frame's host runs it.
4. A database password changes inside the database first (see Database Passwords), or the volume is recreated.

### Keys That Must Match

| Key A | Key B | Reason |
|-------|-------|--------|
| `API_KEY_SECRET` | `TEG_REGISTRY_JWT_SECRET` | The generator writes them equal; rotate them together. |
| `PG_PASS_REGISTRY`, `PG_PASS_TEG` | `pgbouncer.ini`, `userlist.txt` (operator) | The pooler holds the same passwords. |

---

## Complete .env.operator Template

What `operator-setup.sh` writes on a standalone registry, values replaced:

```bash
# .env.operator: generated by generate-operator-env.sh. Do not commit: it contains secrets.

# -- Identity
REGISTRY_NAME="<your-registry-name>"
OPERATOR_DID=did:theprotocol:operator-<16 hex characters>
TRUST_DOMAIN=<your-registry-name>.local

# -- Database passwords
PG_PASS_REGISTRY=<48 hex characters>
PG_PASS_TEG=<48 hex characters>
PG_PASS_EVENT_STORE=<48 hex characters>

# -- Security keys
SECRET_KEY=<64 hex characters, read by nothing>
JWT_SECRET_KEY=<64 hex characters, read by nothing>
API_KEY_SECRET=<64 hex characters>
TEG_REGISTRY_JWT_SECRET=<the same as API_KEY_SECRET>
TEG_ADMIN_API_KEY=<64 hex characters>
TEG_AVTP_SYSTEM_API_KEY=<64 hex characters>
TEG_TOKEN_SIGNING_KEY=<64 hex characters>
EVENT_STORE_INTERNAL_API_KEY=<64 hex characters>

# -- Production checks: put your public https address in the list when you set BASE_URL
ALLOWED_ORIGINS=["http://localhost:8000"]
FEDERATION_HEALTH_CHECK_SECRET=<64 hex characters>

# -- Units
TEG_ID=teg-layer
MINTING_AUTHORITY=teg-layer

# -- Federation (empty on a standalone registry)
FEDERATION_LICENSE_KEY=
KAFKA_BOOTSTRAP_SERVERS=
KAFKA_ENABLED=false
FEDERATION_SYNC_INTERVAL_SECONDS=30

# -- Email (configure before real users register)
MAIL_SERVER=smtp.example.com
MAIL_PORT=587
MAIL_USERNAME=noreply@example.com
MAIL_PASSWORD=CHANGE_ME
MAIL_FROM=noreply@example.com
MAIL_FROM_NAME="<your-registry-name>"
MAIL_STARTTLS=True
MAIL_SSL_TLS=False

# -- Monitoring
GRAFANA_ADMIN_PASSWORD=<32 hex characters>

# -- Features
ENABLE_PROJECTION_SNAPSHOTS=true
GENESIS_GRANT_ENABLED=true
GENESIS_GRANT_AMOUNT=5000.0
BETA_INVITE_REQUIRED=false
AUDITED_BALANCE_ENABLED=true

# -- The ledger's broker: the event store's password and the key it signs every record with
KAFKA_ES_PASSWORD=<64 hex characters>
ES_KAFKA_RECORD_KEY=<64 hex characters>
```

The operator generator in a bundle writes the same kind of file with `MINTING_AUTHORITY=disabled`,
`CROSS_TEG_ENABLED=true`, `RELEASE_CHANNEL_CHECK_ENABLED=true` and no `TRUST_DOMAIN`, `TEG_ID` or event store key,
and under a name that does not start with `cloud-op-` the operator's own Redis passwords and proxy trust secrets; for
a cloud operator, the frame's provisioner then appends the values it holds for it (its addresses, its licence, its
secrets and the frame's switches).

---

*See also: Quickstart (chapter 00) | Architecture (chapter 01) | Federation Guide (chapter 03)*
