// V0667 static pages (order gwo_a9f121caa4138ec9b369814c): the static document around a view rendered from the app's own source. Pure: no
// framework, no network. A static page carries no script and no handler: it is text, links and the app's own stylesheet.
export const SITE = 'TheProtocol'
export const APEX_ORIGIN = 'https://theprotocol.cloud'
const LANDING_END = '<!--static-landing-end-->'

const ENTITIES: Record<string, string> = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'", '&nbsp;': ' ', '&#x27;': "'" }

export function escapeHtml(s: string): string {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/** The text a reader without JavaScript gets: no comment (a template's comment is not text), no script, no style, no tag. */
export function pageText(html: string): string {
  return String(html)
    .replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&(?:amp|lt|gt|quot|nbsp|#39|#x27);/g, (m) => ENTITIES[m] ?? ' ')
    .replace(/&[a-z#0-9]+;/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/** Leave out every region marked data-static="omit" (live data: a number frozen at build time reads as a fact, an empty list as an outage). */
export function omitLive(html: string): string {
  const doc = new DOMParser().parseFromString(`<!DOCTYPE html><html><body>${html}</body></html>`, 'text/html')
  doc.querySelectorAll('[data-static="omit"]').forEach((el) => el.remove())
  return doc.body.innerHTML
}

/** The description: the first paragraph long enough to say something, cut at a word to 160 characters. */
export function descriptionOf(html: string): string {
  for (const m of String(html).matchAll(/<p\b[^>]*>([\s\S]*?)<\/p>/gi)) {
    const t = pageText(m[1])
    if (t.length >= 60) return t.length <= 160 ? t : t.slice(0, 157).replace(/\s+\S*$/, '') + '…'
  }
  return ''
}

export interface PageDoc {
  path: string                                  // the page's own plain path, '/compliance/'
  live: string                                  // its live counterpart in the app
  title: string
  description: string
  body: string                                  // the view's rendered HTML, live regions already left out
  css: string[]                                 // the app's own stylesheets
  nav: { path: string; title: string }[]       // the other static pages
}

export function pageDocument(d: PageDoc): string {
  const nav = d.nav.map((n) => `<a href="${escapeHtml(n.path)}">${escapeHtml(n.title)}</a>`).join(' · ')
  return [
    '<!DOCTYPE html>',
    '<html lang="en">',
    '<head>',
    '<meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    `<title>${escapeHtml(d.title)} · ${SITE}</title>`,
    `<meta name="description" content="${escapeHtml(d.description)}">`,
    `<link rel="canonical" href="${APEX_ORIGIN}${escapeHtml(d.path)}">`,
    ...d.css.map((href) => `<link rel="stylesheet" href="${escapeHtml(href)}">`),
    '</head>',
    '<body class="theme-neural static-page">',
    `<header class="static-page-head"><a href="/">${SITE}</a> · <a href="${escapeHtml(d.live)}">Open this page in the console</a></header>`,
    `<main id="main">${d.body}</main>`,
    `<footer class="static-page-foot"><nav>${nav}</nav></footer>`,
    '</body>',
    '</html>',
    '',
  ].join('\n')
}

/** The landing page, inside the app's own index.html: in #app, where the app mounts over it; its scripts and head kept. */
export function injectLanding(indexHtml: string, body: string): string {
  const open = '<div id="app">'
  const at = indexHtml.indexOf(open)
  if (at < 0) throw new Error('the index has no #app (<div id="app">): nothing to put the landing page in')
  const from = at + open.length
  const end = indexHtml.indexOf(LANDING_END, from)
  const close = end >= 0 ? end + LANDING_END.length : from                      // a second run replaces what the first put there
  return indexHtml.slice(0, from) + body + LANDING_END + indexHtml.slice(close)
}

/** The gate every page passes, in the render test and in the generator alike: at least its minimum of text, both its phrases, none of its live
 *  data. Answers the reasons a page fails (none: it passes). */
export function pageGate(text: string, inst: { minText: number; phrases: string[]; absent?: string[] }): string[] {
  return [
    text.length < inst.minText ? `${text.length} characters, fewer than ${inst.minText}` : '',
    ...inst.phrases.filter((ph) => !text.includes(ph)).map((ph) => `no "${ph}"`),
    ...(inst.absent ?? []).filter((ph) => text.includes(ph)).map((ph) => `live data "${ph}"`),
  ].filter(Boolean)
}
