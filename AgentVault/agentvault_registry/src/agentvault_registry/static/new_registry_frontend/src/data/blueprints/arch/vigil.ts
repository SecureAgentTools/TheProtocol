import type { BlueprintDeep } from '../types'

// VIGIL deep architecture (§18) — clinical operations with the EHR kept
// deliberately on the read-side of a hard boundary.

export const deep: BlueprintDeep = {
  intro:
    'VIGIL deployed: the hospital group runs identity, authority and settlement on its own frame; staffing agencies and vendors act from theirs; and the clinical estate sits underneath on the read-side of a boundary that is the design, not a limitation of it. No patient record appears anywhere in this drawing, which is the point of the drawing. The trace replays one locum shift, roster gap to settlement.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE HOSPITAL GROUP’S FRAME', sub: 'identity, authority, settlement: no PHI', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'AGENCIES AND VENDORS', sub: 'their registries, their law', x: 530, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'money and identity, never records', x: 530, y: 455, w: 440, h: 115, kind: 'fabric' },
      { id: 'ze', label: 'CLINICAL ESTATE, READ-SIDE ONLY', sub: 'the EHR stays the EHR', x: 30, y: 625, w: 520, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'clinician', label: 'named clinician', sub: 'mandate, presence', kind: 'human', x: 140, y: 135 },
      { id: 'gate', label: 'authority gate', sub: 'ceilings, declared', kind: 'gate', x: 140, y: 253 },
      { id: 'sched', label: 'scheduling-agent', sub: 'fills theatre slots', kind: 'agent', x: 140, y: 375 },
      { id: 'teg', label: 'shift escrow', sub: 'funded before travel', kind: 'teg', x: 310, y: 255 },
      { id: 'logi', label: 'logistics-agent', sub: 'budgeted consumables', kind: 'agent', x: 310, y: 375 },
      { id: 'es', label: 'event ledger', sub: 'authority snapshots', kind: 'ledger', x: 310, y: 135 },
      { id: 'agency', label: 'agency-desk', sub: 'staffs the shift', kind: 'agent', x: 690, y: 255 },
      { id: 'a-reg', label: 'agency registry', sub: 'signed card', kind: 'registry', x: 860, y: 255 },
      { id: 'locum', label: 'locum-347', sub: 'reputation travelled', kind: 'agent', x: 690, y: 135 },
      { id: 'a-es', label: 'their ledger', sub: 'same shift', kind: 'ledger', x: 860, y: 135 },
      { id: 'xfer', label: 'cross-frame pay', sub: 'exactly-once', kind: 'teg', x: 740, y: 522 },
      { id: 'mesh', label: 'federation mesh', sub: 'peer cards, licenses', kind: 'registry', x: 900, y: 522 },
      { id: 'ehr', label: 'EHR (read-side)', sub: 'no PHI crosses', kind: 'external', x: 460, y: 692 },
      { id: 'roster', label: 'rostering system', sub: 'source of shifts', kind: 'external', x: 300, y: 692 },
    ],
    edges: [
      { id: 'e-roster', from: 'roster', to: 'sched', label: 'theatre gaps', dashed: true, labelT: 0.5 },
      { id: 'e-ehr', from: 'ehr', to: 'logi', label: 'reads only, no PHI', dashed: true, labelT: 0.5 },
      { id: 'e-check', from: 'sched', to: 'gate', label: 'ceiling, re-derived', dashed: true, labelT: 0.15 },
      { id: 'e-mandate', from: 'clinician', to: 'gate', label: 'presence signs', dashed: true },
      { id: 'e-escrow', from: 'sched', to: 'teg', label: 'escrow' },
      { id: 'e-emit', from: 'teg', to: 'es', label: 'snapshot', dashed: true, labelT: 0.5 },
      { id: 'e-buy', from: 'logi', to: 'teg', label: 'within budget', labelT: 0.5 },
      { id: 'e-xpay', from: 'teg', to: 'xfer', label: 'settle, keyed', curve: 82 },
      { id: 'e-credit', from: 'xfer', to: 'agency', label: 'credit exactly once', labelT: 0.5 },
      { id: 'e-assign', from: 'agency', to: 'locum' },
      { id: 'e-aemit', from: 'locum', to: 'a-es', dashed: true },
      { id: 'e-card', from: 'a-reg', to: 'mesh', label: 'signed card', dashed: true },
    ],
    script: [
      { edge: 'e-roster', dwellMs: 1300, caption: 'The rostering system shows Thursday’s theatre gaps. The protocol reads; it does not touch.' },
      { edge: 'e-check', dwellMs: 1400, caption: 'The scheduling agent moves to fill a locum shift. Its ceiling is checked on this very request.' },
      { edge: 'e-mandate', dwellMs: 1400, caption: 'The shift is above the ceiling, so a named clinician’s mandate stands behind it, presence-signed.' },
      { edge: 'e-escrow', dwellMs: 1400, caption: 'The shift escrows. The agency watches the money exist before anyone travels.' },
      { edge: 'e-emit', dwellMs: 1300, caption: 'Every action lands with an authority snapshot: who could do what, at that moment, provably.' },
      { edge: 'e-xpay', dwellMs: 1400, caption: 'The shift settles across frames with an idempotency key.' },
      { edge: 'e-credit', dwellMs: 1300, caption: 'The agency’s frame credits exactly once.' },
      { edge: 'e-assign', dwellMs: 1300, caption: 'The agency assigns locum-347. The reputation travelled with the DID, not with a PDF CV.' },
      { edge: 'e-aemit', dwellMs: 1200, caption: 'Their ledger writes the same shift. Two organisations, one record.' },
      { edge: 'e-buy', dwellMs: 1300, caption: 'Meanwhile logistics keeps consumables ahead of demand, inside a budget a human declared.' },
      { edge: 'e-ehr', dwellMs: 1500, caption: 'And the EHR? It was read, never written. No patient record exists on this drawing, by design.' },
    ],
    traceLabel: 'One locum shift, roster gap to settled, and no patient data anywhere.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'Draw the ceilings before any agent exists.',
      runs: 'Nothing in the estate. The authority model on paper: which roles, which ceilings, which escalations reach a named clinician.',
      agents: 'None. Operations and clinical governance argue about the ceilings, which is the productive argument.',
      integrates: 'Nothing. The EHR and the rostering system are untouched.',
      notYet: 'No agent acts. Nothing settles.',
      proof: 'One month of historical scheduling decisions re-told as ceiling checks, and governance agrees where every escalation would have landed.',
    },
    {
      name: 'Pilot',
      headline: 'One ward’s scheduling, ceilings live.',
      runs: 'A group-run registry seat, single VM. Read-side connectors to the roster only.',
      agents: 'One scheduling agent under declared ceilings; a named clinician holds the mandate; revocation is drilled weekly.',
      integrates: 'The rostering system, read-side. The EHR is not connected, and that is asserted, not assumed.',
      notYet: 'No money moves to external parties. Locum settlement is simulated against escrow.',
      proof: 'A month of pilot scheduling in which every action carries an authority snapshot and zero writes ever reached a clinical system.',
    },
    {
      name: 'Production',
      headline: 'Shifts settle for real; the boundary holds.',
      runs: 'The group’s frame: registry, TEG, EventStore, identity fabric, no PHI in any of them.',
      agents: 'Scheduling, logistics and claims roles under IRONKEY ceilings; escalations presence-signed; agents revocable in under a second.',
      integrates: 'Roster and procurement read-side; staffing agencies federate bilaterally; claims files carry authority snapshots.',
      notYet: 'Only contracted agencies are peers. Open marketplace staffing is a policy decision, not a technical step.',
      proof: 'An external review samples the ledger and finds an authority snapshot behind every action and no clinical data anywhere, because there is none to find.',
    },
    {
      name: 'Federation',
      headline: 'Agencies and vendors as peers.',
      runs: 'Unchanged. Each agency connects its registry or seat.',
      agents: 'Locum reputations travel with DIDs; vendor settlement rides milestone contracts.',
      integrates: 'Each new agency is a signed card and a license, not a portal login.',
      notYet: 'Nothing structural. Growth is corridors and ceilings.',
      proof: 'A locum staffed from a new agency works one shift with escrowed settlement and zero bilateral integration work.',
    },
  ],
  sequenceTitle: 'One escalated shift, gap to settlement',
  sequence: `sequenceDiagram
  participant Ros as roster (read-side)
  participant Sch as scheduling-agent
  participant Gate as authority gate
  participant Doc as named clinician
  participant TEG as shift escrow
  participant XT as cross-registry pay
  participant Agy as agency (their frame)
  Ros-->>Sch: theatre gap, read only
  Sch->>Gate: fill shift (ceiling check)
  Gate->>Doc: above ceiling: mandate required
  Doc-->>Gate: presence-signed approval
  Gate-->>Sch: clamped approval
  Sch->>TEG: escrow the shift
  TEG->>XT: settle (idempotency key)
  XT->>Agy: agency credited, exactly once
  Note over Gate,TEG: every event carries an authority snapshot#59; no PHI exists on this path`,
  sizing: [
    { level: 'L1', what: 'Agencies and vendors join with accounts and agents only', containers: '0 of theirs' },
    { level: 'L2', what: 'The group runs its agents against a hosted registry seat', containers: 'agents only' },
    { level: 'L3', what: 'The group’s sovereign frame, no PHI aboard by construction', containers: '~9, one VM up' },
  ],
}
