import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0664 (order gwo_c101e38685cd18581be34c2f; his phone report, room seq 3760): a picture sent alone showed as a file card with a name, a
 * size and Download. It now shows as a picture (the viewer's own authenticated read, never an <img src> naming the registry), the
 * Download button stays, and a stranger's request, an SVG and every other file keep the file card.
 */
const h = vi.hoisted(() => ({ get: null as any }))
vi.mock('@/services/api/client', () => {
  const c = { get: (...a: any[]) => h.get(...a), post: vi.fn(), put: vi.fn(), delete: vi.fn() }
  return { default: c, apiClient: c }
})

import OurStateCard from './OurStateCard.vue'

const media = (data: Record<string, any>) => ({ v: 1, type: 'media', data: {
  attachment_id: 'att-9', name: 'shot.png', mime: 'image/png', bytes: 4096, sha256: 'cd'.repeat(32), ...data } })
const card = (data: Record<string, any>, props: Record<string, any> = {}) =>
  mount(OurStateCard, { props: { card: media(data), ...props }, global: { stubs: { Icon: true } } })

describe('a picture sent alone shows as a picture', () => {
  beforeEach(() => {
    h.get = vi.fn().mockResolvedValue({ data: new Blob(['x'], { type: 'image/png' }) })
    ;(globalThis.URL as any).createObjectURL = vi.fn(() => 'blob:picture')
    ;(globalThis.URL as any).revokeObjectURL = vi.fn()
  })

  it('reads the file with the viewer\'s own session and keeps the file card around it', async () => {
    const w = card({})
    await flushPromises()
    expect(h.get).toHaveBeenCalledTimes(1)
    expect(h.get.mock.calls[0][0]).toBe('/chat/attachments/att-9')
    expect(w.find('[data-testid="cp-img"]').attributes('src')).toBe('blob:picture')
    expect(w.find('[data-testid="osc-media"]').text()).toContain('shot.png')
    expect(w.find('[data-testid="osc-media-get"]').exists()).toBe(true)
  })

  it('shows nothing of a stranger\'s picture on sight, and nothing at all for an SVG or any other file', async () => {
    for (const w of [card({}, { defang: true }), card({ mime: 'image/svg+xml', name: 'a.svg' }), card({ mime: 'application/pdf', name: 'a.pdf' })]) {
      await flushPromises()
      expect(w.find('[data-testid="cp-root"]').exists()).toBe(false)
    }
    expect(h.get).not.toHaveBeenCalled()
  })
})
