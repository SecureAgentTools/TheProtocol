import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE (2026-10-05): the three tables' empty rows said none over a failed read ("no results", and in green "no
 * failing agents" and "no flags"); the tiles and tab counts already waited for their reads. Each table says its read
 * failed; answered empty tables still say none.
 */
const svc = vi.hoisted(() => ({ getFleetSummary: vi.fn(), listDeployments: vi.fn(), listFlagsGlobal: vi.fn(), acknowledgeFlag: vi.fn() }))
vi.mock('@/services/api/cicdAdmin', () => ({ cicdAdminService: svc }))
vi.mock('@/services/accessToken', () => ({ readAccessToken: () => null }))

import AdminCICD from './AdminCICD.vue'

const opts = { global: { stubs: { Icon: true, RouterLink: true } } }
const failure = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })

async function eachTab(w: ReturnType<typeof mount>, fn: (tab: number) => void) {
  const tabs = w.findAll('.ac-tabs button, button.ac-tab')
  for (let i = 0; i < 3; i++) {
    await tabs[i].trigger('click')
    await flushPromises()
    fn(i)
  }
}

describe('the CI/CD tables say what they read', () => {
  beforeEach(() => { for (const f of Object.values(svc)) f.mockReset() })

  it('failed reads: every table says its read failed, none says none', async () => {
    svc.getFleetSummary.mockRejectedValue(failure())
    svc.listDeployments.mockRejectedValue(failure())
    svc.listFlagsGlobal.mockRejectedValue(failure())
    const w = mount(AdminCICD, opts)
    await flushPromises()
    const ids = ['ac-deployments-failed', 'ac-failing-failed', 'ac-flags-failed']
    await eachTab(w, (i) => {
      expect(w.find(`[data-testid="${ids[i]}"]`).exists(), ids[i]).toBe(true)
      expect(w.findAll('td.ac-empty').filter((td) => td.text() !== '…').length, `no empty row on tab ${i}`).toBe(0)
    })
    w.unmount()
  })

  it('answered empty reads still say none', async () => {
    svc.getFleetSummary.mockResolvedValue({ pipelines: { total: 0, last_created_at: null },
      deployments: { total: 0, success: 0, failed: 0, pending: 0, top_failing_agents: [] } })
    svc.listDeployments.mockResolvedValue({ items: [] })
    svc.listFlagsGlobal.mockResolvedValue({ flags: [], by_type: {} })
    const w = mount(AdminCICD, opts)
    await flushPromises()
    await eachTab(w, (i) => {
      expect(w.findAll('td.ac-empty').length, `the empty row on tab ${i}`).toBe(1)
      expect(w.find('[data-read-failed]').exists()).toBe(false)
    })
    w.unmount()
  })
})
