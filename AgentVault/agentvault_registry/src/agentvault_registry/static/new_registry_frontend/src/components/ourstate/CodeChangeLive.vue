<!--
  V0666 D3 (order gwo_542285271416c653ca39af3f): a code distribution's change, live in its organization's room. The record is the card's
  (code.change.live, built and kept current by the registry's code changes rail: its state, the line and its organization, the signed
  checker, the reviews, the line's own ballot). What THIS reader may do is the reader's own, read from the change itself
  (GET /code-changes/{id}: line_ballot.my_vote, line_ballot.i_decide, reader_may_review), never from the card everyone sees, and read
  again whenever the card moves. A decider votes from here through the selected agent (D1's vote route, gov.vote), confirmed because a
  vote is never changed; another developer of the organization reviews the accepted commit from here (the main line's review route).
  The registry decides every step again; its refusal sentence is shown where it was asked. Nothing here moves value.
  Mounted by OurStateCard, the chat's card component, for this one card type: unlike the other cards, its two acts are D1's own routes,
  not the thread's, so they live here rather than as intents the thread would have to know.
-->
<template>
  <div class="ccl" data-testid="osc-cc-live" :data-state="view.state">
    <div class="osc-head ccl-head">
      <span class="ccl-kind">{{ t('contributions.card.kind', 'Code change') }}</span>
      <span class="ccl-state" :data-state="view.state" data-testid="osc-cc-state">{{ stateText }}</span>
      <span v-if="view.sensitive" class="ccl-state warn">{{ t('codeChanges.sensitive', 'Sensitive path') }}</span>
    </div>
    <div class="ccl-title">{{ view.title }}</div>
    <div class="ccl-line" data-testid="osc-cc-line"><code>{{ view.line.releaseName }}</code><template v-if="view.line.organizationName"> · {{ view.line.organizationName }}</template></div>
    <p v-if="view.line.paused" class="ccl-small ccl-warn" data-testid="osc-cc-paused">{{ t('contributions.card.paused', 'The line is paused: no vote, ballot or merge until it resumes.') }}</p>
    <p class="ccl-small" :data-checker="view.checker.state" data-testid="osc-cc-checker">{{ checkerText }}</p>
    <p class="ccl-small" data-testid="osc-cc-reviews">{{ reviewsText }}</p>
    <p v-if="ballotText" class="ccl-small" data-testid="osc-cc-ballot">{{ ballotText }}</p>

    <template v-if="reader">
      <p v-if="myVote !== null" class="ccl-small ccl-ok" data-testid="osc-cc-voted">{{ myVote ? t('contributions.vote.castFor', 'Your vote for this change is in. A vote is never changed.') : t('contributions.vote.castAgainst', 'Your vote against this change is in. A vote is never changed.') }}</p>
      <div v-else-if="canVote" class="ccl-act" data-testid="osc-cc-vote">
        <p v-if="!agentDid" class="ccl-small" data-testid="osc-cc-vote-agent">{{ t('contributions.vote.needAgent', 'Choose one of your agents first: the vote goes through an agent, as on the main line.') }}</p>
        <template v-else-if="confirming !== null">
          <p class="ccl-small" data-testid="osc-cc-vote-confirm-text">{{ confirming ? t('contributions.vote.confirmFor', 'Vote for this change? A vote is never changed.') : t('contributions.vote.confirmAgainst', 'Vote against this change? A vote is never changed.') }}</p>
          <div class="ccl-row">
            <button type="button" class="ccl-btn primary" :disabled="busy" data-testid="osc-cc-vote-confirm" @click="vote(confirming)">{{ t('contributions.vote.confirm', 'Cast the vote') }}</button>
            <button type="button" class="ccl-btn" :disabled="busy" @click="confirming = null">{{ t('contributions.form.cancel', 'Cancel') }}</button>
          </div>
        </template>
        <div v-else class="ccl-row">
          <button type="button" class="ccl-btn" data-testid="osc-cc-vote-for" @click="confirming = true">{{ t('contributions.vote.for', 'Vote for') }}</button>
          <button type="button" class="ccl-btn" data-testid="osc-cc-vote-against" @click="confirming = false">{{ t('contributions.vote.against', 'Vote against') }}</button>
        </div>
      </div>

      <p v-if="reviewed" class="ccl-small ccl-ok" data-testid="osc-cc-reviewed">{{ t('contributions.card.reviewed', 'Your review is in.') }}</p>
      <div v-else-if="canReview" class="ccl-act">
        <button v-if="!reviewing" type="button" class="ccl-btn" data-testid="osc-cc-review-open" @click="reviewing = true">{{ t('contributions.card.review', 'Review this commit') }}</button>
        <template v-else>
          <label class="ccl-field"><span>{{ t('contributions.card.findings', 'What you read and found') }}</span>
            <textarea v-model="findings" rows="3" maxlength="4000" data-testid="osc-cc-review-findings"></textarea></label>
          <div class="ccl-row">
            <button type="button" class="ccl-btn primary" :disabled="busy" data-testid="osc-cc-review-approve" @click="review('approve')">{{ t('contributions.card.approve', 'Approve') }}</button>
            <button type="button" class="ccl-btn" :disabled="busy" data-testid="osc-cc-review-changes" @click="review('changes')">{{ t('contributions.card.askChanges', 'Ask for changes') }}</button>
            <button type="button" class="ccl-btn" :disabled="busy" @click="reviewing = false">{{ t('contributions.form.cancel', 'Cancel') }}</button>
          </div>
        </template>
      </div>
    </template>
    <p v-if="refusal" class="ccl-small ccl-refusal" role="alert" data-testid="osc-cc-refusal">{{ refusal }}</p>
    <RouterLink :to="{ name: 'code-change', params: { id: view.changeId } }" class="ccl-open" data-testid="osc-cc-open">{{ t('contributions.card.open', 'Open the change') }}</RouterLink>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { getChange, refusalWords, reviewChange, type ChangeRecord } from '@/services/api/codeChanges'
import { voteLineChange } from '@/services/api/codeDistributions'
import { stateWord } from '@/services/codeChanges/codeChangeView'
import { useTr } from '@/services/codeChanges/tr'
import { lineStateWord } from '@/services/codeDistributions/lines'

type LiveView = {
  changeId: string; title: string; state: string; sensitive: boolean
  line: { slug: string; title: string; releaseName: string; organizationName: string; paused: boolean }
  checker: { state: 'none' | 'ok' | 'failed'; reasons: string[] }
  reviews: { count: number; approvals: number; needed: number; blockers: number }
  ballot: { votes: number; deciders: number; ends: string | null; result: string | null; sentence: string | null; note: string | null }
}
const props = withDefaults(defineProps<{ view: LiveView; rev?: number }>(), { rev: 0 })
const { t, tp } = useI18n()
const tr = useTr()
const auth = useAuthStore() as any

const reader = ref<ChangeRecord | null>(null)
const confirming = ref<boolean | null>(null)
const busy = ref(false)
const refusal = ref('')
const reviewing = ref(false)
const reviewed = ref(false)
const findings = ref('')
const agentDid = computed(() => auth.activeAgent?.did || '')

const stateText = computed(() => lineStateWord(props.view.state, (x) => stateWord(x, tr), tr))
const checkerText = computed(() => {
  const c = props.view.checker
  if (c.state === 'ok') return t('contributions.checker.ok', 'The signed checks passed for this commit.')
  if (c.state === 'failed') return tp('contributions.checker.failed', 'The signed checks did not pass: {reasons}', { reasons: c.reasons.join('; ') || '?' })
  return t('contributions.checker.none', 'Not checked yet: the signed checker reads the commit first.')
})
const reviewsText = computed(() => {
  const r = props.view.reviews
  if (!r.count) return t('contributions.review.none', 'No review yet')
  const base = tp('contributions.review.count', '{a} of {n} approving reviews', { a: r.approvals, n: r.needed })
  return r.blockers ? `${base} · ${t('contributions.review.blocked', 'a reviewer asks for changes')}` : base
})
const ballotText = computed(() => {
  const b = props.view.ballot
  if (b.result) {
    const word = b.result === 'PASSED' ? t('contributions.ballot.passed', 'Passed') : t('contributions.ballot.failed', 'Failed')
    return b.sentence ? `${word}: ${b.sentence}` : word
  }
  if (props.view.state !== 'balloting') return b.note || ''
  if (b.note) return b.note
  const ends = b.ends ? new Date(b.ends) : null
  const when = ends && !Number.isNaN(ends.getTime()) ? ends.toISOString().slice(0, 16).replace('T', ' ') + ' UTC' : '?'
  return tp('contributions.ballot.open', '{v} of {n} deciders voted; it closes at {when}, or once every decider has voted', { v: b.votes, n: b.deciders, when })
})
const lb = computed(() => (reader.value?.line_ballot || {}) as { my_vote?: string | null; i_decide?: boolean })
const myVote = computed<boolean | null>(() => (lb.value.my_vote === 'FOR' ? true : lb.value.my_vote === 'AGAINST' ? false : null))
const canVote = computed(() => props.view.state === 'balloting' && !props.view.line.paused && lb.value.i_decide === true)
const canReview = computed(() => props.view.state === 'accepted' && reader.value?.reader_may_review === true)

async function read() {
  if (!props.view.changeId || !auth.isAuthenticated) { reader.value = null; return }
  try { reader.value = await getChange(props.view.changeId) } catch { reader.value = null }
}
async function vote(v: boolean) {
  busy.value = true; refusal.value = ''
  try { reader.value = await voteLineChange(props.view.changeId, v); confirming.value = null } catch (e) {
    refusal.value = refusalWords(e, t('codeChanges.failed', 'The registry did not take it.')); confirming.value = null
  } finally { busy.value = false }
}
async function review(verdict: 'approve' | 'changes') {
  busy.value = true; refusal.value = ''
  try {
    reader.value = await reviewChange(props.view.changeId, { verdict, commit: String(reader.value?.commit || ''), findings: findings.value.trim() })
    reviewed.value = true; reviewing.value = false
  } catch (e) { refusal.value = refusalWords(e, t('codeChanges.failed', 'The registry did not take it.')) } finally { busy.value = false }
}
onMounted(read)
watch(() => [props.rev, props.view.state], () => { void read() })
</script>

<style scoped>
.ccl { display: grid; gap: .4rem; }
.ccl-head { display: flex; flex-wrap: wrap; gap: .4rem; align-items: center; }
.ccl-kind { font: 700 10px/1 'IBM Plex Mono', monospace; letter-spacing: .08em; text-transform: uppercase; opacity: .7; }
.ccl-state { font: 700 10px/1 'IBM Plex Mono', monospace; letter-spacing: .06em; text-transform: uppercase; border-radius: 999px; padding: 4px 8px;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), .35); color: var(--nc-primary, #00d2d2); }
.ccl-state[data-state='merged'], .ccl-state[data-state='passed'] { color: #34d399; border-color: rgba(16, 185, 129, .45); }
.ccl-state[data-state='failed'], .ccl-state[data-state='vetoed'] { color: #fca5a5; border-color: rgba(248, 113, 113, .45); }
.ccl-state.warn { color: #fcd34d; border-color: rgba(245, 158, 11, .45); }
.ccl-title { font-weight: 500; overflow-wrap: anywhere; }
.ccl-line { font-size: .78rem; opacity: .85; overflow-wrap: anywhere; }
.ccl-line code { font: .74rem 'IBM Plex Mono', monospace; color: var(--nc-primary, #00d2d2); }
.ccl-small { margin: 0; font-size: .78rem; line-height: 1.45; overflow-wrap: anywhere; }
.ccl-small[data-checker='failed'], .ccl-refusal { color: #fca5a5; }
.ccl-small[data-checker='ok'], .ccl-ok { color: #86efac; }
.ccl-warn { color: #fcd34d; }
.ccl-act { display: grid; gap: .4rem; border-top: 1px solid rgba(255,255,255,.08); padding-top: .4rem; }
.ccl-row { display: flex; flex-wrap: wrap; gap: .4rem; }
.ccl-btn { min-height: 40px; padding: 0 14px; border-radius: 8px; border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), .4);
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), .1); color: var(--nc-primary, #00d2d2); font: inherit; font-size: .82rem; cursor: pointer; }
.ccl-btn.primary { background: var(--nc-primary, #00d2d2); color: #04141a; font-weight: 600; border-color: transparent; }
.ccl-btn:disabled { opacity: .5; cursor: not-allowed; }
.ccl-field { display: grid; gap: .25rem; font-size: .78rem; }
.ccl-field span { font: 700 10px/1.2 'IBM Plex Mono', monospace; letter-spacing: .08em; text-transform: uppercase; opacity: .75; }
.ccl-field textarea { border-radius: 8px; border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), .3); background: rgba(0,0,0,.3); color: inherit;
  font: inherit; font-size: .84rem; padding: .45rem .6rem; width: 100%; box-sizing: border-box; }
.ccl-open { justify-self: start; font-size: .8rem; color: var(--nc-primary, #00d2d2); min-height: 32px; display: inline-flex; align-items: center; }
</style>
