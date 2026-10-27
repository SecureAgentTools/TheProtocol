import type { BlueprintDeep } from '../types'

// ARCADIA deep architecture (§18) — a game economy with a real supply
// invariant and an immune system the gold farmers have to meet.

export const deep: BlueprintDeep = {
  intro:
    'ARCADIA deployed: the studio’s frame runs the world’s economy: recorded faucets, recorded sinks, an order-book auction house, a defended prize pool; the players and their guilds act as first-class accounts; and the auditor that verifies conservation sits outside the studio’s reach, which converts "the devs duped gold" from a rumour into a checkable claim. The trace replays one season: issue, trade, ring, quarantine, prizes.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE STUDIO’S FRAME', sub: 'the world economy, conserved', x: 30, y: 50, w: 440, h: 480, kind: 'frame' },
      { id: 'zp', label: 'PLAYERS AND GUILDS', sub: 'accounts, treasuries, one ring', x: 530, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zx', label: 'OUTSIDE THE STUDIO’S REACH', sub: 'independent verification', x: 30, y: 570, w: 440, h: 115, kind: 'fabric' },
      { id: 'ze', label: 'THE GAME ITSELF', sub: 'gameplay stays in the engine', x: 530, y: 470, w: 440, h: 130, kind: 'external' },
    ],
    nodes: [
      { id: 'director', label: 'economy-director', sub: 'tunes, cannot issue', kind: 'agent', x: 140, y: 135 },
      { id: 'gov', label: 'governance gate', sub: 'parameters by vote', kind: 'gate', x: 310, y: 133 },
      { id: 'es', label: 'world ledger', sub: 'supply invariant', kind: 'ledger', x: 140, y: 375 },
      { id: 'pool', label: 'season pool', sub: 'breakers + velocity', kind: 'teg', x: 310, y: 255 },
      { id: 'teg', label: 'faucets + sinks', sub: 'issue + burn logged', kind: 'teg', x: 310, y: 495 },
      { id: 'market', label: 'auction house', sub: 'an order book', kind: 'registry', x: 310, y: 375 },
      { id: 'guild', label: 'guild-treasury', sub: 'members vote', kind: 'agent', x: 690, y: 135 },
      { id: 'maker', label: 'market-maker', sub: 'quotes the book', kind: 'agent', x: 690, y: 255 },
      { id: 'ring', label: 'farm ring (x400)', sub: 'the immune test', kind: 'agent', x: 690, y: 375 },
      { id: 'trust', label: 'trust-watch', sub: 'freezes on evidence', kind: 'agent', x: 860, y: 255 },
      { id: 'auditor', label: 'external auditor', sub: 'no studio control', kind: 'registry', x: 390, y: 637 },
      { id: 'mesh', label: 'federation mesh', sub: 'other worlds', kind: 'registry', x: 230, y: 637 },
      { id: 'engine', label: 'engine + servers', sub: 'gameplay stays here', kind: 'external', x: 600, y: 580 },
      { id: 'launcher', label: 'store + launcher', sub: 'accounts map to DIDs', kind: 'external', x: 880, y: 510 },
    ],
    edges: [
      { id: 'e-tune', from: 'director', to: 'gov', label: 'proposes', dashed: true },
      { id: 'e-params', from: 'gov', to: 'pool', label: 'parameters', labelT: 0.66 },
      { id: 'e-mint', from: 'engine', to: 'teg', label: 'faucets in', labelT: 0.44 },
      { id: 'e-launch', from: 'launcher', to: 'market', label: 'listings, orders', dashed: true, labelT: 0.5 },
      { id: 'e-supply', from: 'teg', to: 'es', label: 'issuance + burn', labelT: 0.5 },
      { id: 'e-book', from: 'market', to: 'teg' },
      { id: 'e-audit', from: 'es', to: 'auditor', label: 'conservation, checked', dashed: true, curve: 52, labelT: 0.6 },
      { id: 'e-public', from: 'auditor', to: 'mesh', dashed: true },
      { id: 'e-votes', from: 'guild', to: 'gov', label: 'votes, by locks', labelT: 0.72 },
      { id: 'e-season', from: 'pool', to: 'guild', label: 'season prizes', labelT: 0.17 },
      { id: 'e-quote', from: 'maker', to: 'market', label: 'quotes', labelT: 0.5 },
      { id: 'e-ring', from: 'ring', to: 'market', label: 'the ring trades', labelT: 0.42 },
      { id: 'e-quarantine', from: 'trust', to: 'ring', label: 'as a set', dashed: true, labelT: 0.5 },
    ],
    script: [
      { edge: 'e-mint', dwellMs: 1400, caption: 'The engine drops loot. Every faucet is a recorded issuance; every sink is a recorded burn.' },
      { edge: 'e-supply', dwellMs: 1300, caption: 'The world ledger carries a real supply invariant, continuously.' },
      { edge: 'e-audit', dwellMs: 1500, caption: 'An auditor the studio does not control verifies conservation. "The devs duped gold" becomes a checkable claim.' },
      { edge: 'e-public', dwellMs: 1200, caption: 'The verification is public. Players can read it; so can journalists.' },
      { edge: 'e-launch', dwellMs: 1300, caption: 'The auction house is an order book, not a database the operator edits.' },
      { edge: 'e-quote', dwellMs: 1200, caption: 'Market makers quote inside spend policies.' },
      { edge: 'e-votes', dwellMs: 1300, caption: 'Guilds are organizations: treasuries, points, distributions, votes.' },
      { edge: 'e-tune', dwellMs: 1300, caption: 'The economy director proposes a faucet change. Proposing is all it can do alone.' },
      { edge: 'e-params', dwellMs: 1300, caption: 'Parameters move by governance, on the record.' },
      { edge: 'e-ring', dwellMs: 1500, caption: 'A farming operation spins up four hundred accounts trading in a tight ring: exactly the structure the collusion detector walks the trade graph for, every day.' },
      { edge: 'e-quarantine', dwellMs: 1500, caption: 'The ring is quarantined as a set, its flow frozen in place, on evidence.' },
      { edge: 'e-season', dwellMs: 1400, caption: 'The season pool, defended by circuit breakers and velocity tracking, pays the players who actually played.' },
    ],
    traceLabel: 'One season: issued, traded, one ring frozen, the players paid.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'The economy design, made falsifiable.',
      runs: 'Nothing. The faucet and sink tables of the current game, redrawn as recorded issuances and burns.',
      agents: 'None. The economy team argues about which faucets are actually recorded today, which is the uncomfortable, productive argument.',
      integrates: 'Nothing. The engine and the live game stay untouched.',
      notYet: 'No invariant exists to check.',
      proof: 'One patch cycle’s currency changes re-expressed as faucet and sink records, and the net supply comes out where the designers believed it was.',
    },
    {
      name: 'Pilot',
      headline: 'A test shard with a conserved economy.',
      runs: 'A frame for one test shard: registry, TEG, EventStore, identity fabric on one VM.',
      agents: 'economy-director, one guild treasury, market makers; the auditor runs from day one, outside the team.',
      integrates: 'The engine issues through the recorded faucets only; the auction house replaces the shard’s trade window.',
      notYet: 'No real players. The collusion detector trains on staged rings.',
      proof: 'A staged four-hundred-account ring is detected and quarantined as a set within a day, with the season pool untouched.',
    },
    {
      name: 'Production',
      headline: 'The live world, conserved in public.',
      runs: 'A frame per game world or per studio. The economy tooling is the platform, not a mod.',
      agents: 'The full cast; guild treasuries and distributions live; circuit breakers and velocity tracking defend the pool.',
      integrates: 'The engine talks to the economy like any other client; the launcher’s storefront, where fiat exists at all, is purchase-only.',
      notYet: 'Cross-world trading. One world’s invariant proves itself first.',
      proof: 'A season closes with the independent auditor publishing continuous conservation, and support tickets about duped gold answered with a link.',
    },
    {
      name: 'Federation',
      headline: 'Worlds trade like registries do.',
      runs: 'Unchanged. World frames federate bilaterally where studios choose to.',
      agents: 'Guild and player reputations travel with DIDs between titles that opt in.',
      integrates: 'Each connected world is a signed card and a licence.',
      notYet: 'Redeemability of any unit for money remains the studio’s design and the studio’s regulatory question.',
      proof: 'Two worlds exchange value through a corridor for a season with both invariants intact and both auditors public.',
    },
  ],
  sequenceTitle: 'One trade, and the invariant behind it',
  sequence: `sequenceDiagram
  participant Eng as game engine
  participant TEG as faucets + sinks
  participant AH as auction house
  participant Pool as season pool
  participant ES as world ledger
  participant Aud as independent auditor
  Eng->>TEG: loot drop = recorded issuance
  AH->>TEG: trade settles, fee sinks
  Pool->>TEG: prizes, breakers + velocity checked
  TEG-->>ES: every issuance, burn and trade, append-only
  ES-->>Aud: conservation verified continuously
  Aud-->>Aud: published: supply delta is zero
  Note over AH: a 400-account ring is a graph shape, and the detector walks the graph daily`,
  sizing: [
    { level: 'L1', what: 'Players and guilds are accounts on the world’s frame', containers: '0 of theirs' },
    { level: 'L2', what: 'A studio pilots the economy tooling against a hosted seat', containers: 'agents only' },
    { level: 'L3', what: 'A frame per world or per studio, auditor outside the wall', containers: 'one frame per world' },
  ],
}
