// V0667 D5 (order gwo_d238dcda72add8e05b6d657b): the fast lane in words, pure. The registry decides every step; this words its record and builds the proposal from the form.
import { CONTENT_KINDS, type ContentKind, type ContentProposal, type ContentRecord } from '@/services/api/contentChanges'

type Tr = (key: string, fallback: string, params?: Record<string, unknown>) => string

export const CONTENT_STATES = ['balloting', 'applied', 'undone', 'failed', 'apply_failed', 'withdrawn'] as const

export function kindWord(kind: string, tr: Tr): string {
  switch (kind) {
    case 'kit': return tr('contentChanges.kind.kit', 'Migration kit')
    case 'proxy_spec': return tr('contentChanges.kind.proxy_spec', 'Proxy spec')
    case 'policy_value': return tr('contentChanges.kind.policy_value', 'Policy value')
    case 'console_text': return tr('contentChanges.kind.console_text', 'Console text')
    case 'branding': return tr('contentChanges.kind.branding', 'Branding')
    case 'compliance_pack': return tr('contentChanges.kind.compliance_pack', 'Compliance pack')
    default: return kind
  }
}

export function stateWord(state: string, tr: Tr): string {
  switch (state) {
    case 'balloting': return tr('contentChanges.state.balloting', 'In its ballot')
    case 'applied': return tr('contentChanges.state.applied', 'Applied')
    case 'undone': return tr('contentChanges.state.undone', 'Undone')
    case 'failed': return tr('contentChanges.state.failed', 'Not passed')
    case 'apply_failed': return tr('contentChanges.state.apply_failed', 'Passed, not applied')
    case 'withdrawn': return tr('contentChanges.state.withdrawn', 'Withdrawn')
    default: return state
  }
}

/** Our checker's record in a sentence. */
export function checkerLine(c: ContentRecord, tr: Tr): string {
  const k = c.checker as { ok?: boolean; rules?: string[]; bytes?: number } | null | undefined
  if (!k || k.ok !== true) return tr('contentChanges.checker.none', 'Not checked.')
  return tr('contentChanges.checker.ok', 'Our checker passed it: {rules} ({bytes} bytes).', { rules: (k.rules || []).join(', ') || '-', bytes: k.bytes ?? 0 })
}

/** The ballot in a sentence: the result once closed, else how many of the deciders voted and when it ends. */
export function ballotLine(c: ContentRecord, tr: Tr): string {
  const b = c.ballot as { result?: any; ends?: string | null; deciders?: number; cast?: number } | undefined
  if (!b) return ''
  if (b.result && typeof b.result === 'object') {
    const word = b.result.status === 'PASSED' ? tr('contentChanges.ballot.passed', 'Passed') : tr('contentChanges.ballot.failed', 'Not passed')
    return b.result.sentence ? `${word}: ${b.result.sentence}` : word
  }
  const base = tr('contentChanges.ballot.open', '{cast} of {deciders} deciders have voted', { cast: b.cast ?? 0, deciders: b.deciders ?? 0 })
  return b.ends ? `${base} · ${tr('contentChanges.ballot.ends', 'closes {when} or when all have voted', { when: b.ends.slice(0, 16).replace('T', ' ') + ' UTC' })}` : base
}

/** What the change says it puts into the organization's space, short. */
export function contentSummary(c: ContentRecord, tr: Tr): string {
  const content = (c.content || {}) as Record<string, any>
  switch (c.kind) {
    case 'kit': return tr('contentChanges.summary.kit', 'A new version of {target} with {n} files', { target: String(c.target), n: Object.keys(content.files || {}).length })
    case 'proxy_spec': return tr('contentChanges.summary.proxy', 'A new proxy.yaml for {target} ({n} lines)', { target: String(c.target), n: String(content.proxy_yaml || '').split('\n').length })
    case 'policy_value': return tr('contentChanges.summary.policy', '{key} set to {value}', { key: String(c.target), value: JSON.stringify(content.value) })
    case 'console_text': return tr('contentChanges.summary.text', 'The console text {key}: {text}', { key: String(c.target), text: String(content.text || '') })
    case 'branding': return tr('contentChanges.summary.branding', 'Branding: {fields}', { fields: Object.keys(content).join(', ') })
    case 'compliance_pack': return tr('contentChanges.summary.pack', 'The compliance pack {name}: {rules}', { name: String(c.target), rules: Object.keys(content.rules || {}).join(', ') })
    default: return String(c.target)
  }
}

/** The applied record's before and after, as the two texts the page shows side by side (a kit shows its version numbers, a setting its values). */
export function appliedDiff(c: ContentRecord): { before: string; after: string } | null {
  if (c.state !== 'applied' && c.state !== 'undone') return null
  const before = c.before as Record<string, any> | null
  const after = c.after as Record<string, any> | null
  if (!before || !after) return null
  const show = (v: unknown) => (typeof v === 'string' ? v : v === null || v === undefined ? '' : JSON.stringify(v))
  if (c.kind === 'kit' || c.kind === 'proxy_spec') return { before: `v${show(before.latest_version)}`, after: `v${show(after.version)}` }
  return { before: show(before.value), after: show(after.value) }
}

// ── the proposal form ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

export interface ContentDraft {
  line: string; kind: ContentKind; target: string; title: string; problem: string
  filesJson: string; proxyYaml: string; valueJson: string; text: string; tagline: string; accent: string; logo: string; rulesJson: string
}
export function emptyDraft(line = '', title = ''): ContentDraft {
  return { line, kind: 'console_text', target: '', title, problem: '', filesJson: '', proxyYaml: '', valueJson: '', text: '', tagline: '', accent: '', logo: '', rulesJson: '' }
}

/** The target a kind takes as its own label: a template id, a settings key, a console text key, or the fixed word. */
export function targetLabel(kind: ContentKind, tr: Tr): string {
  switch (kind) {
    case 'kit': case 'proxy_spec': return tr('contentChanges.form.targetTemplate', 'Template id (one of the organization’s own)')
    case 'policy_value': return tr('contentChanges.form.targetPolicy', 'Setting key (e.g. liability.mode)')
    case 'console_text': return tr('contentChanges.form.targetText', 'Text key (e.g. landing.tagline)')
    case 'compliance_pack': return tr('contentChanges.form.targetPack', 'Pack name (e.g. eu-retention)')
    default: return tr('contentChanges.form.targetBranding', 'Target')
  }
}

export function contentOf(d: ContentDraft): { ok: true; content: Record<string, unknown> } | { ok: false; field: string } {
  switch (d.kind) {
    case 'kit': {
      try { const files = JSON.parse(d.filesJson); return files && typeof files === 'object' && !Array.isArray(files) ? { ok: true, content: { files } } : { ok: false, field: 'files' } } catch { return { ok: false, field: 'files' } }
    }
    case 'proxy_spec': return d.proxyYaml.trim() ? { ok: true, content: { proxy_yaml: d.proxyYaml } } : { ok: false, field: 'proxy_yaml' }
    case 'policy_value': {
      try { return { ok: true, content: { value: JSON.parse(d.valueJson) } } } catch { return { ok: false, field: 'value' } }
    }
    case 'console_text': return d.text.trim() ? { ok: true, content: { text: d.text } } : { ok: false, field: 'text' }
    case 'compliance_pack': {
      try { const rules = JSON.parse(d.rulesJson); return rules && typeof rules === 'object' && !Array.isArray(rules) ? { ok: true, content: { rules } } : { ok: false, field: 'rules' } } catch { return { ok: false, field: 'rules' } }
    }
    default: {
      const content: Record<string, unknown> = {}
      if (d.tagline.trim()) content.tagline = d.tagline.trim()
      if (d.accent.trim()) content.accent_color = d.accent.trim()
      if (d.logo.trim()) content.logo_url = d.logo.trim()
      return Object.keys(content).length ? { ok: true, content } : { ok: false, field: 'branding' }
    }
  }
}

export interface Problem { field: string; sentence: string }
function contentFieldProblem(field: string, tr: Tr): string {
  switch (field) {
    case 'files': return tr('contentChanges.problem.files', 'The files are a JSON object of path to text.')
    case 'value': return tr('contentChanges.problem.value', 'The value is JSON (a number, text in quotes, true or false).')
    case 'branding': return tr('contentChanges.problem.branding', 'Give a tagline, an accent colour or a logo.')
    case 'proxy_yaml': return tr('contentChanges.problem.proxyYaml', 'Give the new proxy.yaml.')
    case 'rules': return tr('contentChanges.problem.rules', 'The rules are a JSON object: data_residency, retention, approval_thresholds, reporting.')
    default: return tr('contentChanges.problem.text', 'Fill in the text.')
  }
}
export function contentProblems(d: ContentDraft, tr: Tr): Problem[] {
  const out: Problem[] = []
  if (!d.line.trim()) out.push({ field: 'line', sentence: tr('contentChanges.problem.line', 'Choose the release line.') })
  if (!d.title.trim() || d.title.length > 160) out.push({ field: 'title', sentence: tr('contentChanges.problem.title', 'A title of 1 to 160 characters.') })
  if (!d.problem.trim() || d.problem.length > 6000) out.push({ field: 'problem', sentence: tr('contentChanges.problem.problem', 'Say why, in 1 to 6000 characters.') })
  const target = d.kind === 'branding' ? 'branding' : d.target.trim()
  if (!target || target.length > 200) out.push({ field: 'target', sentence: tr('contentChanges.problem.target', 'Name the target.') })
  const c = contentOf(d)
  if (!c.ok) out.push({ field: c.field, sentence: contentFieldProblem(c.field, tr) })
  return out
}

export function proposalOf(d: ContentDraft): ContentProposal | null {
  const c = contentOf(d)
  if (!c.ok || contentProblems(d, (_k, f) => f).length) return null
  return { code_distribution: d.line, kind: d.kind, target: d.kind === 'branding' ? 'branding' : d.target.trim(), title: d.title.trim(), problem: d.problem.trim(), content: c.content }
}

export function isKind(v: unknown): v is ContentKind { return typeof v === 'string' && (CONTENT_KINDS as readonly string[]).includes(v) }
