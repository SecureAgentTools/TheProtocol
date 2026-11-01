<!--
  V0652 (ak) (order gwo_8c69cc0fd1f3033a35f47969): the thread's settings, one menu for the console's #/ourchat, Pocket
  wide and the phone. The maintainer (the sessions' room, seq 370/373): the three-dots settings, "do it thoroughly and
  make sure nothing was forgotten or left unpolished"; the design (sessionlogs2026/DESIGN_2026-11-01_OURCHAT_SETTINGS.md)
  and session-lead's review of it (seq 397).

  On a wide screen it is a menu under its button (never moving the history); on a phone a bottom sheet. Every row says
  what it does and shows its state. It decides nothing: each row hands its action to the thread, which opens the sheet
  or calls the rail. Keyboard: arrows, Home and End move; Enter opens; Space flips a switch; Escape and Tab close.
  The testids the suites drive are kept (ost-menu-sheet and each row's).
-->
<template>
  <Teleport to="body">
    <div v-if="surface === 'sheet'" class="csm-scrim" data-testid="csm-scrim" @click="emit('close')" />
    <div ref="rootEl" class="csm" :class="surface === 'sheet' ? 'csm-sheet' : 'csm-pop'" :style="popStyle"
         :role="surface === 'sheet' ? 'dialog' : 'menu'" :aria-label="tp('ourstate.settings.aria', 'Settings for {name}', { name: title })"
         data-testid="ost-menu-sheet" :data-surface="surface" @keydown="onKey">
      <div v-if="surface === 'sheet'" class="csm-grab" data-testid="csm-grab" @pointerdown="grabStart" />
      <div class="csm-head">
        <span class="csm-title">{{ title }}</span>
        <span v-if="subline" class="csm-sub" data-testid="csm-sub">{{ subline }}</span>
      </div>

      <!-- this room / this chat / this ticket -->
      <div class="csm-sec" role="group">
        <span class="csm-lbl">{{ kind === 'room' ? t('ourstate.settings.thisRoom', 'This room')
          : kind === 'support' ? t('ourstate.settings.thisTicket', 'This ticket') : t('ourstate.settings.thisChat', 'This chat') }}</span>
        <template v-if="kind === 'room' && room">
          <button class="csm-row" role="menuitem" data-csm-row data-testid="ost-room-members" @click="pick('members')">
            <Icon name="mdi:account-group" class="csm-ic" />
            <span class="csm-tx">{{ t('ourstate.rooms.members', 'Members') }}<small>{{ t('ourstate.settings.membersSub', 'Who has opened the room') }}</small></span>
            <span v-if="room.opened != null" class="csm-val">{{ room.opened }}</span><span class="csm-chev" aria-hidden="true">›</span>
          </button>
          <button class="csm-row" role="menuitem" data-csm-row data-testid="ost-room-settings" @click="pick('room')">
            <Icon name="mdi:tune" class="csm-ic" />
            <span class="csm-tx">{{ t('ourstate.rooms.settings', 'Room settings') }}<small>{{ room.isOperator
              ? t('ourstate.settings.roomSubOp', "Topic, who may post, the room's rules")
              : t('ourstate.settings.roomSubMember', 'Read only: an owner or an admin sets them') }}</small></span>
            <span class="csm-val">{{ room.mode === 'announce' ? t('ourstate.settings.modeAnnounce', 'Announce only') : t('ourstate.settings.modeOpen', 'Open') }}</span>
            <span class="csm-chev" aria-hidden="true">›</span>
          </button>
          <button v-if="room.isOperator" class="csm-row" role="menuitemcheckbox" :aria-checked="room.assistantPresent ? 'true' : 'false'"
                  data-csm-row data-testid="ost-assistant-toggle" @click="pick('assistant')">
            <Icon name="mdi:robot-outline" class="csm-ic" />
            <span class="csm-tx">@assistant<small>{{ t('ourstate.settings.assistantSub', "Answers when addressed; reads the organization's records only") }}</small></span>
            <span class="csm-sw" :class="{ on: room.assistantPresent }" aria-hidden="true" />
          </button>
          <div v-else class="csm-row csm-static" data-testid="csm-assistant-state">
            <Icon name="mdi:robot-outline" class="csm-ic" />
            <span class="csm-tx">@assistant<small>{{ t('ourstate.settings.assistantMember', 'An owner or an admin adds it') }}</small></span>
            <span class="csm-val">{{ room.assistantPresent ? t('ourstate.settings.on', 'On') : t('ourstate.settings.off', 'Off') }}</span>
          </div>
        </template>
        <div v-if="kind === 'support' && ticket" class="csm-row csm-static" data-testid="ost-ticket">
          <Icon name="mdi:lifebuoy" class="csm-ic" />
          <span class="csm-tx">{{ tp('ourstate.settings.ticket', 'Ticket #{id}', { id: String(ticket.id) }) }}<small>{{ t('ourstate.support.decides', 'Support sets the status; replying here reopens a closed ticket.') }}</small></span>
          <span class="csm-val">{{ ticket.status }}</span>
        </div>
        <button v-if="kind !== 'support'" class="csm-row" role="menuitem" data-csm-row data-testid="ost-timer-open" @click="pick('timer')">
          <Icon name="mdi:timer-sand" class="csm-ic" />
          <span class="csm-tx">{{ t('ourstate.thread.timerMenu', 'Disappearing messages') }}<small>{{ timerEditable
            ? (kind === 'room' ? t('ourstate.settings.timerSubRoom', 'Set by an owner or an admin; everyone sees who') : t('ourstate.settings.timerSubDm', 'Set by either of you; both see who'))
            : t('ourstate.settings.timerSubReadOnly', 'Read only: an owner or an admin sets it') }}</small></span>
          <span class="csm-val" data-testid="csm-timer-val">{{ retention }}</span><span class="csm-chev" aria-hidden="true">›</span>
        </button>
        <button class="csm-row" role="menuitem" data-csm-row data-testid="ost-privacy-open" @click="pick('privacy')">
          <Icon name="mdi:shield-account" class="csm-ic" />
          <span class="csm-tx">{{ t('ourstate.thread.privacy', 'Who can read this') }}<small>{{ readers }}</small></span>
          <span class="csm-chev" aria-hidden="true">›</span>
        </button>
      </div>

      <!-- you here -->
      <div class="csm-sec" role="group">
        <span class="csm-lbl">{{ t('ourstate.settings.youHere', 'You here') }}</span>
        <button class="csm-row" role="menuitem" data-csm-row data-testid="ost-notify" @click="pick('notify')">
          <Icon :name="muted ? 'mdi:bell-off' : 'mdi:bell'" class="csm-ic" />
          <span class="csm-tx">{{ t('ourstate.settings.notify', 'Notifications') }}<small>{{ kind === 'support'
            ? t('ourstate.settings.notifySubSupport', 'Replies from the desk')
            : t('ourstate.settings.notifySub', 'Asks that wait on you always reach you') }}</small></span>
          <span class="csm-val" data-testid="csm-notify-val">{{ notify }}</span><span class="csm-chev" aria-hidden="true">›</span>
        </button>
        <button v-if="kind === 'dm' && away?.enabled" class="csm-row" role="menuitemcheckbox"
                :aria-checked="away.silencedHere ? 'false' : 'true'" data-csm-row data-testid="ost-away-here" @click="pick('away')">
          <Icon name="mdi:account-clock" class="csm-ic" />
          <span class="csm-tx">{{ t('ourstate.settings.standIn', 'Stand-in here') }}<small>{{ t('ourstate.settings.standInSub', 'While away mode is on, your stand-in answers here') }}</small></span>
          <span class="csm-sw" :class="{ on: !away.silencedHere }" aria-hidden="true" />
        </button>
      </div>

      <!-- you in OurChat -->
      <div class="csm-sec" role="group">
        <span class="csm-lbl">{{ t('ourstate.settings.youInChat', 'You in OurChat') }}</span>
        <button class="csm-row" role="menuitem" data-csm-row data-testid="ost-you-settings" @click="pick('you')">
          <Icon name="mdi:at" class="csm-ic" />
          <span class="csm-tx">{{ t('ourstate.settings.you', 'Your chat settings') }}<small>{{ t('ourstate.settings.youSub', 'Handle, who can reach you, away, blocked, push') }}</small></span>
          <span class="csm-chev" aria-hidden="true">›</span>
        </button>
      </div>

      <!-- the acts that remove: set apart, last -->
      <div class="csm-sec csm-danger" role="group">
        <button v-if="canBlock" class="csm-row csm-warn" role="menuitem" data-csm-row data-testid="ost-block" @click="pick('block')">
          <Icon name="mdi:cancel" class="csm-ic" />
          <span class="csm-tx">{{ tp('ourstate.settings.block', 'Block {name}…', { name: counterpartyName || t('ourstate.settings.them', 'them') }) }}<small>{{ t('ourstate.settings.blockSub', 'Nothing from them reaches you; they are not told') }}</small></span>
          <span class="csm-chev" aria-hidden="true">›</span>
        </button>
        <button v-if="kind !== 'support'" class="csm-row csm-warn" role="menuitem" data-csm-row data-testid="ost-leave" @click="pick('leave')">
          <Icon name="mdi:logout" class="csm-ic" />
          <span class="csm-tx">{{ kind === 'room' ? t('ourstate.settings.leaveRoom', 'Leave this room…') : t('ourstate.settings.leaveChat', 'Leave this chat…') }}<small>{{ kind === 'room'
            ? t('ourstate.settings.leaveRoomSub', 'It leaves your list; open it again to come back')
            : t('ourstate.settings.leaveChatSub', 'It leaves your list; they are not told') }}</small></span>
          <span class="csm-chev" aria-hidden="true">›</span>
        </button>
        <button class="csm-row csm-warn" role="menuitem" data-csm-row data-testid="ost-burn" @click="pick('burn')">
          <Icon name="mdi:fire" class="csm-ic" />
          <span class="csm-tx">{{ t('ourstate.settings.burn', 'Burn this thread for you…') }}<small>{{ t('ourstate.settings.burnSub', 'Your history goes; the others keep theirs') }}</small></span>
          <span class="csm-chev" aria-hidden="true">›</span>
        </button>
      </div>
      <div v-if="surface === 'popover'" class="csm-foot" aria-hidden="true">{{ t('ourstate.settings.keys', '↑ ↓ move · enter open · space switch · esc close') }}</div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'

type SettingsAction = 'members' | 'room' | 'assistant' | 'timer' | 'privacy' | 'notify' | 'away' | 'block'
  | 'you' | 'burn' | 'leave'

const props = withDefaults(defineProps<{
  surface: 'popover' | 'sheet'
  kind: 'room' | 'dm' | 'support'
  title: string
  subline?: string
  /** The button that opened it: the popover sits under it, right edges aligned. */
  anchor?: HTMLElement | null
  room?: { opened: number | null; isOperator: boolean; mode: string; assistantPresent: boolean } | null
  /** The timer's state, already worded ("Off", "7 days"). */
  retention: string
  timerEditable?: boolean
  /** The notification level, already worded. */
  notify: string
  muted?: boolean
  /** Who can read the thread, in one line. */
  readers: string
  away?: { enabled: boolean; silencedHere: boolean } | null
  canBlock?: boolean
  counterpartyName?: string
  ticket?: { id: string | number; status: string } | null
}>(), { subline: '', anchor: null, room: null, timerEditable: true, muted: false, away: null, canBlock: false,
  counterpartyName: '', ticket: null })

const emit = defineEmits<{ (e: 'close'): void; (e: 'pick', action: SettingsAction): void }>()
const { t, tp } = useI18n()
const rootEl = ref<HTMLElement | null>(null)
const pos = ref<{ top: number; right: number; maxH: number } | null>(null)

/** What a phone's bottom bar keeps under the page (Pocket's tab bar), read, never assumed. */
function bottomReserve(): number {
  const bar = document.querySelector('[data-testid="pk-tabbar"], .pk-tabbar, .pk-nav') as HTMLElement | null
  const r = bar?.getBoundingClientRect()
  return r && r.top > window.innerHeight / 2 ? Math.max(0, window.innerHeight - r.top) : 0
}
function place() {
  if (props.surface !== 'popover' || !props.anchor) { pos.value = null; return }
  const r = props.anchor.getBoundingClientRect()
  const top = Math.round(r.bottom + 8)
  pos.value = { top, right: Math.max(8, Math.round(window.innerWidth - r.right)),
    maxH: Math.max(160, Math.round(window.innerHeight - top - 12 - bottomReserve())) }
}
const popStyle = computed(() => (props.surface === 'popover' && pos.value
  ? { top: `${pos.value.top}px`, right: `${pos.value.right}px`, maxHeight: `${pos.value.maxH}px` } : undefined))

function rows(): HTMLElement[] {
  return Array.from(rootEl.value?.querySelectorAll<HTMLElement>('[data-csm-row]') || [])
}
function pick(a: SettingsAction) { emit('pick', a) }

function onKey(e: KeyboardEvent) {
  const list = rows()
  const i = list.indexOf(document.activeElement as HTMLElement)
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); emit('close'); return }
  if (e.key === 'Tab' && props.surface === 'popover') { emit('close'); return }
  let next = -1
  if (e.key === 'ArrowDown') next = i < 0 ? 0 : (i + 1) % list.length
  else if (e.key === 'ArrowUp') next = i < 0 ? list.length - 1 : (i - 1 + list.length) % list.length
  else if (e.key === 'Home') next = 0
  else if (e.key === 'End') next = list.length - 1
  if (next >= 0 && list[next]) { e.preventDefault(); list[next].focus() }
}

/* a click outside the popover closes it (the button that opened it toggles it itself) */
function onPointerDown(e: PointerEvent) {
  if (props.surface !== 'popover') return
  const tgt = e.target as Node | null
  if (!tgt || rootEl.value?.contains(tgt) || props.anchor?.contains(tgt)) return
  emit('close')
}

/* the phone sheet closes on a swipe down its handle */
let grabY: number | null = null
function grabStart(e: PointerEvent) {
  grabY = e.clientY
  const move = (ev: PointerEvent) => { if (grabY != null && ev.clientY - grabY > 60) { grabY = null; done(); emit('close') } }
  const done = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', done) }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', done)
}

onMounted(async () => {
  place()
  window.addEventListener('resize', place)
  document.addEventListener('pointerdown', onPointerDown, true)
  await nextTick()
  rows()[0]?.focus()
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', place)
  document.removeEventListener('pointerdown', onPointerDown, true)
})
defineExpose({ place })
</script>

<style scoped>
.csm { position: fixed; z-index: 1200; color: #e6edf3; background: var(--nc-elevated, #181f2e); overflow-y: auto;
  font-family: 'IBM Plex Sans', system-ui, sans-serif; -webkit-font-smoothing: antialiased; }
.csm-pop { width: 380px; max-width: calc(100vw - 16px); border: 1px solid var(--nc-border-strong, #343a4d); border-radius: 10px;
  box-shadow: 0 22px 56px rgba(0, 0, 0, .6), 0 2px 6px rgba(0, 0, 0, .4); padding: 4px 0 0; }
.csm-sheet { left: 0; right: 0; bottom: 0; max-height: calc(100dvh - 48px); border-top: 1px solid var(--nc-border-strong, #343a4d);
  border-radius: 16px 16px 0 0; padding: 4px 0 calc(18px + env(safe-area-inset-bottom)); box-shadow: 0 -12px 40px rgba(0, 0, 0, .5); }
.csm-scrim { position: fixed; inset: 0; z-index: 1199; background: rgba(3, 6, 12, .6); }
.csm-grab { width: 38px; height: 4px; border-radius: 2px; background: #4b5568; margin: 8px auto 6px; touch-action: none; cursor: grab; }
.csm-head { padding: 12px 16px 10px; border-bottom: 1px solid var(--nc-border-subtle, #232833); }
.csm-sheet .csm-head { padding: 4px 18px 12px; }
.csm-title { display: block; font-weight: 400; font-size: 1.02rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.csm-sub, .csm-lbl, .csm-foot, .csm-val { font-family: 'IBM Plex Mono', ui-monospace, monospace; }
.csm-sub { display: block; margin-top: 3px; font-size: .6rem; letter-spacing: .15em; text-transform: uppercase; color: #8b96a5; }
.csm-sec { padding: 4px 0; }
.csm-sec + .csm-sec { border-top: 1px solid var(--nc-border-subtle, #232833); }
.csm-lbl { display: block; padding: 9px 16px 3px; font-size: .58rem; letter-spacing: .17em; text-transform: uppercase; color: #8b96a5; }
.csm-row { display: flex; align-items: center; gap: 12px; width: 100%; min-height: 46px; padding: 7px 16px; background: none; border: 0;
  color: inherit; text-align: left; font: inherit; font-size: .9rem; line-height: 1.3; cursor: pointer; }
.csm-sheet .csm-row { min-height: 54px; font-size: .96rem; padding: 7px 18px; }
.csm-row:hover:not(.csm-static) { background: rgba(var(--nc-primary-rgb, 0, 210, 210), .07); }
.csm-row:focus-visible { outline: none; background: rgba(var(--nc-primary-rgb, 0, 210, 210), .08);
  box-shadow: inset 2px 0 0 var(--nc-primary, #00d2d2), inset 0 0 0 1px rgba(var(--nc-primary-rgb, 0, 210, 210), .45); }
.csm-static { cursor: default; }
.csm-ic { flex: none; width: 16px; height: 16px; opacity: .85; }
.csm-tx { flex: 1; min-width: 0; display: flex; flex-direction: column; }
/* #8b96a5 holds 4.5:1 on --nc-elevated at this size */
.csm-tx small { font-size: .74rem; color: #8b96a5; margin-top: 2px; line-height: 1.35; }
.csm-val { flex: none; font-size: .68rem; letter-spacing: .05em; color: #b4bfcc; white-space: nowrap; }
.csm-chev { flex: none; opacity: .45; font-size: 1rem; }
.csm-sw { position: relative; flex: none; width: 32px; height: 18px; border-radius: 9px; border: 1px solid #556074; }
.csm-sw::after { content: ''; position: absolute; top: 2px; left: 2px; width: 12px; height: 12px; border-radius: 50%; background: #8b96a5; }
.csm-sw.on { border-color: var(--nc-primary, #00d2d2); background: rgba(var(--nc-primary-rgb, 0, 210, 210), .16); }
.csm-sw.on::after { left: 16px; background: var(--nc-primary, #00d2d2); }
.csm-warn { color: #f2b544; }
.csm-warn .csm-tx small { color: #c9a35a; }
.csm-foot { padding: 9px 16px; border-top: 1px solid var(--nc-border-subtle, #232833); font-size: .58rem; letter-spacing: .13em;
  text-transform: uppercase; color: #7d8899; }
</style>
