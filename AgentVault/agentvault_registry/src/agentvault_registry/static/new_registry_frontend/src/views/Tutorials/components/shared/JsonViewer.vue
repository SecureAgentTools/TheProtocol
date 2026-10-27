<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  data: any
  maxHeight?: string
  initiallyCollapsed?: boolean
}>()

const isCollapsed = ref(props.initiallyCollapsed ?? false)

const formattedJson = computed(() => {
  if (props.data === null || props.data === undefined) return 'null'
  if (typeof props.data === 'string') {
    try {
      return JSON.stringify(JSON.parse(props.data), null, 2)
    } catch {
      return props.data
    }
  }
  return JSON.stringify(props.data, null, 2)
})

const syntaxHighlighted = computed(() => {
  // Escape HTML entities first to prevent XSS injection via JSON values
  const escaped = formattedJson.value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  return escaped.replace(
    /("(?:\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*")\s*:/g,
    '<span class="json-key">$1</span>:'
  ).replace(
    /:\s*("(?:\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*")/g,
    ': <span class="json-string">$1</span>'
  ).replace(
    /:\s*(\d+\.?\d*)/g,
    ': <span class="json-number">$1</span>'
  ).replace(
    /:\s*(true|false)/g,
    ': <span class="json-boolean">$1</span>'
  ).replace(
    /:\s*(null)/g,
    ': <span class="json-null">$1</span>'
  )
})

const lineCount = computed(() => formattedJson.value.split('\n').length)

function toggleCollapse() {
  isCollapsed.value = !isCollapsed.value
}

function copyToClipboard() {
  navigator.clipboard.writeText(formattedJson.value).catch(() => {})
}
</script>

<template>
  <div class="json-viewer rounded-lg bg-gray-950 border border-gray-800 overflow-hidden">
    <!-- Header bar -->
    <div
      class="flex items-center justify-between px-3 py-1.5 bg-gray-900/70 border-b border-gray-800 text-xs"
    >
      <button
        @click="toggleCollapse"
        class="flex items-center gap-1.5 text-gray-400 hover:text-gray-200 transition-colors"
      >
        <svg
          :class="['w-3 h-3 transition-transform', isCollapsed ? '' : 'rotate-90']"
          fill="currentColor" viewBox="0 0 20 20"
        >
          <path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" />
        </svg>
        <span>JSON</span>
        <span class="text-gray-600">{{ lineCount }} lines</span>
      </button>
      <button
        @click="copyToClipboard"
        class="text-gray-500 hover:text-gray-300 transition-colors"
        title="Copy JSON"
      >
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
      </button>
    </div>
    <!-- Content -->
    <div
      v-if="!isCollapsed"
      class="overflow-auto p-3 text-xs font-mono leading-relaxed"
      :style="{ maxHeight: maxHeight || '400px' }"
    >
      <pre class="whitespace-pre-wrap break-all m-0" v-html="syntaxHighlighted"></pre>
    </div>
  </div>
</template>

<style scoped>
.json-viewer :deep(.json-key) {
  color: #67d6ed;
}
.json-viewer :deep(.json-string) {
  color: #a5d6a7;
}
.json-viewer :deep(.json-number) {
  color: #ffcc80;
}
.json-viewer :deep(.json-boolean) {
  color: #ce93d8;
}
.json-viewer :deep(.json-null) {
  color: #ef9a9a;
}
</style>
