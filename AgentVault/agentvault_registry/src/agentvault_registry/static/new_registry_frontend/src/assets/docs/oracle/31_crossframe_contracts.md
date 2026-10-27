# Contracts That Cross Frames

*A contract lives where its escrow lives. What crosses the frame boundary is a signed copy of the facts and a rail for asking the owner to act. The copy is never the authority, and nobody has to hope it is current.*

## Why It Matters

Two agents on different registries want one agreement. The obvious design is to put a copy of the contract on both frames and keep them in step.

That design is wrong, for a reason worth stating plainly: **the escrow can only be in one place.** The units sit in one registry's treasury. If two frames both believed they could release them, you would not have built replication, you would have built a double payment waiting for a network partition. The contract system already applies the same rule one level down: a dispute ruling and a contract resolution cannot both drive the same escrow, so one of them is the settlement authority and the other defers (chapter 04). Crossing frames is the same rule, one level up.

So the contract does not travel. It has a **home**: the registry of the client, which holds the escrow. That registry is the only place a transition can happen.

What travels is a **replica**: a read-only, signed record of the contract's facts, kept on the provider's own registry, so the provider and its owner can see the agreement there without pretending to own it.

```
HOME (client's registry)                      PEER (provider's registry)
  contracts, escrow, authority       ──▶      contract_replicas  (read-only, signed)
  ▲                                                 │
  └────────── relayed command ─────────────────────┘
```

The replica table has no escrow reference and no fee or settlement columns. A replica cannot move money because there is nothing in it to move.

## What Makes a Copy Trustworthy

Two things, in this order.

**It is signed.** The home registry signs the contract's material facts (contract id, home, status, sequence number, both parties, currency, amount and title) with Ed25519, using the same key that signs its registry card, and sends their SHA-256 digest with the signature. No new key material and no new trust root: a peer already knows how to verify that signature. The list of released milestones travels beside these facts under a second signature over the facts plus the list, so a registry that does not know the list still verifies the facts.

The digest covers *material* facts only. If a presentation detail changes, the signature must not break. If the amount changes, it must.

Verification runs the cheap check first: the digest is recomputed from the payload and compared, then the signature is checked against the home registry's published keys (refetched once if the key has rotated). An envelope that does not verify is dropped and logged, never stored. A replica whose origin cannot be established is *worse* than no replica, because the interface would present it as fact. A replica only ever moves forward: an older envelope arriving late cannot replace a newer one.

**It is reconciled.** This is the part that matters, and it is where most designs quietly fail.

Cross-frame event fan-out is best-effort by design. That is a reasonable property for a cache and an unacceptable one for a legal object. So the provider's registry does not rely on delivery. Every 60 seconds it takes up to 100 of the replicas it holds, the ones checked longest ago first (a contract that has ended, completed, cancelled or expired, is no longer checked), and asks the home registry for each contract's current digest (`GET /api/v1/federation/contract-digest`). On a mismatch it takes home's signed envelope as the truth; if it cannot verify anything, it marks the replica **stale**, so the surface can say "I am not currently sure" instead of showing a figure it can no longer stand behind. A home it cannot reach is left alone and asked again next time.

> The event is the optimisation. The reconciler is the guarantee.

That sentence is the whole design. Events make replication fast; the reconciler makes it *true*. If every event were lost, every replica would still converge: more slowly, but correctly.

## Bootstrapping and Naming

**Push alone cannot bootstrap.** Each mirror event carries a fixed idempotency key, so re-sending an unchanged transition is correctly ignored by the event store. That means a registry that starts listening *after* a mirror was published never hears about that contract, and the reconciler cannot help, because it only repairs replicas it already holds.

So the provider's registry also **pulls**. Every fifth cycle (about every five minutes) it asks each active peer registry which cross-frame contracts are addressed to it (`GET /api/v1/federation/contracts-for-peer`) and adopts the signed envelopes it gets back. The caller's mTLS identity decides which rows come back; a name in the request is never trusted, and a caller the home cannot identify gets an empty list. The same pull is the recovery path if a replica table is ever lost.

**A peer has more than one name.** The field that names the counterparty's registry can hold a peer's name, its base URL or a SPIFFE ID, depending on where the contract came from. The resolver matches every form against the known-peers table before it returns a peer, prefers an active peer row over a deactivated one, and refuses to guess when a trust domain alone matches more than one active frame. This widens what the system can *recognise*, never what it will *trust*.

## Acting From the Other Side

The provider still needs to accept the offer and deliver its milestones. It does so on its own registry, with the ordinary contract routes (`POST /api/v1/contracts/v2/{cid}/accept`, `.../milestones/{seq}/submit`, `.../cancel`). Its registry sees that the contract is a replica and relays the action to the home (`POST /api/v1/federation/contract-command`), then refreshes the replica from the home's digest so the new state shows at once.

The provider's registry is a **courier, never a principal**. Its mTLS identity authenticates the channel; it does not authorise anything. The home checks that the relaying registry is the provider's own registry, and that the acting agent is the provider named on *this* contract. A trusted peer cannot act as an agent that is not its own, and it cannot act on a contract that is not homed there. The client lives on the home registry and acts there directly; none of the client's actions is ever relayed.

The relay accepts a closed set of actions, exactly the provider's own: `offer.accept`, `milestone.submit` and `contract.cancel`. Anything else is refused by construction (`400`), not by validation: a relay that accepts arbitrary actions is not a relay, it is a remote procedure call with its trust boundary drawn in the wrong place. The home applies an action with the same code as its local routes; for an acceptance it also runs the reputation bond and enforcement checks again against the provider's mirrored card.

Retries are safe: each relayed action carries an idempotency key that the home records in the contract's own event trail (the trail the digest is derived from), so a repeated relay answers `already_applied` instead of making a second transition. If the home cannot be reached, the provider's registry answers `502` and leaves its replica as it was; send the action again, and the home applies it at most once.

## How It Ships

One setting, three positions: `CONTRACTS_XFRAME_MODE` = `off`, `shadow` or `enforce`, set per registry, default `off`.

- **Off**: the worker idles, mirror events are ignored, and the federation routes for digests, the bootstrap pull and commands answer `404` (the courier route answers that this registry cannot carry actions). An offer to a provider on another registry is refused with `409` instead of being created, because it could never reach the provider, and a provider's action on a replica is refused with `409` because it cannot be carried home.
- **Shadow**: replication runs for real (mirroring, adoption, reconciliation), while a relayed *command* is authenticated, authorised, deduplicated, recorded in the contract's trail and explicitly **not applied** (the answer says `"applied": false` with the reason `shadow_mode`). Because an acceptance would not be applied, a registry in shadow also refuses to create a new offer to a provider on another registry (`409`). This is the position that exercises the rail against production traffic before it can change anything.
- **Enforce**: relayed commands are applied. A home also creates an offer for a provider on another registry only when the provider's registry says it can carry the provider's actions back (`GET /api/v1/federation/contract-courier`); otherwise it refuses with `409`, so no offer is ever stranded.

EU, ASIA and their four cloud operators run `enforce` (`GET /api/v1/public/env-catalog`, entry `cross_frame_contracts`). A frame someone else runs sets its own position.

Replication moves no money. A relayed command applies the home registry's own transition, and the money it moves (escrowing the client's total when the provider accepts, refunding the remainder on a cancellation) moves on the home registry's escrow rail, exactly as for a local action. When the client releases a milestone, the home pays it out of escrow to the client and, in the same call, sends it on with the client's own cross-registry transfer, so the provider is paid on its own registry in its own unit, less that transfer's fee (chapter 04). If that transfer fails with an answer that proves nothing moved, the units go back into escrow and the milestone waits for the client to release it again; any other failure (a timeout, a `5xx`, an answer that says its outcome is not known, an HTTP 200 with `"status": "failed"` that does not say that no funds moved) may have paid the provider all the same, so that release is held for an administrator instead and nothing is taken back into escrow (chapter 04 lists what counts as proof). Every one of these moves is an ordinary transfer, so the supply invariant holds on both frames.

## What's Next

- [Chapter 04: Contracts, A2A Payments & Disputes](/docs/04): the contract lifecycle, escrow and disputes
- [Chapter 05: Federation & Cross-Registry](/docs/05): the peer registries a contract can cross to
