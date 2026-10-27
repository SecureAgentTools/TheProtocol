import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE (2026-10-05): a failed relay read drew "No relay callers configured." and "No relay traffic recorded." under
 * the error card. The relay tables read a dash until the relay answered; an answered empty relay still says none.
 */
const svc = vi.hoisted(() => ({ fleet: vi.fn(), sender: vi.fn(), relayActivity: vi.fn(), relayLicenses: vi.fn() }))
vi.mock('@/services/api/mailFleet', () => ({ mailFleetService: svc }))

import AdminMailFleet from './AdminMailFleet.vue'

describe('the relay tables say what they read', () => {
  beforeEach(() => {
    for (const f of Object.values(svc)) f.mockReset()
    svc.fleet.mockResolvedValue({ nodes: [] })
    svc.sender.mockResolvedValue({ relay_enabled: true })
  })

  it('a failed relay read is no "No relay callers configured"', async () => {
    svc.relayActivity.mockRejectedValue(Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } }))
    svc.relayLicenses.mockRejectedValue(Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } }))
    const w = mount(AdminMailFleet)
    await flushPromises()
    expect(w.text()).toContain('Could not load.')
    expect(w.text()).not.toContain('No relay callers configured.')
    expect(w.text()).not.toContain('No relay traffic recorded.')
    expect(w.find('[data-testid="mf-callers-unread"]').exists()).toBe(true)
    w.unmount()
  })

  it('an answered empty relay says none', async () => {
    svc.relayActivity.mockResolvedValue({ events: [], last_24h: [] })
    svc.relayLicenses.mockResolvedValue({ licenses: [] })
    const w = mount(AdminMailFleet)
    await flushPromises()
    expect(w.text()).toContain('No relay callers configured.')
    expect(w.text()).toContain('No relay traffic recorded.')
    w.unmount()
  })
})
