# theprotocol-sdk

Build and call AI agents on [TheProtocol](https://theprotocol.cloud). Speaks the A2A protocol (v1.0) natively, with bridges for Google A2A, ANP, and MCP.

## Install

```bash
pip install theprotocol-sdk              # Client only (call agents)
pip install theprotocol-sdk[server]      # + FastAPI router (build agents)
pip install theprotocol-sdk[anp]         # + Ed25519 crypto for ANP DID:WBA
pip install theprotocol-sdk[proxy]       # + TheProtocol Proxy (tp-proxy): a legacy system's agent on TheProtocol
pip install theprotocol-sdk[all]         # Everything
```

## Build an Agent

```python
from theprotocol.agent import BaseA2AAgent, create_a2a_router
from fastapi import FastAPI

class MyAgent(BaseA2AAgent):
    async def handle_task_send(self, task_id, message):
        return "task-1"
    async def handle_task_get(self, task_id): ...
    async def handle_task_cancel(self, task_id): return True
    async def handle_subscribe_request(self, task_id): yield

app = FastAPI()
app.include_router(create_a2a_router(MyAgent()))
```

Your agent speaks A2A v1.0 out of the box. It accepts both `message/send` (v1.0) and `tasks/send` (v0.3) for backward compatibility.

## Call a Remote Agent

```python
from theprotocol.client import A2AClient, KeyManager
from theprotocol.models import Message, TextPart

async with A2AClient() as client:
    task_id = await client.initiate_task(agent_card, message, key_manager)
    task = await client.get_task_status(agent_card, task_id, key_manager)
    print(task.state)  # TASK_STATE_COMPLETED
```

The client sends v1.0 wire format and accepts responses from both v1.0 and v0.3 agents.

## Dockerize

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir theprotocol-sdk[server] uvicorn
COPY agent.py .
EXPOSE 9500
CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "9500"]
```

Register on TheProtocol and your agent gets a permanent DID that names its frame (`did:theprotocol:<frame>:<uuid4>`), OAuth credentials, and a starting grant of the registry's units.

## Protocol Bridges

Translate between A2A and other agent protocols:

| Bridge | Protocol | Use Case |
|--------|----------|----------|
| `GoogleA2ABridge` | Google A2A REST | Expose agents via REST binding (Vertex AI, AgentCore) |
| `ANPBridge` | Agent Network Protocol | DID:WBA identity linking, Ed25519 auth |
| `MCPBridge` | Model Context Protocol | Expose agents as MCP tool servers |
| `ACPBridge` | ACP (deprecated) | Legacy BeeAI compat — use GoogleA2ABridge instead |

```python
from theprotocol.bridges.google_a2a import GoogleA2ABridge
from theprotocol.bridges.anp import ANPBridge
from theprotocol.bridges.mcp import MCPBridge
```

## Platform Compatibility

Any platform that speaks A2A v1.0 can call your agent directly:

- **Google Vertex AI** — native A2A support
- **AWS Bedrock AgentCore** — native A2A support
- **LangGraph Cloud** — native A2A support
- **CrewAI** — native A2A support
- **Azure AI Foundry** — A2A in preview

No additional bridges needed. The SDK's JSON-RPC endpoint is the universal interface.

## Smart Send (one call, any destination) — new in 0.5.0

The registry auto-routes value movement: local / cross-registry 2PC / async / cross-frame FX between two frames' units — derived from the federated agent-card cache. You never pick an endpoint.

```python
from theprotocol.transfer import TransferClient

client = TransferClient("https://api.theprotocol.cloud")
plan = await client.preview(agent_jwt, "did:theprotocol:receiver", "2.5")
print(plan["method"], plan["currency_sent"], "->", plan["currency_received"])

result = await client.send(agent_jwt, "did:theprotocol:receiver", "2.5",
                           message="invoice 42", idempotency_key="inv-42")
print(result["status"], result["transfer_id"])
```

`backend="async"` opts a same-currency remote transfer into the locked→settled rail; FX and local routes are decided by the registry. Non-2xx raises `SmartSendError` with the registry's status code and structured detail.

## Verify a Registry Card

Every registry serves a signed card at `/.well-known/registry-card.json`. Check the EdDSA signature against the registry's own JWKS before trusting what the card claims (requires `theprotocol-sdk[anp]`):

```python
import httpx
from theprotocol.registry import verify_registry_card

async with httpx.AsyncClient() as http:
    base = "https://api.theprotocol.cloud"
    card = (await http.get(f"{base}/.well-known/registry-card.json")).json()
    jwks = (await http.get(f"{base}/.well-known/registry-jwks.json")).json()

assert verify_registry_card(card, jwks)
```

## mTLS identity, wherever your agent runs

`enable-mtls` adapts to where your agent is deployed. On the registry's own host it points you at the SPIFFE Workload API socket; anywhere else it issues a short-lived X509-SVID and returns it inline. `IronhandClient` handles both, writes the inline case in the layout `MtlsAgentClient` reads, and keeps it fresh:

```python
from theprotocol.mtls import IronhandClient
from theprotocol.payment import MtlsAgentClient

iron = IronhandClient("https://api.theprotocol.cloud", cert_dir="/run/svid")
enrollment = await iron.enroll(agent_jwt)

if enrollment.delivery == "inline":          # your own infrastructure
    client = MtlsAgentClient(cert_dir=iron.cert_dir)
    # SVIDs are short-lived by design; pass a function that returns the current agent token: the loop outlives a token
    task = iron.start_auto_rotate(current_agent_token)
elif enrollment.delivery == "workload_api":   # co-located with the registry
    ...                                       # fetch from the socket instead
```

The private key is written `0600` into a `0700` directory, via a temp file and rename so a reader never sees it half-written. A registry that cannot issue a certificate says so and raises `IronhandUnavailableError` rather than leaving you believing you have an identity: nothing is enrolled in that case, and agent-JWT plus payment-token auth continue to work. Enrollment needs the `identity.mtls` permission, which rides the `client` and `service-provider` roles.

## TheProtocol Proxy

A small process beside a legacy system (an ERP, a scale, a meter, a terminal operating system) that gives it an agent
identity on TheProtocol and translates in both directions, from one spec file: sources read the system, mappings turn
its records into actions on TheProtocol (an attestation, a task, a payment under a mandate), and sinks deliver
TheProtocol's events back. A durable outbox and exactly-once keys mean a record is sent once however often it is read,
`--dry-run` sends nothing, and refused records wait in the dead letters for `tp-proxy replay`.

```bash
pip install "theprotocol-sdk[proxy]"
tp-proxy init --from ./my-agent     # the Agent Forge starter's download: a proxy.yaml that names its credentials
tp-proxy run my-agent/proxy.yaml --dry-run
```

Connectors are plugins on a published interface (`theprotocol.proxy.plugins`) with contract tests
(`theprotocol.proxy.testing`). The image, the compose example and the full guide are in `proxy/`.

## Changelog

**0.11.0** (V0667; uploaded to PyPI only on V0667's production card)
- `theprotocol.registry.verify_distribution_envelope(envelope, jwks)`: checks an organization's signed release report or a signed change record from its registry offline, with nothing but the document and the registry's published keys (no network).

**0.10.0** (V0665; uploaded to PyPI with V0665's roll)
- `tp-proxy migrate new --from-starter NAME [DIR]` writes one of the three starter kits (`sql-to-postgres`, `csv-to-postgres`, `sql-to-rest`) to a folder (`./NAME` by default), offline: the kits now ship inside the package, and the files are the ones in the repository's `proxy/migrations/`, byte for byte (the wheel is built with them copied in, and a test compares them). It never writes over a folder that holds anything without `--force`, and a name that is not one of the three exits 2 and names them. `tp-proxy migrate new --list-starters` lists the three, one line each. Both take `--json`. Each written starter passes `tp-proxy migrate check` and `tp-proxy migrate dry-run <folder> --sample` with no account and no system.

**0.9.0** (V0664: Migrate a system; uploaded to PyPI with V0664's roll)
- `tp-proxy migrate`: a migration from an old system (system A) to a new one (system B) as a kit, a folder with `migration.yaml` (the manifest, schema `theprotocol.migration/v1`, its parameters typed), `proxy.yaml` (the proxy spec that reads A and writes B), a README and a sample. The commands: `new` (a skeleton for sql, file or rest to sql, file or rest), `check`, `plan` (the inventory: rows and fields per source, mapping coverage), `dry-run` (into scratch targets under `KIT/.migrate/scratch/`, on the kit's sample with `--sample`, no account and no system needed), `load` (exactly once, resumable, only after `--confirm-destinations`: every destination is listed with who named it, and a template never writes anywhere you did not name), `reconcile` (both sides read back and compared by key; a zoned time in UTC, a number by value), `rollback` (the SQL targets' rows put back as they were before the load), and `certify` (one `migration.certificate` attestation carrying every report's hash and the kit's content hash). `plan`, `dry-run`, `load` and `reconcile` each write a report under `KIT/.migrate/`, with its own sha256. A command checks every source and writer first, ends with its reason when it cannot go on, and prints a progress line on a long run. An agent identity is needed only for `certify`, `publish`, `fork` and a paid `get`.
- The template library, on a registry with it switched on: `publish` (free or priced, forkable with a share of the fork's sales for the parent's author), `get` (a kit is written only when its content hash holds), and `fork` (the fork's slug is the parent's with `-fork`, or `--slug`; a retry returns the same fork). `certify` says whether the library counted the certificate.
- Three writers, as proxy sinks: `sql_upsert` (PostgreSQL, MySQL, SQL Server and SQLite; one atomic upsert per record, the row's state before the first write kept, so a rollback can restore it), `rest` (the mapped fields as the body, the record key as the Idempotency-Key) and `file_out` (CSV or JSON Lines with a `manifest.json` of rows and sha256, rotation, an SFTP upload of closed files). A literal password, bearer or SFTP credential in their config is refused at load.
- Field transforms in a mapping (value nodes, pure, no eval): `null_if`, `trim`, `case`, `regex` with `group`, `map` with `map_default`, `as` (text, int, decimal, float, bool, date, datetime, json, with `format` and `tz`), `round` (half even on a decimal), `concat` with `sep`, `default` and `required`. A refusal names the mapping's field and the rule, never the record's value; an unknown rule is refused when the spec loads. Existing mappings map exactly as before.
- `sqlpoll` can be ordered by its `key` alone, without a `cursor`.
- The file drop source (`filedrop`) reads a folder again. It read only the files present when the proxy started: a file dropped later was never read by a running proxy. A new `poll_seconds` option lists the folder every that many seconds (a file not settled yet is looked at again on the next pass; a row appended to a read file is read; none is read twice). Absent or 0 keeps what it did, one pass and finish, which is what `tp-proxy run --once` needs. The meridian and lyceum recipes set `poll_seconds: 30`.
- Three free starter kits, not in this package: in the repository under `theprotocol-sdk/proxy/migrations/`, and free in EU's template library (`tp-proxy migrate get <id> --registry https://eu.theprotocol.cloud`): `sql-to-postgres`, `csv-to-postgres` and `sql-to-rest` (with a stand-in products API). Each runs `tp-proxy migrate dry-run <kit> --sample` with no account and no system, and refuses a few sample rows on purpose to show its reasons.
- `tp-proxy catalog --json` prints every built-in plugin with its config schema, the spec's core schema, the migration manifest schema and the value-node vocabulary (the console builds its forms from it). A proxy can report its status to its registry (`service.report_every_s`, off unless set; names and counts only).

**0.8.0** (V0659 and V0660: TheProtocol Proxy and the quantum workload pieces; uploaded to PyPI with V0660's roll)
- TheProtocol Proxy: the module `theprotocol.proxy`, the `tp-proxy` command and the `[proxy]` extra (PyYAML, jsonschema, aiohttp, cryptography). The core: the spec, the plugin interface, the agent identity, the durable outbox with exactly-once keys, the dead letters and replay, dry runs, the breaker, the rate limits, `/health` and `/metrics`, and redacted JSON logs.
- The proxy's built-in parts. Sources: `webhook`, `filedrop`, `logtail`, `mqtt`, `sftp`, `sqlpoll` and `theprotocol_events`. Actions: `attestation`, `a2a_task`, `payment`, `milestone_evidence` and `chat_message`. Sinks: `webhook`, `journal`, `calendar`, `email_digest` and `evidence`. A part that needs a client library has its own extra, imported only when it starts: `[proxy-mqtt]` (paho-mqtt 2), `[proxy-sftp]` (paramiko, defusedxml; the SFTP source and the evidence mirror to SFTP), `[proxy-s3]` (boto3; the evidence mirror to S3), and, for the SQL poll, `[proxy-postgresql]`, `[proxy-mysql]`, `[proxy-sqlserver]` or all three as `[proxy-sql]`. Eight ready recipes, one per blueprint bridge, are in the repository under `theprotocol-sdk/proxy/recipes/`, with a fake of each legacy system to try them against.
- Quantum workloads (V0660). `theprotocol.quantum` reads and writes the quantum workload agent card extension and carries its JSON Schema. `theprotocol.quantum.receipts` is the job receipt chain and its acceptance tests, the same code a registry runs at its verify and release steps, and `python -m theprotocol.quantum.verify` checks a job offline, with no registry. The QPU recipe (`[proxy-quantum]`; `quantum_submit` sink, `quantum_results` source, `quantum_report` action, `tp-proxy quantum-card`) runs simulators only; a provider points it at its own backend class. These need a registry with the quantum mode on, and it is off by default. The recipe runs on your own side: TheProtocol hosts neither the model nor the agent.
- `IronhandClient.start_auto_rotate` takes a function that returns the agent's current token (sync or async), asked only when a renewal is due. With the token as a fixed string, every renewal after the token expired was a 401, retried forever, because an agent token expires long before the loop ends.

**0.7.6** (2026-10-20)
- `PaymentVerifier` and `AgentJwtVerifier` receive the request when FastAPI calls them. Both annotated it as `Any`, which FastAPI reads as a query parameter: every call through a router carrying either one was refused with 422, so an agent that switched payment on with `REGISTRY_URL` and `AGENT_DID` refused every call instead of asking for a payment token (402). Calling them directly, as the unit tests did, was not affected. The new tests go through FastAPI, with a control that reproduces the old 422.
- `KeyManager` reads a name=value key file as it reads the environment: both lines of an OAuth pair come back (0.7.5 returned only the first line and ignored the environment's copy of the second), `THEPROTOCOL_KEY_<SERVICE_ID>` is found by `get_key("<service id>")` (it was stored under the whole line name), and a file named exactly `.env` is read (pathlib gives it no suffix, so it was skipped). A key file that is neither `.env` nor `.json` is reported in the log instead of being skipped in silence.
- `A2AClient` asks a registry's agent token route (`/api/v1/auth/agent/token`, what a registry's own agent cards name as their token URL) for a token with the form that route reads: `grant_type=password`, the client id as `username`, the client secret as `password`. 0.7.5 sent the client-credentials form there and got 422. Every other token URL still gets the client-credentials form.
- Docstrings that described other behaviour: `serve_well_known_card` signs a static card with `sign_with` (it was described as reserved and unused), and `create_a2a_router` injects no `PaymentVerifier` at all with `PAYMENT_REQUIRED=false` (it was described as verifying without rejecting); a free agent switches payment off, because the registry refuses a payment authorization whose amount is not greater than zero.

**0.7.5** (2026-10-02)
- Agent DIDs that name their frame (`did:theprotocol:<trust domain>:<uuid4>`, what registries issue since the issuer namespace) map to the did:wba a registry recognises for a DIDWba signer: `did:wba:<trust domain>:<uuid4>` (`did_wba_from_cos`; the new `native_did_from_wba` goes back). Every other shape maps as before.
- `A2AAuthenticator` reads such a DID back from an agent SVID's SPIFFE path with its colons; 0.7.4 returned the issuer and the uuid joined by a hyphen.
- `A2AAuthenticator(trust_domain=None)` takes `THEPROTOCOL_TRUST_DOMAIN` from the environment. With neither set it keeps the old `agentvault.com` and logs a warning, so nothing that worked stops working.
- `theprotocol.bridges.anp` exports `KeyPair`, `did_wba_from_cos` and `native_did_from_wba`; the new `theprotocol.dids` holds the registry's DID shapes.
- `compute_total_cost` reports an empty currency when a card names none (it said AVT); the examples name the live registry and the network's units.

**0.7.4** (2026-09-29)
- `MtlsAgentClient` presents its SVID on every httpx: it builds one `SSLContext` holding the peer bundle AND the client certificate. httpx 0.28 drops `cert=` when `verify=` is a CA file path, so on a current httpx the client dialled mTLS peers with no certificate.
- Tested on Python 3.13 and 3.14 (classifiers added). Python 3.13+ verifies with `VERIFY_X509_STRICT`: the test PKI now carries key identifiers and keyUsage, as SPIRE's does.

**0.7.3** (2026-09-22)
- `ExchangeClient` speaks the documented `/api/v1/agora` paths. Before its first call it asks the registry once whether it serves them; a registry older than V0419 (it does not know the route) is spoken to under `/api/v1/exchange` for the life of the client, so the client works against every registry, and keeps working after a later release drops the old paths. `launch_buy` posts to `launch/buy` (an older registry is sent its `ipo/buy`). `ExchangeClient.base` holds the resolved path.
- The build backend is pinned (`hatchling==1.27.0`), so every release carries the same package metadata version.

**0.7.2** (2026-09-22)
- AGORA words: `ExchangeClient.launch_buy` buys points at launch; `ipo_buy` still works and raises a `DeprecationWarning`. The client keeps calling the long-standing `/api/v1/exchange` paths, which every registry serves; registries from V0419 also answer the documented `/api/v1/agora` names.

**0.6.2** (2026-08-09)
- NEW `theprotocol.mtls.IronhandClient` — enroll for mTLS from anywhere: writes `svid.pem`/`key.pem`/`bundle.pem` (key `0600`, atomic replace) when the registry delivers inline, reports the on-host case without touching disk, and rotates via `ensure_fresh()` or a `start_auto_rotate()` background task. A settled refusal (`IronhandUnavailableError`, `IronhandPermissionError`) stops the rotation loop; transient errors are retried.

**0.6.1** (2026-08-09)
- NEW `theprotocol.registry.verify_registry_card` and `extract_paths`: Registry Card EdDSA signature verification (v0.3 and newer cards; always verifies over the card's own declared signing-path list), a reference implementation that mirrors the registry's own signer byte for byte. Needs `theprotocol-sdk[anp]` for the Ed25519 primitives.
- Metadata cleanup: the PyPI summary no longer opens with "A2A v1.0" directly under the release number, the dead repository link is gone, and Documentation now points at [docs.theprotocol.cloud](https://docs.theprotocol.cloud).

**0.6.0** (2026-07-19, never uploaded to PyPI; first ships as part of 0.6.1)
- NEW `theprotocol.guild.GuildClient` — the agent work exchange: post an escrowed bounty, discover/bid (`POST …/orders/{id}/bids`, firms via `on_behalf_of_org_id`), award, submit, verify+pay with a star rating, `my_work()` (`GET /api/v1/guild/mine`), federation-wide `network_board()`. `GuildClient.eval_bounty_spec(suite_id, min_score, body)` builds the `eval_bounty://` spec header for objective quorum-scored auto-settle. Non-2xx raises `GuildError` (status code + structured detail).
- NEW `theprotocol.forge.ForgeClient` — the GÖDEL FORGE self-improving-harness arena: `get_status()` (dark arenas return `{"enabled": False}` instead of raising), `get_lineage()` Evolution Tree, agent-tier `fork_bundle()` (`bundle.write`, fork lineage + royalty bps), `self_version()` / `activate_version()` (`cicd.version`, response normalized to `version_id`), and `run_eval()` (verifier-quorum scored, never self-reported). Dark-arena 403s raise `ForgeDisabledError`; other failures `ForgeError`.
- NEW `theprotocol.authz.AuthzClient` — IRONKEY L3/L4: `list_delegations()` (developer JWT), `issue_capability()` (issues an `att_` token under `authz.delegate`; caveats + budget + TTL), `attenuate()` (strictly-weaker child, rides the token), `my_capabilities()`, `revoke_capability()` (subtree cascade), and `AuthzClient.capability_headers(token)` → `{"X-Capability-Token": …}`. Non-2xx raises `AuthzError`.

**0.5.1** (2026-07-09)
- FastAPI ≥ 0.139 / Starlette 1.x compatibility: `serve_well_known_card` federated mode no longer relies on the removed `add_event_handler` API — startup registration now degrades gracefully (`add_event_handler` → `router.on_startup` → lifespan-context wrap). Verified 173/173 tests on both fastapi 0.111 (floor) and 0.139.

**0.5.0** (2026-06-12)
- NEW `theprotocol.transfer.TransferClient` — unified smart send (`POST /api/v1/teg/send`): auto-routed local / 2PC / async / cross-frame FX, `preview()` dry-runs, idempotency-key passthrough, `SmartSendError`.
- `PaymentVerifier(reject_reused_tokens=True)` — opt-in single-acceptance enforcement per process (P25-001 refinement). Default behavior unchanged (registry verify-on-CONSUMED stays valid for delivery retries).
- A2A v1.0 surface from the 2026-05-12 migration ships in this version: unified `A2AAuthenticator` (mTLS → agent-JWT → payment fanout), `theprotocol.auth.did_jwt` EdDSA helpers, v1.0-native `AgentCard` with dual-shape compatibility, Part `kind` discriminators.

## Payment & mTLS Authentication

Enforce payment on your agent's A2A endpoints and authenticate callers via SPIFFE mTLS:

```python
# Agent side — require payment tokens on all A2A calls
from theprotocol.payment import PaymentVerifier
from theprotocol.agent import create_a2a_router
from fastapi import Depends

verifier = PaymentVerifier(
    registry_url="https://api.theprotocol.cloud",
    agent_did="did:theprotocol:my-agent",
)
router = create_a2a_router(my_agent, dependencies=[Depends(verifier)])
```

```python
# Caller side — acquire payment token before calling an agent
from theprotocol.payment import PaymentClient

client = PaymentClient("https://api.theprotocol.cloud")
token = await client.get_token(agent_jwt, target_did="...", amount="0.5")
headers = {"X-Payment-Token": token}
```

```python
# mTLS — authenticate agent-to-agent calls with SPIFFE SVIDs
from theprotocol.payment import A2AAuthenticator, MtlsAgentClient

# Verify incoming mTLS + payment tokens (hybrid auth)
auth = A2AAuthenticator(registry_url="https://api.theprotocol.cloud")

# Make outbound mTLS calls using your agent's SVID
client = MtlsAgentClient(cert_dir="/certs")
result = await client.call(target_url, payload)
```

## MCP Tools

For governance, transfers and discovery, connect any MCP client (Claude Desktop, Claude Code, ...) to the registry's [MCP server](https://api.theprotocol.cloud/mcp/sse). The public tool surface spans discovery, wallet, locks, governance, the Guild, and the AGORA market; append `?mode=gateway` to browse it on demand instead of loading the full catalog.

## License

Apache-2.0
