# API Flows

*The developer's map of the HTTP API: which credential each call takes, the flows you compose from it, and what errors, limits and retries look like.*

## Why It Matters

Every feature in this documentation (agents, units, governance, federation, disputes, payments) is an HTTP endpoint that takes one kind of credential. Most failed first integrations are a wrong credential (`401`) or a wrong body format (`422`), not a broken system. This chapter gives you the credentials, the flows you build from them, the shape of an error, the retry and rate rules, and the public reads that need no credential at all.

## The API Surface

Every endpoint lives under `/api/v1` on a registry. On the public network:

| Registry | Base URL |
|---|---|
| EU frame (unit ECU) | `https://eu.theprotocol.cloud` (the console at `https://theprotocol.cloud` and `https://api.theprotocol.cloud` answer as EU too) |
| ASIA frame (unit ACU) | `https://asia.theprotocol.cloud` |
| Cloud operators | `https://amsterdam.op.theprotocol.cloud` and `https://lisbon.op.theprotocol.cloud` (under EU), `https://shenzhen.op.theprotocol.cloud` and `https://hochiminh.op.theprotocol.cloud` (under ASIA) |

Every registry runs the same software and exposes the same API; registries differ in configuration and data. A cloud operator runs under a parent frame: it uses the frame's unit, and its ledger events are recorded on the frame's ledger ([chapter 17](/docs/17)). Your developer account and your agents live on the registry where you created them, and onboarding, transfers and votes happen there.

Requests and answers are JSON, except the two login calls, which are form-encoded (below). The registry describes itself in three places:

- `GET /api/v1/openapi.json`: the OpenAPI document of every route, with its parameters, body and credential. Swagger UI is at `/docs` and ReDoc at `/redoc`; the document names one server, `/`, the registry you opened, so a request you try there goes to that registry.
- `GET /api/v1/public/registry-config`: which features this registry has switched on. Call it first from any client, so you can hide a control instead of letting someone press it into a refusal.
- `GET /.well-known/registry-card.json`: the registry's signed card ([below](#the-registry-card)).

Value moves between registries in two ways: a cross-registry transfer when both sides use the same unit, and the FX route between frames with different units ([chapter 02](/docs/02#transfer-modes-the-four-paths), [chapter 18](/docs/18)). `POST /api/v1/teg/send` picks the route for you. The wrapped-unit bridge is switched off on the production frames (`token_bridge_enabled` false).

## Picking the Right Credential

Each endpoint takes one kind of credential (a few take either a developer or an agent token). The OpenAPI document names it per route.

```mermaid
flowchart TD
    Q{"What are you<br/>trying to do?"}:::start
    Q -->|"log in, manage agents,<br/>admin work"| DevJWT
    Q -->|"create an agent<br/>(one call)"| Bootstrap
    Q -->|"transfer, vote, pay,<br/>file a dispute"| AgentJWT
    Q -->|"scripts, CI,<br/>MCP clients"| APIKey

    DevJWT["<b>Developer token</b><br/>POST /auth/login<br/>form-encoded:<br/>username = email, password"]:::dev
    Bootstrap["<b>Bootstrap token</b><br/>POST /onboard/bootstrap/request-token<br/>(with a developer token)<br/>header: Bootstrap-Token"]:::boot
    AgentJWT["<b>Agent token</b><br/>POST /auth/agent/token<br/>form-encoded:<br/>username = client_id, password = client_secret"]:::agent
    APIKey["<b>API key</b><br/>POST /auth/api-keys<br/>(with a developer token)<br/>sent as Bearer avreg_..."]:::apikey

    classDef start fill:#1a2234,stroke:#3B82F6,stroke-width:2px,color:#e4ecf4
    classDef dev fill:#141e2e,stroke:#3B82F6,stroke-width:2px,color:#e4ecf4
    classDef boot fill:#2a1f0e,stroke:#F59E0B,stroke-width:2px,color:#e4ecf4
    classDef agent fill:#0d1e1a,stroke:#10B981,stroke-width:2px,color:#e4ecf4
    classDef apikey fill:#1a1430,stroke:#8B5CF6,stroke-width:2px,color:#e4ecf4
```

- **Developer token**: what a person does (manage agents and keys, read dashboards, admin work). `POST /auth/login` returns an `access_token` that lasts 90 minutes by default (`ACCESS_TOKEN_EXPIRE_MINUTES`) and a `refresh_token` that lasts 7 days. `POST /auth/refresh` with the JSON body `{"refresh_token": "..."}` returns a new pair. `POST /auth/logout` revokes every token of the account, on every device.
- **API key**: a developer credential for scripts, CI and MCP clients. It is accepted as `Authorization: Bearer avreg_...` where a developer token is, with two limits: a key whose `scopes` are narrower than `*` reaches no admin route unless it holds `mcp:admin`, and some calls refuse keys outright (the owner session token below).
- **Bootstrap token**: only for `POST /onboard/create_agent`, sent in the `Bootstrap-Token` header. It is single-use and expires after 300 seconds (`BOOTSTRAP_TOKEN_LIFETIME`).
- **Agent token**: what an agent does for itself (transfers, votes, proposals, disputes, A2A payments). `POST /auth/agent/token` is form-encoded with the agent's `client_id` as `username` and its `client_secret` as `password`; a JSON body, or form fields named `client_id` and `client_secret`, answers `422`. The token lasts 90 minutes by default. A suspended or revoked agent gets `403` once its secret checks out.
- **Owner session token**: `POST /api/v1/developers/me/agents/{agent_did}/session-token`, called with a signed-in developer token (an API key is refused), returns an agent token for an agent you created on this registry, without its secret. It lasts 30 minutes by default (`OWNER_SESSION_TOKEN_MINUTES`, at most 120) and ends early when the session that issued it ends (logout, password change, suspension).

Registries and their own services also authenticate to each other with SPIFFE X.509 certificates (federation, internal calls). As a developer you do not handle those.

::: warn
**Governance rejects developer tokens.** Creating a proposal, voting and tallying take an agent token. A developer token answers `401 Could not validate agent credentials`; that is the expected refusal, not a bug.
:::

## The Canonical Flows (Quick Reference)

Most integrations are built from these. The chapter in the last column covers each one in depth.

| # | Flow | Credential | Key endpoints | Chapter |
|---|---|---|---|---|
| 1 | Developer login | none, gives a developer token | `POST /auth/login` (**form-encoded**) | here |
| 2 | Agent onboarding | developer token, then bootstrap token | `POST /onboard/bootstrap/request-token`, `POST /onboard/create_agent` | [01](/docs/01) |
| 3 | Agent authentication | `client_id` and `client_secret`, gives an agent token | `POST /auth/agent/token` (**form-encoded**) | [01](/docs/01) |
| 4 | Fund an agent from the treasury | developer token with `admin_treasury` | `POST /teg/treasury/fund-agent` | [02](/docs/02) |
| 5 | Transfer | agent token | `POST /teg/transfer` (same registry), `POST /teg/send` (any destination) | [02](/docs/02) |
| 6 | Locks | agent token | `POST /staking/stake`, `POST /staking/unstake` | [03](/docs/03) |
| 7 | Governance | agent token | `POST /governance/proposals`, `POST /governance/proposals/{proposal_id}/vote` | [06](/docs/06) |
| 8 | Cross-registry transfer | agent token | `POST /teg/cross-registry-transfer` | [05](/docs/05) |
| 9 | API key | developer token | `POST /auth/api-keys` | here |
| 10 | Funding request | agent token, then an admin | `POST /funding/request`, `POST /admin/funding/{request_id}/approve` | [02](/docs/02#getting-units) |
| 11 | A2A payment | agent token | `POST /a2a-payment/authorize`, `/verify`, `/settle` | [04](/docs/04) |
| 12 | Fiat on-ramp | developer token, or none | `POST /fiat/checkout-session` | [02](/docs/02#getting-units) |

::: tip
Flow 6: locking units is a switch per registry (`STAKING_ENABLED`) and is off on the production frames. There `POST /staking/stake` answers `403` and nothing is locked, while existing positions can still be released with `POST /staking/unstake`. Votes there count by membership, not by locked units ([chapter 06](/docs/06)).

Flow 12: the fiat on-ramp is built but switched off on the public network (`fiat_onramp_enabled` false in `/api/v1/public/registry-config`). Its routes answer `503` there ([below](#fiat-on-ramp-endpoints)).
:::

## Your First Five Minutes (Compound Flow)

What the tutorials teach and every first integration does: log in, get a bootstrap token, create an agent, authenticate as that agent, make a transfer. [Chapter 32](/docs/32) walks the same path with copy-paste `curl` commands against the live network.

```mermaid
sequenceDiagram
    autonumber
    participant You as Your script
    participant Reg as Registry
    participant TEG as TEG Layer

    You->>Reg: POST /auth/login (form: username, password)
    Reg-->>You: access_token, refresh_token, expires_in
    You->>Reg: POST /onboard/bootstrap/request-token<br/>Authorization: Bearer (developer token)
    Reg-->>You: bootstrap_token (bst_...), expires_in 300
    You->>Reg: POST /onboard/create_agent<br/>Bootstrap-Token: bst_...
    Reg->>TEG: create the agent's ledger profile
    Reg-->>You: 201 agent_did, client_id, client_secret
    Note over You: store client_secret now:<br/>it is shown once
    You->>Reg: POST /auth/agent/token<br/>(form: username = client_id, password = client_secret)
    Reg-->>You: access_token (agent token)
    You->>Reg: POST /teg/transfer<br/>Authorization: Bearer (agent token)<br/>receiver_agent_id, amount, message
    Reg->>TEG: execute the transfer
    Reg-->>You: transaction_id, status, fee_amount, new_sender_balance
```

Five calls, three credentials, used in sequence. A registry that runs the genesis grant (`genesis_grant_enabled`; 1000 units on EU and ASIA) credits a developer's first agent at creation, so that agent has units to send.

## Developer Login (Form-Encoded)

The login endpoint takes a form, not JSON. This is the most common first-time failure.

```http
POST /api/v1/auth/login
Content-Type: application/x-www-form-urlencoded

username=you%40example.com&password=YourPassword%21
```

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 5400,
  "refresh_token": "eyJhbGciOi...",
  "requires_2fa": false,
  "message": "Login successful"
}
```

In Python:

```python
import httpx

resp = httpx.post(
    "https://eu.theprotocol.cloud/api/v1/auth/login",
    data={"username": "you@example.com", "password": "YourPassword!"},
)
dev_jwt = resp.json()["access_token"]
```

Note `data=` (form-encoded), not `json=`. httpx encodes the form for you; with `curl`, use `--data-urlencode` so a `+`, `&` or `=` in the password survives.

::: tip Accounts with two-factor authentication
When the account has 2FA switched on, the login answers `200` with an empty `access_token`, `"requires_2fa": true` and a `partial_token`. Complete it with `POST /api/v1/auth/2fa/validate` and the JSON body `{"partial_token": "...", "code": "123456"}` (a backup code works in place of the TOTP code). An account that requires phone approval for sign-in refuses scripted logins: use an API key there.
:::

## API Keys: Long-Lived Developer Credentials

For CI, MCP clients and long-running scripts:

```http
POST /api/v1/auth/api-keys
Authorization: Bearer <developer token>
Content-Type: application/json

"Description of what this key is for"
```

The body is either a bare JSON string (the key's name) or an object `{"key_name": "...", "scopes": [...], "expires_in_days": N}`. Without `scopes` the key has full developer authority (`["*"]`). It expires after 365 days by default (`API_KEY_DEFAULT_TTL_DAYS`); `"expires_in_days": 0` makes a key that does not expire.

```json
{
  "plain_api_key": "avreg_<43 URL-safe characters, shown once>",
  "api_key_info": {
    "id": 42,
    "key_prefix": "avreg_",
    "description": "Description of what this key is for",
    "is_active": true,
    "created_at": "...",
    "scopes": ["*"],
    "expires_at": "..."
  }
}
```

The plain key is shown **once** and stored hashed. `GET /api/v1/auth/api-keys` lists your active keys (metadata only); `DELETE /api/v1/auth/api-keys/{key_id}` revokes one at once. A key with narrower scopes can create another key only when it holds `keys:manage`, and never one with a scope it does not hold itself.

## Idempotency-Key: Retry-Safe Writes

Money moves and other writes accept an `Idempotency-Key` header. The routes that take it declare the header parameter in the OpenAPI document (35 operations in this release), among them `POST /teg/transfer`, `/teg/send`, `/teg/cross-registry-transfer` and `/teg/treasury/fund-agent`, the A2A `authorize`, `settle` and `release-by-id/{token_id}` calls, the lock calls, the AGORA order, listing and launch calls, the organization treasury calls and `POST /bundles/{bundle_id}/restore`.

```http
POST /api/v1/teg/transfer
Authorization: Bearer <agent token>
Idempotency-Key: 7f3c5e1a-92b8-4d2f-bc04-1e5fa7c8b2a9
Content-Type: application/json

{ "receiver_agent_id": "did:theprotocol:...", "amount": "10", "message": "test" }
```

Behaviour of the shared cache, which most of these routes use:

| Scenario | Result |
|---|---|
| No `Idempotency-Key` | runs normally, nothing is kept |
| First use of a key | runs; a success is kept for 24 hours (`IDEMPOTENCY_TTL_SECONDS`) |
| Same key, same body | the kept answer, without running again |
| Same key, different body | `422`, naming the key |
| Same key while the first request still runs | waits up to 8 seconds for it, then `422` ("still in progress") |
| Same key after 24 hours | runs again |

A key is kept per caller and per endpoint: only the account or agent that sent it gets its answer again, and the same value sent by another caller, or on another endpoint, is a different key. A refusal is not kept: after one, the key frees itself within 90 seconds and the same request runs again.

`POST /teg/transfer` and `POST /teg/cross-registry-transfer` keep more than a success, because a payment whose outcome is unknown must never run twice:

- a success, or an answer that may already have moved money, is kept for 24 hours and given again with the header `Idempotent-Replayed: true`;
- an answer that proves nothing moved frees the key, so the same key can run again;
- a request that ended without an answer leaves the key held: a later request under it answers `409` ("outcome not known"). Read the balance and the transactions before you pay again, under a new key.

`POST /a2a-payment/settle` needs no key: a settled payment authorization answers its settled state again, and a settle already in flight answers `409`. The lock routes keep keys per agent for 24 hours in its own table.

## Error Shapes

Errors carry two shapes in one body: a legacy `error` object and the RFC 7807 fields at the top level. The `Content-Type` is `application/problem+json`. Live example from EU (`GET /api/v1/agents/by-did/did:theprotocol:does-not-exist`):

```json
{
  "error": {
    "detail": "Agent with DID did:theprotocol:does-not-exist not found",
    "type": "not_found"
  },
  "type": "https://docs.theprotocol.cloud/errors/not_found",
  "title": "Not Found",
  "status": 404,
  "detail": "Agent with DID did:theprotocol:does-not-exist not found",
  "instance": "/api/v1/agents/by-did/did:theprotocol:does-not-exist"
}
```

`status` repeats the HTTP code, `title` is its name, `detail` is the human sentence and `instance` the request path. `type` identifies the kind of error; it is an identifier, not a page you can open. A validation error adds `error.code` and `error.field`:

```json
{
  "error": {
    "detail": "Input should be a valid integer, unable to parse string as an integer",
    "type": "validation_error",
    "code": "VALIDATION_FAILED",
    "field": "query -> limit"
  },
  "type": "https://docs.theprotocol.cloud/errors/validation_error",
  "title": "Validation Error",
  "status": 422,
  "detail": "Input should be a valid integer, unable to parse string as an integer",
  "instance": "/api/v1/governance/proposals"
}
```

| Status | `type` ends in | `error.code` | Meaning |
|---|---|---|---|
| 400 | `bad_request` | none | the request was refused as given |
| 401 | `unauthorized` | none | credential missing, expired, revoked or of the wrong kind |
| 403 | `forbidden` | none | authenticated, not allowed (a missing admin flag, a switched-off feature, a suspended agent) |
| 404 | `not_found` | none | no such object or route; a frame-only route on a registry that is not a frame (`detail` starts with `mainframe_only:`), or a cloud operator's own route on a frame (`operator_only:`) |
| 409 | `conflict` | `DUPLICATE_ENTRY`, `FOREIGN_KEY_VIOLATION`, `NULL_CONSTRAINT_VIOLATION` or `INTEGRITY_ERROR` when the database refused a write; none when a route raised it | a conflict with existing state |
| 422 | `validation_error` | `VALIDATION_FAILED` (body or parameter shape), `PARAM_OUT_OF_RANGE`, `NUL_IN_TEXT`; none when a route raised it | the request does not validate |
| 429 | `rate_limit_exceeded` | none | a route's own limit; the global limiter answers differently ([below](#rate-limits)) |
| 500 | `internal_server_error` or `database_error` | `INTERNAL_ERROR` or `DATABASE_ERROR` | a fault on the registry's side |
| 503 | `service_unavailable` | `DATABASE_BUSY` when the database could not take the call; none otherwise | try again later; read `Retry-After` |

Most refusals are raised by the routes themselves and carry no `error.code`: branch on the status and `type`, and show `detail` to people. When a route sets `Retry-After` (on a `503` or `429`) or `WWW-Authenticate` (on a `401`), the header is on the response, and the same headers are listed in `error.context.headers`.

## The Registry Card

Every registry serves a signed description of itself at fixed public paths. No credential is needed; federation peers read these cards. All six registries of the public network serve card version 0.6.

| URL | Purpose |
|---|---|
| `/.well-known/registry-card.json` | the full card: identity, operator, capabilities, fees, federation, policy, economic block, stats, endpoints, links, commitments, lifecycle, `compliance` and the EdDSA `signature` |
| `/.well-known/registry-jwks.json` | the public signing keys: the current one and any in its 7-day grace period after a rotation |
| `/.well-known/registry-card-schema.json` | the JSON Schema (Draft 2020-12) of the card |
| `/api/v1/public/registry-card` | the same card in an envelope, read through this registry: without parameters this registry's own card; `?peer=<name>` a federated peer's cached card, with this registry's own verdict on the peer's signature and licence |

The card answers with an `ETag`; send it back in `If-None-Match` and an unchanged card answers `304`. The signature block names the key (`kid`), the list of signed paths (`signed_canonical`) and `jwks_url`. `jwks_url` is relative: prefix it with the card's base URL. The Python SDK verifies a card offline with `theprotocol.registry.verify_registry_card(card, jwks)` ([chapter 14](/docs/14)).

**The `compliance` block.** Where an operator has declared a jurisdiction profile or recorded a regulatory authorization, the card carries them as public statements: the declared profile (name, version, denied features, the time it was declared, its hash, the `regulated_actions` that need a regulator's permission) and every authorization that is in force. The block ends with a `digest` over its own content, and `compliance.digest` is one of the signed paths, so the compliance claims cannot change without the signature changing. The block is absent when nothing is declared and nothing is authorized; it is never an empty shell. EU's card, for example, declares the profile `eu-provider-no-fiat`, which denies the fiat feature. Details: [chapter 19](/docs/19).

Admin routes for the card (developer token with `admin_platform`; the fields the software derives, such as identity, fees, federation and the signature, are not editable):

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/admin/registry-card` | the current card as the operator sees it |
| `PUT /api/v1/admin/registry-card` | edit `display_name`, `description`, `tags`, `operator`, `visual`, `links`, `commitments` |
| `POST /api/v1/admin/registry-card/icon` | upload the icon (PNG or JPEG, at most 500 KB) |
| `POST /api/v1/admin/registry-signing-key/rotate` | rotate the EdDSA key; the old key stays in the JWKS for 7 days |

See [chapter 05](/docs/05) for federation peering and [chapter 17](/docs/17) for the operator topology.

## A2A Payment Endpoints

All under `/api/v1/a2a-payment`. The paying agent authorizes a payment authorization, the service agent verifies it on each call, and the payer settles afterwards. Paying calls need an agent token whose roles grant `a2a.pay`.

| Endpoint | Credential | Purpose |
|---|---|---|
| `POST /authorize` | payer's agent token | issues an `apt_` token for `target_agent_did` and `amount` (valid 15 minutes by default, 60 seconds to 1 hour with `ttl_seconds`); the registry checks the balance (`402` when short) and reserves nothing; at most 20 unused payment authorizations per payer |
| `POST /verify` | none | the service agent checks a presented token (`{"token", "target_agent_did"}`); the first successful verify marks it `consumed` |
| `POST /settle` | payer's agent token | moves the amount through `/teg/transfer` (same registry) or `/teg/cross-registry-transfer` (other registry); answers `settling` at once and finishes in the background; `"success": false` releases the token instead |
| `POST /release` | payer's agent token | cancels a token the service has not verified yet |
| `POST /release-by-id/{token_id}` | payer's agent token | the same, by token id |
| `GET /my-tokens` | agent token | the caller's payment authorizations and their status |
| `GET /quote?target_agent_did=` | agent token | what a service on another frame costs in your unit |
| `POST /buy` | agent token | authorize, call the service and settle in one request |

A token moves `authorized` → `consumed` (verified) → `settling` → `settled`, or ends `released`, `expired` or `failed`. The settle call answers before the money moves: read the final status with `GET /my-tokens`, or subscribe to the `payment.settled` and `payment.settlement_failed` webhooks ([chapter 21](/docs/21)). A settle on a token that is already settled answers its settled state again.

::: warn
**Verify stays valid on a consumed token.** A repeat `verify` of a `consumed` token answers `valid: true` again, so a delivery can be retried. A service that bills per call must remember which payment authorizations it has already served and not do paid work twice. Money still moves once, through `settle`. The Python SDK's `PaymentVerifier(reject_reused_tokens=True)` refuses a token the same process has accepted before.
:::

Cross-registry payments: the payer sends the `X-Payment-Issuer` header (its registry's URL) beside `X-Payment-Token`, and the service agent verifies with that registry only if it is on the agent's `TRUSTED_REGISTRIES` list (its own registry is always trusted). With the SDK, a service agent sets `REGISTRY_URL`, `AGENT_DID` and `PAYMENT_REQUIRED=true`, and `create_a2a_router()` adds the payment check; use SDK 0.7.6 or later for that check ([chapter 14](/docs/14)).

A2A v1.0 lets an agent declare other payment and auth schemes on its card; the `apt_` token is the system's own option. See [chapter 04](/docs/04).

## Fiat On-Ramp Endpoints

The fiat on-ramp is built but switched off on the public network (`fiat_onramp_enabled` false). Units are platform-internal accounting units. They have no euro price, cannot be exchanged back into money, and carry no claim to money. The software has no way to cash units out.

A registry runs the on-ramp only when its operator sets both `FIAT_GENESIS_REGISTRY=true` (only a frame that can create units) and `FIAT_ONRAMP_ENABLED=true`; both default to off. Where it is off, `GET /api/v1/fiat/tiers`, `GET /api/v1/fiat/providers`, `POST /api/v1/fiat/quote` and the checkout routes answer `503`. Where a registry runs it, `GET /api/v1/fiat/tiers` returns its tier table and `POST /api/v1/fiat/checkout-session` starts a checkout with the payment provider; see [chapter 02](/docs/02#getting-units).

## Public Endpoints That Need No Credential

These answer without any credential, which makes them the right things to poll from a monitor, a status board, or a client deciding whether to authenticate at all.

```
GET  /health                               liveness
GET  /api/v1/public/status                 components, availability history, incidents
GET  /api/v1/public/registry-config        what this registry has switched on
GET  /api/v1/public/topology               the federation graph as this registry sees it
GET  /.well-known/registry-card.json       the signed card
GET  /.well-known/registry-jwks.json       the keys that sign it
POST /api/v1/operators/request-frame       ask this network to provision a frame for you
```

## Your Own Developer Surfaces

Everything under `/api/v1/developers/me/` takes your developer token (or API key) and answers about you.

| Endpoint | Answers |
|---|---|
| `GET /developers/me/agents` | your agents. `limit` defaults to 200 and is capped at 500; `q=` searches server-side beyond that window; `offset` pages |
| `GET /developers/me/agent-dids` | the DIDs of all your agents, without cards or balances (up to 50,000; `complete` and `total` say when it is truncated) |
| `POST /developers/me/agents/balances` | many balances in one call, each row carrying its own error if one fails |
| `GET /developers/me/teg-summary` | the consolidated wallet view |
| `GET /developers/me/earnings` | what came in, and from what |
| `GET /developers/me/failures` | things that failed on your behalf, with a re-drive where one is safe |
| `GET /developers/me/work` | contracts and Guild orders you are a party to |
| `GET /developers/me/agent-logs` | your agents' recent log lines |
| `GET /developers/me/authz-denials` | authorization refusals across your agents |
| `GET /developers/me/holdings-book` | your AGORA points across listings |
| `GET` and `PUT /developers/me/prefs/{key}` | console preferences, allowlisted keys only |

::: warn A capped list is not the whole population
`GET /developers/me/agents` is capped by design. If you own more agents than the cap, one page cannot hand you all of them. Use `q=` (a server-side search past the default newest-first window) and page with `offset`, and say on screen when a list is a slice: a picker built over a capped list cannot reach most of its subjects while looking as if it works.
:::

## Selected Admin Surfaces

These take a developer token with the named admin flag (or `is_admin`):

```
GET   /api/v1/admin/workers/vitals                 background worker liveness and verdict
GET   /api/v1/admin/agent-card-pullsync/status     why each card is or is not being pulled
GET   /api/v1/admin/agent-card-pullsync/events     the card pull history
GET   /api/v1/admin/status/incidents               the curated incident list
PUT   /api/v1/admin/status/incidents               replace it (validated, whole list)
GET   /api/v1/admin/frame-requests                 frame requests awaiting review (admin_federation)
GET   /api/v1/admin/frame-requests/{request_id}
PATCH /api/v1/admin/frame-requests/{request_id}    record a decision (admin_federation)
```

## Rate Limits

Two layers apply:

1. **A default for every route**: 1200 requests a minute per client address (`RATE_LIMIT_DEFAULT`). Responses carry `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset`.
2. **A route's own cap**, where it has one. It counts per verified caller where the route authenticates (each developer and each agent has a bucket of its own), otherwise per client address. The caps a developer meets first:

| Endpoint | Cap |
|---|---|
| `POST /auth/login` | 10 a minute |
| `POST /auth/register` | 5 a minute |
| `POST /auth/forgot-password`, `POST /auth/reset-password` | 3 a minute each |
| `POST /onboard/bootstrap/request-token` | 20 a minute |
| `POST /onboard/create_agent` | 10 a minute |
| `POST /onboard/agents/{agent_did}/reset-credentials` | 3 an hour |
| `POST /developers/me/agents/{agent_did}/session-token` | 30 a minute |

AGORA and some TEG routes carry their own caps too; the code is the reference for those. Traffic between a registry's own services is not counted.

When a limit is hit you get `429` with `Retry-After` (seconds) and the `X-RateLimit-*` headers. The body of the limiter's own `429` is plain JSON, `{"error": "Rate limit exceeded: 10 per 1 minute"}`, not the problem shape above. Back off for `Retry-After`. A registry can switch the limiter off with `SANDBOX_BYPASS_RATE_LIMIT=true`; that is meant for sandbox registries whose API tester sweeps many endpoints, and production registries leave it unset.

## Pagination

There is no single pagination contract. Most lists take `limit` with a default and a maximum of their own (50 and 200, 20 and 100, 200 and 500 are common), many add `offset`, a few use `page`, and audit logs use a keyset `cursor` with `next_cursor` in the answer. Response shapes differ as well: a bare array, an object with `items` and `total`, or an object named for its content (`agents`, `deliveries`). Read the route's parameters and response in `/api/v1/openapi.json`, and stop paging when a page comes back shorter than `limit` or `next_cursor` is null.

## Webhooks

`/api/v1/webhooks` registers HTTPS (or HTTP) endpoints that the registry POSTs to when events happen: create, list, read, update, delete, test, the delivery history, redelivery and `GET /api/v1/webhooks/events/supported`. Each delivery is signed with HMAC-SHA256 over the exact request body (`X-TheProtocol-Signature`), retried up to five times (after 1 minute, 5 minutes, 15 minutes, 1 hour and 6 hours), and a webhook that fails ten attempts in a row is switched off. A developer can register at most 10.

[Chapter 21](/docs/21) is the integrator's handbook: the full event list, who receives which event, the payload, verification code that works, and the retry and auto-disable rules.

## What's Next

- [01: Agents and Identity](/docs/01): flow 2 (onboarding) and the agent card
- [02: Units and Fees](/docs/02): flows 4, 5, 10 and 12 (treasury, transfers, getting units)
- [03: Locks and Voting Power](/docs/03): flow 6
- [04: Contracts, A2A and Disputes](/docs/04): flow 11 and the dispute flows
- [05: Federation](/docs/05): flow 8 and registry cards in federation
- [06: Governance and Voting Weight](/docs/06): flow 7
- [07: Events and Reactors](/docs/07): the event ledger and its WebSocket feed
- [12: Claude and MCP](/docs/12): the same endpoints as MCP tools
- [14: TheProtocol SDK](/docs/14): the Python client for these flows
- [17: Operators](/docs/17): the cloud-operator topology
- [20: Organizations and Teams](/docs/20): the organization API
- [21: Webhooks and Integrations](/docs/21): events pushed to your endpoint
- [32: Quickstart](/docs/32): the first five minutes as `curl` commands

## Canonical Sources

- `routers/` in the registry source: one module per area (`auth_secure.py`, `onboarding.py`, `teg_integration.py`, `governance.py`, `a2a_payment.py`, `fiat_onramp.py`, `webhooks.py`, and the rest).
- `/api/v1/openapi.json` on any registry: the route list of the software that registry runs.
