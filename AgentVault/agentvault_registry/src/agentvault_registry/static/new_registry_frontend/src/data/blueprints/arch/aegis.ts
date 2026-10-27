import type { BlueprintDeep } from '../types'

// AEGIS deep architecture (§18): a frozen method, fees escrowed per reading, and a season that three parties read
// from the same ledger (reworded 2026-10-26 like MOIRA: readings and verified events, no cover, no claims).

export const deep: BlueprintDeep = {
  intro:
    'AEGIS deployed: the analyst’s frame holds the frozen methods, the reading escrow and the event gate; the cooperative and its auditor read a signed replica on their own side; the weather arrives raw underneath and leaves the oracles as signed attestations. Nothing in this drawing is a report anyone files afterwards. The trace replays one season, publish to verified report to the three readers.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE ANALYST’S FRAME', sub: 'method, escrow, gates: yours', x: 30, y: 50, w: 530, h: 420, kind: 'frame' },
      { id: 'zp', label: 'THE READERS', sub: 'cooperative and auditor, read-only', x: 590, y: 50, w: 380, h: 340, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'signed mirrors travel here', x: 590, y: 430, w: 380, h: 170, kind: 'fabric' },
      { id: 'ze', label: 'WEATHER AND BACK OFFICE', sub: 'raw feeds in, evidence out', x: 30, y: 625, w: 940, h: 110, kind: 'external' },
    ],
    nodes: [
      { id: 'desk', label: 'risk-desk', sub: 'publishes, issues', kind: 'agent', x: 160, y: 130 },
      { id: 'tmpl', label: 'template gate', sub: 'publish = freeze', kind: 'gate', x: 160, y: 245 },
      { id: 'egate', label: 'event gate', sub: 'method vs readings', kind: 'gate', x: 330, y: 300 },
      { id: 'escrow', label: 'reading escrow', sub: 'funded at order', kind: 'teg', x: 480, y: 230 },
      { id: 'es', label: 'event ledger', sub: 'season, append-only', kind: 'ledger', x: 330, y: 405 },
      { id: 'oracle', label: 'oracle-dwd, -sat', sub: 'signed attestations', kind: 'agent', x: 160, y: 375 },
      { id: 'audwatch', label: 'auditor-watch', sub: 'reads the method', kind: 'agent', x: 745, y: 295 },
      { id: 'replica', label: 'signed replica', sub: 'read-only mirror', kind: 'registry', x: 895, y: 360 },
      { id: 'coopwatch', label: 'coop-watch', sub: 'reads all season', kind: 'agent', x: 745, y: 135 },
      { id: 'mirror', label: 'mirror relay', sub: 'signed events out', kind: 'registry', x: 690, y: 520 },
      { id: 'mesh', label: 'federation mesh', sub: 'peer cards, licenses', kind: 'registry', x: 865, y: 520 },
      { id: 'wx', label: 'DWD / satellite', sub: 'licensed, attested', kind: 'external', x: 465, y: 665 },
      { id: 'plan', label: 'planning tools', sub: 'plans stay here', kind: 'external', x: 690, y: 665 },
    ],
    edges: [
      { id: 'e-publish', from: 'desk', to: 'tmpl', label: 'publish v4', labelT: 0.42 },
      { id: 'e-bind', from: 'tmpl', to: 'escrow', label: 'order + fee', labelT: 0.51 },
      { id: 'e-terms', from: 'tmpl', to: 'egate', label: 'frozen method', dashed: true, labelT: 0.66, curve: 2 },
      { id: 'e-wx', from: 'wx', to: 'oracle', label: 'raw weather', dashed: true, labelT: 0.44, curve: -36 },
      { id: 'e-sign', from: 'oracle', to: 'egate', label: 'signed', curve: -4, labelT: 0.45 },
      { id: 'e-fire', from: 'egate', to: 'escrow', label: 'release', curve: 24, labelT: 0.52 },
      { id: 'e-emit', from: 'escrow', to: 'es', dashed: true, curve: -52 },
      { id: 'e-evidence', from: 'es', to: 'plan', label: 'evidence export', dashed: true, curve: 12, labelT: 0.53 },
      { id: 'e-mirror', from: 'es', to: 'mirror', label: 'signed mirror', dashed: true, labelT: 0.45 },
      { id: 'e-re', from: 'mirror', to: 'replica', label: 'same season', curve: 8, labelT: 0.33 },
      { id: 'e-read2', from: 'coopwatch', to: 'replica', dashed: true },
      { id: 'e-read1', from: 'audwatch', to: 'replica', dashed: true, curve: -10 },
      { id: 'e-card', from: 'mesh', to: 'replica', label: 'signed cards', dashed: true, labelT: 0.31 },
    ],
    script: [
      { edge: 'e-publish', dwellMs: 1400, caption: 'The risk desk publishes method v4. Publishing is an irreversible freeze.' },
      { edge: 'e-bind', dwellMs: 1400, caption: 'The cooperative orders a season of readings: the order copies the frozen method, and the fee waits in escrow, on the ledger.' },
      { edge: 'e-terms', dwellMs: 1300, caption: 'The event gate holds the frozen method. Nobody argues about a PDF, because there is no PDF.' },
      { edge: 'e-wx', dwellMs: 1200, caption: 'All season, the weather arrives raw.' },
      { edge: 'e-sign', dwellMs: 1400, caption: 'The oracles sign what they saw. An attestation has an identity, not just a value.' },
      { edge: 'e-fire', dwellMs: 1500, caption: '02:12, 14 June. Hail crosses Emsland. The readings meet the method; the gate issues the report and the escrow releases its fee.' },
      { edge: 'e-emit', dwellMs: 1400, caption: '61 verified reports land before the growers wake up. The 62nd is contested, so its fee stops in escrow and waits for the four-phase ruling.' },
      { edge: 'e-evidence', dwellMs: 1300, caption: 'The back office receives evidence, not spreadsheets to reconcile.' },
      { edge: 'e-mirror', dwellMs: 1300, caption: 'The season mirrors out as signed events.' },
      { edge: 'e-re', dwellMs: 1300, caption: 'The replica carries the same method, the same reports, the same refusals.' },
      { edge: 'e-read2', dwellMs: 1300, caption: 'The cooperative reads all season. Every number traces to a signed source.' },
      { edge: 'e-read1', dwellMs: 1400, caption: 'The auditor reads the same replica. One ledger, three readers, nothing to reconcile.' },
    ],
    traceLabel: 'One season: publish, order, hail, 61 verified reports, three readers.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'Your method, re-read as a schema.',
      runs: 'Nothing. One risk product redrawn as a template, an event table and a fee rule.',
      agents: 'None. The analysts argue about the event table, and that argument is the deliverable.',
      integrates: 'Nothing. Planning tools and the weather licences stay as they are.',
      notYet: 'Nothing is published, so nothing is frozen.',
      proof: 'One historic season replayed against the drafted method reproduces every event decision, including the contested one.',
    },
    {
      name: 'Pilot',
      headline: 'One district, real readings, pocket fees.',
      runs: 'A hosted registry seat, or a single-VM frame if the escrow must sit inside your walls from day one.',
      agents: 'risk-desk, two oracle agents with their own identities, event-gate. The auditor is not connected yet.',
      integrates: 'Licensed weather feeds into the oracles; orders flow in from the cooperative’s planning tool via the SDK.',
      notYet: 'Pocket limits. One product. Disputes are drilled, not yet real.',
      proof: 'A staged storm produces verified reports for a pilot district with no human in the release path, and the ledger shows every fee.',
    },
    {
      name: 'Production',
      headline: 'The method becomes a fact the cooperative watches.',
      runs: 'A sovereign frame in the analyst’s estate; the escrow and the season ledger live under your law.',
      agents: 'The full cast, plus coop-watch with read-only ceilings. The oracles attest under SPIFFE identities.',
      integrates: 'Orders flow continuously; the evidence chain exports to the back office instead of month-end reconciliation.',
      notYet: 'The auditor still reads exports. The next phase makes it a peer.',
      proof: 'The cooperative’s agent reads the season and its view never disagrees with the analyst’s books, because both are the same ledger.',
    },
    {
      name: 'Federation',
      headline: 'The auditor reads the replica, not an export.',
      runs: 'Unchanged. The auditor connects its own registry, or a seat.',
      agents: 'auditor-watch reads the signed replica of the season, all season.',
      integrates: 'Each new reader is a signed card and a licence. Nothing is exported by hand.',
      notYet: 'Nothing structural. New products are template versions.',
      proof: 'A season closes with the auditor citing the replica rather than an export, and no reconciliation audit is scheduled.',
    },
  ],
  sequenceTitle: 'One event, weather to verified report',
  sequence: `sequenceDiagram
  participant WX as weather feed
  participant Ora as oracle agents
  participant Gate as event gate
  participant TEG as reading escrow
  participant ES as event ledger
  participant Rep as signed replica
  WX->>Ora: raw readings, all season
  Ora->>Gate: signed attestations (SPIFFE identity)
  Gate->>Gate: readings vs frozen method (v4)
  Gate->>TEG: report issued, per district
  TEG-->>ES: fee released + logged, append-only
  ES-->>Rep: signed mirror update
  Rep-->>Rep: cooperative + auditor read, cannot write
  Note over TEG: a contested report's fee stops in escrow, four-phase dispute`,
  sizing: [
    { level: 'L1', what: 'Growers and planners join as accounts; readings land on their desks', containers: '0 of theirs' },
    { level: 'L2', what: 'The analyst runs oracles and gates against a hosted registry seat', containers: 'agents only' },
    { level: 'L3', what: 'The analyst’s sovereign frame: escrow and season ledger under its law', containers: '~9, one VM up' },
  ],
}
