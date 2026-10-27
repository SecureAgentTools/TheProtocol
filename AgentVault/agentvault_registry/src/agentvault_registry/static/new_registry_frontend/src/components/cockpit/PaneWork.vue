<script setup lang="ts">
/**
 * §COCKPITMODULES M3 — WORK: contracts, guild orders and disputes, both sides.
 *
 * ⚠ THE PLAN SAID "mount `BridgeWorkView`, do not re-implement it" AND THAT PREMISE WAS
 * STALE. That component is an 840-line MODAL with a `show` prop and a FOCUS TRAP; mounting
 * it in a dashboard tile would trap keyboard focus inside a grid cell. So this is a
 * read-only summary over the same rails, and the modal remains the one place work is done.
 *
 * ⚠ ACCOUNT-WIDE, like `book`, and it says so — it does NOT follow the header switcher.
 * Work belongs to an agent, but a desk asking "what is outstanding" means everything I own,
 * and a pane that does not declare which convention it follows will be misread (§FOREIGNACT).
 *
 * ⚠ BOTH SIDES of every relationship: an agent is as often the client as the provider, and
 * counting one side would under-report by construction.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { apiClient } from '@/services/api/client'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import RecordLink from './RecordLink.vue'
import { useI18n } from '@/composables/useI18n'
import { PANES } from './paneRegistry'

const { t, tp } = useI18n()
const def = PANES.work

const data = ref<any>({})
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
let poll: ReturnType<typeof setInterval> | null = null

async function load() {
  try {
    const r = await apiClient.get('/developers/me/work')
    data.value = r.data || {}
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 120) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

const families = computed(() => ([
  { key: 'contracts', label: t('cockpit.work.contracts', 'Contracts'), d: data.value.contracts },
  { key: 'guild',     label: t('cockpit.work.guild', 'Guild work'),    d: data.value.guild },
  { key: 'disputes',  label: t('cockpit.work.disputes', 'Disputes'),   d: data.value.disputes },
]).filter(f => !!f.d))

const empty = computed(() => !loading.value && families.value.length === 0)
const openTotal = computed(() =>
  families.value.reduce((a, f) => a + Number(f.d?.open || 0), 0))
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="t('cockpit.work.empty', 'No contracts, guild orders or disputes involve your agents.')"
             data-testid="ckd-work">
    <p class="ckd-w-head" data-testid="ckd-w-head">
      {{ openTotal > 0
          ? tp('cockpit.work.openN', '{n} open across everything you own.', { n: openTotal })
          : t('cockpit.work.openNone', 'Nothing open across everything you own.') }}
    </p>

    <section v-for="f in families" :key="f.key" class="ckd-w-fam" :data-fam="f.key"
             data-testid="ckd-w-fam">
      <header class="ckd-w-famh">
        <span class="ckd-w-label">{{ f.label }}</span>
        <span class="ckd-w-open" :class="{ 'is-open': Number(f.d.open) > 0 }">
          {{ tp('cockpit.work.openOf', '{o} open of {t}', { o: f.d.open, t: f.d.total }) }}
        </span>
      </header>
      <ul class="ckd-w-st">
        <li v-for="s in f.d.by_status" :key="s.status" class="ckd-w-strow">
          <span class="ckd-w-stname">{{ s.status }}</span>
          <span class="ckd-w-stn">{{ s.n }}</span>
        </li>
      </ul>
    </section>

    <p class="ckd-w-foot" data-testid="ckd-w-foot">
      {{ t('cockpit.work.foot', 'Everything you own, both sides of each deal. This pane does not follow the agent switcher.') }}
      <span class="ckd-w-doors">
        <RecordLink kind="contract" :label="t('cockpit.door.contracts', 'Contracts')" />
        <RecordLink kind="dispute" :label="t('cockpit.door.disputes', 'Disputes')" />
        <RecordLink kind="guild" :label="t('cockpit.door.guild', 'Guild board')" />
      </span>
    </p>
  </PaneShell>
</template>

<style scoped>
.ckd-w-head { margin: 0 0 .45rem; font-size: .72rem; color: var(--nc-text-secondary, #c9d1d9); }
.ckd-w-fam { margin: 0 0 .5rem; }
.ckd-w-famh { display: flex; align-items: baseline; gap: .4rem; }
.ckd-w-label { flex: 1; font-size: .72rem; font-weight: 600; color: var(--nc-text-primary, #e6edf3); }
.ckd-w-open { font-size: .64rem; color: var(--nc-text-muted, #6e7681);
  font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums; }
.ckd-w-open.is-open { color: var(--nc-warning, #d29922); }
.ckd-w-st { list-style: none; margin: .12rem 0 0 .5rem; padding: 0;
  display: flex; flex-direction: column; gap: .1rem; }
.ckd-w-strow { display: flex; align-items: baseline; gap: .35rem; font-size: .66rem; }
.ckd-w-stname { flex: 1; color: var(--nc-text-muted, #6e7681);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ckd-w-stn { font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums;
  color: var(--nc-text-dim, #8b949e); flex: 0 0 2.2rem; width: 2.2rem; text-align: right; }
.ckd-w-foot { margin: .35rem 0 0; font-size: .62rem; color: var(--nc-text-muted, #6e7681); }
.ckd-w-doors { display: inline-flex; gap: .6rem; margin-left: .4rem; }
</style>
