import { describe, it, expect } from 'vitest'
import { catchUpCause, firstUnreadIndex, liveState, mergeBySeq, pollRetry, POLL_BACKOFF_MS } from './catchUp'

/** V0652 (ag): the catch-up's rules. BASE (V0651): catchUp.ts does not exist; the thread caught up on a socket
 *  reconnect only, and opened at the end whatever was unread. */
const m = (seq: number, mine = false) => ({ id: `m${seq}`, seq, mine })

describe('the live mark', () => {
  it('says live, catching up or offline', () => {
    expect(liveState({ connected: true, catching: false })).toBe('live')
    expect(liveState({ connected: false, catching: false })).toBe('offline')
    expect(liveState({ connected: true, catching: true })).toBe('catching_up')
    expect(liveState({ connected: false, catching: true })).toBe('catching_up')
  })
})

describe('the merge by seq', () => {
  it('adds what is new, in seq order, never twice', () => {
    const r = mergeBySeq([m(1), m(2), m(3)], [m(3), m(5), m(4)])
    expect(r.messages.map((x) => x.seq)).toEqual([1, 2, 3, 4, 5])
    expect(r.added).toBe(2)
    expect(r.gap).toBe(false)
  })
  it('says when messages were missed in between (more than a page arrived while away)', () => {
    expect(mergeBySeq([m(1), m(2)], [m(50), m(51)]).gap).toBe(true)
    expect(mergeBySeq([m(1), m(2)], [m(3)]).gap).toBe(false)
    expect(mergeBySeq([], [m(50)]).gap).toBe(false)
    expect(mergeBySeq([m(1)], []).added).toBe(0)
  })
})

describe('where a thread opens', () => {
  const mine = (x: any) => !!x.mine
  it('at the first message someone else wrote after what you read', () => {
    expect(firstUnreadIndex([m(1), m(2), m(3), m(4)], 2, mine)).toBe(2)
  })
  it('skips your own sends (read by definition)', () => {
    expect(firstUnreadIndex([m(1), m(2, true), m(3)], 1, mine)).toBe(2)
  })
  it('at the end (-1) when nothing new waits', () => {
    expect(firstUnreadIndex([m(1), m(2)], 2, mine)).toBe(-1)
    expect(firstUnreadIndex([m(1), m(2, true)], 1, mine)).toBe(-1)
  })
})

describe('what triggers a catch-up', () => {
  it('the tab coming back, the focus, the socket coming back', () => {
    expect(catchUpCause({ type: 'visibilitychange', visibilityState: 'visible' })).toBe('visible')
    expect(catchUpCause({ type: 'visibilitychange', visibilityState: 'hidden' })).toBeNull()
    expect(catchUpCause({ type: 'focus' })).toBe('focus')
    expect(catchUpCause({ type: 'reconnected' })).toBe('reconnect')
    expect(catchUpCause({ type: 'blur' })).toBeNull()
  })
})

describe('what the long-poll does after a failed call (session-lead, seq 381)', () => {
  it('401 and 403 stop it', () => {
    expect(pollRetry({ status: 401 }, 0)).toEqual({ stop: true })
    expect(pollRetry({ status: 403 }, 7)).toEqual({ stop: true })
  })
  it('429 and 503 wait their Retry-After, bounded to 1 s .. 5 min', () => {
    expect(pollRetry({ status: 429, retryAfterS: 30 }, 0)).toEqual({ stop: false, delayMs: 30000 })
    expect(pollRetry({ status: 503, retryAfterS: 0.2 }, 0)).toEqual({ stop: false, delayMs: 1000 })
    expect(pollRetry({ status: 503, retryAfterS: 9999 }, 0)).toEqual({ stop: false, delayMs: 300000 })
  })
  it('anything else backs off 5, 10, 20, 40, then 60 s, within 20% either way', () => {
    const half = () => 0.5
    expect([0, 1, 2, 3, 4, 5, 9].map((a) => (pollRetry({ status: 502 }, a, half) as any).delayMs))
      .toEqual([5000, 10000, 20000, 40000, 60000, 60000, 60000])
    expect((pollRetry(new Error('network') as any, 0, () => 0) as any).delayMs).toBe(4000)
    expect((pollRetry(null, 4, () => 1) as any).delayMs).toBe(72000)
    expect((pollRetry({ status: 503 }, 1, half) as any).delayMs).toBe(POLL_BACKOFF_MS[1])   // 503 with no Retry-After
  })
})
