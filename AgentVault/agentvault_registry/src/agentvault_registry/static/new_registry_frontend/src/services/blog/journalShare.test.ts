/**
 * V0664 (order gwo_565d65d77f4906cdd36f957c, part of gwo_f34431851c76649484ae1216): the journal's Share button and its
 * link preview image.
 *   - a post's public link is its static page on the apex, https://theprotocol.cloud/blog/<slug>/ (the page that
 *     previews; the console's #/blog/<slug> cannot, a crawler never runs the app);
 *   - a post's preview image is the one scratchpad/gen_blog_static.mjs writes beside that page (og.jpg), made from the
 *     post's lead figure (its first /static/blog/ image, a real console screenshot); a post with no figure uses the
 *     site image, so the console never names an image the generator did not write;
 *   - Share on a touch screen opens the share sheet; elsewhere it copies the link; a link it could not copy is shown
 *     to copy by hand; a sheet the reader closed is not an error;
 *   - while a post is open the head carries its preview tags, and leaving puts the page's own tags back.
 * Red on b27f2ebaf: the module does not exist.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  JOURNAL_ORIGIN, SITE_PREVIEW_IMAGE, applyPostHead, leadFigure, postPreviewImage, postPublicUrl, sharePost,
} from './journalShare'

const POST = {
  slug: 'the-last-puzzle-piece', title: 'The Last Puzzle Piece', excerpt: 'The closing piece.',
  content: '<p>x</p><figure><img src="/static/blog/p54-eu-discovery.jpg" alt="a"></figure><img src="/static/blog/p54-b.jpg">',
}
const NO_FIGURE = { ...POST, slug: 'agent-mtls-cryptographic-identity', content: '<p>words only</p><img src="https://elsewhere.example/x.png">' }

describe('the public link and the preview image', () => {
  it('the link is the static page on the apex, with its trailing slash', () => {
    expect(JOURNAL_ORIGIN).toBe('https://theprotocol.cloud')
    expect(postPublicUrl(POST.slug)).toBe('https://theprotocol.cloud/blog/the-last-puzzle-piece/')
  })

  it('the lead figure is the first journal image of the post, and only a journal image counts', () => {
    expect(leadFigure(POST.content)).toBe('p54-eu-discovery.jpg')
    expect(leadFigure(NO_FIGURE.content)).toBeNull()
  })

  it('a post with a figure previews with the image beside its page; one without, with the site image', () => {
    expect(postPreviewImage(POST)).toBe('https://theprotocol.cloud/blog/the-last-puzzle-piece/og.jpg')
    expect(postPreviewImage(NO_FIGURE)).toBe(SITE_PREVIEW_IMAGE)
    expect(SITE_PREVIEW_IMAGE).toBe('https://theprotocol.cloud/og-image.jpg')
  })
})

function env(o: { coarse?: boolean, share?: any, writeText?: any } = {}) {
  return {
    share: o.share,
    clipboard: o.writeText ? { writeText: o.writeText } : undefined,
    coarsePointer: () => !!o.coarse,
  }
}

describe('Share', () => {
  it('on a touch screen it opens the share sheet with the title and the link', async () => {
    const share = vi.fn().mockResolvedValue(undefined)
    const writeText = vi.fn()
    expect(await sharePost(POST, env({ coarse: true, share, writeText }))).toBe('shared')
    expect(share).toHaveBeenCalledWith({ title: POST.title, url: 'https://theprotocol.cloud/blog/the-last-puzzle-piece/' })
    expect(writeText).not.toHaveBeenCalled()
  })

  it('a share sheet the reader closed is not an error', async () => {
    const share = vi.fn().mockRejectedValue(Object.assign(new Error('closed'), { name: 'AbortError' }))
    expect(await sharePost(POST, env({ coarse: true, share, writeText: vi.fn() }))).toBe('cancelled')
  })

  it('a share sheet that failed falls back to copying', async () => {
    const share = vi.fn().mockRejectedValue(Object.assign(new Error('no'), { name: 'NotAllowedError' }))
    const writeText = vi.fn().mockResolvedValue(undefined)
    expect(await sharePost(POST, env({ coarse: true, share, writeText }))).toBe('copied')
    expect(writeText).toHaveBeenCalledWith('https://theprotocol.cloud/blog/the-last-puzzle-piece/')
  })

  it('with a mouse it copies the link, even where a share sheet exists', async () => {
    const share = vi.fn()
    const writeText = vi.fn().mockResolvedValue(undefined)
    expect(await sharePost(POST, env({ coarse: false, share, writeText }))).toBe('copied')
    expect(share).not.toHaveBeenCalled()
  })

  it('a link it could not copy is shown to copy by hand', async () => {
    expect(await sharePost(POST, env({ writeText: vi.fn().mockRejectedValue(new Error('denied')) }))).toBe('shown')
    expect(await sharePost(POST, env({}))).toBe('shown')
  })
})

describe('the head while a post is open', () => {
  afterEach(() => { document.head.innerHTML = '' })

  const tag = (sel: string) => document.head.querySelector(sel)?.getAttribute(sel.startsWith('link') ? 'href' : 'content')

  it('carries the post, and leaving puts the page tags back and drops the ones it added', () => {
    document.head.innerHTML = '<meta property="og:title" content="Site"><meta name="twitter:image" content="/site.jpg">'
      + '<link rel="canonical" href="https://theprotocol.cloud/">'
    const restore = applyPostHead(POST)
    expect(tag('meta[property="og:title"]')).toBe('The Last Puzzle Piece')
    expect(tag('meta[property="og:description"]')).toBe('The closing piece.')
    expect(tag('meta[property="og:url"]')).toBe('https://theprotocol.cloud/blog/the-last-puzzle-piece/')
    expect(tag('meta[property="og:type"]')).toBe('article')
    expect(tag('meta[property="og:image"]')).toBe('https://theprotocol.cloud/blog/the-last-puzzle-piece/og.jpg')
    expect(tag('meta[property="og:image:alt"]')).toBe('The Last Puzzle Piece')
    expect(tag('meta[name="twitter:card"]')).toBe('summary_large_image')
    expect(tag('meta[name="twitter:image"]')).toBe('https://theprotocol.cloud/blog/the-last-puzzle-piece/og.jpg')
    expect(tag('link[rel="canonical"]')).toBe('https://theprotocol.cloud/blog/the-last-puzzle-piece/')
    restore()
    expect(tag('meta[property="og:title"]')).toBe('Site')
    expect(tag('meta[name="twitter:image"]')).toBe('/site.jpg')
    expect(tag('link[rel="canonical"]')).toBe('https://theprotocol.cloud/')
    expect(document.head.querySelector('meta[property="og:image:alt"]')).toBeNull()
    expect(document.head.querySelector('meta[name="twitter:card"]')).toBeNull()
  })
})
