<!-- THE COMMONS (§MEMBERSHIP phase C, 2026-10-02) — a share of this registry's fee income becomes a season's budget;
     work already done is submitted with its evidence; members spread up to 100 points over it in one ballot; at the
     close each submission gets the median of its points and the budget pays the work (routers/commons.py).
     Shown where /public/registry-config says commons_enabled; the parent decides that. The words are the commons'
     own: season, budget, submission, ballot, points, award. Nothing here is a reward, a yield or a share. -->
<template>
  <section class="cmn" data-testid="commons-panel" :data-state="state">
    <header class="cmn-head">
      <div>
        <h2 class="cmn-title"><Icon name="mdi:scale-balance" /> {{ t('commons.title', 'The commons') }}</h2>
        <p class="cmn-lead">{{ t('commons.lead', "Part of this registry's fee income becomes a season's budget. Members spread points over work already done, and the budget pays for that work.") }}
          <RouterLink :to="{ name: 'registries' }" class="cmn-link" data-testid="commons-board-link">{{ t('commons.compare', "Every registry's commons") }}</RouterLink></p>
      </div>
      <label v-if="seasons.length > 1" class="cmn-pick">
        <span class="cmn-muted">{{ t('commons.season.pick', 'Season') }}</span>
        <select v-model.number="selectedId" class="tp-input cmn-pick__select" data-testid="commons-season-pick">
          <option v-for="s in seasons" :key="s.id" :value="s.id">#{{ s.id }} {{ s.title }} · {{ statusWord(s.status) }}</option>
        </select>
      </label>
    </header>

    <p v-if="state === 'loading'" class="cmn-muted" aria-busy="true">…</p>
    <p v-else-if="state === 'disabled'" class="cmn-muted" data-testid="commons-disabled">{{ t('commons.disabled', 'The commons is not open on this registry.') }}</p>
    <p v-else-if="state === 'failed'" class="cmn-muted" role="status">{{ t('commons.loadFailed', 'The commons could not be read right now.') }}</p>
    <div v-else-if="state === 'empty'" class="cmn-empty" data-testid="commons-empty">
      <p class="cmn-muted">{{ t('commons.empty', 'No season has been opened on this registry yet.') }}</p>
    </div>

    <template v-else-if="season">
      <!-- the season: its window, its budget and where the budget came from, its rules -->
      <div class="cmn-season" data-testid="commons-season" :data-phase="phase" :data-season="season.id">
        <div class="cmn-season__top">
          <h3 class="cmn-season__title">#{{ season.id }} {{ season.title }}</h3>
          <span class="cmn-chip" :class="`cmn-chip--${phase}`" data-testid="commons-phase">{{ phaseWord }}</span>
        </div>
        <p class="cmn-season__when" data-testid="commons-when">{{ whenLine }}</p>
        <div class="cmn-budget">
          <div class="cmn-budget__value" data-testid="commons-budget">{{ amount(season.budget) }} <span class="cmn-unit">{{ season.currency }}</span></div>
          <div class="cmn-muted" data-testid="commons-budget-source">{{ budgetSource }}</div>
        </div>
        <ul class="cmn-rules" data-testid="commons-rules">
          <li>{{ tp('commons.rules.points', 'A member spreads up to {points} points over the submissions, never on their own work.', { points: season.ballot_points }) }}</li>
          <li>{{ tp('commons.rules.median', 'A submission counts once at least {n} of the members give it points; it then gets the median of their points.', { n: season.min_voters }) }}</li>
          <li>{{ tp('commons.rules.cap', 'No developer receives more than {cap}% of the budget; what is not awarded is not paid out.', { cap: num(season.recipient_cap_percent) }) }}</li>
        </ul>
        <p class="cmn-muted" data-testid="commons-counts">
          {{ tp('commons.counts', 'Submissions: {subs} · Ballots: {ballots}', { subs: liveSubmissions.length, ballots: season.ballots_cast }) }}
        </p>
      </div>

      <!-- the result once the tally is fixed -->
      <div v-if="season.tally" class="cmn-result" data-testid="commons-result">
        <Icon name="mdi:check-circle-outline" />
        <span>{{ tp('commons.result', 'Awarded {awarded} {cur} (ballots counted: {counted}); {left} {cur} of the budget is not paid out.',
          { awarded: amount(season.tally.awarded), left: amount(season.tally.unallocated), cur: season.currency, counted: season.tally.ballots_counted }) }}</span>
      </div>

      <!-- the member's side: the ballot they would replace, or why they cannot cast one -->
      <div v-if="phase === 'open'" class="cmn-mine" data-testid="commons-mine">
        <p v-if="mineState === 'failed'" class="cmn-muted" role="status">{{ t('commons.mine.failed', 'Your ballot could not be read right now; sending one still works.') }}</p>
        <p v-else-if="mine && !mine.isMember" class="cmn-note" data-testid="commons-not-member">
          <Icon name="mdi:information-outline" /> {{ t('commons.mine.notMember', 'Only members cast a ballot. Anyone with a verified account can submit work.') }}
        </p>
        <p v-else-if="mine && mine.myBallot" class="cmn-muted" data-testid="commons-saved-ballot">
          {{ tp('commons.mine.saved', 'Your ballot from {date} is shown below, with {points} of {max} points given. Sending a new one replaces it until the season closes.',
            { date: fmtDate(mine.myBallot.updatedAt, true), points: mine.myBallot.totalPoints, max: season.ballot_points }) }}
        </p>
      </div>

      <!-- the submissions -->
      <div class="cmn-list-head">
        <h4 class="cmn-h4">{{ t('commons.subs.title', 'Submissions') }}</h4>
        <button v-if="phase === 'open'" type="button" class="tp-btn tp-btn--ghost cmn-submit-btn" data-testid="commons-submit-open" @click="showSubmit = true">
          <Icon name="mdi:plus" /> {{ t('commons.submit.open', 'Submit work') }}
        </button>
      </div>
      <p v-if="season.submissions.length === 0" class="cmn-muted" data-testid="commons-no-subs">{{ t('commons.subs.none', 'Nothing has been submitted to this season yet.') }}</p>
      <ul v-else class="cmn-subs">
        <li v-for="s in season.submissions" :key="s.id" class="cmn-sub" data-testid="commons-sub" :data-id="s.id" :data-status="s.status"
            :class="{ 'cmn-sub--struck': s.status !== 'submitted', 'cmn-sub--mine': isMine(s.id) }">
          <div class="cmn-sub__top">
            <span class="cmn-kind">{{ kindWord(s.kind) }}</span>
            <span class="cmn-sub__title">{{ s.title }}</span>
            <span v-if="isMine(s.id)" class="cmn-tag" data-testid="commons-sub-mine">{{ t('commons.subs.yours', 'Yours') }}</span>
          </div>
          <div class="cmn-muted">
            {{ t('commons.subs.by', 'by') }}
            <RouterLink :to="{ name: 'agent-details', params: { agentId: s.submitter_did } }" class="cmn-link" data-testid="commons-sub-by">{{ submitterLabel(s, season.submissions) }}</RouterLink>
            <template v-if="s.created_at"> · {{ fmtDate(s.created_at) }}</template>
          </div>
          <details v-if="s.description" class="cmn-sub__desc"><summary>{{ t('commons.subs.description', 'Description') }}</summary><p>{{ s.description }}</p></details>
          <ul v-if="s.evidence.length" class="cmn-evidence" data-testid="commons-evidence">
            <li v-for="(e, i) in s.evidence" :key="i">
              <span class="cmn-muted">{{ evidenceWord(e.type) }}:</span>
              <a v-if="e.url" :href="safeExternalUrl(e.url)" target="_blank" rel="noopener noreferrer nofollow" class="cmn-link">{{ e.ref }}</a>
              <span v-else>{{ e.ref }}</span>
            </li>
          </ul>

          <p v-if="s.status === 'struck'" class="cmn-struck" data-testid="commons-sub-struck">{{ tp('commons.subs.struck', 'Struck: {reason}', { reason: s.struck_reason || '' }) }}</p>

          <!-- after the close: what the tally gave it, and why when nothing -->
          <p v-if="s.award" class="cmn-award" data-testid="commons-award" :data-award="s.award.status">
            {{ tp('commons.award.line', '{amount} {cur} awarded: a median of {median} points, from {voters} of the members', { median: num(s.award.median_points), voters: s.award.voters, amount: amount(s.award.amount), cur: season.currency }) }}
            · <span :class="`cmn-award--${s.award.status}`">{{ awardStatusWord(s.award) }}</span>
          </p>
          <p v-else-if="tallyRow(s.id)?.reason" class="cmn-muted" data-testid="commons-no-award">{{ noAwardWord(tallyRow(s.id)!) }}</p>

          <!-- an award whose payment failed (or never answered): an admin writes it off with a public reason -->
          <div v-if="canAdmin && season.status === 'closed' && s.award && s.award.id && awaitsDecision(s.award)" class="cmn-strike">
            <button v-if="writeOffId !== s.award.id" type="button" class="tp-btn tp-btn--ghost" :data-testid="`commons-writeoff-open-${s.id}`" @click="openWriteOff(s.award.id)">
              {{ t('commons.admin.writeOff', 'Write off') }}
            </button>
            <form v-else class="cmn-strike__form" @submit.prevent="doWriteOff(s.award.id)">
              <input v-model="writeOffReason" class="tp-input" maxlength="240" :placeholder="t('commons.admin.writeOffReason', 'Why this award is settled without a payment (kept on the award)')" :data-testid="`commons-writeoff-reason-${s.id}`" />
              <button type="submit" class="tp-btn tp-btn--danger" :disabled="adminBusy || writeOffReason.trim().length < 5" :data-testid="`commons-writeoff-confirm-${s.id}`">{{ t('commons.admin.writeOffConfirm', 'Write it off') }}</button>
              <button type="button" class="tp-btn tp-btn--ghost" @click="writeOffId = null">{{ t('common.cancel', 'Cancel') }}</button>
            </form>
          </div>

          <!-- the ballot field: members only, never on their own work, only while the season takes ballots -->
          <div v-if="canBallot && s.status === 'submitted'" class="cmn-points">
            <template v-if="isMine(s.id)">
              <span class="cmn-muted">{{ t('commons.ballot.ownWork', 'Other members decide the points for your own work.') }}</span>
            </template>
            <template v-else>
              <button type="button" class="tp-btn tp-btn--ghost cmn-step" :disabled="ballotLocked || (draft[String(s.id)] || 0) <= 0"
                      :aria-label="t('commons.ballot.less', 'Fewer points')" @click="bump(s.id, -5)">−</button>
              <input class="tp-input cmn-points__input" type="number" inputmode="numeric" min="0" :max="season.ballot_points" step="1"
                     :value="draft[String(s.id)] || 0" :disabled="ballotLocked" :data-testid="`commons-points-${s.id}`"
                     :aria-label="tp('commons.ballot.pointsFor', 'Points for {title}', { title: s.title })"
                     @change="onPoints(s.id, ($event.target as HTMLInputElement).value)" />
              <button type="button" class="tp-btn tp-btn--ghost cmn-step" :disabled="ballotLocked || left <= 0"
                      :aria-label="t('commons.ballot.more', 'More points')" @click="bump(s.id, 5)">+</button>
            </template>
          </div>

          <div v-if="canAdmin && s.status === 'submitted' && (season.status === 'open' || (season.status === 'closed' && !payStarted))" class="cmn-strike">
            <button v-if="strikeId !== s.id" type="button" class="tp-btn tp-btn--ghost cmn-strike__open" :data-testid="`commons-strike-open-${s.id}`" @click="openStrike(s.id)">
              <Icon name="mdi:flag-outline" /> {{ t('commons.admin.strike', 'Strike') }}
            </button>
            <form v-else class="cmn-strike__form" @submit.prevent="doStrike(s.id)">
              <input v-model="strikeReason" class="tp-input" maxlength="240" :placeholder="t('commons.admin.strikeReason', 'Why the evidence does not hold (shown publicly)')" :data-testid="`commons-strike-reason-${s.id}`" />
              <button type="submit" class="tp-btn tp-btn--danger" :disabled="adminBusy || strikeReason.trim().length < 5" :data-testid="`commons-strike-confirm-${s.id}`">{{ t('commons.admin.strikeConfirm', 'Strike it') }}</button>
              <button type="button" class="tp-btn tp-btn--ghost" @click="strikeId = null">{{ t('common.cancel', 'Cancel') }}</button>
            </form>
          </div>
        </li>
      </ul>

      <!-- the ballot's own bar -->
      <div v-if="canBallot && votableCount > 0" class="cmn-ballot" data-testid="commons-ballot">
        <span class="cmn-ballot__left" data-testid="commons-points-left">{{ tp('commons.ballot.left', '{left} of {max} points left', { left, max: season.ballot_points }) }}</span>
        <button type="button" class="tp-btn tp-btn--primary" :disabled="!!problem || ballotLocked" data-testid="commons-ballot-send" @click="sendBallot">
          <Icon name="mdi:vote" /> {{ mine?.myBallot ? t('commons.ballot.replace', 'Replace my ballot') : t('commons.ballot.send', 'Send my ballot') }}
        </button>
        <span v-if="problem === 'empty'" class="cmn-muted">{{ t('commons.ballot.empty', 'Give points to at least one submission.') }}</span>
      </div>

      <!-- who gave what, once the season closed (the transparency that makes a ring visible) -->
      <details v-if="season.ballots && season.ballots.length" class="cmn-ballots" data-testid="commons-ballots">
        <summary>{{ tp('commons.ballots.title', 'The ballots ({n})', { n: season.ballots.length }) }}</summary>
        <ul>
          <li v-for="b in season.ballots" :key="b.voter_did">
            <span class="cmn-mono" :title="b.voter_did">{{ shortDid(b.voter_did) }}</span>:
            <span v-for="(p, sid) in b.allocations" :key="sid" class="cmn-alloc">#{{ sid }} {{ p }}</span>
          </li>
        </ul>
      </details>

      <CommonsAdmin v-if="canAdmin" :season="season" :busy="adminBusy" class="cmn-admin" @act="onAdmin" />
    </template>

    <!-- an admin opens the first season, or the next once the last one is settled -->
    <CommonsAdmin v-if="canAdmin && (state === 'empty' || (state === 'ready' && !liveSeason))" :season="null" :busy="adminBusy" class="cmn-admin" @act="onAdmin" />

    <CommonsSubmitForm v-if="season && showSubmit" :season-id="season.id" :limit="Number(season.rules?.max_submissions_per_developer) || null"
                       @close="showSubmit = false" @submitted="onSubmitted" />

    <StepUpConfirm
      v-if="flow.stepUp.value"
      :show="!!flow.stepUp.value"
      :challenge="flow.stepUp.value"
      :busy="flow.busy.value"
      :error="flow.stepUpError.value"
      @update:show="(v: boolean) => { if (!v) flow.cancel() }"
      @approved="(id: string) => flow.approved(id)"
      @code="(code: string) => flow.code(code)"
    />
  </section>
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { computed, onMounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import StepUpConfirm from '@/components/membership/StepUpConfirm.vue'
import CommonsSubmitForm from './CommonsSubmitForm.vue'
import CommonsAdmin from './CommonsAdmin.vue'
import { useI18n } from '@/composables/useI18n'
import { useStepUpFlow } from '@/composables/useMemberVoteFlow'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { appLocale } from '@/services/appLocale'
import { fmt } from '@/services/cockpit/num'
import { commonsApi, type BallotOutcome, type MySeasonView } from '@/services/api/commons'
import {
  awaitsDecision, ballotProblem, ballotTotal, cleanAllocations, leadSeason, paymentStarted, pointsLeft, seasonPhase, setPoints,
  submitterLabel,
  type Award, type CommonsAdminAct, type SeasonDetail, type SeasonListItem, type SeasonPhase, type TallyRow,
} from '@/services/commons/commons'

const { t, tp } = useI18n()
const auth = useAuthStore()
const ui = useUIStore()

type State = 'loading' | 'ready' | 'empty' | 'disabled' | 'failed'
const state = ref<State>('loading')
const seasons = ref<SeasonListItem[]>([])
const selectedId = ref<number | null>(null)
const season = ref<SeasonDetail | null>(null)
const mine = ref<MySeasonView | null>(null)
const mineState = ref<'idle' | 'ready' | 'failed'>('idle')
const draft = ref<Record<string, number>>({})
const showSubmit = ref(false)
const adminBusy = ref(false)
const strikeId = ref<number | null>(null)
const strikeReason = ref('')
const writeOffId = ref<number | null>(null)
const writeOffReason = ref('')
const now = ref(Date.now())

const canAdmin = computed(() => {
  const u = auth.user as unknown as Record<string, unknown> | null
  return auth.userRole === 'admin' || !!u?.admin_treasury
})
const liveSeason = computed(() => seasons.value.find((s) => s.status === 'open' || s.status === 'closed') || null)
const phase = computed<SeasonPhase | null>(() => seasonPhase(season.value, now.value))
const liveSubmissions = computed(() => (season.value?.submissions || []).filter((s) => s.status === 'submitted'))
const payStarted = computed(() => paymentStarted(season.value?.submissions))
const myIds = computed(() => new Set((mine.value?.mySubmissions || []).map((s) => Number(s.id))))
function isMine(id: number) { return myIds.value.has(Number(id)) }
const canBallot = computed(() => phase.value === 'open' && !!mine.value?.isMember)
const votableCount = computed(() => liveSubmissions.value.filter((s) => !isMine(s.id)).length)
const max = computed(() => season.value?.ballot_points || 100)
const left = computed(() => pointsLeft(draft.value, max.value))
const problem = computed(() => ballotProblem(draft.value, max.value))

// ── words ─────────────────────────────────────────────────────────────────
function fmtDate(iso: string | null | undefined, withTime = false): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
  try { return new Intl.DateTimeFormat(appLocale(), withTime ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'medium' }).format(d) } catch { return iso.slice(0, 10) }
}
function amount(v: string | null | undefined) { return fmt(v, 6) }
function num(v: string | number | null | undefined) { return fmt(v, 2) }
function shortDid(did: string) { return did.length > 26 ? `${did.slice(0, 18)}…${did.slice(-6)}` : did }
function statusWord(s: string) {
  return ({ open: t('commons.status.open', 'open'), closed: t('commons.status.closed', 'closed'),
    paid: t('commons.status.paid', 'paid'), cancelled: t('commons.status.cancelled', 'cancelled') } as Record<string, string>)[s] || s
}
const phaseWord = computed(() => ({
  open: t('commons.phase.open', 'Open'), ended: t('commons.phase.ended', 'Window ended'),
  closed: t('commons.phase.closed', 'Closed, awards pending'), paid: t('commons.phase.paid', 'Paid'),
  cancelled: t('commons.phase.cancelled', 'Cancelled'),
} as Record<string, string>)[phase.value || ''] || '')
const whenLine = computed(() => {
  const s = season.value
  if (!s) return ''
  switch (phase.value) {
    case 'open': return tp('commons.when.open', 'Open since {from}; submissions and ballots until {until}.', { from: fmtDate(s.opens_at), until: fmtDate(s.ends_at, true) })
    case 'ended': return tp('commons.when.ended', 'The window ended {until}; the season is closed next and its tally fixed.', { until: fmtDate(s.ends_at, true) })
    case 'closed': return tp('commons.when.closed', 'Closed {date}; the tally is fixed and the awards wait for payment.', { date: fmtDate(s.closed_at) })
    case 'paid': return tp('commons.when.paid', 'Paid {date}.', { date: fmtDate(s.paid_at) })
    case 'cancelled': return tp('commons.when.cancelled', 'Cancelled {date}: {reason}', { date: fmtDate(s.cancelled_at), reason: s.cancel_reason || '' })
    default: return ''
  }
})
const budgetSource = computed(() => {
  const s = season.value
  if (!s) return ''
  const p = { pct: num(s.fee_share_percent), balance: amount(s.fee_collector_balance_at_open), cur: s.currency, seed: amount(s.seed) }
  return Number(s.seed || 0) > 0
    ? tp('commons.budget.fromFeesAndSeed', "{pct}% of the fee collector's {balance} {cur} when the season opened, plus {seed} {cur} from the treasury.", p)
    : tp('commons.budget.fromFees', "{pct}% of the fee collector's {balance} {cur} when the season opened.", p)
})
function kindWord(k: string) {
  return ({ guild_order: t('commons.kind.guild_order', 'Guild order'), change: t('commons.kind.change', 'Change'),
    translation: t('commons.kind.translation', 'Translation'), operations: t('commons.kind.operations', 'Operations'),
    help: t('commons.kind.help', 'Help'), other: t('commons.kind.other', 'Other') } as Record<string, string>)[k] || k
}
function evidenceWord(k: string) {
  return ({ guild_order: t('commons.evidence.guild_order', 'Guild order'), url: t('commons.evidence.url', 'Link'),
    commit: t('commons.evidence.commit', 'Commit'), ticket: t('commons.evidence.ticket', 'Ticket'),
    document: t('commons.evidence.document', 'Document'), other: t('commons.evidence.other', 'Other') } as Record<string, string>)[k] || k
}
function awardStatusWord(a: Award) {
  if (a.status === 'paid') return tp('commons.award.paid', 'paid {date}', { date: fmtDate(a.paid_at) })
  if (a.status === 'partial') return tp('commons.award.partial', 'paid {funded}, {short} short', { funded: amount(a.funded_amount), short: amount(a.shortfall) })
  if (a.status === 'written_off') return tp('commons.award.writtenOff', 'written off: {reason}', { reason: a.written_off_reason || '' })
  if (a.status === 'failed' || (a.status === 'pending' && a.attempted_at)) return t('commons.award.failed', 'payment failed; it waits for the next payment run or an admin\'s decision')
  return t('commons.award.pending', 'waiting for payment')
}
function tallyRow(id: number): TallyRow | undefined {
  return season.value?.tally?.rows.find((r) => Number(r.submission_id) === Number(id))
}
function noAwardWord(r: TallyRow) {
  return r.reason === 'too_few_voters'
    ? tp('commons.award.tooFew', 'Points came from {voters} of the members; {min} are needed, so no award.', { voters: r.voters, min: season.value?.min_voters ?? 0 })
    : t('commons.award.noPoints', 'No member gave it points, so no award.')
}

// ── loading ───────────────────────────────────────────────────────────────
async function loadList() {
  state.value = 'loading'
  try {
    const out = await commonsApi.seasons()
    if (out.state === 'disabled') { state.value = 'disabled'; return }
    seasons.value = out.seasons
    if (!out.seasons.length) { state.value = 'empty'; season.value = null; return }
    const keep = selectedId.value != null && out.seasons.some((s) => s.id === selectedId.value)
    const id = keep ? selectedId.value! : leadSeason(out.seasons)!.id
    if (id === selectedId.value) await loadSeason(id)
    else selectedId.value = id            // the watcher loads it
  } catch {
    state.value = 'failed'
  }
}

async function loadSeason(id: number) {
  try {
    const out = await commonsApi.season(id)
    if (out.state === 'disabled') { state.value = 'disabled'; return }
    if (out.state === 'not_found') { await loadList(); return }
    season.value = out.season
    state.value = 'ready'
    now.value = Date.now()
  } catch {
    state.value = 'failed'
    return
  }
  await loadMine(id)
}

async function loadMine(id: number) {
  mine.value = null
  mineState.value = 'idle'
  draft.value = {}
  if (!auth.isAuthenticated) return
  try {
    mine.value = await commonsApi.mine(id)
    mineState.value = 'ready'
    // a replaced ballot starts from the saved one (only points on submissions still live)
    const live = new Set(liveSubmissions.value.map((s) => String(s.id)))
    const saved = cleanAllocations(mine.value?.myBallot?.allocations || {})
    draft.value = Object.fromEntries(Object.entries(saved).filter(([k]) => live.has(k)))
  } catch {
    mineState.value = 'failed'
  }
}

watch(selectedId, (id) => { if (id != null) void loadSeason(id) })
onMounted(loadList)

// ── the ballot ────────────────────────────────────────────────────────────
const ballotLocked = computed(() => flow.busy.value || !!flow.stepUp.value)
function onPoints(id: number, value: string) { draft.value = setPoints(draft.value, id, value, max.value) }
function bump(id: number, by: number) { draft.value = setPoints(draft.value, id, (draft.value[String(id)] || 0) + by, max.value) }

type BallotSettled = Exclude<BallotOutcome, { kind: 'step_up' }>
const flow = useStepUpFlow<BallotSettled>(onBallotSettled)

async function sendBallot() {
  const s = season.value
  if (!s || problem.value) return
  const alloc = cleanAllocations(draft.value)     // fixed here: a proof is bound to exactly these points
  try {
    await flow.start((extra) => commonsApi.ballot(s.id, alloc, extra))
  } catch (e: any) {
    ui.showError(t('commons.ballot.failed', 'The ballot could not be sent'), e?.response?.data?.message || e?.message || '')
  }
}

function onBallotSettled(out: BallotSettled) {
  if (out.kind === 'saved') {
    ui.showSuccess(t('commons.ballot.saved', 'Ballot saved'),
      tp('commons.ballot.savedMsg', 'Points given: {points}, to {n} of the submissions. You can change the ballot until the season closes.',
        { points: out.totalPoints || ballotTotal(out.allocations), n: Object.keys(out.allocations).length }))
    if (season.value) void loadSeason(season.value.id)
  } else if (out.kind === 'not_member') {
    ui.showWarning(t('commons.mine.notMemberTitle', 'Only members cast a ballot'), t('commons.mine.notMember', 'Only members cast a ballot. Anyone with a verified account can submit work.'))
    if (season.value) void loadMine(season.value.id)
  } else if (out.kind === 'second_factor_required') {
    ui.showWarning(t('membership.vote.secondFactor', 'Set up a confirmation first'),
      t('commons.ballot.secondFactorMsg', 'This registry needs every ballot confirmed. Enrol your phone in Pocket or turn on two-factor sign-in in Settings, then send it again.'))
  } else if (out.kind === 'refused') {
    if (out.error === 'own_submission' || out.error === 'unknown_submission') {
      // drop the points the server will not take, and say so; the rest of the ballot stays as it was
      const drop = new Set(out.submissionIds)
      draft.value = Object.fromEntries(Object.entries(draft.value).filter(([k]) => !drop.has(k)))
    }
    if (out.error === 'season_not_open' && season.value) void loadSeason(season.value.id)
    ui.showWarning(t('commons.ballot.refused', 'The ballot was not taken'), refusalWord(out.error, out.message))
  }
}

function refusalWord(code: string, server: string): string {
  const words: Record<string, string> = {
    own_submission: t('commons.refusal.own_submission', 'A member never gives points to their own work; those points were removed.'),
    unknown_submission: t('commons.refusal.unknown_submission', 'Some submissions are no longer in the season; their points were removed.'),
    too_many_points: t('commons.refusal.too_many_points', 'A ballot spreads at most 100 points.'),
    empty_ballot: t('commons.ballot.empty', 'Give points to at least one submission.'),
    season_not_open: t('commons.refusal.noMoreBallots', 'This season no longer takes ballots.'),
    agent_not_active: t('commons.refusal.agent_not_active', 'The agent you act as is suspended.'),
    developer_not_eligible: t('commons.refusal.developer_not_eligible', 'Your account needs a verified email to take part.'),
  }
  return words[code] || server || code
}

// ── a submission ──────────────────────────────────────────────────────────
function onSubmitted() {
  showSubmit.value = false
  if (season.value) void loadSeason(season.value.id)
}

// ── admin_treasury ────────────────────────────────────────────────────────
function openStrike(id: number) { strikeId.value = id; strikeReason.value = '' }

async function doStrike(id: number) {
  const s = season.value
  if (!s || adminBusy.value) return
  adminBusy.value = true
  try {
    const out = await commonsApi.strike(s.id, id, strikeReason.value.trim())
    if (out.kind === 'ok') {
      ui.showSuccess(t('commons.admin.struck', 'Submission struck'), tp('commons.admin.struckMsg', '#{id} no longer counts.', { id }))
      strikeId.value = null
      await loadSeason(s.id)
    } else {
      ui.showWarning(t('commons.admin.refused', 'Not done'), adminRefusalWord(out.error, out.message))
    }
  } catch (e: any) {
    ui.showError(t('commons.admin.failed', 'The action failed'), e?.message || '')
  } finally {
    adminBusy.value = false
  }
}

function openWriteOff(id: number) { writeOffId.value = id; writeOffReason.value = '' }

async function doWriteOff(awardId: number) {
  const s = season.value
  if (!s || adminBusy.value) return
  adminBusy.value = true
  try {
    const out = await commonsApi.writeOff(s.id, awardId, writeOffReason.value.trim())
    if (out.kind === 'ok') {
      ui.showSuccess(t('commons.admin.writtenOff', 'Award written off'),
        tp('commons.admin.writtenOffMsg', 'Awards still unpaid: {left}. If the award is owed, pay it by hand through the treasury.', { left: out.data.unpaid_awards ?? 0 }))
      writeOffId.value = null
      await loadList()
    } else {
      ui.showWarning(t('commons.admin.refused', 'Not done'), adminRefusalWord(out.error, out.message))
    }
  } catch (e: any) {
    ui.showError(t('commons.admin.failed', 'The action failed'), e?.message || '')
  } finally {
    adminBusy.value = false
  }
}

function adminRefusalWord(code: string, server: string): string {
  const words: Record<string, string> = {
    payment_started: t('commons.refusal.payment_started', 'Payment of this season has started, so its tally is fixed.'),
    award_not_failed: t('commons.refusal.award_not_failed', 'Only a payment that failed or never answered is written off.'),
    season_live: t('commons.refusal.season_live', 'A season is still open or waiting for payment; settle it first.'),
    empty_budget: t('commons.refusal.empty_budget', 'The fee collector holds nothing and no seed was given: a season without a budget pays nobody.'),
    fee_collector_unreadable: t('commons.refusal.fee_collector_unreadable', "The ledger did not report the fee collector's balance; try again, or open with a seed."),
  }
  return words[code] || server || code
}

async function onAdmin(act: CommonsAdminAct) {
  if (adminBusy.value) return
  adminBusy.value = true
  try {
    const s = season.value
    const out = act.kind === 'open' ? await commonsApi.open(act.body)
      : act.kind === 'close' && s ? await commonsApi.close(s.id)
      : act.kind === 'pay' && s ? await commonsApi.pay(s.id)
      : act.kind === 'cancel' && s ? await commonsApi.cancel(s.id, act.reason)
      : null
    if (!out) return
    if (out.kind === 'refused') {
      ui.showWarning(t('commons.admin.refused', 'Not done'), adminRefusalWord(out.error, out.message))
      return
    }
    if (act.kind === 'pay') {
      const d = out.data as { payments?: Array<{ status: string }>; unpaid_awards?: number; needs_decision?: unknown[] }
      const failed = (d.payments || []).filter((p) => p.status === 'failed').length
      const decide = (d.needs_decision || []).length
      if (decide) ui.showWarning(t('commons.admin.needsDecision', 'Some awards need a decision'),
        tp('commons.admin.needsDecisionMsg', "Awards past the 23-hour window: {n}. A payment run will not send them again, because a second send could pay twice. Check the recipient's ledger rows, then write each one off (and pay it by hand through the treasury if it is owed).", { n: decide }))
      else if (failed || d.unpaid_awards) ui.showWarning(t('commons.admin.payPartly', 'Some awards were not paid'),
        tp('commons.admin.payPartlyMsg', 'Payments failed: {failed}. Awards still unpaid: {left}. Paying again pays only those.', { failed, left: d.unpaid_awards ?? 0 }))
      else ui.showSuccess(t('commons.admin.paid', 'Awards paid'), tp('commons.admin.paidMsg', 'Recipients paid: {n}.', { n: (d.payments || []).length }))
    } else {
      ui.showSuccess(t('commons.admin.done', 'Done'), ({
        open: t('commons.admin.opened', 'The season is open.'),
        close: t('commons.admin.closed', 'The season is closed and its tally fixed.'),
        cancel: t('commons.admin.cancelled', 'The season is cancelled.'),
      } as Record<string, string>)[act.kind] || '')
    }
    if (act.kind === 'open') selectedId.value = null
    await loadList()
  } catch (e: any) {
    ui.showError(t('commons.admin.failed', 'The action failed'), e?.message || '')
  } finally {
    adminBusy.value = false
  }
}
</script>

<style scoped>
.cmn { display: flex; flex-direction: column; gap: 0.8rem; }
.cmn-head { display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; align-items: flex-start; }
.cmn-title { display: inline-flex; align-items: center; gap: 0.4rem; margin: 0; font-size: 1.05rem; font-weight: 800; }
.cmn-title :deep(svg) { width: 1.15rem; height: 1.15rem; }
.cmn-lead { margin: 0.25rem 0 0; font-size: 0.82rem; line-height: 1.5; opacity: 0.85; max-width: 60ch; }
.cmn-pick { display: flex; flex-direction: column; gap: 0.2rem; min-width: 12rem; }
.cmn-pick__select { font-size: 0.8rem; }
.cmn-muted { margin: 0; font-size: 0.76rem; opacity: 0.8; line-height: 1.45; }
.cmn-season, .cmn-result, .cmn-ballot, .cmn-sub { background: rgba(255,255,255,0.02); border: 1px solid rgba(var(--nc-primary-rgb, 0,212,255), 0.14); border-radius: 10px; }
.cmn-season { padding: 0.9rem 1rem; display: flex; flex-direction: column; gap: 0.45rem; }
.cmn-season__top { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; }
.cmn-season__title { margin: 0; font-size: 0.95rem; font-weight: 700; overflow-wrap: anywhere; }
.cmn-season__when { margin: 0; font-size: 0.8rem; }
.cmn-chip { font-size: 0.68rem; font-weight: 700; padding: 0.15rem 0.5rem; border-radius: 999px; border: 1px solid currentColor; }
.cmn-chip--open { color: rgb(74,222,128); }
.cmn-chip--ended, .cmn-chip--closed { color: rgb(251,191,36); }
.cmn-chip--paid { color: var(--nc-primary, #00d4ff); }
.cmn-chip--cancelled { color: rgb(248,113,113); }
.cmn-budget__value { font-size: 1.4rem; font-weight: 800; font-variant-numeric: tabular-nums; color: var(--nc-primary, #00d4ff); }
.cmn-unit { font-size: 0.8rem; font-weight: 600; opacity: 0.85; }
.cmn-rules { margin: 0; padding-left: 1.1rem; font-size: 0.76rem; line-height: 1.5; opacity: 0.9; }
.cmn-result { display: flex; gap: 0.5rem; align-items: flex-start; padding: 0.6rem 0.8rem; font-size: 0.8rem; }
.cmn-result :deep(svg) { width: 1rem; height: 1rem; flex: 0 0 auto; color: rgb(74,222,128); margin-top: 0.1rem; }
.cmn-note { display: flex; gap: 0.4rem; align-items: flex-start; margin: 0; font-size: 0.8rem; }
.cmn-note :deep(svg) { width: 1rem; height: 1rem; flex: 0 0 auto; color: rgb(251,191,36); margin-top: 0.1rem; }
.cmn-list-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
.cmn-h4 { margin: 0; font-size: 0.85rem; font-weight: 700; }
.cmn-submit-btn :deep(svg) { width: 0.9rem; height: 0.9rem; }
.cmn-subs { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.cmn-sub { padding: 0.7rem 0.85rem; display: flex; flex-direction: column; gap: 0.3rem; }
.cmn-sub--struck { opacity: 0.7; }
.cmn-sub--mine { border-color: rgba(var(--nc-primary-rgb, 0,212,255), 0.35); }
.cmn-sub__top { display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; }
.cmn-sub__title { font-weight: 700; font-size: 0.86rem; overflow-wrap: anywhere; }
.cmn-kind, .cmn-tag { font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.1rem 0.4rem; border-radius: 4px; background: rgba(255,255,255,0.06); }
.cmn-tag { background: rgba(var(--nc-primary-rgb, 0,212,255), 0.15); }
.cmn-sub__desc summary { cursor: pointer; font-size: 0.76rem; opacity: 0.85; }
.cmn-sub__desc p { margin: 0.3rem 0 0; font-size: 0.8rem; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }
.cmn-evidence { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.15rem; font-size: 0.78rem; overflow-wrap: anywhere; }
.cmn-link { color: inherit; text-decoration: underline; text-underline-offset: 2px; }
.cmn-struck { margin: 0; font-size: 0.78rem; color: rgb(248,113,113); }
.cmn-award { margin: 0; font-size: 0.8rem; font-variant-numeric: tabular-nums; }
.cmn-award--paid { color: rgb(74,222,128); }
.cmn-award--partial, .cmn-award--pending { color: rgb(251,191,36); }
.cmn-award--failed { color: rgb(248,113,113); }
.cmn-points { display: flex; align-items: center; gap: 0.35rem; margin-top: 0.2rem; }
.cmn-points__input { width: 4.5rem; text-align: center; font-variant-numeric: tabular-nums; font-size: 16px; }
.cmn-step { min-width: 2.25rem; min-height: 2.25rem; padding: 0 0.5rem; font-size: 1rem; }
.cmn-strike { margin-top: 0.2rem; }
.cmn-strike__open :deep(svg) { width: 0.85rem; height: 0.85rem; }
.cmn-strike__form { display: flex; gap: 0.4rem; flex-wrap: wrap; }
.cmn-strike__form .tp-input { flex: 1 1 14rem; min-width: 0; }
.cmn-ballot { position: sticky; bottom: 0.5rem; display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; padding: 0.6rem 0.85rem; background: rgba(10,14,24,0.96); }
.cmn-ballot__left { font-weight: 700; font-variant-numeric: tabular-nums; font-size: 0.85rem; }
.cmn-ballots summary { cursor: pointer; font-size: 0.8rem; font-weight: 700; }
.cmn-ballots ul { list-style: none; margin: 0.4rem 0 0; padding: 0; display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.76rem; }
.cmn-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.cmn-alloc { margin-left: 0.5rem; font-variant-numeric: tabular-nums; }
</style>
