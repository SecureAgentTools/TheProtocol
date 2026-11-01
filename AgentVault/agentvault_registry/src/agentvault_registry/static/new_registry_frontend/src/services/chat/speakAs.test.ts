/**
 * V0652 (aj) (order gwo_9fa441b938ff31f95662243f): a message goes out as you unless an agent was chosen for this
 * thread; the choice is remembered per thread; an acting agent chosen elsewhere never carries in.
 */
import { describe, expect, it } from 'vitest'
import { rememberedSpeaker, rememberSpeaker, resolveSpeaker } from './speakAs'

function memory() {
  const m = new Map<string, string>()
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v) },
    removeItem: (k: string) => { m.delete(k) }, m }
}
const TESTER = 'did:theprotocol:eu.theprotocol.cloud:19c1aa48'
const OTHER = 'did:theprotocol:eu.theprotocol.cloud:f1947aec'

describe('who a message goes out as', () => {
  it('you, in a room, whatever agent the console is acting as', () => {
    expect(resolveSpeaker({ isAgentThread: false, activeDid: TESTER, remembered: null })).toBe(null)
    expect(resolveSpeaker({ isAgentThread: false, activeDid: null, remembered: null })).toBe(null)
  })

  it('the agent chosen for this thread, while it is the acting agent', () => {
    expect(resolveSpeaker({ isAgentThread: false, activeDid: TESTER, remembered: TESTER })).toBe(TESTER)
  })

  it('you again when the acting agent changed on another screen (never another agent silently)', () => {
    expect(resolveSpeaker({ isAgentThread: false, activeDid: OTHER, remembered: TESTER })).toBe(null)
    expect(resolveSpeaker({ isAgentThread: false, activeDid: null, remembered: TESTER })).toBe(null)
  })

  it("an agent's service thread speaks as the acting agent: the rail's payer", () => {
    expect(resolveSpeaker({ isAgentThread: true, activeDid: OTHER, remembered: null })).toBe(OTHER)
  })
})

describe('the choice is remembered per thread', () => {
  it('per thread, and "you" stores nothing', () => {
    const s = memory()
    rememberSpeaker('room-a', TESTER, s)
    expect(rememberedSpeaker('room-a', s)).toBe(TESTER)
    expect(rememberedSpeaker('room-b', s)).toBe(null)
    rememberSpeaker('room-a', null, s)
    expect(rememberedSpeaker('room-a', s)).toBe(null)
    expect(s.m.size).toBe(0)
  })

  it('a stored value that is not a DID is no choice', () => {
    const s = memory()
    s.setItem('ourchat.speakAs.room-a', 'nonsense')
    expect(rememberedSpeaker('room-a', s)).toBe(null)
  })
})
