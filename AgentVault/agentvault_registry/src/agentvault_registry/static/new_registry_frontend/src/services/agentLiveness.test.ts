/**
 * §COCKPITPOLISH P2 — unit proof for the shared ranking rail.
 *
 * The point of these is the ORDER, so the ranking cases assert against inputs ordered
 * WORST-FIRST: a ranking test fed an already-sorted list passes on a function that
 * returns its argument, which is the "test that cannot fail" this project keeps
 * re-learning. Each ranking case also carries a control that nothing was DROPPED.
 */
import { describe, it, expect } from 'vitest'
import {
  livenessTier, secondsSinceCall, probeVerdict, hasUsableCredentials, hasRealName,
  rankScore, rankAgents, countLive, FRESH_S, RECENT_S,
} from './agentLiveness'

const NOW = Date.parse('2026-08-31T12:00:00Z')
const agoS = (s: number) => new Date(NOW - s * 1000).toISOString()

describe('livenessTier', () => {
  it('bands by age of the last call', () => {
    expect(livenessTier({ last_active_at: agoS(30) }, NOW)).toBe('fresh')
    expect(livenessTier({ last_active_at: agoS(FRESH_S + 1) }, NOW)).toBe('recent')
    expect(livenessTier({ last_active_at: agoS(RECENT_S + 1) }, NOW)).toBe('quiet')
    expect(livenessTier({ last_active_at: agoS(48 * 3600) }, NOW)).toBe('silent')
  })
  it('never called and unparseable are BOTH "never", not "just now"', () => {
    expect(livenessTier({}, NOW)).toBe('never')
    expect(livenessTier({ last_active_at: 'not-a-date' }, NOW)).toBe('never')
    expect(secondsSinceCall({ last_active_at: 'not-a-date' }, NOW)).toBeNull()
  })
})

describe('probeVerdict', () => {
  it('is null when never probed — never-probed is not unhealthy', () => {
    expect(probeVerdict({})).toBeNull()
    expect(probeVerdict({ last_health: '' })).toBeNull()
    expect(probeVerdict({ last_health: 'weird' })).toBeNull()
  })
  it('reads the three real verdicts', () => {
    expect(probeVerdict({ last_health: 'healthy' })).toBe('healthy')
    expect(probeVerdict({ last_health: 'UNREACHABLE' })).toBe('unreachable')
  })
})

describe('credentials and names', () => {
  it('invalid credentials are NOT usable credentials', () => {
    expect(hasUsableCredentials({ hasCredentials: true, hasInvalidCredentials: true })).toBe(false)
    expect(hasUsableCredentials({ hasCredentials: true })).toBe(true)
    expect(hasUsableCredentials({ client_id: 'a', client_secret: 'b' })).toBe(true)
    expect(hasUsableCredentials({ client_id: 'a' })).toBe(false)
  })
  it('a DID stub and the empty placeholder are not names', () => {
    expect(hasRealName({ name: 'did:theprotocol:9b9a07' })).toBe(false)
    expect(hasRealName({ name: '<no name>' })).toBe(false)
    expect(hasRealName({ name: '  ' })).toBe(false)
    expect(hasRealName({ name: 'Ironhand Alpha' })).toBe(true)
    expect(hasRealName({ card_data: { name: 'Glass Gerald' } })).toBe(true)
  })
})

describe('rankScore', () => {
  it('puts the acting agent above even a live one', () => {
    const live = { did: 'a', last_active_at: agoS(10) }
    const acting = { did: 'b', last_active_at: agoS(90000) }
    expect(rankScore(acting, { activeDid: 'b', nowMs: NOW }))
      .toBeGreaterThan(rankScore(live, { activeDid: 'b', nowMs: NOW }))
  })
  it('ranks live above probed-healthy above credentialed above named', () => {
    const s = (a: any) => rankScore(a, { nowMs: NOW })
    expect(s({ last_active_at: agoS(60) })).toBeGreaterThan(s({ last_health: 'healthy' }))
    expect(s({ last_health: 'healthy' })).toBeGreaterThan(s({ hasCredentials: true }))
    expect(s({ hasCredentials: true })).toBeGreaterThan(s({ name: 'Named Thing' }))
    expect(s({ name: 'Named Thing' })).toBeGreaterThan(s({ status: 'active' }))
    expect(s({ status: 'revoked' })).toBe(0)
  })
})

describe('credentialsFirst — the header switcher\'s question', () => {
  it('a credentialed idle agent outranks an uncredentialed LIVE one, because you cannot act as what you hold no secret for', () => {
    const out = rankAgents([
      { did: 'live-no-creds', last_active_at: agoS(5) },
      { did: 'idle-creds', hasCredentials: true },
    ], { nowMs: NOW, credentialsFirst: true }).map(a => a.did)
    expect(out).toEqual(['idle-creds', 'live-no-creds'])
  })
  it('and among credentialed agents the live one still comes first', () => {
    const out = rankAgents([
      { did: 'creds-idle', hasCredentials: true },
      { did: 'creds-live', hasCredentials: true, last_active_at: agoS(5) },
    ], { nowMs: NOW, credentialsFirst: true }).map(a => a.did)
    expect(out).toEqual(['creds-live', 'creds-idle'])
  })
  it('CONTROL — without the flag the ordering flips, so the flag is doing the work', () => {
    const rows = [
      { did: 'live-no-creds', last_active_at: agoS(5) },
      { did: 'idle-creds', hasCredentials: true },
    ]
    expect(rankAgents(rows, { nowMs: NOW }).map(a => a.did)).toEqual(['live-no-creds', 'idle-creds'])
  })
  it('the acting agent still wins outright', () => {
    const out = rankAgents([
      { did: 'creds-live', hasCredentials: true, last_active_at: agoS(5) },
      { did: 'acting' },
    ], { nowMs: NOW, credentialsFirst: true, activeDid: 'acting' }).map(a => a.did)
    expect(out[0]).toBe('acting')
  })
})

describe('rankAgents', () => {
  it('lifts the live fleet over a wall of fixtures — the actual registry-a shape', () => {
    // Deliberately ordered WORST first, which is what created_at DESC returns.
    const input = [
      { did: 'd1', name: '<no name>' },
      { did: 'd2', name: 'forge-a-gen-7' },
      { did: 'd3', name: 'extmtls-probe-invalid' },
      { did: 'd4', name: 'Glass Gerald', last_active_at: agoS(300), last_health: 'healthy' },
      { did: 'd5', name: 'Ironhand Alpha', last_active_at: agoS(20) },
      { did: 'd6', name: 'CurrencyAgent', last_health: 'healthy' },
    ]
    const out = rankAgents(input, { nowMs: NOW }).map(a => a.did)
    expect(out.slice(0, 3)).toEqual(['d5', 'd4', 'd6'])
    // CONTROL: nothing was dropped. Ranking is not filtering.
    expect(out.length).toBe(input.length)
    expect(new Set(out)).toEqual(new Set(input.map(a => a.did)))
  })
  it('breaks ties by who called most recently, and never-called sinks below called', () => {
    const out = rankAgents([
      { did: 'never' },
      { did: 'older', last_active_at: agoS(600) },
      { did: 'newer', last_active_at: agoS(5) },
    ], { nowMs: NOW }).map(a => a.did)
    expect(out).toEqual(['newer', 'older', 'never'])
  })
  it('does not mutate its input', () => {
    const input = [{ did: 'a' }, { did: 'b', last_active_at: agoS(5) }]
    const before = input.map(a => a.did)
    rankAgents(input, { nowMs: NOW })
    expect(input.map(a => a.did)).toEqual(before)
  })
})

describe('countLive', () => {
  it('counts only fresh+recent, so a pane can say "0 alive" honestly', () => {
    expect(countLive([
      { last_active_at: agoS(10) },
      { last_active_at: agoS(RECENT_S - 5) },
      { last_active_at: agoS(RECENT_S + 5) },
      {},
    ], NOW)).toBe(2)
  })
})
