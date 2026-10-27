<template>
  <Teleport to="body">
    <div v-if="show" class="tp-overlay" @click.self="$emit('update:show', false)">
      <div ref="panelRef" class="tp-modal tp-modal--lg" role="dialog" aria-modal="true" :aria-labelledby="titleId">

        <div class="tp-modal-header">
          <span :id="titleId" class="tp-modal-title"><Icon name="mdi:scroll-text" /> {{ t('senateView.governance.createProposal', 'Create Proposal') }}</span>
          <button type="button" class="tp-modal-close" :aria-label="t('common.close', 'Close')" @click="$emit('update:show', false)">✕</button>
        </div>

        <div class="tp-modal-body">

          <!-- Title -->
          <div class="tp-field">
            <label class="tp-label">{{ t('senateView.createModal.fieldTitle', 'Proposal Title') }} <span style="color:#ef4444">*</span></label>
            <input v-model="title" class="tp-input" :placeholder="t('senateView.createModal.titlePh', 'Enter a clear, descriptive title')" maxlength="200" />
            <div class="tp-hint" style="text-align:right">{{ title.length }}/200</div>
          </div>

          <!-- Type selector -->
          <div class="tp-field">
            <label class="tp-label">{{ t('senateView.createModal.fieldType', 'Proposal Type') }}</label>
            <div class="tp-type-grid">
              <!-- §FESUITE: buttons, so a keyboard can choose; and no thresholds stated here: the frame's own policy
                   decides them (an amended frame votes with other numbers) and each proposal shows the quorum its
                   tally applies. The "7-day window" contradicted the duration chosen below. -->
              <button
                type="button"
                :class="['tp-type-tile', proposalType === 'standard' && 'tp-type-tile--active']"
                :aria-pressed="proposalType === 'standard'"
                @click="proposalType = 'standard'"
              >
                <div class="tp-type-tile__label"><Icon name="mdi:scale-balance" /> {{ t('senateView.governance.standard', 'Standard') }}</div>
                <div class="tp-type-tile__desc">{{ t('senateView.createModal.standardDesc', "Decided by this frame's quorum and majority") }}</div>
              </button>
              <button
                type="button"
                :class="['tp-type-tile tp-type-tile--policy', proposalType === 'policy_change' && 'tp-type-tile--active']"
                :aria-pressed="proposalType === 'policy_change'"
                @click="proposalType = 'policy_change'"
              >
                <div class="tp-type-tile__label" style="color:#a78bfa"><Icon name="mdi:cog" /> {{ t('senateView.governance.policyChange', 'Policy Change') }}</div>
                <div class="tp-type-tile__desc">{{ t('senateView.createModal.policyDesc', "Changes this frame's rules; needs its supermajority") }}</div>
              </button>
            </div>
          </div>

          <!-- Duration selector -->
          <div class="tp-field">
            <label class="tp-label">{{ t('senateView.createModal.fieldDuration', 'Voting Duration') }}</label>
            <div class="tp-duration-grid">
              <button
                v-for="opt in durationOptions"
                :key="opt.value"
                type="button"
                :class="['tp-duration-tile', duration === opt.value && 'tp-duration-tile--active']"
                :aria-pressed="duration === opt.value"
                @click="duration = opt.value"
              >
                <div class="tp-duration-tile__label">{{ opt.label }}</div>
              </button>
            </div>
          </div>

          <!-- Description -->
          <div class="tp-field">
            <label class="tp-label">{{ t('senateView.createModal.fieldDescription', 'Description') }} <span style="color:#ef4444">*</span></label>
            <textarea
              v-model="description"
              class="tp-textarea"
              rows="5"
              :placeholder="t('senateView.createModal.descriptionPh', 'Provide detailed description and rationale…')"
              style="min-height:110px"
            ></textarea>
          </div>

          <!-- Policy diff (policy_change only) -->
          <div v-if="proposalType === 'policy_change'" class="tp-field">
            <label class="tp-label">{{ t('senateView.createModal.fieldPolicyDiff', 'Policy Diff (JSON)') }} <span style="color:#ef4444">*</span></label>
            <textarea
              v-model="policyDiff"
              class="tp-textarea"
              rows="4"
              placeholder='{"staking.min_lock_days": {"old": 7, "new": 14}}'
              style="font-family:'IBM Plex Mono',monospace;font-size:0.8rem"
            ></textarea>
            <div v-if="policyError" class="tp-hint" style="color:rgb(239,68,68)">{{ policyError }}</div>
            <div v-else class="tp-hint">{{ t('senateView.createModal.policyDiffHint', 'JSON object describing parameter changes') }}</div>
          </div>

          <!-- Info bar -->
          <div class="tp-banner" :class="proposalType === 'policy_change' ? 'tp-banner--warn' : 'tp-banner--info'" style="margin-bottom:0">
            <span v-if="proposalType === 'standard'">
              <Icon name="mdi:scale-balance" /> {{ t('senateView.createModal.bannerStandard', "Standard: decided by this frame's quorum and majority over the duration chosen above. Who may open one is this frame's rule: its members, or agents holding the locked units it sets.") }}
            </span>
            <span v-else>
              <Icon name="mdi:cog" /> {{ t('senateView.createModal.bannerPolicy', "Policy Change: needs this frame's supermajority, a higher threshold; use it for changes to the frame's rules.") }}
            </span>
          </div>

        </div>

        <div class="tp-modal-footer">
          <button class="tp-btn tp-btn--ghost" @click="$emit('update:show', false)">{{ t('common.cancel', 'Cancel') }}</button>
          <button
            class="tp-btn tp-btn--primary"
            :disabled="!canSubmit || loading"
            @click="submit"
          >
            <span v-if="loading"><span class="tp-spinner"></span> {{ t('senateView.createModal.creating', 'Creating…') }}</span>
            <span v-else>{{ t('senateView.governance.createProposal', 'Create Proposal') }}</span>
          </button>
        </div>

      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import Icon from '@/components/Icon.vue'
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()

const props = defineProps<{
  show: boolean
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  (e: 'create', payload: { title: string; description: string; type: string; duration_seconds: number; policy_diff?: any }): void
}>()

// §COCKPITDESK (2026-10-15): a dialog says it is one (role, aria-modal, its title as its name) and Escape closes it
// wherever the focus is, never while it submits (agentvault2-5b's scoped run of 99 on V0616: Create a proposal
// opened as no dialog at all)
const panelRef = ref<HTMLElement | null>(null)
const titleId = `sn-dlg-${Math.random().toString(36).slice(2, 10)}`
useEscapeClose(() => !!props.show, () => emit('update:show', false), () => !props.loading, () => panelRef.value)

const title        = ref('')
const description  = ref('')
const proposalType = ref<'standard' | 'policy_change'>('standard')
const policyDiff   = ref('')
const duration     = ref(604800) // default 7 days

// §FESUITE: the labels follow the console's language (computed, so a language switch re-renders them)
const durationOptions = computed(() => [
  { label: t('senateView.createModal.d1', '1 Day'),    value: 86400 },
  { label: t('senateView.createModal.d3', '3 Days'),   value: 259200 },
  { label: t('senateView.createModal.d7', '7 Days'),   value: 604800 },
  { label: t('senateView.createModal.d14', '14 Days'), value: 1209600 },
  { label: t('senateView.createModal.d30', '30 Days'), value: 2592000 },
])

const policyError = computed(() => {
  if (proposalType.value !== 'policy_change' || !policyDiff.value.trim()) return ''
  try { JSON.parse(policyDiff.value); return '' }
  catch { return t('senateView.createModal.invalidJson', 'Invalid JSON') }
})

const canSubmit = computed(() => {
  if (!title.value.trim() || !description.value.trim()) return false
  if (proposalType.value === 'policy_change') {
    if (!policyDiff.value.trim() || policyError.value) return false
  }
  return true
})

function submit() {
  if (!canSubmit.value || props.loading) return
  const payload: any = {
    title: title.value.trim(),
    description: description.value.trim(),
    type: proposalType.value,
    duration_seconds: duration.value
  }
  if (proposalType.value === 'policy_change' && policyDiff.value.trim()) {
    try { payload.policy_diff = JSON.parse(policyDiff.value) } catch { /* expected */ }
  }
  emit('create', payload)
}

watch(() => props.show, (v) => {
  if (v) {
    title.value = ''
    description.value = ''
    proposalType.value = 'standard'
    policyDiff.value = ''
    duration.value = 604800
  }
})
</script>
