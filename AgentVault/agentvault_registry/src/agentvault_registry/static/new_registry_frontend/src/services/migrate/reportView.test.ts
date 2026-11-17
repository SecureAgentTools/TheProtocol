import { describe, it, expect } from 'vitest'
import v from './report.vectors.c4.json'
import { STEP_WORDS, fillRows, readTexts, reasonRows, sortItems, verdictWords } from './reportView'

/** V0664 C4: what the report page shows of a report, as plain data (counts only, never a value): the verdict in words, the rejected rows by
 *  reason, the fill per field, and the order of what was dropped. */
const V: any = v
const text = (o: any) => JSON.stringify(o)

describe('words and order', () => {
  it('says a verdict in words with a tone, never by colour alone', () => {
    expect(verdictWords('pass')).toEqual({ label: 'Passed', tone: 'ok' })
    expect(verdictWords('fail')).toEqual({ label: 'Failed', tone: 'bad' })
    expect(verdictWords('not_measured')).toEqual({ label: 'Not measured', tone: 'warn' })
    expect(verdictWords('weird')).toEqual({ label: 'weird', tone: 'warn' })
    expect(verdictWords(undefined).label).toBe('Not measured')
  })
  it('names the four steps', () => {
    expect(STEP_WORDS).toEqual({ inventory: 'Inventory', dry_run: 'Dry run', load: 'Load', reconcile: 'Reconcile' })
  })
})

describe('rejected rows by reason', () => {
  it('lists the most frequent reason first and gives each its share of the rejected rows', () => {
    const rows = reasonRows(V.load.mappings.customers)
    expect(rows.map((r) => r.n)).toEqual([30, 4])
    expect(rows[0].reason).toContain('created')
    expect(rows[0].pct).toBe(88)                                      // 30 of 34, rounded
    expect(rows[1].pct).toBe(12)
  })
  it('breaks a tie by the reason\'s own text, and says nothing for a mapping that rejected nothing', () => {
    expect(reasonRows({ rejected: 4, rejected_by_reason: { b: 2, a: 2 } }).map((r) => r.reason)).toEqual(['a', 'b'])
    expect(reasonRows({ rejected: 0, rejected_by_reason: {} })).toEqual([])
    expect(reasonRows({})).toEqual([])
  })
})

describe('fill per field', () => {
  it('gives the filled share of each field, in the fields\' own order of name', () => {
    const rows = fillRows(V.dry_run.mappings.customers)
    expect(rows.map((r) => r.field)).toEqual(['created', 'email', 'id', 'name'])
    expect(rows.find((r) => r.field === 'email')).toMatchObject({ filled: 100, null: 17, pct: 85 })
    expect(rows.find((r) => r.field === 'id')!.pct).toBe(100)
  })
  it('does not divide by zero for a field nothing was counted for', () => {
    expect(fillRows({ fields: { x: { filled: 0, null: 0 } } })[0].pct).toBe(0)
    expect(fillRows({})).toEqual([])
  })
})

describe('reading what was dropped', () => {
  it('reads a report, a certificate and says why a file is neither, one item each, in the order of the steps', async () => {
    const items = sortItems(await readTexts([
      { name: 'reconcile.json', text: text(V.reconcile_pass) }, { name: 'cert.json', text: text(V.certificate) },
      { name: 'load.json', text: text(V.load) }, { name: 'notes.txt', text: 'not json at all' }, { name: 'other.json', text: '{"hello":1}' },
      { name: 'dry.json', text: text(V.dry_run) }]))
    expect(items.map((i) => i.kind)).toEqual(['certificate', 'report', 'report', 'report', 'error', 'error'])
    expect(items.filter((i) => i.kind === 'report').map((i: any) => i.doc.step)).toEqual(['dry_run', 'load', 'reconcile'])
    const bad = items.filter((i) => i.kind === 'error')
    expect(bad[0].error).toMatch(/not JSON/i)
    expect(bad[1].error).toMatch(/not a migration report or certificate/i)
  })
  it('recomputes each report\'s hash and marks one that does not hold', async () => {
    const tampered = JSON.parse(text(V.load)); tampered.targets.pg.written = 1
    const items = await readTexts([{ name: 'a.json', text: text(V.load) }, { name: 'b.json', text: text(tampered) }])
    expect(items.map((i: any) => i.holds)).toEqual([true, false])
  })
  it('refuses a file that is too large to be a report, without reading it into a page', async () => {
    const items = await readTexts([{ name: 'huge.json', text: 'x'.repeat(6 * 1024 * 1024) }])
    expect(items[0].kind).toBe('error')
    expect(items[0].kind === 'error' && items[0].error).toMatch(/too large/i)
  })
})
