/**
 * Client-side fuzzy search index for the Oracle docs.
 *
 * Splits every chapter into sections (one per h2/h3/h4), indexes each section's
 * chapter title + heading + body, and returns ranked results with a snippet
 * highlighting the matched term.
 */

import MiniSearch, { type SearchResult as MiniSearchResult } from 'minisearch'
import { slugify } from './useDocsMarkdown'
import { applySwitchBlocks, type KnownSwitches } from './switchBlocks'

export interface SearchableChapter {
  id: string
  number: string
  title: string
  subtitle?: string
  content: string
}

export interface DocsSearchResult {
  id: string
  chapterId: string
  chapterNumber: string
  chapterTitle: string
  headingText: string | null
  headingSlug: string | null
  snippet: string
  score: number
  matchedTerms: string[]
}

interface IndexEntry {
  id: string
  chapterId: string
  chapterNumber: string
  chapterTitle: string
  headingText: string | null
  headingSlug: string | null
  body: string
}

function stripMarkdown(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/[*_]{1,3}([^*_]+)[*_]{1,3}/g, '$1')
    .replace(/^>\s+/gm, '')
    .replace(/^[-*+]\s+/gm, '')
    .replace(/^\d+\.\s+/gm, '')
    .replace(/\|/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function buildEntries(chapters: SearchableChapter[], switches: KnownSwitches): IndexEntry[] {
  const entries: IndexEntry[] = []

  for (const ch of chapters) {
    // search finds only what the page shows: a part this registry leaves out is not indexed (switchBlocks.ts)
    const lines = applySwitchBlocks(ch.content, switches).text.split('\n')
    // Dedup repeated heading slugs the way markdown-it-anchor does in the DOM
    // ("how-it-works", "how-it-works-1", …) — entry ids are keyed on the slug and
    // MiniSearch throws on a duplicate id, which took the whole docs view down.
    const seenSlugs = new Map<string, number>()
    let inFence = false
    let currentHeading: { text: string; slug: string } | null = null
    let buffer: string[] = []

    const flush = () => {
      const bodyRaw = buffer.join('\n').trim()
      if (!bodyRaw && !currentHeading) return
      const body = stripMarkdown(bodyRaw)
      if (!body && !currentHeading) return
      entries.push({
        id: `${ch.id}::${currentHeading?.slug ?? 'intro'}`,
        chapterId: ch.id,
        chapterNumber: ch.number,
        chapterTitle: ch.title,
        headingText: currentHeading?.text ?? null,
        headingSlug: currentHeading?.slug ?? null,
        body,
      })
    }

    for (const raw of lines) {
      const line = raw.replace(/\r$/, '')
      if (/^\s*```/.test(line)) {
        inFence = !inFence
        buffer.push(line)
        continue
      }
      const m = !inFence ? line.match(/^(#{2,4}) +(.+?)\s*#*\s*$/) : null
      if (m) {
        flush()
        buffer = []
        const text = m[2].trim()
        const base = slugify(text)
        const n = seenSlugs.get(base) ?? 0
        seenSlugs.set(base, n + 1)
        currentHeading = { text, slug: n === 0 ? base : `${base}-${n}` }
      } else {
        buffer.push(line)
      }
    }
    flush()
  }

  return entries
}

function extractSnippet(body: string, terms: string[]): string {
  if (!body) return ''
  const lower = body.toLowerCase()
  let bestIdx = -1
  let bestTerm = ''
  for (const t of terms) {
    if (!t) continue
    const idx = lower.indexOf(t.toLowerCase())
    if (idx !== -1 && (bestIdx === -1 || idx < bestIdx)) {
      bestIdx = idx
      bestTerm = t
    }
  }
  const SPAN = 140
  let start = bestIdx === -1 ? 0 : Math.max(0, bestIdx - 60)
  let end = Math.min(body.length, start + SPAN)
  if (end - start < SPAN) start = Math.max(0, end - SPAN)
  let snippet = body.slice(start, end)
  if (start > 0) snippet = '… ' + snippet
  if (end < body.length) snippet = snippet + ' …'
  if (bestTerm) {
    const re = new RegExp(`(${bestTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
    snippet = snippet.replace(re, '<mark>$1</mark>')
  }
  return snippet
}

// §OPDOCS (2026-08-02): the index used to be a single module-level cache, which
// was correct while the Oracle was the only consumer. The Operator docs view now
// builds its own index, and a shared singleton would have meant "visit the Oracle
// first and operator search silently returns Oracle chapters". Namespaced, with
// 'oracle' as the default so every existing caller behaves byte-identically.
interface NamespaceState {
  index: MiniSearch<IndexEntry>
  entries: IndexEntry[]
  /** the switches the index was built for: a registry config that answers later rebuilds it */
  switchKey: string
}
const _namespaces = new Map<string, NamespaceState>()

export function buildSearchIndex(chapters: SearchableChapter[], namespace = 'oracle', switches: KnownSwitches = {}): void {
  const switchKey = JSON.stringify(Object.entries(switches).sort())
  if (_namespaces.get(namespace)?.switchKey === switchKey) return
  // Never throw: search is an enhancement — a bad entry must degrade to
  // "no results", not take the entire docs view down through the error boundary
  // (which is exactly what a duplicate-id MiniSearch throw did on first deploy).
  try {
    const entries = buildEntries(chapters, switches)
    const index = new MiniSearch<IndexEntry>({
      fields: ['chapterTitle', 'headingText', 'body'],
      storeFields: [
        'chapterId',
        'chapterNumber',
        'chapterTitle',
        'headingText',
        'headingSlug',
        'body',
      ],
      searchOptions: {
        fuzzy: 0.2,
        prefix: true,
        boost: { chapterTitle: 2, headingText: 4, body: 1 },
        combineWith: 'AND',
      },
    })
    index.addAll(entries)
    _namespaces.set(namespace, { index, entries, switchKey })
  } catch (err) {
    console.error(`[docs-search] failed to build "${namespace}" index; search disabled:`, err)
  }
}

export function searchDocs(query: string, limit = 12, namespace = 'oracle'): DocsSearchResult[] {
  const state = _namespaces.get(namespace)
  if (!state || !query.trim()) return []
  const raw = state.index.search(query) as (MiniSearchResult & IndexEntry)[]
  return raw.slice(0, limit).map((r) => ({
    id: r.id,
    chapterId: r.chapterId,
    chapterNumber: r.chapterNumber,
    chapterTitle: r.chapterTitle,
    headingText: r.headingText,
    headingSlug: r.headingSlug,
    snippet: extractSnippet(r.body, r.terms ?? []),
    score: r.score,
    matchedTerms: r.terms ?? [],
  }))
}

/** Suggested queries for the empty-state of the command palette. */
export const DEFAULT_SEARCH_SUGGESTIONS: string[] = [
  'staking',
  'federation',
  'transfer',
  'governance',
  'a2a payment',
  'mcp tools',
  'zkp attestation',
]
