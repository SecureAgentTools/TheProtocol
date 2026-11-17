/**
 * V0663 (his yes seq 3068, "empty lists that say why"), the Firms page: with no organization opted into public transparency the
 * list says why it is empty, through the shared reason line (kind "none yet"), and keeps its test id and its sentence.
 * BASE: the sentence sits in a bare div.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'

const h = vi.hoisted(() => ({ get: vi.fn(), route: { query: {} as Record<string, any> } }))
vi.mock('@/services/api/client', () => ({ default: { get: h.get }, apiClient: { get: h.get } }))
vi.mock('vue-router', () => ({ useRoute: () => h.route }))

import PublicFirms from './PublicFirms.vue'

describe('the Firms page with no firm', () => {
  beforeEach(() => { h.get.mockReset(); h.route = reactive({ query: {} }) })

  it('says why the list is empty, through the reason line', async () => {
    h.get.mockImplementation(async (url: string) => {
      if (url === '/organizations/public/transparent') return { data: { organizations: [] } }
      throw new Error(`unexpected read ${url}`)
    })
    const w = mount(PublicFirms, { global: { stubs: { OrgDirectory: true, ViewAmbient: true } } })
    await flushPromises()
    const empty = w.get('[data-testid="pf-empty"]')
    const why = empty.get('[data-testid="empty-reason"]')
    expect(why.attributes('data-kind')).toBe('none-yet')
    expect(why.text()).toContain('No organization has opted into public transparency yet')
    expect(why.text()).toContain('The switch lives in every org')
  })
})
