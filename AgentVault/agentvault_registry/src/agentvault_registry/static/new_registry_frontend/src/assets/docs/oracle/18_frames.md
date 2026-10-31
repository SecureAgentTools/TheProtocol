# Sovereign Frames

*What makes a registry a frame: its own trust domain, its own ledger and its own unit, federated with other frames as an equal. This chapter covers how two frames federate, what crosses between them, and how to get a frame of your own.*

## Why It Matters

A cloud operator (chapter 17) is a registry under a frame: it has its own accounts and agents, but it lives in its frame's trust domain, settles in its frame's unit and writes into its frame's ledger. That is enough for most needs. Some deployments need more: their own certificate authority, their own ledger and their own unit, for example to keep data in one jurisdiction or to run under their own rules. That is a **frame**.

The production network runs two frames, EU (unit ECU) and ASIA (unit ACU), each with its own trust domain. The diagrams in this chapter use them, with illustrative domains (`example.com` and `peer.example.com`). The pattern is the same for every frame.

## Frame vs Operator: The Difference

| | Operator | Frame |
|---|---|---|
| SPIRE trust domain | shares its frame's | **its own** |
| Event store (ledger) | writes into its frame's | **its own** |
| Unit | its frame's | **its own** |
| Issuance | disabled | **its own treasury issues its own unit** |
| Licence | an admission key and a signed operator licence from its frame; rides its frame's network licence | **a network licence from the genesis, where the network enforces licences, and an admission key from each frame that admitted it** |
| Value to another frame | through its frame's FX route (an operator holds no FX reserve) | **the FX pool with each peer frame (or the wrapped-unit bridge, where it is switched on)** |
| Relationship | under one frame | **a peer of other frames** |

An operator works inside its frame's trust. A frame is its own authority, with an agreement with each frame it federates with.

## A Frame and Its Own Operators

A frame issues its own cloud operators' licences from the day it stands up, under its own operator policy: it admits them, signs their licences and runs them in its own trust domain (chapter 17). That relationship belongs to the frame. Whom it admits, what it asks of them in return (for hosting them, say) and on what terms are agreed between the frame and its operators; the network takes no part in it. Inside one trust domain no network licence is checked (*The Network Licence* in chapter 5), so a frame that does not federate with another frame runs itself and its operators under the code's open-source licences alone, and sets its own fee rates in its own policy (*The feature switches*, below).

Federating with **another frame** is the one step that involves the network: it crosses between two trust domains, and that needs a network licence on both sides. The licence is free of charge; private, educational, research and non-profit frames hold it without an end date (the Federation Operator Terms, § 2). A frame that federates keeps the network's shared parameters, its fee rates among them, for itself and its operators, because their agents now trade with every other frame's.

## The Topology

> **Click any diagram to enlarge.**

```mermaid
flowchart LR
    subgraph FA["Frame EU (example.com)"]
        SA["SPIRE EU<br/>trust root"]:::spire
        RA[Registry EU]:::reg
        TA[TEG EU]:::teg
        EA[(Event Store EU)]:::es
        OpsA["EU's operators<br/>(cloud operator registries)"]:::ops
    end
    subgraph FB["Frame ASIA (peer.example.com)"]
        SB["SPIRE ASIA<br/>trust root"]:::spire
        RB[Registry ASIA]:::reg
        TB[TEG ASIA]:::teg
        EB[(Event Store ASIA)]:::es
        OpsB["ASIA's operators<br/>(cloud operator registries)"]:::ops
    end

    SA <-. "SPIFFE bundle" .-> SB
    RA <-. "invitation, then federation calls" .-> RB
    TA <-. "FX reserve legs" .-> TB
    EA <-. "event replication" .-> EB

    SA --- RA
    RA --- TA
    RA --- EA
    SA --- OpsA

    SB --- RB
    RB --- TB
    RB --- EB
    SB --- OpsB

    classDef spire fill:#0d2a23,stroke:#10B981,stroke-width:3px,color:#d1fae5
    classDef reg fill:#1a1430,stroke:#8B5CF6,stroke-width:2px,color:#e4ecf4
    classDef teg fill:#0d1e1a,stroke:#10B981,stroke-width:2px,color:#e4ecf4
    classDef es fill:#141e2e,stroke:#3B82F6,stroke-width:2px,color:#e4ecf4
    classDef ops fill:#2a1f0e,stroke:#F59E0B,stroke-width:2px,color:#e4ecf4
```

Four lines between the frames, four jobs:

- **SPIFFE bundle exchange**: each frame's SPIRE server holds the other's root, so each frame's gateways can verify the other frame's certificates.
- **The frame invitation**: the bilateral handshake that sets up the relationship, after which the registries pull each other's cards and make federation calls.
- **The FX pool**: value crosses between the two units through the two frames' FX reserves.
- **Event replication**: each event store copies the other's events into an audit table.

The rest of the chapter walks each one.

### What a single cross-frame payment does

Between EU and ASIA every payment changes unit, so it is an FX swap. The sender's registry runs it: it moves the units into its own frame's FX reserve, then asks the other frame's TEG, through that TEG's gateway and with its own certificate, to pay the receiver out of the other frame's reserve.

```mermaid
sequenceDiagram
    autonumber
    participant Ag as Agent on EU
    participant RE as Registry EU
    participant TE as TEG EU
    participant GA as TEG gateway of ASIA
    participant TA as TEG ASIA

    Ag->>RE: POST /api/v1/teg/cross-registry-transfer
    RE->>RE: the receiver settles in ACU, so this is an FX swap
    RE->>TE: read EU's reserve
    RE->>GA: read ASIA's reserve (mTLS, EU's certificate)
    GA->>TA: forwarded after the certificate check
    RE->>RE: price the swap from both reserves, less the FX fee
    RE->>TE: move ECU from the sender into EU's FX reserve
    RE->>GA: move ACU from ASIA's FX reserve to the receiver
    GA->>TA: forwarded after the certificate check
    TA-->>RE: credited
    RE->>RE: record FxSwapSettled
    RE-->>Ag: completed: amount, credited amount, fee
```

Each leg is a transfer inside one frame, so each frame's supply still balances on its own. If the credit on the far side is refused, the sender's leg is returned (`FxSwapRefunded`). If its outcome cannot be established, nothing is refunded: the swap is held for review, because the receiver may already hold the units. The far frame's TEG accepts this call because the two frames trust each other's certificates; admitting a peer frame means trusting its services with these legs. An agent on a cloud operator pays across frames through its frame: the operator holds no FX reserve, so it hands the transfer to its frame's FX route (`FX_ROUTE_ENABLED`, on for the production operators). The units move to the frame in the operator's own unit, and the frame runs the swap and delivers the result.

## The Frame Invitation

Two frames federate through an invitation that one frame sends and the other frame's admin approves. Neither frame is above the other. Where the network enforces licences (the production network does), the joining frame also needs a network licence: the network's genesis issues it, and can do so in the same approval.

```mermaid
sequenceDiagram
    autonumber
    participant AdmA as Admin of the joining frame
    participant FA as Joining frame
    participant FB as Approving frame
    participant AdmB as Admin of the approving frame

    AdmA->>FA: POST /api/v1/admin/federation/frame-invitations/outbound<br/>target_registry_url, contact_email
    FA->>FB: POST /api/v1/federation/frame-invitations<br/>trust domain, bundle endpoint, federation endpoint,<br/>event store, nonce, licence key, network licence
    FB->>FA: fetch the joining frame's SPIFFE bundle (a reachability check)
    Note over FB: invitation pending: FrameInvitationRequested
    AdmB->>FB: POST /api/v1/admin/federation/frame-invitations/{id}/approve
    FB->>FB: check the network licence (enforce refuses without one)
    FB->>FA: fetch the joining frame's bundle
    FB->>FB: import it into SPIRE, federate the workload entries,<br/>create the SPIRE federation relationship
    FB->>FB: write the peer row (frame), issue the admission key
    Note over FB: FrameInvitationApproved
    FB->>FA: POST /api/v1/federation/frame-invitations/{id}/finalize<br/>its bundle, the nonce echoed, the admission key,<br/>and a network licence if the genesis issued one
    FA->>FA: check the nonce, import the bundle,<br/>create the relationship, write the peer row,<br/>hold the admission key for an hour
    Note over FA,FB: FrameFederationEstablished on both sides
    FB->>FB: start pulling the joining frame's events,<br/>when the invitation named its event store
```

What to know about it:

- **The public endpoint is guarded.** `POST /api/v1/federation/frame-invitations` takes no credential, so it is rate-limited (5 an hour per caller), allows one pending invitation per trust domain, and probes the bundle endpoint it is given (an anonymous caller may name only a public https address). A frame can switch it off entirely with a setting (`FRAME_INVITATIONS_PUBLIC_DISABLED`).
- **Two sandbox frames on one host can federate with each other.** A host without public names has its frames' bundle endpoints on private addresses, behind an edge with its own internal certificate authority. A sandbox frame opts in with `FRAME_INVITATIONS_SAME_HOST_PEERS=true`, and names that authority's root with `FRAME_INVITATIONS_PEER_CA_FILE`. Then an anonymous invitation from the private network may name a bundle host on a private (RFC 1918 or ULA) address, and the invitation and its callback also trust that root when they reach the other frame's console. Loopback, link-local and shared (CGNAT) addresses stay refused, and so does any caller outside the private network. The setting takes effect only on a frame born as a sandbox (its standup wrote `FRAME_POSTURE=sandbox`). Elsewhere it does nothing, and the frame's invitation list says `refused`.
- **Approving is one admin's decision.** The approve, the reject and every other admin step need the federation flag (`admin_federation`) on the approving frame. A rejection needs a reason.
- **The callback can be retried.** If the callback to the joining frame fails, the approving side is already live and the joining side is not. `POST /api/v1/admin/federation/frame-invitations/{id}/finalize-retry` sends it again (with a new admission key, since the first was never delivered).
- **The admission key is collected once.** The joining frame's admin takes the delivered key, within an hour of the callback, with `GET /api/v1/admin/federation/frame-invitations/{id}/licence-key`; a second request answers 404. A key that was not collected in time is gone, and a `finalize-retry` cannot replace it once the callback has succeeded: the joining frame sends a new invitation, and its approval issues a new key.
- **SPIRE keeps the bundles fresh.** The federation relationship makes each SPIRE server re-fetch the other's bundle on its own schedule, so certificate rotation needs no further step. `GET /api/v1/admin/federation/frames/spire-status` compares the bundles SPIRE holds with the frame peer rows.
- **Either frame can leave alone.** `POST /api/v1/admin/federation/frames/{peer_id}/revoke` (with a reason) removes the SPIRE federation relationship and the peer's bundle, sets the peer row `INACTIVE` so it is never revived automatically, stops event replication from that peer, and tells the peer's contact by mail. No appeal, no central authority.

Every step is recorded on the frame's ledger: `FrameInvitationRequested`, `FrameInvitationApproved` or `FrameInvitationRejected`, `FrameFederationEstablished` (on both sides), and on a revoke `FrameFederationRevoked` and `PeerRegistryDeactivated`.

A frame stood up with the frame kit sends its invitation from its own host with `scripts/distribution/frame-federate.py`, which imports the peer's bundle, creates the invitation, waits for the approval and installs the delivered admission key. The operator documentation's *Federating a frame, call by call* lists every call both sides make.

## The Wrapped-Unit Bridge

::: info Off on the production frames
The production frames move value between them through the FX pool. The bridge is a second mechanism, mounted only where a registry switches it on (`TOKEN_BRIDGE_ENABLED`; the source default is on, the frame template and the production frames set it off, so its routes are not served there). It runs only on frames, never on operators.
:::

The bridge answers a different question: how can units issued on one frame be held on another frame without the other frame issuing anything of its own? The answer is wrapped units. The original units stay counted on the source frame, locked and out of circulation; the destination frame issues the same amount of wrapped units against them.

```mermaid
sequenceDiagram
    autonumber
    participant S as Sender on EU
    participant RE as Registry EU
    participant TE as TEG EU
    participant RA as Registry ASIA
    participant TA as TEG ASIA

    S->>RE: POST /api/v1/bridge/transfer<br/>target_agent_did, amount (at most 100,000)
    RE->>TE: lock the amount on the sender's account
    RE->>RA: POST /api/v1/bridge/mint-wrapped (mTLS)
    RA->>RE: POST /api/v1/bridge/confirm-lock (mTLS)
    RE-->>RA: confirmed: this lock, still held
    RA->>TA: issue wrapped units for the receiver
    RA->>RA: record WrappedTokensMinted
    RA-->>RE: issued
    RE->>RE: record TokensBridgeLocked
    RE-->>S: bridge_tx_id, status COMPLETED
    Note over RE,TE: if the issuance fails, the lock is released<br/>and the transaction is FAILED
```

The destination frame issues only against a lock the source frame confirms. The frame asking for the issuance must be an active frame peer of the destination, and the transfer's `source_frame` must name it. Before anything is issued, the destination frame asks that frame, at the address its own peer table holds, to confirm the lock (`POST /api/v1/bridge/confirm-lock`): the source frame answers only for a transfer it recorded and still holds locked, for the sending agent, the receiver and the amount the issuance names, with more than a minute left before the lock would expire, and only to the frame the transfer targets. Without that confirmation nothing is issued (409).

To go back, the agent the wrapped units were issued to calls `POST /api/v1/bridge/redeem` on the destination frame, naming the transfer (`bridge_tx_id`): the wrapped units of that transfer are burned on the destination frame, and the source frame releases that transfer's lock, its whole amount, back to the balance of the agent that sent it (`POST /api/v1/bridge/unlock`, which records `TokensBridgeUnlocked`). The destination frame takes the amount, the locked agent and the source frame from its own record of the transfer; the source frame releases only a lock it made, for the frame that holds the wrapped units, and only once. So a redemption returns the originals to the agent whose units were locked (normally the one that sent them), not to the holder of the wrapped units. If the unlock fails, the wrapped units are issued back. `GET /api/v1/bridge/status/{bridge_tx_id}` reports a transfer's state.

What the accounting promises:

- **The source frame's supply stays whole.** Locked units are still counted as issued; they only leave circulation while they are locked.
- **The destination frame issues nothing native.** Wrapped units are a separate balance, backed by the lock on the source frame.
- **The two sides can be compared.** Units locked on the source frame should equal the wrapped units outstanding on the destination frame. The event store's cross-frame audit counts the bridge events it has replicated from each peer frame; it reports counts, not amounts. One gap in the released software: a redemption burns the wrapped units but records no `WrappedTokensBurned` event, so the destination ledger's figure for wrapped units outstanding does not go down when units are redeemed.

## Event Replication Between Frames

Each event store copies the other frame's events, so each frame can see what happened on the other. The copy is pulled, not pushed, and it never changes the frame's own ledger.

```mermaid
sequenceDiagram
    autonumber
    participant ESB as Event store ASIA
    participant ESA as Event store EU
    participant FT as foreign events table on EU
    participant RX as EU's registry workers

    loop every CROSS_FRAME_POLL_INTERVAL (default 30 s)
        ESA->>ESB: GET /api/v1/events/export since the last position (mTLS)
        ESB-->>ESA: the events ASIA recorded since then
        ESA->>FT: store each one, keyed by frame and source event id
        ESA->>RX: pass on a few kinds live: cross-frame transfer steps,<br/>peer and licence changes, admin broadcasts
    end
```

What it is and what it is not:

- **Everything, as an audit copy.** The puller takes every event the peer recorded, and stores it in a separate `foreign_events` table, keyed by the peer frame and the source event's id, so a repeat is stored once.
- **Never part of the frame's own balances.** Replicated events do not move the frame's own projected balances or its supply check. Each frame's balances come only from its own ledger.
- **A few kinds are passed on live.** The steps of an asynchronous cross-frame transfer, peer and licence lifecycle events and admin broadcasts are also handed to the frame's own workers as they arrive, so that the asynchronous transfer path can settle and a peer's revocation reaches every frame.
- **What reads it.** The event store's cross-frame audit counts the replicated events per peer frame, and a frame's admins can read it (`GET /api/v1/admin/supply-auditor/cross-frame-audit`). Each frame also keeps the trust scores the other frame published, read from the replicated events, beside its own (`GET /api/v1/reputation/cross-frame`); they are shown, not mixed into its own reputation computation.

Replication is set up per direction, on the frame that pulls. The approve starts the approving frame's pull of the joining frame's events, when the invitation named the joining frame's event store (`event_store_url`); on the approving frame, `POST /api/v1/admin/federation/frames/{peer_id}/resync-eventstore` registers that store again when the step failed. On the joining frame no invitation names the approving frame's store: resync there takes the naming convention (`https://events-<trust domain>:8201`), and its answer says which source it used (`event_store_url_source`, `invitation` or `convention`). The callback does not start the other direction: the joining frame pulls the approving frame's events only once that store is registered on the joining frame too, for example by an invitation approved the other way. A revoke stops the pull from that peer. Replication runs only where the event store's `CROSS_FRAME_REPLICATION_ENABLED` is on (the frame template ships it off). On the production network both directions run: each frame's `GET /api/v1/reputation/cross-frame` lists scores replicated from the other.

## Governance Across Frames

A frame is governed by its own voters on its own proposals: its members or, on a registry that counts votes by locked units, the agents that locked units there. Which of the two a registry counts is a registry setting (`governance_weight_mode`), and the production frames count votes by membership. **No other frame votes on a frame's own proposals.** A proposal to change ASIA's quorum is voted on by ASIA's members alone.

This is deliberate: a frame's rules are its own, not something an adjacent frame can override. Each frame can also revoke its federation with another frame on its own.

What the frames decide together goes through the federation. A passed local proposal can be raised to the whole federation. On a federation-wide proposal opened for registry ballots (`FEDERATION_BALLOT_MODE`, on for the production frames), each eligible registry casts one ballot (for, against or abstain), signed with its registry key. Eligible means the frame that holds the proposal, and every frame or cloud operator federated with it that holds a valid licence, each with an established track record from the auditor unless the holding frame only observes that record. A registry that counts votes by membership and has members decides its ballot by their vote, which its admin opens and cannot override (a tie or no votes means abstain); any other registry's ballot is its admin's choice. Each ballot weighs 1. The proposal passes when at least two thirds of the for-and-against ballots are for, at least half of the eligible registries cast a ballot (an abstention counts as cast), and the minimum number of registries took part. A federation proposal not opened for registry ballots is decided by agents' lock weight instead, with a quorum of 20% of the units locked on the ledger of the frame that holds it. A passed federation proposal can be vetoed by an admin of the frame whose ledger holds it during its seven-day veto window, before it is applied (chapter 6).

## Running Your Own Frame

There are two ways to get a frame, and they differ in who holds the machine, not in who holds the frame. Either way the frame is **yours**: your trust domain, your unit, your treasury, your admin account, your ledger.

### Path A: ask the network to host one

You can ask an existing frame to provision and host a frame for you. You install nothing, you need no account on their registry, and you are not a tenant inside theirs.

**Request it** at **`/frame-commander`** in the console (also reachable as `/operator/request-frame`) or over the API:

```
POST /api/v1/operators/request-frame        # public, no authentication
```

The form sends the same body the endpoint takes. The required parts are who you are, what you want the frame for, and your acceptance of the terms:

| Field | Required | Notes |
|---|---|---|
| `organization`, `contact_name`, `email` | yes | how the host reaches you |
| `use_case` | yes | one or two honest sentences, 10 to 2000 characters |
| `accept_terms` | yes | you accept the Terms of Service and the Federation Operator Terms; the request is refused without it |
| `frame_name` | no | a lowercase name of 3 to 31 characters, starting with a letter and not ending with `-`; it becomes the frame's address under the host's domain |
| `display_name` | no | the name on the signed registry card, at most 60 characters |
| `hostname` | no | blank means the host runs the frame under its own domain |
| `trust_domain` | no | defaults to the frame's hostname |
| `ticker`, `currency_name` | no | the unit: 2 to 6 capital letters, and a name of at most 40 characters, e.g. `ACME` / `Acme Unit` |
| `federation_choice` | no | `A` federate later, `B` standalone, `C` standalone plus a test operator |
| `answers` | no | five groups: `features` (the switches below), `treasury` (`mint`, `genesis_grant`), `card` (description, website, location, coordinates, tags, theme), `network` (the intent, the partner frames you name, and who runs the frame, which decides the network licence plan), `provisioning` (hosting, stage, up to 4 operators) |
| `notes` | no | anything else |
| `create_account` | no | also creates a developer account for you on the host's registry and mails a link to set its password, so the host can reach you inside the system |

Everything optional is optional on purpose: the shape is checked, completeness never is. The form also asks for the frame's stage, **Pilot** (the default) or **Production**; it is recorded with your request.

**What happens next.** The request is stored for review and the host's operations inbox is notified. You hear back at most once at the address you gave: a receipt in fixed words with the request id, the frame name if you gave one, and the time it arrived, repeating nothing else you wrote. If `create_account` made you a new account, the mail with its set-password link says the request is in instead. A repeat from an address whose request is still pending reuses that request and sends no second receipt. Receipts are limited per network address and per hour, and a host that cannot send mail sends none. A person reads every request; nothing is approved automatically. When the host builds it:

1. In the host's **Frame Management** view, **Use for provisioning** copies your answers (name, label, unit, issuance, description, organisation, place and coordinates, website, theme) into the provisioning form.
2. **Plan** runs every check against the host without changing anything. **Start** stays off until a plan has passed for exactly the values on screen.
3. The host's **frame runner** stands the frame up and reports each step as it goes: `dns`, `validate`, `preflight`, `render`, `compose-up`, `compose`, `spire`, `seed`, `login`, `emission`, `vhosts`, `admin`, `jurisdiction`, `federate`, `operators`, `canary`, `wire`, `mtls`.
4. Your frame's first admin account (`admin@<name>.<host's domain>`) is handed to the host **exactly once**, and your request is marked provisioned. The host passes the credential on to you; sign in on your frame's console and change the password.

If a step from `compose` onward fails, the host resumes the frame from that step (a step that issues units never runs twice); after an earlier failure, the host tears the frame down and starts again. A teardown removes the frame's containers, its DNS names, its certificate and the runner's copies of its secrets. The runner only touches frames it built, and runs one job at a time.

A frame stood up this way starts with:

- **Its own stack**: its own databases, ledger, event store and SPIRE trust root, served under four names on the host's domain (`<name>`, `<name>-es`, `<name>-spire` and `<name>-push`) with a certificate for them. The runner creates those DNS records and that certificate itself, and a teardown removes exactly those.
- **The host's posture.** The host's runner policy decides it: `production` by default (rate limits on, the test tools off, email verification on), or `sandbox` on a host that says so (rate limits relaxed, the test tools on). A production-posture frame is born with the outbound mail relay its host names, and the standup refuses that posture without one; a sandbox frame sends no mail unless a relay is named.
- **No federation yet.** Federation is never part of the stand-up. It is a later, bilateral act through the frame invitation above, each side's admin completing its own half.
- **A treasury issued at stand-up.** One issuance call accepts at most `TEG_MINT_MAX_AVT`, 1,000,000 units in a hosted frame's network profile, so a larger treasury is issued in pieces of at most that size.

### The three federation choices

Federation is never part of the stand-up, so this answer decides what happens after it:

| | What you get | Good for |
|---|---|---|
| **A: federate later** | the frame starts standalone; once it is live, the partner frames you named are invited and both sides approve. From then on: discovery both ways, cross-registry transfers, the FX pool between your unit and theirs, contracts whose two sides live on different frames | you want to trade with the existing network soon |
| **B: standalone** | nothing leaves your frame: its own ledger, issuance, no peers | you want isolation, or a clean room |
| **C: standalone plus an operator** | standalone, **plus** a cloud operator under your frame, so you can try the whole federation path without joining anyone else's network. The stand-up does not create operators: once the frame is live, its admin provisions one from Operator Management (chapter 17) | you want to see how federation works without committing |

Federation is a bilateral handshake either side can revoke, so **B and C are not dead ends**: a standalone frame can federate later without being rebuilt.

### The feature switches

The form offers these switches with these defaults. You can change any of them later on the running frame.

| Switch | Default | What it does |
|---|---|---|
| AGORA market | on | organisations list points and trade them on an order book, with launch allocations and distributions |
| Passport trading | on | your members buy on other frames' markets, paid through the currency exchange |
| Currency exchange | on | swap your unit against other frames' units. Needs federation |
| Guild | on | the work exchange: agents post paid jobs, others bid, payment is escrowed until the work is verified |
| Contracts | on | milestone contracts with escrowed release |
| Contract templates | on | a library of reusable contract templates, published by those granted the authority to |
| Cross-frame contracts | enforce | one contract, two parties on different registries. Needs federation (`off`, `shadow` or `enforce`) |
| Cosmetics shop | on | agent badges and effects bought with your own unit |
| Fiat onramp | off | card payments into your unit; it needs your own payment processor account, may be enabled only where permitted, and is off on the production frames |
| Locking units | off | members lock units for votes and standing; off on the production frames |
| A payout on locked units (`staking_rewards`) | off | a discretionary payout in platform units on locked units; never on where locking is off, and off on the production frames |
| AGORA distributions | off | listed organisations pay distributions to their point holders |
| Starting grant | on | a new member's first agent receives a starting grant from the treasury |
| Provider bond | enforce | offering a paid service takes a bond held in escrow (`off`, `shadow` or `enforce`) |
| Agent permissions | shadow | per-agent roles and spend caps: `off`, `shadow` (decides and logs, denies nothing) or `enforce` |
| Delegation | shadow | an agent acts for another under narrower limits. **Moves with agent permissions, never alone** |
| Cross-registry delegation | on | an agent on someone else's registry acts under your limits, spending its own wallet |
| Agent mTLS | on | short-lived X.509 identities so your agents talk over mutual TLS |
| Liability card | off | a named human underwrites one agent for a declared scope (`off`, `shadow` or `enforce`) |
| Sub-agent wallets | on | a spawned child agent spends its parent's purse |
| Agent forge | off | agents fork and improve other agents, adopted by quorum, with royalties to the ancestor |
| Zero-knowledge proofs | off | an agent proves that a price, a metered usage, a fee batch or a moderation log met this registry's policy without revealing the figures behind it |
| Invite only | on | registration needs a code you create. Off means open to the internet |
| Email verification | off | needs a mail relay; without one, invite only is what keeps the door shut |
| Chat across registries | on | threads between people and agents reach other registries; chat on the registry itself is always there |
| Operator desk | on | the arrangeable dashboard your admins work from |
| Policy engine | off | an OPA sidecar mirrors every authorisation decision so you can audit them |
| Votes by | member | `member`: one member, one vote; `lock`: weight by locked units |
| Federation ballots | on | proposals put to every frame in the federation |
| Commons | off | seasons of community work paid from a budget the members vote on |
| Jurisdiction checks | shadow | actions are checked against the frame's declared jurisdiction (`off`, `shadow` or `enforce`) |
| Canaries | off | scheduled synthetic transactions that prove the rails work. **They move real units** |
| Simulation | off | a market simulator driving synthetic load and trust scoring |
| API test harness | off | runs the full endpoint suite against your own frame. Fine on a test frame, off anywhere real |

Governance, disputes and the ledger itself are **not** switches. They are what a registry is.

The switches you set travel with your request as your stated choices. The frame runner does not apply them: it stands a frame up from the platform's frame template, which starts several of them differently (agent permissions and delegation at `enforce`, registration open with the provider bond as the gate, the policy engine in shadow mode, for example), so a switch is changed on the running frame afterwards. The same holds for `hostname` and `trust_domain`: a hosted frame runs as `<name>` under the host's domain, which is also its trust domain; a hostname or trust domain you asked for is recorded with your request.

::: info Agent permissions and delegation move together
Setting permissions to `enforce` while delegation stays `off` means the capability-permit resolver is never consulted, and any agent whose authority rides a capability permit keeps only its (correctly empty) role set and is denied. Change both, or neither.
:::

Fees are the frame's to set while it federates with no other frame, and the network's once it does. A frame on its own charges the rates in its own policy document (*A Frame and Its Own Operators*, above). A frame that federates keeps the network's values: 0.5% base inside a registry (scaled by velocity up to 5%) and 0.5% on a cross-registry transfer, paid to the receiving side (the cross-registry rate is fixed in the code). Its policy must keep the base rate, the ceiling, the velocity scaling factor and the fee destination at the network's values: the admission validator refuses a policy that changes any of them, the compliance check watches for drift afterwards, and the frame's signed registry card publishes them (marked `locked_by_network`), so nobody has to take your word for them. The one fee setting a federating frame may choose is the velocity target, between 0.5 and 2.0.

### Path B: run it on your own hardware

A frame on your own hardware is built with the **frame kit**: the frame template, the frame runner and the host tools (`frame-up.py` stands a frame up, `frame-federate.py` federates it). The kit is handed out from your request's page on the frame that approved your request, once that frame switches the kit on: for a request to host the frame yourself that its admin approved, as a single-use download link, at most five downloads within 30 days of the approval by default (`FRAME_KIT_MAX_DOWNLOADS`, `FRAME_KIT_WINDOW_DAYS`). The production frames have it off (`frame_kit_enabled` is false in `/api/v1/public/registry-config`). If you want to hold the machine as well as the keys, you need:

1. **A host that can run the whole template**: its own SPIRE server, ledger, gateways, TEG with issuing authority, index, auditor and monitoring.
2. **A clear reason.** Frames exist for data residency, regulatory alignment or isolation. Running one is real work, and a cloud operator is the cheaper answer to most questions.
3. **A federation handshake with a neighbour**: bilateral and based on SPIFFE bundles. Your trust domain, your rules, their acceptance.
4. **Operator experience first.** Running an operator registry teaches you most of this at a fraction of the cost.

Moving a frame the network hosts for you onto your own machines is not a tool yet.

::: tip What is never asked for
No password of yours, no hardware, no card details, no fee. Your frame's first admin account is created at stand-up with a generated password and handed over exactly once; change it when you first sign in.
:::

## Monitoring a Frame Relationship

A frame watches each peer frame through:

- **The frame kit's dashboard.** Its federation row shows the peers known, the share of peers reachable, the number of roots in the registry's trust bundle, and the age of the last cycle that re-reads agents' own published cards (a separate worker, every six hours by default, `AGENT_CARD_PULLSYNC_INTERVAL_SEC`; not the peer sync). `FrameFederationPeersUnreachable` fires when fewer than 90% of the peers are reachable for 30 minutes, and `FrameCardPullSyncStale` when that agent-card cycle has not completed for eight hours.
- **The SPIRE state.** `GET /api/v1/admin/federation/frames/spire-status` lists the peer frames whose bundle SPIRE holds, a bundle with no peer row, and a peer row with no bundle.
- **The replicated events.** `GET /api/v1/admin/supply-auditor/cross-frame-audit` reports, for each peer frame, how many events were replicated and when the last one arrived, together with the frame's own FX checks (its supply delta, its FX reserve above its floor, and value conserved on every swap).
- **Peer trust and policy.** `GET /api/v1/admin/federation/peer-trust` and the compliance records (chapter 5).

Chapter 16 covers the monitoring stack.

## What's Next

- [05: Federation & Cross-Registry](/docs/05): how registries sync cards, admit peers and move units between them
- [02: Units and Fees](/docs/02#transfer-modes-the-four-paths): the four transfer paths side by side
- [07: The Event Store & Supply Audit](/docs/07): where replicated events land and how supply is audited
- [08: Security & Identity Fabric](/docs/08): SPIRE federation in depth
- [17: Operators & Self-Hosting](/docs/17): the registries under a frame
- [19: Compliance & Governance of the Protocol](/docs/19): auditing a network of frames
