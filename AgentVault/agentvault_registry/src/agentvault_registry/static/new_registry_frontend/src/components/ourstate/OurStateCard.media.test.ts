import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0652 (ae) (order gwo_5b9de9adb052d681ca95853d): a text file's card shows its first lines, as its registry wrote
 * them: markdown rendered by the chat's renderer (raw HTML stays text), JSON, CSV, logs and text as text. "Open" fetches
 * the file (the member's authenticated read) and shows all of it in the card; "Download" stays. A file shaped like a
 * credential, or a binary, shows none and says why; a stranger's request shows nothing. BASE (V0651): name, size and a
 * Download button, nothing else.
 */
const h = vi.hoisted(() => ({ get: null as unknown as (...a: any[]) => any }))
vi.mock('@/services/api/client', () => {
  const c = { get: (...a: any[]) => h.get(...a), post: vi.fn(), put: vi.fn(), delete: vi.fn() }
  return { default: c, apiClient: c }
})

import OurStateCard from './OurStateCard.vue'
import { cardView } from '@/services/chat/cards'

const media = (data: Record<string, any>) => ({ v: 1, type: 'media', data: {
  attachment_id: 'att-1', name: 'plan.md', mime: 'text/markdown', bytes: 2048, sha256: 'ab'.repeat(32), ...data } })
const card = (data: Record<string, any>, props: Record<string, any> = {}) =>
  mount(OurStateCard, { props: { card: media(data), ...props }, global: { stubs: { Icon: true } } })
const buf = (s: string) => new TextEncoder().encode(s).buffer

describe('a text file shows its first lines on its card', () => {
  beforeEach(() => { h.get = vi.fn() })

  it('markdown is rendered; its HTML stays text', () => {
    const w = card({ preview: '# Plan\n\n**ship** (ae)\n\n<script>alert(1)</script>', preview_kind: 'markdown',
      preview_truncated: true })
    const p = w.find('[data-testid="osc-media-preview"]')
    expect(p.attributes('data-kind')).toBe('markdown')
    expect(p.find('h1').text()).toBe('Plan')
    expect(p.find('strong').text()).toBe('ship')
    expect(p.find('script').exists()).toBe(false)
    expect(p.text()).toContain('<script>alert(1)</script>')
    expect(w.find('[data-testid="osc-media-more"]').exists()).toBe(true)        // the file goes on
  })

  it.each(['json', 'csv', 'log', 'text'])('%s is text in a monospace block, never markup', (kind) => {
    const w = card({ name: 'x', mime: 'text/plain', preview: '<b>{"a": 1}</b>', preview_kind: kind, preview_truncated: false })
    const p = w.find('[data-testid="osc-media-preview"]')
    expect(p.element.tagName).toBe('PRE')
    expect(p.attributes('data-kind')).toBe(kind)
    expect(p.find('b').exists()).toBe(false)
    expect(p.text()).toBe('<b>{"a": 1}</b>')
    expect(w.find('[data-testid="osc-media-more"]').exists()).toBe(false)
  })

  it('a file shaped like a credential shows no preview, says why, and offers no Open', () => {
    const w = card({ preview_withheld: 'credential' })
    expect(w.find('[data-testid="osc-media-preview"]').exists()).toBe(false)
    expect(w.find('[data-testid="osc-media-withheld"]').attributes('data-why')).toBe('credential')
    expect(w.find('[data-testid="osc-media-open-btn"]').exists()).toBe(false)
    expect(w.find('[data-testid="osc-media-get"]').exists()).toBe(true)          // the member's download stays
  })

  it('in a stranger\'s request nothing shows on sight', () => {
    const w = card({ preview: '# hi', preview_kind: 'markdown' }, { defang: true })
    expect(w.find('[data-testid="osc-media-preview"]').exists()).toBe(false)
    expect(w.find('[data-testid="osc-media-open-btn"]').exists()).toBe(false)
    expect(w.find('[data-testid="osc-media-defanged"]').exists()).toBe(true)
  })

  it('a picture shows no preview and no Open', () => {
    const w = card({ name: 'a.png', mime: 'image/png' })
    expect(w.find('[data-testid="osc-media-preview"]').exists()).toBe(false)
    expect(w.find('[data-testid="osc-media-open-btn"]').exists()).toBe(false)
  })

  it('Open shows the whole file in the card (JSON pretty-printed), Close folds it back', async () => {
    h.get = vi.fn().mockResolvedValue({ data: buf('{"order":"(ae)","done":true}') })
    const w = card({ name: 'state.json', mime: 'application/json', preview: '{\n  "order": "(ae)",', preview_kind: 'json',
      preview_truncated: true })
    await w.find('[data-testid="osc-media-open-btn"]').trigger('click')
    await flushPromises()
    expect(h.get).toHaveBeenCalledWith('/chat/attachments/att-1', { responseType: 'arraybuffer' })
    const open = w.find('[data-testid="osc-media-open"]')
    expect(open.attributes('data-kind')).toBe('json')
    expect(open.find('pre').text()).toBe('{\n  "order": "(ae)",\n  "done": true\n}')
    expect(w.find('[data-testid="osc-media-preview"]').exists()).toBe(false)
    expect(w.find('[data-testid="osc-media-open-btn"]').text()).toContain('Close')
    await w.find('[data-testid="osc-media-open-btn"]').trigger('click')
    expect(w.find('[data-testid="osc-media-open"]').exists()).toBe(false)
    expect(w.find('[data-testid="osc-media-preview"]').exists()).toBe(true)
  })

  it('Open on a removed file says so', async () => {
    h.get = vi.fn().mockRejectedValue(Object.assign(new Error('gone'), { response: { status: 410 } }))
    const w = card({ preview: 'x', preview_kind: 'text' })
    await w.find('[data-testid="osc-media-open-btn"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="osc-media-err"]').text()).toContain('removed')
    expect(w.find('[data-testid="osc-media-open"]').exists()).toBe(false)
  })
})

describe('the card view keeps the registry\'s bounds', () => {
  it('no more than 600 characters, a known kind, and nothing in a request', () => {
    const v = cardView(media({ preview: 'y'.repeat(900), preview_kind: 'html', preview_truncated: true }) as any) as any
    expect(v.preview.length).toBe(600)
    expect(v.previewKind).toBe('text')
    expect(v.previewTruncated).toBe(true)
    const d = cardView(media({ preview: 'x', preview_withheld: 'credential' }) as any, { defang: true }) as any
    expect(d.preview).toBe(null)
    expect(d.previewWithheld).toBe(null)
    expect((cardView(media({ preview_withheld: 'maybe' }) as any) as any).previewWithheld).toBe(null)
  })
})
