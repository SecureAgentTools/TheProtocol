// The blueprint data, checked the way a reader meets it: every edge names nodes that exist, every
// replay walks edges that exist, every attack fails on a rail the chamber cites, the spine rule holds,
// and on the Frontier chambers the drawings themselves are clean. The geometry below is the same
// bezier the looms draw (FlowLoom 1000x560, ArchLoom 1000x760), so an edge that runs through a node it
// does not connect, a label that sits on a node, a zone title or another label, and text wider than
// its box are found here instead of by eye.
import { describe, it, expect } from 'vitest'
import { BLUEPRINTS, RAIL_BY_ID, liveRatioOf } from './index'
import { ARCH_LOADERS } from './arch'
import type { Blueprint, BlueprintArch, NodeKind } from './types'

interface Pt { x: number; y: number }
interface Box { id: string; what: string; x0: number; x1: number; y0: number; y1: number }
interface Geo {
  hw: number; hh: number; gr: number; labX: number; labCh: number; subCh: number
  gLabY: number; gSubY: number; gLabCh: number; gSubCh: number; eCh: number; eDy: number; eH: number
}
interface Drawable {
  nodes: { id: string; label: string; sub?: string; kind: NodeKind; x: number; y: number }[]
  edges: { id: string; from: string; to: string; label?: string; curve?: number; labelT?: number; attackOnly?: boolean; d?: string }[]
  zones?: BlueprintArch['zones']
}

// Monospace advance 0.6 em at each text's font size (FlowLoom 11 / 9.5 / 10.5 px, ArchLoom 10.5 / 8.5 / 10 px).
const LOOM: Geo = { hw: 74, hh: 23, gr: 33, labX: -46, labCh: 6.6, subCh: 5.7, gLabY: 46, gSubY: 60, gLabCh: 6.6, gSubCh: 5.7, eCh: 6.3, eDy: 7, eH: 11 }
const ARCH: Geo = { hw: 64, hh: 20, gr: 28, labX: -38, labCh: 6.3, subCh: 5.1, gLabY: 40, gSubY: 52, gLabCh: 6.3, gSubCh: 5.1, eCh: 6.0, eDy: 6, eH: 10 }

const bez = (t: number, p0: Pt, c1: Pt, c2: Pt, p1: Pt): Pt => {
  const u = 1 - t
  return {
    x: u * u * u * p0.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * p1.x,
    y: u * u * u * p0.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * p1.y,
  }
}
const overlap = (a: Box, b: Box, pad = 0) => a.x0 < b.x1 + pad && a.x1 > b.x0 - pad && a.y0 < b.y1 + pad && a.y1 > b.y0 - pad
const inBox = (p: Pt, b: Box, pad = 0) => p.x > b.x0 - pad && p.x < b.x1 + pad && p.y > b.y0 - pad && p.y < b.y1 + pad

/** Every geometry finding on one drawing; [] is clean. Mirrors the components' own cubic. */
export function drawingFindings(g: Drawable, P: Geo, W: number, H: number): string[] {
  const half = (k: NodeKind) => (k === 'gate' ? { hw: P.gr, hh: P.gr } : { hw: P.hw, hh: P.hh })
  const byId = Object.fromEntries(g.nodes.map((n) => [n.id, n]))
  const out: string[] = []
  const boxes: Box[] = []
  for (const n of g.nodes) {
    if (n.kind === 'gate') {
      boxes.push({ id: n.id, what: 'node', x0: n.x - P.gr, x1: n.x + P.gr, y0: n.y - P.gr, y1: n.y + P.gr })
      const lw = n.label.length * P.gLabCh, sw = (n.sub || '').length * P.gSubCh
      boxes.push({ id: `${n.id}:label`, what: 'gate text', x0: n.x - lw / 2, x1: n.x + lw / 2, y0: n.y + P.gLabY - 10, y1: n.y + P.gLabY + 2 })
      if (n.sub) boxes.push({ id: `${n.id}:sub`, what: 'gate text', x0: n.x - sw / 2, x1: n.x + sw / 2, y0: n.y + P.gSubY - 9, y1: n.y + P.gSubY + 2 })
    } else {
      boxes.push({ id: n.id, what: 'node', x0: n.x - P.hw, x1: n.x + P.hw, y0: n.y - P.hh, y1: n.y + P.hh })
      const avail = P.hw - P.labX + 2
      if (n.label.length * P.labCh > avail) out.push(`text: ${n.id} label "${n.label}" is wider than its box`)
      if (n.sub && n.sub.length * P.subCh > avail) out.push(`text: ${n.id} sub "${n.sub}" is wider than its box`)
    }
    if (n.x - P.hw < 0 || n.x + P.hw > W || n.y - P.hh < 0 || n.y + P.hh > H) out.push(`canvas: node ${n.id} is off the canvas`)
  }
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    if (boxes[i].id.split(':')[0] === boxes[j].id.split(':')[0]) continue
    if (overlap(boxes[i], boxes[j], 2)) out.push(`overlap: ${boxes[i].id} and ${boxes[j].id}`)
  }
  const zoneText: Box[] = (g.zones || []).flatMap((z) => [
    { id: `${z.id}:title`, what: 'zone title', x0: z.x + 14, x1: z.x + 14 + z.label.length * 7.7, y0: z.y + 12, y1: z.y + 25 },
    ...(z.sub ? [{ id: `${z.id}:sub`, what: 'zone sub', x0: z.x + 14, x1: z.x + 14 + z.sub.length * 5.4, y0: z.y + 28, y1: z.y + 39 }] : []),
  ])
  for (const zt of zoneText) for (const b of boxes) if (overlap(zt, b, 2)) out.push(`overlap: ${zt.what} ${zt.id} and ${b.id}`)
  for (const z of g.zones || []) for (const b of boxes.filter((bb) => !bb.id.includes(':'))) {
    const inside = b.x0 >= z.x && b.x1 <= z.x + z.w && b.y0 >= z.y && b.y1 <= z.y + z.h
    if (overlap(b, { id: z.id, what: 'zone', x0: z.x, x1: z.x + z.w, y0: z.y, y1: z.y + z.h }) && !inside) out.push(`zone: ${b.id} straddles the border of ${z.id}`)
  }
  const curves = new Map<string, { p0: Pt; c1: Pt; c2: Pt; p1: Pt }>()
  for (const e of g.edges) {
    if (e.d) continue
    const a = byId[e.from], b = byId[e.to]
    if (!a || !b) { out.push(`ref: edge ${e.id} names a missing node`); continue }
    const ah = half(a.kind), bh = half(b.kind)
    const dx = b.x - a.x, dy = b.y - a.y
    let p0: Pt, p1: Pt, c1: Pt, c2: Pt
    if (Math.abs(dx) >= Math.abs(dy)) {
      const s = Math.sign(dx) || 1
      p0 = { x: a.x + ah.hw * s, y: a.y }; p1 = { x: b.x - bh.hw * s, y: b.y }
      const pull = (p1.x - p0.x) * 0.42
      c1 = { x: p0.x + pull, y: p0.y }; c2 = { x: p1.x - pull, y: p1.y }
    } else {
      const s = Math.sign(dy) || 1
      p0 = { x: a.x, y: a.y + ah.hh * s }; p1 = { x: b.x, y: b.y - bh.hh * s }
      const pull = (p1.y - p0.y) * 0.42
      c1 = { x: p0.x, y: p0.y + pull }; c2 = { x: p1.x, y: p1.y - pull }
    }
    if (e.curve) {
      const len = Math.hypot(dx, dy) || 1
      const px = (-dy / len) * e.curve, py = (dx / len) * e.curve
      c1 = { x: c1.x + px, y: c1.y + py }; c2 = { x: c2.x + px, y: c2.y + py }
    }
    curves.set(e.id, { p0, c1, c2, p1 })
  }
  const samples = (id: string) => { const c = curves.get(id)!; return Array.from({ length: 97 }, (_, k) => bez((k + 2) / 100, c.p0, c.c1, c.c2, c.p1)) }
  const labels: (Box & { attack: boolean; edge: string })[] = []
  for (const e of g.edges) {
    if (!curves.has(e.id)) continue
    const pts = samples(e.id)
    for (const b of boxes) {
      const base = b.id.split(':')[0]
      if (base === e.from || base === e.to) continue
      if (pts.some((p) => inBox(p, b, 1))) out.push(`cross: edge ${e.id} runs through ${b.what} ${b.id}`)
    }
    for (const zt of zoneText) if (pts.filter((p) => inBox(p, zt)).length > 2) out.push(`cross: edge ${e.id} runs through ${zt.what} ${zt.id}`)
    if (pts.some((p) => p.x < 0 || p.x > W || p.y < 0 || p.y > H)) out.push(`canvas: edge ${e.id} leaves the canvas`)
    if (e.label) {
      const c = curves.get(e.id)!
      const m = bez(e.labelT ?? 0.5, c.p0, c.c1, c.c2, c.p1)
      const w = e.label.length * P.eCh
      const lb = { id: `${e.id}:label`, what: `label "${e.label}"`, edge: e.id, attack: !!e.attackOnly, x0: m.x - w / 2, x1: m.x + w / 2, y0: m.y - P.eDy - P.eH + 2, y1: m.y - P.eDy + 3 }
      labels.push(lb)
      for (const b of boxes) if (overlap(lb, b, 1)) out.push(`label: ${lb.what} of ${e.id} sits on ${b.what} ${b.id}`)
      for (const zt of zoneText) if (overlap(lb, zt, 1)) out.push(`label: ${lb.what} of ${e.id} sits on ${zt.what} ${zt.id}`)
      if (lb.x0 < 0 || lb.x1 > W || lb.y0 < 0 || lb.y1 > H) out.push(`canvas: ${lb.what} of ${e.id} is off the canvas`)
    }
  }
  for (let i = 0; i < labels.length; i++) for (let j = i + 1; j < labels.length; j++) {
    if (labels[i].attack && labels[j].attack) continue // attacks replay one at a time
    if (overlap(labels[i], labels[j], 2)) out.push(`label: ${labels[i].what} and ${labels[j].what} overlap`)
  }
  for (const lb of labels) for (const e of g.edges) {
    if (e.id === lb.edge || !curves.has(e.id)) continue
    if (samples(e.id).filter((p) => inBox(p, lb, -1)).length > 1) out.push(`label: ${lb.what} of ${lb.edge} lies on edge ${e.id}`)
  }
  return out
}

const frontier = BLUEPRINTS.filter((b) => b.frontier)
const strings = (o: unknown): string[] =>
  typeof o === 'string' ? [o] : Array.isArray(o) ? o.flatMap(strings) : o && typeof o === 'object' ? Object.values(o).flatMap(strings) : []

describe('blueprint data', () => {
  it('ids and ranks are unique, and every chamber is reachable', () => {
    expect(new Set(BLUEPRINTS.map((b) => b.id)).size).toBe(BLUEPRINTS.length)
    expect(new Set(BLUEPRINTS.map((b) => b.rank)).size).toBe(BLUEPRINTS.length)
  })

  it.each(BLUEPRINTS.map((b) => [b.id, b] as [string, Blueprint]))('%s: every reference resolves', (_id, bp) => {
    const bad: string[] = []
    for (const r of bp.rails) if (!RAIL_BY_ID[r]) bad.push(`rail ${r} is not in the catalogue`)
    const loom = bp.loom
    if (loom) {
      const nodes = new Set(loom.nodes.map((n) => n.id)), edges = new Set(loom.edges.map((e) => e.id))
      for (const e of loom.edges) if (!e.d && (!nodes.has(e.from) || !nodes.has(e.to))) bad.push(`edge ${e.id} names a missing node`)
      for (const s of loom.script) if (!edges.has(s.edge)) bad.push(`script step names missing edge ${s.edge}`)
      for (const a of bp.attacks) for (const s of a.script) {
        if (!edges.has(s.edge)) bad.push(`attack "${a.title}" names missing edge ${s.edge}`)
        if (s.flashNode && !nodes.has(s.flashNode)) bad.push(`attack "${a.title}" flashes missing node ${s.flashNode}`)
      }
    }
    for (const a of bp.attacks) if (!bp.rails.includes(a.rail)) bad.push(`attack "${a.title}" fails on ${a.rail}, which the chamber does not cite`)
    expect(bad).toEqual([])
  })

  it.each(BLUEPRINTS.map((b) => [b.id, b] as [string, Blueprint]))('%s: the spine rule holds and the ratio is the table\'s', (_id, bp) => {
    const [live, total] = liveRatioOf(bp.primitives)
    expect(live * 2).toBeGreaterThan(total)
    expect(bp.liveRatio).toEqual([live, total])
  })
})

describe('the Frontier', () => {
  it('exists, and every frontier chamber has a deep architecture', () => {
    expect(frontier.length).toBeGreaterThan(0)
    for (const bp of frontier) expect(ARCH_LOADERS[bp.id], bp.id).toBeTypeOf('function')
  })

  it.each(frontier.map((b) => [b.id, b] as [string, Blueprint]))('%s: the house register (no em dash, no "moat", no conditional voice)', (_id, bp) => {
    const text = strings(bp).join('\n')
    expect(text).not.toMatch(/—/)
    expect(text).not.toMatch(/\bmoat\b/i)
    expect(text).not.toMatch(/\b(would|could|imagine)\b/i)
  })

  it.each(frontier.map((b) => [b.id] as [string]))('%s: the deep architecture keeps the register', async (id) => {
    const { deep } = await ARCH_LOADERS[id]()
    expect(strings(deep).join('\n')).not.toMatch(/\u2014/)
  })
})

// Every chamber, not only the Frontier (2026-09-25, his word "also fix the drawings of the older chambers"): the 21 older
// chambers were redrawn to zero findings, and this holds all 27 there.
describe('every chamber draws clean', () => {
  it.each(BLUEPRINTS.filter((b) => b.loom).map((b) => [b.id, b] as [string, Blueprint]))('%s: the loom', (_id, bp) => {
    expect(drawingFindings(bp.loom!, LOOM, 1000, 560)).toEqual([])
  })

  it.each(Object.keys(ARCH_LOADERS).map((id) => [id] as [string]))('%s: the deep architecture, and its trace walks real edges', async (id) => {
    const { deep } = await ARCH_LOADERS[id]()
    const edges = new Set(deep.arch.edges.map((e) => e.id))
    for (const s of deep.arch.script || []) expect(edges.has(s.edge), `trace step ${s.edge}`).toBe(true)
    expect(drawingFindings(deep.arch, ARCH, 1000, 760)).toEqual([])
  })
})

describe('the geometry check can fail', () => {
  const nodes: Drawable['nodes'] = [
    { id: 'a', label: 'a', kind: 'agent', x: 118, y: 220 },
    { id: 'b', label: 'b', kind: 'agent', x: 336, y: 220 },
    { id: 'c', label: 'c', kind: 'agent', x: 560, y: 220 },
  ]
  it('finds an edge through a node it does not connect', () => {
    expect(drawingFindings({ nodes, edges: [{ id: 'ac', from: 'a', to: 'c' }] }, LOOM, 1000, 560)).toContain('cross: edge ac runs through node b')
  })
  it('finds a label wider than its box', () => {
    const wide = [{ ...nodes[0], label: 'a label far too long for any box' }]
    expect(drawingFindings({ nodes: wide, edges: [] }, LOOM, 1000, 560).some((f) => f.startsWith('text: a label'))).toBe(true)
  })
  it('passes the same drawing without the crossing', () => {
    expect(drawingFindings({ nodes, edges: [{ id: 'ab', from: 'a', to: 'b' }, { id: 'bc', from: 'b', to: 'c' }] }, LOOM, 1000, 560)).toEqual([])
  })
})

// His word 2026-10-26 ("insurance blueprints approved, reword them like moira"): no chamber sells cover. The console's
// critical-word gate leaves data/blueprints/ out (i18n/vocabulary.test.ts NOT_COUNTED), so the chambers hold their own.
// Kept senses: a human underwrites an agent (the Cockpit Card's word), and a third party's own insurer reading evidence.
const SELLS_COVER = /\b(?:insurance|insured|insureds|reinsur\w*|parametric|policyholders?|underwriter|underwriting|loss adjusters?|claims? (?:administrators?|adjusters?|gates?|platforms?|seasons?))\b/i

describe('no chamber sells cover', () => {
  it('the guard sees the words, and lets the kept senses through', () => {
    for (const s of ['parametric cover', 'Insurance and Parametric Claims', 'reinsurer-watch', 'the insured', 'underwriter-desk', 'a claims gate'])
      expect(s).toMatch(SELLS_COVER)
    for (const s of ['she underwrites the steward', 'the firm’s insurer reads a hash chain', 'a premium buyer'])
      expect(s).not.toMatch(SELLS_COVER)
  })
  it.each(BLUEPRINTS.map((b) => [b.id, b] as [string, Blueprint]))('%s: the chamber', (_id, bp) => {
    expect(strings(bp).filter((t) => SELLS_COVER.test(t))).toEqual([])
  })
  it.each(Object.keys(ARCH_LOADERS).map((id) => [id] as [string]))('%s: the deep architecture', async (id) => {
    const { deep } = await ARCH_LOADERS[id]()
    expect(strings(deep).filter((t) => SELLS_COVER.test(t))).toEqual([])
  })
})

// A capability permit is a permit (2026-10-26, agentvault2-5b's sweep): "token" stays only in its credential senses,
// a captured admin token, the X-Capability-Token header, the apt_ payment token, and edge ids.
const TOKEN_KEPT = /\b(?:admin token|X-Capability-Token|apt_ token|e-token)\b/gi
const tokenWords = (t: string) => t.replace(TOKEN_KEPT, ' ').match(/\btokens?\b/gi) || []
describe('a capability permit is called a permit', () => {
  it('the guard sees the word and lets the credential senses through', () => {
    expect(tokenWords('books on a token')).toEqual(['token'])
    expect(tokenWords('a captured admin token, the X-Capability-Token header, an apt_ token, e-token')).toEqual([])
  })
  it.each(BLUEPRINTS.map((b) => [b.id, b] as [string, Blueprint]))('%s: the chamber', (_id, bp) => {
    expect(strings(bp).filter((t) => tokenWords(t).length)).toEqual([])
  })
  it.each(Object.keys(ARCH_LOADERS).map((id) => [id] as [string]))('%s: the deep architecture', async (id) => {
    const { deep } = await ARCH_LOADERS[id]()
    expect(strings(deep).filter((t) => tokenWords(t).length)).toEqual([])
  })
})
