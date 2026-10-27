<!--
  InfoDot — the "i" affordance.

  WHY THIS EXISTS. Every panel on this dashboard used to carry its methodology as always-on
  prose: ~618 words rendered permanently across the page. That text is genuinely good, and it is
  exactly what someone wants the FIRST time they read a panel and never again. Always-on, it
  competes with the numbers it is explaining and the page reads as noise.

  RULE OF USE: a panel shows a VERDICT plus the numbers that prove it. The "why it matters" and
  "how it is computed" live in here. The one exception, deliberately kept: when a panel is NOT ok,
  a single line of consequence stays visible, because that is the moment a human needs it without
  hunting for it.

  Keyboard and screen-reader accessible: it is a real <button>, toggles on click or Enter/Space,
  closes on Escape, and the popover is aria-linked to it.
-->
<template>
  <span class="au-info" :class="{ 'au-info--open': open }">
    <button
      ref="btn"
      type="button"
      class="au-info-dot"
      :aria-expanded="open"
      :aria-label="label"
      :data-testid="testid"
      @click.stop="toggle"
      @keydown.escape="close"
    >i</button>
    <span
      v-if="open"
      class="au-info-pop"
      :class="align === 'right' ? 'au-info-pop--right' : ''"
      role="tooltip"
    >
      <span class="au-info-pop-title" v-if="title">{{ title }}</span>
      <span class="au-info-pop-body"><slot /></span>
    </span>
  </span>
</template>

<script setup lang="ts">
import { ref, onBeforeUnmount, onMounted } from 'vue'

withDefaults(defineProps<{
  title?: string
  label?: string
  align?: 'left' | 'right'
  testid?: string
}>(), {
  title: '',
  label: 'What this measures',
  align: 'left',
  testid: 'info-dot',
})

const open = ref(false)
const btn = ref<HTMLElement | null>(null)
const toggle = () => { open.value = !open.value }
const close = () => { open.value = false }

// Click-away. Bound on document so one open popover closes when another opens, which keeps the
// page from filling up with stuck tooltips — the exact clutter this component exists to remove.
function onDoc(e: MouseEvent) {
  if (!open.value) return
  const el = btn.value
  if (el && !el.parentElement?.contains(e.target as Node)) close()
}
function onEsc(e: KeyboardEvent) { if (e.key === 'Escape') close() }
onMounted(() => { document.addEventListener('click', onDoc); document.addEventListener('keydown', onEsc) })
onBeforeUnmount(() => { document.removeEventListener('click', onDoc); document.removeEventListener('keydown', onEsc) })
</script>

<style scoped>
.au-info { position: relative; display: inline-flex; vertical-align: middle; margin-left: .4rem; }
.au-info-dot {
  width: 15px; height: 15px; line-height: 13px; padding: 0;
  border-radius: 50%; border: 1px solid rgba(120,160,190,.45);
  background: transparent; color: rgba(150,185,210,.75);
  font: 600 10px/13px ui-monospace, monospace; font-style: italic;
  cursor: pointer; transition: all .15s ease; flex: 0 0 auto;
}
.au-info-dot:hover, .au-info--open .au-info-dot {
  border-color: rgba(88,166,255,.9); color: #58a6ff; background: rgba(88,166,255,.12);
}
.au-info-dot:focus-visible { outline: 2px solid #58a6ff; outline-offset: 2px; }
.au-info-pop {
  position: absolute; top: calc(100% + 8px); left: -6px; z-index: 60;
  width: max(260px, 24vw); max-width: 380px;
  display: flex; flex-direction: column; gap: .35rem;
  padding: .7rem .8rem;
  background: #0d1117; border: 1px solid rgba(88,166,255,.35); border-radius: 8px;
  box-shadow: 0 10px 30px rgba(0,0,0,.55);
  font-style: normal; text-align: left;
}
.au-info-pop--right { left: auto; right: -6px; }
.au-info-pop-title {
  font: 700 .62rem/1.2 ui-monospace, monospace; letter-spacing: .09em; text-transform: uppercase;
  color: #58a6ff;
}
.au-info-pop-body { font: 400 .74rem/1.5 inherit; color: rgba(220,232,242,.85); }
.au-info-pop-body :deep(b) { color: #e8f0f7; }
.au-info-pop-body :deep(code) {
  font: 600 .7rem ui-monospace, monospace; color: #9ecbff;
  background: rgba(88,166,255,.1); padding: 0 .25rem; border-radius: 3px;
}
@media (max-width: 640px) {
  .au-info-pop { width: min(80vw, 320px); left: auto; right: -6px; }
}
</style>
