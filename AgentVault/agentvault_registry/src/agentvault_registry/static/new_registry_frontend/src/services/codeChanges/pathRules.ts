// V0664 (order gwo_fc4ec96d3679ca02d5e3afa8): the registry's rules for a code change's paths, a commit id and the reviews, in the browser, so the guided
// proposal says what the registry will say BEFORE the person presses Propose. A port of services/code_changes.py (check_paths, _SHA, reviews_verdict) pinned
// by vectors made by running that Python (path.vectors.json); the registry decides again at every step.
export const REPOSITORY = 'theprotocol/AgentVault'
export const CONSOLE_PREFIX = 'agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/'
export const OPEN_PATHS: Record<string, string[]> = { [REPOSITORY]: [CONSOLE_PREFIX] }
export const MAX_PATHS = 50
export const MAX_PATH_LEN = 300

// never open to a vote in this phase: secrets and keys, and the files that decide what code runs or what it depends on
const FORBIDDEN = /(^|\/)\.env|\.pem$|\.key$|\.p12$|\.crt$|secret|credential|password|(^|\/)keys?\/|(^|\/)package(-lock)?\.json$|(^|\/)\.npmrc$|(^|\/)Dockerfile|(^|\/)vite\.config|(^|\/)tsconfig[^/]*\.json$/i
// a change here needs a second reviewer and the policy_change thresholds: auth, admin, money, federation trust
const SENSITIVE = /auth|admin|wallet|fiat|treasury|payment|escrow|stake|bond|federation|signing|(^|\/)router\/|services\/api\/client\.ts$|safeUrl/i
const SHA = /^[0-9a-f]{40}([0-9a-f]{24})?$/

export interface PathCheck { ok: boolean; reason: string | null; sensitive: boolean; paths: string[] }

const malformed = (p: unknown): boolean => {
  if (typeof p !== 'string' || !p || [...p].length > MAX_PATH_LEN) return true
  if (p.startsWith('/') || p.includes('\\') || p.includes('//')) return true
  return p.split('/').some((seg) => seg === '..' || seg === '.')
}
export const isForbidden = (p: string): boolean => FORBIDDEN.test(p)
export const isSensitive = (p: string): boolean => SENSITIVE.test(p)
export const isCommitId = (v: string): boolean => SHA.test(v)

/** Whether a change may name these paths in this phase, and whether it is sensitive. A refusal says why (the registry's own sentence). */
export function checkPaths(repository: string, paths: unknown[]): PathCheck {
  const no = (reason: string): PathCheck => ({ ok: false, reason, sensitive: false, paths: [] })
  const prefixes = OPEN_PATHS[repository]
  if (!prefixes) return no(`the repository ${pyRepr(repository)} is not open to proposals in this phase`)
  if (!paths.length) return no('no paths: name the files or directories the change touches')
  if (paths.length > MAX_PATHS) return no(`more than ${MAX_PATHS} paths`)
  if (new Set(paths).size !== paths.length) return no('a path is named twice')
  for (const p of paths) {
    if (malformed(p)) return no(`a malformed path: ${pyRepr(String(p).slice(0, 80))} (relative, forward slashes, no '..')`)
    const s = p as string
    if (isForbidden(s)) return no(`a forbidden path: ${s} (secrets, keys, build and dependency files are never voted on)`)
    if (!prefixes.some((pre) => s === pre.replace(/\/+$/, '') || s.startsWith(pre.endsWith('/') ? pre : pre + '/'))) {
      return no(`${s} is not open in this phase (open: ${prefixes.join(', ')})`)
    }
  }
  return { ok: true, reason: null, sensitive: paths.some((p) => isSensitive(p as string)), paths: [...(paths as string[])] }
}

/** Python's repr of a short string: single quotes unless the text holds one and no double quote. */
function pyRepr(s: string): string {
  const q = s.includes("'") && !s.includes('"') ? '"' : "'"
  return q + s.replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/\r/g, '\\r').replace(/\t/g, '\\t').replace(new RegExp(q, 'g'), '\\' + q) + q
}

export interface ReviewRow { reviewer_developer_id?: number | null; verdict?: string; commit?: string; at?: number }
export interface ReviewVerdict { ok: boolean; approvals: number; needed: number; blockers: number[] }
/** Independent reviews of THIS commit: each reviewer's latest word; one asking for changes holds the ballot; a sensitive change needs two approvals. */
export function reviewsVerdict(reviews: ReviewRow[], commit: string, sensitive: boolean, excluded: ReadonlySet<number> = new Set()): ReviewVerdict {
  const latest = new Map<number, ReviewRow>()
  for (const r of reviews) {
    const dev = r.reviewer_developer_id
    if (r.commit !== commit || dev === null || dev === undefined || excluded.has(dev)) continue
    const cur = latest.get(dev)
    if (!cur || (r.at || 0) >= (cur.at || 0)) latest.set(dev, r)
  }
  const approvals = [...latest].filter(([, r]) => r.verdict === 'approve').map(([d]) => d).sort((a, b) => a - b)
  const blockers = [...latest].filter(([, r]) => r.verdict === 'changes').map(([d]) => d).sort((a, b) => a - b)
  const needed = sensitive ? 2 : 1
  return { ok: approvals.length >= needed && !blockers.length, approvals: approvals.length, needed, blockers }
}
