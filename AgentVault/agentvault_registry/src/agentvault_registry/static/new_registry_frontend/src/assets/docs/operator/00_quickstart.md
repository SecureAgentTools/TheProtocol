# Quickstart: Operator Setup Guide

**Audience**: anyone who wants a registry of their own
**Checked against the source**: 2026-10-16 (the frame kit 1.0.0-beta.20: `scripts/distribution/` and
`templates/frame-test/`; the registry's auth, onboarding, treasury and operator routes); the standalone build, its
environment file, its ledger and the bundle again 2026-10-22 (the frame kit 1.0.0-beta.22); the frame section and the
release images again 2026-10-31 (the frame kit 1.0.0-beta.27, on a clean host)

A registry of your own comes in three shapes. They are different stacks, so pick one before you run anything:

| Shape | Runs on | What it is | Start here |
|---|---|---|---|
| Standalone registry | your host | one registry with its own ledger, supply audit and unit; it issues its own units and does not federate | the steps on this page |
| Frame | your host, under your own DNS name | the full sovereign stack: its own SPIRE server, ledger, unit and mTLS gateways, with monitoring, an auditor and a federated directory; it federates with other frames by invitation | [A Frame on Your Own Host](#a-frame-on-your-own-host) |
| Cloud operator | the host of the frame you join | a registry inside that frame's trust domain, unit and ledger, provisioned by the frame | [A Cloud Operator Under a Frame](#a-cloud-operator-under-a-frame) |

All three run the same application images. Each release's six images are public and pull without an account from
`images.theprotocol.cloud/theprotocol` (see Releases, images and updates); the kit can also build them
on your host (`scripts/distribution/build.sh`). A cloud operator runs the images of the frame that provisions it.
[Run Your Own Registry](/docs/17) explains what each shape gives and what it gives up.

---

## Self-Hosted Setup

The steps below stand up a standalone registry: twelve services from one compose file, nothing to ask of anyone. A
frame uses the same images and has its own section further down.

### Prerequisites

| Requirement | Detail |
|-------------|--------|
| Docker | Docker Engine with BuildKit (the default builder since Docker 23) and the Compose v2 plugin (`docker compose`) |
| Tools | `bash`, `openssl` and `git`; `operator-setup.sh` refuses to run without `docker`, `openssl` and `docker compose` |
| The kit | this repository, cloned or unpacked; every command below runs in `scripts/distribution` |
| Network | the first build downloads Python and npm packages, and the first start pulls the public base images (PostgreSQL, PgBouncer, Redis, Redpanda, OPA); after that the stack needs no outside service |
| Memory | the ledger's broker alone is started with 1 GB (`--memory 1G` in the compose); leave room for three PostgreSQL databases, Redis and the application workers |

---

## Build the Images

```bash
cd scripts/distribution
./build.sh
```

`build.sh` builds six images (`registry`, `teg-layer`, `event-store`, `auditor`, `directory` and `cert-writer`), starts
each one once to prove it imports its application, and tags them `theprotocol/<name>` with the kit's version, `latest`
and `stable`. `theprotocol/` is a local name: nothing is pulled from or pushed to anyone's image registry, and the
standalone compose runs `theprotocol/<name>:stable` by default. The first build takes a while; later builds reuse
Docker's cache.

A kit unpacked from a release carries a list of its own files (`KIT_FILES.sha256`), and a build of a tree that differs
from that list tags the new images with the version only, never `stable`. The files the setup writes beside the
scripts (`.env.operator`, `pgbouncer.ini`, `userlist.txt` and `redis-users.acl` in `scripts/distribution`) do not
count, so a build after the setup keeps its tags.

---

## Generate the Environment File

```bash
./operator-setup.sh my-registry standalone
```

The script writes `.env.operator` (it asks before overwriting one) with a random value for every secret the stack needs:
the three database passwords, the registry's signing secret, the TEG's keys, the event store's internal key, the
federation health-check secret and the ledger broker's password and record key. It also writes
`ALLOWED_ORIGINS=["http://localhost:8000"]`, which suits a trial on this host. `my-registry` becomes
`REGISTRY_NAME`, the prefix of every container name.

For a trial on this host, add two lines to `.env.operator`:

```bash
# your unit's ticker; unset, the code falls back to its historical default
FRAME_CURRENCY=MYU
# the generated mail settings are placeholders and send nothing
REQUIRE_EMAIL_VERIFICATION=false
```

For a registry other people reach, set these as well, before the first start:

| Variable | Why |
|----------|-----|
| `BASE_URL` | your registry's `https://` address. A value that is not `localhost` switches on the registry's production checks, and the next three rows are what those checks ask of a standalone registry |
| `ALLOWED_ORIGINS` | your `https://` address in the JSON list the generator wrote, such as `["https://registry.example.org"]`. The production checks refuse the wildcard |
| `FEDERATION_HEALTH_CHECK_SECRET` | written by the generator: keep it. The standalone compose runs the registry as a central registry (`IS_CENTRAL_REGISTRY=true`), and the production checks refuse one without this secret |
| `MAIL_*` | a working SMTP account, or no mail at all: `MAIL_DISABLED=true` with `MAIL_USERNAME` left empty, plus `REQUIRE_EMAIL_VERIFICATION=false` and `BETA_INVITE_REQUIRED=true`. Chapter 02 has the three mail postures |
| `TRUST_DOMAIN` | your DNS name. The registry signs its card with it and issues its agents' DIDs under it; the generated `<name>.local` suits a local trial only |
| `REGISTRY_HTTP_PORT` | only if host port 8000 is taken |

A registry whose production checks fail does not start, and its log names each missing value.

::: info The standalone ledger takes the internal key
The event store requires mutual TLS for writes unless it is told otherwise, and a standalone stack has no TLS terminator
in front of it, so the standalone compose sets `EVENTSTORE_INTERNAL_KEY_WRITES: "allow"` on its `event-store` service:
the registry and the TEG write with the internal key on the stack's own network. A kit older than 1.0.0-beta.21 lacks
that line, and its store refuses every event the registry writes (`403 mtls_required`); add it there under
`environment:` of the `event-store` service before the first start.
:::

---

## Boot the Stack

```bash
docker compose -f docker-compose.standalone.yml --env-file .env.operator up -d
docker logs my-registry-registry 2>&1 | grep -A3 "FIRST-BOOT ADMIN PASSWORD"
```

The first start creates the databases and runs the migrations. The registry then creates its first admin,
`admin@<registry-name>.dev`, and prints a random password to its log, once. To choose them yourself, set
`FIRST_ADMIN_EMAIL` and `FIRST_ADMIN_PASSWORD` in `.env.operator` before the first start. Change the password before the
registry is reachable from outside, and put your own TLS reverse proxy in front of it: the registry serves plain HTTP
on port 8000.

---

## Verify Health

```bash
docker compose -f docker-compose.standalone.yml --env-file .env.operator ps
curl -s http://localhost:8000/health
```

Every service should be running, and `redpanda-init` should have exited with code 0: it creates the ledger's topics once
and stops. `/health` answers `{"status": "ok", "event_store": {...}}`.

A standalone treasury starts empty. Log in as the admin and issue the initial supply:

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=admin@my-registry.dev" \
  --data-urlencode "password=<first-boot password>"

curl -s -X POST http://localhost:8000/api/v1/teg/treasury/mint \
  -H "Authorization: Bearer <admin access_token>" \
  -H "Content-Type: application/json" \
  -d '{"amount": "1000000", "reason": "initial supply"}'
```

The units go to the system treasury. Genesis grants are paid from the registry's own accounts, so until they hold
units a new agent's grant cannot be paid in full. Then read the supply invariant:

```bash
curl -s http://localhost:8000/api/v1/public/supply-invariant
```

`"status": "OK"` and `"delta": 0.0`, with a `total_circulating` equal to what you issued, mean the ledger recorded the
issuance and accounts for every unit (chapter 01, *The Ledger and the Supply Audit*). An empty ledger also reads a delta of
0, so check the total.

---

## Register a Developer and Create an Agent

```bash
# 1. Register (the password needs 12 characters with upper and lower case, a digit and a special character;
#    tos_accepted records the person's acceptance of the terms; a registry that requires invites also wants "invite_code")
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"name": "my-developer", "email": "dev@example.com", "password": "<your password>", "tos_accepted": true, "age_confirmed": true}'

# 2. Log in (form-encoded) and keep the access_token
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=dev@example.com" \
  --data-urlencode "password=<your password>"

# 3. Ask for a bootstrap token (single use, valid for 5 minutes)
curl -s -X POST http://localhost:8000/api/v1/onboard/bootstrap/request-token \
  -H "Authorization: Bearer <developer access_token>" \
  -H "Content-Type: application/json" \
  -d '{}'

# 4. Create the agent with it
curl -s -X POST http://localhost:8000/api/v1/onboard/create_agent \
  -H "Bootstrap-Token: <bootstrap_token>" \
  -H "Content-Type: application/json" \
  -d '{"agent_did_method": "theprotocol", "agent_host": "https://my-agent.example.com"}'
```

The registration answer carries the account's recovery keys, shown once. While `REQUIRE_EMAIL_VERIFICATION` is on (the
default), the login answers 403 until the developer follows the mailed link; on a registry that sends no mail, the admin
verifies the account instead (`POST /api/v1/admin/developers/{id}/force-email-verify`, the id from
`GET /api/v1/admin/developers?search=dev@example.com`). The agent's answer carries its `agent_did`, its `client_id` and
its `client_secret`: the secret is shown once, so store it. `agent_host` is where the agent will serve
`/.well-known/agent-card.json`; the registry keeps a placeholder card until the agent answers there.

---

## What's Running Now

Twelve services: `registry`, `teg-layer`, `event-store`, their three PostgreSQL databases (`db`, `teg-db`, `es-db`),
`pgbouncer`, `redis`, the ledger's broker `redpanda` with its one-shot `redpanda-init`, `opa` (in shadow) and the solo
`auditor` (on `127.0.0.1:8045`). There is no SPIRE agent, no cert-writer and no federation gateway, so a standalone
registry does not federate. Chapter 01 describes each piece and what a frame and a cloud operator add. Prometheus,
Alertmanager and Grafana come as a second compose file, `docker-compose.monitoring.yml`, on the loopback ports 9090,
9093 and 3000.

---

## A Frame on Your Own Host

A frame is the whole sovereign stack under your own DNS name: registry, TEG, ledger, its own SPIRE server, the mTLS
gateways, the auditor, the federated directory and the monitoring kit. It federates with other frames through the
invitation rail. You need one Linux host with 8 GiB of free memory (16 GB of RAM is comfortable) and 20 GB of free
disk, Python 3.10 or newer with the Docker SDK (`python3-docker`, or `pip install docker`), a DNS name that resolves to
it, ports 80 and 443 open for the edge's Let's Encrypt certificate (or `--edge-tls internal` on a test host), and an SMTP
account (or `--posture sandbox`, which mails nobody). Run the scripts as root: they
write under the stack root (`--stack-root`, default `/opt/theprotocol/stack`) and drive Docker.

```bash
cd scripts/distribution
./build.sh       # or skip the build: frame-up pulls a release's six images with
                 #   --images-prefix images.theprotocol.cloud/theprotocol --version <release> (pass both to the doctor too)
./frame-doctor.py --public-name frame.example.org
./frame-up.py --name myframe --public-name frame.example.org --ticker MYF --currency-name "My Unit" \
    --admin-email admin@example.org --location-label "Lisbon" --lat 38.7223 --lng -9.1393 \
    --mail-server smtp.example.org --mail-address noreply@example.org \
    --mail-token-file <file holding the SMTP password> --accept-terms
```

Joining the network as a frame operator means accepting the Federation Operator Terms (read them at
<https://theprotocol.cloud/#/legal/operators>). `frame-up.py` asks for that acceptance before it creates anything, and
your frame's registry records it with the admin account it issues, at the version it serves. Run without a terminal,
`--accept-terms` says you accept them; without the flag and without a terminal, `frame-up.py` refuses to start.

`frame-doctor.py` writes nothing: it names every missing precondition (Docker and the Compose plugin, the six images,
memory and disk, the five public ports, the DNS name pointing at this host), and `frame-up.py` runs the same checks
first. A production frame also refuses to start without the mail relay and without its location, because its signed
card publishes the location. `frame-up.py` then starts the stack and its public edge (Caddy) and prints four addresses:
the console, the federation lane (8443), the SPIRE bundle endpoint (8444) and the ledger gateway (8445). Open the edge
ports and those three lanes, nothing else. The admin's first password and the frame's other secrets are written to
`<stack root>/myframe-secrets` and never printed. `--posture sandbox` stands a frame up without a mail relay,
`--edge-tls internal` uses Caddy's own CA on a host that cannot answer on 80 and 443, and `--with-runner` also installs
the frame runner, so the frame can provision cloud operators on the same host.

To federate, `frame-federate.py --stack-dir <stack dir> --with <a peer's console URL> --admin-secret-file <stack root>/myframe-secrets/.myframe_frame_admin.secret.json`
 sends the invitation and applies the licence the peer
delivers once its admin approves. It waits up to 20 minutes (`--timeout-min`) and exits with code 4 while the
invitation is pending; run it again later and it resumes. *Federating a Frame* (chapter 15) walks every call.
`frame-down.py --name myframe` removes the frame.

---

## A Cloud Operator Under a Frame

A cloud operator runs on the host of the frame it joins, which builds and starts its stack. Nothing runs on your side:

1. **Apply** on the frame's console (its Operator page, `POST /api/v1/operator-applications`).
2. **The frame's admin approves** the application. You receive a one-time activation code by mail, valid for 7 days.
3. **Activate** with that code, signed in as a developer on that frame (`POST /api/v1/operators/activate`). The frame
   registers your operator's SPIRE identity and builds its bundle.
4. **The frame's admin provisions** the operator. The frame's runner starts your stack on the frame's host, and the
   frame's admin receives your registry's first admin login, once, in the provisioning answer.

The bundle you can download afterwards (`GET /api/v1/operators/my-bundle`) is not a stack that runs on its own: its
compose gives the registry and the TEG a fixed ledger address (`EVENT_STORE_URL`), a line only the frame's
provisioner replaces with the frame's own ledger gateway. Since the frame kit 1.0.0-beta.21 its generator writes the
per-operator secrets (`REDIS_PASSWORD_REGISTRY`, `REDIS_PASSWORD_TEG`, `REGISTRY_PROXY_TRUST_SECRET`,
`TEG_PROXY_TRUST_SECRET`), the Redis access list and the terminators' markers itself, for an operator name that does
not start with `cloud-op-`; for a cloud operator the frame writes them. [Run Your Own Registry](/docs/17) walks the
whole provisioning.

---

## Learn by Doing: Guided Tours

::: tip Guided tours ship with your registry
**API Tutorials** in the menu (`/ui#/tutorials`) lists the guided tours: each one spotlights the real interface step by
step, so what you learn is what your users see. Start with **First Steps**. The operator tours, starting with
Operator: First Steps, open only to accounts with admin rights. A tour about a feature your registry has switched off is
not offered.
:::

---

## Hand It to an Assistant

Your registry documents itself for AI assistants: `GET <your-registry-url>/api/v1/downloads/CLAUDE.md` returns an
operator manual with this registry's URL, name, role, unit and trust domain filled in, and the registry speaks MCP
(`POST /mcp/rpc`). Paste the manual into an assistant, or connect Claude Code with the downloadable stdio bridge:
*AI Assistants & MCP* (chapter 13) is the short version of that setup.

---

## Next Steps

- **Architecture** (chapter 01): the containers of each shape, the identity fabric and the data flows
- **Configuration** (chapter 02): the environment variables an operator sets
- **Federation Guide** (chapter 03): how a registry connects to its peers
- **Sovereign Frames** (chapter 11): what a frame runs that an operator does not
- **The tp Host CLI** (chapter 12): day-2 operations from the host
- **Federating a Frame** (chapter 15): the invitation, call by call
