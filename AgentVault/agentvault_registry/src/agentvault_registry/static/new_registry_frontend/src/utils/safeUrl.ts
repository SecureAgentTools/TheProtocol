/**
 * safeExternalUrl — guard for hrefs bound to user / operator / agent-supplied
 * URLs (repo links, websites, operator cloud URLs, card icon URLs, …).
 *
 * Returns the URL only if it is http(s) or a site-relative path; otherwise
 * returns undefined, so `:href="safeExternalUrl(x)"` renders no href and a
 * malicious `javascript:` / `data:` scheme cannot execute when the link is
 * clicked. Always pair with target="_blank" rel="noopener noreferrer".
 */
export function safeExternalUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined
  const v = String(url).trim()
  if (!v) return undefined
  // Site-relative path (but not protocol-relative "//evil.com").
  if (v.startsWith('/') && !v.startsWith('//')) return v
  try {
    const u = new URL(v, window.location.origin)
    if (u.protocol === 'http:' || u.protocol === 'https:') return u.href
  } catch {
    /* not a parseable URL → treat as unsafe */
  }
  return undefined
}
