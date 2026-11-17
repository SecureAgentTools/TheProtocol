<!--
  PersonName — a person of a code change, named (V0665, order gwo_fbadffa68e593603d0c59b66): the name the registry gave (an agent's name, a member's public name), a short tail only where
  the page shows two different people under one name, and for an agent the WHOLE DID as the element's title and behind a Copy control (a member has no DID to copy). An agent the
  registry no longer finds is said in words (the label's text). services/codeChanges/people decides every word; this draws it.
-->
<template>
  <span class="pn" :class="{ 'pn-gone': gone }" :title="label.full || undefined" :data-testid="testid">
    <span class="pn-name" data-testid="pn-name">{{ label.text }}</span><code v-if="label.tail" class="pn-tail" data-testid="pn-tail">{{ label.tail }}</code>
    <button v-if="label.full" type="button" class="pn-copy" :aria-label="copied ? t('codeChanges.copiedDid', 'DID copied') : t('codeChanges.copyDid', 'Copy the agent\'s whole DID')" :title="label.full" data-testid="pn-copy" @click.stop="copy">
      <Icon :name="copied ? 'mdi:check' : 'mdi:content-copy'" />
    </button>
  </span>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import type { Label } from '@/services/codeChanges/people'

const props = defineProps<{ label: Label; gone?: boolean; testid?: string }>()
const { t } = useI18n()
const copied = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
async function copy() {
  if (!props.label.full) return
  try {
    await navigator.clipboard.writeText(props.label.full)
    copied.value = true
    clearTimeout(timer)
    timer = setTimeout(() => (copied.value = false), 1800)
  } catch { /* clipboard blocked: the whole DID is still the element's title */ }
}
</script>

<style scoped>
.pn { display: inline-flex; align-items: center; gap: .35rem; max-width: 100%; min-width: 0; }
.pn-name { overflow-wrap: anywhere; }
.pn-gone .pn-name { color: #8b97a6; font-style: italic; }
.pn-tail { font: .68rem 'IBM Plex Mono', monospace; color: #8b97a6; background: rgba(0,0,0,.3); border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), .14); border-radius: 5px; padding: 1px 6px; }
.pn-copy { flex: none; display: inline-grid; place-items: center; width: 32px; height: 32px; margin: -6px 0; border-radius: 6px; border: 1px solid transparent; background: none; color: #8b97a6; cursor: pointer; }
.pn-copy:hover, .pn-copy:focus-visible { color: var(--nc-primary, #00d2d2); border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), .35); }
.pn-copy :deep(svg) { width: .85rem; height: .85rem; }
</style>
