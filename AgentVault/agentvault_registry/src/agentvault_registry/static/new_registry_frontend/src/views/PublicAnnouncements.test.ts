/**
 * V0664 (order gwo_1b3e2cc74c1afec6c6cedc3d): the public Announcements page, mounted for real. A visitor reads what an admin marked
 * public: a body is TEXT (markup typed into it shows as typed, never as a tag), a call to action only through a safe address, and
 * a registry with none, or one that cannot be read, says which of the two it is. BASE: the page does not exist.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => ({ default: { get: h.get }, apiClient: { get: h.get } }))

import PublicAnnouncements from './PublicAnnouncements.vue'

const row = (over: Record<string, unknown> = {}) => ({
  id: 1, title: 'Release V0663', body: 'Mentions, the bell and workflows.', broadcast_type: 'info', created_at: '2026-11-14T10:00:00Z',
  cta_url: null, cta_label: null, ...over,
})

describe('the public Announcements page', () => {
  beforeEach(() => h.get.mockReset())

  it('reads the public route, with no sign-in, and lists each announcement with its type', async () => {
    h.get.mockResolvedValue({ data: [row(), row({ id: 2, title: 'Saturday maintenance', broadcast_type: 'maintenance' })] })
    const w = mount(PublicAnnouncements)
    await flushPromises()
    expect(h.get.mock.calls[0][0]).toBe('/public/announcements')
    const items = w.findAll('[data-testid="pa-item"]')
    expect(items.map((i) => i.get('[data-testid="pa-title"]').text())).toEqual(['Release V0663', 'Saturday maintenance'])
    expect(items[1].attributes('data-type')).toBe('maintenance')
  })

  it('shows a body as text: markup in it is never a tag', async () => {
    h.get.mockResolvedValue({ data: [row({ body: 'Read <b>this</b> <img src=x onerror=alert(1)>' })] })
    const w = mount(PublicAnnouncements)
    await flushPromises()
    const body = w.get('[data-testid="pa-body"]')
    expect(body.find('b').exists()).toBe(false)
    expect(body.find('img').exists()).toBe(false)
    expect(body.text()).toContain('<b>this</b>')
  })

  it('draws a call to action only through a safe address, apart and without a referrer', async () => {
    h.get.mockResolvedValue({ data: [
      row({ id: 1, cta_url: 'https://example.org/go', cta_label: 'Read more' }),
      row({ id: 2, cta_url: 'javascript:alert(1)', cta_label: 'Click' }),
    ] })
    const w = mount(PublicAnnouncements)
    await flushPromises()
    const links = w.findAll('[data-testid="pa-cta"]')
    expect(links).toHaveLength(1)
    expect(links[0].attributes('href')).toBe('https://example.org/go')
    expect(links[0].attributes('rel')).toContain('noopener')
    expect(links[0].attributes('rel')).toContain('noreferrer')
    expect(links[0].text()).toBe('Read more')
  })

  it('says none is public when the registry has none, through the reason line', async () => {
    h.get.mockResolvedValue({ data: [] })
    const w = mount(PublicAnnouncements)
    await flushPromises()
    expect(w.find('[data-testid="pa-item"]').exists()).toBe(false)
    const why = w.get('[data-testid="empty-reason"]')
    expect(why.attributes('data-kind')).toBe('none-yet')
    expect(why.text()).toContain('No announcement has been made public')
  })

  it('says it could not read them, and offers a retry, rather than "none"', async () => {
    h.get.mockRejectedValueOnce(new Error('down'))
    const w = mount(PublicAnnouncements)
    await flushPromises()
    expect(w.find('[data-testid="empty-reason"]').exists()).toBe(false)
    expect(w.get('[data-testid="pa-failed"]').text()).toContain('could not be read')
    h.get.mockResolvedValueOnce({ data: [row()] })
    await w.get('[data-testid="pa-retry"]').trigger('click')
    await flushPromises()
    expect(w.findAll('[data-testid="pa-item"]')).toHaveLength(1)
    expect(w.find('[data-testid="pa-failed"]').exists()).toBe(false)
  })
})
