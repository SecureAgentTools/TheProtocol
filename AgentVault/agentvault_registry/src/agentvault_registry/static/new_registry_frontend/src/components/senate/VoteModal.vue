<template>
  <Teleport to="body">
    <div v-if="show && proposal" class="tp-overlay" @click.self="$emit('update:show', false)">
      <div ref="panelRef" class="tp-modal" role="dialog" aria-modal="true" :aria-labelledby="titleId">

        <div class="tp-modal-header">
          <span :id="titleId" class="tp-modal-title"><Icon name="mdi:vote" /> {{ t('senateView.proposalVote.title', 'Cast Vote') }}</span>
          <button type="button" class="tp-modal-close" :aria-label="t('common.close', 'Close')" @click="$emit('update:show', false)">✕</button>
        </div>

        <div class="tp-modal-body">

          <!-- Proposal summary -->
          <div class="sn-proposal-summary">
            <div class="sn-proposal-summary__title">{{ proposal.title }}</div>
            <div class="sn-proposal-summary__meta">
              <span :class="['sn-type-pill', proposal.proposalType === 'policy_change' ? 'sn-type-pill--policy' : 'sn-type-pill--standard']">
                {{ proposal.proposalType === 'policy_change' ? t('senateView.governance.policyChange', 'Policy Change') : t('senateView.governance.standard', 'Standard') }}
              </span>
              <span class="sn-proposal-summary__end">{{ tp('senateView.proposalVote.ends', 'Ends {when}', { when: timeAgo(proposal.votingEnd || proposal.endTime) }) }}</span>
            </div>
          </div>

          <!-- Voting power -->
          <div class="sn-power-box">
            <!-- §MEMBERSHIP: in member mode a vote is one per member, weighted by tenure; no lock is involved -->
            <template v-if="memberMode">
              <div class="sn-power-box__label">{{ t('membership.voteModal.powerLabel', 'Your vote weight') }}</div>
              <div class="sn-power-box__value" data-testid="vote-modal-weight">{{ memberWeight }}</div>
              <div class="sn-power-box__hint">{{ t('membership.voteModal.powerHint', 'One vote per member, weighted by how long you have been a member.') }}</div>
            </template>
            <template v-else>
            <div class="sn-power-box__label">{{ t('senateView.proposalVote.powerLabel', 'Your Voting Power') }}</div>
            <div class="sn-power-box__value">{{ votingPower }} <span style="font-size:0.75rem;font-weight:400;opacity:0.7">{{ t('senateView.proposalVote.powerUnit', 'vote power') }}</span></div>
            <div class="sn-power-box__hint">{{ t('senateView.proposalVote.powerHint', 'Time-weighted quadratic from your lock positions') }}</div>
            </template>
          </div>

          <!-- Vote choice tiles -->
          <div class="tp-field">
            <label class="tp-label">{{ t('senateView.proposalVote.yourVote', 'Your Vote') }}</label>
            <div class="tp-vote-grid">
              <!-- §FESUITE: buttons, so a keyboard can vote -->
              <button
                type="button"
                :class="['tp-vote-tile tp-vote-tile--for', choice === 'for' && 'tp-vote-tile--active']"
                :aria-pressed="choice === 'for'"
                @click="choice = 'for'"
              >
                <div class="tp-vote-tile__icon"><Icon name="mdi:check-circle" /></div>
                <div class="tp-vote-tile__label">{{ t('senateView.governance.for', 'For') }}</div>
              </button>
              <button
                type="button"
                :class="['tp-vote-tile tp-vote-tile--against', choice === 'against' && 'tp-vote-tile--active']"
                :aria-pressed="choice === 'against'"
                @click="choice = 'against'"
              >
                <div class="tp-vote-tile__icon"><Icon name="mdi:close-circle" /></div>
                <div class="tp-vote-tile__label">{{ t('senateView.governance.against', 'Against') }}</div>
              </button>
            </div>
          </div>

          <!-- Reason (optional) -->
          <div class="tp-field" style="margin-bottom:0">
            <label class="tp-label">{{ t('senateView.proposalVote.reason', 'Reason') }} <span style="color:#7b91b2;font-weight:400;text-transform:none;letter-spacing:0">{{ t('senateView.proposalVote.optional', '(optional)') }}</span></label>
            <textarea v-model="reason" class="tp-textarea" rows="3" :placeholder="t('senateView.proposalVote.reasonPh', 'Explain your vote…')"></textarea>
          </div>

        </div>

        <div class="tp-modal-footer">
          <button class="tp-btn tp-btn--ghost" @click="$emit('update:show', false)">{{ t('common.cancel', 'Cancel') }}</button>
          <button
            class="tp-btn"
            :class="choice === 'for' ? 'tp-btn--success' : 'tp-btn--danger'"
            :disabled="!choice || loading"
            @click="submit"
          >
            <span v-if="loading"><span class="tp-spinner"></span> {{ t('senateView.proposalVote.submitting', 'Submitting…') }}</span>
            <!-- §FESUITE: the no-emoji rule; a screen reader read "check mark button For" -->
            <span v-else>{{ choice === 'for' ? t('senateView.proposalVote.submitFor', 'Submit For') : choice === 'against' ? t('senateView.proposalVote.submitAgainst', 'Submit Against') : t('senateView.proposalVote.submitVote', 'Submit Vote') }}</span>
          </button>
        </div>

      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import Icon from '@/components/Icon.vue'
import { ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
dayjs.extend(relativeTime)

const props = defineProps<{
  show: boolean
  loading: boolean
  votingPower: string | number
  proposal: { title: string; proposalType?: string; votingEnd?: string; endTime?: string } | null
  /** §MEMBERSHIP — the registry runs member mode: show the member's weight instead of the lock power */
  memberMode?: boolean
  memberWeight?: string
}>()

const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  (e: 'vote', choice: 'for' | 'against', reason: string): void
}>()

// §COCKPITDESK (2026-10-15): a dialog says it is one (role, aria-modal, its title as its name) and Escape closes it
// wherever the focus is, never while it submits (agentvault2-5b's scoped run of 99 on V0616: Create a proposal
// opened as no dialog at all)
const panelRef = ref<HTMLElement | null>(null)
const titleId = `sn-dlg-${Math.random().toString(36).slice(2, 10)}`
useEscapeClose(() => !!(props.show && props.proposal), () => emit('update:show', false), () => !props.loading, () => panelRef.value)

const { t, tp } = useI18n()

const choice = ref<'for' | 'against' | ''>('')
const reason = ref('')

function timeAgo(d?: string) {
  if (!d) return '—'
  return dayjs(d).fromNow()
}

function submit() {
  if (!choice.value || props.loading) return
  emit('vote', choice.value, reason.value)
}

watch(() => props.show, (v) => {
  if (v) { choice.value = ''; reason.value = '' }
})
</script>

<style scoped>
.sn-proposal-summary {
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(var(--nc-primary-rgb),0.1);
  border-radius: 8px; padding: 0.85rem 1rem;
  margin-bottom: 1rem;
}
.sn-proposal-summary__title {
  font-size: 0.9rem; font-weight: 600; color: #e2e8f0;
  margin-bottom: 0.5rem; line-height: 1.4;
}
.sn-proposal-summary__meta { display: flex; align-items: center; gap: 0.75rem; }
.sn-proposal-summary__end  { font-size: 0.75rem; color: #7b91b2; }

.sn-type-pill {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem; font-weight: 600;
  letter-spacing: 0.07em; text-transform: uppercase;
  padding: 0.15rem 0.5rem; border-radius: 9999px;
}
.sn-type-pill--standard { background: rgba(var(--nc-primary-rgb),0.1); color: rgb(0,210,210); }
.sn-type-pill--policy   { background: rgba(167,139,250,0.12); color: rgb(167,139,250); }

.sn-power-box {
  background: rgba(var(--nc-primary-rgb),0.06);
  border: 1px solid rgba(var(--nc-primary-rgb),0.15);
  border-radius: 8px; padding: 0.85rem 1rem;
  margin-bottom: 1rem;
  display: flex; flex-direction: column; align-items: center;
  text-align: center;
}
.sn-power-box__label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.1em;
  color: #7b91b2; margin-bottom: 0.35rem;
}
.sn-power-box__value {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.6rem; font-weight: 700; color: rgb(0,210,210);
  margin-bottom: 0.2rem;
}
.sn-power-box__hint { font-size: 0.72rem; color: #7b91b2; }
</style>
