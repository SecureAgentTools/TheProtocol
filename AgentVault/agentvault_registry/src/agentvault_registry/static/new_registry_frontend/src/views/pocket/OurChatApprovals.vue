<!-- V0650 (l) — approvals in the chat, pinned above the history.

     The maintainer's words in the sessions' room (2026-10-31): "the approvals should not scroll up with the history ...
     it should stay locked above the chat window. manually approveable each or approve all button." This panel sits
     between the thread's header and its message scroll (outside the scroll), so the history moves underneath and the
     requests stay put. Each request: what is asked, what it unlocks, why, who asks (name and DID tail: agent names
     are not unique), the artifact's sha256, a live countdown, and Approve / Deny; "Approve all" sends exactly the
     requests on screen that have not expired at the moment of the press. A decided request leaves the panel and its
     decision arrives in the thread as a card. A caller who may not decide sees the list without buttons. A failed read
     says so (never an empty list). When the room asks for a phone confirmation the existing step-up dialog opens and
     the same decision is sent again with the approved challenge. Decisions go with the developer token only. -->
<template>
  <section v-if="enabled && (shown.length || readFailed)" class="oca" data-testid="ost-approvals" aria-live="polite">
    <ReadFailedNotice v-if="readFailed" dense :retry="refresh" data-testid="oca-read-failed"
                      :text="t('ourstate.approvals.readFailed', 'Approval requests could not be read just now.')" />
    <template v-else>
      <header class="oca-head">
        <Icon name="mdi:shield-check" />
        <span class="oca-count" data-testid="oca-count">
          {{ tp('ourstate.approvals.waiting', '{n} waiting for a decision', { n: shown.length }) }}</span>
        <button v-if="canDecide && allIds.length >= 2" type="button" class="oca-btn oca-all" data-testid="oca-approve-all"
                :disabled="busyIds.size > 0" @click="approveAll">
          <Icon name="mdi:check" /> {{ tp('ourstate.approvals.approveAll', 'Approve all ({n})', { n: allIds.length }) }}</button>
      </header>
      <p v-if="!canDecide" class="oca-who" data-testid="oca-not-decider">
        {{ t('ourstate.approvals.whoDecides', "The organization's owner or a named approver decides these.") }}</p>
      <ul class="oca-list">
        <li v-for="a in shown" :key="a.id" class="oca-item" :data-testid="`oca-item-${a.id}`"
            :data-expired="isExpired(a, now) ? '1' : '0'">
          <div class="oca-title">{{ a.title }}</div>
          <div v-if="a.unlocks" class="oca-unlocks">
            {{ tp('ourstate.approvals.unlocks', 'Unlocks: {what}', { what: a.unlocks }) }}</div>
          <details v-if="a.reason" class="oca-why">
            <summary>{{ t('ourstate.approvals.why', 'Why') }}</summary>
            <p>{{ a.reason }}</p>
          </details>
          <div class="oca-meta">
            <span class="oca-from">{{ a.requester?.name || '' }} <code>{{ didTail(a.requester?.agent_did) }}</code></span>
            <code v-if="a.artifact_sha256" class="oca-sha" :title="a.artifact_sha256" data-testid="oca-sha">
              {{ a.artifact_label ? `${a.artifact_label} · ` : '' }}{{ shortSha(a.artifact_sha256) }}</code>
            <span v-if="a.production_impact" class="oca-prod" data-testid="oca-prod">
              {{ t('ourstate.approvals.production', 'Affects production') }}</span>
            <span class="oca-left" :data-testid="`oca-left-${a.id}`">
              <Icon name="mdi:clock-outline" /> {{ leftText(a) }}</span>
          </div>
          <div v-if="canDecide" class="oca-actions">
            <button type="button" class="oca-btn oca-approve" :data-testid="`oca-approve-${a.id}`"
                    :disabled="isExpired(a, now) || busyIds.has(a.id)" @click="approve(a.id)">
              <Icon name="mdi:check" /> {{ t('ourstate.approvals.approve', 'Approve') }}</button>
            <button type="button" class="oca-btn oca-deny" :data-testid="`oca-deny-${a.id}`"
                    :disabled="isExpired(a, now) || busyIds.has(a.id)" @click="deny(a.id)">
              <Icon name="mdi:close" /> {{ t('ourstate.approvals.deny', 'Deny') }}</button>
          </div>
        </li>
      </ul>
      <p v-if="lastError" class="oca-error" role="alert" data-testid="oca-error">{{ lastError }}</p>
    </template>
    <StepUpConfirm :show="!!stepUp" :challenge="stepUp?.challenge || null" :busy="busyIds.size > 0"
                   :title="t('ourstate.approvals.confirmTitle', 'Confirm this decision')"
                   :lead="t('ourstate.approvals.confirmLead', 'This room asks for a confirmation on your phone before an approval counts.')"
                   :denied-text="t('ourstate.approvals.confirmDenied', 'You declined on your phone. Nothing was decided.')"
                   :expired-text="t('ourstate.approvals.confirmExpired', 'This confirmation expired. Press Approve again for a new one.')"
                   @update:show="onStepUpShow"
                   @approved="resendWithChallenge" />
  </section>
</template>

<script setup lang="ts">
import { toRef } from 'vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import StepUpConfirm from '@/components/membership/StepUpConfirm.vue'
import { useChatApprovals } from '@/composables/useChatApprovals'
import { didTail, isExpired, leftParts, secondsLeft, shortSha, type ApprovalItem } from '@/services/chat/approvals'
import { useI18n } from '@/composables/useI18n'

const props = withDefaults(defineProps<{
  conversationId: string
  /** The DEVELOPER token: agents never decide. */
  token: string
  /** Org rooms only: approvals live there. */
  enabled?: boolean
}>(), { enabled: true })

const { t, tp } = useI18n()
const {
  shown, allIds, canDecide, readFailed, busyIds, lastError, stepUp, now,
  refresh, approve, deny, approveAll, resendWithChallenge,
} = useChatApprovals(toRef(props, 'conversationId'), toRef(props, 'token'), toRef(props, 'enabled'))

function leftText(a: ApprovalItem): string {
  if (isExpired(a, now.value)) return t('ourstate.approvals.expired', 'expired')
  const s = secondsLeft(a, now.value)
  if (!Number.isFinite(s)) return ''
  const { h, m, s: sec } = leftParts(s)
  if (h > 0) return tp('ourstate.approvals.leftHours', '{h} h {m} min left', { h, m: String(m).padStart(2, '0') })
  if (m > 0) return tp('ourstate.approvals.leftMinutes', '{m} min {s} s left', { m, s: String(sec).padStart(2, '0') })
  return tp('ourstate.approvals.leftSeconds', '{s} s left', { s: sec })
}

function onStepUpShow(v: boolean) { if (!v) stepUp.value = null }

/** The thread calls this when an approval card arrives (a request posted, or one decided elsewhere). */
defineExpose({ refresh })
</script>

<style scoped>
.oca {
  flex: 0 0 auto;
  max-height: min(40vh, 320px);
  overflow-y: auto;
  margin: 0 12px 8px;
  padding: 8px 10px;
  border: 1px solid var(--nc-border, rgba(255, 255, 255, 0.14));
  border-radius: 10px;
  background: var(--nc-surface, rgba(255, 255, 255, 0.04));
}
.oca-head { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.oca-count { flex: 1 1 auto; }
.oca-who { margin: 4px 0 0; font-size: 0.85em; opacity: 0.8; }
.oca-list { list-style: none; margin: 6px 0 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.oca-item { padding: 8px; border-radius: 8px; background: rgba(255, 255, 255, 0.05); }
.oca-item[data-expired='1'] { opacity: 0.55; }
.oca-title { font-weight: 600; overflow-wrap: anywhere; }
.oca-unlocks { font-size: 0.9em; overflow-wrap: anywhere; }
.oca-why summary { cursor: pointer; font-size: 0.85em; }
.oca-why p { margin: 4px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 0.9em; }
.oca-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 4px; font-size: 0.8em; opacity: 0.85; }
.oca-from { overflow-wrap: anywhere; }
.oca-sha { font-variant-numeric: tabular-nums; }
.oca-prod { padding: 1px 6px; border-radius: 6px; background: rgba(255, 170, 0, 0.18); }
.oca-left { font-variant-numeric: tabular-nums; }
.oca-actions { display: flex; gap: 8px; margin-top: 6px; }
.oca-btn {
  min-height: 44px; min-width: 44px; padding: 0 14px; border-radius: 8px; border: 1px solid transparent;
  display: inline-flex; align-items: center; gap: 6px; cursor: pointer; font: inherit;
}
.oca-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.oca-approve, .oca-all { background: var(--nc-success, #1f8f4e); color: #fff; }
.oca-deny { background: transparent; border-color: var(--nc-border, rgba(255, 255, 255, 0.3)); color: inherit; }
.oca-error { margin: 6px 0 0; color: var(--nc-danger, #e5484d); font-size: 0.9em; }
</style>
