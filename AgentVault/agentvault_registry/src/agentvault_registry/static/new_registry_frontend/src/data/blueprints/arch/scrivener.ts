import type { BlueprintDeep } from '../types'

// SCRIVENER deep architecture (§18) — engagements as frozen templates plus an
// evidence chain, for a regulated firm.

export const deep: BlueprintDeep = {
  intro:
    'SCRIVENER deployed: the firm’s frame holds the templates, the escrow and the evidence chain; the client acts from its own registry; the fabric couriers signed bytes between them. The partner’s mandate sits where the money moves, and the document system receives evidence instead of producing archaeology. The trace replays one engagement from matter-open to evidence chain.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE FIRM’S FRAME', sub: 'templates, escrow, evidence: yours', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zc', label: 'CLIENT’S REGISTRY', sub: 'their side of the letter', x: 530, y: 50, w: 440, h: 250, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'exact bytes, both ways', x: 530, y: 435, w: 440, h: 165, kind: 'fabric' },
      { id: 'ze', label: 'THE FIRM’S SYSTEMS', sub: 'DMS and practice management', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'intake', label: 'intake-clerk', sub: 'instantiates', kind: 'agent', x: 230, y: 375 },
      { id: 'template', label: 'template gate', sub: 'published = frozen', kind: 'gate', x: 400, y: 375 },
      { id: 'es', label: 'evidence chain', sub: 'append-only', kind: 'ledger', x: 110, y: 135 },
      { id: 'teg', label: 'TEG escrow', sub: 'fees by milestone', kind: 'teg', x: 400, y: 255 },
      { id: 'partner', label: 'partner', sub: 'mandate above 5,000', kind: 'human', x: 400, y: 135 },
      { id: 'qa', label: 'qa-reviewer', sub: 'verify only', kind: 'agent', x: 200, y: 255 },
      { id: 'client', label: 'client-desk', sub: 'accepts, funds', kind: 'agent', x: 750, y: 235 },
      { id: 'c-es', label: 'their mirror', sub: 'same engagement', kind: 'ledger', x: 610, y: 135 },
      { id: 'relay', label: 'contract relay', sub: 'signed bytes', kind: 'registry', x: 700, y: 550 },
      { id: 'xfer', label: 'cross-registry', sub: 'exactly-once', kind: 'teg', x: 880, y: 510 },
      { id: 'dms', label: 'DMS / documents', sub: 'files never move', kind: 'external', x: 200, y: 692 },
      { id: 'pm', label: 'practice mgmt', sub: 'matters stay here', kind: 'external', x: 350, y: 692 },
    ],
    edges: [
      { id: 'e-pm', from: 'pm', to: 'intake', label: 'matter opened', dashed: true, labelT: 0.55 },
      { id: 'e-inst', from: 'intake', to: 'template', label: 'instantiate' },
      { id: 'e-offer', from: 'template', to: 'relay', label: 'offer, signed', labelT: 0.21, curve: 3 },
      { id: 'e-accept', from: 'relay', to: 'client', label: 'exact bytes', curve: -3, labelT: 0.48 },
      { id: 'e-fund', from: 'client', to: 'xfer', label: 'fund milestone', labelT: 0.6 },
      { id: 'e-escrow', from: 'xfer', to: 'teg', label: 'escrow lands home', labelT: 0.63, curve: -12 },
      { id: 'e-verify', from: 'qa', to: 'es', dashed: true },
      { id: 'e-mandate', from: 'partner', to: 'teg', label: 'release, presence', labelT: 0.42 },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true },
      { id: 'e-mirror', from: 'es', to: 'c-es', label: 'signed mirror', dashed: true, curve: -72, labelT: 0.45 },
      { id: 'e-evidence', from: 'es', to: 'dms', label: 'chain exports', dashed: true, labelT: 0.55 },
    ],
    script: [
      { edge: 'e-pm', dwellMs: 1300, caption: 'A matter opens in practice management, where matters already open.' },
      { edge: 'e-inst', dwellMs: 1400, caption: 'The clerk instantiates the engagement from a published template. Published means frozen.' },
      { edge: 'e-offer', dwellMs: 1400, caption: 'The letter crosses as signed bytes, not as an attachment.' },
      { edge: 'e-accept', dwellMs: 1400, caption: 'The client accepts the exact bytes. There is no quiet rewrite of clause seven.' },
      { edge: 'e-fund', dwellMs: 1400, caption: 'Milestone one funds from the client’s frame.' },
      { edge: 'e-escrow', dwellMs: 1400, caption: 'The escrow lands on the engagement’s home frame, exactly once.' },
      { edge: 'e-verify', dwellMs: 1300, caption: 'QA verifies the deliverable. The verification is itself evidence.' },
      { edge: 'e-mandate', dwellMs: 1500, caption: 'Above threshold, the partner’s mandate releases: named, present, recorded.' },
      { edge: 'e-emit', dwellMs: 1200, caption: 'The release is one append-only event.' },
      { edge: 'e-mirror', dwellMs: 1400, caption: 'The client’s mirror carries the same chain. Both sides hold the truth.' },
      { edge: 'e-evidence', dwellMs: 1400, caption: 'The chain exports to the DMS. Discovery becomes a query, not archaeology.' },
    ],
    traceLabel: 'One engagement, template to evidence chain.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'Read your own letters as schemas.',
      runs: 'Nothing. Two of your standard engagement letters redrawn as terms schemas and milestones.',
      agents: 'None. Partners argue about the schema, which is the productive argument.',
      integrates: 'Nothing. The DMS and practice management are untouched.',
      notYet: 'No template is published, so nothing is frozen.',
      proof: 'One real historic engagement re-expressed as template + milestones with no clause left unrepresentable.',
    },
    {
      name: 'Pilot',
      headline: 'One engagement class, live, small.',
      runs: 'A hosted registry seat, or a single-VM frame if client confidentiality demands your walls.',
      agents: 'intake-clerk, one associate agent, qa-reviewer; the partner holds a pilot-ceiling mandate.',
      integrates: 'Matter-open events from practice management; evidence exports to a supervised DMS folder.',
      notYet: 'One template only; releases capped; clients join as accounts, not registries.',
      proof: 'Three engagements run template-to-release with the evidence chain accepted by your own risk partner.',
    },
    {
      name: 'Production',
      headline: 'The template library becomes the firm’s law.',
      runs: 'Sovereign frame in the firm’s estate; versioned template library; the evidence chain is the record.',
      agents: 'Full cast; associates submit, QA verifies, the partner mandate gates releases above threshold with presence.',
      integrates: 'DMS receives the chain continuously; billing reads settled milestones instead of timesheets arguing with invoices.',
      notYet: 'Cross-registry clients. The next phase makes the client a peer, not just an account.',
      proof: 'An external audit samples engagements and reconstructs each from the chain alone, without one email produced.',
    },
    {
      name: 'Federation',
      headline: 'Clients and counsel as peers.',
      runs: 'Unchanged. Corporate clients connect their own registries; opposing counsel can too.',
      agents: 'Client desks act from their own frames; the letter is the same bytes on both.',
      integrates: 'Each new peer is a signed card and a license.',
      notYet: 'Nothing structural. Growth is template instantiations.',
      proof: 'A contested engagement survives discovery with both parties citing the same chain, because there is only one.',
    },
  ],
  sequenceTitle: 'One release, submission to evidence',
  sequence: `sequenceDiagram
  participant Assoc as associate agent
  participant QA as qa-reviewer
  participant Gate as partner mandate
  participant TEG as firm TEG escrow
  participant ES as evidence chain
  participant Cli as client mirror
  Assoc->>QA: milestone submitted
  QA-->>ES: verification recorded
  QA->>Gate: release requested (above threshold)
  Gate->>TEG: release with presence proof
  TEG-->>ES: release event, append-only
  ES-->>Cli: signed mirror update
  ES-->>ES: chain grows#59; discovery is a query`,
  sizing: [
    { level: 'L1', what: 'Clients join engagements with accounts and agents only', containers: '0 of theirs' },
    { level: 'L2', what: 'The firm runs agents against a hosted registry seat', containers: 'agents only' },
    { level: 'L3', what: 'The firm runs its sovereign frame; the chain lives under its walls', containers: '~9, one VM up' },
  ],
}
