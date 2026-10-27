<!--
  §pass51 — BundleCard
  Used in all 3 BundlesView tabs (My, Browse Templates, search results).
  Click → opens manifest drawer. Actions: Download, Restore, Fork.
-->
<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import type { BundleSummary } from '@/services/api/bundles'

const props = withDefaults(defineProps<{
  bundle: BundleSummary
  showActions?: boolean
}>(), {
  showActions: true,
})

const emit = defineEmits<{
  (e: 'view-manifest', id: string): void
  (e: 'download', id: string): void
  (e: 'restore', id: string): void
  (e: 'fork', id: string): void
  (e: 'delete', id: string): void
}>()

const kindLabel = computed(() => {
  return { snapshot: 'SNAPSHOT', template: 'TEMPLATE', migration: 'MIGRATION' }[props.bundle.kind] || 'BUNDLE'
})

const kindIcon = computed(() => {
  return { snapshot: 'mdi:content-save-outline', template: 'mdi:file-document-multiple-outline', migration: 'mdi:swap-horizontal-bold' }[props.bundle.kind] || 'mdi:archive-outline'
})

const tierBadge = computed(() => {
  if (props.bundle.signature_tier === 2) return { text: 'VERIFIED ✓', cls: 'tier-2' }
  if (props.bundle.signature_tier === 1) return { text: 'SIGNED', cls: 'tier-1' }
  return { text: 'UNSIGNED', cls: 'tier-0' }
})

const sizeKb = computed(() => (props.bundle.size_bytes / 1024).toFixed(1))
const created = computed(() => props.bundle.created_at ? new Date(props.bundle.created_at).toLocaleString(appLocale()) : '?')
</script>

<template>
  <div class="bdl-card" :class="{ 'is-official': bundle.is_official, [`kind-${bundle.kind}`]: true }">
    <div class="bdl-card-head">
      <div class="bdl-card-title-row">
        <Icon :name="kindIcon" class="bdl-card-kind-icon" />
        <span class="bdl-card-kind">{{ kindLabel }}</span>
        <span class="bdl-card-tier" :class="tierBadge.cls">{{ tierBadge.text }}</span>
        <span v-if="bundle.is_official" class="bdl-card-official">★ OFFICIAL</span>
        <span v-if="bundle.forked_from_bundle_id" class="bdl-card-forked"
              :title="`Forked from ${bundle.forked_from_bundle_id}`">
          <Icon name="mdi:source-branch" /> FORKED
        </span>
        <span v-if="bundle.royalty_bps > 0" class="bdl-card-royalty"
              :title="`Descendants pay ${(bundle.royalty_bps / 100).toFixed(2)}% up this lineage per payment`">
          ROYALTY {{ bundle.royalty_bps }} bps
        </span>
      </div>
      <h3 class="bdl-card-name" @click="emit('view-manifest', bundle.id)">{{ bundle.name }}</h3>
      <p v-if="bundle.description" class="bdl-card-desc">{{ bundle.description }}</p>
    </div>

    <div class="bdl-card-meta">
      <span class="bdl-card-meta-item"><Icon name="mdi:archive-outline" />{{ sizeKb }} KB</span>
      <span class="bdl-card-meta-item"><Icon name="mdi:cloud-download-outline" />{{ bundle.download_count }} dl</span>
      <span class="bdl-card-meta-item"><Icon name="mdi:check-circle" />{{ bundle.install_count }} install</span>
      <span v-if="bundle.rating_count > 0" class="bdl-card-meta-item">★ {{ bundle.rating_avg?.toFixed(1) }} ({{ bundle.rating_count }})</span>
      <span class="bdl-card-meta-time">{{ created }}</span>
    </div>

    <div v-if="showActions" class="bdl-card-actions">
      <button class="bdl-btn" @click="emit('view-manifest', bundle.id)">
        <Icon name="mdi:eye-outline" /> View
      </button>
      <button class="bdl-btn" @click="emit('download', bundle.id)">
        <Icon name="mdi:cloud-download-outline" /> Download
      </button>
      <button class="bdl-btn bdl-btn--primary" @click="emit('fork', bundle.id)">
        <Icon name="mdi:rocket-launch" /> Fork
      </button>
      <button v-if="bundle.source_dev_id" type="button" class="bdl-btn bdl-btn--ghost" data-action="delete" @click="emit('delete', bundle.id)" title="Delete (owner only)" :aria-label="`Delete ${bundle.name}`">
        <Icon name="mdi:trash-can-outline" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.bdl-card {
  background: linear-gradient(180deg, rgba(13,22,38,0.65) 0%, rgba(8,14,24,0.75) 100%);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 10px;
  padding: 14px 16px 12px;
  display: flex; flex-direction: column; gap: 10px;
  transition: border-color 0.18s, background 0.18s;
  font-family: 'IBM Plex Mono', monospace;
  position: relative;
}
.bdl-card:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.45);
  background: linear-gradient(180deg, rgba(13,22,38,0.78) 0%, rgba(8,14,24,0.88) 100%);
}
.bdl-card.is-official {
  border-color: rgba(255, 215, 0, 0.4);
  background: linear-gradient(180deg, rgba(43, 32, 8, 0.6) 0%, rgba(20, 14, 8, 0.75) 100%);
}
.bdl-card.is-official:hover { border-color: rgba(255, 215, 0, 0.75); }

.bdl-card-head { display: flex; flex-direction: column; gap: 4px; }
.bdl-card-title-row {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  font-size: 0.6rem; letter-spacing: 0.18em; font-weight: 700;
}
.bdl-card-kind-icon { width: 14px; height: 14px; color: rgba(var(--nc-primary-rgb), 0.7); }
.bdl-card-kind { color: rgba(var(--nc-primary-rgb), 0.85); }
.bdl-card-tier {
  padding: 1px 6px; border-radius: 3px; font-size: 0.55rem; letter-spacing: 0.16em;
}
.bdl-card-tier.tier-0 { background: rgba(148,163,184,0.15); color: rgba(148,163,184,0.7); }
.bdl-card-tier.tier-1 { background: rgba(0,210,210,0.16); color: rgba(0,210,210,0.95); }
.bdl-card-tier.tier-2 { background: rgba(0,255,136,0.22); color: rgba(0,255,136,0.95); }
.bdl-card-official { background: rgba(255,215,0,0.22); color: rgba(255,215,0,0.95); padding: 1px 6px; border-radius: 3px; font-size: 0.55rem; letter-spacing: 0.16em; }
.bdl-card-forked { display: inline-flex; align-items: center; gap: 3px; background: rgba(139,92,246,0.18); color: #c4b5fd; padding: 1px 6px; border-radius: 3px; font-size: 0.55rem; letter-spacing: 0.14em; }
.bdl-card-royalty { background: rgba(16,185,129,0.14); color: #6ee7b7; padding: 1px 6px; border-radius: 3px; font-size: 0.55rem; letter-spacing: 0.1em; font-family: 'SF Mono', 'Fira Code', monospace; }

.bdl-card-name {
  font-size: 0.95rem; font-weight: 700; color: #e8eaed; margin: 4px 0 0; line-height: 1.25;
  cursor: pointer; transition: color 0.15s;
}
.bdl-card-name:hover { color: var(--nc-primary, #00d2d2); }
.bdl-card-desc { font-size: 0.75rem; color: #99a5b3; margin: 0; line-height: 1.4; }

.bdl-card-meta {
  display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
  font-size: 0.65rem; color: rgba(148,163,184,0.7);
  padding: 4px 0; border-top: 1px solid rgba(var(--nc-primary-rgb), 0.08);
}
.bdl-card-meta-item { display: inline-flex; align-items: center; gap: 3px; }
.bdl-card-meta-item svg { width: 11px; height: 11px; }
.bdl-card-meta-time { margin-left: auto; font-style: italic; opacity: 0.7; }

.bdl-card-actions { display: flex; gap: 5px; flex-wrap: wrap; padding-top: 4px; border-top: 1px solid rgba(var(--nc-primary-rgb), 0.08); }
.bdl-btn {
  display: inline-flex; align-items: center; gap: 4px;
  background: transparent; border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  color: rgba(var(--nc-primary-rgb), 0.85);
  font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; font-weight: 600;
  padding: 5px 9px; border-radius: 4px; cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s, transform 0.06s;
}
.bdl-btn:hover { background: rgba(var(--nc-primary-rgb), 0.1); color: var(--nc-primary); border-color: rgba(var(--nc-primary-rgb), 0.55); }
.bdl-btn:active { transform: translateY(1px); }
.bdl-btn svg { width: 12px; height: 12px; }
.bdl-btn--primary {
  background: linear-gradient(180deg, var(--nc-primary-bright, #00e8e8) 0%, var(--nc-primary, #00d2d2) 100%);
  border-color: var(--nc-primary, #00d2d2); color: #04141f;
}
.bdl-btn--primary:hover { background: linear-gradient(180deg, #fff 0%, var(--nc-primary-bright, #00e8e8) 100%); color: #04141f; }
.bdl-btn--ghost { border-color: rgba(255,68,68,0.25); color: rgba(255,68,68,0.7); margin-left: auto; }
.bdl-btn--ghost:hover { background: rgba(255,68,68,0.1); color: #ff4444; border-color: rgba(255,68,68,0.55); }
</style>
