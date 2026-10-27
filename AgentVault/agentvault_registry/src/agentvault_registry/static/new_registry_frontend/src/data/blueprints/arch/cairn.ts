import type { BlueprintDeep } from '../types'

// CAIRN deep architecture (§18): the mission's frame and the excavation contractor's frame on site, Earth's frame
// minutes away or silent. The fabric between them is a band, so every crossing is a straight lane; the machines'
// controllers and the twin stay outside. Drawn on ORRERY's coordinates, which the geometry checks already hold.

export const deep: BlueprintDeep = {
  intro:
    'CAIRN deployed: Site Corvus’s frame holds the mandate gate, the section contracts, the escrow and the site ledger; the excavation contractor acts from its own frame on the same site; Earth’s frame, minutes away or silent, holds the eval agent and a replica that catches up on contact. The machines’ controllers and the twin stay where they run, outside the protocol by design. The trace replays section 14 from posting to settled scan, then the evals, the mandate and a decision that waits for the next contact.',
  arch: {
    zones: [
      { id: 'zf', label: 'SITE CORVUS’S FRAME', sub: 'mandate, contract, escrow, ledger', x: 30, y: 50, w: 370, h: 480, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'scans and units cross', x: 430, y: 50, w: 160, h: 480, kind: 'fabric' },
      { id: 'zg', label: 'THE CONTRACTOR’S FRAME', sub: 'paid by the section', x: 620, y: 50, w: 350, h: 220, kind: 'frame' },
      { id: 'zt', label: 'EARTH, MISSION CONTROL', sub: 'minutes away, or silent', x: 620, y: 300, w: 350, h: 230, kind: 'frame' },
      { id: 'ze', label: 'THE MACHINES AND THE TWIN', sub: 'controllers and tests stay put', x: 30, y: 575, w: 940, h: 120, kind: 'external' },
    ],
    nodes: [
      { id: 'contract', label: 'section contract', sub: 'names drone-2', kind: 'registry', x: 300, y: 135 },
      { id: 'escrow', label: 'section escrow', sub: 'held from posting', kind: 'teg', x: 300, y: 250 },
      { id: 'mgate', label: 'mandate gate', sub: 'budget, expiry, key', kind: 'gate', x: 300, y: 365 },
      { id: 'ledger', label: 'site ledger', sub: 'every unit, in order', kind: 'ledger', x: 120, y: 250 },
      { id: 'steward', label: 'site-steward', sub: 'posts on a permit', kind: 'agent', x: 120, y: 365 },
      { id: 'md', label: 'mission director', sub: 'Elif Brandt', kind: 'human', x: 120, y: 470 },
      { id: 'mesh', label: 'site mesh', sub: 'courier, not party', kind: 'registry', x: 510, y: 135 },
      { id: 'xfer', label: 'cross-frame pay', sub: 'exactly-once', kind: 'teg', x: 510, y: 250 },
      { id: 'drone', label: 'survey-drone-2', sub: 'signs each scan', kind: 'agent', x: 880, y: 150 },
      { id: 'desk', label: 'builder-desk', sub: 'sells excavation', kind: 'agent', x: 710, y: 230 },
      { id: 'replica', label: 'their replica', sub: 'no path to money', kind: 'ledger', x: 880, y: 230 },
      { id: 'evals', label: 'forge-evals', sub: 'tests every version', kind: 'agent', x: 710, y: 400 },
      { id: 'earth', label: 'earth replica', sub: 'the fortnight, later', kind: 'ledger', x: 880, y: 400 },
      { id: 'ctl', label: 'machine control', sub: 'commands stay here', kind: 'external', x: 280, y: 650 },
      { id: 'twin', label: 'site twin', sub: 'the site, simulated', kind: 'external', x: 710, y: 650 },
    ],
    edges: [
      { id: 'e-post', from: 'steward', to: 'mgate', label: 'section 14' },
      { id: 'e-hold', from: 'mgate', to: 'escrow' },
      { id: 'e-scan', from: 'drone', to: 'mesh', label: 'scan, signed' },
      { id: 'e-check', from: 'mesh', to: 'contract' },
      { id: 'e-release', from: 'contract', to: 'escrow' },
      { id: 'e-pay', from: 'escrow', to: 'xfer' },
      { id: 'e-paid', from: 'xfer', to: 'desk' },
      { id: 'e-replica', from: 'desk', to: 'replica', dashed: true },
      { id: 'e-emit', from: 'escrow', to: 'ledger', dashed: true },
      { id: 'e-twin', from: 'twin', to: 'evals', dashed: true },
      { id: 'e-evals', from: 'evals', to: 'md', label: 'evals, signed', dashed: true, labelT: 0.3 },
      { id: 'e-record', from: 'evals', to: 'earth', dashed: true },
      { id: 'e-mandate', from: 'md', to: 'steward', dashed: true },
      { id: 'e-hers', from: 'md', to: 'ctl', label: 'the plan, hers', dashed: true },
    ],
    script: [
      { edge: 'e-post', dwellMs: 1400, caption: 'Day 1 of the silence. The site-steward posts section 14 of the landing-field trench, 80 units, on a permit cut from the director’s mandate.' },
      { edge: 'e-hold', dwellMs: 1400, caption: 'A named job, inside the fortnight’s budget and before the expiry: the 80 units are escrowed at posting, on the site’s own frame.' },
      { edge: 'e-scan', dwellMs: 1400, caption: 'Six hours later the contractor’s survey-drone-2 flies the section and signs its scan: 40.2 metres, graded to tolerance.' },
      { edge: 'e-check', dwellMs: 1400, caption: 'The site mesh couriers the scan. The contract checks the principal: survey-drone-2, the one party it names.' },
      { edge: 'e-release', dwellMs: 1300, caption: 'The escrow releases on that signature, and on nothing else. An excavator’s own report releases nothing.' },
      { edge: 'e-pay', dwellMs: 1300, caption: 'The 80 units cross to the contractor’s frame exactly once, whatever the retries.' },
      { edge: 'e-paid', dwellMs: 1300, caption: 'The contractor is paid. Its own frame holds a replica of the job, with no path to the money.' },
      { edge: 'e-emit', dwellMs: 1300, caption: 'The section lands on the site’s ledger beside its scan, in order, for Earth to replay when the link returns.' },
      { edge: 'e-twin', dwellMs: 1300, caption: 'Before the silence, every agent version that flew ran 400 hours against the site’s twin on Earth.' },
      { edge: 'e-evals', dwellMs: 1500, caption: 'The eval agent signed the results, and the mission director read them before she signed the mandate.' },
      { edge: 'e-mandate', dwellMs: 1500, caption: 'Her mandate is the steward’s ceiling for the fortnight: a budget, named jobs, an expiry, and her key above 500 units.' },
      { edge: 'e-hers', dwellMs: 1600, caption: 'Moving the landing field waits for the next contact and goes up through mission control as it always has. The protocol carries authority, payment and evidence, never a command.' },
    ],
    traceLabel: 'Section 14: escrowed at posting, paid on the drone’s signature, replayed on Earth when the silence ends.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'One week of site work, re-read as contracts.',
      runs: 'Nothing. A week at a terrestrial analogue site redrawn as postings, escrows and signed scans.',
      agents: 'None. Operations, the contractor and the mission agree what a scan must say before anyone is paid for one.',
      integrates: 'Nothing. Controllers, the twin and the link stay exactly as they are.',
      notYet: 'No escrow, no mandate, no identity for any machine.',
      proof: 'One historical week re-expressed as section contracts, and both sides agree its signed scans release exactly the work actually done.',
    },
    {
      name: 'Pilot',
      headline: 'One analogue site, real machines, a rehearsed silence.',
      runs: 'A frame on the site’s computers at a desert or polar analogue, federated with a frame at mission control.',
      agents: 'The steward under a pilot mandate, one excavator and one survey drone, each with its own identity.',
      integrates: 'The machines’ controllers feed their agents; the link is cut on a schedule to rehearse a conjunction.',
      notYet: 'One contractor. No spend above the presence threshold. The delay-tolerant link is a scheduled cut.',
      proof: 'Fourteen days without a link, every section paid on a signed scan, and the fortnight replays at mission control in order, matching the site’s own log to the second.',
    },
    {
      name: 'Production',
      headline: 'The site on rails, through a real conjunction.',
      runs: 'Site Corvus’s frame and the contractor’s, on site, federated with Earth’s, each booted from the free licence.',
      agents: 'The full cast: both stewards under the director’s mandate, one agent per machine, the eval agent on Earth.',
      integrates: 'Mission control reads the replayed fortnight; the twin tests every version before it flies; planners write the next mandate.',
      notYet: 'A second contractor or site on the same terms. One set of partners proves itself first.',
      proof: 'A refused self-report, the restriction that followed and the scan that contradicted it replay from the ledger in order, and every section in the fortnight is paid exactly once.',
    },
    {
      name: 'Federation',
      headline: 'Every site, one grammar of work.',
      runs: 'Unchanged. New sites and contractors bring frames.',
      agents: 'A machine’s track record travels with its identity and its tested versions to the next site.',
      integrates: 'Each new contractor is a signed card and a licence, not a bilateral integration project.',
      notYet: 'Nothing structural. Growth is sites and machines.',
      proof: 'A site hires a contractor it has never used, on the strength of track records and eval results it can replay.',
    },
  ],
  sequenceTitle: 'One section, posting to signed release',
  sequence: `sequenceDiagram
  participant Stw as site-steward (Site Corvus)
  participant Gat as mandate gate
  participant Esc as section escrow
  participant Drn as survey-drone-2 (contractor frame)
  participant Msh as site mesh (fabric)
  participant Con as section contract
  participant Led as site ledger
  Stw->>Gat: post section 14, 80 units
  Gat->>Esc: inside the caveats: escrow at posting
  Drn->>Msh: scan, signed: 40.2 m, graded to tolerance
  Msh->>Con: couriered, principal checked
  Con->>Esc: release on the signature of the named drone
  Esc-->>Led: released exactly once, append-only
  Note over Msh: a valid channel proves the sender, never the principal
  Note over Gat: above 500 units the mission director signs with her device key`,
  sizing: [
    { level: 'L1', what: 'A science team joins with an account and agents on the site’s frame', containers: 'none of theirs' },
    { level: 'L2', what: 'A contractor runs its machines’ agents against a seat on the site’s frame', containers: 'agents only' },
    { level: 'L3', what: 'The mission, each contractor and Earth each run a sovereign frame', containers: 'a full frame each' },
  ],
}
