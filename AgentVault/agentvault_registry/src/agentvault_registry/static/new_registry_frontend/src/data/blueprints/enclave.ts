import type { Blueprint } from './types'
import { liveRatioOf } from './types'

// ENCLAVE: data clean rooms and data marketplaces (frontier wave 2026-09-25). Owners sell answers,
// not copies: priced query templates that run inside the owner's own enclave, paid per question on
// single-use authorizations, bounded by capability caveats, recorded question by question on the ledger.
// A frontier chamber: the sector is arriving now; the rails are the live ones.

const primitives = [
  { step: 'Each question paid once', primitive: 'A2A payment authorization: one single-use apt_ authorization per query, exactly-once settlement', railStatus: 'LIVE' as const, href: '/docs/14' },
  { step: 'Templates and budget as bounds', primitive: 'IRONKEY L4 capability caveats: counterparty allowlist, atomic budget debit', railStatus: 'LIVE' as const, href: '/docs/24' },
  { step: 'A partner gets less, never more', primitive: 'Derived capability permits: a subset of the parent on templates, budget and expiry', railStatus: 'LIVE' as const, href: '/docs/24' },
  { step: 'A reduced grant, with no chase', primitive: 'Issuer clamp: reducing an issuer empties every permit it issued', railStatus: 'LIVE' as const, href: '/docs/24' },
  { step: 'One identity per query service', primitive: 'SPIFFE identity per workload and agent, short-lived certificates', railStatus: 'LIVE' as const, href: '/docs/08' },
  { step: 'Answers signed on the way out', primitive: 'Signed attestations from identified parties, append-only', railStatus: 'LIVE' as const },
  { step: 'Retries that never pay twice', primitive: 'Idempotency keys, two-layer dedup (cache + ledger unique)', railStatus: 'LIVE' as const },
  { step: 'An audit that is a query', primitive: 'Immutable event ledger, replayable, forensically searchable', railStatus: 'LIVE' as const, href: '/docs/07' },
  { step: 'Seats funded from home', primitive: 'Cross-registry transfer and FX pools across sovereign frames', railStatus: 'LIVE' as const },
  { step: 'Every unit accounted for', primitive: 'Delta = 0 supply invariant, independently audited', railStatus: 'LIVE' as const, href: 'https://auditor.theprotocol.cloud' },
  { step: 'Proof a cell met its minimum group size', primitive: 'ZK attestation over a new circuit, not yet written', railStatus: 'DESIGNED' as const },
]

export const enclave: Blueprint = {
  id: 'enclave',
  tier: 2,
  frontier: true,
  rank: 27,
  industry: 'Data Clean Rooms and Data Marketplaces',
  systemName: 'ENCLAVE',
  promise: 'Data owners sell answers instead of copies: each question paid once, run inside the owner’s walls, signed on the way out and kept on the ledger.',
  cases: [
    { role: 'Public transit authority', line: 'Ridership questions answered and paid per query, while the counts stay inside its own walls.' },
    { role: 'Retail consortium', line: 'Footfall sold as signed aggregates, never as a file that leaves.' },
    { role: 'Academic research group', line: 'A study’s budget, templates and partners carried as bounds, not as a binder of agreements.' },
    { role: 'Data broker', line: 'Per-query answers instead of bulk copies that outlive every contract.' },
  ],
  problem:
    'Data sharing still runs on copies. To answer a researcher’s question, an owner ships an extract under a sharing agreement, and from then on nobody can show who asked what, what each answer was worth, or where the file went next; ending the agreement means asking every recipient to delete, and taking their word for it. Clean rooms keep the rows inside, but the licence, the budget and the record of questions still live in contracts and invoices beside them, reconciled by hand.',
  system: [
    'ENCLAVE is a market for questions. Three data owners run their own frames: the Lindhaven transit authority with four years of door-sensor passenger counts from 1,140 buses and trams, a consortium of 212 retail stores with footfall, and a regional logistics firm with delivery timings. Each exposes query services that run inside its own enclave, one service per approved template, each with its own identity and price, and only aggregates ever leave. At 09:40 on a Wednesday, study-desk, the agent of Dr Nadia Halvorsen’s mobility institute, buys a batch of 120 aggregate queries against the transit counts at 15 units a query: boardings by stop and hour on nine corridors. Every query rides its own single-use payment authorization; query-LHV-2 verifies it, runs the question against 2.3 billion rows it never lets out, and signs the aggregate it returns. Each authorization settles exactly once, and every unit it moves is conserved and independently audited.',
    'The desk is a licence seat on the authority’s own frame, and its grant is the authority’s to set and to reduce. It works through a capability permit cut from that grant: the three templates the licence names and 18,000 units of query budget, debited atomically. Each template is its own service, so the templates the permit may run are the only counterparties it may pay. For the partner lab that builds the corridor model, the desk derives a narrower permit: one template, 2,400 units, an earlier expiry. A capability permit can only narrow, and whatever the desk issues conveys no more than its grant allows at the moment of use. When the partner reaches for a template the licence never named, the ask is refused before a unit moves.',
    'Every question lands on the append-only ledger beside its price and the signature over its answer, so an audit is a query, not an investigation. The authority lists every question a licence ever asked in one read; the institute shows a reviewer which signed aggregate stands behind each figure in its paper. An answer that query-LHV-2 did not sign never reaches the ledger, and a question nobody paid for is never answered.',
  ],
  cast: [
    { agent: 'study-desk', role: 'The institute’s licence seat: buys the batch, derives partner permits', ceiling: 'Its grant is the authority’s to set and to reduce. Every permit it cuts conveys no more than that grant allows at the moment of use.' },
    { agent: 'partner-lab', role: 'Runs one template for the corridor model', ceiling: 'Holds nothing of its own: a permit derived from the desk’s, one template, 2,400 units. Cannot widen any of them.' },
    { agent: 'query-LHV-2', role: 'Answers one template inside the enclave, signs every aggregate', ceiling: 'Collects per query and signs what it returns. Holds no budget and grants nothing.' },
    { agent: 'data steward (human)', role: 'Sets and reduces the grant behind each licence seat', ceiling: 'Acts on grants, not on queries. Reducing one empties every permit the seat issued, on the next request.' },
  ],
  loom: {
    nodes: [
      { id: 'steward', label: 'Data steward', sub: 'sets the grant', kind: 'human', x: 118, y: 110 },
      { id: 'desk', label: 'study-desk', sub: 'a licence seat', kind: 'agent', x: 118, y: 330 },
      { id: 'gate', label: 'Licence gate', sub: 'templates, budget, issuer', kind: 'gate', x: 336, y: 220 },
      { id: 'partner', label: 'partner-lab', sub: 'a narrower permit', kind: 'agent', x: 336, y: 450 },
      { id: 'pay', label: 'Query payment', sub: 'single-use, once', kind: 'teg', x: 560, y: 110 },
      { id: 'query', label: 'query-LHV-2', sub: 'signs each aggregate', kind: 'agent', x: 560, y: 330 },
      { id: 'rows', label: 'Transit enclave', sub: 'rows never leave', kind: 'external', x: 560, y: 450 },
      { id: 'ledger', label: 'Question ledger', sub: 'every question, kept', kind: 'ledger', x: 764, y: 110 },
      { id: 'reviewer', label: 'Reviewer', sub: 'an audit is a query', kind: 'external', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-grant', from: 'steward', to: 'gate', label: 'the grant' },
      { id: 'e-ask', from: 'desk', to: 'gate' },
      { id: 'e-derive', from: 'desk', to: 'partner', label: 'narrower permit' },
      { id: 'e-pay', from: 'gate', to: 'pay', label: 'single-use payment authorization' },
      { id: 'e-rows', from: 'rows', to: 'query', label: 'aggregates only' },
      { id: 'e-sign', from: 'query', to: 'pay', label: 'answer, signed' },
      { id: 'e-settle', from: 'pay', to: 'ledger' },
      { id: 'e-audit', from: 'ledger', to: 'reviewer', label: 'every question' },
      { id: 'a-widen', from: 'desk', to: 'gate', attackOnly: true, curve: -46, labelT: 0.5, label: 'a wider copy' },
      { id: 'a-next', from: 'partner', to: 'gate', attackOnly: true, curve: 44, label: 'the next query' },
    ],
    script: [
      { edge: 'e-grant', state: 'active', dwellMs: 1500, caption: 'The authority’s data steward sets the grant behind the institute’s licence seat, and holds the right to reduce it.' },
      { edge: 'e-ask', state: 'active', dwellMs: 1400, caption: '09:40. study-desk asks for 120 aggregate queries under its permit: three templates, 18,000 units of budget.' },
      { edge: 'e-derive', state: 'active', dwellMs: 1400, caption: 'For the partner lab it derives a narrower permit: one template, 2,400 units. It cannot derive a wider one.' },
      { edge: 'e-pay', state: 'active', dwellMs: 1400, caption: 'Each query gets its own single-use payment authorization, 15 units, checked against the templates and the budget first.' },
      { edge: 'e-rows', state: 'active', dwellMs: 1500, caption: 'Inside the enclave the question meets 2.3 billion rows. The rows stay; only the aggregate comes out.' },
      { edge: 'e-sign', state: 'active', dwellMs: 1400, caption: 'query-LHV-2 signs the aggregate it returns, and the payment authorization settles exactly once.' },
      { edge: 'e-settle', state: 'settled', dwellMs: 1400, caption: 'Question, price and signature land on the ledger, append-only.' },
      { edge: 'e-audit', state: 'active', dwellMs: 1500, caption: 'An audit is a query, not an investigation: every question the licence ever asked, in one read.' },
    ],
  },
  attacks: [
    {
      title: 'The template nobody licensed',
      attack: 'The partner asks for finer data, and the desk derives it a copy of its authority with a fourth template added: stop-to-stop flows in 15-minute windows, which the licence never named.',
      mechanism: 'A derived permit is checked against the permit it comes from at the moment it is cut: templates a subset, budget no larger than what remains, expiry no later. The fourth template is not in the parent, so the derivation fails there, and a payment to any template a permit does not name is refused at the gate before a payment authorization exists. A permit can narrow what its issuer holds; it cannot add a template.',
      rail: 'S03',
      consequence: 'No wider permit exists, no payment authorization is issued, and no question reaches the enclave. There is nothing to unwind.',
      script: [
        { edge: 'a-widen', state: 'denied', dwellMs: 1900, stopAt: 0.8, flashNode: 'gate', caption: 'S03. A derived permit is a subset of its parent. A fourth template is refused before any payment authorization exists.' },
      ],
    },
    {
      title: 'The grant reduced mid-study',
      attack: 'Six weeks in, the authority and the institute dispute whether a published chart stayed inside the licence. The steward reduces the desk’s grant while the dispute is resolved. The partner lab, which nobody told, sends its next query.',
      mechanism: 'The partner’s permit was cut by the desk, and a capability permit conveys its caveats intersected with its issuer’s authority as that authority stands at the moment of each request. The desk no longer holds the authority to buy, so every permit it ever issued conveys none from the next request on. Nobody hunts for the partner’s permit, and no revocation list is published or consulted.',
      rail: 'S04',
      consequence: 'The partner’s query is refused at the gate before a payment authorization exists. Every question answered before the dispute stays on the ledger, and nothing needs to be unwound.',
      script: [
        { edge: 'e-grant', state: 'active', dwellMs: 1300, caption: 'A dispute over a published chart. The steward reduces the desk’s grant: it may no longer buy.' },
        { edge: 'a-next', state: 'denied', dwellMs: 1900, stopAt: 0.72, flashNode: 'gate', caption: 'S04. The partner’s permit conveys only what the desk holds now, which is nothing to pay with. No chase, no revocation list.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Data Protection Policy', href: '/compliance/doc/data-protection-policy' },
    { label: 'Compliance Audit Procedures', href: '/compliance/doc/compliance-audit-procedures' },
  ],
  rails: ['S01', 'S03', 'S04', 'S14', 'S15', 'S16'],
  standup: {
    infra: 'Each data owner on a frame of its own, booted from the free licence. Buyers fund their seats from their own frames or from a hosted account.',
    agents: 'One query agent per approved template on the owner’s side, and a seat per licensee. The query logic is the owner’s; the SDK carries identity, payment verification and signing.',
    integration: 'The enclave itself: the warehouse, the aggregation rules and the minimum group size. This is where the real time goes, and it stays the owner’s.',
  },
  nonClaims: [
    'ENCLAVE does not see, store or process the data. It carries who may ask what, what each answer cost, and the record of every question.',
    'Privacy, aggregation and every data-protection duty stay with the enclave’s owner. The minimum group size is the owner’s rule, enforced inside the owner’s walls; a proof that each answer met it is designed, not built.',
    'No claim of conformity with any data-protection law, certification or data-sharing scheme is made or implied. Those questions stay with the owners, the buyers and their regulators.',
  ],
  mermaid: `flowchart LR
  ST(["data steward<br/>the grant"]) -->|"grant, reducible"| G{"licence gate<br/>templates, budget,<br/>issuer authority"}
  D["study-desk<br/>licence seat"] -->|"120 queries"| G
  D -.->|"narrower permit"| PL["partner-lab<br/>one template"]
  G -->|"single-use payment authorization"| P["query payment<br/>exactly once"]
  E[("transit enclave<br/>rows stay inside")] -.->|"aggregates only"| Q["query-LHV-2"]
  Q -->|"answer, signed"| P
  P --> L[("question ledger<br/>asked, priced, signed")]
  L -->|"an audit is a query"| R["reviewer"]`,
  legacy: [
    { system: 'Data warehouses and lakehouses', connect: 'The rows stay where they are. The query agent runs beside the warehouse, inside the owner’s walls, and only signed aggregates leave.' },
    { system: 'Clean-room products', connect: 'The clean room keeps doing the computation. ENCLAVE carries the licence, the price of each question and the record around it.' },
    { system: 'Data catalogues', connect: 'An approved catalogue entry becomes a priced query template with its own identity. The catalogue stays where owners describe what they hold.' },
    { system: 'Contract and data-sharing agreement management', connect: 'The signed agreement stays with legal. Its operative terms, the templates, the budget and the term, become the grant and the caveats that enforce them.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
