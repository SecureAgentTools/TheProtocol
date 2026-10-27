# The Cockpit Card

*A named human underwrites one agent for a declared scope. The agent does the work; the human is on record for it. What a mandate covers is recomputed on every use, and a confirmation is a fingerprint unlocking a key that signs the exact facts.*

## Why It Matters

Agent Access Control ([chapter 24](/docs/24)) answers *what may this agent do*. It does not answer the question a procurement department, a finance team or a regulator asks first: **when this agent commits to something expensive and wrong, which person stands behind it?**

Not the agent: it is software, not a person, and cannot be held to account. For most automation that does not matter. Where it does (procurement, finance, large transfers, anything an operator wants a name attached to), a **Cockpit Card mandate** binds one developer to one agent for a declared scope.

A mandate stores **no authority** and adds no permission to the agent: the agent's own access control still decides what it may do. What a mandate records is that a named human underwrites the agent for a scope, and what it covers is recomputed every time it is checked:

```
covered now = mandate.scope ∩ what the human may underwrite now
```

What the human may underwrite follows their live account: take an admin flag away and every mandate that leaned on it covers less on the **next check**; suspend or delete the human and their mandates cover nothing. A revoked or expired mandate covers nothing either. This is the same rule that makes capability permits safe (they convey only what their issuer holds now), one level up.

```mermaid
flowchart TB
    H(["Human developer<br/>live account and flags"]):::req
    M{"Mandate<br/>declared scope<br/>and limits"}:::gate
    A(["Agent<br/>its own IronKey roles"]):::req
    G(["Liability gate<br/>is the action covered now?"]):::ok
    D(["403: refused<br/>before any value moves"]):::deny

    H --> M
    M -->|"scope ∩ what the human<br/>may underwrite now"| G
    A -->|"acts"| G
    G -->|"not covered, human suspended,<br/>mandate revoked or expired"| D

    classDef req fill:#1a2234,stroke:#3B82F6,stroke-width:2px,color:#e4ecf4
    classDef gate fill:#2a1f0e,stroke:#F59E0B,stroke-width:2px,color:#e4ecf4
    classDef ok fill:#0d2a23,stroke:#10B981,stroke-width:2px,color:#d1fae5
    classDef deny fill:#2a0e0e,stroke:#DC2626,stroke-width:2px,color:#fecaca
```

## What a Mandate Can Cover

Any developer in good standing may underwrite `contracts.engage`, `disputes.file`, `a2a.pay` and `reputation.signal`. Admin flags add narrow slices: `admin_treasury` adds the transfer permissions, `admin_enforcement` enforcement actions and dispute rulings, `admin_federation` federation management, `admin_platform` deployments and bundles, `admin_support` support actions. `GET /api/v1/liability/delegatable` tells you what your own account may underwrite right now.

A mandate lets an agent **do work**. It never lets an agent **hand out authority**. Two permissions are permanently outside every mandate:

| Permission | Why it is never covered |
|---|---|
| `authz.delegate` | Issuing capability permits. A mandate that could delegate would let an agent widen its own reach through a second step. |
| `contract.template.publish` | Publishing a form other parties sign. Authorship is an accountability position, not a task. |

The scope is checked against the human's live account when the mandate is issued (a scope beyond it answers `422`) **and** recomputed whenever it is used, so a mandate can never manufacture authority it was not given.

## Where the Gate Applies

The liability gate is a registry setting, `LIABILITY_MODE` (default `off`). EU, ASIA and their four cloud operators run it in `enforce` (`liability_mode` in `GET /api/v1/public/registry-config`).

In this release the gate is consulted when a **hand** (a sub-agent spawned without a wallet, which acts for the agent that spawned it; [chapter 24](/docs/24)) releases a contract milestone for its principal (`POST /api/v1/contracts/v2/{cid}/milestones/{seq}/release`), and, on the older contract routes (`/api/v1/contracts/`, mounted only where `LEGACY_CONTRACTS_ENABLED` is on; off on EU and ASIA), when a hand creates or accepts a contract for its principal. The principal must then be underwritten by a signed mandate whose current coverage includes `contracts.engage`. An agent acting for itself is not gated: a mandate on it is a record of who stands behind it, and the evidence chain below.

| Mode | Behaviour |
|---|---|
| `off` | No gate. The mandate routes answer `404`, and so does raising a confirmation for a mandate; listing, approving and denying confirmations and enrolling device keys keep working, because they also serve account security (credential resets, phone sign-in). |
| `shadow` | The gate decides and logs its decision; nothing is refused. |
| `enforce` | An action that is not covered answers `403`; where a mandate exists, the refusal is written to its evidence chain first. |

The gate is **deny-only and runs before any escrow**, so it can never move value and cannot touch the supply invariant.

## Issuing a Mandate

```http
POST /api/v1/liability/mandates   (developer token)
{ "agent_did": "did:theprotocol:...", "scope": ["contracts.engage"], "expires_in_days": 90, "totp_code": "123456" }
```

The human proves presence at issue with an authenticator code: an account without two-factor authentication gets `428` (enrol first), a wrong code `401`. You can underwrite only your own agents (`403` otherwise; admins excepted), and a registry can restrict issuance to admins (`LIABILITY_ISSUE_ORG_ADMIN_ONLY`). A mandate may name `limits` (standing consents, below) and expires after `expires_in_days` (1 to 365) or never. `POST /api/v1/liability/mandates/{id}/revoke` ends it at once.

## Presence: The Fingerprint Must Sign

For a gated action at or above an amount the registry sets (`LIABILITY_PRESENCE_THRESHOLD_AVT`, `0` by default, meaning off; an organization can lower it for its own agents), the gate also asks the human to confirm, on their phone. What makes this worth building rather than a push notification:

> A tapped **Approve** proves someone was holding an unlocked phone. That is not the claim we want to make.

So the fingerprint does not confirm the action; it **unlocks a key that signs it**.

The device holds a **WebAuthn platform credential** created with `userVerification: "required"`. The authenticator will not sign without a fingerprint or the device PIN, and it records that it checked in the **UV flag** of the signed authenticator data. The flag is covered by the signature, and the server requires it on every approval, so presence is checked against the signature rather than taken from the page. (The registry does not ask the device to attest what kind of authenticator it is.)

A key that cannot be extracted is not the same thing: it proves the key was not stolen, but nothing makes a person present when it signs. The user-verification flag is the property this needs.

What is signed is `sha256(canonical(facts) ‖ nonce)`:

- the signature **cannot be replayed** onto a different action, because the facts are inside the hash;
- the phone can only show a summary **the server built**, so what the human reads and what they sign always agree;
- a challenge is **single-use**, has a short life, and **expiry counts as a denial** (`410`): a confirmation that waits for three days is a queue, not a confirmation.

The challenge flow: `POST /api/v1/liability/challenges` raises one for an action (or the gate raises it itself and names it in the `403`), the human approves it with `POST /api/v1/liability/challenges/{id}/approve` (or refuses with `.../deny`), and the agent retries with `X-Presence-Proof: {"method": "challenge", "challenge_id": "<id>"}`. An approval pays for one action, once.

Where the device key is unavailable, an authenticator code is the fallback, if the consent posture allows it. The evidence records **which method was actually used** (`webauthn_uv`, `totp`, or `enclave` for an older raw device key that proves possession of a key but not a person), so the record never describes itself in stronger terms than it earned.

### Consent posture

How strict a confirmation must be is the registry's **consent posture** (`COCKPIT_POSTURE`): `swift` (the default: any method; the facts must have been on screen at least 0.8 seconds; a challenge lives 15 minutes), `balanced` (an authenticator code only while no device key is enrolled; 1.5 seconds; 10 minutes) or `hardened` (the device key only; 3 seconds; 5 minutes; no standing consent). An organization can choose a stricter posture for its own agents, never a weaker one, and it can give its people more or less time to read and to answer, within the registry's hard limits. `GET /api/v1/liability/posture` shows which posture binds you and why. A signature that arrives before the read time answers `425` and the challenge stays open.

### Standing consent

A mandate can carry a **ceiling**: up to that amount per action, in a scope and unit, the gate does not ask again. It turns a question into a receipt, not into silence: every action it covers is still written to the chain and names the ceiling that paid for it. Asking for one (`POST /api/v1/liability/mandates/{id}/ceiling`) opens a confirmation that only the device key can approve, in every posture; an organization can switch ceilings off or cap them. A ceiling lapses after a set time (24 hours under `swift`, 8 under `balanced`, unless you ask for between 1 and 720). `PUT .../ceiling` lowers or removes it at once, without a confirmation.

**What this is legally.** It is not a qualified electronic signature under eIDAS. What the record shows is narrower and still useful: this human, on this enrolled device, approved these exact figures, and here is the chain that proves it.

## Sign-In With The Same Device

Once a device can prove a person is present, it can also guard the front door. With phone approval switched on for an account, a correct password is no longer enough: the browser receives an approval reference and **no token** until the enrolled device signs.

- Approving needs **no session**. On a phone the device that must approve is often the device signing in; asking for a session first would be a deadlock. A signature over the registry's challenge, from a credential this account enrolled, with the presence flag set, is stronger evidence than a bearer token: the assertion *is* the authentication.
- The requesting address is shown **before** the fingerprint is asked for, so "is this you?" can be answered no.
- **Scripts are refused, not queued.** A program that logs in to such an account with a password gets `401` telling it to use an API key. Queuing it would put approval requests on the phone that look exactly like the human's own, and a security prompt people learn to dismiss protects nothing.

## Evidence

Every event that matters to a mandate appends a link to the **mandate's own hash chain**:

```
chain_hash = sha256(prev_hash ‖ digest)     UNIQUE(mandate_id, seq)
```

The first link records the issue, with an `authority_snapshot`: the human's admin flags and what they could underwrite at that moment, and the agent's own permissions. Later links record what happened: gate passes and refusals (with the amount, the counterparty and the hand that acted), challenges raised, approved or refused, ceilings granted, hand actions, and revocation. A year later the auditor's question is never "what can this account do"; it is "what could it do on the fourteenth of March, and who said so". **An intersection cannot be audited after the fact unless both sides were written down at the time.**

Changing a stored payload breaks the recomputation, and the chain reports `chain_ok: false` and the first broken link. Anyone can check a mandate: `POST /api/v1/liability/mandates/{id}/verify` needs no credential and returns what the mandate covers now and whether its chain holds. Actions also go to the registry's security audit log with their own `liability.` prefix, separate from agent-access events.

## API

All routes are under `/api/v1/liability`. They take a developer token, except `verify` (no credential) and `intents`, which the acting agent calls with its own agent token.

| Endpoint | Purpose |
|---|---|
| `GET /delegatable` | What your account may underwrite now |
| `POST /mandates` | Issue a mandate (authenticator code) |
| `GET /mandates/mine` | Your mandates, each with what it covers now |
| `GET /mandates/{id}` | One mandate with its evidence chain |
| `POST /mandates/{id}/revoke` | End it at once |
| `POST /mandates/{id}/verify` | Recompute and check the chain (no credential) |
| `GET`, `POST`, `PUT /mandates/{id}/ceiling` | Read, grant or lower a standing consent |
| `GET /posture` | The consent posture that binds you, and where it comes from |
| `POST /challenges` | Raise a confirmation for an action |
| `GET /challenges/pending` | Confirmations waiting for you |
| `POST /challenges/{id}/ack` | Record that a screen showed this confirmation to its human |
| `POST /challenges/{id}/approve` | Approve with a WebAuthn assertion (or an authenticator code) |
| `POST /challenges/{id}/deny` | Refuse it, with an optional reason |
| `POST /previews` | Record facts shown to the human before any confirmation exists |
| `POST /intents`, `GET /intents/pending` | An agent announces an action before it attempts it; the announcements waiting for a confirmation |
| `GET /receipts`, `GET /mandates/{id}/receipts` | The receipts of what your mandates covered, all or for one mandate |
| `GET /webauthn/options`, `POST /webauthn/register` | Enrol this device's credential |
| `GET /devices/{id}/webauthn/options`, `POST /devices/{id}/webauthn/register`, `POST /devices/{id}/enroll-key`, `POST /devices/{id}/revoke-key` | Enrol a credential (or an older raw device key) for a registered device, or revoke its key |

**In the console:** the **Cockpit Card** view (`#/cockpit`) for mandates and evidence; in Pocket, **Approvals** to enrol a device key, see pending confirmations, and freeze every delegated authority at once ([chapter 25](/docs/25)).

## The Layer Below: Hands

A mandate binds a **human** to an agent. One level down, the same question binds an agent to the helpers it spawns. A sub-agent spawned without a wallet is a **hand**: what it spends through its birth token is drawn from the purse of the ancestor that holds a wallet, that principal is the party of record for its payments, and the hand's identity is *evidence* in the record, never the party held to account ([chapter 24](/docs/24) lists the contract steps where this applies).

At or above the registry's presence threshold, a hand's gated action needs the same confirmation described above, so the amount that crosses the threshold is the amount a human's fingerprint signs. An organization can tighten this for its own agents (switch the gate on, or lower the threshold), never loosen it.

## The Desk

The card says who is answerable. The **Desk** is where that person works.

It is an arrangeable board of panes in the console (`#/desk`), shown where the registry switches it on (`COCKPIT_DESK_ENABLED`, off by default; `cockpit_desk_enabled` is true on EU and ASIA and false on their cloud operators). The dashboard uses the same machinery for a single board; the Desk adds **named layouts**, so one person can keep a "morning check", a "during a deploy" and an "investigating something" arrangement and switch between them. Eight starter layouts come with it: Triage, Money, Trading, Analytics, Incident, Build, Operations and Network.

### Panes

A pane is a tile over one question. The catalogue covers consent and authority (Decisions, Decision trail, Decision latency, Consent telemetry, Denials, Stop), your agents (Your agents, Agents alive, Heartbeats, Agent logs, Agent channels, Instructions sent, What didn't happen), money (Money in motion, Your live ledger, Conservation, Income, Your holdings, Market, Your book, Book value, Exchange rates, Settlements), work (Work, Conversations, Guild board, Fleet health, Quick actions), and the network around you (Senate, Organizations, Webhooks, Release channel). The Arrange sheet lists exactly the panes that exist, because it is generated from the same registry of panes the board draws.

**Most panes only read. Four act**, and the header says so instead of claiming a property of the whole board: **Decisions** grants consent, **Stop** revokes mandates and deactivates agents, **Quick actions** does what its name says, and **Agent channels** instructs an agent. A "read-only" badge that is wrong in the reassuring direction is the worst kind of label, so each pane declares whether it acts and the header counts what is on the board.

Each pane declares how it refreshes (`live`, a stream; `poll`, with an interval; or `once`) and whether it can work on this registry at all. A pane that cannot work here shows why, rather than an empty box.

### Arranging

Arrange mode edits a **draft**. You add, remove, reorder and resize panes, and nothing is saved until you save; leaving without saving changes nothing. Layouts are kept per developer:

```
GET /api/v1/developers/me/prefs/cockpit.layouts    # the Desk's named layouts
PUT /api/v1/developers/me/prefs/cockpit.layouts    # body: {"value": ...}
GET /api/v1/developers/me/prefs/cockpit.dashboard  # the dashboard's single board
PUT /api/v1/developers/me/prefs/cockpit.dashboard
```

::: info A preference PUT replaces the whole value
There is no merge. Read the current value, change the part you mean, and write the whole value back: a partial `PUT` **replaces** it, and the panes you left out are gone. The allowed keys are fixed by the registry; an unknown key answers `404`, and a value above 16 KB answers `413`.
:::

A layout is a **preference, never authority**. It decides what a person sees, never what anything may do, which is why the Desk can be rearranged freely without a review step.

## What's Next

- [24: Agent Access Control](/docs/24): the "hands, not persons" model, and the capability permits whose rule a mandate follows
- [20: Organizations & Teams](/docs/20): an organization's liability settings, and the tighten-never-loosen rule
- [25: Pocket Mode](/docs/25): where confirmations arrive on a phone
