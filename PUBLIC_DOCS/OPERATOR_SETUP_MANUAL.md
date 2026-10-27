<!-- GENERATED from AgentVault/agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/assets/docs/operator/14_setup_manual.md by scripts/distribution/gen_public_docs.py. Edit that file, not this copy: the export refuses a copy that differs from its source. -->

# TheProtocol Operator Setup Manual

> **Audience:** anyone standing up their **own** TheProtocol registry from the public repository.
> **Status:** where this manual and the Quickstart, Configuration or Federation pages disagree, this manual is the
> one checked against the source.
> **Checked against the source:** 2026-10-16 (the frame kit in `scripts/distribution`, the registry V0618); the
> generators, section 4.1, the bundle and the known limits again 2026-10-22 (the frame kit 1.0.0-beta.22).

This manual covers what the **code does not decide for you**: the deployment mode, the environment and its secrets,
TLS and DNS, the public reverse proxy and, if you join a frame, the mTLS sidecars and the SPIRE identity.

---

## 0. Pick your deployment mode first

| | **Standalone** (start here) | **Federated operator** (a registry under a frame) |
|---|---|---|
| Compose | `scripts/distribution/docker-compose.standalone.yml` | the `docker-compose.operator.yml` in the bundle your frame provisions for you |
| Containers | **11**, plus `redpanda-init`, which runs once and exits | **10** |
| Your own event store | **yes** (your ledger) | no: your registry writes to its parent frame's event store |
| Issuance | **yes**: your treasury issues your registry's own unit | **no**: units reach you from the federation |
| SPIRE and mTLS sidecars | none | a SPIRE agent, a cert-writer and two nginx mTLS sidecars |
| Needs the frame | **no**: self-contained, can run air-gapped | **yes**: an application, its approval and the provisioning on the frame |

Standalone runs `registry`, `teg-layer`, `event-store`, `db`, `teg-db`, `es-db`, `redis`, `pgbouncer`, `redpanda`,
`opa` (policy checks in shadow) and `auditor` (the independent supply auditor). The federated bundle runs `registry`,
`teg-layer` (container `<name>-teg`), `db`, `teg-db`, `redis`, `pgbouncer`, `spire-agent`, `cert-writer`,
`nginx-federation` and `nginx-teg`.

A **whole frame** of your own, with its own SPIRE server, mTLS gateways, ledger and kit, is a third path:
`scripts/distribution/frame-up.py` stands it up under your DNS name and `frame-federate.py` joins the network through
the invitation rail. The repository README ("Run a federated frame on your own host") and operator chapter 15
describe it; this manual covers the single registry.

The rest of this manual: section 1 prerequisites, section 2 the software, section 3 the **standalone** walkthrough,
section 4 configuration (both modes), section 5 **joining a frame**, section 6 verification, section 7 operations,
section 8 troubleshooting, section 9 known limits.

---

## 1. Prerequisites

- **Host:** Linux with Docker (BuildKit, the default since Docker 23) and the Compose v2 plugin (`docker compose`,
  not `docker-compose`), plus `openssl` and `bash`. The images build for the machine they are built on; the registry
  image fetches its proving tools for x86-64 and for arm64.
- **Memory:** plan for a few gigabytes. The standalone stack runs three PostgreSQL databases, Redis, a Redpanda broker
  started with 1 GB (`--memory 1G`) and the Python services. It is ready about two minutes after `up`.
- **A domain** with an A record pointing at the host, if browsers and API clients will reach it over HTTPS
  (section 4.4). Not needed for a local trial.
- **Ports:** the standalone registry publishes plain HTTP on host port `8000` (`REGISTRY_HTTP_PORT`) **on every
  interface**; the auditor publishes `8045` on loopback only. Put TLS in front of the registry (section 4.4) and keep
  `8000` off the internet.
- **Federated only:** an approved application on the frame you join (section 5). You cannot issue a federation
  identity to yourself.

---

## 2. Obtain the software

### 2a. Pre-built images

There is no public image registry to pull the application images from yet: pre-built images and a signed update
channel open with the public release (operator chapter 16). A federated operator pulls from its frame's image host,
with the pull credential the frame issues at activation (section 5). Everyone else builds the images (section 2b).

### 2b. Build from source

`scripts/distribution/build.sh` builds six images from the repository, runs a boot check on each (the application
must import and mount its routes) and tags them `theprotocol/<name>:<VERSION>`, `:latest` and `:stable`:

```
registry      scripts/distribution/Dockerfile.registry.dist     <-  ./AgentVault
teg-layer     scripts/distribution/Dockerfile.teg.dist          <-  ./AgentVault/agentvault_teg_layer_mvp
event-store   scripts/distribution/Dockerfile.eventstore.dist   <-  ./agentvault-event-store
auditor       Agents/TheAuditor/Dockerfile                      <-  ./Agents/TheAuditor
directory     directory/Dockerfile                              <-  ./directory
cert-writer   nginx/Dockerfile.cert-writer                      <-  ./nginx
```

`theprotocol/` is a **local** name, and it is what `docker-compose.standalone.yml` runs by default (`:stable`), so
nothing is pulled from anywhere. A tree you changed takes only `:<VERSION>`, so an experiment never becomes what a
restart runs. `--registry <host/namespace>` (or `IMAGE_REGISTRY`) changes the prefix, and `--push` pushes, only to a
registry you name. The registry image builds the web console itself in a Node.js stage (BuildKit is the only
requirement), keeps the Python source with its bytecode precompiled, and keeps `alembic/`, so migrations run at boot
(section 4.3). The first build downloads the Python and npm dependencies and takes a while; later builds reuse the
cache.

---

## 3. Standalone setup: step by step

The fully self-contained path: no SPIRE, no sidecars, nothing asked of anyone.

```bash
# 1. enter the distribution directory of the kit (this repository, unpacked)
cd scripts/distribution

# 2. build the six images (section 2b)
./build.sh

# 3. write .env.operator with random per-registry secrets
./operator-setup.sh my-registry standalone

# 4. edit .env.operator: the values nothing can generate for you (section 4.1)
#    - TRUST_DOMAIN: your DNS name (the generated <name>.local suits a local trial only); the registry signs its
#      card with it and mints its agents' DIDs under it
#    - MAIL_*: your SMTP account (the generated smtp.example.com / CHANGE_ME send nothing)
#    - BASE_URL, once the registry has a public https address, and that address in ALLOWED_ORIGINS (section 4.1)
#    - REGISTRY_HTTP_PORT=<port> if 8000 is taken on this host; the kit's other host ports are AUDITOR_HTTP_PORT
#      (8045) and, with the monitoring overlay, PROMETHEUS_HTTP_PORT (9090), GRAFANA_HTTP_PORT (3000) and
#      ALERTMANAGER_HTTP_PORT (9093), all on loopback
nano .env.operator

# 5. launch
docker compose -f docker-compose.standalone.yml --env-file .env.operator up -d

# 6. after about two minutes, read the first admin's password, printed once
docker logs my-registry-registry 2>&1 | grep -A3 "FIRST-BOOT ADMIN PASSWORD"

# 7. check the registry
curl -s http://localhost:8000/health        # {"status":"ok", ...}
```

Then, as that admin (`admin@<name>.dev` unless you set `FIRST_ADMIN_EMAIL`):

1. **Log in and change the password.** `POST /api/v1/auth/login` is form-encoded (`username=...&password=...`);
   `POST /api/v1/auth/change-password` takes the new one. Do this before the registry is reachable from the internet.
2. **Issue the initial supply.** A standalone treasury starts empty, and until it holds units every new agent's
   genesis grant reports `partial`:
   `POST /api/v1/teg/treasury/mint` with `{"amount": "1000000", "reason": "initial supply"}` and the admin's bearer
   token. The standalone compose makes the registry its own sovereign frame (`IS_CENTRAL_REGISTRY=true` with its name
   in `MAINFRAME_REGISTRY_NAMES`), which is what allows the issuance; the first admin holds every admin flag.
3. **No SMTP yet?** Verify a registrant from the admin rail instead of the mailed link:
   `POST /api/v1/admin/developers/{id}/force-email-verify`.
4. **Create the first agent.** As a developer: `POST /api/v1/onboard/bootstrap/request-token` (developer JWT or API
   key) returns a `bootstrap_token`; `POST /api/v1/onboard/create_agent` with the header `Bootstrap-Token: <token>`
   and `{"agent_did_method": "theprotocol"}` returns the agent's `agent_did`, `client_id` and `client_secret` (shown
   once) and `initial_funding_status`, the genesis grant (`GENESIS_GRANT_AMOUNT`, 5000 units in the kit's env).

**What happened automatically (you do not do these by hand):**

- `generate-operator-env.sh` (called by `operator-setup.sh`) wrote every application secret: the database
  passwords, `API_KEY_SECRET`, the TEG's keys, the internal keys and the federation health-check secret.
- On first `up`, the registry ran `migration_bridge`, `alembic upgrade head` and `operator_seed`, then started.
  Migrations create every table and seed the event emission policies (migration `0077`); `operator_seed` creates the
  first admin with a random password printed once (unless `FIRST_ADMIN_PASSWORD` is set) and seeds the essential
  emission policies when the table is empty. The TEG migrates the same way; the event store creates its schema at
  startup.

**You are responsible for:** the values of section 4.1, the TLS front door (section 4.4), backups (section 7) and
the first admin's password.

---

## 4. Configuration reference (applies to both modes)

### 4.1 Environment variables you must set

`generate-operator-env.sh` writes a complete `.env.operator`; you edit only what it cannot know.

**Generated for you (random per registry), leave as written:** `PG_PASS_REGISTRY`, `PG_PASS_TEG`,
`PG_PASS_EVENT_STORE`, `SECRET_KEY`, `JWT_SECRET_KEY`, `API_KEY_SECRET` (and `TEG_REGISTRY_JWT_SECRET`, the same
value), `TEG_ADMIN_API_KEY`, `TEG_AVTP_SYSTEM_API_KEY`, `TEG_TOKEN_SIGNING_KEY`, `EVENT_STORE_INTERNAL_API_KEY`,
`FEDERATION_HEALTH_CHECK_SECRET`, the ledger bus's `KAFKA_ES_PASSWORD` and `ES_KAFKA_RECORD_KEY`, and
`GRAFANA_ADMIN_PASSWORD`. Also written: `ALLOWED_ORIGINS=["http://localhost:8000"]` (put your address in it with
`BASE_URL`), `MINTING_AUTHORITY=teg-layer` (standalone), `GENESIS_GRANT_ENABLED=true`, `GENESIS_GRANT_AMOUNT=5000.0`,
`BETA_INVITE_REQUIRED=false` and `FEDERATION_SYNC_INTERVAL_SECONDS=30`.

**You must edit before going public:**

| Variable(s) | Why |
|---|---|
| `TRUST_DOMAIN` | Your DNS name: the trust domain the registry signs its card with and issues DIDs under. |
| `MAIL_SERVER`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM` | Verification mails and password resets. The generated `smtp.example.com` / `CHANGE_ME` send nothing. A registry that sends no mail declares `MAIL_DISABLED=true` instead. |
| `BASE_URL` | Your public `https://` address. A `BASE_URL` without `localhost` switches the registry's **production checks** on, and it then refuses to boot unless `ALLOWED_ORIGINS` is a JSON list without `*` (your address in the list the generator wrote, for example `["https://registry.example.org"]`; a bare URL fails to parse), mail is configured (SMTP, a parent relay or `MAIL_DISABLED=true`), `API_KEY_SECRET` contains none of `test`, `example`, `demo`, `sample` and, on a standalone registry (which the compose marks as its own frame), `FEDERATION_HEALTH_CHECK_SECRET` is set (the generator writes one). |
| `PUBLIC_UI_URL` | Only when the web console is served at another address than `BASE_URL`: the links the registry mails point there. |
| `REGISTRY_SIGNING_KEY_PASSPHRASE` *(recommended)* | Encrypts the registry's card-signing key at rest (HKDF, then AES-GCM). Unset, the key is stored in plaintext in the database, with a warning in the log. |

**Off by default, turn on deliberately:** the card payment rail (`FIAT_ONRAMP_ENABLED`, with its provider keys),
the monitoring overlay (`docker-compose.monitoring.yml`), and the AGORA and cross-frame FX switches.

**Frame identity, only if you customize it:** `FRAME_CURRENCY`, the code of your registry's unit (unset, the code
default `FRAME_CURRENCY=AVT` applies, so set your own), `REGISTRY_NAME` and `REGISTRY_FEDERATION_NAME`.

The kit no longer writes `DEFAULT_FEE_RATE` and `MAX_FEE_RATE` (an older `.env.operator` may still carry them; no
service reads them): the transfer fee comes from the registry's enforcement policy (0.5 % base, at most 5 % under
high velocity, by default).

> The full list is the compose file you run (every `${VAR}` without a `:-default` is required) plus the
> applications' settings: `AgentVault/agentvault_registry/src/agentvault_registry/config.py` and
> `AgentVault/agentvault_teg_layer_mvp/src/teg_core_service/core/secure_config.py`.

### 4.2 Secrets and what they protect

Generate any secret with `openssl rand -hex 32`. Three facts the code enforces:

1. **`API_KEY_SECRET` signs the registry's developer and agent JWTs** (HS256). Changing it signs everyone out. It
   must not contain `test`, `example`, `demo` or `sample` once the production checks are on. The generator also writes
   `TEG_REGISTRY_JWT_SECRET` with the same value, and `tp-operator validate-config` checks that the two match. The TEG
   does not use that copy to accept the registry: it accepts the registry's calls by its mTLS identity or the TEG's
   admin key.
2. **The TEG's `TEG_TOKEN_SIGNING_KEY` and `AVTP_SYSTEM_API_KEY`** (written as `TEG_AVTP_SYSTEM_API_KEY` and passed
   on by the compose) must each be at least 32 characters, or the TEG refuses to start.
3. **SPIRE certificates and the card-signing key are not env secrets:** the stack issues or generates them at
   runtime.

### 4.3 Database bootstrap is automatic

Each service migrates itself through its compose `command:`. You never run alembic, create databases, seed policies
or initialize a treasury by hand.

- **Registry:** `migration_bridge` (a safe re-stamp, nothing to do on a fresh database), `alembic upgrade head`,
  `operator_seed`, then gunicorn.
- **TEG:** `migration_bridge`, `alembic upgrade head`, then gunicorn.
- **Event store:** its schema is created at startup (an append-only ledger).

### 4.4 TLS, DNS and the public reverse proxy

The registry serves plain HTTP. Browsers, the web console and API clients need HTTPS on your domain:

- **Standalone, with the kit's Caddy overlay:** set `DOMAIN` (and optionally `ACME_EMAIL`) in `.env.operator` and
  start with both files,
  `docker compose -f docker-compose.standalone.yml -f docker-compose.tls.yml --env-file .env.operator up -d`.
  Caddy obtains and renews a Let's Encrypt certificate on ports 80 and 443 and proxies to the registry.
  `scripts/distribution/TLS_SETUP.md` has the details. Then bind the registry to loopback: change its port mapping to
  `"127.0.0.1:${REGISTRY_HTTP_PORT:-8000}:8000"` and open only 80 and 443.
- **Your own proxy** (nginx, Caddy, Traefik): obtain a certificate, `proxy_pass` to the registry's port and forward
  `Host`, `X-Forwarded-For` and `X-Forwarded-Proto`.

In both cases, set `BASE_URL` to the `https://` address (section 4.1). **Do not ask for client certificates on this
public address:** browsers then show a certificate picker and ordinary users are locked out. Client certificates
belong only on the federation port of a federated operator (section 5).

---

## 5. Joining a frame as a federated operator

**Skip this section for standalone.** A federated operator's identity comes from the frame it joins: the frame's
SPIRE server attests your SPIRE agent with a certificate signed by the frame's CA, which you do not hold.

### 5.1 The application and the bundle

1. **Apply** on the frame you want to join: its console's operator application form (`POST
   /api/v1/operator-applications`, public).
2. **The frame's admin approves** the application. You receive an activation code by mail, valid for 7 days.
3. **Activate** as a developer on that frame: `POST /api/v1/operators/activate` with `{"activation_code": "..."}`.
   The frame provisions your bundle: an x509pop attestation certificate signed by its SPIRE CA, its trust bundle, the
   SPIRE entries for your agent, your `agent.conf`, the nginx configuration, the compose file, the env generator and
   `pgbouncer.ini`. It also issues an image pull credential (user `operator-<name>`), mailed once.
4. **Download the bundle** (`GET /api/v1/operators/my-bundle`, kept for 30 days) and unpack it. Your federation
   licence key (`tp_fed_...`) comes from the frame's admin.
5. **Write the env in the bundle's directory:** `./generate-operator-env.sh <name>`. It writes `.env.operator`,
   `pgbouncer.ini`, `userlist.txt` and, under a name that does not start with `cloud-op-`, the operator's Redis
   passwords, proxy trust secrets, `redis-users.acl` and the terminators' markers itself. Set
   `FEDERATION_LICENSE_KEY`, then log in to the frame's image host with the pull credential and start the stack.

Since the frame kit 1.0.0-beta.21 the generator writes those secrets, but the bundle's compose still gives the
registry and the TEG a fixed ledger address (`EVENT_STORE_URL`), a line only the frame's own provisioner replaces
with the frame's ledger gateway, for a cloud operator it hosts. A bundle downloaded for your own host therefore does
not run as shipped. Until that changes, the working ways to federate are a **cloud operator hosted
by the frame** (its admin provisions it from Frame Management) or a **whole frame of your own** (section 0).

The bundle publishes the federation port `12443` (mTLS), the registry `12000` and the TEG `12080` on every interface:
let the frame reach `12443`, and keep `12000` and `12080` off the internet.

### 5.2 What the mTLS sidecars do

- **`nginx-federation`** terminates TLS for federation traffic on `8443` (published as `12443`) with **mutual** TLS:
  its server certificate is a SPIRE-issued X.509 SVID, and `ssl_verify_client on` refuses any peer whose client
  certificate does not chain to the SPIRE trust bundle. nginx checks the chain; the registry checks the SPIFFE ID
  itself. It routes federation, cross-TEG and well-known paths to the registry and the TEG, and answers health on
  `8080`.
- **`nginx-teg`** is the internal mTLS gateway in front of your TEG; it sets `Host: teg-layer:8080` because the TEG
  checks the host it is called as.
- **`cert-writer`** fetches the SVID from the SPIRE agent's socket (`spire-agent api fetch x509`), writes
  `/certs/svid.0.pem`, `/certs/svid.0.key` and `/certs/bundle.0.pem` with the roots of every federated peer appended,
  makes the key readable by the non-root nginx (mode 644) and refreshes every 300 seconds.

You do not edit the nginx routes: the entrypoint renders the TEG's upstream (`TEG_UPSTREAM_HOST`). Each terminator
also carries a per-operator proxy secret (`REGISTRY_PROXY_TRUST_SECRET`, `TEG_PROXY_TRUST_SECRET`), the values
section 5.1 names as missing from the generator.

### 5.3 SPIRE node attestation

- **Node attestation is `x509pop`.** The guides in `identity-fabric/docs/` describe an earlier join-token setup;
  ignore them for a federated operator.
- A federated operator runs **only a SPIRE agent**, no SPIRE server. Its `agent.conf` (written by the frame) names
  the frame's SPIRE server, port and trust domain, and the agent attests with the certificate the frame signed.
- The SPIRE agent's socket is shared read-only with the registry and the cert-writer at `/opt/spire/sockets`.

`scripts/distribution/onboard-operator.sh` is an older, manual form of the same provisioning, written for the
network's own host (it names a fixed SPIRE container and a former trust domain); use the application flow above.

---

## 6. First-run verification

```bash
# the containers (standalone: 11 running, redpanda-init exited)
docker compose -f docker-compose.standalone.yml --env-file .env.operator ps

# the registry, its signed card and its public switches
curl -s http://localhost:8000/health
curl -s http://localhost:8000/.well-known/registry-card.json
curl -s http://localhost:8000/api/v1/public/registry-config

# the supply invariant, from the standalone auditor (loopback only): your registry's entry reads "status": "OK"
# and a delta of 0
curl -s http://127.0.0.1:8045/api/auditor/latest
```

Log in as the first admin, change the password (section 3) and create your real developer accounts and agents.

For a federated operator, the frame's admin sees your operator and its licence as active. `tp-operator license
verify` is not a licence check: it only reaches a public endpoint (operator chapter 12).

---

## 7. Operations

- **Backups:** dump the databases (`pg_dump`) and keep the env file with them. On an operator stack,
  `tp-operator backup` does the registry and TEG databases with the configuration; a standalone stack's event store
  database (`es-db`) is dumped separately (operator chapter 12). Units move only through the API: never edit a
  balance in a database.
- **Upgrades:** build or pull the new release, then `up -d`; migrations run at boot. Keep the previous image to roll
  back, and read the release notes first: a release that crossed a migration needs its downgrade before the older
  image starts (operator chapter 16).
- **Secrets:** rotating `API_KEY_SECRET` signs everyone out; keep `TEG_REGISTRY_JWT_SECRET` equal to it. Change the
  first admin's password at first boot.

---

## 8. Troubleshooting & known gotchas

- **The registry exits with "Production configuration validation failed"** after you set `BASE_URL`: the message
  lists what is missing. Usually `ALLOWED_ORIGINS` (a JSON list without `*`, your address in it) or, in an
  `.env.operator` from a kit older than 1.0.0-beta.21, a missing `FEDERATION_HEALTH_CHECK_SECRET` (section 4.1).
- **The browser shows a "select a certificate" prompt:** client-certificate verification is on for a public address.
  Turn it off there; keep mTLS only on the federation port.
- **nginx returns 502 after a backend container restarts:** a `proxy_pass` to a variable needs
  `resolver 127.0.0.11 valid=10s;`, or nginx keeps the old address. The bundle's configuration has it.
- **The TEG answers 403 or refuses the host:** keep `proxy_set_header Host "teg-layer:8080"` in `nginx-teg`.
- **nginx does not start:** it waits up to 120 seconds for the cert-writer's `/certs/.ready` marker, and the
  cert-writer gives up after 60 seconds when the SPIRE agent's socket never appears. Fix the SPIRE agent first. If you
  tightened the key's mode, the non-root nginx cannot read it.

---

## 9. Known limits

1. **The federated bundle does not run on a host of your own as shipped** (section 5.1): its compose names a fixed
   ledger address that only the frame's provisioner replaces (the generator writes the operator's secrets since the
   frame kit 1.0.0-beta.21).
2. **The SPIRE guides in `identity-fabric/docs/`** describe join-token attestation; the real scheme is x509pop
   (section 5.3).

---

*End of Operator Setup Manual.*
