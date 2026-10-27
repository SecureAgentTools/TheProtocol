import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'The registry is not a vendor', primitive: 'Sovereign frame under the authority that holds title', railStatus: 'LIVE' as const },
  { step: 'A transfer chain that cannot fork', primitive: 'Immutable, replayable event ledger', railStatus: 'LIVE' as const },
  { step: 'Conveyance money in escrow', primitive: 'Contract spine: funds held through completion', railStatus: 'LIVE' as const },
  { step: 'Exactly-once settlement', primitive: 'Idempotent transfer across retries and crashes', railStatus: 'LIVE' as const },
  { step: 'A named registrar behind changes', primitive: 'Cockpit Card mandate, authority re-derived', railStatus: 'LIVE (gated)' as const },
  { step: 'Public verifiability', primitive: 'Signed registry card and public read surfaces', railStatus: 'LIVE' as const, href: '/.well-known/registry-card.json' },
]

export const cadastre: Blueprint = {
  id: 'cadastre',
  tier: 2,
  vault: true,
  rank: 15,
  industry: 'Real Estate and Title',
  systemName: 'CADASTRE',
  promise: 'A title chain that cannot fork, and conveyance money that moves exactly once, at completion.',
  cases: [
    { role: 'Land registry authority', line: 'A sovereign frame under your law, not a vendor tenancy.' },
    { role: 'Conveyancing practice', line: 'Completion funds in escrow both sides can watch.' },
    { role: 'Mortgage lender', line: 'Charges recorded on a chain that cannot be quietly edited.' },
    { role: 'Lender or title researcher', line: 'Read the title’s history from a replay, not archive boxes.' },
  ],
  problem:
    'A property transfer is a week of held breath: money in flight between accounts, a title that is true in one database and pending in another, and a fraud window exactly as wide as the gap between the two. The registry that could close the gap cannot become a tenant in anyone’s platform, so the gap persists.',
  system: [
    'CADASTRE is a land registry operating its own sovereign frame in its own datacenter, under its own statute. Every parcel’s history is an append-only chain: grants, transfers, charges, discharges, each entry signed, each replayable. Completion day for parcel 4471 is not a wire race. The buyer’s funds sit in escrow visible to both conveyancers; the transfer entry and the release are one atomic completion; and the money moves exactly once, with the idempotency machinery absorbing every retry the banks’ systems throw at it.',
    'A change to the register is never an anonymous database write. Every completion is released by the register’s completion agent, a sub-agent of the registrar’s account with no wallet of its own, so each change it makes answers to the registrar’s mandate: re-derived on every request, recorded with an authority snapshot, behind presence proof above the routine threshold. When a forged discharge attempt arrives in March, it does not fail quietly in a log. It fails loudly at a gate, in an audit record the fraud unit reads, with the attempt itself preserved as evidence.',
  ],
  cast: [
    { agent: 'registrar (human)', role: 'Authorises register changes', ceiling: 'Cockpit mandate over the register’s completion agent, a sub-agent with no wallet. Presence above threshold.' },
    { agent: 'conveyancer-buyer', role: 'Funds and claims completion', ceiling: 'Escrow fund and completion claim on its own matter.' },
    { agent: 'conveyancer-seller', role: 'Delivers title, receives funds', ceiling: 'Completion claim only. Cannot touch the chain.' },
    { agent: 'lender-desk', role: 'Registers and discharges charges', ceiling: 'Its own charges only, evidence attached.' },
    { agent: 'fraud-watch', role: 'Reads refusals and anomalies', ceiling: 'Read-only over the whole register.' },
  ],
  loom: {
    nodes: [
      { id: 'buyer', label: 'buyer side', sub: 'funds completion', kind: 'external', x: 118, y: 220 },
      { id: 'escrow', label: 'Completion escrow', sub: 'both sides watch', kind: 'teg', x: 336, y: 110 },
      { id: 'gate', label: 'Registrar gate', sub: 'named, presence', kind: 'gate', x: 560, y: 330 },
      { id: 'seller', label: 'seller side', sub: 'delivers title', kind: 'agent', x: 118, y: 330 },
      { id: 'registrar', label: 'registrar', sub: 'mandate re-derived', kind: 'human', x: 336, y: 450 },
      { id: 'chain', label: 'Title chain', sub: 'parcel 4471', kind: 'ledger', x: 900, y: 330 },
      { id: 'payout', label: 'Funds move once', sub: 'at completion', kind: 'teg', x: 900, y: 110 },
    ],
    edges: [
      { id: 'e-fund', from: 'buyer', to: 'escrow', label: 'purchase funds' },
      { id: 'e-title', from: 'seller', to: 'gate', label: 'transfer instrument' },
      { id: 'e-sign', from: 'registrar', to: 'gate', label: 'presence sign-off', labelT: 0.35 },
      { id: 'e-entry', from: 'gate', to: 'chain', label: 'atomic entry' },
      { id: 'e-release', from: 'escrow', to: 'payout' },
      { id: 'a-forge', from: 'seller', to: 'chain', attackOnly: true, label: 'forged discharge', curve: -90 },
    ],
    script: [
      { edge: 'e-fund', state: 'active', dwellMs: 1500, caption: 'Completion funds sit in escrow both conveyancers can watch.' },
      { edge: 'e-title', state: 'active', dwellMs: 1400, caption: 'The transfer instrument arrives at the registrar gate.' },
      { edge: 'e-sign', state: 'active', dwellMs: 1400, caption: 'A named registrar signs, mandate re-derived on this very request.' },
      { edge: 'e-entry', state: 'active', dwellMs: 1400, caption: 'The chain gains one atomic entry. History cannot fork.' },
      { edge: 'e-release', state: 'active', dwellMs: 1500, caption: 'The money moves exactly once, at completion, retries absorbed.' },
    ],
  },
  attacks: [
    {
      title: 'The forged discharge',
      attack: 'A fraudster with a stolen conveyancer credential submits a discharge of the lender’s charge, clearing the path to sell a mortgaged property.',
      mechanism: 'A register change is released under the registrar’s mandate, not written by whoever holds a credential. The submission arrives without the registrar’s re-derived authority and without the lender as principal on its own charge, so the gate refuses it and records the attempt as evidence.',
      rail: 'S05',
      riskRef: 'R-OP-05',
      consequence: 'The charge stands, the sale cannot complete against it, and the fraud unit reads the refusal on the same day rather than the loss a year later.',
      script: [
        { edge: 'a-forge', state: 'denied', dwellMs: 1900, stopAt: 0.66, flashNode: 'gate', caption: 'S05. A stolen credential is not a registrar mandate. The refusal is recorded as evidence.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Data Protection Policy', href: '/compliance/doc/data-protection-policy' },
  ],
  rails: ['S01', 'S05', 'S06', 'S14', 'S15', 'S16'],
  standup: {
    infra: 'The authority’s own frame on its own hardware, under its own statute.',
    agents: '5 roles. Conveyancers connect through their own registries, federated.',
    integration: 'Cadastral maps and survey systems stay authoritative for geometry; the protocol carries title acts, authority and money.',
  },
  nonClaims: [
    'CADASTRE implements a register’s acts; it does not decide property law, and statutory registration effects remain defined by statute.',
    'No claim about any jurisdiction’s land registration regime. The mechanism serves the authority that adopts it.',
  ],
  mermaid: `flowchart LR
  B["buyer conveyancer"] -->|"fund completion escrow"| TEG["TEG escrow"]
  S["seller conveyancer"] -->|"transfer instrument"| G{"registrar gate<br/>mandate + presence"}
  R["registrar (human)"] --> G
  G -->|"one atomic entry"| ES[("title chain<br/>append-only, replayable")]
  TEG -->|"exactly-once at completion"| OUT["funds to seller"]
  L["lender charges"] -.->|"principal-only discharge"| G`,
  legacy: [
    { system: 'The land registry of record', connect: 'Runs in parallel as the signed act chain. Legal registration stays with the registry until the law says otherwise.' },
    { system: 'Survey and GIS systems', connect: 'Maps stay authoritative for geometry. Acts reference parcels by identifier.' },
    { system: 'Conveyancing case systems', connect: 'Completion money moves exactly once, from escrow. The case file records the settlement event.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
