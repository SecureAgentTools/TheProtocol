<!-- POCKET · Senate sheet — §POCKETBRIDGE #PK17. Governance reaches Pocket for
     the first time: open proposals, FOR/AGAINST as a credentialed agent, and
     the terminal's honesty rules verbatim (reading is public; whether YOU
     voted needs an agent, and the sheet says which it knows). The logic is
     useSenateLane — the SAME brain the desktop terminal runs, second consumer,
     zero copies (#PK16). -->
<template>
  <transition name="pk-sheet">
    <div v-if="open" class="pn-scrim" @click.self="close">
      <div ref="trapEl" class="pn-sheet" role="dialog" aria-modal="true" :aria-label="t('pocket.senate.title', 'Senate')">
        <div class="pn-grip" aria-hidden="true"></div>
        <h2 class="pn-title"><Icon name="mdi:gavel" /> {{ t('pocket.senate.title', 'Senate') }}
          <span v-if="senate.openProposals.value.length" class="pn-count">{{ senate.openProposals.value.length }}</span>
        </h2>

        <label for="pocketsenate-sel-17" class="pn-lab">{{ t('pocket.senate.votingAs', 'Voting as') }}</label>
        <select id="pocketsenate-sel-17" v-if="credAgents.length" v-model="agentDid" class="pn-in" :disabled="senate.busy.value" @change="reload">
          <option v-for="a in credAgents" :key="a.did" :value="a.did">{{ a.name || shorten(a.did) }}</option>
        </select>
        <p v-else class="pn-note pn-warn">{{ noAgentReason }}</p>
        <p v-if="!agentReady && credAgents.length" class="pn-note">
          {{ t('pocket.senate.publicNote', 'Proposals are public, so they are listed. Whether you already voted cannot be known until the agent signs in.') }}
        </p>
        <!-- §MEMBERSHIP: in member mode the vote is the member's, so the sheet says whether you are one -->
        <MembershipPanel v-if="memberMode" compact style="margin: 0.5rem 0" />
        <VotePermissionNotice v-if="memberMode" :did="agentDid" :refused="permissionRefused" style="margin: 0.5rem 0" />

        <div v-if="senate.busy.value && !senate.loaded.value" class="pn-list"><div v-for="n in 3" :key="n" class="pn-skel"></div></div>
        <p v-else-if="senate.loaded.value && !senate.openProposals.value.length" class="pn-empty" data-testid="pn-empty">
          <Icon name="mdi:gavel" /> {{ t('pocket.senate.empty', 'No proposal is open for voting right now.') }}
        </p>
        <ul v-else class="pn-list">
          <li v-for="p in senate.openProposals.value" :key="p.id" class="pn-row" data-testid="pn-proposal">
            <div class="pn-row-body">
              <div class="pn-row-title">{{ p.title }}</div>
              <div v-if="p.description" class="pn-row-sub">{{ String(p.description).slice(0, 140) }}</div>
            </div>
            <span v-if="agentReady && senate.myVoted.value.has(String(p.id))" class="pn-voted" data-testid="pn-voted">
              <Icon name="mdi:check-circle" /> {{ t('pocket.senate.youVoted', 'you voted') }}
            </span>
            <div v-else-if="agentReady" class="pn-votes">
              <button class="pn-btn pn-for" :disabled="senate.busy.value" data-testid="pn-vote-for" @click="cast(p, 'for')">{{ t('pocket.senate.for', 'FOR') }}</button>
              <button class="pn-btn pn-against" :disabled="senate.busy.value" data-testid="pn-vote-against" @click="cast(p, 'against')">{{ t('pocket.senate.against', 'AGAINST') }}</button>
            </div>
          </li>
        </ul>

        <p v-if="msg" class="pn-msg" :class="{ bad: !msgOk }" data-testid="pn-msg">{{ msg }}</p>
        <StepUpConfirm
          v-if="flow.stepUp.value"
          :show="true"
          :challenge="flow.stepUp.value"
          :busy="flow.busy.value || signing"
          :error="flow.stepUpError.value"
          :can-sign-here="device.canSign.value"
          @update:show="(v: boolean) => { if (!v) flow.cancel() }"
          @approved="(id: string) => flow.approved(id)"
          @code="(c: string) => flow.code(c)"
          @sign="signHere"
        />
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useFocusTrap } from '@/composables/useFocusTrap'
import Icon from '@/components/Icon.vue'
import { usePocketAgent } from '@/composables/usePocketAgent'
import { useSenateLane } from '@/composables/useSenateLane'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { useMemberVoteFlow, type SettledOutcome } from '@/composables/useMemberVoteFlow'
import { useThisDeviceApproval } from '@/composables/useThisDeviceApproval'
import { useMembership } from '@/composables/useMembership'
import { governanceMode } from '@/services/membership/membership'
import MembershipPanel from '@/components/membership/MembershipPanel.vue'
import VotePermissionNotice from '@/components/membership/VotePermissionNotice.vue'
import StepUpConfirm from '@/components/membership/StepUpConfirm.vue'

const { t, tp } = useI18n()


// §POCKETBRIDGE5 W-D — the dialog role was already declared; the trap makes it TRUE:
// focus enters on open, Tab cycles inside, and RETURNS to the opener on close.
const trapEl = ref<HTMLElement | null>(null)
const props = defineProps<{ open: boolean }>()
// §MEMBERSHIP: the step-up dialog renders outside the sheet; the trap pauses while it is open, or its code field
// could not take focus
const stepUpOpen = ref(false)
useFocusTrap(trapEl, { activeWhen: computed(() => props.open && !stepUpOpen.value) })
const emit = defineEmits<{ (e: 'close'): void }>()

const { credAgents, noAgentReason, ensureAgentFor } = usePocketAgent()
const senate = useSenateLane()

const agentDid = ref('')
const agentReady = ref(false)
const msg = ref('')
const msgOk = ref(true)
const shorten = (s: string) => !s ? '—' : s.length > 26 ? s.slice(0, 14) + '…' + s.slice(-5) : s

function close() { emit('close') }

const errText = (e: any) =>
  e?.response?.data?.detail || e?.response?.data?.title || e?.message || t('pocket.common.failed', 'failed')

async function reload() {
  msg.value = ''
  agentReady.value = await ensureAgentFor(agentDid.value)
  const r = await senate.load(agentReady.value)
  if (!r.ok) { msg.value = tp('pocket.senate.readFailed', 'Could not read proposals: {err}', { err: String(errText(r.error)).slice(0, 120) }); msgOk.value = false }
}

// §MEMBERSHIP (2026-10-02): where the registry runs member mode, the vote is the member's, one per member, and a
// binding vote may need a step-up: this phone can confirm it in place when it holds an enrolled key.
const { config: registryCfg } = useRegistryConfig()
const memberMode = computed(() => governanceMode(registryCfg.value) === 'member')
const { reload: reloadMembership } = useMembership()
const device = useThisDeviceApproval()
const signing = ref(false)
let lastCast: { title: string; choice: 'for' | 'against' } | null = null
// the agent lacked gov.vote: the notice under the membership panel says so and offers to allow it (no text here)
const permissionRefused = ref(false)

function onSettled(out: SettledOutcome) {
  permissionRefused.value = out.kind === 'needs_permission'
  if (out.kind === 'needs_permission') { msg.value = ''; return }
  if (out.kind === 'cast') {
    const label = lastCast?.choice === 'for' ? t('pocket.senate.for', 'FOR') : t('pocket.senate.against', 'AGAINST')
    msg.value = tp('pocket.senate.voteRecorded', 'Vote recorded — {choice} on “{title}”.', { choice: label, title: String(lastCast?.title || '').slice(0, 60) })
    msgOk.value = true
    try { (navigator as any).vibrate?.(8) } catch {}
  } else if (out.kind === 'not_member') {
    msg.value = t('membership.vote.notMember', 'Only members vote here'); msgOk.value = false
    void reloadMembership()
  } else if (out.kind === 'second_factor_required') {
    msg.value = t('membership.vote.secondFactorMsg', 'This registry needs every binding vote confirmed. Enrol your phone in Pocket or turn on two-factor sign-in in Settings, then vote again.'); msgOk.value = false
  } else if (out.kind === 'already_voted') {
    msg.value = t('membership.vote.alreadyVotedMsg', 'One vote per member: you voted on this proposal through another agent.'); msgOk.value = true
  }
}
const flow = useMemberVoteFlow(onSettled)
watch(() => flow.stepUp.value, (v) => { stepUpOpen.value = !!v; if (v) void device.check() })

async function signHere() {
  const ch = flow.stepUp.value
  if (!ch || signing.value) return
  signing.value = true
  try {
    await device.approve(ch)
    await flow.approved(ch.challengeId)
  } catch (e: any) {
    flow.stepUpError.value = e?.response?.data?.message || e?.message || t('pocket.common.failed', 'failed')
  } finally { signing.value = false }
}

async function cast(p: any, choice: 'for' | 'against') {
  msg.value = ''
  if (!await ensureAgentFor(agentDid.value)) { msg.value = t('pocket.senate.signInFailed', 'Could not sign in as that agent.'); msgOk.value = false; return }
  if (memberMode.value) {
    lastCast = { title: String(p.title || ''), choice }
    try { await flow.start((extra) => senate.voteMember(p, choice, extra)) }
    catch (e) { msg.value = tp('pocket.senate.voteFailed', 'Vote failed: {err}', { err: String(errText(e)).slice(0, 120) }); msgOk.value = false }
    return
  }
  const r = await senate.vote(p, choice)
  if (r.ok) {
    const label = choice === 'for' ? t('pocket.senate.for', 'FOR') : t('pocket.senate.against', 'AGAINST')
    msg.value = tp('pocket.senate.voteRecorded', 'Vote recorded — {choice} on “{title}”.',
                   { choice: label, title: String(p.title).slice(0, 60) })
    msgOk.value = true
    try { (navigator as any).vibrate?.(8) } catch {} }
  else { msg.value = tp('pocket.senate.voteFailed', 'Vote failed: {err}', { err: String(errText(r.error)).slice(0, 120) }); msgOk.value = false }
}

watch(() => props.open, (o) => {
  if (!o) return
  msg.value = ''
  if (!agentDid.value && credAgents.value.length) agentDid.value = credAgents.value[0].did
  void reload()
})
</script>

<style scoped>
.pn-scrim { position: fixed; inset: 0; z-index: 90; background: rgba(0,0,0,0.55); backdrop-filter: blur(3px); display: flex; align-items: flex-end; }
.pn-sheet { width: 100%; max-width: 560px; margin: 0 auto; background: #0c0f15; border: 1px solid rgba(255,255,255,0.09);
  border-radius: 22px 22px 0 0; padding: 0.8rem 1.1rem calc(1.4rem + env(safe-area-inset-bottom, 0px));
  box-shadow: 0 -20px 50px rgba(0,0,0,0.5); max-height: 88dvh; overflow-y: auto; }
.pn-grip { width: 40px; height: 4px; border-radius: 2px; background: rgba(255,255,255,0.18); margin: 0.1rem auto 0.9rem; }
.pn-title { display: flex; align-items: center; gap: 0.45rem; font-size: 1.1rem; margin: 0 0 0.7rem; }
.pn-title :deep(svg) { width: 1.2rem; height: 1.2rem; color: var(--nc-primary, #00d4ff); }
.pn-count { font-size: 0.68rem; font-weight: 700; color: var(--nc-primary, #00d4ff); background: rgba(0,212,255,0.09);
  border: 1px solid rgba(0,212,255,0.24); border-radius: 7px; padding: 0.1rem 0.45rem; }
.pn-lab { display: block; font-size: 0.7rem; letter-spacing: 0.05em; text-transform: uppercase; opacity: 0.5; font-weight: 600; margin: 0.4rem 0 0.3rem; }
.pn-in { width: 100%; box-sizing: border-box; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
  border-radius: 12px; padding: 0.75rem 0.85rem; color: #e6edf3; font-size: 0.92rem; outline: none; min-height: 44px; }
.pn-note { font-size: 0.76rem; opacity: 0.65; margin: 0.5rem 0 0; }
.pn-warn { color: #fbbf24; opacity: 0.9; }
.pn-list { list-style: none; margin: 0.8rem 0 0; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.pn-row { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.07); border-left: 3px solid rgba(0,212,255,0.35); border-radius: 13px; padding: 0.7rem 0.8rem; }
.pn-row-body { flex: 1 1 14rem; min-width: 0; }
.pn-row-title { font-size: 0.88rem; font-weight: 650; }
.pn-row-sub { font-size: 0.74rem; opacity: 0.6; margin-top: 0.15rem; line-height: 1.4; }
.pn-voted { display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.74rem; color: #34d399; font-weight: 600; }
.pn-voted :deep(svg) { width: 0.95rem; height: 0.95rem; }
.pn-votes { display: flex; gap: 0.45rem; }
.pn-btn { min-height: 44px; min-width: 44px; padding: 0.5rem 0.9rem; border-radius: 11px; font-size: 0.78rem; font-weight: 700;
  letter-spacing: 0.05em; cursor: pointer; border: 1px solid transparent; -webkit-tap-highlight-color: transparent; }
.pn-btn:disabled { opacity: 0.45; }
.pn-for { background: rgba(16,185,129,0.14); border-color: rgba(16,185,129,0.4); color: #d1fae5; }
.pn-against { background: rgba(255,107,107,0.1); border-color: rgba(255,107,107,0.35); color: #ffd7d7; }
.pn-empty { display: flex; align-items: center; justify-content: center; gap: 0.45rem; padding: 1.6rem 1rem; opacity: 0.55; font-size: 0.84rem; }
.pn-empty :deep(svg) { width: 1.1rem; height: 1.1rem; }
.pn-msg { text-align: center; font-size: 0.8rem; margin: 0.8rem 0 0; color: #34d399; }
.pn-msg.bad { color: #ff8a8a; }
.pn-skel { height: 3.6rem; border-radius: 13px; background: linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.11), rgba(255,255,255,0.05)); background-size: 200% 100%; animation: pn-shim 1.3s ease-in-out infinite; }
@keyframes pn-shim { to { background-position: -200% 0; } }
.pk-sheet-enter-active, .pk-sheet-leave-active { transition: opacity 0.2s ease; }
.pk-sheet-enter-active .pn-sheet, .pk-sheet-leave-active .pn-sheet { transition: transform 0.24s cubic-bezier(0.34,1.3,0.64,1); }
.pk-sheet-enter-from, .pk-sheet-leave-to { opacity: 0; }
.pk-sheet-enter-from .pn-sheet, .pk-sheet-leave-to .pn-sheet { transform: translateY(100%); }
@media (prefers-reduced-motion: reduce) { .pn-skel { animation: none; } .pk-sheet-enter-active .pn-sheet, .pk-sheet-leave-active .pn-sheet { transition: none; } }
</style>
