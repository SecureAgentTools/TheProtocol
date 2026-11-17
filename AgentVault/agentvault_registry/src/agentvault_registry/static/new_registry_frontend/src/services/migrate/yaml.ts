// V0664 C4 (order gwo_85a6015257385f6bb010682e): a YAML writer for the two files of a kit (migration.yaml, proxy.yaml), which the builder produces from
// data. Writer only: the console never reads YAML. What it writes is read back by Python's yaml.safe_load (what the registry and the SDK use)
// to exactly the data it was given: yaml.golden.c4.json holds outputs that were each checked that way.
//
// Block style, two spaces. A string is written plain only when it is plainly safe (a word, a path); anything a YAML reader could take for
// something else (yes, 1e3, a leading dash, a colon, a hash, a placeholder in braces) is written double-quoted with JSON's escapes.
type Json = any

const RESERVED = /^(?:true|false|null|yes|no|on|off|y|n|~)$/i
const NUMBERISH = /^[-+]?(?:\.?\d|0[xob])/i
const PLAIN = /^[A-Za-z_][A-Za-z0-9_./-]*$/

function scalar(v: Json): string {
  if (v === null || v === undefined) return 'null'
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) throw new Error('YAML here carries finite numbers only')
    // PyYAML (YAML 1.1) reads 1e-7 as text: a float needs its point (1.0e-7)
    return String(v).replace(/^(-?\d+)e/, '$1.0e')
  }
  const s = String(v)
  if (PLAIN.test(s) && !RESERVED.test(s) && !NUMBERISH.test(s)) return s
  // YAML breaks a line at U+0085, U+2028 and U+2029 too, which JSON leaves as they are: write them escaped
  return JSON.stringify(s).replace(/[\u0085\u2028\u2029]/g, (c) => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'))
}

const isObj = (v: Json) => v !== null && typeof v === 'object' && !Array.isArray(v)
const isScalar = (v: Json) => !isObj(v) && !Array.isArray(v)

function inline(v: Json): string | null {
  if (isScalar(v)) return scalar(v)
  if (Array.isArray(v) && v.length === 0) return '[]'
  if (isObj(v) && Object.keys(v).length === 0) return '{}'
  if (Array.isArray(v) && v.every(isScalar)) {                         // a short list of plain things stays on one line
    const one = '[' + v.map(scalar).join(', ') + ']'
    if (one.length <= 72) return one
  }
  return null
}

function emit(v: Json, indent: number, lines: string[], listItem = false): void {
  const pad = ' '.repeat(indent)
  if (Array.isArray(v)) {
    for (const item of v) {
      const one = inline(item)
      if (one !== null) lines.push(`${pad}- ${one}`)
      else if (isObj(item)) {
        const sub: string[] = []
        emit(item, indent + 2, sub, true)
        sub[0] = `${pad}- ${sub[0].slice(indent + 2)}`
        lines.push(...sub)
      } else {
        lines.push(`${pad}-`)
        emit(item, indent + 2, lines)
      }
    }
    return
  }
  for (const [k, val] of Object.entries(v as Record<string, Json>)) {
    const key = scalar(k)
    const one = inline(val)
    if (one !== null) lines.push(`${pad}${key}: ${one}`)
    else {
      lines.push(`${pad}${key}:`)
      emit(val, Array.isArray(val) ? indent + 2 : indent + 2, lines)
    }
  }
}

/** The YAML text of a mapping, with optional leading comment lines. */
export function toYaml(doc: Record<string, Json>, comments: string[] = []): string {
  const lines: string[] = comments.map((c) => `# ${c}`)
  emit(doc, 0, lines)
  return lines.join('\n') + '\n'
}
