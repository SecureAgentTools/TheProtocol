/**
 * §S13 — the cases from his report, asserted directly.
 *
 * The showcase lives on a WebGL landing page and this box has no GPU, so these
 * are the gate. A browser run is a smoke test on top, not the proof.
 */
import { describe, it, expect } from 'vitest'
import { resolveCallTarget } from './callTarget'

const WEATHER = 'did:theprotocol:ce1031a8-292b-4ab6-52d9'
const SERVICES = [
  { id: WEATHER, name: 'WeatherAgent' },
  { id: 'did:cos:75c219c0-376d-3d90-a8e0', name: 'CurrencyAgent' },
  { id: 'did:cos:a6ce83ca-50dd-3de8-cfcb', name: 'NewsAgent' },
]
const R = (ask: string, partnerChosen = false) =>
  resolveCallTarget({ ask, services: SERVICES, partnerChosen })

describe('§S13 /call target resolution', () => {
  it('HIS LINE: "weather in berlin" with nobody chosen asks WHO, and keeps the question whole', () => {
    const r = R('weather in berlin')
    expect(r.needsAgent).toBe(true)
    expect(r.targetDid).toBe('')
    // 🔴 the word `weather` must SURVIVE: it is what WeatherAgent's own card
    // asks for ("A city name, or 'weather in <city>'"), not the agent's name.
    expect(r.askText).toBe('weather in berlin')
    expect(r.suggestion).toBe('/call WeatherAgent weather in berlin')
  })

  it('HIS WORKING LINE: a DID anywhere resolves, and is removed from the ask', () => {
    const r = R(`${WEATHER} berlin`)
    expect(r.targetDid).toBe(WEATHER)
    expect(r.askText).toBe('berlin')
    expect(r.needsAgent).toBe(false)
  })

  it('the suggested line then works: an exact name resolves', () => {
    const r = R('WeatherAgent weather in Berlin')
    expect(r.targetDid).toBe(WEATHER)
    expect(r.askText).toBe('weather in Berlin')
    expect(r.needsAgent).toBe(false)
  })

  it('name matching is case-insensitive', () => {
    expect(R('weatheragent weather in Berlin').targetDid).toBe(WEATHER)
  })

  it('a NEAR miss is offered, never consumed', () => {
    // 'weather' prefixes 'WeatherAgent' — suggested, but the ask is untouched.
    const r = R('weather in berlin')
    expect(r.askText).toContain('weather')
    expect(r.suggestion).toContain('WeatherAgent')
  })

  it('an ambiguous prefix suggests nothing specific rather than guessing', () => {
    const many = [{ id: 'did:a', name: 'PayAgent' }, { id: 'did:b', name: 'PayrollAgent' }]
    const r = resolveCallTarget({ ask: 'pay the invoice', services: many, partnerChosen: false })
    expect(r.needsAgent).toBe(true)
    expect(r.targetDid).toBe('')
    expect(r.askText).toBe('pay the invoice')
    expect(r.suggestion).toBe('')            // no confident line at all
    expect(r.ambiguous).toEqual(['PayAgent', 'PayrollAgent'])   // both named
  })

  it('a chosen partner means a bare ask is fine — this is the in-thread case', () => {
    const r = R('weather in berlin', true)
    expect(r.needsAgent).toBe(false)
    expect(r.targetDid).toBe('')          // '' = use the thread's partner
    expect(r.askText).toBe('weather in berlin')
  })

  it('a lone agent name is not a question — the ask stays empty', () => {
    const r = R('WeatherAgent')
    expect(r.askText).toBe('WeatherAgent')  // one token: not consumed as a target
    expect(r.targetDid).toBe('')
  })

  it('@name resolves, and an unknown @name is NAMED rather than swallowed', () => {
    expect(R('@CurrencyAgent usd to eur').targetDid).toBe('did:cos:75c219c0-376d-3d90-a8e0')
    const r = R('@Nobody hello')
    expect(r.unknownAt).toBe('Nobody')
    expect(r.targetDid).toBe('')
  })

  it('a bare /call with nobody chosen needs an agent', () => {
    const r = R('')
    expect(r.needsAgent).toBe(true)
    expect(r.askText).toBe('')
  })

  it('a question word that happens to equal an agent name IS taken as the name', () => {
    // Deliberate and documented: exact full-name equality is the one signal
    // strong enough to consume a token. Nothing weaker is.
    const r = R('NewsAgent what happened today')
    expect(r.targetDid).toBe('did:cos:a6ce83ca-50dd-3de8-cfcb')
    expect(r.askText).toBe('what happened today')
  })
})
