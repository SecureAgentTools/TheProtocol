<template>
  <Teleport to="body">
    <div class="cicd-modal-backdrop cicd-module" @click.self="$emit('close')">
      <div class="cicd-modal cicd-modal-wide" style="max-height:90vh;display:flex;flex-direction:column;">

        <!-- Header -->
        <div class="cicd-modal-header" style="flex-shrink:0;">
          <div style="display:flex;flex-direction:column;gap:3px;">
            <span class="cicd-modal-title">◫ DEPLOYMENT LOGS</span>
            <span style="font-size:11px;color:var(--cicd-text-muted);font-family:var(--cicd-font-mono);">
              {{ deployment.environment?.toUpperCase() }} · {{ formatDate(deployment.started_at) }}
            </span>
          </div>
          <div style="display:flex;gap:6px;align-items:center;">
            <!-- Status badge -->
            <span class="cicd-badge" :class="`cicd-badge-${deployment.status}`">
              <span class="cicd-badge-dot"></span>
              {{ deployment.status }}
            </span>
            <button
              class="cicd-btn cicd-btn-ghost cicd-btn-sm"
              :disabled="isRefreshing"
              @click="refresh"
              title="Refresh"
            >↻</button>
            <button
              class="cicd-btn cicd-btn-ghost cicd-btn-sm"
              :class="autoScroll ? 'cicd-btn-primary' : ''"
              @click="autoScroll = !autoScroll"
              title="Auto-scroll"
            >↓</button>
            <button
              class="cicd-btn cicd-btn-ghost cicd-btn-sm"
              @click="downloadLogs"
              title="Download"
            >⬇</button>
            <a
              v-if="cicdHref"
              class="cicd-btn cicd-btn-ghost cicd-btn-sm"
              :href="safeExternalUrl(cicdHref)"
              data-record="open" data-record-kind="agentCicd"
              title="Open this agent's CI/CD"
              style="text-decoration:none;"
            >⧉</a>
            <button class="cicd-btn cicd-btn-ghost cicd-btn-icon" @click="$emit('close')">✕</button>
          </div>
        </div>

        <!-- Meta bar -->
        <div style="
          flex-shrink:0;
          padding:8px 22px;
          background:var(--cicd-surface-2);
          border-bottom:1px solid var(--cicd-border);
          display:flex;gap:20px;font-size:11px;color:var(--cicd-text-muted);font-family:var(--cicd-font-mono);
        ">
          <span v-if="deployment.pipeline_name">PIPELINE: <span style="color:var(--cicd-text-dim);">{{ deployment.pipeline_name }}</span></span>
          <span v-if="deployment.version">VERSION: <span style="color:var(--cicd-text-dim);">{{ deployment.version }}</span></span>
          <span v-if="deployment.duration_seconds != null">DURATION: <span style="color:var(--cicd-text-dim);">{{ deployment.duration_seconds }}s</span></span>
          <span>TYPE: <span style="color:var(--cicd-text-dim);">{{ deployment.deployment_type || 'standard' }}</span></span>
        </div>

        <!-- Terminal body -->
        <div
          ref="terminal"
          class="cicd-terminal"
          style="flex:1;border-radius:0;border-left:none;border-right:none;max-height:none;"
        >
          <div v-if="cicdStore.loadingStates.logs" style="padding:32px;text-align:center;color:var(--cicd-text-muted);">
            <div style="font-size:22px;animation:cicd-pulse 1s infinite;">◌</div>
            <div style="margin-top:8px;font-size:11px;">Loading logs…</div>
          </div>

          <!-- §FESUITE (V0577): the logs could not be read. It said "No logs available" (or kept showing the previous
               deployment's logs under this one's header, the store being one for every deployment) -->
          <ReadFailedNotice v-else-if="cicdStore.readFailed.logs" :retry="refresh" data-testid="cicd-logs-failed" />
          <div v-else-if="!parsedLogs.length" class="cicd-empty" style="padding:32px;">
            <div class="cicd-empty-icon">◫</div>
            <div class="cicd-empty-title">No logs available</div>
            <div class="cicd-empty-sub">Logs appear here once the deployment runs.</div>
          </div>

          <template v-else>
            <div
              v-for="(line, i) in parsedLogs"
              :key="i"
              style="display:flex;gap:10px;"
            >
              <span class="log-ts">{{ line.ts }}</span>
              <span :class="line.cls">[{{ line.level }}]</span>
              <span style="flex:1;white-space:pre-wrap;word-break:break-word;">{{ line.msg }}</span>
            </div>
          </template>

          <div ref="scrollAnchor"></div>
        </div>

        <!-- Footer -->
        <div class="cicd-modal-footer" style="flex-shrink:0;justify-content:space-between;">
          <span style="font-family:var(--cicd-font-mono);font-size:10px;color:var(--cicd-text-muted);">
            {{ parsedLogs.length }} lines
            <span v-if="deployment.status === 'running'" style="color:var(--cicd-green);"> ● LIVE</span>
          </span>
          <button class="cicd-btn cicd-btn-ghost" @click="$emit('close')">Close</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useCICDStore } from '@/stores/cicd'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useRouter } from 'vue-router'
import './tp-cicd.css'

const props = defineProps<{ deployment: any; agentDid: string }>()

/**
 * §COCKPITUP U4 (2026-09-01) — a door out of the logs.
 *
 * ⚠ Built from the route NAME, never a hand-rolled path: `agent-cicd` is `agent/:did/ci-cd`
 * while its sibling `agent-details` is `agent/:agentId`, so a path assembled by hand here
 * silently produces an empty segment. `resolve()` on an unknown name throws, which is why
 * the empty string (no door) is the failure mode rather than an anchor to nowhere.
 */
const router = useRouter()
const cicdHref = computed(() => {
  if (!props.agentDid) return ''
  try {
    const r = router.resolve({ name: 'agent-cicd', params: { did: props.agentDid } })
    return r.name ? r.href : ''
  } catch { return '' }
})
const emit = defineEmits<{ close: [] }>()

const cicdStore = useCICDStore()
const terminal = ref<HTMLElement>()
const scrollAnchor = ref<HTMLElement>()
const autoScroll = ref(true)
const isRefreshing = ref(false)
let interval: ReturnType<typeof setInterval> | null = null

const parsedLogs = computed(() => {
  const raw = cicdStore.deploymentLogs
  if (!raw) return []

  // raw can be a string (raw log text) or array of DeploymentLog objects
  if (typeof raw === 'string') {
    return raw.split('\n').filter(Boolean).map((line, i) => {
      const level = line.includes('[ERROR]') ? 'ERROR'
        : line.includes('[WARN]') ? 'WARN'
        : line.includes('[DEBUG]') ? 'DEBUG'
        : 'INFO'
      const cls = level === 'ERROR' ? 'log-error'
        : level === 'WARN' ? 'log-warn'
        : level === 'DEBUG' ? 'log-ts'
        : 'log-info'
      return { ts: String(i + 1).padStart(4, '0'), level, cls, msg: line }
    })
  }
  // array of DeploymentLog objects
  return (raw as any[]).map((entry, i) => {
    const level = (entry.level || 'info').toUpperCase()
    const cls = level === 'ERROR' ? 'log-error'
      : level === 'WARNING' || level === 'WARN' ? 'log-warn'
      : level === 'SUCCESS' ? 'log-success'
      : level === 'DEBUG' ? 'log-ts'
      : 'log-info'
    const ts = entry.timestamp
      ? new Date(entry.timestamp).toLocaleTimeString('en-GB', { hour12: false })
      : String(i + 1).padStart(4, '0')
    return { ts, level, cls, msg: entry.message || '' }
  })
})

function formatDate(d: string) {
  return new Date(d).toLocaleString(appLocale())
}

async function refresh() {
  isRefreshing.value = true
  await cicdStore.fetchDeploymentLogs(props.agentDid, props.deployment.id)
  isRefreshing.value = false
  if (autoScroll.value) await nextTick().then(scrollToBottom)
}

function scrollToBottom() {
  scrollAnchor.value?.scrollIntoView({ behavior: 'smooth' })
}

function downloadLogs() {
  const text = parsedLogs.value.map(l => `${l.ts} [${l.level}] ${l.msg}`).join('\n')
  const a = Object.assign(document.createElement('a'), {
    href: URL.createObjectURL(new Blob([text], { type: 'text/plain' })),
    download: `deployment-${props.deployment.id}.log`,
  })
  document.body.appendChild(a); a.click(); document.body.removeChild(a)
}

watch(() => parsedLogs.value.length, async () => {
  if (autoScroll.value) { await nextTick(); scrollToBottom() }
})

onMounted(() => {
  refresh()
  if (props.deployment.status === 'running') {
    interval = setInterval(refresh, 3000)
  }
})
onUnmounted(() => { if (interval) clearInterval(interval) })
</script>
