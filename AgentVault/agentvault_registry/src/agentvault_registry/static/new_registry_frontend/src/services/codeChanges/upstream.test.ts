/**
 * V0667 D4 (order gwo_b12f07e4c5adaa1f5bf4d115): upstream, the console's rules. A change merged in an organization's release line is proposed to the main code by the line's
 * deciders: the action is offered only then; the line's own copy says the proposal, its state and, once it landed, "upstream since"; the change on the main code shows where it
 * came from, with nothing dropped. The registry decides every step again (who decides, the paths, once).
 * Red before: services/codeChanges/upstream.ts does not exist.
 */
import { describe, expect, it } from 'vitest'
import { canProposeUpstream, lineStatus, provenanceFacts, upstreamKind } from './upstream'

const tr = (_k: string, fb: string, p?: Record<string, unknown>) => (p ? fb.replace(/\{(\w+)\}/g, (_m, k) => String(p[k])) : fb)
const line = (over: Record<string, any> = {}) => ({ id: 'cc_line', state: 'merged', title: 'A clearer page', code_distribution: { slug: 'lyceum', title: 'Lyceum', organization_name: 'Lyceum Labs' },
  line_ballot: { i_decide: true }, upstream: null, ...over })
const PROV = {
  line: { id: 'cdst_1', slug: 'lyceum', title: 'Lyceum', base_release: 'V0666', organization_id: 'org-a', organization_name: 'Lyceum Labs', branch: 'distribution/V0666_lyceum' },
  line_change: { id: 'cc_line', title: 'A clearer page', problem: 'P', branch: 'b', commit: 'a'.repeat(40), paths: ['x'], proposer_did: 'did:a:m', proposer_developer_id: 6, merged: { commit: 'a'.repeat(40), into: 'distribution/V0666_lyceum', at: '2026-11-16T10:00:00+00:00' } },
  ballot: { rule: { quorum_percent: 50 }, ends: '2026-11-15T10:00:00+00:00', result: { status: 'PASSED', counted: 3, for: 3, against: 0, sentence: 'passed: 3 for, 0 against' }, org_go: null },
  reviews: [{ reviewer_developer_id: 4, verdict: 'approve', commit: 'a'.repeat(40), findings: 'read', at: 1 }, { reviewer_developer_id: 5, verdict: 'changes', commit: 'a'.repeat(40), findings: '', at: 2 }],
  checker: { ok: true, record: { commit: 'a'.repeat(40), read_from: 'checker', checker_kid: 'kid-1', ci: { status: 'success' }, touched: ['x'] } },
}

describe('which change is which', () => {
  it('a change in a release line is a line change; one that carries a line change upstream is carried; any other is neither', () => {
    expect(upstreamKind(line())).toBe('line')
    expect(upstreamKind({ id: 'cc_u', state: 'proposed', upstream_of: 'cc_line', provenance: PROV })).toBe('carried')
    expect(upstreamKind({ id: 'cc_m', state: 'proposed' })).toBeNull()
  })
})

describe('the action', () => {
  it('is offered to a signed-in decider on a merged line change that has not gone upstream', () => {
    expect(canProposeUpstream(line(), true)).toBe(true)
  })
  it.each([
    ['not signed in', line(), false],
    ['not a decider', line({ line_ballot: { i_decide: false } }), true],
    ['no ballot fact at all', line({ line_ballot: undefined }), true],
    ['not merged (proposed)', line({ state: 'proposed' }), true],
    ['not merged (passed)', line({ state: 'passed' }), true],
    ['not merged (withdrawn)', line({ state: 'withdrawn' }), true],
    ['already proposed upstream', line({ upstream: { change_id: 'cc_u', state: 'proposed', since: null } }), true],
    ['already landed upstream', line({ upstream: { change_id: 'cc_u', state: 'merged', since: '2026-11-20T10:00:00+00:00' } }), true],
    ['a main-line change', { id: 'cc_m', state: 'merged' }, true],
  ])('is not offered: %s', (_why, rec, signedIn) => {
    expect(canProposeUpstream(rec as any, signedIn as boolean)).toBe(false)
  })
})

describe('what the line\'s own copy says', () => {
  it('says nothing for a copy that went nowhere', () => {
    expect(lineStatus(line(), tr)).toEqual({ kind: 'none', text: '', changeId: null })
  })
  it('says the proposal and its state while it is open', () => {
    const s = lineStatus(line({ upstream: { change_id: 'cc_u', state: 'balloting', since: null } }), tr)
    expect(s.kind).toBe('proposed')
    expect(s.changeId).toBe('cc_u')
    expect(s.text).toContain('Proposed upstream')
    expect(s.text).toContain('Members voting')
  })
  it('says "upstream since" once the main code has it, with the day', () => {
    const s = lineStatus(line({ upstream: { change_id: 'cc_u', state: 'merged', since: '2026-11-20T10:00:00+00:00' } }), tr)
    expect(s.kind).toBe('landed')
    expect(s.text).toContain('Upstream since')
    expect(s.text).toContain('2026-11-20')
  })
  it.each(['withdrawn', 'failed', 'vetoed'])('says plainly when the proposal ended as %s: it is not in the main code', (state) => {
    const s = lineStatus(line({ upstream: { change_id: 'cc_u', state, since: null } }), tr)
    expect(s.kind).toBe('ended')
    expect(s.text).toMatch(/not in the main code/i)
  })
})

describe('the provenance a carried change shows', () => {
  const rec = { id: 'cc_u', state: 'proposed', upstream_of: 'cc_line', provenance: PROV }
  it('names the line, the change it carries, the ballot and its result, every review and the checker\'s record', () => {
    const f = provenanceFacts(rec as any, tr)
    expect(f.map((x) => x.key)).toEqual(['line', 'change', 'ballot', 'reviews', 'checker'])
    const by = Object.fromEntries(f.map((x) => [x.key, x.text]))
    expect(by.line).toContain('Lyceum')
    expect(by.line).toContain('Lyceum Labs')
    expect(by.line).toContain('V0666')
    expect(by.change).toContain('A clearer page')
    expect(by.ballot).toContain('passed: 3 for, 0 against')
    expect(by.reviews).toContain('1 approval')
    expect(by.reviews).toContain('1 asked for changes')
    expect(by.checker).toContain('kid-1')
    expect(by.checker).toContain('success')
  })
  it('drops nothing: a provenance with a part missing says it is not recorded, never leaves the row out', () => {
    for (const part of ['ballot', 'reviews', 'checker', 'line', 'line_change']) {
      const cut = { ...PROV } as Record<string, unknown>
      delete cut[part]
      const f = provenanceFacts({ ...rec, provenance: cut } as any, tr)
      expect(f).toHaveLength(5)
      expect(f.some((x) => /not recorded/i.test(x.text))).toBe(true)
    }
  })
  it('is empty for a change that carries nothing', () => {
    expect(provenanceFacts({ id: 'cc_m', state: 'proposed' } as any, tr)).toEqual([])
  })
  it('names the line change it came from, for the link', () => {
    expect(provenanceFacts(rec as any, tr).find((x) => x.key === 'change')?.changeId).toBe('cc_line')
  })
})
