<template>
  <div :class="['lc-block', `lc-block--${tone}`]">
    <div class="lc-block-header">
      <span class="lc-block-icon" aria-hidden="true">
        <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M2 4l4 4-4 4M8 12h6" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </span>
      <span class="lc-block-eyebrow">Local command</span>
      <span class="lc-block-host">runs on YOUR host</span>
      <button
        type="button"
        class="lc-block-copy"
        :class="{ 'lc-block-copy--copied': copied }"
        :aria-label="copied ? 'Command copied' : 'Copy command'"
        @click="onCopy"
      >
        <svg v-if="!copied" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5">
          <rect x="4" y="4" width="9" height="10" rx="1.5"/>
          <path d="M3 11V3a1.5 1.5 0 011.5-1.5h7" stroke-linecap="round"/>
        </svg>
        <svg v-else viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 8.5l3 3 7-7" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <span>{{ copied ? 'copied' : 'copy' }}</span>
      </button>
    </div>
    <pre class="lc-block-cmd"><span class="lc-block-prompt">$</span> <code>{{ command }}</code></pre>
    <p v-if="caption" class="lc-block-caption">{{ caption }}</p>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

interface Props {
  /** The full tp-cli command to display + copy. */
  command: string
  /** One-line caption (what happens locally, side effects, etc.) */
  caption?: string
  /** Visual tone — info (default), warning (yellow), danger (red) */
  tone?: 'info' | 'warning' | 'danger'
}
const props = withDefaults(defineProps<Props>(), {
  caption: '',
  tone: 'info',
})

const copied = ref(false)
async function onCopy() {
  try {
    await navigator.clipboard.writeText(props.command)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch {
    // Fallback for non-secure-context environments
    const ta = document.createElement('textarea')
    ta.value = props.command
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy'); copied.value = true; setTimeout(() => { copied.value = false }, 1500) }
    finally { document.body.removeChild(ta) }
  }
}
</script>

<style scoped>
.lc-block {
  margin: 0.5rem 0;
  background: rgba(0, 12, 20, 0.55);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 4px;
  overflow: hidden;
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
  font-size: 0.78rem;
  transition: border-color 0.25s ease, background 0.25s ease;
}
.lc-block:hover { border-color: rgba(var(--nc-primary-rgb), 0.3); }

.lc-block--warning { border-color: rgba(255, 176, 0, 0.22); background: rgba(40, 24, 0, 0.4); }
.lc-block--warning:hover { border-color: rgba(255, 176, 0, 0.35); }
.lc-block--danger  { border-color: rgba(255, 82, 82, 0.25); background: rgba(40, 0, 0, 0.4); }
.lc-block--danger:hover { border-color: rgba(255, 82, 82, 0.4); }

.lc-block-header {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.45rem 0.7rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  background: rgba(0, 0, 0, 0.18);
}
.lc-block-icon { color: rgba(var(--nc-primary-rgb), 0.65); display: inline-flex; }
.lc-block--warning .lc-block-icon { color: rgba(255, 200, 80, 0.85); }
.lc-block--danger .lc-block-icon  { color: rgba(255, 120, 120, 0.85); }
.lc-block-eyebrow {
  font-size: 0.62rem; letter-spacing: 0.12em;
  text-transform: uppercase; color: rgba(var(--nc-primary-rgb), 0.7);
  font-weight: 600;
}
.lc-block-host {
  margin-left: 0.25rem;
  font-size: 0.6rem; letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.48);  /* §FESUITE: 4.97:1 (0.32 was 2.78:1) */
  font-weight: 500;
}
.lc-block-copy {
  margin-left: auto;
  display: inline-flex; align-items: center; gap: 0.25rem;
  background: transparent;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  color: rgba(var(--nc-primary-rgb), 0.85);
  padding: 0.18rem 0.5rem;
  font-size: 0.6rem; letter-spacing: 0.08em;
  text-transform: uppercase; font-weight: 600;
  border-radius: 2px; cursor: pointer;
  transition: background 0.18s, border-color 0.18s, color 0.18s;
  font-family: inherit;
}
.lc-block-copy:hover {
  background: rgba(var(--nc-primary-rgb), 0.08);
  border-color: rgba(var(--nc-primary-rgb), 0.4);
}
.lc-block-copy--copied {
  background: rgba(0, 230, 118, 0.12);
  border-color: rgba(0, 230, 118, 0.4);
  color: rgba(120, 255, 180, 0.95);
}

.lc-block-cmd {
  margin: 0;
  padding: 0.7rem 0.7rem 0.55rem;
  color: #c0e4ff;
  white-space: pre-wrap; word-break: break-all;
  font-size: 0.82rem;
  line-height: 1.5;
}
.lc-block-prompt {
  color: rgba(var(--nc-primary-rgb), 0.55);
  margin-right: 0.45rem;
  user-select: none;
}
.lc-block-cmd code { color: inherit; background: none; padding: 0; }

.lc-block-caption {
  margin: 0;
  padding: 0 0.7rem 0.55rem;
  font-family: 'Inter', system-ui, sans-serif;
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.55);
  line-height: 1.45;
}
</style>
