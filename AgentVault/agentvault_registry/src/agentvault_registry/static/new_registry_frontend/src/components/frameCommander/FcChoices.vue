<template>
  <div class="fch" :class="['fch--cols-' + columns, { 'fch--compact': compact }]" role="radiogroup" :aria-label="label">
    <button
      v-for="(o, i) in options"
      :key="o.id"
      ref="buttons"
      type="button"
      role="radio"
      class="fch-choice"
      :class="{ 'is-on': modelValue === o.id }"
      :aria-checked="modelValue === o.id ? 'true' : 'false'"
      :tabindex="modelValue === o.id || (!hasValue && i === 0) ? 0 : -1"
      :data-testid="testid + '-' + o.id"
      @click="choose(i)"
      @keydown="onKey($event, i)"
    >
      <span v-if="o.swatch" class="fch-swatch" :style="{ '--sw': o.swatch }" aria-hidden="true" />
      <Icon v-else-if="o.icon" :name="o.icon" class="fch-icon" />
      <span class="fch-copy">
        <span class="fch-title">
          {{ o.title }}
          <span v-if="o.badge" class="fch-badge">{{ o.badge }}</span>
        </span>
        <span v-if="o.desc" class="fch-desc">{{ o.desc }}</span>
      </span>
      <span class="fch-radio" aria-hidden="true" />
    </button>
  </div>
</template>

<script setup lang="ts">
/**
 * A row of choice cards that behaves as one radio group: a single tab stop, the arrow keys move the choice, Home and
 * End jump to the ends. Used by the frame request for hosting, colour, network intent and posture.
 */
import { computed, nextTick, ref } from 'vue'
import Icon from '@/components/Icon.vue'

interface ChoiceOption {
  id: string
  title: string
  desc?: string
  icon?: string
  swatch?: string
  badge?: string
}

const props = withDefaults(defineProps<{
  modelValue: string
  options: ChoiceOption[]
  label: string
  testid: string
  columns?: number
  compact?: boolean
}>(), { columns: 2, compact: false })

const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>()

const buttons = ref<HTMLButtonElement[]>([])
const hasValue = computed(() => props.options.some(o => o.id === props.modelValue))

function choose(i: number) {
  const o = props.options[i]
  if (o) emit('update:modelValue', o.id)
}

function onKey(event: KeyboardEvent, i: number) {
  const n = props.options.length
  let j = -1
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') j = (i + 1) % n
  else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') j = (i - 1 + n) % n
  else if (event.key === 'Home') j = 0
  else if (event.key === 'End') j = n - 1
  if (j < 0) return
  event.preventDefault()
  choose(j)
  nextTick(() => buttons.value[j]?.focus())
}
</script>

<style scoped>
.fch { display: grid; gap: 10px; }
.fch--cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.fch--cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.fch-choice {
  position: relative; display: flex; align-items: flex-start; gap: 11px;
  padding: 13px 38px 13px 13px; border-radius: 10px; cursor: pointer; text-align: left;
  color: inherit; background: rgba(0, 0, 0, 0.28);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
  transition: border-color 0.18s, background 0.18s, box-shadow 0.18s;
}
.fch--compact .fch-choice { padding: 10px 36px 10px 11px; }
.fch-choice:hover { border-color: rgba(var(--nc-primary-rgb), 0.35); }
.fch-choice:focus-visible { outline: none; box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb), 0.25); }
.fch-choice.is-on {
  border-color: rgba(var(--nc-primary-rgb), 0.6);
  background: linear-gradient(168deg, rgba(var(--nc-primary-rgb), 0.12), rgba(var(--nc-primary-rgb), 0.04));
}
.fch-icon { flex: 0 0 auto; font-size: 20px; margin-top: 1px; color: var(--muted, #7d8594); transition: color 0.18s; }
.fch-choice.is-on .fch-icon { color: var(--nc-primary); }
.fch-swatch {
  flex: 0 0 auto; width: 20px; height: 20px; margin-top: 1px; border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #fff8, rgb(var(--sw)) 55%, rgba(var(--sw), 0.5));
  box-shadow: 0 0 12px rgba(var(--sw), 0.55);
}
.fch-copy { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.fch-title { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; font-size: 13px; font-weight: 600; color: var(--text, #e6e9ef); }
.fch-desc { font-size: 12px; line-height: 1.45; color: var(--muted, #7d8594); }
.fch-badge {
  padding: 1px 6px; border-radius: 4px; font-family: var(--mono, ui-monospace, monospace);
  font-size: 9px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
  color: #f59e0b; background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.3);
}
.fch-radio {
  position: absolute; top: 13px; right: 12px; width: 16px; height: 16px; border-radius: 50%;
  border: 1.5px solid rgba(255, 255, 255, 0.25); transition: border-color 0.18s;
}
.fch--compact .fch-radio { top: 11px; }
.fch-choice.is-on .fch-radio { border-color: var(--nc-primary); }
.fch-choice.is-on .fch-radio::after {
  content: ''; position: absolute; inset: 3px; border-radius: 50%;
  background: var(--nc-primary); box-shadow: 0 0 8px rgba(var(--nc-primary-rgb), 0.8);
}
@media (max-width: 760px) {
  .fch--cols-3 { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 520px) {
  .fch--cols-2 { grid-template-columns: minmax(0, 1fr); }
}
</style>
