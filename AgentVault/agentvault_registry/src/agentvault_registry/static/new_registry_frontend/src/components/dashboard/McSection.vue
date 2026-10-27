<!--
  McSection.vue — §MCFOLD (2026-09-02) — one folded strip on Mission Control.

  The body is rendered with `v-if`, never hidden with CSS: a folded strip MOUNTS NOTHING,
  so nothing inside it polls or opens a socket (the Bridge's ticker-door rule, generalised).
  The open/folded state is per browser (`services/dashboard/mcSections.ts`), folded by
  default. The whole header is the button; `aria-expanded` says which way it is.
-->
<template>
  <section class="mcs" :class="{ 'is-open': open }" :data-testid="`mc-sec-${id}`" :data-open="open ? '1' : '0'">
    <button type="button" class="mcs-head" :aria-expanded="open ? 'true' : 'false'"
            :aria-controls="`mc-sec-body-${id}`" :data-testid="`mc-sec-${id}-toggle`" @click="toggle">
      <Icon :name="icon" class="mcs-ico" />
      <span class="mcs-title">{{ title }}</span>
      <span class="mcs-sum"><slot name="summary" /></span>
      <span class="mcs-spacer" />
      <span class="mcs-state">{{ open ? t('mc.section.hide', 'Hide') : t('mc.section.show', 'Show') }}</span>
      <Icon name="mdi:chevron-down" class="mcs-chev" />
    </button>
    <div v-if="open" :id="`mc-sec-body-${id}`" class="mcs-body" :data-testid="`mc-sec-${id}-body`">
      <slot />
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { isSectionOpen, setSectionOpen } from '@/services/dashboard/mcSections'

const props = withDefaults(defineProps<{ id: string; title: string; icon?: string }>(), { icon: 'mdi:view-dashboard-outline' })
const { t } = useI18n()
const open = ref(isSectionOpen(props.id, false))
function toggle() { open.value = !open.value; setSectionOpen(props.id, open.value) }
</script>

<style scoped>
.mcs { border: 1px solid rgba(var(--nc-primary-rgb), 0.18); border-radius: 11px;
  background: linear-gradient(168deg, rgba(255,255,255,0.025), rgba(255,255,255,0) 60%), rgba(var(--nc-primary-rgb), 0.035); }
.mcs-head { display: flex; align-items: center; gap: 0.6rem; width: 100%; padding: 0.55rem 0.9rem;
  background: none; border: 0; color: inherit; cursor: pointer; text-align: left; border-radius: 11px; }
.mcs-head:hover { background: rgba(var(--nc-primary-rgb), 0.05); }
.mcs-head:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.6); outline-offset: -2px; }
.mcs-ico { width: 14px; height: 14px; color: rgba(var(--nc-primary-rgb), 0.85); flex: none; }
.mcs-title { font-family: ui-monospace, monospace; font-size: 10px; letter-spacing: 0.16em; font-weight: 700;
  color: rgba(var(--nc-primary-rgb), 0.9); white-space: nowrap; }
.mcs-sum { font-size: 0.68rem; color: var(--nc-text-muted, #6e7681); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mcs-spacer { flex: 1; }
.mcs-state { font-size: 0.62rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--nc-text-muted, #6e7681); }
.mcs-chev { width: 14px; height: 14px; color: var(--nc-text-muted, #6e7681); transition: transform 0.15s ease; flex: none; }
.is-open .mcs-chev { transform: rotate(180deg); }
.mcs-body { padding: 0.15rem 0.6rem 0.65rem; }
</style>
