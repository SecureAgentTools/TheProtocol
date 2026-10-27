import type { BlueprintDeep } from '../types'

// ADMIRALTY deep architecture (§18) — a port call as one escrowed account,
// settled off signed events, with the laytime clock attested as it runs.

export const deep: BlueprintDeep = {
  intro:
    'ADMIRALTY deployed: the port authority runs its sovereign frame under its own law; MV Kestrel and the charter desk act from the operator’s side; the harbour systems feed the agent who signs what happened, when it happened. The disbursement account is one escrow the agent can see but not raid, and the laytime clock is a record both parties signed at the time. The trace replays one call at Piraeus, funding to demurrage that never becomes a fight.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE PORT’S FRAME (PIRAEUS)', sub: 'its registry, its tariff, its law', x: 30, y: 50, w: 440, h: 460, kind: 'frame' },
      { id: 'zp', label: 'THE SHIP AND THE CHARTER', sub: 'operator and charterer, from their side', x: 530, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'four jurisdictions, one voyage', x: 530, y: 455, w: 440, h: 115, kind: 'fabric' },
      { id: 'ze', label: 'THE HARBOUR', sub: 'AIS and terminals in; cargo ops stay aboard', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'port', label: 'port-authority', sub: 'berthing, dues', kind: 'agent', x: 140, y: 135 },
      { id: 'spine', label: 'the port call', sub: 'one escrowed account', kind: 'gate', x: 310, y: 253 },
      { id: 'es', label: 'signed timeline', sub: 'the laytime clock', kind: 'ledger', x: 310, y: 135 },
      { id: 'teg', label: 'call escrow', sub: 'seen, not raided', kind: 'teg', x: 310, y: 375 },
      { id: 'agent', label: 'port-agent', sub: 'signs the events', kind: 'agent', x: 140, y: 375 },
      { id: 'pilots', label: 'pilotage, towage', sub: 'each a slice', kind: 'agent', x: 310, y: 470 },
      { id: 'vessel', label: 'MV Kestrel', sub: 'the ship’s identity', kind: 'agent', x: 690, y: 135 },
      { id: 'v-reg', label: 'their registry', sub: 'signed card', kind: 'registry', x: 860, y: 135 },
      { id: 'charter', label: 'charter-desk', sub: 'laytime, demurrage', kind: 'agent', x: 860, y: 375 },
      { id: 'c-es', label: 'their ledger', sub: 'same timeline', kind: 'ledger', x: 775, y: 255 },
      { id: 'relay', label: 'event relay', sub: 'signed commands', kind: 'registry', x: 900, y: 527 },
      { id: 'xfer', label: 'cross-frame pay', sub: 'exactly-once', kind: 'teg', x: 680, y: 527 },
      { id: 'ais', label: 'AIS / terminals', sub: 'feeds the attestors', kind: 'external', x: 330, y: 692 },
      { id: 'cargo', label: 'cargo ops', sub: 'no link, by design', kind: 'external', x: 150, y: 692 },
    ],
    edges: [
      { id: 'e-fund', from: 'vessel', to: 'xfer', label: 'funds the call', curve: -30 },
      { id: 'e-landx', from: 'xfer', to: 'teg', label: 'one DA, visible', curve: -4, labelT: 0.5 },
      { id: 'e-ais', from: 'ais', to: 'agent', label: 'feeds events', dashed: true, labelT: 0.5 },
      { id: 'e-nor', from: 'agent', to: 'spine', label: 'NOR, signed', labelT: 0.3 },
      { id: 'e-berth', from: 'port', to: 'spine', label: 'berthing', dashed: true },
      { id: 'e-clock', from: 'spine', to: 'es', label: 'both signed', dashed: true, labelT: 0.8 },
      { id: 'e-slice', from: 'spine', to: 'teg', label: 'per service', labelT: 0.85, curve: -40 },
      { id: 'e-apaid', from: 'teg', to: 'agent' },
      { id: 'e-pilot', from: 'pilots', to: 'teg', label: 'its slice', labelT: 0.5 },
      { id: 'e-charter', from: 'charter', to: 'relay', label: 'dispute, evidenced', labelT: 0.5 },
      { id: 'e-relay', from: 'relay', to: 'spine', label: 'principal checked', curve: 28, labelT: 0.5 },
      { id: 'e-vemit', from: 'vessel', to: 'c-es', dashed: true },
      { id: 'e-vreg', from: 'vessel', to: 'v-reg', dashed: true },
    ],
    script: [
      { edge: 'e-fund', dwellMs: 1400, caption: 'Before MV Kestrel arrives, her operator funds the call: agency, pilotage, towage, dues.' },
      { edge: 'e-landx', dwellMs: 1400, caption: 'One escrowed disbursement account. The port agent can see it and cannot raid it.' },
      { edge: 'e-ais', dwellMs: 1300, caption: 'AIS and the terminal systems feed the agent who will sign what happened.' },
      { edge: 'e-nor', dwellMs: 1400, caption: 'Notice of readiness, signed by the master’s agent. An attestation, not an email.' },
      { edge: 'e-berth', dwellMs: 1300, caption: 'Berthing, signed by the port. Completion will be signed by both.' },
      { edge: 'e-clock', dwellMs: 1500, caption: 'Laytime runs from signed NOR to signed completion. The clock is not a claim either side makes; both already signed it at the time.' },
      { edge: 'e-slice', dwellMs: 1400, caption: 'Each service releases its slice at its trigger.' },
      { edge: 'e-pilot', dwellMs: 1200, caption: 'Pilotage and towage are paid as their events land.' },
      { edge: 'e-apaid', dwellMs: 1400, caption: 'The agent who used to finance the ship’s costs and chase reimbursement for a quarter is simply paid at completion.' },
      { edge: 'e-charter', dwellMs: 1500, caption: 'A genuine dispute, the weather clause, goes to ruling with the timeline as shared evidence, and the disputed amount holds until then.' },
      { edge: 'e-relay', dwellMs: 1300, caption: 'Signed commands courier through the fabric; the relaying peer is never the principal.' },
      { edge: 'e-vemit', dwellMs: 1400, caption: 'The operator’s ledger holds the same call. The next port, in the next jurisdiction, settles the same way, and nobody wires money on faith.' },
    ],
    traceLabel: 'One call at Piraeus: funded ahead, settled off signed events, clock attested.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'One call, re-told as events.',
      runs: 'Nothing. One completed port call redrawn as attestations, slices and triggers.',
      agents: 'None. The agency and the charterer agree which events start which clocks, for once before the voyage.',
      integrates: 'Nothing. AIS, the terminal and the ship stay exactly as they are.',
      notYet: 'No escrow, no timeline, no identity for the ship.',
      proof: 'Last year’s worst demurrage fight replayed against the event model, and both sides agree where the attested clock would have left it.',
    },
    {
      name: 'Pilot',
      headline: 'One berth, shadow disbursement.',
      runs: 'A single-VM frame at the port authority. One agency and one operator connect with seats.',
      agents: 'port-authority, port-agent, the vessel identity for one ship; the charter desk reads the timeline.',
      integrates: 'AIS and terminal events feed the attestors; the paper DA process runs in parallel.',
      notYet: 'Shadow money only. One berth. Disputes are drilled against history.',
      proof: 'Five calls settle in shadow with every slice releasing at its signed trigger, and the shadow DA matches the agency’s final account line for line.',
    },
    {
      name: 'Production',
      headline: 'The port settles itself, under its law.',
      runs: 'The authority’s sovereign frame: registry, TEG, EventStore, identity fabric, jurisdiction profile declared.',
      agents: 'The full cast; vessels fund calls before arrival; the attested timeline is the laytime record.',
      integrates: 'AIS and terminal systems in production; agencies read the escrow instead of financing the ship.',
      notYet: 'Other ports. One authority proves the pattern under its own law first.',
      proof: 'A quarter of calls closes with disbursement accounts settled from escrow and demurrage resolved from the attested clock, without one competing spreadsheet.',
    },
    {
      name: 'Federation',
      headline: 'A voyage across four jurisdictions.',
      runs: 'Unchanged. Each port authority runs its frame; operators and charterers federate in.',
      agents: 'The vessel identity travels with the ship; each port applies its own tariff under its own declared profile.',
      integrates: 'Each new port or operator is a signed card and a licence.',
      notYet: 'Charterparty law, general average and the law of the sea remain with the contracts and tribunals that own them.',
      proof: 'MV Kestrel completes a four-port voyage with every call settled in that port’s jurisdiction from escrow, and no money wired on faith anywhere on the route.',
    },
  ],
  sequenceTitle: 'One port call, funding to completion',
  sequence: `sequenceDiagram
  participant Ves as MV Kestrel (operator frame)
  participant XT as cross-registry pay
  participant Call as the port call (port frame)
  participant Agt as port-agent
  participant Port as port-authority
  participant TEG as disbursement escrow
  participant ES as attested timeline
  Ves->>XT: funds the call ahead
  XT->>TEG: one DA, escrowed, visible
  Agt->>Call: NOR signed
  Port->>Call: berthing signed
  Call-->>ES: the clock, signed by both at the time
  Call->>TEG: each service releases its slice
  TEG->>Agt: agent paid at completion
  Note over ES: demurrage argues over a record, not against one
  Note over Call: the disputed slice holds until the ruling#59; the rest settles`,
  sizing: [
    { level: 'L1', what: 'Agencies and charterers join with accounts and agents', containers: '0 of theirs' },
    { level: 'L2', what: 'An operator runs vessel identities against a hosted seat', containers: 'agents only' },
    { level: 'L3', what: 'A sovereign frame per port authority, profile declared', containers: 'one frame per port' },
  ],
}
