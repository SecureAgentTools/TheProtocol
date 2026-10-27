<script setup lang="ts">
import { homeRoute } from '@/services/uiMode'
import { useRouter } from 'vue-router'
import NeuralCard from '@/components/ui/NeuralCard.vue'
import NeuralIcon from '@/components/ui/NeuralIcon.vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()

const goHome = () => {
  // Anonymous visitors go to the public landing page; sending them at a
  // requiresAuth route bounces every lost visitor into /login instead.
  router.push(authStore.isAuthenticated ? homeRoute() : { name: 'landing' })   // §PHONESTART — a phone goes home to Pocket
}
</script>

<template>
  <div class="nc-page min-h-screen flex items-center justify-center">
    <NeuralCard variant="elevated" class="text-center p-12 max-w-lg">
      <NeuralIcon name="alert-triangle" :size="64" class="nc-text-accent mb-6 mx-auto" />
      <h1 class="nc-h1 mb-4">
        404
      </h1>
      <h2 class="nc-h2 mb-4">
        {{ t('notFoundView.title') }}
      </h2>
      <p class="nc-text-secondary mb-8">
        {{ t('notFoundView.description') }}
      </p>
      <button
        @click="goHome"
        class="nc-btn nc-btn-primary"
      >
        <NeuralIcon name="home" :size="18" />
        <span>{{ t('notFoundView.cta') }}</span>
      </button>
    </NeuralCard>
  </div>
</template>

<style scoped>
/* Neural Command styles are applied through classes */
</style>
