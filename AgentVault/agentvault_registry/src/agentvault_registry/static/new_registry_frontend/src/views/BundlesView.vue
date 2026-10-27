<!--
  §pass51 — BundlesView
  Replaces /export-import. Three tabs:
   - My Bundles: snapshots + templates owned by current dev
   - Browse Templates: public + official templates (marketplace)
   - Restore from File: upload .tpb (or legacy .json) and restore
-->
<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useBundlesStore } from '@/stores/bundles'
import { useUIStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import BundleCard from '@/components/bundles/BundleCard.vue'
import NewBundleModal from '@/components/bundles/NewBundleModal.vue'
import RestoreDropzone from '@/components/bundles/RestoreDropzone.vue'
import BundleManifestDrawer from '@/components/bundles/BundleManifestDrawer.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'

const bundlesStore = useBundlesStore()
const uiStore = useUIStore()
const route = useRoute()
const router = useRouter()

type Tab = 'mine' | 'browse' | 'restore'
const activeTab = ref<Tab>('mine')
const newModalShow = ref(false)
const drawerBundleId = ref<string | null>(null)
const search = ref('')

/* §FESUITE — GET /bundles answers own + public + official: "My Bundles" showed a fresh account six official templates
   it does not own (and no empty state). Mine = the ones this developer exported. */
const authStore = useAuthStore()
const myId = computed(() => Number((authStore.user as any)?.id ?? NaN))
const myBundles = computed(() => bundlesStore.bundles.filter(b =>
  b.source_dev_id !== null && Number(b.source_dev_id) === myId.value
).filter(b =>
  !search.value ||
  b.name.toLowerCase().includes(search.value.toLowerCase()) ||
  (b.description || '').toLowerCase().includes(search.value.toLowerCase())
))
const publicBundles = computed(() => bundlesStore.bundles.filter(b => b.kind === 'template' && b.visibility === 'public'))
const officialBundles = computed(() => bundlesStore.bundles.filter(b => b.is_official))
/* D6-481: a colleague's 'org' bundle (GET /bundles lists it to its organization's owner, admins and members). */
const orgBundles = computed(() => bundlesStore.bundles.filter(b =>
  b.visibility === 'org' && !b.is_official && !(b.source_dev_id !== null && Number(b.source_dev_id) === myId.value)
))
/** Each bundle once: the official ones are public templates too, and the tab counted them twice. */
const browseCount = computed(() => new Set([...publicBundles.value, ...officialBundles.value, ...orgBundles.value].map(b => b.id)).size)

onMounted(async () => {
  await bundlesStore.load({ include_official: true })
  if (route.params.bundleId) drawerBundleId.value = String(route.params.bundleId)
})

watch(() => route.params.bundleId, (id) => {
  drawerBundleId.value = id ? String(id) : null
})

async function onCreated(result: any) {
  uiStore.showSuccess?.('Bundle created', result?.name || undefined)
  await bundlesStore.load({ include_official: true })
}

async function handleDownload(id: string) {
  const b = bundlesStore.bundles.find(x => x.id === id)
  const fname = `${(b?.name || 'bundle').replace(/[^a-z0-9-]+/gi, '-').toLowerCase()}-${id.slice(0,8)}.tpb`
  // §FESUITE — a failed download used to reject unhandled: nothing on screen, an uncaught error in the console
  try { await bundlesStore.download(id, fname) }
  catch (e: any) { uiStore.showError?.('Download failed', typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : (e?.message || '')) }
}

/** §FESUITE — the confirm dialog renders its message as HTML: a bundle's name is the owner's text, never markup. */
const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' } as Record<string, string>)[c])

const forkResult = ref<any | null>(null)
// GÖDEL FORGE fork options — a fork records lineage + an optional royalty the ancestor line
// earns whenever the fork's descendants earn (250 bps default, 500 cap — arena constitution).
const forkTarget = ref<any | null>(null)
const forkRoyalty = ref<number>(250)

function handleForkPrompt(id: string) {
  const b = [...myBundles.value, ...publicBundles.value, ...officialBundles.value, ...orgBundles.value].find((x: any) => x.id === id)
  forkTarget.value = b || { id }
  forkRoyalty.value = Number.isFinite(b?.royalty_bps) && b.royalty_bps > 0 ? b.royalty_bps : 250
}

async function doFork() {
  const id = forkTarget.value?.id
  if (!id) return
  forkTarget.value = null
  uiStore.showInfo?.('Forking bundle…')
  const bps = Math.max(0, Math.min(500, Math.round(forkRoyalty.value || 0)))
  const result = await bundlesStore.fork(id, { royalty_bps: bps })
  if (result.success) {
    forkResult.value = result
  } else {
    uiStore.showError?.(result.errors?.[0] || 'Fork failed')
  }
}

// Restore (dropzone / own-snapshot revive) keeps the plain restore semantics — no lineage.
async function handleFork(id: string) {
  uiStore.showInfo?.('Restoring bundle…')
  const result = await bundlesStore.restoreById(id, { conflict_resolution: 'rename', mode: 'copy', include_cicd: true })
  if (result.success) {
    forkResult.value = result
  } else {
    uiStore.showError?.(result.errors?.[0] || 'Restore failed')
  }
}

function copyForkCreds() {
  if (!forkResult.value?.produced_agents) return
  const block = forkResult.value.produced_agents.map((a: any) =>
    `Agent: ${a.name}\nDID: ${a.did}\nClient ID: ${a.client_id}\nClient Secret: ${a.client_secret}`
  ).join('\n\n---\n\n')
  try {
    navigator.clipboard?.writeText(block)
    uiStore.showSuccess?.('Credentials copied to clipboard')
  } catch (_) { /* ignore */ }
}

const deleteTarget = ref<{ id: string; name: string } | null>(null)
const deleting = ref(false)

function handleDelete(id: string) {
  const b = bundlesStore.bundles.find(x => x.id === id)
  deleteTarget.value = { id, name: b?.name || 'this bundle' }
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await bundlesStore.deleteBundle(deleteTarget.value.id)
    uiStore.showSuccess?.('Bundle deleted')
    deleteTarget.value = null
  } catch (e: any) {
    uiStore.showError?.(e?.response?.data?.detail || 'Delete failed')
  } finally {
    deleting.value = false
  }
}

function handleViewManifest(id: string) {
  drawerBundleId.value = id
}

function closeDrawer() {
  drawerBundleId.value = null
}
</script>

<template>
  <div class="bdl-view">
    <div class="bdl-page-head">
      <div>
        <div class="bdl-page-eyebrow">SOVEREIGN // BUNDLES</div>
        <h1 class="bdl-page-title" data-tour="bdl-hero">Agent Bundles</h1>
        <p class="bdl-page-subtitle">
          Signed, portable archives of your agents. Snapshot for backup. Template for sharing. Migration for moving.
        </p>
      </div>
      <button class="bdl-new-btn" data-tour="bdl-new" @click="newModalShow = true">
        <Icon name="mdi:plus" />
        <span>New bundle</span>
      </button>
    </div>

    <nav class="bdl-tabs" data-tour="bdl-tabs" role="tablist" aria-label="Bundles">
      <button type="button" role="tab" class="bdl-tab" data-tab="mine" :aria-selected="activeTab === 'mine'" :class="{ 'is-active': activeTab === 'mine' }" @click="activeTab = 'mine'">
        <Icon name="mdi:archive-outline" />
        <span>My Bundles</span>
        <span class="bdl-tab-count">{{ bundlesStore.loaded ? myBundles.length : '—' }}</span>
      </button>
      <button type="button" role="tab" class="bdl-tab" data-tab="browse" data-tour="bdl-browse" :aria-selected="activeTab === 'browse'" :class="{ 'is-active': activeTab === 'browse' }" @click="activeTab = 'browse'">
        <Icon name="mdi:telescope" />
        <span>Browse Templates</span>
        <span class="bdl-tab-count">{{ bundlesStore.loaded ? browseCount : '—' }}</span>
      </button>
      <button type="button" role="tab" class="bdl-tab" data-tab="restore" data-tour="bdl-restore" :aria-selected="activeTab === 'restore'" :class="{ 'is-active': activeTab === 'restore' }" @click="activeTab = 'restore'">
        <Icon name="mdi:cloud-upload-outline" />
        <span>Restore from File</span>
      </button>
    </nav>

    <section v-if="activeTab === 'mine'" class="bdl-tab-panel">
      <div class="bdl-toolbar">
        <input v-model="search" class="bdl-search" placeholder="Filter by name or description…" aria-label="Filter bundles" />
      </div>
      <div v-if="bundlesStore.loading" class="bdl-loading">Loading…</div>
      <!-- §FESUITE (the failing-reads census, 2026-10-04): with the read failed this said "No bundles yet" -->
      <ReadFailedNotice v-else-if="!bundlesStore.loaded && bundlesStore.error" :retry="() => bundlesStore.load({ include_official: true })" />
      <div v-else-if="myBundles.length === 0" class="bdl-empty-state">
        <Icon name="mdi:archive-outline" class="bdl-empty-icon" />
        <h3>No bundles yet</h3>
        <p>Snapshot an agent for backup, or publish a template for others to fork.</p>
        <button class="bdl-empty-cta" @click="newModalShow = true">
          <Icon name="mdi:plus" /> Create your first bundle
        </button>
      </div>
      <div v-else class="bdl-grid">
        <BundleCard v-for="b in myBundles" :key="b.id" :bundle="b"
          @view-manifest="handleViewManifest" @download="handleDownload"
          @fork="handleForkPrompt" @delete="handleDelete" @restore="handleFork" />
      </div>
    </section>

    <section v-if="activeTab === 'browse'" class="bdl-tab-panel">
      <!-- §FESUITE: with the read failed this said "Marketplace is loading" for as long as the page stayed open -->
      <ReadFailedNotice v-if="!bundlesStore.loaded && bundlesStore.error" :retry="() => bundlesStore.load({ include_official: true })" />
      <div v-else-if="publicBundles.length === 0 && officialBundles.length === 0 && orgBundles.length === 0" class="bdl-empty-state">
        <Icon name="mdi:telescope" class="bdl-empty-icon" />
        <h3>Marketplace is loading</h3>
        <p>Official sovereign-pattern templates will appear here once seeded.</p>
      </div>
      <div v-else>
        <h2 v-if="officialBundles.length" class="bdl-section-title" data-tour="bdl-official">✦ Official Sovereign Patterns</h2>
        <div v-if="officialBundles.length" class="bdl-grid">
          <BundleCard v-for="b in officialBundles" :key="b.id" :bundle="b"
            @view-manifest="handleViewManifest" @download="handleDownload" @fork="handleForkPrompt" />
        </div>
        <h2 v-if="publicBundles.filter(b => !b.is_official).length" class="bdl-section-title">Community templates</h2>
        <div v-if="publicBundles.filter(b => !b.is_official).length" class="bdl-grid">
          <BundleCard v-for="b in publicBundles.filter(b => !b.is_official)" :key="b.id" :bundle="b"
            @view-manifest="handleViewManifest" @download="handleDownload" @fork="handleForkPrompt" />
        </div>
        <h2 v-if="orgBundles.length" class="bdl-section-title" data-section="org-bundles">Shared in your organizations</h2>
        <div v-if="orgBundles.length" class="bdl-grid">
          <BundleCard v-for="b in orgBundles" :key="b.id" :bundle="b"
            @view-manifest="handleViewManifest" @download="handleDownload" @fork="handleForkPrompt" />
        </div>
      </div>
    </section>

    <section v-if="activeTab === 'restore'" class="bdl-tab-panel">
      <RestoreDropzone @restored="onCreated" />
    </section>

    <NewBundleModal :show="newModalShow" @close="newModalShow = false" @created="onCreated" />
    <BundleManifestDrawer :bundle-id="drawerBundleId" @close="closeDrawer" />

    <!-- Delete confirmation modal (replaces ugly browser confirm()) -->
    <ConfirmActionModal
      :show="!!deleteTarget"
      tone="danger"
      title="Delete bundle"
      :message="`Delete <strong>${esc(deleteTarget?.name || 'bundle')}</strong>?<br><br>This is irreversible. The bundle row + .tpb file on disk are both removed. Existing forks of this bundle are not affected.`"
      confirm-text="Delete bundle"
      cancel-text="Keep it"
      busy-text="Deleting…"
      :busy="deleting"
      @close="deleteTarget = null"
      @confirm="confirmDelete"
    />

    <!-- GÖDEL FORGE fork options — lineage royalty before the fork fires -->
    <Teleport to="body">
      <Transition name="bdl-fade">
        <div v-if="forkTarget" class="bdl-scrim" @click.self="forkTarget = null">
          <Transition name="bdl-pop">
            <div v-if="forkTarget" class="bdl-fork-modal bdl-fork-options" @click.stop>
              <header class="bdl-fork-head">
                <div>
                  <div class="bdl-fork-eyebrow">FORK — EVOLUTION WITH A LEDGER</div>
                  <h2 class="bdl-fork-title">Fork "{{ forkTarget.name || 'bundle' }}"</h2>
                  <p class="bdl-fork-subtitle">
                    The fork restores the agents as yours AND records the lineage edge. The royalty is what
                    this fork's line pays UP the ancestry whenever a descendant is paid — carved from the
                    payment, never newly issued (cap 500 bps, depth 3).
                  </p>
                </div>
              </header>
              <div class="bdl-fork-royalty-row">
                <label class="bdl-fork-royalty-label" for="fork-royalty">Royalty (bps)</label>
                <input id="fork-royalty" v-model.number="forkRoyalty" type="number" min="0" max="500" step="25"
                       class="bdl-fork-royalty-input" />
                <span class="bdl-fork-royalty-hint">{{ (Math.max(0, Math.min(500, forkRoyalty || 0)) / 100).toFixed(2) }}% of each payment to ancestors</span>
              </div>
              <div class="bdl-fork-actions">
                <button class="bdl-btn" @click="forkTarget = null">Cancel</button>
                <button class="bdl-btn bdl-btn--primary" @click="doFork">
                  <Icon name="mdi:source-branch" /> Fork with lineage
                </button>
              </div>
            </div>
          </Transition>
        </div>
      </Transition>
    </Teleport>

    <!-- Fork success modal — shows produced agent + credentials (one-time) -->
    <Teleport to="body">
      <Transition name="bdl-fade">
        <div v-if="forkResult?.success" class="bdl-scrim" @click.self="forkResult = null">
          <Transition name="bdl-pop">
            <div v-if="forkResult?.success" class="bdl-fork-modal" @click.stop>
              <header class="bdl-fork-head">
                <div>
                  <div class="bdl-fork-eyebrow">FORK SUCCESS</div>
                  <h2 class="bdl-fork-title">Agent forked from bundle</h2>
                  <p class="bdl-fork-subtitle">
                    {{ forkResult.produced_agents.length }} new agent(s) created. Credentials shown ONCE — save them now.
                  </p>
                </div>
                <button class="bdl-fork-close" @click="forkResult = null"><Icon name="mdi:close" /></button>
              </header>
              <section class="bdl-fork-body">
                <div v-for="a in forkResult.produced_agents" :key="a.did" class="bdl-fork-agent">
                  <div class="bdl-fork-row"><span class="bdl-fork-k">Agent name:</span><span class="bdl-fork-v">{{ a.name }}</span></div>
                  <div class="bdl-fork-row"><span class="bdl-fork-k">DID:</span><code class="bdl-fork-code">{{ a.did }}</code></div>
                  <div class="bdl-fork-row"><span class="bdl-fork-k">Client ID:</span><code class="bdl-fork-code">{{ a.client_id }}</code></div>
                  <div class="bdl-fork-row"><span class="bdl-fork-k">Client Secret:</span><code class="bdl-fork-code bdl-fork-secret">{{ a.client_secret }}</code></div>
                </div>
                <p v-if="forkResult.warnings?.length" class="bdl-fork-warn">
                  <Icon name="mdi:alert" />
                  {{ forkResult.warnings.join('; ') }}
                </p>
                <p class="bdl-fork-note">
                  These credentials are also saved to this browser's localStorage if you click "Use this agent now" —
                  or copy them somewhere safe and configure your runtime separately.
                </p>
              </section>
              <footer class="bdl-fork-foot">
                <button class="bdl-btn bdl-btn--ghost" @click="forkResult = null">Done</button>
                <button class="bdl-btn bdl-btn--primary" @click="copyForkCreds">
                  <Icon name="mdi:content-copy" /> Copy all credentials
                </button>
              </footer>
            </div>
          </Transition>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.bdl-view {
  min-height: 100%; position: relative; z-index: 1;
  font-family: 'IBM Plex Mono', monospace;
  padding: 1.4rem 1.6rem 2rem;
  color: #e8eaed;
}
.bdl-page-head {
  display: flex; justify-content: space-between; align-items: flex-start; gap: 1.5rem;
  padding-bottom: 1rem; margin-bottom: 1rem; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.12);
}
.bdl-page-eyebrow { font-size: 0.62rem; letter-spacing: 0.24em; color: rgba(var(--nc-primary-rgb), 0.7); font-weight: 700; margin-bottom: 0.5rem; }
.bdl-page-title { font-size: 1.8rem; font-weight: 700; margin: 0; color: #fff; letter-spacing: -0.005em; }
.bdl-page-subtitle { font-size: 0.85rem; color: #99a5b3; margin: 0.5rem 0 0; line-height: 1.5; max-width: 640px; }

.bdl-new-btn {
  display: inline-flex; align-items: center; gap: 0.4rem;
  background: linear-gradient(180deg, var(--nc-primary-bright, #00e8e8) 0%, var(--nc-primary, #00d2d2) 100%);
  border: 1px solid var(--nc-primary, #00d2d2); color: #04141f;
  font-family: 'IBM Plex Mono', monospace; font-weight: 700; font-size: 0.78rem; letter-spacing: 0.08em;
  padding: 10px 18px; border-radius: 6px; cursor: pointer;
  box-shadow: 0 4px 16px rgba(var(--nc-primary-rgb), 0.32), inset 0 1px 0 rgba(255,255,255,0.25);
  transition: background 0.18s, transform 0.08s;
}
.bdl-new-btn:hover { background: linear-gradient(180deg, #fff 0%, var(--nc-primary-bright, #00e8e8) 100%); }
.bdl-new-btn:active { transform: translateY(1px); }
.bdl-new-btn svg { width: 14px; height: 14px; }

.bdl-tabs { display: flex; gap: 0.4rem; padding-bottom: 0.6rem; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.1); margin-bottom: 1.2rem; }
.bdl-tab {
  display: inline-flex; align-items: center; gap: 0.4rem;
  background: transparent; border: 1px solid transparent;
  color: rgba(148,163,184,0.7); font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; font-weight: 600;
  padding: 8px 14px; border-radius: 5px 5px 0 0; cursor: pointer;
  transition: color 0.15s, background 0.15s, border-color 0.15s;
}
.bdl-tab:hover { color: rgba(var(--nc-primary-rgb), 0.85); background: rgba(var(--nc-primary-rgb), 0.05); }
.bdl-tab.is-active { color: var(--nc-primary); border-color: rgba(var(--nc-primary-rgb), 0.3); border-bottom-color: var(--nc-primary, #00d2d2); background: rgba(var(--nc-primary-rgb), 0.08); }
.bdl-tab svg { width: 14px; height: 14px; }
.bdl-tab-count { font-size: 0.62rem; background: rgba(var(--nc-primary-rgb), 0.18); color: var(--nc-primary, #00d2d2); padding: 1px 7px; border-radius: 3px; font-weight: 700; }

.bdl-tab-panel { padding: 0.4rem 0; }
.bdl-toolbar { display: flex; gap: 0.6rem; margin-bottom: 1rem; }
.bdl-search { flex: 1; background: rgba(0,0,0,0.4); border: 1px solid rgba(var(--nc-primary-rgb), 0.22); border-radius: 5px; padding: 8px 12px; font-family: inherit; font-size: 0.78rem; color: #e8eaed; outline: none; }
.bdl-search:focus { border-color: rgba(var(--nc-primary-rgb), 0.65); }

.bdl-loading { padding: 2rem; color: #99a5b3; text-align: center; font-style: italic; }
.bdl-empty-state {
  padding: 3rem 1.5rem; text-align: center;
  display: flex; flex-direction: column; align-items: center; gap: 0.6rem;
  background: rgba(255,255,255,0.02); border: 1px dashed rgba(var(--nc-primary-rgb), 0.18); border-radius: 8px;
}
.bdl-empty-icon { width: 52px; height: 52px; color: rgba(var(--nc-primary-rgb), 0.5); margin-bottom: 0.4rem; }
.bdl-empty-state h3 { font-size: 1.1rem; color: #e8eaed; margin: 0; }
.bdl-empty-state p { font-size: 0.82rem; color: #99a5b3; margin: 0 0 0.6rem; max-width: 320px; }
.bdl-empty-cta {
  display: inline-flex; align-items: center; gap: 0.4rem;
  background: linear-gradient(180deg, var(--nc-primary-bright, #00e8e8) 0%, var(--nc-primary, #00d2d2) 100%);
  border: 1px solid var(--nc-primary, #00d2d2); color: #04141f;
  font-family: 'IBM Plex Mono', monospace; font-weight: 700; font-size: 0.78rem;
  padding: 9px 16px; border-radius: 5px; cursor: pointer;
}
.bdl-empty-cta:hover { background: linear-gradient(180deg, #fff 0%, var(--nc-primary-bright, #00e8e8) 100%); }
.bdl-empty-cta svg { width: 14px; height: 14px; }

.bdl-section-title { font-size: 0.95rem; color: rgba(var(--nc-primary-rgb), 0.85); margin: 1.4rem 0 0.8rem; letter-spacing: 0.05em; font-weight: 700; }
.bdl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 0.8rem; }

/* Fork success modal */
.bdl-scrim { position: fixed; inset: 0; z-index: 10095; background: radial-gradient(ellipse at center, rgba(2,6,12,0.78) 0%, rgba(0,0,0,0.88) 100%); backdrop-filter: blur(8px); display: flex; align-items: center; justify-content: center; padding: 1.5rem; }
.bdl-fork-modal { width: 100%; max-width: 580px; max-height: 92vh; background: linear-gradient(180deg, rgba(8,28,16,0.97) 0%, rgba(4,16,10,0.99) 100%); border: 1px solid rgba(0,255,136,0.38); border-radius: 12px; box-shadow: 0 32px 96px rgba(0,0,0,0.78), 0 0 100px rgba(0,255,136,0.14); display: flex; flex-direction: column; overflow: hidden; color: #e8eaed; }
.bdl-fork-head { padding: 1.4rem 1.6rem 1rem; border-bottom: 1px solid rgba(0,255,136,0.18); display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
/* GÖDEL FORGE fork-options modal — violet family (the arena's accent), same skeleton */
.bdl-fork-options { border-color: rgba(139,92,246,0.45); background: linear-gradient(180deg, rgba(20,14,34,0.97) 0%, rgba(10,7,18,0.99) 100%); box-shadow: 0 32px 96px rgba(0,0,0,0.78), 0 0 100px rgba(139,92,246,0.16); }
.bdl-fork-options .bdl-fork-head { border-bottom-color: rgba(139,92,246,0.22); }
.bdl-fork-royalty-row { display: flex; align-items: center; gap: 12px; padding: 1.1rem 1.6rem; flex-wrap: wrap; }
.bdl-fork-royalty-label { font-size: 0.72rem; letter-spacing: 0.12em; opacity: 0.8; }
.bdl-fork-royalty-input { width: 96px; padding: 7px 10px; border-radius: 8px; border: 1px solid rgba(139,92,246,0.4); background: transparent; color: inherit; font-family: 'SF Mono', 'Fira Code', monospace; }
.bdl-fork-royalty-hint { font-size: 0.7rem; opacity: 0.65; }
.bdl-fork-actions { display: flex; justify-content: flex-end; gap: 8px; padding: 0 1.6rem 1.4rem; }
.bdl-fork-eyebrow { font-size: 0.6rem; letter-spacing: 0.22em; color: #00ff88; font-weight: 800; margin-bottom: 0.5rem; }
.bdl-fork-title { font-size: 1.35rem; margin: 0; color: #fff; font-weight: 700; }
.bdl-fork-subtitle { font-size: 0.78rem; color: #99a5b3; margin: 0.5rem 0 0; line-height: 1.5; }
.bdl-fork-close { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); cursor: pointer; color: #8b95a3; width: 32px; height: 32px; border-radius: 6px; display: grid; place-items: center; }
.bdl-fork-close:hover { background: rgba(255,68,68,0.12); color: #ff5252; }
.bdl-fork-close svg { width: 16px; height: 16px; }
.bdl-fork-body { padding: 1.2rem 1.6rem; overflow-y: auto; }
.bdl-fork-agent { background: rgba(0,255,136,0.06); border: 1px solid rgba(0,255,136,0.22); border-radius: 6px; padding: 0.8rem 1rem; margin-bottom: 0.7rem; }
.bdl-fork-row { display: flex; gap: 0.5rem; padding: 3px 0; font-size: 0.78rem; align-items: baseline; }
.bdl-fork-k { color: rgba(0,255,136,0.85); font-weight: 700; min-width: 120px; }
.bdl-fork-v { color: #e8eaed; font-weight: 600; }
.bdl-fork-code { background: rgba(0,0,0,0.4); padding: 3px 8px; border-radius: 3px; color: #d0d8e0; font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; word-break: break-all; }
.bdl-fork-secret { color: #fbbf24; }
.bdl-fork-warn { display: flex; align-items: center; gap: 0.4rem; margin: 0.7rem 0 0; padding: 0.6rem 0.8rem; background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.25); color: rgba(245,158,11,0.95); border-radius: 5px; font-size: 0.74rem; }
.bdl-fork-warn svg { width: 14px; height: 14px; }
.bdl-fork-note { font-size: 0.72rem; color: #6b7785; font-style: italic; margin: 0.8rem 0 0; line-height: 1.5; }
.bdl-fork-foot { padding: 1rem 1.6rem 1.2rem; border-top: 1px solid rgba(0,255,136,0.15); background: rgba(0,0,0,0.22); display: flex; gap: 0.5rem; justify-content: flex-end; }
.bdl-btn { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.55rem 1rem; border-radius: 5px; cursor: pointer; font-family: 'IBM Plex Mono', monospace; font-size: 0.74rem; font-weight: 700; letter-spacing: 0.08em; }
.bdl-btn--ghost { background: transparent; border: 1px solid rgba(var(--nc-primary-rgb), 0.25); color: rgba(var(--nc-primary-rgb), 0.8); }
.bdl-btn--ghost:hover { color: var(--nc-primary); background: rgba(var(--nc-primary-rgb), 0.05); }
.bdl-btn--primary { background: linear-gradient(180deg, #36ffa8 0%, #00ff88 100%); border: 1px solid #00ff88; color: #04141f; }
.bdl-btn--primary:hover { background: linear-gradient(180deg, #fff 0%, #36ffa8 100%); }
.bdl-btn svg { width: 13px; height: 13px; }

.bdl-fade-enter-active, .bdl-fade-leave-active { transition: opacity 0.2s; }
.bdl-fade-enter-from, .bdl-fade-leave-to { opacity: 0; }
.bdl-pop-enter-active { transition: transform 0.26s cubic-bezier(.2,.7,.3,1.25), opacity 0.18s; }
.bdl-pop-leave-active { transition: transform 0.16s ease, opacity 0.14s; }
.bdl-pop-enter-from { transform: translateY(14px) scale(0.96); opacity: 0; }
.bdl-pop-leave-to { transform: translateY(8px) scale(0.98); opacity: 0; }
</style>
