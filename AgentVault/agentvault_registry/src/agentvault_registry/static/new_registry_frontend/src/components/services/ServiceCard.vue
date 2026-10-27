<template>
  <div class="svc-card svc-card-x" :class="{ 'is-open': open }">
    <button class="svc-card-head" @click="$emit('toggle')" :aria-expanded="open">
      <span class="svc-card-icon" :style="{ background: `rgba(${svc.accent},0.14)`, color: `rgb(${svc.accent})` }">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" v-html="svc.svg"></svg>
      </span>
      <span class="svc-card-meta">
        <span class="svc-card-name">{{ svc.label }}</span>
        <span class="svc-card-blurb">{{ svc.blurb }}</span>
      </span>
      <span class="svc-card-price" :title="priceTitle">
        <template v-if="isCrossCurrency">
          <span class="svc-card-fx">FX</span>
          <span class="svc-card-pay">{{ svc.priceLocal }}<small>{{ svc.currencyLocal }}</small></span>
          <span class="svc-card-arrow">&rarr;</span>
          <span class="svc-card-bill">{{ svc.priceNative }}<small>{{ svc.currencyNative }}</small></span>
        </template>
        <template v-else>
          {{ svc.priceNative || svc.price }}<small>{{ svc.currencyNative || localCurrency }}</small>
        </template>
      </span>
      <svg class="svc-card-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>
    </button>

    <div v-if="open" class="svc-card-body">
      <!-- §MCPTEST30 (V0641, D6-831): this agent cannot be paid from here; the call's own words, and no run -->
      <p v-if="svc.uncallable && !unavailable" class="svc-card-off" role="status" data-testid="svc-uncallable">{{ svc.uncallable }}</p>
      <ServiceRunner :svc="svc" :loading="loading" :unavailable="unavailable || svc.uncallable || null" @run="$emit('run')" />
      <!-- Loading state: shared kit skeleton while the live A2A call settles -->
      <div v-if="loading && !response" class="svc-card-skel" aria-live="polite" aria-busy="true">
        <div class="svc-card-skel-bar">
          <span class="svc-card-skel-pill"></span>
          <span class="svc-card-skel-pill svc-card-skel-pill--sm"></span>
        </div>
        <SkeletonLoader variant="text" :rows="3" label="Running agent…" />
      </div>
      <ServiceResult v-if="response" :svc="svc" :response="response" style="margin-top:.8rem" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useCurrency } from '@/composables/useCurrency'
import ServiceRunner from './ServiceRunner.vue'
import ServiceResult from './ServiceResult.vue'
import SkeletonLoader from '@/components/common/SkeletonLoader.vue'
import type { ShowcaseService } from '@/composables/useShowcaseServices'

const props = defineProps<{ svc: ShowcaseService; open: boolean; loading: boolean; response: any; unavailable?: string | null }>()
defineEmits<{ (e: 'toggle'): void; (e: 'run'): void }>()
const { localCurrency } = useCurrency()

// The agent bills in ITS currency. When this frame settles in another, the card
// states the conversion rather than printing the agent's number under our own
// label, which is what made frame-c read "0.5 BVT" for a 0.5 AVT service.
// Absent local price (no live rate) falls back to the true charge, never a
// relabelled one.
const isCrossCurrency = computed(() =>
  !!props.svc.priceLocal &&
  !!props.svc.currencyLocal &&
  !!props.svc.currencyNative &&
  props.svc.currencyLocal !== props.svc.currencyNative,
)
const priceTitle = computed(() => {
  if (!isCrossCurrency.value) {
    return `${props.svc.priceNative || props.svc.price} ${props.svc.currencyNative || localCurrency.value} per call`
  }
  const fee = props.svc.fxFee ? `, ${(Number(props.svc.fxFee) * 100).toFixed(2)}% FX fee` : ''
  return `This agent bills ${props.svc.priceNative} ${props.svc.currencyNative}. `
    + `Your frame sends ${props.svc.priceLocal} ${props.svc.currencyLocal} at the live cross-frame rate`
    + (props.svc.fxRate ? ` of ${props.svc.fxRate} ${props.svc.currencyLocal} per ${props.svc.currencyNative}` : '')
    + `${fee}, so the agent receives its full price.`
})
</script>

<style scoped>
.svc-card-x { overflow: hidden; transition: border-color 0.2s ease, box-shadow 0.2s ease; }
.svc-card-x.is-open { border-color: rgba(var(--svc-rgb), 0.4); box-shadow: 0 0 0 1px rgba(var(--svc-rgb), 0.12), 0 22px 46px -30px rgba(0, 0, 0, 0.9); }
.svc-card-head { display: flex; align-items: center; gap: 0.9rem; width: 100%; padding: 0.95rem 1.1rem; background: none; border: 0; cursor: pointer; text-align: left; color: inherit; font-family: inherit; }
.svc-card-head:hover { background: rgba(255, 255, 255, 0.015); }
.svc-card-icon { width: 42px; height: 42px; border-radius: 11px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.svc-card-icon svg { width: 20px; height: 20px; }
.svc-card-meta { flex: 1; min-width: 0; }
.svc-card-name { display: block; font-size: 0.86rem; font-weight: 700; color: var(--svc-ink); }
.svc-card-blurb { display: block; font-size: 0.68rem; color: var(--svc-dim); margin-top: 0.12rem; overflow: hidden; text-overflow: ellipsis; }
.svc-card-price { font-size: 0.85rem; font-weight: 800; color: var(--svc); font-variant-numeric: tabular-nums; flex-shrink: 0; white-space: nowrap; }
.svc-card-price small { font-weight: 500; font-size: 0.6rem; opacity: 0.7; margin-left: 0.18rem; }
.svc-card-price { display: inline-flex; align-items: baseline; gap: 0.3rem; cursor: help; }
.svc-card-fx { font-size: 0.52rem; font-weight: 800; letter-spacing: 0.09em; color: var(--svc); border: 1px solid currentColor; border-radius: 4px; padding: 0.08rem 0.26rem; opacity: 0.75; align-self: center; }
.svc-card-pay { font-weight: 800; }
.svc-card-arrow { opacity: 0.5; font-size: 0.75rem; }
.svc-card-bill { opacity: 0.72; font-weight: 600; }
.svc-card-chev { width: 16px; height: 16px; color: var(--svc-faint); transition: transform 0.25s ease, color 0.2s ease; flex-shrink: 0; }
.is-open .svc-card-chev { transform: rotate(180deg); color: var(--svc); }
.svc-card-body { padding: 0 1.1rem 1.1rem; }
.svc-card-off { font-size: 0.7rem; line-height: 1.5; color: var(--svc-warn); margin: 0 0 0.6rem; }

/* Loading skeleton (shared kit) — mirrors the result-panel chrome so a pending
   A2A call reads as "result incoming", not empty space. */
.svc-card-skel { margin-top: 0.8rem; padding: 0.7rem 0.8rem 0.85rem; border-radius: 12px; border: 1px solid var(--svc-line-soft); background: rgba(255, 255, 255, 0.02); animation: svc-skel-fade 0.25s ease; }
.svc-card-skel-bar { display: flex; gap: 0.4rem; margin-bottom: 0.7rem; }
.svc-card-skel-pill { width: 84px; height: 0.95rem; border-radius: 6px; background: rgba(var(--svc-rgb), 0.1); }
.svc-card-skel-pill--sm { width: 48px; }
@keyframes svc-skel-fade { from { opacity: 0; } to { opacity: 1; } }
</style>
