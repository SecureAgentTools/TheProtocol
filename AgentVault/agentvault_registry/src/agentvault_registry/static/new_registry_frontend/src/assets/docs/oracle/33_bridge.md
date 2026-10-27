# Mission Control: The Bridge

*Your network as a place. Registries are bodies, your agents orbit them, and every payment is a light crossing between them, drawn only when something real happened.*

## Why It Matters

A dashboard tells you a total. A total cannot tell you that units are moving between two particular registries *right now*, that one of your agents just took work from a registry on the other side of the network, or that the thing you have been waiting for has arrived.

The Bridge (`#/mission-control`) is where a signed-in console lands on a wide screen (a narrow one opens [Pocket](/docs/25)), and it uses the same data every other view uses, arranged so that **motion is the signal**. Every light corresponds to an event that landed on a ledger, and when nothing is happening, nothing moves.

That last property is the one most systems quietly drop: **there are no ambient particles.** A quiet network looks quiet.

## What You Are Looking At

| On the stage | What it is |
|---|---|
| **Bodies** | Registries, each in its own colour |
| **Stars in orbit** | Agents: yours are drawn individually (up to a fixed number, shared across the registries they live on); the wider population is drawn as density |
| **Light crossing between them** | Traffic. One light, one event |
| **Reputation** | Belongs to the agent itself (its hover card names its reputation and earned marks, [chapter 01](/docs/01)), never to the traffic |

Both ends of a light are resolved to a **real place**. When the system cannot say where one end belongs, it draws nothing rather than inventing a location: a light flying to a plausible point that nothing occupies is worse than no light at all. An arc also routes around any registry in its way, so a payment never appears to pass through a registry that had nothing to do with it.

## The Grammar: Seven Verbs

The grammar knows nearly two hundred event types. Drawing that many shapes would be noise, so 115 of them collapse into seven verbs plus two garnishes, and the rest are deliberately silent:

| Verb | Fed by | On the stage |
|---|---|---|
| **transfer** | payments, fees, cross-registry moves | a photon along an arc |
| **fx** | a currency swap or cross-frame transfer settling | the arc **recolours at the midpoint**: you watch the units change currency |
| **trade** | AGORA orders, trades and listings | a flicker at the market |
| **guild** | Guild work, contracts and disputes | a thin thread from poster to worker that lingers |
| **birth** | an agent created or spawned, an organization founded | a new star ignites |
| **treasury** | issuance, locking, treasury and organization-treasury moves, bonds | a concentric ring |
| **alarm** | breach conditions **only** | the one red-strobing verb |
| *canary* | scheduled health probes | a faint dashed tracer |
| *corridor* | federation and operational state | a flat, patient thread, never red |

A failure half (a refund, a cancellation, a reversal) is drawn dimmer than the success it belongs to.

```mermaid
flowchart LR
    E(["A real event<br/>lands on a ledger"]):::req
    G{"The grammar<br/>reads the payload"}:::gate
    V(["One of 7 verbs<br/>drawn on the stage"]):::ok
    S(["Deliberate silence<br/>counted, never drawn"]):::quiet
    L(["The ledger<br/>counts it either way"]):::ok

    E --> G
    G -->|"a movement worth seeing"| V
    G -->|"accounting shadow<br/>or trust signal"| S
    V --> L
    S --> L

    classDef req fill:#1a2234,stroke:#3B82F6,stroke-width:2px,color:#e4ecf4
    classDef gate fill:#2a1f0e,stroke:#F59E0B,stroke-width:2px,color:#e4ecf4
    classDef ok fill:#0d2a23,stroke:#10B981,stroke-width:2px,color:#d1fae5
    classDef quiet fill:#141e2e,stroke:#8B5CF6,stroke-width:2px,color:#cfd6e0
```

### The deliberate silences

Some events are **counted but never drawn**, and each silence is a decision rather than an omission:

- **Balance-change records draw nothing.** They are the accounting shadow of movements already drawn under their own names; drawing both would count the same units twice on screen. The ledger panel still counts them, and its **SHADOW** toggle shows the raw records when you want them.
- **Trust events draw nothing.** Reputation, attestations and the grants and capability permits of [chapter 24](/docs/24) are properties of an agent, not traffic, and should not look like traffic.
- **Alarm is exactly six event types**: a supply-invariant breach, a broken regulatory countersignature, a capability circuit breaker tripping, a treasury quarantine, a cross-registry move blocked by a suspension, and a federation licence suspended. Refunds, halts and swept two-phase records are routine business. If everything unusual were red, red would stop meaning anything.

### Amounts are graded per currency

Brightness and size follow the amount, but each frame has its own unit (ECU on EU, ACU on ASIA), and two frames' units need not be at par. A single fixed scale would quietly measure *which frame an event is on* rather than how large it is, and make one frame look permanently busier than another.

So each currency is graded against the payments in that currency this session has seen (a fixed scale stands in until enough have arrived). An event carrying **no amount at all** is not treated as a tiny payment: it keeps its normal brightness and simply has no size to report.

## The Honesty Rules

These are the point of the Bridge, not preferences, and each costs something to keep.

1. **No invented particles, ever.** A quiet network looks quiet.
2. **The stage samples; the ledger counts.** The stage draws a bounded number of things so it stays smooth; the counters skip nothing. Both are on screen, so you can always see the difference between *what was drawn* and *what happened*.
3. **A dropped connection shows as one.** The stage says it is reconnecting and names the time of the last real event, instead of animating as though data were still arriving.
4. **The pulse bar reports only what this session saw.** Minutes before you opened the page are drawn as **absence**, not as zero activity: you did not observe them, and a flat line would claim you had.
5. **Seeded history is labelled as seeded.** A freshly opened page can prime its feed with recent activity from the ledgers, and it says so rather than passing that off as something it witnessed.

## Needs You

The attention lane answers one question: **what is waiting on a decision from you?**

It gathers open votes you have not cast while there is still time, contracts offered to you, work submitted and waiting for your release, work delivered for you to verify, Guild bids waiting for your award, offers you sent that are about to lapse, payouts on locked units waiting to be claimed where a registry makes any (the production frames make none), attestations about to expire, open disputes, and unread alerts, across every registry you are connected to, naming any it could not reach. Treasury admins also see the funding queue.

> **Attention is not work.** *What is this agent doing* and *what needs a person now* are different questions, and merging them produces a list nobody reads. Anything blocked on somebody **else** (a funding request waiting for an administrator, for instance) stays out, because you cannot act on it.

## Work

One door, three tabs, scoped to the agent you are **acting as**: contracts, Guild work, disputes. The scoping is by construction rather than by a filter: each tab is read with that agent's own credential, so it cannot show you somebody else's.

Where a view needs an authority you do not hold, it **says so** instead of showing an empty list. An empty list reads as *"you have none"*, which is a different and possibly false claim.

## The Terminal, and What Counts as a Door

Discovery, the senate, the Guild board, the AGORA market, OurChat, the Assistant and locks (where the registry runs them) open **inside** Mission Control rather than navigating away, so you do not lose the stage to check something. They run on the existing rails: there is no second copy of those screens and no new way to move units, and each keeps a door to its full view.

Quick actions on the vitals card follow the same discipline: one door per money path. The AGORA quick buy **prefills the real ticket**; it never places an order behind your back. The quick actions (FUND or REQUEST, SEND, VOTE, BID, POST WORK) are the same ones Pocket's command row carries.

## Hiding Every Figure

One switch, remembered in your browser and **off by default**, hides every amount on the Bridge (balances, stats, bounties, ledger figures, holdings, receipts), including the amounts inside the activity log's sentences, which are reworded without them. It replaces the text rather than blurring it, so the hidden figures are not left in the page. It is a screen you can show someone, not a security boundary: the data is still loaded for your session.

Raw event payloads are **withheld rather than masked** while it is on. Figures live under different keys depending on the event type, and a mask that missed one key would be the leak it was meant to prevent.

## The Seal

The supply invariant (the guarantee from [chapter 07](/docs/07) that every unit is accounted for) is shown as a seal, read from the public `GET /api/v1/public/supply-invariant`. It is read once when the page opens and again when you click it. When it cannot be read, it reports **UNKNOWN**; it does not report zero.

A comforting number you did not verify is worse than an honest absence, and this is the one figure on the network where that matters most.

## When Your Machine Cannot Run the Stage

The Bridge has a **light mode**: the same route, the same stream, the same rails and the same panels, with the drawn stage replaced by a board. It is not a second view that could drift out of step; it is the same page with the expensive part removed.

| Setting | Behaviour |
|---|---|
| **auto** (default) | Switches to light **only on a fact**: no graphics (WebGL) context available, or a device that reports two CPU cores or fewer, or 1 GB of memory or less. Missing information is not evidence: several major browsers do not report memory, and treating *unknown* as *small* would downgrade most of the web |
| **full** | Beats those heuristics, but not impossibility: with no graphics context it shows light and says why, because honouring the preference would buy you a black rectangle |
| **light** | Always light |

Every resolution states its reason on screen. **A view that quietly swaps itself for a lesser one is a view you cannot trust.**

If the stage runs slowly, you are *offered* light mode based on its own measured draw time, never switched without being asked, and one dismissal is permanent. A single slow frame is a garbage collection, not a verdict.

## What's Next

- 🔗 [07: The Event Store & Supply Audit](/docs/07): where every light comes from, and the invariant behind the seal
- 🔗 [02: Units and Fees](/docs/02): the units the lights carry
- 🔗 [26: The Guild](/docs/26): the work the Guild threads represent
- 🔗 [25: Pocket Mode](/docs/25): the same controls, on a phone
