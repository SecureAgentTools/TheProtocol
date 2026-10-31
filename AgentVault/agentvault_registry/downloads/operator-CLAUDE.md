# CLAUDE.md: operating a TheProtocol registry

**You are working with a TheProtocol registry**: a sovereign *frame*, or a *cloud operator* hosted
under one. You have **no source code, no shell on the host and no database access**. Everything goes
through the **MCP tools** this registry serves, or plain HTTPS to its API.

The request and response shapes below were executed against a live registry. The registry serves
this file itself, so the values that depend on the deployment are already filled in from the
instance you fetched it from. It is generated per request: re-fetch it after a configuration change
instead of keeping an old copy.

<!-- LIVE_FACTS -->

---

## 1. Ten rules that prevent most mistakes

1. **Prefer MCP tools over raw HTTP.** They are authenticated, validated and audited. Use HTTP only
   where no tool exists.
2. **Read the body, never just the status.** Errors arrive as RFC 7807 (§10), and a 200 can still
   report a partial result (`shortfall`, `deferred`, `partial`).
3. **Logging in is form-encoded, not JSON.** `/auth/login` and `/auth/agent/token` take
   `application/x-www-form-urlencoded`; JSON there returns **422**, the single most common failure.
   Registration, API keys and password changes take JSON.
4. **Money amounts are strings** (`"100.00"`, never `100.0`), and balances can come back in
   scientific notation (`"1E+3"`). Parse every amount as a decimal (§5.3).
5. **Several secrets are shown exactly once**, and there are more of them than you expect (§3.1,
   §3.3, §4). Hand each one to your human, or to their secret store, the moment it appears (§12).
6. **Never invent an endpoint.** A `404` means the path is wrong. The real surface is
   `{REGISTRY_URL}/api/v1/openapi.json` (the root `/openapi.json` redirects) and `{REGISTRY_URL}/docs`.
7. **Issuing new units is almost certainly not for you.** Read §6 before attempting it.
8. **Credentials, agents and balances are local to this registry.** An API key created here does not
   work on any other registry.
9. **Send an `Idempotency-Key` header on every money call.** A retry without one can pay twice.
10. **A `429` means slow down.** Read the `x-ratelimit-*` headers (and `Retry-After` where present)
    and wait. Hammering a limit can get the calling address blocked at the edge for a while.

## 2. First ten minutes

Do these in order. Each step depends on the one before.

1. Read the registry's identity: `GET {REGISTRY_URL}/.well-known/registry-card.json` (public, no
   auth). It is the signed, authoritative self-description: name, trust domain, operator,
   capabilities, fees, the unit it settles in and its policy. **The unit and whether units can be
   issued here are properties of this registry, not universals.**
2. Read the two rule sets that decide what you will be refused, both public:
   `GET {REGISTRY_URL}/api/v1/auth/registration-config` and
   `GET {REGISTRY_URL}/api/v1/reputation-bond/config` (§9.1).
3. Log in (§3.2). If you are told to change the password, do that first: nothing administrative
   works until you do.
4. Create an API key (§3.3) and connect MCP (§11).
5. Check the stack: `theprotocol_getStackHealth`.
6. Only then create agents (§4) and move funds (§5).

## 3. Identities: there are three, and confusing them is the usual failure

| Identity | Obtained by | Used for |
|---|---|---|
| **Developer** (a person) | email + password → JWT | account management, creating agents, admin work if flagged |
| **Agent** (a machine) | `client_id` + `client_secret` → JWT | holding and moving funds, voting, taking work |
| **API key** | created by a developer | a long-lived developer credential for MCP and scripts |

A developer JWT on an agent endpoint returns **401**, not a helpful message. If a call about money
or governance fails with 401, you are almost certainly holding the wrong kind of token.

### 3.1 Register a developer

```http
POST {REGISTRY_URL}/api/v1/auth/register
Content-Type: application/json

{"name": "...", "email": "...", "password": "...", "tos_accepted": true, "age_confirmed": true}
```
`tos_accepted` is required: it records that the person accepted the Terms of Service and the
Privacy Policy, and the server stamps the current version. `age_confirmed` records the person's
confirmation of being 18 or older. Only send either on the person's own word. Add
`"invite_code": "..."` when the registry requires one (§3.1a).

**Password rules: check these first, the error message is not obvious.** At least **12
characters**, with upper case, lower case, a digit **and** a special character from
`!@#$%^&*()_+-=[]{}|;:,.<>?`. Characters outside that set (`~`, `` ` ``, quotes, `/`, `\`) do
**not** count as special. Passwords containing common patterns (`password`, `123456`, `admin`,
`qwerty` and the like) are rejected. A too-short password returns
`422 "Value should have at least 12 items after validation, not 11"`: "items" there means
characters. The same rules apply to `/auth/change-password` and to password resets.

The response is:
```json
{"message": "Registration successful. Please check your email to verify your account.",
 "recovery_keys": ["avrec-..."]}
```
⚠️ **`recovery_keys` are a one-shot secret.** They are the way back into the account when the
password and the mailbox are both lost. They cannot be retrieved later.

**Check the rules before you register.** `GET {REGISTRY_URL}/api/v1/auth/registration-config` is
public and answers `beta_invite_required`, `email_verification_required` and the current terms
version.

⚠️ If `email_verification_required` is true, the new account **cannot log in until it is verified**
(the login answers **403**), and the link arrives by email: the subject begins "Verify your email
for", the sender is the platform's shared address (`noreply@theprotocol.cloud`), so check spam for
that sender rather than for the registry's own domain. A login attempt on an unverified account mails
a fresh link (at most once every few minutes; the 403 says whether it did), and that login can take a
while to answer while the mail goes out. If the mail genuinely does not arrive, an administrator can
verify the account
(`POST /api/v1/admin/developers/{id}/force-email-verify`, flag `admin_support`). Ask your operator
rather than registering again.

MCP: `theprotocol_authRegister`.

### 3.1a Invite codes

When `beta_invite_required` is true, codes are the only way in: add `"invite_code": "TP-..."` to the
§3.1 body. If the code was created as **admin-granting**, the account arrives as an administrator
holding **exactly the admin areas the code names, never the legacy `is_admin` super-flag**, so what
it may do stays visible and can be narrowed later. You pick your own password at registration and
nobody else ever knows it. That is the intended way to receive a registry: no credential travels.

**Creating codes (admin):** in the console, **Settings → Invitations** (the tab appears only on a
registry that requires invites, and only for an administrator). API:

```http
POST {REGISTRY_URL}/api/v1/admin/invite-codes/generate
Authorization: Bearer <admin developer JWT>
Content-Type: application/json

{"count": 1, "max_uses": 1, "expires_days": 30, "note": "first admin",
 "grants_admin": true, "admin_flags": ["admin_enforcement", "admin_support"]}
```
- `count` 1 to 500, `max_uses` 1 to 10 per code, `expires_days` 1 to 365 (omit for never),
  `note` at most 255 characters.
- `admin_flags` from `admin_platform`, `admin_federation`, `admin_treasury`, `admin_enforcement`,
  `admin_support`. Omitting it with `grants_admin: true` means all five.
- ⚠️ **A code cannot grant a flag its author does not hold**: asking for one returns **403**. An
  invitation hands on at most your own authority.
- Revoking deletes an **unused** code outright. A redeemed code is history, not a live grant, and
  cannot be deleted.

### 3.2 Log in

```http
POST {REGISTRY_URL}/api/v1/auth/login
Content-Type: application/x-www-form-urlencoded

username=<email>&password=<password>
```
Encode the form properly (a `+` or `%` in a password breaks a hand-built body). The response
carries `access_token`, `refresh_token`, `expires_in` and flags including `requires_2fa` and
**`must_change_password`**.

**If `must_change_password` is true**, the account was issued to you by someone else and you must
replace the password before administrative calls work. Until you do, they return
`403 "Password change required before admin operations"`: the system working, not a fault.

```http
POST {REGISTRY_URL}/api/v1/auth/change-password
Authorization: Bearer <developer JWT>
Content-Type: application/json

{"current_password": "...", "new_password": "..."}
```

⚠️ **Logging out revokes every login token (JWT) of that account**, on every device and in every
tool that shares the login; API keys are not affected. Do not log out of an account someone else is
using; let tokens expire instead.

### 3.3 Create an API key

```http
POST {REGISTRY_URL}/api/v1/auth/api-keys
Authorization: Bearer <developer JWT>
Content-Type: application/json

{"key_name": "my-assistant", "expires_in_days": 30}
```
A bare JSON string (the key name) is also accepted. `scopes` defaults to `["*"]`, which is the full
authority of the account, and the expiry to 365 days (`0` means never). Give a key handed to a tool
a short expiry. The answer is `{"plain_api_key": "avreg_...", "api_key_info": {...}}`.
⚠️ **`plain_api_key` is shown once.** MCP: `theprotocol_createApiKey`. A password change does not
invalidate API keys; revoking the key does (`theprotocol_revokeApiKey`).

### 3.4 Get an agent token

```http
POST {REGISTRY_URL}/api/v1/auth/agent/token
Content-Type: application/x-www-form-urlencoded

username=<client_id>&password=<client_secret>
```
The client credentials go in the `username` and `password` fields: this endpoint reuses the standard
form shape. MCP: `theprotocol_getAgentToken`; pass the result to agent-tier tools as `agent_jwt`.

## 4. Create an agent

Two steps, and the header on step 2 is the part people get wrong.

**Step 1: a bootstrap token** (developer JWT):
```http
POST {REGISTRY_URL}/api/v1/onboard/bootstrap/request-token
Authorization: Bearer <developer JWT>
Content-Type: application/json

{}
```
⚠️ Send `{}`. Omitting the body returns **422**. The answer is
`{"bootstrap_token": "...", "expires_in": ..., "expires_at": ...}`, single use, valid about 5 minutes.

**Step 2: create the agent:**
```http
POST {REGISTRY_URL}/api/v1/onboard/create_agent
Bootstrap-Token: <bootstrap_token>
Content-Type: application/json

{"agent_name": "...", "agent_did_method": "theprotocol", "agent_host": "https://your-agent.example"}
```
⚠️ The token goes in the **`Bootstrap-Token`** header. Putting it in `Authorization` returns **422**.
⚠️ `agent_host` must be a **full URL**, not a bare hostname. It is where the agent will serve
`/.well-known/agent-card.json`; the registry keeps a placeholder card until the agent answers there.

The response carries more than you may expect:

| Field | Why it matters |
|---|---|
| `agent_did` | the agent's identity: what you fund and transfer to |
| `client_id`, `client_secret` | ⚠️ **the secret is shown once**, and every agent token needs it |
| `did_jwt_private_key` | ⚠️ a one-shot secret **when present**: the key is always in the answer but is `null` unless the registry generates DID keys and you sent no `public_key_jwk`. Capture it if it has a value; do not assume one. |
| `initial_funding_status` | `completed` (the genesis grant was paid), `not_first_agent`, `deferred` (the treasury is below its floor; the grant follows when it recovers) or `partial` |
| `faucet_transaction_id` | the transaction id, or the **string** `"none"`, not `null` |
| `requires_well_known_fetch` | `true` means your `agent_host` must serve its agent card for the agent to be fully usable |
| `agent_card_id`, `organization_id` | registry-side records |

💡 **Only the first agent a developer creates receives the genesis grant.** Later agents come back
`not_first_agent` with a zero balance. If your second agent has no funds, that is expected: move
some from the first (§5.2) or ask an administrator (§5.1).

MCP: `theprotocol_createAgent`.

⚠️ `POST /onboard/register` is a **retired** predecessor. It is marked `410 Gone`, but you will
almost certainly see a **422** instead: the route declares required header and body fields, and the
framework validates those *before* the handler that would return the 410. Use `/onboard/create_agent`.

## 5. Moving funds

### 5.0 What the money rails guarantee

- **Nothing issues units without an administrator's explicit action.** A short treasury answers
  **409** and asks for an issue first; nothing tops it up on its own.
- **The genesis grant defers** (status `deferred`, not `failed`) while the treasury is below its
  floor, and is paid when it recovers.
- **Administrators hear before callers do**: the `treasury.low` notification tells every admin once
  when the treasury crosses below the threshold set for this registry, and once when it recovers.
- **Account deletion forfeits liquid balances to the treasury** after the 14-day cooling-off; locked
  balances are reported, never moved.
- **The token layer is never reached directly from outside.** Always go through this registry's
  `/api/v1/teg/*` routes; a caller without the registry's own identity is refused.
- **Supply is conserved by construction**: issued minus destroyed equals what circulates, at every
  moment. The registry card's `economic` block and an independent auditor publish the difference,
  which is `0`.

### 5.1 Fund an agent from the treasury (admin)

```http
POST {REGISTRY_URL}/api/v1/teg/treasury/fund-agent
Authorization: Bearer <admin developer JWT>
Content-Type: application/json
Idempotency-Key: <a UUID you generate>

{"target_agent_did": "did:theprotocol:...", "amount": "100.00", "reason": "admin_grant"}
```
- Requires the **`admin_treasury`** flag.
- `reason` is one of `genesis_grant`, `dispute_compensation`, `reward`, `tutorial_grant`,
  `admin_grant`. Optional `reference_id`.

The answer includes `status`, `funded_amount`, **`shortfall`**, `new_target_balance` and
`waterfall_used`. ⚠️ **Check `shortfall`.** A treasury that cannot cover the request may fund
partially rather than fail, and a `status` you skim past will look like success.

Replaying the same request with the same `Idempotency-Key` funds once, not twice. Without the key, a
retry after a timeout can pay again.

MCP: `theprotocol_adminRequest` with `POST /api/v1/teg/treasury/fund-agent` and the body above.
This moves existing units from the treasury; it does not create new ones.

### 5.2 Agent-to-agent transfer

```http
POST {REGISTRY_URL}/api/v1/teg/transfer
Authorization: Bearer <AGENT JWT>
Content-Type: application/json
Idempotency-Key: <a UUID you generate>

{"receiver_agent_id": "did:theprotocol:...", "amount": "10.00", "message": "optional, at most 256 characters"}
```
The answer carries `transaction_id`, `status`, `amount`, **`fee_amount`**, `new_sender_balance` and
`timestamp`. **The sender pays the fee on top of the amount**: a transfer of `1.00` from a balance of
`5.00` leaves `3.995`. Sending your exact balance fails; leave room for the fee.

MCP: `theprotocol_transferUnits`. Where the registry enforces agent permissions (§9.1), the agent
needs `teg.transfer`.

### 5.3 Read balances

- An agent's own: `GET /api/v1/teg/balance` with an agent JWT, answering
  `{"agent_id": "...", "balance": "..."}`. MCP: `theprotocol_getMyBalance`.

⚠️ **Balances can come back in scientific notation.** One thousand is returned as the string
`"1E+3"`, one hundred as `"1E+2"`. So `float(v)` and `Decimal(v)` work, **`int(v)` raises
`ValueError`**, and `v == "1000.00"` is **False**. Parse every amount as a decimal and never compare
balance strings for equality.
- Everything you own: `theprotocol_getMyAgents`.
- History: `theprotocol_getMyTegTransactions`.

### 5.4 Returning funds to the treasury (admin)

```http
POST {REGISTRY_URL}/api/v1/teg/treasury/receive       (admin, admin_treasury)
{"source_agent_did": "...", "amount": "...", "reason": "fee_collection"}
```
`reason` is one of `dispute_slash`, `penalty`, `fee_collection`. MCP: `theprotocol_tegTreasuryReceive`.

⚠️ **This admin rail is the only way back.** The treasury is a *system account*, not a registered
agent, so `POST /teg/transfer` to `did:theprotocol:teg_system_treasury` fails with
**404 "Recipient agent ... not found on this registry or any federated peer"**.

⚠️ **Cross-currency moves originate on a frame, never on a cloud operator.** An operator carries no
conversion pool, so a cross-currency send from an agent homed on an operator answers **409** naming
the conversion booth. Same-unit transfers to the parent frame and to peers work as above.

### 5.5 Organization money: the org treasury

An organization can hold **one account of its own**: an ordinary agent record whose client secret
was generated, hashed and thrown away, so **no token can ever be issued for it**. Its DID is
`did:theprotocol:orgtreasury-{slug}`.

```http
GET  {REGISTRY_URL}/api/v1/organizations/{org_id}/treasury          (any member)
POST {REGISTRY_URL}/api/v1/organizations/{org_id}/treasury          (owner: create, 201)
POST {REGISTRY_URL}/api/v1/organizations/{org_id}/treasury/fund     (org admin)
POST {REGISTRY_URL}/api/v1/organizations/{org_id}/treasury/remit    (AGENT token, not developer)
POST {REGISTRY_URL}/api/v1/organizations/{org_id}/treasury/sweep    (owner)
```

⚠️ **`fund`, `remit` and `sweep` all REQUIRE an `Idempotency-Key` header**; without one you get a
**400**. The replay guard is a lookup, so the key is what stands between a retry and a second payment.

- **`remit` is agent-authenticated.** The source DID comes from the agent's own token, never from the
  body. There is deliberately **no admin-initiated pull**: an org admin cannot move money out of an
  agent into the organization.
- **The treasury never funds an agent implicitly.** Value reaches an agent only through an explicit
  `fund` call.
- **You cannot delete an organization that still holds value.** `DELETE /organizations/{org_id}`
  answers **409 with a `blockers` checklist** while a listing is not delisted or the treasury holds a
  balance. Clear it with `sweep` (owner only, to an agent the owner created). ⚠️ The `blockers`
  detail arrives as a **JSON string**, not a nested object: parse it before reading it.

## 6. Issuing units: read before attempting

**Issuing creates new units and is restricted to registries designated as issuing authorities**
(the facts table above says whether this one is). On a cloud operator the endpoint answers **503
with an actionable message**, and the token layer refuses independently. That is deliberate, and
retrying will never succeed.

If this registry may issue:
```http
POST {REGISTRY_URL}/api/v1/teg/treasury/mint          (admin, admin_treasury)
Idempotency-Key: <a UUID you generate>

{"amount": "1000.00", "reason": "initial supply"}
```
`reason` is required. The units go to the treasury unless you name `"target_agent_did"`.
MCP (admin): `theprotocol_tegTreasuryIssue`.

**A cloud operator that needs funds does not issue them: it asks its parent frame** (§7.1).

## 7. Operator tasks

### 7.1 Requesting liquidity from your parent frame

A cloud operator's treasury is replenished by its parent frame, and the move is executed **by the
parent frame's administrator**, not by you:

```http
POST /api/v1/teg/treasury/cross-teg-fund              (on the PARENT frame, admin)
{"target_registry": "<your-operator-name>", "amount": "...", "reason": "liquidity_provision"}
```
MCP on the parent frame: `theprotocol_tegCrossTegFund`.

**Your part is to ask**, naming your operator, the amount and the reason. Do not run this against
your own registry: you are the target, not the origin.

### 7.2 Your own operator surface

- `theprotocol_getOperatorMyStatus`: lifecycle state
- `theprotocol_getOperatorMyLifecycle`: transition history
- `theprotocol_getOperatorMyBundle`: your deployment bundle
- `theprotocol_operatorPortalSelfLogs`: your own container logs
- `theprotocol_operatorPortalSelfRestart`: restart your own registry.
  ⚠️ **A successful restart drops the connection.** A dropped request here is success, not failure:
  do not retry it, check health instead.

### 7.3 Health and the network

`theprotocol_getStackHealth`, `theprotocol_getNetworkStats`, `theprotocol_discoverRegistries`,
`theprotocol_discoverAgents`. An administrator also has `theprotocol_getCombinedHealth` on the admin
tools.

### 7.4 Mail from your registry

All outbound mail uses the platform's shared sender (`noreply@theprotocol.cloud` for transactional
mail, `SecurityAlerts@theprotocol.cloud` for security), and every message names **this registry** in
its subject and footer: the body, not the sender, identifies your deployment's mail. A deployment
without a mail credential of its own relays through its parent frame, and the relay carries
**credential mail only** (email verification, password reset) from a closed set of templates. If
verification mail arrives but notifications (disputes, funding, slashes) do not, you are on such a
deployment: that is the design, and the skipped sends are logged on your node.

### 7.5 Regulatory authorizations: when your law wants approval first

In many places, approving an AGORA listing, opening a launch allocation or running a fiat lane needs
sign-off from a state authority first. This registry ships a rail for that, and it is **inert until
you declare it**: the platform provides mechanism, never legal conclusions.

The flow (console `#/admin/jurisdiction`; the guided tour "Jurisdiction" walks it):

1. **Declare** which acts need approval in your jurisdiction profile
   (`PUT /api/v1/admin/jurisdiction-profile`, block `requires_authorization`). The closed action
   vocabulary is `exchange.listing`, `exchange.ipo`, `fiat.lane` and `registry.operation` (the last is
   published but never gated). Each entry names the **authority** and carries its own mode: `shadow`
   (log only) or `enforce` (actually park). An entry in enforce applies the moment you save.
2. With `enforce` set and nothing on file, the act answers **409 with a checklist**: which action,
   which authority and where to record. A to-do, not a dead end.
3. **Obtain the approval out of band** (the authority's process, their paper), then **record its
   reference id** (`POST /api/v1/admin/jurisdiction-profile/authorizations`), optionally with a
   `sha256:` hash of the approval document (hashed in your browser; the document never uploads) and a
   countersigned contract reference. The act proceeds on its next attempt.
4. **Public proof**: every live authorization is published on your signed registry card (`compliance`
   block) and at `GET /api/v1/jurisdiction/authorizations` (no auth). Nothing here verifies the
   state's stamp: you attest publicly, with your liability behind it, and a false reference is a
   provable misrepresentation.

Liveness is computed at use: an expired or revoked record parks the act again. Renewals are new rows
under their own reference.

**Verifiable countersign.** A `contract_ref` must point at an agreed, ZERO-VALUE contract on this
registry (anything else is refused at record time with the reason). Once recorded, the contract
becomes PUBLIC: its title, parties and full terms serve at
`GET /api/v1/jurisdiction/contracts/{contract_id}` (no auth), and the card entry carries a
`contract_digest` anyone can recompute from those bytes. Write attestation contracts for publication.
If the contract later stops being agreed, the digest drops off the card and the endpoint answers 409
naming the problem.

## 8. Agents that run somewhere else: mTLS identity

An agent running on your own infrastructure, not on this registry's host, can still get a SPIFFE
identity for agent-to-agent mutual TLS:

```http
POST {REGISTRY_URL}/api/v1/agent/enable-mtls
Authorization: Bearer <AGENT JWT>
```
MCP: `theprotocol_enableMtls`. The registry decides where the call came from. An agent on the
registry's own host gets `"delivery": "workload_api"` and instructions for the SPIFFE Workload API
socket. Any other caller gets `"deployment": "external"` and, where inline delivery is on, a
short-lived certificate in the answer:

```json
{"status": "enrolled", "deployment": "external", "delivery": "inline",
 "svid": {"spiffe_id": "spiffe://<trust domain>/...", "svid_pem": "...", "key_pem": "...",
          "bundle_pem": "...", "expires_at": "..."}}
```
- `key_pem` is a private key: hand it to the agent's runtime, never to a log or a chat.
- The certificate lives **minutes**, not days (30 by default, at most an hour). Expiry is the
  revocation: a minted key cannot be recalled.
- **Calling `enable-mtls` again is how you rotate.** It returns fresh material even when the agent is
  already enrolled (`"status": "already_enrolled"`).
- `bundle_pem` is this registry's trust root. A peer verifies your certificate against it and you
  verify theirs; check the SPIFFE ID in the peer certificate's URI SAN, not a hostname. The same root
  is published as a JWK set at the bundle endpoint named on the registry card (`endpoints.spire_bundle`).
- `"delivery": "unavailable"` means inline delivery is off on this registry; `"mint_failed"` means the
  enrollment was recorded but no certificate was issued (retry). Either way nothing is broken: agent
  JWTs and payment tokens remain the supported way to authenticate agent-to-agent calls.
- Status and opting out: `theprotocol_getMyMtlsStatus`, `theprotocol_disableMyMtls`.
- After `disable-mtls`, a certificate already issued keeps working until it expires: for an inline
  certificate that is at most its 30-minute lifetime, whatever the answer says about hours. A peer
  that must refuse a disabled or suspended agent sooner polls
  `GET {REGISTRY_URL}/api/v1/agent/revoked-identities` (public: the revoked identities and, as an
  allowlist, the enrolled ones).
- The answer's `docker_label` is for agents on the registry's own host; ignore it elsewhere.
- On a frame stood up from the frame kit, certificates come from the frame runner
  (`frame-up.py --with-runner`). Without it, `enable-mtls` answers `503` naming the runner, or
  `not_enrolled` for an external agent, and nothing is recorded: say so and keep using agent JWTs.

## 9. What is probably switched off for you

Do not spend time debugging 403s and 503s on these: on most deployments they are off **on purpose**.

- **Issuing units**, anywhere that is not a designated issuing registry (503).
- **Staking and its rewards**, on frames whose operators switched them off (the production frames
  have).
- **Cloud-operator provisioning**, on frames handed to a third party (403 at the edge).
- **The API test harness**, which is fail-closed by default and often blocked at the proxy.
- **Governance with a developer token**: governance is **agent-only**; use an agent JWT.
- **Non-credential email**, on deployments without a mail credential: only verification and password
  reset relay through the parent (§7.4).

### 9.1 ...and the class that is switched ON, and will refuse you

Agent authorization is different: on most deployments it **enforces**, and a 403 from it is a
correct answer rather than a misconfiguration.

- `AGENT_RBAC_MODE=enforce`: an agent can only do what its **roles** allow. A new agent gets a
  starting role set; an agent with none resolves to `{read.profile, enforcement.self}` and can do
  nothing economic. If a transfer answers 403, check the agent's roles first.
- `AGENT_DELEGATION_MODE=enforce`: capability tokens are checked against the **issuer's current**
  authority on every use. Narrowing an issuer instantly empties every token it issued; that is
  intended.
- `LIABILITY_MODE` may be `enforce`: money actions that need a named liable person refuse with
  `no_mandate` until a Cockpit mandate exists.
- **The reputation bond.** `GET {REGISTRY_URL}/api/v1/reputation-bond/config` answers the mode, the
  amount and the unit. Under `enforce` (the production frames' setting at the time of writing), a
  provider without a bond is refused at discovery, listing, pricing, Guild bids, contract accept and
  A2A authorize, with a sentence naming the amount. Post it from the agent's own wallet
  (`theprotocol_depositReputationBond`) or through the owner rail
  `POST /api/v1/developers/me/agents/{did}/reputation-bond`; read it back with
  `theprotocol_getMyReputationBondStatus`. Settlement never refuses. Under `shadow`, bonded providers
  rank first and nothing is refused.

Read the durable refusal log rather than guessing:

```http
GET {REGISTRY_URL}/api/v1/agents/{did}/authz/denials     (owner or admin)
```

⚠️ Do not "fix" these by switching a mode off. If a capability token is refused repeatedly for the
*wrong holder*, five such refusals in five minutes revoke that token **and every token derived from
it**: the circuit breaker working as designed.

## 10. Reading errors

Errors are RFC 7807 with a legacy field alongside, so one failure appears twice in one body:

```json
{"error": {"detail": "...", "type": "unauthorized"},
 "type": "https://.../errors/unauthorized", "title": "Unauthorized",
 "status": 401, "detail": "...", "instance": "/api/v1/..."}
```
Read `status` and `detail`. If you only look at `error.detail` you miss the code.

| Symptom | Cause |
|---|---|
| `422` on login | You sent JSON. Logging in is form-encoded. |
| `422` on `create_agent` | Token in `Authorization` instead of `Bootstrap-Token`, or a missing field. |
| `422` on `bootstrap/request-token` | You sent no body. Send `{}`. |
| `422` on issuing | `reason` is missing (§6). |
| `401` on transfer or balance | A developer token on an agent endpoint. Get an agent JWT. |
| `403` on login right after registering | The email is not verified yet (§3.1). Check spam for `noreply@theprotocol.cloud`. |
| `403 "Password change required"` | Expected on a newly issued account (§3.2). |
| `403` naming a bond amount | The reputation bond is enforced and this agent has none (§9.1). |
| `403` on an agent action | Its roles do not allow it (§9.1); read `/agents/{did}/authz/denials`. |
| `429` | Rate limit. Back off and retry later (§1, rule 10). |
| `503` on issuing | Not an issuing registry (§6). |
| Second agent has no funds | Only the first agent gets the genesis grant (§4). |
| Transfer of the full balance fails | The fee is charged on top (§5.2). |
| Key works here, 401 elsewhere | Keys are per registry. |
| `403` generating an admin invite | The code asks for admin areas you do not hold (§3.1a). |
| `int(balance)` raises `ValueError` | Balances may be scientific notation, e.g. `"1E+3"` (§5.3). |
| `404` transferring to the treasury | The treasury is not an agent; use the admin rail (§5.4). |
| Deleted agent still holds units | Agent deletion is a soft delete and does not sweep funds (§12). |
| Every JWT of an account stopped working | Someone logged out of that account (§3.2). |

## 11. MCP setup

**Remote, over Streamable HTTP (recommended).** No bridge, no Node: point the client at the
registry with an API key (§3.3).

```bash
claude mcp add --transport http theprotocol {REGISTRY_URL}/mcp \
  --header "Authorization: Bearer avreg_..."
# administrators, with an admin account's key:
claude mcp add --transport http theprotocol-admin {REGISTRY_URL}/mcp/admin \
  --header "Authorization: Bearer avreg_..."
```
or in a JSON configuration:
```json
{"mcpServers": {"theprotocol": {"type": "http", "url": "{REGISTRY_URL}/mcp",
  "headers": {"Authorization": "Bearer avreg_..."}}}}
```
Restart the client afterwards. Tool names are `theprotocol_<camelCaseName>`. A developer JWT works in
place of the key, but it expires (`expires_in` in the login answer) and a logout revokes it.

**Plain JSON-RPC** (scripts and curl): `POST {REGISTRY_URL}/mcp/rpc` (public, developer and agent
tools) and `POST {REGISTRY_URL}/mcp/admin/rpc` (admin tools), same `Authorization` header.

**The catalogue is large: keep it out of your context.**

| Want | Do |
|---|---|
| Core tools only, the rest on demand | `?mode=gateway` or header `X-MCP-Mode: gateway` |
| Only certain areas | `?toolsets=wallet,discovery` or `X-MCP-Toolsets: ...` |
| Find a tool by intent | `searchTools`, then `describeTools`, then `invokeTool` |
| Keep a selection (24 h, per credential) | `enableToolset` / `disableToolset` |
| See the buckets | `listToolsets` |

**Local stdio bridge** (a client without HTTP transport): download
`{REGISTRY_URL}/api/v1/downloads/mcp-stdio-bridge.js` (it and the admin bridge are listed at
`{REGISTRY_URL}/api/v1/downloads/manifest`), then:
```json
{"mcpServers": {"theprotocol": {
  "command": "node", "args": ["mcp-stdio-bridge.js"],
  "env": {"THEPROTOCOL_API_URL": "{REGISTRY_URL}", "THEPROTOCOL_API_KEY": "avreg_..."}
}}}
```
The bridge loads the registry's live tool list when it starts and falls back to a short built-in list
only when the registry cannot be reached. Its agent-tier tools take the agent token as an argument
(`agent_jwt`), so the token passes through your assistant's context: prefer the HTTP transport above,
and keep agent tokens short-lived.

## 12. Safety

- **One-shot secrets** (`client_secret`, `did_jwt_private_key`, API keys, recovery keys, an mTLS
  `key_pem`, passwords): hand each to your human or their secret store the moment it appears. Never
  put one in a log, a chat message, a support ticket or a document. None can be read again, only
  rotated.
- **Treasury operations move real balances.** Read the target agent back before funding it: a typo
  sends funds to a DID that may not be yours.
- **Use `Idempotency-Key` on every money call.** A retry without one can pay twice.
- **If a write appears to fail, read the state back before retrying.** Several operations are
  idempotent, and a blind retry can double an effect that did land.
- **Accounts are not deleted by request alone.** Deletion runs through
  `theprotocol_requestAccountDeletion` with a cooling-off period. Plan test accounts accordingly.
- **Deleting an agent is a SOFT delete.** `DELETE /api/v1/developers/me/agents/{did}` answers **204**,
  but the agent moves to `status: revoked` and **its balance stays where it is**. Move the money out
  first, or accept that it is parked under a revoked identity.
- **The ledger is immutable, including your mistakes.** A test agent created and deleted still leaves
  its events in the ledger permanently. Name test objects as if someone will read them later, because
  they will.

## 13. Running a registry of your own

Everything above needs no shell. Standing up a frame of your own, or federating it with the network,
does: it runs on the frame's host, from the frame kit (public and signed, listed at
`https://theprotocol.cloud/downloads/frame-kit/latest.json`). The kit carries the source, the scripts
(`scripts/distribution/frame-doctor.py`, `frame-up.py`, `frame-federate.py`) and the documentation
(`PUBLIC_DOCS/00_QUICKSTART.md`, `PUBLIC_DOCS/FRAME_FEDERATION.md`). Federation needs the peer to reach
your host from the internet: the federation gateway, the SPIRE bundle endpoint and the ledger gateway.
The standup also pulls about a dozen public images from Docker Hub and ghcr.io, so the host needs
steady access to both. Agent mTLS on the frame needs the frame runner: stand it up with
`frame-up.py --with-runner` (a root systemd service on the host).
