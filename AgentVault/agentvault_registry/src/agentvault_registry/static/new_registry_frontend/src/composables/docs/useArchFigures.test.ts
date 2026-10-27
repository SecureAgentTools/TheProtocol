import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest'
import MarkdownIt from 'markdown-it'
import { renderArchFigure, DEFAULT_ARCH_LABELS, type Archmap } from './archmap'

// vitest 4+ types an untyped vi.fn() as Mock<Procedure | Constructable>, which is not a callback of this shape: the
// expand handler's mock carries the signature enhanceArchFigures takes.
type OnExpand = (svgMarkup: string, map: Archmap) => void
import { enhanceArchFigures, archReduce, litSet, readArchmap } from './useArchFigures'

const esc = new MarkdownIt().utils.escapeHtml

const FLOW_MAP = `id: frame
checked: V0446 · 2026-09-25
layer money | Money | TEG GW
node TEG | TEG | Holds every balance. | /docs/02
node GW | TEG gateway | mTLS in front of the TEG. | /docs/08
node REG | Registry | Takes every request.`

// What mermaid 11 draws for a flowchart, reduced to the attributes the enhancer reads.
const FLOW_SVG = `<svg id="mermaid-7" xmlns="http://www.w3.org/2000/svg">
  <g class="node default" id="mermaid-7-flowchart-TEG-0"><rect></rect></g>
  <g class="node default" id="mermaid-7-flowchart-GW-1"><rect></rect></g>
  <g class="node default" id="mermaid-7-flowchart-REG-2"><rect></rect></g>
  <g class="node default" id="mermaid-7-flowchart-STRAY-3"><rect></rect></g>
  <path data-edge="true" data-id="L_REG_GW_0" class="flowchart-link"></path>
  <path data-edge="true" data-id="L_GW_TEG_0" class="flowchart-link"></path>
  <g class="edgeLabel"><g class="label" data-id="L_REG_GW_0"></g></g>
</svg>`

const SEQ_MAP = `id: transfer
kind: sequence
node A | Agent | Pays.
node B | Registry | Decides.
step 1 | Ask | A asks B. | m1 A
step 2 | Answer | B answers. | m2 B`

const SEQ_SVG = `<svg id="mermaid-8" xmlns="http://www.w3.org/2000/svg">
  <g data-et="participant" data-id="A"><rect></rect></g>
  <g data-et="participant" data-id="B"><rect></rect></g>
  <line data-et="message" data-id="i0" data-from="A" data-to="B"></line>
  <text class="messageText">ask</text>
  <line data-et="message" data-id="i1" data-from="B" data-to="A"></line>
  <text class="messageText">answer</text>
  <text class="sequenceNumber">1</text>
  <text class="sequenceNumber">2</text>
  <g data-et="participant" data-id="A"><rect></rect></g>
  <g data-et="participant" data-id="B"><rect></rect></g>
</svg>`

function mount(mermaidSrc: string, map: string, svg: string): HTMLElement {
  document.body.innerHTML = `<article class="orc-article">${renderArchFigure(mermaidSrc, map, 'orc', esc)}</article>`
  const box = document.querySelector('.orc-mermaid') as HTMLElement
  box.innerHTML = svg // what mermaid.run leaves behind
  box.setAttribute('data-processed', 'true')
  return document.querySelector('figure.orc-archfig') as HTMLElement
}

const q = (sel: string) => document.querySelector(sel) as Element
const node = (id: string) => q(`svg [data-arch-node="${id}"]`)
const click = (el: Element) => el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
const key = (el: Element, k: string) => el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }))

describe('a flow figure', () => {
  let onExpand: Mock<OnExpand>
  let cleanup: () => void
  beforeEach(() => {
    mount('flowchart LR\n  TEG["TEG"]', FLOW_MAP, FLOW_SVG)
    onExpand = vi.fn<OnExpand>()
    cleanup = enhanceArchFigures(document, { prefix: 'orc', onExpand })
  })

  it('turns every mapped component into a named control, and leaves strangers alone', () => {
    const teg = node('TEG')
    expect(teg).toBeTruthy()
    expect(teg.getAttribute('tabindex')).toBe('0') // the diagram's one tab stop
    expect(node('GW').getAttribute('tabindex')).toBe('-1')
    expect(node('REG').getAttribute('tabindex')).toBe('-1')
    expect(teg.getAttribute('role')).toBe('button')
    expect(teg.getAttribute('aria-label')).toBe('TEG: Holds every balance.')
    expect(teg.querySelector('title')?.textContent).toBe('TEG: Holds every balance.')
    expect(q('#mermaid-7-flowchart-STRAY-3').hasAttribute('data-arch-node')).toBe(false)
    expect(q('[data-id="L_GW_TEG_0"]').getAttribute('data-arch-from')).toBe('GW')
    expect(q('g.edgeLabel').getAttribute('data-arch-to')).toBe('GW')
    expect(q('figure').getAttribute('data-arch-ready')).toBe('1')
  })

  it('lights one layer and dims the rest, and a second press clears it', () => {
    const chip = q('[data-arch-layer="money"]')
    click(chip)
    expect(node('TEG').classList.contains('arch-hot')).toBe(true)
    expect(node('GW').classList.contains('arch-hot')).toBe(true)
    expect(node('REG').classList.contains('arch-dim')).toBe(true)
    expect(q('[data-id="L_GW_TEG_0"]').classList.contains('arch-hot')).toBe(true)
    expect(q('[data-id="L_REG_GW_0"]').classList.contains('arch-dim')).toBe(true)
    expect(chip.getAttribute('aria-pressed')).toBe('true')
    expect(q('.orc-arch-item[data-arch-node="REG"]').classList.contains('is-dim')).toBe(true)
    click(chip)
    expect(document.querySelectorAll('svg .arch-dim, svg .arch-hot')).toHaveLength(0)
    expect(q('[data-arch-layer=""]').getAttribute('aria-pressed')).toBe('true')
  })

  it('selects a component: it and its neighbours stay lit, the panel explains it', () => {
    click(node('REG'))
    expect(node('REG').classList.contains('arch-selected')).toBe(true)
    expect(node('GW').classList.contains('arch-hot')).toBe(true) // one edge away
    expect(node('TEG').classList.contains('arch-dim')).toBe(true) // two edges away
    const panel = q('.orc-arch-detail')
    expect(panel.querySelector('.orc-arch-detail-title')?.textContent).toBe('Registry')
    expect(panel.querySelector('.orc-arch-detail-purpose')?.textContent).toBe('Takes every request.')
    expect(panel.querySelector('a')).toBeNull() // REG has no chapter link
    expect(q('.orc-arch-item[data-arch-node="REG"]').getAttribute('aria-pressed')).toBe('true')
    click(node('REG'))
    expect(panel.querySelector('.orc-arch-detail-idle')?.textContent).toBe(DEFAULT_ARCH_LABELS.select)
  })

  it('shows a card beside the selected component, and its close button clears it', () => {
    click(node('TEG'))
    const pop = q('.orc-mermaid > .orc-arch-pop') as HTMLElement
    expect(pop.hidden).toBe(false)
    expect(pop.querySelector('.orc-arch-pop-title')?.textContent).toBe('TEG')
    expect(pop.querySelector('.orc-arch-pop-purpose')?.textContent).toBe('Holds every balance.')
    expect(pop.querySelector('a')?.getAttribute('href')).toBe('/docs/02')
    expect(q('.orc-arch-detail').classList.contains('has-pop')).toBe(true)
    click(pop.querySelector('.orc-arch-pop-purpose')!) // reading the card changes nothing
    expect(node('TEG').classList.contains('arch-selected')).toBe(true)
    click(pop.querySelector('.orc-arch-pop-close')!)
    expect(pop.hidden).toBe(true)
    expect(document.querySelectorAll('svg .arch-selected')).toHaveLength(0)
    expect(q('.orc-arch-detail').classList.contains('has-pop')).toBe(false)
  })

  it('reaches the same state from the keyboard and from the legend', () => {
    key(node('TEG'), 'Enter')
    expect(node('TEG').classList.contains('arch-selected')).toBe(true)
    expect(q('.orc-arch-detail a')?.getAttribute('href')).toBe('/docs/02')
    key(node('TEG'), 'Escape')
    expect(document.querySelectorAll('svg .arch-selected')).toHaveLength(0)
    click(q('.orc-arch-item[data-arch-node="GW"]'))
    expect(node('GW').classList.contains('arch-selected')).toBe(true)
  })

  it('leaves links to the view and hands Expand the SVG and the map', () => {
    click(node('TEG'))
    const link = q('.orc-arch-detail a')
    const ev = new MouseEvent('click', { bubbles: true, cancelable: true })
    link.dispatchEvent(ev)
    expect(ev.defaultPrevented).toBe(false)
    expect(node('TEG').classList.contains('arch-selected')).toBe(true) // the link click changed nothing
    click(q('[data-arch-action="expand"]'))
    expect(onExpand).toHaveBeenCalledTimes(1)
    expect(onExpand.mock.calls[0][0]).toContain('<svg')
    expect(onExpand.mock.calls[0][1].id).toBe('frame')
  })

  it('clears on a click on the empty diagram', () => {
    click(node('TEG'))
    click(q('.orc-mermaid svg'))
    expect(document.querySelectorAll('svg .arch-selected, svg .arch-dim')).toHaveLength(0)
  })

  it('is wired once, and the cleanup lets it be wired again', () => {
    enhanceArchFigures(document, { prefix: 'orc' })() // already wired: this call wires and unwires nothing
    click(q('[data-arch-layer="money"]'))
    expect(node('REG').classList.contains('arch-dim')).toBe(true) // the first wiring still answers
    click(q('[data-arch-layer="money"]'))
    cleanup()
    expect(q('figure').hasAttribute('data-arch-ready')).toBe(false)
    click(q('[data-arch-layer="money"]'))
    expect(node('REG').classList.contains('arch-dim')).toBe(false) // nothing listens any more
    enhanceArchFigures(document, { prefix: 'orc' })
    click(q('[data-arch-layer="money"]'))
    expect(node('REG').classList.contains('arch-dim')).toBe(true) // wired again
  })
})

describe('a sequence figure walked step by step', () => {
  beforeEach(() => {
    mount('sequenceDiagram\n  A->>B: ask', SEQ_MAP, SEQ_SVG)
    enhanceArchFigures(document, { prefix: 'orc' })
  })

  const msg = (n: number) => q(`line[data-arch-msg="${n}"]`)

  it('numbers messages, texts and badges in drawing order', () => {
    expect(msg(1).getAttribute('data-arch-from')).toBe('A')
    expect(document.querySelectorAll('text.messageText[data-arch-msg]')).toHaveLength(2)
    expect(q('text.sequenceNumber').getAttribute('data-arch-msg')).toBe('1')
    // a participant is drawn twice (top and bottom); only the first is a tab stop
    expect(document.querySelectorAll('[data-arch-node="A"][tabindex="0"]')).toHaveLength(1)
  })

  it('walks forward and back, lighting only the step', () => {
    const next = q('[data-arch-action="next"]') as HTMLButtonElement
    const prev = q('[data-arch-action="prev"]') as HTMLButtonElement
    expect(q('.orc-arch-step-count').textContent).toBe('Step 0 of 2')
    click(next)
    expect(q('.orc-arch-step-count').textContent).toBe('Step 1 of 2')
    expect(msg(1).classList.contains('arch-hot')).toBe(true)
    expect(msg(2).classList.contains('arch-dim')).toBe(true)
    expect(q('text.messageText[data-arch-msg="2"]').classList.contains('arch-dim')).toBe(true)
    expect(q('[data-arch-node="B"]').classList.contains('arch-hot')).toBe(true) // the other end of message 1
    expect(q('.orc-arch-narration-title').textContent).toBe('1. Ask')
    expect(prev.disabled).toBe(true)
    click(next)
    expect(next.disabled).toBe(true)
    expect(msg(2).classList.contains('arch-hot')).toBe(true)
    click(prev)
    expect(q('.orc-arch-step-count').textContent).toBe('Step 1 of 2')
    click(q('[data-arch-action="reset"]'))
    expect(document.querySelectorAll('svg .arch-dim, svg .arch-hot')).toHaveLength(0)
    expect(q('.orc-arch-narration-idle').textContent).toBe(DEFAULT_ARCH_LABELS.start)
  })

  it('takes the arrow keys inside the walkthrough', () => {
    key(q('[data-arch-action="next"]'), 'ArrowRight')
    expect(q('.orc-arch-step-count').textContent).toBe('Step 1 of 2')
    key(q('[data-arch-action="next"]'), 'ArrowLeft')
    expect(q('.orc-arch-step-count').textContent).toBe('Step 1 of 2') // never below step 1 while walking
  })
})

describe('the state machine', () => {
  const map = readArchmap(mount('flowchart LR', FLOW_MAP, FLOW_SVG))!
  const zero = { layer: '', node: null, step: 0 }

  it('keeps layer, selection and walkthrough mutually exclusive', () => {
    const a = archReduce(map, zero, { type: 'layer', id: 'money' })
    const b = archReduce(map, a, { type: 'node', id: 'TEG' })
    expect(b).toEqual({ layer: '', node: 'TEG', step: 0 })
    expect(archReduce(map, b, { type: 'layer', id: 'money' })).toEqual({ layer: 'money', node: null, step: 0 })
  })

  it('ignores a component the map does not know', () => {
    expect(archReduce(map, zero, { type: 'node', id: 'NOPE' })).toBe(zero)
  })

  it('lights nothing at rest', () => {
    expect(litSet(map, zero)).toBeNull()
    expect(litSet(map, { layer: 'money', node: null, step: 0 })?.nodes).toEqual(new Set(['TEG', 'GW']))
  })
})

// Positions as mermaid writes them (a translate per node), plus a layout-only invisible link.
// Read by columns the order is REG, GW, TEG; read by rows it is GW, REG, TEG.
const ROVE_SVG = `<svg id="mermaid-9" viewBox="0 0 1000 400" xmlns="http://www.w3.org/2000/svg">
  <g class="node default" id="mermaid-9-flowchart-TEG-0" transform="translate(300, 300)"><rect></rect></g>
  <g class="node default" id="mermaid-9-flowchart-REG-1" transform="translate(100, 300)"><rect></rect></g>
  <g class="node default" id="mermaid-9-flowchart-GW-2" transform="translate(300, 100)"><rect></rect></g>
  <path data-edge="true" data-id="L_REG_GW_0" class="flowchart-link"></path>
  <path data-edge="true" data-id="L_GW_TEG_0" class="edge-thickness-invisible edge-pattern-solid"></path>
</svg>`

describe('the keyboard walks a diagram in the order it reads', () => {
  it('left to right: one tab stop, the arrows move along the columns, Home and End jump', () => {
    mount('flowchart LR\n  REG --> GW', FLOW_MAP, ROVE_SVG)
    expect(q('figure').getAttribute('data-arch-dir')).toBe('LR')
    enhanceArchFigures(document, { prefix: 'orc' })
    const stops = Array.from(document.querySelectorAll('svg [data-arch-node][tabindex="0"]'))
    expect(stops.map((e) => e.getAttribute('data-arch-node'))).toEqual(['REG'])
    expect(q('.orc-mermaid svg').getAttribute('tabindex')).toBe('-1') // the drawing is not a stop of its own
    ;(node('REG') as HTMLElement).focus()
    key(node('REG'), 'ArrowRight')
    expect(document.activeElement).toBe(node('GW'))
    expect(node('GW').getAttribute('tabindex')).toBe('0')
    expect(node('REG').getAttribute('tabindex')).toBe('-1')
    key(node('GW'), 'End')
    expect(document.activeElement).toBe(node('TEG'))
    key(node('TEG'), 'ArrowRight') // the last one stays put
    expect(document.activeElement).toBe(node('TEG'))
    key(node('TEG'), 'Home')
    expect(document.activeElement).toBe(node('REG'))
  })

  it('top to bottom: row by row, left to right within a row', () => {
    mount('---\nconfig:\n  flowchart:\n    rankSpacing: 38\n---\nflowchart TB\n  REG --> GW', FLOW_MAP, ROVE_SVG)
    expect(q('figure').getAttribute('data-arch-dir')).toBe('TB')
    enhanceArchFigures(document, { prefix: 'orc' })
    const stops = Array.from(document.querySelectorAll('svg [data-arch-node][tabindex="0"]'))
    expect(stops.map((e) => e.getAttribute('data-arch-node'))).toEqual(['GW'])
    ;(node('GW') as HTMLElement).focus()
    key(node('GW'), 'ArrowDown')
    expect(document.activeElement).toBe(node('REG'))
    key(node('REG'), 'ArrowDown')
    expect(document.activeElement).toBe(node('TEG'))
    key(node('TEG'), 'ArrowUp')
    expect(document.activeElement).toBe(node('REG'))
  })

  it('an invisible link shapes the layout and is never lit', () => {
    mount('flowchart LR\n  REG --> GW', FLOW_MAP, ROVE_SVG)
    enhanceArchFigures(document, { prefix: 'orc' })
    const ghost = q('[data-id="L_GW_TEG_0"]')
    expect(ghost.hasAttribute('data-arch-from')).toBe(false)
    click(node('GW'))
    expect(ghost.classList.contains('arch-hot')).toBe(false)
    expect(q('[data-id="L_REG_GW_0"]').classList.contains('arch-hot')).toBe(true)
  })
})

describe('a diagram drawn too small to read', () => {
  let onExpand: Mock<OnExpand>
  beforeEach(() => {
    mount('flowchart LR\n  REG --> GW', FLOW_MAP, ROVE_SVG)
    const svg = q('.orc-mermaid svg') as SVGSVGElement
    // 1000 wide by its viewBox, drawn 300 wide: a phone.
    svg.getBoundingClientRect = () => ({ width: 300, height: 120, left: 0, top: 0, right: 300, bottom: 120, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect
    onExpand = vi.fn<OnExpand>()
    enhanceArchFigures(document, { prefix: 'orc', onExpand })
  })

  it('says so, and a tap anywhere on it opens the full-screen view instead of a tiny card', () => {
    expect(q('figure').classList.contains('is-tiny')).toBe(true)
    click(node('GW'))
    expect(onExpand).toHaveBeenCalledTimes(1)
    expect(node('GW').classList.contains('arch-selected')).toBe(false)
    click(q('.orc-arch-explore'))
    expect(onExpand).toHaveBeenCalledTimes(2)
  })

  it('a component chosen from the list is explained in the panel, not in a card that cannot fit', () => {
    click(q('.orc-arch-item[data-arch-node="TEG"]'))
    expect(node('TEG').classList.contains('arch-selected')).toBe(true)
    const pop = document.querySelector('.orc-mermaid > .orc-arch-pop') as HTMLElement | null
    expect(pop === null || pop.hidden).toBe(true)
    expect(q('.orc-arch-detail').classList.contains('has-pop')).toBe(false)
    expect(q('.orc-arch-detail .orc-arch-detail-title').textContent).toBe('TEG')
  })
})
