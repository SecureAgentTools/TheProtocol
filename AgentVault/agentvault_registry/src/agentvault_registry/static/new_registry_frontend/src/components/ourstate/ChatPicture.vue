<!--
  V0664 (order gwo_c101e38685cd18581be34c2f; his phone report, the sessions' room seq 3741 to 3761) — a picture in a chat message, shown as a
  picture. The bytes arrive only through the viewer's own authenticated read of /chat/attachments/{id}, turned into a local blob: no <img src>
  names the registry, so a card cannot make the app load a file the viewer's session did not ask for. `auto` (the default) asks at once, for
  the viewer's own pictures and the people of a room; a stranger's request (`defang`) passes auto=false and waits for a press. Only the
  registry's picture types reach here (png, jpeg, webp, gif: services/chat/attachmentGroups.isPictureMime; SVG never).
-->
<template>
  <figure class="cp" :class="{ open }" data-testid="cp-root">
    <img v-if="url" class="cp-img" :src="url" :alt="name" data-testid="cp-img" @click="open = !open" />
    <button v-else-if="!auto && !loading && !failed && !gone" type="button" class="cp-btn" data-testid="cp-show" @click="load">
      <Icon name="mdi:eye" /> {{ tp('ourstate.picture.show', 'Show {name} ({size})', { name, size: sizeWords }) }}
    </button>
    <p v-else-if="gone" class="cp-note" data-testid="cp-gone">{{ t('ourstate.picture.gone', 'This picture was removed.') }}</p>
    <p v-else-if="failed" class="cp-note" data-testid="cp-failed">
      {{ t('ourstate.picture.failed', 'The picture could not be read.') }}
      <button type="button" class="cp-btn small" data-testid="cp-retry" @click="load">{{ t('ourstate.picture.retry', 'Try again') }}</button>
    </p>
    <p v-else class="cp-note" data-testid="cp-loading">{{ name }} <span>{{ sizeWords }}</span></p>
  </figure>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { apiClient } from '@/services/api/client'
import { humanSize } from '@/services/chat/attachments'

const props = withDefaults(defineProps<{ attachmentId: string; name: string; mime?: string; bytes?: number; auto?: boolean }>(), { mime: '', bytes: 0, auto: true })
const { t, tp } = useI18n()
const url = ref('')
const loading = ref(false)
const failed = ref(false)
const gone = ref(false)
const open = ref(false)
const sizeWords = computed(() => (props.bytes ? humanSize(props.bytes) : ''))

async function load() {
  if (loading.value || url.value) return
  loading.value = true; failed.value = false; gone.value = false
  try {
    const r = await apiClient.get(`/chat/attachments/${props.attachmentId}`, { responseType: 'blob' })
    url.value = URL.createObjectURL(r.data as Blob)
  } catch (e: any) {
    if (e?.response?.status === 410) gone.value = true
    else failed.value = true
  } finally { loading.value = false }
}

onMounted(() => { if (props.auto) void load() })
onBeforeUnmount(() => { if (url.value) URL.revokeObjectURL(url.value) })
</script>

<style scoped>
.cp { margin: 0; max-width: 100%; }
.cp-img { display: block; max-width: 100%; max-height: 320px; object-fit: contain; border-radius: 10px; cursor: zoom-in; background: rgba(0,0,0,.25); }
.cp.open .cp-img { max-height: none; cursor: zoom-out; }
.cp-btn { display: inline-flex; align-items: center; gap: 6px; min-height: 36px; padding: 0 12px; border-radius: 10px; border: 1px solid var(--border-color, rgba(128,128,128,.35)); background: none; color: inherit; font: inherit; font-size: .8rem; cursor: pointer; }
.cp-btn.small { min-height: 28px; padding: 0 8px; font-size: .74rem; }
.cp-note { margin: 0; font-size: .78rem; opacity: .75; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
</style>
