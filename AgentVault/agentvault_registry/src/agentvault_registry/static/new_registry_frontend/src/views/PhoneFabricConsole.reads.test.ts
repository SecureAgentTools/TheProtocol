import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09; found by agentvault2-b2): the Phone Fabric console's admin reads answer 200
 * with `enabled: false` where the fabric is off, so a failure is a failure, and it was kept quiet: the pill said
 * DISABLED, the list "No phone sessions yet" (with no active session drawn, the GLOBAL HALT row stayed hidden too), and a
 * failed trace read said "No actions recorded." about what the drawer calls the non-repudiable ledger. Each says its read
 * failed now, with Try again; answered reads keep their words.
 */
const h = vi.hoisted(() => ({ sessions: vi.fn(), pool: vi.fn(), actions: vi.fn() }))
vi.mock('@/services/api/phoneFabric', () => ({
  phoneFabricApi: { sessions: h.sessions, pool: h.pool, actions: h.actions, kill: vi.fn(), globalHalt: vi.fn() },
}))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn() }) }))

import PhoneFabricConsole from './PhoneFabricConsole.vue'

const opts = { global: { stubs: { Icon: true, ConfirmActionModal: true } } }
const failure = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })
const SESSION = { id: 's1', agent_did: 'did:theprotocol:a', backend: 'mock', status: 'ended', actions_used: 2, budget_spent: '0',
  current_app: null, started_at: '2026-10-05T12:00:00Z' }

describe('the Phone Fabric console says what its reads answered', () => {
  beforeEach(() => { h.sessions.mockReset(); h.pool.mockReset(); h.actions.mockReset() })

  it('a failed list read: no DISABLED, no "No phone sessions yet"; a failed trace: no "No actions recorded."', async () => {
    h.sessions.mockRejectedValueOnce(failure()); h.pool.mockRejectedValueOnce(failure())
    const w = mount(PhoneFabricConsole, opts)
    await flushPromises()
    expect(w.text()).not.toContain('DISABLED')
    expect(w.text()).not.toContain('No phone sessions yet')
    expect(w.find('[data-testid="pfc-sessions-unread"]').exists()).toBe(true)
    h.sessions.mockResolvedValueOnce({ sessions: [SESSION], total: 1, enabled: true, backend: 'mock', mode: 'enforce' })
    h.pool.mockResolvedValueOnce({ instances: [], active_sessions: 0, max_concurrent: 8 })
    await w.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('ENABLED')
    h.actions.mockRejectedValueOnce(failure())
    await w.find('li.pfc-row').trigger('click')
    await flushPromises()
    expect(w.text()).not.toContain('No actions recorded.')
    expect(w.find('[data-testid="pfc-trace-unread"]').exists()).toBe(true)
    w.unmount()
  })

  it('answered: a fabric that is off says DISABLED, an empty list says none, an empty trace says none', async () => {
    h.sessions.mockResolvedValue({ sessions: [SESSION], total: 1, enabled: false, backend: '', mode: '' })
    h.pool.mockResolvedValue({ instances: [], active_sessions: 0, max_concurrent: 8 })
    h.actions.mockResolvedValueOnce({ session: SESSION, actions: [], total: 0 })
    const w = mount(PhoneFabricConsole, opts)
    await flushPromises()
    expect(w.text()).toContain('DISABLED')
    await w.find('li.pfc-row').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('No actions recorded.')
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    w.unmount()
  })
})
