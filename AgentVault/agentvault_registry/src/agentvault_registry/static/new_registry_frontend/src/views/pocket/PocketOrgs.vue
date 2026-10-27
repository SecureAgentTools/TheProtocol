<!-- ─────────────────────────────────────────────────────────────────────────────
     POCKET · Organizations (§ORGPOCKET, 2026-08-28)

     Organizations had 39 backend routes, a ten-tab desktop dashboard, and NO
     phone surface at all: `views/pocket/` contained no org view and the only
     mention of an organization anywhere in the Pocket tree was an error string
     in PocketTrade. On a phone the only way in was the desktop dashboard, where
     seven of its ten tabs were unreachable (measured: the tab row is 1082px of
     content clipped inside a 324px `overflow:hidden` panel).

     THIS IS NOT A PORT OF THOSE TEN TABS. A phone answers a short list of
     questions and hands the rest to the desktop:
        · which organizations am I in, and what am I in them
        · is anything waiting on ME
        · take me to the room (which now carries an unread count)
        · what is in the treasury
        · who else is here
     Teams, CI/CD, authority slices, governance and the audit trail stay on
     desktop, and this view says so rather than pretending they do not exist.

     ONE IMPLEMENTATION, not a second org UI: every action here is an existing
     rail — the room door is the same `/pocket/ourchat/{id}` route OrgRoomCard
     pushes, and the ownership answer is the same POST .../ownership/respond the
     desktop card uses. The drift between two copies of one surface is exactly
     what left `/balance` alive in the showcase chat and dead in OurChat.
────────────────────────────────────────────────────────────────────────────── -->
<template>
  <div class="po-wrap" ref="ptrEl" @touchstart.passive="ptr.onTouchStart" @touchmove.passive="ptr.onTouchMove" @touchend="ptr.onTouchEnd">
    <div class="pkx-ptr" :style="{ height: ptr.ptrH.value + 'px', opacity: ptr.ptrH.value ? 1 : 0 }" aria-hidden="true">
      <Icon name="mdi:refresh" :class="{ 'pkx-spin': ptr.ptrArmed.value }" />
    </div>

    <!-- ══ LIST ══════════════════════════════════════════════════════════ -->
    <template v-if="!openOrg">
      <div class="po-head">
        <h1 class="po-title">{{ t('pocket.orgs.title', 'Organizations') }}</h1>
        <span v-if="!loading" class="po-count" data-testid="po-count">{{ orgs.length }}</span>
      </div>

      <!-- §FESUITE — a link that names an organization you are not in (a shared link, a removed membership) used to
           land on your own list without a word, reading as if the link were broken. Say what happened. -->
      <p v-if="openId && !loading && !listErr" class="po-err" role="status" data-testid="po-notyours">
        {{ t('pocket.orgs.notYours', 'That link names an organization you are not a member of, or one that no longer exists. Your own organizations are below.') }}
      </p>

      <div v-if="loading" class="po-list"><div v-for="n in 3" :key="n" class="po-skel"></div></div>

      <p v-else-if="listErr" class="po-err" data-testid="po-err">{{ listErr }}</p>

      <!-- An empty list is a real answer, not a failure. -->
      <div v-else-if="!orgs.length" class="po-empty" data-testid="po-empty">
        <Icon name="mdi:office-building" class="po-empty-ico" />
        <p>{{ t('pocket.orgs.emptyTitle', 'You are not in an organization yet.') }}</p>
        <p class="po-empty-sub">{{ t('pocket.orgs.emptyBody', 'Organizations are created on the desktop. Once you are a member, this is where they live.') }}</p>
      </div>

      <ul v-else class="po-list" data-testid="po-list">
        <li v-for="o in orgs" :key="o.id">
          <!-- §FESUITE — the li stays a list item (axe: a <ul> holds only list items); the tap target inside it is the button -->
          <div class="po-card" role="button" tabindex="0"
            :data-testid="'po-org-' + o.id"
            @click="open(o.id)" @keydown.enter.prevent="open(o.id)" @keydown.space.prevent="open(o.id)">
          <div class="po-ava"><Icon name="mdi:office-building" /></div>
          <div class="po-body">
            <div class="po-name">{{ o.name }}</div>
            <div class="po-sub">
              <span v-if="o.my_role" class="po-role" :class="'po-role--' + o.my_role">{{ roleLabel(o.my_role) }}</span>
              <span v-if="o.my_role && o.member_count != null" class="po-dot">·</span>
              <span v-if="o.member_count != null">{{ memberLabel(o.member_count) }}</span>
            </div>
          </div>
          <div class="po-right">
            <!-- Something is waiting on YOU: an ownership offer outranks an
                 unread count, because one expires and the other does not. -->
            <span v-if="o.pending_owner_is_me" class="po-needs" data-testid="po-needs">{{ t('pocket.orgs.needsYou', 'Needs you') }}</span>
            <span v-else-if="unreadFor(o.id) > 0" class="po-unread" :data-testid="'po-unread-' + o.id">{{ unreadFor(o.id) }}</span>
            <Icon name="mdi:chevron-right" class="po-chev" />
          </div>
          </div>
        </li>
      </ul>
    </template>

    <!-- ══ ONE ORGANIZATION ═══════════════════════════════════════════════ -->
    <template v-else>
      <div class="po-head">
        <button class="po-back" data-testid="po-back" :aria-label="t('pocket.common.back', 'Back')" @click="close()">
          <Icon name="mdi:chevron-left" />
        </button>
        <h1 class="po-title po-title--detail">{{ openOrg.name }}</h1>
      </div>
      <div class="po-detail-sub">
        <span v-if="openOrg.my_role" class="po-role" :class="'po-role--' + openOrg.my_role">{{ roleLabel(openOrg.my_role) }}</span>
        <span v-if="openOrg.my_role && openOrg.member_count != null" class="po-dot">·</span>
        <span v-if="openOrg.member_count != null">{{ memberLabel(openOrg.member_count) }}</span>
        <span v-if="openOrgTr && openOrgTr.verified_jobs > 0" class="po-dot">·</span>
        <span v-if="openOrgTr && openOrgTr.verified_jobs > 0" data-testid="cd-po-tr">{{ openOrgTr.verified_jobs }} {{ t('chatdesk.tr.jobsWord', 'verified jobs') }}</span>
      </div>

      <!-- 1 · WAITING ON YOU. First, because it is the only thing here with a
           deadline: a transfer offer self-retires when it expires. -->
      <section v-if="openOrg.pending_owner_is_me" class="po-sec po-sec--act" data-testid="po-ownership">
        <h2 class="po-sec-title">{{ t('pocket.orgs.ownershipTitle', 'Ownership offered to you') }}</h2>
        <p class="po-sec-lede">{{ t('pocket.orgs.ownershipLede', 'The current owner has offered you this organization. Accepting makes you the owner and moves them to admin. Mandates do not transfer.') }}</p>
        <div class="po-actions">
          <button class="po-btn po-btn--primary" :disabled="busy" data-testid="po-own-accept" @click="respondOwnership(true)">
            <Icon name="mdi:check" /> {{ t('pocket.orgs.accept', 'Accept') }}
          </button>
          <button class="po-btn" :disabled="busy" data-testid="po-own-decline" @click="respondOwnership(false)">
            <Icon name="mdi:close" /> {{ t('pocket.orgs.decline', 'Decline') }}
          </button>
        </div>
        <p v-if="ownMsg" class="po-msg" data-testid="po-own-msg">{{ ownMsg }}</p>
      </section>

      <!-- 2 · THE ROOM. The door, never a second chat implementation. -->
      <section class="po-sec" data-testid="po-room">
        <h2 class="po-sec-title">{{ t('pocket.orgs.roomTitle', 'Room') }}</h2>
        <template v-if="roomFor(openOrg.id)">
          <button class="po-row po-row--tap" data-testid="po-room-open" @click="openRoom(openOrg.id)">
            <Icon name="mdi:chat" class="po-row-ico" />
            <span class="po-row-main">{{ t('pocket.orgs.roomOpen', 'Open the room') }}</span>
            <span v-if="unreadFor(openOrg.id) > 0" class="po-unread">{{ unreadFor(openOrg.id) }}</span>
            <Icon name="mdi:chevron-right" class="po-chev" />
          </button>
        </template>
        <!-- Absent from BOTH halves of the rail is a third state and must not
             read as "no room" — it means the rail could not tell us. -->
        <p v-else-if="roomKnown(openOrg.id)" class="po-sec-lede" data-testid="po-room-off">
          {{ t('pocket.orgs.roomOff', 'This organization has no room yet. An owner or admin opens it from the desktop dashboard.') }}
        </p>
        <p v-else class="po-sec-lede po-muted" data-testid="po-room-unknown">
          {{ t('pocket.orgs.roomUnknown', 'The room setting did not answer.') }}
        </p>
      </section>

      <!-- 3 · TREASURY. The org's money account lives on THIS registry, so the
           local currency is the one it is actually denominated in — the label
           is derived from where the number comes from, never from the viewer. -->
      <section v-if="canSeeMoney" class="po-sec" data-testid="po-treasury">
        <h2 class="po-sec-title">{{ t('pocket.orgs.treasuryTitle', 'Treasury') }}</h2>
        <div v-if="treasuryLoading" class="po-skel po-skel--line"></div>
        <ReadFailedNotice v-else-if="treasuryFailed" dense :retry="() => readTreasury(openId)" />
        <template v-else-if="treasury && treasury.exists">
          <div class="po-money" data-testid="po-treasury-bal">
            <span v-if="treasury.balance == null" class="po-money-val">{{ t('pocket.trade.tegUnreachable', 'TEG unreachable') }}</span>
            <template v-else>
              <span class="po-money-val">{{ amount(treasury.balance) }}</span>
              <span class="po-money-ccy">{{ localCurrency }}</span>
            </template>
          </div>
          <div class="po-did">{{ shorten(treasury.treasury_agent_did) }}</div>
          <!-- §ORGSPEND — YOUR per-transaction draw limit, only when one binds you -->
          <p v-if="myProcurementCap" class="po-proc-cap" data-testid="po-proc-cap">
            {{ t('pocket.orgs.procCap', 'Your procurement limit:') }}
            <strong>{{ myProcurementCap }} {{ localCurrency }}</strong>
            {{ t('pocket.orgs.procCapPerTx', 'per transaction') }}
          </p>
        </template>
        <p v-else class="po-sec-lede" data-testid="po-treasury-none">
          {{ t('pocket.orgs.treasuryNone', 'No treasury account yet. An owner opens one from the desktop dashboard.') }}
        </p>
      </section>

      <!-- 4 · APPROVALS waiting on an operator of this org. -->
      <section v-if="canSeeMoney && (approvals > 0 || approvalsFailed)" class="po-sec" data-testid="po-approvals">
        <h2 class="po-sec-title">{{ t('pocket.orgs.approvalsTitle', 'Spend approvals') }}</h2>
        <ReadFailedNotice v-if="approvalsFailed" dense :retry="() => readApprovals(openId)" />
        <button v-else class="po-row po-row--tap" data-testid="po-approvals-open" @click="goApprovals()">
          <Icon name="mdi:shield-account" class="po-row-ico" />
          <span class="po-row-main">{{ approvalsLabel }}</span>
          <Icon name="mdi:chevron-right" class="po-chev" />
        </button>
      </section>

      <!-- 4b · INVITED, NOT YET ARRIVED. Withdraw IS a phone act, unlike role
           changes: it is one tap, it is how you take back a typo, and it is the
           only way to free that address for a correct invitation. -->
      <OrgPendingInvitations
        v-if="canSeeMoney"
        :org-id="openOrg.id"
        :my-role="openOrg.my_role"
        @changed="loadDetail(openOrg.id)"
      />

      <!-- 5 · WHO IS HERE. Read-only on a phone: changing someone's role is a
           desktop act, and offering a control that 403s is worse than absence. -->
      <section class="po-sec" data-testid="po-members">
        <h2 class="po-sec-title">{{ t('pocket.orgs.membersTitle', 'Members') }}</h2>
        <div v-if="membersLoading" class="po-list"><div v-for="n in 3" :key="n" class="po-skel"></div></div>
        <p v-else-if="membersErr" class="po-err">{{ membersErr }}</p>
        <ul v-else class="po-mlist">
          <li v-for="m in members" :key="m.developer_id" class="po-mrow">
            <div class="po-mava">{{ initial(m.developer_name || m.developer_email) }}</div>
            <div class="po-mbody">
              <div class="po-mname">{{ m.developer_name || m.developer_email }}</div>
              <div class="po-mmail" :title="m.developer_email">{{ m.developer_email }}</div>
            </div>
            <span class="po-role" :class="'po-role--' + m.role">{{ roleLabel(m.role) }}</span>
          </li>
        </ul>
      </section>

      <p class="po-foot">{{ t('pocket.orgs.deskNote', 'Teams, agents, authority, CI/CD, governance and the audit trail are on the desktop dashboard.') }}</p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'
import { usePullToRefresh } from '@/composables/usePullToRefresh'
import { useCurrency } from '@/composables/useCurrency'
import { useAuthStore } from '@/stores/auth'
import { organizationService, type Organization, type OrganizationMember } from '@/services/api/organizationService'
import { chatApi } from '@/services/api/chat'
import OrgPendingInvitations from '@/components/organizations/OrgPendingInvitations.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { amount, localCurrency } = useCurrency()

const ptrEl = ref<HTMLElement | null>(null)
const ptr = usePullToRefresh(ptrEl, () => { void loadAll() })

const loading = ref(true)
const listErr = ref('')
const orgs = ref<Organization[]>([])
/** org_id -> the room row from EITHER half of /chat/org-rooms. `open` tells the
 *  two halves apart; absence from both is "the rail did not say", which is a
 *  third state and not the same as "no room". */
const rooms = ref<Record<string, any>>({})
const enableable = ref<Record<string, any>>({})

const busy = ref(false)
const ownMsg = ref('')
const members = ref<OrganizationMember[]>([])
const membersLoading = ref(false)
const membersErr = ref('')
const treasury = ref<any | null>(null)
const treasuryLoading = ref(false)
const approvals = ref(0)

const openId = computed(() => String(route.query.org || ''))
const openOrg = computed(() => orgs.value.find(o => o.id === openId.value) || null)

// §ORGSPEND — YOUR per-transaction treasury-draw limit in THIS org, or '' when none
// binds you. Mirrors the server resolver (org_policy.procurement_cap): a per-member
// override beats the default; 0/unset = unlimited at both levels.
const myProcurementCap = computed<string>(() => {
  const s: any = (openOrg.value as any)?.settings
  if (!s || typeof s !== 'object') return ''
  const myId = String(authStore.user?.developer_id || authStore.user?.id || '')
  const overrides = (s.procurement_limits && typeof s.procurement_limits === 'object') ? s.procurement_limits : {}
  const raw = myId && myId in overrides ? overrides[myId] : s.procurement_limit_default
  const v = Number(raw)
  return v > 0 && !Number.isNaN(v) ? String(raw) : ''
})
// §CHATDESK H1.1 — the firm's verified-jobs line (declared BELOW openOrg: an
// immediate watcher above its dep is the TDZ blank-view class, §HIRECOHERE).
const openOrgTr = ref<any>(null)
watch(openOrg, async (o) => {
  openOrgTr.value = null
  if (!o) return
  try { openOrgTr.value = await organizationService.getOrgTrackRecord(o.id) } catch { /* chip hides */ }
}, { immediate: true })
const canSeeMoney = computed(() => ['owner', 'admin'].includes(String(openOrg.value?.my_role || '')))

const roomFor = (id: string) => rooms.value[id] || null
const roomKnown = (id: string) => !!rooms.value[id] || !!enableable.value[id]
const unreadFor = (id: string) => Number(rooms.value[id]?.unread || 0)

/* §FOREIGNACT's rule, applied to authority instead of currency: a label that
   describes what someone IS must come from the field that says so, and print
   NOTHING when that field has not answered. The control run for this batch
   proved why — against the unpatched backend `my_role` was undefined and an
   earlier version of this defaulted to 'member', so the OWNER'S OWN CARD read
   "MEMBER · 0 members" about the organization they own. Empty is honest;
   a confident wrong role is not. */
const roleLabel = (r?: string | null) => {
  if (!r) return ''
  return ({
    owner: t('pocket.orgs.roleOwner', 'Owner'),
    admin: t('pocket.orgs.roleAdmin', 'Admin'),
    member: t('pocket.orgs.roleMember', 'Member'),
    guest: t('pocket.orgs.roleGuest', 'Guest'),
  } as Record<string, string>)[String(r)] || String(r)
}

/* Counted nouns compose in JS: the count renders from the template and the noun
   picks its own one/many key, so a locale is never handed English word order. */
const memberLabel = (n?: number | null) => {
  // null/undefined is "the server did not say", which is not the same as zero.
  if (n === null || n === undefined) return ''
  const c = Number(n)
  return `${c} ${c === 1 ? t('pocket.orgs.memberOne', 'member') : t('pocket.orgs.memberMany', 'members')}`
}
const approvalsLabel = computed(() =>
  `${approvals.value} ${approvals.value === 1
    ? t('pocket.orgs.approvalOne', 'approval waiting')
    : t('pocket.orgs.approvalMany', 'approvals waiting')}`)

const initial = (s?: string) => (s || '?').trim().charAt(0).toUpperCase()
const shorten = (d?: string | null) => !d ? '' : (d.length > 34 ? `${d.slice(0, 20)}…${d.slice(-8)}` : d)

async function loadAll() {
  loading.value = true; listErr.value = ''
  try {
    const [list, roomRes] = await Promise.allSettled([
      organizationService.listOrganizations(),
      chatApi.orgRooms(authStore.token || ''),
    ])
    if (list.status === 'fulfilled') orgs.value = list.value || []
    else listErr.value = t('pocket.orgs.listErr', 'Could not read your organizations.')
    if (roomRes.status === 'fulfilled') {
      const r: any = roomRes.value || {}
      rooms.value = Object.fromEntries((r.rooms || []).map((x: any) => [x.org_id, x]))
      enableable.value = Object.fromEntries((r.enableable || []).map((x: any) => [x.org_id, x]))
    }
  } finally { loading.value = false }
}

async function loadDetail(id: string) {
  ownMsg.value = ''
  membersLoading.value = true; membersErr.value = ''; members.value = []
  treasury.value = null; approvals.value = 0; treasuryFailed.value = false; approvalsFailed.value = false
  try {
    members.value = await organizationService.listMembers(id)
  } catch {
    membersErr.value = t('pocket.orgs.membersErr', 'Could not read the member list.')
  } finally { membersLoading.value = false }

  if (!canSeeMoney.value) return
  await readTreasury(id)
  await readApprovals(id)
}

// §FESUITE (V0575): a failed treasury read is not "No treasury account yet", and a failed approvals read must not
// hide the approvals an operator of this org is waiting on: each says its read failed and offers it again
const treasuryFailed = ref(false)
const approvalsFailed = ref(false)
async function readTreasury(id: string) {
  treasuryLoading.value = true; treasuryFailed.value = false
  try { treasury.value = await organizationService.getOrgTreasuryAccount(id) } catch { treasury.value = null; treasuryFailed.value = true }
  finally { treasuryLoading.value = false }
}
async function readApprovals(id: string) {
  approvalsFailed.value = false
  try {
    const a = await organizationService.listOrgSpendApprovals(id, 'pending', 50)
    approvals.value = (a?.approvals || []).length
  } catch { approvals.value = 0; approvalsFailed.value = true }
}

/* The org id rides the QUERY, so the phone back gesture returns to the list
   instead of leaving Pocket entirely. */
function open(id: string) { router.push({ query: { ...route.query, org: id } }).catch(() => {}) }
function close() { const q = { ...route.query }; delete q.org; router.push({ query: q }).catch(() => {}) }
function openRoom(id: string) {
  const cid = rooms.value[id]?.conversation_id
  router.push(cid ? `/pocket/ourchat/${cid}` : '/pocket/ourchat').catch(() => {})
}
function goApprovals() { router.push('/pocket/approvals').catch(() => {}) }

async function respondOwnership(accept: boolean) {
  if (busy.value) return
  busy.value = true; ownMsg.value = ''
  try {
    await organizationService.respondOwnershipTransfer(openId.value, accept)
    ownMsg.value = accept
      ? t('pocket.orgs.ownAccepted', 'You are now the owner.')
      : t('pocket.orgs.ownDeclined', 'Offer declined.')
    await loadAll()
  } catch (e: any) {
    ownMsg.value = String(e?.message || t('pocket.orgs.ownFailed', 'That did not go through.'))
  } finally { busy.value = false }
}

/* §FESUITE — only an organization on YOUR list is read: a link naming another (a shared link, a removed membership)
   used to ask for its member list and draw a 403 the page never mentioned; it now says so (po-notyours). */
const isMine = (id: string) => orgs.value.some((o) => o.id === id)
watch(openId, (id) => { if (id && isMine(id)) void loadDetail(id) }, { immediate: false })
onMounted(async () => { await loadAll(); if (openId.value && isMine(openId.value)) await loadDetail(openId.value) })
</script>

<style scoped>
.po-wrap { padding: 12px 14px 96px; max-width: 760px; margin: 0 auto; }
.po-head { display: flex; align-items: center; gap: 10px; margin: 4px 0 14px; }
.po-title { font-size: 1.35rem; font-weight: 700; margin: 0; color: var(--nc-text, rgba(226,232,240,0.95)); }
.po-title--detail { font-size: 1.1rem; overflow-wrap: anywhere; min-width: 0; }
.po-count { margin-left: auto; font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; color: var(--nc-text-dim, #8b98a8); }
.po-back {
  display: inline-flex; align-items: center; justify-content: center;
  width: 34px; height: 34px; flex: 0 0 auto; border-radius: 9px; cursor: pointer;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
  color: var(--nc-text-dim, #8b98a8);
}
.po-detail-sub { display: flex; align-items: center; gap: 7px; font-size: 0.8rem; color: var(--nc-text-dim, #8b98a8); margin: -6px 0 16px; }

.po-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.po-card {
  display: flex; align-items: center; gap: 12px; padding: 13px 14px; cursor: pointer;
  background: rgba(6,11,20,0.55); border: 1px solid rgba(var(--nc-primary-rgb),0.12);
  border-radius: 12px; transition: border-color 0.15s, background 0.15s;
}
.po-card:hover, .po-card:focus-visible { border-color: rgba(var(--nc-primary-rgb),0.3); background: rgba(6,11,20,0.75); }
.po-ava {
  width: 38px; height: 38px; flex: 0 0 auto; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(var(--nc-primary-rgb),0.1); color: rgba(var(--nc-primary-rgb),0.85);
}
.po-body { flex: 1 1 auto; min-width: 0; }
.po-name { font-weight: 600; font-size: 0.95rem; color: var(--nc-text, rgba(226,232,240,0.95)); overflow-wrap: anywhere; }
.po-sub { display: flex; align-items: center; gap: 6px; font-size: 0.76rem; color: var(--nc-text-dim, #8b98a8); margin-top: 3px; }
.po-dot { opacity: 0.5; }
.po-right { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.po-chev { color: rgba(148,163,184,0.45); width: 16px; height: 16px; }

.po-role {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem; letter-spacing: 0.08em;
  text-transform: uppercase; padding: 2px 7px; border-radius: 5px;
  background: rgba(255,255,255,0.05); color: rgba(148,163,184,0.8); white-space: nowrap;
}
.po-role--owner { background: rgba(234,179,8,0.12); color: rgba(250,204,21,0.9); }
.po-role--admin { background: rgba(var(--nc-primary-rgb),0.12); color: rgba(var(--nc-primary-rgb),0.9); }

.po-unread {
  min-width: 20px; height: 20px; padding: 0 6px; border-radius: 10px;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 0.68rem; font-weight: 700;
  background: rgba(var(--nc-primary-rgb),0.85); color: #061018;
}
.po-needs {
  font-size: 0.62rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
  padding: 3px 8px; border-radius: 6px;
  background: rgba(234,179,8,0.15); color: rgba(250,204,21,0.95);
}

.po-sec { margin: 0 0 18px; padding: 14px; border-radius: 12px;
  background: rgba(6,11,20,0.4); border: 1px solid rgba(var(--nc-primary-rgb),0.1); }
.po-sec--act { border-color: rgba(234,179,8,0.35); background: rgba(234,179,8,0.05); }
.po-sec-title { font-size: 0.68rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb),0.75); margin: 0 0 8px; font-family: 'IBM Plex Mono', monospace; }
.po-sec-lede { font-size: 0.82rem; line-height: 1.6; color: var(--nc-text-dim, #8b98a8); margin: 0; }
.po-muted { opacity: 0.7; }

.po-row { display: flex; align-items: center; gap: 10px; width: 100%; padding: 10px 2px;
  background: none; border: none; color: inherit; font: inherit; text-align: left; }
.po-row--tap { cursor: pointer; }
.po-row-ico { color: rgba(var(--nc-primary-rgb),0.8); width: 18px; height: 18px; flex: 0 0 auto; }
.po-row-main { flex: 1 1 auto; min-width: 0; font-size: 0.88rem; }

.po-actions { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.po-btn {
  display: inline-flex; align-items: center; gap: 6px; cursor: pointer;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; font-weight: 600; letter-spacing: 0.08em;
  padding: 9px 15px; border-radius: 8px;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
  color: rgba(226,232,240,0.85);
}
.po-btn--primary { background: rgba(var(--nc-primary-rgb),0.14); border-color: rgba(var(--nc-primary-rgb),0.35); color: rgba(var(--nc-primary-rgb),0.95); }
.po-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.po-msg { font-size: 0.8rem; margin: 10px 0 0; color: rgba(226,232,240,0.8); }

.po-money { display: flex; align-items: baseline; gap: 7px; }
.po-money-val { font-size: 1.4rem; font-weight: 700; font-family: 'IBM Plex Mono', monospace; color: var(--nc-text, rgba(226,232,240,0.95)); }
.po-money-ccy { font-size: 0.75rem; color: var(--nc-text-dim, #8b98a8); }
.po-did { font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; color: rgba(var(--nc-primary-rgb),0.5); margin-top: 5px; word-break: break-all; }
/* §ORGSPEND — the viewer's own draw limit */
.po-proc-cap { font-size: 0.72rem; color: rgba(148,163,184,0.55); margin: 8px 0 0; }
.po-proc-cap strong { color: rgba(226,232,240,0.8); font-family: 'IBM Plex Mono', monospace; font-weight: 600; }

.po-mlist { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
/* Top-aligned, not centred: a long address wraps and a centred avatar then
   floats beside the middle of a three-line block. The address is truncated to
   one line because on a phone the NAME is the identifier and three wrapped
   lines of email is noise — the full value is still there for a screen reader
   and for copy. */
.po-mrow { display: flex; align-items: flex-start; gap: 10px; }
.po-mava { width: 30px; height: 30px; flex: 0 0 auto; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; font-size: 0.8rem; font-weight: 700;
  background: rgba(var(--nc-primary-rgb),0.1); color: rgba(var(--nc-primary-rgb),0.85); }
.po-mbody { flex: 1 1 auto; min-width: 0; }
.po-mname { font-size: 0.85rem; color: var(--nc-text, rgba(226,232,240,0.9)); overflow-wrap: anywhere; }
.po-mmail { font-size: 0.7rem; color: var(--nc-text-dim, #8b98a8);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.po-skel { height: 62px; border-radius: 12px; background: rgba(255,255,255,0.04); animation: po-pulse 1.4s ease-in-out infinite; }
.po-skel--line { height: 30px; }
@keyframes po-pulse { 0%,100% { opacity: 0.5 } 50% { opacity: 0.85 } }
@media (prefers-reduced-motion: reduce) { .po-skel { animation: none } }

.po-empty { text-align: center; padding: 40px 16px; color: var(--nc-text-dim, #8b98a8); }
.po-empty-ico { font-size: 34px; opacity: 0.4; margin-bottom: 10px; }
.po-empty-sub { font-size: 0.8rem; opacity: 0.8; margin-top: 6px; }
.po-err { color: rgba(248,113,113,0.9); font-size: 0.85rem; padding: 12px 2px; }
.po-foot { font-size: 0.74rem; line-height: 1.6; color: var(--nc-text-dim, #8b98a8); opacity: 0.75; margin: 22px 2px 0; }
</style>
