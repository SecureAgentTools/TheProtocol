/**
 * Shared Mermaid renderer for the Whitepaper and Oracle Docs views.
 *
 * Two themes:
 *   - `whitepaper`: solid dark cyan theme (existing whitepaper look)
 *   - `oracle`: translucent glass theme that lets the starfield breathe through
 *
 * Mermaid is dynamically imported on first use so the ~1MB library is not in
 * the initial bundle.
 */

import { useLogger } from '@/composables/useLogger'

const log = useLogger('useMermaidRenderer')

export type MermaidTheme = 'whitepaper' | 'oracle' | 'blueprints'

interface RenderOptions {
  selector: string
  theme: MermaidTheme
  root?: ParentNode | null
}

const THEME_CONFIG: Record<MermaidTheme, {
  themeVariables: Record<string, string>
  fontFamily: string
}> = {
  whitepaper: {
    themeVariables: {
      background: '#060810',
      primaryColor: '#0a0e18',
      primaryTextColor: '#e4ecf4',
      primaryBorderColor: '#00b8b8',
      lineColor: '#00b8b8',
      secondaryColor: '#0d1422',
      tertiaryColor: '#0a0e18',
      clusterBkg: 'rgba(0, 184, 184, 0.04)',
      clusterBorder: 'rgba(0, 184, 184, 0.3)',
      edgeLabelBackground: '#060810',
      textColor: '#b0bec5',
      mainBkg: '#0d1422',
      nodeBorder: '#00b8b8',
      titleColor: '#e4ecf4',
    },
    fontFamily: "'JetBrains Mono', 'Fira Code', 'SF Mono', Consolas, monospace",
  },
  oracle: {
    themeVariables: {
      background: 'transparent',
      primaryColor: 'rgba(20, 24, 36, 0.6)',
      primaryTextColor: '#e4ecf4',
      primaryBorderColor: 'rgba(59, 130, 246, 0.7)',
      lineColor: 'rgba(139, 92, 246, 0.75)',
      secondaryColor: 'rgba(16, 185, 129, 0.18)',
      tertiaryColor: 'rgba(20, 24, 36, 0.4)',
      clusterBkg: 'rgba(20, 24, 36, 0.35)',
      clusterBorder: 'rgba(139, 92, 246, 0.3)',
      edgeLabelBackground: 'rgba(6, 8, 16, 0.88)',
      textColor: '#cfd6e0',
      mainBkg: 'rgba(20, 24, 36, 0.45)',
      nodeBorder: 'rgba(59, 130, 246, 0.7)',
      titleColor: '#e4ecf4',
    },
    fontFamily: "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
  },
  // Industry Blueprints wiring diagrams: translucent panels over the page's
  // own dark surface, cyan-family accents matching the Loom's default flow.
  blueprints: {
    themeVariables: {
      background: 'transparent',
      primaryColor: 'rgba(10, 14, 22, 0.72)',
      primaryTextColor: '#e4ecf4',
      primaryBorderColor: 'rgba(0, 210, 210, 0.55)',
      lineColor: 'rgba(0, 210, 210, 0.6)',
      secondaryColor: 'rgba(16, 185, 129, 0.15)',
      tertiaryColor: 'rgba(10, 14, 22, 0.5)',
      clusterBkg: 'rgba(10, 14, 22, 0.35)',
      clusterBorder: 'rgba(0, 210, 210, 0.25)',
      edgeLabelBackground: 'rgba(6, 8, 16, 0.9)',
      textColor: '#cfd6e0',
      mainBkg: 'rgba(10, 14, 22, 0.6)',
      nodeBorder: 'rgba(0, 210, 210, 0.55)',
      titleColor: '#e4ecf4',
    },
    fontFamily: "'IBM Plex Mono', 'Fira Code', 'SF Mono', Consolas, monospace",
  },
}

let renderSeq = 0

/**
 * §SUITES1018 (2026-10-20, his report: "labels with multiple lines are cut off" in the architecture chapter). Mermaid
 * sizes every label's box with its own type (16px, line-height 1.5) while it lays the diagram out off the page; in the
 * page a view's prose rule on `p` (the docs: `.orc-article :deep(p)`, 1.1rem and line-height 1.85) then grew each
 * label past its box, and the box cut it: 163 of 213 labels on chapter 35, the last line of every multi-line one.
 * themeCSS is scoped to the diagram's own id, so `#tp-mmd-N foreignObject p` outranks any page's class rule and a
 * label keeps the type it was measured with (measured on EU: 0 of 213 clipped with these rules).
 */
export const LABEL_TYPE_RESET =
  'foreignObject div, foreignObject span, foreignObject p { margin: 0; font-family: inherit; font-size: inherit; ' +
  'font-weight: inherit; line-height: 1.5; letter-spacing: normal; }'

/** The diagram's source as mermaid reads it: the common indentation removed, the ends trimmed. */
export function dedentDiagram(text: string): string {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const indents = lines.filter((l) => l.trim()).map((l) => (l.match(/^[ \t]*/)?.[0].length ?? 0))
  const cut = indents.length ? Math.min(...indents) : 0
  return lines.map((l) => l.slice(cut)).join('\n').trim()
}

export async function renderMermaidDiagrams(opts: RenderOptions): Promise<void> {
  const root = opts.root ?? document
  const nodes = root.querySelectorAll(opts.selector)
  if (!nodes.length) return

  // Filter to (a) still-connected DOM nodes and (b) nodes that haven't already
  // been processed. Rapid chapter navigation in Vue can hand us either stale
  // refs (Vue swapped innerHTML after our query) or already-rendered nodes
  // (double-render races) — mermaid's internal code then null-dereferences.
  const pending = Array.from(nodes).filter((n) => {
    if (!(n instanceof HTMLElement)) return false
    if (!n.isConnected) return false
    if (n.getAttribute('data-processed') === 'true') return false
    return true
  }) as HTMLElement[]
  if (!pending.length) return

  try {
    const mermaid = (await import('mermaid')).default
    const themeCfg = THEME_CONFIG[opts.theme]

    mermaid.initialize({
      startOnLoad: false,
      // Mermaid 12 lays out flowchart, state, class, ER, requirement and use-case diagrams with ELK instead of dagre,
      // and its default look is `neo`. Its 12.0.0 release notes: add `layout: dagre`, `theme: default` and
      // `look: classic` "to keep the old look". The layout and the look are set here; the theme stays this file's
      // own 'base' with its themeVariables.
      layout: 'dagre',
      look: 'classic',
      theme: 'base',
      securityLevel: 'strict',
      fontFamily: themeCfg.fontFamily,
      themeVariables: themeCfg.themeVariables,
      themeCSS: LABEL_TYPE_RESET,
      flowchart: {
        curve: 'basis',
        padding: 18,
        nodeSpacing: 40,
        rankSpacing: 50,
        htmlLabels: true,
      },
      sequence: {
        actorMargin: 40,
        messageMargin: 38,
      },
    })

    // §FESUITE V0600: one diagram at a time, laid out OFF the page (mermaid.render with no container lays it out in a
    // visible scratch element of its own) and written only into an element still in the document. mermaid.run lays a
    // diagram out inside the very element it is given: inside a container that is not displayed at that moment (the
    // operator docs between two chapters) it sets transform="translate(undefined, NaN)" on a group, which the browser
    // reports as a console error no catch can see, and the run rejects (V0599's proof, sbxbetaop: on /operator-docs/02,
    // chapter 01's diagram; reproduced with mermaid 12 in a display:none container, and clean with render()).
    for (const n of pending) {
      if (!n.isConnected || n.getAttribute('data-processed') === 'true') continue
      const code = dedentDiagram(n.textContent || '')
      if (!code) continue
      try {
        const { svg, bindFunctions } = await mermaid.render(`tp-mmd-${++renderSeq}`, code)
        if (!n.isConnected || n.getAttribute('data-processed') === 'true') continue   // the page moved on meanwhile
        n.innerHTML = svg
        n.setAttribute('data-processed', 'true')
        bindFunctions?.(n)
      } catch (err) {
        log.warn('a diagram did not render (non-fatal):', err)
      }
    }
  } catch (err) {
    // Downgrade to warn: rapid chapter navigation can race the Vue DOM swap
    // against mermaid's internal iteration. Diagrams still render correctly
    // on the next navigation tick — this is noise, not a user-facing failure.
    log.warn('render race (non-fatal):', err)
  }
}
