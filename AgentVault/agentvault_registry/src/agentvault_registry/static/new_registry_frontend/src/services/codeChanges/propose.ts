// V0664 (order gwo_fc4ec96d3679ca02d5e3afa8): the guided proposal's rules, pure: what each step needs before the next, the path suggestions from the console tree, what each
// added path means, and the body the registry takes. The registry decides again (services/code_changes.propose); this says what it will say before the person presses Propose.
import { CONSOLE_PREFIX, REPOSITORY, checkPaths, isCommitId, isForbidden, isSensitive, type PathCheck } from './pathRules'
import { pathLabel, pathsInsideLine } from '@/services/codeDistributions/lines'

/** V0666 D2: a proposal into an organization's release line (its code distribution) names the line and stays inside its open paths (D1: paths_inside_line). */
export interface LineTarget { slug: string; open_paths: string[] }

export type Mode = 'bounty' | 'branch'
export interface Draft { title: string; problem: string; paths: string[]; mode: Mode; bounty: string; branch: string; commit: string }
export const emptyDraft = (): Draft => ({ title: '', problem: '', paths: [], mode: 'bounty', bounty: '', branch: '', commit: '' })

export const STEPS = ['what', 'files', 'how', 'review'] as const
export type StepId = typeof STEPS[number]

export interface Problem { field: string; sentence: string }
type Tr = (key: string, fallback: string, params?: Record<string, unknown>) => string

/** What a step still needs, as sentences (empty: the step may be left). */
export function problemsFor(step: StepId, d: Draft, tr: Tr, line?: LineTarget | null): Problem[] {
  const out: Problem[] = []
  if (step === 'what' || step === 'review') {
    if (!d.title.trim()) out.push({ field: 'title', sentence: tr('codeChanges.new.needTitle', 'Give the change a title.') })
    else if (d.title.trim().length > 160) out.push({ field: 'title', sentence: tr('codeChanges.new.longTitle', 'A title of at most 160 characters.') })
    if (d.problem.trim().length < 20) out.push({ field: 'problem', sentence: tr('codeChanges.new.needProblem', 'Say what is wrong, in a sentence or two (at least 20 characters).') })
    else if (d.problem.trim().length > 6000) out.push({ field: 'problem', sentence: tr('codeChanges.new.longProblem', 'The problem fits in 6000 characters.') })
  }
  if (step === 'files' || step === 'review') {
    const c = checkPaths(REPOSITORY, d.paths)
    if (!c.ok) out.push({ field: 'paths', sentence: c.reason || '' })
    else if (line) { const why = pathsInsideLine(d.paths, line.open_paths, (p) => pathLabel(p, tr)); if (why) out.push({ field: 'paths', sentence: why }) }
  }
  if (step === 'how' || step === 'review') {
    if (d.mode === 'bounty') {
      const n = Number(String(d.bounty).replace(',', '.'))
      if (!String(d.bounty).trim() || !Number.isFinite(n) || n <= 0) out.push({ field: 'bounty', sentence: tr('codeChanges.new.needBounty', 'A bounty above zero.') })
    } else {
      if (!d.branch.trim()) out.push({ field: 'branch', sentence: tr('codeChanges.new.needBranch', 'Name the branch that holds the code.') })
      if (!isCommitId(d.commit.trim())) out.push({ field: 'commit', sentence: tr('codeChanges.new.needCommit', 'The commit as a full id: 40 hexadecimal characters (64 for a SHA-256 repository).') })
    }
  }
  return out
}

export interface PathRow { path: string; status: 'ok' | 'sensitive' | 'refused'; sentence: string }
/** What each added path means by itself (the whole list is checked as one in problemsFor). */
export function pathRows(paths: string[], tr: Tr, line?: LineTarget | null): PathRow[] {
  return paths.map((p) => {
    const c: PathCheck = checkPaths(REPOSITORY, [p])
    if (!c.ok) return { path: p, status: 'refused', sentence: c.reason || '' }
    const outside = line ? pathsInsideLine([p], line.open_paths, (x) => pathLabel(x, tr)) : null
    if (outside) return { path: p, status: 'refused', sentence: outside }
    return c.sensitive
      ? { path: p, status: 'sensitive', sentence: tr('codeChanges.new.pathSensitive', 'Sensitive: two approving reviews and the stricter ballot.') }
      : { path: p, status: 'ok', sentence: line ? tr('contributions.propose.pathOk', 'Open in this line.') : tr('codeChanges.new.pathOk', 'Open in this phase.') }
  })
}

export interface Tree { dirs: string[]; files: string[] }
/** Suggestions for what the person is typing: the console's files and directories (relative to src/), the best first (a match at the start of a name, then anywhere),
 *  never a forbidden one, never one already added. `typed` may be a full path or the part after src/. */
export function suggestions(typed: string, tree: Tree, have: string[], limit = 8): string[] {
  const q = typed.trim().replace(CONSOLE_PREFIX, '').toLowerCase()
  if (!q) return []
  const haveRel = new Set(have.map((p) => p.replace(CONSOLE_PREFIX, '')))
  const score = (p: string): number => {
    const low = p.toLowerCase()
    const base = low.split('/').pop() || low
    if (low === q) return 0
    if (base.startsWith(q)) return 1
    if (low.startsWith(q)) return 2
    if (base.includes(q)) return 3
    return low.includes(q) ? 4 : 9
  }
  return [...tree.dirs.map((d) => d + '/'), ...tree.files]
    .filter((p) => !isForbidden(CONSOLE_PREFIX + p) && !haveRel.has(p.replace(/\/$/, '')) && !haveRel.has(p))
    .map((p) => [score(p), p] as const).filter(([s]) => s < 9)
    .sort((a, b) => a[0] - b[0] || a[1].length - b[1].length || a[1].localeCompare(b[1]))
    .slice(0, limit).map(([, p]) => p)
}

/** A path typed or picked, as the registry takes it: under the console, no trailing slash. */
export function fullPath(typed: string): string {
  const t = typed.trim().replace(/\/+$/, '')
  return !t ? '' : t.startsWith(CONSOLE_PREFIX.replace(/\/$/, '')) || t.includes('/') && t.split('/')[0] === 'agentvault_registry' ? t : CONSOLE_PREFIX + t.replace(/^\/+/, '')
}

export function bodyFor(d: Draft, line?: LineTarget | null, room?: string | null): Record<string, unknown> {
  const base: Record<string, unknown> = { repository: REPOSITORY, paths: d.paths, title: d.title.trim(), problem: d.problem.trim() }
  if (line) base.code_distribution = line.slug
  // V0666 D3: the room /change came from (a line's change only; the registry checks it is the line's organization's)
  if (line && room) base.room_id = room
  if (d.mode === 'bounty') base.bounty = Number(String(d.bounty).replace(',', '.'))
  else Object.assign(base, { branch: d.branch.trim(), commit: d.commit.trim() })
  return base
}

export { isSensitive }
