<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
// §RELEASECHANNEL (2026-09-21): what this registry runs, what the signed channel lists, and the rollout window the
// admin schedules. The page changes nothing on the host: it prints the command for the window.
import { computed, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { releaseChannelApi, releaseChannelState } from '@/services/api/releaseChannel'

const { t, tp } = useI18n()
// the status the banner above every admin page shows too: each read and check here replaces it for both
const status = releaseChannelState
const loading = ref(false)
const checking = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const form = ref({ version: '', at: '', note: '' })

const running = computed(() => status.value?.running?.kit_version || status.value?.running?.software_version || '')
// what a window can be scheduled for: the releases newer than this registry (the newest is not one of them once this
// registry runs it; the rail refuses those too)
const candidates = computed(() => (status.value ? status.value.newer.map((r) => r.version) : [] as string[]))
const checkedAgainst = computed(() => status.value?.checked_against?.kit_version || status.value?.checked_against?.software_version || '')
const verdict = computed(() => {
  const s = status.value
  if (!s) return 'loading'
  if (!s.enabled) return 'disabled'
  if (s.last_outcome !== 'ok') return s.last_outcome || 'never'
  if (s.comparable === false) return 'unknown'
  return s.update_available ? 'behind' : 'current'
})
const outcomeLabel = (o: string | null) =>
  o === 'ok' ? t('adminRelease.outcome.ok', 'verified')
  : o === 'unreachable' ? t('adminRelease.outcome.unreachable', 'not published or unreachable')
  : o === 'invalid_signature' ? t('adminRelease.outcome.invalid_signature', 'signature did not verify')
  : o === 'invalid_document' ? t('adminRelease.outcome.invalid_document', 'not a release document')
  : t('adminRelease.outcome.never', 'never checked')
const kindLabel = (k?: string | null) =>
  k === 'security' ? t('adminRelease.kind.security', 'security')
  : k === 'hotfix' ? t('adminRelease.kind.hotfix', 'hotfix') : t('adminRelease.kind.stable', 'stable')
const fmt = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : '')
const localToIso = (local: string) => (local ? new Date(local).toISOString() : '')

async function load() {
  loading.value = true; error.value = null
  try {
    status.value = await releaseChannelApi.status()
    if (!form.value.version && candidates.value.length) form.value.version = candidates.value[0]
  } catch (e: any) { error.value = e?.response?.data?.detail || e?.message || t('adminRelease.error', 'The request failed.') }
  finally { loading.value = false }
}
async function checkNow() {
  checking.value = true; error.value = null
  try { status.value = await releaseChannelApi.checkNow() }
  catch (e: any) { error.value = e?.response?.data?.detail || e?.message || t('adminRelease.error', 'The request failed.') }
  finally { checking.value = false }
}
async function saveSchedule() {
  if (!form.value.version || !form.value.at) return
  saving.value = true; error.value = null
  try {
    status.value = await releaseChannelApi.schedule({ version: form.value.version, at: localToIso(form.value.at), note: form.value.note || undefined })
  } catch (e: any) { error.value = e?.response?.data?.detail || e?.message || t('adminRelease.error', 'The request failed.') }
  finally { saving.value = false }
}
async function clearSchedule() {
  saving.value = true; error.value = null
  try { status.value = await releaseChannelApi.unschedule() }
  catch (e: any) { error.value = e?.response?.data?.detail || e?.message || t('adminRelease.error', 'The request failed.') }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <div class="rc-page" data-testid="admin-release-channel">
    <header class="rc-head">
      <div>
        <h1 class="rc-title"><Icon name="mdi:package" /> {{ t('adminRelease.title', 'Release channel') }}</h1>
        <p class="rc-sub">{{ t('adminRelease.subtitle', 'Stable releases and hotfixes on the signed channel. You schedule the rollout; the registry changes nothing by itself.') }}</p>
      </div>
      <button class="rc-btn" :disabled="checking || !status?.enabled" data-testid="rc-check" @click="checkNow">
        <Icon name="mdi:refresh" /> {{ checking ? t('adminRelease.checking', 'Checking...') : t('adminRelease.checkNow', 'Check now') }}
      </button>
    </header>

    <p v-if="error" class="rc-error" data-testid="rc-error">{{ error }}</p>

    <section v-if="status" class="rc-grid">
      <div class="rc-card" data-testid="rc-running">
        <div class="rc-label">{{ t('adminRelease.running', 'This registry runs') }}</div>
        <div class="rc-value">{{ running || t('adminRelease.unknownVersion', 'unknown') }}</div>
        <div v-if="status.running?.modified_build" class="rc-muted">{{ t('adminRelease.modified', 'a build that differs from its release') }}</div>
        <div class="rc-muted">{{ status.node_kind === 'operator' ? t('adminRelease.nodeOperator', 'cloud operator') : t('adminRelease.nodeFrame', 'frame') }}</div>
      </div>
      <div class="rc-card" :data-verdict="verdict" data-testid="rc-verdict">
        <div class="rc-label">{{ t('adminRelease.channel', 'Channel') }}</div>
        <div class="rc-value">
          <span v-if="verdict === 'disabled'">{{ t('adminRelease.disabled', 'The checker is off on this registry (RELEASE_CHANNEL_CHECK_ENABLED).') }}</span>
          <span v-else-if="verdict === 'behind'" class="rc-behind">{{ t('adminRelease.behind', 'Update available') }} ({{ kindLabel(status.kind) }})</span>
          <span v-else-if="verdict === 'current'" class="rc-ok">{{ t('adminRelease.upToDate', 'Up to date') }}</span>
          <span v-else-if="verdict === 'unknown'">{{ t('adminRelease.unknown', 'Cannot compare versions') }}</span>
          <span v-else>{{ outcomeLabel(status.last_outcome) }}</span>
        </div>
        <div class="rc-muted">{{ t('adminRelease.lastCheck', 'Last check') }}: {{ status.last_check_at ? fmt(status.last_check_at) : t('adminRelease.outcome.never', 'never checked') }}<span v-if="status.last_error"> ({{ status.last_error }})</span></div>
        <div v-if="checkedAgainst" class="rc-muted" data-testid="rc-checked-against">{{ tp('adminRelease.checkedAgainst', 'That check saw {v}; its releases are read again against the build that runs now.', { v: checkedAgainst }) }}</div>
        <div class="rc-muted rc-url">{{ status.channel_url }}</div>
      </div>
      <div class="rc-card" data-testid="rc-pull">
        <div class="rc-label">{{ t('adminRelease.publicPull', 'Public image pull') }}</div>
        <div class="rc-value">{{ status.public_pull ? t('adminRelease.on', 'on') : t('adminRelease.off', 'off') }}</div>
        <div class="rc-muted">{{ status.public_namespace }}/*</div>
      </div>
    </section>

    <section v-if="status?.latest" class="rc-card rc-latest" data-testid="rc-latest">
      <div class="rc-label">{{ t('adminRelease.latest', 'Newest release') }}</div>
      <div class="rc-value">{{ status.latest.version }} <span class="rc-chip" :data-kind="status.latest.kind">{{ kindLabel(status.latest.kind) }}</span></div>
      <div class="rc-muted">{{ t('adminRelease.released', 'released') }} {{ fmt(status.latest.released_at) }}<span v-if="status.latest.registry_software_version"> · {{ status.latest.registry_software_version }}</span></div>
      <p v-if="status.latest.notes" class="rc-notes">{{ status.latest.notes }}</p>
      <dl class="rc-facts">
        <template v-if="status.latest.kit_url"><dt>{{ t('adminRelease.kit', 'Kit') }}</dt><dd><a :href="safeExternalUrl(status.latest.kit_url)" rel="noopener noreferrer">{{ status.latest.kit_url }}</a><span v-if="status.latest.kit_sha256" class="rc-muted"> sha256 {{ status.latest.kit_sha256 }}</span></dd></template>
        <template v-if="status.latest.images_prefix"><dt>{{ t('adminRelease.images', 'Images') }}</dt><dd>{{ status.latest.images_prefix }}/*:{{ status.latest.images_tag }}</dd></template>
        <template v-if="status.latest.min_upgrade_from"><dt>{{ t('adminRelease.minFrom', 'Upgrades from') }}</dt><dd>{{ status.latest.min_upgrade_from }}</dd></template>
        <template v-if="status.latest.rollback"><dt>{{ t('adminRelease.rollback', 'Rollback') }}</dt><dd>{{ status.latest.rollback }}</dd></template>
      </dl>
      <div v-if="status.newer.length > 1" class="rc-muted">{{ t('adminRelease.moreNewer', 'Releases newer than this registry') }}: {{ status.newer.map((r) => r.version).join(', ') }}</div>
    </section>

    <section v-if="status" class="rc-card" data-testid="rc-schedule">
      <div class="rc-label">{{ t('adminRelease.schedule', 'Schedule the rollout') }}</div>
      <p class="rc-muted">{{ t('adminRelease.scheduleHint', 'Pick the window. The registry reminds you when it is due and changes nothing itself; the command below runs on the host.') }}</p>
      <div v-if="status.schedule" class="rc-current" data-testid="rc-scheduled">
        <Icon name="mdi:calendar-clock" />
        <span>{{ t('adminRelease.scheduled', 'Scheduled') }}: {{ status.schedule.version }} · {{ fmt(status.schedule.at) }}<span v-if="status.schedule.note"> · {{ status.schedule.note }}</span><span v-if="status.schedule.set_by" class="rc-muted"> ({{ t('adminRelease.setBy', 'set by') }} {{ status.schedule.set_by }})</span></span>
        <button class="rc-btn rc-btn-quiet" :disabled="saving" data-testid="rc-clear" @click="clearSchedule">{{ t('adminRelease.clear', 'Clear') }}</button>
      </div>
      <form v-if="candidates.length" class="rc-form" @submit.prevent="saveSchedule">
        <label>{{ t('adminRelease.version', 'Version') }}
          <select v-model="form.version" data-testid="rc-version"><option v-for="v in candidates" :key="v" :value="v">{{ v }}</option></select>
        </label>
        <label>{{ t('adminRelease.at', 'When (your local time)') }}
          <input v-model="form.at" type="datetime-local" required data-testid="rc-at" />
        </label>
        <label>{{ t('adminRelease.note', 'Note') }}
          <input v-model="form.note" type="text" maxlength="400" data-testid="rc-note" />
        </label>
        <button class="rc-btn" type="submit" :disabled="saving || !form.version || !form.at" data-testid="rc-save">{{ t('adminRelease.save', 'Save window') }}</button>
      </form>
      <p v-else-if="status.latest && verdict === 'current'" class="rc-muted" data-testid="rc-nothing-newer">{{ t('adminRelease.nothingNewer', 'Nothing to schedule: this registry runs the newest release.') }}</p>
      <p v-else class="rc-muted">{{ t('adminRelease.nothingToSchedule', 'Nothing to schedule: the channel lists no release for this registry yet.') }}</p>
      <div v-if="status.rollout_command" class="rc-cmd">
        <div class="rc-label">{{ t('adminRelease.command', 'Run on the host in your window') }}</div>
        <code data-testid="rc-command">{{ status.schedule ? status.rollout_command.replace(status.newer[0]?.version || '', status.schedule.version) : status.rollout_command }}</code>
      </div>
    </section>
  </div>
</template>

<style scoped>
.rc-page { padding: 24px; max-width: 1080px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
.rc-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.rc-title { font-size: 1.4rem; font-weight: 600; display: flex; align-items: center; gap: 8px; margin: 0; }
.rc-sub { margin: 4px 0 0; opacity: 0.75; max-width: 70ch; }
.rc-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
.rc-card { border: 1px solid rgba(148, 163, 184, 0.25); border-radius: 10px; padding: 14px 16px; background: rgba(15, 23, 42, 0.35); }
.rc-label { font-size: 0.78rem; opacity: 0.7; margin-bottom: 4px; }
.rc-value { font-size: 1.05rem; font-weight: 600; word-break: break-word; }
.rc-muted { font-size: 0.82rem; opacity: 0.7; margin-top: 4px; }
.rc-url { word-break: break-all; }
.rc-behind { color: #fbbf24; }
.rc-ok { color: #34d399; }
.rc-chip { font-size: 0.72rem; padding: 2px 8px; border-radius: 999px; border: 1px solid currentColor; margin-left: 6px; vertical-align: middle; }
.rc-chip[data-kind="security"], .rc-chip[data-kind="hotfix"] { color: #f87171; }
.rc-notes { white-space: pre-wrap; margin: 10px 0; }
.rc-facts { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; margin: 8px 0 0; font-size: 0.88rem; }
.rc-facts dt { opacity: 0.7; } .rc-facts dd { margin: 0; word-break: break-all; }
.rc-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; align-items: end; margin-top: 10px; }
.rc-form label { display: flex; flex-direction: column; gap: 4px; font-size: 0.82rem; }
.rc-form input, .rc-form select { padding: 6px 8px; border-radius: 6px; border: 1px solid rgba(148, 163, 184, 0.35); background: rgba(2, 6, 23, 0.5); color: inherit; }
.rc-btn { padding: 8px 14px; border-radius: 8px; border: 1px solid rgba(56, 189, 248, 0.5); background: rgba(56, 189, 248, 0.12); color: inherit; cursor: pointer; display: inline-flex; gap: 6px; align-items: center; }
.rc-btn:disabled { opacity: 0.5; cursor: default; }
.rc-btn-quiet { border-color: rgba(148, 163, 184, 0.35); background: transparent; }
.rc-current { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 8px 0; }
.rc-cmd { margin-top: 12px; }
.rc-cmd code { display: block; padding: 8px 10px; border-radius: 6px; background: rgba(2, 6, 23, 0.6); font-size: 0.85rem; word-break: break-all; }
.rc-error { color: #f87171; }
@media (max-width: 640px) { .rc-page { padding: 16px; } }
</style>
