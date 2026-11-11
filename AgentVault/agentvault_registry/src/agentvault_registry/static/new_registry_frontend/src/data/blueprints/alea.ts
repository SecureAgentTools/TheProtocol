import type { Blueprint } from './types'
import { liveRatioOf } from './types'

// ALEA: certified randomness (V0660 (f)). The most DESIGNED-heavy chamber in the set, on purpose. A
// certified draw needs real quantum hardware and a certification protocol, and neither is ours. What runs
// today is the discipline AROUND a draw: committed before use, published where it cannot be edited,
// metered, paid once, and verifiable offline by whoever consumes it. The chamber says which is which.

const primitives = [
  { step: 'A draw is committed before anyone uses it', primitive: 'The commitment lands on the ledger ahead of the reveal', railStatus: 'LIVE' as const },
  { step: 'The commitment cannot be edited afterwards', primitive: 'Append-only ledger, replayable, forensically searchable', railStatus: 'LIVE' as const, href: 'https://auditor.theprotocol.cloud' },
  { step: 'Who may draw, and how often', primitive: 'IRONKEY caps and allowlists on the beacon’s consumers', railStatus: 'LIVE' as const, href: '/docs/24' },
  { step: 'A consumer checks the chain without asking us', primitive: 'Offline verifier over the signed chain and its manifest', railStatus: 'LIVE' as const },
  { step: 'Paid per draw, exactly once', primitive: 'Idempotency keys, two-layer dedup (cache + ledger unique)', railStatus: 'LIVE' as const },
  { step: 'Shots reported match a committed meter log', primitive: 'accurateResourceUsagePolicy/v2.0.0, a published circuit with its verification key', railStatus: 'LIVE' as const, href: '/docs/10' },
  { step: 'A named operator behind the beacon', primitive: 'Cockpit Card mandate, scope-clamped, re-derived per request', railStatus: 'LIVE (gated)' as const, href: '/docs/30' },
  { step: 'The source states its own facts', primitive: 'Quantum workload card extension: device, limits, queue, each with its as_of', railStatus: 'LIVE (gated)' as const },
  { step: 'A disputed draw, ruled on', primitive: 'Four-phase dispute; the ruling drives the escrow split', railStatus: 'LIVE' as const },
  { step: 'The entropy drawn on real quantum hardware', primitive: 'A provider’s own device, booked and attested like any other service', railStatus: 'DESIGNED' as const },
  { step: 'The certification test over the raw outcomes', primitive: 'A published protocol’s statistical test, run by the certifier', railStatus: 'DESIGNED' as const },
]

export const alea: Blueprint = {
  id: 'alea',
  tier: 2,
  frontier: true,
  rank: 32,
  industry: 'Randomness Beacons and Public Draws',
  systemName: 'ALEA',
  promise: 'A draw is committed before it is used, published where nobody can edit it, and checkable offline by everyone who relied on it.',
  cases: [
    { role: 'Lottery or public draw operator', line: 'Every draw committed before use and replayable afterwards by anyone.' },
    { role: 'Audit or sampling authority', line: 'Select a sample nobody can be accused of choosing.' },
    { role: 'Protocol or consortium designer', line: 'A beacon your members verify offline instead of trusting.' },
    { role: 'Randomness service provider', line: 'Sell draws with evidence rather than with assurances.' },
  ],
  problem:
    'A public draw is only as good as the belief that nobody saw it coming or changed it afterwards, and that belief usually rests on a notary and a process document. The people who most need the guarantee, the ones who lost, have no way to check it. Meanwhile a beacon that claims a quantum source gives no way to tell a quantum source from a software one.',
  system: [
    'ALEA is a sampling beacon for a regional audit authority: one source on its own frame, the authority as a consumer, and eleven municipalities relying on each draw. Every draw is committed to the ledger before any consumer reads it, so the order is a matter of record rather than of testimony. The reveal follows, carrying the draw, the device that produced it and the shots behind it, and the authority selects its sample from a value the record already held before anyone read it.',
    'Mira Castellan runs the beacon for the authority. She underwrites it once with a mandate for the year, and the beacon agent holds no wallet of its own. Consumers are allowlisted and capped: a municipality may read the daily draw and nothing else, and a consumer that asks twice is answered from the record rather than charged twice. Each draw is paid for once, under a key made from the draw and the consumer.',
    'Two things in this chamber are specified and not built, and that is the honest centre of it. The entropy itself comes from a provider’s device, and a certification protocol has to run its own statistical test over the raw outcomes before the word certified means anything. Neither is ours and neither is live, so both are marked DESIGNED. What is live is everything around them: the commitment before use, the ledger that cannot be edited, the metering, the single payment, and the offline check a consumer runs without asking anyone.',
  ],
  cast: [
    { agent: 'beacon-agent', role: 'Commits and publishes each draw', ceiling: 'The authority’s sub-agent, with no wallet of its own. Publishes what the source signed and nothing it composed itself.' },
    { agent: 'source-GEN-1', role: 'Produces the draw and signs it', ceiling: 'Attests its own draws and meters its own shots. Cannot publish, charge or edit a commitment.' },
    { agent: 'consumer-desk', role: 'Reads the daily draw for a municipality', ceiling: 'Allowlisted and capped: the daily draw and nothing else. A repeat is answered from the record.' },
    { agent: 'decode-assistant', role: 'Decodes syndromes for a hardware source, in batches', ceiling: 'A classical service beside the device. Produces no randomness and signs no draw.' },
  ],
  loom: {
    nodes: [
      { id: 'operator', label: 'Mira Castellan', sub: 'the mandate, one tap', kind: 'human', x: 118, y: 110 },
      { id: 'beacon', label: 'beacon-agent', sub: 'publishes each draw', kind: 'agent', x: 118, y: 330 },
      { id: 'gate', label: 'Draw gate', sub: 'who, how often', kind: 'gate', x: 336, y: 220 },
      { id: 'escrow', label: 'Draw escrow', sub: 'paid per draw', kind: 'teg', x: 560, y: 110 },
      { id: 'source', label: 'source-GEN-1', sub: 'signs each draw', kind: 'agent', x: 560, y: 330 },
      { id: 'commit', label: 'Commit log', sub: 'before any use', kind: 'ledger', x: 336, y: 450 },
      { id: 'ledger', label: 'Beacon ledger', sub: 'draws and proofs', kind: 'ledger', x: 764, y: 110 },
      { id: 'consumer', label: 'consumer-desk', sub: 'verifies offline', kind: 'agent', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-mandate', from: 'operator', to: 'gate', label: 'scope, signed' },
      { id: 'e-ask', from: 'beacon', to: 'gate', label: 'today’s draw', labelT: 0.3 },
      { id: 'e-pay', from: 'gate', to: 'escrow', label: 'one draw, once' },
      { id: 'e-commit', from: 'gate', to: 'commit', label: 'committed first' },
      { id: 'e-draw', from: 'source', to: 'escrow', label: 'draw, signed', labelT: 0.62 },
      { id: 'e-emit', from: 'escrow', to: 'ledger' },
      { id: 'e-verify', from: 'consumer', to: 'ledger', label: 'checked offline' },
      { id: 'a-late', from: 'beacon', to: 'gate', attackOnly: true, curve: 70, labelT: 0.5, label: 'late commit' },
      { id: 'a-twice', from: 'source', to: 'escrow', attackOnly: true, curve: 90, labelT: 0.3, label: 'same draw, again' },
    ],
    script: [
      { edge: 'e-mandate', state: 'active', dwellMs: 1500, caption: 'Ms Castellan underwrites the beacon once: its consumers, their caps, a year.' },
      { edge: 'e-ask', state: 'active', dwellMs: 1400, caption: 'The beacon agent asks the source for today’s draw.' },
      { edge: 'e-commit', state: 'active', dwellMs: 1500, caption: 'The commitment lands on the ledger before any consumer reads the draw.' },
      { edge: 'e-pay', state: 'active', dwellMs: 1300, caption: 'The draw is paid for once, under a key made from the draw and the consumer.' },
      { edge: 'e-draw', state: 'active', dwellMs: 1500, caption: 'The source signs the draw: the device, the shots, the outcome.' },
      { edge: 'e-emit', state: 'settled', dwellMs: 1400, caption: 'The reveal follows the commitment, in that order, on a ledger nobody can edit.' },
      { edge: 'e-verify', state: 'active', dwellMs: 1500, caption: 'A municipality checks the chain and its manifest offline, without asking the authority.' },
    ],
  },
  attacks: [
    {
      title: 'The draw committed after it was seen',
      attack: 'A beacon operator reads today’s draw, dislikes the sample it selects, and tries to commit a different one in its place.',
      mechanism: 'The commitment is a ledger entry and the ledger is append-only, hash-linked and replayable. The original commitment stays where it is, and a second one is a second entry with its own position in the chain. A consumer’s offline check reads the order, so the substitution is visible to everyone who relied on it.',
      rail: 'S14',
      consequence: 'The first commitment stands in the record. The attempt is evidence, not a replacement.',
      script: [
        { edge: 'a-late', state: 'denied', dwellMs: 1900, stopAt: 0.82, flashNode: 'gate', caption: 'S14. History cannot be edited, so a late commitment is an extra entry and not a swap.' },
      ],
    },
    {
      title: 'The draw sold twice',
      attack: 'A source re-sends a draw it has already been paid for, and a consumer that asks twice is billed twice.',
      mechanism: 'Each draw is paid under a key made from the draw and the consumer, and the key is enforced in the cache and again by a unique constraint on the ledger. A repeat is answered from the record, and a retried payment replays under the same key and moves nothing.',
      rail: 'S15',
      consequence: 'One draw, one payment, whatever the retries. The duplicate is visible, not profitable.',
      script: [
        { edge: 'a-twice', state: 'denied', dwellMs: 1900, stopAt: 0.74, flashNode: 'escrow', caption: 'S15. This draw’s key was already paid. A retry or a replay moves the money exactly once.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [{ label: 'Risk Assessment Framework', href: '/compliance/doc/risk-assessment-framework' }],
  rails: ['S01', 'S02', 'S05', 'S14', 'S15', 'S16', 'S19'],
  standup: {
    infra: 'An authority frame, with the source on a frame of its own, federated, booted from the free licence and pre-built images. Quantum workloads are one frame switch, off by default.',
    agents: 'A beacon agent, a consumer desk per member, one agent per source. The entropy is the source’s own and the certification is its certifier’s.',
    integration: 'The sampling procedure, the publication channel and the municipalities’ own systems. This is where the real time goes, and it stays the authority’s.',
  },
  nonClaims: [
    'ALEA carries identity, authority, money and evidence around a draw. It does not generate randomness, certify it, or judge whether a sampling procedure is sound.',
    'Nothing in this chamber is certified randomness today. The entropy from a real device and the certification protocol’s statistical test are both specified and marked DESIGNED, and a simulator’s output is not certified randomness under any protocol.',
    'A commitment shows that a value existed before it was used. It does not show where the value came from; that is what the source’s own attestation and a certifier’s test are for.',
    'The decoding assistant is a classical service beside a device, running in batches. A live error-correction loop sits next to the hardware in microseconds and is not a network service.',
  ],
  mermaid: `flowchart LR
  M(["Mira Castellan<br/>mandate"]) -->|"scope"| G{"draw gate<br/>who, how often"}
  B["beacon-agent"] -->|"today’s draw"| G
  G -->|"committed first"| K[("commit log")]
  G -->|"one draw, once"| E["draw escrow"]
  S["source-GEN-1"] -->|"draw, signed"| E
  E --> L[("beacon ledger<br/>draws and proofs")]
  C["consumer-desk"] -->|"checked offline"| L`,
  legacy: [
    { system: 'Existing draw and notary procedures', connect: 'The notary’s record becomes a commitment anyone can replay. The procedure stays the authority’s.' },
    { system: 'Publication channels', connect: 'They publish the reveal as they do today, with the commitment already on the ledger.' },
    { system: 'Members’ own systems', connect: 'A member reads the draw under its cap and verifies the chain offline.' },
    { system: 'Hardware random number generators', connect: 'A source joins as an agent with its own card. Its device and its certification stay its own.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
