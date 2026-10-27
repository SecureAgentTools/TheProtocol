<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { computed } from 'vue'

const props = defineProps<{
  title: string
  subtitle?: string
  explanation: string
  stepNumber: number
  isComplete: boolean
  isActive: boolean
  notes?: string
}>()

/**
 * Lightweight markdown-like rendering:
 * - **bold** → <strong>
 * - `code` → <code>
 * - newlines → <br>
 * - Lines starting with "- " → bullet points
 */
const renderedExplanation = computed(() => {
  return renderMarkdownLite(props.explanation)
})

const renderedNotes = computed(() => {
  if (!props.notes) return ''
  return renderMarkdownLite(props.notes)
})

function renderMarkdownLite(text: string): string {
  const lines = text.split('\n')
  let html = ''
  let inList = false

  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.startsWith('- ')) {
      if (!inList) { html += '<ul class="list-disc list-inside space-y-1 my-2">'; inList = true }
      html += `<li>${inlineFormat(trimmed.slice(2))}</li>`
    } else {
      if (inList) { html += '</ul>'; inList = false }
      if (trimmed === '') {
        html += '<br>'
      } else {
        html += `<p class="mb-2">${inlineFormat(trimmed)}</p>`
      }
    }
  }
  if (inList) html += '</ul>'
  return html
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function inlineFormat(text: string): string {
  // Escape HTML first, then apply markdown formatting on safe content
  const safe = escapeHtml(text)
  return safe
    .replace(/\*\*(.+?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>')
    .replace(/`(.+?)`/g, '<code class="px-1.5 py-0.5 bg-gray-700 rounded-sm text-sm font-mono text-violet-300">$1</code>')
}
</script>

<template>
  <div class="rounded-lg border border-gray-700/50 bg-gray-800/30 overflow-hidden">
    <!-- Header -->
    <div class="flex items-center gap-3 px-4 py-3 border-b border-gray-700/50">
      <div
        :class="[
          'flex items-center justify-center w-8 h-8 rounded-full text-sm font-bold transition-colors',
          isComplete
            ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
            : isActive
              ? 'bg-violet-500/20 text-violet-400 border border-violet-500/30'
              : 'bg-gray-700/50 text-gray-500 border border-gray-600/30'
        ]"
      >
        <span v-if="isComplete">✓</span>
        <span v-else>{{ stepNumber }}</span>
      </div>
      <div class="flex-1 min-w-0">
        <h3 class="text-white font-semibold text-sm">{{ title }}</h3>
        <p v-if="subtitle" class="text-gray-400 text-xs mt-0.5">{{ subtitle }}</p>
      </div>
    </div>

    <!-- Explanation Body -->
    <div class="px-4 py-3">
      <div
        class="text-gray-300 text-sm leading-relaxed prose-invert"
        v-html="renderedExplanation"
      />
    </div>

    <!-- Notes (optional) -->
    <div
      v-if="notes"
      class="px-4 py-3 border-t border-gray-700/30 bg-amber-500/5"
    >
      <div class="flex items-start gap-2">
        <span class="text-amber-400 text-sm mt-0.5"><Icon name="mdi:lightning-bolt" /></span>
        <div
          class="text-amber-200/80 text-xs leading-relaxed"
          v-html="renderedNotes"
        />
      </div>
    </div>
  </div>
</template>
