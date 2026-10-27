/**
 * §MCPTEST30 (V0557) — the Senate floor's half of federal ballots (§MEMBERSHIP D2, agentvault2-33's routes).
 *
 * Where a registry runs FEDERATION_BALLOT_MODE=on, a federation proposal is decided by REGISTRIES, one signed ballot
 * each: a registry with members casts its members' result (a linked local vote of at least an hour), a registry without
 * members casts its operator's choice. The ballot travels to the registry that hosts the proposal, which verifies it
 * against the caster's card key before its store takes it. The floor shows three things the routes already answer:
 *   GET  /governance/federation-ballots                   open ballot proposals here and at the frame peers, each with
 *                                                         this registry's members' vote on it (local_vote)
 *   GET  /governance/federation/proposals/{id}/ballots    the ballots on a proposal THIS registry hosts, each whole
 *   POST /admin/federation/ballots/local-vote | /admin/federation/ballots | /governance/federation/proposals/{id}/tally
 *
 * agentvault2-33's three rules for the console: in member mode NEVER offer a choice for the cast (the members decide;
 * a different choice is refused 409 members_decided); the members' vote takes 1 h to 30 d, capped 15 minutes before the
 * host proposal ends (409 too_late when under 30 minutes would remain); and every refusal shows its own word.
 * Pure helpers plus thin calls, so the rules are unit-tested without a browser.
 */
import { apiClient } from '@/services/api/client'

export type BallotChoice = 'for' | 'against' | 'abstain'

export interface LocalVote {
  local_proposal_id: number
  ends_at: string | null
  open: boolean
}

export interface OpenBallotProposal {
  id: string
  title?: string | null
  description?: string | null
  end_timestamp?: string | null
  host?: { trust_domain?: string; name?: string }
  /** registry ids that have cast at the host; null when the host could not read its own ballots */
  ballots_cast_by?: string[] | null
  cast_here?: boolean | null
  local_vote?: LocalVote | null
}

export interface BallotHost {
  host: string                 // 'self' or the peer row's name
  name: string
  trust_domain: string
  proposals: OpenBallotProposal[]
  error: string | null
}

export interface OpenBallotsDoc {
  ballot_mode: boolean
  registry_id: string
  hosts: BallotHost[]
  as_of?: string
}

export interface BallotBasis {
  mode?: 'members' | 'operator' | string
  voters?: number
  points_for?: number
  points_against?: number
  local_proposal_id?: number
}

export interface Ballot {
  registry_id: string
  choice: BallotChoice | string
  basis?: BallotBasis | null
  eligibility?: { licence_ok?: boolean; licence_state?: string; track_ok?: boolean; reasons?: string[] } | null
  cast_at?: string | null
  envelope?: { ballot?: Record<string, unknown>; alg?: string; kid?: string; signature?: string } | null
  verified_at_receipt?: boolean
}

export interface BallotSummary {
  status?: string
  for?: number
  against?: number
  abstain?: number
  cast?: number
  eligible?: number
  eligible_registries?: string[]
  not_counted?: string[]
  two_thirds_met?: boolean
  participation_met?: boolean
  multi_registry_met?: boolean
  pass_rate?: number
}

export interface ProposalBallots {
  proposal_id: string
  host: { trust_domain: string; name: string; id: string }
  ballot_mode: boolean
  status?: string
  ballot_summary?: BallotSummary | null
  ballots: Ballot[]
}

/** A refusal as the routes word it: {error, message, ...extra}. */
export interface BallotRefusal {
  error: string
  message: string
  status: number
  extra: Record<string, unknown>
}

// ── the reads and the presses ────────────────────────────────────────────────────────────────────────────────────

export async function fetchOpenBallots(): Promise<OpenBallotsDoc> {
  const { data } = await apiClient.get('/governance/federation-ballots')
  return data as OpenBallotsDoc
}

export async function fetchProposalBallots(proposalId: string): Promise<ProposalBallots> {
  const { data } = await apiClient.get(`/governance/federation/proposals/${encodeURIComponent(proposalId)}/ballots`)
  return data as ProposalBallots
}

export async function openMembersVote(host: string, proposalId: string, durationSeconds: number): Promise<{ local_proposal_id: number; ends_at: string }> {
  const { data } = await apiClient.post('/admin/federation/ballots/local-vote',
    { host, proposal_id: proposalId, duration_seconds: durationSeconds })
  return data
}

/** No choice in member mode (the members decide); the operator's choice where the registry has no members. */
export async function castBallot(host: string, proposalId: string, choice: BallotChoice | null): Promise<{ recorded: boolean; choice: string }> {
  const body: Record<string, unknown> = { host, proposal_id: proposalId }
  if (choice) body.choice = choice
  const { data } = await apiClient.post('/admin/federation/ballots', body)
  return data
}

/** Who may cast at THIS registry now (admin_platform): the host's own count of who is eligible. */
export async function fetchBallotEligibility(): Promise<{ rule: string; registries: { id: string; name?: string; eligible: boolean; reasons?: string[] }[] }> {
  const { data } = await apiClient.get('/admin/federation/ballots/eligibility')
  return data
}

/** Whether the host's admin may count a ballot proposal NOW (agentvault2-33's review, 2026-10-03). A ballot proposal's
 *  count is FINAL and the server allows it any time, so one early press would close the vote for every registry and
 *  fail it on turnout. The floor allows it once every eligible registry has cast, or once the voting time has ended
 *  (the auto-tally would count it then anyway); otherwise it says why not. Eligible unknown = not before the end. */
export function countGate(opts: { eligibleIds: string[] | null; castIds: string[]; endIso?: string | null; nowMs?: number }):
    { open: boolean; reason: 'all_cast' | 'ended' | 'waiting'; cast: number; eligible: number | null } {
  const now = opts.nowMs ?? Date.now()
  const end = opts.endIso ? Date.parse(opts.endIso) : NaN
  const eligible = opts.eligibleIds ? opts.eligibleIds.length : null
  const cast = opts.castIds.length
  if (Number.isFinite(end) && now >= end) return { open: true, reason: 'ended', cast, eligible }
  if (opts.eligibleIds && opts.eligibleIds.length && opts.eligibleIds.every(id => opts.castIds.includes(id))) {
    return { open: true, reason: 'all_cast', cast, eligible }
  }
  return { open: false, reason: 'waiting', cast, eligible }
}

export async function tallyFederationProposal(proposalId: string): Promise<Record<string, unknown>> {
  const { data } = await apiClient.post(`/governance/federation/proposals/${encodeURIComponent(proposalId)}/tally`, {})
  return data
}

// ── pure rules ────────────────────────────────────────────────────────────────────────────────────────────────────

/** The refusal inside an axios error, or null when the answer carried no word of its own. */
export function refusalOf(e: unknown): BallotRefusal | null {
  const r = (e as { response?: { status?: number; data?: unknown } })?.response
  const d = r?.data as Record<string, unknown> | undefined
  if (!r || !d || typeof d.error !== 'string') return null
  const { error, message, ...extra } = d as { error: string; message?: string } & Record<string, unknown>
  return { error, message: typeof message === 'string' ? message : '', status: r.status ?? 0, extra }
}

/** `registry:<trust domain>/<slug>` → its parts; anything else → null. */
export function parseRegistryId(id: string | null | undefined): { trustDomain: string; slug: string } | null {
  const m = /^registry:([^/\s]+)\/(\S+)$/.exec(String(id || ''))
  return m ? { trustDomain: m[1].toLowerCase(), slug: m[2] } : null
}

/** The trust domain in a SPIFFE id (`spiffe://<td>/...`), lowercased; '' when it is not one. */
export function spiffeTrustDomain(spiffeId: string | null | undefined): string {
  const m = /^spiffe:\/\/([^/]+)/i.exec(String(spiffeId || ''))
  return m ? m[1].toLowerCase() : ''
}

/** The name a reader knows a registry by: a host the open list names for that trust domain where exactly one does,
 *  else the id's own slug. A trust domain can hold a frame AND its operators, so a match is made by slug first. */
export function registryLabel(registryId: string, hosts: Pick<BallotHost, 'name' | 'trust_domain'>[]): string {
  const p = parseRegistryId(registryId)
  if (!p) return registryId
  const slug = (n: string) => n.normalize('NFKD').replace(/[\u0080-\uffff]/g, '').trim().toLowerCase()
    .replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '')
  const exact = hosts.find(h => (h.trust_domain || '').toLowerCase() === p.trustDomain && slug(h.name || '') === p.slug)
  return exact ? exact.name : p.slug
}

/** Who raised a federation proposal. The store records an mTLS registry caller as 'origin' (its proposer field is an
 *  operator's name, which a frame's registry does not have), so that word is never shown: the origin's SPIFFE id
 *  names its trust domain, and the open list names the registry that holds it. */
/** §MCPTEST30 (V0558): the Senate floor's status pill for a federation proposal's status (the governance tab's own
 * variants; a test holds each to a rule in the view's stylesheet). */
export function fedStatusPill(status: string | null | undefined): string {
  const s = (status || '').toUpperCase()
  if (s === 'VOTING') return 'sn-prop-status-pill--active'
  if (s === 'PASSED' || s === 'APPLIED') return 'sn-prop-status-pill--passed'
  if (s === 'FAILED' || s === 'VETOED') return 'sn-prop-status-pill--failed'
  return 'sn-prop-status-pill--pending'
}

export function raisedBy(p: { proposer_operator_name?: string | null; origin_registry_id?: string | null },
                         hosts: Pick<BallotHost, 'name' | 'trust_domain'>[]): string {
  const named = String(p.proposer_operator_name || '').trim()
  if (named && !['origin', 'unknown'].includes(named.toLowerCase())) return named
  const td = spiffeTrustDomain(p.origin_registry_id)
  if (!td) return named || ''
  const frames = hosts.filter(h => (h.trust_domain || '').toLowerCase() === td)
  return frames.length === 1 ? frames[0].name : td
}

/** Has this registry cast at the host? From the full ballots where the host is this registry, else the open list. */
export function castHere(myRegistryId: string, p: Pick<OpenBallotProposal, 'ballots_cast_by'> | null,
                         ballots?: Pick<Ballot, 'registry_id'>[] | null): boolean | null {
  if (ballots) return ballots.some(b => b.registry_id === myRegistryId)
  const by = p?.ballots_cast_by
  return Array.isArray(by) ? by.includes(myRegistryId) : null
}

export const MIN_MEMBERS_VOTE_S = 3600
export const MAX_MEMBERS_VOTE_S = 30 * 86400
const CAP_BEFORE_END_S = 15 * 60
const TOO_LATE_S = 30 * 60

/** The members' vote durations the floor offers. Each is what the floor ASKS for (an hour to thirty days, the route's
 *  bounds) with what the route will GRANT: at most 15 minutes before the host proposal ends. Asks that would be granted
 *  the same length fold into one; nothing at all when 30 minutes or less would remain (the route answers too_late).
 *  A vote cut short by the cap is still offered, shorter than an hour: the route allows it, so the floor shows it. */
export function membersVoteOptions(hostEndIso: string | null | undefined, nowMs: number = Date.now(),
                                   wanted: number[] = [3600, 86400, 3 * 86400, 7 * 86400]): { request: number; effective: number }[] {
  const end = hostEndIso ? Date.parse(hostEndIso) : NaN
  const room = Number.isFinite(end) ? Math.floor((end - nowMs) / 1000) - CAP_BEFORE_END_S : MAX_MEMBERS_VOTE_S
  if (room <= TOO_LATE_S) return []
  const out: { request: number; effective: number }[] = []
  for (const w of wanted) {
    const request = Math.min(Math.max(w, MIN_MEMBERS_VOTE_S), MAX_MEMBERS_VOTE_S)
    const effective = Math.min(request, room)
    if (!out.some(o => o.effective === effective)) out.push({ request, effective })
  }
  return out
}

/** What this registry may do on a VOTING proposal now; the server decides, this only picks which door to show. */
export type BallotStep =
  | { kind: 'cast'; choice: string | null }                      // already cast
  | { kind: 'open_members_vote' }                                // members, no vote yet
  | { kind: 'members_voting'; localProposalId: number; endsAt: string | null }
  | { kind: 'cast_members_result'; localProposalId: number }     // members decided; the cast carries no choice
  | { kind: 'operator_choice' }                                  // no members: the operator's choice is the ballot
  | { kind: 'closed' }
  | { kind: 'unknown' }      // who this registry is, or whether it has members, is not known yet: no door is offered

/** agentvault2-0f's review (2026-10-03): on a cold arrival the registry's config, its open list or its membership can
 *  answer after the floor renders. A step chosen before then would GUESS "not cast yet" or "no members" and offer the
 *  wrong door, so while who this registry is (`known`) or whether it has members (`hasMembers` null) is unknown, the
 *  step is 'unknown' and no door is shown. */
export function nextStep(opts: { status?: string | null; cast?: boolean | null; castChoice?: string | null;
                                 hasMembers: boolean | null; localVote?: LocalVote | null; known?: boolean }): BallotStep {
  if (opts.status && opts.status.toUpperCase() !== 'VOTING') return { kind: 'closed' }
  if (opts.known === false || opts.cast === null) return { kind: 'unknown' }      // null: whether it has cast is unread
  if (opts.cast) return { kind: 'cast', choice: opts.castChoice ?? null }
  if (opts.hasMembers === null) return { kind: 'unknown' }
  if (!opts.hasMembers) return { kind: 'operator_choice' }
  const lv = opts.localVote
  if (!lv) return { kind: 'open_members_vote' }
  if (lv.open) return { kind: 'members_voting', localProposalId: lv.local_proposal_id, endsAt: lv.ends_at }
  return { kind: 'cast_members_result', localProposalId: lv.local_proposal_id }
}

/** The refusal words the ballot routes answer (routers/federation_ballots.py, services/federation_ballot.py). */
export const REFUSAL_WORDS = [
  'members_must_vote', 'local_vote_open', 'no_members', 'choice_required', 'not_eligible', 'host_refused',
  'host_unreachable', 'too_late', 'local_vote_exists', 'already_cast', 'members_decided', 'unknown_host',
  'proposal_not_open', 'proposal_closed', 'not_a_ballot_proposal', 'store_unreadable', 'not_hosted_here',
  'proposal_not_found', 'bad_proposal_id', 'mtls_required',
] as const
