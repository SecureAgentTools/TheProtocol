// V0664 C4 (order gwo_85a6015257385f6bb010682e): the TypeScript port of the proxy's VALUE NODES, so a console can show what a mapping
// does to a sample record without a server and without the sample leaving the browser.
//
// The truth is the SDK's mapping.py (the chain's final file, stack v0664/stack-cut 300a3bed): its VALUE_KEYS, the order of the
// steps, every `as`, concat, and the refusal texts that name the mapping's field and the rule, never the record's value. This
// file follows it line by line and is tested against vectors produced by RUNNING that Python (mapping.test.ts); a case that
// disagrees fails there. A mapping's other half (a spec's sources, actions, sinks) is not here.
//
// The steps, in order: read the path (missing: `default` if given; `required: false` gives null; else refused) -> null_if -> trim ->
// case -> regex + group -> map + map_default -> as -> round (half to even, on an exact decimal). A null stays null through the rest.
//
// Where JavaScript cannot be Python, and what is done: numbers are one type (a payload's 1.0 reads as 1); a Decimal is an exact
// coefficient and exponent here (decimal.ts-style, no precision cap), printed the way Python prints one; a regex is JavaScript's
// (the `(?P<name>` spelling is rewritten); a time zone is the browser's IANA database; strptime is Python's directive set.

export class MappingRefused extends Error {
  detail: string
  constructor(detail: string) { super(detail); this.detail = detail; this.name = 'MappingRefused' }
}

export const VALUE_KEYS = new Set(['path', 'default', 'required', 'as', 'format', 'tz', 'trim', 'case', 'map', 'map_default', 'null_if',
  'round', 'regex', 'group', 'concat', 'sep'])
export const AS_TYPES = ['text', 'int', 'decimal', 'float', 'bool', 'date', 'datetime', 'json'] as const
export const CASES = ['upper', 'lower', 'title'] as const
const NUMERIC_AS = ['int', 'decimal', 'float']
const BOOLS: Record<string, boolean> = { true: true, false: false, '1': true, '0': false, yes: true, no: false }
const INT = /^[+-]?[0-9]+$/

type Json = any
const MISSING = undefined
const isObj = (v: any): v is Record<string, any> => v !== null && typeof v === 'object' && !Array.isArray(v)
const isNum = (v: any): v is number => typeof v === 'number'

export function isValueNode(node: Json): boolean {
  if (!isObj(node)) return false
  const keys = Object.keys(node)
  if (!keys.length || !keys.every((k) => VALUE_KEYS.has(k))) return false
  return (typeof node.path === 'string' && node.path.startsWith('$')) || Array.isArray(node.concat)
}

// ── a decimal: sign, coefficient, exponent ───────────────────────────────────────────────────────────────────────────

export class Dec {
  constructor(readonly neg: boolean, readonly coef: bigint, readonly exp: number) {}

  /** Python's Decimal(str): digits with an optional point and exponent; NaN and Infinity are not finite (null). */
  static parse(text: string): Dec | null {
    const m = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(text)
    if (!m || (!m[2] && !m[3])) return null
    const frac = m[3] || ''
    return new Dec(m[1] === '-', BigInt((m[2] || '') + frac || '0'), (m[4] ? parseInt(m[4], 10) : 0) - frac.length)
  }

  /** The scientific string Python's str(Decimal) gives: plain unless the exponent is positive or the adjusted one is below -6. */
  toString(): string {
    const s = this.coef.toString()
    const adjusted = this.exp + s.length - 1
    const sign = this.neg ? '-' : ''
    if (this.exp <= 0 && adjusted >= -6) {
      if (this.exp === 0) return sign + s
      const point = s.length + this.exp
      if (point > 0) return sign + s.slice(0, point) + '.' + s.slice(point)
      return sign + '0.' + '0'.repeat(-point) + s
    }
    const mant = s.length > 1 ? s[0] + '.' + s.slice(1) : s
    return sign + mant + 'E' + (adjusted >= 0 ? '+' : '-') + Math.abs(adjusted)
  }

  toNumber(): number { return Number(`${this.neg ? '-' : ''}${this.coef}e${this.exp}`) }

  /** quantize to the exponent `q` with ROUND_HALF_EVEN (the sign of a zero is kept, as Python keeps it). */
  quantize(q: number): Dec {
    if (this.exp >= q) return new Dec(this.neg, this.coef * 10n ** BigInt(this.exp - q), q)
    const div = 10n ** BigInt(q - this.exp)
    let quo = this.coef / div
    const rem = this.coef % div
    const twice = rem * 2n
    if (twice > div || (twice === div && quo % 2n === 1n)) quo += 1n
    return new Dec(this.neg, quo, q)
  }
}

// ── Python's str.title(): a letter after a non-letter (or the start) is capitalized, a letter after a letter lowered ─────

const cased = (c: string) => c.toLowerCase() !== c.toUpperCase()
const TITLE_SPECIAL: Record<string, string> = { 'ß': 'Ss' }
function pyTitle(s: string): string {
  let out = ''
  let prev = false
  for (const ch of s) {
    const isCased = cased(ch) || ch in TITLE_SPECIAL
    out += isCased ? (prev ? ch.toLowerCase() : (TITLE_SPECIAL[ch] ?? ch.toUpperCase())) : ch
    prev = isCased
  }
  return out
}

// ── dates: ISO, strptime, zones ──────────────────────────────────────────────────────────────────────────────────────

interface Stamp { y: number; mo: number; d: number; h: number; mi: number; s: number; us: number; off: number | null /* minutes east of UTC */ }

const pad = (n: number, w = 2) => String(n).padStart(w, '0')
const leap = (y: number) => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0
const dim = (y: number, mo: number) => [31, leap(y) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1]

function valid(st: Stamp): boolean {
  return st.y >= 1 && st.y <= 9999 && st.mo >= 1 && st.mo <= 12 && st.d >= 1 && st.d <= dim(st.y, st.mo)
    && st.h >= 0 && st.h <= 23 && st.mi >= 0 && st.mi <= 59 && st.s >= 0 && st.s <= 59
}

/** An ISO 8601 date or datetime the way Python 3.11+ reads one: a Z or an offset, a T or a space, a fraction, the basic form. */
function parseIso(text: string): Stamp | null {
  let t = text.trim()
  let off: number | null = null
  const z = /([Zz]|[+-]\d{2}(?::?\d{2}(?::?\d{2})?)?)$/.exec(t)
  if (z && t.length > 10) {
    const tz = z[1]
    if (/^[Zz]$/.test(tz)) off = 0
    else {
      const sign = tz[0] === '-' ? -1 : 1
      const digits = tz.slice(1).replace(/:/g, '')
      off = sign * (parseInt(digits.slice(0, 2), 10) * 60 + parseInt(digits.slice(2, 4) || '0', 10))
    }
    t = t.slice(0, t.length - tz.length)
  }
  const m = /^(\d{4})-?(\d{2})-?(\d{2})(?:[T ](\d{2})(?::?(\d{2})(?::?(\d{2})(?:[.,](\d{1,9}))?)?)?)?$/.exec(t)
  if (!m) return null
  const st: Stamp = { y: +m[1], mo: +m[2], d: +m[3], h: +(m[4] || 0), mi: +(m[5] || 0), s: +(m[6] || 0),
    us: m[7] ? parseInt((m[7] + '000000').slice(0, 6), 10) : 0, off }
  if (m[4] === undefined && off !== null) return null           // an offset on a bare date is not ISO
  return valid(st) ? st : null
}

const MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']
const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

/** Python's strptime for the directives a legacy export uses: %Y %y %m %d %H %I %M %S %f %p %b %B %a %A %z %j %% and whitespace. */
function strptime(text: string, fmt: string): Stamp | null {
  let pattern = ''
  const groups: string[] = []
  for (let i = 0; i < fmt.length; i++) {
    const c = fmt[i]
    if (c === '%') {
      const d = fmt[++i]
      const add = (name: string, rx: string) => { groups.push(name); pattern += `(${rx})` }
      switch (d) {
        case 'Y': add('Y', '\\d\\d\\d\\d'); break
        case 'y': add('y', '\\d\\d'); break
        case 'm': add('m', '1[0-2]|0[1-9]|[1-9]'); break
        case 'd': add('d', '3[0-1]|[1-2]\\d|0[1-9]|[1-9]| [1-9]'); break
        case 'H': add('H', '2[0-3]|[0-1]\\d|\\d'); break
        case 'I': add('I', '1[0-2]|0[1-9]|[1-9]'); break
        case 'M': add('M', '[0-5]\\d|\\d'); break
        case 'S': add('S', '6[0-1]|[0-5]\\d|\\d'); break
        case 'f': add('f', '[0-9]{1,6}'); break
        case 'p': add('p', 'am|pm'); break
        case 'j': add('j', '36[0-6]|3[0-5]\\d|[1-2]\\d\\d|0[1-9]\\d|00[1-9]|[1-9]\\d|0[1-9]|[1-9]'); break
        case 'B': add('B', MONTHS.join('|')); break
        case 'b': add('b', MONTHS.map((m) => m.slice(0, 3)).join('|')); break
        case 'A': add('A', DAYS.join('|')); break
        case 'a': add('a', DAYS.map((m) => m.slice(0, 3)).join('|')); break
        case 'z': add('z', '[+-]\\d\\d:?[0-5]\\d(?::?[0-5]\\d(?:\\.\\d{1,6})?)?|Z'); break
        case '%': pattern += '%'; break
        default: return null
      }
    } else if (/\s/.test(c)) {
      pattern += '\\s+'
      while (/\s/.test(fmt[i + 1] || 'x')) i++
    } else pattern += c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  }
  const m = new RegExp(`^(?:${pattern})$`, 'i').exec(text)
  if (!m) return null
  const st: Stamp = { y: 1900, mo: 1, d: 1, h: 0, mi: 0, s: 0, us: 0, off: null }
  let pm: boolean | null = null
  let hour12: number | null = null
  let jday = null as number | null          // assigned in the switch below: without the cast TS narrows it to null and then never
  let yy: number | null = null
  groups.forEach((g, idx) => {
    const v = m[idx + 1]
    if (v === undefined) return
    switch (g) {
      case 'Y': st.y = +v; break
      case 'y': yy = +v; break
      case 'm': st.mo = +v; break
      case 'd': st.d = +v.trim(); break
      case 'H': st.h = +v; break
      case 'I': hour12 = +v; break
      case 'M': st.mi = +v; break
      case 'S': st.s = Math.min(+v, 59); break
      case 'f': st.us = parseInt((v + '000000').slice(0, 6), 10); break
      case 'p': pm = v.toLowerCase() === 'pm'; break
      case 'j': jday = +v; break
      case 'B': st.mo = MONTHS.indexOf(v.toLowerCase()) + 1; break
      case 'b': st.mo = MONTHS.findIndex((x) => x.slice(0, 3) === v.toLowerCase()) + 1; break
      case 'z': {
        if (v.toUpperCase() === 'Z') { st.off = 0; break }
        const sign = v[0] === '-' ? -1 : 1
        const digits = v.slice(1).replace(/:/g, '')
        st.off = sign * (+digits.slice(0, 2) * 60 + +digits.slice(2, 4))
        break
      }
      default: break
    }
  })
  if (yy !== null) st.y = yy >= 69 ? 1900 + yy : 2000 + yy                 // Python's pivot
  if (hour12 !== null) st.h = (hour12 % 12) + (pm ? 12 : 0)
  if (jday !== null && !groups.includes('m') && !groups.includes('B') && !groups.includes('b')) {
    let rem = jday
    let mo = 1
    while (mo <= 12 && rem > dim(st.y, mo)) { rem -= dim(st.y, mo); mo++ }
    st.mo = mo; st.d = rem
  }
  return valid(st) ? st : null
}

function zoneParts(epochMs: number, zone: string) {
  const f = new Intl.DateTimeFormat('en-US', { timeZone: zone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit' })
  const p: Record<string, number> = {}
  for (const part of f.formatToParts(new Date(epochMs))) if (part.type !== 'literal') p[part.type] = +part.value
  return p
}
/** The zone's offset (minutes east of UTC) at an instant. */
function zoneOffset(epochMs: number, zone: string): number {
  const p = zoneParts(epochMs, zone)
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour === 24 ? 0 : p.hour, p.minute, p.second)
  return Math.round((asUtc - Math.floor(epochMs / 1000) * 1000) / 60000)
}
export function zoneKnown(name: string): boolean {
  try { new Intl.DateTimeFormat('en-US', { timeZone: name }); return true } catch { return false }
}

/** The instant (UTC epoch seconds) a naive local time has in a zone, the way Python's fold=0 reads it: the first of two, the offset
 *  before the change in a gap. */
function localToUtcSeconds(st: Stamp, zone: string): number {
  const asUtcMs = Date.UTC(st.y, st.mo - 1, st.d, st.h, st.mi, st.s)
  const offsets = new Set<number>([zoneOffset(asUtcMs - 86400000, zone), zoneOffset(asUtcMs + 86400000, zone)])
  const fits: number[] = []
  for (const o of offsets) if (zoneOffset(asUtcMs - o * 60000, zone) === o) fits.push(o)
  const o = fits.length ? Math.max(...fits) : Math.min(...offsets)
  return Math.floor(asUtcMs / 1000) - o * 60
}

function utcText(epochSeconds: number, us: number): string {
  const d = new Date(epochSeconds * 1000)
  return `${pad(d.getUTCFullYear(), 4)}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`
    + (us ? `.${pad(us, 6)}` : '') + 'Z'
}

// ── lookup and the record's document ─────────────────────────────────────────────────────────────────────────────────

export function lookup(doc: Json, path: string): Json {
  if (path === '$') return doc
  if (!path.startsWith('$.')) throw new Error(`a path starts with $.: ${JSON.stringify(path)}`)
  let cur = doc
  for (const part of path.slice(2).split('.')) {
    if (isObj(cur)) {
      if (!Object.prototype.hasOwnProperty.call(cur, part)) return MISSING
      cur = cur[part]
    } else if (Array.isArray(cur) && /^\d+$/.test(part)) {
      const i = parseInt(part, 10)
      if (i >= cur.length) return MISSING
      cur = cur[i]
    } else return MISSING
  }
  return cur
}

export interface MapRecord { record_id: string; payload: Json; source?: string; meta?: Json; observed_at?: string | null }
const recordDoc = (r: MapRecord) => ({ payload: r.payload, record_id: r.record_id, source: r.source ?? '', meta: r.meta ?? {}, observed_at: r.observed_at ?? null })

// ── Python equality and text ─────────────────────────────────────────────────────────────────────────────────────────

function pyEq(a: Json, b: Json): boolean {
  const num = (v: Json) => (typeof v === 'boolean' ? (v ? 1 : 0) : v)
  if ((isNum(a) || typeof a === 'boolean') && (isNum(b) || typeof b === 'boolean')) return num(a) === num(b)
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => pyEq(x, b[i]))
  if (isObj(a) && isObj(b)) { const ka = Object.keys(a); return ka.length === Object.keys(b).length && ka.every((k) => k in b && pyEq(a[k], b[k])) }
  return a === b
}
/** bool kept apart from a number (False is not the number 0). */
const same = (a: Json, b: Json) => (typeof a === 'boolean') === (typeof b === 'boolean') && pyEq(a, b)

const cmpCodePoints = (a: string, b: string) => { const x = [...a], y = [...b]; for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i]!.codePointAt(0)! - y[i]!.codePointAt(0)!; return x.length - y.length }
/** json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False) */
export function canonicalJson(v: Json): string {
  if (Array.isArray(v)) return '[' + v.map(canonicalJson).join(',') + ']'
  if (isObj(v)) return '{' + Object.keys(v).sort(cmpCodePoints).map((k) => JSON.stringify(k) + ':' + canonicalJson(v[k])).join(',') + '}'
  return JSON.stringify(v)
}
function pyStr(v: Json): string {
  if (typeof v === 'boolean') return v ? 'True' : 'False'
  if (v === null) return 'None'
  if (isNum(v)) return String(v)
  if (typeof v === 'string') return v
  return canonicalJson(v)
}

// ── value nodes ──────────────────────────────────────────────────────────────────────────────────────────────────────

function toDec(v: Json): Dec | null {
  return Dec.parse(typeof v === 'string' ? v.trim() : String(v))
}

function asType(v: Json, node: Record<string, any>, where: string): Json {
  const kind = node.as
  if (v === null) return null
  if (kind === 'text') {
    if (typeof v === 'boolean') return v ? 'true' : 'false'
    if (isObj(v) || Array.isArray(v)) return canonicalJson(v)
    return String(v)
  }
  if (kind === 'int') {
    if (typeof v === 'boolean') throw new MappingRefused(`${where}: not a whole number`)
    if (isNum(v)) { if (Number.isInteger(v)) return v; throw new MappingRefused(`${where}: not a whole number`) }
    if (typeof v === 'string' && INT.test(v.trim())) return Number(v.trim())
    throw new MappingRefused(`${where}: not a whole number`)
  }
  if (kind === 'decimal' || kind === 'float') {
    if (typeof v === 'boolean' || !(isNum(v) || typeof v === 'string')) throw new MappingRefused(`${where}: not a number`)
    const d = toDec(v)
    if (!d) throw new MappingRefused(`${where}: not a number`)
    return kind === 'decimal' ? d : d.toNumber()
  }
  if (kind === 'bool') {
    if (typeof v === 'boolean') return v
    const key = typeof v === 'string' ? v.trim().toLowerCase() : (isNum(v) && Number.isInteger(v) ? String(v) : null)
    if (key !== null && key in BOOLS) return BOOLS[key]
    throw new MappingRefused(`${where}: not a boolean`)
  }
  if (kind === 'date' || kind === 'datetime') {
    const fmt = node.format
    const tz = node.tz
    if (typeof v !== 'string') throw new MappingRefused(`${where}: not a ${kind}` + (fmt ? ` in the format ${fmt}` : ''))
    const st = fmt ? strptime(v.trim(), fmt) : parseIso(v)
    if (!st) throw new MappingRefused(fmt ? `${where}: not a ${kind} in the format ${fmt}` : `${where}: not an ISO 8601 ${kind}`)
    if (kind === 'date') return `${pad(st.y, 4)}-${pad(st.mo)}-${pad(st.d)}`
    if (st.off === null) {
      if (!tz) throw new MappingRefused(`${where}: a datetime with no zone needs tz`)
      return utcText(localToUtcSeconds(st, String(tz)), st.us)
    }
    return utcText(Math.floor(Date.UTC(st.y, st.mo - 1, st.d, st.h, st.mi, st.s) / 1000) - st.off * 60, st.us)
  }
  if (kind === 'json') {
    if (isObj(v) || Array.isArray(v)) return v
    try {
      if (typeof v !== 'string') throw new Error('x')
      return JSON.parse(v)
    } catch { throw new MappingRefused(`${where}: not JSON`) }
  }
  throw new MappingRefused(`${where}: as ${JSON.stringify(kind)} is not a type`)
}

function roundTo(v: Json, digits: number, where: string): Json {
  if (v === null) return null
  const isDec = v instanceof Dec
  if (!(isNum(v) || isDec)) throw new MappingRefused(`${where}: round needs a number`)
  if (isNum(v) && Number.isInteger(v)) return v
  const d = isDec ? (v as Dec) : Dec.parse(String(v))!
  const q = d.quantize(-digits)
  return isDec ? q : q.toNumber()
}

/** Python's regex spelling to JavaScript's: (?P<name> and (?P=name). */
function jsRegex(src: string): RegExp { return new RegExp(src.replace(/\(\?P</g, '(?<').replace(/\(\?P=(\w+)\)/g, '\\k<$1>')) }
const groupCount = (rx: RegExp) => new RegExp(rx.source + '|', rx.flags).exec('')!.length - 1

function steps(v: Json, node: Record<string, any>, where: string): Json {
  if ('null_if' in node) {
    const nulls = Array.isArray(node.null_if) ? node.null_if : [node.null_if]
    if (nulls.some((n: Json) => same(v, n))) return null
  }
  if (v === null) return null
  if (node.trim && typeof v === 'string') v = v.trim()
  if ('case' in node) {
    if (typeof v !== 'string') throw new MappingRefused(`${where}: case needs text`)
    v = node.case === 'upper' ? v.toUpperCase() : node.case === 'lower' ? v.toLowerCase() : pyTitle(v)
  }
  if ('regex' in node) {
    const rx = jsRegex(node.regex)
    const m = rx.exec(typeof v === 'string' ? v : pyStr(v))
    if (m === null) {
      if ('default' in node) return node.default
      throw new MappingRefused(`${where}: does not match the pattern`)
    }
    const g = 'group' in node ? node.group : (groupCount(rx) ? 1 : 0)
    const got = typeof g === 'string' ? m.groups?.[g] : m[g]
    if (got === undefined || got === null) {
      if ('default' in node) return node.default
      throw new MappingRefused(`${where}: does not match the pattern`)
    }
    v = got
  }
  if ('map' in node) {
    const table = node.map as Record<string, any>
    const has = (k: string) => Object.prototype.hasOwnProperty.call(table, k)
    if ((typeof v === 'string' || isNum(v)) && has(String(v))) v = table[String(v)]
    else if (has(pyStr(v))) v = table[pyStr(v)]
    else if ('map_default' in node) v = node.map_default
    else throw new MappingRefused(`${where}: no map entry and no map_default`)
  }
  if ('as' in node) v = asType(v, node, where)
  if ('round' in node) v = roundTo(v, node.round, where)
  return v instanceof Dec ? v.toString() : v
}

function value(node: Record<string, any>, doc: Json, where: string): Json {
  if ('concat' in node) {
    const sep = String(node.sep || '')
    const parts: string[] = []
    ;(node.concat as Json[]).forEach((part, i) => {
      const at = `${where}[${i}]`
      let pv: Json
      let optional = false
      if (typeof part === 'string' && part.startsWith('$')) {
        const got = lookup(doc, part)
        if (got === MISSING) throw new MappingRefused(`the record has no ${part} (the mapping's field ${where})`)
        pv = got
      } else if (isValueNode(part)) {
        pv = value(part, doc, at)
        optional = part.required === false
      } else pv = part
      if (pv === null) {
        if (!optional) throw new MappingRefused(`${where}: a part of concat is null`)
        parts.push('')
      } else parts.push(asType(pv, { as: 'text' }, where))
    })
    return steps(parts.join(sep), node, where)
  }
  const v = lookup(doc, String(node.path))
  if (v === MISSING) {
    if ('default' in node) return node.default
    if (node.required === false) return null
    throw new MappingRefused(`the record has no ${node.path} (the mapping's field ${where})`)
  }
  return steps(v, node, where)
}

// ── checking a mapping's fields when the spec is loaded ──────────────────────────────────────────────────────────────

export function checkFields(fields: Json, where = ''): string[] {
  const out: string[] = []
  const at = (p: string) => p || "(the mapping's fields)"
  function nodeProblems(node: Record<string, any>, path: string) {
    if ('path' in node && 'concat' in node) { out.push(`${at(path)}: concat: a value node has a path or a concat, not both`); return }
    const kind = node.as
    if ('as' in node && !(AS_TYPES as readonly string[]).includes(kind)) out.push(`${at(path)}: as: ${pyRepr(kind)} is not one of ${AS_TYPES.join(', ')}`)
    if ('case' in node && !(CASES as readonly string[]).includes(node.case)) out.push(`${at(path)}: case: ${pyRepr(node.case)} is not one of ${CASES.join(', ')}`)
    for (const flag of ['trim', 'required']) if (flag in node && typeof node[flag] !== 'boolean') out.push(`${at(path)}: ${flag}: true or false`)
    if ('regex' in node) {
      if (typeof node.regex !== 'string') out.push(`${at(path)}: regex: a pattern (text)`)
      else {
        try {
          const rx = jsRegex(node.regex)
          if ('group' in node) {
            const g = node.group
            const names = [...node.regex.matchAll(/\(\?P<(\w+)>/g)].map((m) => m[1])
            const ok = (Number.isInteger(g) && typeof g !== 'boolean' && g >= 0 && g <= groupCount(rx)) || (typeof g === 'string' && names.includes(g))
            if (!ok) out.push(`${at(path)}: group: ${pyRepr(g)} is not a group of the regex`)
          }
        } catch (e: any) { out.push(`${at(path)}: regex: not a valid pattern (${e?.message || e})`) }
      }
    } else if ('group' in node) out.push(`${at(path)}: group: needs a regex`)
    if ('map' in node && !isObj(node.map)) out.push(`${at(path)}: map: an object of from: to entries`)
    if ('map_default' in node && !('map' in node)) out.push(`${at(path)}: map_default: needs a map`)
    if ('format' in node) {
      if (kind !== 'date' && kind !== 'datetime') out.push(`${at(path)}: format: only for as: date or datetime`)
      else if (typeof node.format !== 'string' || !node.format) out.push(`${at(path)}: format: a strptime format (text)`)
    }
    if ('tz' in node) {
      if (kind !== 'datetime') out.push(`${at(path)}: tz: only for as: datetime`)
      else if (!zoneKnown(String(node.tz))) out.push(`${at(path)}: tz: ${pyRepr(node.tz)} is not a time zone name`)
    }
    if ('round' in node) {
      const r = node.round
      if (!Number.isInteger(r) || typeof r === 'boolean') out.push(`${at(path)}: round: a whole number of digits`)
      else if ('as' in node && !NUMERIC_AS.includes(kind)) out.push(`${at(path)}: round: needs as: int, decimal or float (not ${pyRepr(kind)})`)
    }
    if ('sep' in node && !('concat' in node)) out.push(`${at(path)}: sep: only with concat`)
    if ('concat' in node) {
      const parts = node.concat as Json[]
      if (!parts.length) out.push(`${at(path)}: concat: a list with at least one part`)
      parts.forEach((part, i) => { if (isValueNode(part)) nodeProblems(part, path ? `${path}.concat[${i}]` : `concat[${i}]`) })
    }
  }
  function walk(node: Json, path: string) {
    if (isValueNode(node)) nodeProblems(node, path)
    else if (isObj(node)) for (const [k, v] of Object.entries(node)) walk(v, path ? `${path}.${k}` : k)
    else if (Array.isArray(node)) node.forEach((v, i) => walk(v, `${path}[${i}]`))
  }
  walk(fields, where)
  return out
}

/** Spellings a pattern may use that Python's `re` and the browser's RegExp read differently (the run uses Python, a preview here uses the browser's):
 *  a warning to show beside a regex field, never a refusal. Ordinary patterns (classes, groups, quantifiers, anchors, alternation) read the same. */
export function regexWarnings(pattern: string): string[] {
  const out: string[] = []
  const p = String(pattern ?? '')
  if (/\(\?<[=!]/.test(p)) out.push('A lookbehind: Python needs it to be of a fixed width, the browser does not, so the preview may accept what the run refuses.')
  if (/\(\?P[<=]/.test(p)) out.push('A named group written (?P<name>...): the preview rewrites it for the browser; the run uses it as it is.')
  if (/(?:[*+?]|\})\+/.test(p.replace(/\\(?:[pP]\{[^}]*\}|.)/g, ''))) out.push('A possessive quantifier: Python 3.11 reads it, the browser does not.')
  if (/\(\?>/.test(p)) out.push('An atomic group (?>...): Python 3.11 reads it, the browser does not.')
  if (/\\[pP]\{/.test(p)) out.push('A Unicode class \\p{...}: the browser reads it, Python\'s re does not.')
  if (/\\[AZ]/.test(p)) out.push('\\A and \\Z: Python reads them, the browser does not.')
  if (/\(\?[aiLmsux-]+\)/.test(p.slice(1))) out.push('An inline flag in the middle of a pattern: Python 3.11 refuses it, the browser reads it differently.')
  return out
}

/** Python's repr for the few values a problem names: a string in single quotes, a number or bool as itself. */
function pyRepr(v: Json): string {
  if (typeof v === 'string') return `'${v.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`
  if (typeof v === 'boolean') return v ? 'True' : 'False'
  if (v === null || v === undefined) return 'None'
  return String(v)
}

function mapNode(node: Json, doc: Json, where: string): Json {
  if (typeof node === 'string' && node.startsWith('$')) {
    const v = lookup(doc, node)
    if (v === MISSING) throw new MappingRefused(`the record has no ${node} (the mapping's field ${where})`)
    return v
  }
  if (isValueNode(node)) return value(node, doc, where)
  if (isObj(node)) { const o: Record<string, Json> = {}; for (const [k, v] of Object.entries(node)) o[k] = mapNode(v, doc, where ? `${where}.${k}` : k); return o }
  if (Array.isArray(node)) return node.map((v, i) => mapNode(v, doc, `${where}[${i}]`))
  return node
}

/** What an action takes for this record (MappingRefused when a field's path is not in it). */
export function apply(fields: Record<string, Json>, rec: MapRecord): Record<string, Json> {
  return mapNode({ ...fields }, recordDoc(rec), '')
}

/** Whether the mapping takes this record. */
export function takes(when: Record<string, Json> | null | undefined, rec: MapRecord): boolean {
  if (!when || !Object.keys(when).length) return true
  const v = lookup(recordDoc(rec), String(when.path ?? '$'))
  if ('exists' in when) return (v !== MISSING) === Boolean(when.exists)
  if (v === MISSING) return false
  if ('equals' in when) return pyEq(v, when.equals)
  if ('in' in when) return ((when.in as Json[]) || []).some((x) => pyEq(v, x))
  return true
}
