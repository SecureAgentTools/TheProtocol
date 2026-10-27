/**
 * The architecture chapter (oracle 35) as a gate. A view whose diagram and
 * explanation disagree, a link to a chapter that does not exist, or a port or
 * a container name in a public page fails here, in the build, instead of on
 * someone's screen.
 */
import { describe, it, expect } from 'vitest'
import chapter from '@/assets/docs/oracle/35_architecture.md?raw'
import {
  parseArchmap,
  flowchartNodeIds,
  sequenceParticipantIds,
  sequenceMessageCount,
  type Archmap,
} from './archmap'
import { renderDocsMarkdown } from './useDocsMarkdown'

const chapterFiles = Object.keys(import.meta.glob('@/assets/docs/oracle/*.md'))

interface Fence { lang: string; body: string }

function fences(md: string): Fence[] {
  const out: Fence[] = []
  let cur: Fence | null = null
  for (const line of md.split('\n')) {
    const m = line.match(/^```(\S*)\s*$/)
    if (m && !cur) { cur = { lang: m[1], body: '' }; continue }
    if (m && cur && m[1] === '') { out.push(cur); cur = null; continue }
    if (cur) cur.body += line + '\n'
  }
  return out
}

const all = fences(chapter)
const pairs: { mermaid: string; map: Archmap }[] = []
all.forEach((f, i) => {
  if (f.lang !== 'archmap') return
  const r = parseArchmap(f.body)
  if (!r.ok) throw new Error(`archmap ${i}: line ${r.line}: ${r.error}`)
  pairs.push({ mermaid: all[i - 1]?.lang === 'mermaid' ? all[i - 1].body : '', map: r.map })
})

describe('oracle 35, The Architecture', () => {
  it('explains every diagram it draws', () => {
    expect(pairs.map((p) => p.map.id)).toEqual([
      'network', 'frame', 'frame-kit', 'operator', 'federation-setup', 'federation-call', 'transfer', 'identity', 'machines', 'lifecycle',
    ])
    const mermaidCount = all.filter((f) => f.lang === 'mermaid').length
    expect(mermaidCount).toBe(pairs.length)
    for (const p of pairs) expect(p.mermaid, `${p.map.id} has no mermaid block right before it`).not.toBe('')
  })

  it.each(pairs.map((p) => [p.map.id, p] as const))('%s: the diagram and its explanation name the same components', (_id, p) => {
    const mapped = p.map.nodes.map((n) => n.id).sort()
    const drawn = (p.map.kind === 'sequence' ? sequenceParticipantIds(p.mermaid) : flowchartNodeIds(p.mermaid)).sort()
    expect(drawn).toEqual(mapped)
  })

  it('walks the transfer message by message, each message in exactly one step', () => {
    const t = pairs.find((p) => p.map.id === 'transfer')!
    const count = sequenceMessageCount(t.mermaid)
    expect(count).toBeGreaterThan(8)
    const seen = t.map.steps.flatMap((s) => s.messages)
    expect([...seen].sort((a, b) => a - b)).toEqual(Array.from({ length: count }, (_, i) => i + 1))
  })

  it('stamps every view with the release it was checked against', () => {
    const stamps = new Set(pairs.map((p) => p.map.checked))
    expect(stamps.size).toBe(1)
    expect([...stamps][0]).toMatch(/^V\d{4} · \d{4}-\d{2}-\d{2}$/)
  })

  it('links only to chapters that exist', () => {
    const hrefs = [
      ...pairs.flatMap((p) => p.map.nodes.map((n) => n.href).filter(Boolean) as string[]),
      ...[...chapter.matchAll(/\]\((\/docs\/\d{2})[^)]*\)/g)].map((m) => m[1]),
    ]
    expect(hrefs.length).toBeGreaterThan(40)
    for (const h of hrefs) {
      const num = h.slice(6, 8)
      expect(chapterFiles.some((f) => f.includes(`/oracle/${num}_`)), `${h} names no chapter`).toBe(true)
    }
  })

  it('is safe to publish: no ports, no host or container names, house style', () => {
    const text = chapter.split('\n').filter((l) => !/^\s*classDef\b/.test(l)).join('\n')
    expect(text).not.toMatch(/:\d{2,5}\b/)
    expect(text).not.toMatch(/localhost|127\.0\.0\.1|0\.0\.0\.0/)
    const hosts = [...text.matchAll(/\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:cloud|com|net|io|org|dev|local)\b/gi)].map((m) => m[0])
    expect(hosts.filter((h) => h !== 'theprotocol.cloud')).toEqual([])
    // container names, not concepts: "cross-registry" is a word, "eu-registry" is a container
    expect(text).not.toMatch(/nginx-|redpanda|pgbouncer|cert-writer|\b(?!cross-)[a-z0-9]+-(?:registry|teg|event-store|db|redis)\b/i)
    expect(chapter).not.toContain('—') // no em dashes in outward text
  })

  it('renders as ten explorable figures and nothing broken', () => {
    const html = renderDocsMarkdown(chapter, { classPrefix: 'orc', headingAnchors: true })
    expect(html.match(/<figure class="orc-archfig"/g)).toHaveLength(10)
    expect(html).not.toContain('orc-arch-error')
    expect(html).not.toContain('language-archmap')
  })
})
