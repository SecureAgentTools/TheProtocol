import type { BlueprintDeep } from '../types'

// LIFELINE deep architecture (§18) — a grant as escrowed tranches, attested
// in the field, readable by everyone with standing to read it.

export const deep: BlueprintDeep = {
  intro:
    'LIFELINE deployed: the donor’s frame holds the grant contract and its tranches; implementing partners claim from their own registries; field attestors sign what actually happened, where it happened; and a public mirror lets the donor, the auditor and the press read the same season. Beneficiary registration and last-mile logistics stay with the humanitarian systems built for them: their only wires run read-side into the people who claim and attest, never into the money. The trace replays tranche three, attestation to credit.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE DONOR’S FRAME', sub: 'the grant and its tranches live here', x: 30, y: 50, w: 360, h: 480, kind: 'frame' },
      { id: 'zp', label: 'PARTNERS IN THE FIELD', sub: 'their registries, their law', x: 640, y: 50, w: 330, h: 480, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'courier, never principal', x: 410, y: 50, w: 210, h: 480, kind: 'fabric' },
      { id: 'ze', label: 'THE HUMANITARIAN ESTATE', sub: 'kept as built; wires run read-side only, never into the money', x: 30, y: 580, w: 940, h: 110, kind: 'external' },
    ],
    nodes: [
      { id: 'grant', label: 'grant-desk', sub: 'funds, structures', kind: 'agent', x: 110, y: 135 },
      { id: 'spine', label: 'grant contract', sub: 'escrowed tranches', kind: 'gate', x: 300, y: 133 },
      { id: 'es', label: 'grant ledger', sub: 'a query, not a PDF', kind: 'ledger', x: 110, y: 375 },
      { id: 'teg', label: 'tranche escrow', sub: 'seen by every party', kind: 'teg', x: 110, y: 255 },
      { id: 'donorw', label: 'donor-watch', sub: 'reads everything', kind: 'agent', x: 110, y: 495 },
      { id: 'qgate', label: 'licence gate', sub: 'quarantine, reversible', kind: 'gate', x: 300, y: 255 },
      { id: 'partner', label: 'partner-ops', sub: 'claims tranches', kind: 'agent', x: 720, y: 255 },
      { id: 'field', label: 'field-attestor', sub: 'signs on site', kind: 'agent', x: 890, y: 135 },
      { id: 'replica', label: 'public mirror', sub: 'donor, audit, press', kind: 'registry', x: 720, y: 495 },
      { id: 'audw', label: 'auditor-watch', sub: 'reads, never writes', kind: 'agent', x: 720, y: 375 },
      { id: 'relay', label: 'contract relay', sub: 'signed commands', kind: 'registry', x: 515, y: 135 },
      { id: 'xfer', label: 'cross-registry', sub: 'exactly-once', kind: 'teg', x: 515, y: 375 },
      { id: 'benef', label: 'beneficiary data', sub: 'read-side only', kind: 'external', x: 450, y: 647 },
      { id: 'logi', label: 'field logistics', sub: 'confirmations attest', kind: 'external', x: 800, y: 647 },
    ],
    edges: [
      { id: 'e-benef', from: 'benef', to: 'partner', label: 'registration, read-side', dashed: true, curve: -60, labelT: 0.45 },
      { id: 'e-logi', from: 'logi', to: 'field', label: 'delivery confirmations', dashed: true, labelT: 0.6 },
      { id: 'e-fund', from: 'grant', to: 'spine', label: 'tranches', labelT: 0.45 },
      { id: 'e-escrow', from: 'grant', to: 'teg', label: 'fund milestones', labelT: 0.35 },
      { id: 'e-claim', from: 'partner', to: 'relay', label: 'claims tranche three', labelT: 0.45 },
      { id: 'e-attest', from: 'field', to: 'relay', label: 'distribution eleven, signed' },
      { id: 'e-relay', from: 'relay', to: 'spine', label: 'principal checked', labelT: 0.55 },
      { id: 'e-release', from: 'spine', to: 'teg', label: 'release' },
      { id: 'e-pay', from: 'teg', to: 'xfer', label: 'cross-registry pay', curve: 72, labelT: 0.55 },
      { id: 'e-payout', from: 'xfer', to: 'partner', label: 'their TEG credits' },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true },
      { id: 'e-mirror', from: 'es', to: 'replica', label: 'signed mirror', dashed: true, curve: 12, labelT: 0.8 },
      { id: 'e-watch', from: 'audw', to: 'replica', dashed: true },
      { id: 'e-donor', from: 'donorw', to: 'es', label: 'reads everything', dashed: true, labelT: 0.4 },
      { id: 'e-evidence', from: 'es', to: 'qgate', label: 'evidence', dashed: true, labelT: 0.4 },
      { id: 'e-quar', from: 'qgate', to: 'xfer', label: 'tranches stop', dashed: true, labelT: 0.6 },
    ],
    script: [
      { edge: 'e-fund', dwellMs: 1400, caption: 'The grant is a contract: milestones, terms, nine partners named.' },
      { edge: 'e-escrow', dwellMs: 1400, caption: 'The tranches fund at award. Nothing is wired ahead; tranche three exists on the ledger, visible to every party.' },
      { edge: 'e-attest', dwellMs: 1500, caption: 'A field attestor, holding its own signed identity, attests distribution eleven: at the site, on the day.' },
      { edge: 'e-claim', dwellMs: 1300, caption: 'The partner claims the tranche from its own registry.' },
      { edge: 'e-relay', dwellMs: 1400, caption: 'The fabric couriers the signed commands home. The relaying peer is never the principal.' },
      { edge: 'e-release', dwellMs: 1300, caption: 'The escrow-holding frame, and only it, releases the tranche.' },
      { edge: 'e-pay', dwellMs: 1400, caption: 'The money crosses registries with an idempotency key.' },
      { edge: 'e-payout', dwellMs: 1300, caption: 'The partner’s own TEG credits it, under its own law.' },
      { edge: 'e-emit', dwellMs: 1200, caption: 'One truth per tranche, on the grant ledger, append-only.' },
      { edge: 'e-mirror', dwellMs: 1400, caption: 'The season mirrors out, signed. The donor, the auditor and the press read the same record.' },
      { edge: 'e-evidence', dwellMs: 1400, caption: 'Week six: a partner’s numbers stop matching its attestations. The evidence is already on the ledger.' },
      { edge: 'e-quar', dwellMs: 1500, caption: 'Its licence suspends: further tranches stop within a sync cycle. Nobody files a lawsuit first, the other eight partners keep operating, and the quarantine reverses on evidence.' },
    ],
    traceLabel: 'Tranche three: attested on site, released once, readable by everyone.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'One grant, re-told as tranches.',
      runs: 'Nothing. One finished grant redrawn as milestones, attestations and tranches.',
      agents: 'None. Programme and compliance define what counts as delivery evidence, before anyone is standing in the field.',
      integrates: 'Nothing. Beneficiary systems and logistics stay untouched, now and later.',
      notYet: 'No registry, no escrow, no attestor.',
      proof: 'One historical response re-expressed as tranches and attestations, and the final report reproduces as a query over the model.',
    },
    {
      name: 'Pilot',
      headline: 'One partner, one corridor, real attestations.',
      runs: 'The donor runs a single-VM frame; one implementing partner joins with a registry seat.',
      agents: 'grant-desk, partner-ops, two field attestors on phones. donor-watch reads from day one.',
      integrates: 'Distribution schedules in via the SDK; the humanitarian systems remain the operational truth.',
      notYet: 'Small tranches. One partner. Quarantine is drilled, not needed.',
      proof: 'Three distributions release from escrow on field attestations alone, with zero settlement emails between the organisations.',
    },
    {
      name: 'Production',
      headline: 'The full response, visible all season.',
      runs: 'The donor’s sovereign frame; a registry per implementing partner, free licence, federated bilaterally.',
      agents: 'The full cast across nine partners; the public mirror serves the auditor and the press the same signed record.',
      integrates: 'Programme systems feed schedules; the ledger feeds reporting instead of the other way round.',
      notYet: 'Cross-donor pooling. One donor’s response proves the shape first.',
      proof: 'A partner audit is completed from the ledger and the mirror alone, and the partner agrees with every number in it.',
    },
    {
      name: 'Federation',
      headline: 'Many donors, many partners, one grammar.',
      runs: 'Unchanged. New donors and partners bring frames or seats.',
      agents: 'Partner track records travel with their DIDs to the next response.',
      integrates: 'Each new relationship is a signed card and a licence, not a memorandum negotiation.',
      notYet: 'Nothing structural. Growth is corridors.',
      proof: 'A new partner onboards mid-response and receives its first attested tranche within a week, with no bilateral integration project.',
    },
  ],
  sequenceTitle: 'One tranche, attestation to credit',
  sequence: `sequenceDiagram
  participant Fld as field-attestor (on site)
  participant Prt as partner-ops (their frame)
  participant Fab as federation fabric
  participant GC as grant contract (donor frame)
  participant TEG as tranche escrow
  participant XT as cross-registry pay
  participant Mir as public mirror
  Fld->>Fab: distribution attested, signed
  Prt->>Fab: tranche claim
  Fab->>GC: relayed commands (principal checked)
  GC->>TEG: release tranche three
  TEG->>XT: pay partner (idempotency key)
  XT->>Prt: their TEG credits, exactly once
  TEG-->>Mir: signed mirror update
  Note over Mir: donor, auditor and press read the same record
  Note over GC: mismatched numbers suspend a licence, not a convoy`,
  sizing: [
    { level: 'L1', what: 'Small partners join with accounts and phone-borne attestors', containers: '0 of theirs' },
    { level: 'L2', what: 'An NGO runs its agents against a hosted registry seat', containers: 'agents only' },
    { level: 'L3', what: 'Donor and large partners run sovereign frames, federated', containers: 'a full frame each' },
  ],
}
