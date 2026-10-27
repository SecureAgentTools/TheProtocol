<!--
  §bc1 polish: cap visible stack at 3 toasts; show overflow pill
  "+N more" that opens the bell dropdown via a custom 'open-bell' event.
  Mobile (<640): toasts dock to bottom, width 100vw - 1rem.
  Critical toasts are sticky (no auto-dismiss) — their close button is the
  only way to remove them (or via store.markRead from the banner).
-->
<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { computed } from 'vue'
import { useNotificationStore } from '@/stores/notifications'
import { useViewport } from '@/composables/useViewport'

const store = useNotificationStore()
const viewport = useViewport()

const TOAST_CAP = 3

const visibleToasts = computed(() => store.toasts.slice(0, TOAST_CAP))
const overflowCount = computed(() => Math.max(0, store.toasts.length - TOAST_CAP))

function typeColor(t: string): string {
  if (t === 'critical') return '#ff4444'
  if (t === 'maintenance') return '#ff9100'
  if (t === 'warning') return '#ffb300'
  return 'var(--nc-primary)'
}

/**
 * §TOASTPOLISH (2026-07-27): these were raw emoji (🚨 🔧 ⚠️ 📢), which is the one thing the
 * design language forbids outright — every other surface renders inline SVG through
 * components/Icon.vue. Each name below was CHECKED against Icon.vue's local map first: an
 * unknown name blank-renders silently (standing gotcha), so an unverified swap would have
 * traded an ugly icon for an invisible one.
 */
function typeIcon(t: string): string {
  if (t === 'critical') return 'mdi:alert-octagon'
  if (t === 'maintenance') return 'mdi:wrench'
  if (t === 'warning') return 'mdi:alert'
  return 'mdi:bullhorn'
}

// §bc2 T2.7 — CTA URL sanitizer (mirrors CriticalBanner — allowlist https:// + same-origin)
function isSafeCtaUrl(url: string | null | undefined): boolean {
  if (!url) return false
  try {
    if (url.startsWith('/')) return true
    const parsed = new URL(url, window.location.origin)
    return parsed.protocol === 'https:'
  } catch { return false }
}

/**
 * §bc1 T1.5 — clicking the overflow pill should open the bell dropdown.
 * Bell is rendered in the header; we communicate via a window CustomEvent
 * so we don't need a singleton store coupling. Bell subscribes to this
 * event in onMounted and toggles open.
 */
function openBellAndDismiss() {
  try {
    window.dispatchEvent(new CustomEvent('theprotocol:open-notification-bell'))
  } catch (_) { /* ignore */ }
  // Also clear overflow toasts (we just funneled the user to the bell where
  // they can see them all).
  for (const t of store.toasts.slice(TOAST_CAP)) {
    store.dismissToast(t.toast_id)
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      class="nt-stack"
      :class="{ 'is-mobile': viewport.isSmallPhone.value }"
    >
      <TransitionGroup name="nt-slide">
        <div
          v-for="toast in visibleToasts"
          :key="toast.toast_id"
          class="nt-toast"
          :class="{
            'is-critical': toast.broadcast_type === 'critical',
            'is-warning': toast.broadcast_type === 'warning',
            'is-maintenance': toast.broadcast_type === 'maintenance',
            'is-info': toast.broadcast_type === 'info',
            'is-sticky-ack': toast.requires_ack,
          }"
          :style="{ borderLeftColor: typeColor(toast.broadcast_type) }"
          @click="toast.requires_ack ? null : store.dismissToast(toast.toast_id)"
        >
          <div class="nt-top">
            <span class="nt-icon" :style="{ color: typeColor(toast.broadcast_type) }">
              <Icon :name="typeIcon(toast.broadcast_type)" />
            </span>
            <span class="nt-type" :style="{ color: typeColor(toast.broadcast_type) }">
              {{ toast.broadcast_type.toUpperCase() }}
            </span>
            <!-- §bc2 T2.8 — lock icon when requires_ack -->
            <span v-if="toast.requires_ack" class="nt-lock" title="Requires acknowledgement"><Icon name="mdi:lock" /></span>
            <button
              v-if="!toast.requires_ack"
              class="nt-close"
              @click.stop="store.dismissToast(toast.toast_id)"
              aria-label="Dismiss"
            >×</button>
          </div>
          <div class="nt-title">{{ toast.title }}</div>
          <!-- §pass50.1 — body clamped to 1 line for cleaner stack; full text on hover via title= -->
          <div class="nt-body" :title="toast.body">{{ toast.body }}</div>
          <!-- §bc2 T2.7 — CTA + §bc2 T2.8 ACK button when requires_ack -->
          <div v-if="isSafeCtaUrl(toast.cta_url) || toast.requires_ack" class="nt-actions">
            <a
              v-if="isSafeCtaUrl(toast.cta_url)"
              :href="toast.cta_url!"
              class="nt-cta"
              target="_blank"
              rel="noopener noreferrer"
              @click.stop
            >{{ toast.cta_label || 'Learn more' }} →</a>
            <button
              v-if="toast.requires_ack"
              class="nt-ack"
              @click.stop="store.markRead(toast.id)"
            >ACKNOWLEDGE</button>
          </div>
        </div>
        <button
          v-if="overflowCount > 0"
          key="overflow-pill"
          class="nt-overflow"
          @click="openBellAndDismiss"
          type="button"
        >+{{ overflowCount }} more · open inbox</button>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.nt-stack {
  position: fixed;
  bottom: 1.5rem;
  right: 1.5rem;
  z-index: 99999;
  display: flex;
  flex-direction: column-reverse;
  gap: 0.6rem;
  pointer-events: none;
  max-width: 360px;
}
.nt-stack.is-mobile {
  bottom: 0.75rem;
  right: 0.5rem;
  left: 0.5rem;
  max-width: none;
}

/* §TOASTPOLISH — was a flat #070d18 slab with a hard edge. Brought in line with the rest of
   the design language: layered surface gradient, a hairline top highlight, a corner accent
   bracket, and a hover lift instead of a crude opacity fade. */
.nt-toast {
  position: relative;
  width: 320px;
  background:
    linear-gradient(180deg, rgba(var(--nc-primary-rgb),0.055) 0%, rgba(var(--nc-primary-rgb),0) 46%),
    linear-gradient(158deg, #0a1322 0%, #060b14 100%);
  border: 1px solid rgba(var(--nc-primary-rgb),0.18);
  border-left: 3px solid var(--nc-primary);
  border-radius: 3px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.62), inset 0 1px 0 rgba(var(--nc-primary-rgb),0.14);
  padding: 0.9rem 1rem;
  cursor: pointer;
  pointer-events: all;
  overflow: hidden;
  transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
}
/* corner accent bracket — the same motif the admin panels use */
.nt-toast::after {
  content: '';
  position: absolute;
  top: 0; right: 0;
  width: 14px; height: 14px;
  border-top: 1px solid rgba(var(--nc-primary-rgb),0.5);
  border-right: 1px solid rgba(var(--nc-primary-rgb),0.5);
  pointer-events: none;
}
.nt-toast:hover {
  transform: translateY(-1px);
  border-color: rgba(var(--nc-primary-rgb),0.34);
  box-shadow: 0 14px 36px rgba(0,0,0,0.7), inset 0 1px 0 rgba(var(--nc-primary-rgb),0.2);
}
@media (prefers-reduced-motion: reduce) {
  .nt-toast, .nt-toast:hover { transition: none; transform: none; }
}
.is-mobile .nt-toast { width: 100%; }
.nt-toast.is-critical {
  border-color: rgba(220, 38, 38, 0.45);
  border-left-color: #ff4444 !important;
  background: linear-gradient(160deg, #1a0404 0%, #070d18 70%);
}

.nt-top {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.35rem;
}
.nt-icon {
  display: inline-flex;
  align-items: center;
  font-size: 0.86rem;
  line-height: 1;
  filter: drop-shadow(0 0 6px currentColor);
  opacity: 0.95;
}
.nt-type {
  font-size: 0.55rem;
  letter-spacing: 0.14em;
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 700;
}
.nt-close {
  margin-left: auto;
  background: none;
  border: none;
  color: #556677;
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
  padding: 0 0.4rem;
  min-height: 24px;
  min-width: 24px;
}
.nt-close:hover { color: var(--nc-primary); }

.nt-title {
  font-size: 0.9rem;
  font-weight: 700;
  color: #e0ecf4;
  margin-bottom: 0.25rem;
  line-height: 1.3;
  /* §pass50.1 — give title prominence + 1-line clamp for stack consistency */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.nt-body {
  font-size: 0.74rem;
  color: #8899aa;
  line-height: 1.5;
  /* §pass50.1 — 1-line ellipsis (was 2-line wall of text); full text on hover */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nt-lock { font-size: 0.7rem; margin-left: 0.3rem; }
.nt-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.5rem;
  align-items: center;
  flex-wrap: wrap;
}
.nt-cta {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem;
  color: var(--nc-primary);
  text-decoration: underline;
  text-underline-offset: 3px;
  letter-spacing: 0.04em;
}
.nt-cta:hover { color: #fff; }
.nt-ack {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  background: rgba(var(--nc-primary-rgb), 0.18);
  color: var(--nc-primary);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.5);
  border-radius: 4px;
  padding: 4px 9px;
  cursor: pointer;
}
.nt-ack:hover { background: rgba(var(--nc-primary-rgb), 0.35); color: #fff; }
.is-sticky-ack .nt-ack {
  background: rgba(220, 38, 38, 0.18);
  color: #fca5a5;
  border-color: rgba(220, 38, 38, 0.5);
}
.is-sticky-ack .nt-ack:hover { background: rgba(220, 38, 38, 0.35); color: #fff; }

.nt-overflow {
  pointer-events: all;
  background: rgba(var(--nc-primary-rgb), 0.06);
  border: 1px dashed rgba(var(--nc-primary-rgb), 0.32);
  color: rgba(var(--nc-primary-rgb), 0.85);
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.7rem;
  letter-spacing: 0.06em;
  padding: 0.45rem 0.75rem;
  border-radius: 4px;
  cursor: pointer;
  min-height: 32px;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.nt-overflow:hover {
  background: rgba(var(--nc-primary-rgb), 0.14);
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  color: var(--nc-primary);
}

/* Transitions */
.nt-slide-enter-active,
.nt-slide-leave-active { transition: all 0.2s ease; }
.nt-slide-enter-from { opacity: 0; transform: translateX(24px); }
.nt-slide-leave-to { opacity: 0; transform: translateX(24px); }
@media (prefers-reduced-motion: reduce) {
  .nt-slide-enter-active, .nt-slide-leave-active { transition: none; }
}

/* §bc3 T3.5 — type-coded entry animations (3 distinct per-type flash effects) */
.nt-toast.is-critical {
  animation: nt-pulse-red 1.6s ease-in-out 0s 2;
}
.nt-toast.is-warning {
  animation: nt-flash-amber 1.1s ease-out;
}
.nt-toast.is-maintenance {
  animation: nt-shimmer-cyan 1.4s ease-out;
}
.nt-toast.is-info {
  animation: nt-subtle 0.35s ease-out;
}
@keyframes nt-pulse-red {
  0%, 100% { box-shadow: 0 6px 24px rgba(0,0,0,0.7), 0 0 0 0 rgba(255,68,68,0); }
  50%      { box-shadow: 0 6px 24px rgba(0,0,0,0.7), 0 0 18px 2px rgba(255,68,68,0.5); }
}
/* §TOASTPOLISH — animate background-COLOR, not the `background` shorthand: the shorthand wiped
   the new layered gradient for the duration of the flash and snapped it back, which read as a
   flicker. Colour sits under the (semi-transparent) gradient layers instead. */
@keyframes nt-flash-amber {
  0%   { background-color: #2a1c00; box-shadow: 0 10px 30px rgba(0,0,0,0.62), 0 0 12px 1px rgba(255,179,0,0.6); }
  100% { background-color: #060b14; box-shadow: 0 10px 30px rgba(0,0,0,0.62), 0 0 0 0 transparent; }
}
@keyframes nt-shimmer-cyan {
  0%   { background-position: -150% 0; background-image: linear-gradient(115deg, transparent 0%, rgba(var(--nc-primary-rgb),0.06) 50%, transparent 100%); }
  100% { background-position: 250% 0; background-image: linear-gradient(115deg, transparent 0%, rgba(var(--nc-primary-rgb),0.06) 50%, transparent 100%); }
}
.nt-toast.is-maintenance {
  background-size: 250% 100%;
  background-color: #070d18;
}
@keyframes nt-subtle {
  0%   { transform: translateX(8px); opacity: 0.6; }
  100% { transform: translateX(0); opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .nt-toast.is-critical,
  .nt-toast.is-warning,
  .nt-toast.is-maintenance,
  .nt-toast.is-info { animation: none; background-image: none; }
}
</style>
