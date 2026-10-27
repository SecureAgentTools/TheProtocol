<template>
  <div class="ap-root" data-tour="org-authority-panel">
    <p class="ap-intro">
      {{ t('orgAgentAuthority.intro', 'Org authority is an IRONKEY delegation grant: it adds a permission slice on top of an agent\'s own roles, and it only bites when the agent presents an org-acting token (act.sub = org:…). Revoking collapses the authority on the very next request.') }}
    </p>

    <!-- A1 catalog: the four default slices -->
    <section class="ap-sec" data-tour="org-authority-catalog">
      <header class="ap-h">{{ t('orgAgentAuthority.catalogTitle', 'AUTHORITY LEVELS (default slices)') }}</header>
      <div v-if="catalogLoading" class="ap-muted">{{ t('orgAgentAuthority.loading', 'Loading…') }}</div>
      <div v-else class="ap-levels">
        <div v-for="row in catalogRows" :key="row.role" class="ap-level">
          <div class="ap-level-head">
            <span :class="['ap-role-badge', 'ap-role--' + row.role]">{{ row.role.toUpperCase() }}</span>
            <span class="ap-muted">{{ row.permissions.length }} {{ t('orgAgentAuthority.perms', 'perms') }}</span>
          </div>
          <div class="ap-chips">
            <span v-for="p in row.adds" :key="p" class="ap-chip ap-chip--add" :title="[t('orgAgentAuthority.addsTitle', 'added at this level'), permissionTitle(p)].filter(Boolean).join(' · ')">{{ permissionLabel(p) }}</span>
          </div>
        </div>
      </div>
      <p class="ap-note">{{ t('orgAgentAuthority.neverNote', 'Never in any slice (always an explicit per-agent act):') }} <code>{{ neverIncluded.join(', ') }}</code></p>

      <!-- A4: bulk apply / revoke across every org agent -->
      <div v-if="canEdit && agents.length" class="ap-bulk" data-tour="org-authority-bulk">
        <span class="ap-bulk-label">{{ t('orgAgentAuthority.bulkLabel', 'APPLY TO ALL') }} ({{ agents.length }})</span>
        <button
          v-for="row in catalogRows" :key="'bulk-' + row.role"
          class="ap-btn" :disabled="bulkBusy"
          :title="t('orgAgentAuthority.bulkTitle', 'Upsert this slice for every org agent (idempotent)')"
          @click="bulkApply(row.role)"
        >{{ row.role.toUpperCase() }}</button>
        <button class="ap-btn ap-btn--danger" :disabled="bulkBusy" @click="bulkRevoke">
          {{ t('orgAgentAuthority.bulkRevokeBtn', 'REVOKE ALL') }}
        </button>
      </div>
    </section>

    <!-- per-agent authority -->
    <section class="ap-sec" data-tour="org-authority-agents">
      <header class="ap-h">
        {{ t('orgAgentAuthority.agentsTitle', 'ORG AGENTS · GRANTED AUTHORITY') }}
        <span class="ap-muted">({{ agents.length }})</span>
      </header>
      <div v-if="grantsLoading" class="ap-muted">{{ t('orgAgentAuthority.loading', 'Loading…') }}</div>
      <ReadFailedNotice v-else-if="grantsFailed && agents.length" :retry="loadGrants" data-testid="ap-grants-failed" />
      <div v-else-if="!agents.length" class="ap-muted ap-empty">
        {{ t('orgAgentAuthority.noAgents', 'No agents assigned to this organization yet — assign one under the Agents tab first.') }}
      </div>
      <div v-else class="ap-agent-rows">
        <div v-for="a in agents" :key="a.did" class="ap-agent-row">
          <div class="ap-agent-id">
            <span class="ap-agent-name">{{ a.name || (a.did || '').slice(0, 22) }}</span>
            <span class="ap-agent-did">{{ (a.did || '').slice(0, 34) }}…</span>
          </div>
          <div class="ap-agent-grant">
            <template v-if="grantFor(a.did)">
              <div class="ap-chips">
                <span v-for="p in grantFor(a.did)!.permissions" :key="p" class="ap-chip ap-chip--org" :title="permissionTitle(p)">{{ permissionLabel(p) }}</span>
              </div>
              <span v-if="!grantFor(a.did)!.org_linked" class="ap-warn" :title="t('orgAgentAuthority.unlinkedTitle', 'The agent is not linked to this org, so this grant resolves to nothing (linkage tenet).')">
                {{ t('orgAgentAuthority.unlinked', '⚠ not org-linked — inert') }}
              </span>
            </template>
            <span v-else class="ap-muted">{{ t('orgAgentAuthority.noGrant', 'no org authority granted') }}</span>
          </div>
          <div v-if="canEdit" class="ap-agent-actions">
            <button
              v-for="row in catalogRows" :key="row.role"
              class="ap-btn"
              :class="{ 'ap-btn--active': grantMatchesSlice(a.did, row) }"
              :disabled="busyDid === a.did"
              :title="t('orgAgentAuthority.applyTitle', 'Grant this slice (upserts the org grant)')"
              @click="applySlice(a, row)"
            >{{ row.role.toUpperCase() }}</button>
            <button
              v-if="grantFor(a.did)"
              class="ap-btn ap-btn--danger"
              :disabled="busyDid === a.did"
              @click="revoke(a)"
            >{{ t('orgAgentAuthority.revokeBtn', 'REVOKE') }}</button>
          </div>
        </div>
      </div>
      <p class="ap-note">
        {{ t('orgAgentAuthority.actNote', 'Agent side: the agent obtains its org-acting token itself via POST /api/v1/agents/act-token {"act_as": "org:' ) }}{{ orgSlug }}{{ t('orgAgentAuthority.actNote2', '"} — refused unless a live grant exists.') }}
      </p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { organizationService } from '@/services/api/organizationService'
import { agentDelegationApi } from '@/services/api/agentDelegation'
import { useUIStore } from '@/stores/ui'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { permissionLabel, permissionTitle } from '@/services/permissionLabel'

const props = defineProps<{
  orgId: string
  orgSlug: string
  agents: any[]
  canEdit: boolean
}>()
const emit = defineEmits<{ changed: [] }>()

const { t } = useI18n()
const uiStore = useUIStore()

const catalogRows = ref<{ role: string; permissions: string[]; adds: string[] }[]>([])
const neverIncluded = ref<string[]>([])
const catalogLoading = ref(false)
const grants = ref<Record<string, { grant_id: number; permissions: string[]; org_linked: boolean }>>({})
const grantsLoading = ref(false)
// §FESUITE (V0577): a grants read that failed is not "no org authority granted" on every agent (with a Grant button over
// grants that may exist). The panel is shown to owners and admins only (the dashboard's tab), for whom the read answers;
// any failure says so here (the service throws a plain Error, so a refusal cannot be told apart, and says so too)
const grantsFailed = ref(false)
const busyDid = ref('')
const bulkBusy = ref(false)

const orgSlug = computed(() => props.orgSlug)

function grantFor(did: string) {
  return grants.value[did] || null
}
function grantMatchesSlice(did: string, row: { permissions: string[] }) {
  const g = grantFor(did)
  if (!g) return false
  const a = [...g.permissions].sort().join('|')
  const b = [...row.permissions].sort().join('|')
  return a === b
}

async function loadCatalog() {
  catalogLoading.value = true
  try {
    const c = await organizationService.getOrgAuthzCatalog(props.orgId)
    catalogRows.value = c.roles
    neverIncluded.value = c.never_included
  } catch (e: any) {
    uiStore.showError(t('orgAgentAuthority.catalogErr', 'Catalog failed'), e?.message || '')
  } finally {
    catalogLoading.value = false
  }
}

async function loadGrants() {
  grantsLoading.value = true
  grantsFailed.value = false
  try {
    const r = await organizationService.getOrgAuthorityGrants(props.orgId)
    const map: Record<string, any> = {}
    for (const g of r.grants) map[g.agent_did] = g
    grants.value = map
  } catch (e: any) {
    // non-admin members never see this panel (the dashboard mounts it behind the owner/admin tab); for the rest the
    // read failed: say so rather than draw every agent as holding no grant
    grants.value = {}
    grantsFailed.value = true
  } finally {
    grantsLoading.value = false
  }
}

async function applySlice(agent: any, row: { role: string; permissions: string[] }) {
  busyDid.value = agent.did
  try {
    await agentDelegationApi.createGrant(agent.did, {
      principal_type: 'org',
      principal_ref: `org:${props.orgSlug}`,
      permissions: row.permissions,
    })
    uiStore.showSuccess(
      t('orgAgentAuthority.granted', 'Authority granted'),
      `${row.role.toUpperCase()} → ${agent.name || agent.did}`
    )
    await loadGrants()
    emit('changed')
  } catch (e: any) {
    uiStore.showError(t('orgAgentAuthority.grantErr', 'Grant failed'), e?.message || '')
  } finally {
    busyDid.value = ''
  }
}

async function revoke(agent: any) {
  const g = grantFor(agent.did)
  if (!g) return
  busyDid.value = agent.did
  try {
    await agentDelegationApi.revokeGrant(g.grant_id)
    uiStore.showSuccess(
      t('orgAgentAuthority.revoked', 'Authority revoked'),
      t('orgAgentAuthority.revokedBody', 'The agent loses the org slice on its next request.')
    )
    await loadGrants()
    emit('changed')
  } catch (e: any) {
    uiStore.showError(t('orgAgentAuthority.revokeErr', 'Revoke failed'), e?.message || '')
  } finally {
    busyDid.value = ''
  }
}

async function bulkApply(role: string) {
  bulkBusy.value = true
  try {
    const r = await organizationService.bulkApplyAuthority(props.orgId, role as any)
    uiStore.showSuccess(
      t('orgAgentAuthority.bulkApplied', 'Authority applied org-wide'),
      `${role.toUpperCase()} → ${r.agents} ${t('orgAgentAuthority.agentsWord', 'agents')}`
    )
    await loadGrants()
    emit('changed')
  } catch (e: any) {
    uiStore.showError(t('orgAgentAuthority.bulkErr', 'Bulk apply failed'), e?.message || '')
  } finally {
    bulkBusy.value = false
  }
}

async function bulkRevoke() {
  bulkBusy.value = true
  try {
    const r = await organizationService.bulkRevokeAuthority(props.orgId)
    uiStore.showSuccess(
      t('orgAgentAuthority.bulkRevoked', 'Org authority revoked'),
      `${r.revoked} ${t('orgAgentAuthority.grantsWord', 'grants')}`
    )
    await loadGrants()
    emit('changed')
  } catch (e: any) {
    uiStore.showError(t('orgAgentAuthority.bulkRevokeErr', 'Bulk revoke failed'), e?.message || '')
  } finally {
    bulkBusy.value = false
  }
}

onMounted(() => { loadCatalog(); loadGrants() })
</script>

<style scoped>
.ap-root { display: flex; flex-direction: column; gap: 18px; }
.ap-intro { font-size: 0.78rem; color: rgba(148,163,184,0.55); line-height: 1.5; margin: 0; }
.ap-sec { border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 14px 16px; background: rgba(255,255,255,0.015); }
.ap-h {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.66rem; font-weight: 700;
  letter-spacing: 0.12em; color: rgba(var(--nc-primary-rgb),0.75); margin-bottom: 12px;
}
.ap-muted { color: rgba(148,163,184,0.4); font-size: 0.72rem; }
.ap-empty { padding: 8px 0; }
.ap-note { font-size: 0.68rem; color: rgba(148,163,184,0.35); margin: 10px 0 0; line-height: 1.5; }
.ap-note code { font-size: 0.62rem; color: rgba(148,163,184,0.5); }

.ap-bulk {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  margin-top: 12px; padding-top: 12px; border-top: 1px dashed rgba(255,255,255,0.07);
}
.ap-bulk-label {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem; font-weight: 700;
  letter-spacing: 0.1em; color: rgba(148,163,184,0.5); margin-right: 4px;
}
.ap-levels { display: flex; flex-direction: column; gap: 10px; }
.ap-level { display: flex; flex-direction: column; gap: 6px; }
.ap-level-head { display: flex; align-items: center; gap: 10px; }
.ap-role-badge {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem; font-weight: 700;
  letter-spacing: 0.1em; padding: 2px 9px; border-radius: 12px; border: 1px solid transparent;
}
.ap-role--guest  { background: rgba(148,163,184,0.08); color: rgba(148,163,184,0.7); border-color: rgba(148,163,184,0.2); }
.ap-role--member { background: rgba(41,182,246,0.08);  color: rgba(41,182,246,0.85); border-color: rgba(41,182,246,0.22); }
.ap-role--admin  { background: rgba(var(--nc-primary-rgb),0.08); color: rgba(var(--nc-primary-rgb),0.85); border-color: rgba(var(--nc-primary-rgb),0.22); }
.ap-role--owner  { background: rgba(255,215,0,0.08);   color: #ffd700; border-color: rgba(255,215,0,0.25); }

.ap-chips { display: flex; flex-wrap: wrap; gap: 4px; }
.ap-chip {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem;
  padding: 2px 7px; border-radius: 4px;
  background: rgba(255,255,255,0.04); color: rgba(148,163,184,0.6);
  border: 1px solid rgba(255,255,255,0.07);
}
.ap-chip--add { color: rgba(148,163,184,0.75); }
.ap-chip--org { background: rgba(var(--nc-primary-rgb),0.06); color: rgba(var(--nc-primary-rgb),0.8); border-color: rgba(var(--nc-primary-rgb),0.18); }

.ap-agent-rows { display: flex; flex-direction: column; gap: 10px; }
.ap-agent-row {
  display: flex; flex-wrap: wrap; align-items: center; gap: 12px;
  padding: 10px 12px; border: 1px solid rgba(255,255,255,0.05); border-radius: 7px;
  background: rgba(255,255,255,0.015);
}
.ap-agent-id { display: flex; flex-direction: column; min-width: 200px; }
.ap-agent-name { font-size: 0.82rem; color: rgba(226,232,240,0.85); }
.ap-agent-did { font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem; color: rgba(148,163,184,0.35); }
.ap-agent-grant { flex: 1; min-width: 220px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ap-warn { font-size: 0.64rem; color: rgba(255,180,80,0.85); }
.ap-agent-actions { display: flex; gap: 6px; }
.ap-btn {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.58rem; font-weight: 700;
  letter-spacing: 0.08em; padding: 4px 9px; border-radius: 5px; cursor: pointer;
  background: rgba(255,255,255,0.03); color: rgba(148,163,184,0.6);
  border: 1px solid rgba(255,255,255,0.1); transition: all 0.12s;
}
.ap-btn:hover:not(:disabled) { border-color: rgba(var(--nc-primary-rgb),0.4); color: rgba(var(--nc-primary-rgb),0.85); }
.ap-btn:disabled { opacity: 0.4; cursor: default; }
.ap-btn--active { border-color: rgba(var(--nc-primary-rgb),0.5); color: rgba(var(--nc-primary-rgb),0.9); background: rgba(var(--nc-primary-rgb),0.07); }
.ap-btn--danger { color: rgba(255,120,120,0.7); }
.ap-btn--danger:hover:not(:disabled) { border-color: rgba(255,120,120,0.45); color: rgba(255,120,120,0.9); }
</style>
