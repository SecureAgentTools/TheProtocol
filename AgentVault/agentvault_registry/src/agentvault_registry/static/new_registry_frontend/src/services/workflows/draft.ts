// V0663 — the workflow builder's draft: pure, no network. The server (services/workflow_rules.py) is the authority; this
// mirrors only its shapes and limits so the builder can say what is wrong before a request goes out.
import type { WorkflowBody, WorkflowRuleset } from '@/services/api/workflows'

export const MAX_STEPS = 12
const KEY_RE = /^[a-z0-9][a-z0-9_-]{0,39}$/

export interface RulesDraft {
  bondedOnly: boolean
  minReputation: string
  minProvenOrders: string
  maxPrice: string
  orgIds: string
  independentOf: string[]
}

export interface StepDraft {
  key: string
  role: string
  spec: string
  acceptance: string
  budget: string
  deadlineHours: string
  inputFrom: string
  rules: RulesDraft
}

export interface WorkflowDraft {
  title: string
  totalBudget: string
  currency: string
  rules: RulesDraft
  steps: StepDraft[]
}

export interface DraftProblem { where: string; message: string }

export function emptyRules(): RulesDraft {
  return { bondedOnly: false, minReputation: '', minProvenOrders: '', maxPrice: '', orgIds: '', independentOf: [] }
}

export function emptyStep(n: number): StepDraft {
  return { key: `step${n}`, role: '', spec: '', acceptance: '', budget: '', deadlineHours: '', inputFrom: '', rules: emptyRules() }
}

export function emptyDraft(): WorkflowDraft {
  return { title: '', totalBudget: '', currency: '', rules: emptyRules(), steps: [emptyStep(1)] }
}

function num(s: string): number | null {
  const t = (s ?? '').trim()
  if (!t) return null
  const n = Number(t)
  return Number.isFinite(n) ? n : NaN
}

/** The rules the user filled in, in the server's shape; an empty field is no rule. */
export function toRuleset(r: RulesDraft): WorkflowRuleset {
  const out: WorkflowRuleset = {}
  if (r.bondedOnly) out.bonded_only = true
  const rep = num(r.minReputation); if (rep !== null && !Number.isNaN(rep)) out.min_reputation = rep
  const proven = num(r.minProvenOrders); if (proven !== null && !Number.isNaN(proven)) out.min_proven_orders = proven
  const price = num(r.maxPrice); if (price !== null && !Number.isNaN(price)) out.max_price = price
  const orgs = r.orgIds.split(/[\s,]+/).map(s => s.trim()).filter(Boolean)
  if (orgs.length) out.org_ids = Array.from(new Set(orgs))
  if (r.independentOf.length) out.independent_of = [...r.independentOf]
  return out
}

export function budgetSum(d: WorkflowDraft): number {
  return d.steps.reduce((a, s) => a + (num(s.budget) || 0), 0)
}

function rulesProblems(where: string, r: RulesDraft, out: DraftProblem[]) {
  for (const [field, label, whole] of [['minReputation', 'minimum reputation', false], ['minProvenOrders', 'minimum proven orders', true], ['maxPrice', 'price ceiling', false]] as const) {
    const n = num(r[field])
    if (n === null) continue
    if (Number.isNaN(n) || n < 0) out.push({ where, message: `The ${label} must be a number of at least 0.` })
    else if (whole && !Number.isInteger(n)) out.push({ where, message: `The ${label} must be a whole number.` })
  }
}

export function validateDraft(d: WorkflowDraft): DraftProblem[] {
  const out: DraftProblem[] = []
  if (!d.title.trim()) out.push({ where: 'workflow', message: 'Give the workflow a title.' })
  const total = num(d.totalBudget)
  if (total === null || Number.isNaN(total) || total <= 0) out.push({ where: 'workflow', message: 'The total budget must be above zero.' })
  if (d.steps.length < 1 || d.steps.length > MAX_STEPS) out.push({ where: 'workflow', message: `A workflow has 1 to ${MAX_STEPS} steps.` })
  rulesProblems('workflow', d.rules, out)
  const seen: string[] = []
  d.steps.forEach((s, i) => {
    const w = `step ${i + 1}`
    if (!KEY_RE.test(s.key)) out.push({ where: w, message: 'The key is 1 to 40 lowercase letters, digits, - or _.' })
    else if (seen.includes(s.key)) out.push({ where: w, message: `The key ${s.key} is used twice.` })
    seen.push(s.key)
    if (!s.role.trim()) out.push({ where: w, message: 'Name the role of the step.' })
    const b = num(s.budget)
    if (b === null || Number.isNaN(b) || b <= 0) out.push({ where: w, message: 'The step budget must be above zero.' })
    const h = num(s.deadlineHours)
    if (h !== null && (Number.isNaN(h) || h * 3600 < 60 || h * 3600 > 2592000)) out.push({ where: w, message: 'The deadline is between 1 minute and 30 days.' })
    if (s.inputFrom && !d.steps.slice(0, i).some(p => p.key === s.inputFrom)) out.push({ where: w, message: 'The input must come from an earlier step.' })
    for (const k of s.rules.independentOf) {
      if (k === s.key) out.push({ where: w, message: 'A step cannot be independent of itself.' })
      else if (!d.steps.some(p => p.key === k)) out.push({ where: w, message: `Independence names no such step: ${k}.` })
    }
    rulesProblems(w, s.rules, out)
  })
  if (total !== null && !Number.isNaN(total) && total > 0 && budgetSum(d) > total) {
    out.push({ where: 'workflow', message: `The steps add up to ${budgetSum(d)}, above the total budget ${total}.` })
  }
  return out
}

export function toBody(d: WorkflowDraft): WorkflowBody {
  const body: WorkflowBody = {
    title: d.title.trim(),
    total_budget: Number(d.totalBudget),
    steps: d.steps.map(s => {
      const step: WorkflowBody['steps'][number] = { key: s.key, role: s.role.trim(), budget: Number(s.budget) }
      if (s.spec.trim()) step.spec = s.spec.trim()
      if (s.acceptance.trim()) step.acceptance = s.acceptance.trim()
      const h = num(s.deadlineHours)
      if (h !== null && !Number.isNaN(h)) step.deadline_seconds = Math.round(h * 3600)
      const rs = toRuleset(s.rules)
      if (Object.keys(rs).length) step.ruleset = rs
      if (s.inputFrom) step.input_from = s.inputFrom
      return step
    }),
  }
  if (d.currency.trim()) body.currency = d.currency.trim()
  const rs = toRuleset(d.rules)
  if (Object.keys(rs).length) body.ruleset = rs
  return body
}

/** One line per rule, for showing a ruleset to a person. */
export function describeRules(r: WorkflowRuleset): string[] {
  const out: string[] = []
  if (r.bonded_only) out.push('holds a reputation bond')
  if (r.min_reputation !== undefined) out.push(`reputation at least ${r.min_reputation}`)
  if (r.min_proven_orders !== undefined) out.push(`at least ${r.min_proven_orders} settled orders`)
  if (r.max_price !== undefined) out.push(`price at most ${r.max_price}`)
  if (r.org_ids?.length) out.push(`member of ${r.org_ids.length} named organization${r.org_ids.length === 1 ? '' : 's'}`)
  if (r.independent_of?.length) out.push(`a different owner than the worker of ${r.independent_of.join(', ')}`)
  return out
}
