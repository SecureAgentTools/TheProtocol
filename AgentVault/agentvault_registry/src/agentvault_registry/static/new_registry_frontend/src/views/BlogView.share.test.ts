/**
 * V0664 (order gwo_565d65d77f4906cdd36f957c): the journal's Share button and the head of an open post, in the view.
 *   - an open post has a Share button that copies its public link (the static page on the apex) and says so;
 *   - a link the browser would not copy is shown in a field, selected, to copy by hand;
 *   - the journal index has no Share button (it shares no single post);
 *   - an open post's head carries its preview tags, a move to another post carries that post's, leaving restores;
 *   - every journal image a post names exists in public/blog, so a lead figure the generator makes a preview from is
 *     there (the class of D6-848, a figure that existed nowhere).
 * Red on b27f2ebaf: no Share button, no head tags.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RouterLinkStub, flushPromises, mount } from '@vue/test-utils'

vi.mock('@/composables/docs/useMermaidRenderer', () => ({ renderMermaidDiagrams: vi.fn().mockResolvedValue(undefined) }))

import BlogView from './BlogView.vue'
import source from './BlogView.vue?raw'

const SLUG = 'the-last-puzzle-piece'
const URL_ = `https://theprotocol.cloud/blog/${SLUG}/`

function open(slug: string | null = SLUG) {   // null opens the index (undefined would take the default)
  return mount(BlogView, { props: slug === null ? {} : { slug }, global: { stubs: { RouterLink: RouterLinkStub } } })
}
function setClipboard(value: unknown) {
  Object.defineProperty(navigator, 'clipboard', { value, configurable: true })
}

describe('the Share button on a post', () => {
  beforeEach(() => {
    document.head.innerHTML = '<meta property="og:url" content="https://api.theprotocol.cloud/ui">'
      + '<link rel="canonical" href="https://theprotocol.cloud/">'
  })
  afterEach(() => { setClipboard(undefined); document.head.innerHTML = '' })

  it('copies the post public link and says so', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    setClipboard({ writeText })
    const w = open()
    await w.find('[data-testid="bl-share"]').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith(URL_)
    expect(w.find('[data-testid="bl-share-status"]').attributes('data-outcome')).toBe('copied')
    w.unmount()
  })

  it('a link the browser would not copy is shown to copy by hand', async () => {
    setClipboard(undefined)
    const w = open()
    await w.find('[data-testid="bl-share"]').trigger('click')
    await flushPromises()
    const field = w.find('[data-testid="bl-share-link"]')
    expect(field.exists()).toBe(true)
    expect((field.element as HTMLInputElement).value).toBe(URL_)
    expect(field.attributes('readonly')).toBeDefined()
    w.unmount()
  })

  it('the journal index has no Share button', () => {
    const w = open(null)
    expect(w.find('.bl-hero').exists()).toBe(true)
    expect(w.find('[data-testid="bl-share"]').exists()).toBe(false)
    w.unmount()
  })

  it('an open post carries its preview tags, another post its own, and leaving restores the page tags', async () => {
    const w = open()
    await flushPromises()
    const og = () => document.head.querySelector('meta[property="og:url"]')?.getAttribute('content')
    expect(og()).toBe(URL_)
    expect(document.head.querySelector('meta[name="twitter:card"]')?.getAttribute('content')).toBe('summary_large_image')
    await w.setProps({ slug: 'built-through-itself' })
    await flushPromises()
    expect(og()).toBe('https://theprotocol.cloud/blog/built-through-itself/')
    await w.setProps({ slug: undefined })
    await flushPromises()
    expect(og()).toBe('https://api.theprotocol.cloud/ui')
    await w.setProps({ slug: SLUG })
    await flushPromises()
    w.unmount()
    expect(og()).toBe('https://api.theprotocol.cloud/ui')
    expect(document.head.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe('https://theprotocol.cloud/')
  })
})

describe('the figures a post names', () => {
  it('every journal image a post names exists in public/blog', async () => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const posts = source.slice(0, source.indexOf('<style'))
    const names = [...new Set([...posts.matchAll(/src="\/static\/blog\/([^"]+)"/g)].map((m) => m[1]))]
    expect(names.length).toBeGreaterThan(100)
    const missing = names.filter((n) => !fs.existsSync(path.resolve(__dirname, '../../public/blog', n)))
    expect(missing).toEqual([])
  })
})
