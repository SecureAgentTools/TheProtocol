<script setup lang="ts">
// ─────────────────────────────────────────────────────────────────────────────
// §OURCHAT-ORG — the organization's ROOM, on the desktop.
//
// The switch itself has existed since §OURSTATE-6 (`organizations.chat_enabled`
// + `chat_open_policy`, PUT /chat/org-rooms/{id}/settings). What did not exist
// was any way to reach it from the org dashboard: ten tabs, 145 mentions of
// treasury, and zero mentions of the room. An org owner on a desktop could
// administer members, agents, authority, CI/CD, treasury and governance, and
// could not answer "does this organization have a place to talk".
//
// TWO SETTINGS, AND THEY ARE DIFFERENT POWERS. `chat_enabled` is "do we have a
// room"; `chat_open_policy` is "who may decide that". The server treats the
// policy as always an owner/admin act even in an org that lets members open
// the room, because deciding who may act is not the same as acting — this card
// mirrors that split rather than collapsing it into one toggle.
//
// It also refuses to offer what the server would refuse: `may_enable` comes
// from the list rail, so a member in an owner_admin org is told why the switch
// is not theirs instead of pressing a button that 403s.
// ─────────────────────────────────────────────────────────────────────────────
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useOurChatBase } from '@/composables/useOurChatBase'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { chatApi } from '@/services/api/chat'

const { t } = useI18n()
const router = useRouter()
const { base } = useOurChatBase()
const authStore = useAuthStore()
const uiStore = useUIStore()

const props = defineProps<{ orgId: string }>()

const loading = ref(true)
const loadError = ref<string | null>(null)
const busy = ref(false)

/** The org's row, from whichever half of the rail it is in. `open` distinguishes
 *  "there is a room" from "the room could exist" — absence from BOTH is a third
 *  thing (you are not a member) and must not read as "no room". */
const room = ref<any | null>(null)
const enableable = ref<any | null>(null)
const known = computed(() => !!room.value || !!enableable.value)

const roomOn = computed(() => !!room.value)
const myRole = computed(() => String(room.value?.my_org_role || enableable.value?.my_org_role || ''))
const isOp = computed(() => myRole.value === 'owner' || myRole.value === 'admin')
/** The LIVE policy, read from whichever half of the rail answered. It is never
 *  defaulted into the select: a control that shows a default as if it were the
 *  setting is a label disagreeing with the branch, and this one is a permission. */
const policy = ref<'owner_admin' | 'members'>('owner_admin')
/** May I flip the room switch? The rail says so directly in both halves. */
const mayToggle = computed(() =>
  enableable.value ? !!enableable.value.may_enable
                   : (room.value?.may_disable ?? (isOp.value || policy.value === 'members')))

const token = computed(() => authStore.token || '')

async function load() {
  loading.value = true; loadError.value = null
  try {
    const r = await chatApi.orgRooms(token.value)
    room.value = (r.rooms || []).find((x: any) => String(x.org_id) === String(props.orgId)) || null
    enableable.value = (r.enableable || []).find((x: any) => String(x.org_id) === String(props.orgId)) || null
    const live = room.value?.policy || enableable.value?.policy
    if (live) policy.value = live
  } catch (e: any) {
    // An unreadable answer is NOT "this org has no room" — say which it is.
    loadError.value = e?.detail || e?.message || t('orgRoom.loadFailed', 'could not read the room setting')
  } finally { loading.value = false }
}
onMounted(load)

async function toggleRoom() {
  if (busy.value || !mayToggle.value) return
  const next = !roomOn.value
  busy.value = true
  try {
    await chatApi.setOrgChatSettings(token.value, props.orgId, { chat_enabled: next })
    uiStore.showSuccess(
      next ? t('orgRoom.onDoneTitle', 'Room on') : t('orgRoom.offDoneTitle', 'Room off'),
      next ? t('orgRoom.onDoneBody', 'This organization now has a room, listed for every member.')
           : t('orgRoom.offDoneBody', 'Nothing was deleted — turning it back on returns the same conversation.'))
    await load()
  } catch (e: any) {
    uiStore.showError(t('orgRoom.failedTitle', 'Room setting unchanged'),
                      e?.detail || e?.message || t('orgRoom.failedBody', 'the registry refused the change'))
  } finally { busy.value = false }
}

async function savePolicy(next: 'owner_admin' | 'members') {
  if (busy.value || !isOp.value || next === policy.value) return
  const prev = policy.value
  busy.value = true
  try {
    await chatApi.setOrgChatSettings(token.value, props.orgId, { chat_open_policy: next })
    policy.value = next
    uiStore.showSuccess(t('orgRoom.policyDoneTitle', 'Saved'),
      t('orgRoom.policyDoneBody', 'This decides who may open the room, not who may talk in it.'))
    await load()
  } catch (e: any) {
    policy.value = prev
    uiStore.showError(t('orgRoom.failedTitle', 'Room setting unchanged'),
                      e?.detail || e?.message || t('orgRoom.failedBody', 'the registry refused the change'))
  } finally { busy.value = false }
}

/** A door, not a second implementation — and it opens on the SURFACE the
 *  viewer is on: the desktop mounts land in /ourchat, Pocket stays in Pocket
 *  (§CHATDESK C2 — useOurChatBase is the one brain). */
function openRoom() {
  const id = room.value?.conversation_id
  router.push(id ? `${base.value}/${id}` : base.value)
}
</script>

<template>
  <div class="settings-section" data-testid="org-room-card">
    <h3 class="settings-section-title">
      {{ t('orgRoom.title', 'Room') }}
    </h3>
    <p class="orc-lede">
      {{ t('orgRoom.lede', 'A room is one conversation for the whole organization, hosted by this registry. Membership is the live org roster: nobody is added or removed by hand, and losing your membership removes you from the room on the next read.') }}
    </p>

    <div v-if="loading" class="orc-muted" data-testid="org-room-loading">
      {{ t('orgRoom.loading', 'Reading the room setting…') }}
    </div>

    <!-- An unreadable answer is its own state. It is not "no room". -->
    <div v-else-if="loadError" class="orc-error" data-testid="org-room-error">
      <Icon name="mdi:alert-circle-outline" />
      <span>{{ t('orgRoom.errorPrefix', 'The room setting could not be read:') }} {{ loadError }}</span>
      <button class="orc-link" @click="load">{{ t('orgRoom.retry', 'try again') }}</button>
    </div>

    <div v-else-if="!known" class="orc-muted" data-testid="org-room-unknown">
      {{ t('orgRoom.notMember', 'You are not an active member of this organization, so its room is not yours to see.') }}
    </div>

    <template v-else>
      <div class="orc-row" data-testid="org-room-switch-row">
        <div class="orc-row-text">
          <span class="orc-row-title">
            {{ roomOn ? t('orgRoom.onTitle', 'This organization has a room')
                      : t('orgRoom.offTitle', 'No room yet') }}
          </span>
          <span class="orc-row-sub">
            {{ roomOn
               ? t('orgRoom.onSub', 'It appears in OurChat for every member. Turning it off hides it; the conversation is kept.')
               : t('orgRoom.offSub', 'Turning this on creates one conversation for the organization and lists it for every member.') }}
          </span>
        </div>
        <button
          class="orc-switch" :class="{ on: roomOn, disabled: !mayToggle || busy }"
          role="switch" :aria-checked="roomOn ? 'true' : 'false'"
          :disabled="!mayToggle || busy"
          data-testid="org-room-toggle"
          @click="toggleRoom"
        ><span class="orc-knob" aria-hidden="true"></span></button>
      </div>

      <!-- Said plainly, rather than discovered by pressing a button that 403s. -->
      <p v-if="!mayToggle" class="orc-why" data-testid="org-room-why">
        {{ t('orgRoom.whyNotYou', 'This organization lets only owners and admins turn the room on. You are a') }}
        <strong>{{ myRole }}</strong>.
      </p>

      <div v-if="isOp" class="orc-row orc-row--policy" data-testid="org-room-policy-row">
        <div class="orc-row-text">
          <span class="orc-row-title">{{ t('orgRoom.policyTitle', 'Who may open the room') }}</span>
          <span class="orc-row-sub">
            {{ t('orgRoom.policySub', 'Deciding who may act is a different power from acting, so changing this is always an owner or admin decision — even where members may open the room themselves.') }}
          </span>
        </div>
        <select :aria-label="t('orgRoom.policyAria', 'Who may open the room')"
          class="orc-select" :value="policy" :disabled="busy"
          data-testid="org-room-policy"
          @change="savePolicy(($event.target as HTMLSelectElement).value as any)"
        >
          <option value="owner_admin">{{ t('orgRoom.policyOps', 'Owners and admins') }}</option>
          <option value="members">{{ t('orgRoom.policyMembers', 'Any member') }}</option>
        </select>
      </div>

      <div v-if="roomOn" class="orc-actions">
        <button class="cmd-btn" data-testid="org-room-open" @click="openRoom">
          <Icon name="mdi:chat" />
          {{ t('orgRoom.openBtn', 'Open the room') }}
        </button>
        <span v-if="room?.topic" class="orc-topic" data-testid="org-room-topic">{{ room.topic }}</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* §ORGPOCKET O3 — `.cmd-btn` and `.settings-section-title` are defined only in
   OrganizationDashboard's SCOPED block. A parent's scoped rule reaches a child's
   root node and nothing deeper, so "Open the room" — the single control that
   opens the org room — painted as a default browser button. Same class as
   §ROOMVIEW's `.ost-hosting`: markup with no rule that can reach it. */
.settings-section-title {
  font-size: 0.95rem; font-weight: 600; letter-spacing: 0.02em;
  color: var(--nc-text, rgba(226,232,240,0.95)); margin: 0 0 6px;
}
.orc-actions .cmd-btn {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; font-weight: 600; letter-spacing: 0.1em;
  padding: 8px 16px; border-radius: 6px; cursor: pointer;
  background: rgba(var(--nc-primary-rgb),0.12);
  border: 1px solid rgba(var(--nc-primary-rgb),0.3);
  color: rgba(var(--nc-primary-rgb),0.9);
  transition: all 0.15s;
}
.orc-actions .cmd-btn:hover {
  background: rgba(var(--nc-primary-rgb),0.2);
  border-color: rgba(var(--nc-primary-rgb),0.55);
}
.orc-lede { font-size: 13px; line-height: 1.6; color: var(--nc-text-dim, #8b98a8); margin: 0 0 16px; max-width: 62ch; }
.orc-muted { font-size: 13px; color: var(--nc-text-dim, #8b98a8); }
.orc-error {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  font-size: 13px; color: #f6ad55;
  background: rgba(246,173,85,.08); border: 1px solid rgba(246,173,85,.28);
  border-radius: 8px; padding: 10px 12px;
}
.orc-link { background: none; border: 0; color: inherit; text-decoration: underline; cursor: pointer; font: inherit; padding: 0; }

.orc-row {
  display: flex; align-items: center; justify-content: space-between; gap: 20px;
  padding: 14px 0; border-top: 1px solid var(--nc-border, rgba(255,255,255,.07));
}
.orc-row--policy { align-items: flex-start; }
.orc-row-text { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.orc-row-title { font-size: 14px; font-weight: 600; color: var(--nc-text, #e6edf3); }
.orc-row-sub { font-size: 12.5px; line-height: 1.55; color: var(--nc-text-dim, #8b98a8); max-width: 62ch; }

.orc-switch {
  flex: 0 0 auto; width: 46px; height: 26px; border-radius: 999px; cursor: pointer;
  background: rgba(255,255,255,.10); border: 1px solid var(--nc-border, rgba(255,255,255,.14));
  position: relative; transition: background .18s ease, border-color .18s ease;
}
.orc-switch.on { background: rgba(var(--nc-primary-rgb), .38); border-color: rgba(var(--nc-primary-rgb), .55); }
.orc-switch.disabled { opacity: .45; cursor: not-allowed; }
.orc-knob {
  position: absolute; top: 2px; left: 2px; width: 20px; height: 20px; border-radius: 50%;
  background: #e6edf3; transition: transform .18s ease;
}
.orc-switch.on .orc-knob { transform: translateX(20px); }

.orc-why { font-size: 12.5px; color: var(--nc-text-dim, #8b98a8); margin: 8px 0 0; }
.orc-why strong { color: var(--nc-text, #e6edf3); }

.orc-select {
  flex: 0 0 auto; background: var(--nc-surface-2, #111823); color: var(--nc-text, #e6edf3);
  border: 1px solid var(--nc-border, rgba(255,255,255,.14)); border-radius: 8px;
  padding: 7px 10px; font-size: 13px; cursor: pointer;
}
.orc-select:disabled { opacity: .5; cursor: not-allowed; }

.orc-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 16px; }
.orc-topic { font-size: 12.5px; color: var(--nc-text-dim, #8b98a8); font-style: italic; }
</style>
