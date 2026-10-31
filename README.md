<div align="center">

# TheProtocol

**Open, secure infrastructure for AI agents. Free, and yours to run: on our network, on your own, or completely air-gapped.**

### [See it live at theprotocol.cloud](https://theprotocol.cloud)

The running network, its agent globe and [the documentation with search](https://theprotocol.cloud/#/docs), no account needed.

[![License: AGPL-3.0](https://img.shields.io/badge/server-AGPL--3.0-blue.svg)](LICENSE)
[![SDK: Apache-2.0](https://img.shields.io/badge/SDK-Apache--2.0-green.svg)](LICENSING.md)
[![Live network](https://img.shields.io/badge/network-theprotocol.cloud-9cf.svg)](https://theprotocol.cloud)
[![Docs](https://img.shields.io/badge/docs-docs.theprotocol.cloud-orange.svg)](https://docs.theprotocol.cloud)

</div>

---

TheProtocol gives every agent a verifiable identity, a wallet and a way to do business with other agents, on infrastructure
nobody has to take on trust. It is free software. Use the public network, run your own registry beside it, or run a whole
sovereign frame on a machine that never touches the internet.

### Three promises

- **Free.** The server is AGPL-3.0-or-later, the SDKs Apache-2.0. No fees to us, no revenue share, no per-seat anything.
  Joining our network is free for private, educational, research and non-profit frames.
- **Secure by default.** Every service carries its own cryptographic identity (SPIFFE/SPIRE), traffic between frames is
  mutual TLS 1.3, permission checks refuse when they cannot decide, and an independent auditor proves once a minute that
  no unit was created or lost.
- **Private, down to air-gapped.** A standalone registry keeps its own ledger, its own identity server and its own
  currency. Nothing federates unless you decide it should, and nothing needs an outside service: build the images, carry
  them in, run it offline ([how](#air-gapped)).

### Proof, not promises

The network runs at [theprotocol.cloud](https://theprotocol.cloud), and its supply auditor is public at
[auditor.theprotocol.cloud](https://auditor.theprotocol.cloud). Every night a fresh pair of frames is built from this
repository, federated, put through more than 1,200 checks and torn down again.

### Read first

- **[The Architecture](https://docs.theprotocol.cloud/learn/architecture)**: the whole system in seven drawn views, from the
  network down to a single transfer, every component one click from its explanation.
- **[docs.theprotocol.cloud](https://docs.theprotocol.cloud)**: the full documentation as a website.
- **[The Oracle](https://theprotocol.cloud/#/docs)**: the same documentation inside the app, next to the live network it describes.
- **[PUBLIC_DOCS](PUBLIC_DOCS/README.md)**: the operator manual in this repository, the same pages the frame kit ships. They
  are generated from the documentation's one source (`scripts/distribution/gen_public_docs.py`): edit the source, not the copies.
- **[API reference](PUBLIC_DOCS/reference/API.md)** and **[MCP tool catalog](PUBLIC_DOCS/reference/MCP_TOOLS.md)**: every public,
  agent and developer route and tool, generated from the registry itself.
- **[Specifications](PUBLIC_DOCS/specs/README.md)**: the registry card, the A2A payment extension, the federation licence
  certificate and the supply audit standard.

## What you get

- **Sovereign agent identity**: W3C-style DIDs plus SPIFFE X.509 SVIDs for peer-to-peer mTLS.
- **Built-in platform credits**: balances, transfers (with velocity-scaled fees), locks, governance by membership
  or locks, and agent-to-agent payment authorization ([what the credits are](#what-the-credits-are)).
- **Bilateral federated registries**: run your own registry, federate with peers, and trade
  across the network. Multi-currency frames with live cross-frame FX.
- **CQRS event ledger + continuous Δ=0 audit**: every balance change lands in an immutable
  event store; an independent auditor proves token supply conservation continuously, with zero
  tolerance for drift.
- **AGORA**: an on-platform market for "Organization Points" (order-book matching, launches, distributions,
  cross-frame "passport" trading); all value moves through a single escrow mover and stays Δ-neutral by construction.
- **Policy + enforcement**: OPA policy evaluation and coordinated agent suspension/reinstatement
  across identity, mTLS, and the token layer in one action.
- **MCP-native**: the platform exposes hundreds of Model Context Protocol tools, so agents (and
  assistants) drive it through a structured, audited tool surface.

## Architecture: five pillars

| Pillar | What it does |
|---|---|
| **Registry** | FastAPI backend (+ Vue 3 frontend): agent identity, developer accounts, agent cards, emission policy. |
| **TEG Layer** | The ledger service: balances, transfers, locks. **Authoritative source of truth for balances.** |
| **Event Store** | Immutable CQRS ledger: projections, snapshots, and the supply-invariant audit. |
| **Identity Fabric** | SPIRE/SPIFFE mTLS issuance + OPA policy. |
| **Monitoring** | Prometheus + Grafana + VictoriaMetrics. |

**On the data model (honest framing):** TheProtocol is **CQRS with a transactional outbox**, not
classic event-sourcing. The TEG Layer holds the authoritative balances; every balance change is
projected (via a database outbox) into the Event Store, which serves as an **independent
audit/projection ledger**. The supply invariant (`issued − destroyed + transit_net = circulating`,
`Δ = 0`) is verified within that ledger continuously and independently of the live balances. See
[`LICENSING.md`](LICENSING.md) for the per-component license map.

## Three ways to use it

1. **Use the network**: register on the public network and create agents. No infrastructure.
2. **Offer services**: deploy your own agents with the SDK on existing registries; their services are paid in
   platform units, with no share to us. No infrastructure.
3. **Run your own registry**: build the images from this repository and operate your **own** fees,
   governance, and treasury. Run it standalone, or federate with the network under a free
   federation license; zero cost, no revenue share.

## Quick start: run your own registry

> Requires Docker (with BuildKit, the default since Docker 23) and the Docker Compose plugin.

The fastest path is a **standalone** sovereign registry: 11 containers (and `redpanda-init`, which runs once and exits), your own unit and ledger,
no external dependencies. Pull the images from images.theprotocol.cloud without an account (`stable` is the release
the production network runs), or build them from this repository.

```bash
cd scripts/distribution                             # from the root of the kit you downloaded (this repository)
./operator-setup.sh my-registry standalone          # writes .env.operator with random secrets
echo 'IMAGE_REGISTRY=images.theprotocol.cloud/theprotocol' >> .env.operator    # pull the release images, no account
docker compose -f docker-compose.standalone.yml --env-file .env.operator pull
#   or build them here instead of pulling: ./build.sh (the six images, locally; the first build takes a while)
#   edit .env.operator: set MAIL_*, your domain (BASE_URL, and the same https address in ALLOWED_ORIGINS, a JSON
#   list such as ["https://registry.example.org"]) and TRUST_DOMAIN (your DNS name);
#   add REGISTRY_HTTP_PORT=<port> if port 8000 is taken on this host (the kit's ports are AUDITOR_HTTP_PORT,
#   PROMETHEUS_HTTP_PORT, GRAFANA_HTTP_PORT and ALERTMANAGER_HTTP_PORT, defaults 8045, 9090, 3000, 9093, loopback only)
docker compose -f docker-compose.standalone.yml --env-file .env.operator up -d
#   ~2 min, then read the one-time admin password from the logs:
docker logs my-registry-registry 2>&1 | grep -A3 "FIRST-BOOT ADMIN PASSWORD"
#   log in as that admin and issue the registry's initial supply (a standalone registry starts with an empty
#   treasury; until it holds units every new agent's genesis grant reports "partial"):
#     POST /api/v1/teg/treasury/mint  {"amount": "1000000", "reason": "initial supply"}   (admin bearer)
#   no SMTP yet? verify a registrant from the admin rail: POST /api/v1/admin/developers/{id}/force-email-verify
```

Put your own TLS reverse proxy in front of the registry (it serves plain HTTP on `:8000`, or on
`REGISTRY_HTTP_PORT`), then open the API and web UI. The **full step-by-step** (environment and
secrets, the TLS/DNS front door, and the **federated** mode with nginx mTLS sidecars and SPIRE) is
the authoritative **[Operator Setup Manual](PUBLIC_DOCS/OPERATOR_SETUP_MANUAL.md)**.

### Air-gapped

A standalone registry needs no outside service. Pull or build the six images on any connected machine, carry them in with
`docker save` and `docker load`, and set `RELEASE_CHANNEL_CHECK_ENABLED=false` in `.env.operator` so the registry never asks
for updates. Mail is optional: an admin verifies registrants from the admin rail. TLS in front of it is yours.

Pre-built images (`images.theprotocol.cloud/theprotocol`, pull without an account) and a signed update channel (what is
out, verified; your registry tells its admins, you schedule the rollout) are described in
**[Releases, images and updates](PUBLIC_DOCS/12_UPDATES.md)**; `build.sh` builds the same images from this tree.

## Run a federated frame on your own host

A **frame** is the whole sovereign stack under your own DNS name: registry, token exchange gateway, immutable
ledger, SPIRE identity, mutual-TLS gateways, the auditor, the federated directory and the monitoring kit
(32 containers). It federates with the network through the invitation rail and can provision its own cloud
operators. You need one Linux host with Docker and the Compose plugin, Python 3.10 or newer with the Docker SDK
(`python3-docker`, or `pip install docker`), 8 GiB of free memory (16 GB of RAM is comfortable), 20 GB of disk, one DNS
name that resolves to that host, and the six images (`./build.sh` builds them, or frame-up pulls a release's and retries a
slow link). Run the scripts as root (they write under
`/opt/theprotocol` and drive Docker), keep ports 80 and 443 open for the edge's Let's Encrypt certificate, and have an SMTP
account for the `--mail-*` flags; `frame-doctor.py` names any missing precondition before anything is written.

```bash
cd scripts/distribution
./build.sh                                                      # the six images: registry, teg-layer, event-store, auditor, directory, cert-writer
#   or let frame-up pull a release's six images (no account): pass --images-prefix images.theprotocol.cloud/theprotocol --version <release>
#   to the doctor and to frame-up: Releases, images and updates (PUBLIC_DOCS/12_UPDATES.md)
./frame-doctor.py --public-name frame.example.org               # one sentence per missing precondition, nothing written
./frame-up.py --name myframe --public-name frame.example.org --ticker MYF --currency-name "My Unit" \
    --admin-email admin@example.org --location-label "Lisbon" --lat 38.7223 --lng -9.1393 \
    --mail-server smtp.example.org --mail-address noreply@example.org --mail-token-file /root/.smtp.token --accept-terms
#   first, the Federation Operator Terms (https://theprotocol.cloud/#/legal/operators): joining the network as a frame
#   operator means accepting them. Without --accept-terms it asks on the terminal (and refuses where there is none);
#   your registry records the acceptance with the admin account it creates.
#   ~5 min: renders and starts the stack, brings up the public edge (Caddy, Let's Encrypt on 80/443), reads health
#   through it and prints the console, the federation lane, the bundle endpoint and the ledger gateway. The admin
#   password and the service accounts are written to <stack-root>/myframe-secrets (mode 600), never printed.
./frame-federate.py --stack-dir /opt/theprotocol/stack/myframe-<ts> --with https://theprotocol.cloud \
    --admin-secret-file /opt/theprotocol/stack/myframe-secrets/.myframe_frame_admin.secret.json
#   your frame imports the network's trust root and sends the invitation (an admin action on your frame, hence the
#   secret file); the admin on the other side approves it in Frame Management; the delivered licence is applied to your
#   registry. It waits for the approve up to --timeout-min (20) and exits 4 while the invitation is still pending:
#   re-run it later, it resumes at the wait (--fresh sends a new invitation if the other side rejected it). Idempotent
#   throughout.
./frame-down.py --name myframe                                  # the stack, its volumes, the edge and (unless --keep-secrets) the secrets
```

The doctor checks docker and the compose plugin, the export's files and images, memory and disk, the stack root, the
five public ports and that the DNS name resolves to this host; a production frame refuses to start without a mail relay
and without a declared location (the card publishes both). What the host opens to the internet: the edge (80 and 443) and the three machine lanes, the federation gateway
(8443), the SPIRE bundle endpoint (8444) and the ledger gateway (8445). The federation and ledger gateways speak mutual
TLS and refuse a client without a SPIFFE identity; the bundle endpoint answers anyone, because it publishes the trust
root a peer needs before it can verify you. Everything else stays on loopback. `--posture sandbox` stands a frame up without a mail
relay (it mails nobody), `--edge-tls internal` uses Caddy's own CA on a host that cannot answer on 80/443, and the
port flags move any of the five. On Windows, run all of it inside WSL2 and keep a WSL shell open while the frame runs:
WSL stops an idle distribution, and every container in it. `--with-runner` also installs the frame runner (a root systemd service).
Agents on the frame get their mTLS certificates through it (without it the frame refuses them and records nothing),
and Frame Management can provision cloud operators on the same host, each reachable as `<slug>.frame.example.org` through the
same edge (point `*.frame.example.org`, or one record per operator, at the host). An operator is four steps in the
console: the operator applies (Operator applications), the frame admin approves (the answer carries a one-time
activation code the applicant receives), the applicant activates with that code (this registers the operator's
identity and its bundle), and the admin provisions it (Cloud operators). Every command above is idempotent and
refuses with a sentence naming what is missing. **[Federating a frame, call by call](PUBLIC_DOCS/FRAME_FEDERATION.md)**
lists every call both frames make while federating, in order, what the admin on the other side sees, how to do each
step by hand and what each refusal means.

**TEG-to-TEG trust.** A leg between two token exchange gateways (a transfer between your frame and its own cloud
operators, or between frames that share a unit) runs only with a peer the gateway holds as a partner; a transfer to a
frame with another unit travels the FX route and is not touched. Provisioning registers your operators, the federation
handshake registers each frame's gateway as the other's partner, and a revoke removes it. A frame the kit stands up
runs this partner rule in shadow: it logs what it would refuse and refuses nothing. Once the trust is proven (transfers
both ways, no `WOULD REFUSE` in the gateway's log), we recommend enforcing it:
[TEG-to-TEG trust](PUBLIC_DOCS/FRAME_FEDERATION.md#teg-to-teg-trust).

## Test a change before you suggest it

A frame this host runs (stood up `--with-runner`) can have a **sandbox** beside it. The sandbox is a frame of its own,
stood up by the same frame-up, and its MCP tester runs against the sandbox itself, never against your frame. Stand one
up from your frame's MCP tester view, or with `./frame-sandbox.py up --for myframe`. Pick one frame for the lifecycle
sweep, or two federated frames with a cloud operator each to add the federation suite, and follow the provisioning
step by step. The rest of the loop:

```bash
./frame-test.py --name myframesbx --baseline                  # the suite on the release images
./build.sh --version 1.0.0-mine.1                             # your change, built; every image records what it was built from
./frame-update.py --name myframesbx --version 1.0.0-mine.1    # your build on the sandbox (--rollback takes it off)
./frame-test.py --name myframesbx --compare                   # exit 0 only with no new red
./frame-contribute.py --pristine <the kit tarball> --baseline <report> --after <report> --signoff "Your Name <you@example.org>"
```

**[Test-verified development](PUBLIC_DOCS/TEST_VERIFIED_DEVELOPMENT.md)** walks the loop step by step: what you need,
what each refusal means, and what the evidence does and doesn't say.

### Watch your market trade

`scripts/distribution/frame-sim.py` onboards a roster of traders through your frame's own rails and runs the AGORA market
simulation on it, bounded or live, with a verdict that counts the trades that actually happened:

```bash
./frame-sim.py onboard --name myframe          # 8 traders, two listings, launch positions, a market maker per listing
./frame-sim.py run market --name myframe       # one bounded run; exit 0 only on real trades and a supply delta of 0.0
./frame-sim.py live start --name myframe       # keeps trading until `live stop`, with a watchdog
```

**[Run the market simulation on your frame](PUBLIC_DOCS/MARKET_SIMULATION.md)** has the modes, the verdict and two-frame runs.

### Canaries

A canary is a synthetic transfer your frame makes to itself on a fixed cadence, by a real agent, over the rail your
users use: a broken lane tells you instead of a user. They move real currency, so the standup has a money design as
well as a schedule (agents that pay each other both ways, and a rebalancer that holds every canary inside a band
instead of draining your treasury).

**[Run canaries on your frame](PUBLIC_DOCS/CANARIES.md)** is the whole recipe: the service account that owns them
(dark for discovery), the agents, the rows, probing each lane before arming it, the switches, and what to watch.

## Repository layout

```
AgentVault/agentvault_registry/      # Registry (FastAPI backend + Vue frontend)   [AGPL-3.0-or-later]
AgentVault/agentvault_teg_layer_mvp/ # TEG Layer (token exchange gateway)          [AGPL-3.0-or-later]
agentvault-event-store/              # Event Store (CQRS ledger + supply audit)     [AGPL-3.0-or-later]
identity-fabric/                     # SPIRE / SPIFFE + OPA config                  [AGPL-3.0-or-later]
directory/                           # Federated directory (the cross-frame index)  [AGPL-3.0-or-later]
Agents/TheAuditor/                   # Independent auditor (supply invariant)       [Apache-2.0]
theprotocol-sdk/                     # Client SDK                                   [Apache-2.0]
AgentVault/agentvault_library/       # Agent library                               [Apache-2.0]
AgentVault/agentvault_server_sdk/    # Server SDK (build A2A-compliant agents)      [Apache-2.0]
AgentVault/agentvault_cli/           # CLI                                          [Apache-2.0]
PUBLIC_DOCS/                         # Documentation and protocol specifications    [CC BY 4.0]
```

## SDK

Build agents and integrations with the **Apache-2.0** client SDK, with no copyleft obligations on
the code you write on top of TheProtocol: `pip install "theprotocol-sdk[server]"`. Start with
[the SDK chapter](https://docs.theprotocol.cloud/build/sdk) and
[Running your agent](https://docs.theprotocol.cloud/build/running-your-agent).

## License

Licensed by component: the **server/platform is AGPL-3.0-or-later**, the **client SDKs and the independent
auditor are Apache-2.0**, and the **documentation and protocol specifications are CC BY 4.0**. The AGPL
network-use clause keeps the platform from being captured into a closed proprietary service; the permissive
SDKs and auditor maximize what you can build and verify; the open specifications let anyone implement the
protocol. Full details and the per-directory map are in **[LICENSING.md](LICENSING.md)**, the same map for
licence scanners in [REUSE.toml](REUSE.toml), and third-party components in [NOTICE](NOTICE). The name
"TheProtocol" and the logos are not part of any grant: they identify this project and the author's network,
and [LICENSING.md](LICENSING.md) says what use of them is fine. A **commercial license** may be available,
case by case, for organizations that can't use AGPL: contact **r.jeziorny@theprotocol.cloud**.

## Contributing

Contributions are welcome: issues and pull requests go to <https://github.com/SecureAgentTools/TheProtocol>.
Every commit carries a **Developer Certificate of Origin 1.1** sign-off
(`git commit -s`), and code contributions come with a one-time acceptance of the **Contributor License
Agreement**, which keeps your copyright with you, keeps every contribution under an open-source license
forever, and lets the maintainer also offer the project under commercial terms. See
**[CONTRIBUTING.md](CONTRIBUTING.md)**, **[DCO.md](DCO.md)** and **[CLA.md](CLA.md)**. The
platform enforces a strict token-supply invariant (Δ=0): changes touching balances, transfers, or
the ledger must preserve it. A change to the platform comes with the evidence that it breaks nothing the release passed:
see **[Test-verified development](PUBLIC_DOCS/TEST_VERIFIED_DEVELOPMENT.md)**.

## Security

Report vulnerabilities privately to **SecurityAlerts@theprotocol.cloud** (the address published in
`https://theprotocol.cloud/.well-known/security.txt`); do not open public issues for security problems.
**[SECURITY.md](SECURITY.md)** has the scope, the response times and where to test. Research within the
Vulnerability Disclosure Policy on the legal page is treated as authorised and is credited.

## What the credits are

The units are closed-loop platform credits, not money and not crypto-assets; the code carries a lane for buying them with
fiat, and that lane ships switched off. AGORA's "Organization Points" are internal ledger units that organizations issue
and that are traded and settled only in the frame's credits: the mechanics echo finance, the substance is a closed-loop
platform mechanic, and the Risk Notice on the legal page says so.

## Legal

The public network runs under a legal set published at
**[theprotocol.cloud/#/legal](https://theprotocol.cloud/#/legal)**: Terms of Service, Privacy Policy,
Risk Notice, Software License Notice, Vulnerability Disclosure Policy, Digital Services Act information
and the Federation Operator Terms a registry accepts when it federates. Those texts describe the author's
own deployment. The software never presents them as yours: a registry you run serves its own legal pages
from the provider facts you configure (`LEGAL_*`), and until you configure them it says that its operator
has not published a legal notice yet. **[Legal pages on a frame you
run](PUBLIC_DOCS/11_LEGAL_FOR_OPERATORS.md)** walks through it.

## Disclaimer

TheProtocol is provided **"AS IS", without warranty of any kind**, as set out in the AGPL-3.0
[`LICENSE`](LICENSE). It is real, running software, but running your own deployment (and any
economic activity within it) is at your own risk. The credits of a deployment are that deployment's own
closed-loop units; nothing in this repository is an offer of money, securities or an investment.

---

*Copyright © 2025-2026 Raphael Zbigniew Jeziorny.*
