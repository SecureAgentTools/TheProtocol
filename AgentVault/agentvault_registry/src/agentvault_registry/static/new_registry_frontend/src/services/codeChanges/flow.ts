// V0664 (order gwo_fc4ec96d3679ca02d5e3afa8): the way a code change goes, as data the page draws: the seven steps with where a change stands, the
// filters, the timeline of one change from its record (GET /code-changes/{id}, services/code_changes.CodeChangeFlow.view), the ballot's tally
// (GET /governance/proposals/{id}) and the words about paths. Pure: the words come through `t`, nothing here fetches or touches the DOM.
import { CONSOLE_PREFIX } from './pathRules'
import { proposerOf, reviewerOf, type Person } from './people'

type T = (key: string, fallback: string, params?: Record<string, unknown>) => string
type Rec = Record<string, any>

export const STEP_KEYS = ['propose', 'checks', 'review', 'ballot', 'veto', 'merge', 'release'] as const
export type StepKey = typeof STEP_KEYS[number]
export type StepState = 'done' | 'current' | 'todo' | 'stopped'
export interface StepView { key: StepKey; state: StepState; title: string; who: string; note: string }

/** The titles and who acts at each step: the page's explanation of the way a change goes (D1 to D8, sessionlogs2026/DESIGN_2026-11-13_GOVERNED_CODE.md). */
export function stepWords(t: T): Array<{ key: StepKey; title: string; who: string; body: string }> {
  return [
    { key: 'propose', title: t('codeChanges.step.propose', 'Propose'), who: t('codeChanges.who.propose', 'A member\'s agent'),
      body: t('codeChanges.step.proposeBody', 'Name the files, the problem, and either a branch you wrote or a bounty for someone to write it. A bounty is held by the Guild from the start.') },
    { key: 'checks', title: t('codeChanges.step.checks', 'Contract and checks'), who: t('codeChanges.who.checks', 'A worker, then the checker'),
      body: t('codeChanges.step.checksBody', 'A worker delivers the code with its tests. A checker reads the repository and signs: CI is green on that exact commit, only the named paths changed, no secret in them.') },
    { key: 'review', title: t('codeChanges.step.review', 'Review'), who: t('codeChanges.who.review', 'Members who did not write it'),
      body: t('codeChanges.step.reviewBody', 'One independent member reads the commit and approves it, or asks for changes. A sensitive change needs two.') },
    { key: 'ballot', title: t('codeChanges.step.ballot', 'Members\' ballot'), who: t('codeChanges.who.ballot', 'The frame\'s members'),
      body: t('codeChanges.step.ballotBody', 'The members vote in the Senate, as for any policy: a quorum and a share in favour. A sensitive change needs the stricter pair.') },
    { key: 'veto', title: t('codeChanges.step.veto', 'Veto window'), who: t('codeChanges.who.veto', 'The maintainer'),
      body: t('codeChanges.step.vetoBody', 'During the beta the maintainer may veto a passed change for 24 hours, or say go sooner.') },
    { key: 'merge', title: t('codeChanges.step.merge', 'Merged'), who: t('codeChanges.who.merge', 'A session'),
      body: t('codeChanges.step.mergeBody', 'A session merges exactly the voted commit; the bounty then settles.') },
    { key: 'release', title: t('codeChanges.step.release', 'Release'), who: t('codeChanges.who.release', 'The release'),
      body: t('codeChanges.step.releaseBody', 'A merge reaches production only through a release, with its proofs and the maintainer\'s card.') },
  ]
}

/** The stepper for one change: where it stands. A step is done, the current one, still to come, or the one it stopped at. */
export function stepper(r: Rec, t: T): StepView[] {
  const words = stepWords(t)
  const rv = r.review_verdict || { approvals: 0, needed: r.sensitive ? 2 : 1, blockers: [], ok: false }
  const failedCheck = !!(r.acceptance && r.acceptance.ok === false)
  let cur = 0                     // the index of the current (or stopped) step
  let stopped = false
  let note = ''
  switch (r.state) {
    case 'proposed': cur = 1; stopped = failedCheck
      note = failedCheck ? (r.acceptance.reasons || []).join('; ') : (r.mode === 'bounty' ? t('codeChanges.note.delivery', 'Waiting for the worker\'s delivery.') : t('codeChanges.note.check', 'Waiting for the checker\'s signed word on the commit.'))
      break
    case 'accepted':
      if (rv.blockers?.length) { cur = 2; stopped = true; note = t('codeChanges.note.changesAsked', 'A reviewer asks for changes.') }
      else if (!rv.ok) { cur = 2; note = t('codeChanges.note.reviews', '{n} of {needed} approvals.', { n: rv.approvals, needed: rv.needed }) }
      else { cur = 3; note = t('codeChanges.note.openBallot', 'Reviewed: the proposer opens the ballot.') }
      break
    case 'balloting': cur = 3; note = t('codeChanges.note.voting', 'Members are voting.'); break
    case 'passed': cur = 4
      // V0666: a pass on the maintainer's go while members are few says so, in words (the count and the threshold are the record's)
      note = r.bootstrap ? t('codeChanges.note.bootstrap', 'Passed on the maintainer\'s go: the frame has {n} members, fewer than {t}.', { n: r.bootstrap.members, t: r.bootstrap.threshold })
        : t('codeChanges.note.window', 'Passed: waiting for the veto window or the go.'); break
    case 'merged': cur = 6; note = t('codeChanges.note.releaseOnly', 'Merged into {into}. It reaches production only through a release.', { into: r.merged?.into || '' }); break
    case 'failed': cur = 3; stopped = true; note = failedNote(r.ballot_outcome, t); break
    case 'vetoed': cur = 4; stopped = true; note = r.veto?.reason || t('codeChanges.note.vetoed', 'Vetoed.'); break
    case 'withdrawn': cur = r.acceptance?.ok && r.commit ? 2 : 0; stopped = true; note = t('codeChanges.note.withdrawn', 'Withdrawn.'); break
    default: cur = 0
  }
  return words.map((w, i) => {
    let state: StepState = i < cur ? 'done' : i > cur ? 'todo' : stopped ? 'stopped' : 'current'
    // a merge is done; the release is never "done" by it: it stays to come (a release carries the proofs)
    if (r.state === 'merged') state = i < 6 ? 'done' : 'todo'
    return { key: w.key, state, title: w.title, who: w.who, note: i === cur || (r.state === 'merged' && i === 6) ? note : '' }
  })
}

export const FILTERS = [
  { key: 'all', states: null as string[] | null },
  { key: 'open', states: ['proposed', 'accepted', 'balloting', 'passed'] },
  { key: 'merged', states: ['merged'] },
  { key: 'ended', states: ['failed', 'vetoed', 'withdrawn'] },
]
export function matchesFilter(r: Rec, key: string): boolean {
  const f = FILTERS.find((x) => x.key === key)
  return !f || !f.states || f.states.includes(String(r.state))
}

/** `by` is who did it, by name (the registry's names, V0665): set only when the caller can name people. */
export interface TimelineEvent { key: string; kind: 'ok' | 'bad' | 'info' | 'wait'; title: string; detail?: string; at: string | null; by?: string }

const iso = (v: unknown): string | null => {
  if (typeof v === 'number' && Number.isFinite(v)) return new Date(v * 1000).toISOString()
  if (typeof v === 'string' && v) return v
  return null
}

/** One change's steps in the order they happened, each with its time where the record has one. */
/** V0666: who voted on a ballot a bootstrap go passed: "2 members voted: 1 for, 1 against" (the members as people, never an id). */
export function bootstrapVoters(b: Rec, t: T): string | undefined {
  const voted = Array.isArray(b?.voted) ? b.voted : []
  if (!voted.length) return undefined
  const f = voted.filter((v: Rec) => v.vote === true).length
  return t('codeChanges.tl.bootstrapVoters', '{n} members voted: {f} for, {a} against', { n: voted.length, f, a: voted.length - f })
}

export function timeline(r: Rec, t: T, nameOf?: (p: Person) => string): TimelineEvent[] {
  const ev: TimelineEvent[] = []
  ev.push({ key: 'proposed', kind: 'info', at: iso(r.created_at), by: nameOf ? nameOf(proposerOf(r)) : undefined,
    title: r.mode === 'bounty' ? t('codeChanges.tl.proposedBounty', 'A change was proposed with a bounty') : t('codeChanges.tl.proposedBranch', 'A change was proposed with a branch') })
  const a = r.acceptance
  if (a) {
    ev.push(a.ok
      ? { key: 'checks', kind: 'ok', at: iso(a.at), title: t('codeChanges.tl.checksOk', 'The checker signed: CI green, paths inside, no secret'),
          detail: a.record?.commit ? String(a.record.commit).slice(0, 12) : undefined }
      : { key: 'checks', kind: 'bad', at: iso(a.at), title: t('codeChanges.tl.checksBad', 'The checks did not pass'), detail: (a.reasons || []).join('\n') })
  }
  for (const [i, rv] of (r.reviews || []).entries()) {
    ev.push({ key: 'review', kind: rv.verdict === 'approve' ? 'ok' : 'bad', at: iso(rv.at), by: nameOf ? nameOf(reviewerOf(rv)) : undefined,
      title: rv.verdict === 'approve' ? t('codeChanges.tl.approved', 'A member approved the commit') : t('codeChanges.tl.changesAsked', 'A member asked for changes'),
      detail: rv.findings || undefined })
    void i
  }
  if (r.proposal_id) ev.push({ key: 'ballot', kind: 'info', at: null, title: t('codeChanges.tl.ballot', 'The members\' ballot was opened (#{id})', { id: r.proposal_id }) })
  if (r.bootstrap) {
    // V0666: the ballot ended without its quorum and the maintainer's go passed it while the frame has few members: both lines, with who did vote
    ev.push({ key: 'failed', kind: 'info', at: outcomeAt(r.ballot_outcome), title: t('codeChanges.tl.noQuorum', 'The ballot ended without a quorum'),
      detail: outcomeWords(r.ballot_outcome, t) || undefined })
    ev.push({ key: 'passed', kind: 'ok', at: iso(r.bootstrap.at || r.passed_at),
      title: t('codeChanges.tl.bootstrap', 'Passed on the maintainer\'s go: the frame has {n} members, fewer than {t}', { n: r.bootstrap.members, t: r.bootstrap.threshold }),
      detail: bootstrapVoters(r.bootstrap, t) })
  } else if (r.passed_at) ev.push({ key: 'passed', kind: 'ok', at: iso(r.passed_at), title: t('codeChanges.tl.passed', 'The ballot passed') })
  // V0668: dated by the tally (the record's time stood at the ballot's opening), and why under it
  if (r.state === 'failed') ev.push({ key: 'failed', kind: 'bad', at: outcomeAt(r.ballot_outcome) || iso(r.updated_at), title: t('codeChanges.tl.failed', 'The ballot did not pass'),
    detail: outcomeWords(r.ballot_outcome, t) || undefined })
  if (r.veto) ev.push({ key: 'veto', kind: 'bad', at: iso(r.veto.at), title: t('codeChanges.tl.veto', 'The maintainer vetoed it'), detail: r.veto.reason || undefined })
  if (r.go && !r.bootstrap) ev.push({ key: 'go', kind: 'ok', at: iso(r.go.at), title: t('codeChanges.tl.go', 'The maintainer said go') })
  if (r.merged) ev.push({ key: 'merged', kind: 'ok', at: iso(r.merged.at), title: t('codeChanges.tl.merged', 'Merged into {into}', { into: r.merged.into || '' }),
    detail: r.merged.commit ? String(r.merged.commit).slice(0, 12) : undefined })
  if (r.state === 'withdrawn') ev.push({ key: 'withdrawn', kind: 'bad', at: iso(r.updated_at), title: t('codeChanges.tl.withdrawn', 'The change was withdrawn') })
  // while it is still going, the last line says what it waits for
  const waiting = stepper(r, t).find((s) => s.state === 'current')
  if (waiting && !['merged', 'failed', 'vetoed', 'withdrawn'].includes(String(r.state))) {
    ev.push({ key: 'waiting', kind: 'wait', at: null, title: waiting.note || waiting.title })
  }
  return ev
}

// V0668 (order gwo_2d51e1af1b2a21a0bcdff5e7): a decided ballot's outcome, from the registry's `ballot_outcome` (services/code_changes.ballot_outcome for
// the main line, line_ballot_outcome for a line's own ballot): why it did (not) pass, with the numbers it was decided on, and when it was tallied.
const num = (x: unknown): string => { const v = Math.round(Number(x) * 100) / 100; return Number.isFinite(v) ? String(v) : '?' }

/** When a decided ballot was tallied: the tally's time, else the ballot's end (a tally that kept no time), else null. */
export function outcomeAt(o: Rec | null | undefined): string | null {
  return o && typeof o === 'object' ? iso(o.tallied_at) || iso(o.ended_at) : null
}

/** Why a decided ballot did (not) pass, in one sentence; '' without an outcome. */
export function outcomeWords(o: Rec | null | undefined, t: T): string {
  if (!o || typeof o !== 'object') return ''
  const p = { took: num(o.took_part), req: num(o.required), q: num(o.quorum_percent), share: num(o.share_for), pass: num(o.pass_percent), f: num(o.for), a: num(o.against) }
  switch (o.reason) {
    case 'quorum_not_met':
      if (o.required == null) return t('codeChanges.outcome.quorumNoFigure', 'The quorum was not met: {took} took part.', p)
      if (o.unit === 'deciders') return t('codeChanges.outcome.quorumDeciders', 'The quorum was not met: {took} of the {req} deciders required voted (quorum {q}%).', p)
      if (o.unit === 'lock') return t('codeChanges.outcome.quorumLock', 'The quorum was not met: {took} of the {req} voting power required took part (quorum {q}%).', p)
      return t('codeChanges.outcome.quorumMember', 'The quorum was not met: {took} of the {req} members\' points required took part (quorum {q}%).', p)
    case 'rejected':
      return o.unit === 'deciders'
        ? t('codeChanges.outcome.rejectedLine', 'The deciders decided against it: {f} for, {a} against (more for than against is needed).', p)
        : t('codeChanges.outcome.rejected', 'The members decided against it: {share}% in favour, {pass}% needed to pass.', p)
    case 'no_deciders': return t('codeChanges.outcome.noDeciders', 'Nobody decided: the line had no deciders at the close.')
    case 'passed': return t('codeChanges.outcome.passed', 'Passed: {share}% in favour, the quorum met.', p)
    case 'unknown': return t('codeChanges.outcome.unknown', 'The tally kept no reason (it ran before the registry stored one).')
    default: return ''
  }
}

/** The stopped ballot step's note: why the ballot did not pass, when the record says. */
function failedNote(o: Rec | null | undefined, t: T): string {
  switch (o?.reason) {
    case 'quorum_not_met': return t('codeChanges.note.failedQuorum', 'The ballot did not pass: it missed its quorum.')
    case 'rejected': return o?.unit === 'deciders' ? t('codeChanges.note.failedRejectedLine', 'The ballot did not pass: the deciders decided against it.')
      : t('codeChanges.note.failedRejected', 'The ballot did not pass: the members decided against it.')
    case 'no_deciders': return t('codeChanges.note.failedNoDeciders', 'The ballot did not pass: nobody could decide it.')
    default: return t('codeChanges.note.failed', 'The ballot did not pass.')
  }
}

export interface Tally { id: number; status: string; open: boolean; forVotes: number; against: number; voters: number; quorumPct: number | null; passPct: number | null; forShare: number | null; endsAt: string | null }
/** The ballot's numbers from the governance proposal (public). The share in favour is of the votes cast; null while there are none. */
export function ballotTally(p: Rec): Tally {
  const f = Number(p.votes_for) || 0
  const a = Number(p.votes_against) || 0
  const status = String(p.status || '')
  return { id: Number(p.id), status, open: /^(ACTIVE|OPEN)$/i.test(status), forVotes: f, against: a, voters: Number(p.total_voters) || 0,
    quorumPct: typeof p.quorum_percent === 'number' ? p.quorum_percent : null, passPct: typeof p.pass_percent === 'number' ? p.pass_percent : null,
    forShare: f + a > 0 ? Math.round((f / (f + a)) * 100) : null, endsAt: iso(p.end_timestamp) }
}

export const shortPath = (p: string): string => (p.startsWith(CONSOLE_PREFIX) ? p.slice(CONSOLE_PREFIX.length) : p)
export function pathSummary(paths: string[], max = 2): { shown: string[]; more: number } {
  return { shown: paths.slice(0, max), more: Math.max(0, paths.length - max) }
}
/** What the registry asks of a change that touches auth, admin, money or federation trust (D3). */
export function sensitiveNeeds(t: T): string {
  return t('codeChanges.sensitiveNeeds', 'A sensitive path (auth, admin, money or federation trust) needs two approving reviews and the stricter ballot: a quorum of 20 % and two thirds in favour.')
}

/** The seven steps as the explanation draws them: none of them is anyone's yet. */
export function explainer(t: T): StepView[] {
  return stepWords(t).map((w) => ({ key: w.key, state: 'todo' as StepState, title: w.title, who: w.who, note: '' }))
}

/** The step a change is at (the current or the stopped one), for a card's one line. */
export function whereItStands(r: Rec, t: T): StepView | null {
  const s = stepper(r, t)
  return s.find((x) => x.state === 'current' || x.state === 'stopped') || s[s.length - 1] || null
}

/** A touched path is a declared file, or sits under a declared directory (services/code_changes.path_inside). */
export function insideDeclared(touched: string, declared: string[]): boolean {
  return declared.some((d) => { const x = d.replace(/\/+$/, ''); return touched === x || touched.startsWith(x + '/') })
}
