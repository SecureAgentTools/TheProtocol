import { describe, it, expect } from 'vitest'
import { agoWord, cleanSessions, secondsSince } from './agentStatus'

/** V0662 (OurChat lane): the session board's rules. BASE (f6a47e3c9): the module does not exist. */

describe('the rows', () => {
  it('keep what the registry said and never make "unknown" into something else', () => {
    const [r] = cleanSessions([{ key: 'agt:a', name: 'session-lead', state: 'unknown', wake_mode: null, last_wake_at: null, wakes_24h: null, reported_at: 'x', age_s: 400 }])
    expect(r).toMatchObject({ key: 'agt:a', state: 'unknown', wake_mode: null, wakes_24h: null, age_s: 400 })
  })
  it('read a missing count as none, not zero', () => {
    expect(cleanSessions([{ key: 'agt:a', state: 'active' }])[0].wakes_24h).toBeNull()
    expect(cleanSessions([{ key: 'agt:a', state: 'active', wakes_24h: 0 }])[0].wakes_24h).toBe(0)
  })
  it('turn a state this console does not know into unknown, and drop an entry with no key', () => {
    expect(cleanSessions([{ key: 'agt:a', state: 'asleep' }])[0].state).toBe('unknown')
    expect(cleanSessions([null, 5, {}, { key: 7 }])).toEqual([])
    expect(cleanSessions('nope')).toEqual([])
  })
  it('name a row by its key when it has no name', () => {
    expect(cleanSessions([{ key: 'agt:did:x', state: 'active' }])[0].name).toBe('agt:did:x')
  })
})

describe('how long ago', () => {
  it('is in seconds, minutes, hours and days', () => {
    expect(agoWord(30)).toBe('30 s')
    expect(agoWord(0)).toBe('1 s')
    expect(agoWord(120)).toBe('2 min')
    expect(agoWord(7200)).toBe('2 h')
    expect(agoWord(3 * 86400)).toBe('3 d')
  })
  it('is none for nothing, a negative or a non-number', () => {
    for (const bad of [null, undefined, -1, NaN]) expect(agoWord(bad as any)).toBeNull()
  })
  it('seconds since an ISO time, never negative, none for garbage', () => {
    const now = Date.parse('2026-11-13T12:10:00Z')
    expect(secondsSince('2026-11-13T12:05:00Z', now)).toBe(300)
    expect(secondsSince('2026-11-13T12:20:00Z', now)).toBe(0)
    expect(secondsSince('garbage', now)).toBeNull()
    expect(secondsSince(null, now)).toBeNull()
  })
})
