/**
 * §FESUITE (V0577): the org's Books showed a failed statement read as its error AND "No money records yet." under it;
 * the failed read now stands in the list's place, and Try again reads it.
 */
import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get } }))

import OrgBooks from './OrgBooks.vue'

describe('the org Books over a statement read that failed', () => {
  it('says the read failed (no "No money records yet."), and Try again reads the statement', async () => {
    h.get.mockRejectedValue(new Error('Request failed with status code 502'))
    const w = mount(OrgBooks, { props: { orgId: 'org-1' } })
    await flushPromises()
    expect(w.find('[data-read-failed]').exists(), 'the books say the read failed').toBe(true)
    expect(w.find('[data-testid="ob-empty"]').exists(), 'no "No money records yet." over a failed read').toBe(false)

    h.get.mockResolvedValue({ data: { rows: [], note: null } })
    await w.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    expect(w.find('[data-testid="ob-empty"]').exists(), 'an answered empty statement says so').toBe(true)
  })
})
