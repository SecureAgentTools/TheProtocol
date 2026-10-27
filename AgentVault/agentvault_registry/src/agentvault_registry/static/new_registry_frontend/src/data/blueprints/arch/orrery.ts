import type { BlueprintDeep } from '../types'

// ORRERY deep architecture (§18): three sovereign frames around one pass. The operator books and holds the escrow,
// the ground network's antenna signs the report, the traffic service signs the warning. The fabric sits between
// them as a band, so every crossing is a straight lane; mission control and the tracking feeds stay outside.

export const deep: BlueprintDeep = {
  intro:
    'ORRERY deployed: Halcyon Imaging’s frame holds the mandate gate, the pass contract, the escrow and the mission ledger; the ground network and the space-traffic service act from their own frames; the fabric between them carries signed reports and exactly-once payments. Mission control and the tracking feeds stay where they run, outside the protocol by design. The trace replays pass 48213 from booking to settled report, then the warning, the flight director’s key, and the burn that stays Halcyon’s own.',
  arch: {
    zones: [
      { id: 'zf', label: 'HALCYON IMAGING’S FRAME', sub: 'mandate, contract, escrow, ledger', x: 30, y: 50, w: 370, h: 480, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'reports and money cross', x: 430, y: 50, w: 160, h: 480, kind: 'fabric' },
      { id: 'zg', label: 'THE GROUND NETWORK’S FRAME', sub: 'antennas sold by the pass', x: 620, y: 50, w: 350, h: 220, kind: 'frame' },
      { id: 'zt', label: 'THE SPACE-TRAFFIC SERVICE', sub: 'screens the sky, signs warnings', x: 620, y: 300, w: 350, h: 230, kind: 'frame' },
      { id: 'ze', label: 'THE GROUND AND THE SKY', sub: 'commands and tracking stay put', x: 30, y: 575, w: 940, h: 120, kind: 'external' },
    ],
    nodes: [
      { id: 'contract', label: 'pass contract', sub: 'names antenna-PCL-2', kind: 'registry', x: 300, y: 135 },
      { id: 'escrow', label: 'pass escrow', sub: 'held from booking', kind: 'teg', x: 300, y: 250 },
      { id: 'mgate', label: 'mandate gate', sub: 'networks, budget, key', kind: 'gate', x: 300, y: 365 },
      { id: 'ledger', label: 'mission ledger', sub: 'passes, warnings', kind: 'ledger', x: 120, y: 250 },
      { id: 'sched', label: 'pass-scheduler', sub: 'books on a permit', kind: 'agent', x: 120, y: 365 },
      { id: 'fd', label: 'flight director', sub: 'Mara Lindqvist', kind: 'human', x: 120, y: 470 },
      { id: 'relay', label: 'report relay', sub: 'courier, not party', kind: 'registry', x: 510, y: 135 },
      { id: 'xfer', label: 'cross-frame pay', sub: 'exactly-once', kind: 'teg', x: 510, y: 250 },
      { id: 'antenna', label: 'antenna-PCL-2', sub: 'signs pass reports', kind: 'agent', x: 880, y: 150 },
      { id: 'desk', label: 'station-desk', sub: 'sells antenna time', kind: 'agent', x: 710, y: 230 },
      { id: 'replica', label: 'their replica', sub: 'no path to money', kind: 'ledger', x: 880, y: 230 },
      { id: 'screener', label: 'traffic-screener', sub: 'signs each warning', kind: 'agent', x: 710, y: 400 },
      { id: 'sledger', label: 'service ledger', sub: 'same warnings', kind: 'ledger', x: 880, y: 400 },
      { id: 'mcs', label: 'mission control', sub: 'commands stay here', kind: 'external', x: 280, y: 650 },
      { id: 'feeds', label: 'tracking feeds', sub: 'radar and optical', kind: 'external', x: 710, y: 650 },
    ],
    edges: [
      { id: 'e-book', from: 'sched', to: 'mgate', label: 'pass 48213' },
      { id: 'e-hold', from: 'mgate', to: 'escrow' },
      { id: 'e-report', from: 'antenna', to: 'relay', label: 'report, signed' },
      { id: 'e-check', from: 'relay', to: 'contract' },
      { id: 'e-release', from: 'contract', to: 'escrow' },
      { id: 'e-pay', from: 'escrow', to: 'xfer' },
      { id: 'e-paid', from: 'xfer', to: 'desk' },
      { id: 'e-replica', from: 'desk', to: 'replica', dashed: true },
      { id: 'e-emit', from: 'escrow', to: 'ledger', dashed: true },
      { id: 'e-feeds', from: 'feeds', to: 'screener', dashed: true },
      { id: 'e-warn', from: 'screener', to: 'fd', label: 'warning, signed', dashed: true, labelT: 0.3 },
      { id: 'e-swarn', from: 'screener', to: 'sledger', dashed: true },
      { id: 'e-mandate', from: 'fd', to: 'sched', dashed: true },
      { id: 'e-burn', from: 'fd', to: 'mcs', label: 'the burn, hers', dashed: true },
    ],
    script: [
      { edge: 'e-book', dwellMs: 1400, caption: 'At 22:10 UTC the scheduler books pass 48213 at Punta Clara, 120 units, on a permit cut from the flight director’s mandate.' },
      { edge: 'e-hold', dwellMs: 1400, caption: 'An approved network, inside the week’s budget: the 120 units are escrowed at booking, on Halcyon’s own frame.' },
      { edge: 'e-report', dwellMs: 1400, caption: 'At 04:28 the antenna signs its report: acquired 04:17:06, lost 04:27:51, 46.8 GB received.' },
      { edge: 'e-check', dwellMs: 1400, caption: 'The relay couriers the report. The contract checks the principal: antenna-PCL-2, the one party it names.' },
      { edge: 'e-release', dwellMs: 1300, caption: 'The escrow releases on that signature, and on nothing else.' },
      { edge: 'e-pay', dwellMs: 1300, caption: 'The 120 units cross to the network exactly once, whatever the retries.' },
      { edge: 'e-paid', dwellMs: 1300, caption: 'The network is paid. Its own frame holds a replica of the pass, with no path to the money.' },
      { edge: 'e-emit', dwellMs: 1300, caption: 'The pass lands on Halcyon’s ledger beside its report, replayable by the network or the insurer.' },
      { edge: 'e-feeds', dwellMs: 1300, caption: 'The traffic service screens against its own tracking data, paid per screening through a single-use payment authorization.' },
      { edge: 'e-warn', dwellMs: 1500, caption: 'At 06:40 its signed warning reaches the flight director: HALCYON-4 and a debris fragment, closest approach 11:02.' },
      { edge: 'e-mandate', dwellMs: 1500, caption: 'The decision is hers. The 900-unit priority pass exceeds her threshold, so it waits until her device key signs it.' },
      { edge: 'e-burn', dwellMs: 1600, caption: 'The burn goes up through Halcyon’s own mission control. The protocol carries authority, money and evidence, never a command.' },
    ],
    traceLabel: 'Pass 48213: escrowed at booking, paid on the antenna’s signature. Then a warning, and a decision that stays hers.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'One week of passes, re-read as contracts.',
      runs: 'Nothing. Last week’s passes at one partner network redrawn as bookings, escrows and signed reports.',
      agents: 'None. Operations, the network and finance agree what a pass report must say before anyone is paid for one.',
      integrates: 'Nothing. Mission control, the network’s scheduler and the tracking feeds stay exactly as they are.',
      notYet: 'No escrow, no mandate, no identity for any antenna.',
      proof: 'One historical week re-expressed as pass contracts, and both sides agree its signed reports release exactly the amounts they actually paid.',
    },
    {
      name: 'Pilot',
      headline: 'One network, one antenna, real passes.',
      runs: 'A registry seat or a single-VM frame for Halcyon, federated with the network’s frame.',
      agents: 'The scheduler under a pilot mandate, and antenna-PCL-2 signing its own reports.',
      integrates: 'The antenna’s modem logs feed its reports; the network’s scheduling interface keeps the calendar.',
      notYet: 'One network. Screenings still arrive by email. No spend above the presence threshold.',
      proof: 'Thirty passes booked, escrowed and paid on signed reports, with every acquisition and loss time matching the network’s own pass log to the second.',
    },
    {
      name: 'Production',
      headline: 'The constellation on rails, warnings signed.',
      runs: 'Halcyon’s frame, federated with the network’s and the traffic service’s, each booted from the free licence.',
      agents: 'The full cast: planner and scheduler under the flight director’s mandate, one agent per antenna, the traffic service’s screener.',
      integrates: 'Mission control reads booked passes; the tracking feeds stay the service’s own; finance reads settlement from the ledger.',
      notYet: 'A second network or service on the same terms. One set of partners proves itself first.',
      proof: 'A warning, the flight director’s signed decision and the priority pass that carries the burn plan replay from the ledger in order, and every pass in the month is paid exactly once.',
    },
    {
      name: 'Federation',
      headline: 'Every network, one grammar of passes.',
      runs: 'Unchanged. New networks and traffic services bring frames or seats.',
      agents: 'A network’s delivery record travels with its antennas’ identities to the next operator.',
      integrates: 'Each new network is a signed card and a licence, not a bilateral integration project.',
      notYet: 'Nothing structural. Growth is stations and coverage.',
      proof: 'An operator books and pays for a pass at a network it has never used, on the strength of reports it can replay.',
    },
  ],
  sequenceTitle: 'One pass, booking to signed release',
  sequence: `sequenceDiagram
  participant Sch as pass-scheduler (Halcyon)
  participant Gat as mandate gate
  participant Esc as pass escrow
  participant Ant as antenna-PCL-2 (network frame)
  participant Rel as report relay (fabric)
  participant Con as pass contract
  participant Led as mission ledger
  Sch->>Gat: book pass 48213, 120 units
  Gat->>Esc: inside the caveats: escrow at booking
  Ant->>Rel: pass report, signed: AOS 04:17:06, LOS 04:27:51, 46.8 GB
  Rel->>Con: couriered, principal checked
  Con->>Esc: release on the signature of the named antenna
  Esc-->>Led: released exactly once, append-only
  Note over Rel: a valid channel proves the courier, never the principal
  Note over Gat: above 500 units the flight director signs with her device key`,
  sizing: [
    { level: 'L1', what: 'A payload team joins with an account and agents on a hosted frame', containers: 'none of theirs' },
    { level: 'L2', what: 'An operator runs its planner and scheduler against a registry seat', containers: 'agents only' },
    { level: 'L3', what: 'Operators, networks and traffic services each run a sovereign frame', containers: 'a full frame each' },
  ],
}
