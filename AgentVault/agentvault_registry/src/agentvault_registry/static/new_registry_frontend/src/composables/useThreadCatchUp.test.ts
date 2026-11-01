import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref } from 'vue'
import { POLL_FLOOR_MS, POLL_GRACE_MS, useThreadCatchUp } from './useThreadCatchUp'

/** V0652 (ag): the page's causes each catch the thread up, one run at a time; while the socket is down it long-polls
 *  (with a floor between calls), and stops when the socket is back. BASE (V0651): the composable does not exist. */
function host(connected: ReturnType<typeof ref<boolean>>, catchUp: () => Promise<void>, longPollOnce: () => Promise<void>) {
  let api: any
  const C = defineComponent({ setup() { api = useThreadCatchUp({ connected: connected as any, catchUp, longPollOnce }); return () => h('div') } })
  const w = mount(C, { attachTo: document.body })
  return { w, api: () => api }
}
const setVisibility = (v: 'visible' | 'hidden') => Object.defineProperty(document, 'visibilityState', { value: v, configurable: true })

describe('the thread catches up', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers(); document.body.innerHTML = '' })

  it('when the tab comes back and when the window gets focus', async () => {
    const catchUp = vi.fn().mockResolvedValue(undefined)
    const { w } = host(ref(true), catchUp, vi.fn())
    setVisibility('hidden'); document.dispatchEvent(new Event('visibilitychange')); await Promise.resolve()
    expect(catchUp).not.toHaveBeenCalled()
    setVisibility('visible'); document.dispatchEvent(new Event('visibilitychange')); await vi.runAllTimersAsync()
    window.dispatchEvent(new Event('focus')); await vi.runAllTimersAsync()
    expect(catchUp).toHaveBeenCalledTimes(2)
    w.unmount()
  })

  it('one run at a time, and the mark says so meanwhile', async () => {
    let release!: () => void
    const catchUp = vi.fn().mockImplementation(() => new Promise<void>((r) => { release = r }))
    const { w, api } = host(ref(true), catchUp, vi.fn())
    window.dispatchEvent(new Event('focus'))
    window.dispatchEvent(new Event('focus'))
    await nextTick()
    expect(catchUp).toHaveBeenCalledTimes(1)
    expect(api().state.value).toBe('catching_up')
    release(); await vi.runAllTimersAsync()
    expect(api().state.value).toBe('live')
    w.unmount()
  })

  it('long-polls while the socket is down, with a floor between calls, and stops when it is back', async () => {
    const connected = ref(false)
    const longPollOnce = vi.fn().mockResolvedValue(undefined)   // answers at once, like a registry that ignores wait
    const catchUp = vi.fn().mockResolvedValue(undefined)
    const { w, api } = host(connected, catchUp, longPollOnce)
    expect(api().state.value).toBe('offline')
    await vi.advanceTimersByTimeAsync(POLL_GRACE_MS - 1)
    expect(longPollOnce).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(longPollOnce).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(POLL_FLOOR_MS * 2)
    expect(longPollOnce.mock.calls.length).toBeLessThanOrEqual(3)
    connected.value = true
    await vi.advanceTimersByTimeAsync(POLL_FLOOR_MS * 3)
    const n = longPollOnce.mock.calls.length
    await vi.advanceTimersByTimeAsync(POLL_FLOOR_MS * 5)
    expect(longPollOnce.mock.calls.length).toBe(n)
    expect(catchUp).toHaveBeenCalledTimes(1)   // the socket came back: one catch-up
    expect(api().state.value).toBe('live')
    w.unmount()
  })

  it('a socket that connects within the grace never polls', async () => {
    const connected = ref(false)
    const longPollOnce = vi.fn().mockResolvedValue(undefined)
    const { w } = host(connected, vi.fn().mockResolvedValue(undefined), longPollOnce)
    await vi.advanceTimersByTimeAsync(POLL_GRACE_MS / 2)
    connected.value = true
    await vi.advanceTimersByTimeAsync(POLL_GRACE_MS * 3)
    expect(longPollOnce).not.toHaveBeenCalled()
    w.unmount()
  })
})

/** session-lead's review (the sessions' room, seq 381): the long-poll retried every failure after 5 s, forever, 401 and
 *  403 included, so a tab left open on a dead token sent a refused call every 5 s all day (CrowdSec's brute-force
 *  pattern). BASE (b6999bc0d): a 401 is retried every 5 s, and a 503 too, at the same pace. */
describe('a failed long-poll', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.spyOn(Math, 'random').mockReturnValue(0.5) })
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); document.body.innerHTML = '' })
  const fail = (status: number, retryAfterS?: number) => Object.assign(new Error(`HTTP ${status}`), { status, retryAfterS })

  it.each([401, 403])('a %i is asked once, then the poll ends: signing in again is the app\'s', async (status) => {
    const longPollOnce = vi.fn().mockRejectedValue(fail(status))
    const { w } = host(ref(false), vi.fn().mockResolvedValue(undefined), longPollOnce)
    await vi.advanceTimersByTimeAsync(POLL_GRACE_MS)
    expect(longPollOnce).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(10 * 60 * 1000)
    expect(longPollOnce).toHaveBeenCalledTimes(1)
    w.unmount()
  })

  it('a 503 is asked again after 5, 10, 20 and 40 s, then every 60 s', async () => {
    const longPollOnce = vi.fn().mockRejectedValue(fail(503))
    const { w } = host(ref(false), vi.fn().mockResolvedValue(undefined), longPollOnce)
    await vi.advanceTimersByTimeAsync(POLL_GRACE_MS)
    const calls: number[] = [longPollOnce.mock.calls.length]
    for (const gap of [5000, 10000, 20000, 40000, 60000, 60000]) {
      await vi.advanceTimersByTimeAsync(gap - 1)
      expect(longPollOnce.mock.calls.length).toBe(calls[calls.length - 1])     // not before its time
      await vi.advanceTimersByTimeAsync(1)
      calls.push(longPollOnce.mock.calls.length)
    }
    expect(calls).toEqual([1, 2, 3, 4, 5, 6, 7])
    w.unmount()
  })

  it('a 429 waits as long as its Retry-After says', async () => {
    const longPollOnce = vi.fn().mockRejectedValueOnce(fail(429, 30)).mockResolvedValue(undefined)
    const { w } = host(ref(false), vi.fn().mockResolvedValue(undefined), longPollOnce)
    await vi.advanceTimersByTimeAsync(POLL_GRACE_MS)
    expect(longPollOnce).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(29999)
    expect(longPollOnce).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(longPollOnce).toHaveBeenCalledTimes(2)
    w.unmount()
  })
})
