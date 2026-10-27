<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useAlive } from '@/composables/useAlive'
import { useNotificationStore } from '@/stores/notifications'
import type { BroadcastItem, FeedItem } from '@/stores/notifications'
import { useRouter } from 'vue-router'
import { useViewport } from '@/composables/useViewport'

const store = useNotificationStore()
const router = useRouter()
const viewport = useViewport()
const open = ref(false)
const btnRef = ref<HTMLElement | null>(null)
const modalItem = ref<BroadcastItem | null>(null)

const dropPos = ref({ top: 0, right: 0 })

// §bc1 T1.6 — client-side type filter, persisted to localStorage.
const FILTER_KEY = 'theprotocol:bellTypeFilter'
type FilterValue = 'all' | 'info' | 'warning' | 'maintenance' | 'critical'
const FILTERS: { value: FilterValue; label: string }[] = [
  { value: 'all',         label: 'All'         },
  { value: 'critical',    label: 'Critical'    },
  { value: 'warning',     label: 'Warning'     },
  { value: 'maintenance', label: 'Maintenance' },
  { value: 'info',        label: 'Info'        },
]
const activeFilter = ref<FilterValue>(
  (typeof localStorage !== 'undefined'
    && (localStorage.getItem(FILTER_KEY) as FilterValue))
  || 'all'
)
function setFilter(v: FilterValue) {
  activeFilter.value = v
  try { localStorage.setItem(FILTER_KEY, v) } catch (_) { /* ignore */ }
}

// §bc3 T3.4 — search input (debounced 150ms, title-only, case-insensitive)
const searchInput = ref('')
const debouncedSearch = ref('')
let searchDebounceTimer: ReturnType<typeof setTimeout> | null = null
function onSearchInput(v: Event) {
  searchInput.value = (v.target as HTMLInputElement).value
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  searchDebounceTimer = setTimeout(() => {
    debouncedSearch.value = searchInput.value.trim().toLowerCase()
  }, 150)
}

const filteredItems = computed(() => {
  const f = activeFilter.value
  const q = debouncedSearch.value
  let pool = f === 'all' ? store.items : store.items.filter(i => i.broadcast_type === f)
  if (q) pool = pool.filter(i => i.title.toLowerCase().includes(q))
  return pool
})

// §bc3 T3.5 — bell glow tracks highest-priority unread (computed for badge)
const highestPriorityUnread = computed<BroadcastItem['broadcast_type'] | null>(() => {
  if (store.items.length === 0) return null
  const order: BroadcastItem['broadcast_type'][] = ['critical', 'warning', 'maintenance', 'info']
  for (const t of order) {
    if (store.items.some(i => i.broadcast_type === t)) return t
  }
  return null
})

function priorityGlowColor(p: BroadcastItem['broadcast_type'] | null): string {
  if (p === 'critical') return 'rgba(255, 68, 68, 0.45)'
  if (p === 'warning') return 'rgba(255, 179, 0, 0.35)'
  if (p === 'maintenance') return 'rgba(255, 145, 0, 0.30)'
  if (p === 'info') return 'rgba(var(--nc-primary-rgb), 0.32)'
  return 'transparent'
}

// §bc1 T1.5 — overflow toast pill dispatches a window event to open us.
// §ALERTS header strip (2026-10-06): the event names a broadcast (the critical banner's "Show full", a press on the
// header strip). It used to be ignored and the dropdown opened instead; a broadcast the bell holds opens in the modal.
function handleOpenBellEvent(e?: Event) {
  const id = (e as CustomEvent<{ broadcastId?: number }> | undefined)?.detail?.broadcastId
  const item = id != null ? store.items.find(i => i.id === id) : undefined
  if (item) { openModal(item); return }
  if (!open.value) toggle()
}

// §FESUITE (the leave sweep's gate, useAlive.sites.test.ts): a bell unmounted during its first read adds no listeners when it lands
const alive = useAlive()
onMounted(async () => {
  await store.fetchUnread()
  if (!alive()) return
  document.addEventListener('click', handleOutsideClick)
  window.addEventListener('resize', closeIfOpen)
  window.addEventListener('theprotocol:open-notification-bell', handleOpenBellEvent)
})

onUnmounted(() => {
  document.removeEventListener('click', handleOutsideClick)
  window.removeEventListener('resize', closeIfOpen)
  window.removeEventListener('theprotocol:open-notification-bell', handleOpenBellEvent)
})

function closeIfOpen() {
  if (open.value) open.value = false
}

function handleOutsideClick(e: MouseEvent) {
  const dropdown = document.getElementById('nb-teleported-dropdown')
  const modal = document.getElementById('nb-modal-overlay')
  if (modal) return // Don't close dropdown when modal is open
  if (
    btnRef.value && !btnRef.value.contains(e.target as Node) &&
    dropdown && !dropdown.contains(e.target as Node)
  ) {
    open.value = false
  }
}

async function toggle() {
  if (modalItem.value) return // Don't toggle dropdown when modal is open
  if (!open.value) {
    void store.fetchFeed()
    await nextTick()
    if (btnRef.value && !viewport.isSmallPhone.value) {
      const rect = btnRef.value.getBoundingClientRect()
      dropPos.value = {
        top: rect.bottom + 8,
        right: window.innerWidth - rect.right,
      }
    }
  }
  open.value = !open.value
}

function openModal(item: BroadcastItem) {
  modalItem.value = item
  open.value = false
}

function closeModal() {
  modalItem.value = null
}

async function dismiss(item: BroadcastItem) {
  await store.markRead(item.id)
  if (modalItem.value?.id === item.id) modalItem.value = null
}

/**
 * §FESUITE — a feed entry names where to go (`click`, e.g. "/ui/#/settings"): go there inside the app (the console is
 * served at / on the apex and at /ui/ on a registry, so only the hash route is portable), and the entry is read.
 */
function feedRoute(click: string | null): string | null {
  if (!click) return null
  const hash = click.indexOf('#')
  const route = hash >= 0 ? click.slice(hash + 1) : click
  return route.startsWith('/') && !route.startsWith('//') ? route : null
}
async function openFeed(e: FeedItem) {
  open.value = false
  await store.markFeedRead(e.id)
  const route = feedRoute(e.click)
  if (route) router.push(route).catch(() => {})
}

async function dismissAll() {
  await store.markAllRead()
  open.value = false
}

function typeColor(t: string): string {
  if (t === 'critical') return '#ff4444'
  if (t === 'maintenance') return '#ff9100'
  if (t === 'warning') return '#ffb300'
  return 'var(--nc-primary)'
}

function typeIcon(t: string): string {
  if (t === 'critical') return 'mdi:alert'
  if (t === 'maintenance') return 'mdi:wrench'
  if (t === 'warning') return 'mdi:alert'
  return 'mdi:bullhorn'
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

function renderBody(text: string): string {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong style="color:#c8dce8">$1</strong>')
    .replace(/^- /gm, '<span style="color:var(--nc-primary);margin-right:0.4em;">&#x2022;</span> ')
}

// §bc2 T2.7 — CTA URL sanitizer (mirrors CriticalBanner)
function isSafeCtaUrl(url: string | null | undefined): boolean {
  if (!url) return false
  try {
    if (url.startsWith('/')) return true
    const parsed = new URL(url, window.location.origin)
    return parsed.protocol === 'https:'
  } catch { return false }
}
</script>

<template>
  <div class="nb-wrap" ref="btnRef">
    <!-- Bell button — §bc3 T3.5 glow tracks highest-priority unread -->
    <button
      class="nb-btn"
      :class="{ 'has-critical': highestPriorityUnread === 'critical' }"
      :style="{ '--nb-glow': priorityGlowColor(highestPriorityUnread) }"
      @click.stop="toggle"
      :aria-label="`${store.unreadCount} unread notifications`"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
        <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
      </svg>
      <span v-if="store.unreadCount > 0" class="nb-badge">
        {{ store.unreadCount > 99 ? '99+' : store.unreadCount }}
      </span>
    </button>

    <!-- Dropdown — compact list, click item to open modal -->
    <Teleport to="body">
      <Transition name="nb-drop">
        <div
          v-if="open"
          id="nb-teleported-dropdown"
          class="nb-dropdown"
          :class="{ 'nb-dropdown--sheet': viewport.isSmallPhone.value }"
          :style="viewport.isSmallPhone.value ? {} : {
            position: 'fixed',
            top: dropPos.top + 'px',
            right: dropPos.right + 'px',
          }"
          @scroll.stop
          @wheel.stop
        >
          <div class="nb-header">
            <span class="nb-header-title">NOTIFICATIONS</span>
            <button v-if="store.unreadCount > 0" class="nb-clear-all" @click="dismissAll">
              clear all
            </button>
          </div>

          <!-- §bc1 T1.6 — type filter chip row -->
          <div class="nb-filter-row" role="tablist" aria-label="Filter notifications by type">
            <button
              v-for="f in FILTERS"
              :key="f.value"
              class="nb-chip"
              :class="{ 'is-active': activeFilter === f.value }"
              role="tab"
              :aria-selected="activeFilter === f.value"
              @click="setFilter(f.value)"
            >{{ f.label }}</button>
          </div>

          <!-- §bc3 T3.4 — search input only when items > 8 (low-noise UX) -->
          <div v-if="store.items.length > 8" class="nb-search-row">
            <input
              type="search"
              class="nb-search-input"
              :value="searchInput"
              @input="onSearchInput"
              placeholder="Search by title…"
              aria-label="Search notifications by title"
            />
          </div>

          <!-- §FESUITE — the per-developer in-app feed, above the broadcasts (it was shown on Pocket only) -->
          <div v-if="store.feed.length" class="nb-feed" data-testid="nb-feed">
            <div class="nb-section">YOUR ACCOUNT</div>
            <div v-for="e in store.feed" :key="'feed-' + e.id" class="nb-feed-item" :data-feed-id="e.id" :data-type="e.type_key">
              <button type="button" class="nb-feed-open" @click="openFeed(e)">
                <span class="nb-item-title">{{ e.title }}</span>
                <span class="nb-item-preview">{{ e.body }}</span>
                <span class="nb-item-age">{{ relativeTime(e.created_at || '') }}</span>
              </button>
              <button type="button" class="nb-feed-read" :aria-label="`Mark read: ${e.title}`" @click="store.markFeedRead(e.id)">
                <Icon name="mdi:check" />
              </button>
            </div>
          </div>

          <!-- §FESUITE (2026-10-05): "All clear." only over reads that answered; a failed one says so, with Try again -->
          <div v-if="(store.unreadFailed || store.feedFailed) && store.items.length === 0 && store.feed.length === 0" class="nb-empty" data-testid="nb-read-failed">
            <ReadFailedNotice dense :retry="store.fetchUnread" />
          </div>
          <div v-else-if="store.items.length === 0 && store.feed.length === 0" class="nb-empty">
            <span>All clear.</span>
          </div>
          <div v-else-if="store.items.length && filteredItems.length === 0" class="nb-empty">
            <span>No notifications match this filter.</span>
          </div>

          <div v-else-if="filteredItems.length" class="nb-list">
            <div
              v-for="item in filteredItems"
              :key="item.id"
              class="nb-item"
              role="button"
              tabindex="0"
              :style="{ borderLeftColor: typeColor(item.broadcast_type) }"
              @click="openModal(item)"
              @keydown.enter.prevent="openModal(item)"
              @keydown.space.prevent="openModal(item)"
            >
              <div class="nb-item-top">
                <span class="nb-item-icon"><Icon :name="typeIcon(item.broadcast_type)" /></span>
                <span class="nb-item-type" :style="{ color: typeColor(item.broadcast_type) }">
                  {{ item.broadcast_type.toUpperCase() }}
                </span>
                <!-- §bc2 T2.8 — lock icon for ack-required items -->
                <span v-if="item.requires_ack" class="nb-item-lock" title="Requires acknowledgement"><Icon name="mdi:lock" /></span>
                <span class="nb-item-age">{{ relativeTime(item.created_at) }}</span>
              </div>
              <div class="nb-item-title">{{ item.title }}</div>
              <div class="nb-item-preview">{{ item.body.slice(0, 120) }}{{ item.body.length > 120 ? '...' : '' }}</div>
            </div>
          </div>
        </div>
      </Transition>

      <!-- Full-screen Modal — for reading the complete notification -->
      <Transition name="nb-modal">
        <div
          v-if="modalItem"
          id="nb-modal-overlay"
          class="nb-modal-overlay"
          @click.self="closeModal"
        >
          <div class="nb-modal" role="dialog" aria-modal="true" :aria-label="modalItem.title" @click.stop>
            <div class="nb-modal-header">
              <div class="nb-modal-type-row">
                <span class="nb-modal-icon"><Icon :name="typeIcon(modalItem.broadcast_type)" /></span>
                <span class="nb-modal-type" :style="{ color: typeColor(modalItem.broadcast_type) }">
                  {{ modalItem.broadcast_type.toUpperCase() }}
                </span>
                <span class="nb-modal-age">{{ relativeTime(modalItem.created_at) }}</span>
              </div>
              <button class="nb-modal-close" @click="closeModal" aria-label="Close">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2" stroke-linecap="round">
                  <path d="M18 6L6 18M6 6l12 12"/>
                </svg>
              </button>
            </div>
            <h2 class="nb-modal-title">{{ modalItem.title }}</h2>
            <div class="nb-modal-body" v-html="renderBody(modalItem.body)"></div>
            <div class="nb-modal-footer">
              <!-- §bc2 T2.7 — CTA link rendered in modal footer -->
              <a
                v-if="isSafeCtaUrl(modalItem.cta_url)"
                :href="modalItem.cta_url!"
                class="nb-modal-cta"
                target="_blank"
                rel="noopener noreferrer"
              >{{ modalItem.cta_label || 'Learn more' }} →</a>
              <button class="nb-modal-dismiss" @click="dismiss(modalItem)">
                {{ modalItem.requires_ack ? 'ACKNOWLEDGE' : 'Dismiss notification' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
/* §FESUITE — the in-app feed section */
.nb-section { padding: 8px 14px 4px; font-size: 10px; letter-spacing: 0.14em; color: var(--nc-text-muted, #8f9399); font-weight: 700; }
.nb-feed { border-bottom: 1px solid rgba(255, 255, 255, 0.06); padding-bottom: 4px; }
.nb-feed-item { display: flex; align-items: stretch; gap: 4px; padding: 0 8px 0 0; }
.nb-feed-open { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; text-align: left; background: none; border: none;
  color: inherit; font: inherit; cursor: pointer; padding: 8px 14px; border-left: 3px solid var(--nc-primary); }
.nb-feed-open:hover, .nb-feed-open:focus-visible { background: rgba(255, 255, 255, 0.04); }
.nb-feed-read { align-self: center; width: 28px; height: 28px; display: grid; place-items: center; background: none; cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 6px; color: var(--nc-text-secondary, #9aa0a6); }
.nb-feed-read:hover, .nb-feed-read:focus-visible { color: var(--nc-primary); border-color: var(--nc-primary); }
.nb-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.nb-btn {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: none;
  background: transparent;
  color: #556677;
  cursor: pointer;
  border-radius: 4px;
  transition: color 0.15s, background 0.15s;
}
.nb-btn:hover {
  color: var(--nc-primary);
  background: rgba(var(--nc-primary-rgb),0.06);
}
.nb-btn {
  /* §bc3 T3.5 — priority-tracked glow halo */
  box-shadow: 0 0 0 0 var(--nb-glow, transparent);
  transition: box-shadow 0.2s ease;
}
.nb-btn.has-critical {
  box-shadow: 0 0 8px 2px var(--nb-glow);
  animation: nb-pulse-critical 2.4s ease-in-out infinite;
}
@keyframes nb-pulse-critical {
  0%, 100% { box-shadow: 0 0 6px 1px var(--nb-glow); }
  50%      { box-shadow: 0 0 12px 3px var(--nb-glow); }
}
@media (prefers-reduced-motion: reduce) {
  .nb-btn.has-critical { animation: none; }
}

.nb-badge {
  position: absolute;
  top: 3px;
  right: 3px;
  min-width: 14px;
  height: 14px;
  padding: 0 3px;
  border-radius: 7px;
  background: #d32f2f; /* §FESUITE: white text on it reads 4.98:1 (was #ff4444, 3.41:1) */
  color: #fff;
  font-size: 0.55rem;
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

/* ── Dropdown (compact list) ── */
:global(.nb-dropdown) {
  width: 360px;
  max-height: min(400px, calc(100vh - 80px));
  overflow-y: auto;
  background: #070d18;
  border: 1px solid rgba(var(--nc-primary-rgb),0.15);
  border-radius: 6px;
  box-shadow: 0 12px 40px rgba(0,0,0,0.75);
  z-index: 99999;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
}
/* §bc1 T1.10 — mobile bottom-sheet variant */
:global(.nb-dropdown.nb-dropdown--sheet) {
  position: fixed !important;
  top: auto !important;
  right: 0 !important;
  bottom: 0;
  left: 0;
  width: 100%;
  max-height: 78vh;
  border-radius: 12px 12px 0 0;
  border-bottom: none;
  box-shadow: 0 -10px 40px rgba(0,0,0,0.8);
}

/* §bc1 T1.6 — type filter chip row */
:global(.nb-filter-row) {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  padding: 0.55rem 0.9rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.06);
  background: rgba(var(--nc-primary-rgb),0.02);
  position: sticky;
  top: 41px;
  z-index: 1;
}
:global(.nb-chip) {
  background: rgba(var(--nc-primary-rgb), 0.04);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.12);
  color: rgba(var(--nc-primary-rgb), 0.8); /* §FESUITE: 4.5:1+ (0.55 read 3.7:1) */
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  letter-spacing: 0.06em;
  padding: 3px 8px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
:global(.nb-chip:hover) {
  background: rgba(var(--nc-primary-rgb), 0.1);
  color: var(--nc-primary);
}
:global(.nb-chip.is-active) {
  background: rgba(var(--nc-primary-rgb), 0.18);
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  color: var(--nc-primary);
}

/* §bc3 T3.4 — search input row */
:global(.nb-search-row) {
  padding: 0.45rem 0.9rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.06);
  background: rgba(var(--nc-primary-rgb), 0.015);
}
:global(.nb-search-input) {
  width: 100%;
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 3px;
  padding: 5px 9px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  color: #c8d8e8;
  outline: none;
  transition: border-color 0.15s;
}
:global(.nb-search-input:focus) {
  border-color: rgba(var(--nc-primary-rgb), 0.7);
  background: rgba(var(--nc-primary-rgb), 0.04);
}
:global(.nb-search-input::placeholder) {
  color: rgba(var(--nc-primary-rgb), 0.4);
}
:global(.nb-dropdown::-webkit-scrollbar) { width: 4px; }
:global(.nb-dropdown::-webkit-scrollbar-track) { background: transparent; }
:global(.nb-dropdown::-webkit-scrollbar-thumb) { background: rgba(var(--nc-primary-rgb),0.15); border-radius: 2px; }

:global(.nb-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.08);
  position: sticky;
  top: 0;
  background: #070d18;
  z-index: 1;
}
:global(.nb-header-title) {
  font-size: 0.6rem;
  letter-spacing: 0.18em;
  font-weight: 600;
  color: rgba(var(--nc-primary-rgb),0.85); /* §FESUITE: 4.5:1+ (0.5 read 3.3:1) */
}
:global(.nb-clear-all) {
  font-size: 0.7rem;
  color: rgba(var(--nc-primary-rgb),0.85);
  background: none;
  border: none;
  cursor: pointer;
  font-family: 'IBM Plex Mono', monospace;
  padding: 0;
}
:global(.nb-clear-all:hover) { color: var(--nc-primary); }

:global(.nb-empty) {
  padding: 2rem;
  text-align: center;
  font-size: 0.8rem;
  color: #8a9bb0; /* §FESUITE: was #2a3a4a, 1.6:1 */
}

:global(.nb-list) {
  display: flex;
  flex-direction: column;
}

:global(.nb-item) {
  padding: 0.75rem 1rem;
  border-left: 2px solid transparent;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.05);
  cursor: pointer;
  transition: background 0.15s;
}
:global(.nb-item:hover) { background: rgba(var(--nc-primary-rgb),0.05); }

:global(.nb-item-top) {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.25rem;
}
:global(.nb-item-icon) { font-size: 0.8rem; }
:global(.nb-item-type) {
  font-size: 0.55rem;
  letter-spacing: 0.14em;
  font-weight: 700;
}
:global(.nb-item-age) {
  margin-left: auto;
  font-size: 0.6rem;
  color: #7d8ea3; /* §FESUITE: was #2a3a4a, 1.6:1 */
}
:global(.nb-item-title) {
  font-size: 0.8rem;
  font-weight: 600;
  color: #c8d8e8;
  margin-bottom: 0.2rem;
  line-height: 1.3;
}
:global(.nb-item-preview) {
  font-size: 0.7rem;
  color: #8a9bb0; /* §FESUITE: was #445566, 2.6:1 */
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* ── Modal overlay ── */
:global(.nb-modal-overlay) {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  z-index: 100000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
}

:global(.nb-modal) {
  background: #0a1020;
  border: 1px solid rgba(var(--nc-primary-rgb),0.2);
  border-radius: 10px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.8), 0 0 40px rgba(var(--nc-primary-rgb),0.05);
  width: 100%;
  max-width: 600px;
  max-height: calc(100vh - 4rem);
  display: flex;
  flex-direction: column;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
}

:global(.nb-modal-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem 1.5rem 0.75rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.08);
}
:global(.nb-modal-type-row) {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
:global(.nb-modal-icon) { font-size: 1rem; }
:global(.nb-modal-type) {
  font-size: 0.6rem;
  letter-spacing: 0.16em;
  font-weight: 700;
}
:global(.nb-modal-age) {
  font-size: 0.65rem;
  color: #2a3a4a;
  margin-left: 0.5rem;
}
:global(.nb-modal-close) {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: #445566;
  cursor: pointer;
  border-radius: 6px;
  transition: color 0.15s, background 0.15s;
}
:global(.nb-modal-close:hover) {
  color: #ff4444;
  background: rgba(255,68,68,0.08);
}

:global(.nb-modal-title) {
  font-size: 1.1rem;
  font-weight: 700;
  color: #e0ecf4;
  padding: 1rem 1.5rem 0.5rem;
  line-height: 1.3;
  margin: 0;
}

:global(.nb-modal-body) {
  padding: 0.5rem 1.5rem 1.5rem;
  font-size: 0.85rem;
  color: #8899aa;
  line-height: 1.7;
  overflow-y: auto;
  flex: 1;
  white-space: pre-wrap;
  word-break: break-word;
}
:global(.nb-modal-body::-webkit-scrollbar) { width: 4px; }
:global(.nb-modal-body::-webkit-scrollbar-track) { background: transparent; }
:global(.nb-modal-body::-webkit-scrollbar-thumb) { background: rgba(var(--nc-primary-rgb),0.15); border-radius: 2px; }

:global(.nb-modal-footer) {
  padding: 0.75rem 1.5rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb),0.08);
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  align-items: center;
}
:global(.nb-modal-cta) {
  font-size: 0.72rem;
  font-family: 'IBM Plex Mono', monospace;
  color: var(--nc-primary);
  text-decoration: underline;
  text-underline-offset: 3px;
  margin-right: auto;
}
:global(.nb-modal-cta:hover) { color: #fff; }
:global(.nb-item-lock) { font-size: 0.65rem; margin-left: 0.2rem; opacity: 0.85; }
:global(.nb-modal-dismiss) {
  font-size: 0.72rem;
  font-family: 'IBM Plex Mono', monospace;
  color: rgba(var(--nc-primary-rgb),0.5);
  background: rgba(var(--nc-primary-rgb),0.06);
  border: 1px solid rgba(var(--nc-primary-rgb),0.12);
  border-radius: 4px;
  padding: 0.4rem 1rem;
  cursor: pointer;
  transition: all 0.15s;
}
:global(.nb-modal-dismiss:hover) {
  color: var(--nc-primary);
  background: rgba(var(--nc-primary-rgb),0.1);
  border-color: rgba(var(--nc-primary-rgb),0.25);
}

/* ── Transitions ── */
.nb-drop-enter-active,
.nb-drop-leave-active { transition: opacity 0.12s, transform 0.12s; }
.nb-drop-enter-from,
.nb-drop-leave-to { opacity: 0; transform: translateY(-6px); }

.nb-modal-enter-active { transition: opacity 0.2s ease; }
.nb-modal-leave-active { transition: opacity 0.15s ease; }
.nb-modal-enter-from,
.nb-modal-leave-to { opacity: 0; }
</style>
