<!--
  V0652 (ad) (order gwo_e5e9ad061d6e5be9605a3067): an organization room's side panel on the console's chat. The
  maintainer (the sessions' room, seq 257): "the chat is very narrow it has a lot of space on the sides. we could utilize
  this maybe ... this makes me miss the sequence to evaluate who posts what from just the chat". The width the column
  does not need carries what the room is doing: how many approval requests wait (V0653 (al), his seq 686: the requests
  themselves are pinned above the history again, at every width, and this section opens their whole list there), its
  status board and live cards (sections that (ac) and (aa) fill: drawn only when the thread hands one in, never an
  empty promise), and who is present (V0650 (a)'s presence: each agent's live status line). Each section folds; its
  state is kept per person on this device. A read that failed says so; it never reads as an empty room. Under the
  breakpoint the thread draws without it, as before.
-->
<template>
  <aside class="csp" data-testid="ost-side" :aria-label="t('ourstate.side.aria', 'This room, at a glance')">
    <section v-for="s in sections()" :key="s.key" class="csp-sec" :data-testid="`csp-${s.key}`" :data-open="open[s.key] ? '1' : '0'">
      <h3 class="csp-h">
        <button type="button" class="csp-head" :aria-expanded="open[s.key] ? 'true' : 'false'" :aria-controls="`${uid}-${s.key}`"
                :data-testid="`csp-${s.key}-toggle`" @click="toggle(s.key)">
          <span class="csp-lbl">{{ s.label }}</span>
          <span v-if="s.count" class="csp-count" :data-testid="`csp-${s.key}-count`">{{ s.count }}</span>
          <Icon name="mdi:chevron-right" class="csp-caret" :class="{ open: open[s.key] }" aria-hidden="true" />
        </button>
      </h3>
      <!-- approvals stay mounted while folded (v-show): the count stays live and an arriving card still refreshes them -->
      <div v-if="s.key === 'approvals'" v-show="open.approvals" :id="`${uid}-approvals`" class="csp-body">
        <slot name="approvals" />
      </div>
      <div v-else-if="s.key === 'board' && open.board" :id="`${uid}-board`" class="csp-body"><slot name="board" /></div>
      <div v-else-if="s.key === 'live' && open.live" :id="`${uid}-live`" class="csp-body"><slot name="live" /></div>
      <div v-else-if="s.key === 'present' && open.present" :id="`${uid}-present`" class="csp-body">
        <ReadFailedNotice v-if="presenceFailed" dense :retry="loadPresence" data-testid="csp-present-failed"
                          :text="t('ourstate.side.presenceFailed', 'Who is present could not be read just now.')" />
        <p v-else-if="!presence" class="csp-muted" data-testid="csp-present-reading">{{ t('common.loading', 'Loading…') }}</p>
        <p v-else-if="!presence.agents.length" class="csp-muted" data-testid="csp-present-none">
          {{ t('ourstate.side.noAgents', 'No agent is assigned to this organization.') }}</p>
        <ul v-else class="csp-list">
          <li v-for="a in sortedAgents" :key="a.did" class="csp-agent" :data-testid="`csp-agent-${a.did}`" :data-live="a.status ? '1' : '0'">
            <!-- live by shape, not only by colour: a filled dot has a live status line, a hollow one has none -->
            <span class="csp-dot" :class="{ on: !!a.status }" aria-hidden="true" />
            <span class="csp-who">
              <span class="csp-name" :title="a.did">{{ a.name || shortDid(a.did) }}</span>
              <span class="csp-status">{{ a.status ? a.status.text : t('ourstate.side.noStatus', 'no live status') }}</span>
              <span v-if="a.last_active_at" class="csp-ago" :title="absolute(a.last_active_at)">
                {{ tp('ourstate.side.active', 'active {ago} ago', { ago: agoShort(a.last_active_at) }) }}</span>
              <!-- V0654 (aq): what of this room wakes it (a member of the room); the room's owner, signed in, switches it -->
              <template v-if="wakeOf(a.did)">
                <WakeModeSwitch v-if="canSetWake" class="csp-wake" :mode="wakeOf(a.did) as WakeMode"
                                :who="a.name || shortDid(a.did)" :testid="a.did" :busy="wakeBusy === agentKey(a.did)"
                                @set="(m) => emit('set-wake', agentKey(a.did), m)" />
                <span v-else-if="wakeOf(a.did) !== 'listen'" class="csp-wake-chip" :data-testid="`csp-wake-${a.did}`">
                  {{ wakeOf(a.did) === 'off' ? t('ourstate.wake.off', 'Off') : t('ourstate.wake.onCall', 'On call') }}</span>
              </template>
            </span>
          </li>
        </ul>
      </div>
    </section>
  </aside>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, useSlots, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import WakeModeSwitch from '@/components/ourstate/WakeModeSwitch.vue'
import type { WakeMode } from '@/services/api/chat'
import { organizationService, type OrgPresence } from '@/services/api/organizationService'
import { agoShort } from '@/services/cockpit/when'
import { appLocale } from '@/services/appLocale'
import { useI18n } from '@/composables/useI18n'
import { saveSidePanelOpen, sidePanelOpen, type SideSection } from '@/services/chat/sidePanel'

const props = withDefaults(defineProps<{
  orgId: string
  /** Whose fold state this is (kept per person on this device). */
  viewerKey: string
  /** How many approval requests the approvals section holds (null until it has read them). */
  approvalsCount?: number | null
  /** A link opened one request (?approval=): the approvals section opens to show it. */
  focusApprovals?: boolean
  /** V0654 (aq): the room's members' wake modes, by key (agt:<did>), and whether the viewer (the room's owner, signed
   *  in) switches them; the key being switched now. */
  wakeModes?: Record<string, string> | null
  canSetWake?: boolean
  wakeBusy?: string | null
}>(), { approvalsCount: null, focusApprovals: false, wakeModes: null, canSetWake: false, wakeBusy: null })
const emit = defineEmits<{ (e: 'set-wake', key: string, mode: WakeMode): void }>()
const agentKey = (did: string) => `agt:${String(did || '').toLowerCase()}`
/** A member's wake mode here, or '' for an agent of the organization that is not a member of this room. */
const wakeOf = (did: string): string => props.wakeModes?.[agentKey(did)] || ''
const { t, tp } = useI18n()
const slots = useSlots()
const uid = `csp-${Math.random().toString(36).slice(2, 8)}`

const open = reactive(sidePanelOpen(props.viewerKey))
watch(() => props.viewerKey, (v) => Object.assign(open, sidePanelOpen(v)))
watch(() => props.focusApprovals, (v) => { if (v) open.approvals = true }, { immediate: true })
function toggle(s: SideSection) {
  open[s] = !open[s]
  saveSidePanelOpen(props.viewerKey, { ...open })
  if (s === 'present' && open.present) void loadPresence()
}

const presence = ref<OrgPresence | null>(null)
const presenceFailed = ref(false)
async function loadPresence() {
  const org = props.orgId
  if (!org) return
  try {
    const p = await organizationService.getOrgPresence(org)
    if (org !== props.orgId) return
    presence.value = p
    presenceFailed.value = false
  } catch {
    if (org === props.orgId) presenceFailed.value = true
  }
}
watch(() => props.orgId, () => { presence.value = null; presenceFailed.value = false; if (open.present) void loadPresence() })
const liveCount = computed(() => (presence.value?.agents || []).filter((a) => !!a.status).length)
/* who has a live status line first, then by name */
const sortedAgents = computed(() => [...(presence.value?.agents || [])].sort((a, b) =>
  (b.status ? 1 : 0) - (a.status ? 1 : 0) || String(a.name || a.did).localeCompare(String(b.name || b.did))))
function shortDid(did: string): string { return did.length > 18 ? `…${did.slice(-10)}` : did }
function absolute(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(appLocale())
}

/* the board and the live cards are drawn only when the thread hands them in ((ac) and (aa) fill them); read at each
   render, so a slot handed in later is seen */
function sections() {
  const out: Array<{ key: SideSection; label: string; count: string }> = [
    { key: 'approvals', label: t('ourstate.side.approvals', 'Approvals'),
      count: props.approvalsCount ? String(props.approvalsCount) : '' },
  ]
  if (slots.board) out.push({ key: 'board', label: t('ourstate.side.board', 'Status board'), count: '' })
  if (slots.live) out.push({ key: 'live', label: t('ourstate.side.live', 'Live cards'), count: '' })
  out.push({ key: 'present', label: t('ourstate.side.present', 'Present'),
    count: presence.value ? tp('ourstate.side.liveOf', '{n} of {total} live', { n: liveCount.value, total: presence.value.agents.length }) : '' })
  return out
}

/* presence moves: read again when the window comes back to it, and every two minutes while it shows */
let timer: ReturnType<typeof setInterval> | null = null
const onFocus = () => { if (open.present) void loadPresence() }
onMounted(() => {
  if (open.present) void loadPresence()
  window.addEventListener('focus', onFocus)
  timer = setInterval(() => { if (open.present && document.visibilityState === 'visible') void loadPresence() }, 120000)
})
onBeforeUnmount(() => { window.removeEventListener('focus', onFocus); if (timer) clearInterval(timer) })
</script>

<style scoped>
.csp { flex: 0 0 300px; width: 300px; min-width: 0; min-height: 0; overflow-y: auto; display: flex; flex-direction: column;
  padding: 6px 14px 16px; border-left: 1px solid var(--nc-border-subtle, rgba(128, 128, 128, .18)); }
.csp-sec { display: flex; flex-direction: column; border-bottom: 1px solid var(--nc-border-subtle, rgba(128, 128, 128, .14)); }
.csp-sec:last-child { border-bottom: 0; }
.csp-h { margin: 0; font: inherit; }
.csp-head { display: flex; align-items: center; gap: 8px; width: 100%; min-height: 44px; padding: 0 2px; border: 0; background: none;
  color: inherit; cursor: pointer; text-align: left; }
.csp-head:focus-visible { outline: 2px solid var(--nc-primary, #00d2d2); outline-offset: -2px; border-radius: 6px; }
.csp-lbl { flex: 1; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .62rem; letter-spacing: .17em;
  text-transform: uppercase; color: #8b96a5; }
.csp-count { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .66rem; color: #b4bfcc; font-variant-numeric: tabular-nums; }
.csp-caret { flex: none; width: 14px; height: 14px; opacity: .55; transition: transform .15s; }
.csp-caret.open { transform: rotate(90deg); }
.csp-body { min-width: 0; padding: 0 0 12px; }
.csp-muted { margin: 0; padding: 0 2px; font-size: .8rem; color: #8b96a5; }
.csp-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.csp-agent { display: flex; align-items: flex-start; gap: 10px; padding: 7px 2px; }
.csp-agent + .csp-agent { border-top: 1px solid var(--nc-border-subtle, rgba(128, 128, 128, .1)); }
.csp-dot { flex: none; width: 8px; height: 8px; margin-top: 6px; border-radius: 50%; border: 1px solid #8b96a5; }
.csp-dot.on { border-color: var(--nc-primary, #00d2d2); background: var(--nc-primary, #00d2d2); }
.csp-who { min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.csp-name { font-size: .88rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.csp-status { font-size: .78rem; line-height: 1.4; color: #c4ccd6; overflow-wrap: anywhere; }
.csp-agent[data-live='0'] .csp-status { color: #8b96a5; }
.csp-ago { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .62rem; letter-spacing: .04em; color: #8b96a5; }
/* V0654 (aq): a session's wake mode in this room */
.csp-wake { margin-top: 4px; align-self: flex-start; }
.csp-wake-chip { align-self: flex-start; margin-top: 2px; font-size: .62rem; padding: 0 7px; border-radius: 999px;
  border: 1px solid var(--border-color, rgba(128,128,128,.3)); color: #8b96a5; }
</style>
