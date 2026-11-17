import { describe, it, expect } from 'vitest'
import { ALLOWED_ATTR, ALLOWED_TAGS, URI_SAFE_ATTR, renderMarkdown, renderMessage } from './messageText'

/** V0662 (OurChat lane, order gwo_173e400022a85073f908044b): tables, task lists, collapsible sections and an opt-in copy
 *  button on code blocks. BASE (7a2dddb62): a table is text, `- [x]` is a bullet with brackets, `::: details` is text,
 *  and a code block is the bare `<pre><code>`. The sanitizer's allowlist grew to carry these, so most of this file is
 *  the other direction: what a message author types must never reach the page as markup. */

const noMarkup = (html: string, ...tags: string[]) => { for (const t of tags) expect(html).not.toMatch(new RegExp(`<${t}[\\s>]`, 'i')) }
/** THE TEST DOM CANNOT SANITIZE: under happy-dom (the repo's default; jsdom is not installed) DOMPurify leaves attributes it
 *  was told to drop (measured: `onclick` and `style` survive an allowlist that has neither). So the cases below assert what
 *  the PARSER does (html:false, the rules in this file): an author's markup arrives as text, and no element carries an
 *  attribute. DOMPurify's own work (style off a table cell, a handler off a tag) is checked in a real browser by
 *  scratchpad/ourchat/browser_sanitize_check.mjs, and the policy it enforces is pinned in the last describe. */
const attrsOf = (html: string): string[] => {
  const box = document.createElement('div')
  box.innerHTML = html
  return [...box.querySelectorAll('*')].flatMap((el) => [...el.attributes].map((a) => `${el.tagName.toLowerCase()}@${a.name}`))
}

describe('tables', () => {
  const t = '| name | size |\n|------|------|\n| a.png | 12 |\n| b.pdf | 340 |'

  it('render as a table, the header cells as th and the rows as td', () => {
    const h = renderMarkdown(t)
    expect(h).toMatch(/<table>/)
    expect(h.match(/<th>/g)).toHaveLength(2)
    expect(h.match(/<td>/g)).toHaveLength(4)
    expect(h).toContain('<th>name</th>')
    expect(h).toContain('<td>b.pdf</td>')
  })

  it('stay text when there is no separator row', () => {
    expect(renderMarkdown('| a | b |\n| c | d |')).not.toContain('<table')
  })

  it('keep inline markdown in a cell', () => {
    expect(renderMarkdown('| h |\n|---|\n| **bold** and `code` |')).toMatch(/<td><strong>bold<\/strong> and <code>code<\/code><\/td>/)
  })

  it('take an alignment row without error, and the style it asks for is the sanitizer\'s to drop', () => {
    const h = renderMarkdown('| a | b | c |\n|:--|:-:|--:|\n| 1 | 2 | 3 |')
    expect(h).toContain('<table>')
    expect(h.match(/<th[\s>]/g)).toHaveLength(3)
  })

  it('carry no markup a cell\'s text types', () => {
    const h = renderMarkdown('| h |\n|---|\n| <script>alert(1)</script> |\n| <img src=x onerror=alert(2)> |')
    noMarkup(h, 'script', 'img')
    expect(h).toContain('&lt;script&gt;')
  })

  it('make no link of a script address a cell names: it stays visible text', () => {
    const h = renderMarkdown('| h |\n|---|\n| [x](javascript:alert(1)) |')
    noMarkup(h, 'a')
    expect(attrsOf(h)).not.toContain('a@href')
  })
})

describe('task lists', () => {
  it('draw a box for each item, done or open, and take the marker out of the text', () => {
    const h = renderMarkdown('- [ ] write it\n- [x] test it\n- [X] ship it')
    expect(h.match(/cm-task cm-task-open/g)).toHaveLength(1)
    expect(h.match(/cm-task cm-task-done/g)).toHaveLength(2)
    expect(h).toContain('write it')
    expect(h).not.toContain('[ ]')
    expect(h).not.toContain('[x]')
    expect(h).not.toContain('[X]')
  })

  it('say done or to do to a screen reader, and use no input element', () => {
    const h = renderMarkdown('- [x] a\n- [ ] b')
    expect(h).toContain('<span class="cm-sr">done</span>')
    expect(h).toContain('<span class="cm-sr">to do</span>')
    noMarkup(h, 'input')
  })

  it('mark the list item, so the bullet can come off', () => {
    expect(renderMarkdown('- [x] a')).toMatch(/<li class="cm-task-item">/)
  })

  it('work in an ordered list and in a nested one', () => {
    expect(renderMarkdown('1. [x] a\n2. [ ] b').match(/cm-task /g)).toHaveLength(2)
    expect(renderMarkdown('- parent\n  - [x] child').match(/cm-task-done/g)).toHaveLength(1)
  })

  it('leave brackets that are not a marker alone', () => {
    for (const body of ['- see [x] later', '- [] empty', '- [xx] two', '- [x]no space', 'plain [x] text', '[x] not in a list']) {
      expect(renderMarkdown(body)).not.toContain('cm-task')
    }
  })

  it('leave brackets inside code alone', () => {
    expect(renderMarkdown('- `[x] a`')).not.toContain('cm-task')
    expect(renderMarkdown('```\n- [x] a\n```')).not.toContain('cm-task')
  })

  it('take a marker with nothing after it', () => {
    expect(renderMarkdown('- [x]')).toContain('cm-task-done')
  })
})

describe('collapsible sections', () => {
  it('open as details with the summary, closed, and hold markdown inside', () => {
    const h = renderMarkdown('::: details Why this way\nBecause **reasons**.\n:::')
    expect(h).toContain('<details class="cm-details"><summary>Why this way</summary>')
    expect(h).toContain('<strong>reasons</strong>')
    expect(h).toContain('</details>')
    expect(h).not.toMatch(/<details[^>]*\sopen/)
  })

  it('say "Details" when no summary is given', () => {
    expect(renderMarkdown('::: details\nx\n:::')).toContain('<summary>Details</summary>')
  })

  it('close themselves at the end of the message when left open', () => {
    const h = renderMarkdown('::: details Open ended\nstill here')
    expect(h).toContain('<details')
    expect(h).toContain('</details>')
  })

  it('are only details: another container name is text', () => {
    const h = renderMarkdown('::: warning\nx\n:::')
    expect(h).not.toContain('<details')
    expect(h).not.toContain('<div')
  })

  it('carry no markup the summary types', () => {
    const h = renderMarkdown('::: details <img src=x onerror=alert(1)> and <b>bold</b>\nx\n:::')
    noMarkup(h, 'img', 'b')
    expect(h).toContain('&lt;img')
  })

  it('cannot be given an attribute: a broken opening line is text, and no element carries a handler', () => {
    const h = renderMarkdown('::: details" onclick="alert(1)\nx\n:::')
    expect(h).not.toContain('<details')
    expect(attrsOf(h).filter((a) => /@on/.test(a))).toEqual([])
  })
})

describe('code blocks', () => {
  it('are the bare block they always were, unless a copy label is passed', () => {
    expect(renderMarkdown('```js\nlet a = 1\n```')).toMatch(/^<pre><code class="language-js">let a = 1\n<\/code><\/pre>/)
    expect(renderMarkdown('    indented')).toMatch(/^<pre><code>indented\n<\/code><\/pre>/)
    noMarkup(renderMarkdown('```\nx\n```'), 'button', 'div')
  })

  it('get a language, a copy button and a wrapper when a label is passed', () => {
    const h = renderMarkdown('```bash\nmake test\n```', { copyLabel: 'Copy' })
    expect(h).toContain('<div class="cm-code">')
    expect(h).toContain('<span class="cm-code-lang">bash</span>')
    expect(h).toContain('<button type="button" class="cm-copy">Copy</button>')
    expect(h).toMatch(/<pre><code class="language-bash">make test\n<\/code><\/pre>/)
  })

  it('wrap an indented block too, with no language', () => {
    const h = renderMarkdown('    run this', { copyLabel: 'Copy' })
    expect(h).toContain('<button type="button" class="cm-copy">Copy</button>')
    expect(h).not.toContain('cm-code-lang')
  })

  it('leave inline code and a block without a label unwrapped', () => {
    expect(renderMarkdown('use `make`', { copyLabel: 'Copy' })).not.toContain('<button')
  })

  it('keep the code itself escaped', () => {
    const h = renderMarkdown('```\n<script>alert(1)</script>\n```', { copyLabel: 'Copy' })
    noMarkup(h, 'script')
    expect(h).toContain('&lt;script&gt;')
  })

  it('cut a language name to what a language name is made of: no quote can leave the attribute', () => {
    const h = renderMarkdown('```js"onmouseover="alert(1)\nx\n```', { copyLabel: 'Copy' })
    expect(attrsOf(h).filter((a) => /@on/.test(a))).toEqual([])
    expect(h).not.toContain('"onmouseover')
    expect(h.match(/class="language-[a-z0-9+#._-]{0,20}"/)).not.toBeNull()
  })

  it('keep a language name at twenty characters at most', () => {
    const h = renderMarkdown('```' + 'a'.repeat(60) + '\nx\n```', { copyLabel: 'Copy' })
    expect(h).toContain('language-' + 'a'.repeat(20) + '"')
    expect(h).not.toContain('a'.repeat(21))
  })

  it('carry no markup the label types', () => {
    const h = renderMarkdown('```\nx\n```', { copyLabel: '<img src=x onerror=alert(1)>' })
    noMarkup(h, 'img')
  })
})

describe('what a message author still cannot type', () => {
  it('raw HTML stays text, the new tags included', () => {
    for (const raw of ['<details open onclick="alert(1)">x</details>', '<button onclick="alert(1)">go</button>',
      '<table><tr><td>x</td></tr></table>', '<div class="cm-code">x</div>', '<summary>x</summary>']) {
      const h = renderMarkdown(raw)
      noMarkup(h, 'details', 'button', 'table', 'div', 'summary', 'tr', 'td')
      expect(h).toContain('&lt;')
    }
  })

  it('a message cannot write the class of a drawn box or a copy button', () => {
    const h = renderMarkdown('<span class="cm-task cm-task-done">x</span>')
    expect(h).not.toMatch(/<span class="cm-task/)
  })
})

describe('the message as a whole', () => {
  it('folds a long table the way it folds long text', () => {
    const rows = Array.from({ length: 12 }, (_, i) => `| r${i} | ${i} |`).join('\n')
    expect(renderMessage('| a | b |\n|---|---|\n' + rows).foldable).toBe(true)
  })

  it('still marks a mention beside a table', () => {
    const h = renderMessage('@lead see\n\n| a |\n|---|\n| 1 |', { mentionLabels: ['lead'] }).html
    expect(h).toContain('cm-mention')
    expect(h).toContain('<table>')
  })

  it('a status tag still opens a message that carries a table', () => {
    const r = renderMessage('DONE: results\n\n| a |\n|---|\n| 1 |')
    expect(r.tag).toBe('DONE')
    expect(r.html).toContain('<table>')
  })
})

describe('the sanitizer\'s policy, pinned', () => {
  it('has no way to carry a script, an embed, a form control, an image or a style', () => {
    for (const bad of ['script', 'style', 'iframe', 'object', 'embed', 'img', 'svg', 'math', 'form', 'input', 'textarea',
      'select', 'option', 'link', 'meta', 'base', 'video', 'audio', 'source', 'frame', 'frameset', 'applet']) {
      expect(ALLOWED_TAGS).not.toContain(bad)
    }
  })

  it('has no attribute that loads a resource, submits a form or runs code', () => {
    for (const bad of ['style', 'src', 'srcset', 'action', 'formaction', 'background', 'data', 'srcdoc', 'poster', 'ping', 'xlink:href']) {
      expect(ALLOWED_ATTR).not.toContain(bad)
    }
    expect(ALLOWED_ATTR.filter((a) => /^on/i.test(a))).toEqual([])
  })

  it('has exactly the tags this lane added and nothing it did not name', () => {
    const base = ['p', 'br', 'strong', 'em', 'del', 's', 'code', 'pre', 'ul', 'ol', 'li', 'a', 'blockquote', 'hr',
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'span']
    const added = ['table', 'thead', 'tbody', 'tr', 'th', 'td', 'details', 'summary', 'div', 'button']
    expect([...ALLOWED_TAGS].sort()).toEqual([...base, ...added].sort())
    expect([...ALLOWED_ATTR].sort()).toEqual(['class', 'href', 'rel', 'start', 'target', 'title', 'type'])
  })

  it('does not judge the attributes the renderer itself writes as if they were addresses', () => {
    // a real browser tests the value of every attribute not named here against the address rule: `type="button"` fails it
    // and was dropped (seen in Chromium: a button with no type is a submit button). target and rel were the same case.
    expect([...URI_SAFE_ATTR].sort()).toEqual(['rel', 'target', 'type'])
  })
})
