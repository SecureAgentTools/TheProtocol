/**
 * Shared Markdown renderer for the Whitepaper and Oracle Docs views.
 *
 * Replaces the two near-identical custom regex renderers with a single
 * markdown-it pipeline configurable per-view via a CSS class prefix:
 *   - `wp` → matches the whitepaper's existing `.wp-*` scoped CSS
 *   - `orc` → matches the Oracle's existing `.orc-*` scoped CSS
 *
 * What this replaces and what it adds:
 *   - Same visible output as the old regex renderer (by design — no CSS churn)
 *   - Robust list/table/escape handling (the old regex had edge cases)
 *   - Auto heading IDs on h1–h4 when `headingAnchors: true`
 *   - ```mermaid blocks become `<div class="{prefix}-mermaid mermaid">…</div>`
 *     and are picked up by `useMermaidRenderer`
 *   - a ```mermaid block followed directly by an ```archmap block becomes an
 *     explorable figure (archmap.ts renders it, useArchFigures.ts wires it)
 */

import MarkdownIt, { type MarkdownIt as MarkdownItInstance } from 'markdown-it'
import anchor from 'markdown-it-anchor'
import container from 'markdown-it-container'
import { renderArchFigure, renderOrphanArchmap, type ArchLabels, DEFAULT_ARCH_LABELS } from './archmap'
import { applySwitchBlocks, type KnownSwitches } from './switchBlocks'

export type DocsClassPrefix = 'wp' | 'orc' | 'opd'

export interface UseDocsMarkdownOptions {
  classPrefix: DocsClassPrefix
  headingAnchors?: boolean
  /** The figure's UI words, already translated by the view; English when omitted. */
  archLabels?: ArchLabels
  /** What this registry said about the switches a doc's parts follow (switchBlocks.ts); a part whose switch is not
   *  said on is left out, so a caller that passes nothing shows only what every registry runs. */
  switches?: KnownSwitches
}

/**
 * Slugify matching the whitepaper's original implementation so TOC deep-links
 * continue to work after the renderer swap.
 */
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/[\s_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

/**
 * Strip YAML frontmatter (`--- ... ---`) from the top of a markdown file.
 * Kept here so both views can share the helper.
 */
export function stripFrontmatter(md: string): string {
  if (md.startsWith('---')) {
    const end = md.indexOf('\n---', 3)
    if (end !== -1) {
      return md.slice(end + 4).replace(/^\s+/, '')
    }
  }
  return md
}

export function createDocsMarkdown(opts: UseDocsMarkdownOptions): MarkdownItInstance {
  const prefix = opts.classPrefix

  const md = new MarkdownIt({
    html: false,
    linkify: false,
    breaks: false,
    typographer: false,
  })

  if (opts.headingAnchors) {
    md.use(anchor, {
      slugify,
    })
  }

  // Callout containers: ::: tip / warn / info / note — see §6.2 doc template. D6-257: 'warning' and 'danger', the names
  // the docs site (VitePress) knows, render as a warning here too, so a page written for either renderer shows a
  // callout, never its literal ':::' line.
  const CALLOUT_KINDS = ['tip', 'warn', 'info', 'note', 'warning', 'danger'] as const
  const CALLOUT_CLASS: Record<string, string> = { warning: 'warn', danger: 'warn' }
  const CALLOUT_LABELS: Record<string, string> = {
    tip: 'Tip',
    warn: 'Warning',
    info: 'Info',
    note: 'Note',
    warning: 'Warning',
    danger: 'Danger',
  }
  for (const kind of CALLOUT_KINDS) {
    md.use(container, kind, {
      render(tokens: { nesting: number; info: string }[], idx: number) {
        const token = tokens[idx]
        if (token.nesting === 1) {
          // Optional inline title after the keyword: "::: tip Custom title"
          const raw = token.info.trim().slice(kind.length).trim()
          const label = raw || CALLOUT_LABELS[kind]
          const escLabel = md.utils.escapeHtml(label)
          return `<aside class="${prefix}-callout ${prefix}-callout-${CALLOUT_CLASS[kind] || kind}"><div class="${prefix}-callout-head"><span class="${prefix}-callout-icon" aria-hidden="true"></span><span class="${prefix}-callout-label">${escLabel}</span></div><div class="${prefix}-callout-body">\n`
        }
        return '</div></aside>\n'
      },
    })
  }

  const fenceDefault = md.renderer.rules.fence

  md.renderer.rules.fence = (tokens, idx, options, env, self) => {
    const token = tokens[idx]
    const info = (token.info || '').trim()
    const lang = info.split(/\s+/)[0] || 'text'
    const content = token.content

    if (lang === 'mermaid') {
      const next = tokens[idx + 1]
      if (next && next.type === 'fence' && (next.info || '').trim().split(/\s+/)[0] === 'archmap') {
        return renderArchFigure(content, next.content, prefix, md.utils.escapeHtml, opts.archLabels ?? DEFAULT_ARCH_LABELS)
      }
      const escaped = md.utils.escapeHtml(content.replace(/\n+$/, ''))
      return `<div class="${prefix}-mermaid mermaid">${escaped}</div>`
    }

    if (lang === 'archmap') {
      // Rendered by the mermaid fence it explains (above); on its own it is a mistake.
      const prev = tokens[idx - 1]
      const explained = prev && prev.type === 'fence' && (prev.info || '').trim().split(/\s+/)[0] === 'mermaid'
      return explained ? '' : renderOrphanArchmap(prefix, md.utils.escapeHtml)
    }

    const cleaned = md.utils.escapeHtml(
      content.replace(/\r\n/g, '\n').replace(/\n+$/, '')
    )
    const langLabel = lang === 'text' ? '' : lang.toUpperCase()
    return (
      `<div class="${prefix}-code-wrap">` +
      `<button type="button" class="${prefix}-code-copy" data-action="copy-code" aria-label="Copy code to clipboard">Copy</button>` +
      `<span class="${prefix}-code-lang" aria-hidden="true">${md.utils.escapeHtml(langLabel)}</span>` +
      // tabindex: a code block or table that scrolls sideways (on a phone) must be reachable by keyboard (axe
      // scrollable-region-focusable, §FESUITE's phone sweep 2026-10-03)
      `<pre class="${prefix}-code" tabindex="0"><code class="language-${md.utils.escapeHtml(lang)}">${cleaned}</code></pre>` +
      `</div>`
    )
  }

  md.renderer.rules.code_inline = (tokens, idx) => {
    return `<code class="${prefix}-ic">${md.utils.escapeHtml(tokens[idx].content)}</code>`
  }

  md.renderer.rules.table_open = () => `<div class="${prefix}-tbl-wrap" tabindex="0"><table>`
  md.renderer.rules.table_close = () => `</table></div>`

  md.renderer.rules.ordered_list_open = () => `<ol class="${prefix}-ol">`

  return md
}

export function renderDocsMarkdown(source: string, opts: UseDocsMarkdownOptions): string {
  const md = createDocsMarkdown(opts)
  return md.render(applySwitchBlocks(source, opts.switches ?? {}).text)
}

export interface DocsHeading {
  level: 2 | 3 | 4
  slug: string
  text: string
}

/**
 * Extract h2/h3/h4 headings from a markdown source.
 * - Skips headings inside fenced code blocks (``` … ```)
 * - Emits slugs identical to those produced by markdown-it-anchor (same slugify,
 *   same duplicate handling: the second "How it works" renders id "how-it-works-1",
 *   so repeated headings must be deduped here too or TOC links jump to the first
 *   occurrence — and downstream consumers keying on the slug collide)
 * - h1 is intentionally excluded — it is the chapter title / whitepaper title
 */
export function extractHeadings(source: string, switches: KnownSwitches = {}): DocsHeading[] {
  const headings: DocsHeading[] = []
  // a heading inside a part this registry leaves out is not in the page, so it is not in the table of contents
  const lines = applySwitchBlocks(source, switches).text.split('\n')
  const seen = new Map<string, number>()
  let inFence = false
  for (const raw of lines) {
    const line = raw.replace(/\r$/, '')
    if (/^\s*```/.test(line)) {
      inFence = !inFence
      continue
    }
    if (inFence) continue
    const m = line.match(/^(#{2,4}) +(.+?)\s*#*\s*$/)
    if (!m) continue
    const level = m[1].length as 2 | 3 | 4
    const text = m[2].trim()
    if (!text) continue
    const base = slugify(text)
    const n = seen.get(base) ?? 0
    seen.set(base, n + 1)
    headings.push({ level, slug: n === 0 ? base : `${base}-${n}`, text })
  }
  return headings
}
