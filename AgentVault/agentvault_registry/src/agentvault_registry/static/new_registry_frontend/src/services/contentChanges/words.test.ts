/**
 * V0667 D5 (order gwo_d238dcda72add8e05b6d657b): the fast lane in words and the proposal built from the form, pure.
 * Red before D5: services/contentChanges/words.ts does not exist.
 */
import { describe, expect, it } from 'vitest'
import { appliedDiff, ballotLine, checkerLine, contentOf, contentProblems, contentSummary, emptyDraft, kindWord, proposalOf, stateWord, targetLabel } from './words'

const tr = (_k: string, f: string, p?: Record<string, unknown>) => (p ? f.replace(/\{(\w+)\}/g, (_, k) => String(p[k])) : f)
const draft = (over: Record<string, unknown> = {}) => ({ ...emptyDraft('lyceum', 'A change'), problem: 'Because.', ...over }) as any

describe('the words', () => {
  it('names every kind and every state in words, and an unknown one as it is', () => {
    expect(['kit', 'proxy_spec', 'policy_value', 'console_text', 'branding'].map((k) => kindWord(k, tr))).toEqual(['Migration kit', 'Proxy spec', 'Policy value', 'Console text', 'Branding'])
    expect(['balloting', 'applied', 'undone', 'failed', 'apply_failed', 'withdrawn'].map((s) => stateWord(s, tr))).toEqual(['In its ballot', 'Applied', 'Undone', 'Not passed', 'Passed, not applied', 'Withdrawn'])
    expect(kindWord('x', tr)).toBe('x')
  })
  it('says what our checker ran, and "Not checked" without a record', () => {
    expect(checkerLine({ checker: { ok: true, rules: ['schema', 'secrets'], bytes: 42 } }, tr)).toBe('Our checker passed it: schema, secrets (42 bytes).')
    expect(checkerLine({}, tr)).toBe('Not checked.')
  })
  it('words the ballot: how many voted while open, the registry\'s sentence once closed', () => {
    expect(ballotLine({ ballot: { cast: 1, deciders: 3, ends: '2026-11-23T10:00:00+00:00' } }, tr)).toBe('1 of 3 deciders have voted · closes 2026-11-23 10:00 UTC or when all have voted')
    expect(ballotLine({ ballot: { result: { status: 'PASSED', sentence: '2 for, 0 against, of 3 deciders: passed' } } }, tr)).toBe('Passed: 2 for, 0 against, of 3 deciders: passed')
    expect(ballotLine({ ballot: { result: { status: 'FAILED' } } }, tr)).toBe('Not passed')
    expect(ballotLine({}, tr)).toBe('')
  })
  it('summarises each kind\'s content in one line', () => {
    expect(contentSummary({ kind: 'kit', target: 'wtpl_1', content: { files: { a: '1', b: '2' } } }, tr)).toBe('A new version of wtpl_1 with 2 files')
    expect(contentSummary({ kind: 'proxy_spec', target: 'wtpl_1', content: { proxy_yaml: 'a\nb\nc' } }, tr)).toBe('A new proxy.yaml for wtpl_1 (3 lines)')
    expect(contentSummary({ kind: 'policy_value', target: 'liability.mode', content: { value: 'shadow' } }, tr)).toBe('liability.mode set to "shadow"')
    expect(contentSummary({ kind: 'console_text', target: 'landing.tagline', content: { text: 'Hi' } }, tr)).toBe('The console text landing.tagline: Hi')
    expect(contentSummary({ kind: 'branding', target: 'branding', content: { tagline: 'x', accent_color: '#000000' } }, tr)).toBe('Branding: tagline, accent_color')
  })
  it('shows the applied before and after: version numbers for a kit, values for a setting; nothing before it applied', () => {
    expect(appliedDiff({ state: 'applied', kind: 'kit', before: { latest_version: 1 }, after: { version: 2 } })).toEqual({ before: 'v1', after: 'v2' })
    expect(appliedDiff({ state: 'applied', kind: 'policy_value', before: { value: null }, after: { value: 14 } })).toEqual({ before: '', after: '14' })
    expect(appliedDiff({ state: 'undone', kind: 'console_text', before: { value: 'old' }, after: { value: 'new' } })).toEqual({ before: 'old', after: 'new' })
    expect(appliedDiff({ state: 'balloting', kind: 'console_text', before: null, after: null })).toBeNull()
  })
  it('labels the target of each kind', () => {
    expect(targetLabel('kit', tr)).toMatch(/Template id/)
    expect(targetLabel('policy_value', tr)).toMatch(/Setting key/)
    expect(targetLabel('console_text', tr)).toMatch(/Text key/)
  })
})

describe('the proposal built from the form', () => {
  it('builds each kind\'s content, and refuses what cannot be sent', () => {
    expect(contentOf(draft({ kind: 'kit', filesJson: '{"a.txt":"x"}' }))).toEqual({ ok: true, content: { files: { 'a.txt': 'x' } } })
    expect(contentOf(draft({ kind: 'kit', filesJson: '[1]' }))).toEqual({ ok: false, field: 'files' })
    expect(contentOf(draft({ kind: 'kit', filesJson: 'nope' }))).toEqual({ ok: false, field: 'files' })
    expect(contentOf(draft({ kind: 'proxy_spec', proxyYaml: 'version: 1' }))).toEqual({ ok: true, content: { proxy_yaml: 'version: 1' } })
    expect(contentOf(draft({ kind: 'policy_value', valueJson: '14' }))).toEqual({ ok: true, content: { value: 14 } })
    expect(contentOf(draft({ kind: 'policy_value', valueJson: 'shadow' }))).toEqual({ ok: false, field: 'value' })
    expect(contentOf(draft({ kind: 'console_text', text: ' ' }))).toEqual({ ok: false, field: 'text' })
    expect(contentOf(draft({ kind: 'branding', tagline: ' Lyceum ', accent: '#12ab9f' }))).toEqual({ ok: true, content: { tagline: 'Lyceum', accent_color: '#12ab9f' } })
    expect(contentOf(draft({ kind: 'branding' }))).toEqual({ ok: false, field: 'branding' })
  })
  it('lists what is missing, in sentences', () => {
    const p = contentProblems(emptyDraft(), tr)
    expect(p.map((x) => x.field)).toEqual(['line', 'title', 'problem', 'target', 'text'])
    expect(contentProblems(draft({ kind: 'console_text', target: 'landing.tagline', text: 'ok' }), tr)).toEqual([])
  })
  it('a branding change needs no target: its target is the word branding', () => {
    expect(proposalOf(draft({ kind: 'branding', tagline: 'Hi' }))).toEqual({ code_distribution: 'lyceum', kind: 'branding', target: 'branding', title: 'A change', problem: 'Because.', content: { tagline: 'Hi' } })
  })
  it('gives nothing to send while anything is missing', () => {
    expect(proposalOf(draft({ kind: 'console_text', target: '', text: 'x' }))).toBeNull()
    expect(proposalOf(draft({ kind: 'console_text', target: 'landing.tagline', text: 'x' }))).toEqual({ code_distribution: 'lyceum', kind: 'console_text', target: 'landing.tagline', title: 'A change', problem: 'Because.', content: { text: 'x' } })
  })
})

describe('V0667 D7: the compliance pack, the sixth kind', () => {
  it('has its word, its summary and its target label', () => {
    expect(kindWord('compliance_pack', tr)).toBe('Compliance pack')
    expect(contentSummary({ kind: 'compliance_pack', target: 'eu-retention', content: { rules: { retention: { audit_log_days: 2555 }, reporting: { interval_days: 90 } } } }, tr)).toBe('The compliance pack eu-retention: retention, reporting')
    expect(targetLabel('compliance_pack', tr)).toMatch(/Pack name/)
  })
  it('builds the pack from the form: a JSON object of rules, nothing else', () => {
    expect(contentOf(draft({ kind: 'compliance_pack', rulesJson: '{"retention":{"audit_log_days":2555}}' }))).toEqual({ ok: true, content: { rules: { retention: { audit_log_days: 2555 } } } })
    expect(contentOf(draft({ kind: 'compliance_pack', rulesJson: '[1]' }))).toEqual({ ok: false, field: 'rules' })
    expect(contentOf(draft({ kind: 'compliance_pack', rulesJson: 'nope' }))).toEqual({ ok: false, field: 'rules' })
    expect(proposalOf(draft({ kind: 'compliance_pack', target: 'eu-retention', rulesJson: '{"reporting":{"interval_days":90}}' }))).toEqual({
      code_distribution: 'lyceum', kind: 'compliance_pack', target: 'eu-retention', title: 'A change', problem: 'Because.', content: { rules: { reporting: { interval_days: 90 } } } })
  })
  it('says what is missing for a pack in a sentence', () => {
    expect(contentProblems(draft({ kind: 'compliance_pack', target: 'eu-retention', rulesJson: '' }), tr).map((p) => p.field)).toEqual(['rules'])
  })
})
