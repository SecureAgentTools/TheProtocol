<script setup lang="ts">
// §RELEASECHANNEL: one line above every admin page while the signed channel lists a newer release; nothing otherwise.
// Admin-only by construction (the rail is admin-only), silent on any failure. It shows the one shared status, which
// the release page's own reads and checks replace, so "Check now" there is this line's answer too.
import { computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/composables/useI18n'
import { releaseChannelApi, releaseChannelState } from '@/services/api/releaseChannel'

const { t } = useI18n()
const auth = useAuthStore()
const status = releaseChannelState
// §FESUITE (agentvault2-c9's report): the rail requires admin_platform; any OTHER admin flag (a support desk, a service
// account with admin_federation) asked anyway and was refused with 403 on every dashboard load.
const platformAdmin = computed(() => {
  const u = auth.user as unknown as Record<string, unknown> | null
  return auth.userRole === 'admin' || Boolean(u?.admin_platform)
})
const show = computed(() => Boolean(platformAdmin.value && status.value?.enabled && status.value?.update_available && status.value?.latest))
const kindWord = computed(() => {
  const k = status.value?.kind
  return k === 'security' ? t('adminRelease.kind.security', 'security') : k === 'hotfix' ? t('adminRelease.kind.hotfix', 'hotfix') : t('adminRelease.kind.stable', 'stable')
})
onMounted(async () => {
  if (!platformAdmin.value) return
  try { await releaseChannelApi.status() } catch { /* the line stays as it was: a failed read is not news */ }
})
</script>

<template>
  <div v-if="show" class="rcb" :data-kind="status?.kind" data-testid="release-channel-banner">
    <span>{{ t('adminRelease.bannerText', 'A newer release is on the signed channel') }}: <strong>{{ status?.latest?.version }}</strong> ({{ kindWord }})<span v-if="status?.schedule"> · {{ t('adminRelease.scheduled', 'Scheduled') }} {{ new Date(status.schedule.at).toLocaleString() }}</span></span>
    <RouterLink to="/admin/release-channel" class="rcb-link">{{ t('adminRelease.bannerLink', 'Schedule the rollout') }}</RouterLink>
  </div>
</template>

<style scoped>
.rcb { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; align-items: center; padding: 8px 16px; font-size: 0.86rem; border-bottom: 1px solid rgba(251, 191, 36, 0.4); background: rgba(251, 191, 36, 0.08); }
.rcb[data-kind="security"], .rcb[data-kind="hotfix"] { border-bottom-color: rgba(248, 113, 113, 0.5); background: rgba(248, 113, 113, 0.08); }
.rcb-link { text-decoration: underline; }
</style>
