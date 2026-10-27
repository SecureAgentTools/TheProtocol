<template>
  <component :is="as" class="fcf" :class="{ 'is-invalid': !!error, 'is-wide': wide }">
    <span class="fcf-label">
      <span class="fcf-label-text">{{ label }}</span>
      <span v-if="required" class="fcf-req" aria-hidden="true">*</span>
      <span v-else-if="optionalText" class="fcf-opt">{{ optionalText }}</span>
      <span v-if="counter" class="fcf-count" :class="{ 'is-over': counter.n > counter.max }">{{ counter.n }}/{{ counter.max }}</span>
    </span>
    <slot />
    <span v-if="error" class="fcf-error" aria-live="polite"><Icon name="mdi:alert-circle-outline" class="fcf-error-icon" />{{ error }}</span>
    <span v-else-if="hint" class="fcf-hint">{{ hint }}</span>
  </component>
</template>

<script setup lang="ts">
/**
 * One form field of the frame request: the label, whether it is required, a character counter, and either the rule
 * it breaks or its hint. The control itself is the slot, so the view keeps its v-model and data-testid.
 */
import Icon from '@/components/Icon.vue'

withDefaults(defineProps<{
  label: string
  required?: boolean
  optionalText?: string
  hint?: string
  error?: string
  counter?: { n: number; max: number } | null
  as?: 'label' | 'div'
  wide?: boolean
}>(), { required: false, optionalText: '', hint: '', error: '', counter: null, as: 'label', wide: false })
</script>

<style scoped>
.fcf { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.fcf.is-wide { grid-column: 1 / -1; }
.fcf-label {
  display: flex; align-items: baseline; gap: 6px;
  font-size: 12px; font-weight: 600; letter-spacing: 0.02em; color: var(--text-secondary, #b8c0cc);
}
.fcf-req { color: var(--nc-primary); font-weight: 700; }
.fcf-opt { font-size: 11px; font-weight: 400; color: var(--muted, #7d8594); }
.fcf-count {
  margin-left: auto; font-family: var(--mono, ui-monospace, monospace); font-size: 10px;
  color: var(--muted, #7d8594); font-variant-numeric: tabular-nums;
}
.fcf-count.is-over { color: #ef4444; }
.fcf-hint { font-size: 12px; line-height: 1.5; color: var(--muted, #7d8594); }
.fcf-error {
  display: flex; align-items: flex-start; gap: 5px;
  font-size: 12px; line-height: 1.45; color: #f87171;
}
.fcf-error-icon { flex: 0 0 auto; font-size: 14px; margin-top: 1px; }
</style>
