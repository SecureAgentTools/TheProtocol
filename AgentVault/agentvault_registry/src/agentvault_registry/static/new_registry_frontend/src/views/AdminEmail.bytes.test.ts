/**
 * §FESUITE (V0578): the email studio's toolbar says how big the preview on screen is. It read "0 B" before the first
 * render answered, and the previous template's size while a render was out or after one failed (the preview pane said
 * the render failed; the toolbar kept the other template's figure). It now reads "—" whenever no preview of this
 * template is on screen.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ previewHtml: vi.fn() }))
vi.mock('@/services/api/emailAdmin', () => ({
  emailAdminService: {
    list: async () => ({ templates: ['welcome', 'reset'] }),
    previewHtml: (...a: unknown[]) => h.previewHtml(...a),
    previewText: async () => 'text',
  },
  emailSendService: { senders: vi.fn(), sampleContext: vi.fn(), send: vi.fn() },
  emailPreviewWithContext: { html: vi.fn(), text: vi.fn() },
}))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn() }) }))

import AdminEmail from './AdminEmail.vue'

const badGateway = () => new AxiosError('Request failed with status code 502', 'ERR_BAD_RESPONSE', undefined, undefined,
  { status: 502, statusText: '', data: {}, headers: {}, config: {} } as any)
const BODY = '<html><body>' + 'x'.repeat(2048) + '</body></html>'   // 2.0 kB
let w: VueWrapper | null = null
const bytes = () => w!.findAll('.ae-toolbar-right .ae-mono-val')[0].text()

describe("the email studio's preview size", () => {
  beforeEach(() => { h.previewHtml.mockReset() })
  afterEach(() => { w?.unmount(); w = null })

  it('reads no size before the first render answers', async () => {
    h.previewHtml.mockReturnValue(new Promise(() => {}))
    w = mount(AdminEmail, { global: { stubs: { Icon: true } } })
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(bytes(), 'claimed a size before the render answered').not.toMatch(/\d/)
  })

  it('a failed render of another template does not keep the previous template\'s size', async () => {
    h.previewHtml.mockResolvedValueOnce(BODY)
    w = mount(AdminEmail, { global: { stubs: { Icon: true } } })
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(bytes()).toBe('2.0 kB')
    h.previewHtml.mockRejectedValueOnce(badGateway())
    await w.findAll('.ae-side-item').find(b => b.text().includes('reset'))!.trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(w.find('.ae-main').text()).toContain('Request failed with status code 502')
    expect(bytes(), 'kept the "welcome" size beside a "reset" render that failed').not.toMatch(/\d/)
  })
})
