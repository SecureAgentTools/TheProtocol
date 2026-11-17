import { describe, it, expect } from 'vitest'
import { FALLBACK_WAIT_S, MAX_HELD_TRIES, MAX_WAIT_S, dueRetry, held, newLine, failedLine, sentLine, settle, tick, waitSeconds } from './relayHold'

/**
 * V0664 (order gwo_874694de65551c5c1488641c): the states a sender's own line goes through when the cross-frame relay limit holds it
 * back. The numbers come from the host's limit (Retry-After, read by the chat client as retryAfterS); an older host that sends none
 * gets one fixed fallback, and the wait is bounded so a bad number cannot park a line for an hour.
 */
const base = () => newLine({ clientRef: 'ref-1', body: 'hello', replyTo: null })

describe('how long to wait', () => {
  it('is the limit\'s own number, rounded up and bounded', () => {
    expect(waitSeconds({ retryAfterS: 17 })).toBe(17)
    expect(waitSeconds({ retryAfterS: 2.2 })).toBe(3)
    expect(waitSeconds({ retryAfterS: 99999 })).toBe(MAX_WAIT_S)
  })
  it('is one fixed fallback when the host named none, or a nonsense number', () => {
    for (const e of [null, undefined, {}, { retryAfterS: 0 }, { retryAfterS: -4 }, { retryAfterS: Number.NaN }]) expect(waitSeconds(e as any)).toBe(FALLBACK_WAIT_S)
  })
})

describe('a held line', () => {
  it('waits the limit\'s seconds, counting a try, and shows no error', () => {
    const l = held(base(), { retryAfterS: 17 })
    expect(l).toMatchObject({ state: 'waiting', tries: 1, secondsLeft: 17 })
    expect(l.error).toBeUndefined()
  })
  it('counts down to zero and is then due for the same send again, and only a waiting line counts down', () => {
    let l = held(base(), { retryAfterS: 2 })
    expect(dueRetry(l)).toBe(false)
    l = tick(l); expect(l.secondsLeft).toBe(1); expect(dueRetry(l)).toBe(false)
    l = tick(l); expect(l.secondsLeft).toBe(0); expect(dueRetry(l)).toBe(true)
    expect(tick(l).secondsLeft).toBe(0)                                        // never below zero
    expect(tick(sentLine(l)).state).toBe('sent')
    expect(dueRetry(sentLine(l))).toBe(false)
  })
  it('keeps the same client_ref through every try (the host takes a line once, whatever the retries)', () => {
    let l = held(base(), { retryAfterS: 1 })
    for (let i = 0; i < MAX_HELD_TRIES - 2; i++) l = held(l, { retryAfterS: 1 })
    expect(l.clientRef).toBe('ref-1')
    expect(l.state).toBe('waiting')
  })
  it('is given up on after the last try, saying so in the host\'s own words, and keeps the text', () => {
    let l = base()
    for (let i = 0; i < MAX_HELD_TRIES; i++) l = held(l, { retryAfterS: 1, detail: 'the thread is capped' })
    expect(l.state).toBe('failed')
    expect(l.error).toBe('the thread is capped')
    expect(l.body).toBe('hello')
  })
})

describe('the other end states', () => {
  it('a line the relay took is sent, and waits for the host\'s copy', () => {
    expect(sentLine(held(base(), { retryAfterS: 5 }))).toMatchObject({ state: 'sent', secondsLeft: 0 })
  })
  it('a refusal that is not a limit is a failed line with the host\'s sentence', () => {
    expect(failedLine(base(), { detail: 'you are no longer in this room' })).toMatchObject({ state: 'failed', error: 'you are no longer in this room' })
  })
  it('a line is settled when the host\'s copy arrives (its client_ref), and not before', () => {
    const lines = [sentLine(base()), newLine({ clientRef: 'ref-2', body: 'two', replyTo: null })]
    expect(settle(lines, [{ client_ref: 'other' }])).toHaveLength(2)
    expect(settle(lines, [{ client_ref: 'ref-1' }, { client_ref: 'x' }]).map((l) => l.clientRef)).toEqual(['ref-2'])
  })
})
