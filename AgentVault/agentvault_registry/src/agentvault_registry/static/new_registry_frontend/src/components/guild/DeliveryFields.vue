<!-- V0662 console polish, item 3: a Guild delivery as fields a person can copy (the link, the note, the hash, each
     commit, then any other key by its name), never as raw JSON. Only an http or https address is a link
     (services/guild/orderView.deliveryFields); every value has its own copy button (components/quickOnboarding/
     CopyButton, which says "Copied" only once the browser took it). -->
<template>
  <dl class="gdf">
    <div v-for="f in fields" :key="f.key" class="gdf-row" :data-testid="`gld-deliv-field-${f.key}`">
      <dt class="gdf-label">{{ f.label }}</dt>
      <dd class="gdf-value">
        <span class="gdf-text">
          <a v-if="f.href" :href="safeExternalUrl(f.href)" target="_blank" rel="noopener noreferrer nofollow" class="gdf-link">{{ f.value }}</a>
          <span v-else :class="{ 'gdf-mono': f.key !== 'text' }">{{ f.value }}</span>
          <span v-if="f.detail" class="gdf-detail">{{ f.detail }}</span>
        </span>
        <CopyButton v-if="f.copy" :value="f.value" :what="f.label" icon-only quiet :data-testid="`gld-copy-${f.key}`" />
      </dd>
    </div>
  </dl>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import CopyButton from '@/components/quickOnboarding/CopyButton.vue'
import { useI18n } from '@/composables/useI18n'
import { deliveryFields } from '@/services/guild/orderView'
import { safeExternalUrl } from '@/utils/safeUrl'   // the poster's worker wrote the address: the console's link rule

const props = defineProps<{ deliverable: unknown }>()
const { t } = useI18n()
const fields = computed(() => deliveryFields(props.deliverable, t))
</script>

<style scoped>
.gdf { margin: 0 0 0.5rem; display: grid; gap: 0.35rem; }
.gdf-row { display: grid; grid-template-columns: 5.5rem minmax(0, 1fr); gap: 0.5rem; align-items: start; }
.gdf-label { font-size: 0.7rem; opacity: 0.6; padding-top: 0.35rem; }
.gdf-value { margin: 0; display: flex; align-items: flex-start; gap: 0.4rem; min-width: 0; }
.gdf-text { flex: 1 1 auto; min-width: 0; font-size: 0.78rem; background: rgba(0, 0, 0, 0.2); border-radius: 6px;
  padding: 0.35rem 0.45rem; overflow-wrap: anywhere; white-space: pre-wrap; }
.gdf-mono { font-family: ui-monospace, monospace; font-size: 0.72rem; }
.gdf-link { color: #7dd3fc; text-decoration: underline; font-family: ui-monospace, monospace; font-size: 0.72rem; }
.gdf-detail { display: block; opacity: 0.55; font-size: 0.66rem; margin-top: 0.15rem; }
@media (max-width: 520px) { .gdf-row { grid-template-columns: minmax(0, 1fr); gap: 0.15rem; } .gdf-label { padding-top: 0; } }
</style>
