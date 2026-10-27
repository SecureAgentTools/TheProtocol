/**
 * §FESUITE V0600: a diagram is laid out OFF the page and written only into an element still in the document. V0599's
 * proof on sbxbetaop logged `<g> attribute transform: Expected number, "translate(undefined, NaN)"` on /operator-docs/02:
 * chapter 01's diagram laid out by mermaid.run inside the docs' article while it was not displayed (between chapters).
 * Reproduced in a real browser with mermaid 12 (run() in a display:none container: that exact console error; render()
 * with no container: a clean diagram). RED on fe/batch-v0599 (mermaid.run({ nodes }) with the element as the layout
 * container; no dedentDiagram).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const calls: Array<{ id: string, code: string, container: unknown }> = []
let onRender: (() => void) | null = null
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    run: vi.fn(async () => { throw new Error('run must not be used: it lays a diagram out inside the given element') }),
    render: vi.fn(async (id: string, code: string, container?: unknown) => {
      calls.push({ id, code, container })
      onRender?.()
      return { svg: `<svg id="${id}"><g transform="translate(1, 2)"></g></svg>`, bindFunctions: vi.fn() }
    }),
  },
}))

import { dedentDiagram, LABEL_TYPE_RESET, renderMermaidDiagrams } from './useMermaidRenderer'

function diagram(code: string, cls = 'opd-mermaid'): HTMLElement {
  const pre = document.createElement('pre')
  pre.className = cls
  pre.textContent = code
  document.body.appendChild(pre)
  return pre
}

describe('mermaid diagrams render off the page', () => {
  beforeEach(() => { calls.length = 0; onRender = null; document.body.innerHTML = '' })
  afterEach(() => { document.body.innerHTML = '' })

  it('lays each diagram out with no container and writes the svg into its element', async () => {
    const a = diagram('\n    graph TD\n      A --> B\n')
    const b = diagram('sequenceDiagram\n  A->>B: hi')
    await renderMermaidDiagrams({ selector: '.opd-mermaid', theme: 'oracle' })
    expect(calls.map((c) => [c.code, c.container])).toEqual([['graph TD\n  A --> B', undefined], ['sequenceDiagram\n  A->>B: hi', undefined]])
    expect(new Set(calls.map((c) => c.id)).size).toBe(2)
    for (const el of [a, b]) {
      expect(el.getAttribute('data-processed')).toBe('true')
      expect(el.innerHTML.startsWith('<svg id="tp-mmd-')).toBe(true)
    }
  })

  it('writes nothing into an element the page swapped out while the diagram was laid out', async () => {
    const a = diagram('graph TD\n  A --> B')
    onRender = () => { a.remove() }   // Vue replaces the article while mermaid lays the diagram out
    await renderMermaidDiagrams({ selector: '.opd-mermaid', theme: 'oracle' })
    expect(calls.length).toBe(1)
    expect(a.getAttribute('data-processed')).toBeNull()
    expect(a.textContent).toBe('graph TD\n  A --> B')
  })

  it('leaves a processed diagram alone and renders a hidden one (the layout is off the page)', async () => {
    const done = diagram('graph TD\n  X --> Y')
    done.setAttribute('data-processed', 'true')
    const hidden = diagram('graph TD\n  H --> I')
    hidden.style.display = 'none'
    await renderMermaidDiagrams({ selector: '.opd-mermaid', theme: 'oracle' })
    expect(calls.map((c) => c.code)).toEqual(['graph TD\n  H --> I'])
    expect(hidden.getAttribute('data-processed')).toBe('true')
  })

  it('keeps every label in the type mermaid measured it with, whatever the page says about p (§SUITES1018)', async () => {
    // His report 2026-10-20: multi-line labels cut off in the architecture chapter. The docs' `.orc-article :deep(p)`
    // (1.1rem, line-height 1.85) grew 163 of 213 labels on chapter 35 past their boxes; the reset rides themeCSS, which
    // mermaid scopes to the diagram's id, so it outranks any view's class rule.
    const mermaid = (await import('mermaid')).default as unknown as { initialize: ReturnType<typeof vi.fn> }
    mermaid.initialize.mockClear()
    diagram('graph TD\n  A["two<br/>lines"] --> B')
    await renderMermaidDiagrams({ selector: '.opd-mermaid', theme: 'oracle' })
    const cfg = mermaid.initialize.mock.calls[0][0] as { themeCSS?: string }
    expect(cfg.themeCSS).toBe(LABEL_TYPE_RESET)
    for (const rule of ['foreignObject p', 'foreignObject span', 'foreignObject div', 'margin: 0', 'font-size: inherit',
      'line-height: 1.5', 'font-family: inherit', 'letter-spacing: normal']) expect(LABEL_TYPE_RESET).toContain(rule)
  })

  it('dedents the way mermaid reads a fence', () => {
    expect(dedentDiagram('\n\t  graph LR\n\t    A --> B\n\n')).toBe('graph LR\n  A --> B')
    expect(dedentDiagram('')).toBe('')
  })
})
