/**
 * §FESUITE (V0578): the OPA console's decisions read swallowed its own failure ("surfaced by refresh", which it never
 * was), so with /admin/opa/status and /admin/opa/policies answering and /admin/opa/decisions not, the DECISIONS tab said
 * "No decisions retained yet on this worker" and nothing on the page said a read had failed. A failed re-read after
 * ticking "only disagreements" kept the previous unfiltered rows under the filter. Now the tab says the read failed (with
 * Try again), clears the rows, and says "none" only when the read answered (in the filter's own words when it is on).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ decisions: vi.fn() }))
vi.mock('@/services/api/opaAdmin', () => {
  const api = {
    status: async () => ({
      opa_enabled: true, opa_enforce: false, mode: 'shadow', sidecar: { reachable: true },
      divergence: { retained: 2, capacity: 500, mismatches: 1, opa_errors: 0, agreement_pct: 50, latency_ms_avg: 3, latency_ms_max: 9 },
    }),
    policies: async () => ({ enabled: true, count: 0, policies: [] }),
    decisions: (...a: unknown[]) => h.decisions(...a),
    simulate: async () => ({}),
  }
  return { default: api, opaAdminApi: api }
})

import OpaConsole from './OpaConsole.vue'

const NONE = 'No decisions retained yet'
const ROWS = [
  { ts: '2026-10-05T14:00:01Z', policy: 'agentvault/agent/allow', label: null, input: { a: 1 }, python: true, opa: true, match: true, latency_ms: 2 },
  { ts: '2026-10-05T14:00:02Z', policy: 'agentvault/agent/allow', label: null, input: { a: 2 }, python: true, opa: false, match: false, latency_ms: 3 },
]
const badGateway = () => new AxiosError('Request failed with status code 502', 'ERR_BAD_RESPONSE', undefined, undefined,
  { status: 502, statusText: '', data: {}, headers: {}, config: {} } as any)

async function consoleOpen() {
  const w = mount(OpaConsole, { global: { stubs: { Icon: true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  await w.find('[data-testid="opa-tab-decisions"]').trigger('click')
  return w
}
const panel = (w: ReturnType<typeof mount>) => w.find('[data-testid="opa-panel-decisions"]')
const rows = (w: ReturnType<typeof mount>) => panel(w).findAll('tbody tr').length

describe('the OPA console decisions tab', () => {
  beforeEach(() => { h.decisions.mockReset() })

  it('a failed decisions read says it failed, never "No decisions retained yet"', async () => {
    h.decisions.mockRejectedValue(badGateway())
    const w = await consoleOpen()
    expect(panel(w).text(), 'said none over a decisions read that failed').not.toContain(NONE)
    expect(panel(w).find('[data-testid="opa-decisions-failed"]').exists()).toBe(true)
    h.decisions.mockResolvedValue({ count: 2, decisions: ROWS, stats: {} })
    await panel(w).find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(rows(w)).toBe(2)
    expect(panel(w).find('[data-testid="opa-decisions-failed"]').exists()).toBe(false)
  })

  it('a failed re-read under "only disagreements" clears the earlier unfiltered rows', async () => {
    h.decisions.mockResolvedValueOnce({ count: 2, decisions: ROWS, stats: {} })
    const w = await consoleOpen()
    expect(rows(w)).toBe(2)
    h.decisions.mockRejectedValueOnce(badGateway())
    await panel(w).find('input[type="checkbox"]').setValue(true)
    await flushPromises()
    expect(rows(w), 'kept the unfiltered rows under "only disagreements" after its read failed').toBe(0)
    expect(panel(w).find('[data-testid="opa-decisions-failed"]').exists()).toBe(true)
    expect(h.decisions).toHaveBeenLastCalledWith(200, true)
  })

  it('"none" only once the read answered, in the filter\'s words when the filter is on', async () => {
    h.decisions.mockResolvedValue({ count: 0, decisions: [], stats: {} })
    const w = await consoleOpen()
    expect(panel(w).text()).toContain(NONE)
    await panel(w).find('input[type="checkbox"]').setValue(true)
    await flushPromises()
    expect(panel(w).text()).not.toContain(NONE)
    expect(panel(w).text()).toContain('No disagreements among the decisions retained on this worker.')
  })

  it('while the decisions read is in flight: no "none" and no failure notice', async () => {
    h.decisions.mockReturnValue(new Promise(() => {}))
    const w = await consoleOpen()
    expect(panel(w).text()).not.toContain(NONE)
    expect(panel(w).find('[data-testid="opa-decisions-failed"]').exists()).toBe(false)
  })
})
