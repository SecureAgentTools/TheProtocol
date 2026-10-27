<script setup lang="ts">
import { computed } from 'vue'
import type { TargetSummary } from '@/services/api/types/diagnostics'
import { useI18n } from '@/composables/useI18n'

const { t, tp } = useI18n()

const props = defineProps<{
  target: TargetSummary
  inflight: boolean
}>()

defineEmits<{
  (e: 'open'): void
}>()

const okCount = computed(() => props.target.check_results.filter(r => r.status === 'ok').length)
const warnCount = computed(() => props.target.check_results.filter(r => r.status === 'warn').length)
const failCount = computed(() => props.target.check_results.filter(r => r.status === 'fail').length)
const totalCount = computed(() => props.target.check_results.length)

const statusToken = computed(() => {
  if (props.target.status === 'down')     return 'var(--nc-danger)'
  if (props.target.status === 'degraded') return 'var(--nc-warning)'
  if (props.target.status === 'healthy')  return 'var(--nc-success)'
  return 'var(--nc-border-strong)'
})

const lastSnapshotLabel = computed(() => {
  if (!props.target.last_snapshot_at) return t('commandCenterView.tile.never', 'never run')
  const sec = Math.max(0, Math.round((Date.now() - new Date(props.target.last_snapshot_at).getTime()) / 1000))
  if (sec < 60) return tp('commandCenterView.tile.secondsAgo', '{n}s ago', { n: sec })
  if (sec < 3600) return tp('commandCenterView.tile.minutesAgo', '{n}m ago', { n: Math.round(sec / 60) })
  return tp('commandCenterView.tile.hoursAgo', '{n}h ago', { n: Math.round(sec / 3600) })
})

// §MCPTEST30 (V0562): this registry itself is a target (is_self); it is named as such, not as "FRAME x · frame"
const isSelf = computed(() => props.target.is_self === true)
const roleLabel = computed(() => (isSelf.value
  ? t('commandCenterView.tile.thisRegistry', 'this registry')
  : props.target.role))
</script>

<template>
  <div
    class="cc-tile"
    :data-status="target.status"
    :data-frame="target.frame"
    :data-self="isSelf ? 'true' : null"
    role="button"
    tabindex="0"
    :aria-label="`${target.display_name}, ${roleLabel}`"
    @click="$emit('open')"
    @keydown.enter.prevent="$emit('open')"
    @keydown.space.prevent="$emit('open')"
  >
    <span class="cc-tile-accent" :style="{ background: statusToken }"></span>

    <div class="cc-tile-head">
      <div class="cc-tile-name-block">
        <div class="cc-tile-name">{{ target.display_name }}</div>
        <div class="cc-tile-sub">
          <template v-if="!isSelf">
            <span class="cc-tile-frame">{{ t('commandCenterView.tile.frame', 'Frame') }} {{ target.frame }}</span>
            <span class="cc-tile-dot">·</span>
          </template>
          <span class="cc-tile-role">{{ roleLabel }}</span>
        </div>
      </div>
      <div v-if="totalCount" class="cc-tile-score" :style="{ color: statusToken }">
        {{ okCount }}<span class="cc-tile-slash">/</span>{{ totalCount }}
      </div>
      <div v-else class="cc-tile-score cc-tile-score-empty">—</div>
    </div>

    <div class="cc-tile-foot">
      <span v-if="failCount" class="cc-tile-pill" data-tone="fail">{{ tp('commandCenterView.tile.fail', '{n} fail', { n: failCount }) }}</span>
      <span v-if="warnCount" class="cc-tile-pill" data-tone="warn">{{ tp('commandCenterView.tile.warn', '{n} warn', { n: warnCount }) }}</span>
      <span v-if="!failCount && !warnCount && totalCount" class="cc-tile-pill" data-tone="ok">{{ t('commandCenterView.tile.allClear', 'all clear') }}</span>
      <span v-if="!totalCount" class="cc-tile-pill" data-tone="muted">{{ t('commandCenterView.tile.noData', 'not run yet') }}</span>
      <span class="cc-tile-time">{{ lastSnapshotLabel }}</span>
    </div>

    <div v-if="inflight" class="cc-tile-spinner">⟳</div>
  </div>
</template>

<style scoped>
.cc-tile:focus-visible { outline: 2px solid var(--nc-primary); outline-offset: 2px; }
.cc-tile {
  position: relative;
  background: var(--nc-surface);
  border: 1px solid var(--nc-border);
  border-radius: 8px;
  padding: 10px 12px 10px 16px;
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease;
  overflow: hidden;
}
.cc-tile:hover {
  border-color: var(--nc-border-strong);
  background: var(--nc-elevated);
}
.cc-tile[data-status="down"] {
  border-color: var(--nc-danger-subtle);
}
.cc-tile[data-status="degraded"] { border-color: var(--nc-warning-subtle); }
.cc-tile[data-status="healthy"]  { border-color: var(--nc-success-subtle); }

.cc-tile-accent {
  position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
}

.cc-tile-head { display: flex; gap: 10px; align-items: center; justify-content: space-between; }
.cc-tile-name-block { min-width: 0; }
.cc-tile-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--nc-text-primary);
  line-height: 1.2;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.cc-tile-sub {
  display: flex; gap: 5px;
  font-size: 9px; color: var(--nc-text-muted);
  margin-top: 3px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  text-transform: uppercase; letter-spacing: 0.08em;
}
.cc-tile-frame { color: var(--nc-text-muted); }
.cc-tile[data-frame="B"] .cc-tile-frame { color: var(--nc-chart-5); }
.cc-tile-dot { opacity: 0.5; }
.cc-tile-role { color: var(--nc-text-muted); }

.cc-tile-score {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 14px; font-weight: 600; line-height: 1;
  white-space: nowrap;
}
.cc-tile-slash { opacity: 0.4; padding: 0 1px; font-weight: 400; }
.cc-tile-score-empty { color: var(--nc-text-muted); }

.cc-tile-foot {
  display: flex; gap: 6px; align-items: center;
  margin-top: 8px; flex-wrap: wrap;
}
.cc-tile-pill {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 9px; font-weight: 600;
  padding: 1px 7px; border-radius: 999px;
  letter-spacing: 0.08em; text-transform: uppercase;
  border: 1px solid;
}
.cc-tile-pill[data-tone="ok"]    { background: var(--nc-success-subtle); color: var(--nc-success); border-color: var(--nc-success-subtle); }
.cc-tile-pill[data-tone="warn"]  { background: var(--nc-warning-subtle); color: var(--nc-warning); border-color: var(--nc-warning-subtle); }
.cc-tile-pill[data-tone="fail"]  { background: var(--nc-danger-subtle);  color: var(--nc-danger);  border-color: var(--nc-danger-subtle); }
.cc-tile-pill[data-tone="muted"] { background: transparent; color: var(--nc-text-muted); border-color: var(--nc-border); }
.cc-tile-time {
  margin-left: auto;
  font-size: 9px; color: var(--nc-text-muted);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  letter-spacing: 0.04em;
}

.cc-tile-spinner {
  position: absolute; top: 8px; right: 8px;
  font-size: 12px; color: var(--nc-primary);
  animation: ccSpin 1s linear infinite;
}
@keyframes ccSpin { to { transform: rotate(360deg); } }
</style>
