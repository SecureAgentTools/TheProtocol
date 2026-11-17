<!--
  V0666 (gwo_dc5050837e93b0a64d1fdae7, room seq 4404): the landing page's door to the systems a visitor already runs:
  Migrate a system (only where the registry has the template library on, workflow_templates_enabled, as the nav and the
  route), the Proxy, and Code changes. One sentence of what each is and one door; the page's own idiom (the atlas's centred
  mono eyebrow, a light heading, hairline cards).
-->
<template>
  <section class="lsu" data-testid="lp-surfaces">
    <div class="lsu-inner">
      <div class="lsu-header">
        <div class="lsu-eyebrow"><span class="lsu-mark">◆</span> {{ t('landingPage.surfaces.eyebrow', 'SYSTEMS YOU ALREADY RUN') }}</div>
        <h2 class="lsu-h2">{{ t('landingPage.surfaces.titleA', 'Bring what you run,') }} <span class="lsu-accent">{{ t('landingPage.surfaces.titleAccent', 'or move off it.') }}</span></h2>
        <p class="lsu-lead">{{ t('landingPage.surfaces.lead', 'An old system does not have to be rewritten to take part: connect it as it is, move its data off it with a check you can read, and propose changes to this console itself.') }}</p>
      </div>
      <ul class="lsu-tiles">
        <li v-if="workflowTemplatesEnabled" class="lsu-tile" data-testid="lp-surface-migrate">
          <span class="lsu-glyph" aria-hidden="true"><Icon name="mdi:database-export" /></span>
          <h3>{{ t('landingPage.surfaces.migrateTitle', 'Migrate a system') }}</h3>
          <p>{{ t('landingPage.surfaces.migrateBody', 'Move off an old system with a free dry run on your own machine and a load that runs once, from templates people share.') }}</p>
          <RouterLink :to="{ name: 'migrate' }" class="lsu-door">{{ t('landingPage.surfaces.migrateDoor', 'Open the library') }} <span aria-hidden="true">→</span></RouterLink>
        </li>
        <li class="lsu-tile" data-testid="lp-surface-proxy">
          <span class="lsu-glyph" aria-hidden="true"><Icon name="mdi:connection" /></span>
          <h3>{{ t('landingPage.surfaces.proxyTitle', 'The Proxy') }}</h3>
          <p>{{ t('landingPage.surfaces.proxyBody', 'Connect a system that stays: the proxy reads what it already writes and acts on TheProtocol as its own agent, from one spec file.') }}</p>
          <RouterLink :to="{ name: 'proxy' }" class="lsu-door">{{ t('landingPage.surfaces.proxyDoor', 'The connectors and the spec builder') }} <span aria-hidden="true">→</span></RouterLink>
        </li>
        <li class="lsu-tile" data-testid="lp-surface-code-changes">
          <span class="lsu-glyph" aria-hidden="true"><Icon name="mdi:code-braces" /></span>
          <h3>{{ t('landingPage.surfaces.codeTitle', 'Code changes') }}</h3>
          <p>{{ t('landingPage.surfaces.codeBody', 'Propose a change to the console and its docs, reviewed and voted on by the members before it merges.') }}</p>
          <RouterLink :to="{ name: 'code-changes' }" class="lsu-door">{{ t('landingPage.surfaces.codeDoor', 'See the changes') }} <span aria-hidden="true">→</span></RouterLink>
        </li>
      </ul>
    </div>
  </section>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'

const { t } = useI18n()
const { workflowTemplatesEnabled } = useRegistryConfig()
</script>

<style scoped>
.lsu { position: relative; padding: 4.5rem 1.5rem 4rem; border-top: 1px solid rgba(255, 255, 255, 0.04); }
.lsu-inner { max-width: 1200px; margin: 0 auto; position: relative; z-index: 2; }
.lsu-header { text-align: center; margin-bottom: 2.6rem; }
.lsu-eyebrow { font-family: 'IBM Plex Mono', monospace; font-size: 0.56rem; font-weight: 600; letter-spacing: 0.25em; color: rgba(var(--nc-primary-rgb), 0.5); margin-bottom: 1rem; }
.lsu-mark { color: rgba(var(--nc-primary-rgb), 0.85); margin-right: 0.35rem; }
.lsu-h2 { font-size: clamp(1.6rem, 3.5vw, 2.4rem); font-weight: 300; line-height: 1.2; color: rgba(255, 255, 255, 0.92); margin: 0 0 1rem; }
.lsu-accent { color: rgba(var(--nc-primary-rgb), 0.95); font-weight: 400; }
.lsu-lead { max-width: 680px; margin: 0 auto; font-size: 0.88rem; line-height: 1.7; color: rgba(255, 255, 255, 0.55); }
.lsu-tiles { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(17rem, 100%), 1fr)); gap: 1rem; }
.lsu-tile { position: relative; display: flex; flex-direction: column; gap: 0.6rem; padding: 1.4rem 1.3rem 1.2rem; border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 10px; background: rgba(255, 255, 255, 0.015); overflow: hidden; transition: border-color 0.25s ease, background 0.25s ease; }
.lsu-tile::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px; background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb), 0.7), transparent); opacity: 0; transition: opacity 0.25s ease; }
.lsu-tile:hover, .lsu-tile:focus-within { border-color: rgba(var(--nc-primary-rgb), 0.3); background: rgba(var(--nc-primary-rgb), 0.03); }
.lsu-tile:hover::before, .lsu-tile:focus-within::before { opacity: 1; }
.lsu-glyph { width: 2.2rem; height: 2.2rem; display: grid; place-items: center; border-radius: 8px; border: 1px solid rgba(var(--nc-primary-rgb), 0.25); color: rgba(var(--nc-primary-rgb), 0.85); }
.lsu-glyph :deep(svg) { width: 1.1rem; height: 1.1rem; }
.lsu-tile h3 { margin: 0; font-size: 1.1rem; font-weight: 500; letter-spacing: 0.02em; color: rgba(255, 255, 255, 0.94); }
.lsu-tile p { margin: 0; flex: 1; font-size: 0.82rem; line-height: 1.6; color: rgba(255, 255, 255, 0.55); }
.lsu-door { align-self: flex-start; display: inline-flex; align-items: center; gap: 0.4rem; min-height: 40px; font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem;
  letter-spacing: 0.04em; color: rgba(var(--nc-primary-rgb), 0.9); text-decoration: none; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.3); }
.lsu-door span { transition: transform 0.25s ease; }
.lsu-door:hover span, .lsu-door:focus-visible span { transform: translateX(3px); }
.lsu-door:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.6); outline-offset: 3px; }
@media (max-width: 640px) { .lsu { padding: 3.5rem 1rem 3rem; } .lsu-header { margin-bottom: 1.8rem; } }
</style>
