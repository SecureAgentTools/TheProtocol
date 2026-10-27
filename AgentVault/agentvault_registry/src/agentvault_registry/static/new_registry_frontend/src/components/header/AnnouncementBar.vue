<script setup lang="ts">
/**
 * The announcement bar: the header strip's still alternative to the LED ticker (§ALERTS header strip, 2026-10-06,
 * agentvault2-09; his words "can we make the new announcement bar optional in the settings? i really like the led").
 * Settings > Preferences > Header strip chooses it; the LED stays the default.
 *
 * One broadcast at a time, in plain type: its kind, its title, one line of its body, its age. Several rotate every
 * 8 seconds (paused while the pointer or the focus is on the bar; no fade for a reduced-motion setting) and can be
 * stepped. A press opens the broadcast in the bell's modal; the x marks it read. It reads the same notification store
 * as the bell (one read, one unread set), and a failed read says so with a way to try again. For an admin the right end
 * carries the alert chip (vmalert's alerts, services/header/activeAlerts.ts): a count, never "no alerts" for a read
 * that failed; a press opens the Health Monitor's alert list.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { hasAdminFlag } from '@/composables/usePermissions'
import { useNotificationStore } from '@/stores/notifications'
import Icon from '@/components/Icon.vue'
import { alertsChip, oneLine, orderBroadcasts, shortAge } from '@/services/header/headerStrip'
import { acquireActiveAlerts, activeAlerts, refreshActiveAlerts } from '@/services/header/activeAlerts'

const { t } = useI18n()
const tt = (key: string, fallback: string): string => t(key, fallback)
const router = useRouter()
const authStore = useAuthStore()
const notif = useNotificationStore()

const ROTATE_MS = 8000

const ordered = computed(() => orderBroadcasts(notif.items))
const index = ref(0)
const current = computed(() => (ordered.value.length ? ordered.value[Math.min(index.value, ordered.value.length - 1)] : null))
watch(() => ordered.value.length, (n) => { if (index.value >= n) index.value = 0 })

/** "no new broadcasts" only after a read said so; a failed read with nothing to show says it failed */
const readState = computed<'items' | 'failed' | 'loading' | 'none'>(() => {
  if (ordered.value.length) return 'items'
  if (notif.unreadFailed) return 'failed'
  if (!notif.lastReadAt) return 'loading'
  return 'none'
})

// D6-837 (agentvault2-69's find, 2026-10-25): GET /admin/alerts/active asks for admin_platform
// (routers/admin_health.get_active_alerts); asked whenever isAdmin held (any of the five admin flags), it refused a
// treasury-only or support-only admin on every page (403). The same rule as the route: is_admin or admin_platform.
const canReadAlerts = computed(() => hasAdminFlag(authStore.user, 'platform'))
// an admin's chip only: the shared reader starts at `loading` and only an admin ever reads it, so for anyone else
// its state says nothing about them
const chip = computed(() => (canReadAlerts.value
  ? alertsChip(activeAlerts.state, activeAlerts.counts, activeAlerts.reason, tt, activeAlerts.withheldInhibited || 0)
  : { show: false, tone: 'dim' as const, label: '', title: '' }))

function typeIcon(type: string): string {
  if (type === 'critical' || type === 'warning') return 'mdi:alert'
  if (type === 'maintenance') return 'mdi:wrench'
  return 'mdi:bullhorn'
}
function typeLabel(type: string): string {
  if (type === 'critical') return t('headerStrip.typeCritical', 'Critical')
  if (type === 'warning') return t('headerStrip.typeWarning', 'Warning')
  if (type === 'maintenance') return t('headerStrip.typeMaintenance', 'Maintenance')
  return t('headerStrip.typeInfo', 'Notice')
}

function step(delta: number) {
  const n = ordered.value.length
  if (n < 2) return
  index.value = (index.value + delta + n) % n
}

function openCurrent() {
  if (!current.value) return
  try {
    window.dispatchEvent(new CustomEvent('theprotocol:open-notification-bell', { detail: { broadcastId: current.value.id } }))
  } catch (_) { /* ignore */ }
}

function markCurrentRead() {
  if (current.value) void notif.markRead(current.value.id)
}

function openAlerts() {
  if (activeAlerts.state === 'unreadable') { void refreshActiveAlerts(); return }
  void router.push({ path: '/health-monitor', query: { tab: 'prometheus' } })
}

// ── rotation: paused while the person is on the bar ──
const hovered = ref(false)
const focused = ref(false)
const reducedMotion = ref(false)
let timer: ReturnType<typeof setInterval> | null = null
let motionQuery: MediaQueryList | null = null
function onMotion() { reducedMotion.value = !!motionQuery?.matches }

let releaseAlerts: (() => void) | null = null
watch(() => canReadAlerts.value, (admin) => {
  if (admin && !releaseAlerts) releaseAlerts = acquireActiveAlerts()
  if (!admin && releaseAlerts) { releaseAlerts(); releaseAlerts = null }
}, { immediate: true })

onMounted(() => {
  motionQuery = window.matchMedia?.('(prefers-reduced-motion: reduce)') ?? null
  onMotion()
  motionQuery?.addEventListener?.('change', onMotion)
  timer = setInterval(() => {
    if (!hovered.value && !focused.value && !(typeof document !== 'undefined' && document.hidden)) step(1)
  }, ROTATE_MS)
})

onUnmounted(() => {
  if (timer) { clearInterval(timer); timer = null }
  motionQuery?.removeEventListener?.('change', onMotion)
  if (releaseAlerts) { releaseAlerts(); releaseAlerts = null }
})
</script>

<template>
  <div
    class="ab-wrap"
    data-testid="announcement-bar"
    :data-state="readState"
    @pointerenter="hovered = true"
    @pointerleave="hovered = false"
    @focusin="focused = true"
    @focusout="focused = false"
  >
    <div class="ab-main" aria-live="polite">
      <template v-if="readState === 'items' && current">
        <button
          type="button"
          class="ab-open"
          :class="'ab-type-' + current.broadcast_type"
          :data-broadcast-id="current.id"
          data-testid="ab-open"
          :title="t('headerStrip.openBroadcast', 'Open this broadcast')"
          @click.stop="openCurrent"
        >
          <Transition :name="reducedMotion ? '' : 'ab-fade'" mode="out-in">
            <span :key="current.id" class="ab-line">
              <Icon class="ab-icon" :name="typeIcon(current.broadcast_type)" aria-hidden="true" />
              <span class="ab-kind">{{ typeLabel(current.broadcast_type) }}</span>
              <span class="ab-title" data-testid="ab-title">{{ current.title }}</span>
              <span v-if="oneLine(current.body)" class="ab-body">{{ oneLine(current.body) }}</span>
              <span v-if="shortAge(current.created_at)" class="ab-age">{{ shortAge(current.created_at) }}</span>
            </span>
          </Transition>
        </button>
        <div v-if="ordered.length > 1" class="ab-pager" data-testid="ab-pager">
          <button type="button" class="ab-icon-btn" :aria-label="t('headerStrip.previous', 'Previous broadcast')" @click.stop="step(-1)">
            <Icon name="mdi:chevron-left" />
          </button>
          <span class="ab-count" data-testid="ab-count">{{ Math.min(index, ordered.length - 1) + 1 }}/{{ ordered.length }}</span>
          <button type="button" class="ab-icon-btn" :aria-label="t('headerStrip.next', 'Next broadcast')" @click.stop="step(1)">
            <Icon name="mdi:chevron-right" />
          </button>
        </div>
        <button
          type="button"
          class="ab-icon-btn"
          data-testid="ab-mark-read"
          :aria-label="t('headerStrip.markRead', 'Mark as read')"
          :title="t('headerStrip.markRead', 'Mark as read')"
          @click.stop="markCurrentRead"
        >
          <Icon name="mdi:close" />
        </button>
      </template>
      <div v-else-if="readState === 'failed'" class="ab-line ab-muted ab-warn" data-testid="ab-read-failed">
        <Icon class="ab-icon" name="mdi:alert-circle" aria-hidden="true" />
        <span>{{ t('headerStrip.broadcastsUnreadable', 'Broadcasts could not be read just now.') }}</span>
        <button type="button" class="ab-link" data-testid="ab-retry" @click.stop="notif.fetchUnread()">
          {{ t('headerStrip.tryAgain', 'Try again') }}
        </button>
      </div>
      <div v-else-if="readState === 'loading'" class="ab-line ab-muted" data-testid="ab-loading">
        {{ t('headerStrip.readingBroadcasts', 'Reading broadcasts…') }}
      </div>
      <div v-else class="ab-line ab-muted" data-testid="ab-none">
        <Icon class="ab-icon" name="mdi:bullhorn-outline" aria-hidden="true" />
        <span>{{ t('headerStrip.noBroadcasts', 'No new broadcasts') }}</span>
      </div>
    </div>
    <button
      v-if="chip.show"
      type="button"
      class="ab-chip"
      :class="'ab-chip-' + chip.tone"
      data-testid="ab-alerts"
      :data-tone="chip.tone"
      :title="chip.title"
      @click.stop="openAlerts"
    >
      <span class="ab-chip-dot" aria-hidden="true" />{{ chip.label }}
    </button>
  </div>
</template>

<style scoped>
.ab-wrap {
  position: relative;
  height: 33px;
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 6px 0 10px;
  border-radius: 5px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.1);
  background: rgba(5, 5, 10, 0.92);
  box-shadow: inset 0 1px 4px rgba(0, 0, 0, 0.5);
  overflow: hidden;
  font-family: 'Fira Code', monospace;
}
.ab-main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}
.ab-open {
  flex: 1;
  min-width: 0;
  height: 27px;
  display: flex;
  align-items: center;
  padding: 0 6px;
  border: 1px solid transparent;
  border-radius: 4px;
  background: none;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.ab-open:hover,
.ab-open:focus-visible {
  border-color: rgba(var(--nc-primary-rgb), 0.25);
  outline: none;
}
.ab-line {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
  overflow: hidden;
  font-size: 11.5px;
  color: rgba(226, 232, 240, 0.9);
}
.ab-icon { width: 14px; height: 14px; flex: 0 0 auto; }
.ab-kind {
  flex: 0 0 auto;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  padding: 1px 5px;
  border-radius: 3px;
  border: 1px solid currentColor;
}
.ab-title { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; font-weight: 700; }
.ab-body { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; color: rgba(148, 163, 184, 0.9); }
.ab-age { flex: 0 0 auto; font-size: 10px; color: rgba(148, 163, 184, 0.7); }
.ab-type-info .ab-icon, .ab-type-info .ab-kind { color: rgb(var(--nc-primary-rgb)); }
.ab-type-maintenance .ab-icon, .ab-type-maintenance .ab-kind { color: #ff9100; }
.ab-type-warning .ab-icon, .ab-type-warning .ab-kind { color: #ffb300; }
.ab-type-critical .ab-icon, .ab-type-critical .ab-kind { color: #ff4d4d; }
.ab-muted { color: rgba(148, 163, 184, 0.75); padding: 0 6px; }
.ab-warn .ab-icon { color: #f5b41e; }
.ab-link {
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  color: rgb(var(--nc-primary-rgb));
  text-decoration: underline;
  cursor: pointer;
}
.ab-pager { display: flex; align-items: center; gap: 2px; flex: 0 0 auto; }
.ab-count { font-size: 10px; color: rgba(148, 163, 184, 0.8); min-width: 28px; text-align: center; font-variant-numeric: tabular-nums; }
.ab-icon-btn {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  border: 1px solid transparent;
  border-radius: 4px;
  background: none;
  color: rgba(148, 163, 184, 0.85);
  cursor: pointer;
}
.ab-icon-btn:hover, .ab-icon-btn:focus-visible { border-color: rgba(var(--nc-primary-rgb), 0.3); color: #e2e8f0; outline: none; }
.ab-chip {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 22px;
  padding: 0 9px;
  border-radius: 11px;
  border: 1px solid currentColor;
  background: rgba(0, 0, 0, 0.25);
  font-family: inherit;
  font-size: 10.5px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
}
.ab-chip-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.ab-chip-red { color: #ff5a5a; }
.ab-chip-amber { color: #f5b41e; }
.ab-chip-green { color: #10dc81; }
.ab-chip-dim { color: rgba(148, 163, 184, 0.8); }
.ab-chip:focus-visible { outline: 1px solid currentColor; outline-offset: 1px; }
@media (prefers-reduced-motion: no-preference) {
  .ab-chip-red .ab-chip-dot { animation: ab-pulse 1.6s ease-in-out infinite; }
}
@keyframes ab-pulse { 50% { opacity: 0.35; } }
.ab-fade-enter-active, .ab-fade-leave-active { transition: opacity 0.25s ease; }
.ab-fade-enter-from, .ab-fade-leave-to { opacity: 0; }
@media (max-width: 760px) {
  .ab-body, .ab-age { display: none; }
}
</style>
