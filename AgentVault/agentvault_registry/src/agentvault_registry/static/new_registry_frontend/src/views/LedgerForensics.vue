<template>
  <div class="lf-root">
    <!-- Ambient is painted by DashboardLayout's <ViewAmbient> via
         route.meta.viewAmbientTone='admin'. No local ambient. -->
    <div class="lf-content">
      <!-- Hero -->
      <div class="lf-hero" data-tour="forensics-hero">
        <div>
          <div class="lf-chip"><span class="lf-chip-dot"></span>ADMINISTRATION · LEDGER FORENSICS</div>
          <h1 class="lf-h1">Ledger Forensics</h1>
          <p class="lf-lead">
            Find exactly where funds are stuck, trace any aggregate's money path, and govern event
            emission — without reading 88M events by hand.
          </p>
        </div>
        <div class="lf-hero-actions">
          <!-- §FEDEVENTS: LOCAL registry + connected Multi-Frame sessions only —
               no hardcoded letters, works on any deployment (hetzner-frame incl.). -->
          <label class="lf-frame">
            <span class="lf-frame-label">FRAME</span>
            <select v-model="frame" class="lf-input">
              <option v-for="o in selectableFrames" :key="o.key" :value="o.key">
                {{ o.label }}{{ o.isLocal ? ' · local' : '' }}
              </option>
            </select>
          </label>
          <router-link
            v-if="selectableFrames.length === 1"
            class="lf-connect-link"
            to="/settings?tab=multiframe"
            title="Foreign frames appear here once their admin is connected in the Multi-Frame Console"
          >+ connect frames</router-link>
        </div>
      </div>

      <!-- Tab bar -->
      <div class="lf-tabs" role="tablist" data-tour="forensics-tabs">
        <button
          v-for="tb in tabs"
          :key="tb.key"
          type="button"
          role="tab"
          class="lf-tab"
          :data-tour="'forensics-tab-' + tb.key"
          :class="{ 'lf-tab--active': activeTab === tb.key }"
          :aria-selected="activeTab === tb.key"
          @click="activeTab = tb.key"
        >
          <Icon :name="tb.icon" class="lf-tab-ico" />
          <span>{{ tb.label }}</span>
        </button>
      </div>

      <!-- Panels (lazy: each tab loads its own data when first shown) -->
      <div class="lf-panel-host" data-tour="forensics-panel">
        <StuckFundsTab v-if="activeTab === 'stuck'" :frame="frame" />
        <QueryTab v-else-if="activeTab === 'query'" :frame="frame" />
        <TraceTab v-else-if="activeTab === 'trace'" :frame="frame" />
        <FindingsTab v-else-if="activeTab === 'findings'" />
        <PolicyTab v-else-if="activeTab === 'policy'" />
      </div>

      <!-- Roadmap footer — what's live vs. the next backend layer -->
      <div class="lf-footnote">
        <Icon name="mdi:information" class="lf-foot-ico" />
        <span>
          Live: AGORA + supply invariants, gateway-keeper, registry-rail <strong>Inventory</strong>,
          time-ranged <strong>Query</strong>, txid <strong>Trace</strong>, and the <strong>Findings</strong> inbox
          (scanner default-OFF — enable <code>FORENSIC_SCANNER_ENABLED</code> per frame). Next layer: the full
          anchor→3-DB <strong>made-whole verdict</strong> (registry + TEG row status, both frames) and a GIN index
          for arbitrary payload-containment search.
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { LOCAL_FRAME, type FrameId } from '@/services/api/eventStoreAdmin'
import { useAdminFrames } from '@/composables/useAdminFrames'
import StuckFundsTab from '@/components/forensics/StuckFundsTab.vue'
import QueryTab from '@/components/forensics/QueryTab.vue'
import TraceTab from '@/components/forensics/TraceTab.vue'
import FindingsTab from '@/components/forensics/FindingsTab.vue'
import PolicyTab from '@/components/forensics/PolicyTab.vue'

type TabKey = 'stuck' | 'query' | 'trace' | 'findings' | 'policy'

// §FEDEVENTS: default is ALWAYS the local frame (the old hardcoded 'A' landed
// frame-b/c/hetzner admins on a foreign — often unconfigured — frame).
const { selectableFrames } = useAdminFrames()
const frame = ref<FrameId>(LOCAL_FRAME)
// If the selected foreign frame's session disconnects, fall back to local.
watch(selectableFrames, (opts) => {
  if (!opts.some(o => o.key === frame.value)) frame.value = LOCAL_FRAME
})
const activeTab = ref<TabKey>('stuck')

const tabs: Array<{ key: TabKey; label: string; icon: string }> = [
  { key: 'stuck', label: 'Stuck Funds', icon: 'mdi:bank' },
  { key: 'query', label: 'Query', icon: 'mdi:magnify' },
  { key: 'trace', label: 'Trace', icon: 'mdi:map-marker-path' },
  { key: 'findings', label: 'Findings', icon: 'mdi:shield-alert' },
  { key: 'policy', label: 'Emission Policy', icon: 'mdi:file-document-edit' },
]
</script>

<style scoped>
.lf-root {
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --red: #ff3366;
  --green: #00ff88;
  --amber: #ff9500;
  --muted: #788593;  /* §FESUITE: 4.89:1 on the footnote (#6b7785 was 4.0:1) */
  --border: rgba(var(--cyan-rgb), 0.18);
  --surface: #0a0d16;
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  --text-bright: #e8eaed;
  position: relative; min-height: 100vh; color: var(--text-bright);
  padding: 24px; overflow-x: hidden;
}
.lf-content { position: relative; z-index: 1; max-width: 1500px; margin: 0 auto; }

.lf-hero { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
.lf-hero-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.lf-chip {
  display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px; border-radius: 12px;
  background: rgba(var(--cyan-rgb), 0.08); border: 1px solid rgba(var(--cyan-rgb), 0.25);
  color: var(--cyan); font-size: 10px; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase;
}
.lf-chip-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--cyan); box-shadow: 0 0 8px var(--cyan); }
.lf-h1 { font-size: 28px; font-weight: 800; margin: 8px 0 4px 0; color: var(--text-bright); letter-spacing: -0.02em; }
.lf-lead { font-size: 13px; color: var(--muted); margin: 0; max-width: 720px; line-height: 1.5; }

.lf-frame { display: flex; align-items: center; gap: 8px; }
.lf-frame-label { font-size: 9px; font-weight: 700; letter-spacing: 0.16em; color: var(--muted); }
.lf-connect-link { font-size: 11px; color: rgba(var(--cyan-rgb), 0.75); text-decoration: none; font-family: var(--mono); }
.lf-connect-link:hover { color: var(--cyan); text-decoration: underline; }
.lf-input {
  background: rgba(0,0,0,0.35); color: var(--text-bright); border: 1px solid var(--border);
  border-radius: 4px; padding: 6px 10px; font-size: 12px; font-family: var(--mono);
}
.lf-input:focus { outline: none; border-color: rgba(var(--cyan-rgb), 0.5); }

.lf-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 18px; flex-wrap: wrap; }
.lf-tab {
  display: inline-flex; align-items: center; gap: 7px; padding: 10px 16px;
  background: transparent; border: none; border-bottom: 2px solid transparent;
  color: var(--muted); font-size: 13px; font-weight: 600; cursor: pointer; transition: color 0.15s, border-color 0.15s;
}
.lf-tab:hover { color: var(--text-bright); }
.lf-tab--active { color: var(--cyan); border-bottom-color: var(--cyan); }
.lf-tab-ico { width: 16px; height: 16px; }

.lf-panel-host { position: relative; }

.lf-footnote {
  display: flex; gap: 10px; align-items: flex-start; margin-top: 22px; padding: 12px 14px;
  background: rgba(var(--cyan-rgb), 0.04); border: 1px solid var(--border); border-radius: 6px;
  color: var(--muted); font-size: 12px; line-height: 1.5;
}
.lf-footnote strong { color: #c8d8e8; font-weight: 700; }
.lf-foot-ico { width: 18px; height: 18px; flex-shrink: 0; color: var(--cyan); margin-top: 1px; }
</style>
