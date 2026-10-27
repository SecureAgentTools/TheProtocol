<script setup lang="ts">
// §FESUITE V0595 (his word 2026-10-11, "also correct the avt prose in the docs"): a docs page says which of its parts it
// left out and why: a switch this registry runs off (named by the setting an operator reads), or a configuration it could
// not read (then it says neither on nor off). Rendered only once the read settled and only where a part was left out.
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { switchEnvNames, type DocSwitch } from '@/composables/docs/switchBlocks'

const props = defineProps<{ leftOut: DocSwitch[]; unread: DocSwitch[]; loaded: boolean }>()
const { t, tp } = useI18n()
const names = computed(() => switchEnvNames(props.leftOut))
</script>

<template>
  <aside v-if="loaded && (leftOut.length || unread.length)" class="dsn" role="note" data-testid="docs-switch-note">
    <p v-for="name in names" :key="name" data-testid="docs-switch-left-out">
      {{ tp('docsSwitches.leftOut', 'Parts of this page that apply only where {name} is on are left out: this registry runs with it off.', { name }) }}
    </p>
    <p v-if="unread.length" data-testid="docs-switch-unread">
      {{ t('docsSwitches.unread', "Some parts of this page depend on this registry's settings and are not shown: its configuration could not be read.") }}
    </p>
  </aside>
</template>

<style scoped>
.dsn {
  margin: 0 0 1.25rem;
  padding: 0.7rem 1rem;
  border-left: 3px solid var(--nc-primary, #00d2d2);
  border-radius: 6px;
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.05);
  font-size: 0.9rem;
  line-height: 1.55;
}
.dsn p { margin: 0; }
.dsn p + p { margin-top: 0.4rem; }
</style>
