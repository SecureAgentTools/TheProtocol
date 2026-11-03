<!--
  V0655 (ay) (order gwo_57362aa3484807226198b8de): a small window over the room for a direct message to one member of
  the room's organization, opened from the side panel's Message. It opens the direct thread with that identity, the
  existing one or a new one as the chat already allows (inside one organization at once), shows its last lines, sends
  a line and links to the whole thread. No new rail: the chat's own conversation and message routes. The room stays
  open under it and keeps its place; Escape or the close button closes it.
-->
<template>
  <section class="cdw" role="dialog" aria-modal="false" :aria-label="tp('ourstate.dm.aria', 'Direct message with {who}', { who })"
           data-testid="cdw" :data-conv="convId" @keydown.esc.stop="emit('close')">
    <header class="cdw-head">
      <span class="cdw-who" :title="target.did">{{ who }}</span>
      <button type="button" class="cdw-btn" data-testid="cdw-open" :disabled="!convId" @click="emit('open', convId)">
        {{ t('ourstate.dm.openThread', 'Open the thread') }}</button>
      <button type="button" class="cdw-btn" data-testid="cdw-close" @click="emit('close')">{{ t('common.close', 'Close') }}</button>
    </header>
    <div ref="listEl" class="cdw-lines" data-testid="cdw-lines" aria-live="polite">
      <p v-if="failed" class="cdw-note" data-testid="cdw-failed">{{ failed }}</p>
      <p v-else-if="!convId" class="cdw-note" data-testid="cdw-opening">{{ t('ourstate.dm.opening', 'Opening the thread…') }}</p>
      <p v-else-if="!lines.length" class="cdw-note" data-testid="cdw-empty">
        {{ t('ourstate.dm.empty', 'No messages yet. Your first line starts the thread.') }}</p>
      <div v-for="m in lines" :key="m.id || m.seq" class="cdw-line" :class="{ mine: !fromTarget(m) }" :data-testid="`cdw-line-${m.seq}`">
        <span class="cdw-author">{{ fromTarget(m) ? who : t('ourstate.dm.you', 'You') }}</span>
        <span class="cdw-body">{{ bodyOf(m) }}</span>
      </div>
    </div>
    <form class="cdw-compose" @submit.prevent="send">
      <textarea ref="inputEl" v-model="text" class="cdw-input" rows="2" maxlength="4000" data-testid="cdw-input"
                :aria-label="tp('ourstate.dm.placeholder', 'Message {who} directly', { who })"
                :placeholder="tp('ourstate.dm.placeholder', 'Message {who} directly', { who })" :disabled="!convId"
                @keydown.enter.exact.prevent="send" />
      <button type="submit" class="cdw-btn cdw-send" data-testid="cdw-send" :disabled="!convId || !text.trim() || sending">
        {{ t('ourstate.dm.send', 'Send') }}</button>
    </form>
    <p v-if="sendFailed" class="cdw-note cdw-err" data-testid="cdw-send-failed">{{ sendFailed }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { chatApi } from '@/services/api/chat'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ token: string; target: { did: string; name?: string | null } }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'open', conversationId: string): void }>()
const { t, tp } = useI18n()

const LINES = 6
const convId = ref('')
const lines = ref<any[]>([])
const failed = ref('')
const text = ref('')
const sending = ref(false)
const sendFailed = ref('')
const listEl = ref<HTMLElement | null>(null)
const inputEl = ref<HTMLTextAreaElement | null>(null)
const who = computed(() => String(props.target.name || '').trim() || props.target.did)
const targetDid = computed(() => String(props.target.did || '').toLowerCase())

function fromTarget(m: any): boolean {
  return m?.sender_ptype === 'agent' && String(m?.sender_id || '').toLowerCase() === targetDid.value
}
function bodyOf(m: any): string {
  if (m?.deleted) return t('ourstate.thread.deleted', 'message deleted')
  if (m?.kind === 'card') return t('ourstate.dm.card', '(a card: open the thread to see it)')
  return String(m?.body || '')
}
function newRef(): string {
  return (crypto as any).randomUUID ? crypto.randomUUID() : `cdw-${Date.now()}-${Math.random().toString(36).slice(2)}`
}
function scrollDown() { if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight }

async function open() {
  const want = props.target.did
  convId.value = ''; lines.value = []; failed.value = ''; sendFailed.value = ''
  try {
    const r = await chatApi.createConversation(props.token, 'dm', { ptype: 'agent', agent_did: want })
    const id = String(r?.conversation_id || '')
    if (!id) throw new Error('no thread')
    const page = await chatApi.getMessages(props.token, id, undefined, LINES)
    if (want !== props.target.did) return
    convId.value = id
    lines.value = (page?.messages || []).slice(-LINES)
    await nextTick()
    scrollDown()
    inputEl.value?.focus()
  } catch (e: any) {
    if (want === props.target.did) failed.value = e?.detail || t('ourstate.dm.failed', 'The direct thread could not be opened just now.')
  }
}
watch(() => props.target.did, () => { void open() }, { immediate: true })

async function send() {
  const body = text.value.trim()
  if (!convId.value || !body || sending.value) return
  sending.value = true
  sendFailed.value = ''
  try {
    const r = await chatApi.postMessage(props.token, convId.value, { kind: 'text', body, client_ref: newRef() })
    if (r?.message) lines.value = [...lines.value, r.message].slice(-LINES)
    text.value = ''
    await nextTick()
    scrollDown()
  } catch (e: any) {
    sendFailed.value = e?.detail || t('ourstate.dm.sendFailed', 'The line was not sent; it is still in the box.')
  } finally {
    sending.value = false
  }
}
</script>

<style scoped>
.cdw { position: fixed; right: 324px; bottom: 96px; z-index: 60; width: 340px; max-width: calc(100vw - 32px); display: flex;
  flex-direction: column; gap: 8px; padding: 10px 12px 12px; border-radius: 10px;
  border: 1px solid var(--nc-border-subtle, rgba(128, 128, 128, .3)); background: var(--nc-surface, #0f1720);
  box-shadow: 0 12px 32px rgba(0, 0, 0, .45); }
.cdw-head { display: flex; align-items: center; gap: 8px; }
.cdw-who { flex: 1; min-width: 0; font-size: .88rem; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cdw-btn { min-height: 30px; padding: 0 10px; border-radius: 999px; border: 1px solid var(--border-color, rgba(128, 128, 128, .3));
  background: none; color: inherit; font-size: .72rem; cursor: pointer; }
.cdw-btn:disabled { opacity: .5; cursor: default; }
.cdw-btn:focus-visible, .cdw-input:focus-visible { outline: 2px solid var(--nc-primary, #00d2d2); outline-offset: 1px; }
.cdw-lines { display: flex; flex-direction: column; gap: 6px; max-height: 240px; overflow-y: auto; overscroll-behavior: contain; }
.cdw-line { display: flex; flex-direction: column; gap: 1px; padding: 5px 8px; border-radius: 8px; background: rgba(128, 128, 128, .08); }
.cdw-line.mine { align-self: flex-end; background: rgba(79, 216, 196, .12); }
.cdw-author { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .6rem; letter-spacing: .06em; color: #8b96a5; }
.cdw-body { font-size: .82rem; line-height: 1.4; overflow-wrap: anywhere; white-space: pre-wrap; }
.cdw-note { margin: 0; font-size: .78rem; color: #8b96a5; }
.cdw-err { color: #f0a0a0; }
.cdw-compose { display: flex; align-items: flex-end; gap: 8px; }
.cdw-input { flex: 1; min-width: 0; resize: none; padding: 6px 8px; border-radius: 8px; font: inherit; font-size: .84rem;
  border: 1px solid var(--border-color, rgba(128, 128, 128, .3)); background: rgba(0, 0, 0, .2); color: inherit; }
.cdw-send { flex: none; }
</style>
