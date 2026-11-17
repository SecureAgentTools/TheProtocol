<!--
  V0666 (order gwo_e086b25f868da7ec9fce9fd2): shown on a registry that is not the governing one, in place of the ways to submit. The sentence is the registry's own (the one its refusals carry);
  its link is the governing registry's console as that registry's card publishes it.
-->
<template>
  <aside class="cc-governed" role="note" data-testid="cc-governed-elsewhere">
    <Icon name="mdi:shield-check" />
    <p>
      <span data-testid="cc-governed-sentence">{{ view.sentence }}</span>
      <a v-if="view.link && safeExternalUrl(view.link)" :href="safeExternalUrl(view.link)" target="_blank" rel="noopener noreferrer" class="cc-governed-link" data-testid="cc-governed-link">{{ t('codeChanges.governed.open', 'Open it there') }}</a>
    </p>
  </aside>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { safeExternalUrl } from '@/utils/safeUrl'
import type { AuthorityView } from '@/services/codeChanges/authority'

defineProps<{ view: AuthorityView }>()
const { t } = useI18n()
</script>

<style scoped>
.cc-governed { display: flex; gap: 12px; align-items: flex-start; margin: 14px 0; padding: 14px 16px; border: 1px solid var(--nc-border, rgba(255, 255, 255, 0.14)); border-radius: 12px; }
.cc-governed p { margin: 0; line-height: 1.5; }
.cc-governed-link { margin-left: 10px; font-weight: 600; }
</style>
