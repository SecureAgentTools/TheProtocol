// V0664 (order gwo_565d65d77f4906cdd36f957c): the journal's Share button and the link preview of a post.
//
// A post's public link is its static page on the apex (scratchpad/gen_blog_static.mjs writes /blog/<slug>/ there): a
// crawler never runs the app, so the console's #/blog/<slug> previews as the site's front page. The generator also
// writes the post's preview image beside that page (og.jpg) from its lead figure, the first journal image in the post;
// LEAD_FIGURE below is the same rule as the generator's, so the console never names an image it did not write. A post
// with no figure previews with the site image.

export const JOURNAL_ORIGIN = 'https://theprotocol.cloud'
export const SITE_PREVIEW_IMAGE = `${JOURNAL_ORIGIN}/og-image.jpg`
const LEAD_FIGURE = /<img\b[^>]*\bsrc="\/static\/blog\/([^"]+)"/

export interface SharablePost { slug: string, title: string, excerpt: string, content: string }

export function postPublicUrl(slug: string): string {
  return `${JOURNAL_ORIGIN}/blog/${encodeURIComponent(slug)}/`
}

export function leadFigure(content: string): string | null {
  const m = LEAD_FIGURE.exec(content || '')
  return m ? m[1] : null
}

export function postPreviewImage(post: Pick<SharablePost, 'slug' | 'content'>): string {
  return leadFigure(post.content) ? `${postPublicUrl(post.slug)}og.jpg` : SITE_PREVIEW_IMAGE
}

// ── Share ────────────────────────────────────────────────────────────────────────────────────────────────────────
// A touch screen gets the share sheet (it holds copy as well); a mouse gets the link copied, the sheet on a desktop
// being a detour. A sheet the reader closed is no error. A link the browser would not copy is shown to copy by hand.

export type ShareOutcome = 'shared' | 'copied' | 'shown' | 'cancelled'

export interface ShareEnv {
  share?: (data: { title: string, url: string }) => Promise<void>
  clipboard?: { writeText: (text: string) => Promise<void> }
  coarsePointer: () => boolean
}

export function browserShareEnv(): ShareEnv {
  const nav: any = typeof navigator === 'undefined' ? {} : navigator
  return {
    share: typeof nav.share === 'function' ? (d) => nav.share(d) : undefined,
    clipboard: nav.clipboard && typeof nav.clipboard.writeText === 'function' ? nav.clipboard : undefined,
    coarsePointer: () => typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      && window.matchMedia('(pointer: coarse)').matches,
  }
}

export async function sharePost(post: Pick<SharablePost, 'slug' | 'title'>, env: ShareEnv = browserShareEnv()): Promise<ShareOutcome> {
  const url = postPublicUrl(post.slug)
  if (env.share && env.coarsePointer()) {
    try {
      await env.share({ title: post.title, url })
      return 'shared'
    } catch (e: any) {
      if (e && e.name === 'AbortError') return 'cancelled'
    }
  }
  if (env.clipboard) {
    try {
      await env.clipboard.writeText(url)
      return 'copied'
    } catch { /* shown below */ }
  }
  return 'shown'
}

// ── The head of an open post ─────────────────────────────────────────────────────────────────────────────────────
// The same tags the static page carries, so an app that reads the head (a reader's share extension, an unfurler that
// runs scripts) sees the post. Returns the restore: the page's own values back, the tags it added removed.

type HeadTag = [kind: 'property' | 'name' | 'link', key: string, value: string]

export function postHeadTags(post: SharablePost): HeadTag[] {
  const url = postPublicUrl(post.slug)
  const image = postPreviewImage(post)
  return [
    ['property', 'og:type', 'article'],
    ['property', 'og:title', post.title],
    ['property', 'og:description', post.excerpt],
    ['property', 'og:url', url],
    ['property', 'og:image', image],
    ['property', 'og:image:alt', post.title],
    ['name', 'twitter:card', 'summary_large_image'],
    ['name', 'twitter:title', post.title],
    ['name', 'twitter:description', post.excerpt],
    ['name', 'twitter:image', image],
    ['link', 'canonical', url],
  ]
}

export function applyPostHead(post: SharablePost, head: HTMLHeadElement = document.head): () => void {
  const undo: Array<() => void> = []
  for (const [kind, key, value] of postHeadTags(post)) {
    const isLink = kind === 'link'
    const attr = isLink ? 'href' : 'content'
    const selector = isLink ? `link[rel="${key}"]` : `meta[${kind}="${key}"]`
    let el = head.querySelector(selector)
    if (el) {
      const before = el.getAttribute(attr)
      const tag = el
      undo.push(() => { if (before === null) tag.removeAttribute(attr); else tag.setAttribute(attr, before) })
    } else {
      el = document.createElement(isLink ? 'link' : 'meta')
      el.setAttribute(isLink ? 'rel' : kind, key)
      head.appendChild(el)
      const added = el
      undo.push(() => added.remove())
    }
    el.setAttribute(attr, value)
  }
  return () => { for (const f of undo.reverse()) f() }
}
