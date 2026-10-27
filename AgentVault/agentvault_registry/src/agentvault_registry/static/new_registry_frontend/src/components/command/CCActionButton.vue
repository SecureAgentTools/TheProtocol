<script setup lang="ts">
import { computed, ref } from 'vue'

const props = withDefaults(defineProps<{
  actionId: string
  label?: string
  destructive?: boolean
  busy?: boolean
  // §MCPTEST30 (V0561): false fires on the first press (a dry run changes nothing); true asks for a second press
  confirm?: boolean
}>(), { confirm: true })

const emit = defineEmits<{
  (e: 'confirm'): void
}>()

const stage = ref<'idle' | 'confirming'>('idle')
let resetHandle: ReturnType<typeof setTimeout> | null = null

const text = computed(() => {
  if (props.busy) return '⟳ running…'
  if (stage.value === 'confirming') {
    if (props.destructive) return 'Click again to confirm — destructive'
    return 'Click again to confirm'
  }
  return props.label || `Apply ${props.actionId} →`
})

function onClick() {
  if (props.busy) return
  if (!props.confirm) { emit('confirm'); return }
  if (stage.value === 'idle') {
    stage.value = 'confirming'
    if (resetHandle) clearTimeout(resetHandle)
    resetHandle = setTimeout(() => { stage.value = 'idle' }, 4500)
    return
  }
  if (resetHandle) { clearTimeout(resetHandle); resetHandle = null }
  stage.value = 'idle'
  emit('confirm')
}
</script>

<template>
  <button
    class="cc-act-btn"
    :class="{
      'cc-act-confirm': stage === 'confirming',
      'cc-act-destructive': destructive,
      'cc-act-busy': busy,
    }"
    :disabled="busy"
    @click="onClick"
  >{{ text }}</button>
</template>

<style scoped>
.cc-act-btn {
  background: rgba(0,176,255,0.15); border: 1px solid rgba(0,176,255,0.5);
  color: #6dd0ff; padding: 8px 14px; border-radius: 6px; cursor: pointer;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px; white-space: nowrap;
  transition: background 0.18s ease, border-color 0.18s ease, color 0.18s ease;
}
.cc-act-btn:hover { background: rgba(0,176,255,0.25); }
.cc-act-confirm {
  background: rgba(255,179,0,0.15); border-color: rgba(255,179,0,0.6); color: #ffd980;
  animation: ccActPulse 1.4s ease-in-out infinite;
}
.cc-act-destructive.cc-act-confirm {
  background: rgba(255,23,68,0.15); border-color: rgba(255,23,68,0.6); color: #ff8da3;
}
.cc-act-busy { opacity: 0.7; cursor: progress; }

@keyframes ccActPulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255,179,0,0); }
  50% { box-shadow: 0 0 12px 2px rgba(255,179,0,0.35); }
}
</style>
