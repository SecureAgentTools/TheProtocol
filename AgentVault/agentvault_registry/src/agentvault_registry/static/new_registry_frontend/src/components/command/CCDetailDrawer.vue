<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { useCommandCenterStore } from '@/stores/commandCenter'
import { useI18n } from '@/composables/useI18n'
import type { ActionDescriptor, TargetSummary } from '@/services/api/types/diagnostics'
import CCActionButton from './CCActionButton.vue'
import CCCheckRow from './CCCheckRow.vue'
import CCConfigSection from './CCConfigSection.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'

const props = defineProps<{
  target: TargetSummary | null
  inflight: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'rerun', operator_id: string): void
}>()

const store = useCommandCenterStore()
const { t } = useI18n()
const { actions, actionsFailed, configByTarget, lastActionResult, error } = storeToRefs(store)

type Tab = 'diagnostics' | 'config' | 'actions' | 'logs'
const activeTab = ref<Tab>('diagnostics')
const configLoading = ref(false)

watch(() => props.target?.operator_id, (operatorId) => {
  activeTab.value = 'diagnostics'
  if (operatorId) {
    store.loadActions().catch(() => {})
  }
})

// §MCPTEST30 (V0562): this registry itself (role "frame") has no containers to read a configuration from
const isSelf = computed(() => props.target?.is_self === true)

watch([activeTab, () => props.target?.operator_id], async ([tab, operatorId]) => {
  if (tab === 'config' && operatorId && !isSelf.value) {
    configLoading.value = true
    try { await store.loadConfig(operatorId) }
    finally { configLoading.value = false }
  }
})

const visible = computed(() => props.target !== null)

const sortedResults = computed(() => {
  if (!props.target) return []
  const order = { fail: 0, warn: 1, unknown: 2, ok: 3 } as const
  return [...props.target.check_results].sort(
    (a, b) => (order[a.status] ?? 4) - (order[b.status] ?? 4),
  )
})

const failingActionIds = computed(() => {
  if (!props.target) return new Set<string>()
  const ids = new Set<string>()
  for (const r of props.target.check_results) {
    if (r.remediation && r.remediation.action_id !== 'manual-investigate') {
      ids.add(r.remediation.action_id)
    }
  }
  return ids
})

const targetActions = computed(() => actions.value)

const targetConfig = computed(() => {
  if (!props.target) return null
  return configByTarget.value[props.target.operator_id] ?? null
})

function close() { emit('close') }
function rerun() { if (props.target) emit('rerun', props.target.operator_id) }

async function reloadConfig() {
  if (!props.target || isSelf.value) return
  configLoading.value = true
  try { await store.loadConfig(props.target.operator_id, true) }
  finally { configLoading.value = false }
}

// §MCPTEST30 (V0561): DRY RUN FIRST. Both actions answer a dry run (nginx -t without the reload; the lifecycle route a
// restart would take) and the page never asked for one: it sent dry_run false on the second click of a two-click
// confirm. Now the first press asks what the action would do, and Apply appears only after a dry run that came back ok.
const previews = ref<Record<string, { status: string; summary: string }>>({})
watch(() => props.target?.operator_id, () => { previews.value = {} })
function previewKey(actionId: string): string { return `${actionId}@${props.target?.operator_id ?? ''}` }
function previewOf(actionId: string) { return previews.value[previewKey(actionId)] ?? null }

async function applyAction(action: ActionDescriptor) {
  if (!props.target) return
  const key = previewKey(action.action_id)
  const preview = previews.value[key]
  const dryRun = !(preview && preview.status === 'ok')
  const result = await store.runAction(action.action_id, props.target.operator_id, dryRun)
  if (!result) return
  if (dryRun) {
    previews.value = { ...previews.value, [key]: { status: result.status, summary: result.summary } }
    // a remediation pressed on a check row lands where its dry run and its Apply are
    activeTab.value = 'actions'
  } else {
    const next = { ...previews.value }
    delete next[key]
    previews.value = next
  }
}

function isActionRunning(actionId: string): boolean {
  if (!props.target) return false
  return store.isActionRunning(actionId, props.target.operator_id)
}

function actionRecency(actionId: string): string | null {
  const last = lastActionResult.value
  if (!last || !props.target) return null
  if (last.action_id !== actionId || last.target !== props.target.operator_id) return null
  return `${last.status.toUpperCase()} — ${last.summary}`
}
</script>

<template>
  <Teleport to="body">
    <transition name="cc-drawer-fade">
      <div v-if="visible" class="cc-drawer-backdrop" @click.self="close">
        <transition name="cc-drawer-slide" appear>
          <aside v-if="visible" class="cc-drawer">
            <header class="cc-drawer-head">
              <div class="cc-drawer-titles">
                <div class="cc-drawer-title">{{ target?.display_name }}</div>
                <div class="cc-drawer-sub">
                  <template v-if="!isSelf">
                    <span>Frame {{ target?.frame }}</span>
                    <span class="cc-drawer-dot">·</span>
                  </template>
                  <span>{{ isSelf ? t('commandCenterView.tile.thisRegistry', 'this registry') : target?.role }}</span>
                  <span class="cc-drawer-dot">·</span>
                  <span :data-status="target?.status">{{ target?.status }}</span>
                </div>
              </div>
              <div class="cc-drawer-actions">
                <button class="cc-drawer-btn" :disabled="inflight" @click="rerun">
                  <span v-if="inflight">⟳ running</span>
                  <span v-else>↻ re-run</span>
                </button>
                <button class="cc-drawer-x" @click="close">×</button>
              </div>
            </header>

            <nav class="cc-drawer-tabs">
              <button :class="{ active: activeTab === 'diagnostics' }" @click="activeTab = 'diagnostics'">Diagnostics</button>
              <button :class="{ active: activeTab === 'config' }" @click="activeTab = 'config'">Config</button>
              <button :class="{ active: activeTab === 'actions' }" @click="activeTab = 'actions'">Actions</button>
              <button :class="{ active: activeTab === 'logs' }" @click="activeTab = 'logs'">Logs</button>
            </nav>

            <section class="cc-drawer-body">
              <!-- §MCPTEST30 (V0562): a failed run or action is said HERE; the page's banner sits under this backdrop -->
              <div v-if="error" class="cc-drawer-error" role="alert" data-testid="cc-drawer-error">{{ error }}</div>
              <!-- DIAGNOSTICS -->
              <div v-if="activeTab === 'diagnostics'" class="cc-drawer-tab">
                <div v-if="!sortedResults.length" class="cc-drawer-empty">
                  No results yet — click ↻ re-run to populate.
                </div>
                <div v-else class="cc-drawer-rows">
                  <CCCheckRow
                    v-for="r in sortedResults"
                    :key="r.check_id"
                    :result="r"
                    @remediate="(actionId) => applyAction({ action_id: actionId, description: '', destructive: false, post_check: r.check_id, requires_confirmation: true })"
                  />
                </div>
              </div>

              <!-- CONFIG -->
              <div v-else-if="activeTab === 'config'" class="cc-drawer-tab">
                <div class="cc-drawer-toolbar">
                  <span class="cc-drawer-toolbar-text">read-only · secrets masked server-side</span>
                  <button class="cc-drawer-btn" :disabled="configLoading" @click="reloadConfig">
                    <span v-if="configLoading">⟳ loading…</span>
                    <span v-else>↻ refresh</span>
                  </button>
                </div>
                <div v-if="isSelf" class="cc-drawer-empty" data-testid="cc-self-config">{{ t('commandCenterView.drawer.selfConfig', "This registry's own configuration is not shown here: its checks read what they need directly (its Redis, its SVID, its trust bundle, its TEG, and on a frame its store).") }}</div>
                <div v-else-if="configLoading && !targetConfig" class="cc-drawer-empty">Loading…</div>
                <div v-else-if="!targetConfig" class="cc-drawer-empty">Config not loaded.</div>
                <template v-else>
                  <CCConfigSection v-if="targetConfig.docker" title="containers" :payload="targetConfig.docker" />
                  <CCConfigSection v-if="targetConfig.env" title="env (masked)" :payload="targetConfig.env" />
                  <CCConfigSection v-if="targetConfig.partner_tegs" title="PARTNER_TEGS" :payload="targetConfig.partner_tegs" />
                  <CCConfigSection v-if="targetConfig.spire" title="SPIRE federation + bundle" :payload="targetConfig.spire" />
                  <CCConfigSection v-if="targetConfig.nginx" title="nginx-federation conf" :payload="targetConfig.nginx" />
                </template>
              </div>

              <!-- ACTIONS -->
              <div v-else-if="activeTab === 'actions'" class="cc-drawer-tab">
                <ReadFailedNotice v-if="actionsFailed && !targetActions.length" dense :retry="() => store.loadActions()" data-testid="cc-actions-unread" />
                <div v-else-if="!targetActions.length" class="cc-drawer-empty">No remediation actions registered.</div>
                <div v-else class="cc-drawer-rows">
                  <div
                    v-for="action in targetActions"
                    :key="action.action_id"
                    class="cc-drawer-action"
                    :data-recommended="failingActionIds.has(action.action_id) ? 'true' : 'false'"
                  >
                    <div class="cc-drawer-action-text">
                      <div class="cc-drawer-action-id">
                        {{ action.action_id }}
                        <span v-if="failingActionIds.has(action.action_id)" class="cc-drawer-action-recommend">recommended</span>
                        <span v-if="action.destructive" class="cc-drawer-action-dest">destructive</span>
                      </div>
                      <div class="cc-drawer-action-desc">{{ action.description }}</div>
                      <div class="cc-drawer-action-meta">post-check <code>{{ action.post_check }}</code></div>
                      <div v-if="actionRecency(action.action_id)" class="cc-drawer-action-recency">last: {{ actionRecency(action.action_id) }}</div>
                      <div v-if="previewOf(action.action_id)" class="cc-drawer-action-preview" data-testid="cc-action-preview"
                           :data-status="previewOf(action.action_id)!.status">
                        {{ t('commandCenterView.actions.dryRunSaid', 'Dry run') }}: {{ previewOf(action.action_id)!.summary }}
                      </div>
                    </div>
                    <CCActionButton
                      :action-id="action.action_id"
                      :destructive="action.destructive"
                      :busy="isActionRunning(action.action_id)"
                      :label="previewOf(action.action_id)?.status === 'ok'
                        ? t('commandCenterView.actions.apply', 'Apply') + ` ${action.action_id} →`
                        : t('commandCenterView.actions.dryRun', 'Dry run') + ` ${action.action_id}`"
                      :confirm="previewOf(action.action_id)?.status === 'ok'"
                      @confirm="applyAction(action)"
                    />
                  </div>
                </div>
              </div>

              <!-- LOGS -->
              <div v-else-if="activeTab === 'logs'" class="cc-drawer-tab cc-drawer-coming-soon">
                <div class="cc-coming-glyph"><Icon name="mdi:scroll-text" /></div>
                <div class="cc-coming-title">{{ t('commandCenterView.logs.title', 'Logs') }}</div>
                <div class="cc-coming-desc">{{ t('commandCenterView.logs.where', "An operator's recent logs are on Operator Management, read through the operator lifecycle.") }}</div>
                <router-link class="cc-coming-link" :to="{ name: 'operator-management' }">{{ t('commandCenterView.logs.open', 'Open Operator Management') }} →</router-link>
              </div>
            </section>
          </aside>
        </transition>
      </div>
    </transition>
  </Teleport>
</template>

<style scoped>
.cc-drawer-backdrop {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0,0,0,0.55);
  backdrop-filter: blur(4px);
}
.cc-drawer {
  position: fixed; right: 0;
  /* Offset below the 48px DashboardHeader so close button is never occluded */
  top: 48px; bottom: 0;
  width: 540px; max-width: 92vw;
  background: linear-gradient(180deg, rgba(14,20,28,0.98), rgba(8,12,18,0.98));
  border-left: 1px solid rgba(0,200,83,0.22);
  box-shadow: -16px 0 40px rgba(0,0,0,0.5);
  display: flex; flex-direction: column;
  color: #f4f6f8;
}
.cc-drawer-head { display: flex; gap: 12px; align-items: flex-start; padding: 18px 20px 12px; border-bottom: 1px solid rgba(255,255,255,0.06); }
.cc-drawer-titles { flex: 1; }
.cc-drawer-title { font-size: 18px; font-weight: 600; }
.cc-drawer-sub { display: flex; gap: 6px; font-size: 11px; color: rgba(255,255,255,0.55); margin-top: 4px; font-family: 'IBM Plex Mono', monospace; text-transform: uppercase; letter-spacing: 0.06em; }
.cc-drawer-sub [data-status="down"] { color: #ff4d6a; }
.cc-drawer-sub [data-status="degraded"] { color: #f5c842; }
.cc-drawer-sub [data-status="healthy"] { color: #00e5a0; }
.cc-drawer-sub [data-status="unknown"] { color: rgba(255,255,255,0.55); }
.cc-drawer-dot { opacity: 0.4; }

.cc-drawer-actions { display: flex; gap: 8px; align-items: center; }
.cc-drawer-btn {
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.12);
  color: rgba(255,255,255,0.85); padding: 6px 12px; border-radius: 6px;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px; cursor: pointer;
}
.cc-drawer-btn:hover { background: rgba(255,255,255,0.08); }
.cc-drawer-btn:disabled { opacity: 0.6; cursor: progress; }
.cc-drawer-x {
  background: none; border: none; color: rgba(255,255,255,0.6);
  font-size: 22px; line-height: 1; padding: 4px 10px; cursor: pointer; border-radius: 6px;
}
.cc-drawer-x:hover { color: #f4f6f8; background: rgba(255,255,255,0.06); }

.cc-drawer-tabs { display: flex; gap: 4px; padding: 0 20px; border-bottom: 1px solid rgba(255,255,255,0.06); }
.cc-drawer-tabs button {
  background: none; border: none; padding: 12px 14px; cursor: pointer;
  color: rgba(255,255,255,0.55); font-size: 12px; letter-spacing: 0.06em;
  border-bottom: 2px solid transparent;
}
.cc-drawer-tabs button:hover { color: #f4f6f8; }
.cc-drawer-tabs button.active { color: #f4f6f8; border-bottom-color: #00e5a0; }

.cc-drawer-body { flex: 1; overflow-y: auto; padding: 16px 20px 24px; }
.cc-drawer-tab { display: flex; flex-direction: column; gap: 10px; }
.cc-drawer-rows { display: flex; flex-direction: column; gap: 8px; }
.cc-drawer-empty { padding: 32px 8px; text-align: center; color: rgba(255,255,255,0.5); font-size: 13px; font-style: italic; }

.cc-drawer-toolbar { display: flex; gap: 12px; justify-content: space-between; align-items: center; }
.cc-drawer-toolbar-text { font-size: 11px; color: rgba(255,255,255,0.5); font-family: 'IBM Plex Mono', monospace; }

.cc-drawer-coming-soon { align-items: center; padding-top: 32px; }
.cc-coming-glyph { font-size: 48px; opacity: 0.6; }
.cc-coming-title { font-size: 14px; color: #f4f6f8; margin-top: 12px; }
.cc-coming-desc { font-size: 12px; color: rgba(255,255,255,0.55); text-align: center; margin-top: 6px; max-width: 320px; }
.cc-coming-link {
  margin-top: 16px; display: inline-block;
  padding: 8px 18px; border-radius: 8px; text-decoration: none;
  background: rgba(0,176,255,0.15); border: 1px solid rgba(0,176,255,0.5); color: #6dd0ff;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px;
}
.cc-coming-link:hover { background: rgba(0,176,255,0.25); }

.cc-drawer-action {
  display: flex; gap: 14px; align-items: center;
  padding: 12px 14px; border-radius: 8px;
  background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05);
}
.cc-drawer-action[data-recommended="true"] { background: rgba(0,176,255,0.06); border-color: rgba(0,176,255,0.35); }
.cc-drawer-action-text { flex: 1; }
.cc-drawer-action-id { font-family: 'IBM Plex Mono', monospace; font-size: 13px; color: #6dd0ff; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.cc-drawer-action-recommend { font-size: 9px; padding: 1px 6px; border-radius: 999px; background: rgba(0,176,255,0.18); color: #6dd0ff; letter-spacing: 0.08em; text-transform: uppercase; border: 1px solid rgba(0,176,255,0.4); }
.cc-drawer-action-dest { font-size: 9px; padding: 1px 6px; border-radius: 999px; background: rgba(255,23,68,0.15); color: #ff8da3; letter-spacing: 0.08em; text-transform: uppercase; border: 1px solid rgba(255,23,68,0.4); }
.cc-drawer-action-desc { font-size: 12px; color: rgba(255,255,255,0.7); margin-top: 4px; }
.cc-drawer-action-meta { font-size: 10px; color: rgba(255,255,255,0.45); margin-top: 4px; font-family: 'IBM Plex Mono', monospace; }
.cc-drawer-action-meta code { background: rgba(255,255,255,0.06); padding: 1px 4px; border-radius: 3px; }
.cc-drawer-action-recency { font-size: 10px; color: rgba(255,255,255,0.6); margin-top: 6px; font-family: 'IBM Plex Mono', monospace; }
.cc-drawer-error {
  background: var(--nc-danger-subtle); color: var(--nc-danger); border: 1px solid var(--nc-danger-subtle);
  border-radius: 6px; padding: 8px 12px; margin-bottom: 10px; font-size: 11.5px; line-height: 1.5;
}
.cc-drawer-action-preview { font-size: 10.5px; margin-top: 6px; font-family: 'IBM Plex Mono', monospace; color: var(--nc-text-secondary); }
.cc-drawer-action-preview[data-status="ok"] { color: var(--nc-success); }
.cc-drawer-action-preview[data-status="fail"] { color: var(--nc-danger); }

/* transitions */
.cc-drawer-fade-enter-active, .cc-drawer-fade-leave-active { transition: opacity 0.2s ease; }
.cc-drawer-fade-enter-from, .cc-drawer-fade-leave-to { opacity: 0; }
.cc-drawer-slide-enter-active, .cc-drawer-slide-leave-active { transition: transform 0.28s cubic-bezier(0.2, 0.8, 0.4, 1); }
.cc-drawer-slide-enter-from, .cc-drawer-slide-leave-to { transform: translateX(100%); }
</style>
