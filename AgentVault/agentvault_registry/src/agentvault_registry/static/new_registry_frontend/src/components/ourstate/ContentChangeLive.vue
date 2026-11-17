<!--
  V0667 D5b (order gwo_efd89f2041bfda1eeb7e2cda): an organization's content change, live in its room. The record is the card's (content.change.live, built and kept current by the registry's code changes
  rail: its kind, state, the line and its organization, our checker's verdict, the line's ballot). What THIS reader may do is the reader's own, read from the change itself (GET /content-changes/{id}:
  ballot.can_vote, ballot.my_vote), never from the card everyone sees, and read again whenever the card moves. A decider votes from here through the selected agent (the fast lane's vote route, gov.vote),
  confirmed because a vote is never changed. The registry decides every step again; its refusal sentence is shown where it was asked. Nothing here moves value. Mounted by OurStateCard for this one card type.
-->
<template>
  <div class="ctl" data-testid="osc-ct-live" :data-state="view.state">
    <div class="ctl-head">
      <span class="ctl-kind">{{ t('contentChanges.card.kind', 'Content change') }} · {{ kindWord(view.kind, tr) }}</span>
      <span class="ctl-state" :data-state="view.state" data-testid="osc-ct-state">{{ stateWord(view.state, tr) }}</span>
    </div>
    <div class="ctl-title">{{ view.title }}</div>
    <div class="ctl-line" data-testid="osc-ct-line"><code>{{ view.line.releaseName }}</code><template v-if="view.line.organizationName"> · {{ view.line.organizationName }}</template></div>
    <p v-if="view.line.paused" class="ctl-small ctl-warn" data-testid="osc-ct-paused">{{ t('contentChanges.card.paused', 'The line is paused: no vote and no apply until it resumes.') }}</p>
    <p class="ctl-small" :data-checker="view.checker.state" data-testid="osc-ct-checker">{{ checkerText }}</p>
    <p v-if="ballotText" class="ctl-small" data-testid="osc-ct-ballot">{{ ballotText }}</p>

    <template v-if="reader">
      <p v-if="reader.ballot?.my_vote" class="ctl-small ctl-ok" data-testid="osc-ct-voted">{{ t('contentChanges.voted', 'Your vote is in. A vote is never changed.') }}</p>
      <div v-else-if="canVote" class="ctl-act" data-testid="osc-ct-vote">
        <p v-if="!agentDid" class="ctl-small" data-testid="osc-ct-vote-agent">{{ t('contributions.vote.needAgent', 'Choose one of your agents first: the vote goes through an agent, as on the main line.') }}</p>
        <template v-else-if="confirming !== null">
          <p class="ctl-small">{{ confirming ? t('contentChanges.confirmFor', 'Vote for this change? A vote is never changed.') : t('contentChanges.confirmAgainst', 'Vote against this change? A vote is never changed.') }}</p>
          <div class="ctl-row">
            <button type="button" class="ctl-btn primary" :disabled="busy" data-testid="osc-ct-vote-confirm" @click="vote(confirming)">{{ t('contentChanges.cast', 'Cast the vote') }}</button>
            <button type="button" class="ctl-btn" :disabled="busy" @click="confirming = null">{{ t('contributions.form.cancel', 'Cancel') }}</button>
          </div>
        </template>
        <div v-else class="ctl-row">
          <button type="button" class="ctl-btn" data-testid="osc-ct-vote-for" @click="confirming = true">{{ t('contributions.vote.for', 'Vote for') }}</button>
          <button type="button" class="ctl-btn" data-testid="osc-ct-vote-against" @click="confirming = false">{{ t('contributions.vote.against', 'Vote against') }}</button>
        </div>
      </div>
    </template>
    <p v-if="refusal" class="ctl-small ctl-refusal" role="alert" data-testid="osc-ct-refusal">{{ refusal }}</p>
    <RouterLink :to="{ name: 'contributions', query: { line: view.line.slug } }" class="ctl-open" data-testid="osc-ct-open">{{ t('contentChanges.card.open', 'Open it under Contributions') }}</RouterLink>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { refusalWords } from '@/services/api/codeChanges'
import { getContentChange, voteContentChange, type ContentRecord } from '@/services/api/contentChanges'
import { useTr } from '@/services/codeChanges/tr'
import { kindWord, stateWord } from '@/services/contentChanges/words'

type LiveView = {
  changeId: string; kind: string; title: string; state: string; applied: boolean
  line: { slug: string; title: string; releaseName: string; organizationName: string; paused: boolean }
  checker: { state: 'none' | 'ok'; rules: string[] }
  ballot: { votes: number; deciders: number; ends: string | null; result: string | null; sentence: string | null }
}
const props = withDefaults(defineProps<{ view: LiveView; rev?: number }>(), { rev: 0 })
const { t, tp } = useI18n()
const tr = useTr()
const auth = useAuthStore() as any

const reader = ref<ContentRecord | null>(null)
const confirming = ref<boolean | null>(null)
const busy = ref(false)
const refusal = ref('')
const agentDid = computed(() => auth.activeAgent?.did || '')

const checkerText = computed(() => props.view.checker.state === 'ok'
  ? tp('contentChanges.card.checkerOk', 'Our checker passed it: {rules}.', { rules: props.view.checker.rules.join(', ') || '-' })
  : t('contentChanges.checker.none', 'Not checked.'))
const ballotText = computed(() => {
  const b = props.view.ballot
  if (b.result) {
    const word = b.result === 'PASSED' ? t('contentChanges.ballot.passed', 'Passed') : t('contentChanges.ballot.failed', 'Not passed')
    return b.sentence ? `${word}: ${b.sentence}` : word
  }
  if (props.view.state !== 'balloting') return ''
  const ends = b.ends ? new Date(b.ends) : null
  const when = ends && !Number.isNaN(ends.getTime()) ? ends.toISOString().slice(0, 16).replace('T', ' ') + ' UTC' : '?'
  return tp('contentChanges.card.ballotOpen', '{v} of {n} deciders voted; it closes at {when}, or once every decider has voted', { v: b.votes, n: b.deciders, when })
})
const canVote = computed(() => props.view.state === 'balloting' && !props.view.line.paused && reader.value?.ballot?.can_vote === true)

async function read() {
  if (!props.view.changeId || !auth.isAuthenticated) { reader.value = null; return }
  try { reader.value = await getContentChange(props.view.changeId) } catch { reader.value = null }
}
async function vote(v: boolean) {
  busy.value = true; refusal.value = ''
  try { reader.value = await voteContentChange(props.view.changeId, v); confirming.value = null } catch (e) {
    refusal.value = refusalWords(e, t('codeChanges.failed', 'The registry did not take it.')); confirming.value = null
  } finally { busy.value = false }
}
onMounted(read)
watch(() => [props.rev, props.view.state], () => { void read() })
</script>

<style scoped>
.ctl { display: grid; gap: .4rem; }
.ctl-head { display: flex; flex-wrap: wrap; gap: .4rem; align-items: center; }
.ctl-kind { font: 700 10px/1 'IBM Plex Mono', monospace; letter-spacing: .08em; text-transform: uppercase; opacity: .7; }
.ctl-state { font: 700 10px/1 'IBM Plex Mono', monospace; letter-spacing: .06em; text-transform: uppercase; border-radius: 999px; padding: 4px 8px;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), .35); color: var(--nc-primary, #00d2d2); }
.ctl-state[data-state='applied'] { color: #34d399; border-color: rgba(16, 185, 129, .45); }
.ctl-state[data-state='failed'], .ctl-state[data-state='apply_failed'] { color: #fca5a5; border-color: rgba(248, 113, 113, .45); }
.ctl-title { font-weight: 500; overflow-wrap: anywhere; }
.ctl-line { font-size: .78rem; opacity: .85; overflow-wrap: anywhere; }
.ctl-line code { font: .74rem 'IBM Plex Mono', monospace; color: var(--nc-primary, #00d2d2); }
.ctl-small { margin: 0; font-size: .78rem; line-height: 1.45; overflow-wrap: anywhere; }
.ctl-small[data-checker='ok'], .ctl-ok { color: #86efac; }
.ctl-refusal { color: #fca5a5; }
.ctl-warn { color: #fcd34d; }
.ctl-act { display: grid; gap: .4rem; border-top: 1px solid rgba(255,255,255,.08); padding-top: .4rem; }
.ctl-row { display: flex; flex-wrap: wrap; gap: .4rem; }
.ctl-btn { min-height: 40px; padding: 0 14px; border-radius: 8px; border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), .4);
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), .1); color: var(--nc-primary, #00d2d2); font: inherit; font-size: .82rem; cursor: pointer; }
.ctl-btn.primary { background: var(--nc-primary, #00d2d2); color: #04141a; font-weight: 600; border-color: transparent; }
.ctl-btn:disabled { opacity: .5; cursor: not-allowed; }
.ctl-open { justify-self: start; font-size: .8rem; color: var(--nc-primary, #00d2d2); min-height: 32px; display: inline-flex; align-items: center; }
</style>
