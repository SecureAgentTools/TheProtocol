// §pass51 — Bundles Pinia store
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { bundlesApi, type BundleSummary, type CreateBundlePayload, type RestoreOptions, type RestoreResult } from '@/services/api/bundles'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'

export const useBundlesStore = defineStore('bundles', () => {
  const bundles = ref<BundleSummary[]>([])
  const loading = ref(false)
  const error = ref('')
  /** §FESUITE (the loading sweep): true once a list has answered; a later failed load keeps it (and the list shown). */
  const loaded = ref(false)
  const featured = ref<any[]>([])
  const lastRestoreResult = ref<RestoreResult | null>(null)
  const activeManifest = ref<any | null>(null)

  const mineSnapshots = computed(() => bundles.value.filter(b => b.kind === 'snapshot'))
  const mineTemplates = computed(() => bundles.value.filter(b => b.kind === 'template'))
  const publicTemplates = computed(() => bundles.value.filter(b => b.kind === 'template' && b.visibility === 'public'))

  async function load(opts: { kind?: string; visibility?: string; include_official?: boolean } = {}) {
    loading.value = true
    error.value = ''
    try {
      const data = await bundlesApi.list(opts)
      bundles.value = data.bundles
      loaded.value = true
    } catch (e: any) {
      error.value = e?.response?.data?.detail || e?.message || 'Failed to load bundles'
    } finally {
      loading.value = false
    }
  }

  async function loadFeatured() {
    try {
      const data = await bundlesApi.featured(12)
      featured.value = data.featured
    } catch (e) {
      // public endpoint failing is non-fatal for store
    }
  }

  async function create(payload: CreateBundlePayload) {
    loading.value = true
    error.value = ''
    try {
      const result = await bundlesApi.create(payload)
      await load()
      return result
    } catch (e: any) {
      error.value = e?.response?.data?.detail || e?.message || 'Create failed'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function download(id: string, filename = 'bundle.tpb') {
    const blob = await bundlesApi.download(id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  /**
   * §FEFRAME W1 — a restore or fork shows each new agent's secret ONCE; save them too, so the agents can be flown from
   * this browser. Minted by this console's registry, so local (no address).
   */
  function saveProduced(result: RestoreResult | any) {
    try {
      const rows = Array.isArray(result?.produced_agents) ? result.produced_agents : []
      const good = rows.filter((a: any) => a?.did && a?.client_id && a?.client_secret && !String(a.client_secret).startsWith('['))
      if (good.length) {
        agentCredentialsStore.storeMultipleCredentials(good.map((a: any) => ({
          did: a.did, client_id: a.client_id, client_secret: a.client_secret, name: a.name || undefined,
        })))
      }
    } catch { /* the result still shows the pairs */ }
  }

  async function restoreById(id: string, opts: RestoreOptions = {}) {
    const result = await bundlesApi.restoreById(id, opts)
    lastRestoreResult.value = result
    saveProduced(result)
    if (result.success) await load()
    return result
  }

  // GÖDEL FORGE: true fork — restores the agents AND records the child bundle + lineage.
  async function fork(id: string, opts: { name?: string; royalty_bps?: number } = {}) {
    const result = await bundlesApi.fork(id, opts)
    lastRestoreResult.value = result
    saveProduced(result)
    if (result.success) await load()
    return result
  }

  async function restoreFromUpload(file: File, opts: RestoreOptions = {}) {
    const result = await bundlesApi.restoreFromUpload(file, opts)
    lastRestoreResult.value = result
    saveProduced(result)
    if (result.success) await load()
    return result
  }

  async function viewManifest(id: string) {
    activeManifest.value = await bundlesApi.getManifest(id)
    return activeManifest.value
  }

  async function deleteBundle(id: string) {
    await bundlesApi.delete(id)
    bundles.value = bundles.value.filter(b => b.id !== id)
  }

  return {
    bundles, loading, loaded, error, featured, lastRestoreResult, activeManifest,
    mineSnapshots, mineTemplates, publicTemplates,
    load, loadFeatured, create, download, restoreById, fork, restoreFromUpload, viewManifest, deleteBundle,
  }
})
