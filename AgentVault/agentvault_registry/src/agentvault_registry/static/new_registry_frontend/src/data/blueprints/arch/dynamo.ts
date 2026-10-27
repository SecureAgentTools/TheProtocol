import type { BlueprintDeep } from '../types'

// DYNAMO deep architecture (§18) — a device fleet with economic identities,
// per-reading settlement, and a kill switch that outruns the firmware.

export const deep: BlueprintDeep = {
  intro:
    'DYNAMO at deployment scale: your grid frame holds the identity fabric, the per-reading settlement and the kill switch; a neighbouring operator runs its own frame for roaming; the fabric between them settles corridors without a clearing house. The field devices live below, enrolled upward. The trace replays one evening peak, readings to revocation.',
  arch: {
    zones: [
      { id: 'zf', label: 'YOUR GRID FRAME', sub: 'identity, settlement, revocation: one region', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'NEIGHBOUR OPERATOR', sub: 'their frame, their tariffs', x: 530, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'roaming without a clearing house', x: 530, y: 440, w: 440, h: 150, kind: 'fabric' },
      { id: 'ze', label: 'THE FIELD AND THE MARKET', sub: 'metering heads in, bids out. SCADA stays out of scope', x: 30, y: 625, w: 940, h: 110, kind: 'external' },
    ],
    nodes: [
      { id: 'operator', label: 'site operator', sub: 'holds kill switch', kind: 'human', x: 100, y: 165 },
      { id: 'es', label: 'event ledger', sub: 'each reading, signed', kind: 'ledger', x: 385, y: 95 },
      { id: 'revoke', label: 'IRONHAND revoke', sub: 'under 500ms', kind: 'gate', x: 100, y: 290 },
      { id: 'settle', label: 'per-read settle', sub: 'fee carved in-rail', kind: 'teg', x: 315, y: 185 },
      { id: 'fab', label: 'identity fabric', sub: 'SVIDs, short TTL', kind: 'gate', x: 190, y: 345 },
      { id: 'subops', label: 'substation-ops', sub: 'L4: one substation', kind: 'agent', x: 385, y: 340 },
      { id: 'p-teg', label: 'their TEG', sub: 'credits exactly once', kind: 'teg', x: 730, y: 170 },
      { id: 'p-reg', label: 'their registry', sub: 'signed card', kind: 'registry', x: 890, y: 290 },
      { id: 'p-roam', label: 'roaming-desk', sub: 'confirms sessions', kind: 'agent', x: 885, y: 180 },
      { id: 'p-es', label: 'their ledger', sub: 'same truth', kind: 'ledger', x: 890, y: 85 },
      { id: 'xfer', label: 'roaming settle', sub: 'idempotency-keyed', kind: 'teg', x: 720, y: 520 },
      { id: 'mesh', label: 'federation mesh', sub: 'peer cards, licenses', kind: 'registry', x: 895, y: 520 },
      { id: 'fleet', label: 'inverter-7741', sub: '+ fleet, readings up', kind: 'external', x: 570, y: 695 },
      { id: 'market', label: 'market operator', sub: 'positions as today', kind: 'external', x: 730, y: 695 },
    ],
    edges: [
      { id: 'e-read', from: 'fleet', to: 'fab', label: 'signed readings', curve: 12, labelT: 0.3 },
      { id: 'e-scope', from: 'subops', to: 'fab', label: 'L4: one shift', dashed: true, curve: 10, labelT: 0.47 },
      { id: 'e-auth', from: 'fab', to: 'settle' },
      { id: 'e-emit', from: 'settle', to: 'es', label: 'one event', dashed: true, labelT: 0.43 },
      { id: 'e-bid', from: 'subops', to: 'market', label: 'bids the peak', dashed: true, labelT: 0.34 },
      { id: 'e-card', from: 'p-reg', to: 'mesh', label: 'signed card', dashed: true, curve: 2, labelT: 0.47 },
      { id: 'e-xset', from: 'settle', to: 'xfer', label: 'roaming leg, keyed', curve: 60, labelT: 0.6 },
      { id: 'e-credit', from: 'xfer', to: 'p-teg', label: 'credit exactly once', curve: -8, labelT: 0.49 },
      { id: 'e-pleg', from: 'p-teg', to: 'p-roam', curve: 10 },
      { id: 'e-pemit', from: 'p-roam', to: 'p-es', dashed: true },
      { id: 'e-kill', from: 'operator', to: 'revoke', label: 'one action', dashed: true, labelT: 0.55 },
      { id: 'e-dead', from: 'revoke', to: 'fab' },
    ],
    script: [
      { edge: 'e-read', dwellMs: 1300, caption: 'A reading arrives from the field, signed by the device’s own short-lived identity.' },
      { edge: 'e-scope', dwellMs: 1400, caption: 'The substation desk holds a capability permit scoped to one substation, one shift. Blast radius is a data structure.' },
      { edge: 'e-auth', dwellMs: 1300, caption: 'The identity fabric admits the reading: a live SVID, inside its scope. Settlement follows in fractions of a cent.' },
      { edge: 'e-emit', dwellMs: 1200, caption: 'Every reading and its fee land on the ledger, append-only.' },
      { edge: 'e-bid', dwellMs: 1300, caption: 'The site desk bids the evening peak into the market. A bid is not a settlement.' },
      { edge: 'e-card', dwellMs: 1300, caption: 'Roaming exists because two operators exchanged signed cards and licenses, not API keys.' },
      { edge: 'e-xset', dwellMs: 1400, caption: 'A roaming session settles across frames with an idempotency key. A retry can never double it.' },
      { edge: 'e-credit', dwellMs: 1400, caption: 'The neighbour frame credits exactly once. No clearing house sits between them.' },
      { edge: 'e-pleg', dwellMs: 1200, caption: 'Their roaming desk confirms the session.' },
      { edge: 'e-pemit', dwellMs: 1200, caption: 'Their ledger writes the same settlement. Two operators, one truth.' },
      { edge: 'e-kill', dwellMs: 1400, caption: '17:42. A meter reports impossible numbers. The operator acts once.' },
      { edge: 'e-dead', dwellMs: 1500, caption: 'Revocation rides the event stream. The identity is dead in under half a second, the balance freezes, and cross-frame receipt is blocked by the same action.' },
    ],
    traceLabel: 'One evening peak: readings, roaming, and a kill switch.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'No device changes yet.',
      runs: 'Nothing in your estate. One meter’s history and a workstation.',
      agents: 'None. Your grid team reads a live ledger and walks the identity model on paper.',
      integrates: 'Nothing. Metering heads, the market interface and SCADA stay exactly as they are.',
      notYet: 'No device holds an identity. No money moves.',
      proof: 'One meter’s month re-told as per-reading settlements, and the sum matches the billing system to the cent.',
    },
    {
      name: 'Pilot',
      headline: 'One substation, fifty devices, a working kill switch.',
      runs: 'One hosted registry seat, or a single-VM frame if policy requires your walls. Fifty devices enroll through the identity fabric.',
      agents: 'substation-ops under an L4 shift permit; grid-settlement paying per reading; the site operator holds the kill switch.',
      integrates: 'Metering heads feed readings in. The market interface stays read-only.',
      notYet: 'Pocket ceilings. No roaming. Revocation drills run against pilot devices only.',
      proof: 'A revocation drill kills a live pilot device in under half a second, measured at the gate, and its next reading settles nothing.',
    },
    {
      name: 'Production',
      headline: 'A region’s fleet, enrolled, settling, revocable.',
      runs: 'One sovereign frame per operator region: registry, TEG, EventStore, identity fabric.',
      agents: 'The full cast. The fleet enrolls itself through the fabric; nobody hand-provisions a hundred thousand certificates.',
      integrates: 'Metering heads and the market operator interface. SCADA stays out of scope, deliberately and in writing.',
      notYet: 'No cross-operator roaming. The federation license is held but dark.',
      proof: 'A full region settles per reading for a month with the supply delta at zero and every settlement attributable to a live SVID.',
    },
    {
      name: 'Federation',
      headline: 'Roaming corridors without a clearing house.',
      runs: 'Unchanged infrastructure. Peer operators.',
      agents: 'Unchanged cast; per-corridor spend policies bound what each roaming partner can reach.',
      integrates: 'Each roaming partner is a signed card and a license, not a settlement bureau.',
      notYet: 'Nothing on this path requires new software.',
      proof: 'Two operators settle a roaming corridor for a quarter with zero reconciliation calls between their back offices.',
    },
  ],
  sequenceTitle: 'One reading, and the revocation that outruns the next one',
  sequence: `sequenceDiagram
  participant Dev as inverter-7741
  participant Fab as identity fabric
  participant TEG as your TEG
  participant ES as event ledger
  participant Op as site operator
  Dev->>Fab: signed reading (SVID, short TTL)
  Fab->>TEG: A2A authorize + settle per reading
  TEG-->>ES: reading + fee, append-only
  Op->>Fab: revoke device (one action)
  Note over Fab: revocation over the event stream, under 500ms
  Dev->>Fab: next reading
  Fab-->>Dev: no identity to be
  Fab-->>ES: refusal recorded, balance frozen in place`,
  sizing: [
    { level: 'L1', what: 'Devices and site agents live on an existing registry', containers: '0 of yours' },
    { level: 'L2', what: 'Run your site desks via the SDK, registry hosted', containers: 'your agents only' },
    { level: 'L3', what: 'A sovereign frame per operator region, fleet enrolled through the fabric', containers: 'one frame per region' },
  ],
}
