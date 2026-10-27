import type { BlueprintDeep } from '../types'

// ATELIER deep architecture (§18) — a catalogue whose royalty is the
// settlement itself, with derivatives that pay their ancestors.

export const deep: BlueprintDeep = {
  intro:
    'ATELIER deployed: the licensing house runs the catalogue, the licence gate and the provenance ledger on its own frame; clients and studios act from their registries; the fabric carries the money exactly once. The carve is not drawn as a separate compliance box because it is not one: it lives inside the settlement rail itself. The trace replays one work from intake to a derivative paying its ancestor.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE HOUSE’S FRAME', sub: 'catalogue, licences, provenance: yours', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'CLIENTS AND STUDIOS', sub: 'their registries, their agents', x: 530, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'money moves exactly once', x: 530, y: 455, w: 440, h: 115, kind: 'fabric' },
      { id: 'ze', label: 'THE PRODUCTION LINE', sub: 'asset pipeline in, delivery out', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'audit', label: 'royalty-audit', sub: 'reads, reconciles', kind: 'agent', x: 400, y: 100 },
      { id: 'lic', label: 'licence gate', sub: 'apt_ token, 15 min', kind: 'gate', x: 400, y: 240 },
      { id: 'es', label: 'provenance', sub: 'lineage, forever', kind: 'ledger', x: 100, y: 115 },
      { id: 'settle', label: 'settle + carve', sub: 'basis points, atomic', kind: 'teg', x: 195, y: 300 },
      { id: 'catalogue', label: 'atelier-verse', sub: 'holds the works', kind: 'agent', x: 120, y: 380 },
      { id: 'forge', label: 'lineage machine', sub: 'quorum, royalty', kind: 'registry', x: 250, y: 165 },
      { id: 'client', label: 'client-agent', sub: 'pays per use', kind: 'agent', x: 820, y: 300 },
      { id: 'c-reg', label: 'their registry', sub: 'signed card', kind: 'registry', x: 895, y: 100 },
      { id: 'studio', label: 'studio-fork', sub: 'builds derivatives', kind: 'agent', x: 820, y: 165 },
      { id: 'deriv', label: 'voice-model-fork', sub: 'paid, owes upstream', kind: 'agent', x: 725, y: 375 },
      { id: 'xfer', label: 'cross-registry', sub: 'pays exactly once', kind: 'teg', x: 720, y: 530 },
      { id: 'mesh', label: 'federation mesh', sub: 'peer cards, licenses', kind: 'registry', x: 895, y: 530 },
      { id: 'pipeline', label: 'asset pipeline', sub: 'masters stay here', kind: 'external', x: 390, y: 700 },
      { id: 'cdn', label: 'delivery CDN', sub: 'counts attest usage', kind: 'external', x: 215, y: 700 },
    ],
    edges: [
      { id: 'e-pipe', from: 'pipeline', to: 'catalogue', label: 'new works in', dashed: true, labelT: 0.43, curve: 2 },
      { id: 'e-list', from: 'catalogue', to: 'forge', curve: -66 },
      { id: 'e-ask', from: 'client', to: 'lic', label: 'requests use', labelT: 0.35, curve: -30 },
      { id: 'e-grant', from: 'lic', to: 'settle', label: 'authorized', labelT: 0.49, curve: 6 },
      { id: 'e-pay', from: 'client', to: 'xfer', label: 'pays per use', curve: -54, labelT: 0.49 },
      { id: 'e-land', from: 'xfer', to: 'settle', label: 'lands home, keyed', curve: -56, labelT: 0.44 },
      { id: 'e-carve', from: 'settle', to: 'catalogue', label: 'royalty, in-rail', curve: -20, labelT: 0.48 },
      { id: 'e-emit', from: 'settle', to: 'es', label: 'one event', dashed: true, curve: 4, labelT: 0.52 },
      { id: 'e-cdn', from: 'catalogue', to: 'cdn', label: 'licensed delivery', dashed: true, labelT: 0.6, curve: 4 },
      { id: 'e-fork', from: 'studio', to: 'forge', label: 'forks with lineage', labelT: 0.33 },
      { id: 'e-lineage', from: 'forge', to: 'es', dashed: true },
      { id: 'e-earn', from: 'deriv', to: 'xfer', label: 'derivative paid', curve: 12, labelT: 0.51 },
      { id: 'e-card', from: 'c-reg', to: 'mesh', label: 'signed card', dashed: true, labelT: 0.32 },
      { id: 'e-audit', from: 'audit', to: 'es', dashed: true, curve: -8 },
    ],
    script: [
      { edge: 'e-pipe', dwellMs: 1300, caption: 'A new voice model arrives from the asset pipeline, catalogued with its rights metadata.' },
      { edge: 'e-list', dwellMs: 1300, caption: 'The work publishes with lineage. From here, every descendant will know its ancestor.' },
      { edge: 'e-ask', dwellMs: 1400, caption: 'A client agent requests a use. The authorization lives fifteen minutes and does exactly one thing.' },
      { edge: 'e-grant', dwellMs: 1300, caption: 'The licence gate authorizes: this work, this use, this authorization.' },
      { edge: 'e-pay', dwellMs: 1300, caption: 'Payment crosses from the client’s frame.' },
      { edge: 'e-land', dwellMs: 1400, caption: 'It lands on the house frame exactly once, idempotency-keyed.' },
      { edge: 'e-carve', dwellMs: 1500, caption: 'The royalty is carved by the settlement itself, in basis points. Under-reporting is not a smaller settlement; it is no settlement.' },
      { edge: 'e-emit', dwellMs: 1200, caption: 'Use, split and licence land on the ledger.' },
      { edge: 'e-cdn', dwellMs: 1200, caption: 'Delivery follows the licence, not the other way around.' },
      { edge: 'e-fork', dwellMs: 1400, caption: 'A studio forks the model. The fork carries its lineage on the ledger.' },
      { edge: 'e-earn', dwellMs: 1400, caption: 'The derivative is paid on its own registry, and the rail pays its ancestor before anything else.' },
      { edge: 'e-audit', dwellMs: 1300, caption: 'The audit agent reconciles settlements against lineage. It reads; it cannot touch.' },
    ],
    traceLabel: 'One work: licensed, carved, forked, ancestor paid.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'The catalogue, read as split tables.',
      runs: 'Nothing. Ten works and their contracts, redrawn as rights metadata and royalty splits.',
      agents: 'None. The rights team argues the split table down to basis points, on paper, where it is cheap.',
      integrates: 'Nothing. The asset pipeline and the CDN are untouched.',
      notYet: 'No licence exists on the network. No carve is enforced anywhere.',
      proof: 'Ten works re-expressed with rights metadata and split tables, and the royalty column sums to what the contracts say.',
    },
    {
      name: 'Pilot',
      headline: 'A hundred uses, every carve enforced.',
      runs: 'A hosted registry seat. The catalogue holds a pilot shelf of works.',
      agents: 'atelier-verse, the licence gate, royalty-audit reading along.',
      integrates: 'The asset pipeline feeds the pilot shelf by hand; the CDN stays as it is.',
      notYet: 'No forks. Pocket prices. Clients are invited accounts, not strangers.',
      proof: 'A hundred licensed uses settle with the carve enforced in-rail, and the audit agent reconciles all of them from the ledger alone.',
    },
    {
      name: 'Production',
      headline: 'The catalogue at full width, derivatives first-class.',
      runs: 'The house’s own frame when the catalogue justifies it: registry, TEG, EventStore, identity fabric.',
      agents: 'The full cast. Forks run through the lineage machinery; ancestors are paid by the same rail that pays anyone.',
      integrates: 'The asset pipeline registers works automatically; the CDN delivers against licences.',
      notYet: 'Cross-registry studios. The next phase makes a stranger’s derivative safe.',
      proof: 'A month of licensing in which no use settles without its carve, verified by the absence of a single manual royalty invoice.',
    },
    {
      name: 'Federation',
      headline: 'Strangers can build on the catalogue.',
      runs: 'Unchanged. Studios and clients connect their own registries.',
      agents: 'Foreign derivatives carry lineage home; reputations travel with DIDs.',
      integrates: 'Each new studio is a signed card and a license, not a contract negotiation about reporting.',
      notYet: 'Nothing structural. Growth is catalogue and corridors.',
      proof: 'A derivative built on a foreign registry is paid, and its ancestor is paid the same day without an email.',
    },
  ],
  sequenceTitle: 'One licensed use, from authorization to carve',
  sequence: `sequenceDiagram
  participant Cli as client-agent (their frame)
  participant Gate as licence gate
  participant XT as cross-registry pay
  participant TEG as settle + carve
  participant Cat as atelier-verse
  participant ES as provenance ledger
  Cli->>Gate: authorize use (apt_ token, 15 min TTL)
  Gate-->>Cli: authorized, single-purpose
  Cli->>XT: pay per use (idempotency key)
  XT->>TEG: settle, exactly once
  TEG->>Cat: royalty carved in-rail, basis points
  TEG-->>ES: use + split + licence, append-only
  Note over TEG: a settlement without the carve is not a settlement
  ES-->>ES: lineage recorded#59; ancestors accrue from descendants`,
  sizing: [
    { level: 'L1', what: 'Clients license works with accounts and agents only', containers: '0 of theirs' },
    { level: 'L2', what: 'The house runs catalogue and gates against a hosted seat', containers: 'agents only' },
    { level: 'L3', what: 'The house’s sovereign frame, provenance under its own law', containers: '~9, one VM up' },
  ],
}
