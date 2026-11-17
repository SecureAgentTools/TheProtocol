import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useRelayHold } from './useRelayHold'
import { MAX_HELD_TRIES } from '@/services/chat/relayHold'

/**
 * V0664 (order gwo_874694de65551c5c1488641c): the countdown and the retry behind a held line. A held line waits its seconds, sends again
 * under the SAME client_ref, and ends sent (waiting for the host's copy) or, after the last try, failed with Send again.
 */
const payload = { kind: 'text' as const, body: 'hello', client_ref: 'ref-1' }
const limit = (retryAfterS = 2, detail = 'capped') => Object.assign(new Error(detail), { status: 429, retryAfterS, detail })

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers() })

describe('a held line', () => {
  it('shows its seconds counting down, sends again under the same client_ref, and ends sent', async () => {
    const send = vi.fn().mockResolvedValue({ relayed: true, host_seq: 4 })
    const h = useRelayHold({ send })
    h.take(payload, limit(2))
    expect(h.lines.value[0]).toMatchObject({ state: 'waiting', secondsLeft: 2, body: 'hello', clientRef: 'ref-1' })
    await vi.advanceTimersByTimeAsync(1000)
    expect(h.lines.value[0].secondsLeft).toBe(1)
    expect(send).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1000)
    expect(send).toHaveBeenCalledTimes(1)
    expect(send.mock.calls[0][0]).toEqual(payload)                            // the very same payload, client_ref included
    expect(h.lines.value[0].state).toBe('sent')
    h.dispose()
  })

  it('waits again when the limit holds the retry too, and gives up after the last try with the host\'s words', async () => {
    const send = vi.fn().mockRejectedValue(limit(1, 'the thread is capped'))
    const h = useRelayHold({ send })
    h.take(payload, limit(1, 'the thread is capped'))
    await vi.advanceTimersByTimeAsync(1000 * 20)
    expect(send).toHaveBeenCalledTimes(MAX_HELD_TRIES - 1)                    // the first try was the one that took it
    expect(h.lines.value[0]).toMatchObject({ state: 'failed', error: 'the thread is capped', body: 'hello' })
    await vi.advanceTimersByTimeAsync(1000 * 20)
    expect(send).toHaveBeenCalledTimes(MAX_HELD_TRIES - 1)                    // a failed line does not keep asking
    h.dispose()
  })

  it('a refusal that is not a limit ends the line failed at once, with the host\'s sentence', async () => {
    const send = vi.fn().mockRejectedValue(Object.assign(new Error('x'), { status: 403, detail: 'you are no longer in this room' }))
    const h = useRelayHold({ send })
    h.take(payload, limit(1))
    await vi.advanceTimersByTimeAsync(1000)
    expect(h.lines.value[0]).toMatchObject({ state: 'failed', error: 'you are no longer in this room' })
    h.dispose()
  })

  it('a network failure on the retry holds the line again (nothing was refused: try again) rather than losing it', async () => {
    const send = vi.fn().mockRejectedValueOnce(new Error('network')).mockResolvedValue({ relayed: true })
    const h = useRelayHold({ send })
    h.take(payload, limit(1))
    await vi.advanceTimersByTimeAsync(1000)
    expect(h.lines.value[0].state).toBe('waiting')
    await vi.advanceTimersByTimeAsync(1000 * 20)
    expect(h.lines.value[0].state).toBe('sent')
    h.dispose()
  })

  it('Send again on a failed line starts a fresh round at once, and keeps its client_ref', async () => {
    const send = vi.fn().mockRejectedValue(Object.assign(new Error('x'), { status: 403, detail: 'no' }))
    const h = useRelayHold({ send })
    h.take(payload, limit(1))
    await vi.advanceTimersByTimeAsync(1000)
    expect(h.lines.value[0].state).toBe('failed')
    send.mockResolvedValue({ relayed: true })
    await h.again('ref-1')
    expect(send).toHaveBeenLastCalledWith(payload)
    expect(h.lines.value[0].state).toBe('sent')
    h.dispose()
  })
})

describe('a sent line', () => {
  it('is shown waiting for the host\'s copy, and goes when that copy (its client_ref) arrives', () => {
    const h = useRelayHold({ send: vi.fn() })
    h.track(payload)
    expect(h.lines.value[0]).toMatchObject({ state: 'sent', clientRef: 'ref-1' })
    h.settle([{ client_ref: 'ref-1' }])
    expect(h.lines.value).toHaveLength(0)
    h.dispose()
  })
  it('a line whose copy never arrives stays, rather than being dropped on a guess', async () => {
    const h = useRelayHold({ send: vi.fn() })
    h.track(payload)
    await vi.advanceTimersByTimeAsync(1000 * 600)
    expect(h.lines.value).toHaveLength(1)
    h.dispose()
  })
  it('a line is taken once: tracking the same client_ref twice shows one line', () => {
    const h = useRelayHold({ send: vi.fn() })
    h.track(payload); h.track(payload)
    h.take(payload, limit(3))
    expect(h.lines.value).toHaveLength(1)
    h.dispose()
  })
})
