import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'Player economies on real rails', primitive: 'Agent wallets, transfers, locks: the live unit economy', railStatus: 'LIVE' as const },
  { step: 'In-game orgs with real books', primitive: 'Organization points: holdings, order books, votes', railStatus: 'LIVE (gated)' as const },
  { step: 'Bots pay per action', primitive: 'A2A payment authorization with exactly-once settlement', railStatus: 'LIVE' as const },
  { step: 'The economy cannot inflate', primitive: 'Delta = 0 supply invariant, independently audited', railStatus: 'LIVE' as const, href: 'https://auditor.theprotocol.cloud' },
  { step: 'Farm rings get found', primitive: 'Collusion detection over the trade graph, daily', railStatus: 'LIVE' as const },
  { step: 'Prize pools defended', primitive: 'Circuit breakers and velocity tracking on prize pools', railStatus: 'LIVE' as const },
]

export const arcadia: Blueprint = {
  id: 'arcadia',
  tier: 2,
  vault: true,
  rank: 16,
  industry: 'Gaming Economies',
  systemName: 'ARCADIA',
  promise: 'A game economy with a real supply invariant, where the gold farmers meet a collusion detector.',
  cases: [
    { role: 'Studio economy team', line: 'Design the faucets and sinks; the invariant holds the line.' },
    { role: 'Player-run guilds', line: 'Guild treasuries as real organizations with real books.' },
    { role: 'Marketplace operators', line: 'Player trades settle exactly once, disputes included.' },
    { role: 'Anti-cheat and trust', line: 'Farm rings surface in the trade graph, not in forum threads.' },
  ],
  problem:
    'Every large game economy eventually meets the same three horsemen: inflation from duplicated or over-fauceted currency, gold-farming rings that industrialise the loops, and a marketplace where the operator quietly holds all the books. Studios rebuild the same fragile economy tooling, game after game.',
  system: [
    'ARCADIA runs a persistent world’s economy on the same rails this network uses for everything else. The game’s currency is a frame unit with a supply invariant: every faucet is a recorded issuance, every sink a recorded burn, and an auditor the studio does not control verifies conservation continuously, which converts "the devs duped gold" from a rumour into a checkable claim. Player guilds are organizations with treasuries, holder registers and votes; the auction house is an order book, not a database the operator edits.',
    'At scale, the interesting part is the immune system. A farming operation spins up four hundred accounts trading in a tight ring, and the ring is exactly the kind of structure the collusion detector walks the trade graph for every day. The accounts are quarantined as a set, their flow frozen in place, and the season’s prize pool, defended by circuit breakers and velocity tracking, pays the players who actually played.',
  ],
  cast: [
    { agent: 'economy-director', role: 'Tunes faucets, sinks and seasons', ceiling: 'Parameters via governance. Cannot issue outside the recorded faucets.' },
    { agent: 'guild-treasury', role: 'Holds a guild’s funds and points', ceiling: 'Org treasury rails only, members vote the big moves.' },
    { agent: 'market-maker', role: 'Quotes the auction house', ceiling: 'Order placement inside spend policies.' },
    { agent: 'trust-watch', role: 'Reviews collusion flags', ceiling: 'Quarantine on evidence. Cannot touch balances.' },
  ],
  loom: {
    nodes: [
      { id: 'player', label: 'player', sub: 'plays the loop', kind: 'external', x: 118, y: 110 },
      { id: 'faucet', label: 'Faucet', sub: 'recorded issuance', kind: 'teg', x: 336, y: 220 },
      { id: 'market', label: 'Auction house', sub: 'a real order book', kind: 'teg', x: 560, y: 110 },
      { id: 'guild', label: 'guild-treasury', sub: 'org with books', kind: 'agent', x: 764, y: 220 },
      { id: 'detector', label: 'Collusion sweep', sub: 'trade graph, daily', kind: 'gate', x: 336, y: 330 },
      { id: 'ring', label: 'farm ring', sub: '400 accounts', kind: 'external', x: 118, y: 330 },
      { id: 'ledger', label: 'Economy ledger', sub: 'delta = 0, audited', kind: 'ledger', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-earn', from: 'player', to: 'faucet', label: 'paid, recorded' },
      { id: 'e-trade', from: 'faucet', to: 'market', label: 'trades settle once' },
      { id: 'e-guild', from: 'market', to: 'guild', label: 'guild distribution' },
      { id: 'e-emit', from: 'guild', to: 'ledger' },
      { id: 'a-farm', from: 'ring', to: 'detector', attackOnly: true, label: 'industrial loop' },
    ],
    script: [
      { edge: 'e-earn', state: 'active', dwellMs: 1400, caption: 'Every faucet is a recorded issuance. Every sink is a recorded burn.' },
      { edge: 'e-trade', state: 'active', dwellMs: 1400, caption: 'The auction house is an order book, not an editable table.' },
      { edge: 'e-guild', state: 'active', dwellMs: 1400, caption: 'Guilds are organizations: treasuries, points, votes.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1600, caption: 'An auditor the studio does not control verifies conservation, continuously.' },
    ],
  },
  attacks: [
    {
      title: 'The four-hundred-account farm',
      attack: 'A farming operation runs four hundred accounts in a tight trading ring to industrialise the season prizes.',
      mechanism: 'The ring is a strongly connected component in the trade graph, which the collusion detector walks daily; prize pools sit behind circuit breakers and velocity tracking, so the extraction pattern trips defenses before it drains anything.',
      rail: 'S08',
      riskRef: 'R-AI-04',
      consequence: 'The set quarantines together, flows freeze in place for review, and the season pool pays the players who played.',
      script: [
        { edge: 'a-farm', state: 'denied', dwellMs: 1900, stopAt: 0.7, flashNode: 'detector', caption: 'A tight ring is a graph shape. The sweep finds shapes.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Compliance posture', href: '/compliance' },
  ],
  rails: ['S01', 'S02', 'S08', 'S14', 'S15', 'S18'],
  standup: {
    infra: 'A frame per game world, or per studio. The economy tooling is the platform.',
    agents: '4 to 6 roles; the game server talks to them like any other client.',
    integration: 'Gameplay stays in the engine. The protocol carries the economy underneath it.',
  },
  nonClaims: [
    'ARCADIA is an in-game economy on network units. Whether any unit is redeemable for money is the studio’s design and the studio’s regulatory question.',
    'The fiat lane, where enabled at all, is purchase-only with no withdrawal path by design.',
  ],
  mermaid: `flowchart LR
  P["players + bots"] -->|"paid via recorded faucets"| TEG["frame unit economy<br/>delta = 0 audited"]
  TEG -->|"order book trades"| AH["AGORA venue<br/>auction house"]
  AH -->|"distributions"| ORG["guild organizations<br/>treasuries + points"]
  CD["collusion detector<br/>Tarjan SCC, daily"] -.->|"ring quarantine"| TEG
  TEG --> ES[("economy ledger")]
  AUD["independent auditor"] --> ES`,
  legacy: [
    { system: 'The game engine and inventory services', connect: 'Gameplay stays in the engine. The economy underneath gains a supply invariant.' },
    { system: 'Player account systems', connect: 'Accounts map to agent identities. Bans propagate as revocations.' },
    { system: 'Marketplace and trading services', connect: 'Existing trade UIs call the settlement rail instead of a mutable database.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
