<!--
  PublicAnnouncementsStrip.vue: the newest public announcements in a visitor's sidebar (V0664, order gwo_1b3e2cc74c1afec6c6cedc3d).

  Mounted where the sidebar shows a visitor its one sign-in line. It reads GET /public/announcements (no sign-in) for the newest
  three titles and a door to the full page. With none, or when they cannot be read, it draws NOTHING: a line that told every visitor
  "no announcements" would be noise, and a read that failed is not worth a visitor's attention in a sidebar.
-->
<template>
  <div v-if="items.length" class="pas-root" data-testid="pas-root">
    <div class="pas-head">{{ t('announcements.title', 'Announcements') }}</div>
    <ul class="pas-list">
      <li v-for="a in items" :key="a.id" class="pas-item" data-testid="pas-item">{{ a.title }}</li>
    </ul>
    <button type="button" class="pas-all" data-testid="pas-all" @click="router.push('/announcements')">
      {{ t('announcements.all', 'All announcements') }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import { fetchPublicAnnouncements, type PublicAnnouncement } from '@/services/announcements/publicAnnouncements'

const { t } = useI18n()
const router = useRouter()
const items = ref<PublicAnnouncement[]>([])

onMounted(async () => {
  try {
    items.value = (await fetchPublicAnnouncements(3)).slice(0, 3)
  } catch {
    items.value = []
  }
})
</script>

<style scoped>
.pas-root { margin: 8px 12px 0; padding: 8px 10px; border: 1px solid var(--nc-border); border-radius: 6px; font-size: 0.78rem; }
.pas-head { color: var(--nc-text-secondary); font-size: 0.68rem; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 4px; }
.pas-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 3px; color: var(--nc-text-primary); }
.pas-item { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pas-all { margin-top: 6px; background: none; border: 0; padding: 0; color: var(--nc-primary); text-decoration: underline; cursor: pointer; font-size: 0.75rem; }
</style>
