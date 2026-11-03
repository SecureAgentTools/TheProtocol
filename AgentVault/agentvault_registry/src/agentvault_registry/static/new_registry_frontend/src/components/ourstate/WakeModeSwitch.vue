<template>
  <!-- V0654 (aq): what of the room wakes a member: listen (every line meant for it), on call (only when named, a direct
       message, a decision on its own request, the owner's @all) or off. One radio group; the chosen one is pressed. -->
  <div class="wms" role="radiogroup" :aria-label="tp('ourstate.wake.aria', 'What wakes {who} in this room', { who })"
       :data-testid="`wake-switch-${testid}`" :data-mode="mode">
    <button v-for="m in MODES" :key="m.mode" type="button" role="radio" class="wms-opt" :class="{ on: mode === m.mode }"
            :aria-checked="mode === m.mode ? 'true' : 'false'" :disabled="busy" :title="t(m.helpKey, m.help)"
            :data-testid="`wake-${m.mode}-${testid}`" @click="mode !== m.mode && emit('set', m.mode)">
      {{ t(m.key, m.label) }}</button>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from '@/composables/useI18n'
import type { WakeMode } from '@/services/api/chat'

defineProps<{ mode: WakeMode; who: string; testid: string; busy?: boolean }>()
const emit = defineEmits<{ (e: 'set', mode: WakeMode): void }>()
const { t, tp } = useI18n()
const MODES: { mode: WakeMode; key: string; label: string; helpKey: string; help: string }[] = [
  { mode: 'listen', key: 'ourstate.wake.listen', label: 'Listen', helpKey: 'ourstate.wake.listenHelp',
    help: 'Wakes for every line meant for it, as before' },
  { mode: 'on-call', key: 'ourstate.wake.onCall', label: 'On call', helpKey: 'ourstate.wake.onCallHelp',
    help: 'Wakes only when named, for a direct message, a decision on its own request, or your @all' },
  { mode: 'off', key: 'ourstate.wake.off', label: 'Off', helpKey: 'ourstate.wake.offHelp',
    help: 'Nothing in this room wakes it, until it is set back' },
]
</script>

<style scoped>
.wms { display: inline-flex; border: 1px solid var(--border-color, rgba(128,128,128,.3)); border-radius: 999px; overflow: hidden; }
.wms-opt { min-height: 30px; padding: 0 9px; border: none; background: none; color: inherit; font-size: .7rem; cursor: pointer; opacity: .75; }
.wms-opt + .wms-opt { border-left: 1px solid var(--border-color, rgba(128,128,128,.3)); }
.wms-opt.on { opacity: 1; font-weight: 600; background: rgba(79, 216, 196, .14); color: var(--primary-color, #4fd8c4); }
.wms-opt:disabled { cursor: progress; }
</style>
