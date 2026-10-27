import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): Operator Management swallowed three reads.
 *  - cloud operators: "No cloud operators provisioned yet. Provision one from an activated application below." under
 *    "0/10 slots used" (its default limit);
 *  - operator licences: "No licenses found — generate one to start federating" under Active 0 · Suspended 0 · Revoked 0
 *    · Total 0;
 *  - the lifecycle overview: "✓ No lifecycle drift across 0 operators." and "✓ No stale-license operators detected";
 *  - and the application counts read 0 over a failed applications read (its table already said it failed).
 * Each says its read failed now (Try again) and counts nothing it did not read. Answered empties keep their words.
 */
const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: vi.fn(), put: vi.fn(), delete: vi.fn() } }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showInfo: vi.fn(), showSuccess: vi.fn(), showWarning: vi.fn() }) }))

import OperatorManagement from './OperatorManagement.vue'

const opts = { global: { stubs: { Icon: true, ConfirmActionModal: true, Teleport: true, teleport: true, RouterLink: true } } }
const failure = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })

function routes(fail: boolean) {
  h.get.mockImplementation(async (url: string) => {
    if (url === '/admin/cloud-operators') {
      if (fail) throw failure()
      return { data: { operators: [], active_count: 0, beta_limit: 10 } }
    }
    if (url === '/admin/federation/licenses') {
      if (fail) throw failure()
      return { data: [] }
    }
    if (url === '/admin/operator-applications') {
      if (fail) throw failure()
      return { data: [] }
    }
    if (url === '/admin/operators/lifecycle-overview') {
      if (fail) throw failure()
      return { data: { operators: [] } }
    }
    if (url === '/stack-health') return { data: { services: [] } }
    return { data: {} }
  })
}
const stats = (w: ReturnType<typeof mount>) => w.findAll('.opm-license-stat-val').map((e) => e.text())
const appStats = (w: ReturnType<typeof mount>) => w.findAll('.opm-stat-val').map((e) => e.text())

describe('Operator Management says what its cloud and licence reads answered', () => {
  beforeEach(() => { h.get.mockReset() })

  it('failed reads: no "No cloud operators", no "0/10 slots", no "No licenses found", no 0 counts, no all-clears', async () => {
    routes(true)
    const w = mount(OperatorManagement, opts)
    await flushPromises()
    expect(w.text()).not.toContain('No cloud operators provisioned yet')
    expect(w.text()).not.toContain('0/10 slots used')
    expect(w.text()).not.toContain('No licenses found')
    expect(w.text()).not.toContain('No lifecycle drift')
    expect(w.text()).not.toContain('No stale-license operators detected')
    expect(w.find('[data-testid="opm-drift-unread"]').exists()).toBe(true)
    expect(w.find('[data-testid="opm-stale-unread"]').exists()).toBe(true)
    expect(stats(w)).toEqual(['—', '—', '—', '—'])
    expect(appStats(w), 'the application counts (the table already said its read failed)').toEqual(['—', '—', '—', '—', '—'])
    expect(w.find('[data-testid="opm-cloud-unread"]').exists()).toBe(true)
    expect(w.find('[data-testid="opm-lic-unread"]').exists()).toBe(true)
    w.unmount()
  })

  it('answered empties keep their words and counts', async () => {
    routes(false)
    const w = mount(OperatorManagement, opts)
    await flushPromises()
    expect(w.text()).toContain('No cloud operators provisioned yet')
    expect(w.text()).toContain('0/10 slots used')
    expect(w.text()).toContain('No licenses found')
    expect(w.text()).toContain('No lifecycle drift')
    expect(w.text()).toContain('No stale-license operators detected')
    expect(stats(w)).toEqual(['0', '0', '0', '0'])
    expect(appStats(w)).toEqual(['0', '0', '0', '0', '0'])
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    w.unmount()
  })
})
