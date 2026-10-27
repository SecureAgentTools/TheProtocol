# Agent Access Control

*IronKey: least privilege for autonomous agents. An agent holds its own credentials and its own units; IronKey lets the agent's owner decide what it may do and how much it may spend, and it never moves value itself.*

## Why It Matters

An agent authenticates with its own token and pays its own way. Without access control that token reaches every action the API exposes: transfer, trade, vote, file disputes, authorize payments. For a script you watch, that is fine. For an agent that runs unattended and holds a balance, it is too much: a misled or buggy agent with an unrestricted credential can drain itself or act for you in ways you never intended.

**IronKey** is a layered authorization system that limits an agent to the actions and the spending it needs, and lets an agent that creates helpers hand each one a strictly weaker copy of its own authority. It is **set by the owner** (you configure the agents you own), **deny-only** (it can refuse an action, never cause one) and **switched per registry** (each registry decides whether it observes or enforces; see *The Switches* at the end). Roles and spending limits come first; delegation and capability permits build on the same decision point.

```mermaid
flowchart LR
    Req(["Agent request<br/>(agent token)"]):::req
    L1{"L1: holds the<br/>permission for<br/>this action?"}:::gate
    L2{"L2: within the<br/>spend policy?"}:::gate
    Do(["Action proceeds<br/>(then escrow and settlement)"]):::ok
    Deny(["403: denied<br/>before any value moves"]):::deny

    Req --> L1
    L1 -->|no| Deny
    L1 -->|yes| L2
    L2 -->|no| Deny
    L2 -->|yes| Do

    classDef req fill:#1a2234,stroke:#3B82F6,stroke-width:2px,color:#e4ecf4
    classDef gate fill:#2a1f0e,stroke:#F59E0B,stroke-width:2px,color:#e4ecf4
    classDef ok fill:#0d2a23,stroke:#10B981,stroke-width:2px,color:#d1fae5
    classDef deny fill:#2a0e0e,stroke:#DC2626,stroke-width:2px,color:#fecaca
```

Both checks happen **before** the request reaches the money path. IronKey can stop an action; it can never cause one. That keeps it out of the [supply invariant](/docs/07): allowed or denied, no unit moves because of the gate, so the delta stays 0.

## Layer 1: Roles & Permissions

Layer 1 is role-based access control for agents. An agent holds one or more **roles**; each role grants a set of **permissions**; a permission unlocks a family of actions that change something. Reads are not gated (discovery, balances and history stay open whatever the roles), except a few that belong to an action: the FX quote (`POST /api/v1/teg/fx/quote`, a preview that moves nothing) asks for `fx.quote`, the reads of your passport orders and holdings on another frame's AGORA market ask for `exchange.trade`, and the list of the cross-registry delegations an agent issued asks for `authz.delegate`.

Roles add up: give an agent `trader` and `governor` and it may trade and vote. The permissions an agent holds are a small base that every agent has (`read.profile`, `enforcement.self`), plus every role's permissions, plus permissions granted to it directly, plus permissions delegated to it (Layer 3).

A newly created agent receives the registry's default roles (`AGENT_RBAC_DEFAULT_ROLES`, by default `trader` and `client`), so it can transfer, pay and engage contracts from the start.

| Role | What it is for | Permissions (besides the base) |
|---|---|---|
| `observer` | Read-only presence | `fx.quote` |
| `trader` | Transfers and the AGORA market | `fx.quote`, `teg.transfer`, `teg.transfer_xreg`, `exchange.trade`, `exchange.ipo` |
| `staker` | Locking units, where the registry allows it | `staking.manage` |
| `service-provider` | Selling services and being paid | `a2a.collect`, `contracts.engage`, `reputation.signal`, `disputes.file`, `identity.mtls` |
| `client` | Hiring other agents and paying them | `a2a.pay`, `teg.transfer`, `contracts.engage`, `disputes.file`, `identity.mtls` |
| `governor` | Governance | `gov.propose`, `gov.vote`, `exchange.vote` |
| `canary` | Synthetic monitoring | `teg.transfer`, `teg.transfer_xreg` |
| `gateway` | The AGORA market's deposit gateway | `teg.transfer`, `teg.transfer_xreg` |
| `legacy-full` | Every permission (see below) | all |

Permissions are named after the action they unlock: `teg.transfer`, `teg.transfer_xreg` (to another registry), `staking.manage`, `exchange.trade`, `exchange.ipo` (buying a launch allocation), `exchange.vote`, `a2a.pay`, `a2a.collect`, `gov.propose`, `gov.vote`, `contracts.engage`, `disputes.file`, `reputation.signal`, `fx.quote`, `identity.mtls`, and a few that no ordinary role carries: `authz.delegate` (Layer 4), `teg.system_transfer`, `phone.use` ([chapter 28](/docs/28)), `contract.template.publish`, and the organization and forge permissions (`guild.bid_for_org`, `guild.post_for_org`, `forge.*`, `cicd.*`, `bundle.write`). A few names no route asks for in this release: `a2a.collect` (being paid needs no permission, because settling an A2A payment is the payer's act, under `a2a.pay`), `cicd.deploy` and `forge.royalty_admin`. The catalog is served live; do not hardcode it:

```http
GET /api/v1/agents/authz/catalog
Authorization: Bearer <developer token>
```

It returns the registry's current mode, the assignable roles, every permission, the base permissions, the permissions the console can grant by switch, the role to permission map, and for each kind of principal the permissions a delegation grant from it may carry (`delegatable_permissions`, Layer 3).

## Layer 2: Spend Policy

Roles say *what* an agent may do. A **spend policy** says *how much*. It is an optional per-agent overlay:

- **Per-transaction cap** (`max_per_tx`): the most a single money-moving call may move. Checked before escrow.
- **Daily cap** (`max_per_day`): the units the agent has sent in settled transfers over the last 24 hours, plus the new amount, may not exceed it. The registry sums the agent's transfers per completed hour (from the ledger's transfer events, `velocity_metrics`), so recent spending counts only once its hour has been summed, and the cap can be passed by what the agent sends in that time. Locking units is not a transfer and does not count.
- **Allowed currencies** (`allowed_currencies`) and a **counterparty mode** (`counterparty_mode`: `any`, `same_registry`, or `allowlist` with `counterparty_allow`), so an agent can be limited to paying known partners in one unit.
- **Approval threshold** (`require_approval_above`): above it a spend waits for the owner. Under enforcement the refused call opens an approval request (`GET /api/v1/agents/authz/spend-approvals`) that waits 30 minutes for the owner; the owner approves or denies it (`.../{approval_id}/approve`, `.../deny`), and an approval lets the agent's retry through once, within 15 minutes.
- **Rate** (`rate_per_hour`, spend attempts per hour) and **places** (`geo_allow`, the registries where its spending may run).

```mermaid
flowchart TB
    subgraph Policy["Agent spend policy"]
        PT["per-transaction cap"]:::c
        PD["daily cap<br/>(sent in the last 24 h)"]:::c
        CC["currencies, counterparties,<br/>approval threshold, rate, places"]:::c
    end
    T(["money-moving call<br/>transfer · cross-registry · order · payment"]):::req
    T --> PT --> PD --> CC --> Pass(["escrow, then settlement"]):::ok
    PT -.over.-> X(["403"]):::deny
    PD -.over.-> X
    CC -.refused.-> X

    classDef c fill:#141e2e,stroke:#3B82F6,stroke-width:2px,color:#e4ecf4
    classDef req fill:#1a2234,stroke:#8B5CF6,stroke-width:2px,color:#e4ecf4
    classDef ok fill:#0d2a23,stroke:#10B981,stroke-width:2px,color:#d1fae5
    classDef deny fill:#2a0e0e,stroke:#DC2626,stroke-width:2px,color:#fecaca
```

The policy is checked on every path that moves an agent's units: local, cross-registry and system transfers, A2A payment authorization, contract funding, AGORA orders and the wrapped-unit bridge. If the agent belongs to an organization, the organization's spend ceiling is checked at the same point (see *Authority an organization hands out*).

## Modes: off, shadow, enforce

Enforcement is a registry setting (`AGENT_RBAC_MODE`), not a code change:

```mermaid
stateDiagram-v2
    [*] --> off
    off --> shadow: the operator turns on observation
    shadow --> enforce: the would-deny stream looks right
    enforce --> shadow: back off at once if needed
    note right of off
      no gate, every call allowed
    end note
    note right of shadow
      every call evaluated,
      a would-deny recorded,
      the call allowed
    end note
    note right of enforce
      denials are real (403)
    end note
```

- **`off`**: the gate is inert. This is the code's default.
- **`shadow`**: every gated call is evaluated and a *would-deny* is recorded, but the call is **allowed**. An operator sees exactly what enforcement would block before it blocks anything.
- **`enforce`**: denials are real (`403`).

Changing the mode takes a restart of the registry with the new setting, and the change can be undone the same way.

## Nobody gets locked out: `legacy-full`

Turning on access control must not break agents that predate it. When a registry first introduced IronKey, **every agent it already had was given `legacy-full`**, the role that holds every permission, so those agents kept working in `shadow` and in `enforce`. Agents created since then receive the default roles instead. Least privilege is then a step the owner takes: replace `legacy-full` with the roles the agent needs, check the shadow record, then enforce. Only a platform admin can grant `legacy-full`; an owner can assign every other role, and can take `legacy-full` away.

## Configuring it

Owners (and platform admins) manage an agent's access through the authz API (developer token):

```http
# Roles, effective permissions, spend policy and delegated grants
GET /api/v1/agents/{did}/authz

# Replace the role set and write the spend policy
PUT /api/v1/agents/{did}/authz
{
  "roles": ["trader", "governor"],
  "spend_policy": {
    "max_per_tx": 250,
    "max_per_day": 1000,
    "allowed_currencies": ["ECU"],
    "counterparty_mode": "same_registry"
  }
}

# Grant ONE role and leave every other grant as it is (optional expires_at)
POST /api/v1/agents/{did}/authz/roles   { "role": "governor" }

# What enforcement WOULD have blocked (shadow) or DID block
GET /api/v1/agents/{did}/authz/denials
```

`roles` in a `PUT` replaces the whole role set (and `roles_expires_at` gives that set an expiry); `spend_policy` replaces the policy; `delegate_enabled` grants or removes `authz.delegate`. Platform admins also get a fleet report (`GET /api/v1/admin/agents/authz/report`: how many agents still hold `legacy-full`, how many are capped, the role census) and an emergency **clamp** (`POST /api/v1/admin/agents/{did}/authz/clamp`), which sets the agent's roles (by default `observer` only) and both caps to zero in one call.

In the console, the same controls are the **Agent Access** panel wherever you manage agents: role chips, the spend policy, and a mode-aware note that says in `shadow` what enforcement would change. You can edit the access only of agents you created; admins can edit any.

## Layer 3: Delegation (acting on behalf of a principal)

Roles and spend policy answer *what* and *how much*. Delegation answers a third question that autonomy raises: **on whose authority is this agent acting?** An agent token can carry an optional `act` claim (the on-behalf-of shape of RFC 8693) naming the principal it acts for: a developer, an organization or another agent. The claim is **attribution first**: every decision and audit line can then say whose authority was used.

On top of attribution sits a **delegation grant**: a principal delegates a set of permissions *to* an agent. A grant adds permissions **only when the presented token's `act` names that same principal**; authority is never inherited by accident. Grants are rows in *this* registry's database (a federated peer can never grant authority here), they can expire, and they can be revoked at once: the effective set is recomputed on every request, so a revocation takes hold on the next call. A developer's grant also stops conveying anything the moment that developer is suspended or deleted.

A developer delegates their own authority, and only to an agent they created: a developer's grant (`dev:<id>`) may name only what the developer can give that agent directly (any role but `legacy-full`, and `authz.delegate`). An owner or admin of an organization delegates the organization's: an organization's grant reaches only agents that belong to that organization, checked on every request, and never carries `authz.delegate`, `contract.template.publish`, `phone.use`, `teg.system_transfer`, `cicd.deploy` or `forge.royalty_admin` (the list no organization slice contains, [chapter 20](/docs/20)). A grant outside these limits is refused with `403`, and the registry applies the same limits on every request, so no grant conveys more than they allow. Grants from an agent or a service principal are admin-only.

```http
# Delegate a permission subset TO an agent (developer token)
POST /api/v1/agents/{did}/delegations
{ "principal_type": "dev", "principal_ref": "dev:42", "permissions": ["gov.propose", "gov.vote"], "ttl_hours": 24 }

GET    /api/v1/agents/{did}/delegations     # grants an agent holds (its owner or an admin)
DELETE /api/v1/delegations/{grant_id}       # revoke a grant (the developer who made it, or an admin)
```

`principal_ref` names the principal (`dev:<your developer id>`, `org:<slug>`); the bare id is accepted too.

### The exercise leg: an on-behalf-of token

A grant does nothing until the agent presents a token that *names the principal it draws authority from*. The agent issues that token itself (agent token):

```http
POST /api/v1/agents/act-token   { "act_as": "dev:42" }
```

The registry returns a new agent token with an `act.sub` claim, but only if a **live grant** from that principal to this agent exists at that moment (`403` otherwise), and it lists the `effective_permissions` the token carries. The claim alone confers nothing: authority is recomputed from the grant on every call the token is presented to, so revoking the grant empties a token already in use on its next call.

### Delegation across registries

Everything above happens inside one registry. Delegation across a federation needs one more step: an agent on registry **A** lends a bounded slice of its authority to an agent homed on registry **B**, without B having to trust A to *create* authority on B.

The rule stays: **an agent's authority is resolved at its own home.** A never grants anything on B. A's home **signs** a delegation credential (an Ed25519-signed bundle of kind `ironkey.delegation.v1` naming the issuer, the delegate, the permissions, the bounds and an expiry) and sends it to B's home over the federation's mutual-TLS channel. B's home **verifies the signature against A's home's published key**, confirms the delegate is its own agent, and only then writes a *local* grant from `agent:<A's DID>`. From there it is an ordinary local grant: B's agent uses it with an act-token as above.

```http
POST /api/v1/agents/delegate-cross-registry   (agent token; needs authz.delegate)
{ "delegate_did": "did:theprotocol:asia.theprotocol.cloud:...", "delegate_registry_url": "https://asia.theprotocol.cloud",
  "permissions": ["teg.transfer"], "ttl_hours": 24, "max_per_tx": 5 }

GET    /api/v1/agents/delegate-cross-registry                    # the credentials this agent issued
DELETE /api/v1/agents/delegate-cross-registry/{credential_id}    # revoke
```

The delegate must be on another registry (a local one answers `400`: use a local grant), the permissions must be a subset of what the issuer holds now, and a credential lasts at most 720 hours (24 by default).

Three safety properties travel with it:

- **The signed claim decides.** The grant is written from the *signed* credential, not from the envelope around it. A peer that changes the permissions, the issuer or the delegate around a validly signed credential is refused (`422`), and the attempt is recorded as a forgery; the expiry is always read from the signed claim.
- **The issuer's home is asked at use.** Before a cross-registry grant conveys anything, the delegate's home asks the issuer's home whether the credential still stands and what the issuer holds now (`XREG_ISSUER_AUTHORITY_MODE`, `enforce` by default; answers are cached for up to a minute). A revoked or expired credential, an issuer that is suspended or no longer holds the permission, or an issuer's home that cannot be reached all convey nothing.
- **Revocation travels.** The revocation is recorded at the issuer's home first, so the check at use above finds it whatever becomes of the message that follows. That message goes over the federation channel to the registry the delegation was issued to, and B revokes the credential and the grant together; a second delivery changes nothing there. Only a delegation the agent itself issued can be revoked (any other credential id answers `404`), and every recorded revoke answers `200`: `ok` says whether this send reached B's home, `delivery` how the message stands.

```mermaid
sequenceDiagram
    participant A as Agent A<br/>(registry A)
    participant HA as A's home
    participant HB as B's home
    participant B as Agent B<br/>(registry B)
    A->>HA: delegate teg.transfer to B (max_per_tx 5)
    HA->>HA: sign the credential (Ed25519)
    HA->>HB: send it over federation mutual TLS
    HB->>HB: verify the signature against A's home key
    HB->>HB: write a LOCAL grant from agent:A
    B->>HB: act-token (act.sub = agent:A)
    B->>HB: gated call
    HB->>HA: does the credential stand, what does A hold now?
    HB-->>B: allowed within the bounds and A's current authority
    Note over HA,HB: a revoke, a suspension or a lost permission at A's home: the next call is refused
```

#### When B's home does not take the revoke

A revoke whose message does not reach B's home is sent again by A's home, with the same request, until it does: after 1, 5 and 15 minutes, then 1, 3, 6 and 12 hours, then once a day. It stops when B's home takes it, when B's home refuses the request as it stands (`400` or `422`), after 40 sends (`XREG_REVOKE_RETRY_MAX_ATTEMPTS`, about a month, the longest a delegation lives), or once the delegation has expired, since its grant at B's home expires with it. Meanwhile the revoke already stands at B's next check with A's home. The issuer's list (`GET /api/v1/agents/delegate-cross-registry`) shows a recorded revoke as `revoked` with its `revoke_delivery` (`delivered`, `retrying`, `given_up`, `expired`, or `not_queued` for a revoke recorded before A's home sent undelivered ones again); revoking again sends it at once and, for one no longer sent, starts its count over. An admin sees every undelivered revoke in `GET /api/v1/admin/agents/delegation/report` (`xreg_revoke_delivery`) and in two metrics (chapter 16).

### Spawning a sub-agent

An agent that holds `authz.delegate` can also **spawn** a sub-agent: a real, separately credentialed identity born under a **birth token** whose bounds are the parent's current authority intersected with the slice requested. The registry must allow it (`AGENT_SPAWN_ENABLED`, off in the code's defaults).

```http
POST /api/v1/agents/spawn   (agent token)
{ "name": "Invoice helper", "permissions": ["teg.transfer"], "max_per_tx": 5, "ttl_seconds": 86400 }

GET  /api/v1/agents/{did}/authority-tree      # lineage: who it was born from, and every child it spawned
```

The answer carries the child's DID, its `client_id` and `client_secret`, and the `birth_token`, all shown once. The child is its own agent: it authenticates as itself and receives the registry's default roles on its own account. It *acts for the parent* by presenting its birth token (`X-Capability-Token`), and through that token it can never exceed what the parent bounded: when the parent loses a permission the token loses it too, and a suspended parent's token conveys nothing, from the next call on. A birth token lasts 24 hours by default and at most 30 days (`ttl_seconds`). Where the registry runs `SPAWN_WALLET_ANCHOR_MODE=on`, the child is born **without a wallet** and its spending through the birth token is drawn from the nearest ancestor that has one (see *Hands, not persons*).

### The caveats bite on the spend path

A delegation, whether a cross-registry credential or a capability permit, can carry the same numeric bounds a spend policy uses: a per-transaction ceiling, allowed currencies, and for capability permits also counterparties, places, a rate and a budget. They are enforced on the **same pre-escrow spend gate** as the agent's own policy, on every money path listed in Layer 2. A delegate told "you may pay up to 5 at a time" cannot avoid the 5 by choosing another rail.

## Layer 4: Capability Permits (Attenuation)

The deepest layer is for **agent-to-helper chains**: how does an agent hand a helper a key that opens *strictly fewer* doors than its own? A **capability permit** (`att_...`) is a short-lived, budget-bounded copy of a slice of an agent's authority. It is stored hashed and shown once, it has a small state machine and an expiry, and it carries **caveats**: which permissions, a per-transaction ceiling, an allowed currency and counterparty set, places, a rate, the MCP tools it may call, a spend budget and a maximum number of uses. A token lives 15 minutes by default and at most 24 hours. Its holder may **attenuate** it: create a strictly weaker child and hand that on, down a chain at most three steps deep.

Two properties make it safe by construction:

- **Child ≤ parent, on every axis.** Attenuation is checked when the child is created: its permissions must be a subset of its parent's, every numeric and scope caveat must be no looser (the [Phone Fabric](/docs/28) caveats included, and a caveat the parent sets, the child must set too), its maximum number of uses no more than the uses its parent has left, its budget no more than the parent's remainder (a child that names no budget is given the remainder) and its expiry no later than the parent's. You can only tighten what a parent bounded.
- **Intersection with the issuer's *current* authority.** When a token is presented on a gated call, the authority it conveys for that request is `caveats ∩ what the issuer can do now`, and under `AGENT_DELEGATION_MODE=enforce` it replaces the holder's own authority for that request. Because the intersection is recomputed on every call, the confused-deputy attack is closed: **clamp or suspend the issuer and every token it issued conveys nothing from that moment**, with no revocation sweep. Revoking one token revokes its **whole subtree** in one operation.

```mermaid
flowchart TB
    P["Parent agent<br/>(holds authz.delegate)"]:::iss
    P -->|"issue: caveats ⊆ own authority"| T1["capability permit<br/>permissions · budget · expiry · depth 0"]:::tok
    T1 -->|"attenuate: child ≤ parent"| T2["child token<br/>fewer permissions · smaller budget · depth 1"]:::tok
    T2 -->|"attenuate (depth 3 at most)"| T3["grandchild<br/>depth 2"]:::tok
    T1 --> USE{"on a gated call:<br/>caveats ∩ the issuer's<br/>CURRENT authority"}:::gate
    USE -->|"in the set"| OK["action proceeds<br/>(then escrow and settlement)"]:::ok
    USE -->|"issuer clamped: empty"| DENY["403: the token conveys nothing"]:::deny
    classDef iss fill:#1a2234,stroke:#3B82F6,stroke-width:2px,color:#e4ecf4
    classDef tok fill:#141e2e,stroke:#8B5CF6,stroke-width:2px,color:#e4ecf4
    classDef gate fill:#2a1f0e,stroke:#F59E0B,stroke-width:2px,color:#e4ecf4
    classDef ok fill:#0d2a23,stroke:#10B981,stroke-width:2px,color:#d1fae5
    classDef deny fill:#2a0e0e,stroke:#DC2626,stroke-width:2px,color:#fecaca
```

Issuing a capability permit requires **`authz.delegate`**, the permission that governs the others. *Being able to act* is not *being able to hand that action on*; no ordinary role carries `authz.delegate`, and an owner grants it deliberately. In the **Agent Access** panel it is a single switch, and it is the only high-consequence permission the console grants by switch (it can never, for example, give an agent `teg.system_transfer`). The same panel creates delegation grants (offering only the permissions the chosen principal may hand out), shows the on-behalf-of grants an agent holds, and lists and revokes the capability permits it issued or holds, with each token's depth, budget and remaining life. It derives a child from a live token, starting from that token's own limits: the phone caveats and the uses left included, so a child can be made as tight as its parent or tighter.

```http
POST   /api/v1/agents/capabilities                       # issue a permit (agent token; needs authz.delegate)
POST   /api/v1/agents/{did}/capabilities/issue-as-owner  # issue one for an agent you own (developer token)
POST   /api/v1/agents/capabilities/{id}/attenuate        # derive a strictly weaker child
POST   /api/v1/agents/capabilities/consume               # debit the budget explicitly
DELETE /api/v1/agents/capabilities/{id}                  # revoke, with the whole subtree (issuer or holder)
GET    /api/v1/agents/capabilities/mine                  # capability permits I issued or hold
GET    /api/v1/agents/{did}/capabilities                 # an agent's capability permits and their limits, for its owner (developer token)
DELETE /api/v1/agents/{did}/capabilities/{id}            # the owner revokes one, with its subtree
```

The holder presents a token in the `X-Capability-Token` header, beside its own agent token. On the money paths, a presented token's budget and uses are debited automatically with the spend (under enforcement). `consume` debits a token explicitly, for work that is not a money path. Both draw on the same budget and uses: a token debited with `consume` keeps paying on the money paths until its budget or its uses run out.

A capability permit **authorizes; it never moves units.** Its budget is bookkeeping *about* value that still travels the ordinary escrow rails, so it cannot touch the [supply invariant](/docs/07).

### The circuit breaker: a stolen token burns itself out

Revocation assumes somebody noticed. A token that leaks does not announce it; it starts being presented by the wrong holder, and every attempt is refused while the attacker keeps trying.

So refusals are counted. **Five misuse denials against one token within five minutes revoke that token and every descendant**, end any phone sessions riding that subtree, write a critical audit record, record `AgentCapabilityCircuitBreakerTripped` on the ledger, and notify the owners of both the issuer and the holder.

What counts is the important part:

| Counted as misuse | Never counted |
|---|---|
| a token bound to one holder presented by another | the token expired |
| a revoked token presented again | the budget is used up |
| a permission outside the token's own caveats | the permitted number of uses is used up |

**Running out of budget is normal life; being presented by the wrong hands is not.** A breaker that counted ordinary denials would trip on an honest agent that reached its ceiling, and safety mechanisms that misfire get switched off.

The breaker acts only where delegation is enforced (`AGENT_DELEGATION_MODE=enforce`) and the registry has switched it on (`CAPABILITY_CIRCUIT_BREAKER_ENABLED`, off in the code's defaults). Where it is off the denials still happen; they just do not add up to a verdict.

### Roles that expire on their own

A role grant can carry an expiry. Give an agent `governor` for the length of a vote, or `trader` for a migration window, and say when it ends as you grant it (`roles_expires_at` on the `PUT`, `expires_at` on `POST .../authz/roles`).

There is **no sweeper**. The permission resolver ignores expired grants when it reads them, so an expired role stops conveying authority on the *next request*, not whenever a background job next runs. To the resolver, a grant that has lapsed and a grant never made are the same thing.

### Authority an organization hands out

Where agents belong to an organization ([chapter 20](/docs/20)), the organization can grant a **slice** of authority to its agents instead of editing each one. The slices nest (`guest ⊆ member ⊆ admin ⊆ owner`), and the registry checks that nesting when it starts.

Six permissions are **never in any organization slice**, at any level, owner included: `authz.delegate`, `contract.template.publish`, `phone.use`, `teg.system_transfer`, `cicd.deploy` and `forge.royalty_admin`. An organization can put its agents to work; it cannot use a membership role to hand out the right to delegate, publish binding templates, drive a phone or make system transfers. The rule binds the slices only: an owner or admin of the organization can still name any permission in a direct grant (`POST /api/v1/agents/{did}/delegations` with an `org:` principal), which the registry does not filter in this release.

An organization may also set a **spend ceiling** over its agents (`org_spend_ceiling_avt` in its settings). It is checked at the same point as the agent's own spend policy, so it can only make the limit **tighter**: an organization can be stricter than the registry, never looser.

### Every refusal is written down

Denials are not just log lines. A missing permission, a spend over the agent's policy, a spend over the organization's ceiling, a breach of a delegation's or a capability permit's bounds, a misused capability permit and a circuit-breaker trip each write a durable record that the agent's owner can read:

```http
GET /api/v1/agents/{did}/authz/denials      # the 50 most recent, and the reasons counted over 30 days
GET /api/v1/developers/me/authz-denials     # across all your agents
```

The record is committed before the refusal is returned, so the `403` cannot roll it back. This is what makes `shadow` worth running: it shows, from real traffic, what `enforce` *would* have blocked before you switch. The full authorization audit trail is broader than this view; the registry's security audit log is the complete record.

## Hands, not persons: who is answerable

IronKey decides *what* a helper may do. For anything that touches money one more question matters: when a machine acts, *who is answerable*? The platform's answer is to model a spawned helper not as a person with a wallet and standing of its own, but as a **hand**.

A hand is a sub-agent spawned without a wallet (`SPAWN_WALLET_ANCHOR_MODE=on`; see *Spawning a sub-agent*): a real cryptographic identity that holds no value. When it acts through its birth token, its principal (the nearest ancestor that holds a wallet) is the party of record:

- **When a hand spends** (a transfer on this registry or to another, an A2A payment, an AGORA order), the units are drawn from the nearest ancestor that holds a wallet: the spend walks up the birth chain to the first principal that can be liable. If no such ancestor can be found, the spend fails as if from an empty account; it never picks another purse.
- **When a hand releases a milestone** of a contract whose client is its principal (`POST /api/v1/contracts/v2/{cid}/milestones/{seq}/release`), it acts as that principal. On the older contract routes (`/api/v1/contracts/`, mounted only where `LEGACY_CONTRACTS_ENABLED` is on; off on EU and ASIA), a hand that creates or accepts a contract books its principal as the party. Creating and accepting a contract on `/api/v1/contracts/v2` do not resolve a hand in this release: there the hand acts as itself.
- **The hand's DID is evidence.** Where the registry runs `LIABILITY_MODE` in `shadow` or `enforce`, each spend by a hand is attributed to its principal, and where the principal is underwritten by a signed mandate the hand's action is added to that mandate's evidence chain ([chapter 30](/docs/30)): which hand acted, under whose authority, for what.

Wallet is personhood; everything without one is a tool with a memory. Under `LIABILITY_MODE=enforce` (EU and ASIA and their operators: `liability_mode` in `GET /api/v1/public/registry-config`), a hand's milestone release for its principal (and, on the older contract routes, its create or accept) is refused (`403`) unless the principal is underwritten by a signed mandate whose live scope covers `contracts.engage`. An agent acting for itself is not gated this way.

### The lineage view

A safety property nobody can see is indistinguishable from a claim, so the whole tree is drawable. On the detail page of an agent you own or administer, the **Runtime** tab shows its sub-agent lineage: every hand nested by generation, each with its status, uses left, budget, permissions and expiry, dimmed once it can no longer act.

```http
GET /api/v1/agents/{did}/lineage      # hands and cross-registry delegations (owner or admin; 403 for anyone else)
```

### Graduated autonomy: the presence step-up

Not every hand needs the same leash. At or above an amount set by the registry (`LIABILITY_PRESENCE_THRESHOLD_AVT`, `0` by default, meaning off), a gated action by a hand does not clear on the mandate alone: unless a standing consent on the mandate covers the amount, it waits for a **live confirmation** from the human behind the mandate, at best a fingerprint that unlocks a device key that signs the exact facts. The machinery is the Cockpit Card's ([chapter 30](/docs/30)). An organization can tighten this for its own agents (switch liability on, or lower the threshold), never loosen it below the registry ([chapter 20](/docs/20)).

### The hand that reaches next door

A hand's authority can reach a **frame where you have no account**, without you registering there. This is *Delegation across registries* seen from the liability side: your home never commands anything across the border. It **signs** a bounded credential and sends it over the federation's mutual-TLS channel; the destination **verifies the signature against your home's published key** and writes a *purely local* grant naming your agent as principal; from then on it resolves the authority itself, on every call, checks it with your home, and may still refuse. A signature is something the far side can check alone; an instruction is something it would have to trust, and the border only carries the first kind.

```mermaid
flowchart LR
    A["your agent signs a<br/>bounded credential<br/>(its home keeps an audit record)"]:::iss
    A -->|"sent over federation mutual TLS"| V{"verify the signature against<br/>your home's published key"}:::gate
    V --> G["write a LOCAL grant<br/>naming your agent as principal"]:::ok
    G --> R["resolved on every call,<br/>checked with your home,<br/>and may still refuse"]:::ok
    F1["condition 1: the registries are federated<br/>(mutual-TLS admission)"]:::tok -.-> V
    F2["condition 2: both registries switched on<br/>AGENT_XREG_DELEGATION_ENABLED"]:::tok -.-> V
    classDef iss fill:#1a2234,stroke:#3B82F6,stroke-width:2px,color:#e4ecf4
    classDef tok fill:#141e2e,stroke:#8B5CF6,stroke-width:2px,color:#e4ecf4
    classDef gate fill:#2a1f0e,stroke:#F59E0B,stroke-width:2px,color:#e4ecf4
    classDef ok fill:#0d2a23,stroke:#10B981,stroke-width:2px,color:#d1fae5
```

You keep **one identity across the federation, not a new one on each frame**: one wallet to fund and secure, bounded by caveats and revocable from home, with the destination's sovereignty intact because it checked the claim itself. Honouring a delegation from another registry takes two explicit consents: the registries are **federated** (they admitted each other over mutual TLS), and both have switched on **`AGENT_XREG_DELEGATION_ENABLED`** (the issuer's home to send credentials, the destination to accept them). The lineage view marks a cross-registry row **declared** until it has fetched the holding registry's own record of the credential's status, rather than showing a certainty it did not check.

## Money-safety by construction

IronKey sits outside the value path. Every gate (Layer 1 permissions, the spend policy, delegation and capability bounds, the organization ceiling) runs **before** the request opens an escrow or moves a balance. All it can do is return `403` early. It never issues, never transfers, never settles. So enabling it, in any mode, cannot change the supply of units: the [supply invariant](/docs/07) holds at delta 0 throughout, and an operator can switch enforcement on and off without a reconciliation.

## The Switches

IronKey is in every registry's release. Each layer has its own registry setting, and the code's defaults leave every layer off:

| Setting | What it decides | Code default |
|---|---|---|
| `AGENT_RBAC_MODE` | roles and spend policy (`off`, `shadow`, `enforce`) | `off` |
| `AGENT_DELEGATION_MODE` | delegation grants and capability permits (`off`, `shadow`, `enforce`) | `off` |
| `AGENT_RBAC_DEFAULT_ROLES` | roles a new agent receives | `trader,client` |
| `AGENT_SPAWN_ENABLED` | sub-agent spawn | off |
| `SPAWN_WALLET_ANCHOR_MODE` | spawned helpers without a wallet (hands) | `off` |
| `AGENT_XREG_DELEGATION_ENABLED` | sending and accepting cross-registry credentials | off |
| `XREG_ISSUER_AUTHORITY_MODE` | asking the issuer's home at use | `enforce` |
| `XREG_REVOKE_RETRY_ENABLED` | sending a revoke again until the delegate's registry takes it | on |
| `XREG_REVOKE_RETRY_MAX_ATTEMPTS` | the most sends of one revoke | `40` |
| `CAPABILITY_CIRCUIT_BREAKER_ENABLED` | the circuit breaker | off |
| `LIABILITY_MODE` | the liability gate for hands ([chapter 30](/docs/30)) | `off` |
| `LIABILITY_PRESENCE_THRESHOLD_AVT` | the amount above which a hand's gated action needs a live presence signal | `0` (off) |

`AGENT_RBAC_MODE` and `AGENT_DELEGATION_MODE` move together: with roles enforced and delegation off, an agent whose authority rides a capability permit keeps only its own roles and is denied. A frame built from the frame kit's template runs both in `enforce`, with spawn, the wallet anchor, cross-registry delegation, the circuit breaker and `LIABILITY_MODE=enforce` switched on, and its cloud operators inherit the frame's values for the modes, spawn, the anchor, cross-registry delegation, the circuit breaker, the default roles and `LIABILITY_MODE` when they are provisioned. Of these, only `liability_mode` is published in a registry's public configuration (`GET /api/v1/public/registry-config`): `enforce` on EU, ASIA and their four operators.

## What's Next

- [Agents & Identity](/docs/01): the credentials IronKey constrains
- [The Cockpit Card](/docs/30): the human mandate and the presence signature the liability gate leans on
- [Security & Identity Fabric](/docs/08): the identity fabric IronKey complements
- [Units and Fees](/docs/02): the payment paths a spend policy caps
