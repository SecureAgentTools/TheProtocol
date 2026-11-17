/**
 * V0664 (order gwo_1b3e2cc74c1afec6c6cedc3d): the visitor's sidebar shows the newest public announcements where it shows its one
 * sign-in line, and nothing at all when there are none (a strip that says "no announcements" to every visitor would be noise).
 * BASE: the component does not exist.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ get: vi.fn(), push: vi.fn() }))
vi.mock('@/services/api/client', () => ({ default: { get: h.get }, apiClient: { get: h.get } }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))

import PublicAnnouncementsStrip from './PublicAnnouncementsStrip.vue'

const row = (id: number, title: string, type = 'info') => ({
  id, title, body: 'b', broadcast_type: type, created_at: '2026-11-14T10:00:00Z', cta_url: null, cta_label: null,
})

describe('the visitor sidebar strip', () => {
  beforeEach(() => { h.get.mockReset(); h.push.mockReset() })

  it('shows the newest three titles and a door to the page', async () => {
    h.get.mockResolvedValue({ data: [row(4, 'Four'), row(3, 'Three'), row(2, 'Two'), row(1, 'One')] })
    const w = mount(PublicAnnouncementsStrip)
    await flushPromises()
    expect(h.get.mock.calls[0][0]).toBe('/public/announcements')
    expect(h.get.mock.calls[0][1]).toMatchObject({ params: { limit: 3 } })
    expect(w.findAll('[data-testid="pas-item"]').map((i) => i.text())).toEqual(['Four', 'Three', 'Two'])
    await w.get('[data-testid="pas-all"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith('/announcements')
  })

  it('draws nothing when there are none, and nothing when they cannot be read', async () => {
    h.get.mockResolvedValue({ data: [] })
    const a = mount(PublicAnnouncementsStrip)
    await flushPromises()
    expect(a.find('[data-testid="pas-root"]').exists()).toBe(false)
    h.get.mockRejectedValue(new Error('down'))
    const b = mount(PublicAnnouncementsStrip)
    await flushPromises()
    expect(b.find('[data-testid="pas-root"]').exists()).toBe(false)
  })
})
