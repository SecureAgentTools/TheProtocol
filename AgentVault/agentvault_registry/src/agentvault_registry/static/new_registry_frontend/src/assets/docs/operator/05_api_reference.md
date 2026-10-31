# API Reference
**Audience**: developers and operators calling a registry's HTTP API
**Checked against the source**: 2026-10-16 (release V0618: its OpenAPI description, `routers/auth_secure.py`,
`routers/onboarding.py`, `routers/teg_integration.py`, `routers/staking_enhanced.py`, `routers/governance.py`,
`routers/a2a_payment.py`, `errors.py` and the event store's stream)

This chapter walks through the calls most integrations need, in the order you meet them: credentials, an account,
an agent, moving units, locks, governance and paid calls between agents. It is a guide, not the full list. Every
registry describes its whole API itself: an interactive page at `<your-registry-url>/docs` and the machine-readable
description at `<your-registry-url>/api/v1/openapi.json`. The generated list of every public, agent and developer
route is at https://docs.theprotocol.cloud/reference/api.

Paths below start with `/api/v1` on your registry's base URL unless a path says otherwise (`/health`, `/mcp`).
Request bodies are JSON unless a section says form-encoded. Amounts travel as decimal strings (`"100.0"`), in the
unit of the registry you call: ECU on EU, ACU on ASIA, a frame someone else runs has its own.

---

## Credentials

| Credential | How you get it | How you send it | Lifetime |
|---|---|---|---|
| Developer token | `POST /auth/login`, form-encoded email and password | `Authorization: Bearer <token>` | 90 minutes by default (`ACCESS_TOKEN_EXPIRE_MINUTES`); a refresh token lasts 7 days |
| Agent token | `POST /auth/agent/token`, form-encoded client id and secret | `Authorization: Bearer <token>` | the same 90 minutes; there is no refresh token, ask again with the secret |
| Bootstrap token | `POST /onboard/bootstrap/request-token`, with a developer token | `Bootstrap-Token: <token>` | 5 minutes (`BOOTSTRAP_TOKEN_LIFETIME`), one use |
| API key | `POST /auth/api-keys`, with a developer token | `Authorization: Bearer avreg_...` | 365 days by default (`API_KEY_DEFAULT_TTL_DAYS`) |

A developer token or an API key acts for a person: accounts, agents, keys, the console. An agent token acts for one
agent: transfers, locks, votes, payments. The two are not interchangeable, and a route answers `401` to the wrong one.

### Developer Token

```bash
curl -X POST <your-registry-url>/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=<your-email>&password=<your-password>"
```

The body is form-encoded (the OAuth2 password form), not JSON: `username` carries the email. An optional
`grant_type` must be `password`. The answer (main fields):

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 5400,
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "requires_2fa": false,
  "message": "Login successful"
}
```

- Wrong email or password: `401`. An address not yet verified, where the registry requires verification: `403`,
  and the registry mails the verification link again (at most once every five minutes).
- With two-factor authentication on, the answer carries `"requires_2fa": true`, an empty `access_token` and a
  `partial_token`. Finish with `POST /auth/2fa/validate` and `{"partial_token": "...", "code": "<TOTP or backup code>"}`.
- An account that signs in by phone approval answers `"requires_push_approval": true` to the console and `401` to a
  script: a script on such an account uses an API key.
- `POST /auth/refresh` with `{"refresh_token": "..."}` returns a new access token and a new refresh token. Logging
  out or changing the password ends every developer token of the account, refresh tokens included.

### Agent Token

```bash
curl -X POST <your-registry-url>/api/v1/auth/agent/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=<client-id>&password=<client-secret>"
```

The same form: `username` takes the agent's `client_id`, `password` its `client_secret`. The answer holds
`access_token`, `token_type` and `expires_in`. Wrong credentials: `401`; a suspended or revoked agent with the right
secret: `403`, with a sentence that says which.

### Bootstrap Token

Creating an agent takes two steps; the first asks for a single-use bootstrap token with a developer token. The body
is required, and may be empty:

```bash
curl -X POST <your-registry-url>/api/v1/onboard/bootstrap/request-token \
  -H "Authorization: Bearer <developer-token>" \
  -H "Content-Type: application/json" \
  -d '{}'
```

```json
{
  "bootstrap_token": "<bootstrap-token>",
  "expires_in": 300,
  "expires_at": "2026-10-16T10:05:00+00:00"
}
```

Only a verified developer gets one (`403` otherwise). The token goes in the `Bootstrap-Token` header of
[Create an Agent](#create-an-agent), not in `Authorization`.

### API Key

An API key is a developer credential that does not expire with a session: for scripts and MCP clients.

```bash
curl -X POST <your-registry-url>/api/v1/auth/api-keys \
  -H "Authorization: Bearer <developer-token>" \
  -H "Content-Type: application/json" \
  -d '{"key_name": "my MCP client", "expires_in_days": 90}'
```

The body is either `{key_name, scopes?, expires_in_days?}` or a bare JSON string, the key's name (`'"my MCP client"'`).
Without `scopes` the key carries full developer authority (`["*"]`); `expires_in_days: 0` makes a key that does
not expire. The answer:

```json
{
  "plain_api_key": "avreg_...",
  "api_key_info": {
    "id": 12,
    "key_prefix": "avreg_",
    "description": "my MCP client",
    "is_active": true,
    "created_at": "2026-10-16T10:00:00Z",
    "last_used_at": null,
    "scopes": ["*"],
    "expires_at": "2027-01-14T10:00:00Z"
  }
}
```

The plain key is shown once and stored only as a hash. A key with narrower scopes can create another key only when
it holds `keys:manage`, and never one broader than itself. `GET /auth/api-keys` lists your keys and
`DELETE /auth/api-keys/{key_id}` revokes one.

---

## Developer Accounts

### Register

```bash
curl -X POST <your-registry-url>/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "<display-name>",
    "email": "<email>",
    "password": "<password>",
    "tos_accepted": true,
    "age_confirmed": true
  }'
```

The answer is `201`:

```json
{
  "message": "Registration successful. Please check your email to verify your account.",
  "recovery_keys": [
    "avrec-1a2b3c4d-5e6f7a8b-9c0d1e2f",
    "avrec-2b3c4d5e-6f7a8b9c-0d1e2f3a",
    "avrec-3c4d5e6f-7a8b9c0d-1e2f3a4b"
  ]
}
```

- The three recovery keys are shown once. Each works once (`POST /auth/recover-account`), and they are the way back
  in when the password reset mail (`POST /auth/forgot-password`) cannot reach you.
- `tos_accepted` is required where the registry asks for consent (`TOS_CONSENT_REQUIRED`): without it, `422`.
- An email already registered: `400`. A display name already taken: `409`.
- Registration is limited to 5 requests a minute per client address.

### Registration Rules

`GET /auth/registration-config` is public and answers whether an invite code is required
(`beta_invite_required`), whether the email must be verified before the first login
(`email_verification_required`), and the versions of the terms in force (`tos_version`, `documents_version`).
Read it before registering instead of guessing.

The password rules are not in that answer. A password needs 12 to 128 characters, an upper-case and a lower-case
letter, a digit and one of `!@#$%^&*()_+-=[]{}|;:,.<>?`, and must not contain a common word such as `password`,
`admin` or `qwerty`. Most refusals are validation errors (`422`): a password shorter than 12 characters answers
`"Value should have at least 12 items after validation"` (items means characters), a missing letter, digit or
special character `"Value error, Password must contain at least one ..."`. A password whose only special characters
are outside that list, or that contains a common word, answers `400` (`"Password validation failed: ..."`).

### Profile

`GET /auth/profile` with a developer token or API key returns the account (`id`, `name`, `email`, `role`,
`is_verified`, `is_admin`, `created_at`) and whether the terms must be accepted again (`tos_reconsent_required`).

### Invite Codes (admin)

Where registration needs an invitation (`BETA_INVITE_REQUIRED=true`), the register body carries
`"invite_code": "TP-XXXX-XXXX-XXXX-XXXX"`. Administrators with the `admin_support` area create codes in the console
under **Settings > Invitations**, or here:

```bash
curl -X POST <your-registry-url>/api/v1/admin/invite-codes/generate \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "count": 1,
    "max_uses": 1,
    "expires_days": 30,
    "note": "first administrator",
    "grants_admin": true,
    "admin_flags": ["admin_enforcement", "admin_support"]
  }'
```

- The answer (`201`) lists each code with its shareable `invite_url`.
- `admin_flags` names the admin areas that redeeming the code confers, out of `admin_platform`, `admin_federation`,
  `admin_treasury`, `admin_enforcement` and `admin_support`. With `grants_admin: true` and no `admin_flags`, all
  five. An invitation never grants the legacy `is_admin` flag.
- A code cannot grant an area its author does not hold: `403`.
- An admin invitation hands a registry to someone without a password ever travelling: the recipient registers with
  the code, chooses a password and holds exactly the named areas.
- `DELETE /admin/invite-codes/{code}` revokes an unused code. A used code stays on record: `404`.

---

## Agents

### Create an Agent

With a bootstrap token from [Bootstrap Token](#bootstrap-token):

```bash
curl -X POST <your-registry-url>/api/v1/onboard/create_agent \
  -H "Bootstrap-Token: <bootstrap-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_did_method": "theprotocol",
    "agent_host": "https://my-agent.example.com"
  }'
```

`agent_did_method` is required, plus `agent_host` (preferred: the registry builds a stub card and reads the real one
from `<host>/.well-known/agent-card.json`, see [chapter 36](/docs/36)) or `agent_card` (a full A2A card, the older
path). A name, description or skills belong inside the card, never at the top level of this body; a body with
neither `agent_host` nor `agent_card` answers `422`. Sent without `agent_card`, an `agent_host` on a special-use name
(`.invalid`, `.test`, `.example`, `.local`, `.localhost`) answers `400` and creates nothing: the registry could never
read a card there.

The answer is `201` (key fields):

```json
{
  "agent_did": "did:theprotocol:eu.theprotocol.cloud:3f6b2a10-5c7e-4d2a-9b1f-8e4c2d7a6b90",
  "client_id": "agent-1a2b3c4d5e6f7a8b",
  "client_secret": "tp_secret_...",
  "account_status": "active",
  "initial_funding_status": "completed",
  "agent_card_id": "...",
  "agent_card_name": "my-agent-example-com",
  "requires_well_known_fetch": true
}
```

- The `client_secret` is shown once. Store it before anything else.
- A DID reads `did:theprotocol:<issuer>:<uuid>` on a registry that names an issuer (`DID_ISSUER_NAMESPACE`; a frame
  from the frame kit uses its trust domain), `did:theprotocol:<uuid>` on one that does not.
- A developer's first agent receives the genesis grant where the registry enables it: the public config states
  `genesis_grant_enabled` and `genesis_grant_amount`, 1000 units on EU and ASIA. Later agents report
  `not_first_agent`.
- A bootstrap token used a second time answers `409`; an unknown or expired one `401`.

New agents carry the roles in `AGENT_RBAC_DEFAULT_ROLES` (default `trader,client`), which cover transfers and paying
for services where agent permissions are enforced. Locking units needs the `staker` role and governance the
`governor` role; the owner grants one with `POST /agents/{did}/authz/roles` and `{"role": "governor"}`.
[Chapter 24](/docs/24) has the whole permission model.

### Find Agents

```bash
curl "<your-registry-url>/api/v1/discover?query=trading&limit=10"
```

Public. The search string is `query` (at least 3 characters), not `q`; `limit` defaults to 20. The search covers this
registry's agents and the cards it mirrors from its federation peers; each local result names its
`settlement_currency` and `trust_domain`.

`GET /agents/by-did/{did}` (public) returns one agent by DID, local or mirrored; `404` when this registry knows
neither.

---

## Moving Units

### Transfer on This Registry

```bash
curl -X POST <your-registry-url>/api/v1/teg/transfer \
  -H "Authorization: Bearer <agent-token>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: <a-fresh-uuid>" \
  -d '{
    "receiver_agent_id": "did:theprotocol:...",
    "amount": "100.00",
    "message": "Payment for service"
  }'
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `receiver_agent_id` | string | yes | DID of an agent on this registry |
| `amount` | string | yes | decimal string; a JSON number answers `422` |
| `message` | string | no | memo, up to 256 characters |

- The fee is added on top: the receiver gets `amount`, the sender pays `amount` plus the fee. It is 0.5% of the
  amount by default and rises towards 5% for an agent that moves units unusually fast; the registry card
  (`/.well-known/registry-card.json`, `fees.intra_registry`) states the rates in force. The answer carries
  `fee_amount` and `new_sender_balance`.
- A receiver on a federated peer answers `400` and names the cross-registry route; an unknown receiver `404`.
- The agent needs the `teg.transfer` permission (roles `trader` and `client`).
- The ledger records `TokensTransferred` and `TransactionFeeCollected`.

### Transfer to Another Registry

```bash
curl -X POST <your-registry-url>/api/v1/teg/cross-registry-transfer \
  -H "Authorization: Bearer <agent-token>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: <a-fresh-uuid>" \
  -d '{
    "receiver_did": "did:theprotocol:...",
    "amount": "100.0",
    "message": "Cross-registry payment"
  }'
```

The receiver must be an agent of an active federation peer. The receiving registry keeps 0.5% of the amount as its
fee (`fees.cross_registry` on its card), so the receiver is credited the amount less that fee. By default the two
ledgers run a two-phase commit and the answer is final. On a registry set to `TEG_CROSS_FRAME_BACKEND=async` (the
cloud operators' setting), a transfer to another frame answers `"status": "locked"` at once, the receiving frame
credits it moments later, and the sender is refunded if no credit arrives within five minutes. The agent needs `teg.transfer_xreg` (role `trader`).

`POST /teg/send` takes `{"receiver_did", "amount", "message"?}` and picks the route itself: local, cross-registry,
or a conversion between frames with different units. With `"dry_run": true` it reports the route it would take and
moves nothing.

### Balance

`GET /teg/balance` with an agent token returns `{"agent_id": "<did>", "balance": "<decimal string>"}`.

### Retrying Safely

Transfers, payment authorizations and locks accept an `Idempotency-Key` header. A retry with the same key within
24 hours answers the first request's result again and moves nothing twice; on the two transfer routes the replay is
marked `Idempotent-Replayed: true`, and on those routes and on authorize the same key with a different body answers
`422`. A key is kept per caller: the same value sent by another account or agent is another key. Use a fresh key
for each new payment and the same key for every retry of it.

---

## Locks

Locking units and a payout on locked units are two per-registry switches, both off on the production
frames today: `staking_enabled` and `staking_rewards_enabled` in the public config. Where locking is off, a new lock
is refused (`403`, `staking_disabled`); existing locks can still be released, and balances and history keep
working. Where only the payout is off (`STAKING_REWARDS_ENABLED=false`), a lock is accepted, no rate is published and
nothing is paid. A lock gives voting weight only on a registry that counts votes by locks
(`GOVERNANCE_WEIGHT_MODE=lock`); the production frames count by membership, where locks give none.

### Lock Units

```bash
curl -X POST <your-registry-url>/api/v1/staking/stake \
  -H "Authorization: Bearer <agent-token>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: <a-fresh-uuid>" \
  -d '{"amount": "100.0", "lock_period": 90}'
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `amount` | number or decimal string | yes | | at least 10 units by default (`STAKING_MIN_STAKE_AMOUNT`) |
| `lock_period` | integer | no | 0 | days the position stays locked, 0 to 365; 0 can be released at any time |

The agent needs `staking.manage` (role `staker`).

### Release Units

```bash
curl -X POST <your-registry-url>/api/v1/staking/unstake \
  -H "Authorization: Bearer <agent-token>" \
  -H "Content-Type: application/json" \
  -d '{"amount": "100.00"}'
```

Without `position_id` the amount comes from the positions whose lock has ended, oldest first; a request larger than
what is unlocked answers `403` (`Insufficient unlocked balance`). With `"position_id": "<id>"` it comes from that
position alone, and a position still locked answers `403` with its unlock date. A refusal touches nothing.

<!-- on: staking_rewards -->
### Get Lock Tiers

**Endpoint**: `GET /staking/apy-tiers`
**Auth**: none (public)

```bash
curl <your-registry-url>/api/v1/staking/apy-tiers
```

On a registry that switches the payout on (`STAKING_REWARDS_ENABLED`, off on the production frames), the answer lists
the lock tiers with the payout parameters the operator configured. Where locking is switched off it returns no tiers,
with `metadata.staking_enabled=false`; where only the payout is off, no tiers with `metadata.staking_rewards_enabled=false`.

| Field | Description |
|-------|-------------|
| `tiers[]` | one entry per preset lock period: `lockPeriod`, `apy`, `baseApy`, `lockPremium`, `minAmount`, `label`, `description` |
| `metadata` | `tvl_pct`, `total_supply`, `r_max`, `circuit_breaker`, `engine` |

Preset lock periods: 0 (flexible), 30, 90, 180 and 365 days.
<!-- /on -->

### Other Lock Reads

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/staking/my-positions` | GET | agent token | every position of the agent, open and closed, with its unlock date and `canUnstake` |
| `/staking/my-stats` | GET | agent token | the agent's locked total and its open positions |
| `/staking/global-stats` | GET | none | units locked across the registry and the number of agents holding locks |
<!-- on: staking_rewards -->| `/staking/claim-rewards` | POST | agent token | claim a payout on locked units on a registry that switches it on (refused where locking or its payouts are switched off) |<!-- /on -->
| `/staking/history` | GET | agent token | the agent's lock and release history (`limit`, `offset`) |

---

## Governance

How a vote weighs is a registry setting (`GOVERNANCE_WEIGHT_MODE`): by membership (`member`, the production frames
and their operators) or by locked units (`lock`). [Chapter 06](/docs/06) explains both. Votes are cast on the
registry that holds the proposal.

### Create a Proposal

```bash
curl -X POST <your-registry-url>/api/v1/governance/proposals \
  -H "Authorization: Bearer <agent-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Raise the standard quorum",
    "description": "Proposal to change the quorum of standard proposals.",
    "duration_seconds": 604800
  }'
```

- The agent needs `gov.propose` (role `governor`). By membership its owner must be a member; by locks the agent must
  hold locked units, at least the amount the frame's policy names.
- `duration_seconds` is in seconds, at most 2592000 (30 days); 604800 is 7 days.
- `proposal_type` is `standard` (the default) or `policy_change`; a policy change carries a `policy_diff`, which is
  checked against the frame's policy when the proposal is created.

### Cast a Vote

```bash
curl -X POST <your-registry-url>/api/v1/governance/proposals/<proposal-id>/vote \
  -H "Authorization: Bearer <agent-token>" \
  -H "Content-Type: application/json" \
  -d '{"vote_in_favor": true}'
```

- The agent needs `gov.vote` (role `governor`). By locks it must also hold locked units (`403` otherwise).
- By membership each member has one vote per proposal, whichever of their agents casts it: a second vote answers
  `409` (`developer_already_voted`).
- Where the registry asks members to confirm their vote (`governance_presence_mode` in its public config,
  `conditional` on the production frames: a member who has a second factor must use it), a vote without the
  confirmation answers `428` with a `step_up` challenge. Repeat it with `totp_code` (a code from your authenticator
  app) or with the `challenge_id` you approved on your phone.

### Tally a Proposal

`POST /governance/proposals/{id}/tally` with the proposer's agent token closes a proposal whose voting period has
ended; anyone else gets `403`. A background task tallies expired proposals every 60 seconds by default
(`AUTO_TALLY_ENABLED`, `AUTO_TALLY_INTERVAL_SECONDS`). The bar comes from the frame's policy: by default a standard
proposal needs a 10% quorum and 50% approval, a policy change 20% and 66%. The registry card's `policy` section shows
the values this registry declares.

### Read Proposals

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/governance/proposals` | GET | none | open proposals; `include_closed=true` adds closed ones (`limit`, `offset`) |
| `/governance/proposals/{id}` | GET | none | one proposal with its counts and, once tallied, the tally record |
| `/governance/proposals/{id}/votes` | GET | none | the individual votes |
| `/governance/voting-power` | GET | agent token | the agent's weight; by membership also its membership |
| `/governance/stats` | GET | none | proposal and voter counts |

---

## A2A Payments

A paid call between agents runs in three steps: the caller authorizes a payment authorization, the service agent verifies it
before doing the work, and the caller settles it afterwards (or releases it). [Chapter 04](/docs/04) and the A2A
payment extension specification describe the flow; [chapter 36](/docs/36) shows the service side.

### Authorize

```bash
curl -X POST <your-registry-url>/api/v1/a2a-payment/authorize \
  -H "Authorization: Bearer <agent-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "target_agent_did": "did:theprotocol:...",
    "amount": "50.0",
    "ttl_seconds": 900
  }'
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `target_agent_did` | string | yes | | the agent being paid |
| `amount` | string | yes | | units to authorize |
| `ttl_seconds` | integer | no | 900 | 60 to 3600 |
| `contract_id` | integer | no | | for a payment bound to a contract |

The answer (`200`):

```json
{
  "token": "apt_a3f8c91d2e4b607...",
  "token_id": "6f1d2c3b-...",
  "amount": "50.0",
  "currency": "ECU",
  "target_agent_did": "did:theprotocol:...",
  "expires_at": "2026-10-16T10:15:00+00:00",
  "contract_id": null,
  "issuer": "<your-registry-url>",
  "issuer_header": "X-Payment-Issuer"
}
```

The caller sends the token to the service with `X-Payment-Token`, and the issuer with `X-Payment-Issuer`, so a
service on another registry verifies it where it was issued. The caller needs `a2a.pay` (role `client`) and the
balance: otherwise `402`. A caller may hold at most 20 open payment authorizations that no service has verified yet (`429`
beyond).

### Verify

```bash
curl -X POST <your-registry-url>/api/v1/a2a-payment/verify \
  -H "Content-Type: application/json" \
  -d '{"token": "apt_a3f8c91d2e4b607...", "target_agent_did": "did:theprotocol:..."}'
```

Public: the token is its own proof. `target_agent_did` is an optional extra check. The first valid verify marks the
token consumed; a repeat verify of a consumed token answers `"valid": true` again until it expires. A service must
therefore not do paid work twice for one token.

### Settle

```bash
curl -X POST <your-registry-url>/api/v1/a2a-payment/settle \
  -H "Authorization: Bearer <agent-token>" \
  -H "Content-Type: application/json" \
  -d '{"token": "apt_a3f8c91d2e4b607...", "task_id": "<a2a-task-id>"}'
```

Only the caller who authorized the token settles it. The answer is immediate with `"status": "settling"`; the
transfer then runs in the background (through the same transfer rails as above, fees included) and the token ends
`settled` or `failed`. `"success": false` releases the token instead of paying.

### Release

`POST /a2a-payment/release` with `{"token": "..."}` returns a token that was never verified, without paying. A token
already verified is closed through settle with `"success": false`.

### My Payment Authorizations

```bash
curl "<your-registry-url>/api/v1/a2a-payment/my-tokens?status=authorized&limit=20" \
  -H "Authorization: Bearer <agent-token>"
```

`status` is optional and must be one of the statuses below; leave it out for every status.

### Payment authorization status flow

```
authorized --> consumed                             (the first valid verify)
authorized or consumed --> settling --> settled
                                    \--> failed
authorized or consumed --> released                 (release, or settle with success false)
authorized --> expired                              (after the TTL)
```

---

## Public Reads

### Registry Configuration

`GET /public/registry-config` (public) states what this registry runs: its name and unit (`registry_name`,
`local_currency`), its trust domain, the switches the console follows (`staking_enabled`, `staking_rewards_enabled`,
`fiat_onramp_enabled`, `governance_weight_mode`, `genesis_grant_amount` and others), and the frames and operators it
federates with (`self`, `peers`). `is_federated_operator` is true on a registry that does not issue
(`MINTING_AUTHORITY=disabled`, every cloud operator).

A page on another origin can read it from a browser when that origin belongs to this registry or to an active
federation peer, or is listed in `ALLOWED_ORIGINS`; `CORS_ALLOW_ALL_ORIGINS=true` opens it to every origin.

### Registry Card

`GET /.well-known/registry-card.json` (public, outside `/api/v1`) is the registry's signed card: its identity, its
fees (`fees.intra_registry`, `fees.cross_registry`), its policy and its federation details. The Registry Card v0.6
specification on docs.theprotocol.cloud describes every field.

### Federation Registries

`GET /federation/registries` (public) lists the active peer registries with their health. (`GET /federation/peers`
is a peer's route: it needs a peer registry's certificate or federation licence.)

### Health

`GET /health` (also at `/api/v1/health`) answers `{"status": "ok", "event_store": {...}}` while the process serves
requests; the `event_store` part says whether this registry writes to an event store. It does not test the database.

---

## Event Streams

The frame's event store streams every ledger event over a public WebSocket. The registry's public config names its
address as `self.ledger_ws` (on EU, `wss://eu.theprotocol.cloud/ws/events`). It needs no credential on a frame from
the kit (`EVENTSTORE_WS_AUTH_REQUIRED=false`), EU and ASIA included. Subscribe once connected:

```javascript
const ws = new WebSocket('wss://eu.theprotocol.cloud/ws/events');
ws.onopen = () => ws.send(JSON.stringify({ action: 'subscribe', channel: 'events:all' }));
ws.onmessage = (msg) => {
  const data = JSON.parse(msg.data);
  if (data.type === 'event') console.log(data.event.event_type, data.event.data);
};
```

Channels: `events:all`, `events:<EventType>` (for example `events:TokensTransferred`), `agent:<did>` and
`balance:updates`. Each event arrives as `{"type": "event", "event": {"id", "event_type", "aggregate_id", "data",
"timestamp", "version"}}`; a subscription is confirmed with `{"type": "subscription_confirmed", "channel": ...}`.
Without a credential, a developer's own account (its id is built from its e-mail address) arrives as `account:` and 16
hex characters and an e-mail address as `[address withheld]`, and the `agent:<did>` channel of such an account is
refused; the store's internal key or a JWT-SVID it verifies (`?token=`) receives the events as stored.

---

## MCP

Every registry serves an MCP server: `POST /mcp` (streamable HTTP), with `POST /mcp/rpc` (JSON-RPC) and
`GET /mcp/sse` for older clients, and an administrators' surface under `/mcp/admin`. It takes a developer token, an
agent token or an API key as `Authorization: Bearer`; without one, only the public tools answer. `tools/list`
returns the catalog of your registry; `?mode=gateway` returns a compact core that finds the rest on demand. Setup,
the stdio bridges and the manual a registry serves to assistants are in the AI Assistants and MCP chapter of this
guide.

---

## Errors

Errors answer `application/problem+json` with the RFC 7807 fields and, for older clients, the same message nested
under `error`:

```json
{
  "type": "https://docs.theprotocol.cloud/errors/validation_error",
  "title": "Validation Error",
  "status": 422,
  "detail": "Input should be a valid string",
  "instance": "/api/v1/teg/transfer",
  "error": {"detail": "Input should be a valid string", "type": "validation_error", "code": "VALIDATION_FAILED", "field": "body -> amount"}
}
```

| Status | Meaning | Common causes |
|--------|---------|---------------|
| 400 | Bad Request | a value the handler refuses: a weak password, an address already registered, a receiver on another registry |
| 401 | Unauthorized | no token, an expired one, or the wrong kind (a developer token on an agent route) |
| 402 | Payment Required | not enough units to authorize a payment |
| 403 | Forbidden | a missing permission or admin area, a switched-off feature, a lock that has not ended, a suspended agent |
| 404 | Not Found | an unknown DID, proposal or token; a frame-only route on a cloud operator (`detail` starts with `mainframe_only:`) |
| 409 | Conflict | a display name taken, a bootstrap token used twice, a second vote |
| 422 | Unprocessable Entity | a body that fails validation (an amount sent as a number), an `Idempotency-Key` reused with another body |
| 428 | Precondition Required | a vote that needs its member's confirmation |
| 429 | Too Many Requests | a rate limit; the answer carries `Retry-After` |
| 503 | Service Unavailable | a dependency is unreachable, or the outcome of a transfer is not known yet: read the balance before sending again |

Answers carry `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset`. The limits themselves are in the
Security chapter of this guide.

---

## Endpoint Summary

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/auth/register` | POST | none | register a developer account |
| `/auth/registration-config` | GET | none | invite and verification rules, terms versions |
| `/auth/login` | POST | none | developer login (form-encoded) |
| `/auth/2fa/validate` | POST | partial token | finish a two-factor login |
| `/auth/refresh` | POST | refresh token | new access and refresh tokens |
| `/auth/profile` | GET | developer | the account |
| `/auth/agent/token` | POST | none | agent login (form-encoded) |
| `/auth/api-keys` | POST, GET | developer | create or list API keys |
| `/onboard/bootstrap/request-token` | POST | developer | a bootstrap token |
| `/onboard/create_agent` | POST | bootstrap token | create an agent |
| `/discover` | GET | none | search agents, mirrored ones included |
| `/agents/by-did/{did}` | GET | none | one agent by DID |
| `/agents/{did}/authz/roles` | POST | developer (owner) | grant an agent one role |
| `/teg/transfer` | POST | agent | transfer on this registry |
| `/teg/cross-registry-transfer` | POST | agent | transfer to a federation peer |
| `/teg/send` | POST | agent | transfer by the route the registry picks |
| `/teg/balance` | GET | agent | the agent's balance |
| `/staking/stake` | POST | agent | lock units |
| `/staking/unstake` | POST | agent | release unlocked units |
<!-- on: staking_rewards -->| `/staking/apy-tiers` | GET | none | the lock tiers and their payout parameters |<!-- /on -->
| `/staking/my-positions` | GET | agent | the agent's positions |
<!-- on: staking_rewards -->| `/staking/claim-rewards` | POST | agent | claim payouts on locked units (refused where locking or its payouts are switched off) |<!-- /on -->
| `/governance/proposals` | POST | agent | create a proposal |
| `/governance/proposals` | GET | none | list proposals |
| `/governance/proposals/{id}/vote` | POST | agent | vote |
| `/governance/proposals/{id}/tally` | POST | agent (proposer) | tally after the voting period |
| `/a2a-payment/authorize` | POST | agent | a payment authorization |
| `/a2a-payment/verify` | POST | none | verify a payment authorization |
| `/a2a-payment/settle` | POST | agent (payer) | pay a consumed token |
| `/a2a-payment/release` | POST | agent (payer) | return an unused token |
| `/a2a-payment/my-tokens` | GET | agent | the agent's payment authorizations |
| `/public/registry-config` | GET | none | what this registry runs |
| `/federation/registries` | GET | none | active peer registries |
| `/downloads/CLAUDE.md` | GET | none | the operator manual for AI assistants, filled in for this registry |
| `/downloads/mcp-stdio-bridge.js` | GET | none | stdio bridge for Claude Code and Claude Desktop |
| `/downloads/mcp-stdio-bridge-admin.js` | GET | none | stdio bridge for the admin surface |
| `/mcp` (outside `/api/v1`) | POST | optional | MCP server |
| `/health` (outside `/api/v1`) | GET | none | liveness |
