<script setup lang="ts">
// §LANDINGTRUTH (16), V0564: his word ~17:25Z (agentvault2-09) switches production to membership governance. A docs
// chapter that describes lock-weight voting then says, where the registry counts votes by membership, which rule this
// registry runs; the chapter rewrites stay for his docs pass. Rendered only where governance_weight_mode = member, so a
// registry that counts votes by locks shows the chapter exactly as before.
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { governanceMode } from '@/services/membership/membership'

const { t } = useI18n()
const { config } = useRegistryConfig()
const memberMode = computed(() => governanceMode(config.value) === 'member')
</script>

<template>
  <aside v-if="memberMode" class="mmn" role="note" data-testid="member-mode-notice">
    {{ t('docsMemberNotice.text', 'This registry counts votes by membership: one vote per member, weighted by time as a member. The lock-weight rules on this page apply to registries that count votes by locks.') }}
  </aside>
</template>

<style scoped>
.mmn {
  margin: 0 0 1.25rem;
  padding: 0.8rem 1rem;
  border-left: 3px solid var(--nc-primary, #00d2d2);
  border-radius: 6px;
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.07);
  font-size: 0.92rem;
  line-height: 1.55;
}
</style>
