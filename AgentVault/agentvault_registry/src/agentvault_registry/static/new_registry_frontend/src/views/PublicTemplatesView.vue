<!--
  §pass51 P34 — Public /templates landing route. No auth required.
  Visitors browse sovereign-pattern templates + click "Try this agent" → login → fork.
-->
<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import Icon from '@/components/Icon.vue'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()

const featured = ref<any[]>([])
const loading = ref(true)
const error = ref('')

const categories = computed(() => {
  const set = new Set<string>()
  featured.value.forEach(item => item.category && set.add(item.category))
  return Array.from(set).sort()
})
const activeCategory = ref<string | null>(null)
const filtered = computed(() => activeCategory.value
  ? featured.value.filter(item => item.category === activeCategory.value)
  : featured.value)

onMounted(async () => {
  try {
    // Use a separate axios instance so it doesn't drag auth headers (route is anonymous)
    const resp = await axios.get('/api/v1/bundles/marketplace/featured?limit=24')
    featured.value = resp.data?.featured || []
  } catch (e: any) {
    error.value = e?.message || t('publicTemplatesView.errors.couldNotLoad')
  } finally {
    loading.value = false
  }
})

function handleTry(tpl: any) {
  // If already logged in, send to /bundles deep-linked to this template id
  if (authStore.isLoggedIn) {
    router.push({ name: 'bundle-detail', params: { bundleId: tpl.id } })
  } else {
    // Stash the desired template, redirect to login, then to /bundles after auth
    try { sessionStorage.setItem('pendingTemplateFork', tpl.id) } catch (_) {}
    router.push({ name: 'login', query: { next: `/bundles/${tpl.id}` } })
  }
}
</script>

<template>
  <div class="pt-shell">
    <header class="pt-hero">
      <div class="pt-hero-eyebrow">{{ t('publicTemplatesView.hero.eyebrow') }}</div>
      <h1 class="pt-hero-title">{{ t('publicTemplatesView.hero.title') }}</h1>
      <p class="pt-hero-subtitle">
        {{ t('publicTemplatesView.hero.subtitle') }}
      </p>
      <div class="pt-hero-actions">
        <router-link :to="{ name: 'login' }" class="pt-hero-btn pt-hero-btn--primary">
          {{ t('publicTemplatesView.hero.signInToFork') }}
        </router-link>
        <a href="/" class="pt-hero-btn pt-hero-btn--ghost">{{ t('publicTemplatesView.hero.backToMainSite') }}</a>
      </div>
    </header>

    <div v-if="loading" class="pt-loading">{{ t('publicTemplatesView.states.loading') }}</div>
    <div v-else-if="error" class="pt-error">{{ error }}</div>
    <template v-else>
      <nav v-if="categories.length" class="pt-cats">
        <button class="pt-cat" :class="{ 'is-active': activeCategory === null }" @click="activeCategory = null">{{ t('publicTemplatesView.filter.all', { count: featured.length }) }}</button>
        <button v-for="c in categories" :key="c" class="pt-cat" :class="{ 'is-active': activeCategory === c }" @click="activeCategory = c">{{ c }}</button>
      </nav>

      <div class="pt-grid">
        <article v-for="tpl in filtered" :key="tpl.id" class="pt-card" :class="{ 'is-official': tpl.is_official }">
          <header class="pt-card-head">
            <div class="pt-card-tags">
              <span class="pt-card-kind">{{ t('publicTemplatesView.card.kindLabel') }}</span>
              <span v-if="tpl.is_official" class="pt-card-official">{{ t('publicTemplatesView.card.officialLabel') }}</span>
              <span v-if="tpl.signature_tier >= 1" class="pt-card-signed">{{ t('publicTemplatesView.card.signedLabel') }}</span>
            </div>
            <h2 class="pt-card-name">{{ tpl.name }}</h2>
          </header>
          <p class="pt-card-desc">{{ tpl.description }}</p>
          <footer class="pt-card-foot">
            <div class="pt-card-meta">
              <span v-if="tpl.category" class="pt-card-cat">{{ tpl.category }}</span>
              <span class="pt-card-inst">{{ t('publicTemplatesView.card.installCount', { count: tpl.install_count, s: tpl.install_count === 1 ? '' : 's' }) }}</span>
              <span v-if="tpl.rating_count > 0" class="pt-card-rating">★ {{ tpl.rating_avg?.toFixed(1) }}</span>
            </div>
            <button class="pt-card-try" @click="handleTry(tpl)">
              <Icon name="mdi:rocket-launch" /> {{ t('publicTemplatesView.card.tryButton') }}
            </button>
          </footer>
        </article>
      </div>

      <div v-if="filtered.length === 0" class="pt-empty">
        {{ t('publicTemplatesView.states.noMatch') }}
      </div>
    </template>

    <footer class="pt-foot">
      <p>
        {{ t('publicTemplatesView.footer.description') }}
        <router-link :to="{ name: 'login' }">{{ t('publicTemplatesView.footer.signIn') }}</router-link> {{ t('publicTemplatesView.footer.or') }}
        <router-link :to="{ name: 'register' }">{{ t('publicTemplatesView.footer.createAccount') }}</router-link> {{ t('publicTemplatesView.footer.toFork') }}
      </p>
    </footer>
  </div>
</template>

<style scoped>
.pt-shell {
  min-height: 100vh;
  background:
    radial-gradient(ellipse at top, rgba(0,210,210,0.06) 0%, transparent 60%),
    linear-gradient(180deg, #050b15 0%, #02060c 100%);
  color: #e8eaed;
  font-family: 'IBM Plex Mono', monospace;
  padding: 3rem 1.5rem 5rem;
}
.pt-hero { max-width: 880px; margin: 0 auto 2.5rem; text-align: center; }
.pt-hero-eyebrow { font-size: 0.66rem; letter-spacing: 0.24em; color: rgba(0,210,210,0.8); font-weight: 700; margin-bottom: 0.6rem; }
.pt-hero-title { font-size: 2.6rem; font-weight: 700; margin: 0; color: #fff; letter-spacing: -0.02em; }
.pt-hero-subtitle { font-size: 1rem; color: #99a5b3; margin: 1.1rem 0 1.6rem; line-height: 1.6; max-width: 640px; margin-left: auto; margin-right: auto; }
.pt-hero-actions { display: flex; gap: 0.7rem; justify-content: center; flex-wrap: wrap; }
.pt-hero-btn {
  display: inline-flex; align-items: center; gap: 0.4rem;
  font-family: inherit; font-size: 0.84rem; font-weight: 700; letter-spacing: 0.06em;
  padding: 11px 22px; border-radius: 6px; cursor: pointer; text-decoration: none;
  transition: background 0.18s, transform 0.08s;
}
.pt-hero-btn--primary { background: linear-gradient(180deg, #00e8e8 0%, #00d2d2 100%); color: #04141f; border: 1px solid #00d2d2; box-shadow: 0 6px 22px rgba(0,210,210,0.32), inset 0 1px 0 rgba(255,255,255,0.25); }
.pt-hero-btn--primary:hover { background: linear-gradient(180deg, #fff 0%, #00e8e8 100%); }
.pt-hero-btn--ghost { background: transparent; border: 1px solid rgba(0,210,210,0.3); color: rgba(0,210,210,0.85); }
.pt-hero-btn--ghost:hover { background: rgba(0,210,210,0.06); color: #00d2d2; border-color: rgba(0,210,210,0.65); }

.pt-loading, .pt-error, .pt-empty { text-align: center; padding: 3rem; color: #99a5b3; font-size: 0.92rem; max-width: 880px; margin: 0 auto; }
.pt-error { color: #ff8c8c; }

.pt-cats { max-width: 1080px; margin: 0 auto 1.5rem; display: flex; flex-wrap: wrap; gap: 0.4rem; justify-content: center; padding: 0.5rem 0; }
.pt-cat { background: transparent; border: 1px solid rgba(0,210,210,0.2); color: rgba(0,210,210,0.75); font-family: inherit; font-size: 0.72rem; font-weight: 600; padding: 6px 14px; border-radius: 999px; cursor: pointer; transition: background 0.15s, color 0.15s, border-color 0.15s; }
.pt-cat:hover { background: rgba(0,210,210,0.08); color: #00d2d2; }
.pt-cat.is-active { background: rgba(0,210,210,0.18); color: #00d2d2; border-color: rgba(0,210,210,0.65); }

.pt-grid { max-width: 1080px; margin: 0 auto; display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 1rem; }
.pt-card {
  background: linear-gradient(180deg, rgba(14,24,40,0.78) 0%, rgba(8,14,24,0.92) 100%);
  border: 1px solid rgba(0,210,210,0.2);
  border-radius: 12px;
  padding: 1.1rem 1.2rem 1rem;
  display: flex; flex-direction: column; gap: 0.7rem;
  transition: border-color 0.2s, transform 0.12s, box-shadow 0.2s;
}
.pt-card:hover { border-color: rgba(0,210,210,0.55); transform: translateY(-2px); box-shadow: 0 8px 28px rgba(0,210,210,0.12); }
.pt-card.is-official { border-color: rgba(255,215,0,0.35); }
.pt-card.is-official:hover { border-color: rgba(255,215,0,0.7); box-shadow: 0 8px 28px rgba(255,215,0,0.18); }

.pt-card-head { display: flex; flex-direction: column; gap: 0.5rem; }
.pt-card-tags { display: flex; gap: 0.4rem; flex-wrap: wrap; font-size: 0.58rem; letter-spacing: 0.18em; font-weight: 700; }
.pt-card-kind { background: rgba(0,210,210,0.15); color: rgba(0,210,210,0.95); padding: 2px 7px; border-radius: 3px; }
.pt-card-official { background: rgba(255,215,0,0.22); color: rgba(255,215,0,0.95); padding: 2px 7px; border-radius: 3px; }
.pt-card-signed { background: rgba(0,255,136,0.22); color: rgba(0,255,136,0.95); padding: 2px 7px; border-radius: 3px; }
.pt-card-name { font-size: 1.05rem; font-weight: 700; color: #fff; margin: 0; line-height: 1.25; }

.pt-card-desc { font-size: 0.82rem; color: #99a5b3; line-height: 1.55; margin: 0; flex: 1; }

.pt-card-foot { display: flex; flex-direction: column; gap: 0.5rem; }
.pt-card-meta { display: flex; gap: 0.6rem; font-size: 0.66rem; color: rgba(148,163,184,0.7); flex-wrap: wrap; }
.pt-card-cat { color: rgba(0,210,210,0.7); font-weight: 600; }
.pt-card-rating { color: #fbbf24; }
.pt-card-try {
  display: inline-flex; align-items: center; justify-content: center; gap: 0.4rem;
  background: linear-gradient(180deg, #00e8e8 0%, #00d2d2 100%);
  border: 1px solid #00d2d2;
  color: #04141f;
  font-family: inherit; font-size: 0.78rem; font-weight: 700; letter-spacing: 0.06em;
  padding: 9px 14px; border-radius: 6px; cursor: pointer;
  transition: background 0.18s, transform 0.08s;
}
.pt-card-try svg { width: 14px; height: 14px; }
.pt-card-try:hover { background: linear-gradient(180deg, #fff 0%, #00e8e8 100%); }
.pt-card-try:active { transform: translateY(1px); }

.pt-foot { max-width: 880px; margin: 4rem auto 0; text-align: center; color: #6b7785; font-size: 0.78rem; line-height: 1.6; padding: 2rem 0 1rem; border-top: 1px solid rgba(0,210,210,0.08); }
.pt-foot a { color: rgba(0,210,210,0.85); text-decoration: none; border-bottom: 1px dashed rgba(0,210,210,0.4); padding-bottom: 1px; }
.pt-foot a:hover { color: #00d2d2; border-bottom-color: #00d2d2; }
</style>
