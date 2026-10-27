import type { BlueprintDeep } from '../types'

// ZEPHYR deep architecture (§18, frontier wave 2026-09-25): one flight booked across three frames, the
// fleet's, the city's and the vertiport's, paid on the pad's signed arrival; one drone grounded in one action.

export const deep: BlueprintDeep = {
  intro:
    'ZEPHYR deployed: the fleet’s frame holds dispatch, the flight escrow, the drones’ identities and the record; Marholm sells corridor slots from its own frame and the vertiport sells pad time from its own; traffic management, the hangar and the permits stay with the authorities and operators that run them today. The trace replays one flight, slot MH-C4-0710, from booking to signed arrival, and then one grounding.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE FLEET’S FRAME', sub: 'dispatch, escrow, identities, record', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'MARHOLM AND ITS VERTIPORT', sub: 'the city’s frame and the vertiport’s', x: 530, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'arrivals and money cross here', x: 530, y: 455, w: 440, h: 115, kind: 'fabric' },
      { id: 'ze', label: 'THE SKY AND THE HANGAR', sub: 'traffic management: out of scope', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'dispatch', label: 'fleet-dispatch', sub: 'books slot and pad', kind: 'agent', x: 140, y: 135 },
      { id: 'corridor', label: 'corridor gate', sub: 'permit: two cities', kind: 'gate', x: 310, y: 133 },
      { id: 'es', label: 'flight ledger', sub: 'flights, replayable', kind: 'ledger', x: 140, y: 255 },
      { id: 'teg', label: 'flight escrow', sub: 'held at booking', kind: 'teg', x: 310, y: 255 },
      { id: 'lead', label: 'Tove Nyland', sub: 'maintenance lead', kind: 'human', x: 140, y: 375 },
      { id: 'idf', label: 'identity fabric', sub: 'drone certificates', kind: 'registry', x: 310, y: 375 },
      { id: 'slots', label: 'slots-marholm', sub: 'sells corridor slots', kind: 'agent', x: 690, y: 135 },
      { id: 'c-es', label: 'city ledger', sub: 'the same flight', kind: 'ledger', x: 860, y: 135 },
      { id: 'pad', label: 'pad-CL-2', sub: 'signs each arrival', kind: 'agent', x: 860, y: 255 },
      { id: 'relay', label: 'arrival relay', sub: 'courier only', kind: 'registry', x: 900, y: 520 },
      { id: 'xfer', label: 'cross-frame pay', sub: 'exactly once', kind: 'teg', x: 720, y: 520 },
      { id: 'hangar', label: 'hangar system', sub: 'inspections as today', kind: 'external', x: 250, y: 692 },
      { id: 'drones', label: 'drone fleet', sub: '140 onboard agents', kind: 'external', x: 400, y: 692 },
    ],
    edges: [
      { id: 'e-certs', from: 'idf', to: 'drones', label: 'certificates', dashed: true },
      { id: 'e-book', from: 'dispatch', to: 'corridor' },
      { id: 'e-escrow', from: 'corridor', to: 'teg', label: 'escrowed', labelT: 0.78 },
      { id: 'e-slot', from: 'corridor', to: 'slots', label: 'slot MH-C4-0710', labelT: 0.25 },
      { id: 'e-arrive', from: 'pad', to: 'relay', label: 'arrival, signed' },
      { id: 'e-relay', from: 'relay', to: 'teg', label: 'principal checked', curve: 60, labelT: 0.45 },
      { id: 'e-release', from: 'teg', to: 'xfer', label: 'release', curve: 75, labelT: 0.5 },
      { id: 'e-paid', from: 'xfer', to: 'slots', label: 'paid at home' },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true },
      { id: 'e-cemit', from: 'slots', to: 'c-es', dashed: true },
      { id: 'e-inspect', from: 'hangar', to: 'lead', label: 'hub cracked', dashed: true },
      { id: 'e-ground', from: 'lead', to: 'idf' },
    ],
    script: [
      { edge: 'e-certs', dwellMs: 1400, caption: 'Every drone flies on its own certificate from the fleet’s identity fabric, and certificates live hours, not years.' },
      { edge: 'e-book', dwellMs: 1400, caption: '06:52. fleet-dispatch books slot MH-C4-0710 and pad 2 for drone ZP-0419, carrying blood samples from the north clinic.' },
      { edge: 'e-escrow', dwellMs: 1400, caption: 'The corridor gate checks the permit first: Marholm is on it. Ten units are escrowed at booking, on the fleet’s frame.' },
      { edge: 'e-slot', dwellMs: 1400, caption: 'The booking reaches Marholm’s slot service on the city’s own frame, which holds corridor 4 for the 07:10 window.' },
      { edge: 'e-arrive', dwellMs: 1500, caption: '07:23. ZP-0419 lands on pad 2, and the pad agent signs the arrival with its own identity.' },
      { edge: 'e-relay', dwellMs: 1400, caption: 'The signed arrival crosses the fabric. The relaying peer is a courier; the pad agent is the party to the booking.' },
      { edge: 'e-release', dwellMs: 1300, caption: 'On that signature and nothing else, the escrow releases, exactly once.' },
      { edge: 'e-paid', dwellMs: 1400, caption: 'Four units reach the city’s slot service and six the vertiport, each on its own frame, each exactly once.' },
      { edge: 'e-emit', dwellMs: 1300, caption: 'The fleet’s ledger keeps the booking, the arrival and both payments, append-only.' },
      { edge: 'e-cemit', dwellMs: 1200, caption: 'The city’s ledger records the same flight under the same keys.' },
      { edge: 'e-inspect', dwellMs: 1400, caption: '11:40. ZP-0388’s post-flight inspection, recorded in the hangar system as today, finds a cracked propeller hub.' },
      { edge: 'e-ground', dwellMs: 1600, caption: 'Tove Nyland grounds it with one action: identity revoked in under 500ms, account and cross-frame receipts blocked.' },
    ],
    traceLabel: 'One flight booked, landed and paid; one drone grounded.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'One week of flights, re-read as bookings.',
      runs: 'Nothing. One week of one fleet’s flights in one city, redrawn as slots, pads, escrows and signed arrivals.',
      agents: 'None. The fleet, the vertiport and the city office settle what a signed arrival must contain while it is still a document.',
      integrates: 'Nothing. The traffic management supplier, the fleet systems and the pad calendar stay exactly as they are.',
      notYet: 'No escrow exists. No drone holds an identity on the network.',
      proof: 'The week replays on paper, and the fleet, the vertiport and the city agree on where every booking, every payment and every refusal lands.',
    },
    {
      name: 'Pilot',
      headline: 'One corridor, one pad, twenty drones.',
      runs: 'A hosted registry seat for the fleet. The city’s slot desk and the vertiport join as accounts; nobody runs a frame yet.',
      agents: 'Dispatch, one pad agent and twenty drone agents, each with its own certificate. The maintenance lead holds the grounding action.',
      integrates: 'The pad agent signs from the vertiport’s landing sensors; each booking carries the traffic management supplier’s flight reference.',
      notYet: 'One city, one currency, pocket budgets. Ostervik is not on the permit yet.',
      proof: 'A grounding drill revokes a live pilot drone in under half a second, measured at the slot service, and its next booking moves nothing.',
    },
    {
      name: 'Production',
      headline: 'Each party on its own frame.',
      runs: 'Marholm’s frame, the vertiport’s and the fleet’s: registry, TEG, event store, identity fabric, each on its owner’s hardware.',
      agents: 'The full cast: dispatch, 140 drone agents, one agent per pad, the city’s slot service, and the grounding action live.',
      integrates: 'Hangar inspection records drive the grounding action; the pad calendar and the permit list feed their agents.',
      notYet: 'A second city. One city proves itself first.',
      proof: 'A month of flights settles with the supply delta at zero, and every payment on the ledger matches a signed arrival.',
    },
    {
      name: 'Federation',
      headline: 'Cities federate; fleets fly them.',
      runs: 'Unchanged. Ostervik stands up its own frame and federates with Marholm, the vertiports and the fleet.',
      agents: 'Dispatch gains Ostervik on its permit once the authority approves that corridor; each drone’s record travels with its identity.',
      integrates: 'Each new city is a signed card and a licence, not a new portal.',
      notYet: 'Nothing structural. Growth is cities, corridors and pads.',
      proof: 'A second city sells its first slot to the fleet in its first week, and a booking toward a city with no permit is refused on the record.',
    },
  ],
  sequenceTitle: 'One flight, booking to signed arrival',
  sequence: `sequenceDiagram
  participant Dis as fleet-dispatch
  participant Gate as corridor gate
  participant Slot as slots-marholm (city frame)
  participant TEG as flight escrow (fleet frame)
  participant Pad as pad-CL-2 (vertiport frame)
  participant ES as flight ledger
  Dis->>Gate: slot MH-C4-0710 + pad 2, 10 units
  Gate->>Slot: Marholm is on the permit: book corridor 4
  Slot-->>Gate: held for the 07:10 window
  Gate->>TEG: escrow 10 units at booking
  Pad->>TEG: ZP-0419 arrived at 07:23, signed
  TEG-->>Slot: 4 units, exactly once
  TEG-->>Pad: 6 units to the vertiport, exactly once
  TEG-->>ES: booking, arrival and payments, append-only
  Note over Gate: a slot in Tallvik is refused before any escrow
  Note over ES: a grounded drone's bookings are refusals on the record`,
  sizing: [
    { level: 'L1', what: 'Vertiports and small fleets join with accounts and agents only', containers: '0 of theirs' },
    { level: 'L2', what: 'A fleet runs dispatch and its drone agents against a hosted seat', containers: 'agents only' },
    { level: 'L3', what: 'Each city, vertiport operator and fleet on its own frame, federated', containers: 'a full frame each' },
  ],
}
