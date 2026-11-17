import { describe, it, expect } from 'vitest'
import V from './path.vectors.json'
import { checkPaths, isCommitId, reviewsVerdict, OPEN_PATHS, REPOSITORY, CONSOLE_PREFIX } from './pathRules'

/** The registry's rules, in the browser: every case below was made by running services/code_changes.py itself (scratchpad/cc/gen_path_vectors.py). */
describe('the vectors carry what the port assumes', () => {
  it('the repository and the open prefix are the registry\'s', () => {
    expect(V.repo).toBe(REPOSITORY)
    expect(V.prefix).toBe(CONSOLE_PREFIX)
    expect(OPEN_PATHS[REPOSITORY]).toEqual([V.prefix])
  })
})

describe('checkPaths against the registry', () => {
  for (const c of V.paths as any[]) {
    it(`${c.repo || '(none)'} ${JSON.stringify(c.paths.length > 3 ? c.paths.length + ' paths' : c.paths).slice(0, 90)}`, () => {
      const r = checkPaths(c.repo, c.paths)
      expect({ ok: r.ok, reason: r.reason, sensitive: r.sensitive, paths: r.paths }).toEqual({ ok: c.ok, reason: c.reason, sensitive: c.sensitive, paths: c.out })
    })
  }
  it('has cases of every kind (a vector set that lost its refusals would pass anything)', () => {
    const cs = V.paths as any[]
    expect(cs.filter((c) => c.ok && !c.sensitive).length).toBeGreaterThan(3)
    expect(cs.filter((c) => c.ok && c.sensitive).length).toBeGreaterThan(5)
    expect(cs.filter((c) => !c.ok).length).toBeGreaterThan(20)
    expect(new Set(cs.filter((c) => !c.ok).map((c) => String(c.reason).split(':')[0].split(' ').slice(0, 3).join(' '))).size).toBeGreaterThan(5)
  })
})

describe('isCommitId against the registry', () => {
  for (const c of V.shas as any[]) it(JSON.stringify(c.v).slice(0, 30) + '… ' + c.ok, () => expect(isCommitId(c.v)).toBe(c.ok))
})

describe('reviewsVerdict against the registry', () => {
  ;(V.reviews as any[]).forEach((c, i) => it(`case ${i}: sensitive=${c.sensitive}, ${c.reviews.length} review(s)`, () => {
    expect(reviewsVerdict(c.reviews, c.commit, c.sensitive)).toEqual(c.out)
  }))
  it('leaves out a reviewer who may not review (the proposer, the worker)', () => {
    const rs = [{ reviewer_developer_id: 1, verdict: 'approve', commit: 'c', at: 1 }]
    expect(reviewsVerdict(rs, 'c', false, new Set([1])).approvals).toBe(0)
  })
})
