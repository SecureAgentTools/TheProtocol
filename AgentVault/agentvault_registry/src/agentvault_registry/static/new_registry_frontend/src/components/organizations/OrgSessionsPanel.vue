<!-- V0650 (d) — the SESSIONS tab of the organization dashboard (owners and admins).

     One read-only screen for "who of our agents is here, what are they doing, and what did they call": the
     organization's presence (GET /organizations/{id}/presence: each agent's card name, live status line, last activity
     and owner), a door to the organization's room, and the MCP calls the agents made on this registry
     (GET /organizations/{id}/mcp-audit, through the shared McpAuditLogPanel in its org scope). It reads only once its
     tab is open, and once per organization. A failed read says so; it never reads as "no agents". It opens nothing: the
     room door goes to an existing room, or to the ROOM tab where the organization decides whether to have one. -->
<template>
  <div class="osp" data-testid="org-sessions">
    <template v-if="active">
      <p class="osp-lede">{{ t('orgSessions.lede', "Your organization's agents: who is here, what each says it is doing, and the MCP tools they called on this registry.") }}</p>

      <section class="osp-section">
        <ReadFailedNotice v-if="presenceFailed" :retry="loadPresence" data-testid="osp-presence-failed"
                          :text="t('orgSessions.presenceFailed', 'The presence of the organization could not be read just now.')" />
        <p v-else-if="presenceLoading && !presence" class="osp-muted">{{ t('orgSessions.loading', 'Reading…') }}</p>
        <p v-else-if="presence && !presence.agents.length" class="osp-muted" data-testid="osp-no-agents">
          {{ t('orgSessions.noAgents', 'No agent is assigned to this organization.') }}</p>
        <ul v-else-if="presence" class="osp-list">
          <li v-for="a in presence.agents" :key="a.did" class="osp-agent" :data-testid="`osp-agent-${a.did}`">
            <div class="osp-agent-head">
              <span class="osp-name" :title="a.did">{{ a.name || shortDid(a.did) }}</span>
              <span class="osp-account" :data-status="a.account_status">{{ a.account_status }}</span>
            </div>
            <div class="osp-status" :data-live="a.status ? '1' : '0'">
              {{ a.status ? a.status.text : t('orgSessions.noStatus', 'no live status') }}</div>
            <div class="osp-meta">
              <span :title="a.last_active_at ? absolute(a.last_active_at) : ''">{{ a.last_active_at
                ? tp('orgSessions.lastActive', 'active {ago} ago', { ago: agoShort(a.last_active_at) })
                : t('orgSessions.neverActive', 'never active') }}</span>
              <span v-if="a.owner_developer_id != null">· {{ ownerLabel(a.owner_developer_id) }}</span>
            </div>
          </li>
        </ul>
      </section>

      <section class="osp-section">
        <button v-if="roomId" type="button" class="osp-btn" data-testid="osp-room-open" @click="openRoom">
          {{ t('orgSessions.room.open', "Open the organization's room") }}</button>
        <template v-else-if="roomRead">
          <span class="osp-muted" data-testid="osp-room-none">{{ t('orgSessions.room.none', 'This organization has no room yet.') }}</span>
          <button type="button" class="osp-btn osp-btn--ghost" data-testid="osp-room-tab" @click="emit('go', 'room')">
            {{ t('orgSessions.room.toTab', 'Room settings') }}</button>
        </template>
        <span v-else-if="roomFailed" class="osp-muted" data-testid="osp-room-failed">{{ t('orgSessions.room.failed', "The organization's room could not be read just now.") }}</span>
      </section>

      <section class="osp-section">
        <h3 class="osp-h">{{ t('orgSessions.audit.title', 'MCP calls of the organization\'s agents') }}</h3>
        <p class="osp-muted">{{ t('orgSessions.audit.lede', 'Each call an agent made on this registry with its own credentials: the tool, when, the tier and the outcome. Never what the agent sent.') }}</p>
        <McpAuditLogPanel scope="org" :org-id="orgId" :actor-names="actorNames" storage-key="org-sessions-mcp"
                          :page-size="25" />
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import McpAuditLogPanel from '@/components/admin/McpAuditLogPanel.vue'
import { organizationService, type OrgPresence } from '@/services/api/organizationService'
import { chatApi } from '@/services/api/chat'
import { agoShort } from '@/services/cockpit/when'
import { appLocale } from '@/services/appLocale'
import { readAccessToken } from '@/services/accessToken'
import { useAuthStore } from '@/stores/auth'
import { useOrganizationStore } from '@/stores/organizations'
import { useOurChatBase } from '@/composables/useOurChatBase'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ orgId: string; active: boolean }>()
const emit = defineEmits<{ (e: 'go', tab: string): void }>()
const { t, tp } = useI18n()
const router = useRouter()
const auth = useAuthStore() as any
const orgStore = useOrganizationStore() as any
const { base } = useOurChatBase()

const presence = ref<OrgPresence | null>(null)
const presenceLoading = ref(false)
const presenceFailed = ref(false)
const roomId = ref<string | null>(null)
const roomRead = ref(false)
const roomFailed = ref(false)
let loadedFor = ''

const actorNames = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const a of presence.value?.agents || []) if (a.name) out[a.did] = a.name
  return out
})

function shortDid(did: string): string { return did.length > 18 ? `${did.slice(0, 10)}…${did.slice(-6)}` : did }
function absolute(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(appLocale())
}
function ownerLabel(id: number): string {
  const m = (orgStore.members || []).find((x: any) => Number(x.developer_id) === Number(id))
  return m?.developer_name || tp('orgSessions.ownerId', 'owner #{id}', { id })
}

async function loadPresence() {
  const org = props.orgId
  presenceLoading.value = true
  presenceFailed.value = false
  try {
    const p = await organizationService.getOrgPresence(org)
    if (org !== props.orgId) return
    presence.value = p
  } catch {
    if (org !== props.orgId) return
    presenceFailed.value = true
  } finally {
    if (org === props.orgId) presenceLoading.value = false
  }
}

async function loadRoom() {
  const org = props.orgId
  roomRead.value = roomFailed.value = false
  roomId.value = null
  try {
    const r = await chatApi.orgRooms(auth.token || readAccessToken() || '')
    if (org !== props.orgId) return
    const room = (r?.rooms || []).find((x: any) => x?.org_id === org)
    roomId.value = room?.conversation_id || null
    roomRead.value = true
  } catch {
    if (org === props.orgId) roomFailed.value = true
  }
}

function openRoom() {
  if (roomId.value) void router.push(`${base.value}/${roomId.value}`)
}

function maybeLoad() {
  if (!props.active || !props.orgId || loadedFor === props.orgId) return
  loadedFor = props.orgId
  presence.value = null
  void loadPresence()
  void loadRoom()
}

watch(() => [props.active, props.orgId], maybeLoad, { immediate: true })
</script>

<style scoped>
.osp { display: flex; flex-direction: column; gap: 14px; }
.osp-lede { margin: 0; opacity: 0.85; }
.osp-section { display: flex; flex-direction: column; gap: 8px; }
.osp-h { margin: 0; font-size: 0.95rem; letter-spacing: 0.04em; }
.osp-muted { margin: 0; opacity: 0.7; font-size: 0.9em; }
.osp-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.osp-agent { padding: 8px 10px; border: 1px solid var(--nc-border, rgba(255, 255, 255, 0.14)); border-radius: 8px; }
.osp-agent-head { display: flex; justify-content: space-between; gap: 8px; }
.osp-name { font-weight: 600; overflow-wrap: anywhere; }
.osp-account { font-size: 0.8em; opacity: 0.75; }
.osp-status { margin-top: 2px; overflow-wrap: anywhere; }
.osp-status[data-live='0'] { opacity: 0.6; font-style: italic; }
.osp-meta { margin-top: 2px; font-size: 0.8em; opacity: 0.75; display: flex; gap: 6px; flex-wrap: wrap; }
.osp-btn { align-self: flex-start; min-height: 40px; padding: 0 14px; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--nc-border, rgba(255, 255, 255, 0.3)); background: transparent; color: inherit; font: inherit; }
.osp-btn--ghost { opacity: 0.85; }
</style>
