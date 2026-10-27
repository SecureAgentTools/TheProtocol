/** intentGrammar.test.ts — §POCKETBRIDGE3 WS-B1. The voice grammar, pinned. */
import { describe, it, expect } from 'vitest'
import {
  parseUtterance,
  parseAmount,
  matchAgent,
  matchSymbol,
  intentTouchesMoney,
  CAPABILITIES,
  CAPABILITY_ENTRIES,
  exampleIn,
  type GrammarContext,
} from './intentGrammar'

const ROSTER = [
  { did: 'did:theprotocol:d000b1b7', name: 'Trader Theo' },
  { did: 'did:theprotocol:f6dd1a85', name: 'Trader Tilly' },
  { did: 'did:theprotocol:aaaa0001', name: 'Caspian Manifest Services' },
]
const SYMBOLS = [
  { symbol: 'BLD0', name: 'Builder Zero' },
  { symbol: 'QCC', name: 'Quantum Clerk Co' },
  { symbol: 'FIRM72', name: 'Firm 72' },
]
const CTX: GrammarContext = { roster: ROSTER, symbols: SYMBOLS }

describe('parseAmount', () => {
  it('parses digits, decimals, comma decimals, k, word numbers', () => {
    expect(parseAmount('5')).toBe(5)
    expect(parseAmount('5.5')).toBe(5.5)
    expect(parseAmount('12,5')).toBe(12.5)
    expect(parseAmount('5k')).toBe(5000)
    expect(parseAmount('five')).toBe(5)
    expect(parseAmount('twenty')).toBe(20)
    expect(parseAmount('two hundred')).toBe(200)
    expect(parseAmount('five thousand')).toBe(5000)
    expect(parseAmount('2 hundred')).toBe(200)
  })
  it('returns null for garbage', () => {
    expect(parseAmount('everything')).toBeNull()
    expect(parseAmount('')).toBeNull()
    expect(parseAmount(undefined)).toBeNull()
  })
})

describe('matchAgent', () => {
  it('exact, word, prefix, substring, fuzzy', () => {
    expect(matchAgent('trader theo', ROSTER)?.name).toBe('Trader Theo')
    expect(matchAgent('theo', ROSTER)?.name).toBe('Trader Theo')
    expect(matchAgent('tilly', ROSTER)?.name).toBe('Trader Tilly')
    expect(matchAgent('caspian', ROSTER)?.name).toBe('Caspian Manifest Services')
    // fuzzy: one speech typo
    expect(matchAgent('tillie', ROSTER)?.name).toBe('Trader Tilly')
    expect(matchAgent('theod', ROSTER)?.name).toBe('Trader Theo')
  })
  it('empty roster or no hit is honest null', () => {
    expect(matchAgent('theo', [])).toBeNull()
    expect(matchAgent('zebra', ROSTER)).toBeNull()
    // short queries do not fuzz (protects against random 3-letter hits)
    expect(matchAgent('xyz', ROSTER)).toBeNull()
  })
})

describe('matchSymbol', () => {
  it('matches symbol, name, near-miss', () => {
    expect(matchSymbol('bld0', SYMBOLS)).toBe('BLD0')
    expect(matchSymbol('$QCC', SYMBOLS)).toBe('QCC')
    expect(matchSymbol('quantum', SYMBOLS)).toBe('QCC')
    expect(matchSymbol('firm72', SYMBOLS)).toBe('FIRM72')
    expect(matchSymbol('bldo', SYMBOLS)).toBe('BLD0') // speech mishears 0 as o
  })
  it('no venue match is null', () => {
    expect(matchSymbol('zzz9', SYMBOLS)).toBeNull()
  })
})

describe('navigate', () => {
  it('go-to forms and bare words', () => {
    expect(parseUtterance('go to trade', CTX).intent).toEqual({ kind: 'navigate', target: 'trade' })
    expect(parseUtterance('open approvals', CTX).intent).toEqual({ kind: 'navigate', target: 'approvals' })
    expect(parseUtterance('show me the senate', CTX).intent).toEqual({ kind: 'navigate', target: 'senate' })
    expect(parseUtterance('agents', CTX).intent).toEqual({ kind: 'navigate', target: 'agents' })
    expect(parseUtterance('open the market', CTX).intent).toEqual({ kind: 'navigate', target: 'trade' })
    expect(parseUtterance('guild', CTX).intent).toEqual({ kind: 'navigate', target: 'earn' })
  })

  it('§AGORAWORDS: "agora" and "listings" reach the same door as "market"/"exchange"', () => {
    expect(parseUtterance('agora', CTX).intent).toEqual({ kind: 'navigate', target: 'trade' })
    expect(parseUtterance('listings', CTX).intent).toEqual({ kind: 'navigate', target: 'trade' })
    expect(parseUtterance('open agora', CTX).intent).toEqual({ kind: 'navigate', target: 'trade' })
    // "go to X" only ever resolves through NAV_WORDS, so this pins that table
    // (not just the trade block's own "open trade|agora|listings" pattern).
    expect(parseUtterance('go to agora', CTX).intent).toEqual({ kind: 'navigate', target: 'trade' })
    expect(parseUtterance('go to listings', CTX).intent).toEqual({ kind: 'navigate', target: 'trade' })
    // the old words keep working, never replaced
    expect(parseUtterance('exchange', CTX).intent).toEqual({ kind: 'navigate', target: 'trade' })
    expect(parseUtterance('go to market', CTX).intent).toEqual({ kind: 'navigate', target: 'trade' })
  })
})

describe('balance + queue', () => {
  it('balance forms', () => {
    const r1 = parseUtterance('balance', CTX)
    expect(r1.intent.kind).toBe('balance')
    const r2 = parseUtterance('balance of theo', CTX)
    expect(r2.intent).toMatchObject({ kind: 'balance', agent: { name: 'Trader Theo' } })
    const r3 = parseUtterance('how much does tilly have', CTX)
    expect(r3.intent).toMatchObject({ kind: 'balance', agent: { name: 'Trader Tilly' } })
  })
  it('balance of an unknown name says so', () => {
    const r = parseUtterance('balance of zorblax', CTX)
    expect(r.intent.kind).toBe('balance')
    expect(r.unresolved).toContain('zorblax')
  })
  it('queue readout', () => {
    expect(parseUtterance('what needs me', CTX).intent.kind).toBe('queue')
    expect(parseUtterance('read my queue', CTX).intent.kind).toBe('queue')
  })
})

describe('send', () => {
  it('send N CCY to NAME', () => {
    const r = parseUtterance('send 5 bvt to theo', CTX)
    expect(r.intent).toMatchObject({ kind: 'send', amount: 5, currency: 'BVT', to: { name: 'Trader Theo' } })
    expect(r.understood).toContain('You confirm')
  })
  it('word amounts and no currency', () => {
    const r = parseUtterance('transfer five to trader tilly', CTX)
    expect(r.intent).toMatchObject({ kind: 'send', amount: 5, to: { name: 'Trader Tilly' } })
    expect((r.intent as any).currency).toBeUndefined()
  })
  it('pay NAME N form', () => {
    const r = parseUtterance('pay tilly 12,5 bvt', CTX)
    expect(r.intent).toMatchObject({ kind: 'send', amount: 12.5, currency: 'BVT', to: { name: 'Trader Tilly' } })
  })
  it('unknown recipient is honest, still opens the door', () => {
    const r = parseUtterance('send 5 to zorblax', CTX)
    expect(r.intent).toMatchObject({ kind: 'send', amount: 5, toQuery: 'zorblax' })
    expect(r.unresolved).toContain('zorblax')
  })
})

describe('stake', () => {
  it('lock is the word the console says; stake still parses alongside it', () => {
    expect(parseUtterance('lock 10 with tilly', CTX).intent).toMatchObject({ kind: 'stake', amount: 10, agent: { name: 'Trader Tilly' } })
    expect(parseUtterance('lock 10 units', CTX).intent).toMatchObject({ kind: 'stake', amount: 10 })
    expect(parseUtterance('lock 10', CTX).understood).toContain('lock sheet')
    expect(parseUtterance('lock 10', CTX).understood).not.toMatch(/stake/i)
    expect(CAPABILITIES.join(' ')).not.toMatch(/stake/i)
  })
  it('stake with agent', () => {
    const r = parseUtterance('stake 10 with tilly', CTX)
    expect(r.intent).toMatchObject({ kind: 'stake', amount: 10, agent: { name: 'Trader Tilly' } })
  })
  it('bare stake amount', () => {
    const r = parseUtterance('stake ten', CTX)
    expect(r.intent).toMatchObject({ kind: 'stake', amount: 10 })
  })
})

describe('trade', () => {
  it('market buy', () => {
    const r = parseUtterance('buy 5 bld0', CTX)
    expect(r.intent).toMatchObject({ kind: 'trade', side: 'buy', qty: 5, symbol: 'BLD0' })
    expect((r.intent as any).limit).toBeUndefined()
    expect(r.understood).toContain('at market')
  })
  it('limit sell with at-price', () => {
    const r = parseUtterance('sell 2 qcc at 120', CTX)
    expect(r.intent).toMatchObject({ kind: 'trade', side: 'sell', qty: 2, symbol: 'QCC', limit: 120 })
  })
  it('shares-of phrasing and $ prefix', () => {
    const r = parseUtterance('buy five shares of $firm72', CTX)
    expect(r.intent).toMatchObject({ kind: 'trade', side: 'buy', qty: 5, symbol: 'FIRM72' })
  })
  it('§AGORAWORDS: points-of phrasing recognized ALONGSIDE shares-of, same result', () => {
    const r = parseUtterance('buy five points of $firm72', CTX)
    expect(r.intent).toMatchObject({ kind: 'trade', side: 'buy', qty: 5, symbol: 'FIRM72' })
    expect(r.intent).toEqual(parseUtterance('buy five shares of $firm72', CTX).intent)
  })
  it('unknown ticker is honest', () => {
    const r = parseUtterance('buy 5 zzz9', CTX)
    expect(r.intent).toMatchObject({ kind: 'trade', side: 'buy', qty: 5, symbolQuery: 'zzz9' })
    expect(r.unresolved).toContain('zzz9')
  })
  it('open trade for a symbol / bare trade', () => {
    expect(parseUtterance('open trade for qcc', CTX).intent).toMatchObject({ kind: 'trade', symbol: 'QCC' })
    expect(parseUtterance('trade', CTX).intent).toEqual({ kind: 'navigate', target: 'trade' })
  })
})

describe('guild', () => {
  it('bid with and without target', () => {
    expect(parseUtterance('bid 100 on the translation job', CTX).intent).toMatchObject({
      kind: 'guild-bid', amount: 100, ref: 'the translation job',
    })
    expect(parseUtterance('bid fifty', CTX).intent).toMatchObject({ kind: 'guild-bid', amount: 50 })
  })
  it('post a job with bounty', () => {
    const r = parseUtterance('post a job translate my docs for 200', CTX)
    expect(r.intent).toMatchObject({ kind: 'guild-post', title: 'translate my docs', bounty: 200 })
  })
  it('open order by ref', () => {
    expect(parseUtterance('open order 42', CTX).intent).toMatchObject({ kind: 'order', ref: '42' })
    expect(parseUtterance('show the order about the logo', CTX).intent).toMatchObject({ kind: 'order', ref: 'the logo' })
  })
})

describe('find + freeze + help + unknown', () => {
  it('find agent', () => {
    expect(parseUtterance('find agent caspian', CTX).intent).toMatchObject({ kind: 'find', query: 'caspian' })
    expect(parseUtterance('search for theo', CTX).intent).toMatchObject({ kind: 'find', query: 'theo' })
  })
  it('freeze opens the confirm door only', () => {
    const r = parseUtterance('emergency freeze', CTX)
    expect(r.intent.kind).toBe('freeze')
    expect(r.understood).toContain('until you confirm')
    expect(parseUtterance('freeze everything', CTX).intent.kind).toBe('freeze')
  })
  it('help lists capabilities', () => {
    expect(parseUtterance('help', CTX).intent.kind).toBe('help')
    expect(CAPABILITIES.length).toBeGreaterThan(5)
  })
  it('unknown echoes what was heard', () => {
    const r = parseUtterance('flarble the wombat', CTX)
    expect(r.intent).toMatchObject({ kind: 'unknown', heard: 'flarble the wombat' })
    expect(r.understood).toContain('flarble')
  })
  it('empty utterance', () => {
    expect(parseUtterance('', CTX).intent.kind).toBe('unknown')
  })
})

describe('money classification (S8)', () => {
  it('money doors flagged, read-only not', () => {
    expect(intentTouchesMoney(parseUtterance('send 5 to theo', CTX).intent)).toBe(true)
    expect(intentTouchesMoney(parseUtterance('buy 5 bld0', CTX).intent)).toBe(true)
    expect(intentTouchesMoney(parseUtterance('stake 10', CTX).intent)).toBe(true)
    expect(intentTouchesMoney(parseUtterance('emergency freeze', CTX).intent)).toBe(true)
    expect(intentTouchesMoney(parseUtterance('balance', CTX).intent)).toBe(false)
    expect(intentTouchesMoney(parseUtterance('go to trade', CTX).intent)).toBe(false)
    expect(intentTouchesMoney(parseUtterance('what needs me', CTX).intent)).toBe(false)
  })
})

describe('grammar never executes (the iron rule stated in text)', () => {
  it('every money-door understood string names a confirm surface', () => {
    for (const utt of ['send 5 to theo', 'stake 10 with tilly', 'buy 5 bld0', 'bid 100 on x', 'post a job x for 50']) {
      const r = parseUtterance(utt, CTX)
      expect(r.understood.toLowerCase()).toMatch(/you confirm/)
    }
  })
})


// ── §OURSTATE-2: the chat surface joins the grammar (fill, never fire) ──
describe('message / reply intents', () => {
  const roster = [{ did: 'did:theprotocol:t1', name: 'Trader Tilly' }] as any

  it('message <name> about <body> resolves the roster and drafts', () => {
    const r = parseUtterance('message tilly about the invoice', { roster })
    expect(r.intent.kind).toBe('message')
    expect((r.intent as any).to?.name).toBe('Trader Tilly')
    expect((r.intent as any).body).toBe('the invoice')
    expect(r.understood).toMatch(/Nothing sends until you press send/)
  })

  it('an unmatched name is UNRESOLVED, never a guess', () => {
    const r = parseUtterance('dm nobody-here', { roster })
    expect(r.intent.kind).toBe('message')
    expect((r.intent as any).to).toBeUndefined()
    expect(r.unresolved).toMatch(/No agent in your roster matched/)
  })

  it('reply drafts into the current thread', () => {
    const r = parseUtterance('reply the invoice is paid')
    expect(r.intent.kind).toBe('reply')
    expect((r.intent as any).body).toBe('the invoice is paid')
  })

  it('bare reply just opens the composer', () => {
    expect(parseUtterance('reply').intent.kind).toBe('reply')
  })

  it('does NOT swallow the money/queue intents it sits next to', () => {
    expect(parseUtterance('send 5 bvt to tilly', { roster }).intent.kind).toBe('send')
    expect(parseUtterance('what needs me').intent.kind).toBe('queue')
    expect(parseUtterance('freeze').intent.kind).toBe('freeze')
    expect(parseUtterance('balance').intent.kind).toBe('balance')
    expect(parseUtterance('help').intent.kind).toBe('help')
  })
})

/* §VOICEHIRE (H3.4) — the hire/discover grammar. The law under test: every
 * parse is at most a FILLED door; the echo says what will NOT happen. */
describe('voice-hire intents', () => {
  const roster = [
    { did: 'did:x:tilly', name: 'Trader Tilly' },
    { did: 'did:x:sybil', name: 'Sybil' },
  ]

  it('market find with a price cap parses q + cap + currency', () => {
    const r = parseUtterance('find me a translation agent under 2 avt')
    expect(r.intent.kind).toBe('market-find')
    expect((r.intent as any).query).toBe('translation')
    expect((r.intent as any).maxPrice).toBe(2)
    expect((r.intent as any).currency).toBe('AVT')
    expect(r.understood).toMatch(/no price filter/)
  })

  it('market find without a cap stays a plain network search', () => {
    const r = parseUtterance('hire a research agent')
    expect(r.intent.kind).toBe('market-find')
    expect((r.intent as any).query).toBe('research')
    expect((r.intent as any).maxPrice).toBeUndefined()
  })

  it('roster find is NOT swallowed by market find', () => {
    expect(parseUtterance('find agent theo').intent.kind).toBe('find')
    expect(parseUtterance('search tilly').intent.kind).toBe('find')
  })

  it('offer parses agent + amount + currency + title, roster-matched', () => {
    const r = parseUtterance('offer sybil 5 avt for logo design', { roster })
    expect(r.intent.kind).toBe('offer')
    expect((r.intent as any).to?.did).toBe('did:x:sybil')
    expect((r.intent as any).amount).toBe(5)
    expect((r.intent as any).currency).toBe('AVT')
    expect((r.intent as any).title).toBe('logo design')
    expect(r.understood).toMatch(/Nothing posts until you press it/)
  })

  it('offer to an unmatched name resolves honestly to a search', () => {
    const r = parseUtterance('offer stranger 3 bvt for research', { roster })
    expect(r.intent.kind).toBe('offer')
    expect((r.intent as any).to).toBeUndefined()
    expect(r.unresolved).toMatch(/No agent in your roster matched/)
  })

  it('hire the firm goes to the firms lane, never an agent search', () => {
    const r = parseUtterance('hire the firm meridian')
    expect(r.intent.kind).toBe('hire-firm')
    expect((r.intent as any).name).toBe('meridian')
    expect(r.understood).toMatch(/intake door/)
  })

  it('help names the three new capabilities', () => {
    expect(CAPABILITIES.join(' ')).toMatch(/find me a translation agent under 2/)
    expect(CAPABILITIES.join(' ')).toMatch(/offer Sybil 5 for logo design/)
    expect(CAPABILITIES.join(' ')).toMatch(/hire the firm Meridian/)
  })
})

/* D6-835 (agentvault2-d6, 2026-10-25): the grammar knew only the retired triangle's units (BVT, AVT, JDAY) and its
 * help named AVT and BVT on every frame. On EU (ECU beside ASIA's ACU) "send 5 ecu to theo" was not understood and
 * "send 5 avt to theo" prefilled a unit the frame does not have. The caller now passes the network's units; the
 * examples name the frame's own. RED control: against the old grammar the ECU send is unknown and the help says AVT. */
describe('the units are the network\'s, not the retired triangle\'s', () => {
  const EU: GrammarContext = { roster: ROSTER, units: ['ECU', 'ACU'] }

  it('takes the frame\'s own unit and a peer\'s', () => {
    const r = parseUtterance('send 5 ecu to theo', EU)
    expect(r.intent).toMatchObject({ kind: 'send', amount: 5, currency: 'ECU', to: { name: 'Trader Theo' } })
    expect(parseUtterance('offer theo 3 acu for a translation', EU).intent).toMatchObject({ kind: 'offer', currency: 'ACU' })
    expect(parseUtterance('find me a translation agent under 2 ecu', EU).intent).toMatchObject({ kind: 'market-find', maxPrice: 2, currency: 'ECU' })
    expect(parseUtterance('stake 10 ecu with tilly', EU).intent.kind).toBe('stake')
  })

  it('a unit this network does not speak is no unit: never a prefill in it', () => {
    const r = parseUtterance('send 5 avt to theo', EU)
    expect((r.intent as { currency?: string }).currency).not.toBe('AVT')
    expect(r.intent.kind).not.toBe('send')
  })

  it('control: without units the legacy three still parse (the tests above them)', () => {
    expect(parseUtterance('send 5 bvt to theo', { roster: ROSTER }).intent).toMatchObject({ kind: 'send', currency: 'BVT' })
  })

  it('the examples name the frame\'s unit, or none while it is unknown', () => {
    const eu = CAPABILITY_ENTRIES.map(c => exampleIn(c.cmd, 'ECU')).join(' ')
    expect(eu).toMatch(/send 5 ECU to Theo/)
    expect(eu).toMatch(/under 2 ECU/)
    expect(eu).toMatch(/offer Sybil 5 ECU for logo design/)
    expect(eu).not.toMatch(/\b(AVT|BVT|JDAY)\b|\{unit\}/)
    const unknown = CAPABILITY_ENTRIES.map(c => exampleIn(c.cmd, '')).join(' ')
    expect(unknown).toMatch(/send 5 to Theo/)
    expect(unknown).not.toMatch(/\{unit\}|  /)
  })

  it('each example, unit filled, parses with that unit (an example is an instruction that works)', () => {
    const withUnit = CAPABILITY_ENTRIES.filter(e => e.cmd.includes('{unit}'))
    expect(withUnit.map(e => e.key)).toEqual(['send', 'marketFind', 'offer']) // a loop over nothing passes
    for (const c of withUnit) {
      const said = exampleIn(c.cmd, 'ECU').replace(/^"|"$/g, '')
      const r = parseUtterance(said, { ...EU, roster: [...ROSTER, { did: 'did:x:sybil', name: 'Sybil' }] })
      expect(r.intent.kind, said).not.toBe('unknown')
      expect((r.intent as { currency?: string }).currency, said).toBe('ECU')
    }
  })
})
