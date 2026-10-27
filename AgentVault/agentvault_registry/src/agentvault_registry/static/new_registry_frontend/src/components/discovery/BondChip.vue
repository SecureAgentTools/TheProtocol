<script setup lang="ts">
/**
 * §REPBOND (2026-09-05) — the bond chip: locked or matured, with the amount the home registry holds.
 *
 * §BATCH0911 item 3 — one component for BOTH discovery densities. The list card never carried the
 * chip (only the grid did), so switching density lost the fact that an agent is bonded at all; a
 * copied span would have been a second copy of the label rule and of its title.
 */
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{
  bond?: Record<string, any> | null
  isBonded?: boolean
  fallbackCurrency?: string
  volume?: number | string | null
}>()

const { t } = useI18n()

const shown = computed(() => !!(props.bond?.is_bonded || props.isBonded))
const matured = computed(() => props.bond?.status === 'matured')

const title = computed(() => {
  const b = props.bond
  if (!b) return t('discoveryView.bond.chipTitle', 'Reputation bond held in escrow by the home registry')
  const parts: string[] = []
  parts.push(b.status === 'matured'
    ? t('discoveryView.bond.matured', 'Bond matured')
    : t('discoveryView.bond.locked', 'Bonded'))
  if (b.amount) parts.push(`${b.amount} ${b.currency || ''}`.trim())
  if (b.progress && typeof b.progress.percent === 'number') parts.push(`${t('discoveryView.bond.maturity', 'maturity')} ${b.progress.percent}%`)
  if (props.volume != null) parts.push(`${t('discoveryView.bond.volume', 'volume')} ${props.volume}`)
  if (b.source === 'card' && b.registry) parts.push(`${t('discoveryView.bond.signedBy', 'signed by')} ${b.registry}`)
  return parts.join(' · ')
})
</script>

<template>
  <span
    v-if="shown"
    class="disc-bond-chip"
    :class="matured ? 'disc-bond-chip--matured' : 'disc-bond-chip--locked'"
    :title="title"
    data-testid="disc-bond-chip"
    :data-bond-status="bond?.status || 'locked'"
  >
    <Icon name="mdi:shield-account" />
    {{ matured ? t('discoveryView.bond.matured', 'Bond matured') : t('discoveryView.bond.locked', 'Bonded') }}
    <small v-if="bond?.amount">{{ bond.amount }} {{ bond.currency || fallbackCurrency }}</small>
  </span>
</template>

<style scoped>
.disc-bond-chip { display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.1rem 0.5rem; border-radius: 999px;
  font-size: 0.7rem; font-weight: 600; letter-spacing: 0.02em; border: 1px solid rgba(var(--nc-primary-rgb), 0.35);
  color: rgb(var(--nc-primary-rgb)); background: rgba(var(--nc-primary-rgb), 0.08); white-space: nowrap; }
.disc-bond-chip small { font-weight: 500; opacity: 0.8; }
.disc-bond-chip--matured { border-color: rgba(52, 211, 153, 0.5); color: #34d399; background: rgba(52, 211, 153, 0.1); }
</style>
