import { describe, it, expect } from 'vitest'
import { YOU, assistantIds, rememberAssistant, readAsks, writeAsks, type AssistAsk } from './assistOn'

/**
 * V0654 (ap) (order gwo_03a846cb91b37628c3c6710a): the assistant's switch is per identity and per room, on this device;
 * what you asked it stays in this browser session and never anywhere else. BASE (V0653): no such module.
 */
function kv(): Storage {
  const m = new Map<string, string>()
  return {
    getItem: (k: string) => (m.has(k) ? (m.get(k) as string) : null),
    setItem: (k: string, v: string) => { m.set(k, String(v)) },
    removeItem: (k: string) => { m.delete(k) },
    clear: () => m.clear(), key: () => null, get length() { return m.size },
  } as Storage
}
const AGENT = 'did:theprotocol:eu.theprotocol.cloud:19c1aa48'

describe('the switch: per identity, per room, off unless switched on', () => {
  it('is off everywhere until switched on', () => {
    const s = kv()
    expect(assistantIds('room-a', s)).toEqual([])
  })

  it('switched on for you, it is on for you in that room only', () => {
    const s = kv()
    rememberAssistant('room-a', YOU, true, s)
    expect(assistantIds('room-a', s)).toEqual([YOU])
    expect(assistantIds('room-b', s)).toEqual([])
  })

  it('each identity has its own switch', () => {
    const s = kv()
    rememberAssistant('room-a', AGENT, true, s)
    expect(assistantIds('room-a', s)).toEqual([AGENT])
    rememberAssistant('room-a', YOU, true, s)
    rememberAssistant('room-a', AGENT, false, s)
    expect(assistantIds('room-a', s)).toEqual([YOU])
  })

  it('off for every identity leaves nothing stored', () => {
    const s = kv()
    rememberAssistant('room-a', YOU, true, s)
    rememberAssistant('room-a', YOU, false, s)
    expect(s.getItem('ourchat.assist.room-a')).toBeNull()
  })

  it('a stored value that is not an identity is ignored, never trusted', () => {
    const s = kv()
    s.setItem('ourchat.assist.room-a', JSON.stringify(['you', 'javascript:alert(1)', 7, 'did:x']))
    expect(assistantIds('room-a', s)).toEqual(['you', 'did:x'])
    s.setItem('ourchat.assist.room-a', '{not json')
    expect(assistantIds('room-a', s)).toEqual([])
    expect(rememberAssistant('room-a', 'someone', true, s)).toEqual([])
  })
})

describe('what you asked: this browser session, this room', () => {
  const ask = (ref: string, state: AssistAsk['state'], conv = 'room-a'): AssistAsk =>
    ({ ref, conversationId: conv, prompt: `ask ${ref}`, who: '', afterSeq: 3, state })

  it('is kept per room and read back', () => {
    const s = kv()
    writeAsks('room-a', [ask('r1', 'answered'), ask('r2', 'answered', 'room-b')], s)
    expect(readAsks('room-a', 'reloaded', s).map(a => a.ref)).toEqual(['r1'])
    expect(readAsks('room-b', 'reloaded', s)).toEqual([])
  })

  it('a request still waiting when the page went away reads back as one to ask again', () => {
    const s = kv()
    writeAsks('room-a', [ask('r1', 'waiting')], s)
    const [a] = readAsks('room-a', 'the page reloaded', s)
    expect(a.state).toBe('failed')
    expect(a.error).toBe('the page reloaded')
    expect(a.ref).toBe('r1')     // asking again with its ref returns an answer already posted
  })

  it('keeps the newest twenty, and nothing when none is left', () => {
    const s = kv()
    writeAsks('room-a', Array.from({ length: 25 }, (_, i) => ask(`r${i}`, 'answered')), s)
    const kept = readAsks('room-a', '', s)
    expect(kept.length).toBe(20)
    expect(kept[0].ref).toBe('r5')
    writeAsks('room-a', [], s)
    expect(s.getItem('ourchat.assistAsks.room-a')).toBeNull()
  })
})
