import { describe, it, expect } from 'vitest'
import MarkdownIt from 'markdown-it'
import {
  parseArchmap,
  nodeIdFromDomId,
  edgeEnds,
  flowchartNodeIds,
  sequenceParticipantIds,
  sequenceMessageCount,
  renderArchFigure,
  DEFAULT_ARCH_LABELS,
  flowDirection,
} from './archmap'
import { renderDocsMarkdown } from './useDocsMarkdown'

const esc = new MarkdownIt().utils.escapeHtml

const GOOD = `
# a comment
id: frame
title: Inside one frame
checked: V0446 · 2026-09-25
layer money | Money | TEG GW
node TEG | TEG | Holds every balance. | /docs/02
node GW | TEG gateway | mTLS in front of the TEG. | /docs/08#service-to-service-mtls
node REG | Registry | Takes every request.
`

describe('parseArchmap', () => {
  it('reads ids, layers, nodes, links and the stamp', () => {
    const r = parseArchmap(GOOD)
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.map.id).toBe('frame')
    expect(r.map.kind).toBe('flow')
    expect(r.map.checked).toBe('V0446 · 2026-09-25')
    expect(r.map.nodes.map((n) => n.id)).toEqual(['TEG', 'GW', 'REG'])
    expect(r.map.nodes[1].href).toBe('/docs/08#service-to-service-mtls')
    expect(r.map.nodes[2].href).toBeNull()
    expect(r.map.layers).toEqual([{ id: 'money', label: 'Money', nodes: ['TEG', 'GW'] }])
  })

  it('reads a sequence walkthrough', () => {
    const r = parseArchmap(`id: t\nkind: sequence\nnode A | A | a.\nnode B | B | b.\nstep 1 | Ask | A asks. | m1 A\nstep 2 | Answer | B answers. | m2 m3 B`)
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.map.steps).toEqual([
      { n: 1, title: 'Ask', text: 'A asks.', messages: [1], nodes: ['A'] },
      { n: 2, title: 'Answer', text: 'B answers.', messages: [2, 3], nodes: ['B'] },
    ])
  })

  it.each([
    ['node REG_A | R | r.', /letters and digits only/], // an underscore would make L_<from>_<to>_<n> ambiguous
    ['node R | R | r. | https://evil.example/x', /link must be/],
    ['node R | R | r. | javascript:alert(1)', /link must be/],
    ['node R | R | r.\nnode R | R2 | r2.', /declared twice/],
    ['layer money | Money | NOPE\nnode R | R | r.', /unknown node NOPE/],
    ['node R | R | r.\nstep 2 | S | s. | R', /count 1, 2, 3/],
    ['node R | R | r.\nstep 1 | S | s. | m1', /need kind: sequence/],
    ['node R | R | r.\nwhat is this', /unknown line/],
    ['kind: tree\nnode R | R | r.', /unknown kind/],
  ])('refuses %s', (body, err) => {
    const r = parseArchmap(`id: x\n${body}`)
    expect(r.ok).toBe(false)
    if (r.ok) return
    expect(r.error).toMatch(err)
    expect(r.line).toBeGreaterThan(0)
  })

  it('refuses a map with no id or no nodes', () => {
    expect(parseArchmap('node R | R | r.').ok).toBe(false)
    expect(parseArchmap('id: x').ok).toBe(false)
  })
})

describe("mermaid's id conventions", () => {
  it('finds the node id in a flowchart group id', () => {
    expect(nodeIdFromDomId('mermaid-1727-flowchart-REG-12')).toBe('REG')
    expect(nodeIdFromDomId('mermaid-9-flowchart-GWTEG-0')).toBe('GWTEG')
    expect(nodeIdFromDomId('mermaid-9-flowchart-A1-3')).toBe('A1')
    expect(nodeIdFromDomId('subGraph0')).toBeNull()
    expect(nodeIdFromDomId(null)).toBeNull()
  })

  it('splits an edge id into its two ends', () => {
    expect(edgeEnds('L_REG_GWTEG_0')).toEqual(['REG', 'GWTEG'])
    expect(edgeEnds('L_A1_B2_17')).toEqual(['A1', 'B2'])
    expect(edgeEnds('L_REG_A_B_0')).toBeNull() // why node ids may not contain underscores
    expect(edgeEnds('')).toBeNull()
  })
})

describe('what a diagram source declares', () => {
  it('lists shaped nodes, ignoring labels, subgraphs and class lines', () => {
    const src = `flowchart TB
    PPL(["People (and agents)"]):::people
    subgraph EUZONE["EU frame"]
        EU["EU frame<br/>TEG (money)"]:::frame
    end
    DB[("Ledger DB")]:::data
    PPL -->|"TEG[x]"| EU
    EU <==>|"federation"| DB
    classDef people fill:#1a2234,stroke:#3B82F6
    style EU stroke-width:2px`
    expect(flowchartNodeIds(src).sort()).toEqual(['DB', 'EU', 'PPL'])
  })

  it('lists participants and counts messages of a sequence', () => {
    const src = `sequenceDiagram
    autonumber
    participant AG as Agent
    participant REG as Registry
    AG->>REG: POST /api/v1/teg/transfer
    REG->>REG: decides
    REG-->>AG: 200`
    expect(sequenceParticipantIds(src)).toEqual(['AG', 'REG'])
    expect(sequenceMessageCount(src)).toBe(3)
  })
})

describe('renderArchFigure', () => {
  const html = renderArchFigure('flowchart LR\n  TEG["TEG"] --> GW["GW"]\n  REG["R"]\n', GOOD, 'orc', esc)

  it('keeps the mermaid block where the renderer looks for it', () => {
    expect(html).toContain('<div class="orc-mermaid mermaid">flowchart LR')
    expect(html.startsWith('<figure class="orc-archfig"')).toBe(true)
  })

  it('renders chips, legend, stamp and the map as JSON', () => {
    expect(html).toContain('data-arch-layer="money"')
    expect(html).toContain(`>${DEFAULT_ARCH_LABELS.all}</button>`)
    expect(html).toContain('data-arch-node="GW"')
    expect(html).toContain('href="/docs/02"')
    expect(html).toContain('Checked against V0446')
    const m = html.match(/data-arch-json="([^"]*)"/)
    expect(m).not.toBeNull()
    const decoded = m![1].replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    expect(JSON.parse(decoded).nodes).toHaveLength(3)
  })

  it('escapes what the chapter wrote', () => {
    const out = renderArchFigure('flowchart LR\n  A["A"]', 'id: x\nnode A | <img src=x onerror=alert(1)> | "quoted" & <b>bold</b>', 'orc', esc)
    expect(out).not.toContain('<img')
    expect(out).not.toContain('<b>')
    expect(out).toContain('&lt;img')
  })

  it('shows a broken map instead of silently dropping it', () => {
    const out = renderArchFigure('flowchart LR\n  A["A"]', 'id: x\nnode A_B | A | a.', 'orc', esc)
    expect(out).toContain('orc-archfig-broken')
    expect(out).toContain('archmap line 2')
    expect(out).toContain('<div class="orc-mermaid mermaid">')
  })

  it('renders a walkthrough only for a map with steps', () => {
    expect(html).not.toContain('orc-arch-stepper')
    const seq = renderArchFigure('sequenceDiagram\n  A->>B: hi', 'id: s\nkind: sequence\nnode A | A | a.\nnode B | B | b.\nstep 1 | Hi | A says hi. | m1', 'orc', esc)
    expect(seq).toContain('data-arch-steps="1"')
    expect(seq).toContain('data-arch-action="next"')
  })
})

describe('the markdown pipeline', () => {
  it('pairs a mermaid block with the archmap right after it', () => {
    const out = renderDocsMarkdown('```mermaid\nflowchart LR\n  A["A"]\n```\n\n```archmap\nid: x\nnode A | A | a.\n```\n', { classPrefix: 'orc' })
    expect(out.match(/<figure class="orc-archfig"/g)).toHaveLength(1)
    expect(out).not.toContain('orc-arch-error')
    expect(out).not.toContain('language-archmap')
  })

  it('leaves a plain mermaid block exactly as before', () => {
    const out = renderDocsMarkdown('```mermaid\nflowchart LR\n  A --> B\n```\n', { classPrefix: 'orc' })
    expect(out.trim()).toBe('<div class="orc-mermaid mermaid">flowchart LR\n  A --&gt; B</div>')
  })

  it('flags an archmap that explains nothing', () => {
    const out = renderDocsMarkdown('Some text.\n\n```archmap\nid: x\nnode A | A | a.\n```\n', { classPrefix: 'orc' })
    expect(out).toContain('orc-arch-error')
  })

  it('uses the labels the view hands it', () => {
    const out = renderDocsMarkdown('```mermaid\nflowchart LR\n  A["A"]\n```\n\n```archmap\nid: x\nlayer l | L | A\nnode A | A | a.\n```\n', {
      classPrefix: 'orc',
      archLabels: { ...DEFAULT_ARCH_LABELS, all: 'Alles', layers: 'Ebenen' },
    })
    expect(out).toContain('>Alles</button>')
    expect(out).toContain('>Ebenen</span>')
  })
})

describe('flowDirection', () => {
  it('reads the direction a flowchart is drawn in, past its frontmatter', () => {
    expect(flowDirection('flowchart LR\n  A --> B')).toBe('LR')
    expect(flowDirection('graph TD\n  A --> B')).toBe('TB')
    expect(flowDirection('---\nconfig:\n  flowchart:\n    rankSpacing: 38\n---\nflowchart TB\n  A --> B')).toBe('TB')
    expect(flowDirection('    flowchart RL\n  A --> B')).toBe('RL')
    expect(flowDirection('sequenceDiagram\n  A->>B: hi')).toBe('TB')
  })

  it('a figure carries its direction and a way to open it full screen', () => {
    const html = renderArchFigure('flowchart LR\n  A --> B', 'id: x\nnode A | A | a.\nnode B | B | b.', 'orc', esc)
    expect(html).toContain('data-arch-dir="LR"')
    expect(html).toContain('class="orc-arch-explore" data-arch-action="expand"')
    expect(html).toContain(DEFAULT_ARCH_LABELS.explore)
  })
})
