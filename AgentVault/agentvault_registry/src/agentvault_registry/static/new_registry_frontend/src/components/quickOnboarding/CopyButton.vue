<!-- A copy button for one value (quick onboarding, 2026-10-09). It says "Copied" only after utils/copyText resolved
     true, and "Not copied" when the browser refused, so a credential shown once is never taken for saved when it was
     not. The value travels as a prop and never into the DOM: no title, no aria-label carries it (it is often a secret).
     The result is announced by a status region BESIDE the button (a live region inside a button is not reliably
     announced: a button's content is its name), and the button's name starts with the words it shows ("Copy the DID",
     then "Copied the DID"), so a person who says what they see reaches it. The wrapper takes no box of its own. -->
<template>
  <span class="qo-copy-wrap">
    <button
      v-bind="$attrs"
      type="button"
      class="qo-copy"
      :class="{ 'qo-copy--done': state === 'done', 'qo-copy--failed': state === 'failed', 'qo-copy--quiet': quiet }"
      :aria-label="iconOnly ? ariaText : undefined"
      :data-state="state"
      @click="onCopy"
    >
      <Icon :name="state === 'done' ? 'mdi:check' : 'mdi:content-copy'" class="qo-copy__icon" />
      <span v-if="!iconOnly" class="qo-copy__text">{{ visibleText }}<span class="sr-only">{{ ` ${what}` }}</span></span>
    </button>
    <span class="sr-only" role="status" data-testid="qo-copy-status">{{ announcement }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { copyText } from '@/utils/copyText'

defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  /** the value to copy (never rendered) */
  value: string
  /** what is copied, for the accessible name: "Copy the client ID" */
  what: string
  /** an icon-only button (the accessible name still says what it copies) */
  iconOnly?: boolean
  /** a smaller, quieter button for a dense row */
  quiet?: boolean
}>(), { iconOnly: false, quiet: false })

const { t, tp } = useI18n()
const state = ref<'idle' | 'done' | 'failed'>('idle')
let timer: ReturnType<typeof setTimeout> | null = null

const visibleText = computed(() => state.value === 'done'
  ? t('quickOnboarding.copy.done', 'Copied')
  : state.value === 'failed' ? t('quickOnboarding.copy.failedShort', 'Not copied') : t('quickOnboarding.copy.copy', 'Copy'))
const ariaText = computed(() => tp('quickOnboarding.copy.aria', 'Copy {what}', { what: props.what }))
const announcement = computed(() => state.value === 'done' ? t('quickOnboarding.copy.done', 'Copied')
  : state.value === 'failed' ? t('quickOnboarding.copy.failed', 'Not copied: the browser refused') : '')

async function onCopy() {
  const ok = await copyText(props.value)
  state.value = ok ? 'done' : 'failed'
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => { state.value = 'idle' }, ok ? 1800 : 3200)
}
onBeforeUnmount(() => { if (timer) clearTimeout(timer) })
</script>

<style scoped>
.qo-copy-wrap { display: contents; }
.qo-copy {
  display: inline-flex; align-items: center; gap: 0.35rem; flex: 0 0 auto;
  min-height: 32px; padding: 0.3rem 0.6rem; border-radius: 8px; cursor: pointer;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.32);
  background: rgba(var(--nc-primary-rgb), 0.08);
  color: var(--nc-text-primary, #e8eaed);
  font: inherit; font-size: 0.76rem; font-weight: 600; line-height: 1;
  transition: background var(--nc-duration-fast, 200ms) ease, border-color var(--nc-duration-fast, 200ms) ease;
}
.qo-copy:hover { background: rgba(var(--nc-primary-rgb), 0.16); border-color: rgba(var(--nc-primary-rgb), 0.55); }
.qo-copy:focus-visible { outline: 2px solid var(--nc-primary-bright, var(--nc-primary)); outline-offset: 2px; }
.qo-copy--quiet { min-height: 28px; padding: 0.2rem 0.45rem; background: transparent; border-color: rgba(var(--nc-primary-rgb), 0.22); }
.qo-copy--done { border-color: rgba(0, 255, 136, 0.55); background: var(--nc-success-subtle, rgba(0, 255, 136, 0.1)); }
.qo-copy--failed { border-color: rgba(255, 149, 0, 0.6); background: var(--nc-warning-subtle, rgba(255, 149, 0, 0.1)); }
.qo-copy__icon { font-size: 0.95rem; }
.qo-copy__text { white-space: nowrap; }
@media (prefers-reduced-motion: reduce) { .qo-copy { transition: none; } }
</style>
