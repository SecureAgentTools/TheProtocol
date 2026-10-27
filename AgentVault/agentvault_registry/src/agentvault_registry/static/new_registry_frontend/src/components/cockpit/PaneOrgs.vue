<script setup lang="ts">
/**
 * §COCKPITDESK (2026-10-15) — ORGANIZATIONS: the firms you belong to, your role in each, and the spend approvals
 * their agents are waiting on.
 *
 * Over `GET /organizations` (each row carries `my_role` and `pending_owner_is_me`). For a firm where you are an
 * owner or admin it also asks `GET /organizations/{id}/spend-approvals?status=pending` (B3 oversight, read-only),
 * for at most four firms, so a person in many firms does not turn one pane into dozens of reads. The approvals
 * are decided by each agent's own developer (Settings, Approvals), not here and not by the firm, so the pane
 * counts them as waiting, not as waiting on you; a firm whose approvals could not be read says so in its row.
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { apiClient } from '@/services/api/client'
import PaneShell from './PaneShell.vue'
import RecordLink from './RecordLink.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import { reportAttention, clearAttention } from '@/services/cockpit/attention'
import { useI18n } from '@/composables/useI18n'
import { PANES } from './paneRegistry'

const { t, tp } = useI18n()
const def = PANES.orgs
const OVERSIGHT_READS = 4

interface Org {
  id: string; name: string; role: string; members: number; agents: number | null
  ownerPending: boolean
  /** null = not asked (not an owner/admin, or past the read budget); -1 = the read failed. */
  waiting: number | null
}

const orgs = ref<Org[]>([])
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)
let poll: ReturnType<typeof setInterval> | null = null

const OVERSEERS = new Set(['owner', 'admin'])

async function load() {
  try {
    const r = await apiClient.get('/organizations')
    const rows: any[] = Array.isArray(r.data) ? r.data : (Array.isArray(r.data?.organizations) ? r.data.organizations : [])
    const next: Org[] = rows.map(o => ({
      id: String(o?.id ?? ''), name: String(o?.name || o?.slug || ''),
      role: String(o?.my_role || '').toLowerCase(),
      members: Number(o?.member_count) || 0,
      agents: o?.agent_count === undefined || o?.agent_count === null ? null : Number(o.agent_count) || 0,
      ownerPending: o?.pending_owner_is_me === true,
      waiting: null,
    }))
    const asked = next.filter(o => OVERSEERS.has(o.role)).slice(0, OVERSIGHT_READS)
    await Promise.all(asked.map(async o => {
      try {
        const a = await apiClient.get(`/organizations/${encodeURIComponent(o.id)}/spend-approvals`, { params: { status: 'pending', limit: 50 } })
        o.waiting = Number(a.data?.count ?? (Array.isArray(a.data?.approvals) ? a.data.approvals.length : 0)) || 0
      } catch { o.waiting = -1 }
    }))
    orgs.value = next
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 120) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null; clearAttention('orgs') })

const empty = computed(() => !loading.value && orgs.value.length === 0)
const waitingTotal = computed(() => orgs.value.reduce((n, o) => n + (o.waiting && o.waiting > 0 ? o.waiting : 0), 0))
watch(waitingTotal, (n) => reportAttention('orgs', n, n === 1 ? t('cockpit.attn.orgsOne', '1 spend approval pending in your organizations')
  : tp('cockpit.attn.orgs', '{n} spend approvals pending in your organizations', { n }), 'info'), { immediate: true })
/** Waiting first, then the firms you run, then the rest by name. */
const ordered = computed(() => [...orgs.value].sort((a, b) =>
  Number(b.ownerPending) - Number(a.ownerPending) ||
  (b.waiting ?? 0) - (a.waiting ?? 0) ||
  Number(OVERSEERS.has(b.role)) - Number(OVERSEERS.has(a.role)) ||
  a.name.localeCompare(b.name)))

/** Each role a literal key, so the bundle gate can see every one; a role this build does not know prints as it came. */
function roleText(role: string): string {
  switch (role) {
    case 'owner': return t('cockpit.org.role.owner', 'owner')
    case 'admin': return t('cockpit.org.role.admin', 'admin')
    case 'member': return t('cockpit.org.role.member', 'member')
    case 'guest': return t('cockpit.org.role.guest', 'guest')
    default: return role || t('cockpit.org.role.unknown', 'member')
  }
}
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="t('cockpit.org.empty', 'You belong to no organization on this registry.')">
    <div class="org" data-testid="ckd-orgs">
      <p class="org-head" data-testid="org-head" :class="{ 'is-warn': waitingTotal > 0 }">
        {{ orgs.length === 1 ? t('cockpit.org.headOrgOne', '1 organization') : tp('cockpit.org.headOrgs', '{n} organizations', { n: orgs.length }) }}
        · {{ waitingTotal === 1 ? t('cockpit.org.headWaitingOne', '1 spend approval pending') : tp('cockpit.org.headWaiting', '{n} spend approvals pending', { n: waitingTotal }) }}
      </p>
      <ul class="org-list">
        <li v-for="o in ordered" :key="o.id" class="org-row" data-testid="org-row">
          <span class="org-name" :title="o.name">{{ o.name }}</span>
          <span class="org-role">{{ roleText(o.role) }}</span>
          <span class="org-meta">
            {{ o.members === 1 ? t('cockpit.org.memberOne', '1 member') : tp('cockpit.org.members', '{n} members', { n: o.members }) }}
            <template v-if="o.agents !== null"> · {{ o.agents === 1 ? t('cockpit.org.agentOne', '1 agent') : tp('cockpit.org.agents', '{n} agents', { n: o.agents }) }}</template>
            <template v-if="o.waiting !== null && o.waiting > 0">
              · <span class="org-wait" data-testid="org-waiting">{{ tp('cockpit.org.waiting', '{n} pending', { n: o.waiting }) }}</span>
            </template>
            <template v-else-if="o.waiting === -1">
              · <span class="org-unread">{{ t('cockpit.org.unread', 'approvals unread') }}</span>
            </template>
          </span>
          <span v-if="o.ownerPending" class="org-owner" data-testid="org-owner-pending">
            {{ t('cockpit.org.ownerPending', 'ownership is being handed to you: accept it on the organization page') }}
          </span>
        </li>
      </ul>
      <p class="org-foot" data-testid="org-foot">
        {{ t('cockpit.org.foot', "A spend approval is decided by the agent's own developer; the firm's owners and admins see it here.") }}
        <RecordLink kind="organization" class="ckd-doorsep" :label="t('cockpit.door.organization', 'Open organizations')" />
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.org { display: flex; flex-direction: column; gap: .35rem; }
.org-head { margin: 0; font-size: .72rem; color: var(--nc-text-secondary, #c9d1d9); }
.org-head.is-warn { color: var(--nc-warning, #d29922); }
.org-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .35rem; }
.org-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: .5rem; row-gap: .05rem; min-width: 0; }
.org-name { font-size: .72rem; font-weight: 600; color: var(--nc-text-primary, #e6edf3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.org-role { font-size: .58rem; letter-spacing: .06em; text-transform: uppercase; color: var(--nc-text-muted, #8b949e);
  border: 1px solid var(--nc-border, rgba(255,255,255,.14)); border-radius: 999px; padding: 0 .4rem; align-self: center; }
.org-meta { grid-column: 1 / -1; font-size: .64rem; color: var(--nc-text-muted, #8b949e); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.org-wait { color: var(--nc-warning, #d29922); }
.org-unread { color: var(--nc-text-muted, #8b949e); font-style: italic; }
.org-owner { grid-column: 1 / -1; font-size: .64rem; color: var(--nc-primary, #00e5ff); }
.org-foot { margin: .2rem 0 0; font-size: .62rem; color: var(--nc-text-muted, #8b949e); }
.ckd-doorsep { margin-left: .4rem; }
</style>
