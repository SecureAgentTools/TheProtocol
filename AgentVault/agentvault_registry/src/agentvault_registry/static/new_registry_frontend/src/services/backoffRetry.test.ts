import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createBackoffRetry } from './backoffRetry'

/** §FESUITE (2026-10-04) — the retry behind the saved agent's second try (stores/auth.ts) and any read like it. */
describe('a retry that backs off and stops', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('waits a step, runs once, and backs off step by step (the last step repeating)', async () => {
    const run = vi.fn()
    const r = createBackoffRetry(run, [100, 200, 400])
    expect(r.schedule()).toBe(true)
    await vi.advanceTimersByTimeAsync(99)
    expect(run).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(run).toHaveBeenCalledTimes(1)
    r.schedule(); await vi.advanceTimersByTimeAsync(199); expect(run).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1); expect(run).toHaveBeenCalledTimes(2)
    r.schedule(); await vi.advanceTimersByTimeAsync(400); expect(run).toHaveBeenCalledTimes(3)
    r.schedule(); await vi.advanceTimersByTimeAsync(399); expect(run).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(1); expect(run).toHaveBeenCalledTimes(4)
    expect(r.attempts).toBe(4)
  })

  it('one timer at a time: a failure reported twice does not double the pace', async () => {
    const run = vi.fn()
    const r = createBackoffRetry(run, [100])
    expect(r.schedule()).toBe(true)
    expect(r.schedule()).toBe(false)
    expect(r.pending).toBe(true)
    await vi.advanceTimersByTimeAsync(100)
    expect(run).toHaveBeenCalledTimes(1)
    expect(r.pending).toBe(false)
  })

  it('cancel stops the pending try and starts the next outage at the first step', async () => {
    const run = vi.fn()
    const r = createBackoffRetry(run, [100, 1000])
    r.schedule(); await vi.advanceTimersByTimeAsync(100)
    r.schedule(); r.cancel()
    await vi.advanceTimersByTimeAsync(5000)
    expect(run).toHaveBeenCalledTimes(1)
    expect(r.attempts).toBe(0)
    r.schedule(); await vi.advanceTimersByTimeAsync(100)
    expect(run).toHaveBeenCalledTimes(2)
  })

  it('a run that throws or rejects does not escape the timer', async () => {
    const r1 = createBackoffRetry(() => { throw new Error('boom') }, [10])
    const r2 = createBackoffRetry(() => Promise.reject(new Error('later')), [10])
    r1.schedule(); r2.schedule()
    await vi.advanceTimersByTimeAsync(10)
    expect(r1.pending).toBe(false)
    expect(r2.pending).toBe(false)
  })
})
