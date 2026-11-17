/**
 * V0662 console polish, item 3 (order gwo_0aa7b875cbf65b6347f5f775): the Guild order page in words.
 *
 * The page showed the delivery as raw JSON, each event by its stored name (xf_stage_retained), and each party as
 * fifteen characters of a DID. These are the page's words: a delivery as fields a person can copy, an event as a word
 * with its stored name kept for the hover, and a party by the name the order's answer gives (the DID on hover).
 * Red on f569f6a6e: the module does not exist.
 */
import { describe, it, expect } from 'vitest'
import { deliveryFields, eventWord, partyLabel } from './orderView'

const t = (_k: string, fallback: string) => fallback

describe('a delivery as fields', () => {
  it('the link, the note, the hash and each commit, in that order, each one copyable', () => {
    const f = deliveryFields({ text: 'Done, see the branch', hash: 'sha256:ab12', uri: 'https://git.example/x',
      commits: [{ repo: 'theprotocol/AgentVault', commit: 'c4a6b49ab' }] }, t)
    expect(f.map((x) => x.key)).toEqual(['uri', 'text', 'hash', 'commit:0'])
    expect(f.every((x) => x.copy)).toBe(true)
    expect(f[0]).toMatchObject({ label: 'Link', value: 'https://git.example/x', href: 'https://git.example/x' })
    expect(f[3]).toMatchObject({ label: 'Commit', value: 'c4a6b49ab', detail: 'theprotocol/AgentVault' })
  })
  it('only an http or https link is a link; anything else is text to copy', () => {
    const [f] = deliveryFields({ uri: 'javascript:alert(1)' }, t)
    expect(f.href).toBeUndefined()
    expect(f.value).toBe('javascript:alert(1)')
  })
  it('a key it does not know is still shown, by its name, after the known ones; an object is shown as JSON', () => {
    const f = deliveryFields({ zeta: 'last', alpha: { n: 1 }, uri: 'https://x.example' }, t)
    expect(f.map((x) => x.key)).toEqual(['uri', 'alpha', 'zeta'])
    expect(f[1]).toMatchObject({ label: 'Alpha', value: '{"n":1}' })
  })
  it('nothing to show is an empty list, never a field that says "null"', () => {
    expect(deliveryFields(null, t)).toEqual([])
    expect(deliveryFields({ text: '', uri: null }, t)).toEqual([])
  })
})

describe('an event as a word', () => {
  it('each stored name the Guild writes reads as a word', () => {
    for (const [stored, word] of [['posted', 'Posted'], ['bid', 'Bid placed'], ['awarded', 'Awarded'],
      ['submitted', 'Work submitted'], ['verified', 'Accepted'], ['settled', 'Paid out'], ['disputed', 'Disputed'],
      ['xf_stage_retained', 'Cross-frame stage kept'], ['quantum_test_agreed', 'Acceptance test agreed']]) {
      expect(eventWord(stored, t)).toBe(word)
    }
  })
  it('a name it does not know reads as its words, never as a blank', () => {
    expect(eventWord('xf_new_thing', t)).toBe('Xf new thing')
    expect(eventWord('', t)).toBe('Event')
  })
})

describe('a party by name', () => {
  it('the name the order answers; "you" for the reader; the DID shortened where no card names it', () => {
    const did = 'did:theprotocol:eu.test:worker-agent-0001'
    expect(partyLabel(did, { [did]: 'session-code' }, false, t)).toBe('session-code')
    expect(partyLabel(did, { [did]: 'session-code' }, true, t)).toBe('you')
    expect(partyLabel(did, { [did]: null }, false, t)).toBe('did:theprotocol…-0001')
    expect(partyLabel(null, {}, false, t)).toBe('—')
  })
})
