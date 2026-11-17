import { describe, it, expect } from 'vitest'
import TREE from '@/data/codeChanges/consoleTree.generated.json'
import { bodyFor, emptyDraft, fullPath, pathRows, problemsFor, suggestions, type Draft } from './propose'
import { CONSOLE_PREFIX, REPOSITORY, isForbidden } from './pathRules'

const tr = (_k: string, fb: string, p?: Record<string, unknown>) => fb.replace(/\{(\w+)\}/g, (_m, k) => String(p?.[k] ?? ''))
const P = (s: string) => CONSOLE_PREFIX + s
const draft = (o: Partial<Draft> = {}): Draft => ({ ...emptyDraft(), title: 'Show who is paid', problem: 'The order page does not say which agent is paid when a firm bids.', paths: [P('views/GuildBoard.vue')], bounty: '5', ...o })

describe('what each step needs', () => {
  it('the first step needs a title and a problem of a sentence or two', () => {
    expect(problemsFor('what', emptyDraft(), tr).map((p) => p.field)).toEqual(['title', 'problem'])
    expect(problemsFor('what', draft({ problem: 'too short' }), tr).map((p) => p.field)).toEqual(['problem'])
    expect(problemsFor('what', draft({ title: 'x'.repeat(161) }), tr)[0].sentence).toMatch(/160/)
    expect(problemsFor('what', draft(), tr)).toEqual([])
  })
  it('the files step says the registry\'s own sentence for a refused path, and nothing for a good one', () => {
    expect(problemsFor('files', draft({ paths: [] }), tr)[0].sentence).toMatch(/no paths/)
    expect(problemsFor('files', draft({ paths: [P('secret.ts')] }), tr)[0].sentence).toMatch(/forbidden path/)
    expect(problemsFor('files', draft({ paths: ['agentvault_registry/src/agentvault_registry/main.py'] }), tr)[0].sentence).toMatch(/not open in this phase/)
    expect(problemsFor('files', draft(), tr)).toEqual([])
  })
  it('a bounty needs an amount above zero (a comma works as a point), a branch needs a name and a full commit id', () => {
    expect(problemsFor('how', draft({ bounty: '' }), tr)[0].field).toBe('bounty')
    expect(problemsFor('how', draft({ bounty: '0' }), tr)[0].field).toBe('bounty')
    expect(problemsFor('how', draft({ bounty: '2,5' }), tr)).toEqual([])
    const b = draft({ mode: 'branch', branch: '', commit: 'abc' })
    expect(problemsFor('how', b, tr).map((p) => p.field)).toEqual(['branch', 'commit'])
    expect(problemsFor('how', { ...b, branch: 'fix/x', commit: 'a'.repeat(40) }, tr)).toEqual([])
  })
  it('the last step needs everything', () => {
    expect(problemsFor('review', draft(), tr)).toEqual([])
    expect(problemsFor('review', emptyDraft(), tr).map((p) => p.field)).toEqual(['title', 'problem', 'paths', 'bounty'])
  })
})

describe('what a path means', () => {
  it('open, sensitive (what it needs), refused (the registry\'s sentence)', () => {
    const rows = pathRows([P('views/A.vue'), P('stores/auth.ts'), '.env'], tr)
    expect(rows.map((r) => r.status)).toEqual(['ok', 'sensitive', 'refused'])
    expect(rows[1].sentence).toMatch(/two approving reviews/)
    expect(rows[2].sentence).toMatch(/forbidden path/)
  })
})

describe('the picker\'s suggestions come from the console tree', () => {
  const tree = TREE as any
  it('never suggests a path the registry refuses, even when the tree holds one (a file called secrets, a credentials view)', () => {
    const forbidden = [...tree.files, ...tree.dirs].filter((p: string) => isForbidden(CONSOLE_PREFIX + p))
    expect(forbidden.length).toBeGreaterThan(0)                                            // the control: the tree does hold some
    for (const f of forbidden) expect(suggestions(f.split('/').pop()!, tree, [], 200), f).not.toContain(f)
    expect(tree.files.length).toBeGreaterThan(500)
    expect(tree.files).toEqual([...new Set(tree.files)].sort())
  })
  it('names the best matches first (the file name, then the path), directories with a slash, and skips what is already added', () => {
    const s = suggestions('guildboard', tree, [])
    expect(s[0]).toBe('views/GuildBoard.vue')
    expect(suggestions('views', tree, []).some((x) => x === 'views/')).toBe(true)
    expect(suggestions('guildboard', tree, [P('views/GuildBoard.vue')]).includes('views/GuildBoard.vue')).toBe(false)
    expect(suggestions('', tree, [])).toEqual([])
    expect(suggestions('zzzzzzzzqq', tree, [])).toEqual([])
  })
  it('takes a typed full path as well as the part after src/, and caps the list', () => {
    expect(suggestions(P('views/GuildB'), tree, [])[0]).toBe('views/GuildBoard.vue')
    expect(suggestions('a', tree, [], 5)).toHaveLength(5)
  })
})

describe('the body the registry takes', () => {
  it('turns what is typed into a full path under the console', () => {
    expect(fullPath('views/GuildBoard.vue')).toBe(P('views/GuildBoard.vue'))
    expect(fullPath(P('views/'))).toBe(P('views'))
    expect(fullPath('  /views/A.vue ')).toBe(P('views/A.vue'))
    expect(fullPath('')).toBe('')
    expect(fullPath('agentvault_registry/src/agentvault_registry/main.py')).toBe('agentvault_registry/src/agentvault_registry/main.py')   // not rewritten: the registry refuses it in words
  })
  it('a bounty body and a branch body', () => {
    expect(bodyFor(draft())).toEqual({ repository: REPOSITORY, paths: [P('views/GuildBoard.vue')], title: 'Show who is paid', problem: 'The order page does not say which agent is paid when a firm bids.', bounty: 5 })
    const b = bodyFor(draft({ mode: 'branch', branch: ' fix/x ', commit: 'a'.repeat(40) }))
    expect(b).toMatchObject({ branch: 'fix/x', commit: 'a'.repeat(40) }); expect(b).not.toHaveProperty('bounty')
  })
})
