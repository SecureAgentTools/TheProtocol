import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => {
  const c = { get: (...a: any[]) => h.get(...a), post: vi.fn(), put: vi.fn(), delete: vi.fn() }
  return { default: c, apiClient: c }
})
vi.mock('@/composables/useI18n', () => ({ useI18n: () => ({ t: (_k: string, f?: string) => f ?? _k, tp: (_k: string, f?: string, p?: any) => (f ?? _k).replace(/\{(\w+)\}/g, (_m, k) => String(p?.[k] ?? '')) }) }))

import ChatPicture from './ChatPicture.vue'

/** V0664 (order gwo_c101e38685cd18581be34c2f, his phone report): a picture shows as a picture. The bytes still arrive only through the
 *  viewer's own authenticated read (no <img src> naming the registry): shown at once for the viewer's own pictures and for the people of
 *  a room, on a press where the card is a stranger's request (defang). */
const props = (over: Record<string, any> = {}) => ({ attachmentId: 'att-1', name: 'shot.jpg', mime: 'image/jpeg', bytes: 583000, ...over })
const mk = (over: Record<string, any> = {}) => mount(ChatPicture, { props: props(over), global: { stubs: { Icon: true } } })

describe('ChatPicture', () => {
  beforeEach(() => {
    h.get.mockReset()
    ;(URL as any).createObjectURL = vi.fn(() => 'blob:pic-1')
    ;(URL as any).revokeObjectURL = vi.fn()
  })
  afterEach(() => { vi.restoreAllMocks() })

  it('reads the picture with the viewer\'s own token and shows it, named for a screen reader', async () => {
    h.get.mockResolvedValue({ data: new Blob(['x'], { type: 'image/jpeg' }) })
    const w = mk()
    await flushPromises()
    expect(h.get).toHaveBeenCalledWith('/chat/attachments/att-1', { responseType: 'blob' })
    const img = w.find('[data-testid=cp-img]')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toBe('blob:pic-1')
    expect(img.attributes('alt')).toBe('shot.jpg')
  })

  it('on a stranger\'s request reads nothing until it is pressed', async () => {
    h.get.mockResolvedValue({ data: new Blob(['x'], { type: 'image/jpeg' }) })
    const w = mk({ auto: false })
    await flushPromises()
    expect(h.get).not.toHaveBeenCalled()
    expect(w.find('[data-testid=cp-img]').exists()).toBe(false)
    await w.find('[data-testid=cp-show]').trigger('click')
    await flushPromises()
    expect(h.get).toHaveBeenCalledTimes(1)
    expect(w.find('[data-testid=cp-img]').exists()).toBe(true)
  })

  it('a press on the picture makes it larger and a second press gives it back', async () => {
    h.get.mockResolvedValue({ data: new Blob(['x'], { type: 'image/jpeg' }) })
    const w = mk()
    await flushPromises()
    expect(w.find('[data-testid=cp-root]').classes()).not.toContain('open')
    await w.find('[data-testid=cp-img]').trigger('click')
    expect(w.find('[data-testid=cp-root]').classes()).toContain('open')
    await w.find('[data-testid=cp-img]').trigger('click')
    expect(w.find('[data-testid=cp-root]').classes()).not.toContain('open')
  })

  it('says a removed file is removed, and any other failure as a failure that can be tried again', async () => {
    h.get.mockRejectedValueOnce({ response: { status: 410 } })
    const w = mk()
    await flushPromises()
    expect(w.find('[data-testid=cp-gone]').exists()).toBe(true)
    h.get.mockRejectedValueOnce({ response: { status: 500 } })
    const w2 = mk()
    await flushPromises()
    expect(w2.find('[data-testid=cp-retry]').exists()).toBe(true)
    h.get.mockResolvedValue({ data: new Blob(['x'], { type: 'image/jpeg' }) })
    await w2.find('[data-testid=cp-retry]').trigger('click')
    await flushPromises()
    expect(w2.find('[data-testid=cp-img]').exists()).toBe(true)
  })

  it('gives the memory back when it goes away', async () => {
    h.get.mockResolvedValue({ data: new Blob(['x'], { type: 'image/jpeg' }) })
    const w = mk()
    await flushPromises()
    w.unmount()
    expect((URL as any).revokeObjectURL).toHaveBeenCalledWith('blob:pic-1')
  })

  it('names the file and its size while it loads', () => {
    h.get.mockReturnValue(new Promise(() => {}))
    const w = mk()
    expect(w.text()).toContain('shot.jpg')
  })
})
