<script setup lang="ts">
/**
 * §COCKPITDESK (2026-10-15) — RELEASE CHANNEL: what this registry runs, what the signed channel offers, and what is
 * scheduled. Admin only (the platform flag), over `GET /admin/release-channel/status`.
 *
 * The registry never updates itself (§RELEASECHANNEL): the pane says whether a newer release exists and when the
 * channel was last read, and the release channel page holds the command and the schedule. A channel that could
 * not be read is a different answer from "up to date", so the last check's outcome is always on screen.
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import PaneShell from './PaneShell.vue'
import RecordLink from './RecordLink.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import { agoShort, untilShort } from '@/services/cockpit/when'
import { reportAttention, clearAttention } from '@/services/cockpit/attention'
import { useI18n } from '@/composables/useI18n'
import { PANES } from './paneRegistry'
import { releaseChannelApi, type ReleaseChannelStatus } from '@/services/api/releaseChannel'

const { t, tp } = useI18n()
const def = PANES.release

const st = ref<ReleaseChannelStatus | null>(null)
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)
let poll: ReturnType<typeof setInterval> | null = null

async function load() {
  try {
    st.value = await releaseChannelApi.status()
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 300) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null; clearAttention('release') })

const running = computed(() => st.value?.running?.software_version || st.value?.running?.kit_version || '')
const verdict = computed(() => {
  const s = st.value
  if (!s) return { key: 'none', text: '' }
  if (!s.enabled) return { key: 'off', text: t('cockpit.rel.off', 'The release channel is off on this registry.') }
  if (s.last_outcome && s.last_outcome !== 'ok') {
    return { key: 'unread', text: tp('cockpit.rel.unread', 'The channel could not be read ({o}).', { o: s.last_outcome }) }
  }
  if (s.update_available && s.latest) {
    return { key: 'update', text: tp('cockpit.rel.update', 'A newer release is out: {v} ({k}).', { v: s.latest.version, k: s.latest.kind || s.kind || '' }) }
  }
  if (s.comparable === false) return { key: 'unknown', text: t('cockpit.rel.notComparable', 'This build cannot be compared with the channel.') }
  if (!s.last_check_at) return { key: 'unknown', text: t('cockpit.rel.notChecked', 'The channel has not been read yet.') }
  return { key: 'ok', text: t('cockpit.rel.current', 'Up to date with the channel.') }
})
watch(() => verdict.value.key, (k) => reportAttention('release', k === 'update' ? 1 : 0, t('cockpit.attn.release', 'A newer release is out'), 'info'), { immediate: true })
const schedule = computed(() => {
  const sc = st.value?.schedule
  if (!sc) return ''
  const u = untilShort(sc.at)
  return u && !u.past
    ? tp('cockpit.rel.scheduled', '{v} scheduled in {t}', { v: sc.version, t: u.span })
    : tp('cockpit.rel.scheduledPast', '{v} was scheduled {t} ago', { v: sc.version, t: u ? u.span : '?' })
})
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load">
    <div class="rel" data-testid="ckd-release" :data-verdict="verdict.key">
      <p class="rel-run" data-testid="rel-running">
        {{ running ? tp('cockpit.rel.running', 'Runs {v}', { v: running }) : t('cockpit.rel.runningUnknown', 'The running version is not known.') }}
        <span v-if="st?.running?.modified_build" class="rel-mod">{{ t('cockpit.rel.modified', 'modified build') }}</span>
      </p>
      <p class="rel-verdict" :class="`is-${verdict.key}`" data-testid="rel-verdict">{{ verdict.text }}</p>
      <p class="rel-meta">
        <template v-if="st?.last_check_at">{{ tp('cockpit.rel.checked', 'channel read {age} ago', { age: agoShort(st.last_check_at) }) }}</template>
        <template v-if="schedule"> · {{ schedule }}</template>
        <template v-else-if="st?.enabled"> · {{ t('cockpit.rel.nothingScheduled', 'nothing scheduled') }}</template>
      </p>
      <p class="rel-foot">
        <RecordLink kind="release" :label="t('cockpit.door.release', 'Open the release channel')" />
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.rel { display: flex; flex-direction: column; gap: .25rem; }
.rel-run { margin: 0; font-size: .74rem; color: var(--nc-text-primary, #e6edf3); font-family: var(--nc-font-mono, ui-monospace, monospace); }
.rel-mod { font-size: .56rem; letter-spacing: .06em; text-transform: uppercase; margin-left: .35rem; padding: 0 .25rem;
  border: 1px solid currentColor; border-radius: 3px; color: var(--nc-warning, #d29922); font-family: inherit; }
.rel-verdict { margin: 0; font-size: .72rem; color: var(--nc-text-secondary, #c9d1d9); }
.rel-verdict.is-update { color: var(--nc-primary, #00e5ff); }
.rel-verdict.is-unread, .rel-verdict.is-unknown { color: var(--nc-warning, #d29922); }
.rel-verdict.is-ok { color: var(--nc-success, #3fb950); }
.rel-meta { margin: 0; font-size: .64rem; color: var(--nc-text-muted, #8b949e); }
.rel-foot { margin: .1rem 0 0; font-size: .62rem; }
</style>
