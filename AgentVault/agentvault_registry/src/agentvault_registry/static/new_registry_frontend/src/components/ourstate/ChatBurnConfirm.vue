<!--
  V0652 (ak) (order gwo_8c69cc0fd1f3033a35f47969): burning a thread for you, its sentence first, then the hold.
  The server burns FOR YOU (burn_for_me: your history before now goes, on every device); the others keep theirs, and the
  registry that hosts the thread keeps it until your account is deleted; the client also deletes any copy this device
  holds. session-lead's review (seq 397): the registry is named from the thread's hosting, never a literal (1); "any
  copy on this device" (2); Cancel has the focus, and the hold needs a fresh press, so an Enter still held from the menu
  cannot start it (4). The hold works with a pointer or with Space or Enter held down.
-->
<template>
  <div class="ost-sheet-veil" @click.self="emit('cancel')">
    <div class="ost-sheet cbc" role="alertdialog" aria-modal="true" :aria-label="t('ourstate.burn.title', 'Burn this thread for you?')"
         data-testid="ost-burn-confirm">
      <h3>{{ t('ourstate.burn.title', 'Burn this thread for you?') }}</h3>
      <ul class="cbc-facts">
        <li data-testid="cbc-yours">{{ t('ourstate.burn.yours', 'Its history up to now leaves your account, on every device.') }}</li>
        <li data-testid="cbc-kept">{{ keptLine }}</li>
        <li>{{ t('ourstate.burn.device', 'Any copy on this device is deleted now.') }}</li>
      </ul>
      <p class="cbc-warn">{{ t('ourstate.burn.final', 'This cannot be undone. New messages after it still reach you.') }}</p>
      <div class="ost-sheet-btns cbc-btns">
        <button ref="cancelEl" class="ost-btn" data-testid="cbc-cancel" @click="emit('cancel')">{{ t('common.cancel', 'Cancel') }}</button>
        <button class="ost-btn cbc-hold" data-testid="ost-burn-hold" :aria-label="t('ourstate.burn.holdAria', 'Hold to burn')"
                @pointerdown="start" @pointerup="stop" @pointerleave="stop" @pointercancel="stop"
                @keydown="onKeyDown" @keyup="onKeyUp" @blur="stop" @click.prevent>
          <span class="cbc-fill" :style="{ width: pct + '%' }" aria-hidden="true" />
          <span class="cbc-label"><Icon name="mdi:fire" />{{ pct > 0 ? t('ourstate.burn.holding', 'Keep holding…') : t('ourstate.burn.hold', 'Hold to burn') }}</span>
        </button>
      </div>
      <p class="cbc-kbd">{{ t('ourstate.burn.how', 'Press and hold for 1.2 s, or hold Space or Enter. Let go to stop.') }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'

const BURN_HOLD_MS = 1200

const props = withDefaults(defineProps<{
  /** The thread's hosting, as the thread read it: the host and every registry that keeps a copy. */
  hosting?: { registry?: string | null; copies?: string[] | null } | null
}>(), { hosting: null })
const emit = defineEmits<{ (e: 'cancel'): void; (e: 'burn'): void }>()
const { t, tp } = useI18n()

const keptLine = computed(() => {
  const reg = String(props.hosting?.registry || '').trim()
  const copies = (props.hosting?.copies || []).filter(Boolean)
  if (!reg) return t('ourstate.burn.keptUnknown', 'The others keep theirs. The registry that hosts it keeps the thread until your account is deleted.')
  if (copies.length) return tp('ourstate.burn.keptCopies', 'The others keep theirs. {reg} keeps the thread until your account is deleted; {copies} keep their copies.', { reg, copies: copies.join(', ') })
  return tp('ourstate.burn.kept', 'The others keep theirs. {reg} keeps the thread until your account is deleted.', { reg })
})

const cancelEl = ref<HTMLButtonElement | null>(null)
const pct = ref(0)
let timer: ReturnType<typeof setInterval> | null = null
let fired = false

function start() {
  if (timer || fired) return
  const t0 = Date.now()
  timer = setInterval(() => {
    pct.value = Math.min(100, ((Date.now() - t0) / BURN_HOLD_MS) * 100)
    if (pct.value >= 100 && !fired) { fired = true; stop(); emit('burn') }
  }, 40)
}
function stop() {
  if (timer) { clearInterval(timer); timer = null }
  if (!fired) pct.value = 0
}
/* a fresh press only: a key still held (auto-repeat) from the row that opened this never starts the hold */
function onKeyDown(e: KeyboardEvent) {
  if (e.key !== ' ' && e.key !== 'Enter') return
  e.preventDefault()
  if (e.repeat) return
  start()
}
function onKeyUp(e: KeyboardEvent) {
  if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); stop() }
}

/* a hold whose key-up never comes (the window lost the focus, the tab hid) stops: it is not a hold any more
   (session-lead's follow-up on (ak), seq 406) */
const onHidden = () => { if (document.visibilityState === 'hidden') stop() }
onMounted(async () => {
  window.addEventListener('blur', stop)
  document.addEventListener('visibilitychange', onHidden)
  await nextTick()
  cancelEl.value?.focus()
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('blur', stop)
  document.removeEventListener('visibilitychange', onHidden)
})
</script>

<style scoped>
/* the chat's sheet, as the thread draws its own (its scoped rules do not reach a child component) */
.ost-sheet-veil { position: fixed; inset: 0; background: rgba(0,0,0,.5); display: flex; align-items: flex-end; justify-content: center; z-index: 60; }
.ost-sheet { width: 100%; max-width: 480px; max-height: 82vh; overflow-y: auto; background: var(--surface-1, #16181d); border-radius: 16px 16px 0 0;
  padding: 16px 16px calc(16px + env(safe-area-inset-bottom)); display: flex; flex-direction: column; gap: 10px; }
.ost-sheet-btns { display: flex; gap: 8px; justify-content: flex-end; }
.ost-sheet-input { width: 100%; min-height: 44px; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--border-color, rgba(128,128,128,.3));
  background: none; color: inherit; font: inherit; font-size: 16px; box-sizing: border-box; }
.ost-btn { min-height: 44px; padding: 0 18px; border-radius: 10px; border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: none;
  color: inherit; font-weight: 600; cursor: pointer; }
.ost-accept { background: var(--primary-color, #4fd8c4); color: #06211d; border-color: transparent; }
.ost-danger { background: var(--warning-color, #f59e0b); color: #1a1206; border-color: transparent; }
.ost-btn:disabled { opacity: .4; cursor: not-allowed; filter: saturate(.4); }
.cbc h3 { margin: 0; font-weight: 400; }
.cbc-facts { margin: 4px 0 8px; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 8px; }
.cbc-facts li { position: relative; padding-left: 16px; font-size: .92rem; line-height: 1.45; }
.cbc-facts li::before { content: ''; position: absolute; left: 2px; top: .6em; width: 5px; height: 5px; border: 1px solid #f2b544; transform: rotate(45deg); }
.cbc-warn { margin: 0; font-size: .84rem; color: #c9a35a; }
.cbc-btns { margin-top: 8px; }
.cbc-hold { position: relative; overflow: hidden; border: 1px solid #f2b544 !important; color: #f2b544 !important; background: rgba(242, 181, 68, .06) !important; }
.cbc-fill { position: absolute; left: 0; top: 0; bottom: 0; background: rgba(242, 181, 68, .24); pointer-events: none; }
.cbc-label { position: relative; display: inline-flex; align-items: center; gap: 8px; }
.cbc-kbd { margin: 6px 0 0; font-size: .74rem; color: #8b96a5; text-align: right; }
</style>
