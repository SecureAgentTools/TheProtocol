/**
 * V0662 (OurChat lane): files pasted or dropped into the composer.
 *
 * A file is STAGED first (a chip above the box, a cross to take it back) and goes out with Send, never on the paste:
 * an image pasted by accident must not post itself to a room. These rules say what may be staged. They follow the
 * registry's own (`services/chat_media.py`: five MB, the types in ALLOWED_MIME) so a refusal comes from here, with a
 * reason, and not as a rejected upload after Send; the registry stays the final judge (`CHAT_MEDIA_MAX_BYTES` can be set
 * higher or lower on a registry, and its answer is shown as it words it).
 *
 * Pure: no DOM beyond the File fields it reads. The thread turns a reason into words.
 */

/** chat_media.MAX_BYTES: the registry's default cap on one file. */
export const MAX_FILE_BYTES = 5 * 1024 * 1024
/** Files staged for one send: a message is not a folder. */
export const MAX_STAGED = 5

export type FileKind = 'image' | 'pdf' | 'text'

/** chat_media.ALLOWED_MIME, with the kind each is shown as. SVG is not here on purpose: it can carry script. */
const MIME_KIND: Record<string, FileKind> = {
  'image/png': 'image',
  'image/jpeg': 'image',
  'image/webp': 'image',
  'image/gif': 'image',
  'application/pdf': 'pdf',
  'text/plain': 'text',
  'text/markdown': 'text',
  'application/json': 'text',
  'text/csv': 'text',
}

/** A browser often gives a markdown or a log file no type at all, or a generic one: the name settles it. */
const EXT_MIME: Record<string, string> = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif',
  pdf: 'application/pdf', txt: 'text/plain', log: 'text/plain', md: 'text/markdown', markdown: 'text/markdown',
  json: 'application/json', csv: 'text/csv',
}
const ALIASES: Record<string, string> = { 'text/x-markdown': 'text/markdown', 'text/x-log': 'text/plain', 'image/jpg': 'image/jpeg' }

export interface FileLike { name: string; type: string; size: number }

/** The type the file goes up as: the browser's, when it is one the registry takes, else the name's extension, else ''. */
export function mimeOf(f: Pick<FileLike, 'name' | 'type'>): string {
  const declared = ALIASES[(f.type || '').toLowerCase().split(';')[0].trim()] || (f.type || '').toLowerCase().split(';')[0].trim()
  if (MIME_KIND[declared]) return declared
  const ext = (f.name || '').toLowerCase().split('.').pop() || ''
  return (f.name || '').includes('.') ? (EXT_MIME[ext] || '') : ''
}

/** What the file chooser is told to offer (the `accept` attribute): every extension and every type the staging takes, built from
 *  the same two tables, so the chooser and the rules cannot disagree. It is a convenience only: the staging judges again. */
export const ACCEPT = [...Object.keys(EXT_MIME).map((e) => `.${e}`), ...Object.keys(MIME_KIND)].join(',')

export type Refusal = 'empty' | 'too_big' | 'type' | 'too_many'
export type Verdict = { ok: true; mime: string; kind: FileKind } | { ok: false; reason: Refusal }

/** May this file be staged, given how many already are? */
export function classify(f: FileLike, alreadyStaged: number): Verdict {
  if (alreadyStaged >= MAX_STAGED) return { ok: false, reason: 'too_many' }
  if (!f.size) return { ok: false, reason: 'empty' }
  if (f.size > MAX_FILE_BYTES) return { ok: false, reason: 'too_big' }
  const mime = mimeOf(f)
  const kind = MIME_KIND[mime]
  return kind ? { ok: true, mime, kind } : { ok: false, reason: 'type' }
}

/** A size a person reads: 412 B, 3.2 KB, 1.4 MB. */
export function humanSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return ''
  if (bytes < 1024) return `${Math.round(bytes)} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** The files a paste or a drop carries: the `files` list, else file items. An empty list means it is plain text. */
export function filesOf(t: { files?: ArrayLike<File> | null; items?: ArrayLike<{ kind: string; getAsFile?: () => File | null }> | null } | null | undefined): File[] {
  if (!t) return []
  const direct = Array.from(t.files || [])
  if (direct.length) return direct
  const out: File[] = []
  for (const it of Array.from(t.items || [])) {
    if (it && it.kind === 'file') { const f = it.getAsFile?.(); if (f) out.push(f) }
  }
  return out
}
