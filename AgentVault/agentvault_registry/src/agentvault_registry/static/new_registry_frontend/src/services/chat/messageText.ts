/**
 * V0652 (x) (order gwo_cedd900e6d50be18ce4eecf1): a chat message, readable at a glance.
 *
 * The maintainer (the sessions' room, seq 230): "I have a hard time reading this formatting honestly. This also needs
 * some formatting or something highlighting so I can actually fast read it." And his timestamp report (seq 243). So:
 *   - markdown: bold, italics, lists, inline code and code blocks, links, short headings; line breaks kept. Raw HTML is
 *     never markup: the parser escapes it (html: false, as the docs viewer reads its pages), and what it renders is
 *     sanitized again on a short allowlist (DOMPurify), so a message can never carry a script, a style or a handler.
 *   - a status tag at a message's start (DONE, FAIL, REQ, INFO, ORDER, ACK, BID) is a coloured chip;
 *   - a mention of the viewer stands out, other mentions are marked; ids and hashes (apr_..., gwo_..., did:...,
 *     sha256 and other long hex) are small and grey, whole on hover;
 *   - a long message folds after its first lines, with "show more";
 *   - every message carries its time: the local time today, the date before it otherwise, the full time with its zone
 *     on hover or tap.
 * Pure: no Vue, no fetch; the thread and its tests call it.
 */
import MarkdownIt, { type MarkdownIt as MarkdownItInstance } from 'markdown-it'
import DOMPurify from 'dompurify'

export const STATUS_TAGS = ['DONE', 'FAIL', 'REQ', 'INFO', 'ORDER', 'ACK', 'BID'] as const
export type StatusTag = typeof STATUS_TAGS[number]
const TAG_RE = new RegExp(`^\\s*(?:\\[)?(${STATUS_TAGS.join('|')})(?:\\])?(?=[\\s:.,-]|$)[:.,-]?\\s*`)

/** The tag a message opens with, and the body without it. A tag must stand alone ("DONE: x", "[FAIL] y", "ACK"), in
 *  capitals: "Done with it" and "information" are words, not tags. */
export function splitStatusTag(body: string): { tag: StatusTag | null; rest: string } {
  const m = TAG_RE.exec(body || '')
  if (!m) return { tag: null, rest: body || '' }
  return { tag: m[1] as StatusTag, rest: (body || '').slice(m[0].length) }
}

// what reads as an id: the platform's own prefixes, a DID, a sha256 (with or without its prefix), a long hex
const ID_RE = /\b(?:(?:apr|gwo|ctr|att|avreg|tok)_[0-9a-z]{8,}|did:[a-z0-9]+:[A-Za-z0-9.:%_-]{6,}|sha256:[0-9a-f]{12,64}|[0-9a-f]{16,64})\b/g

export interface RenderOptions {
  /** The labels (handle or name, without "@") that name the viewer: their mentions stand out. */
  meLabels?: string[]
  /** Every mention the server resolved for this message (labels without "@"), so a name that names nobody stays text. */
  mentionLabels?: string[]
}

function escapeRe(s: string): string { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') }

/** markdown-it on the docs viewer's terms (raw HTML off), breaks kept, links made from bare URLs, images off (a chat
 *  message shows a file as a file card, never an inline remote image). */
function makeMd(): MarkdownItInstance {
  const md = new MarkdownIt({ html: false, linkify: true, breaks: true, typographer: false })
  md.disable(['image', 'table', 'lheading'])
  const defaultLink = md.renderer.rules.link_open
    || ((tokens: any, idx: number, options: any, _env: any, self: any) => self.renderToken(tokens, idx, options))
  md.renderer.rules.link_open = (tokens: any, idx: number, options: any, env: any, self: any) => {
    tokens[idx].attrSet('target', '_blank')
    tokens[idx].attrSet('rel', 'noopener noreferrer nofollow')
    return defaultLink(tokens, idx, options, env, self)
  }
  // text runs: mentions and ids become spans; everything else stays escaped text
  const defaultText = md.renderer.rules.text!
  md.renderer.rules.text = (tokens: any, idx: number, options: any, env: any, self: any) => {
    const raw: string = tokens[idx].content
    return decorate(raw, env as RenderOptions, (s) => defaultText([{ ...tokens[idx], content: s }] as any, 0, options, env, self))
  }
  return md
}

function decorate(raw: string, env: RenderOptions, esc: (s: string) => string): string {
  const me = new Set((env.meLabels || []).filter(Boolean).map((l) => l.toLowerCase()))
  const known = (env.mentionLabels || []).filter(Boolean)
  const labels = [...new Set([...known, ...(env.meLabels || [])].filter(Boolean))]
  const parts: Array<{ at: number; end: number; html: string }> = []
  if (labels.length) {
    const re = new RegExp(`(^|[^\\w@])@(${labels.map(escapeRe).sort((a, b) => b.length - a.length).join('|')}|all|everyone)(?![\\w-])`, 'gi')
    let m: RegExpExecArray | null
    while ((m = re.exec(raw))) {
      const at = m.index + m[1].length
      const label = m[2]
      const mine = me.has(label.toLowerCase()) || label.toLowerCase() === 'all' || label.toLowerCase() === 'everyone'
      parts.push({ at, end: at + 1 + label.length,
        html: `<span class="${mine ? 'cm-mention cm-me' : 'cm-mention'}">${esc('@' + label)}</span>` })
    }
  }
  let m: RegExpExecArray | null
  ID_RE.lastIndex = 0
  while ((m = ID_RE.exec(raw))) {
    const at = m.index
    if (parts.some((p) => at < p.end && at + m![0].length > p.at)) continue
    parts.push({ at, end: at + m[0].length, html: `<span class="cm-id" title="${esc(m[0])}">${esc(m[0])}</span>` })
  }
  if (!parts.length) return esc(raw)
  parts.sort((a, b) => a.at - b.at)
  let out = ''
  let pos = 0
  for (const p of parts) {
    if (p.at < pos) continue
    out += esc(raw.slice(pos, p.at)) + p.html
    pos = p.end
  }
  return out + esc(raw.slice(pos))
}

let _md: MarkdownItInstance | null = null

const ALLOWED_TAGS = ['p', 'br', 'strong', 'em', 'del', 's', 'code', 'pre', 'ul', 'ol', 'li', 'a', 'blockquote', 'hr',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'span']
const ALLOWED_ATTR = ['href', 'title', 'class', 'target', 'rel', 'start']
/** Attributes whose values are not URIs: the link rule writes them, the URI rule must not judge them. */
export const URI_SAFE_ATTR = ['target', 'rel']

/** A message body as safe HTML: markdown on the docs viewer's terms, then sanitized on a short allowlist. */
export function renderMarkdown(body: string, opts: RenderOptions = {}): string {
  _md ??= makeMd()
  const html = _md.render(String(body ?? ''), { ...opts })   // markdown-it's env: the text rule reads the labels from it
  // A leading newline, taken off again after: DOMPurify under jsdom (the unit tests' DOM) drops the first element of an
  // input that starts with a tag ("<h1>Plan</h1>" came back as "Plan"); browsers keep it. With it, both agree, so the
  // tests see what a browser shows for a message (or a file) that opens with a heading, a list or a code block.
  return (DOMPurify.sanitize('\n' + html, {
    ALLOWED_TAGS, ALLOWED_ATTR,
    ALLOWED_URI_REGEXP: /^(?:https?:|mailto:|#|\/)/i,
    // target and rel are not on DOMPurify's URI-safe list, so a browser tests their values against the URI rule above
    // too: "_blank" and "noopener ..." failed it and both were dropped, and a link opened over the console (session-
    // tester's check 142 in Chromium, the sessions' room seq 616). jsdom kept them, so only a real browser saw it.
    ADD_URI_SAFE_ATTR: URI_SAFE_ATTR,
  }) as unknown as string).replace(/^\n/, '')
}

export interface RenderedMessage {
  tag: StatusTag | null
  html: string
  /** Long enough to fold after its first lines. */
  foldable: boolean
}

export const FOLD_LINES = 8
export const FOLD_CHARS = 700

/** The whole of it: the chip, the safe HTML of the rest, and whether it folds. */
export function renderMessage(body: string, opts: RenderOptions = {}): RenderedMessage {
  const { tag, rest } = splitStatusTag(String(body ?? ''))
  const lines = rest.split('\n').length
  return { tag, html: renderMarkdown(rest, opts), foldable: lines > FOLD_LINES || rest.length > FOLD_CHARS }
}

/** Does this message name the viewer (a mention the server resolved to them, or @all / @everyone)? */
export function namesViewer(m: { body?: string | null; mentions?: Array<{ key?: string }> | null },
                            myKey: string | null | undefined): boolean {
  if (myKey && Array.isArray(m?.mentions) && m.mentions.some((x) => x?.key === myKey)) return true
  return /(^|[^\w@])@(all|everyone)(?![\w-])/i.test(String(m?.body || ''))
}

/** Is this message an ask that waits on someone (an approval or a choice request)? */
export function isAsk(m: { kind?: string; card?: any } | null | undefined): boolean {
  const t = m?.kind === 'card' ? m?.card?.type : null
  return t === 'approval.request' || t === 'choice.request'
}

/** The time a message shows: "14:05" today, "30 Oct 14:05" before it, with the year when not this year. */
export function timeLabel(iso: string | null | undefined, nowMs: number, locale: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (!Number.isFinite(d.getTime())) return ''
  const now = new Date(nowMs)
  const time = d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })
  if (d.toDateString() === now.toDateString()) return time
  const date = d.toLocaleDateString(locale, d.getFullYear() === now.getFullYear()
    ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' })
  return `${date} ${time}`
}

/** The full time, with its zone, for the hover or tap. */
export function timeTitle(iso: string | null | undefined, locale: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (!Number.isFinite(d.getTime())) return ''
  return d.toLocaleString(locale, { dateStyle: 'full', timeStyle: 'long' })
}
