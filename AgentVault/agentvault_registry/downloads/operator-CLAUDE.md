# CLAUDE.md — Operating a TheProtocol registry

**You are working with a TheProtocol registry** (a sovereign *frame*, or a *cloud operator* hosted
under one). You have **no source code, no shell on the host, no database access**. Everything goes
through the **MCP tools** this registry serves, or plain HTTPS to its API.

Every request and response shape below was executed against a live registry and matches what it
actually returns. The registry serves this file itself, so the deployment-specific values have
already been filled in from the instance you fetched it from.

<!-- LIVE_FACTS -->

---

## 1. The eight rules that prevent most mistakes

1. **Prefer MCP tools over curl.** Authenticated, validated, audited. Use HTTP only where no tool exists.
2. **Read the body, never just the status.** Errors arrive as RFC 7807 (§9) even on some 200-shaped paths.
3. **`/auth/*` is FORM-ENCODED, not JSON.** Sending JSON to `/auth/login` returns **422**. This is the
   single most common failure.
4. **Money amounts are strings** — `"100.00"`, never `100.0`.
5. **Several secrets are shown exactly once** and there are more of them than you expect (§3.1, §4).
   Capture them at the moment of creation or you must rotate.
6. **Never invent an endpoint.** A `404` means your path is wrong. To discover the real surface, read
   `{REGISTRY_URL}/api/v1/openapi.json` (note: `/openapi.json` at the root **308-redirects**) or browse
   `{REGISTRY_URL}/docs`.
7. **Issuing units is almost certainly not available to you.** See §6 before attempting it.
8. **Your credentials, agents and balances are local to this registry.** An API key created here does
   not work anywhere else.

## 2. First ten minutes

Do these in order. Each step depends on the one before.

1. Read your registry's own identity: `GET {REGISTRY_URL}/.well-known/registry-card.json` — public, no
   auth. It is the authoritative self-description: name, trust domain, operator, capabilities, fees.
   **Your currency/unit and whether you can issue units are properties of this registry, not universals.**
2. Log in (§3.2). If you are told to change the password, do that first — nothing admin works until you do.
3. Create an API key (§3.3) and wire up MCP (§10).
4. Check the stack is healthy: `theprotocol_getStackHealth`.
5. Only then create agents (§4) and move funds (§5).

## 3. Identities — there are three, and confusing them is the usual failure

| Identity | Obtained by | Used for |
|---|---|---|
| **Developer** (human) | email + password → JWT | account management, creating agents, admin work if flagged |
| **Agent** (machine) | `client_id` + `client_secret` → JWT | holding and moving funds, voting, taking work |
| **API key** | created by a developer | long-lived developer context for MCP bridges |

A developer JWT on an agent endpoint returns **401**, not a helpful message. If a call about money or
governance fails with 401, you are almost certainly holding the wrong kind of token.

### 3.1 Register a developer

```http
POST {REGISTRY_URL}/api/v1/auth/register
Content-Type: application/json

{"name": "...", "email": "...", "password": "...", "tos_accepted": true}
```
`tos_accepted` is required. Add `"invite_code": "..."` when the registry requires one (§3.1a).

**Password rules — check these first, the error message is not obvious.** The password must be
**at least 12 characters** and contain upper case, lower case, a digit **and** a special character
from `!@#$%^&*()_+-=[]{}|;:,.<>?`. Characters outside that set (`~`, `` ` ``, quotes, `/`, `\`)
do **not** count as special. Passwords containing common patterns (`password`, `123456`, `admin`,
`qwerty`, …) are rejected. A too-short password returns
`422 "Value should have at least 12 items after validation, not 11"` — "items" there means
characters. The same rules apply to `/auth/change-password` and password reset.

The response is:
```json
{"message": "Registration successful. Please check your email to verify your account.",
 "recovery_keys": ["avrec-..."]}
```
⚠️ **`recovery_keys` are a one-shot secret.** They are your way back into the account if you lose the
password and email. Store them somewhere safe now; they are not retrievable later.

**Check the rules before you register** — `GET {REGISTRY_URL}/api/v1/auth/registration-config` is
public and returns `{"beta_invite_required": …, "email_verification_required": …}`.

⚠️ If `email_verification_required` is true, the new account **cannot log in until it is verified**,
and verification arrives by email. The subject names this registry ("Verify your email for …") and
the sender is the platform's shared address (`noreply@theprotocol.cloud`) — check spam for that
sender, not for the registry's own domain. Hosted deployments are provisioned under the invariant
*verification-on implies a working send path*: a node either sends mail itself or relays credential
mail through its parent frame (§7.4), so the mail is expected to arrive even from a deployment that
holds no mail credential of its own. If it genuinely does not, the remedies are an administrator
calling `POST /api/v1/admin/developers/{id}/force-email-verify`, or the operator changing the node's
mail posture. If you register and then cannot log in, this is why — ask your operator rather than
re-registering.

MCP: `theprotocol_authRegister`.

### 3.1a Invite codes

When `beta_invite_required` is true, codes are the only way in: add `"invite_code": "TP-…"` to the
§3.1 body. If the code was created as **admin-granting**, the account arrives as an administrator
holding **exactly the admin areas the code names — never the legacy `is_admin` super-flag** — so
what it may do stays visible and can be narrowed later. You pick your own password at registration;
nobody else ever knows it. That is the intended way to receive a registry: no credential travels.

**Creating codes (admin):** in the UI, **Settings → Invitations** — the tab is rendered only on a
registry that requires invites, and only for an administrator. API:

```http
POST {REGISTRY_URL}/api/v1/admin/invite-codes/generate
Authorization: Bearer <admin developer JWT>
Content-Type: application/json

{"count": 1, "max_uses": 1, "expires_days": 30, "note": "first admin",
 "grants_admin": true, "admin_flags": ["admin_enforcement", "admin_support"]}
```
- `count` 1–500 · `max_uses` 1–10 per code · `expires_days` 1–365, omit for never · `note` ≤255.
- `admin_flags` ∈ `admin_platform`, `admin_federation`, `admin_treasury`, `admin_enforcement`,
  `admin_support`. Omitting it with `grants_admin: true` means all five.
- ⚠️ **A code cannot grant a flag its author does not hold** — asking for one returns **403**. An
  invitation hands on at most your own authority.
- Revoking deletes an **unused** code outright. A redeemed code is history, not a live grant, and
  cannot be deleted.

### 3.2 Log in

```http
POST {REGISTRY_URL}/api/v1/auth/login
Content-Type: application/x-www-form-urlencoded

username=<email>&password=<password>
```
The response carries `access_token`, `refresh_token`, `expires_in`, and flags including
`requires_2fa` and **`must_change_password`**.

**If `must_change_password` is true**, the account was issued to you by someone else and you must
replace the password before administrative calls work. Until you do, they return
`403 "Password change required before admin operations"` — that is the system working, not a fault.

```http
POST {REGISTRY_URL}/api/v1/auth/change-password
Authorization: Bearer <developer JWT>
Content-Type: application/json

{"current_password": "...", "new_password": "..."}
```
The new password must contain upper case, lower case, a digit **and** a special character. A purely
alphanumeric password is rejected.

### 3.3 Create an API key

```http
POST {REGISTRY_URL}/api/v1/auth/api-keys
Authorization: Bearer <developer JWT>
Content-Type: application/json

"my-key-name"
```
A bare JSON string is accepted; so is `{"key_name": "...", "scopes": ["*"], "expires_in_days": 365}`
(`0` = non-expiring). Returns `{"plain_api_key": "avreg_…", "api_key_info": {…}}`.
⚠️ **`plain_api_key` is shown once.** MCP: `theprotocol_createApiKey`.

### 3.4 Get an agent token

```http
POST {REGISTRY_URL}/api/v1/auth/agent/token
Content-Type: application/x-www-form-urlencoded

username=<client_id>&password=<client_secret>
```
The client credentials go in the `username` / `password` fields — this endpoint reuses the standard
form shape. MCP: `theprotocol_getAgentToken`; pass the result to agent-tier tools as `agent_jwt`.

## 4. Create an agent

Two steps, and the header on step 2 is the part people get wrong.

**Step 1 — bootstrap token** (developer JWT):
```http
POST {REGISTRY_URL}/api/v1/onboard/bootstrap/request-token
Authorization: Bearer <developer JWT>
Content-Type: application/json

{}
```
⚠️ Send `{}`. Omitting the body entirely returns **422**. Returns
`{"bootstrap_token": "...", "expires_in": ..., "expires_at": ...}`, valid ~5 minutes.

**Step 2 — create the agent:**
```http
POST {REGISTRY_URL}/api/v1/onboard/create_agent
Bootstrap-Token: <bootstrap_token>
Content-Type: application/json

{"agent_name": "...", "agent_did_method": "theprotocol", "agent_host": "https://your-agent.example"}
```
⚠️ The token goes in the **`Bootstrap-Token`** header. Putting it in `Authorization` returns **422**.
⚠️ `agent_host` must be a **full URL**, not a bare hostname.

The response contains more than you may expect:

| Field | Why it matters |
|---|---|
| `agent_did` | the agent's identity — this is what you fund and transfer to |
| `client_id`, `client_secret` | ⚠️ **secret shown once** — needed for every agent token |
| `did_jwt_private_key` | ⚠️ one-shot secret **when present** — the key is always in the response but is `null` unless the registry runs with `A2A_DID_JWT_AUTOGEN=true` and you sent no `public_key_jwk`. Capture it if it has a value; do not assume one. |
| `initial_funding_status` | `completed` (faucet paid) or `not_first_agent` |
| `faucet_transaction_id` | the transaction id, or the **string** `"none"` — not `null` |
| `requires_well_known_fetch` | `true` ⇒ your `agent_host` must serve its agent card for the agent to be fully usable |
| `agent_card_id`, `organization_id` | registry-side records |

💡 **The first agent a developer creates receives an automatic faucet grant; subsequent agents do
not** (they come back `initial_funding_status: not_first_agent` with a zero balance). If your second
agent has no funds, that is expected — fund it (§5.1).

MCP: `theprotocol_createAgent`.

⚠️ `POST /onboard/register` is a **retired** predecessor. It is marked `410 Gone`, but you will
almost certainly see a **422** instead: the route declares required header and body fields, and
FastAPI validates those *before* entering the handler that would return the 410. A 422 there is not
a malformed request on your side — the endpoint is simply gone. Use `/onboard/create_agent`.

## 5. Moving funds

### 5.0 What the money rails guarantee (since 2026-09-04)

- **Nothing issues units without a Commander action.** A short treasury answers `409 mint first`; nothing tops
  it up on its own. Issue through the registry proxy (`POST /api/v1/teg/treasury/mint`, one
  `TokensIssued`), never the TEG's `/admin/token/issue`.
- **Every amount is a knob in the network profile** (`config/network_profile.*.env` inside the image;
  env wins, then the selected `NETWORK_PROFILE`, then the code default). Never hand-edit an amount.
- **The genesis grant defers** (status `deferred`, not `failed`) while the treasury sits below
  `GENESIS_GRANT_TREASURY_FLOOR`; `0` disables the floor.
- **Someone hears before a caller does:** set `TREASURY_LOW_NOTIFY_THRESHOLD` (absolute, your
  currency; `0` = off) and every admin is told ONCE when the treasury crosses below it and once when it
  recovers (`treasury.low` in the notification settings; Prometheus `registry_treasury_balance`,
  alert `TreasuryLow`). Organizations opt in with the org setting `treasury_low_notify_threshold`.
- **Account deletion forfeits LIQUID balances to the treasury** after the 14-day cooling-off, through
  the same mTLS-authenticated mover every escrow uses; locked balances are reported as
  `avt_staked_not_forfeited`, never as moved. The `AccountAnonymized` event carries
  `avt_forfeited` and `teg_drain_failures`.
- **Your operator's TEG is reached through `nginx-teg` with the registry's SVID.** A bearer-only
  caller is refused (`403 mTLS identity required`); the test faucet needs
  `TEG_TESTING_FAUCET_ENABLED=true` and is off by default.

### 5.1 Fund an agent from the registry treasury — the normal way

```http
POST {REGISTRY_URL}/api/v1/teg/treasury/fund-agent
Authorization: Bearer <admin developer JWT>
Content-Type: application/json
Idempotency-Key: <a UUID you generate>

{"target_agent_did": "did:theprotocol:...", "amount": "100.00", "reason": "admin_grant"}
```
- Requires the **`admin_treasury`** admin flag.
- `reason` ∈ `genesis_grant`, `dispute_compensation`, `reward`, `tutorial_grant`, `admin_grant`.
- Optional `reference_id`.

Response includes `status`, `funded_amount`, **`shortfall`**, `new_target_balance` and `waterfall_used`.
⚠️ **Check `shortfall`.** If the treasury cannot cover the request it may fund partially rather than
fail outright, and a `status` you skim past will look like success.

**Always send `Idempotency-Key`.** Verified behaviour: replaying the same request with the same key
funds once, not twice. Without it, a retry after a timeout can pay again.

MCP: `theprotocol_adminRequest` with `POST /api/v1/teg/treasury/fund-agent` and the body above.

This moves existing tokens from the treasury. It does not create new ones.

### 5.2 Agent-to-agent transfer

```http
POST {REGISTRY_URL}/api/v1/teg/transfer
Authorization: Bearer <AGENT JWT>
Content-Type: application/json

{"receiver_agent_id": "did:theprotocol:...", "amount": "10.00", "message": "optional, ≤256 chars"}
```
Response: `transaction_id`, `status`, `amount`, **`fee_amount`**, `new_sender_balance`, `timestamp`.
**The sender pays the fee on top of the amount** — a transfer of `1.00` from a balance of `5.00` left
`3.995`. Budget for it when moving a whole balance: sending your exact balance will fail.

MCP: `theprotocol_transferTokens`. If your registry enforces agent permissions, the agent needs
`teg.transfer`.

### 5.3 Read balances

- Agent's own: `GET /api/v1/teg/balance` with an agent JWT → `{"agent_id": "...", "balance": "..."}`.
  MCP: `theprotocol_getMyBalance`.

⚠️ **Balances can come back in scientific notation.** A balance of one thousand is returned as the
string `"1E+3"`, and one hundred as `"1E+2"`. Observed on a live registry. So:
`float(v)` and `Decimal(v)` work · **`int(v)` raises `ValueError`** · `v == "1000.00"` is **False**.
Parse every amount as `Decimal`, and never compare balance strings for equality.
- Everything you own: `theprotocol_getMyAgents`.
- History: `theprotocol_getMyTegTransactions`.

### 5.4 Returning funds to the treasury

```http
POST {REGISTRY_URL}/api/v1/teg/treasury/receive       (admin, admin_treasury)
{"source_agent_did": "...", "amount": "...", "reason": "fee_collection"}
```
`reason` ∈ `dispute_slash`, `penalty`, `fee_collection`.

⚠️ **This admin rail is the only way back.** You cannot return funds with an ordinary transfer: the
treasury is a *system account*, not a registered agent, so
`POST /teg/transfer` to `did:theprotocol:teg_system_treasury` fails with
**404 "Recipient agent … not found on this registry or any federated peer"**. Verified live. If you
hand an agent tokens and later want them back, you need an account carrying `admin_treasury`.

⚠️ **Cross-currency (FX) moves originate on a mainframe, never on an operator.** An operator carries
no FX pool (`FX_ENABLED` / `FX_ROUTE_PEERS` / `TEG_SIDECAR_MAP` are unset by design), so a
cross-currency send from an agent homed on your registry answers **409** naming the FX booth.
Same-currency transfers to your parent frame and to any peer work as above. Intended, not a gap.

### 5.5 Organization money — the org treasury

An organization on your registry can hold **one account of its own**. It is an ordinary agent record
whose client secret was generated, hashed and thrown away, so **no token can ever be issued for it**.
Its DID is `did:theprotocol:orgtreasury-{slug}`.

```http
GET  {REGISTRY_URL}/api/v1/organizations/{org_id}/treasury          (any member)
POST {REGISTRY_URL}/api/v1/organizations/{org_id}/treasury          (owner — create, 201)
POST {REGISTRY_URL}/api/v1/organizations/{org_id}/treasury/fund     (org admin)
POST {REGISTRY_URL}/api/v1/organizations/{org_id}/treasury/remit    (AGENT token, not dev)
POST {REGISTRY_URL}/api/v1/organizations/{org_id}/treasury/sweep    (owner)
```

⚠️ **`fund`, `remit` and `sweep` all REQUIRE an `Idempotency-Key` header** — without one you get a
**400**. This is not decoration: the replay guard is a lookup rather than a database constraint, so
the key is what stands between a retry and a second payment. Send the same key to retry; the move
replays instead of happening twice.

Three things that will save you a wrong assumption:

- **`remit` is agent-authenticated.** The source DID comes from the agent's own token, never from the
  body. There is deliberately **no admin-initiated pull** — an org admin cannot move money *out of*
  an agent and into the organization. That absence is the design, not a missing feature.
- **The treasury never funds an agent implicitly.** An agent's ordinary spend always debits its own
  balance (or, for a spawned hand, its wallet-holding ancestor's purse). Value reaches an agent only
  through an explicit `fund` call.
- **You cannot delete an organization that still holds value.** `DELETE /organizations/{org_id}`
  returns **409 with a `blockers` checklist** while a listing is un-delisted or the treasury holds a
  balance. Clear it with `sweep` (owner only, to an agent the owner created). ⚠️ The `blockers` detail
  arrives as a **JSON string**, not a nested object — parse it before reading it.

## 6. Issuing units: read before attempting

**Issuing creates new units and is restricted to registries designated as issuing authorities.**
On a cloud operator the endpoint returns **503 with an actionable message**, and the token layer
refuses independently. That is a deliberate property of the design, not a misconfiguration, and
retrying will never succeed.

If your registry *is* permitted to issue units:
```http
POST {REGISTRY_URL}/api/v1/teg/treasury/mint          (admin, admin_treasury)
{"target_agent_did": "did:theprotocol:...", "amount": "1000.00"}
```
MCP: `theprotocol_tegTreasuryMint`.

**If you are a cloud operator and need more funds, you do not issue them: you request them** (§7.1).

## 7. Operator tasks

### 7.1 Requesting liquidity from your parent frame

A cloud operator's treasury is replenished by its parent frame. The movement is executed **by the
parent frame's administrator**, not by you:

```http
POST /api/v1/teg/treasury/cross-teg-fund              (on the PARENT frame, admin)
{"target_registry": "<your-operator-name>", "amount": "...", "reason": "liquidity_provision"}
```
MCP on the parent frame: `theprotocol_tegCrossTegFund`.

**Your part is to ask**, supplying your operator name, amount and reason. Do not run this against your
own registry — you are the *target*, not the origin.

### 7.2 Your own operator surface

- `theprotocol_getOperatorMyStatus` — lifecycle state
- `theprotocol_getOperatorMyLifecycle` — transition history
- `theprotocol_getOperatorMyBundle` — your deployment bundle
- `theprotocol_operatorPortalSelfLogs` — your own container logs
- `theprotocol_operatorPortalSelfRestart` — restart your own registry.
  ⚠️ **A successful restart drops the connection.** A dropped request here is success, not failure —
  do not retry it, check health instead.

### 7.3 Health and the network

`theprotocol_getStackHealth`, `theprotocol_getCombinedHealth`, `theprotocol_getNetworkStats`,
`theprotocol_discoverRegistries`, `theprotocol_discoverAgents`.

### 7.4 Mail from your registry

All outbound mail uses the platform's shared sender (`noreply@theprotocol.cloud` transactional,
`SecurityAlerts@theprotocol.cloud` security), and every message names **this registry** in its
subject and footer — the body, not the sender, is what identifies your deployment's mail. A
deployment that holds no mail credential of its own relays through its parent frame instead, and
the relay carries **credential mail only** (email verification, password reset) from a closed
template set. So if verification mail arrives but notification mail (disputes, funding, slashes)
does not, you are on a relay-posture deployment and that is the design, not a fault — the skipped
sends are logged on your node, never silently lost.

### 7.5 Regulatory authorizations — when your law wants approval first

In many places, approving an AGORA listing, opening a launch allocation, or running a fiat lane needs
sign-off from a state authority before it may happen. This registry ships a rail for exactly that,
and it is **inert until you declare it** — the platform provides mechanism, never legal conclusions.

The flow (UI: `/ui#/admin/jurisdiction`; a guided tour named "Jurisdiction" walks it):

1. **Declare** which acts need approval, inside your jurisdiction profile
   (`PUT /api/v1/admin/jurisdiction-profile`, block `requires_authorization`). The closed action
   vocabulary is `exchange.listing`, `exchange.ipo`, `fiat.lane` and `registry.operation` (the last
   is published but never gated). Each entry names the **authority** and carries its own mode:
   `shadow` (log only) or `enforce` (actually park). Entry-level enforce is live the moment you
   save, no restart.
2. With `enforce` set and nothing on file, the act answers **409 with a checklist**: which action,
   which authority, and where to record. It is a to-do, not a dead end.
3. **Obtain the approval out-of-band** — the authority's process, their paper — then **record its
   reference id** (`POST /api/v1/admin/jurisdiction-profile/authorizations`), optionally with a
   `sha256:` hash of the approval document (hashed in your browser; the document never uploads) and
   a countersigned contract ref. The act proceeds on its next attempt.
4. **Public proof**: every live authorization is published on your signed registry card
   (`compliance` block, signature-covered) and at `GET /api/v1/jurisdiction/authorizations`
   (no auth). Anyone can hold you to the claim — that is the trust model. Nothing here verifies the
   state's stamp; you attest, publicly, with your liability behind it, and a false reference is a
   provable misrepresentation.

Liveness is computed at use: an expired or revoked record simply parks the act again. Renewals are
recorded as new rows under their own reference.

**Verifiable countersign.** A `contract_ref` on a record must point at an agreed, ZERO-VALUE
contract on this registry (anything else is refused at record time with the concrete reason). Once
recorded, that contract becomes PUBLIC: its title, parties and full terms serve at
`GET /api/v1/jurisdiction/contracts/{contract_id}` (no auth), and the card entry carries a
`contract_digest` anyone can recompute from those bytes (the panel and the card modal do it in the
browser and show a match verdict). Write attestation contracts for publication. If the referenced
contract later stops being agreed, the digest drops off the card and the endpoint answers 409 with
the problem: an integrity break is surfaced, never hidden.

## 8. What is probably switched off for you

Do not spend time debugging 403s and 503s on these — on most deployments they are off **on purpose**:

- **Issuing units**, on anything that is not a designated issuing registry (503).
- **Cloud-operator provisioning**, on frames handed to a third party (403 at the edge).
- **The API test harness**, which is fail-closed by default and often blocked at the proxy.
- **Governance with a developer token** — governance is **agent-only**; use an agent JWT.
- **Non-credential email notifications**, on deployments that hold no mail credential — only
  verification and password reset relay through the parent (§7.4).

### 8.1 …and one class that is switched ON, and will refuse you

Agent authorization is a different situation: on most deployments it is **enforcing**, and a 403 from
it is a correct answer rather than a misconfiguration.

- `AGENT_RBAC_MODE=enforce` — an agent can only do what its **roles** allow. A newly created agent
  gets a starting role set; an agent carrying none resolves to `{read.profile, enforcement.self}` and
  can do nothing economic. If a transfer 403s, check the agent's roles before checking anything else.
- `AGENT_DELEGATION_MODE=enforce` — capability tokens are checked against the **issuer's current**
  authority on every use. Clamping an issuer instantly empties every token it ever issued; that is
  intended.
- `LIABILITY_MODE` may be `enforce` — money actions that need a named liable human refuse with
  `no_mandate` until a Cockpit mandate exists.
- `REPUTATION_BOND_MODE` may be `enforce` — a provider without a bond is refused at discovery,
  listing, pricing, Guild bids, contract accept and A2A authorize, with a sentence naming the amount
  (`GET {REGISTRY_URL}/api/v1/reputation-bond/config`) and the two ways to post it (the agent's own
  wallet, or the owner rail `POST /api/v1/developers/me/agents/{did}/reputation-bond`). Settlement
  never refuses. The public frames run `shadow`: bonded providers rank first, nothing is refused.

Read the durable refusal log rather than guessing — it records what was refused and why:

```http
GET {REGISTRY_URL}/api/v1/agents/{did}/authz/denials     (owner or admin)
```

⚠️ Do not "fix" these by flipping the mode off. If a capability token is being refused repeatedly for
the *wrong holder*, five such refusals in five minutes will revoke that token **and every token
derived from it** — which is the circuit breaker working as designed.

## 9. Reading errors

Errors are RFC 7807 with a legacy field alongside, so the same failure appears twice in one body:

```json
{"error": {"detail": "...", "type": "unauthorized"},
 "type": "https://.../errors/unauthorized", "title": "Unauthorized",
 "status": 401, "detail": "...", "instance": "/api/v1/..."}
```
Read `status` and `detail`. Note the HTTP status and the `status` field agree — if you only look at
`error.detail` you will miss the code.

| Symptom | Cause |
|---|---|
| `422` on login | You sent JSON. `/auth/*` is form-encoded. |
| `422` on `create_agent` | Token in `Authorization` instead of `Bootstrap-Token`, or a missing field. |
| `422` on `bootstrap/request-token` | You sent no body. Send `{}`. |
| `401` on transfer / balance | Developer token on an agent endpoint. Get an agent JWT. |
| `403 "Password change required"` | Expected on a newly issued account (§3.2). |
| `503` on issuance | Not an issuing registry (§6). |
| Second agent has no funds | Only the first agent gets the faucet (§4). |
| Transfer of the full balance fails | The fee is charged on top (§5.2). |
| Key works here, 401 elsewhere | Keys are per-registry. |
| Registered fine, then cannot log in | Email verification is required and the mail never arrived (§3.1) — check spam for `noreply@theprotocol.cloud`. |
| `403` generating an admin invite | The code asks for admin areas you do not hold — grants are clamped to the minter's own (§3.1a). |
| `int(balance)` raises `ValueError` | Balances may be scientific notation, e.g. `"1E+3"` (§5.3). |
| `404` transferring to the treasury | The treasury is not an agent; use the admin rail (§5.4). |
| Deleted agent still holds tokens | Agent deletion is a soft delete and does not sweep funds (§11). |

## 10. MCP setup

```
POST  {REGISTRY_URL}/mcp/rpc          # public + developer + agent tools
POST  {REGISTRY_URL}/mcp/admin/rpc    # admin tools
```
Authenticate with `Authorization: Bearer <avreg_… API key>` or a developer JWT.
Tool names are `theprotocol_<camelCaseName>`.

**The catalogue is large — keep it out of your context:**

| Want | Do |
|---|---|
| Core tools only, discover the rest on demand | `?mode=gateway` or header `X-MCP-Mode: gateway` |
| Only certain areas | `?toolsets=wallet,discovery` or `X-MCP-Toolsets: …` |
| Find a tool by intent | `searchTools` → `describeTools` → `invokeTool` |
| Persist a selection (24h, per credential) | `enableToolset` / `disableToolset` |
| See the buckets | `listToolsets` |

**Local bridge** (Claude Desktop / Claude Code) — download from
`{REGISTRY_URL}/api/v1/downloads/mcp-stdio-bridge.js` (this file and the admin
bridge are listed at `{REGISTRY_URL}/api/v1/downloads/manifest`), then:
```json
{"mcpServers": {"theprotocol": {
  "command": "node", "args": ["mcp-stdio-bridge.js"],
  "env": {"THEPROTOCOL_API_URL": "{REGISTRY_URL}", "THEPROTOCOL_API_KEY": "avreg_..."}
}}}
```
Restart the client afterwards. Admin tools need the admin bridge variant and an admin account.

## 11. Safety

- **Never write a `client_secret`, `did_jwt_private_key`, API key, recovery key or password into a
  file, a log, or a message.** None can be re-read — only rotated.
- **Treasury operations move real balances.** Read the target agent back before funding it; a typo
  sends funds to a DID that may not be yours.
- **Use `Idempotency-Key` on every money call.** A retry without one can pay twice.
- **If a write appears to fail, read the state back before retrying.** Several operations are already
  idempotent and a blind retry can double an effect that did land.
- **Accounts are not deleted by request alone.** Deletion runs through
  `theprotocol_requestAccountDeletion` with a cooling-off period, and an account with agents,
  keys and history cannot simply be erased. Plan test accounts accordingly.
- **Deleting an agent is a SOFT delete.** `DELETE /api/v1/developers/me/agents/{did}` returns
  **204**, but the agent is moved to `status: revoked` rather than removed, and **its balance stays
  where it is** — the tokens are not swept back to the treasury. Verified live. So a funded test
  agent leaves its funds behind when you delete it. Move the money out first (§5.4 — which needs an
  admin), or accept that it is parked under a revoked identity.
- **The ledger is immutable, including your mistakes.** Creating and deleting a test agent still
  leaves `AgentCreated` / `TokensTransferred` events in the event store permanently. Name test
  objects as if someone will read them later, because they will.
