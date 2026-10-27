import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): the Command Center drawer's Actions tab said "No remediation actions
 * registered." when the action catalog's read had failed. The store named the failure on its shared error line, but the
 * next targets read clears that line, so the tab's "none" then stood alone. The tab says its read failed now, with Try
 * again; an answered empty catalog still says none.
 */
const h = vi.hoisted(() => ({ listActions: vi.fn(), listTargets: vi.fn() }))
vi.mock('@/services/api/diagnosticsApi', () => ({
  diagnosticsApi: { listActions: h.listActions, listTargets: h.listTargets, listChecks: vi.fn(), getConfig: vi.fn() },
}))

import CCDetailDrawer from './CCDetailDrawer.vue'
import { useCommandCenterStore } from '@/stores/commandCenter'

const TARGET = { operator_id: 'op-a', display_name: 'Op A', frame: 'eu', role: 'operator' as const, cloud_url: null,
  status: 'ok' as any, last_snapshot_at: null, check_results: [] }
const stubs = { Icon: true, CCActionButton: true, CCCheckRow: true, CCConfigSection: true, Teleport: true, teleport: true, Transition: false }

async function openActions(w: ReturnType<typeof mount>) {
  await w.findAll('nav button').find((b) => b.text() === 'Actions')!.trigger('click')
  await flushPromises()
}

describe('the drawer\'s Actions tab says what it read', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.listActions.mockReset()
    h.listTargets.mockReset().mockResolvedValue({ targets: [TARGET] })
  })

  it('a failed catalog read: the tab says so (also after the next targets read clears the shared error)', async () => {
    h.listActions.mockRejectedValueOnce(Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } }))
    const w = mount(CCDetailDrawer, { props: { target: null, inflight: false }, global: { stubs } })
    await w.setProps({ target: TARGET })
    await flushPromises()
    await useCommandCenterStore().loadTargets()   // the poll's next read: it clears the shared error line
    await flushPromises()
    await openActions(w)
    expect(w.text()).not.toContain('No remediation actions registered.')
    expect(w.find('[data-read-failed]').exists()).toBe(true)
    h.listActions.mockResolvedValueOnce({ actions: [{ action_id: 'restart_registry', description: 'Restart', destructive: false,
      requires_confirmation: true, post_check: null }] })
    await w.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    expect(w.text()).toContain('restart_registry')
    w.unmount()
  })

  it('an answered empty catalog still says none', async () => {
    h.listActions.mockResolvedValueOnce({ actions: [] })
    const w = mount(CCDetailDrawer, { props: { target: null, inflight: false }, global: { stubs } })
    await w.setProps({ target: TARGET })
    await flushPromises()
    await openActions(w)
    expect(w.text()).toContain('No remediation actions registered.')
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    w.unmount()
  })
})
