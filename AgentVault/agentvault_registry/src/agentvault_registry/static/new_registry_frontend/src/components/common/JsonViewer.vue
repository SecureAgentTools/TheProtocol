<template>
  <div class="jv-wrap" :class="{ 'jv-wrap--bordered': bordered }">
    <!-- Toolbar -->
    <div v-if="!hideToolbar" class="jv-toolbar">
      <span class="jv-label">{{ label || 'JSON' }}</span>
      <span v-if="bytesLabel" class="jv-bytes">{{ bytesLabel }}</span>
      <span class="jv-spacer"></span>
      <button
        type="button"
        class="jv-btn"
        :title="copied ? 'Copied' : 'Copy JSON'"
        :aria-label="copied ? 'Copied' : 'Copy JSON'"
        @click="onCopy"
      >
        <span v-if="copied">✓ Copied</span>
        <span v-else>⎘ Copy</span>
      </button>
      <button
        v-if="canCollapse"
        type="button"
        class="jv-btn"
        :title="collapsed ? 'Expand' : 'Collapse'"
        :aria-label="collapsed ? 'Expand JSON' : 'Collapse JSON'"
        @click="collapsed = !collapsed"
      >{{ collapsed ? '▸ Expand' : '▾ Collapse' }}</button>
    </div>

    <!-- JSON pre block. Click anywhere on the pre to copy in compact mode. -->
    <pre
      v-if="!collapsed"
      class="jv-pre"
      :class="{ 'jv-pre--mono-tight': dense }"
      tabindex="0"
    >{{ formatted }}</pre>

    <!-- Collapsed preview -->
    <div v-else class="jv-collapsed" @click="collapsed = false">
      <span class="jv-collapsed-hint">▸ {{ compactPreview }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * <JsonViewer> — shared JSON display component (Build #1, 2026-05-07).
 *
 * Used by Webhook Deliveries (Build #1), A2A Payment Token Manager (Build #2),
 * EventStore Explorer (Build #6) per strategy doc §5 cross-build shared
 * components.
 *
 * Features:
 *  - Syntax-friendly pretty-print with 2-space indent
 *  - Copy button with 1.5s feedback
 *  - Optional collapse/expand for nested data
 *  - Byte size indicator
 *  - Theme-aware via --nc-* tokens
 *  - Fixed max-height with scroll for large payloads
 *  - Keyboard-focusable <pre> for screen readers
 */
import { ref, computed } from 'vue'

const props = withDefaults(defineProps<{
  /** The data to display. Can be any JSON-serializable value or a pre-stringified JSON string. */
  data: any
  /** Optional label shown in the toolbar. */
  label?: string
  /** Hide the toolbar entirely (caller controls). */
  hideToolbar?: boolean
  /** Render with a border around the entire block. */
  bordered?: boolean
  /** Tighter line-height for dense lists. */
  dense?: boolean
  /** Default-collapsed view; user can expand. Auto-disabled if data fits on one screen. */
  defaultCollapsed?: boolean
  /** Maximum height in CSS units (e.g., '320px'). Default: '320px'. */
  maxHeight?: string
}>(), {
  hideToolbar: false,
  bordered: true,
  dense: false,
  defaultCollapsed: false,
  maxHeight: '320px',
})

const collapsed = ref<boolean>(props.defaultCollapsed)
const copied = ref(false)

/**
 * Pretty-print the data. If data is a string that parses as JSON, format it.
 * Otherwise stringify the value directly.
 */
const formatted = computed<string>(() => {
  const v = props.data
  if (v === null || v === undefined) return ''
  if (typeof v === 'string') {
    try {
      return JSON.stringify(JSON.parse(v), null, 2)
    } catch {
      return v
    }
  }
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
})

/**
 * Compact one-line preview for collapsed state. Truncates at ~80 chars.
 */
const compactPreview = computed<string>(() => {
  const v = props.data
  if (v === null || v === undefined) return '(empty)'
  let s: string
  try {
    s = typeof v === 'string' ? v : JSON.stringify(v)
  } catch {
    s = String(v)
  }
  if (s.length > 80) s = s.slice(0, 77) + '…'
  return s
})

/**
 * Byte-size label (KB/B). For showing payload weight in the toolbar.
 */
const bytesLabel = computed<string>(() => {
  if (!formatted.value) return ''
  const bytes = new Blob([formatted.value]).size
  if (bytes < 1024) return `${bytes}B`
  return `${(bytes / 1024).toFixed(1)}KB`
})

const canCollapse = computed(() => formatted.value.length > 200)

async function onCopy() {
  try {
    await navigator.clipboard.writeText(formatted.value)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    // execCommand fallback for very old browsers
    const ta = document.createElement('textarea')
    ta.value = formatted.value
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy'); copied.value = true; setTimeout(() => (copied.value = false), 1500) } catch { /* expected */ }
    document.body.removeChild(ta)
  }
}
</script>

<style scoped>
.jv-wrap {
  display: flex;
  flex-direction: column;
  background: rgba(0, 0, 0, 0.18);
  border-radius: 6px;
  overflow: hidden;
}
.jv-wrap--bordered {
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
}

.jv-toolbar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.6rem;
  background: rgba(var(--nc-primary-rgb), 0.04);
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.1);
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.65rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.jv-label {
  color: rgba(var(--nc-primary-rgb), 0.85);
  font-weight: 600;
}
.jv-bytes {
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.6rem;
}
.jv-spacer { flex: 1; }
.jv-btn {
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  background: transparent;
  color: rgba(var(--nc-primary-rgb), 0.85);
  border-radius: 4px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  letter-spacing: 0.06em;
  padding: 3px 7px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.jv-btn:hover {
  background: rgba(var(--nc-primary-rgb), 0.1);
  border-color: rgba(var(--nc-primary-rgb), 0.4);
  color: rgba(var(--nc-primary-rgb), 1);
}
.jv-btn:focus-visible {
  outline: 2px solid rgba(var(--nc-primary-rgb), 0.6);
  outline-offset: 2px;
}

.jv-pre {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.75rem;
  line-height: 1.55;
  color: #d4dbe8;
  padding: 0.65rem 0.8rem;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: v-bind(maxHeight);
  overflow: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(var(--nc-primary-rgb), 0.3) transparent;
}
.jv-pre--mono-tight {
  line-height: 1.35;
  font-size: 0.7rem;
}

.jv-pre::-webkit-scrollbar { width: 6px; height: 6px; }
.jv-pre::-webkit-scrollbar-thumb {
  background: rgba(var(--nc-primary-rgb), 0.25);
  border-radius: 3px;
}
.jv-pre::-webkit-scrollbar-thumb:hover {
  background: rgba(var(--nc-primary-rgb), 0.45);
}

.jv-collapsed {
  padding: 0.5rem 0.8rem;
  cursor: pointer;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: rgba(var(--nc-primary-rgb), 0.7);
  transition: background 0.12s;
}
.jv-collapsed:hover { background: rgba(var(--nc-primary-rgb), 0.06); }
.jv-collapsed-hint {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
