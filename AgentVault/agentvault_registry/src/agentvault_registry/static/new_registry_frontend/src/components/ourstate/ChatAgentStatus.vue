<!--
  V0662 (OurChat lane, the batch's item 11, order gwo_6b2cbdf6e982d1662161e802): the session board. In the side panel of an organization's
  room, for the organization's owners and admins: per session, what the room's desk last reported (state, wake mode, the last wake,
  wakes in 24 hours: who spends). It reads GET /chat/conversations/{id}/agent-status every minute while it is on screen. It draws what
  the registry gives and never guesses: a row not refreshed for 5 minutes is `unknown` and shows no mode or count; a refusal (the
  viewer is not an owner or admin) hides the whole section, it never reads as "nobody".
-->
<template>
  <section v-if="shown" class="csb" data-testid="ost-agent-status">
    <p v-if="!rows.length" class="csb-muted" data-testid="ost-agent-status-empty">{{ t('ourstate.thread.agentStatusEmpty', "No report yet: the room's desk has not reported its sessions.") }}</p>
    <ul v-else class="csb-list">
      <li v-for="r in rows" :key="r.key" class="csb-row" :data-testid="`ost-agent-${r.key}`">
        <span class="csb-name">{{ r.name }}</span>
        <span class="csb-state" :data-state="r.state">{{ stateWord(r.state) }}</span>
        <span v-if="r.wake_mode" class="csb-meta">{{ tp('ourstate.thread.agentStatusMode', 'wake mode: {mode}', { mode: r.wake_mode }) }}</span>
        <span v-if="r.wakes_24h !== null" class="csb-meta" :data-testid="`ost-agent-wakes-${r.key}`">{{ tp('ourstate.thread.agentStatusWakes', '{n} wakes in 24 h', { n: r.wakes_24h }) }}</span>
        <span class="csb-meta">{{ lastWake(r) }}</span>
        <span v-if="ago(r.age_s)" class="csb-meta csb-age">{{ tp('ourstate.thread.agentStatusAge', 'reported {when} ago', { when: ago(r.age_s) }) }}</span>
      </li>
    </ul>
    <p class="csb-muted csb-note">{{ t('ourstate.thread.agentStatusNote', 'What the room\'s desk last reported. A row not refreshed for 5 minutes reads unknown; a wake is not a read.') }}</p>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { chatApi } from '@/services/api/chat'
import { agoWord, cleanSessions, secondsSince, type SessionRow } from '@/services/chat/agentStatus'

const props = defineProps<{ token: string; conversationId: string }>()
const { t, tp } = useI18n()
const POLL_MS = 60_000
const rows = ref<SessionRow[]>([])
const shown = ref(false)                  // false until the registry has answered this viewer (a refusal keeps it false)
let timer: ReturnType<typeof setInterval> | null = null
let seq = 0

async function load() {
  const id = props.conversationId
  const mine = ++seq
  if (!id || !props.token) return
  try {
    const r = await chatApi.agentStatus(props.token, id)
    if (mine !== seq) return
    rows.value = cleanSessions(r?.sessions)
    shown.value = true
  } catch {
    if (mine === seq) { shown.value = false; rows.value = [] }       // not for this viewer (403), not here (409) or unreachable: no section
  }
}
function stateWord(s: string): string {
  return s === 'active' ? t('ourstate.thread.agentStatusStateActive', 'active') : s === 'paused' ? t('ourstate.thread.agentStatusStatePaused', 'paused')
    : s === 'unreachable' ? t('ourstate.thread.agentStatusStateUnreachable', 'unreachable') : t('ourstate.thread.agentStatusStateUnknown', 'unknown')
}
const ago = (s: number | null) => agoWord(s)
function lastWake(r: SessionRow): string {
  const w = agoWord(secondsSince(r.last_wake_at, Date.now()))
  return w ? tp('ourstate.thread.agentStatusLastWake', 'last wake {when} ago', { when: w }) : t('ourstate.thread.agentStatusNever', 'no wake yet')
}
onMounted(() => { void load(); timer = setInterval(() => { void load() }, POLL_MS) })
onBeforeUnmount(() => { if (timer) clearInterval(timer); seq++ })
watch(() => props.conversationId, () => { rows.value = []; shown.value = false; void load() })
</script>

<style scoped>
.csb { padding: 10px 12px; border-top: 1px solid var(--border-color, rgba(128,128,128,.2)); }
.csb-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.csb-row { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 8px; font-size: .78rem; }
.csb-name { font-weight: 600; }
.csb-state { padding: 0 8px; border-radius: 999px; border: 1px solid var(--nc-border, rgba(255,255,255,.3)); font-size: .68rem; }
.csb-state[data-state="active"] { border-color: var(--nc-primary, #00d2d2); color: var(--nc-primary, #00d2d2); }
.csb-state[data-state="unreachable"], .csb-state[data-state="unknown"] { color: #a9b3c1; border-style: dashed; }
.csb-meta { color: #a9b3c1; font-size: .72rem; }
.csb-muted { margin: 4px 0 0; color: #8b96a5; font-size: .72rem; }
</style>
