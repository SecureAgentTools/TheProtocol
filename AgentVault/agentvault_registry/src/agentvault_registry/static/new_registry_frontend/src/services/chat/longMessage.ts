/**
 * V0662 (OurChat lane): a message past the cap goes as a document.
 *
 * THE CAP IS IN BYTES, NOT CHARACTERS. `chat_service.BODY_MAX_BYTES` is 4096 and it counts the UTF-8 encoding of the
 * body (`len(body.encode("utf-8"))`), so German text, accents and emoji reach it long before the same number of
 * characters would: 2,100 letters "ä" are already 4,200 bytes. The wider 8,192 on the request model
 * (routers/chat.py) is characters and is NOT the limit a person meets. A counter that counts characters shows
 * "room left" on a message the server will refuse.
 *
 * Past the cap the composer does what chat_link has done above 1,500 characters since v2.6, in the same three steps:
 * upload the whole text as a markdown file, post the media card the upload returns, then post ONE line, the first
 * non-empty line of the text plus the file's name and size. The steps are chat_link's (`post_card`); the line's wording
 * differs from chat_link's in two ways a reader asked for: it ends in an ellipsis, and it does not repeat the attachment id.
 *
 * Pure: no DOM, no network, no clock (the caller hands in `now`). The upload and the sends are the thread's.
 */

/** chat_service.BODY_MAX_BYTES: the registry refuses a text body over this many UTF-8 bytes. */
export const BODY_MAX_BYTES = 4096
/** From here the composer shows its counter, about 85% of the cap (his plan: "from about 3,500"). */
export const COUNTER_FROM_BYTES = 3500
/** The room keeps one line of a long message: its first non-empty line, cut at this many CHARACTERS (chat_link: 300). */
export const SUMMARY_LIMIT = 300

const encoder = new TextEncoder()

/**
 * The UTF-8 length of `text`, the way the registry counts. A lone surrogate encodes to U+FFFD (3 bytes) here and is
 * dropped by the server's `errors="ignore"`, so the count can only be a little too HIGH for such text, never too low:
 * the safe side for a limit.
 */
export function utf8Bytes(text: string): number {
  return encoder.encode(text).length
}

export interface LengthState {
  /** What would be sent, in bytes (the composer's text trimmed, as `send()` posts it). */
  bytes: number
  /** Bytes left under the cap; negative once past it. */
  remaining: number
  /** Past the cap: Send becomes Send as document. */
  over: boolean
  /** The counter is on screen. */
  showCounter: boolean
}

/** Where the composer stands against the cap. `text` is the raw composer value; the trim is the one `send()` makes. */
export function lengthState(text: string): LengthState {
  const bytes = utf8Bytes((text || '').trim())
  return {
    bytes,
    remaining: BODY_MAX_BYTES - bytes,
    over: bytes > BODY_MAX_BYTES,
    showCounter: bytes >= COUNTER_FROM_BYTES,
  }
}

/**
 * The one line a long message leaves in the room: its first non-empty line, cut at `limit` CHARACTERS and ended with an
 * ellipsis. Counted in code points, so a cut never splits an emoji into a lone half.
 */
export function summaryLine(text: string, limit = SUMMARY_LIMIT): string {
  const first = (text || '').split(/\r?\n/).map((l) => l.trim()).find((l) => l !== '') || ''
  const points = Array.from(first)
  return points.length <= limit ? first : points.slice(0, limit - 1).join('') + '…'
}

const two = (n: number): string => String(n).padStart(2, '0')

/** `message-YYYYMMDD-HHMMSS.md` in UTC, so the same instant names the same file on every machine. */
export function documentName(now: Date): string {
  return `message-${now.getUTCFullYear()}${two(now.getUTCMonth() + 1)}${two(now.getUTCDate())}`
    + `-${two(now.getUTCHours())}${two(now.getUTCMinutes())}${two(now.getUTCSeconds())}.md`
}

export interface LongDocument {
  file: File
  name: string
  /** The file's size in bytes: the same count the registry would have made of the text. */
  bytes: number
  /** The line the room keeps. */
  summary: string
}

/** The text as a markdown file: the file to upload, its name, its size and the line the room keeps. */
export function documentFor(text: string, now: Date): LongDocument {
  const body = (text || '').trim()
  const name = documentName(now)
  return {
    file: new File([body], name, { type: 'text/markdown' }),
    name,
    bytes: utf8Bytes(body),
    summary: summaryLine(body),
  }
}

/**
 * The text posted after the file's card: the summary and which file holds the whole message, by name and size. The
 * attachment's id is not in the line: the card above it carries it, and a reader does not need it.
 */
export function postedLine(summary: string, name: string, bytes: number): string {
  return `${summary} (the whole message: ${name}, ${bytes} bytes)`
}
