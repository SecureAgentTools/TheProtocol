/**
 * V0663 (order gwo_f8251964b96cb1759350b69d, his suggestion 9): two agent cards compared as JSON, path by path, for the
 * compare page (views/CardCompare). Pure: no fetch, no Vue.
 *
 * A path names a leaf by key and index (capabilities.quantum.backends, skills[0].id). A subtree that only one card has
 * is one path, not one per leaf, and a value that changes type is one changed path. The rows follow card A's order,
 * then what only B has, so the table reads like the cards. cardLines prints a card exactly as JSON.stringify(card,
 * null, 2) does, each line carrying the path it belongs to and its mark for that side.
 */

export type DiffStatus = 'same' | 'changed' | 'only_a' | 'only_b'

export interface DiffRow {
  path: string
  status: DiffStatus
  a: unknown
  b: unknown
}

export type LineMark = 'same' | 'changed' | 'only'

export interface CardLine {
  text: string
  path: string
  mark: LineMark
}

const isContainer = (v: unknown): v is Record<string, unknown> | unknown[] => v !== null && typeof v === 'object'
const join = (base: string, key: string | number): string =>
  typeof key === 'number' ? `${base}[${key}]` : (base ? `${base}.${key}` : key)
const ownKeys = (o: Record<string, unknown>): string[] => Object.keys(o).filter((k) => o[k] !== undefined)

function walk(a: unknown, b: unknown, path: string, out: DiffRow[]): void {
  if (isContainer(a) && isContainer(b) && Array.isArray(a) === Array.isArray(b)) {
    if (Array.isArray(a) && Array.isArray(b)) {
      for (let i = 0; i < Math.max(a.length, b.length); i++) {
        if (i >= a.length) out.push({ path: join(path, i), status: 'only_b', a: undefined, b: b[i] })
        else if (i >= b.length) out.push({ path: join(path, i), status: 'only_a', a: a[i], b: undefined })
        else walk(a[i], b[i], join(path, i), out)
      }
      return
    }
    const ao = a as Record<string, unknown>
    const bo = b as Record<string, unknown>
    const keys = [...ownKeys(ao), ...ownKeys(bo).filter((k) => ao[k] === undefined)]
    for (const k of keys) {
      if (bo[k] === undefined) out.push({ path: join(path, k), status: 'only_a', a: ao[k], b: undefined })
      else if (ao[k] === undefined) out.push({ path: join(path, k), status: 'only_b', a: undefined, b: bo[k] })
      else walk(ao[k], bo[k], join(path, k), out)
    }
    return
  }
  out.push({ path, status: JSON.stringify(a) === JSON.stringify(b) ? 'same' : 'changed', a, b })
}

export function diffCards(a: unknown, b: unknown): DiffRow[] {
  const out: DiffRow[] = []
  walk(a, b, '', out)
  return out
}

export function diffSummary(rows: readonly DiffRow[]): Record<DiffStatus, number> {
  const c: Record<DiffStatus, number> = { same: 0, changed: 0, only_a: 0, only_b: 0 }
  for (const r of rows) c[r.status]++
  return c
}

const within = (path: string, base: string): boolean =>
  base === '' || path === base || path.startsWith(`${base}.`) || path.startsWith(`${base}[`)

/** The card as JSON lines (exactly JSON.stringify(card, null, 2)), each with its path and its mark for `side`. */
export function cardLines(card: unknown, rows: readonly DiffRow[], side: 'a' | 'b'): CardLine[] {
  const marked = rows.filter((r) => r.status !== 'same')
  const markOf = (path: string): LineMark => {
    for (const r of marked) {
      if (!within(path, r.path)) continue
      if (r.status === 'changed') return 'changed'
      if ((r.status === 'only_a' && side === 'a') || (r.status === 'only_b' && side === 'b')) return 'only'
    }
    return 'same'
  }
  const lines: Array<{ text: string; path: string }> = []
  const print = (v: unknown, path: string, indent: number, prefix: string, comma: boolean): void => {
    const pad = '  '.repeat(indent)
    const tail = comma ? ',' : ''
    if (Array.isArray(v)) {
      if (!v.length) { lines.push({ text: `${pad}${prefix}[]${tail}`, path }); return }
      lines.push({ text: `${pad}${prefix}[`, path })
      v.forEach((x, i) => print(x === undefined ? null : x, join(path, i), indent + 1, '', i < v.length - 1))
      lines.push({ text: `${pad}]${tail}`, path })
    } else if (isContainer(v)) {
      const keys = ownKeys(v as Record<string, unknown>)
      if (!keys.length) { lines.push({ text: `${pad}${prefix}{}${tail}`, path }); return }
      lines.push({ text: `${pad}${prefix}{`, path })
      keys.forEach((k, i) => print((v as Record<string, unknown>)[k], join(path, k), indent + 1,
        `${JSON.stringify(k)}: `, i < keys.length - 1))
      lines.push({ text: `${pad}}${tail}`, path })
    } else {
      lines.push({ text: `${pad}${prefix}${JSON.stringify(v)}${tail}`, path })
    }
  }
  print(card, '', 0, '', false)
  return lines.map((l) => ({ ...l, mark: markOf(l.path) }))
}
