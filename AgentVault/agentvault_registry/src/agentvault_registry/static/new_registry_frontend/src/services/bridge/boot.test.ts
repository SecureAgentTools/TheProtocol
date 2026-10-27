import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  BootSequencer, bootSummary, isSettled, type BootStep,
  bootAlreadyShown, markBootShown, resetBootShownForTests,
} from './boot'

const step = (id: string, over: Partial<BootStep> = {}): BootStep => ({
  id, label: id, run: async () => {}, ...over,
})

describe('BootSequencer', () => {
  it('runs dependencies before dependents, with no timers', async () => {
    const order: string[] = []
    const b = new BootSequencer([
      step('fleet', { needs: ['reach'], run: async () => { order.push('fleet') } }),
      step('reach', { run: async () => { order.push('reach') } }),
    ])
    await b.run()
    expect(order).toEqual(['reach', 'fleet'])
  })

  it('rejects a dependency that does not exist, at construction', () => {
    expect(() => new BootSequencer([step('a', { needs: ['ghost'] })])).toThrow(/unknown step/)
  })

  it('RE-RUNS ONCE when the input set moved underneath it', async () => {
    // The whole point: the fan-out used to run against a PARTIAL registry set
    // and keep whatever landed first (2 registries, then 5, by luck).
    let connected = 'a,b'
    let sawOnRun: string[] = []
    const b = new BootSequencer([
      step('fleet', {
        inputSig: () => connected,
        run: async () => { sawOnRun.push(connected); if (sawOnRun.length === 1) connected = 'a,b,c,d' },
      }),
    ])
    await b.run()
    expect(sawOnRun).toEqual(['a,b', 'a,b,c,d'])
    expect(b.records()[0].runs).toBe(2)
  })

  it('stops re-running once the input settles, and cannot loop forever', async () => {
    let n = 0
    const b = new BootSequencer([
      step('x', { inputSig: () => String(n), run: async () => { n++ } }),
    ], { maxRuns: 3 })
    await b.run()
    expect(b.records()[0].runs).toBe(3)   // capped, not infinite
    expect(b.records()[0].state).toBe('ok')
  })

  it('isolates failure: one step failing does not stop the others', async () => {
    const b = new BootSequencer([
      step('bad', { run: async () => { throw new Error('boom') } }),
      step('good', { run: async () => 'fine' }),
    ])
    await b.run()
    const r = Object.fromEntries(b.records().map(x => [x.id, x]))
    expect(r.bad.state).toBe('failed')
    expect(r.bad.error).toContain('boom')
    expect(r.good.state).toBe('ok')
    expect(r.good.detail).toBe('fine')
  })

  it('SKIPS a dependent of a failed step, and says why', async () => {
    const b = new BootSequencer([
      step('reach', { label: 'Sessions', run: async () => { throw new Error('no') } }),
      step('fleet', { needs: ['reach'] }),
    ])
    await b.run()
    const fleet = b.records().find(r => r.id === 'fleet')!
    expect(fleet.state).toBe('skipped')
    expect(fleet.error).toMatch(/needs "Sessions", which failed/)
  })

  it('ready() waits only for REQUIRED steps; streaming ones come later', async () => {
    let release!: () => void
    const slow = new Promise<void>(r => { release = r })
    const b = new BootSequencer([
      step('local', { required: true, run: async () => {} }),
      step('foreign', { required: false, run: async () => { await slow } }),
    ])
    const p = b.run()
    await vi.waitFor(() => expect(b.ready()).toBe(true))
    expect(b.done()).toBe(false)      // still streaming
    release(); await p
    expect(b.done()).toBe(true)
  })

  it('a failed REQUIRED step still lets the view come up (degraded, not hung)', async () => {
    const b = new BootSequencer([step('local', { run: async () => { throw new Error('x') } })])
    await b.run()
    expect(b.ready()).toBe(true)
    expect(b.records()[0].state).toBe('failed')
  })

  it('runs each step once even when several dependents need it', async () => {
    const runs = { n: 0 }
    const b = new BootSequencer([
      step('base', { run: async () => { runs.n++ } }),
      step('a', { needs: ['base'] }),
      step('b', { needs: ['base'] }),
      step('c', { needs: ['base'] }),
    ])
    await b.run()
    expect(runs.n).toBe(1)
  })

  it('retry() re-runs a failed step and can turn it green', async () => {
    let fail = true
    const b = new BootSequencer([step('x', { run: async () => { if (fail) throw new Error('nope'); return 'now ok' } })])
    await b.run()
    expect(b.records()[0].state).toBe('failed')
    fail = false
    await b.retry('x')
    expect(b.records()[0].state).toBe('ok')
    expect(b.records()[0].detail).toBe('now ok')
  })

  it('publishes progress and an honest summary', async () => {
    const seen: number[] = []
    const b = new BootSequencer([
      step('a'), step('b', { run: async () => { throw new Error('e') } }), step('c', { needs: ['b'] }),
    ], { onChange: (r) => seen.push(r.filter(x => isSettled(x.state)).length) })
    await b.run()
    expect(b.progress()).toEqual({ settled: 3, total: 3 })
    expect(bootSummary(b.records())).toBe('1/3 ready · 1 failed · 1 skipped')
    expect(seen.length).toBeGreaterThan(0)
  })
})

describe('boot shown flag', () => {
  beforeEach(() => resetBootShownForTests())

  it('starts false — a fresh document boots', () => {
    expect(bootAlreadyShown()).toBe(false)
  })

  it('stays true once marked — a route change does not re-run it', () => {
    markBootShown()
    expect(bootAlreadyShown()).toBe(true)
    expect(bootAlreadyShown()).toBe(true)
  })

  it('is NOT sessionStorage: nothing is persisted for the next document', () => {
    markBootShown()
    // The whole point of the module flag is that it cannot outlive the page.
    // If someone reintroduces a storage write, this catches it.
    const keys: string[] = []
    try { for (let i = 0; i < sessionStorage.length; i++) keys.push(String(sessionStorage.key(i))) } catch { /* node */ }
    expect(keys.some(k => k.includes('bridge.booted'))).toBe(false)
  })
})
