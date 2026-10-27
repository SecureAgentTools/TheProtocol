<!-- FEDERAL BALLOTS (§MCPTEST30, V0557; the rules are agentvault2-33's §MEMBERSHIP D2) — one federation proposal as the
     registries decide it: one signed ballot per registry, its members' result where it has members, its operator's
     choice where it does not. At the registry that HOSTS the proposal the panel lists every ballot whole (who cast, what,
     on what basis, the key that signed it); anywhere else it shows what the host's open list says. Below that, this
     registry's own part, as the next step the routes allow: open the members' vote, wait for it, cast its result, or
     (no members) cast the operator's choice. In member mode the cast never carries a choice. Every refusal shows its own
     word. Nothing here renders for a proposal decided by agents' votes: the floor shows this panel only where the
     proposal itself says ballot_mode. -->
<template>
  <section class="fbp" data-testid="fed-ballot-panel" :data-proposal="proposalId" :data-hosted="hosted ? '1' : '0'">
    <p class="fbp-rule">
      <Icon name="mdi:vote-outline" />
      <span>{{ t('senateView.federation.ballots.rule', "Decided by one signed ballot per registry: its members' result where it has members, its operator's choice where it does not.") }}</span>
    </p>

    <div class="fbp-summary" data-testid="fed-ballot-summary" :data-status="statusUpper" :data-cast="castCount ?? ''"
         :data-eligible="summary?.eligible ?? ''">
      <template v-if="decided && summary">
        <span>{{ tp('senateView.federation.ballots.decided', '{cast} of {eligible} eligible registries cast: {for} for, {against} against, {abstain} abstained.', {
          cast: fmtCount(summary.cast ?? 0), eligible: fmtCount(summary.eligible ?? 0), for: fmtCount(summary.for ?? 0),
          against: fmtCount(summary.against ?? 0), abstain: fmtCount(summary.abstain ?? 0) }) }}</span>
        <span class="fbp-conds">
          <span class="fbp-cond" :class="summary.two_thirds_met ? 'fbp-cond--met' : 'fbp-cond--unmet'" data-testid="fed-ballot-cond" data-cond="two_thirds">
            <Icon :name="summary.two_thirds_met ? 'mdi:check' : 'mdi:close'" />{{ t('senateView.federation.ballots.condTwoThirds', 'two thirds of the for and against ballots') }}
          </span>
          <span class="fbp-cond" :class="summary.participation_met ? 'fbp-cond--met' : 'fbp-cond--unmet'" data-testid="fed-ballot-cond" data-cond="participation">
            <Icon :name="summary.participation_met ? 'mdi:check' : 'mdi:close'" />{{ t('senateView.federation.ballots.condParticipation', 'enough registries cast') }}
          </span>
          <span class="fbp-cond" :class="summary.multi_registry_met ? 'fbp-cond--met' : 'fbp-cond--unmet'" data-testid="fed-ballot-cond" data-cond="multi_registry">
            <Icon :name="summary.multi_registry_met ? 'mdi:check' : 'mdi:close'" />{{ tp('senateView.federation.ballots.condMulti', 'at least {n} registries', { n: minRegistries ?? 2 }) }}
          </span>
        </span>
      </template>
      <template v-else-if="castCount !== null">
        <span>{{ castCount === 1
          ? tp('senateView.federation.ballots.castSoFarOne', '1 ballot cast so far at {host}.', { host: hostName })
          : tp('senateView.federation.ballots.castSoFar', '{n} ballots cast so far at {host}.', { n: fmtCount(castCount), host: hostName }) }}</span>
      </template>
      <template v-else-if="hosted && loadError">
        <span class="fbp-muted">{{ t('senateView.federation.ballots.unreadable', 'The ballots could not be read right now.') }}</span>
      </template>
    </div>

    <ul v-if="hosted && ballots.length" class="fbp-list">
      <li v-for="b in ballots" :key="b.registry_id" class="fbp-row" data-testid="fed-ballot"
          :data-registry="b.registry_id" :data-choice="b.choice">
        <div class="fbp-row-head">
          <span class="fbp-reg">{{ registryLabel(b.registry_id, hosts) }}</span>
          <span class="fbp-choice" :class="'fbp-choice--' + b.choice">{{ choiceLabel(b.choice) }}</span>
          <span v-if="b.registry_id === myRegistryId" class="fbp-here">{{ t('senateView.federation.ballots.thisRegistry', 'this registry') }}</span>
        </div>
        <div class="fbp-basis">{{ basisText(b) }}</div>
        <div class="fbp-sig">
          <Icon name="mdi:check-decagram" />
          <span>{{ tp('senateView.federation.ballots.signed', 'Signed with {kid}, verified by the host on receipt', { kid: b.envelope?.kid || '?' }) }}</span>
          <span v-if="b.cast_at" class="fbp-muted">· {{ fmtDateTime(b.cast_at) }}</span>
        </div>
        <div v-if="b.eligibility" class="fbp-elig">{{ eligibilityText(b) }}</div>
      </li>
    </ul>
    <p v-else-if="hosted && loaded && !loadError && !ballots.length" class="fbp-muted fbp-empty">
      {{ t('senateView.federation.ballots.none', 'No registry has cast a ballot yet.') }}
    </p>

    <div v-if="step.kind !== 'closed'" class="fbp-mine" data-testid="fed-ballot-mine" :data-step="step.kind">
      <template v-if="step.kind === 'unknown'">
        <span class="fbp-muted">{{ t('senateView.federation.ballots.partUnknown', "This registry's part cannot be read yet.") }}</span>
      </template>
      <template v-else-if="step.kind === 'cast'">
        <Icon name="mdi:check-circle-outline" />
        <span>{{ step.choice
          ? tp('senateView.federation.ballots.castHere', 'This registry has cast its ballot: {choice}.', { choice: choiceLabel(step.choice) })
          : t('senateView.federation.ballots.castHereNoChoice', 'This registry has cast its ballot.') }}</span>
      </template>

      <template v-else-if="step.kind === 'open_members_vote'">
        <span>{{ t('senateView.federation.ballots.membersDecide', "This registry has members, so their vote decides its ballot.") }}</span>
        <template v-if="isAdmin">
          <template v-if="durations.length">
            <label class="fbp-field">
              <span>{{ t('senateView.federation.ballots.duration', 'Open for') }}</span>
              <select v-model.number="duration" data-testid="fed-ballot-duration">
                <option v-for="d in durations" :key="d.request" :value="d.request">{{ durationLabel(d.effective) }}</option>
              </select>
            </label>
            <button type="button" class="tp-btn tp-btn--primary" :disabled="busy" data-testid="fed-ballot-open-vote" @click="doOpenVote">
              {{ t('senateView.federation.ballots.openVote', "Open the members' vote") }}
            </button>
          </template>
          <span v-else class="fbp-muted" data-testid="fed-ballot-too-late">{{ t('senateView.federation.ballots.tooLate', "Too little time is left for a members' vote before the federation proposal ends.") }}</span>
        </template>
        <span v-else class="fbp-muted">{{ t('senateView.federation.ballots.operatorOpens', "Its operator opens the members' vote.") }}</span>
      </template>

      <template v-else-if="step.kind === 'members_voting'">
        <Icon name="mdi:timer-sand" />
        <span>{{ tp('senateView.federation.ballots.membersVoting', "The members' vote is open until {ends}.", { ends: step.endsAt ? fmtDateTime(step.endsAt) : '?' }) }}</span>
        <button type="button" class="tp-btn tp-btn--ghost" data-testid="fed-ballot-goto-vote" @click="emit('open-local', step.localProposalId)">
          {{ tp('senateView.federation.ballots.gotoVote', 'Vote on proposal #{id}', { id: step.localProposalId }) }}
        </button>
      </template>

      <template v-else-if="step.kind === 'cast_members_result'">
        <template v-if="isAdmin">
          <span>{{ tp('senateView.federation.ballots.membersClosedAdmin', "The members' vote #{id} has closed: cast their result as this registry's ballot.", { id: step.localProposalId }) }}</span>
          <button type="button" class="tp-btn tp-btn--primary" :disabled="busy" data-testid="fed-ballot-cast" @click="doCast(null)">
            {{ t('senateView.federation.ballots.castResult', "Cast the members' result") }}
          </button>
        </template>
        <span v-else>{{ tp('senateView.federation.ballots.membersClosedOther', "The members' vote #{id} has closed: its operator casts their result as this registry's ballot.", { id: step.localProposalId }) }}</span>
      </template>

      <template v-else-if="step.kind === 'operator_choice'">
        <span>{{ t('senateView.federation.ballots.noMembers', "This registry has no members, so its operator's choice is its ballot.") }}</span>
        <template v-if="isAdmin">
          <label class="fbp-field">
            <span>{{ t('senateView.federation.ballots.choice', 'Choice') }}</span>
            <select v-model="choice" data-testid="fed-ballot-choice">
              <option value="for">{{ choiceLabel('for') }}</option>
              <option value="against">{{ choiceLabel('against') }}</option>
              <option value="abstain">{{ choiceLabel('abstain') }}</option>
            </select>
          </label>
          <button type="button" class="tp-btn tp-btn--primary" :disabled="busy" data-testid="fed-ballot-cast" @click="doCast(choice)">
            {{ t('senateView.federation.ballots.cast', "Cast this registry's ballot") }}
          </button>
        </template>
        <span v-else class="fbp-muted">{{ t('senateView.federation.ballots.operatorCasts', 'Its operator casts it.') }}</span>
      </template>
    </div>

    <div v-if="hosted && isAdmin && statusUpper === 'VOTING'" class="fbp-count" data-testid="fed-ballot-count" :data-gate="gate.reason">
      <template v-if="!confirmingCount">
        <button type="button" class="tp-btn tp-btn--ghost" :disabled="busy || !gate.open" data-testid="fed-ballot-tally" @click="confirmingCount = true">
          <Icon name="mdi:scale-balance" /> {{ t('senateView.federation.ballots.tally', 'Count the ballots') }}
        </button>
        <span v-if="!gate.open" class="fbp-muted">{{ gate.eligible === null
          ? t('senateView.federation.ballots.countWaitEnd', 'Counting opens when the vote ends.')
          : tp('senateView.federation.ballots.countWait', '{cast} of {eligible} eligible registries have cast; counting opens when all have, or when the vote ends.', { cast: fmtCount(gate.cast), eligible: fmtCount(gate.eligible) }) }}</span>
      </template>
      <template v-else>
        <span>{{ t('senateView.federation.ballots.countConfirm', 'Counting is final: it closes the vote for every registry.') }}</span>
        <button type="button" class="tp-btn tp-btn--primary" :disabled="busy" data-testid="fed-ballot-tally-confirm" @click="doTally">
          {{ t('senateView.federation.ballots.countNow', 'Count now') }}
        </button>
        <button type="button" class="tp-btn tp-btn--ghost" :disabled="busy" data-testid="fed-ballot-tally-cancel" @click="confirmingCount = false">
          {{ t('common.cancel', 'Cancel') }}
        </button>
      </template>
    </div>

    <p v-if="refusal" class="fbp-refusal" role="alert" data-testid="fed-ballot-refusal" :data-error="refusal.error">
      <code>{{ refusal.error }}</code> {{ refusalSentence }}
    </p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useUIStore } from '@/stores/ui'
import { appLocale } from '@/services/appLocale'
import { fmtCount, fmtDateTime } from '@/services/cockpit/num'
import { memberVoteFigure } from '@/services/membership/membership'
import {
  castBallot, castHere, countGate, fetchBallotEligibility, fetchProposalBallots, membersVoteOptions, nextStep,
  openMembersVote, refusalOf, registryLabel, tallyFederationProposal,
  type Ballot, type BallotChoice, type BallotHost, type BallotRefusal, type BallotSummary, type OpenBallotProposal,
} from '@/services/governance/federationBallots'

const props = defineProps<{
  proposalId: string
  status?: string | null
  endTimestamp?: string | null
  /** the store's decided summary (the proposal list carries it once counted) */
  summary?: BallotSummary | null
  /** 'self' or the frame peer's name, as the ballot routes take it */
  hostKey: string
  hostName: string
  /** true where this registry's store holds the proposal: only there are the ballots readable whole */
  hosted: boolean
  /** the open list's entry for this proposal (members' vote, who has cast), when it is open */
  open?: OpenBallotProposal | null
  hosts: Pick<BallotHost, 'name' | 'trust_domain'>[]
  myRegistryId: string
  isAdmin: boolean
  /** null while it is not known yet (the registry's config or its membership has not answered): no door is offered */
  hasMembers: boolean | null
  /** the proposal's own floor of registries (min_registries) */
  minRegistries?: number | null
}>()
const emit = defineEmits<{ (e: 'changed'): void; (e: 'open-local', id: number): void }>()

const { t, tp } = useI18n()
const ui = useUIStore()

const ballots = ref<Ballot[]>([])
const loaded = ref(false)
const loadError = ref(false)
const liveSummary = ref<BallotSummary | null>(null)
const liveStatus = ref<string | null>(null)
const busy = ref(false)
const refusal = ref<BallotRefusal | null>(null)
const choice = ref<BallotChoice>('for')
const confirmingCount = ref(false)
const eligibleIds = ref<string[] | null>(null)
const gate = computed(() => countGate({ eligibleIds: eligibleIds.value, castIds: ballots.value.map(b => b.registry_id),
  endIso: props.endTimestamp ?? null }))

const statusUpper = computed(() => String(liveStatus.value || props.status || '').toUpperCase())
const decided = computed(() => !!statusUpper.value && statusUpper.value !== 'VOTING')
const summary = computed(() => liveSummary.value || props.summary || null)

const castCount = computed<number | null>(() => {
  if (props.hosted && loaded.value && !loadError.value) return ballots.value.length
  const by = props.open?.ballots_cast_by
  return Array.isArray(by) ? by.length : null
})

const myBallot = computed(() => ballots.value.find(b => b.registry_id === props.myRegistryId) || null)
/* V0558: what THIS page cast, until a fresh read says so too. The open list a peer's proposal is read from is cached for a
   minute per worker, and the worker that answers the next read may not be the one that took the cast: without this the
   cast door came back for up to a minute after a successful cast (a second press is refused already_cast). */
const castLocal = ref<string | null>(null)
const step = computed(() => nextStep({
  status: statusUpper.value || 'VOTING',
  cast: castLocal.value ? true
    : castHere(props.myRegistryId, props.open ?? null, props.hosted && loaded.value && !loadError.value ? ballots.value : null),
  castChoice: castLocal.value ?? myBallot.value?.choice ?? null,
  hasMembers: props.hasMembers,
  localVote: props.open?.local_vote ?? null,
  known: !!props.myRegistryId,          // the open list names this registry; without it, whether it cast is unknown
}))

const durations = computed(() => membersVoteOptions(props.endTimestamp ?? props.open?.end_timestamp ?? null))
const duration = ref<number>(86400)
watch(durations, (ds) => {
  if (ds.length && !ds.some(d => d.request === duration.value)) duration.value = ds[Math.min(1, ds.length - 1)].request
}, { immediate: true })

async function load() {
  if (!props.hosted) return
  try {
    const doc = await fetchProposalBallots(props.proposalId)
    ballots.value = Array.isArray(doc.ballots) ? doc.ballots : []
    liveSummary.value = doc.ballot_summary || null
    liveStatus.value = doc.status || null
    loadError.value = false
    if (props.isAdmin && String(doc.status || '').toUpperCase() === 'VOTING') {
      // who the host would count now: the count stays shut until every one of them has cast (or the vote has ended)
      eligibleIds.value = await fetchBallotEligibility()
        .then(e => (e.registries || []).filter(r => r.eligible).map(r => r.id)).catch(() => null)
    }
  } catch {
    loadError.value = true
  } finally {
    loaded.value = true
  }
}
onMounted(load)
watch(() => [props.proposalId, props.status], () => { void load() })

function choiceLabel(c: string): string {
  if (c === 'for') return t('senateView.federation.ballots.for', 'for')
  if (c === 'against') return t('senateView.federation.ballots.against', 'against')
  if (c === 'abstain') return t('senateView.federation.ballots.abstain', 'abstain')
  return c
}

function basisText(b: Ballot): string {
  const basis = b.basis || {}
  if (basis.mode === 'members') {
    return tp('senateView.federation.ballots.basisMembers', "Its members' vote #{id}: {voters} voted, weight {for} for and {against} against", {
      id: basis.local_proposal_id ?? '?', voters: fmtCount(basis.voters ?? 0),
      for: memberVoteFigure(basis.points_for ?? 0, 100, appLocale()),
      against: memberVoteFigure(basis.points_against ?? 0, 100, appLocale()) })
  }
  if (basis.mode === 'operator') return t('senateView.federation.ballots.basisOperator', "Its operator's choice (it has no members)")
  return t('senateView.federation.ballots.basisUnknown', 'Basis not stated')
}

function eligibilityText(b: Ballot): string {
  const e = b.eligibility || {}
  const licence = e.licence_ok ? tp('senateView.federation.ballots.licenceOk', 'licence: {state}', { state: e.licence_state || 'ok' })
    : t('senateView.federation.ballots.licenceNo', 'licence: not passing')
  // the host judged the ballot under ITS rule and wrote why; under "observe" it says "(observed, not enforced)", and a
  // registry refused under "required" never reaches the store, so the reason is shown as the server worded it
  const why = (e.reasons || []).filter(r => !/^licence /.test(r))
  const track = e.track_ok ? t('senateView.federation.ballots.trackOk', 'track record: established')
    : (why.length ? why.join('; ') : t('senateView.federation.ballots.trackProvisional', 'track record: provisional'))
  return `${licence} · ${track}`
}

function durationLabel(s: number): string {
  if (s % 86400 === 0) return tp('senateView.federation.ballots.days', '{n} days', { n: s / 86400 })
  if (s % 3600 === 0) return tp('senateView.federation.ballots.hours', '{n} hours', { n: s / 3600 })
  return tp('senateView.federation.ballots.minutes', '{n} minutes', { n: Math.round(s / 60) })
}

const refusalSentence = computed(() => {
  const r = refusal.value
  if (!r) return ''
  const extra = r.extra || {}
  if (r.error === 'local_vote_open' && typeof extra.ends_at === 'string') {
    return tp('senateView.federation.ballots.refusal.local_vote_open', "The members' vote is still open until {ends}.", { ends: fmtDateTime(extra.ends_at) })
  }
  if (r.error === 'not_eligible' && Array.isArray(extra.reasons)) return `${r.message} ${extra.reasons.join('; ')}`
  if (r.error === 'host_refused' && extra.host_answer && typeof extra.host_answer === 'object') {
    const ha = extra.host_answer as { error?: string; message?: string }
    return `${r.message} ${ha.error ? `(${ha.error}) ` : ''}${ha.message || ''}`.trim()
  }
  if (r.error === 'members_decided' && typeof extra.members_decided === 'string') {
    return tp('senateView.federation.ballots.refusal.members_decided', 'The members decided {choice}; the operator does not override them.', { choice: choiceLabel(extra.members_decided) })
  }
  return r.message || r.error
})

async function act<T>(fn: () => Promise<T>, okTitle: string, onOk?: (res: T) => void) {
  busy.value = true
  refusal.value = null
  try {
    const res = await fn()
    if (onOk) onOk(res)
    ui.showSuccess(okTitle)
    await load()
    emit('changed')
  } catch (e: unknown) {
    const r = refusalOf(e)
    refusal.value = r || { error: 'request_failed', message: (e as Error)?.message || '', status: 0, extra: {} }
    ui.showError(t('senateView.federation.ballots.refusedTitle', 'Refused'), `${refusal.value.error}: ${refusalSentence.value}`)
  } finally {
    busy.value = false
  }
}

function doOpenVote() {
  void act(() => openMembersVote(props.hostKey, props.proposalId, duration.value),
    t('senateView.federation.ballots.openedVote', "The members' vote is open"))
}
function doCast(c: BallotChoice | null) {
  // in member mode the members decide: the cast carries no choice (a different one is refused 409 members_decided)
  void act(() => castBallot(props.hostKey, props.proposalId, props.hasMembers === false ? c : null),
    t('senateView.federation.ballots.castDone', 'Ballot cast'), (res) => { castLocal.value = res?.choice || c || 'for' })
}
function doTally() {
  confirmingCount.value = false
  void act(() => tallyFederationProposal(props.proposalId), t('senateView.federation.ballots.tallied', 'Ballots counted'))
}
</script>

<style scoped>
.fbp { margin-top: 10px; padding: 10px 12px; border: 1px solid var(--border, rgba(120, 140, 180, 0.25)); border-radius: 8px; background: rgba(15, 25, 45, 0.35); font-size: 0.82rem; }
.fbp-rule { display: flex; gap: 6px; align-items: flex-start; color: var(--muted); margin: 0 0 8px; }
.fbp-summary { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; margin-bottom: 8px; }
.fbp-conds { display: inline-flex; flex-wrap: wrap; gap: 6px; }
.fbp-cond { display: inline-flex; align-items: center; gap: 3px; padding: 1px 8px; border-radius: 999px; font-size: 0.74rem; border: 1px solid currentColor; }
.fbp-cond--met { color: var(--green, #34d399); }
.fbp-cond--unmet { color: #f87171; }
.fbp-list { list-style: none; margin: 0 0 8px; padding: 0; display: grid; gap: 8px; }
.fbp-row { padding: 8px 10px; border-radius: 6px; background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(120, 140, 180, 0.18); }
.fbp-row-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.fbp-reg { font-weight: 600; }
.fbp-choice { padding: 0 8px; border-radius: 4px; font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.04em; border: 1px solid currentColor; }
.fbp-choice--for { color: var(--green, #34d399); }
.fbp-choice--against { color: #f87171; }
.fbp-choice--abstain { color: var(--amber, #fbbf24); }
.fbp-here { font-size: 0.72rem; color: var(--cyan, #22d3ee); }
.fbp-basis, .fbp-elig { color: var(--muted); margin-top: 3px; }
.fbp-sig { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; margin-top: 3px; color: var(--cyan, #22d3ee); word-break: break-all; }
.fbp-mine { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding-top: 8px; border-top: 1px dashed rgba(120, 140, 180, 0.25); }
.fbp-field { display: inline-flex; gap: 6px; align-items: center; }
.fbp-field select { background: rgba(0, 0, 0, 0.3); color: inherit; border: 1px solid rgba(120, 140, 180, 0.35); border-radius: 4px; padding: 2px 6px; }
.fbp-count { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.fbp-refusal { margin: 8px 0 0; color: #fca5a5; }
.fbp-refusal code { font-size: 0.74rem; padding: 0 4px; border-radius: 3px; background: rgba(248, 113, 113, 0.12); }
.fbp-muted { color: var(--muted); }
.fbp-empty { margin: 0 0 8px; }
</style>
