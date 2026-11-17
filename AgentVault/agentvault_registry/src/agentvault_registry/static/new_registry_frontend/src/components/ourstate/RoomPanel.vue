<template>
  <!-- V0659 (f): a cross-frame room, at the top of its thread. Folded: its address and member count. Open: the address to
       share (and its link form), the join rule (its owner sets it), the members with the key each goes by, and, for
       the room's operators on its HOST, one menu per member. A copy on another registry shows; it never moderates. -->
  <section class="rp" data-testid="room-panel">
    <ReadFailedNotice v-if="failed" dense :retry="load" />
    <template v-else-if="info">
      <button type="button" class="rp-head" :aria-expanded="open" data-testid="room-panel-toggle" @click="open = !open">
        <Icon name="mdi:account-group" />
        <span class="rp-count" data-testid="room-member-count">{{ tp('ourstate.rooms.memberCount', '{n} members', { n: info.member_count }) }}</span>
        <span class="rp-rule" data-testid="room-rule">{{ ruleWords(info.join_rule) }}</span>
        <span v-if="!info.hosted_here" class="rp-hosted" data-testid="room-hosted-elsewhere">
          {{ tp('ourstate.rooms.hostedAt', 'hosted at {host}', { host: hostName }) }}</span>
        <Icon :name="open ? 'mdi:chevron-up' : 'mdi:chevron-down'" />
      </button>
      <div v-if="open" class="rp-body">
        <div class="rp-addr">
          <span class="rp-label">{{ t('ourstate.rooms.address', 'Address to share') }}</span>
          <code data-testid="room-address">{{ info.address }}</code>
          <button type="button" class="rp-btn" data-testid="room-copy" @click="copy(info.address)">
            {{ copied ? t('ourstate.rooms.copied', 'Copied') : t('ourstate.rooms.copy', 'Copy') }}</button>
        </div>
        <p class="rp-note">{{ t('ourstate.rooms.shareHow', 'Someone on another registry pastes this address under "Join a room" in OurChat there.') }}</p>
        <div v-if="info.i_moderate">
          <label class="rp-label" for="rp-rule">{{ t('ourstate.rooms.joinRule', 'Who may join') }}</label>
          <select id="rp-rule" :value="info.join_rule" :disabled="busy" data-testid="room-rule-select"
                  @change="act('rule', undefined, ($event.target as HTMLSelectElement).value)">
            <option v-for="r in JOIN_RULES" :key="r" :value="r">{{ ruleWords(r) }}</option>
          </select>
        </div>
        <ul class="rp-members" data-testid="room-members">
          <li v-for="m in info.members" :key="m.key" class="rp-member" :data-key="m.key">
            <span>{{ m.name }}</span>
            <span v-if="m.remote" class="rp-tag">{{ t('ourstate.rooms.remote', 'another registry') }}</span>
            <span v-if="m.role === 'owner' || m.role === 'moderator'" class="rp-tag">{{ roleWords(m.role) }}</span>
            <span v-if="m.state === 'pending'" class="rp-tag rp-tag--wait">{{ t('ourstate.rooms.asks', 'asks to join') }}</span>
            <span v-if="!m.can_post" class="rp-tag rp-tag--muted">{{ t('ourstate.rooms.muted', 'muted') }}</span>
            <span v-if="info.i_moderate" class="rp-acts">
              <button v-for="a in actsOn(m, info.my_role, null)" :key="a" type="button" class="rp-btn"
                      :disabled="busy" :data-testid="`room-act-${a}`" @click="act(a, m.key)">{{ actWords(a) }}</button>
            </span>
          </li>
        </ul>
        <!-- V0663: archive takes the room out of the lists and out of its owner's cap of 20 rooms, history kept and readable;
             close removes a room nobody has spoken in (a room with messages is archived instead) -->
        <p v-if="info.archived" class="rp-note" data-testid="room-archived-note">
          {{ t('ourstate.rooms.archivedNote', 'This room is archived: it can be read, not posted in.') }}</p>
        <div v-if="info.i_moderate && info.hosted_here" class="rp-lifecycle" data-testid="room-lifecycle">
          <button v-if="!info.archived" type="button" class="rp-btn" :disabled="busy" data-testid="room-archive" @click="act('archive')">
            {{ t('ourstate.rooms.archive', 'Archive this room') }}</button>
          <button v-else type="button" class="rp-btn" :disabled="busy" data-testid="room-unarchive" @click="act('unarchive')">
            {{ t('ourstate.rooms.unarchive', 'Unarchive this room') }}</button>
          <button type="button" class="rp-btn" :disabled="busy" data-testid="room-close" @click="closeIt">
            {{ t('ourstate.rooms.close', 'Close this room') }}</button>
          <p class="rp-note">{{ t('ourstate.rooms.lifecycleNote', 'Archiving takes the room out of your lists and out of your cap of 20 rooms; its history stays readable. Closing removes a room nobody has spoken in.') }}</p>
        </div>
        <p v-if="error" class="rp-error" data-testid="room-error">{{ error }}</p>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { chatApi, type RoomAction } from '@/services/api/chat'
import { JOIN_RULES, actsOn, type RoomMember } from '@/services/chat/rooms'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ conversationId: string; token: string }>()
const emit = defineEmits<{ (e: 'acted', action: string): void; (e: 'closed'): void }>()
const { t, tp } = useI18n()

interface RoomInfo {
  address: string
  join_rule: string
  hosted_here: boolean
  host_registry: string | null
  i_moderate: boolean
  archived?: boolean
  my_role: string
  member_count: number
  members: RoomMember[]
}

const info = ref<RoomInfo | null>(null)
const failed = ref(false)
const open = ref(false)
const busy = ref(false)
const error = ref('')
const copied = ref(false)

const hostName = computed(() => {
  try { return new URL(String(info.value?.host_registry || '')).host } catch { return String(info.value?.host_registry || '') }
})

async function load() {
  failed.value = false
  try {
    info.value = await chatApi.roomInfo(props.token, props.conversationId)
  } catch {
    failed.value = true
  }
}

async function act(action: string, member?: string, value?: string) {
  busy.value = true
  error.value = ''
  try {
    await chatApi.roomAct(props.token, props.conversationId, { action: action as RoomAction, member, value })
    emit('acted', action)
    await load()
  } catch (e: any) {
    error.value = e?.detail || e?.message || t('ourstate.rooms.actFailed', 'That did not go through.')
  } finally {
    busy.value = false
  }
}

async function closeIt() {
  busy.value = true
  error.value = ''
  try {
    await chatApi.closeRoom(props.token, props.conversationId)
    emit('closed')
  } catch (e: any) {
    error.value = e?.detail || e?.message || t('ourstate.rooms.actFailed', 'That did not go through.')
  } finally {
    busy.value = false
  }
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch { /* a browser that refuses the clipboard: the address is on screen to select */ }
}

function ruleWords(r: string) {
  return r === 'anyone' ? t('ourstate.rooms.ruleAnyone', 'anyone with the address joins')
    : r === 'request' ? t('ourstate.rooms.ruleRequest', 'joining asks the operators')
      : t('ourstate.rooms.ruleInvited', 'by invitation')
}
function roleWords(r: string) {
  return r === 'owner' ? t('ourstate.rooms.owner', 'owner') : t('ourstate.rooms.moderator', 'moderator')
}
function actWords(a: string) {
  const w: Record<string, string> = {
    accept: t('ourstate.rooms.actAccept', 'Accept'), mute: t('ourstate.rooms.actMute', 'Mute'),
    unmute: t('ourstate.rooms.actUnmute', 'Unmute'), remove: t('ourstate.rooms.actRemove', 'Remove'),
    ban: t('ourstate.rooms.actBan', 'Ban'), moderator: t('ourstate.rooms.actModerator', 'Make moderator'),
    unmoderator: t('ourstate.rooms.actUnmoderator', 'Remove moderator'),
  }
  return w[a] || a
}

onMounted(load)
watch(() => props.conversationId, load)
defineExpose({ load })
</script>

<style scoped>
.rp { border-bottom: 1px solid rgba(255,255,255,.08); padding: .35rem .75rem; }
.rp-head { display: flex; align-items: center; gap: .5rem; width: 100%; background: none; border: 0; color: inherit;
  font: inherit; font-size: .82rem; cursor: pointer; padding: .2rem 0; text-align: left; }
.rp-count { font-weight: 600; }
.rp-rule, .rp-hosted { color: #8b96a5; }
.rp-body { display: flex; flex-direction: column; gap: .5rem; padding: .4rem 0 .2rem; font-size: .82rem; }
.rp-addr { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem; }
.rp-addr code { word-break: break-all; font-size: .76rem; }
.rp-label { color: #8b96a5; }
.rp-note { margin: 0; color: #8b96a5; font-size: .76rem; }
.rp-lifecycle { display: flex; flex-wrap: wrap; gap: .4rem; align-items: center; }   /* V0663 */
.rp-members { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .3rem; }
.rp-member { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem; }
.rp-tag { font-size: .7rem; border: 1px solid rgba(255,255,255,.18); border-radius: 999px; padding: 0 .4rem; color: #b6c0cc; }
.rp-tag--wait { border-color: #c9a227; color: #e2c35a; }
.rp-tag--muted { border-color: #8b96a5; }
.rp-acts { display: inline-flex; gap: .25rem; margin-left: auto; }
.rp-btn { font-size: .74rem; padding: .1rem .45rem; border-radius: 6px; border: 1px solid rgba(255,255,255,.22);
  background: transparent; color: inherit; cursor: pointer; }
.rp-btn:disabled { opacity: .5; cursor: default; }
.rp-error { margin: 0; color: #f08a8a; }
</style>
