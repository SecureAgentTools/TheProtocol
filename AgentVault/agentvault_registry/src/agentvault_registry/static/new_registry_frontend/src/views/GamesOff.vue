<!--
  V0666 the games switch: where this registry says games_enabled false (GAMES_ENABLED=false), a typed URL to a game view
  (/games, /arena, /tower-defense, /snake-arena, /trading) lands here: one plain sentence, no blank page, no failing calls.
  Where the registry's settings could not be read (?unknown=1), the page says that instead, mounts no game view and offers
  Try again: a fresh read, then the game view asked for once the registry says the games are on.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import { loadRegistryConfig, peekRegistryConfig } from '@/composables/useRegistryConfig'
import { gamesState, gameReturnPath } from '@/services/games/gamesSwitch'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const unknown = computed(() => route.query.unknown === '1')
const trying = ref(false)

async function retry() {
  trying.value = true
  try {
    const cfg: Record<string, any> = await loadRegistryConfig(true)
    const games = gamesState(cfg, peekRegistryConfig().readOk.value)
    if (games === 'on') await router.replace(gameReturnPath(route.query.to))
    else if (games === 'off') await router.replace({ name: 'games-off' })
  } finally {
    trying.value = false
  }
}
</script>

<template>
  <section class="go-root" data-testid="games-off" :data-state="unknown ? 'unknown' : 'off'">
    <h1 class="go-title">{{ t('gamesOff.title', 'Games') }}</h1>
    <template v-if="unknown">
      <p class="go-body">{{ t('gamesOff.unknown', "This registry's settings could not be read, so the games stay closed until they are.") }}</p>
      <button type="button" class="go-retry" data-testid="games-off-retry" :disabled="trying" @click="retry">
        {{ t('gamesOff.retry', 'Try again') }}
      </button>
    </template>
    <p v-else class="go-body">{{ t('gamesOff.body', 'The games are off on this registry.') }}</p>
  </section>
</template>

<style scoped>
.go-root { max-width: 40rem; margin: 4rem auto; padding: 0 1.5rem; }
.go-title { font-size: 1.25rem; font-weight: 300; margin-bottom: 0.75rem; }
.go-body { opacity: 0.85; line-height: 1.6; }
.go-retry { margin-top: 1rem; padding: 0.4rem 1rem; border: 1px solid currentColor; border-radius: 4px; background: transparent; color: inherit; }
.go-retry:disabled { opacity: 0.5; }
</style>
