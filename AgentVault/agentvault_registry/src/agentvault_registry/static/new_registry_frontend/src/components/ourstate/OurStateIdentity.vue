<template>
  <component :is="clickable ? 'button' : 'div'"
             class="osi" :class="[`osi-${size}`, { 'osi-clickable': clickable }]"
             :type="clickable ? 'button' : undefined"
             :aria-label="clickable ? name : undefined"
             :data-remote-address="ptype === 'remote' ? String(pid) : undefined"
             @click="clickable && emit('open')">
    <!-- THE IDENTITY MANDATE (Commander, 2026-08-24): wherever OurState shows
         a name, the WHOLE identity renders — avatar + flare encirclement
         (sovereign-always-wins cascade) + earned-mark collar — pixel-parity
         with Pocket Discover / My Agents. This wrapper is the ONE mount point:
         it hands the by-did profile to UserAvatar VERBATIM (participants.ts
         never re-derives the cascade, never reads a flattened `it.flare` —
         both §POCKETDISC scars) and forwards trackRecord for the collar. A
         flareless agent renders its plain avatar + STANDALONE collar; a human
         renders their public flare tier and no collar (earned marks are agent
         work history). -->
    <UserAvatar
      :user="idn?.user || null"
      :avatar-url="idn?.avatarUrl || null"
      :display-name="name"
      :track-record="idn?.trackRecord || null"
      :size="size"
      class="osi-avatar" />
    <span v-if="showName" class="osi-name">{{ name }}</span>
  </component>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import { resolveIdentity, peekIdentity, type ParticipantIdentity } from '@/services/chat/participants'

const props = withDefaults(defineProps<{
  /** `remote`: a principal on a PEER registry, `pid` its address (§TWOAGENT G1, V0436); nothing here can resolve it. */
  ptype: 'developer' | 'agent' | 'remote'
  pid: string | number
  /** Name from the conversation row — shown immediately, before resolution. */
  fallbackName?: string
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  showName?: boolean
  clickable?: boolean
}>(), { fallbackName: '', size: 'md', showName: false, clickable: false })

const emit = defineEmits<{ (e: 'open'): void }>()

const idn = ref<ParticipantIdentity | null>(null)
const name = computed(() => idn.value?.name || props.fallbackName || String(props.pid))

watch(() => [props.ptype, props.pid], async () => {
  // A principal on a peer registry has no profile HERE: its name is the one the row carries (its card name or its
  // address). Resolving it as a developer looked up an id that does not exist.
  if (props.ptype === 'remote') { idn.value = null; return }
  idn.value = peekIdentity(props.ptype, props.pid)
  idn.value = await resolveIdentity(props.ptype, props.pid, props.fallbackName)
}, { immediate: true })
</script>

<style scoped>
.osi { display: inline-flex; align-items: center; gap: 8px; background: none; border: none; padding: 0; color: inherit; text-align: left; }
.osi-clickable { cursor: pointer; min-width: 44px; min-height: 44px; }
.osi-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
