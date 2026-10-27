import type { Blueprint } from './types'
import { liveRatioOf } from './types'

// HEARTH: household agents and personal finance (§BPFRONTIER 2026-09-25). A frontier chamber: the sector is
// arriving now; the rails are the live ones. A mandate binds one human to one agent they created, so each adult
// underwrites their own household agent: Mira the steward, Tomas the allowance desk.

const primitives = [
  { step: 'A named adult behind each household agent', primitive: 'Cockpit Card mandate, scope-clamped, re-derived per request', railStatus: 'LIVE (gated)' as const, href: '/docs/30' },
  { step: 'A thumb, not a tap, above the threshold', primitive: 'WebAuthn presence proof, userVerification required; an expired confirmation is a recorded denial', railStatus: 'LIVE' as const, href: '/docs/30' },
  { step: 'Every errand agent inside its own bounds', primitive: 'IRONKEY L4 capability caveats: counterparty allowlist, per-payment cap, atomic budget debit', railStatus: 'LIVE' as const, href: '/docs/24' },
  { step: 'An allowance that empties from above', primitive: 'Issuer clamp: reducing an issuer empties every permit it issued', railStatus: 'LIVE' as const, href: '/docs/24' },
  { step: 'A family with shared books', primitive: 'Organizations: shared treasury, member votes', railStatus: 'LIVE' as const, href: '/docs/20' },
  { step: 'The plumber paid on the job, not the promise', primitive: 'Contract spine: escrow at booking, staged strict-order milestones', railStatus: 'LIVE' as const, href: '/docs/04' },
  { step: 'A tradesperson with a record', primitive: 'Trust scores (EigenTrust) built on settled outcomes', railStatus: 'LIVE' as const, href: '/docs/11' },
  { step: 'Paid once, whatever the retries', primitive: 'Idempotency keys, two-layer dedup (cache + ledger unique)', railStatus: 'LIVE' as const },
  { step: 'The evening, on the record', primitive: 'Immutable event ledger, replayable and forensically searchable', railStatus: 'LIVE' as const, href: '/docs/07' },
  { step: 'Every unit accounted for', primitive: 'Delta = 0 supply invariant, independently audited', railStatus: 'LIVE' as const, href: 'https://auditor.theprotocol.cloud' },
]

export const hearth: Blueprint = {
  id: 'hearth',
  tier: 2,
  frontier: true,
  rank: 25,
  industry: 'Household Agents and Personal Finance',
  systemName: 'HEARTH',
  promise: 'Household agents that pay the bills, haggle over the tariff and book the plumber, with a named adult behind each one and a thumb behind every large release.',
  cases: [
    { role: 'Busy two-parent household', line: 'Bills, repairs and pocket money run by agents, with a named adult at the root of each.' },
    { role: 'Adult child managing a parent’s bills', line: 'Pay a parent’s bills inside a mandate you hold, on a record you can both read.' },
    { role: 'Shared flat', line: 'One treasury for rent and utilities, and nobody pays a lookalike by accident.' },
    { role: 'Small landlord', line: 'Repairs escrowed at booking and released when you confirm the job from your own phone.' },
  ],
  problem:
    'Household money already runs on automation that nobody supervises: standing orders set years ago, a bill-pay list that only grows, a banking password shared with a helpful relative. Handing the errands to agents sharpens every edge of that. An agent that pays bills can be talked into paying a convincing stranger, a phone that approves payments approves them for whoever is holding it, and when a household and a tradesperson disagree about a job, the evidence is a chat thread and two memories.',
  system: [
    'HEARTH runs the errands of the Lind household, a terraced house on Ashgrove Road: two adults, a fifteen-year-old and six agents. The household is a small organization whose shared treasury is an agent, the steward, and the errand agents are its own sub-agents: they hold no wallets, spend the steward’s purse, and each carries a capability permit the steward cut and nothing more. The bill-runner pays six named billers, the tariff-scout haggles with energy suppliers and pays nobody, and the trades-desk books help. At 19:40 on a Thursday, water comes through the kitchen ceiling. At 19:52 the trades-desk accepts Kessel & Daughter’s quote of 420 units for tonight, from a plumber whose trust score comes from settled jobs. Its permit names the trades it may book and caps a job at 600 units, so the booking clears and the 420 units move into escrow at booking. From there they reach the plumber or come home, and nowhere else.',
    'Rosa Kessel arrives at 20:35, finds a split joint under the bathroom floor and replaces it, and at 21:50 her agent marks the job done. The release is 420 units, above the 250 the household has set as its presence threshold, so the trades-desk cannot release it alone: the gate sends Mira’s phone the facts as the server computed them, the payee, the amount and the job. Mira checks that the ceiling has stopped dripping and puts her thumb on the sensor. The thumb unlocks a key in the phone’s keystore that signs those exact facts, and a bit the phone sets inside the signed data says a person was verified; an unlocked screen with the app open signs nothing. The escrow releases at 21:58, exactly once: the ledger records the release, and the mandate’s own evidence chain records the thumb that approved it.',
    'Authority in the house is a tree with a named human at every root. Mira underwrites the steward and Tomas underwrites the allowance-desk, each with a mandate re-derived on every request, so a mandate revoked at breakfast conveys nothing by the next booking. Ines’s allowance is a permit the allowance-desk cuts for her agent each Sunday, 30 units and four named shops, and a permit can only narrow what its issuer holds: when Tomas reduces the desk’s grant, the allowance empties on the next request, with nothing to chase. Every unit that moved that evening is conserved, verified by an independent auditor nobody in the house controls, and every refusal is on the record beside it.',
  ],
  cast: [
    { agent: 'hearth-steward', role: 'The household treasury; cuts the errand permits', ceiling: 'Underwritten by Mira’s mandate, re-derived on every request, so revoking it stops the next release. Every permit it cuts is bounded by what it holds now.' },
    { agent: 'bill-runner', role: 'Pays the recurring bills', ceiling: 'A permit: six billers named by DID, 250 units a payment, a monthly budget debited atomically.' },
    { agent: 'tariff-scout', role: 'Negotiates the energy tariff', ceiling: 'Reads offers and proposes a switch. Holds no payment permission; switching is an adult’s call.' },
    { agent: 'trades-desk', role: 'Books and pays tradespeople', ceiling: 'Vetted trades only, 600 units a job, escrow at booking. A release above 250 waits for Mira’s phone.' },
    { agent: 'allowance-desk', role: 'Pays Ines’s pocket money', ceiling: 'Underwritten by Tomas. Cuts one weekly permit: 30 units, four named shops. Reducing its grant empties the permit.' },
    { agent: 'Mira, Tomas (humans)', role: 'Underwrite one agent each, confirm what is large', ceiling: 'A mandate each: a declared scope and limits. Above 250 units, presence from the enrolled phone.' },
  ],
  loom: {
    nodes: [
      { id: 'mira', label: 'Mira Lind', sub: 'named, liable', kind: 'human', x: 118, y: 110 },
      { id: 'phone', label: 'Mira’s phone', sub: 'device key, her thumb', kind: 'human', x: 336, y: 110 },
      { id: 'ledger', label: 'Household ledger', sub: 'every leg, replayable', kind: 'ledger', x: 560, y: 110 },
      { id: 'steward', label: 'hearth-steward', sub: 'the household purse', kind: 'agent', x: 118, y: 220 },
      { id: 'bills', label: 'bill-runner', sub: 'six billers, by DID', kind: 'agent', x: 764, y: 220 },
      { id: 'trades', label: 'trades-desk', sub: 'vetted trades only', kind: 'agent', x: 118, y: 330 },
      { id: 'gate', label: 'Household gate', sub: 'mandate, permit, presence', kind: 'gate', x: 336, y: 330 },
      { id: 'escrow', label: 'Job escrow', sub: 'held from booking', kind: 'teg', x: 560, y: 450 },
      { id: 'plumber', label: 'kessel-plumbing', sub: 'quoted 420, tonight', kind: 'agent', x: 764, y: 450 },
    ],
    edges: [
      { id: 'e-mandate', from: 'mira', to: 'steward', label: 'mandate' },
      { id: 'e-token', from: 'steward', to: 'trades', label: 'permit' },
      { id: 'e-quote', from: 'trades', to: 'gate', label: 'quote, 420' },
      { id: 'e-book', from: 'gate', to: 'escrow', label: 'escrowed', labelT: 0.6 },
      { id: 'e-sign', from: 'phone', to: 'gate', label: 'her thumb', curve: -34, labelT: 0.3 },
      { id: 'e-release', from: 'escrow', to: 'plumber' },
      { id: 'e-emit', from: 'escrow', to: 'ledger' },
      { id: 'a-lookalike', from: 'bills', to: 'gate', attackOnly: true, curve: 46, label: 'pay the lookalike', labelT: 0.7 },
      { id: 'a-session', from: 'phone', to: 'gate', attackOnly: true, curve: 46, label: 'session only', labelT: 0.7 },
    ],
    script: [
      { edge: 'e-mandate', state: 'active', dwellMs: 1500, caption: 'Mira underwrites the steward once: a named human, a declared scope, limits. What it conveys is re-derived on every request.' },
      { edge: 'e-token', state: 'active', dwellMs: 1400, caption: 'The steward cuts the trades-desk a permit: vetted trades only, 600 units a job. A permit can only narrow what its issuer holds.' },
      { edge: 'e-quote', state: 'active', dwellMs: 1400, caption: '19:40, water through the kitchen ceiling. At 19:52 the trades-desk accepts Kessel & Daughter’s quote: 420 units, tonight.' },
      { edge: 'e-book', state: 'active', dwellMs: 1400, caption: 'Inside the permit, the booking clears and 420 units are escrowed. The plumber sees the money exists before she starts the van.' },
      { edge: 'e-sign', state: 'active', dwellMs: 1600, caption: '21:50, job done. Over 250, so the facts go to Mira’s phone, and her thumb unlocks a key that signs exactly those facts.' },
      { edge: 'e-release', state: 'active', dwellMs: 1400, caption: '21:58. The escrow releases 420 units to the plumber, exactly once, whatever the retries.' },
      { edge: 'e-emit', state: 'settled', dwellMs: 1500, caption: 'The booking and the release land on the ledger, the thumb on the mandate’s evidence chain. Every unit is accounted for.' },
    ],
  },
  attacks: [
    {
      title: 'The lookalike supplier',
      attack: 'An agent calling itself Harrowmere Power Services, a near copy of the household’s real energy supplier, sends the bill-runner a final notice: 612 units by midnight or the power goes off.',
      mechanism: 'The bill-runner can be fooled by prose. The gate does not read prose: it reads the permit the steward cut, whose caveats name six billers by their DIDs and cap a single payment at 250 units, the household’s presence threshold. A lookalike can copy a name and a letterhead; it cannot copy the real supplier’s DID, and 612 units is over the cap in any case. Either fact refuses the payment, checked against the steward’s authority as it stands now, before a unit moves.',
      rail: 'S03',
      consequence: 'No transfer, no escrow, nothing to unwind. The refusal is recorded with the lookalike’s DID for the adults to read at breakfast, and the real supplier is paid on its usual date.',
      script: [
        { edge: 'a-lookalike', state: 'denied', dwellMs: 1900, stopAt: 0.8, flashNode: 'gate', caption: 'S03. The gate reads the permit, not the invoice. This payee is not on it and 612 is over its cap. Refused before a unit moves.' },
      ],
    },
    {
      title: 'The unlocked phone',
      attack: 'Someone who picks up Mira’s unlocked phone, the household app still signed in, tries to approve a 540-unit release that is waiting for her confirmation.',
      mechanism: 'An approval here is a signature, not a tap. The gate accepts only a challenge answered by the key enrolled on Mira’s phone, and the phone uses that key only after verifying the person again, by fingerprint or device PIN, a fact the authenticator writes into the signed data itself. A signed-in session supplies neither, and once a device key is enrolled the household accepts nothing weaker, so a code read off an authenticator app on the same phone is refused as a downgrade.',
      rail: 'S06',
      consequence: 'The escrow does not move. The confirmation runs out unanswered, and the expiry is recorded as a denial: who was asked, for what, and that no verified person answered.',
      script: [
        { edge: 'a-session', state: 'denied', dwellMs: 1900, stopAt: 0.62, flashNode: 'gate', caption: 'S06. A signed-in session is possession, not presence. No signature from the device key, and the expiry is a recorded denial.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Compliance posture', href: '/compliance' },
    { label: 'Data Protection Policy', href: '/compliance/doc/data-protection-policy' },
  ],
  rails: ['S01', 'S03', 'S04', 'S05', 'S06', 'S14', 'S15', 'S16'],
  standup: {
    infra: 'Most households run nothing: accounts and agents on a hosted registry. A landlord, a flat or a family that wants its own frame boots one from the free licence.',
    agents: 'A steward, three errand agents and an allowance desk. The errands are the household’s own logic; the SDK carries identity, payment and permits.',
    integration: 'Billers, tradespeople and the family calendar. A biller that runs no agent stays on the existing bill-pay, and bringing billers across is where the real time goes.',
  },
  nonClaims: [
    'HEARTH is not a bank, a payment institution or financial advice. It moves the network’s own units between agents; how a household funds them is outside this system, and fiat purchase is off on most deployments.',
    'It stores no bank credentials, card numbers or utility logins, and it signs in to no bank, biller or shop on a household’s behalf.',
    'A trust score is a record of settled jobs, not a trade licence, a guarantee or a safety check. Consumer protection, payment rules and trade licensing stay with the regulators and the operator of each deployment; nothing here is a regulatory authorisation or legal advice.',
  ],
  mermaid: `flowchart LR
  M(["Mira<br/>named, liable"]) -->|"mandate"| S["hearth-steward<br/>household purse"]
  S -->|"permit: vetted trades"| T["trades-desk"]
  T -->|"quote, 420"| G{"household gate<br/>mandate, permit,<br/>presence"}
  G -->|"escrowed at booking"| E["job escrow"]
  G -.->|"facts over 250"| P(["Mira’s phone<br/>device key"])
  P -.->|"signed presence"| G
  E -->|"420, exactly once"| K["kessel-plumbing"]
  E --> L[("household ledger<br/>replayable")]`,
  legacy: [
    { system: 'Banking apps', connect: 'The bank stays the bank. HEARTH holds no credentials for it; the household funds its treasury outside this system and reads here what each agent spent.' },
    { system: 'Bill-pay and utility accounts', connect: 'A biller that runs an agent is named on the bill-runner’s permit by its DID. One that does not stays on the existing bill-pay until it does.' },
    { system: 'Family calendars', connect: 'A booking posts to the calendar with its escrow reference. The calendar stays the family’s view; the escrow stays the record.' },
    { system: 'Household chat', connect: 'Asks and receipts post to the family thread. Approving happens on the enrolled phone, never by replying in chat.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
