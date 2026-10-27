<!--
  §bc1 T1.1 — CriticalBanner.vue  (§pass50.1 polish: typography + hierarchy + cap-3)
  Full-width pinned banner above the dashboard header for unread broadcasts
  of type=critical. Multiple critical broadcasts stack vertically (newest on
  top); capped at 3 visible with a "+N more" expand link.

  Each row is a STRONG visual unit: tag + age on a thin top line, then a
  prominent title (1rem bold), then ONE line of body with ellipsis, plus
  CTA + ACK button on the right. Click the row (or "Show full →") to open
  the full broadcast modal via the existing bell modal mechanism.

  Theme: sovereign red (always — bypasses neural/sovereign toggle).
  Z-index: 9500. Pulse animation on icon (respects prefers-reduced-motion).
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useNotificationStore, type BroadcastItem } from '@/stores/notifications'
import { useViewport } from '@/composables/useViewport'

const store = useNotificationStore()
const viewport = useViewport()

const VISIBLE_CAP = 3

const allCritical = computed<BroadcastItem[]>(() =>
  store.items.filter(i => i.broadcast_type === 'critical')
)
const expanded = ref(false)
const visibleCritical = computed<BroadcastItem[]>(() =>
  expanded.value ? allCritical.value : allCritical.value.slice(0, VISIBLE_CAP)
)
const overflowCount = computed(() => Math.max(0, allCritical.value.length - VISIBLE_CAP))

function ack(item: BroadcastItem) {
  store.markRead(item.id)
}

// §bc2 T2.7 — CTA URL allowlist
function isSafeCtaUrl(url: string | null | undefined): boolean {
  if (!url) return false
  try {
    if (url.startsWith('/')) return true
    const parsed = new URL(url, window.location.origin)
    return parsed.protocol === 'https:'
  } catch {
    return false
  }
}

function showFull(item: BroadcastItem) {
  // Open the existing bell modal by dispatching a window event the bell
  // listens for, then setting its modalItem via store.
  try {
    window.dispatchEvent(new CustomEvent('theprotocol:open-notification-bell', {
      detail: { broadcastId: item.id },
    }))
  } catch (_) { /* ignore */ }
}

function bodyOneLine(text: string): string {
  // Strip markdown bold + collapse whitespace; banner shows ONE line max
  return text
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}
</script>

<template>
  <Transition name="cb-stack">
    <div
      v-if="allCritical.length > 0"
      class="cb-stack"
      :class="{ 'is-mobile': viewport.isSmallPhone.value }"
      role="alert"
      aria-live="assertive"
    >
      <TransitionGroup name="cb-row">
        <article
          v-for="item in visibleCritical"
          :key="item.id"
          class="cb-row"
        >
          <div class="cb-row__inner">
            <div class="cb-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor"
                   stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                <line x1="12" y1="9" x2="12" y2="13"/>
                <line x1="12" y1="17" x2="12.01" y2="17"/>
              </svg>
            </div>
            <div class="cb-content">
              <div class="cb-meta">
                <span class="cb-tag">CRITICAL</span>
                <span class="cb-age">{{ relativeTime(item.created_at) }}</span>
              </div>
              <h3 class="cb-title">{{ item.title }}</h3>
              <div class="cb-body" :title="item.body">{{ bodyOneLine(item.body) }}</div>
            </div>
            <div class="cb-actions">
              <a
                v-if="isSafeCtaUrl(item.cta_url)"
                :href="item.cta_url!"
                class="cb-cta"
                target="_blank"
                rel="noopener noreferrer"
                @click.stop
              >{{ item.cta_label || 'Learn more' }} &rsaquo;</a>
              <button
                class="cb-show-full"
                type="button"
                @click.stop="showFull(item)"
              >Show full</button>
              <button
                class="cb-ack"
                type="button"
                @click.stop="ack(item)"
                :aria-label="`Acknowledge critical broadcast #${item.id}: ${item.title}`"
              >ACKNOWLEDGE</button>
            </div>
          </div>
        </article>
      </TransitionGroup>
      <button
        v-if="overflowCount > 0 && !expanded"
        class="cb-overflow"
        type="button"
        @click="expanded = true"
      >&plus; {{ overflowCount }} more critical {{ overflowCount === 1 ? 'alert' : 'alerts' }} &mdash; show all</button>
      <button
        v-else-if="expanded && allCritical.length > VISIBLE_CAP"
        class="cb-overflow"
        type="button"
        @click="expanded = false"
      >Collapse</button>
    </div>
  </Transition>
</template>

<style scoped>
.cb-stack {
  position: sticky;
  top: 0;
  left: 0;
  right: 0;
  z-index: 9500;
  display: flex;
  flex-direction: column;
  gap: 0;
  width: 100%;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  pointer-events: none;
}

.cb-row {
  pointer-events: all;
  background: linear-gradient(180deg, #2a0808 0%, #1a0404 100%);
  border-bottom: 1px solid rgba(220, 38, 38, 0.45);
  box-shadow:
    inset 0 1px 0 rgba(255, 80, 80, 0.18),
    0 6px 18px rgba(220, 38, 38, 0.12);
  color: #ffe7e7;
}
.cb-row + .cb-row {
  border-top: 1px solid rgba(220, 38, 38, 0.18);
}

.cb-row__inner {
  display: grid;
  grid-template-columns: 36px 1fr auto;
  gap: 1rem;
  align-items: center;
  padding: 0.85rem 1.25rem;
  max-width: 1600px;
  margin: 0 auto;
}
.is-mobile .cb-row__inner {
  grid-template-columns: 28px 1fr;
  gap: 0.55rem;
  padding: 0.7rem 0.85rem;
}
.is-mobile .cb-actions {
  grid-column: 1 / -1;
  margin-top: 0.45rem;
  width: 100%;
  justify-content: space-between;
}

.cb-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fca5a5;
  animation: cb-pulse 2.2s ease-in-out infinite;
}
@media (prefers-reduced-motion: reduce) {
  .cb-icon { animation: none; }
}
@keyframes cb-pulse {
  0%, 100% { transform: scale(1); opacity: 0.78; }
  50%      { transform: scale(1.12); opacity: 1; }
}

.cb-content { min-width: 0; display: flex; flex-direction: column; gap: 0.18rem; }

.cb-meta {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  font-size: 0.6rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}
.cb-tag {
  color: #fca5a5;
  font-weight: 800;
  background: rgba(220, 38, 38, 0.25);
  padding: 2px 8px;
  border-radius: 3px;
  letter-spacing: 0.2em;
}
.cb-age {
  color: rgba(252, 165, 165, 0.6);
  font-weight: 600;
}

.cb-title {
  font-size: 1rem;
  font-weight: 700;
  color: #fff5f5;
  line-height: 1.25;
  margin: 0;
  letter-spacing: 0.005em;
  /* Cap title to 1 line if exceptionally long */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.is-mobile .cb-title {
  font-size: 0.9rem;
  white-space: normal; /* allow 2-line wrap on phones */
}

.cb-body {
  font-size: 0.78rem;
  color: rgba(254, 226, 226, 0.78);
  line-height: 1.45;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  word-break: break-word;
}
.is-mobile .cb-body { font-size: 0.72rem; white-space: normal;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}

.cb-actions {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-shrink: 0;
}
.cb-cta {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: #fff;
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
}
.cb-cta:hover { color: #fee2e2; text-decoration-thickness: 2px; }

.cb-show-full {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  letter-spacing: 0.06em;
  background: transparent;
  border: 1px solid rgba(220, 38, 38, 0.4);
  color: rgba(254, 226, 226, 0.85);
  padding: 5px 10px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.cb-show-full:hover {
  background: rgba(220, 38, 38, 0.18);
  border-color: rgba(220, 38, 38, 0.75);
  color: #fff;
}

.cb-ack {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.16em;
  background: #dc2626;
  color: #fff;
  border: 1px solid #ef4444;
  border-radius: 4px;
  padding: 0.55rem 1.05rem;
  cursor: pointer;
  transition: background 0.15s, transform 0.06s;
  white-space: nowrap;
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.12) inset, 0 2px 8px rgba(220, 38, 38, 0.35);
}
.cb-ack:hover {
  background: #ef4444;
}
.cb-ack:active {
  transform: translateY(1px);
}
.cb-ack:focus-visible {
  outline: 2px solid #fca5a5;
  outline-offset: 2px;
}

.cb-overflow {
  pointer-events: all;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  background: rgba(0, 0, 0, 0.45);
  color: rgba(254, 226, 226, 0.7);
  border: none;
  border-bottom: 1px solid rgba(220, 38, 38, 0.3);
  padding: 0.45rem 1.25rem;
  cursor: pointer;
  width: 100%;
  text-align: center;
}
.cb-overflow:hover { color: #fff; background: rgba(0, 0, 0, 0.65); }

/* Transitions */
.cb-stack-enter-active, .cb-stack-leave-active { transition: opacity 0.18s; }
.cb-stack-enter-from, .cb-stack-leave-to { opacity: 0; }

.cb-row-enter-active, .cb-row-leave-active { transition: max-height 0.25s ease, opacity 0.18s; overflow: hidden; }
.cb-row-enter-from, .cb-row-leave-to { max-height: 0; opacity: 0; }
.cb-row-enter-to, .cb-row-leave-from { max-height: 200px; opacity: 1; }
@media (prefers-reduced-motion: reduce) {
  .cb-row-enter-active, .cb-row-leave-active { transition: none; }
  .cb-stack-enter-active, .cb-stack-leave-active { transition: none; }
}
</style>
