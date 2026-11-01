/**
 * V0652 (x) (order gwo_cedd900e6d50be18ce4eecf1): the renderer and the highlight rules. Markdown on the docs viewer's
 * terms, the sanitizer refusing HTML and script, the chips, the fold, the mentions, ids small and grey, a time on every
 * message. BASE (V0651): no module; a message was its raw text.
 */
import { describe, expect, it } from 'vitest'
import { isAsk, namesViewer, renderMarkdown, renderMessage, splitStatusTag, timeLabel, timeTitle } from './messageText'

describe('markdown, on the docs viewer terms', () => {
  it('bold, italics, lists, inline code, code blocks and short headings', () => {
    const h = renderMarkdown('**done** and *soon*\n\n- one\n- two\n\n`npm ci`\n\n```\nmake\n```\n\n## Next')
    expect(h).toContain('<strong>done</strong>')
    expect(h).toContain('<em>soon</em>')
    expect(h).toMatch(/<ul>\s*<li>one<\/li>\s*<li>two<\/li>\s*<\/ul>/)
    expect(h).toContain('<code>npm ci</code>')
    expect(h).toMatch(/<pre><code>make\n<\/code><\/pre>/)
    expect(h).toContain('<h2>Next</h2>')
  })

  it('a message that opens with a heading, a list or a code block keeps it', () => {
    expect(renderMarkdown('# Plan')).toBe('<h1>Plan</h1>\n')
    expect(renderMarkdown('- one\n- two')).toMatch(/^<ul>\s*<li>one<\/li>/)
    expect(renderMarkdown('```\nmake\n```')).toMatch(/^<pre><code>make/)
    expect(renderMarkdown('plain')).toBe('<p>plain</p>\n')
  })

  it('keeps line breaks', () => {
    expect(renderMarkdown('first line\nsecond line')).toMatch(/first line<br>\s*second line/)
  })

  it('links open apart and carry no referrer; a bare address becomes a link', () => {
    const h = renderMarkdown('see [the docs](https://docs.theprotocol.cloud/x) or https://example.org/y')
    expect(h).toContain('href="https://docs.theprotocol.cloud/x"')
    expect(h).toContain('target="_blank"')
    expect(h).toContain('rel="noopener noreferrer nofollow"')
    expect(h).toContain('href="https://example.org/y"')
  })

  it('an image is never fetched from a message', () => {
    expect(renderMarkdown('![x](https://example.org/a.png)')).not.toContain('<img')
  })
})

/** What the browser would build from the rendered HTML: every element, and every attribute on it. */
function built(html: string) {
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, 'text/html')
  const els = Array.from(doc.body.querySelectorAll('*'))
  return {
    tags: els.map((e) => e.tagName.toLowerCase()),
    attrs: els.flatMap((e) => Array.from(e.attributes).map((a) => [a.name.toLowerCase(), a.value.toLowerCase()])),
  }
}

describe('the sanitizer refuses HTML and script', () => {
  it.each([
    '<script>alert(1)</script>',
    '<img src=x onerror=alert(1)>',
    '<iframe src="https://example.org"></iframe>',
    '<b onclick="x()">hi</b>',
    '[click](javascript:alert(1))',
    '[data](data:text/html;base64,PHNjcmlwdD4=)',
    '<style>body{display:none}</style>',
    '<a href="javascript:alert(1)">x</a>',
    '<svg><script>alert(1)</script></svg>',
  ])('%s builds no script, no handler, no foreign element, no script link', (src) => {
    const { tags, attrs } = built(renderMarkdown(src))
    for (const bad of ['script', 'img', 'iframe', 'style', 'svg', 'object', 'embed', 'form', 'input']) {
      expect(tags).not.toContain(bad)
    }
    expect(attrs.filter(([n]) => n.startsWith('on'))).toEqual([])
    expect(attrs.filter(([n, v]) => n === 'href' && /^(javascript|data|vbscript):/.test(v))).toEqual([])
  })

  it('raw HTML shows as its text', () => {
    expect(renderMarkdown('<b>bold?</b>')).toContain('&lt;b&gt;bold?&lt;/b&gt;')
  })
})

describe('the status chips', () => {
  it.each([
    ['DONE: the sandbox roll', 'DONE', 'the sandbox roll'],
    ['[FAIL] the pair proof', 'FAIL', 'the pair proof'],
    ['REQ please review', 'REQ', 'please review'],
    ['INFO, the cut moved', 'INFO', 'the cut moved'],
    ['ORDER (x) posted', 'ORDER', '(x) posted'],
    ['ACK', 'ACK', ''],
    ['BID 15 ECU', 'BID', '15 ECU'],
  ])('%s', (body, tag, rest) => {
    expect(splitStatusTag(body)).toEqual({ tag, rest })
    expect(renderMessage(body).tag).toBe(tag)
  })

  it.each(['Done with it', 'information below', 'DONEX x', 'a DONE in the middle'])('%s carries none', (body) => {
    expect(splitStatusTag(body).tag).toBe(null)
  })
})

describe('the fold', () => {
  it('a long message folds, a short one does not', () => {
    expect(renderMessage('one\ntwo\nthree').foldable).toBe(false)
    expect(renderMessage(Array.from({ length: 12 }, (_, i) => `line ${i}`).join('\n')).foldable).toBe(true)
    expect(renderMessage('x'.repeat(900)).foldable).toBe(true)
  })
})

describe('mentions and ids', () => {
  it('a mention of the viewer stands out; another is marked; a name that names nobody stays text', () => {
    const h = renderMarkdown('@maintainer and @session-lead, not @nobody', {
      meLabels: ['maintainer'], mentionLabels: ['maintainer', 'session-lead'],
    })
    expect(h).toContain('<span class="cm-mention cm-me">@maintainer</span>')
    expect(h).toContain('<span class="cm-mention">@session-lead</span>')
    expect(h).not.toContain('>@nobody<')
  })

  it('@all names everyone', () => {
    expect(renderMarkdown('@all the roll starts', { mentionLabels: [] , meLabels: ['x'] }))
      .toContain('<span class="cm-mention cm-me">@all</span>')
  })

  it('ids and hashes are small and grey, whole on hover; inside code they stay code', () => {
    const h = renderMarkdown('approval apr_ae4e82ed28223e3a81ab88408ec69423 and sha256:5e012c1fcb84d251c6c4')
    expect(h).toContain('<span class="cm-id" title="apr_ae4e82ed28223e3a81ab88408ec69423">')
    expect(h).toContain('<span class="cm-id" title="sha256:5e012c1fcb84d251c6c4">')
    expect(renderMarkdown('`apr_ae4e82ed28223e3a`')).toContain('<code>apr_ae4e82ed28223e3a</code>')
  })
})

describe('what is for the viewer', () => {
  it('a mention the server resolved to the viewer, or @all', () => {
    expect(namesViewer({ body: 'hi', mentions: [{ key: 'dev:6' }] }, 'dev:6')).toBe(true)
    expect(namesViewer({ body: 'hi', mentions: [{ key: 'dev:7' }] }, 'dev:6')).toBe(false)
    expect(namesViewer({ body: '@everyone look', mentions: [] }, 'dev:6')).toBe(true)
    expect(namesViewer({ body: 'mail me at x@all.org', mentions: [] }, 'dev:6')).toBe(false)
  })

  it('an approval or a choice asks', () => {
    expect(isAsk({ kind: 'card', card: { type: 'approval.request' } })).toBe(true)
    expect(isAsk({ kind: 'card', card: { type: 'choice.request' } })).toBe(true)
    expect(isAsk({ kind: 'card', card: { type: 'approval.decided' } })).toBe(false)
    expect(isAsk({ kind: 'text' })).toBe(false)
  })
})

describe('a time on every message', () => {
  const now = Date.parse('2026-10-31T22:30:00Z')
  it('the time today, the date before it, the year when not this year', () => {
    const today = timeLabel('2026-10-31T20:05:00Z', now, 'en-GB')
    expect(today).toMatch(/^\d{2}:\d{2}$/)
    expect(timeLabel('2026-10-29T08:00:00Z', now, 'en-GB')).toMatch(/29 Oct \d{2}:\d{2}/)
    expect(timeLabel('2025-12-24T08:00:00Z', now, 'en-GB')).toMatch(/24 Dec 2025 \d{2}:\d{2}/)
    expect(timeLabel(null, now, 'en-GB')).toBe('')
    expect(timeLabel('not a time', now, 'en-GB')).toBe('')
  })

  it('the full time carries its zone', () => {
    expect(timeTitle('2026-10-31T20:05:00Z', 'en-GB')).toMatch(/2026/)
    expect(timeTitle('2026-10-31T20:05:00Z', 'en-GB')).toMatch(/(UTC|GMT|CET|[+-]\d)/)
  })
})
