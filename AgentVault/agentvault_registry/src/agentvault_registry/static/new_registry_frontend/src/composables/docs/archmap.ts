/**
 * ARCHMAP — the metadata that turns a Mermaid diagram into an explorable one.
 *
 * A chapter writes the diagram as an ordinary ```mermaid fence (so every other
 * renderer, the public docs site included, draws it unchanged) and puts an
 * ```archmap fence directly after it. The archmap names each component of the
 * diagram with a one-line purpose and a chapter to read next, groups components
 * into layers, and, for a sequence diagram, narrates it as numbered steps:
 *
 *   id: frame
 *   title: Inside one sovereign frame
 *   kind: flow                                   (flow | sequence, default flow)
 *   checked: V0446 · 2026-09-25                  (the release the view was checked against)
 *   layer money | Money | TEG GWTEG TEGDB
 *   node TEG | TEG | Holds every balance and moves value. | /docs/02
 *   step 1 | The agent asks | Its token says who it is. | m1 AG
 *
 * One directive per line; `#` starts a comment. Node ids are letters and digits
 * only: Mermaid builds an edge's id as `L_<from>_<to>_<n>`, so an underscore in a
 * node id would make that id impossible to split back into its two ends.
 *
 * Everything in this file is pure (no DOM), so the parser, the renderer and the
 * id conventions are unit-tested without a browser. The DOM half lives in
 * useArchFigures.ts.
 */

export type ArchKind = 'flow' | 'sequence'

export interface ArchNode {
  id: string
  title: string
  purpose: string
  /** `/docs/NN` or `/docs/NN#slug`, or null. Nothing else is ever rendered as a link. */
  href: string | null
}

export interface ArchLayer {
  id: string
  label: string
  nodes: string[]
}

export interface ArchStep {
  n: number
  title: string
  text: string
  /** 1-based message numbers in a sequence diagram (the numbers `autonumber` prints). */
  messages: number[]
  /** Components the step is about. */
  nodes: string[]
}

export interface Archmap {
  id: string
  title: string
  kind: ArchKind
  /** The release (and date) this view was last checked against; shown on the figure. */
  checked: string
  nodes: ArchNode[]
  layers: ArchLayer[]
  steps: ArchStep[]
}

export type ArchmapParse =
  | { ok: true; map: Archmap }
  | { ok: false; error: string; line: number }

const MAP_ID = /^[a-z0-9][a-z0-9-]{0,40}$/
const NODE_ID = /^[A-Za-z][A-Za-z0-9]{0,40}$/
const LAYER_ID = /^[a-z][a-z0-9-]{0,30}$/
const DOC_HREF = /^\/docs\/\d{2}(#[a-z0-9][a-z0-9-]*)?$/
const MAX_TITLE = 70
const MAX_PURPOSE = 320
const MAX_STEP_TEXT = 600

function fields(rest: string): string[] {
  return rest.split('|').map((s) => s.trim())
}

export function parseArchmap(source: string): ArchmapParse {
  let id = ''
  let title = ''
  let kind: ArchKind = 'flow'
  let checked = ''
  const nodes: ArchNode[] = []
  const layers: ArchLayer[] = []
  const steps: ArchStep[] = []
  const layerLines: number[] = []
  const stepLines: number[] = []
  const seenNodes = new Set<string>()
  const seenLayers = new Set<string>()

  const lines = source.replace(/\r\n/g, '\n').split('\n')
  for (let i = 0; i < lines.length; i++) {
    const lineNo = i + 1
    const line = lines[i].trim()
    if (!line || line.startsWith('#')) continue
    const fail = (error: string): ArchmapParse => ({ ok: false, error, line: lineNo })

    let m: RegExpMatchArray | null
    if ((m = line.match(/^id:\s*(.+)$/))) {
      if (id) return fail('a second id')
      if (!MAP_ID.test(m[1])) return fail(`bad id "${m[1]}"`)
      id = m[1]
      continue
    }
    if ((m = line.match(/^title:\s*(.+)$/))) {
      if (m[1].length > MAX_TITLE) return fail('title too long')
      title = m[1]
      continue
    }
    if ((m = line.match(/^checked:\s*(.+)$/))) {
      if (m[1].length > 60) return fail('checked too long')
      checked = m[1]
      continue
    }
    if ((m = line.match(/^kind:\s*(.+)$/))) {
      if (m[1] !== 'flow' && m[1] !== 'sequence') return fail(`unknown kind "${m[1]}"`)
      kind = m[1]
      continue
    }
    if ((m = line.match(/^node\s+(.+)$/))) {
      const f = fields(m[1])
      if (f.length < 3 || f.length > 4) return fail('node wants: ID | Title | Purpose | /docs/NN (optional)')
      const [nid, ntitle, purpose, href = ''] = f
      if (!NODE_ID.test(nid)) return fail(`bad node id "${nid}" (letters and digits only)`)
      if (seenNodes.has(nid)) return fail(`node ${nid} declared twice`)
      if (!ntitle || ntitle.length > MAX_TITLE) return fail(`node ${nid}: title missing or too long`)
      if (!purpose || purpose.length > MAX_PURPOSE) return fail(`node ${nid}: purpose missing or too long`)
      if (href && !DOC_HREF.test(href)) return fail(`node ${nid}: link must be /docs/NN or /docs/NN#slug`)
      seenNodes.add(nid)
      nodes.push({ id: nid, title: ntitle, purpose, href: href || null })
      continue
    }
    if ((m = line.match(/^layer\s+(.+)$/))) {
      const f = fields(m[1])
      if (f.length !== 3) return fail('layer wants: id | Label | NODE NODE ...')
      const [lid, label, members] = f
      if (!LAYER_ID.test(lid)) return fail(`bad layer id "${lid}"`)
      if (seenLayers.has(lid)) return fail(`layer ${lid} declared twice`)
      if (!label || label.length > 40) return fail(`layer ${lid}: label missing or too long`)
      const ids = members.split(/\s+/).filter(Boolean)
      if (!ids.length) return fail(`layer ${lid} names no component`)
      seenLayers.add(lid)
      layers.push({ id: lid, label, nodes: ids })
      layerLines.push(lineNo)
      continue
    }
    if ((m = line.match(/^step\s+(.+)$/))) {
      const f = fields(m[1])
      if (f.length !== 4) return fail('step wants: N | Title | Narration | targets')
      const [num, stitle, text, targets] = f
      const n = Number(num)
      if (!Number.isInteger(n) || n !== steps.length + 1) return fail(`steps must count 1, 2, 3 ... (got "${num}")`)
      if (!stitle || stitle.length > MAX_TITLE) return fail(`step ${n}: title missing or too long`)
      if (!text || text.length > MAX_STEP_TEXT) return fail(`step ${n}: narration missing or too long`)
      const messages: number[] = []
      const stepNodes: string[] = []
      for (const tok of targets.split(/\s+/).filter(Boolean)) {
        const mm = tok.match(/^m(\d+)$/)
        if (mm) messages.push(Number(mm[1]))
        else stepNodes.push(tok)
      }
      if (!messages.length && !stepNodes.length) return fail(`step ${n} names no target`)
      steps.push({ n, title: stitle, text, messages, nodes: stepNodes })
      stepLines.push(lineNo)
      continue
    }
    return fail(`unknown line "${line.slice(0, 40)}"`)
  }

  if (!id) return { ok: false, error: 'missing id', line: 1 }
  if (!nodes.length) return { ok: false, error: 'no nodes', line: 1 }
  for (let i = 0; i < layers.length; i++) {
    const unknown = layers[i].nodes.find((n) => !seenNodes.has(n))
    if (unknown) return { ok: false, error: `layer ${layers[i].id} names unknown node ${unknown}`, line: layerLines[i] }
  }
  for (let i = 0; i < steps.length; i++) {
    const unknown = steps[i].nodes.find((n) => !seenNodes.has(n))
    if (unknown) return { ok: false, error: `step ${steps[i].n} names unknown node ${unknown}`, line: stepLines[i] }
  }
  if (steps.length && kind !== 'sequence' && steps.some((s) => s.messages.length)) {
    return { ok: false, error: 'message targets (m1, m2 ...) need kind: sequence', line: stepLines[0] }
  }
  return { ok: true, map: { id, title, kind, checked, nodes, layers, steps } }
}

// ─── Mermaid's DOM id conventions (mermaid 11) ───────────────────────────────

/** A flowchart node's group id is `<diagramId>-flowchart-<nodeId>-<counter>`. */
export function nodeIdFromDomId(domId: string | null | undefined): string | null {
  const m = (domId || '').match(/-flowchart-([A-Za-z0-9]+)-\d+$/)
  return m ? m[1] : null
}

/** An edge path carries `data-id="L_<from>_<to>_<counter>"`, its label group the same. */
export function edgeEnds(dataId: string | null | undefined): [string, string] | null {
  const m = (dataId || '').match(/^L_([A-Za-z0-9]+)_([A-Za-z0-9]+)_\d+$/)
  return m ? [m[1], m[2]] : null
}

// ─── What a diagram's own source declares ───────────────────────────────────

/**
 * The node ids a flowchart declares with a shape (`ID[...]`, `ID(...)`,
 * `ID[(...)]`, `ID{...}`, ...). Labels are removed first, so a word inside a
 * label ("TEG (money)") is never mistaken for a node; subgraph ids are removed
 * after, because `subgraph FA["..."]` has the same shape as a node.
 */
export function flowchartNodeIds(src: string): string[] {
  const noLabels = src.replace(/"[^"\n]*"/g, '""')
  const subgraphs = new Set<string>()
  for (const m of noLabels.matchAll(/^\s*subgraph\s+([A-Za-z][A-Za-z0-9_]*)/gm)) subgraphs.add(m[1])
  const ids = new Set<string>()
  const body = noLabels
    .split('\n')
    .filter((l) => !/^\s*(classDef|class|style|linkStyle|click|%%)\b/.test(l))
    .join('\n')
  for (const m of body.matchAll(/(?:^|[\s;&|>-])([A-Za-z][A-Za-z0-9_]*)\s*(?:\[|\(|\{|>)/gm)) {
    if (!subgraphs.has(m[1]) && m[1] !== 'subgraph') ids.add(m[1])
  }
  return [...ids]
}

/** Participant ids of a sequence diagram (`participant X as ...`, `actor X`). */
export function sequenceParticipantIds(src: string): string[] {
  const ids: string[] = []
  for (const m of src.matchAll(/^\s*(?:participant|actor)\s+([A-Za-z][A-Za-z0-9_]*)/gm)) {
    if (!ids.includes(m[1])) ids.push(m[1])
  }
  return ids
}

/** How many messages a sequence diagram draws (the numbers `autonumber` prints). */
export function sequenceMessageCount(src: string): number {
  let n = 0
  for (const line of src.split('\n')) {
    if (/^\s*[A-Za-z][A-Za-z0-9_]*\s*(?:-{1,2}>>|-{1,2}>|-{1,2}x|-{1,2}\))[+-]?\s*[A-Za-z][A-Za-z0-9_]*\s*:/.test(line)) n++
  }
  return n
}

// ─── The static half of an explorable figure ────────────────────────────────

export interface ArchLabels {
  components: string
  layers: string
  all: string
  expand: string
  select: string
  read: string
  walkthrough: string
  step: string
  of: string
  prev: string
  next: string
  reset: string
  start: string
  checked: string
  close: string
  /** On a diagram drawn too small to use (a phone), the pill that opens it full screen. */
  explore: string
}

export const DEFAULT_ARCH_LABELS: ArchLabels = {
  components: 'Components in this view',
  layers: 'Layers',
  all: 'Everything',
  expand: 'Expand',
  select: 'Select any component in the diagram or the list below to see what it does.',
  read: 'Read chapter',
  walkthrough: 'Walk through it',
  step: 'Step',
  of: 'of',
  prev: 'Previous',
  next: 'Next',
  reset: 'Reset',
  start: 'Press › to start.',
  checked: 'Checked against',
  close: 'Close',
  explore: 'Explore full screen',
}

type Esc = (s: string) => string

/**
 * The direction a flowchart is drawn in (LR, TB, ...), read from its first line, so the
 * keyboard can walk the components in the order the diagram reads. Sequence diagrams and
 * anything unrecognised read top to bottom.
 */
export function flowDirection(mermaidSource: string): 'LR' | 'RL' | 'TB' | 'BT' {
  const body = mermaidSource.replace(/^---\n[\s\S]*?\n---\n/, '')
  const m = body.match(/^\s*(?:flowchart|graph)\s+(LR|RL|TB|TD|BT)\b/m)
  if (!m) return 'TB'
  return m[1] === 'TD' ? 'TB' : (m[1] as 'LR' | 'RL' | 'TB' | 'BT')
}

export function chapterOf(href: string): string {
  const m = href.match(/^\/docs\/(\d{2})/)
  return m ? m[1] : ''
}

function legendHtml(map: Archmap, p: string, labels: ArchLabels, esc: Esc): string {
  const items = map.nodes
    .map((n) => {
      const link = n.href
        ? `<a class="${p}-arch-read" href="${esc(n.href)}">${esc(labels.read)} ${esc(chapterOf(n.href))} →</a>`
        : ''
      return (
        `<li class="${p}-arch-item-row">` +
        `<button type="button" class="${p}-arch-item" data-arch-node="${esc(n.id)}">` +
        `<span class="${p}-arch-item-title">${esc(n.title)}</span>` +
        `<span class="${p}-arch-item-purpose">${esc(n.purpose)}</span>` +
        `</button>${link}</li>`
      )
    })
    .join('')
  return (
    `<details class="${p}-arch-legend">` +
    `<summary class="${p}-arch-legend-head">${esc(labels.components)} <span class="${p}-arch-count">${map.nodes.length}</span></summary>` +
    `<ul class="${p}-arch-list">${items}</ul></details>`
  )
}

function toolbarHtml(map: Archmap, p: string, labels: ArchLabels, esc: Esc): string {
  const chips = map.layers.length
    ? `<div class="${p}-arch-layers" role="group" aria-label="${esc(labels.layers)}">` +
      `<span class="${p}-arch-layers-label">${esc(labels.layers)}</span>` +
      `<button type="button" class="${p}-arch-chip is-on" data-arch-layer="" aria-pressed="true">${esc(labels.all)}</button>` +
      map.layers
        .map(
          (l) =>
            `<button type="button" class="${p}-arch-chip" data-arch-layer="${esc(l.id)}" aria-pressed="false">${esc(l.label)}</button>`
        )
        .join('') +
      `</div>`
    : ''
  const expand = `<button type="button" class="${p}-arch-expand" data-arch-action="expand">⤢ ${esc(labels.expand)}</button>`
  return `<div class="${p}-arch-toolbar">${chips}${expand}</div>`
}

function stepperHtml(map: Archmap, p: string, labels: ArchLabels, esc: Esc): string {
  if (!map.steps.length) return ''
  return (
    `<div class="${p}-arch-stepper" data-arch-steps="${map.steps.length}">` +
    `<div class="${p}-arch-stepper-bar">` +
    `<span class="${p}-arch-stepper-label">${esc(labels.walkthrough)}</span>` +
    `<button type="button" class="${p}-arch-step-btn" data-arch-action="prev" aria-label="${esc(labels.prev)}" disabled>‹</button>` +
    `<span class="${p}-arch-step-count" aria-live="polite">${esc(labels.step)} 0 ${esc(labels.of)} ${map.steps.length}</span>` +
    `<button type="button" class="${p}-arch-step-btn" data-arch-action="next" aria-label="${esc(labels.next)}">›</button>` +
    `<button type="button" class="${p}-arch-step-reset" data-arch-action="reset">${esc(labels.reset)}</button>` +
    `</div>` +
    `<div class="${p}-arch-narration" aria-live="polite"><span class="${p}-arch-narration-idle">${esc(labels.start)}</span></div>` +
    `</div>`
  )
}

/**
 * The figure: toolbar, the Mermaid block (unchanged, still picked up by
 * useMermaidRenderer), the walkthrough, the detail panel and the legend. The
 * parsed map rides along as JSON so the DOM half never re-parses markdown.
 */
export function renderArchFigure(
  mermaidSource: string,
  archmapSource: string,
  p: string,
  esc: Esc,
  labels: ArchLabels = DEFAULT_ARCH_LABELS
): string {
  const parsed = parseArchmap(archmapSource)
  const diagram = `<div class="${p}-mermaid mermaid">${esc(mermaidSource.replace(/\n+$/, ''))}</div>`
  if (!parsed.ok) {
    // Visible on purpose: a broken archmap must not render as a plain diagram that
    // quietly lost its explanations. The chapter test fails long before this ships.
    return (
      `<figure class="${p}-archfig ${p}-archfig-broken">${diagram}` +
      `<figcaption class="${p}-arch-error">archmap line ${parsed.line}: ${esc(parsed.error)}</figcaption></figure>`
    )
  }
  const map = parsed.map
  const title = map.title ? `<figcaption class="${p}-arch-title">${esc(map.title)}</figcaption>` : ''
  return (
    `<figure class="${p}-archfig" data-arch-id="${esc(map.id)}" data-arch-kind="${map.kind}" data-arch-dir="${flowDirection(mermaidSource)}" data-arch-json="${esc(JSON.stringify(map))}">` +
    title +
    toolbarHtml(map, p, labels, esc) +
    diagram +
    `<button type="button" class="${p}-arch-explore" data-arch-action="expand">${esc(labels.explore)} ↗</button>` +
    stepperHtml(map, p, labels, esc) +
    `<div class="${p}-arch-detail" aria-live="polite"><p class="${p}-arch-detail-idle">${esc(labels.select)}</p></div>` +
    legendHtml(map, p, labels, esc) +
    (map.checked ? `<p class="${p}-arch-checked">${esc(labels.checked)} ${esc(map.checked)}</p>` : '') +
    `</figure>`
  )
}

/** An archmap fence with no Mermaid fence right before it has nothing to explain. */
export function renderOrphanArchmap(p: string, esc: Esc): string {
  return `<div class="${p}-arch-error">archmap: no mermaid diagram directly before this block</div>`
}
