<!--
  PublicAnnouncements.vue: what an admin marked public, for anyone (V0664, order gwo_1b3e2cc74c1afec6c6cedc3d, his yes seq 3638).

  A visitor has no account, so the member pages (the bell, the Community Hub) show them nothing. An admin can mark an announcement
  public (the `public` mark, default off), and this page reads exactly those through GET /public/announcements: the registry serves
  only the marked ones that are active, sent and addressed to everyone, and only the fields a visitor needs. A body is shown as TEXT
  (never as markup) and a call to action only through a safe address.
-->
<template>
  <div class="pa-root" data-testid="pa-root">
    <header class="pa-head">
      <h1 class="pa-title">{{ t('announcements.title', 'Announcements') }}</h1>
      <p class="pa-lede">{{ t('announcements.lede', 'What this registry\'s administrators have made public.') }}</p>
    </header>

    <p v-if="loading" class="pa-loading" role="status">{{ t('announcements.loading', 'Reading the announcements…') }}</p>

    <div v-else-if="failed" class="pa-failed" role="alert" data-testid="pa-failed">
      <span>{{ t('announcements.failed', 'The announcements could not be read just now.') }}</span>
      <button type="button" class="pa-retry" data-testid="pa-retry" @click="load">{{ t('announcements.retry', 'Try again') }}</button>
    </div>

    <EmptyReason v-else-if="!items.length" kind="none-yet"
      :reason="t('announcements.none', 'No announcement has been made public on this registry yet.')" />

    <ul v-else class="pa-list">
      <li v-for="a in items" :key="a.id" class="pa-item" :data-type="a.type" data-testid="pa-item">
        <div class="pa-item-head">
          <span class="pa-type" :class="`pa-type--${a.type}`">{{ typeLabel(a.type) }}</span>
          <h2 class="pa-item-title" data-testid="pa-title">{{ a.title }}</h2>
          <time v-if="a.createdAt" class="pa-when" :datetime="a.createdAt">{{ when(a.createdAt) }}</time>
        </div>
        <p class="pa-body" data-testid="pa-body">{{ a.body }}</p>
        <a v-if="a.cta" class="pa-cta" data-testid="pa-cta" :href="safeExternalUrl(a.cta.url)" target="_blank" rel="noopener noreferrer">{{ a.cta.label }}</a>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from '@/composables/useI18n'
import EmptyReason from '@/components/common/EmptyReason.vue'
import { safeExternalUrl } from '@/utils/safeUrl'
import { fetchPublicAnnouncements, type AnnouncementType, type PublicAnnouncement } from '@/services/announcements/publicAnnouncements'

const { t } = useI18n()
const items = ref<PublicAnnouncement[]>([])
const loading = ref(true)
const failed = ref(false)

const LABELS: Record<AnnouncementType, string> = { info: 'Info', warning: 'Warning', maintenance: 'Maintenance', critical: 'Action needed' }
const typeLabel = (k: AnnouncementType): string => LABELS[k] || LABELS.info
const when = (iso: string): string => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toISOString().slice(0, 10)
}

async function load(): Promise<void> {
  loading.value = true
  failed.value = false
  try {
    items.value = await fetchPublicAnnouncements(20)
  } catch {
    failed.value = true
    items.value = []
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<style scoped>
.pa-root { max-width: 720px; margin: 0 auto; padding: 24px 16px; color: var(--nc-text-primary); }
.pa-head { margin-bottom: 4px; }
.pa-title { font-size: 1.4rem; font-weight: 300; letter-spacing: 0.02em; }
.pa-lede { color: var(--nc-text-secondary); font-size: 0.9rem; margin: 4px 0 20px; }
.pa-loading { color: var(--nc-text-secondary); }
.pa-failed { display: flex; gap: 12px; align-items: center; color: var(--nc-text-secondary); }
.pa-retry { background: none; border: 1px solid var(--nc-border); color: var(--nc-text-primary); border-radius: 4px; padding: 4px 12px; cursor: pointer; }
.pa-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 14px; }
.pa-item { border: 1px solid var(--nc-border); border-radius: 6px; padding: 14px 16px; background: var(--nc-surface); }
.pa-item-head { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.pa-item-title { font-size: 1.05rem; font-weight: 500; margin: 0; flex: 1 1 auto; }
.pa-type { font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--nc-text-secondary); border: 1px solid var(--nc-border); border-radius: 10px; padding: 1px 8px; }
.pa-type--warning, .pa-type--maintenance { color: var(--nc-warning); }
.pa-type--critical { color: var(--nc-danger); }
.pa-when { color: var(--nc-text-secondary); font-size: 0.78rem; }
.pa-body { white-space: pre-wrap; overflow-wrap: anywhere; margin: 10px 0 0; line-height: 1.5; }
.pa-cta { display: inline-block; margin-top: 10px; color: var(--nc-primary); text-decoration: underline; }
</style>
