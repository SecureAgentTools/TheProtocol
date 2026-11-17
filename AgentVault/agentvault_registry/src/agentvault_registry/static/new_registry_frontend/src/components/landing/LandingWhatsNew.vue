<!--
  V0666 (gwo_dc5050837e93b0a64d1fdae7, room seq 4424): the landing page's "What's new": the newest release's member
  lines, read from the docs' release notes (chapter 38) after the page is up, so the landing's first load does not carry
  the chapter. A strip in the page's idiom, a hairline per line; one door to all the notes. Nothing shows until the notes
  are read (they ship with the console, so a failed read is a failed chunk load, and the strip stays out of the way).
-->
<template>
  <section v-if="news.items.length" class="lwn" data-testid="lp-news" :aria-label="t('landingPage.news.aria', 'What is new in this release')">
    <div class="lwn-inner">
      <div class="lwn-head">
        <span class="lwn-eyebrow"><span class="lwn-mark">◆</span> {{ t('landingPage.news.eyebrow', "WHAT'S NEW") }}</span>
        <span class="lwn-version" data-testid="lp-news-version">{{ news.version }}</span>
      </div>
      <ul class="lwn-list">
        <li v-for="i in news.items" :key="i.title" class="lwn-item" data-testid="lp-news-item">
          <strong>{{ i.title }}</strong>
          <span>{{ i.line }}</span>
        </li>
      </ul>
      <RouterLink :to="{ path: '/docs/38' }" class="lwn-all" data-testid="lp-news-all">{{ t('landingPage.news.all', 'All the release notes') }} <span aria-hidden="true">→</span></RouterLink>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { parseWhatsNew, type WhatsNew } from '@/services/landing/whatsNew'

const { t } = useI18n()
const news = ref<WhatsNew>({ version: '', items: [] })
onMounted(async () => {
  try { news.value = parseWhatsNew((await import('@/assets/docs/oracle/38_release_notes.md?raw')).default, 4) }
  catch { /* the strip stays out of the way */ }
})
</script>

<style scoped>
.lwn { position: relative; padding: 2.6rem 1.5rem 3rem; border-top: 1px solid rgba(255, 255, 255, 0.04); }
.lwn-inner { max-width: 1200px; margin: 0 auto; position: relative; z-index: 2; display: grid; gap: 1.1rem; }
.lwn-head { display: flex; align-items: baseline; gap: 0.9rem; flex-wrap: wrap; }
.lwn-eyebrow { font-family: 'IBM Plex Mono', monospace; font-size: 0.56rem; font-weight: 600; letter-spacing: 0.25em; color: rgba(var(--nc-primary-rgb), 0.5); }
.lwn-mark { color: rgba(var(--nc-primary-rgb), 0.85); margin-right: 0.35rem; }
.lwn-version { font-family: 'IBM Plex Mono', monospace; font-size: 0.66rem; letter-spacing: 0.08em; padding: 1px 7px; border-radius: 3px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25); color: rgba(var(--nc-primary-rgb), 0.75); }
.lwn-list { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(15rem, 100%), 1fr)); gap: 0 1.4rem; }
.lwn-item { display: grid; gap: 0.25rem; padding: 0.8rem 0; border-top: 1px solid rgba(255, 255, 255, 0.07); align-content: start; }
.lwn-item strong { font-size: 0.86rem; font-weight: 500; color: rgba(255, 255, 255, 0.9); }
.lwn-item span { font-size: 0.78rem; line-height: 1.55; color: rgba(255, 255, 255, 0.5); }
.lwn-all { justify-self: start; display: inline-flex; align-items: center; gap: 0.4rem; min-height: 40px; font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem;
  color: rgba(var(--nc-primary-rgb), 0.9); text-decoration: none; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.3); }
.lwn-all span { transition: transform 0.25s ease; }
.lwn-all:hover span, .lwn-all:focus-visible span { transform: translateX(3px); }
.lwn-all:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.6); outline-offset: 3px; }
@media (max-width: 640px) { .lwn { padding: 2.2rem 1rem 2.4rem; } }
</style>
