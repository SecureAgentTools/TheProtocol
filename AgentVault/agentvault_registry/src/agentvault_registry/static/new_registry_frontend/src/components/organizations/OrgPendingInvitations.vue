<!-- ─────────────────────────────────────────────────────────────────────────────
     PENDING INVITATIONS — §ORGINVITE, 2026-08-28.

     Measured before this existed: an owner who mistyped an address had no route
     and no screen that would show it, no way to withdraw it, and — because
     `create_invitation` refuses a second pending invitation for the same email
     — no way to send a correct one either. The address was held for seven days
     by an invitation nobody would ever receive, and the members tab said
     nothing, because an invitation is not a membership and `list_members` reads
     a different table. The org even showed "Invite your people" ticked off with
     two invitations hanging.

     ONE COMPONENT, TWO SURFACES. The desktop members tab and the Pocket org
     detail mount this same file. Writing it twice is how `/balance` ended up
     alive in the showcase chat and dead in OurChat; it styles itself so it can
     sit in either without inheriting a parent's scoped rules it cannot see.
────────────────────────────────────────────────────────────────────────────── -->
<template>
  <section v-if="canSee" class="opi" data-testid="org-pending-invites">
    <div class="opi-head">
      <h3 class="opi-title">{{ t('orgInvites.title', 'Invitations') }}</h3>
      <span v-if="!loading && pending.length" class="opi-count" data-testid="opi-count">{{ pending.length }}</span>
    </div>

    <div v-if="loading" class="opi-skel" data-testid="opi-loading"></div>
    <p v-else-if="loadErr" class="opi-err" data-testid="opi-err">{{ loadErr }}</p>

    <!-- Nothing outstanding is a real answer and worth saying, because the
         alternative — an empty space — is what let two live invitations hide. -->
    <p v-else-if="!rows.length" class="opi-empty" data-testid="opi-empty">
      {{ t('orgInvites.none', 'Nobody has an invitation outstanding.') }}
    </p>

    <ul v-else class="opi-list">
      <li v-for="r in rows" :key="r.id" class="opi-row" :data-testid="'opi-row-' + r.id">
        <div class="opi-main">
          <div class="opi-email">{{ r.email }}</div>
          <div class="opi-meta">
            <span class="opi-role">{{ roleLabel(r.role) }}</span>
            <span class="opi-dot">·</span>
            <span :class="'opi-st opi-st--' + r.status" :data-testid="'opi-status-' + r.status">{{ statusLabel(r.status) }}</span>
            <template v-if="r.status === 'pending' && r.expires_at">
              <span class="opi-dot">·</span><span>{{ expiryLabel(r.expires_at) }}</span>
            </template>
          </div>
        </div>
        <button v-if="r.status === 'pending'" class="opi-btn" :disabled="busyId === r.id"
                :data-testid="'opi-withdraw-' + r.id" @click="withdraw(r)">
          {{ busyId === r.id ? t('orgInvites.withdrawing', 'Withdrawing…') : t('orgInvites.withdraw', 'Withdraw') }}
        </button>
      </li>
    </ul>

    <p v-if="actionMsg" class="opi-msg" data-testid="opi-msg">{{ actionMsg }}</p>
    <!-- The reason withdrawing matters, said once where it is useful rather than
         discovered by a person who cannot work out why re-inviting fails. -->
    <p v-if="rows.some(r => r.status === 'pending')" class="opi-fine">
      {{ t('orgInvites.fine', 'An address can only hold one open invitation. Withdraw it to send a new one.') }}
    </p>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { organizationService, type OrgInvitationRow } from '@/services/api/organizationService'

const { t, tp } = useI18n()
const props = defineProps<{
  orgId: string
  /** owner|admin|member|guest — the server refuses a member with a 403 anyway;
   *  this only avoids asking a question we already know the answer to. */
  myRole?: string | null
  /** show resolved invitations too (desktop has the room; Pocket does not) */
  showHistory?: boolean
}>()
const emit = defineEmits<{ (e: 'changed'): void }>()

const canSee = computed(() => ['owner', 'admin'].includes(String(props.myRole || '')))
const loading = ref(true)
const loadErr = ref('')
const all = ref<OrgInvitationRow[]>([])
const busyId = ref('')
const actionMsg = ref('')

const pending = computed(() => all.value.filter(r => r.status === 'pending'))
const rows = computed(() => props.showHistory ? all.value : pending.value)

const roleLabel = (r?: string) => ({
  owner: t('orgInvites.roleOwner', 'owner'),
  admin: t('orgInvites.roleAdmin', 'admin'),
  member: t('orgInvites.roleMember', 'member'),
  guest: t('orgInvites.roleGuest', 'guest'),
} as Record<string, string>)[String(r || 'member')] || String(r)

const statusLabel = (s?: string) => ({
  pending: t('orgInvites.stPending', 'waiting'),
  accepted: t('orgInvites.stAccepted', 'joined'),
  expired: t('orgInvites.stExpired', 'expired'),
  cancelled: t('orgInvites.stCancelled', 'withdrawn'),
} as Record<string, string>)[String(s || '')] || String(s)

const expiryLabel = (iso: string) => {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const days = Math.ceil((d.getTime() - Date.now()) / 86400000)
  if (days <= 0) return t('orgInvites.expiresToday', 'expires today')
  return tp('orgInvites.expiresIn', 'expires in {n}', {
    n: days === 1 ? t('orgInvites.dayOne', '1 day') : tp('orgInvites.dayMany', '{d} days', { d: days }),
  })
}

async function load() {
  if (!canSee.value || !props.orgId) { loading.value = false; return }
  loading.value = true; loadErr.value = ''
  try {
    all.value = await organizationService.listInvitations(props.orgId)
  } catch {
    loadErr.value = t('orgInvites.loadErr', 'The invitation list could not be read.')
  } finally { loading.value = false }
}

async function withdraw(r: OrgInvitationRow) {
  if (busyId.value) return
  busyId.value = r.id; actionMsg.value = ''
  try {
    await organizationService.revokeInvitation(props.orgId, r.id)
    actionMsg.value = tp('orgInvites.withdrawn', 'The invitation to {email} was withdrawn.', { email: r.email })
    await load()
    emit('changed')
  } catch (e: any) {
    actionMsg.value = String(e?.response?.data?.detail || e?.message || t('orgInvites.withdrawFailed', 'That did not go through.'))
  } finally { busyId.value = '' }
}

/* The org id is a PROP here rather than a route param, but the same rule applies
   as the invitation page learned the hard way: a component reused across a
   change of subject must re-read, or it shows the previous subject's answer. */
watch(() => props.orgId, (a, b) => { if (a && a !== b) void load() })
watch(canSee, v => { if (v && !all.value.length) void load() })
onMounted(load)
defineExpose({ reload: load })
</script>

<style scoped>
.opi { margin: 18px 0 0; padding: 14px 16px; border-radius: 10px;
  background: rgba(6,11,20,0.45); border: 1px solid rgba(var(--nc-primary-rgb),0.1); }
.opi-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.opi-title { margin: 0; font-family: 'IBM Plex Mono', monospace; font-size: 0.66rem;
  font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb),0.75); }
.opi-count { min-width: 18px; height: 18px; padding: 0 6px; border-radius: 9px;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 0.64rem; font-weight: 700;
  background: rgba(var(--nc-primary-rgb),0.16); color: rgba(var(--nc-primary-rgb),0.95); }
.opi-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.opi-row { display: flex; align-items: flex-start; gap: 10px; }
.opi-main { flex: 1 1 auto; min-width: 0; }
.opi-email { font-size: 0.86rem; color: var(--nc-text, rgba(226,232,240,0.9)); overflow-wrap: anywhere; }
.opi-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 2px;
  font-size: 0.72rem; color: var(--nc-text-dim, #8b98a8); }
.opi-dot { opacity: 0.5; }
.opi-role { font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.04em; }
.opi-st--pending { color: rgba(250,204,21,0.9); }
.opi-st--accepted { color: rgba(74,222,128,0.85); }
.opi-st--expired, .opi-st--cancelled { opacity: 0.65; }
.opi-btn { flex: 0 0 auto; cursor: pointer; min-height: 32px; padding: 0 12px; border-radius: 8px;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem; font-weight: 600; letter-spacing: 0.08em;
  background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.32); color: rgba(248,113,113,0.92); }
.opi-btn:hover { background: rgba(239,68,68,0.16); border-color: rgba(239,68,68,0.6); }
.opi-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.opi-empty, .opi-fine { font-size: 0.76rem; color: var(--nc-text-dim, #8b98a8); margin: 0; }
.opi-fine { margin-top: 12px; opacity: 0.72; line-height: 1.55; }
.opi-msg { font-size: 0.78rem; margin: 10px 0 0; color: rgba(226,232,240,0.82); }
.opi-err { font-size: 0.8rem; margin: 0; color: rgba(248,113,113,0.9); }
.opi-skel { height: 48px; border-radius: 8px; background: rgba(255,255,255,0.05);
  animation: opi-pulse 1.4s ease-in-out infinite; }
@keyframes opi-pulse { 0%,100% { opacity: 0.5 } 50% { opacity: 0.85 } }
@media (prefers-reduced-motion: reduce) { .opi-skel { animation: none } }
</style>
