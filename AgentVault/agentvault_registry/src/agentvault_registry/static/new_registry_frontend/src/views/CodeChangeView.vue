<!--
  V0664 (order gwo_fc4ec96d3679ca02d5e3afa8): one code change, #/code-changes/:id. Where it stands (the stepper), what it waits for, its problem and paths, the timeline of what
  happened with times and who acted, the checker's signed record (what it read and that this frame verified it), the reviews, the ballot's tally and the veto window, and
  the steps this person may take (review, open the ballot, withdraw). A refusal is the registry's own sentence, where it was asked.
-->
<template>
  <div class="ccv" data-testid="ccv-root">
    <CodeChangesTabs current="code-changes" />
    <RouterLink :to="{ name: 'code-changes' }" class="ccv-back" data-testid="ccv-back">{{ t('codeChanges.back', 'All changes') }}</RouterLink>
    <GovernedElsewhere v-if="authorityView_.readOnly" :view="authorityView_" />

    <div v-if="loading && !rec" class="ccv-skel" data-testid="ccv-loading" role="status" aria-busy="true"><span class="ccv-sr">{{ t('codeChanges.loadingOne', 'Reading the change') }}</span><i></i><i></i><i></i></div>
    <div v-else-if="missing" class="ccv-card ccv-missing" data-testid="ccv-missing">
      <h2>{{ t('codeChanges.missing.title', 'No such code change') }}</h2>
      <p>{{ t('codeChanges.missing.body', 'The address names no change on this registry. It may have been mistyped, or it is on another frame.') }}</p>
      <RouterLink :to="{ name: 'code-changes' }" class="ccv-btn">{{ t('codeChanges.back', 'All changes') }}</RouterLink>
    </div>
    <div v-else-if="error" class="ccv-card ccv-bad" role="alert" data-testid="ccv-error">
      <p>{{ t('codeChanges.oneError', 'The change could not be read; try again.') }}</p>
      <button type="button" class="ccv-btn" data-testid="ccv-retry" @click="load">{{ t('codeChanges.retry', 'Try again') }}</button>
    </div>

    <template v-else-if="rec">
      <header class="ccv-head">
        <div class="ccv-chips">
          <span class="ccv-chip" :data-state="rec.state" data-testid="ccv-state">{{ stateWord(String(rec.state), tr) }}</span>
          <span v-if="rec.sensitive" class="ccv-chip warn" data-testid="ccv-sensitive">{{ t('codeChanges.sensitive', 'Sensitive path') }}</span>
        </div>
        <h1 data-testid="ccv-title">{{ rec.title }}</h1>
        <p class="ccv-sub">
          <span>{{ t('codeChanges.author', 'Proposed by') }} <PersonName :label="labelFor(proposer)" :gone="proposer.gone" testid="ccv-author" /></span>
          <span><time :datetime="rec.created_at">{{ when(rec.created_at) }}</time></span>
          <span><code>{{ rec.repository }}</code></span>
          <span v-if="rec.order_id"><RouterLink :to="{ path: '/guild', query: { order: String(rec.order_id) } }" class="ccv-link" data-testid="ccv-order">{{ t('codeChanges.guildOrder', 'Guild order') }}</RouterLink><template v-if="rec.order_status"> · {{ rec.order_status }}</template></span>
        </p>
      </header>

      <section class="ccv-card" :aria-label="t('codeChanges.way.title', 'How a change goes')"><ChangeStepper :steps="steps" compact /></section>

      <p class="ccv-next" data-testid="ccv-next">{{ nextStep(rec as any, tr) }}</p>
      <p v-if="actionError" class="ccv-error" role="alert" data-testid="ccv-action-error">{{ actionError }}</p>

      <div class="ccv-grid">
        <div class="ccv-col">
          <section class="ccv-card">
            <h2>{{ t('codeChanges.problem', 'The problem') }}</h2>
            <p class="ccv-problem" data-testid="ccv-problem">{{ rec.problem }}</p>
            <h3>{{ t('codeChanges.paths', 'Paths') }}</h3>
            <ul class="ccv-paths" data-testid="ccv-paths">
              <li v-for="p in rec.paths" :key="p" :class="{ sens: isSensitive(p) }"><code :title="p">{{ shortPath(p) }}</code><span v-if="isSensitive(p)" class="ccv-tag">{{ t('codeChanges.sensitiveTag', 'sensitive') }}</span></li>
            </ul>
            <p v-if="rec.sensitive" class="ccv-note" data-testid="ccv-needs">{{ sensitiveNeeds(tr) }}</p>
            <dl class="ccv-facts">
              <template v-if="rec.mode === 'branch'"><dt>{{ t('codeChanges.branchFact', 'Branch') }}</dt><dd><code>{{ rec.branch }}</code></dd></template>
              <template v-if="rec.commit"><dt>{{ t('codeChanges.commit', 'Commit') }}</dt><dd><code data-testid="ccv-commit">{{ rec.commit }}</code></dd></template>
            </dl>
          </section>

          <section class="ccv-card" data-testid="ccv-timeline">
            <h2>{{ t('codeChanges.timeline', 'What happened') }}</h2>
            <ol class="ccv-tl">
              <li v-for="(e, i) in events" :key="i" class="ccv-ev" :class="e.kind" :data-testid="`ccv-ev-${e.key}`">
                <span class="ccv-ev-dot" aria-hidden="true"></span>
                <div class="ccv-ev-main">
                  <b>{{ e.title }}</b><span v-if="e.by" class="ccv-ev-by" :data-testid="`ccv-by-${e.key}`">{{ tp('codeChanges.tl.by', 'by {name}', { name: e.by }) }}</span>
                  <time v-if="e.at" :datetime="e.at" class="ccv-ev-t">{{ when(e.at) }}</time>
                  <pre v-if="e.detail" class="ccv-ev-d">{{ e.detail }}</pre>
                </div>
              </li>
            </ol>
          </section>
        </div>

        <div class="ccv-col">
          <UpstreamPanel :rec="rec" :signed-in="signedIn" :read-only="authorityView_.readOnly" :busy="busy" :error="upstreamError" @propose="proposeUp" />
          <section v-if="rec.acceptance" class="ccv-card" :data-ok="String(!!rec.acceptance.ok)" data-testid="ccv-acceptance">
            <h2>{{ rec.acceptance.ok ? t('codeChanges.checksPassed', 'Checks passed') : t('codeChanges.checksFailed', 'Checks did not pass') }}</h2>
            <ul v-if="rec.acceptance.reasons?.length" class="ccv-reasons">
              <li v-for="r in rec.acceptance.reasons" :key="r" data-testid="ccv-acceptance-reason">{{ r }}</li>
            </ul>
            <dl v-if="rec.acceptance.record" class="ccv-facts" data-testid="ccv-record">
              <dt>{{ t('codeChanges.rec.ci', 'CI on that commit') }}</dt><dd>{{ rec.acceptance.record.ci?.status || '—' }}</dd>
              <dt>{{ t('codeChanges.rec.secrets', 'Secret scan') }}</dt><dd>{{ secretWords(rec.acceptance.record.secret_findings) }}</dd>
              <dt>{{ t('codeChanges.rec.base', 'Read against') }}</dt><dd><code>{{ rec.acceptance.record.base }}</code></dd>
              <dt>{{ t('codeChanges.rec.signed', 'Signed') }}</dt>
              <dd>{{ t('codeChanges.rec.signedBy', 'by the checker') }} <code :title="rec.acceptance.record.checker_kid">{{ rec.acceptance.record.checker_kid }}</code>, <time :datetime="rec.acceptance.record.issued_at">{{ when(rec.acceptance.record.issued_at) }}</time>; {{ t('codeChanges.rec.verified', 'the signature was verified by this frame') }}</dd>
            </dl>
            <h3 v-if="touched.length">{{ tp('codeChanges.rec.touched', 'Files the commit touches ({n})', { n: touched.length }) }}</h3>
            <ul v-if="touched.length" class="ccv-touched" data-testid="ccv-touched">
              <li v-for="x in touched" :key="x.path" :class="{ out: !x.inside }"><Icon :name="x.inside ? 'mdi:check-circle' : 'mdi:close-circle'" /><code :title="x.path">{{ shortPath(x.path) }}</code><span v-if="!x.inside" class="ccv-tag bad">{{ t('codeChanges.rec.outside', 'outside the named paths') }}</span></li>
            </ul>
          </section>

          <section class="ccv-card" data-testid="ccv-reviews">
            <h2>{{ tp('codeChanges.reviewsHead', 'Reviews ({approvals} of {needed} approvals)', { approvals: rec.review_verdict?.approvals ?? 0, needed: rec.reviews_needed ?? (rec.sensitive ? 2 : 1) }) }}</h2>
            <p v-if="!(rec.reviews || []).length" class="ccv-note">{{ t('codeChanges.noReviews', 'No member has reviewed the checked commit yet. The proposer and the worker cannot.') }}</p>
            <ul class="ccv-review-list">
              <li v-for="(r, i) in rec.reviews || []" :key="i" class="ccv-review" data-testid="ccv-review">
                <span class="ccv-verdict" :data-verdict="r.verdict">{{ r.verdict === 'approve' ? t('codeChanges.approve', 'Approve') : t('codeChanges.changes', 'Changes asked') }}</span>
                <span class="ccv-who"><PersonName :label="labelFor(reviewerOf(r))" testid="ccv-reviewer" /></span>
                <span v-if="r.at" class="ccv-ev-t">{{ when(new Date(r.at * 1000).toISOString()) }}</span>
                <span v-if="r.findings" class="ccv-findings">{{ r.findings }}</span>
              </li>
            </ul>
            <p v-if="isProposer && rec.state === 'accepted'" class="ccv-note" data-testid="ccv-own">{{ t('codeChanges.ownChange', 'You proposed this change: other members review it.') }}</p>
            <div v-else-if="!authorityView_.readOnly && canReview(rec as any, signedIn)" class="ccv-review-form" data-testid="ccv-review-form">
              <h3>{{ t('codeChanges.yourReview', 'Your review') }}</h3>
              <label :for="`${uid}-f`" class="ccv-lbl">{{ t('codeChanges.findingsLabel', 'What you read and found') }}</label>
              <textarea :id="`${uid}-f`" v-model="findings" class="ccv-in" rows="3" maxlength="4000" data-testid="ccv-review-findings" />
              <div class="ccv-row">
                <button type="button" class="ccv-btn primary" :disabled="busy" data-testid="ccv-review-approve" @click="review('approve')">{{ t('codeChanges.approve', 'Approve') }}</button>
                <button type="button" class="ccv-btn" :disabled="busy" data-testid="ccv-review-changes" @click="review('changes')">{{ t('codeChanges.askChanges', 'Ask for changes') }}</button>
              </div>
            </div>
          </section>

          <section v-if="rec.proposal_id" class="ccv-card" data-testid="ccv-ballot">
            <h2>{{ t('codeChanges.ballot', 'The members\' ballot') }}</h2>
            <template v-if="tally">
              <div class="ccv-bar" aria-hidden="true"><i :style="{ width: (tally.forShare ?? 0) + '%' }"></i></div>
              <p class="ccv-tally" data-testid="ccv-tally">{{ tally.forShare === null ? t('codeChanges.tally.none', 'No votes yet') : tp('codeChanges.tally.words', '{f} for, {a} against', { f: tally.forVotes, a: tally.against }) }}
                <span class="ccv-note"> · {{ tp('codeChanges.tally.voters', '{n} voted', { n: tally.voters }) }}</span></p>
              <p class="ccv-note" data-testid="ccv-thresholds">{{ tp('codeChanges.tally.title', 'Quorum {q}%, {p}% in favour to pass', { q: tally.quorumPct ?? '?', p: tally.passPct ?? '?' }) }}<template v-if="tally.endsAt && tally.open"> · {{ t('codeChanges.tally.ends', 'closes') }} {{ when(tally.endsAt) }}</template></p>
            </template>
            <p v-if="outcomeLine" class="ccv-note ccv-outcome" data-testid="ccv-outcome" :data-reason="(rec as any).ballot_outcome?.reason">{{ outcomeLine }}<template v-if="outcomeTime">
              {{ tp('codeChanges.outcome.at', 'Tallied {at}.', { at: when(outcomeTime) }) }}</template></p>
            <p v-if="rec.bootstrap" class="ccv-note ccv-bootstrap" data-testid="ccv-bootstrap">{{ tp('codeChanges.bootstrap', 'Passed on the maintainer\'s go: the frame has {n} members, fewer than {t}.', { n: rec.bootstrap.members, t: rec.bootstrap.threshold }) }}
              <template v-if="bootstrapVoters">{{ ' ' + bootstrapVoters }}</template></p>
            <p v-if="rec.veto_window_closes_at && rec.state === 'passed'" class="ccv-note" data-testid="ccv-window">{{ tp('codeChanges.window', 'The maintainer\'s veto window is open until {at}.', { at: when(rec.veto_window_closes_at) }) }}</p>
            <RouterLink :to="{ path: '/senate', query: { proposal: String(rec.proposal_id) } }" class="ccv-link" data-testid="ccv-ballot-link">{{ tp('codeChanges.ballotLink', 'The ballot in the Senate (#{id})', { id: rec.proposal_id }) }}</RouterLink>
          </section>

          <section v-if="mine" class="ccv-card" data-testid="ccv-actions">
            <h2>{{ t('codeChanges.yours', 'Yours to do') }}</h2>
            <button v-if="!authorityView_.readOnly && canOpenBallot(rec as any, actingDid)" type="button" class="ccv-btn primary" :disabled="busy" data-testid="ccv-open-ballot" @click="openTheBallot">{{ t('codeChanges.openBallot', 'Open the members\' ballot') }}</button>
            <div v-if="canWithdraw && !authorityView_.readOnly" class="ccv-withdraw">
              <label :for="`${uid}-w`" class="ccv-lbl">{{ t('codeChanges.withdrawWhy', 'Withdraw this change (a bounty returns to you)') }}</label>
              <input :id="`${uid}-w`" v-model="reason" class="ccv-in" maxlength="400" :placeholder="t('codeChanges.withdrawPh', 'Why (optional)')" data-testid="ccv-withdraw-reason" />
              <button type="button" class="ccv-btn" :disabled="busy" data-testid="ccv-withdraw" @click="withdraw">{{ t('codeChanges.withdraw', 'Withdraw') }}</button>
            </div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import ChangeStepper from '@/components/codeChanges/ChangeStepper.vue'
import CodeChangesTabs from '@/components/codeChanges/CodeChangesTabs.vue'
import GovernedElsewhere from '@/components/codeChanges/GovernedElsewhere.vue'
import { authorityView, useCodeAuthority } from '@/services/codeChanges/authority'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { getBallot, getChange, openBallot, proposeUpstream, refusalWords, reviewChange, withdrawChange, type ChangeRecord } from '@/services/api/codeChanges'
import { canOpenBallot, canReview, nextStep, stateWord } from '@/services/codeChanges/codeChangeView'
import { ballotTally, bootstrapVoters as bootstrapWords, insideDeclared, outcomeAt, outcomeWords, sensitiveNeeds, shortPath, stepper, timeline, type Tally } from '@/services/codeChanges/flow'
import { isSensitive } from '@/services/codeChanges/pathRules'
import { labelOf, proposerOf, reviewerOf, sameNames } from '@/services/codeChanges/people'
import PersonName from '@/components/codeChanges/PersonName.vue'
import UpstreamPanel from '@/components/codeChanges/UpstreamPanel.vue'
import { useTr } from '@/services/codeChanges/tr'

const { t, tp } = useI18n()
const { authority } = useCodeAuthority()      // V0666: where code is not governed the record is read-only: the sentence, and none of the acting controls
const authorityView_ = computed(() => authorityView(authority.value))
const tr = useTr()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore() as any
const uid = `ccv${Math.random().toString(36).slice(2, 8)}`

const rec = ref<ChangeRecord | null>(null)
const tally = ref<Tally | null>(null)
const loading = ref(true)
const missing = ref(false)
const error = ref(false)
const busy = ref(false)
const actionError = ref('')
const upstreamError = ref('')
const findings = ref('')
const reason = ref('')

const signedIn = computed(() => !!auth.isAuthenticated)
const actingDid = computed<string | null>(() => auth.activeAgent?.did || null)
const mine = computed(() => !!rec.value && !!actingDid.value && actingDid.value === rec.value.proposer_did && (canOpenBallot(rec.value as any, actingDid.value) || canWithdraw.value))
const isProposer = computed(() => !!rec.value && !!actingDid.value && actingDid.value === rec.value.proposer_did)
const canWithdraw = computed(() => !!rec.value && !!actingDid.value && actingDid.value === rec.value.proposer_did && ['proposed', 'accepted'].includes(String(rec.value.state)))
const steps = computed(() => (rec.value ? stepper(rec.value, tr) : []))
// V0666: who voted on a ballot the maintainer's go passed (the members' words, no ids)
const bootstrapVoters = computed(() => ((rec.value as any)?.bootstrap ? bootstrapWords((rec.value as any).bootstrap, tr) : undefined))
// the people the page shows (the proposer, each reviewer): a tail only where two of them share a name
const proposer = computed(() => proposerOf(rec.value || {}))
const everyone = computed(() => [proposer.value, ...((rec.value?.reviews || []) as any[]).map(reviewerOf)])
const shared = computed(() => sameNames(everyone.value, tr))
const labelFor = (p: ReturnType<typeof proposerOf>) => labelOf(p, shared.value, tr)
// V0668: why a decided ballot did (not) pass and when it was tallied (the registry's ballot_outcome)
const outcomeLine = computed(() => outcomeWords((rec.value as any)?.ballot_outcome, tr))
const outcomeTime = computed(() => outcomeAt((rec.value as any)?.ballot_outcome))
const events = computed(() => (rec.value ? timeline(rec.value, tr, (p) => { const l = labelFor(p); return l.tail ? `${l.text} ${l.tail}` : l.text }) : []))
const touched = computed(() => (rec.value?.acceptance?.record?.touched || []).map((p: string) => ({ path: p, inside: insideDeclared(p, rec.value!.paths || []) })))
const when = (iso: string): string => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? String(iso || '') : d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC' }
const secretWords = (n: unknown): string => (n === 0 ? t('codeChanges.rec.clean', 'clean') : n === undefined || n === null ? '—' : tp('codeChanges.rec.findings', '{n} finding(s)', { n }))

async function load() {
  const id = String(route.params.id || '')
  loading.value = true; error.value = false; missing.value = false
  try {
    rec.value = await getChange(id)
    tally.value = null
    if (rec.value?.proposal_id) { const p = await getBallot(Number(rec.value.proposal_id)); tally.value = p ? ballotTally(p) : null }
  } catch (e: any) {
    if (e?.response?.status === 404) missing.value = true
    else error.value = true
  } finally {
    loading.value = false
  }
}

// V0667 D4: "propose upstream" on a merged line change; the new change on the main code opens, or the registry's own sentence stays where it was asked
async function proposeUp() {
  if (!rec.value || busy.value) return
  busy.value = true; upstreamError.value = ''
  try {
    const made = await proposeUpstream(String(rec.value.id))
    if (made?.id) router.push({ name: 'code-change', params: { id: String(made.id) } })
  } catch (e: any) {
    upstreamError.value = refusalWords(e, t('upstream.failed', 'It could not be proposed; try again.'))
  } finally {
    busy.value = false
  }
}

async function act(call: () => Promise<ChangeRecord>) {
  busy.value = true; actionError.value = ''
  try {
    rec.value = await call()
    if (rec.value?.proposal_id) { const p = await getBallot(Number(rec.value.proposal_id)); tally.value = p ? ballotTally(p) : tally.value }
  } catch (e) {
    actionError.value = refusalWords(e, t('codeChanges.failed', 'The registry did not take it.'))
  } finally {
    busy.value = false
  }
}
const review = (verdict: 'approve' | 'changes') => act(() => reviewChange(rec.value!.id, { verdict, commit: String(rec.value!.commit), findings: findings.value }))
const openTheBallot = () => act(() => openBallot(rec.value!.id))
const withdraw = () => act(() => withdrawChange(rec.value!.id, reason.value))

onMounted(load)
watch(() => route.params.id, () => { void load() })
</script>

<style scoped>
.ccv { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --bright: #e8eaed; --mono: 'IBM Plex Mono', monospace;
  max-width: 72rem; margin: 0 auto; padding: 1.2rem 1.2rem 3rem; color: var(--bright); display: grid; gap: 1.1rem; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.ccv > * { min-width: 0; }
.ccv-back { justify-self: start; font: 600 .74rem var(--mono); color: var(--cyan); text-decoration: none; }
.ccv-back:hover, .ccv-back:focus-visible { text-decoration: underline; }
.ccv-head { display: grid; gap: .55rem; }
.ccv-head h1 { margin: 0; font-size: 1.8rem; font-weight: 300; letter-spacing: -.01em; overflow-wrap: anywhere; line-height: 1.25; }
.ccv-chips { display: flex; flex-wrap: wrap; gap: .4rem; }
.ccv-chip { font: 700 10px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; border-radius: 999px; padding: 5px 10px; border: 1px solid rgba(var(--cyan-rgb), .3); color: var(--cyan); }
.ccv-chip[data-state='merged'], .ccv-chip[data-state='passed'] { color: #34d399; border-color: rgba(16, 185, 129, .4); }
.ccv-chip[data-state='failed'], .ccv-chip[data-state='vetoed'] { color: #fca5a5; border-color: rgba(248, 113, 113, .4); }
.ccv-chip[data-state='withdrawn'] { color: var(--muted); border-color: rgba(255,255,255,.2); }
.ccv-chip[data-state='balloting'], .ccv-chip.warn { color: #fcd34d; border-color: rgba(245, 158, 11, .4); }
.ccv-sub { margin: 0; display: flex; flex-wrap: wrap; gap: .3rem 1.2rem; font-size: .8rem; color: var(--muted); }
.ccv-sub code, .ccv-facts code, .ccv-paths code, .ccv-touched code { font: .74rem var(--mono); overflow-wrap: anywhere; }
.ccv-card { background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; padding: 1.1rem 1.25rem; display: grid; gap: .7rem; min-width: 0; align-content: start; }
.ccv-card h2 { margin: 0; font-size: 1.02rem; font-weight: 500; }
.ccv-card h3 { margin: .3rem 0 0; font: 700 11px/1.2 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.ccv-card[data-ok='false'] { border-color: rgba(245, 158, 11, .4); }
.ccv-next { margin: 0; font-size: .92rem; line-height: 1.55; padding: .8rem 1rem; border-left: 2px solid var(--cyan); background: rgba(var(--cyan-rgb), .05); border-radius: 0 8px 8px 0; }
.ccv-error { margin: 0; font-size: .85rem; color: #fca5a5; overflow-wrap: anywhere; }
.ccv-note { margin: 0; font-size: .78rem; color: var(--muted); line-height: 1.5; }
.ccv-grid { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr); gap: 1.1rem; align-items: start; }
.ccv-col { display: grid; gap: 1.1rem; min-width: 0; }
.ccv-problem { margin: 0; font-size: .9rem; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; color: #cdd6e0; }
.ccv-paths, .ccv-touched, .ccv-reasons, .ccv-review-list, .ccv-tl { list-style: none; margin: 0; padding: 0; display: grid; gap: .4rem; }
.ccv-paths li, .ccv-touched li { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; }
.ccv-paths li.sens code { color: #fcd34d; }
.ccv-touched li.out code { color: #fca5a5; }
.ccv-touched :deep(svg) { width: .95rem; height: .95rem; flex: none; color: #34d399; }
.ccv-touched li.out :deep(svg) { color: #f87171; }
.ccv-tag { font: 700 9.5px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; color: #fcd34d; border: 1px solid rgba(245, 158, 11, .4); border-radius: 999px; padding: 3px 7px; }
.ccv-tag.bad { color: #fca5a5; border-color: rgba(248, 113, 113, .4); }
.ccv-reasons { padding-left: 1.1rem; list-style: disc; font-size: .82rem; color: #fcd34d; }
.ccv-reasons li { overflow-wrap: anywhere; min-width: 0; }
.ccv-facts { margin: 0; display: grid; grid-template-columns: 8.5rem minmax(0, 1fr); gap: .35rem .8rem; font-size: .8rem; }
.ccv-facts dt { color: var(--muted); } .ccv-facts dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.ccv-tl { gap: 0; border-left: 1px solid rgba(var(--cyan-rgb), .22); margin-left: 6px; }
.ccv-ev { position: relative; padding: 0 0 1rem 1.2rem; }
.ccv-ev:last-child { padding-bottom: 0; }
.ccv-ev-dot { position: absolute; left: -5px; top: 5px; width: 9px; height: 9px; border-radius: 50%; background: var(--cyan); border: 2px solid #070d13; }
.ccv-ev.bad .ccv-ev-dot { background: #f87171; } .ccv-ev.wait .ccv-ev-dot { background: #070d13; border-color: var(--cyan); } .ccv-ev.info .ccv-ev-dot { background: var(--muted); }
.ccv-ev-main { display: grid; gap: .2rem; font-size: .84rem; }
.ccv-ev-t { font: .7rem var(--mono); color: var(--muted); }
.ccv-ev-d { margin: .15rem 0 0; font: .78rem/1.5 inherit; white-space: pre-wrap; overflow-wrap: anywhere; color: #aab4c0; font-family: inherit; }
.ccv-ev.wait b { color: var(--muted); font-weight: 500; }
.ccv-review { display: grid; gap: .2rem; padding-bottom: .5rem; border-bottom: 1px solid rgba(255,255,255,.06); font-size: .8rem; }
.ccv-review:last-child { border-bottom: 0; }
.ccv-verdict { font: 700 10px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; color: #34d399; }
.ccv-verdict[data-verdict='changes'] { color: #fcd34d; }
.ccv-who { color: var(--muted); font-size: .74rem; }
.ccv-ev-by { display: block; color: var(--muted); font-size: .78rem; margin-top: 1px; }
.ccv-findings { color: #cdd6e0; overflow-wrap: anywhere; line-height: 1.5; }
.ccv-review-form, .ccv-withdraw { display: grid; gap: .5rem; border-top: 1px solid rgba(255,255,255,.07); padding-top: .8rem; }
.ccv-lbl { font: 600 .74rem var(--mono); color: #cbd5e1; }
.ccv-in { background: rgba(0,0,0,.35); border: 1px solid rgba(var(--cyan-rgb), .18); border-radius: 7px; padding: 8px 11px; color: var(--bright); font: inherit; font-size: .85rem; width: 100%; min-height: 40px; }
.ccv-in:focus { outline: none; border-color: rgba(var(--cyan-rgb), .5); box-shadow: 0 0 0 3px rgba(var(--cyan-rgb), .12); }
.ccv-row { display: flex; flex-wrap: wrap; gap: .5rem; }
.ccv-btn { display: inline-flex; align-items: center; justify-content: center; min-height: 40px; padding: 0 18px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .12); color: var(--cyan); font: inherit; font-size: .85rem; text-decoration: none; cursor: pointer; }
.ccv-btn.primary { background: var(--cyan); color: #04141a; font-weight: 600; border-color: transparent; }
.ccv-btn:disabled { opacity: .5; cursor: default; }
.ccv-link { color: var(--cyan); font-size: .82rem; }
.ccv-bar { height: 8px; border-radius: 4px; background: rgba(255,255,255,.08); overflow: hidden; }
.ccv-bar i { display: block; height: 100%; background: var(--cyan); }
.ccv-tally { margin: 0; font-size: .9rem; }
.ccv-missing, .ccv-bad { justify-items: start; }
.ccv-bad { border-color: rgba(248, 113, 113, .35); color: #fca5a5; }
.ccv-skel { display: grid; gap: .7rem; } .ccv-skel i { display: block; height: 4rem; border-radius: 12px; border: 1px solid rgba(var(--cyan-rgb), .12); }
.ccv-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
@media (max-width: 900px) { .ccv-grid { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 640px) { .ccv { padding: 1rem .8rem 2.5rem; } .ccv-head h1 { font-size: 1.45rem; } .ccv-card { padding: .95rem; } .ccv-facts { grid-template-columns: 1fr; gap: .1rem; } .ccv-facts dd { margin-bottom: .4rem; } }
</style>
