/**
 * The DOM half of an explorable architecture figure (the static half, and the
 * archmap format, are in archmap.ts).
 *
 * After Mermaid has drawn a figure's SVG, `enhanceArchFigures` finds each
 * component in it by Mermaid's own id conventions and makes it a control:
 * focusable, clickable, named for screen readers, with a native tooltip. One
 * small state per figure (a layer, a selected component, a walkthrough step)
 * decides what is lit and what is dimmed; every change goes through
 * `applyArchState`, so the diagram, the legend, the chips, the detail panel and
 * the narration can never disagree with each other.
 *
 * Nothing here builds HTML from strings: text goes in through textContent, and
 * the only links are the `/docs/NN` hrefs the parser already validated.
 */

import {
  chapterOf,
  DEFAULT_ARCH_LABELS,
  edgeEnds,
  nodeIdFromDomId,
  type ArchLabels,
  type Archmap,
  type ArchNode,
} from './archmap'

const SVG_NS = 'http://www.w3.org/2000/svg'

export interface ArchState {
  layer: string
  node: string | null
  /** 0 = the walkthrough is not running; 1..N = the step on screen. */
  step: number
}

export interface EnhanceOptions {
  prefix: string
  labels?: ArchLabels
  /** The Expand button: hands over the figure's SVG markup and its map. */
  onExpand?: (svgMarkup: string, map: Archmap) => void
}

export function readArchmap(fig: Element): Archmap | null {
  const raw = fig.getAttribute('data-arch-json')
  if (!raw) return null
  try {
    const m = JSON.parse(raw) as Archmap
    return m && Array.isArray(m.nodes) ? m : null
  } catch {
    return null
  }
}

/**
 * Mark every component, edge and message of a rendered diagram. Returns how many
 * components it found, so a caller (and a test) can tell a diagram whose ids
 * matched from one whose ids did not.
 */
export function decorateArchSvg(svg: Element, map: Archmap, dir = 'TB'): number {
  const byId = new Map(map.nodes.map((n) => [n.id, n]))
  let found = 0
  // The drawing itself is not a stop: Chrome makes an overflow-hidden <svg> a keyboard-focusable
  // scroller once most of its children leave the tab order, so Tab met a blank stop before the
  // diagram's one real one. The components are the controls.
  svg.setAttribute('tabindex', '-1')
  const mark = (el: Element, n: ArchNode, focusable: boolean) => {
    el.setAttribute('data-arch-node', n.id)
    el.classList.add('arch-node')
    if (focusable) {
      el.setAttribute('tabindex', '-1')
      el.setAttribute('role', 'button')
      el.setAttribute('aria-label', `${n.title}: ${n.purpose}`)
    }
    if (!Array.from(el.children).some((c) => c.localName === 'title')) {
      const t = el.ownerDocument.createElementNS(SVG_NS, 'title')
      t.textContent = `${n.title}: ${n.purpose}`
      el.insertBefore(t, el.firstChild)
    }
  }

  if (map.kind === 'sequence') {
    const seen = new Set<string>()
    svg.querySelectorAll('[data-et="participant"]').forEach((el) => {
      const n = byId.get(el.getAttribute('data-id') || '')
      if (!n) return
      mark(el, n, !seen.has(n.id))
      if (!seen.has(n.id)) found++
      seen.add(n.id)
    })
    const lines = svg.querySelectorAll('[data-et="message"]')
    lines.forEach((el, i) => {
      el.setAttribute('data-arch-msg', String(i + 1))
      el.setAttribute('data-arch-from', el.getAttribute('data-from') || '')
      el.setAttribute('data-arch-to', el.getAttribute('data-to') || '')
    })
    const texts = svg.querySelectorAll('text.messageText')
    if (texts.length === lines.length) texts.forEach((el, i) => el.setAttribute('data-arch-msg', String(i + 1)))
    svg.querySelectorAll('text.sequenceNumber').forEach((el) => {
      const k = (el.textContent || '').trim()
      if (/^\d+$/.test(k)) el.setAttribute('data-arch-msg', k)
    })
    rovingStart(svg, 'LR')
    return found
  }

  svg.querySelectorAll('g.node').forEach((el) => {
    const n = byId.get(nodeIdFromDomId(el.getAttribute('id')) || '')
    if (!n) return
    mark(el, n, true)
    found++
  })
  svg.querySelectorAll('[data-edge="true"]').forEach((el) => {
    if (el.classList.contains('edge-thickness-invisible')) return // a layout hint, not a connection
    const ends = edgeEnds(el.getAttribute('data-id'))
    if (!ends) return
    el.setAttribute('data-arch-from', ends[0])
    el.setAttribute('data-arch-to', ends[1])
  })
  svg.querySelectorAll('g.edgeLabel').forEach((el) => {
    const ends = edgeEnds(el.querySelector('[data-id]')?.getAttribute('data-id'))
    if (!ends) return
    el.setAttribute('data-arch-from', ends[0])
    el.setAttribute('data-arch-to', ends[1])
  })
  rovingStart(svg, dir)
  return found
}

/** Where a component sits: its box on screen when there is one, else Mermaid's own translate. */
function nodePos(el: Element): [number, number] {
  const r = (el as SVGGraphicsElement).getBoundingClientRect?.()
  if (r && (r.width || r.height)) return [r.left + r.width / 2, r.top + r.height / 2]
  const m = (el.getAttribute('transform') || '').match(/translate\(\s*(-?[\d.]+)[\s,]+(-?[\d.]+)/)
  if (m) return [Number(m[1]), Number(m[2])]
  const x = Number(el.getAttribute('x'))
  return [Number.isNaN(x) ? 0 : x, 0]
}

/**
 * The focusable components of a diagram in the order it reads: column by column for a
 * left-to-right flow, row by row for a top-to-bottom one. Components within a few pixels of
 * the same rank share it, so a rank reads as one line.
 */
export function readingOrder(svg: Element, dir = 'TB'): Element[] {
  const els = Array.from(svg.querySelectorAll('[data-arch-node][role="button"]'))
  const across = dir === 'LR' || dir === 'RL'
  const flip = dir === 'RL' || dir === 'BT' ? -1 : 1
  const rank = (v: number) => Math.round(v / 12)
  return els
    .map((el, i) => ({ el, i, p: nodePos(el) }))
    .sort((a, b) => {
      const [pa, sa] = across ? [a.p[0], a.p[1]] : [a.p[1], a.p[0]]
      const [pb, sb] = across ? [b.p[0], b.p[1]] : [b.p[1], b.p[0]]
      return flip * (rank(pa) - rank(pb)) || sa - sb || a.i - b.i
    })
    .map((x) => x.el)
}

/** One tab stop per diagram: the first component in reading order. */
function rovingStart(svg: Element, dir: string) {
  const order = readingOrder(svg, dir)
  order.forEach((el, i) => el.setAttribute('tabindex', i === 0 ? '0' : '-1'))
}

/** Make `el` the diagram's one tab stop. */
function rovingSet(svg: Element, el: Element) {
  svg.querySelectorAll('[data-arch-node][role="button"]').forEach((x) => x.setAttribute('tabindex', x === el ? '0' : '-1'))
}

/** Move the diagram's tab stop to `el` and focus it. */
export function rovingFocus(svg: Element, el: Element) {
  rovingSet(svg, el)
  ;(el as HTMLElement).focus?.()
}

/** Below this drawn-to-natural size a diagram's words are too small to read or to tap. */
export const TINY_SCALE = 0.45

/** How large the diagram is drawn relative to its natural size (1 when it cannot tell). */
export function drawnScale(svg: Element): number {
  const vb = (svg.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number)
  const w = (svg as SVGGraphicsElement).getBoundingClientRect?.().width || 0
  return vb.length === 4 && vb[2] > 0 && w > 0 ? w / vb[2] : 1
}

function toggle(el: Element, cls: string, on: boolean) {
  if (on) el.classList.add(cls)
  else el.classList.remove(cls)
}

/** Which components and messages the state lights up (null = nothing is focused). */
export function litSet(map: Archmap, st: ArchState): { nodes: Set<string>; messages: Set<number> } | null {
  if (st.step > 0) {
    const s = map.steps[st.step - 1]
    if (!s) return null
    return { nodes: new Set(s.nodes), messages: new Set(s.messages) }
  }
  if (st.node) return { nodes: new Set([st.node]), messages: new Set() }
  if (st.layer) {
    const l = map.layers.find((x) => x.id === st.layer)
    if (l) return { nodes: new Set(l.nodes), messages: new Set() }
  }
  return null
}

export function applyArchState(fig: Element, map: Archmap, st: ArchState, p: string, labels: ArchLabels): void {
  const lit = litSet(map, st)
  const svg = fig.querySelector(`.${p}-mermaid svg`)
  const doc = fig.ownerDocument

  if (svg) {
    // Edges (flow) and messages (sequence) light up by what they connect.
    const edgeLit = (from: string, to: string): boolean => {
      if (!lit) return false
      if (st.step > 0 || (st.layer && !st.node)) return lit.nodes.has(from) && lit.nodes.has(to)
      return from === st.node || to === st.node
    }
    const neighbours = new Set<string>()
    svg.querySelectorAll('[data-arch-from]').forEach((el) => {
      const from = el.getAttribute('data-arch-from') || ''
      const to = el.getAttribute('data-arch-to') || ''
      const msg = Number(el.getAttribute('data-arch-msg') || 0)
      let on: boolean
      if (msg && lit && st.step > 0) on = lit.messages.has(msg)
      else if (msg && lit && st.node) on = from === st.node || to === st.node
      else on = edgeLit(from, to)
      if (on && st.node) {
        neighbours.add(from)
        neighbours.add(to)
      }
      toggle(el, 'arch-hot', !!lit && on)
      toggle(el, 'arch-dim', !!lit && !on)
    })
    svg.querySelectorAll('text[data-arch-msg]:not([data-arch-from])').forEach((el) => {
      const on = !!lit && lit.messages.has(Number(el.getAttribute('data-arch-msg')))
      toggle(el, 'arch-hot', on)
      toggle(el, 'arch-dim', !!lit && st.step > 0 && !on)
    })
    // In a step, the participants a lit message joins are part of the step too.
    const stepPeers = new Set<string>()
    if (lit && st.step > 0) {
      svg.querySelectorAll('[data-arch-msg][data-arch-from]').forEach((el) => {
        if (lit.messages.has(Number(el.getAttribute('data-arch-msg')))) {
          stepPeers.add(el.getAttribute('data-arch-from') || '')
          stepPeers.add(el.getAttribute('data-arch-to') || '')
        }
      })
    }
    svg.querySelectorAll('[data-arch-node]').forEach((el) => {
      const id = el.getAttribute('data-arch-node') || ''
      const on = !!lit && (lit.nodes.has(id) || stepPeers.has(id) || neighbours.has(id))
      toggle(el, 'arch-selected', st.node === id)
      toggle(el, 'arch-hot', on)
      toggle(el, 'arch-dim', !!lit && !on)
    })
  }

  // Legend
  fig.querySelectorAll(`.${p}-arch-item[data-arch-node]`).forEach((el) => {
    const id = el.getAttribute('data-arch-node') || ''
    toggle(el, 'is-selected', st.node === id)
    toggle(el, 'is-dim', !!lit && !lit.nodes.has(id))
    el.setAttribute('aria-pressed', st.node === id ? 'true' : 'false')
  })

  // Layer chips
  fig.querySelectorAll(`.${p}-arch-chip`).forEach((el) => {
    const on = (el.getAttribute('data-arch-layer') || '') === st.layer
    toggle(el, 'is-on', on)
    el.setAttribute('aria-pressed', on ? 'true' : 'false')
  })

  // Detail panel
  const detail = fig.querySelector(`.${p}-arch-detail`)
  if (detail) {
    detail.replaceChildren()
    const n = st.node ? map.nodes.find((x) => x.id === st.node) : null
    if (n) {
      const h = doc.createElement('p')
      h.className = `${p}-arch-detail-title`
      h.textContent = n.title
      const body = doc.createElement('p')
      body.className = `${p}-arch-detail-purpose`
      body.textContent = n.purpose
      detail.append(h, body)
      if (n.href) {
        const a = doc.createElement('a')
        a.className = `${p}-arch-read`
        a.setAttribute('href', n.href)
        a.textContent = `${labels.read} ${chapterOf(n.href)} →`
        detail.append(a)
      }
      toggle(detail, 'is-active', true)
    } else {
      const idle = doc.createElement('p')
      idle.className = `${p}-arch-detail-idle`
      idle.textContent = labels.select
      detail.append(idle)
      toggle(detail, 'is-active', false)
    }
  }

  // The card beside the component itself; the panel above then only speaks to screen readers.
  const box = fig.querySelector(`.${p}-mermaid`) as HTMLElement | null
  const tiny = fig.classList.contains('is-tiny')
  const popped = box ? placePop(box, svg, map, tiny ? { ...st, node: null } : st, p, labels) : false
  if (detail) toggle(detail, 'has-pop', popped)

  // Walkthrough
  const stepper = fig.querySelector(`.${p}-arch-stepper`)
  if (stepper && map.steps.length) {
    const count = stepper.querySelector(`.${p}-arch-step-count`)
    if (count) count.textContent = `${labels.step} ${st.step} ${labels.of} ${map.steps.length}`
    const prev = stepper.querySelector('[data-arch-action="prev"]') as HTMLButtonElement | null
    const next = stepper.querySelector('[data-arch-action="next"]') as HTMLButtonElement | null
    if (prev) prev.disabled = st.step <= 1
    if (next) next.disabled = st.step >= map.steps.length
    const narr = stepper.querySelector(`.${p}-arch-narration`)
    if (narr) {
      narr.replaceChildren()
      const s = st.step > 0 ? map.steps[st.step - 1] : null
      if (s) {
        const t = doc.createElement('strong')
        t.className = `${p}-arch-narration-title`
        t.textContent = `${s.n}. ${s.title}`
        const b = doc.createElement('span')
        b.className = `${p}-arch-narration-text`
        b.textContent = s.text
        narr.append(t, b)
      } else {
        const idle = doc.createElement('span')
        idle.className = `${p}-arch-narration-idle`
        idle.textContent = labels.start
        narr.append(idle)
      }
    }
    toggle(stepper, 'is-running', st.step > 0)
  }
  toggle(fig, 'arch-focused', !!lit)
}

/**
 * Show (or hide) the card next to the selected component, inside the diagram's own box.
 * Below the component when it fits, above it when it does not, never outside the box.
 * Returns whether a card is showing.
 */
export function placePop(box: HTMLElement, svg: Element | null, map: Archmap, st: ArchState, p: string, labels: ArchLabels): boolean {
  const doc = box.ownerDocument
  let pop = Array.from(box.children).find((c) => c.classList.contains(`${p}-arch-pop`)) as HTMLElement | undefined
  const n = st.node ? map.nodes.find((x) => x.id === st.node) : null
  const target = n && svg ? svg.querySelector(`[data-arch-node="${n.id}"]`) : null
  if (!n || !target) {
    if (pop) pop.hidden = true
    return false
  }
  if (!pop) {
    pop = doc.createElement('div')
    pop.className = `${p}-arch-pop`
    pop.setAttribute('role', 'note')
    box.appendChild(pop)
  }
  pop.replaceChildren()
  const close = doc.createElement('button')
  close.type = 'button'
  close.className = `${p}-arch-pop-close`
  close.setAttribute('data-arch-action', 'clear')
  close.setAttribute('aria-label', labels.close)
  close.textContent = '×'
  const title = doc.createElement('p')
  title.className = `${p}-arch-pop-title`
  title.textContent = n.title
  const body = doc.createElement('p')
  body.className = `${p}-arch-pop-purpose`
  body.textContent = n.purpose
  pop.append(close, title, body)
  if (n.href) {
    const a = doc.createElement('a')
    a.className = `${p}-arch-read`
    a.setAttribute('href', n.href)
    a.textContent = `${labels.read} ${chapterOf(n.href)} →`
    pop.append(a)
  }
  pop.hidden = false
  const b = box.getBoundingClientRect()
  const r = target.getBoundingClientRect()
  const w = pop.offsetWidth || 340
  const h = pop.offsetHeight || 120
  let left = r.left - b.left + box.scrollLeft + r.width / 2 - w / 2
  left = Math.max(8, Math.min(left, box.scrollWidth - w - 8))
  let top = r.bottom - b.top + box.scrollTop + 10
  const above = r.top - b.top + box.scrollTop - h - 10
  if (top + h > box.scrollHeight - 8 && above > 8) top = above
  pop.style.left = `${Math.round(left)}px`
  pop.style.top = `${Math.round(top)}px`
  return true
}

/** The next state for one user action; pure, so every transition is testable. */
export function archReduce(map: Archmap, st: ArchState, action:
  | { type: 'layer'; id: string }
  | { type: 'node'; id: string }
  | { type: 'clear' }
  | { type: 'next' } | { type: 'prev' } | { type: 'reset' }
): ArchState {
  switch (action.type) {
    case 'layer':
      return { layer: st.layer === action.id ? '' : action.id, node: null, step: 0 }
    case 'node':
      if (!map.nodes.some((n) => n.id === action.id)) return st
      return { layer: '', node: st.node === action.id ? null : action.id, step: 0 }
    case 'clear':
      return { layer: '', node: null, step: 0 }
    case 'next':
      return { layer: '', node: null, step: Math.min(map.steps.length, st.step + 1) }
    case 'prev':
      return { layer: '', node: null, step: Math.max(map.steps.length ? 1 : 0, st.step - 1) }
    case 'reset':
      return { layer: '', node: null, step: 0 }
  }
}

/**
 * Wire every not-yet-wired figure under `root`. A figure whose SVG is not drawn
 * yet is left alone (and left un-marked), so calling this again after a late
 * Mermaid run finishes the job. Returns a cleanup that removes every listener.
 */
export function enhanceArchFigures(root: ParentNode, opts: EnhanceOptions): () => void {
  const p = opts.prefix
  const labels = opts.labels ?? DEFAULT_ARCH_LABELS
  const controllers: AbortController[] = []
  const wired: Element[] = []

  root.querySelectorAll(`figure.${p}-archfig[data-arch-json]`).forEach((fig) => {
    if (fig.getAttribute('data-arch-ready') === '1') return
    const map = readArchmap(fig)
    const svg = fig.querySelector(`.${p}-mermaid svg`)
    if (!map || !svg) return
    const dir = fig.getAttribute('data-arch-dir') || 'TB'
    decorateArchSvg(svg, map, dir)
    let st: ArchState = { layer: '', node: null, step: 0 }
    const set = (next: ArchState) => {
      st = next
      applyArchState(fig, map, st, p, labels)
    }
    const ctl = new AbortController()
    controllers.push(ctl)

    fig.addEventListener(
      'click',
      (e) => {
        const t = e.target as Element | null
        if (!t || t.closest('a')) return // links route through the view
        const chip = t.closest(`.${p}-arch-chip`)
        if (chip) return set(archReduce(map, st, { type: 'layer', id: chip.getAttribute('data-arch-layer') || '' }))
        const action = t.closest('[data-arch-action]')?.getAttribute('data-arch-action')
        if (action === 'expand') {
          opts.onExpand?.(svg.outerHTML, map)
          return
        }
        if (action === 'next' || action === 'prev' || action === 'reset') return set(archReduce(map, st, { type: action }))
        if (action === 'clear') return set(archReduce(map, st, { type: 'clear' }))
        if (t.closest(`.${p}-arch-pop`)) return // reading the card is not a click on the diagram
        // A diagram drawn too small to read opens full screen, where it can be read and tapped.
        if (fig.classList.contains('is-tiny') && t.closest(`.${p}-mermaid`)) {
          opts.onExpand?.(svg.outerHTML, map)
          return
        }
        const item = t.closest(`.${p}-arch-item[data-arch-node]`)
        if (item) {
          set(archReduce(map, st, { type: 'node', id: item.getAttribute('data-arch-node') || '' }))
          const box = fig.querySelector(`.${p}-mermaid`) as HTMLElement | null
          box?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
          return
        }
        const node = t.closest('[data-arch-node]')
        if (node && svg.contains(node)) return set(archReduce(map, st, { type: 'node', id: node.getAttribute('data-arch-node') || '' }))
        if (t.closest(`.${p}-mermaid`)) set(archReduce(map, st, { type: 'clear' }))
      },
      { signal: ctl.signal }
    )

    fig.addEventListener(
      'keydown',
      (e) => {
        const ev = e as KeyboardEvent
        const t = ev.target as Element | null
        if (!t) return
        if (ev.key === 'Escape' && (st.node || st.layer || st.step)) {
          ev.preventDefault()
          return set(archReduce(map, st, { type: 'clear' }))
        }
        const node = t.closest('[data-arch-node]')
        if (node && svg.contains(node) && (ev.key === 'Enter' || ev.key === ' ')) {
          ev.preventDefault()
          return set(archReduce(map, st, { type: 'node', id: node.getAttribute('data-arch-node') || '' }))
        }
        // Inside a diagram the arrows walk its components in reading order; Tab leaves it.
        const walk: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }
        if (node && svg.contains(node) && (ev.key in walk || ev.key === 'Home' || ev.key === 'End')) {
          const order = readingOrder(svg, dir)
          const i = order.indexOf(node)
          if (i < 0 || !order.length) return
          ev.preventDefault()
          const j = ev.key === 'Home' ? 0 : ev.key === 'End' ? order.length - 1 : Math.min(order.length - 1, Math.max(0, i + walk[ev.key]))
          return rovingFocus(svg, order[j])
        }
        if (t.closest(`.${p}-arch-stepper`) && (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft')) {
          ev.preventDefault()
          set(archReduce(map, st, { type: ev.key === 'ArrowRight' ? 'next' : 'prev' }))
        }
      },
      { signal: ctl.signal }
    )

    // Whichever component takes focus (a click, a screen reader) becomes the diagram's tab stop.
    svg.addEventListener(
      'focusin',
      (e) => {
        const node = (e.target as Element | null)?.closest?.('[data-arch-node][role="button"]')
        if (node && svg.contains(node)) rovingSet(svg, node)
      },
      { signal: ctl.signal }
    )

    // Too small to read (a phone): the diagram becomes one door to the full-screen view.
    const measure = () => {
      const tiny = drawnScale(svg) < TINY_SCALE
      if (tiny !== fig.classList.contains('is-tiny')) {
        toggle(fig, 'is-tiny', tiny)
        applyArchState(fig, map, st, p, labels)
      }
    }
    measure()
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(() => measure())
      ro.observe(fig)
      ctl.signal.addEventListener('abort', () => ro.disconnect())
    }

    applyArchState(fig, map, st, p, labels)
    fig.setAttribute('data-arch-ready', '1')
    wired.push(fig)
  })

  // Unwire what this call wired, and say so on the figure, so a later call wires it again
  // instead of skipping a figure whose listeners are gone.
  return () => {
    controllers.forEach((c) => c.abort())
    wired.forEach((f) => f.removeAttribute('data-arch-ready'))
  }
}
