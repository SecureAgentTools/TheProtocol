/**
 * §FESUITE (V0577): the contract Templates tab turned a failed list read into "No templates yet … Create the first
 * template" (under a toast); with nothing on screen it now says the read failed, and Try again reads the list.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ listTemplates: vi.fn() }))
vi.mock('@/services/api/contractsV2', () => ({ contractsV2Api: { listTemplates: h.listTemplates } }))

import TemplatesTab from './TemplatesTab.vue'

describe('the contract Templates tab over a list read that failed', () => {
  beforeEach(() => { setActivePinia(createPinia()) })

  it('says the read failed (no "No templates yet"), and Try again reads the list', async () => {
    h.listTemplates.mockRejectedValue(Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } }))
    const w = mount(TemplatesTab, { global: { stubs: { BaseModal: true } } })
    await flushPromises()
    expect(w.find('[data-testid="tpl-list-failed"]').exists(), 'the list says its read failed').toBe(true)
    expect(w.text()).not.toContain('No templates yet')

    h.listTemplates.mockResolvedValue({ items: [], next_cursor: null })
    await w.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="tpl-list-failed"]').exists()).toBe(false)
    expect(w.text(), 'an answered empty library says so').toContain('No templates yet')
  })
})
