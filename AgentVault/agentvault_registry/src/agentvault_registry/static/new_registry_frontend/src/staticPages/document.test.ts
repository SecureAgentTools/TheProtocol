/**
 * V0667 the public pages readable without JavaScript (order gwo_a9f121caa4138ec9b369814c): the static document around a rendered view
 * (staticPages/document.ts), pure.
 *   - the text a reader without JavaScript gets: tags, scripts, styles and comments out (a comment in a template is not text)
 *   - a region marked data-static="omit" (live data: counts, lists, health) never reaches a static page: a number frozen at build time
 *     reads as a fact, and an empty list as an outage
 *   - the head: the page's title and description, a canonical link to its own plain path, and the link to its live counterpart in the
 *     app; no script of any kind (a static page runs nothing)
 *   - the landing page goes INTO the app's own index.html (inside #app, where the app mounts over it), its scripts kept
 */
import { describe, expect, it } from 'vitest'
import { descriptionOf, injectLanding, omitLive, pageDocument, pageGate, pageText } from './document'

describe('the static document', () => {
  it('reads the text a reader without JavaScript gets', () => {
    const html = '<div><!-- a note --><style>.a{}</style><h1>Title</h1><script>x()</script><p>One &amp; two</p><!-- set meta --> ...</div>'
    expect(pageText(html)).toBe('Title One & two ...')
  })

  it('leaves out every region marked as live data, and only those', () => {
    const html = '<main><h1>Explore</h1><section data-static="omit"><b>1 registries</b></section><p>Discover agents.</p>' +
      '<ul data-static="omit"><li>0 services live</li></ul></main>'
    const out = omitLive(html)
    expect(pageText(out)).toBe('Explore Discover agents.')
    expect(out).not.toContain('data-static="omit"')
  })

  it('takes the description from the first paragraph long enough to say something', () => {
    expect(descriptionOf('<p>Short.</p><p>Self-assessed against ISO/IEC 42001:2023, the international standard for AI management systems.</p>'))
      .toBe('Self-assessed against ISO/IEC 42001:2023, the international standard for AI management systems.')
    expect(descriptionOf('<p>' + 'x '.repeat(200) + '</p>').length).toBeLessThanOrEqual(160)
  })

  it('builds a page with its title, description, canonical link and live counterpart, and no script', () => {
    const doc = pageDocument({ path: '/compliance/', live: 'https://theprotocol.cloud/#/compliance', title: 'Compliance framework',
      description: 'Self-assessed against ISO/IEC 42001.', body: '<h1>ISO 42001 Alignment</h1>', css: ['/assets/index-abc.css'],
      nav: [{ path: '/compliance/', title: 'Compliance framework' }, { path: '/pricing/', title: 'Pricing' }] })
    expect(doc.startsWith('<!DOCTYPE html>')).toBe(true)
    expect(doc).toContain('<title>Compliance framework · TheProtocol</title>')
    expect(doc).toContain('<meta name="description" content="Self-assessed against ISO/IEC 42001.">')
    expect(doc).toContain('<link rel="canonical" href="https://theprotocol.cloud/compliance/">')
    expect(doc).toContain('<link rel="stylesheet" href="/assets/index-abc.css">')
    expect(doc).toContain('href="https://theprotocol.cloud/#/compliance"')
    expect(doc).toContain('href="/pricing/"')
    expect(doc).toContain('<h1>ISO 42001 Alignment</h1>')
    expect(doc).not.toMatch(/<script/i)
    expect(doc).not.toMatch(/\son[a-z]+=/i)
  })

  it('escapes what goes into the head', () => {
    const doc = pageDocument({ path: '/x/', live: 'https://theprotocol.cloud/#/x', title: 'A "quoted" <title>', description: 'a & b',
      body: '', css: [], nav: [] })
    expect(doc).toContain('<title>A &quot;quoted&quot; &lt;title&gt; · TheProtocol</title>')
    expect(doc).toContain('content="a &amp; b"')
  })

  it('puts the landing page inside the app\'s own #app, keeping its scripts and head', () => {
    const index = '<!DOCTYPE html><html><head><title>TheProtocol</title><script type="module" src="/assets/index-1.js"></script></head>' +
      '<body><div id="app"></div></body></html>'
    const out = injectLanding(index, '<h1>The operating system for autonomous agents</h1>')
    expect(out).toContain('<div id="app"><h1>The operating system for autonomous agents</h1>')
    expect(out).toContain('<script type="module" src="/assets/index-1.js"></script>')
    expect(out.indexOf('</div></body>')).toBeGreaterThan(out.indexOf('autonomous agents'))
    expect(() => injectLanding('<html><body></body></html>', '<p>x</p>')).toThrow(/#app/)
    const again = injectLanding(out, '<h1>Again</h1>')                                                       // a second run replaces, never nests
    expect(pageText(again)).toBe('TheProtocol Again')
    expect(again.match(/<div id="app">/g)!.length).toBe(1)
  })

  it('gates a page on its text, its phrases and its live data, the one rule the test and the generator share', () => {
    const inst = { minText: 20, phrases: ['ISO 42001', 'not a certification'], absent: ['SERVICES LIVE'] }
    expect(pageGate('ISO 42001 Alignment: this is not a certification claim.', inst)).toEqual([])
    expect(pageGate('ISO 42001', inst)).toEqual(['9 characters, fewer than 20', 'no "not a certification"'])
    expect(pageGate('ISO 42001, not a certification. 0/4 SERVICES LIVE', inst)).toEqual(['live data "SERVICES LIVE"'])
  })
})
