<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
// ─────────────────────────────────────────────────────────────────────────────
// §FIRMBOOKS (O-F) — the firm's books: ONE merged, time-ordered statement.
// Read-side only; ADMIN-only even when the org is publicly transparent (the
// public feed is the outside surface — the books are the inside one). Each row
// names its source (receipt card vs audit row) and carries its ref.
// ─────────────────────────────────────────────────────────────────────────────
import { ref, watch, onMounted } from 'vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'
import { apiClient } from '@/services/api/client'

const { t } = useI18n()
const props = defineProps<{ orgId: string }>()

const loading = ref(true)
const rows = ref<any[]>([])
const note = ref<string | null>(null)
const err = ref('')   // an export that failed (the rows stay)
// §FESUITE (V0577): the statement read failed: its error showed AND "No money records yet." under it (two separate
// v-if chains); a failed read now stands in the list's place, with Try again
const loadFailed = ref(false)

async function load() {
  loading.value = true; err.value = ''; loadFailed.value = false
  try {
    const { data } = await apiClient.get(`/organizations/${props.orgId}/statement`, { params: { limit: 200 } })
    rows.value = data?.rows || []
    note.value = data?.note || null
  } catch {
    rows.value = []
    loadFailed.value = true
  } finally { loading.value = false }
}

async function exportCsv() {
  // desktop app context: a plain authenticated fetch → blob save
  try {
    const r = await apiClient.get(`/organizations/${props.orgId}/statement`,
      { params: { limit: 500, format: 'csv' }, responseType: 'blob' })
    const url = URL.createObjectURL(new Blob([r.data], { type: 'text/csv' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `org-statement-${props.orgId.slice(0, 8)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e: any) {
    err.value = e?.detail || e?.message || 'Export failed'
  }
}

function fmtAt(iso: string | null): string {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString(appLocale(), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
  catch { return iso }
}

watch(() => props.orgId, load)
onMounted(load)
</script>

<template>
  <section class="ob-root" data-testid="org-books">
    <div class="ob-head">
      <h3 class="ob-title"><Icon name="mdi:clipboard" /> {{ t('orgBooks.title', 'Books') }}</h3>
      <button class="ob-btn" :disabled="loading || !rows.length" data-testid="ob-export" @click="exportCsv">
        {{ t('orgBooks.export', 'Export CSV') }}
      </button>
    </div>
    <p class="ob-lede">{{ t('orgBooks.lede', 'The merged money statement — receipt cards and audit rows, newest first. Admin-only, even when the public feed is on.') }}</p>
    <p v-if="note" class="ob-note">{{ note }}</p>
    <p v-if="err" class="ob-err" role="alert">{{ err }}</p>
    <div v-if="loading" class="ob-state">{{ t('orgBooks.loading', 'Loading…') }}</div>
    <ReadFailedNotice v-else-if="loadFailed" :retry="load" />
    <p v-else-if="!rows.length" class="ob-note" data-testid="ob-empty">{{ t('orgBooks.empty', 'No money records yet.') }}</p>
    <div v-else class="ob-tbl-wrap">
      <table class="ob-tbl" data-testid="ob-table">
        <thead><tr>
          <th>{{ t('orgBooks.when', 'When') }}</th>
          <th>{{ t('orgBooks.kind', 'Kind') }}</th>
          <th>{{ t('orgBooks.amount', 'Amount') }}</th>
          <th>{{ t('orgBooks.counterparty', 'Counterparty') }}</th>
          <th>{{ t('orgBooks.memo', 'Memo') }}</th>
          <th>{{ t('orgBooks.source', 'Source') }}</th>
        </tr></thead>
        <tbody>
          <tr v-for="(r, i) in rows" :key="i">
            <td>{{ fmtAt(r.at) }}</td>
            <td class="ob-kind">{{ r.kind }}</td>
            <td class="ob-amt">{{ r.amount ?? '—' }} {{ r.currency || '' }}</td>
            <td class="ob-cp" :title="r.counterparty || ''">{{ r.counterparty ? (r.counterparty.length > 26 ? r.counterparty.slice(0, 22) + '…' : r.counterparty) : '—' }}</td>
            <td class="ob-memo">{{ r.memo || '—' }}</td>
            <td><span class="ob-chip" :class="'ob-chip--' + r.source">{{ r.source }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.ob-root { margin-top: 28px; }
.ob-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.ob-title {
  display: flex; align-items: center; gap: 8px; margin: 0;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; font-weight: 700;
  letter-spacing: 0.15em; text-transform: uppercase; color: rgba(var(--nc-primary-rgb), 0.55);
}
.ob-btn {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.64rem; font-weight: 600;
  padding: 6px 12px; border-radius: 6px; cursor: pointer;
  background: rgba(var(--nc-primary-rgb), 0.12); border: 1px solid rgba(var(--nc-primary-rgb), 0.3);
  color: rgba(var(--nc-primary-rgb), 0.9); transition: all 0.15s;
}
.ob-btn:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), 0.2); }
.ob-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.ob-lede { font-size: 0.76rem; color: rgba(148, 163, 184, 0.5); margin: 4px 0 10px; max-width: 640px; }
.ob-note { font-size: 0.74rem; color: rgba(148, 163, 184, 0.45); }
.ob-err { font-size: 0.76rem; color: rgba(239, 68, 68, 0.85); }
.ob-state { font-size: 0.78rem; color: rgba(148, 163, 184, 0.5); padding: 8px 0; }
.ob-tbl-wrap { overflow-x: auto; }
.ob-tbl { width: 100%; border-collapse: collapse; font-size: 0.76rem; }
.ob-tbl th { text-align: left; font-size: 0.6rem; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.4; padding: 5px 10px 5px 0; }
.ob-tbl td { padding: 5px 10px 5px 0; border-top: 1px solid rgba(255, 255, 255, 0.04); color: rgba(226, 232, 240, 0.75); }
.ob-kind { font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; }
.ob-amt { font-family: 'IBM Plex Mono', monospace; white-space: nowrap; }
.ob-cp { font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; opacity: 0.6; }
.ob-memo { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ob-chip { font-size: 0.58rem; padding: 1px 6px; border-radius: 999px; background: rgba(148, 163, 184, 0.1); text-transform: uppercase; letter-spacing: 0.05em; }
.ob-chip--receipt { background: rgba(var(--nc-primary-rgb), 0.1); color: rgba(var(--nc-primary-rgb), 0.8); }
.ob-chip--audit { background: rgba(251, 191, 36, 0.1); color: rgba(251, 191, 36, 0.8); }
</style>
