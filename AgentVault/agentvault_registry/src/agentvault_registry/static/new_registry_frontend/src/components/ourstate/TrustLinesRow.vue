<template>
  <!-- The trust surfaces (ONE brain, services/chat/trustCard.ts): rendered on
       a pending request AND summoned by /audit — same lines, same wording,
       absence stated honestly (99.8% of agents have no history; that is a
       fact about the network's age, not a warning). Local-only: composing
       this posts nothing and notifies nobody. -->
  <div class="tlr" data-testid="trust-lines">
    <template v-if="loaded">
      <span v-for="(l, i) in lines" :key="i" class="tlr-chip" :class="`tlr-${l.kind}`">
        <template v-if="l.kind === 'jobs'">
          <Icon name="mdi:check-circle" />
          {{ tp(l.jobs === 1 ? 'ourstate.trust.job' : 'ourstate.trust.jobs', l.jobs === 1 ? '{n} verified job' : '{n} verified jobs', { n: l.jobs }) }}
          <template v-if="l.crossRegistry"> · {{ tp('ourstate.trust.cross', '{n} cross-registry', { n: l.crossRegistry }) }}</template>
        </template>
        <template v-else-if="l.kind === 'stars'">★ {{ l.stars }}</template>
        <template v-else-if="l.kind === 'tier'">{{ l.tier }}</template>
        <template v-else-if="l.kind === 'disputes'">
          {{ tp('ourstate.trust.disputes', '{open} open / {total} disputes', { open: l.open, total: l.total }) }}</template>
        <template v-else-if="l.kind === 'reputation'">
          {{ tp('ourstate.trust.reputation', 'reputation {p}%', { p: Math.round(l.score * 100) }) }}</template>
        <template v-else-if="l.kind === 'no-history'">{{ t('ourstate.trust.noHistory', 'no public history yet') }}</template>
      </span>
      <span v-if="home" class="tlr-chip tlr-home">{{ home }}</span>
    </template>
    <span v-else class="tlr-chip tlr-loading">…</span>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { fetchTrustCard, trustLines, type TrustLine } from '@/services/chat/trustCard'
import { useI18n } from '@/composables/useI18n'

const { t, tp } = useI18n()

const props = defineProps<{ did: string | null }>()

const lines = ref<TrustLine[]>([])
const home = ref<string | null>(null)
const loaded = ref(false)

watch(() => props.did, async (did) => {
  loaded.value = false
  lines.value = []
  home.value = null
  if (!did) { loaded.value = true; return }
  const d = await fetchTrustCard(did)
  lines.value = trustLines(d)
  home.value = d.homeRegistry
  loaded.value = true
}, { immediate: true })
</script>

<style scoped>
.tlr { display: flex; flex-wrap: wrap; gap: 6px; }
.tlr-chip { display: inline-flex; align-items: center; gap: 4px; font-size: .74rem; padding: 3px 9px; border-radius: 999px; border: 1px solid var(--border-color, rgba(128,128,128,.3)); opacity: .9; }
.tlr-jobs { border-color: var(--primary-color, #4fd8c4); }
.tlr-disputes { border-color: var(--warning-color, #f59e0b); }
.tlr-no-history, .tlr-loading { opacity: .55; }
</style>
