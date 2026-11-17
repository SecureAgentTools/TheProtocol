// V0666 D2 (order gwo_f565ebd0575703f199dd9200): an organization's code distributions (its release lines, never an AGORA payout) in words, pure: the
// queue's lanes, who decides and who may act, the ballot and the checker in sentences, the line form's rules and the admin inbox's order and filters.
// Ports of D1's rules (services/code_distributions.py: SLUG, RELEASE, the quorum bounds, the pass rules, deciders(), paths_inside_line()); the
// registry decides every step again and its refusal sentence is what the page shows.
import type { ChangeRecord } from '@/services/api/codeChanges'
import type { LineRecord } from '@/services/api/codeDistributions'
import { CONSOLE_PREFIX, OPEN_PATHS, REPOSITORY, checkPaths } from '@/services/codeChanges/pathRules'

type Tr = (key: string, fallback: string, params?: Record<string, unknown>) => string

export const SLUG = /^[a-z][a-z0-9-]{1,39}$/
export const RELEASE = /^V[0-9]{4}$/
export const QUORUM_MIN = 50
export const QUORUM_MAX = 100
export const QUORUM_DEFAULT = 50
export const PASS_RULES = ['simple'] as const
const DECIDING_ROLES = ['owner', 'admin']
const PROPOSING_ROLES = ['owner', 'admin', 'member']

// -- the queue --------------------------------------------------------------------------------------------------------
/** The queue's lanes in the order a change goes; "ended" holds a change that failed, was vetoed or withdrawn (a failed change is never dropped), "other" a
 *  state this console does not know yet (shown, never hidden). */
export const LANES = ['proposed', 'checked', 'review', 'balloting', 'passed', 'merged', 'ended', 'other'] as const
export type Lane = typeof LANES[number]

const reviewsOfCommit = (c: ChangeRecord): unknown[] => (Array.isArray(c.reviews) ? c.reviews.filter((r: any) => !c.commit || r?.commit === c.commit) : [])

/** Where a change stands in its line's queue: checked = the signed checks passed and nobody has reviewed the commit yet; in review = a review is in. */
export function laneOf(c: ChangeRecord): Lane {
  switch (String(c.state || '')) {
    case 'proposed': return 'proposed'
    case 'accepted': return reviewsOfCommit(c).length ? 'review' : 'checked'
    case 'balloting': return 'balloting'
    case 'passed': return 'passed'
    case 'merged': return 'merged'
    case 'failed': case 'vetoed': case 'withdrawn': return 'ended'
    default: return 'other'
  }
}

export function groupByLane(changes: ChangeRecord[]): Record<Lane, ChangeRecord[]> {
  const out = Object.fromEntries(LANES.map((l) => [l, [] as ChangeRecord[]])) as Record<Lane, ChangeRecord[]>
  for (const c of changes) out[laneOf(c)].push(c)
  return out
}

export function laneWord(lane: Lane, tr: Tr): string {
  switch (lane) {
    case 'proposed': return tr('contributions.lane.proposed', 'Proposed')
    case 'checked': return tr('contributions.lane.checked', 'Checked')
    case 'review': return tr('contributions.lane.review', 'In review')
    case 'balloting': return tr('contributions.lane.balloting', 'Balloting')
    case 'passed': return tr('contributions.lane.passed', 'Passed')
    case 'merged': return tr('contributions.lane.merged', 'Merged')
    case 'ended': return tr('contributions.lane.ended', 'Ended')
    default: return tr('contributions.lane.other', 'Other')
  }
}

/** A line change's state in words: the main line's words, except that a line's ballot is its deciders', never the frame's members'. */
export function lineStateWord(state: string, mainWord: (s: string) => string, tr: Tr): string {
  return state === 'balloting' ? tr('contributions.state.balloting', 'Deciders voting') : mainWord(state)
}

// -- who may act --------------------------------------------------------------------------------------------------------
export interface Me {
  /** the signed-in developer, or null */
  developerId: number | null
  /** the developer's role in the line's organization (owner, admin, member, guest), or null: not a member */
  orgRole: string | null
  /** whether the developer leads the line's deciding team */
  teamLead: boolean
  /** the organization's owner (its owner_id) */
  orgOwnerId?: number | null
}

/** D1's deciders(): the organization's owners and admins, and the deciding team's leads who are non-guest members (the registry also requires a verified
 *  account in good standing, which the console cannot see: it decides again at the vote). */
export const isDecider = (me: Me): boolean =>
  me.developerId !== null && !!me.orgRole && (DECIDING_ROLES.includes(me.orgRole) || (me.teamLead && PROPOSING_ROLES.includes(me.orgRole)))
/** A member proposes into its organization's line; a guest neither proposes, reviews nor decides. */
export const canPropose = (me: Me): boolean => !!me.orgRole && PROPOSING_ROLES.includes(me.orgRole)
/** Owners and admins create and change the organization's lines. */
export const canManage = (me: Me): boolean => !!me.orgRole && DECIDING_ROLES.includes(me.orgRole)
export const isOrgOwner = (me: Me): boolean => me.developerId !== null && me.orgOwnerId !== undefined && me.orgOwnerId !== null && me.orgOwnerId === me.developerId

const windowOpen = (c: ChangeRecord, now: Date): boolean => {
  const closes = c.veto_window_closes_at ? new Date(String(c.veto_window_closes_at)) : null
  return !closes || Number.isNaN(closes.getTime()) || now < closes
}
const lineActive = (c: ChangeRecord): boolean => (c.code_distribution as any)?.state !== 'paused'

export interface Offer { offer: boolean; why: string }
/** The vote control: a decider's, while the line's ballot is open and the line is not paused. */
export function voteOffer(c: ChangeRecord, me: Me, tr: Tr): Offer {
  if (c.state !== 'balloting') return { offer: false, why: '' }
  if (!lineActive(c)) return { offer: false, why: tr('contributions.vote.paused', 'The line is paused: no vote is taken until it resumes.') }
  if (!isDecider(me)) return { offer: false, why: tr('contributions.vote.notDecider', 'The organization’s owners and admins and the deciding team’s leads vote here.') }
  return { offer: true, why: '' }
}
/** The organization owner's go and veto: on a passed change, inside the veto window. */
export function ownerOffer(c: ChangeRecord, me: Me, now: Date = new Date()): boolean {
  return c.state === 'passed' && isOrgOwner(me) && windowOpen(c, now)
}
/** The platform maintainer's veto and go in the inbox: a passed change inside its window (the registry takes them from his account only). */
export function maintainerOffer(c: ChangeRecord, now: Date = new Date()): boolean {
  return c.state === 'passed' && windowOpen(c, now)
}

// -- the record in words --------------------------------------------------------------------------------------------------
/** The signed checker's record of the change's commit. */
export function checkerWords(c: ChangeRecord, tr: Tr): { state: 'none' | 'ok' | 'failed'; text: string } {
  const a = c.acceptance as { ok?: boolean; reasons?: string[] } | null | undefined
  if (!a || typeof a.ok !== 'boolean') return { state: 'none', text: tr('contributions.checker.none', 'Not checked yet: the signed checker reads the commit first.') }
  if (a.ok) return { state: 'ok', text: tr('contributions.checker.ok', 'The signed checks passed for this commit.') }
  return { state: 'failed', text: tr('contributions.checker.failed', 'The signed checks did not pass: {reasons}', { reasons: (a.reasons || []).join('; ') || '?' }) }
}

export function reviewWords(c: ChangeRecord, tr: Tr): string {
  const rv = (c.review_verdict || {}) as { approvals?: number; needed?: number; blockers?: number[] }
  const n = reviewsOfCommit(c).length
  if (!n) return tr('contributions.review.none', 'No review yet')
  const base = tr('contributions.review.count', '{a} of {n} approving reviews', { a: rv.approvals ?? 0, n: rv.needed ?? 1 })
  return rv.blockers && rv.blockers.length ? `${base} · ${tr('contributions.review.blocked', 'a reviewer asks for changes')}` : base
}

/** The line's own ballot (code_distribution_votes, counted by the registry), in a sentence: the result once closed, else how many of the deciders voted. */
export function ballotWords(c: ChangeRecord, tr: Tr): string {
  const lb = c.line_ballot as { ends?: string | null; result?: any; votes?: number; deciders_now?: number; deciders_note?: string | null } | undefined
  if (!lb) return ''
  if (lb.result && typeof lb.result === 'object') {
    const word = lb.result.status === 'PASSED' ? tr('contributions.ballot.passed', 'Passed') : tr('contributions.ballot.failed', 'Failed')
    const words = lb.result.sentence ? `${word}: ${lb.result.sentence}` : word
    // V0668 (gwo_2d51e1af): a closed ballot says when it closed (its result's closed_at)
    const closed = lb.result.closed_at ? new Date(lb.result.closed_at) : null
    return closed && !Number.isNaN(closed.getTime())
      ? tr('contributions.ballot.closedAt', '{words} (closed {when})', { words, when: closed.toISOString().slice(0, 16).replace('T', ' ') + ' UTC' })
      : words
  }
  if (c.state !== 'balloting') return lb.deciders_note || ''
  if (lb.deciders_note) return lb.deciders_note
  const ends = lb.ends ? new Date(lb.ends) : null
  const when = ends && !Number.isNaN(ends.getTime()) ? ends.toISOString().slice(0, 16).replace('T', ' ') + ' UTC' : '?'
  return tr('contributions.ballot.open', '{v} of {n} deciders voted; it closes at {when}, or once every decider has voted', { v: lb.votes ?? 0, n: lb.deciders_now ?? 0, when })
}

// -- the line form --------------------------------------------------------------------------------------------------------
export interface LineDraft { slug: string; title: string; base_release: string; open_paths: string[]; decider_team_id: string; quorum_percent: string | number; pass_rule: string }
export const emptyLine = (base = ''): LineDraft => ({ slug: '', title: '', base_release: base, open_paths: [], decider_team_id: '', quorum_percent: QUORUM_DEFAULT, pass_rule: 'simple' })
export const draftOf = (l: LineRecord): LineDraft => ({
  slug: String(l.slug || ''), title: String(l.title || ''), base_release: String(l.base_release || ''), open_paths: [...(l.open_paths || [])],
  decider_team_id: String(l.decider_team_id || ''), quorum_percent: l.quorum_percent ?? QUORUM_DEFAULT, pass_rule: String(l.pass_rule || 'simple'),
})

/** The platform's open paths, the only ones a line may open (or narrow to a part of). */
export const platformOpenPaths = (): string[] => [...(OPEN_PATHS[REPOSITORY] || [])]
/** A path as a person reads it: under the console, the part after src/; the console itself, named. */
export const pathLabel = (p: string, tr: Tr): string => {
  const rel = p.startsWith(CONSOLE_PREFIX) ? p.slice(CONSOLE_PREFIX.length).replace(/\/+$/, '') : p
  return rel || tr('contributions.form.wholeConsole', 'The whole console')
}

/** The release a line sits on, from a registry's software version (TheProtocolReleaseV0666 → V0666), or '' when the version names none. */
export function releaseOf(version: unknown): string {
  const m = /V(\d{3,6})$/.exec(String(version || ''))
  if (!m) return ''
  const n = m[1].replace(/^0+(?=\d{4})/, '')
  return n.length <= 4 ? `V${n.padStart(4, '0')}` : ''
}

export interface Problem { field: string; sentence: string }
export function lineProblems(d: LineDraft, mode: 'create' | 'edit', tr: Tr): Problem[] {
  const out: Problem[] = []
  if (mode === 'create') {
    if (!SLUG.test(d.slug)) out.push({ field: 'slug', sentence: tr('contributions.form.badSlug', 'A name of 2 to 40 lowercase letters, digits and \'-\', starting with a letter.') })
    if (!RELEASE.test(d.base_release)) out.push({ field: 'base_release', sentence: tr('contributions.form.badRelease', 'The base release is a release name such as V0666.') })
  }
  const title = d.title.trim()
  if (!title || title.length > 200) out.push({ field: 'title', sentence: tr('contributions.form.badTitle', 'A title of 1 to 200 characters.') })
  if (!d.open_paths.length) out.push({ field: 'open_paths', sentence: tr('contributions.form.needPaths', 'Choose at least one path the line opens.') })
  else {
    const pc = checkPaths(REPOSITORY, d.open_paths)
    if (!pc.ok) out.push({ field: 'open_paths', sentence: pc.reason || '' })
  }
  const q = Number(d.quorum_percent)
  if (!Number.isInteger(q) || q < QUORUM_MIN || q > QUORUM_MAX) {
    out.push({ field: 'quorum_percent', sentence: tr('contributions.form.badQuorum', 'The quorum is a whole percent from {min} to {max}.', { min: QUORUM_MIN, max: QUORUM_MAX }) })
  }
  if (!(PASS_RULES as readonly string[]).includes(d.pass_rule)) out.push({ field: 'pass_rule', sentence: tr('contributions.form.badRule', 'The pass rule is a simple majority.') })
  return out
}

export function lineBody(d: LineDraft, organizationId: string) {
  return {
    organization_id: organizationId, slug: d.slug, title: d.title.trim(), base_release: d.base_release, open_paths: [...d.open_paths],
    decider_team_id: d.decider_team_id || null, quorum_percent: Number(d.quorum_percent), pass_rule: d.pass_rule,
  }
}
/** Only what changed (the registry refuses a change of the organization, the name or the base release). */
export function linePatch(before: LineDraft, d: LineDraft): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  if (d.title.trim() !== before.title) out.title = d.title.trim()
  if (JSON.stringify(d.open_paths) !== JSON.stringify(before.open_paths)) out.open_paths = [...d.open_paths]
  if ((d.decider_team_id || '') !== (before.decider_team_id || '')) out.decider_team_id = d.decider_team_id || null
  if (Number(d.quorum_percent) !== Number(before.quorum_percent)) out.quorum_percent = Number(d.quorum_percent)
  if (d.pass_rule !== before.pass_rule) out.pass_rule = d.pass_rule
  return out
}

const inside = (p: string, declared: string[]): boolean => declared.some((d) => { const x = d.replace(/\/+$/, ''); return p === x || p.startsWith(x + '/') })
/** D1's paths_inside_line: every path of a change open on the platform AND inside the line's open paths; null when they are, else why not. */
export function pathsInsideLine(paths: string[], openPaths: string[], label: (p: string) => string = (p) => p): string | null {
  const pc = checkPaths(REPOSITORY, paths)
  if (!pc.ok) return pc.reason
  const outside = paths.filter((p) => !inside(p, openPaths))
  return outside.length ? `${label(outside[0])} is not open in this line (open: ${openPaths.map(label).join(', ')})` : null
}

// -- the admin inbox --------------------------------------------------------------------------------------------------------
export interface InboxRow { change: ChangeRecord; line: LineRecord; lane: Lane }
/** Every line's changes in one queue, newest first (an equal instant by id, so the order never shuffles between reads). */
export function inboxRows(lines: LineRecord[], changesBySlug: Record<string, ChangeRecord[]>): InboxRow[] {
  const rows: InboxRow[] = []
  for (const line of lines) for (const change of changesBySlug[line.slug] || []) rows.push({ change, line, lane: laneOf(change) })
  const at = (r: InboxRow) => { const t = new Date(String(r.change.created_at || '')).getTime(); return Number.isNaN(t) ? 0 : t }
  return rows.sort((a, b) => at(b) - at(a) || String(b.change.id).localeCompare(String(a.change.id)))
}

export interface InboxFilter { organization: string; line: string; lane: string; sensitive: 'any' | 'yes' | 'no' }
export const noFilter = (): InboxFilter => ({ organization: '', line: '', lane: '', sensitive: 'any' })
export function filterInbox(rows: InboxRow[], f: InboxFilter): InboxRow[] {
  return rows.filter((r) => (!f.organization || r.line.organization_id === f.organization)
    && (!f.line || r.line.slug === f.line)
    && (!f.lane || r.lane === f.lane)
    && (f.sensitive === 'any' || (f.sensitive === 'yes') === !!r.change.sensitive))
}

/** A pause needs a reason (the registry stores it and shows it on the line). */
export function pauseProblem(reason: string, tr: Tr): string | null {
  const r = reason.trim()
  if (!r) return tr('contributions.admin.needReason', 'Say why the line is paused; its members read it.')
  if (r.length > 500) return tr('contributions.admin.longReason', 'A reason of at most 500 characters.')
  return null
}
