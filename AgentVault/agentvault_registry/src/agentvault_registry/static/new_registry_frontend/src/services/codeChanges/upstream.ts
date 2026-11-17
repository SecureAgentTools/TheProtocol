/**
 * V0667 D4 (order gwo_b12f07e4c5adaa1f5bf4d115; design section 4): upstream, in words. A change merged in an organization's release line is proposed to the main code by the
 * line's deciders (the registry decides who, the paths and once, again). The line's own copy says the proposal and its state, and "upstream since" once it landed; the change on
 * the main code shows its provenance with nothing dropped. Pure: the registry's record in, the sentences out.
 */
import type { Tr } from './tr'
import { stateWord } from './codeChangeView'

type Rec = Record<string, any>

/** `line`: a change of an organization's release line. `carried`: a main-line change that carries a line's change upstream. Otherwise null. */
export function upstreamKind(rec: Rec | null | undefined): 'line' | 'carried' | null {
  if (!rec) return null
  if (rec.upstream_of) return 'carried'
  if (rec.code_distribution) return 'line'
  return null
}

/** The action: a signed-in decider (the registry's `i_decide` on the line's ballot), on a merged line change that has not gone upstream. */
export function canProposeUpstream(rec: Rec | null | undefined, signedIn: boolean): boolean {
  return !!rec && signedIn && upstreamKind(rec) === 'line' && rec.state === 'merged' && !rec.upstream && rec.line_ballot?.i_decide === true
}

export interface LineStatus { kind: 'none' | 'proposed' | 'landed' | 'ended'; text: string; changeId: string | null }

const ENDED = new Set(['withdrawn', 'failed', 'vetoed'])
const day = (iso: unknown): string => (typeof iso === 'string' && iso.length >= 10 ? iso.slice(0, 10) : '')

/** What a line change says about its own proposal upstream. */
export function lineStatus(rec: Rec, tr: Tr): LineStatus {
  const up = rec?.upstream
  if (!up || !up.change_id) return { kind: 'none', text: '', changeId: null }
  const id = String(up.change_id)
  if (up.state === 'merged') {
    const d = day(up.since)
    return { kind: 'landed', changeId: id, text: d ? tr('upstream.since', 'Upstream since {id} ({day}): the main code has it.', { id, day: d }) : tr('upstream.sinceNoDay', 'Upstream since {id}: the main code has it.', { id }) }
  }
  if (ENDED.has(String(up.state))) {
    return { kind: 'ended', changeId: id, text: tr('upstream.ended', 'Proposed upstream as {id}, which ended as {state}: it is not in the main code.', { id, state: stateWord(String(up.state), tr).toLowerCase() }) }
  }
  return { kind: 'proposed', changeId: id, text: tr('upstream.proposed', 'Proposed upstream as {id}: {state}.', { id, state: stateWord(String(up.state), tr) }) }
}

export interface ProvenanceFact { key: 'line' | 'change' | 'ballot' | 'reviews' | 'checker'; label: string; text: string; changeId?: string }

/** Where a carried change came from: the line, the line's change, its ballot and result, its reviews, the checker's record. A part the record lacks is said, never left out. */
export function provenanceFacts(rec: Rec | null | undefined, tr: Tr): ProvenanceFact[] {
  const p = rec?.provenance
  if (!p || typeof p !== 'object') return []
  const none = tr('upstream.prov.none', 'not recorded')
  const line = p.line
  const lc = p.line_change
  const ballot = p.ballot
  const reviews = Array.isArray(p.reviews) ? p.reviews : null
  const checker = p.checker
  const approvals = reviews ? reviews.filter((r: Rec) => r.verdict === 'approve').length : 0
  const asked = reviews ? reviews.filter((r: Rec) => r.verdict === 'changes').length : 0
  const rec_ = checker?.record
  return [
    { key: 'line', label: tr('upstream.prov.line', 'The release line'),
      text: line ? tr('upstream.prov.lineText', '{title} ({org}), {release}', { title: line.title ?? line.slug, org: line.organization_name ?? '—', release: line.base_release ?? '—' }) : none },
    { key: 'change', label: tr('upstream.prov.change', 'Its change there'), changeId: lc?.id ? String(lc.id) : undefined,
      text: lc ? tr('upstream.prov.changeText', '{title}, merged on {day}', { title: lc.title ?? lc.id, day: day(lc.merged?.at) || '—' }) : none },
    { key: 'ballot', label: tr('upstream.prov.ballot', 'The line\'s ballot'),
      text: ballot?.result ? String(ballot.result.sentence || ballot.result.status || none) : none },
    { key: 'reviews', label: tr('upstream.prov.reviews', 'Reviews'),
      text: reviews ? `${approvals} ${approvals === 1 ? tr('upstream.prov.approval', 'approval') : tr('upstream.prov.approvals', 'approvals')}, ${asked} ${tr('upstream.prov.asked', 'asked for changes')}` : none },
    { key: 'checker', label: tr('upstream.prov.checker', 'The checker\'s record on the line'),
      text: checker && rec_ ? tr('upstream.prov.checkerText', '{ok}, CI {ci}, signed by {kid}', { ok: checker.ok ? tr('upstream.prov.passed', 'checks passed') : tr('upstream.prov.failed', 'checks did not pass'), ci: rec_.ci?.status ?? '—', kid: rec_.checker_kid ?? '—' }) : none },
  ]
}
