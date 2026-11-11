<template>
  <!-- V0658 (t): an organization's room in the chat list wears its organization's logo, as the thread's header does
       (V0657 (b) item 5): the logo the registry hosts (services/orgMark.ts safeLogo: a path on this registry, never
       another host's address). Today's room avatar when the organization hosts none or the image does not load. -->
  <span class="ora" data-testid="os-room-avatar" :data-logo="logo ? 'hosted' : 'none'">
    <img v-if="logo" :src="logo" alt="" class="ora-logo" loading="lazy" referrerpolicy="no-referrer"
         @error="broken = true" />
    <Icon v-else name="mdi:account-group" />
  </span>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { safeLogo } from '@/services/orgMark'

/** The room's organization as the chat list reads it (`org`: id, slug, name, logo, listed); only its logo is read. */
interface RoomOrg {
  logo?: string | null
}
const props = defineProps<{ org?: RoomOrg | null }>()

const broken = ref(false)
watch(() => props.org?.logo, () => { broken.value = false })
// A room's organization is this registry's own and its block names no home, so safeLogo is given none and takes only a
// path on this registry, as the thread's header does: an absolute address is never loaded, whatever origin a block names.
const logo = computed(() => {
  const org = props.org
  if (broken.value || !org) return null
  return safeLogo({ logo: org.logo ?? null, home: null })
})
</script>

<style scoped>
.ora { overflow: hidden; }
.ora-logo { display: block; width: 100%; height: 100%; border-radius: 50%; object-fit: cover; }
</style>
