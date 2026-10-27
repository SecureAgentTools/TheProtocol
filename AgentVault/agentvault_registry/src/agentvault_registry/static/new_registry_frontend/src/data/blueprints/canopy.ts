import type { Blueprint } from './types'
import { liveRatioOf } from './types'

// CANOPY: carbon removal and environmental attestation (frontier wave 2026-09-25). A buyer's offtake is
// escrowed up front, an accredited verifier's signature releases each quarter's tonnes, and every tonne is
// retired on a signed entry beside the attestation that proved it, where a second claim is plain to see.
// A frontier chamber: the sector is arriving now; the rails are the live ones.

const primitives = [
  { step: 'Every probe and every signer an identity', primitive: 'SPIFFE identity per probe gateway and agent, short-lived certificates', railStatus: 'LIVE' as const, href: '/docs/08' },
  { step: 'Readings, batches and retirements, signed', primitive: 'Signed attestations from identified parties, append-only', railStatus: 'LIVE' as const },
  { step: 'Offtake money held before the first tonne', primitive: 'Contract spine: escrow at award, quarterly milestones in strict order', railStatus: 'LIVE' as const, href: '/docs/04' },
  { step: 'A named person behind the offtake', primitive: 'Cockpit Card mandate, scope-clamped, re-derived per request', railStatus: 'LIVE (gated)' as const, href: '/docs/30' },
  { step: 'Three projects and a budget, as bounds', primitive: 'IRONKEY L4 capability caveats: counterparty allowlist, atomic budget debit', railStatus: 'LIVE' as const, href: '/docs/24' },
  { step: 'Each quarter paid once, whatever the retries', primitive: 'Idempotency keys, two-layer dedup (cache + ledger unique index)', railStatus: 'LIVE' as const },
  { step: 'Buyers on other frames, in other currencies', primitive: 'Cross-registry transfer, exactly-once; FX pools across sovereign frames', railStatus: 'LIVE' as const, href: '/docs/18' },
  { step: 'The co-op’s own treasury', primitive: 'Organizations: shared treasuries, member votes, distributions', railStatus: 'LIVE' as const, href: '/docs/20' },
  { step: 'A withdrawn verifier signs nothing more', primitive: 'Coordinated suspension: mTLS identity revoked in under 500ms, account suspended', railStatus: 'LIVE' as const },
  { step: 'A register anyone can replay', primitive: 'Immutable event ledger; conservation independently audited', railStatus: 'LIVE' as const, href: 'https://auditor.theprotocol.cloud' },
  { step: 'Each registry’s declared limits', primitive: 'Jurisdiction profile signed into the registry card', railStatus: 'SHADOW' as const, href: '/.well-known/registry-card.json' },
  { step: 'A sensor threshold proven, the series withheld', primitive: 'ZK attestation over a new circuit, not yet written', railStatus: 'DESIGNED' as const },
]

export const canopy: Blueprint = {
  id: 'canopy',
  tier: 2,
  frontier: true,
  rank: 26,
  industry: 'Carbon Removal and Environmental Attestation',
  systemName: 'CANOPY',
  promise: 'Removal paid from escrow on an accredited verifier’s signature, each quarter released once, and every retirement signed where a second claim on the same tonnes is plain to see.',
  cases: [
    { role: 'Removal project developer', line: 'Offtake money held before the first tonne and released on the verifier’s signature.' },
    { role: 'Accredited verifier', line: 'One signed attestation per batch, and the tranche it unlocks is paid exactly once.' },
    { role: 'Corporate buyer', line: 'Every tonne you retire cites its attestation, on a record your auditor can replay.' },
    { role: 'Registry operator', line: 'A sovereign frame for your country’s projects, federated with the buyers’ frames.' },
  ],
  problem:
    'Carbon removal is bought years before it is delivered and verified months after it happens. Between the kiln and the claim, a tonne passes through a sensor network, a verification report, a registry entry, a purchase order and a sustainability report, each kept in a different system, and the joins between them are spreadsheets. The same tonne can be sold twice, a failed batch can be quietly re-run, and a buyer’s claim rests on a reconciliation somebody performs once a year.',
  system: [
    'CANOPY is a carbon removal network in which each project’s country runs its own registry frame: a cooperative running 38 biochar kilns in the Ember Hollow valley, 164 reforestation plots in the northern uplands and a mineralisation plant on a basalt coast, each checked by independent verifiers and sold to buyers who run frames of their own. At 07:40 on a Tuesday in October, verifier-07 signs Ember Hollow’s third-quarter batch: 1,240 tonnes of removal, drawn from readings that every kiln’s probes signed as they were taken. The buyer’s offtake, 4,800 tonnes for the year at 18 units a tonne, has sat in escrow since January, and the signature releases 22,320 units to the cooperative’s treasury the same morning. Every unit that leaves the escrow arrives in the treasury, and an independent auditor checks continuously that none were created on the way.',
    'A tonne is claimed in the open. When the buyer’s claims desk retires those 1,240 tonnes, it signs the retirement under its own identity, citing verifier-07’s attestation and the carbon registry’s serial numbers, and the entry sits beside the attestation on a ledger that only appends. A second claim on the same batch cites the same attestation, so the buyer, the registry and any auditor see both at once instead of months later in a spreadsheet reconciliation. In July the second quarter’s first attestation failed on a nine-day gap in one kiln’s logs; the failure stayed where it was signed, the corrected batch without that kiln’s tonnes sits beside it, and anyone reading the quarter sees both.',
    'The buyer is a freight line on another continent, on its own frame and in its own currency. Its offtake desk is the treasury’s own sub-agent: it holds no wallet, and every offtake it signs is checked against the mandate Sana Varga, its head of sustainability, signed for twelve months, as that mandate stands at the moment. Its capability permit names three projects and a budget of 120,000 units, and a permit can only narrow what its issuer holds. The year’s money crossed through an FX pool between sovereign frames and landed once, on the project registry’s frame. When an accreditation body withdraws a verifier, the registry operator suspends its agent: its identity dies in under 500ms, and nothing it signs after that reaches a release.',
  ],
  cast: [
    { agent: 'kiln-probes', role: 'Measure each kiln, sign every reading', ceiling: 'Sign their own readings under certificates that live hours, not years. Hold no budget and cannot attest a batch.' },
    { agent: 'verifier-07', role: 'Checks the readings, signs each batch', ceiling: 'Attests batches on the offtakes that name it, one attestation per batch. Its signature releases a tranche to the payee the contract names, and to no one else.' },
    { agent: 'offtake-desk', role: 'Funds the buyer’s offtakes', ceiling: 'The treasury’s sub-agent, with no wallet: every offtake is checked against Sana Varga’s mandate. Its permit names three projects and 120,000 units; a fourth project is refused before a unit moves.' },
    { agent: 'claims-desk', role: 'Retires tonnes against the buyer’s claim', ceiling: 'Signs retirements for the buyer, each citing its attestation and the registry’s serials. Moves no money.' },
    { agent: 'coop-desk', role: 'Claims each quarter, holds the co-op treasury', ceiling: 'The members vote distributions. Cannot attest its own batches, release escrow or remove an entry.' },
  ],
  loom: {
    nodes: [
      { id: 'buyer', label: 'offtake-desk', sub: 'buyer frame, pays in', kind: 'agent', x: 118, y: 110 },
      { id: 'fx', label: 'FX pool', sub: 'frame to frame', kind: 'teg', x: 336, y: 220 },
      { id: 'escrow', label: 'Offtake escrow', sub: 'funded for the year', kind: 'teg', x: 560, y: 110 },
      { id: 'ledger', label: 'Tonne ledger', sub: 'retirements, signed', kind: 'ledger', x: 764, y: 110 },
      { id: 'verifier', label: 'verifier-07', sub: 'accredited, own key', kind: 'agent', x: 336, y: 330 },
      { id: 'probes', label: 'kiln-probes', sub: 'sign every reading', kind: 'agent', x: 118, y: 450 },
      { id: 'gate', label: 'Release gate', sub: 'once per quarter', kind: 'gate', x: 560, y: 330 },
      { id: 'claims', label: 'claims-desk', sub: 'retires for the buyer', kind: 'agent', x: 900, y: 330 },
      { id: 'coop', label: 'Ember Hollow co-op', sub: 'treasury, 38 kilns', kind: 'agent', x: 764, y: 450 },
    ],
    edges: [
      { id: 'e-fund', from: 'buyer', to: 'fx', label: 'offtake, funded' },
      { id: 'e-land', from: 'fx', to: 'escrow', label: 'held up front' },
      { id: 'e-read', from: 'probes', to: 'verifier', label: 'readings, signed' },
      { id: 'e-attest', from: 'verifier', to: 'gate', label: '1,240 t, signed' },
      { id: 'e-tranche', from: 'escrow', to: 'gate', label: 'Q3 tranche' },
      { id: 'e-pay', from: 'gate', to: 'coop', label: '22,320 units', labelT: 0.62 },
      { id: 'e-emit', from: 'escrow', to: 'ledger' },
      { id: 'e-retire', from: 'claims', to: 'ledger', label: '1,240 t retired', labelT: 0.35 },
      { id: 'a-again', from: 'verifier', to: 'gate', attackOnly: true, curve: 44, label: 'after withdrawal' },
      { id: 'a-delete', from: 'coop', to: 'ledger', attackOnly: true, curve: 46, label: 'delete failed Q2' },
    ],
    script: [
      { edge: 'e-fund', state: 'active', dwellMs: 1500, caption: 'In January the buyer’s offtake desk funds the year from its own frame: 4,800 tonnes at 18 units a tonne.' },
      { edge: 'e-land', state: 'active', dwellMs: 1400, caption: 'The FX pool carries it across sovereign frames. The escrow lands on the project registry, exactly once.' },
      { edge: 'e-read', state: 'active', dwellMs: 1400, caption: 'All quarter, the probes on 38 kilns sign every temperature trace and every weighed load.' },
      { edge: 'e-attest', state: 'active', dwellMs: 1500, caption: 'At 07:40 on a Tuesday in October, verifier-07 signs batch Q3: 1,240 tonnes, one attestation, one key.' },
      { edge: 'e-tranche', state: 'active', dwellMs: 1300, caption: 'The attestation unlocks the third-quarter tranche and nothing else.' },
      { edge: 'e-pay', state: 'active', dwellMs: 1400, caption: '22,320 units release to the Ember Hollow co-op’s treasury: 1,240 tonnes at 18 units.' },
      { edge: 'e-emit', state: 'settled', dwellMs: 1400, caption: 'The release lands on the ledger beside the attestation that released it.' },
      { edge: 'e-retire', state: 'active', dwellMs: 1500, caption: 'The buyer’s claims desk signs the retirement of the 1,240 tonnes, citing the attestation. A second claim is plain to see.' },
    ],
  },
  attacks: [
    {
      title: 'The withdrawn verifier',
      attack: 'In November the accreditation body withdraws verifier-07 over a conflict of interest, and the registry operator suspends its agent. The co-op’s desk asks the old verifier to sign batch Q4 anyway, for the same buyer.',
      mechanism: 'The suspension is one coordinated action: the agent’s identity is revoked over the event stream in under 500ms and its account is suspended. A suspended agent is refused at authentication, so it cannot submit an attestation or approve a milestone, and the fourth-quarter tranche releases only on an accepted verifier’s signature.',
      rail: 'S08',
      consequence: 'The Q4 tranche stays in escrow until an accredited verifier signs. Every batch verifier-07 signed before its withdrawal stays on the ledger, and so does its revocation.',
      script: [
        { edge: 'a-again', state: 'denied', dwellMs: 1900, stopAt: 0.8, flashNode: 'gate', caption: 'S08. verifier-07 was suspended in one action. It cannot authenticate, so nothing it signs reaches a release.' },
      ],
    },
    {
      title: 'The quiet deletion',
      attack: 'Before resubmitting, the co-op’s desk asks for the failed second-quarter attestation to be deleted, so the corrected batch reads as a first pass.',
      mechanism: 'The ledger is append-only and no operation removes an entry, for the project, the verifier or the registry operator. A correction is a new signed entry beside the old one, so the corrected batch is verified on its own evidence and the failure stays readable next to it.',
      rail: 'S14',
      consequence: 'The corrected batch still settles on its own attestation. A reviewer replaying the quarter sees the failure, the gap that caused it and the correction, in order.',
      script: [
        { edge: 'a-delete', state: 'denied', dwellMs: 1900, stopAt: 0.7, flashNode: 'ledger', caption: 'S14. There is no delete, for anyone. A correction is a new entry beside the failure, and both stay readable.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Compliance Audit Procedures', href: '/compliance/doc/compliance-audit-procedures' },
    { label: 'Jurisdiction Profiles', href: '/compliance/doc/jurisdiction-profiles' },
  ],
  rails: ['S01', 'S03', 'S05', 'S07', 'S08', 'S14', 'S15', 'S16'],
  standup: {
    infra: 'A frame per national registry, and one for each buyer that wants its own, booted from the free licence and pre-built images. Projects and verifiers can start as accounts.',
    agents: 'Probe gateways, one agent per verifier, a co-op desk, and an offtake desk and a claims desk per buyer. The methodology stays with the verifier; the SDK carries identity, payment and attestation.',
    integration: 'Kiln telemetry, the MRV platform, the carbon registry’s serial numbers and the buyer’s procurement and claims systems. This is where the real time goes, and it stays theirs.',
  },
  nonClaims: [
    'CANOPY does not measure carbon, set methodologies or certify removals. It keeps the record of who attested what, who paid and who retired it on a ledger nobody can edit.',
    'No claim is made about any carbon standard, registry scheme or accounting rule. Accreditation, methodology approval and what a buyer may say about its tonnes stay with the standard setters, regulators and operators who own them today.',
    'An attestation is as true as the measurements under it: a probe that reads wrong signs a wrong number, and the ledger keeps it faithfully. Proving a sensor threshold without revealing the series needs a circuit that is not yet written; it is badged DESIGNED and nothing here depends on it.',
  ],
  mermaid: `flowchart LR
  P["kiln-probes<br/>signed readings"] -->|"readings"| V["verifier-07<br/>one attestation per batch"]
  V -->|"batch Q3, signed"| G{"release gate"}
  B["offtake-desk<br/>buyer frame"] -->|"via the FX pool"| E["offtake escrow<br/>project registry"]
  E -->|"Q3 tranche"| G
  G -->|"22,320 units"| C["co-op treasury"]
  E --> L[("tonne ledger<br/>append-only")]
  D["claims-desk"] -->|"retire 1,240 t"| L`,
  legacy: [
    { system: 'MRV platforms', connect: 'Each batch attestation carries the MRV report’s references. The platform stays the verifier’s working view.' },
    { system: 'Carbon registries', connect: 'A retirement carries the registry’s serial numbers, so the registry’s book and the ledger join on a key instead of a reconciliation.' },
    { system: 'Sensor networks and kiln telemetry', connect: 'Probe gateways sign what the sensors already report. The sensors keep doing the sensing.' },
    { system: 'Buyer procurement and claims systems', connect: 'Offtakes are funded inside a mandate; procurement reads settlements and the claims team reads retirements instead of chasing certificates.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
