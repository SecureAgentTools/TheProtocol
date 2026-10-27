<script setup lang="ts">
/**
 * §COCKPITDESK (2026-10-15) — WEBHOOKS: the endpoints this registry calls for you, and which of them stopped answering.
 *
 * A webhook that fails is something that did not happen elsewhere, which nothing else on the desk can see: the
 * registry records a delivery that got no 2xx and counts it on the hook (`failure_count`, CONSECUTIVE failures,
 * reset by the next success) and pauses the hook after enough of them in a row. So the pane leads with the ones
 * failing now, then the paused ones, then the quiet healthy rest, and links to the view where they are fixed.
 *
 * ⚠ An endpoint URL can carry a token in its query string or its userinfo. The pane prints host and path only.
 * Read-only, account-wide (webhooks belong to the developer, not to an agent), over `GET /webhooks`.
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { apiClient } from '@/services/api/client'
import PaneShell from './PaneShell.vue'
import RecordLink from './RecordLink.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import { agoShort } from '@/services/cockpit/when'
import { reportAttention, clearAttention } from '@/services/cockpit/attention'
import { useI18n } from '@/composables/useI18n'
import { PANES } from './paneRegistry'

const { t, tp } = useI18n()
const router = useRouter()
const def = PANES.webhooks
const SHOWN = 6

interface Hook { id: string; url: string; events: string[]; active: boolean; failures: number; lastAt: string | null }

const hooks = ref<Hook[]>([])
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)
let poll: ReturnType<typeof setInterval> | null = null

function toHook(w: any): Hook {
  return {
    id: String(w?.id ?? ''),
    url: String(w?.url ?? ''),
    events: Array.isArray(w?.events) ? w.events.map(String) : [],
    active: Boolean(w?.is_active ?? w?.active ?? false),
    failures: Math.max(0, Number(w?.failure_count) || 0),
    lastAt: (w?.last_triggered_at || w?.last_triggered || null) as string | null,
  }
}

async function load() {
  try {
    const r = await apiClient.get('/webhooks')
    hooks.value = (Array.isArray(r.data) ? r.data : []).map(toHook)
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 120) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null; clearAttention('webhooks') })

/** failing (active, failures in a row) first, then paused, then healthy by last call. */
function rank(h: Hook): number { return h.active && h.failures > 0 ? 0 : !h.active ? 1 : 2 }
const ordered = computed(() => [...hooks.value].sort((a, b) =>
  rank(a) - rank(b) || b.failures - a.failures ||
  (new Date(b.lastAt || 0).getTime() - new Date(a.lastAt || 0).getTime())))
const shown = computed(() => ordered.value.slice(0, SHOWN))
const failing = computed(() => hooks.value.filter(h => h.active && h.failures > 0).length)
const paused = computed(() => hooks.value.filter(h => !h.active).length)
const empty = computed(() => !loading.value && hooks.value.length === 0)
// the desk's "needs a look" line: endpoints failing now
watch(failing, (n) => reportAttention('webhooks', n, n === 1 ? t('cockpit.attn.webhooksOne', '1 webhook failing')
  : tp('cockpit.attn.webhooks', '{n} webhooks failing', { n })), { immediate: true })

/** Host and path only: never the query string, the fragment or a userinfo part. */
function place(url: string): string {
  try {
    const u = new URL(url)
    const path = u.pathname === '/' ? '' : u.pathname
    return `${u.host}${path}`
  } catch {
    return url.replace(/^[a-z]+:\/\//i, '').replace(/^[^@/]*@/, '').split(/[?#]/)[0]
  }
}

function state(h: Hook): { key: string; text: string } {
  if (!h.active) {
    return h.failures > 0
      ? { key: 'paused', text: tp('cockpit.wh.pausedAfter', 'paused after {n} failures', { n: h.failures }) }
      : { key: 'paused', text: t('cockpit.wh.paused', 'paused') }
  }
  if (h.failures > 0) return { key: 'failing', text: tp('cockpit.wh.failingN', '{n} failed in a row', { n: h.failures }) }
  return { key: 'ok', text: t('cockpit.wh.ok', 'answering') }
}

function last(h: Hook): string {
  return h.lastAt ? tp('cockpit.wh.lastCall', 'called {age} ago', { age: agoShort(h.lastAt) })
                  : t('cockpit.wh.never', 'never called')
}
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="t('cockpit.wh.empty', 'No webhook endpoints. Add one and this registry calls you when something happens.')"
             :empty-action-label="t('cockpit.wh.add', 'Add an endpoint')"
             @empty-action="router.push({ name: 'webhooks' })">
    <div class="wh" data-testid="ckd-webhooks">
      <p class="wh-head" data-testid="wh-head" :class="{ 'is-warn': failing > 0 }">
        {{ hooks.length === 1 ? t('cockpit.wh.headOne', '1 endpoint') : tp('cockpit.wh.headMany', '{n} endpoints', { n: hooks.length }) }}
        · {{ tp('cockpit.wh.headState', '{f} failing · {p} paused', { f: failing, p: paused }) }}
      </p>
      <ul class="wh-list">
        <li v-for="h in shown" :key="h.id" class="wh-row" data-testid="wh-row" :data-state="state(h).key">
          <span class="wh-dot" :class="`is-${state(h).key}`" aria-hidden="true" />
          <span class="wh-main">
            <span class="wh-url" :title="place(h.url)">{{ place(h.url) }}</span>
            <span class="wh-meta">
              <span class="wh-state" :class="`is-${state(h).key}`">{{ state(h).text }}</span>
              · {{ h.events.length === 1 ? t('cockpit.wh.eventOne', '1 event') : tp('cockpit.wh.events', '{n} events', { n: h.events.length }) }}
              · {{ last(h) }}
            </span>
          </span>
        </li>
      </ul>
      <p v-if="hooks.length > shown.length" class="wh-more">
        {{ tp('cockpit.wh.more', 'and {n} more', { n: hooks.length - shown.length }) }}
      </p>
      <p class="wh-foot" data-testid="wh-foot">
        {{ t('cockpit.wh.foot', 'A failure is a delivery that got no 2xx answer; the count resets on the next success.') }}
        <RecordLink kind="webhooks" class="ckd-doorsep" :label="t('cockpit.door.webhooks', 'Open webhooks')" />
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.wh { display: flex; flex-direction: column; gap: .35rem; }
.wh-head { margin: 0; font-size: .72rem; color: var(--nc-text-secondary, #c9d1d9); }
.wh-head.is-warn { color: var(--nc-warning, #d29922); }
.wh-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .3rem; }
.wh-row { display: flex; align-items: flex-start; gap: .45rem; min-width: 0; }
.wh-dot { flex: 0 0 auto; width: 7px; height: 7px; border-radius: 50%; margin-top: .3rem; background: var(--nc-success, #3fb950); }
.wh-dot.is-failing { background: var(--nc-danger, #f85149); }
.wh-dot.is-paused { background: var(--nc-text-muted, #6e7681); }
.wh-main { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.wh-url { font-size: .72rem; color: var(--nc-text-primary, #e6edf3); font-family: var(--nc-font-mono, ui-monospace, monospace);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wh-meta { font-size: .64rem; color: var(--nc-text-muted, #8b949e); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wh-state.is-failing { color: var(--nc-danger, #f85149); }
.wh-state.is-paused { color: var(--nc-warning, #d29922); }
.wh-state.is-ok { color: var(--nc-success, #3fb950); }
.wh-more { margin: 0; font-size: .64rem; color: var(--nc-text-muted, #8b949e); }
.wh-foot { margin: .2rem 0 0; font-size: .62rem; color: var(--nc-text-muted, #8b949e); }
.ckd-doorsep { margin-left: .4rem; }
</style>
