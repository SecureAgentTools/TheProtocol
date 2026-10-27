import type { BlueprintDeep } from '../types'

// DEMETER deep architecture (§18) — lot 88-K from highland cooperative to
// Hamburg roaster, as a chain of signed handoffs with the money escrowed first.

export const deep: BlueprintDeep = {
  intro:
    'DEMETER deployed: the cooperative’s frame holds the forward agreement, the season escrow and the provenance chain; the buyer and the route’s attestors act from their side; the rainfall stations feed the oracle that arms the drought clause. Provenance here is not a claim printed on the bag; it is the chain itself, replayable by anyone the roaster hands the reference to. The trace replays lot 88-K, planting to receipt.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE COOPERATIVE’S FRAME', sub: 'agreement, escrow, chain', x: 30, y: 50, w: 440, h: 490, kind: 'frame' },
      { id: 'zp', label: 'THE BUYER AND THE ROUTE', sub: 'Hamburg, and every handoff between', x: 530, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'attestations and money cross here', x: 530, y: 455, w: 440, h: 115, kind: 'fabric' },
      { id: 'ze', label: 'THE PHYSICAL WORLD', sub: 'weather and steel, signed at the edges', x: 30, y: 625, w: 490, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'coop', label: 'coop-treasury', sub: 'members vote it', kind: 'agent', x: 140, y: 375 },
      { id: 'spine', label: 'forward agreement', sub: 'escrowed before planting', kind: 'gate', x: 310, y: 135 },
      { id: 'es', label: 'provenance chain', sub: 'replayable by anyone', kind: 'ledger', x: 140, y: 255 },
      { id: 'teg', label: 'season escrow', sub: 'visible all season', kind: 'teg', x: 310, y: 255 },
      { id: 'oracle', label: 'oracle-weather', sub: 'signs what fell', kind: 'agent', x: 140, y: 470 },
      { id: 'policy', label: 'drought clause', sub: 'frozen at signing', kind: 'gate', x: 310, y: 470 },
      { id: 'buyer', label: 'buyer-desk', sub: 'Hamburg, funds ahead', kind: 'agent', x: 690, y: 135 },
      { id: 'roaster', label: 'roaster-receipt', sub: 'signs arrival', kind: 'agent', x: 860, y: 135 },
      { id: 'mills', label: 'route attestors', sub: 'mill + exporter sign', kind: 'agent', x: 775, y: 375 },
      { id: 'b-es', label: 'their ledger', sub: 'same lot, same chain', kind: 'ledger', x: 775, y: 255 },
      { id: 'relay', label: 'handoff relay', sub: 'signed handoffs in', kind: 'registry', x: 900, y: 527 },
      { id: 'xfer', label: 'cross-frame pay', sub: 'exactly-once', kind: 'teg', x: 680, y: 527 },
      { id: 'wx', label: 'rain stations', sub: 'raw feeds attest', kind: 'external', x: 260, y: 692 },
      { id: 'container', label: 'container + seal', sub: 'seal attests custody', kind: 'external', x: 450, y: 692 },
    ],
    edges: [
      { id: 'e-forward', from: 'buyer', to: 'spine', label: 'forward agreement', labelT: 0.77, curve: 4 },
      { id: 'e-fund', from: 'buyer', to: 'xfer', label: 'funds the season', curve: -30 },
      { id: 'e-landx', from: 'xfer', to: 'teg', label: 'visible all season', curve: -74, labelT: 0.77 },
      { id: 'e-handoff', from: 'mills', to: 'relay', label: 'weighed, signed', labelT: 0.49 },
      { id: 'e-seal', from: 'container', to: 'relay', label: 'seal attests', dashed: true, labelT: 0.5, curve: 6 },
      { id: 'e-receipt', from: 'roaster', to: 'relay', label: 'receipt, signed', labelT: 0.49 },
      { id: 'e-relay', from: 'relay', to: 'spine', label: 'principal checked', curve: 14, labelT: 0.49 },
      { id: 'e-release', from: 'spine', to: 'teg', label: 'staged release', labelT: 0.69 },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true },
      { id: 'e-rain', from: 'wx', to: 'oracle', label: 'raw rainfall', dashed: true, labelT: 0.45 },
      { id: 'e-sign', from: 'oracle', to: 'policy', label: 'signed', dashed: true, labelT: 0.5 },
      { id: 'e-trigger', from: 'policy', to: 'teg', label: 'trigger', labelT: 0.5 },
      { id: 'e-div', from: 'coop', to: 'teg', label: 'distributions, voted', labelT: 0.49 },
      { id: 'e-bemit', from: 'buyer', to: 'b-es', dashed: true },
    ],
    script: [
      { edge: 'e-forward', dwellMs: 1400, caption: 'The forward agreement is escrowed before planting. The cooperative watches the money exist all season.' },
      { edge: 'e-fund', dwellMs: 1300, caption: 'The buyer funds from Hamburg.' },
      { edge: 'e-landx', dwellMs: 1300, caption: 'The escrow lands on the cooperative’s frame, exactly once, visible to the members.' },
      { edge: 'e-handoff', dwellMs: 1500, caption: 'The wet mill weighs and signs. The dry mill signs. The exporter signs. Four tonnes become a chain.' },
      { edge: 'e-seal', dwellMs: 1300, caption: 'The container attests its seal.' },
      { edge: 'e-receipt', dwellMs: 1300, caption: 'In Hamburg, the roaster signs receipt of lot 88-K.' },
      { edge: 'e-relay', dwellMs: 1300, caption: 'Every signed handoff couriers home through the fabric.' },
      { edge: 'e-release', dwellMs: 1400, caption: 'The agreement releases in stages as the handoffs accumulate.' },
      { edge: 'e-emit', dwellMs: 1300, caption: 'The chain is the provenance. Anyone the roaster hands the reference to can replay it.' },
      { edge: 'e-rain', dwellMs: 1300, caption: 'The drought year: the rainfall stations report what fell, raw.' },
      { edge: 'e-sign', dwellMs: 1300, caption: 'The oracle signs the readings. An attestation has an identity.' },
      { edge: 'e-trigger', dwellMs: 1500, caption: 'The drought clause reads the signed rainfall against its frozen terms, and the buyer’s advance reaches the growers from the season escrow before a bank would have finished asking for collateral.' },
      { edge: 'e-div', dwellMs: 1400, caption: 'The season’s premium lands as a recorded distribution the members voted, not a promise from the chairman.' },
    ],
    traceLabel: 'Lot 88-K: escrowed before planting, signed at every handoff, paid in stages.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'One lot’s journey, re-told as signatures.',
      runs: 'Nothing. Last season’s best-documented lot redrawn as handoffs, weights and release stages.',
      agents: 'None. The cooperative and the buyer argue about which handoffs deserve a signature. Settling that on paper is cheaper than settling it at sea.',
      integrates: 'Nothing. Scales, mills and logistics stay exactly as they are.',
      notYet: 'No escrow, no chain, no oracle.',
      proof: 'One historical lot re-expressed as a chain, and both ends agree the chain matches the paper trail it replaces.',
    },
    {
      name: 'Pilot',
      headline: 'One lot, real escrow, phone-borne attestors.',
      runs: 'A registry seat for the cooperative, or a single-VM frame at the exporter. The buyer connects from its side.',
      agents: 'coop-treasury, buyer-desk, two handoff attestors on phones at the mills.',
      integrates: 'The scales feed the attestors; the cold chain keeps its own systems.',
      notYet: 'One lot. The drought clause is modelled, not signed. Distributions are calculated, not yet paid on-rails.',
      proof: 'One container ships with every physical handoff signed within a day of the paper equivalent, and the staged releases match the agreement to the unit.',
    },
    {
      name: 'Production',
      headline: 'The season on rails, the clause armed.',
      runs: 'A registry per exporter or cooperative federation, wherever the power is reliable.',
      agents: 'The full cast; oracles under their own identities; the drought clause signed with frozen terms.',
      integrates: 'Scales, moisture meters and seals feed attestations; buyers fund forward agreements as the norm.',
      notYet: 'Certification claims. The chain proves custody as signed, and what was true before the first signature stays a physical-world question.',
      proof: 'A drought-year advance reaches grower accounts from oracle-signed readings with no argument about what fell, and the season’s distribution pays out as recorded, member-voted transactions.',
    },
    {
      name: 'Federation',
      headline: 'Every buyer, one grammar of custody.',
      runs: 'Unchanged. Buyers and route operators bring frames or seats.',
      agents: 'A cooperative’s delivery record travels with its DID to the next buyer.',
      integrates: 'Each new buyer or port is a signed card and a licence.',
      notYet: 'Nothing structural. Growth is lots and corridors.',
      proof: 'A new buyer funds a forward agreement with a cooperative it has never met, on the strength of a chain it can replay.',
    },
  ],
  sequenceTitle: 'One handoff, weighbridge to release',
  sequence: `sequenceDiagram
  participant Mill as wet mill attestor
  participant Fab as federation fabric
  participant FA as forward agreement (coop frame)
  participant TEG as season escrow
  participant ES as provenance chain
  participant Roa as roaster (Hamburg)
  Mill->>Fab: handoff signed (weight, moisture)
  Fab->>FA: relayed, principal checked
  FA->>TEG: staged release
  TEG-->>ES: handoff + release, append-only
  Roa->>Fab: receipt signed at arrival
  Fab->>FA: final stage releases
  ES-->>Roa: the chain, replayable by reference
  Note over TEG: the drought clause releases the advance on oracle-signed rainfall`,
  sizing: [
    { level: 'L1', what: 'Growers and small mills join as accounts with phone attestors', containers: '0 of theirs' },
    { level: 'L2', what: 'An exporter runs attestor and treasury agents against a seat', containers: 'agents only' },
    { level: 'L3', what: 'A frame per exporter or cooperative federation', containers: '~9, one VM up' },
  ],
}
