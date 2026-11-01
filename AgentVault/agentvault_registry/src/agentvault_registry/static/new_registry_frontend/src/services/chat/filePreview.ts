/**
 * V0652 (ae) (order gwo_5b9de9adb052d681ca95853d): a text file in a thread, read without downloading it.
 *
 * The maintainer (the sessions' room, seq 265): "can you print like a preview from the context of the file on the
 * card? ... otherwise i would always have to download it to see whats in it if its an md or txt file or json". The
 * registry writes a text file's first lines into its card (services/chat_media.text_preview); this module is how a
 * client shows them and how "Open" shows the whole file in the thread: Markdown rendered on the chat's own terms
 * (messageText.renderMarkdown: raw HTML is text, the result sanitized again), JSON pretty-printed, CSV, logs and plain
 * text as text, never as markup. Pure: no Vue, no fetch.
 */
import { type FileKind } from './cards'
import { renderMarkdown } from './messageText'

export { FILE_KINDS, TEXT_MIMES, type FileKind } from './cards'

/** The most "Open" shows of a file; the rest is a download away. */
export const OPEN_MAX_CHARS = 200_000

const KIND_BY_EXT: Array<[string, FileKind]> = [
  ['.md', 'markdown'], ['.markdown', 'markdown'], ['.json', 'json'], ['.csv', 'csv'], ['.log', 'log'],
]

/** How a text file is shown (the registry's chat_media.preview_kind, the same rule). */
export function fileKind(mime: string, name: string): FileKind {
  if (mime === 'text/markdown') return 'markdown'
  if (mime === 'application/json') return 'json'
  if (mime === 'text/csv') return 'csv'
  let n = String(name || '').toLowerCase()
  if (n.endsWith('.txt')) n = n.slice(0, -4)       // chat_link names a .md sent to an older registry FILE.md.txt
  return KIND_BY_EXT.find(([ext]) => n.endsWith(ext))?.[1] ?? 'text'
}

// eslint-disable-next-line no-control-regex -- a terminal's colour codes, in logs
const ANSI = /\x1b\[[0-?]*[ -/]*[@-~]/g
// eslint-disable-next-line no-control-regex -- the control characters a text file does not show
const CONTROL = /[\x00-\x08\x0b\x0e-\x1f\x7f]/g

/** A file's text as it is shown: its line ends made one, a log's colour codes and stray control characters dropped. */
export function cleanText(s: string): string {
  return s.replace(/\r\n?/g, '\n').replace(ANSI, '').replace(CONTROL, '')
}

/** JSON, pretty-printed when it parses; otherwise as it is. */
export function prettyJson(s: string): string {
  try {
    return JSON.stringify(JSON.parse(s), null, 2)
  } catch {
    return s
  }
}

export interface OpenedFile {
  kind: FileKind
  /** the text shown (for markdown, its source) */
  text: string
  /** markdown only: the sanitized HTML */
  html: string
  /** more of the file than is shown */
  cut: boolean
  /** not text after all: nothing is shown */
  binary: boolean
}

/** The whole file, as "Open" shows it in the thread: at most `max` characters, cut at a line end. */
export function openedFile(bytes: ArrayBuffer | Uint8Array, mime: string, name: string,
                           max: number = OPEN_MAX_CHARS): OpenedFile {
  const kind = fileKind(mime, name)
  let raw: string
  try {
    raw = new TextDecoder('utf-8', { fatal: true }).decode(bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes))
  } catch {
    return { kind, text: '', html: '', cut: false, binary: true }
  }
  if (raw.includes('\u0000')) return { kind, text: '', html: '', cut: false, binary: true }
  let text = cleanText(raw)
  if (kind === 'json') text = prettyJson(text)
  let cut = false
  if (text.length > max) {
    const end = text.lastIndexOf('\n', max)
    text = text.slice(0, end > max / 2 ? end : max)
    cut = true
  }
  return { kind, text, html: kind === 'markdown' ? renderMarkdown(text) : '', cut, binary: false }
}

/** A card's preview as HTML: markdown rendered and sanitized; '' for the other kinds, which are shown as text. */
export function previewHtml(preview: string | null | undefined, kind: FileKind | null | undefined): string {
  return preview && kind === 'markdown' ? renderMarkdown(preview) : ''
}
