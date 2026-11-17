import { describe, it, expect } from 'vitest'
import { buildKit, fieldValue, newField, parametersFor, parseCsv, parseSample, payloadFor, placeholders, preview, skeleton, mappingFields, sniffFormat } from './builder'

/**
 * V0664 C4 (order gwo_85a6015257385f6bb010682e): the migration builder's model. What a person chooses becomes the two files of a kit (and a README), the registry's
 * publish gate is run over them as they are, and the mapping is previewed on a sample that never leaves the browser.
 */
const filled = (from: 'sql' | 'file' | 'rest' = 'file', to: 'sql' | 'file' | 'rest' = 'sql') => {
  const s = skeleton(from, to)
  s.name = 'orders-to-pg'; s.title = 'Orders to PostgreSQL'; s.summary = 'One table to one table'
  return s
}

describe('a skeleton, once it has a name and a title, is a kit the registry\'s gate takes', () => {
  for (const [from, to] of [['sql', 'sql'], ['file', 'sql'], ['sql', 'rest'], ['file', 'rest']] as const) {
    it(`${from} to ${to}`, () => {
      const k = buildKit(filled(from, to))
      expect(k.check.problems, JSON.stringify(k.check.problems)).toEqual([])
      expect(k.manifest.schema).toBe('theprotocol.migration/v1')
      expect(k.manifest.load.mappings).toEqual(['main'])
      expect(Object.keys(k.files).sort()).toEqual(['README.md', 'migration.yaml', 'proxy.yaml'])
    })
  }
  it('without a name or a title it says so, in the registry\'s own words', () => {
    const k = buildKit(skeleton('file', 'sql'))
    expect(k.check.ok).toBe(false)
    expect(k.check.problems.map((p) => p.sentence).join(' ')).toMatch(/name: fails the schema's pattern rule/)
    expect(k.check.problems.map((p) => p.sentence).join(' ')).toMatch(/title: fails the schema's minLength rule/)
  })
})

describe('the parameters a kit declares follow from the placeholders it uses', () => {
  it('lists every placeholder in the sources, the writer and the mapping, and marks the secret ones with no default', () => {
    const s = filled()
    s.mapping.fields.push(Object.assign(newField('ordered_at', '$.payload.data.ordered_at'), { as: 'datetime', format: '%Y-%m-%d %H:%M', tz: '${SOURCE_TZ}' }))
    s.parameters = { TARGET_HOST: { description: 'the new database server', default: 'localhost', secret: false, enum: '' }, SOURCE_TZ: { description: '', default: 'Europe/Berlin', secret: false, enum: '' },
      TARGET_PASSWORD: { description: 'a reference', default: 'ignored', secret: false, enum: '' } }
    const p = parametersFor(s)
    expect(Object.keys(p)).toEqual(expect.arrayContaining(['SOURCE_DIR', 'TARGET_HOST', 'TARGET_DATABASE', 'TARGET_USER', 'TARGET_PASSWORD', 'TARGET_TABLE', 'SOURCE_TZ']))
    expect(p.TARGET_PASSWORD).toEqual({ description: 'a reference', secret: true })              // a secret has no default, whatever was typed
    expect(p.TARGET_HOST).toEqual({ description: 'the new database server', default: 'localhost' })
    expect(buildKit(s).check.problems).toEqual([])
  })
  it('finds placeholders at any depth, once each, in order', () => {
    expect([...placeholders({ a: '${X}/y', b: ['${Y}', { c: '${X}' }], d: 3 })]).toEqual(['X', 'Y'])
  })
})

describe('the registry\'s rules, shown before anything is saved', () => {
  it('names a destination written into the kit, and a credential written out', () => {
    const s = filled()
    s.sink.config.host = 'db.example.com'
    s.sink.config.password = 'hunter2'
    const k = buildKit(s)
    expect(k.check.problems.map((p) => p.rule)).toEqual(expect.arrayContaining(['destination', 'secret']))
    const secret = k.check.problems.find((p) => p.rule === 'secret')!
    expect(secret.sentence).toContain('proxy.yaml:sinks.new.config.password')
    expect(secret.sentence).not.toContain('hunter2')                           // never the value
  })
  it('wants the sample file the manifest names to be in the kit, and puts it there', () => {
    const s = filled()
    s.sample = { text: 'id,name\n1,Ada\n', format: 'csv', name: 'orders.csv' }
    const k = buildKit(s)
    expect(k.manifest.sample).toEqual({ old: { file: 'sample/sample.csv', format: 'csv' } })
    expect(k.files['sample/sample.csv']).toBe('id,name\n1,Ada\n')
    expect(k.check.problems).toEqual([])
  })
  it('derives the reconcile entry from the key and the mapped fields', () => {
    const k = buildKit(filled())
    expect(k.manifest.reconcile[0]).toEqual({ mapping: 'main', source: { key: ['id'], fields: ['name', 'email'] }, target: { key: ['id'], fields: ['name', 'email'] }, pairs: { name: 'name', email: 'email' } })
  })
})

describe('a field becomes a path, a constant or a value node', () => {
  it('a plain path stays a plain string, a constant stays a constant', () => {
    expect(fieldValue(newField('a', '$.payload.a'))).toBe('$.payload.a')
    expect(fieldValue(Object.assign(newField('a'), { mode: 'constant', constant: 'HAM' }))).toBe('HAM')
  })
  it('transforms make a value node, with only what was chosen', () => {
    const r = Object.assign(newField('amount', '$.payload.data.amount'), { as: 'decimal', round: '2', trim: true, nullIf: ' ,N/A' })
    expect(fieldValue(r)).toEqual({ path: '$.payload.data.amount', trim: true, null_if: ['', 'N/A'].filter(Boolean).length ? ['N/A'] : [], as: 'decimal', round: 2 })
  })
  it('a dated field carries its format and zone; a map carries its default; a regex its group', () => {
    const d = Object.assign(newField('at', '$.payload.at'), { as: 'datetime', format: '%d.%m.%Y %H:%M', tz: 'Europe/Berlin' })
    expect(fieldValue(d)).toEqual({ path: '$.payload.at', as: 'datetime', format: '%d.%m.%Y %H:%M', tz: 'Europe/Berlin' })
    const m = Object.assign(newField('s', '$.payload.s'), { case: 'upper', map: [{ from: 'A', to: 'active' }], mapDefault: 'unknown' })
    expect(fieldValue(m)).toEqual({ path: '$.payload.s', case: 'upper', map: { A: 'active' }, map_default: 'unknown' })
    const g = Object.assign(newField('n', '$.payload.n'), { regex: 'ID-(\\d+)', group: '1' })
    expect(fieldValue(g)).toEqual({ path: '$.payload.n', regex: 'ID-(\\d+)', group: 1 })
  })
  it('a concat names its parts and its separator', () => {
    const c = Object.assign(newField('who'), { mode: 'concat', concat: '$.payload.first\n$.payload.last', sep: ' ' })
    expect(fieldValue(c)).toEqual({ concat: ['$.payload.first', '$.payload.last'], sep: ' ' })
  })
  it('a blank target is left out of the mapping', () => {
    const s = filled(); s.mapping.fields.push(newField('', '$.payload.x'))
    expect(Object.keys(mappingFields(s))).toEqual(['id', 'name', 'email'])
  })
})

describe('reading a sample', () => {
  it('reads CSV with quotes, doubled quotes, a comma or a line break inside quotes, CRLF and a BOM', () => {
    const rows = parseCsv('﻿a,b\r\n1,"x, y"\r\n2,"he said ""hi"""\r\n3,"two\nlines"\r\n')
    expect(rows).toEqual([{ a: '1', b: 'x, y' }, { a: '2', b: 'he said "hi"' }, { a: '3', b: 'two\nlines' }])
    expect(parseCsv('')).toEqual([])
    expect(parseCsv('a,b\n')).toEqual([])
  })
  it('reads JSON lines and a JSON array, and says what is wrong with one that is not', () => {
    expect(parseSample('{"a":1}\n{"a":2}\n', 'jsonl').rows).toHaveLength(2)
    expect(parseSample('[{"a":1},{"a":2}]', 'json').rows).toHaveLength(2)
    expect(parseSample('{"items":[{"a":1}]}', 'json').rows).toHaveLength(1)
    expect(parseSample('{"a":1}\nnot json', 'jsonl').error).toMatch(/line 2/)
    expect(parseSample('[1,2]', 'json').error).toMatch(/array of objects/)
    expect(parseSample('   ', 'csv')).toEqual({ rows: [], error: '' })
  })
  it('shapes a record the way each source does: a table gives the row, a file source {file, row, data}', () => {
    expect(payloadFor('sqlpoll', { a: 1 }, 0)).toEqual({ a: 1 })
    expect(payloadFor('filedrop', { a: 1 }, 3, 'x.csv')).toEqual({ file: 'x.csv', row: 3, data: { a: 1 } })
  })
})

describe('the preview runs the mapping on the sample', () => {
  const orders = () => {
    const s = filled('file', 'sql')
    s.mapping.fields = [
      newField('order_no', '$.payload.data.order_no'), 
      Object.assign(newField('amount', '$.payload.data.amount'), { as: 'decimal', round: '2' }),
      Object.assign(newField('currency', '$.payload.data.currency'), { trim: true, case: 'upper' }),
    ]
    s.sample = { text: 'order_no,amount,currency\n100001,1163.60, EUR\n100002,371.976,EUR\n100003,not-a-number,eur\n', format: 'csv', name: 'orders.csv' }
    return s
  }
  it('maps each row, refuses the one it cannot with the rule and never the value, and counts', () => {
    const p = preview(orders())
    expect(p.taken).toBe(3)
    expect(p.mapped).toBe(2)
    expect(p.rejected).toBe(1)
    expect(p.rows[0].out).toEqual({ order_no: '100001', amount: '1163.60', currency: 'EUR' })
    expect(p.rows[1].out!.amount).toBe('371.98')                                 // half to even on the exact decimal
    expect(p.rows[2].refused).toBe('amount: not a number')
    expect(JSON.stringify(p.rows[2])).not.toContain('not-a-number')
    expect(p.reasons).toEqual([{ reason: 'amount: not a number', n: 1, pct: 100 }])
    expect(p.fill.find((f) => f.field === 'currency')).toMatchObject({ filled: 2, null: 0 })
  })
  it('says nothing yet when there is no sample, and names a sample that cannot be read', () => {
    const s = orders(); s.sample.text = ''
    expect(preview(s)).toMatchObject({ taken: 0, sampleError: '' })
    s.sample = { text: 'not json', format: 'jsonl', name: '' }
    expect(preview(s).sampleError).toMatch(/line 1/)
  })
  it('reports a field node the load-time check refuses', () => {
    const s = orders()
    s.mapping.fields.push(Object.assign(newField('x', '$.payload.data.x'), { as: 'decimal', format: '%Y' }))
    expect(preview(s).fieldProblems.join(' ')).toMatch(/format: only for as: date or datetime/)
  })
})

describe('sniffFormat', () => {
  it('reads what a pasted sample looks like', () => {
    expect(sniffFormat('id,name\n1,Ada')).toBe('csv')
    expect(sniffFormat('  \n{"id":1}\n{"id":2}')).toBe('jsonl')
    expect(sniffFormat('[{"id":1}]')).toBe('json')
    expect(sniffFormat('')).toBe('csv')
  })
})
