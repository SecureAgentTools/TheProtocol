<script setup lang="ts">
// ─────────────────────────────────────────────────────────────────────────────
// §CHATDESK C3 — the room's MODERATION sheet, on the desktop org dashboard.
//
// The rails have existed since §OURSTATE-2: POST /conversations/{id}/room
// (kick / mute / unmute / mode / topic / motd), gated on the actor's LIVE org
// role, every act posted as a VISIBLE system row; GET .../members is the
// picker's data ("the /kick·/mute picker" per the service's own docstring).
// Until now they were reachable only as slash-commands in the composer. This
// sheet is a SURFACE, not a second implementation: every button calls the same
// rail the commands call, and the room thread shows the same system rows.
//
// ⚠ Scope law (deliberate): an org admin moderates the ORG ROOM only. Members'
// DMs are not reachable from here and never will be — there is no covert
// read-anything surface in this design.
// ⚠ /kick clears the SEAT only — org removal is the org rail's own explicit
// act, and a kicked member who is still an org member rejoins by reopening.
// ─────────────────────────────────────────────────────────────────────────────
import { ref, computed, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { chatApi } from '@/services/api/chat'

const { t, tp } = useI18n()
const authStore = useAuthStore()
const uiStore = useUIStore()
const props = defineProps<{ orgId: string; active?: boolean }>()

const loading = ref(false)
const err = ref<string | null>(null)
const convId = ref<string | null>(null)
const room = ref<any>(null)
const members = ref<any[]>([])
const busy = ref<string | null>(null)
const kickAsk = ref<any | null>(null)
const topicDraft = ref('')
const motdDraft = ref('')

const isOp = computed(() => !!room.value?.my_is_operator)
const tok = () => authStore.token as string
const rowKey = (m: any) => `${m.ptype}:${m.developer_id ?? m.agent_did}`

async function load() {
  if (!props.orgId) return
  loading.value = true; err.value = null
  try {
    const rooms = await chatApi.orgRooms(tok())
    const mine = (rooms?.rooms || []).find((r: any) => r.org_id === props.orgId)
    if (!mine?.conversation_id) { convId.value = null; room.value = null; members.value = []; return }
    convId.value = mine.conversation_id
    // Opening is the supported (re)entry path and materializes my row; it also
    // answers my_is_operator from the LIVE org role, which gates the buttons.
    const opened = await chatApi.openOrgRoom(tok(), props.orgId)
    room.value = opened?.room || null
    topicDraft.value = room.value?.topic || ''
    const sheet = await chatApi.roomMembers(tok(), convId.value as string)
    members.value = sheet?.members || []
  } catch (e: any) {
    err.value = e?.detail || e?.message || String(e)
  } finally { loading.value = false }
}

function targetOf(m: any) {
  return m.ptype === 'agent'
    ? { ptype: 'agent', agent_did: m.agent_did }
    : { ptype: 'developer', developer_id: m.developer_id }
}

async function act(action: 'kick' | 'mute' | 'unmute', m: any) {
  if (!convId.value) return
  busy.value = rowKey(m)
  try {
    await chatApi.roomAction(tok(), convId.value, { action, target: targetOf(m) as any })
    uiStore.showSuccess(t('orm.doneTitle', 'Done'),
      t('orm.doneBody', 'Posted as a visible system row in the room.'))
    kickAsk.value = null
    await load()
  } catch (e: any) {
    uiStore.showError(t('orm.failedTitle', 'The room refused that'),
      e?.detail || e?.message || t('orm.failedBody', 'no change was made'))
  } finally { busy.value = null }
}

async function setText(action: 'topic' | 'motd', value: string) {
  if (!convId.value) return
  busy.value = action
  try {
    await chatApi.roomAction(tok(), convId.value, { action, value })
    uiStore.showSuccess(t('orm.doneTitle', 'Done'),
      t('orm.doneBody', 'Posted as a visible system row in the room.'))
    if (action === 'motd') motdDraft.value = ''
    await load()
  } catch (e: any) {
    uiStore.showError(t('orm.failedTitle', 'The room refused that'),
      e?.detail || e?.message || t('orm.failedBody', 'no change was made'))
  } finally { busy.value = null }
}

watch(() => [props.orgId, props.active], () => { if (props.active !== false) load() }, { immediate: true })
</script>

<template>
  <div class="settings-section orm" data-testid="cd-room-mod">
    <h3 class="settings-section-title"><Icon name="mdi:gavel" /> {{ t('orm.title', 'Moderation') }}</h3>
    <p class="orm-lede">{{ t('orm.lede', 'Who is in the room and what they may do. Every action below posts a visible system row in the room — moderation here is never silent.') }}</p>

    <div v-if="loading" class="orm-muted" data-testid="orm-loading">{{ t('orm.loading', 'Loading the member sheet…') }}</div>
    <div v-else-if="err" class="orm-error" data-testid="orm-error">{{ err }}</div>
    <div v-else-if="!convId" class="orm-muted" data-testid="orm-no-room">
      {{ t('orm.noRoom', 'This organization has no open room yet — the switch above decides that.') }}
    </div>

    <template v-else>
      <p class="orm-note">
        {{ t('orm.note', 'Only members who have OPENED the room are listed; the full roster lives on the Members tab.') }}
        <span v-if="!isOp"> {{ t('orm.viewerNote', 'You can see the sheet; owner and admin act.') }}</span>
      </p>

      <table class="orm-table" data-testid="orm-table">
        <thead>
          <tr>
            <th>{{ t('orm.colMember', 'Member') }}</th>
            <th>{{ t('orm.colRole', 'Org role') }}</th>
            <th>{{ t('orm.colState', 'State') }}</th>
            <th v-if="isOp" class="orm-th-actions">{{ t('orm.colActions', 'Actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in members" :key="rowKey(m)" :data-testid="'orm-row-' + rowKey(m)">
            <td class="orm-name">
              {{ m.name || m.agent_did || m.developer_id }}
              <span v-if="m.is_me" class="orm-you">{{ t('orm.you', 'you') }}</span>
              <span v-if="m.ptype === 'agent'" class="orm-chip orm-chip--agent">agent</span>
            </td>
            <td class="orm-role">{{ m.org_role || '—' }}</td>
            <td>
              <span :class="['orm-chip', m.can_post ? 'orm-chip--ok' : 'orm-chip--muted']">
                {{ m.can_post ? t('orm.canPost', 'can post') : t('orm.muted', 'muted') }}
              </span>
            </td>
            <td v-if="isOp" class="orm-actions">
              <template v-if="!m.is_me">
                <button v-if="m.can_post" class="orm-btn" :disabled="busy === rowKey(m)"
                        :data-testid="'orm-mute-' + rowKey(m)" @click="act('mute', m)">
                  {{ t('orm.mute', 'Mute') }}</button>
                <button v-else class="orm-btn" :disabled="busy === rowKey(m)"
                        :data-testid="'orm-unmute-' + rowKey(m)" @click="act('unmute', m)">
                  {{ t('orm.unmute', 'Unmute') }}</button>
                <button class="orm-btn orm-btn--danger" :disabled="busy === rowKey(m)"
                        :data-testid="'orm-kick-' + rowKey(m)" @click="kickAsk = m">
                  {{ t('orm.kick', 'Kick') }}</button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="kickAsk" class="orm-confirm" data-testid="orm-kick-confirm">
        <p>{{ tp('orm.kickAsk', 'Kick {name} from the room? They stay in the organization and can reopen the room; this only clears their seat.', { name: kickAsk.name || '' }) }}</p>
        <div class="orm-confirm-row">
          <button class="orm-btn orm-btn--danger" data-testid="orm-kick-go" @click="act('kick', kickAsk)">{{ t('orm.confirm', 'Confirm kick') }}</button>
          <button class="orm-btn" @click="kickAsk = null">{{ t('orm.cancel', 'Cancel') }}</button>
        </div>
      </div>

      <div v-if="isOp" class="orm-textrow">
        <label class="orm-label">{{ t('orm.topicLabel', 'Topic') }}</label>
        <input v-model="topicDraft" class="orm-input" maxlength="200" data-testid="orm-topic-input" />
        <button class="orm-btn" :disabled="busy === 'topic'" data-testid="orm-topic-save"
                @click="setText('topic', topicDraft)">{{ t('orm.save', 'Save') }}</button>
      </div>
      <div v-if="isOp" class="orm-textrow">
        <label class="orm-label">{{ t('orm.motdLabel', 'Message of the day') }}</label>
        <input v-model="motdDraft" class="orm-input" maxlength="500" data-testid="orm-motd-input" />
        <button class="orm-btn" :disabled="busy === 'motd' || !motdDraft" data-testid="orm-motd-save"
                @click="setText('motd', motdDraft)">{{ t('orm.save', 'Save') }}</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* §CHATPOLISH (2026-08-30) — the SAME miss OrgRoomCard documented and fixed for
   itself: `.settings-section-title` lives only in OrganizationDashboard's SCOPED
   block, which reaches a child's root node and nothing deeper, so this panel's
   "Moderation" heading rendered as a default browser <h3>. Fixing one sibling
   and not the other is how a class survives its own post-mortem. */
.settings-section-title {
  font-size: 0.95rem; font-weight: 600; letter-spacing: 0.02em;
  color: var(--nc-text, rgba(226,232,240,0.95)); margin: 0 0 6px;
}
/* the panel sits under the room card in the ROOM tab; give it its own air */
.orm { margin-top: 1.25rem; }
.orm-role { white-space: nowrap; opacity: .8; }
.orm-lede { font-size: .82rem; opacity: .75; margin: 4px 0 10px; max-width: 72ch; }
.orm-note { font-size: .76rem; opacity: .6; margin: 0 0 10px; }
.orm-muted { font-size: .82rem; opacity: .6; padding: 8px 0; }
.orm-error { font-size: .82rem; color: var(--danger-color, #e5484d); padding: 8px 0; }
.orm-table { width: 100%; border-collapse: collapse; font-size: .84rem; }
.orm-table th { text-align: left; font-size: .68rem; letter-spacing: .06em; text-transform: uppercase;
  opacity: .55; padding: 6px 8px; border-bottom: 1px solid var(--border-color, rgba(128,128,128,.25)); }
.orm-table td { padding: 7px 8px; border-bottom: 1px solid var(--border-color, rgba(128,128,128,.12)); }
.orm-name { font-weight: 600; }
.orm-you { margin-left: 6px; font-size: .66rem; opacity: .55; border: 1px solid currentColor;
  border-radius: 8px; padding: 0 6px; }
.orm-chip { font-size: .68rem; border-radius: 9px; padding: 1px 8px; border: 1px solid transparent; }
.orm-chip--ok { color: var(--success-color, #30a46c); border-color: currentColor; }
.orm-chip--muted { color: var(--warning-color, #e5a53a); border-color: currentColor; }
.orm-chip--agent { margin-left: 6px; opacity: .6; border-color: currentColor; }
.orm-actions { text-align: right; white-space: nowrap; }
.orm-th-actions { text-align: right; }
.orm-btn { font-size: .74rem; padding: 3px 10px; border-radius: 7px; margin-left: 6px;
  border: 1px solid var(--border-color, rgba(128,128,128,.35)); background: transparent;
  color: inherit; cursor: pointer; }
.orm-btn:disabled { opacity: .45; cursor: default; }
.orm-btn--danger { color: var(--danger-color, #e5484d); border-color: currentColor; }
.orm-confirm { margin: 10px 0; padding: 10px 12px; border: 1px solid var(--danger-color, #e5484d);
  border-radius: 8px; font-size: .82rem; }
.orm-confirm-row { display: flex; gap: 8px; margin-top: 8px; }
.orm-textrow { display: flex; align-items: center; gap: 8px; margin-top: 10px; }
.orm-label { font-size: .74rem; opacity: .65; min-width: 140px; }
.orm-input { flex: 1; font-size: .82rem; padding: 5px 8px; border-radius: 7px;
  border: 1px solid var(--border-color, rgba(128,128,128,.35)); background: transparent; color: inherit; }
</style>
