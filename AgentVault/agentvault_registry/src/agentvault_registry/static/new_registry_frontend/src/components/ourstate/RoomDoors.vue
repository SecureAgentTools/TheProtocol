<template>
  <!-- V0659 (f): the chat list's doors to cross-frame rooms. "Open a room" makes one hosted here, owned by the speaking
       principal, with its join rule; "Join a room" takes a room's address (room:<id>@https://its.registry), here or on
       another registry. A ?join=<address> link fills the address in and waits for the press: a link never joins anyone
       on its own. -->
  <div class="rd" data-testid="room-doors">
    <div class="rd-row">
      <button type="button" class="rd-door" data-testid="room-open-door" @click="toggle('open')">
        <Icon name="mdi:account-group" /> <span>{{ t('ourstate.rooms.openDoor', 'Open a room') }}</span></button>
      <button type="button" class="rd-door" data-testid="room-join-door" @click="toggle('join')">
        <Icon name="mdi:link-variant" /> <span>{{ t('ourstate.rooms.joinDoor', 'Join a room') }}</span></button>
    </div>
    <form v-if="mode === 'open'" class="rd-form" data-testid="room-open-form" @submit.prevent="openRoom">
      <label class="rd-label" for="rd-title">{{ t('ourstate.rooms.title', 'Room name') }}</label>
      <input id="rd-title" v-model="title" class="rd-in" maxlength="160" data-testid="room-title" />
      <label class="rd-label" for="rd-rule">{{ t('ourstate.rooms.joinRule', 'Who may join') }}</label>
      <select id="rd-rule" v-model="rule" class="rd-in" data-testid="room-rule">
        <option value="invited">{{ t('ourstate.rooms.ruleInvited', 'by invitation') }}</option>
        <option value="request">{{ t('ourstate.rooms.ruleRequest', 'joining asks the operators') }}</option>
        <option value="anyone">{{ t('ourstate.rooms.ruleAnyone', 'anyone with the address joins') }}</option>
      </select>
      <button type="submit" class="rd-go" :disabled="busy || !title.trim()" data-testid="room-open-go">
        {{ t('ourstate.rooms.openGo', 'Open the room') }}</button>
    </form>
    <form v-if="mode === 'join'" class="rd-form" data-testid="room-join-form" @submit.prevent="joinRoom">
      <label class="rd-label" for="rd-addr">{{ t('ourstate.rooms.addressIn', 'The room\'s address') }}</label>
      <input id="rd-addr" v-model="address" class="rd-in" placeholder="room:…@https://…" data-testid="room-address-in" />
      <button type="submit" class="rd-go" :disabled="busy || !valid" data-testid="room-join-go">
        {{ t('ourstate.rooms.joinGo', 'Join') }}</button>
      <p v-if="address && !valid" class="rd-note">{{ t('ourstate.rooms.notAnAddress', 'That is not a room\'s address: it reads room:<id>@https://its.registry') }}</p>
    </form>
    <p v-if="note" class="rd-note" data-testid="room-note">{{ note }}</p>
    <p v-if="error" class="rd-error" data-testid="room-door-error">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { chatApi, type RoomJoinRule } from '@/services/api/chat'
import { parseRoomAddress } from '@/services/chat/rooms'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ token: string; joinAddress?: string | null }>()
const emit = defineEmits<{ (e: 'opened', conversationId: string): void }>()
const { t } = useI18n()

const mode = ref<'' | 'open' | 'join'>('')
const title = ref('')
const rule = ref<RoomJoinRule>('invited')
const address = ref('')
const busy = ref(false)
const error = ref('')
const note = ref('')
const valid = computed(() => parseRoomAddress(address.value) !== null)

function toggle(m: 'open' | 'join') {
  mode.value = mode.value === m ? '' : m
  error.value = ''
  note.value = ''
}

watch(() => props.joinAddress, (a) => {
  if (a) { address.value = a; mode.value = 'join' }
}, { immediate: true })

async function openRoom() {
  busy.value = true; error.value = ''
  try {
    const r = await chatApi.createRoom(props.token, { title: title.value.trim(), join_rule: rule.value })
    title.value = ''; mode.value = ''
    emit('opened', r.conversation_id)
  } catch (e: any) {
    error.value = e?.detail || e?.message || t('ourstate.rooms.openFailed', 'The room could not be opened.')
  } finally { busy.value = false }
}

async function joinRoom() {
  busy.value = true; error.value = ''; note.value = ''
  try {
    const r = await chatApi.joinRoom(props.token, address.value.trim())
    if (r?.state === 'pending') {
      note.value = t('ourstate.rooms.waiting', 'Asked: the room\'s operators decide, and it shows here once they accept.')
    } else {
      address.value = ''; mode.value = ''
      emit('opened', r.conversation_id)
    }
  } catch (e: any) {
    error.value = e?.detail || e?.message || t('ourstate.rooms.joinFailed', 'You did not join: the room\'s host refused or could not be reached.')
  } finally { busy.value = false }
}
</script>

<style scoped>
.rd { display: flex; flex-direction: column; gap: .4rem; margin: .25rem 0 .5rem; }
.rd-row { display: flex; gap: .5rem; }
.rd-door { flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: .35rem; font-size: .82rem;
  padding: .4rem .6rem; border-radius: 8px; border: 1px solid rgba(255,255,255,.16); background: transparent;
  color: inherit; cursor: pointer; }
.rd-form { display: flex; flex-direction: column; gap: .3rem; font-size: .82rem; }
.rd-label { color: #8b96a5; font-size: .76rem; }
.rd-in { padding: .35rem .5rem; border-radius: 6px; border: 1px solid rgba(255,255,255,.18); background: rgba(0,0,0,.2);
  color: inherit; font: inherit; }
.rd-go { align-self: flex-start; padding: .3rem .8rem; border-radius: 6px; border: 1px solid rgba(255,255,255,.25);
  background: transparent; color: inherit; cursor: pointer; }
.rd-go:disabled { opacity: .5; cursor: default; }
.rd-note { margin: 0; color: #8b96a5; font-size: .76rem; }
.rd-error { margin: 0; color: #f08a8a; font-size: .78rem; }
</style>
