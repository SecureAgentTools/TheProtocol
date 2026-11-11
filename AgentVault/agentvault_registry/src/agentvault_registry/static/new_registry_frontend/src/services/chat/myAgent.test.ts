import { describe, it, expect } from 'vitest'
import { fromOwnAgent, markedOwnAgents, type OwnAgentLine } from './myAgent'

/**
 * V0659 (o) (order gwo_d7ce94c88a55f629c17b4ff7): the one rule the thread asks of a line, "did one of my own agents write
 * this itself?". The registry answers it (sender_is_my_agent: the sending agent's creator is the reader); a line he typed
 * as his agent through his own session (sent_by_owner) is his own; a live line that came without the field takes what the
 * registry said about the same agent earlier in the thread. BASE (origin/v0657/cut): the module does not exist.
 */
const AGENT = 'did:theprotocol:eu.test:Session-Lead'
const line = (over: Partial<OwnAgentLine> = {}): OwnAgentLine => ({ sender_ptype: 'agent', sender_id: AGENT, ...over })

describe('a line from one of my own agents', () => {
  it('is the registry\'s word: marked is his agent\'s, unmarked is not', () => {
    expect(fromOwnAgent(line({ sender_is_my_agent: true }))).toBe(true)
    expect(fromOwnAgent(line({ sender_is_my_agent: false }))).toBe(false)
  })

  it('is never a line he typed as his agent through his own session', () => {
    expect(fromOwnAgent(line({ sender_is_my_agent: true, sent_by_owner: true }))).toBe(false)
  })

  it('is only ever an agent\'s line: his own, a rail\'s and a peer\'s are not', () => {
    expect(fromOwnAgent({ sender_ptype: 'developer', sender_id: '6', sender_is_my_agent: true })).toBe(false)
    expect(fromOwnAgent({ sender_ptype: 'system', sender_id: 'guild', sender_is_my_agent: true })).toBe(false)
    expect(fromOwnAgent({ sender_ptype: 'remote', sender_id: `${AGENT}@https://asia.test`, sender_is_my_agent: true })).toBe(false)
    expect(fromOwnAgent(null)).toBe(false)
  })

  it('a line without the field takes what the thread already said about that agent (any case of its DID)', () => {
    const known = markedOwnAgents([line({ sender_is_my_agent: true }), line({ sender_id: 'did:x:other', sender_is_my_agent: false })])
    expect([...known]).toEqual([AGENT.toLowerCase()])
    expect(fromOwnAgent(line({ sender_id: AGENT.toUpperCase() }), known)).toBe(true)
    expect(fromOwnAgent(line({ sender_id: 'did:x:other' }), known)).toBe(false)
    expect(fromOwnAgent(line(), new Set())).toBe(false)               // nothing said yet: not marked
    expect(fromOwnAgent(line({ sender_is_my_agent: false }), known)).toBe(false)   // an answer beats the memory
  })

  it('nothing is learned from lines the registry did not mark, or from a person\'s lines', () => {
    expect(markedOwnAgents([line(), line({ sender_is_my_agent: false }),
      { sender_ptype: 'developer', sender_id: '6', sender_is_my_agent: true }]).size).toBe(0)
    expect(markedOwnAgents(null).size).toBe(0)
  })
})
