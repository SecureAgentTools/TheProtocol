import { describe, expect, it } from 'vitest'
import { budgetSum, describeRules, emptyDraft, emptyRules, emptyStep, toBody, toRuleset, validateDraft } from './draft'

function filled() {
  const d = emptyDraft()
  d.title = 'Release chain'
  d.totalBudget = '30'
  d.steps[0].key = 'build'; d.steps[0].role = 'builder'; d.steps[0].budget = '10'
  d.steps.push({ ...emptyStep(2), key: 'verify', role: 'verifier', budget: '10', inputFrom: 'build' })
  return d
}

describe('toRuleset', () => {
  it('writes only what was filled in, in the server shape', () => {
    const r = emptyRules()
    r.bondedOnly = true; r.minReputation = '3'; r.minProvenOrders = '2'; r.maxPrice = '5.5'; r.orgIds = 'b, a  a'; r.independentOf = ['build']
    expect(toRuleset(r)).toEqual({ bonded_only: true, min_reputation: 3, min_proven_orders: 2, max_price: 5.5, org_ids: ['b', 'a'], independent_of: ['build'] })
    expect(toRuleset(emptyRules())).toEqual({})
  })
})

describe('validateDraft', () => {
  it('passes a complete draft', () => { expect(validateDraft(filled())).toEqual([]) })
  it('names each problem where it is', () => {
    const d = filled()
    d.title = ' '; d.steps[1].inputFrom = 'nope'; d.steps[0].budget = '0'; d.steps[1].key = 'build'
    const where = validateDraft(d).map(p => p.where)
    expect(where).toContain('workflow'); expect(where).toContain('step 1'); expect(where).toContain('step 2')
  })
  it('refuses steps that add up to more than the total', () => {
    const d = filled(); d.totalBudget = '15'
    expect(validateDraft(d).some(p => /above the total/.test(p.message))).toBe(true)
  })
  it('refuses independence from itself or from a step that does not exist', () => {
    const d = filled(); d.steps[1].rules.independentOf = ['verify', 'ghost']
    const msgs = validateDraft(d).map(p => p.message).join(' | ')
    expect(msgs).toMatch(/itself/); expect(msgs).toMatch(/ghost/)
  })
  it('a whole-number rule refuses a fraction', () => {
    const d = filled(); d.rules.minProvenOrders = '1.5'
    expect(validateDraft(d).some(p => /whole number/.test(p.message))).toBe(true)
  })
  it('a deadline outside a minute to thirty days is refused', () => {
    const d = filled(); d.steps[0].deadlineHours = '1000'
    expect(validateDraft(d).some(p => /deadline/.test(p.message))).toBe(true)
  })
})

describe('toBody and budgetSum', () => {
  it('builds the request, leaving out what is empty', () => {
    const d = filled(); d.rules.bondedOnly = true; d.steps[1].rules.independentOf = ['build']; d.steps[0].deadlineHours = '2'
    const b = toBody(d)
    expect(b).toEqual({
      title: 'Release chain', total_budget: 30, ruleset: { bonded_only: true },
      steps: [
        { key: 'build', role: 'builder', budget: 10, deadline_seconds: 7200 },
        { key: 'verify', role: 'verifier', budget: 10, input_from: 'build', ruleset: { independent_of: ['build'] } },
      ],
    })
    expect(budgetSum(d)).toBe(20)
  })
})

describe('describeRules', () => {
  it('reads a ruleset as plain lines', () => {
    expect(describeRules({ bonded_only: true, independent_of: ['build'], org_ids: ['x'] })).toEqual([
      'holds a reputation bond', 'member of 1 named organization', 'a different owner than the worker of build'])
    expect(describeRules({})).toEqual([])
  })
})
